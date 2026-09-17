"""
Integrated WebSocket bridge for Adobe Illustrator CEP panel.

This module acts as a facade, coordinating:
- Transport (via bridge.server.WebSocketServer)
- Request lifecycle (via bridge.request_registry.RequestRegistry)
"""

import asyncio
import json
import logging
import threading
import time
import uuid
from enum import Enum, auto
from typing import Any, Optional, Dict

from illustrator_mcp.config import config, BRIDGE_STARTUP_TIMEOUT
from illustrator_mcp.types import (
    CommandMetadata,
    ExecutionResponse,
)
from illustrator_mcp.errors import ErrorCode, format_code
from illustrator_mcp.connection_helpers import create_connection_error
from illustrator_mcp.bridge.server import WebSocketServer
from illustrator_mcp.bridge.request_registry import RequestRegistry
from illustrator_mcp.bridge.payload import CAPABILITY, PayloadError, PayloadReceiver

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """WebSocket connection state."""
    DISCONNECTED = auto()
    CONNECTING = auto()
    LISTENING = auto()      # Server listening, no client connected
    SHUTTING_DOWN = auto()  # Shutdown initiated, no new requests
    ERROR = auto()


# Explicit transition table — illegal transitions are rejected.
ALLOWED_TRANSITIONS: Dict[ConnectionState, set] = {
    ConnectionState.DISCONNECTED:  {ConnectionState.CONNECTING},
    ConnectionState.CONNECTING:    {ConnectionState.LISTENING, ConnectionState.ERROR, ConnectionState.SHUTTING_DOWN},
    ConnectionState.LISTENING:     {ConnectionState.SHUTTING_DOWN, ConnectionState.ERROR},
    ConnectionState.SHUTTING_DOWN: {ConnectionState.DISCONNECTED},
    ConnectionState.ERROR:         {ConnectionState.DISCONNECTED, ConnectionState.SHUTTING_DOWN},
}


