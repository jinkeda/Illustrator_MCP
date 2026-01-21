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
from typing import Any, Optional, Dict

from illustrator_mcp.config import config
from illustrator_mcp.shared import create_connection_error
from illustrator_mcp.bridge.server import WebSocketServer
from illustrator_mcp.bridge.request_registry import RequestRegistry

logger = logging.getLogger(__name__)


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
        finally:
            # Cancel any pending requests on shutdown
            self.registry.cancel_all("Bridge shutting down")
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
        else:
            logger.info("WebSocket bridge thread started successfully")
            import time
            time.sleep(0.1)

    def stop(self):
        """Stop the WebSocket server."""
        if self.loop and self.server:
            # Signal server specific shutdown event on the loop
            self.loop.call_soon_threadsafe(self.server.stop)
        
        if self._thread:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("WebSocket bridge thread did not exit cleanly")

    def is_connected(self) -> bool:
        """Check if Illustrator CEP panel is connected."""
        return self.server.is_connected()

    async def execute_script_async(
        self, 
        script: str, 
        timeout: float = 30.0,
        command_type: str = None,
        tool_name: str = None,
        params: Dict[str, Any] = None
    ) -> dict:
        """Execute a script in Illustrator (async version)."""
        if not self.is_connected():
            return create_connection_error(self.port)

        # Build command metadata
        command_info = None
        if command_type:
            command_info = {
                "type": command_type,
                "tool": tool_name or command_type,
                "params": params or {}
            }
            logger.info(f"[{command_type}] Executing via {tool_name or 'unknown'}")

        # Register request
        request_id, future = self.registry.create_request(
            self.loop, 
            script, 
            command_info
        )

        # Build message
        message_data = {"id": request_id, "script": script}
        if command_info:
            message_data["command"] = command_info
        
        message = json.dumps(message_data)

        try:
            # Use server transport
            await self.server.send(message)
            logger.debug(f"Sent request {request_id} to Illustrator")

            # Wait for future
            return await asyncio.wait_for(future, timeout=timeout)

        except asyncio.TimeoutError:
            self.registry.fail_request(request_id, TimeoutError("Timeout"))
            cmd_ctx = f" [{command_type}]" if command_type else ""
            return {"error": f"TIMEOUT{cmd_ctx}: Script execution timed out after {timeout}s"}

        except Exception as e:
            self.registry.fail_request(request_id, e)
            cmd_ctx = f" [{command_type}]" if command_type else ""
            return {"error": f"EXECUTION_ERROR{cmd_ctx}: {str(e)}"}


def get_bridge() -> WebSocketBridge:
    """Get the global WebSocket bridge instance, starting it if needed."""
    from illustrator_mcp.runtime import get_runtime
    return get_runtime().get_bridge()




