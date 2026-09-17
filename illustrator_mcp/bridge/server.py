"""
WebSocket server for Illustrator CEP bridge.
"""

import asyncio
import threading
import json
import logging
import websockets
from websockets.server import WebSocketServerProtocol
from typing import Optional, Callable, Awaitable

from illustrator_mcp.config import config

logger = logging.getLogger(__name__)


class WebSocketServer:
    """
    Manages the WebSocket server and client connection.
    Does not handle request logic, only transport.
    """
    
    def __init__(self, port: int, on_message: Callable[[str], Awaitable[None]],
                 on_disconnect: Optional[Callable[[], Awaitable[None]]] = None):
        self.port = port
        self.on_message = on_message
        self.on_disconnect = on_disconnect
        self.client: Optional[WebSocketServerProtocol] = None
        self.server = None
        self._shutdown_event: Optional[asyncio.Event] = None
        self._start_error: Optional[Exception] = None
        
    async def run(self, started_event: Optional[threading.Event] = None):
        """Run the WebSocket server."""
        self._shutdown_event = asyncio.Event()
        
        try:
            # F20: pass the CONFIGURED message limit to the transport.
            #
            # These flags were previously omitted, so websockets applied its
            # own 1 MiB default while the application believed the limit was
            # config.max_message_size_mb (10 MB). A response over 1 MiB was
            # therefore not rejected by the application check in
            # websocket_bridge._handle_message — the library closed the
            # connection first, which surfaces as an abrupt
            # "CEP panel is not connected" on the NEXT call rather than as an
            # error about the oversized message. Worth keeping in proportion:
            # the injected library prelude for execute_task is already ~509 KB,
            # so half the old default was spent before a script did anything.
            max_size = config.max_message_size_mb * 1024 * 1024
            self.server = await websockets.serve(
                self._handle_client,
                config.ws_host,
                self.port,
                ping_interval=30,
                ping_timeout=10,
                max_size=max_size,
                # Do not let the library buffer more than one oversized frame
                # before the handler sees it.
                max_queue=32,
                close_timeout=2,
            )
            logger.info(
                "WebSocket max message size: %d MB", config.max_message_size_mb
            )
            
            logger.info(f"="*50)
            logger.info(f"WebSocket bridge STARTED on port {self.port}")
            logger.info(f"CEP panel should connect to: ws://{config.ws_host}:{self.port}")
            logger.info(f"="*50)
            
            if started_event:
                started_event.set()

            # Keep server running until shutdown event
            await self._shutdown_event.wait()
            
        except OSError as e:
            self._start_error = e
            if started_event:
                started_event.set()
            # Publish failure immediately; stop() still joins this thread so
            # bounded diagnostic evidence is emitted before process exit.
            from illustrator_mcp.startup_diagnostics import log_bind_failure
            log_bind_failure(e, config.ws_host, self.port)
            raise
        except Exception as e:
            logger.error(f"WebSocket server error: {e}")
            self._start_error = e
            if started_event:
                started_event.set()
            raise
        finally:
            # Cancellation and startup errors take the same socket cleanup path.
            if self.server is not None:
                self.server.close()
                await self.server.wait_closed()

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
                if self.on_disconnect:
                    try:
                        await self.on_disconnect()
                    except Exception as e:
                        logger.error(f"on_disconnect callback error: {e}")

    async def send(self, message: str):
        """Send message to connected client."""
        ws = self.client  # snapshot to avoid TOCTOU race
        if ws is None:
            raise ConnectionError("No client connected")
        if not self.is_connected():
            self.client = None
            raise ConnectionError("Client connection is closed")
        await ws.send(message)

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
            # websockets 16+: use state enum (client.open is deprecated)
            if hasattr(self.client, 'state'):
                from websockets.protocol import State
                return self.client.state == State.OPEN
            # Fallback for older websockets versions
            if hasattr(self.client, 'open'):
                return self.client.open
            if hasattr(self.client, 'closed'):
                return not self.client.closed
            return False  # Safe default: assume disconnected if unknown
        except Exception:
            return False
