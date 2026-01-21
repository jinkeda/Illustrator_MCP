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
# Managed via RuntimeContext now

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """
    Manage MCP server startup and shutdown lifecycle.
    
    This ensures the WebSocket bridge is properly started before
    any tools are called, and cleanly shut down when the server stops.
    """
    from illustrator_mcp.runtime import get_runtime
    from illustrator_mcp.config import config
    
    logger.info("=" * 60)
    logger.info("Adobe Illustrator MCP Server - LIFESPAN STARTUP")
    logger.info("=" * 60)
    
    bridge = None
    try:
        # Start the WebSocket bridge via runtime
        logger.info("Starting WebSocket bridge...")
        bridge = get_runtime().get_bridge()
        
        # Verify bridge started successfully
        if bridge._thread and bridge._thread.is_alive():
            logger.info(f"✓ WebSocket bridge started on port {config.ws_port}")
            logger.info(f"  CEP panel should connect to: ws://localhost:{config.ws_port}")
        else:
            logger.error("✗ WebSocket bridge failed to start!")
            logger.error("  CEP panel will NOT be able to connect.")
        
        # Dynamic tool count
        try:
            tools = await server.list_tools()
            tool_count = len(tools)
            msg = f"{tool_count} tools registered"
        except Exception:
            msg = "tools registered"

        logger.info("")
        logger.info(f"MCP server ready ({msg})")
        logger.info("=" * 60)
        
        # Yield empty context - bridge is accessed via get_runtime().get_bridge()
        yield {}
        
    finally:
        # Clean up on shutdown
        logger.info("=" * 60)
        logger.info("Adobe Illustrator MCP Server - LIFESPAN SHUTDOWN")
        logger.info("=" * 60)
        
        if bridge:
            logger.info("Stopping WebSocket bridge...")
            bridge.stop()
            logger.info("WebSocket bridge stopped")
        
        logger.info("Server shutdown complete")


# Create MCP server with lifespan management
mcp = FastMCP(
    "illustrator_mcp",
    lifespan=server_lifespan
)


def create_connection_error(port: int, context: str = "") -> Dict[str, str]:
    """
    Create a standardized connection error response.
    
    Args:
        port: The WebSocket port number.
        context: Optional context string (e.g., command type).
        
    Returns:
        Dict with error message.
    """
    prefix = f" [{context}]" if context else ""
    return {
        "error": f"ILLUSTRATOR_DISCONNECTED{prefix}: CEP panel is not connected. "
                 "Please open Illustrator and ensure the MCP Control panel shows 'Connected'. "
                 f"(WebSocket server running on port {port})"
    }