class WebSocketBridge:
    """
    Coordinator facade for Illustrator WebSocket communication.
    Delegates transport to WebSocketServer and state to RequestRegistry.
    """

    def __init__(self, port: int = None):
        self.port = config.ws_port if port is None else port
        self.registry = RequestRegistry()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()
        self._stop_requested = threading.Event()
        self._server_task = None
        self._stop_signalled = False
        self._cleanup_error = None
        self._ready = threading.Event()  # Ready after server is actually listening
        self.state = ConnectionState.DISCONNECTED
        self._state_lock = threading.Lock()
        
        # Initialize server (will be run in loop)
        self.server = WebSocketServer(
            port=self.port,
            on_message=self._handle_message,
            on_disconnect=self._handle_disconnect
        )

        # E1: Panel health watchdog
        self._watchdog_task: Optional[asyncio.Task] = None

        # Heartbeat tracking
        self._last_heartbeat: float = 0.0
        self._panel_busy: bool = False
        self._panel_idle = asyncio.Event()
        self._panel_active_request: Optional[int] = None
        self._payload_capable = False
        self._payload_session = uuid.uuid4().hex
        self._host_payload_session: Optional[str] = None


    def _transition(self, new_state: ConnectionState, reason: str = "") -> bool:
        """Thread-safe state transition with validation and side-effect dispatch.

        Bridge emits lifecycle events only; the registry decides what to
        do with requests (cancel_all is called by the disconnect handler,
        not by _transition itself, to preserve the registry as the
        single source of truth for request state).

        Returns:
            True if transition was applied, False if rejected.
        """
        with self._state_lock:
            old = self.state
            if old == new_state:
                return True  # no-op
            allowed = ALLOWED_TRANSITIONS.get(old, set())
            if new_state not in allowed:
                logger.error(
                    f"Illegal transition {old.name} → {new_state.name} ({reason})"
                )
                return False
            self.state = new_state
            logger.info(f"Bridge: {old.name} → {new_state.name} ({reason})")

        # Side effects (outside state lock — registry has its own lock)
        if new_state in (
            ConnectionState.ERROR,
            ConnectionState.SHUTTING_DOWN,
        ):
            self.registry.cancel_all(reason)
            self._ready.set()  # unblock startup waiters on failure

        return True

    async def _handle_disconnect(self) -> None:
        """Called when the CEP panel disconnects.

        Keep pending futures and correlate replayed completions after reconnect.
        Transport loss is not evidence that the host stopped. The server stays
        LISTENING and the coordinator quarantines unresolved work.
        """
        logger.warning("CEP panel disconnected — retaining unresolved requests for completion replay")

        # T12: rotate the connection generation. Callbacks from the old
        # connection must not resolve or unlock jobs belonging to the new one,
        # and any job that was RUNNING becomes UNKNOWN rather than being
        # treated as never having happened — Illustrator may well have
        # finished it.
        try:
            from illustrator_mcp.execution import get_coordinator
            get_coordinator().bump_connection_generation()
        except Exception as exc:  # pragma: no cover - never block disconnect
            logger.debug("Could not rotate connection generation: %s", exc)

        # Age the last observation, but never turn loss of contact into idle.
        self._last_heartbeat = 0.0
        self._payload_capable = False
        # State stays LISTENING (server running, no client) — no transition needed
        # since we're already LISTENING

    async def _handle_message(self, message: str) -> None:
        """Callback for incoming WebSocket messages."""
        # I6: Use configurable limit from config (default: 10 MB)
        max_msg_bytes = config.max_message_size_mb * 1024 * 1024
        if len(message.encode("utf-8")) > max_msg_bytes:
            logger.warning(f"Rejecting oversized message: {len(message)} bytes (limit: {config.max_message_size_mb} MB)")
            return
            
        try:
            data = json.loads(message)
            msg_type = data.get("type", "complete")

            # Heartbeat messages (no request_id needed)
            if msg_type == "heartbeat":
                self._handle_heartbeat(data)
                return

            request_id = data.get("id")

            if request_id:
                pending = self.registry.get_pending(request_id)
                if pending and pending.payload and pending.request_token == data.get("requestToken"):
                    receiver = pending.payload
                    try:
                        if msg_type == "payload_descriptor":
                            receiver.describe(data.get("descriptor"))
                            return
                        if msg_type == "payload_chunk":
                            receiver.add_page(data)
                            return
                        if msg_type == "complete":
                            transfer_error = data.get("payloadError")
                            if transfer_error:
                                code = ("C015" if transfer_error == "payload_expired_or_released" else
                                        "C013" if transfer_error in {"stale_host_session", "payload_owner_mismatch"} else "C014")
                                raise PayloadError(code, str(transfer_error))
                            payload, integrity = receiver.finish()
                            data["result"] = payload
                            data["integrity"] = integrity
                            self._host_payload_session = receiver.descriptor["hostSession"]
                    except PayloadError as exc:
                        receiver.failure = exc
                        if msg_type != "complete":
                            return
                        data.update(exc.response(receiver.expected))
                        data.pop("result", None)
                    if msg_type == "complete":
                        receiver.pages.clear()
                elif pending and msg_type == "complete":
                    data["integrity"] = {"status": "unknown", "reason": "legacy_peer"}
                if msg_type == "progress" and pending and pending.progress_queue is not None:
                    if pending.request_token == data.get("requestToken"):
                        try:
                            pending.progress_queue.put_nowait(data)
                        except asyncio.QueueFull:
                            pass  # Progress is advisory; never lose final completion.
                    return
                # Check if this is a streaming request
                if self.registry.is_streaming(request_id):
                    if msg_type == "progress":
                        # Push progress update to streaming queue
                        self.registry.push_update(request_id, data)
                        logger.debug(f"Progress update for streaming request {request_id}")
                    else:
                        # Final result - complete the streaming
                        self.registry.complete_streaming(request_id, data)
                        logger.debug(f"Streaming request {request_id} completed")
                else:
                    # Regular (non-streaming) request
                    accepted = (
                        self.registry.was_completed(request_id, data.get("requestToken"))
                        or self.registry.complete_request(request_id, data)
                    )
                    if accepted:
                        logger.debug(f"Request {request_id} completed")
                        from illustrator_mcp.execution import get_coordinator
                        fence = get_coordinator().probe_fence
                        if (fence and msg_type == "complete" and
                                fence["requestId"] == request_id and
                                fence["requestToken"] == data.get("requestToken")):
                            fence["priorCompletionObserved"] = True
                        if self._panel_active_request == request_id:
                            self._panel_busy = False
                            self._panel_active_request = None
                    else:
                        logger.debug(f"Received response for unknown/done request: {request_id}")
                        # A panel can reconnect to a fresh Python process with a
                        # completion retained from the process that dispatched
                        # it.  The result cannot be applied without that old
                        # registry entry, but receipt does prove the panel's
                        # host call has finished.  Discard it explicitly so the
                        # panel does not remain permanently admission-blocked.
                        if (msg_type == "complete" and data.get("requestToken")
                                and pending is None and self.registry.pending_count == 0
                                and self._panel_active_request in (None, request_id)):
                            self._panel_busy = False
                            self._panel_active_request = None
                    # ACK is receipt/discard confirmation, not acceptance as a
                    # result for a current request. Correlation by token lets a
                    # stale completion be released without settling a colliding
                    # current request ID.
                    if msg_type == "complete" and data.get("requestToken"):
                        await self.server.send(json.dumps({"type": "completion_ack",
                                                           "requestToken": data["requestToken"]}))
            else:
                logger.warning("Received message without ID")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from CEP panel: {e}")

    def _thread_main(self):
        """Main function for the server thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            # Run server on this loop
            self._server_task = self.loop.create_task(self.server.run(self._started))
            if self._stop_requested.is_set():
                self.loop.call_soon(self._signal_stop)
            self.loop.run_until_complete(self._server_task)
        except asyncio.CancelledError:
            pass  # Requested startup cancellation; run() owns socket cleanup.
        except Exception as e:
            logger.error(f"Server thread error: {e}")
            startup_failure = e is self.server._start_error
            if self.server._start_error is None:
                self.server._start_error = e
            if self.state != ConnectionState.SHUTTING_DOWN:
                self._transition(ConnectionState.ERROR, f"Server thread error: {e}")
            if not startup_failure:
                self._cleanup_error = e
        finally:
            # _transition to SHUTTING_DOWN handles cancel_all + unblocking _ready
            self._transition(ConnectionState.SHUTTING_DOWN, "Bridge shutting down")
            try:
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()
                if pending:
                    results = self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    for result in results:
                        if isinstance(result, Exception):
                            self._cleanup_error = result
                            logger.error("Bridge background task cleanup failed: %r", result)
                self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            except Exception as exc:
                self._cleanup_error = exc
                logger.exception("Bridge task cleanup failed")
            finally:
                self.loop.close()
                self._started.set()

    def _signal_stop(self):
        """Run exactly once on the bridge loop, including during delayed bind."""
        if self._stop_signalled:
            return
        self._stop_signalled = True
        self.server.stop()
        if not self._started.is_set() and self._server_task:
            self._server_task.cancel()

    def start(self):
        """Start the WebSocket server in a background thread."""
        if self._thread and self._thread.is_alive():
            if self.is_running():
                return
            raise RuntimeError("Bridge is still stopping; restart through the owning MCP client")
        if self._thread is not None:
            raise RuntimeError("Bridge instances cannot be restarted; restart the MCP integration")

        self._transition(ConnectionState.CONNECTING, "Starting bridge")
        logger.info("Starting WebSocket bridge thread...")
        self._started.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._thread_main, daemon=True, name="WebSocketBridge")
        self._thread.start()

        # Wait for server to start
        if not self._started.wait(timeout=BRIDGE_STARTUP_TIMEOUT):
            if self.server._start_error is None:
                self.server._start_error = TimeoutError(
                    f"WebSocket bridge startup timed out after {BRIDGE_STARTUP_TIMEOUT} seconds")
        elif self.server and self.server._start_error:
            err = self.server._start_error
            logger.error(f"WebSocket bridge failed to start: {err}")
        else:
            if (self._thread.is_alive() and self.state == ConnectionState.CONNECTING
                    and self._transition(ConnectionState.LISTENING, "Server started")):
                logger.info("WebSocket bridge thread started successfully")
                self._ready.set()
                return
            self.server._start_error = RuntimeError("WebSocket bridge exited during startup")

        error = self.server._start_error
        try:
            self.stop()
        except Exception:
            logger.exception("Startup cleanup failed; bridge retained")
        raise error

    def wait_until_ready(self, timeout: float = 10.0) -> bool:
        """Wait until the bridge is ready to accept connections.
        
        Args:
            timeout: Maximum time to wait in seconds.
            
        Returns:
            True if ready, False if timeout expired.
        """
        return self._ready.wait(timeout=timeout) and self.is_running()

    def stop(self):
        """Stop the WebSocket server."""
        if self._thread is None:
            return
        self._stop_requested.set()
        if self._thread and self._thread.is_alive():
            self._transition(ConnectionState.SHUTTING_DOWN, "Stop requested")
            if self.loop:
                try:
                    self.loop.call_soon_threadsafe(self._signal_stop)
                except RuntimeError:
                    if not self.loop.is_closed():
                        raise
            self._thread.join(timeout=10.0)
            if self._thread.is_alive():
                raise TimeoutError("Bridge shutdown exceeded 10 seconds; instance retained")
        if self._cleanup_error:
            raise RuntimeError("Bridge cleanup failed; instance retained") from self._cleanup_error
        
        # SHUTTING_DOWN → DISCONNECTED (SHUTTING_DOWN set by _thread_main.finally)
        self._transition(ConnectionState.DISCONNECTED, "Bridge stopped")

    def is_running(self) -> bool:
        """Check if the bridge thread is alive and running."""
        return (self.state == ConnectionState.LISTENING
                and self._thread is not None and self._thread.is_alive())

    def is_connected(self) -> bool:
        """Check if Illustrator CEP panel is connected."""
        return self.server.is_connected()

    def get_connection_info(self) -> dict:
        """Get information about the current connection state.
        
        Returns:
            Dictionary with connection status, port, state, and client info.
        """
        # I14: Capture once to avoid TOCTOU between gate and return value
        connected = self.is_connected()
        client = self.server.client if connected else None
        client_info = None
        if client:
            client_info = {
                "remote_address": str(getattr(client, 'remote_address', 'unknown')),
            }
        
        return {
            "host": config.ws_host,
            "startup_error": str(self.server._start_error) if self.server and self.server._start_error else None,
            "is_connected": connected,
            "port": self.port,
            "state": self.state.value if hasattr(self.state, 'value') else str(self.state),
            "is_running": self.is_running(),
            "client_info": client_info
        }

    # ==================== Heartbeat ====================

    def _handle_heartbeat(self, data: dict) -> None:
        """Update panel health tracking from a heartbeat message."""
        self._last_heartbeat = time.time()
        self._payload_capable = CAPABILITY in (data.get("capabilities") or [])
        self._panel_busy = data.get("busy", False)
        self._panel_active_request = data.get("activeRequestId")
        if not self._panel_busy:
            self._panel_idle.set()
        logger.debug(
            f"Heartbeat: busy={self._panel_busy}, "
            f"active={self._panel_active_request}, "
            f"uptime={data.get('uptimeMs', 0)}ms"
        )
        # E1: Start watchdog on first heartbeat if not already running
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = self.loop.create_task(self._watchdog_loop())
            logger.debug("Panel watchdog started")

    def get_panel_health(self) -> dict:
        """Get panel health status based on heartbeats.

        Returns:
            Dictionary with:
            - last_heartbeat_ago_ms: ms since last heartbeat (None if never)
            - busy: whether panel reported busy
            - active_request_id: ID of script being executed (if busy)
            - stale: True if no heartbeat within watchdog_stale_threshold
        """
        if self._last_heartbeat == 0.0:
            return {
                "last_heartbeat_ago_ms": None,
                "busy": False,
                "active_request_id": None,
                "stale": True,
            }
        ago_ms = (time.time() - self._last_heartbeat) * 1000
        threshold_ms = config.watchdog_stale_threshold * 1000
        return {
            "last_heartbeat_ago_ms": round(ago_ms),
            "busy": self._panel_busy,
            "active_request_id": self._panel_active_request,
            "stale": ago_ms > threshold_ms,
        }

    async def _watchdog_loop(self) -> None:
        """E1: Periodically check panel health and disconnect if stale.

        Fires _handle_disconnect if the panel has sent no heartbeat for
        longer than watchdog_stale_threshold AND there is no active request
        (to avoid killing long-running scripts).
        """
        interval = config.watchdog_interval
        while True:
            await asyncio.sleep(interval)
            if await self._watchdog_tick():
                break  # stop watchdog; will restart on next heartbeat

    async def _watchdog_tick(self) -> bool:
        """Single watchdog check iteration.

        Returns True if disconnect was triggered (caller should stop loop).
        Extracted for deterministic unit testing.
        """
        health = self.get_panel_health()
        if (
            health["stale"]
            and not health["busy"]
            and self.is_connected()
        ):
            ago_s = health["last_heartbeat_ago_ms"]
            if ago_s is not None:
                ago_s = round(ago_s / 1000, 1)
            logger.warning(
                f"PANEL_WATCHDOG_STALE: no heartbeat for {ago_s}s "
                f"(threshold={config.watchdog_stale_threshold}s) — "
                f"forcing disconnect"
            )
            # F4: Grab local ref before _handle_disconnect (which resets state)
            ws = self.server.client
            try:
                await self._handle_disconnect()
            except asyncio.CancelledError:
                pass
            # F4: Force-close the stale WebSocket so server.client is cleared
            if ws is not None:
                try:
                    await ws.close(1001, "stale heartbeat")
                except Exception:
                    pass
            return True
        return False

    async def execute_script_async(
        self, 
        script: str, 
        timeout: float = 30.0,
        command: Optional[CommandMetadata] = None,
        trace_id: Optional[str] = None,
        _progress_queue: Optional[asyncio.Queue] = None,
    ) -> ExecutionResponse:
        """Execute a script in Illustrator (async version).
        
        Args:
            script: JavaScript code to execute
            timeout: Execution timeout in seconds
            command: Optional CommandMetadata for context
            trace_id: Optional trace ID for request correlation
            
        Returns:
            ExecutionResponse with result or error
        """
        if not self.is_connected():
            return create_connection_error(self.port)

        from illustrator_mcp.execution import get_coordinator
        from illustrator_mcp.execution.coordinator import HostUnresolvedError
        coordinator = get_coordinator()
        from illustrator_mcp.execution.trusted_probe import active as probe_authority
        trusted = probe_authority.get()
        if (trusted and coordinator.probe_fence and
                not coordinator.probe_fence.get("priorCompletionObserved")):
            return {"error": "PROBE_FENCE_UNSUPPORTED: predecessor completion is unproven; no further evaluation dispatched. Lost-callback reload recovery requires measured host support.",
                    "execution": "failed", "dispatched": False,
                    "blocking": dict(coordinator.probe_fence)}
        if coordinator.probe_fence and not trusted:
            return {"error": "PROBE_FENCE_REQUIRED: ordinary host call was not dispatched; inspect the blocking probe with illustrator_job_status.",
                    "execution": "failed", "dispatched": False,
                    "blocking": dict(coordinator.probe_fence)}
        try:
            coordinator.assert_host_available()
        except HostUnresolvedError as exc:
            return {"error": str(exc), "execution": "unknown", "jobId": exc.job_id}
        # busy with no active request can mean a completed response awaiting
        # its ACK. Wait for the panel's idle heartbeat, never guess that an ACK
        # was processed or retry a host phase. This also safely waits for an
        # untracked panel-side evaluation rather than dispatching over it.
        admission_started = time.monotonic()
        if self._panel_busy and self._panel_active_request is None and not self.registry.pending_count:
            self._panel_idle.clear()
            try:
                await asyncio.wait_for(self._panel_idle.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return {"error": "Panel did not confirm idle before the admission deadline; no host phase dispatched.",
                        "execution": "unknown", "jobId": coordinator.active_job_id, "dispatched": False}
            coordinator.assert_host_available()
            if not self.is_connected():
                return create_connection_error(self.port)
        timeout = max(0.001, timeout - (time.monotonic() - admission_started))
        # Also guard direct bridge callers that do not reserve a logical job.
        if self.registry.pending_count or self._panel_busy:
            return {"error": "Illustrator has an unresolved host request; do not dispatch or retry.",
                    "execution": "unknown", "jobId": coordinator.active_job_id}
        job_id = coordinator.active_job_id
        generation = coordinator.connection_generation
        request_token = uuid.uuid4().hex
        standalone = job_id is None or bool(trusted and coordinator.get(job_id).label != "connection_probe")
        if standalone:
            job_id = coordinator.register_host_request(request_token).job_id
        if trusted:
            coordinator.get(job_id).trusted_probe = True
        export_owner = getattr(coordinator.get(job_id), "export_files", None)
        if export_owner is not None and command and command.command_type == "export_document":
            export_owner.request_token = request_token
        else:
            export_owner = None

        # Build command info for message
        command_info = command.to_dict() if command else None
        if command:
            logger.info(f"[{trace_id or 'no-trace'}] Executing {command.command_type}")

        # Register request with trace_id for correlation
        request_id, future = self.registry.create_request(
            self.loop, 
            script, 
            command_info,
            trace_id,
            request_token=request_token,
        )
        self.registry.get_pending(request_id).progress_queue = _progress_queue
        from illustrator_mcp.execution.journal import active_journal
        journal = active_journal.get()
        if journal is not None and coordinator.get(job_id) is not None:
            coordinator.get(job_id).journal = journal

        completion_retained = False
        def retain_completion(done):
            nonlocal completion_retained
            if completion_retained:
                return
            if done.cancelled():
                return
            try:
                result = done.result()
            except Exception:
                return
            completion_retained = True
            if job_id:
                if not coordinator.matches_host_request(job_id, generation, request_token):
                    return
                if journal is not None:
                    result.setdefault("trace_id", trace_id)
                    result.setdefault("jobId", job_id)
                    journal.record_host(result, command=command.command_type if command else "execute_script")
                    coordinator.record_journal_report(journal)
                if isinstance(result, dict) and result.get("execution") == "unknown":
                    coordinator.mark_unknown(job_id, str(result.get("error") or "Payload integrity is unverified"))
                    return
                if not coordinator.host_request_finished(job_id, generation, result,
                                                          request_token=request_token):
                    return
                if export_owner is not None and export_owner.request_token == request_token:
                    from illustrator_mcp.tools._export import _response_ok
                    from illustrator_mcp.execution.export_files import fingerprint
                    export_owner.host_finished = True
                    export_owner.host_ok = _response_ok(result)
                    try:
                        export_owner.completed_output = fingerprint(export_owner.output)
                        export_owner.completion_captured = True
                    except OSError as exc:
                        export_owner.detail = "Completion fingerprint unavailable: " + str(exc)
                        export_owner.host_ok = False
                record = coordinator.get(job_id)
                if standalone and record:
                    from illustrator_mcp.execution import JobStatus
                    from illustrator_mcp.response_classification import classify_response
                    classification = classify_response(result)
                    coordinator.complete(job_id,
                        JobStatus.SUCCEEDED if classification.ok else JobStatus.FAILED,
                        result=result)
        future.add_done_callback(retain_completion)

        # Build message with trace_id for correlation
        message_data: Dict[str, Any] = {"id": request_id, "script": script,
                                       "requestToken": request_token,
                                       "jobId": job_id, "connectionGeneration": generation}
        if self._payload_capable and not trusted:
            from illustrator_mcp.libraries import inject_libraries
            expected = {"jobId": job_id, "requestId": request_id, "requestToken": request_token,
                        "sessionId": self._payload_session, "hostSession": self._host_payload_session,
                        "payloadId": uuid.uuid4().hex,
                        "documentId": (command.params.get("transportDocumentId") if command else None)}
            receiver = PayloadReceiver(expected)
            self.registry.get_pending(request_id).payload = receiver
            # Drop payload bytes even if the panel never reconnects. This does
            # not settle the host request or authorize another mutation.
            from illustrator_mcp.bridge.payload import TTL_SECONDS
            asyncio.get_running_loop().call_later(TTL_SECONDS, receiver.expire)
            message_data["transport"] = {
                "version": 1, "sessionId": expected["sessionId"], "hostSession": expected["hostSession"],
                "payloadId": expected["payloadId"], "expectedDocumentId": expected["documentId"],
                "bindingPrelude": inject_libraries("", ["doc_session"]),
            }
        if _progress_queue is not None:
            message_data["streaming"] = True
        if command_info:
            message_data["command"] = command_info
        if trace_id:
            message_data["trace_id"] = trace_id
        
        message = json.dumps(message_data)

        try:
            # Use server transport
            coordinator.host_request_started(job_id, generation, request_token)
            await self.server.send(message)
            logger.debug(f"Sent request {request_id} (trace: {trace_id}) to Illustrator")

            # Wait for future
            response = await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
            # An already-complete future can return before its scheduled done
            # callback. Establish quarantine before exposing an integrity error.
            retain_completion(future)
            if trusted and not response.get("error") and coordinator.probe_fence:
                fence = coordinator.probe_fence
                from illustrator_mcp.utils.response import require_jsx_payload, JsxPayloadError
                try:
                    require_jsx_payload(response, required_keys=("app", "documentCount"))
                    probe_valid = True
                except JsxPayloadError:
                    probe_valid = False
                if (fence.get("priorCompletionObserved") and
                        probe_valid and generation == coordinator.connection_generation):
                    coordinator.probe_readiness = dict(fence)
                    coordinator.probe_fence = None
            return response

        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            if job_id:
                coordinator.mark_unknown(job_id, "Client wait ended; Illustrator may still be executing. Reconcile before retrying.")
            # Shield leaves the real completion registered. This callback is
            # tied to its original job/generation, never the current job.
            if future.done():
                retain_completion(future)
            if trusted and not completion_retained:
                coordinator.retire_probe(job_id, request_id, request_token, generation)
                future.remove_done_callback(retain_completion)
                self.registry.retire_probe(request_id, request_token)
            if isinstance(exc, asyncio.CancelledError):
                raise
            cmd_ctx = f" [{command.command_type}]" if command else ""
            return {"error": format_code(ErrorCode.R_TIMEOUT,
                f"Client wait timed out after {timeout}s{cmd_ctx}; host outcome unknown"),
                "execution": "unknown", "jobId": job_id,
                "requestToken": request_token}

        except Exception as e:
            # A send exception can occur after bytes reached the panel.
            # Retain the request and fail closed rather than replaying it.
            if job_id:
                coordinator.mark_unknown(job_id, f"Host dispatch/response lost: {e}; reconcile before retrying.")
                if trusted:
                    coordinator.retire_probe(job_id, request_id, request_token, generation)
                    future.remove_done_callback(retain_completion)
                    self.registry.retire_probe(request_id, request_token)
            cmd_ctx = f" [{command.command_type}]" if command else ""
            return {"error": format_code(ErrorCode.R_UNKNOWN,
                f"Script execution outcome unknown{cmd_ctx}: {str(e)}"),
                "execution": "unknown", "jobId": job_id}

    async def execute_script_streaming(
        self, 
        script: str, 
        timeout: float = 300.0,
        command: Optional[CommandMetadata] = None,
        trace_id: Optional[str] = None
    ):
        """
        Execute a script with streaming progress updates.
        
        Use this for long-running operations that emit progress events.
        The script must send progress messages via the CEP panel.
        
        Args:
            script: JavaScript code to execute
            timeout: Client wait deadline for the host request. The evaluation
                remains registered if this deadline expires.
            command: Optional CommandMetadata for context
            trace_id: Optional trace ID for request correlation
            
        Yields:
            Progress updates and final result as dictionaries.
            Each update has a "type" field: "progress" or "complete".
        """
        # Streaming shares the same shielded dispatch and completion lifetime.
        # Cancelling its consumer never cancels the host evaluation.
        queue = asyncio.Queue(maxsize=1000)
        task = asyncio.create_task(self.execute_script_async(
            script, timeout, command, trace_id, _progress_queue=queue))
        update_task = None
        try:
            while not task.done():
                update_task = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait((task, update_task),
                                            return_when=asyncio.FIRST_COMPLETED)
                if update_task in done:
                    yield update_task.result()
                else:
                    update_task.cancel()
                await asyncio.gather(update_task, return_exceptions=True)
                update_task = None
            while not queue.empty():
                yield queue.get_nowait()
            response = await task
            yield dict(response, type="complete")
        finally:
            if update_task is not None:
                update_task.cancel()
                await asyncio.gather(update_task, return_exceptions=True)
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


# NOTE: Use get_runtime().get_bridge() directly.
# Standalone get_bridge() was removed to eliminate duplicate accessor paths.


def get_server():
    """Get the WebSocket server from the bridge."""
    from illustrator_mcp.runtime import get_runtime
    bridge = get_runtime().get_bridge()
    return bridge.server
