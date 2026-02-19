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
    ConnectionState.CONNECTING:    {ConnectionState.LISTENING, ConnectionState.ERROR},
    ConnectionState.LISTENING:     {ConnectionState.SHUTTING_DOWN, ConnectionState.ERROR},
    ConnectionState.SHUTTING_DOWN: {ConnectionState.DISCONNECTED},
    ConnectionState.ERROR:         {ConnectionState.DISCONNECTED, ConnectionState.CONNECTING},
}


class WebSocketBridge:
    """
    Coordinator facade for Illustrator WebSocket communication.
    Delegates transport to WebSocketServer and state to RequestRegistry.
    """

    def __init__(self, port: int = None):
        self.port = port or config.ws_port
        self.registry = RequestRegistry()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()
        self._ready = threading.Event()  # Ready after server is actually listening
        self.state = ConnectionState.DISCONNECTED
        self._state_lock = threading.Lock()
        
        # Initialize server (will be run in loop)
        self.server = WebSocketServer(
            port=self.port,
            on_message=self._handle_message,
            on_disconnect=self._handle_disconnect
        )

        # Library preload state (C1)
        self._preload_version: Optional[str] = None

        # E1: Panel health watchdog
        self._watchdog_task: Optional[asyncio.Task] = None

        # Heartbeat tracking
        self._last_heartbeat: float = 0.0
        self._panel_busy: bool = False
        self._panel_active_request: Optional[int] = None

    # --- Library preload accessors ---

    @property
    def preload_version(self) -> Optional[str]:
        """Current preload version hash, or None if not preloaded."""
        return self._preload_version

    def set_preload_version(self, version: str) -> None:
        """Set the preload version after successful preload."""
        self._preload_version = version

    def clear_preload(self) -> None:
        """Invalidate preload state (e.g., CEP reloaded)."""
        self._preload_version = None


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

        Cancels all pending requests immediately to prevent hanging futures.
        State stays at LISTENING (server still running, no client).
        cancel_all is called here — not in _transition — because
        LISTENING is also the initial post-start state where we don't cancel.
        """
        logger.warning("CEP panel disconnected — cancelling pending requests")
        self.registry.cancel_all("CEP panel disconnected")
        # Reset heartbeat state on disconnect
        self._last_heartbeat = 0.0
        self._panel_busy = False
        self._panel_active_request = None
        # Invalidate preload cache — panel JS globals are lost on reconnect
        self.clear_preload()
        # State stays LISTENING (server running, no client) — no transition needed
        # since we're already LISTENING

    async def _handle_message(self, message: str) -> None:
        """Callback for incoming WebSocket messages."""
        # I6: Use configurable limit from config (default: 10 MB)
        max_msg_bytes = config.max_message_size_mb * 1024 * 1024
        if len(message) > max_msg_bytes:
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
                    if self.registry.complete_request(request_id, data):
                        logger.debug(f"Request {request_id} completed")
                    else:
                        logger.debug(f"Received response for unknown/done request: {request_id}")
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
            self.loop.run_until_complete(self.server.run(self._started))
        except Exception as e:
            logger.error(f"Server thread error: {e}")
            self._transition(ConnectionState.ERROR, f"Server thread error: {e}")
        finally:
            # _transition to SHUTTING_DOWN handles cancel_all + unblocking _ready
            self._transition(ConnectionState.SHUTTING_DOWN, "Bridge shutting down")
            self.loop.close()

    def start(self):
        """Start the WebSocket server in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("WebSocket bridge already running")
            return

        self._transition(ConnectionState.CONNECTING, "Starting bridge")
        logger.info("Starting WebSocket bridge thread...")
        self._started.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._thread_main, daemon=True, name="WebSocketBridge")
        self._thread.start()

        # Wait for server to start
        if not self._started.wait(timeout=BRIDGE_STARTUP_TIMEOUT):
            logger.error(f"WebSocket bridge FAILED to start within {BRIDGE_STARTUP_TIMEOUT} seconds!")
            self._transition(ConnectionState.ERROR, "Startup timeout")
        elif self.server and self.server._start_error:
            err = self.server._start_error
            logger.error(f"WebSocket bridge failed to start: {err}")
            self._transition(ConnectionState.ERROR, f"Server error: {err}")
        else:
            logger.info("WebSocket bridge thread started successfully")
            self._transition(ConnectionState.LISTENING, "Server started")
            self._ready.set()

    def wait_until_ready(self, timeout: float = 10.0) -> bool:
        """Wait until the bridge is ready to accept connections.
        
        Args:
            timeout: Maximum time to wait in seconds.
            
        Returns:
            True if ready, False if timeout expired.
        """
        return self._ready.wait(timeout=timeout)

    def stop(self):
        """Stop the WebSocket server."""
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            self._watchdog_task = None

        if self.loop and self.server:
            # Signal server specific shutdown event on the loop
            self.loop.call_soon_threadsafe(self.server.stop)
        
        if self._thread:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("WebSocket bridge thread did not exit cleanly")
        
        # SHUTTING_DOWN → DISCONNECTED (SHUTTING_DOWN set by _thread_main.finally)
        self._transition(ConnectionState.DISCONNECTED, "Bridge stopped")

    def is_running(self) -> bool:
        """Check if the bridge thread is alive and running."""
        return self._thread is not None and self._thread.is_alive()

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
        self._panel_busy = data.get("busy", False)
        self._panel_active_request = data.get("activeRequestId")
        logger.debug(
            f"Heartbeat: busy={self._panel_busy}, "
            f"active={self._panel_active_request}, "
            f"uptime={data.get('uptimeMs', 0)}ms"
        )
        # E1: Start watchdog on first heartbeat if not already running
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())
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
            try:
                await self._handle_disconnect()
            except asyncio.CancelledError:
                pass
            return True
        return False

    async def execute_script_async(
        self, 
        script: str, 
        timeout: float = 30.0,
        command: Optional[CommandMetadata] = None,
        trace_id: Optional[str] = None
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

        # Build command info for message
        command_info = command.to_dict() if command else None
        if command:
            logger.info(f"[{trace_id or 'no-trace'}] Executing {command.command_type}")

        # Register request with trace_id for correlation
        request_id, future = self.registry.create_request(
            self.loop, 
            script, 
            command_info,
            trace_id
        )

        # Build message with trace_id for correlation
        message_data: Dict[str, Any] = {"id": request_id, "script": script}
        if command_info:
            message_data["command"] = command_info
        if trace_id:
            message_data["trace_id"] = trace_id
        
        message = json.dumps(message_data)

        try:
            # Use server transport
            await self.server.send(message)
            logger.debug(f"Sent request {request_id} (trace: {trace_id}) to Illustrator")

            # Wait for future
            return await asyncio.wait_for(future, timeout=timeout)

        except asyncio.TimeoutError:
            self.registry.fail_request(request_id, TimeoutError("Timeout"))
            cmd_ctx = f" [{command.command_type}]" if command else ""
            return {"error": format_code(ErrorCode.R_TIMEOUT,
                f"Script execution timed out after {timeout}s{cmd_ctx}")}

        except Exception as e:
            self.registry.fail_request(request_id, e)
            cmd_ctx = f" [{command.command_type}]" if command else ""
            return {"error": format_code(ErrorCode.R_UNKNOWN,
                f"Script execution failed{cmd_ctx}: {str(e)}")}

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
            timeout: Timeout for each update (total execution can be longer)
            command: Optional CommandMetadata for context
            trace_id: Optional trace ID for request correlation
            
        Yields:
            Progress updates and final result as dictionaries.
            Each update has a "type" field: "progress" or "complete".
        """
        if not self.is_connected():
            yield create_connection_error(self.port)
            return

        # Build command info for message
        command_info = command.to_dict() if command else None
        if command:
            logger.info(f"[{trace_id or 'no-trace'}] Streaming execution: {command.command_type}")

        # Create streaming request (uses queue instead of future)
        request_id, queue = self.registry.create_streaming_request(
            self.loop, 
            script, 
            command_info,
            trace_id
        )

        # Build message with streaming flag
        message_data: Dict[str, Any] = {
            "id": request_id, 
            "script": script,
            "streaming": True  # Signal CEP to send progress updates
        }
        if command_info:
            message_data["command"] = command_info
        if trace_id:
            message_data["trace_id"] = trace_id
        
        message = json.dumps(message_data)

        try:
            # Send script to CEP panel
            await self.server.send(message)
            logger.debug(f"Sent streaming request {request_id} (trace: {trace_id}) to Illustrator")

            # Yield updates from the queue
            async for update in self.registry.stream_updates(request_id, timeout):
                yield update
                if update.get("type") == "complete":
                    break

        except Exception as e:
            cmd_ctx = f" [{command.command_type}]" if command else ""
            error_result = {
                "error": format_code(ErrorCode.R_UNKNOWN,
                    f"Streaming execution failed{cmd_ctx}: {str(e)}"),
                "type": "error"
            }
            # B16: Clean up streaming entry to prevent resource leak
            self.registry.complete_streaming(request_id, error_result)
            yield error_result


# NOTE: Use get_runtime().get_bridge() directly.
# Standalone get_bridge() was removed to eliminate duplicate accessor paths.


def get_server():
    """Get the WebSocket server from the bridge."""
    from illustrator_mcp.runtime import get_runtime
    bridge = get_runtime().get_bridge()
    return bridge.server
