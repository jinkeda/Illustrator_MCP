"""
WebSocket server for Illustrator CEP bridge.
"""

import asyncio
import json
import logging
import websockets
from websockets.server import WebSocketServerProtocol
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)


class WebSocketServer:
    """
    Manages the WebSocket server and client connection.
    Does not handle request logic, only transport.
    """
    
    def __init__(self, port: int, on_message: Callable[[str], Awaitable[None]]):
        self.port = port
        self.on_message = on_message
        self.client: Optional[WebSocketServerProtocol] = None
        self.server = None
        self._shutdown_event: Optional[asyncio.Event] = None
        
    async def run(self, started_event: Optional[asyncio.Event] = None):
        """Run the WebSocket server."""
        self._shutdown_event = asyncio.Event()
        
        try:
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
            
            if started_event:
                started_event.set()

            # Keep server running until shutdown event
            await self._shutdown_event.wait()
            
            # Graceful shutdown
            logger.info("Shutting down WebSocket bridge...")
            self.server.close()
            await self.server.wait_closed()
            
            # Close active client if any
            if self.client:
                await self.client.close(1000, "Server shutting down")

        except OSError as e:
            if "address already in use" in str(e).lower() or e.errno == 10048:
                logger.error(f"Port {self.port} is already in use!")
            else:
                logger.error(f"WebSocket server OSError: {e}")
            if started_event:
                started_event.set()
            raise
        except Exception as e:
            logger.error(f"WebSocket server error: {e}")
            if started_event:
                started_event.set()
            raise

    async def _handle_client(self, websocket: WebSocketServerProtocol):
        """Handle a connected client."""
        # Reject if there is already an active connection
        if self.client is not None and self.is_connected():
            logger.warning(
                "Connection rejected: Another client is already connected."
            )
            await websocket.close(
                4001,
                "Another MCP client is already connected to Illustrator. "
                "Please close the existing connection first."
            )
            return

        # Clean up zombie connections (disconnected but not yet cleaned)
        if self.client is not None:
            logger.info("Cleaning up stale connection")
            try:
                await self.client.close(1000, "Stale connection cleanup")
            except Exception:
                pass
            self.client = None

        logger.info("Illustrator CEP panel connected")
        self.client = websocket

        try:
            async for message in websocket:
                await self.on_message(message)

        except websockets.exceptions.ConnectionClosed:
            logger.info("Illustrator CEP panel disconnected")
        finally:
            if self.client == websocket:
                self.client = None
                # Let upper layer know if needed (could add on_disconnect callback)

    async def send(self, message: str):
        """Send message to connected client."""
        if not self.client:
            raise ConnectionError("No client connected")
        await self.client.send(message)

    def stop(self):
        """Signal shutdown."""
        # This must be called from the loop thread or via call_soon_threadsafe
        if self._shutdown_event:
            self._shutdown_event.set()

    def is_connected(self) -> bool:
        """Check if client is connected."""
        if self.client is None:
            return False
        try:
            if hasattr(self.client, 'open'):
                return self.client.open
            if hasattr(self.client, 'closed'):
                return not self.client.closed
            return True
        except Exception:
            return False
