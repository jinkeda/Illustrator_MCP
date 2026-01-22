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
from enum import Enum, auto
from typing import Any, Optional, Dict

from illustrator_mcp.config import config, BRIDGE_STARTUP_TIMEOUT
from illustrator_mcp.shared import (
    CommandMetadata,
    ExecutionResponse,
    create_connection_error
)
from illustrator_mcp.bridge.server import WebSocketServer
from illustrator_mcp.bridge.request_registry import RequestRegistry

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """WebSocket connection state."""
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    ERROR = auto()


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
        
        # Initialize server (will be run in loop)
        self.server = WebSocketServer(
            port=self.port,
            on_message=self._handle_message
        )

    async def _handle_message(self, message: str):
        """Callback for incoming WebSocket messages."""
        try:
            data = json.loads(message)
            request_id = data.get("id")

            if request_id:
                # Delegate completion to registry
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
            self.state = ConnectionState.ERROR
        finally:
            # Cancel any pending requests on shutdown
            self.registry.cancel_all("Bridge shutting down")
            self.loop.close()

    def start(self):
        """Start the WebSocket server in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("WebSocket bridge already running")
            return

        self.state = ConnectionState.CONNECTING
        logger.info("Starting WebSocket bridge thread...")
        self._started.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._thread_main, daemon=True, name="WebSocketBridge")
        self._thread.start()

        # Wait for server to start
        if not self._started.wait(timeout=BRIDGE_STARTUP_TIMEOUT):
            logger.error(f"WebSocket bridge FAILED to start within {BRIDGE_STARTUP_TIMEOUT} seconds!")
            self.state = ConnectionState.ERROR
        else:
            logger.info("WebSocket bridge thread started successfully")
            self.state = ConnectionState.CONNECTED
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
        if self.loop and self.server:
            # Signal server specific shutdown event on the loop
            self.loop.call_soon_threadsafe(self.server.stop)
        
        if self._thread:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("WebSocket bridge thread did not exit cleanly")
        
        self.state = ConnectionState.DISCONNECTED

    def is_connected(self) -> bool:
        """Check if Illustrator CEP panel is connected."""
        return self.server.is_connected()

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

        # Register request
        request_id, future = self.registry.create_request(
            self.loop, 
            script, 
            command_info
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
            return {"error": f"TIMEOUT{cmd_ctx}: Script execution timed out after {timeout}s"}

        except Exception as e:
            self.registry.fail_request(request_id, e)
            cmd_ctx = f" [{command.command_type}]" if command else ""
            return {"error": f"EXECUTION_ERROR{cmd_ctx}: {str(e)}"}


def get_bridge() -> WebSocketBridge:
    """Get the global WebSocket bridge instance, starting it if needed."""
    from illustrator_mcp.runtime import get_runtime
    return get_runtime().get_bridge()




