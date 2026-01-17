"""
Integrated WebSocket bridge for Adobe Illustrator CEP panel.

This module provides a WebSocket server that runs within the MCP server process,
eliminating the need for a separate Node.js proxy server.

Architecture:
- WebSocket server runs on port 8081 (configurable)
- CEP panel connects directly to this server
- MCP tools communicate via the bridge's internal API
"""

import asyncio
import json
import logging
import threading
from typing import Any, Optional, Dict, Callable
from dataclasses import dataclass
import websockets
from websockets.server import WebSocketServerProtocol

from illustrator_mcp.config import config

logger = logging.getLogger(__name__)


@dataclass
class PendingRequest:
    """A pending request waiting for Illustrator response."""
    future: asyncio.Future
    script: str
    command: Optional[Dict[str, Any]] = None  # Command metadata for logging


class WebSocketBridge:
    """
    Integrated WebSocket bridge for Illustrator communication.

    Runs a WebSocket server that CEP panel connects to directly.
    Provides async interface for executing scripts in Illustrator.
    """

    def __init__(self, port: int = None):
        self.port = port or config.WS_PORT
        self.client: Optional[WebSocketServerProtocol] = None
        self.pending_requests: Dict[int, PendingRequest] = {}
        self.request_id = 0
        self.server = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()
        self._lock = threading.Lock()

    async def _handle_client(self, websocket: WebSocketServerProtocol):
        """Handle a connected CEP panel client."""
        # Handle new connection - "Last connection wins" strategy
        # If there's an existing client, we assume it's stale or being replaced
        if self.client is not None:
             try:
                # Close old client if it looks open
                is_closed = getattr(self.client, 'closed', True)
                if not is_closed:
                    logger.info("New connection received. Closing existing/stale connection.")
                    # We don't await this close to avoid blocking the new connection acceptance
                    # Just schedule it or let garbage collection handle it eventually, 
                    # but we MUST update self.client immediately.
                    asyncio.create_task(self.client.close(1000, "Replaced by new connection"))
             except Exception as e:
                logger.warning(f"Error closing old connection: {e}")
        
        logger.info("Illustrator CEP panel connected")
        self.client = websocket

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    request_id = data.get("id")

                    if request_id and request_id in self.pending_requests:
                        pending = self.pending_requests.pop(request_id)
                        if not pending.future.done():
                            pending.future.set_result(data)
                        logger.debug(f"Request {request_id} completed")
                    else:
                        logger.warning(f"Received response for unknown request: {request_id}")

                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON from CEP panel: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.info("Illustrator CEP panel disconnected")
        finally:
            if self.client == websocket:
                self.client = None
                # Cancel all pending requests
                for req_id, pending in list(self.pending_requests.items()):
                    if not pending.future.done():
                        pending.future.set_exception(
                            ConnectionError("Illustrator disconnected")
                        )
                self.pending_requests.clear()

    async def _run_server(self):
        """Run the WebSocket server."""
        try:
            # Use localhost instead of 0.0.0.0 for better Windows compatibility
            # CEP panel connects to ws://localhost:8081, so binding to localhost is sufficient
            self.server = await websockets.serve(
                self._handle_client,
                "localhost",
                self.port,
                ping_interval=30,
                ping_timeout=10
            )
            logger.info(f"="*50)
            logger.info(f"WebSocket bridge STARTED on port {self.port}")
            logger.info(f"CEP panel should connect to: ws://localhost:{self.port}")
            logger.info(f"="*50)
            self._started.set()

            # Keep server running
            await asyncio.Future()  # Run forever

        except OSError as e:
            if "address already in use" in str(e).lower() or e.errno == 10048:
                logger.error(f"Port {self.port} is already in use! Another process may be using it.")
                logger.error("Check with: netstat -ano | findstr {self.port}")
            else:
                logger.error(f"WebSocket server OSError: {e}")
            self._started.set()  # Unblock waiters even on error
            raise
        except Exception as e:
            logger.error(f"WebSocket server error: {e}")
            self._started.set()  # Unblock waiters even on error
            raise

    def _thread_main(self):
        """Main function for the server thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            self.loop.run_until_complete(self._run_server())
        except Exception as e:
            logger.error(f"Server thread error: {e}")
        finally:
            self.loop.close()

    def start(self):
        """Start the WebSocket server in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("WebSocket bridge already running")
            return

        logger.info("Starting WebSocket bridge thread...")
        self._started.clear()
        self._thread = threading.Thread(target=self._thread_main, daemon=True, name="WebSocketBridge")
        self._thread.start()

        # Wait for server to start with longer timeout
        if not self._started.wait(timeout=10.0):
            logger.error("WebSocket bridge FAILED to start within 10 seconds!")
            logger.error("This is a critical error - CEP panel will not be able to connect.")
        else:
            logger.info("WebSocket bridge thread started successfully")
            # Brief delay to ensure server is fully ready
            import time
            time.sleep(0.1)

    def stop(self):
        """Stop the WebSocket server."""
        if self.server:
            self.server.close()
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)

    def is_connected(self) -> bool:
        """Check if Illustrator CEP panel is connected."""
        if self.client is None:
            return False
        try:
            # Try 'open' attribute first (websockets 10+)
            if hasattr(self.client, 'open'):
                return self.client.open
            # Fall back to checking 'closed' attribute
            if hasattr(self.client, 'closed'):
                return not self.client.closed
            # Fall back to checking state (websockets 11+)
            if hasattr(self.client, 'state'):
                from websockets.protocol import State
                return self.client.state == State.OPEN
            # If nothing works, assume connected if client exists
            return True
        except Exception as e:
            logger.warning(f"Error checking connection state: {e}")
            return False

    async def execute_script_async(
        self, 
        script: str, 
        timeout: float = 30.0,
        command_type: str = None,
        tool_name: str = None,
        params: Dict[str, Any] = None
    ) -> dict:
        """
        Execute a script in Illustrator (async version).

        Args:
            script: JavaScript/ExtendScript code to execute
            timeout: Maximum time to wait for response
            command_type: Optional command type for logging (e.g., "draw_rectangle")
            tool_name: Optional tool name for logging (e.g., "illustrator_draw_rectangle")
            params: Optional parameters dict for debugging (sanitized, not for execution)

        Returns:
            Response dictionary from Illustrator
        """
        if not self.is_connected():
            return {
                "error": "ILLUSTRATOR_DISCONNECTED: CEP panel is not connected. "
                         "Please open Illustrator and ensure the MCP panel shows 'Connected'."
            }

        with self._lock:
            self.request_id += 1
            request_id = self.request_id

        # Build command metadata if provided
        command_info = None
        if command_type:
            command_info = {
                "type": command_type,
                "tool": tool_name or command_type,
                "params": params or {}
            }
            logger.info(f"[{command_type}] Executing via {tool_name or 'unknown'}")

        # Create future for response
        future = self.loop.create_future()
        self.pending_requests[request_id] = PendingRequest(
            future=future, 
            script=script,
            command=command_info
        )

        # Build message with optional command metadata
        message_data = {"id": request_id, "script": script}
        if command_info:
            message_data["command"] = command_info
        
        message = json.dumps(message_data)

        try:
            await self.client.send(message)
            logger.debug(f"Sent request {request_id} to Illustrator")

            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except asyncio.TimeoutError:
            self.pending_requests.pop(request_id, None)
            cmd_ctx = f" [{command_type}]" if command_type else ""
            return {"error": f"TIMEOUT{cmd_ctx}: Script execution timed out after {timeout}s"}

        except Exception as e:
            self.pending_requests.pop(request_id, None)
            cmd_ctx = f" [{command_type}]" if command_type else ""
            return {"error": f"EXECUTION_ERROR{cmd_ctx}: {str(e)}"}

    def execute_script(
        self, 
        script: str, 
        timeout: float = 30.0,
        command_type: str = None,
        tool_name: str = None,
        params: Dict[str, Any] = None
    ) -> dict:
        """
        Execute a script in Illustrator (sync version for use from other threads).

        Args:
            script: JavaScript/ExtendScript code to execute
            timeout: Maximum time to wait for response
            command_type: Optional command type for logging
            tool_name: Optional tool name for logging
            params: Optional parameters dict for debugging

        Returns:
            Response dictionary from Illustrator
        """
        if not self.loop or not self._thread or not self._thread.is_alive():
            return {"error": "WebSocket bridge not running"}

        if not self.is_connected():
            return {
                "error": "ILLUSTRATOR_DISCONNECTED: CEP panel is not connected. "
                         "Please open Illustrator and ensure the MCP panel shows 'Connected'."
            }

        # Schedule coroutine on the event loop thread
        future = asyncio.run_coroutine_threadsafe(
            self.execute_script_async(
                script, timeout, command_type, tool_name, params
            ),
            self.loop
        )

        try:
            return future.result(timeout=timeout + 5)  # Extra buffer for scheduling
        except Exception as e:
            return {"error": f"BRIDGE_ERROR: {str(e)}"}


# Global bridge instance
_bridge: Optional[WebSocketBridge] = None


def get_bridge() -> WebSocketBridge:
    """Get the global WebSocket bridge instance, starting it if needed."""
    global _bridge
    if _bridge is None:
        _bridge = WebSocketBridge()
        _bridge.start()
    return _bridge


def ensure_bridge_running():
    """Ensure the WebSocket bridge is running."""
    bridge = get_bridge()
    if not bridge._thread or not bridge._thread.is_alive():
        bridge.start()
    return bridge
