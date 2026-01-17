"""
Shared MCP server instance for all tool modules.

This module provides the shared FastMCP instance that is used by all tool modules.
Import `mcp` from this module to register tools.

Uses lifespan management for proper WebSocket bridge startup/shutdown.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Global bridge reference for lifespan management
_bridge_instance = None


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """
    Manage MCP server startup and shutdown lifecycle.
    
    This ensures the WebSocket bridge is properly started before
    any tools are called, and cleanly shut down when the server stops.
    """
    global _bridge_instance
    
    logger.info("=" * 60)
    logger.info("Adobe Illustrator MCP Server - LIFESPAN STARTUP")
    logger.info("=" * 60)
    
    try:
        # Import here to avoid circular imports
        from illustrator_mcp.websocket_bridge import ensure_bridge_running
        from illustrator_mcp.config import config
        
        # Start the WebSocket bridge
        logger.info("Starting WebSocket bridge...")
        _bridge_instance = ensure_bridge_running()
        
        # Verify bridge started successfully
        if _bridge_instance._thread and _bridge_instance._thread.is_alive():
            logger.info(f"✓ WebSocket bridge started on port {config.WS_PORT}")
            logger.info(f"  CEP panel should connect to: ws://localhost:{config.WS_PORT}")
        else:
            logger.error("✗ WebSocket bridge failed to start!")
            logger.error("  CEP panel will NOT be able to connect.")
        
        logger.info("")
        logger.info("MCP server ready (94 tools across 15 categories)")
        logger.info("=" * 60)
        
        # Yield empty context - bridge is accessed via get_bridge()
        yield {}
        
    finally:
        # Clean up on shutdown
        logger.info("=" * 60)
        logger.info("Adobe Illustrator MCP Server - LIFESPAN SHUTDOWN")
        logger.info("=" * 60)
        
        if _bridge_instance:
            logger.info("Stopping WebSocket bridge...")
            _bridge_instance.stop()
            _bridge_instance = None
            logger.info("WebSocket bridge stopped")
        
        logger.info("Server shutdown complete")


# Create MCP server with lifespan management
mcp = FastMCP(
    "illustrator_mcp",
    lifespan=server_lifespan
)
