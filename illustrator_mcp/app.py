"""
Application composition for Illustrator MCP.

Owns the FastMCP singleton and server lifespan wiring.
This is the only module that constructs the MCP application instance.
"""

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """
    Manage MCP server startup and shutdown lifecycle.

    This ensures the WebSocket bridge is properly started before
    any tools are called, and cleanly shut down when the server stops.
    """
    from illustrator_mcp.runtime import get_runtime

    logger.info("=" * 60)
    logger.info("Adobe Illustrator MCP Server - LIFESPAN STARTUP")
    logger.info("=" * 60)
    
    bridge = None
    try:
        # Start the WebSocket bridge via runtime
        logger.info("Starting WebSocket bridge...")
        bridge = get_runtime().get_bridge()
        
        # Verify bridge started successfully
        if bridge.is_running():
            logger.info("WebSocket bridge started at %s", bridge.server.endpoint)
            logger.info("  CEP panel should connect to: %s", bridge.server.endpoint)
        else:
            error = RuntimeError("WebSocket bridge is not listening")
            if bridge.server._start_error is not None:
                raise error from bridge.server._start_error
            raise error
        
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
        primary_error = sys.exc_info()[1]
        # Clean up on shutdown
        logger.info("=" * 60)
        logger.info("Adobe Illustrator MCP Server - LIFESPAN SHUTDOWN")
        logger.info("=" * 60)
        
        # Use runtime.shutdown() for full cleanup (bridge + proxy)
        try:
            from illustrator_mcp.runtime import get_runtime
            get_runtime().shutdown()
            logger.info("Runtime shutdown complete (bridge + proxy)")
        except Exception as e:
            logger.error(f"Error during runtime shutdown: {e}")
            if primary_error is None:
                raise
            # Preserve the startup/request exception; runtime retains the bridge.
            logger.exception("Cleanup also failed while handling %r", primary_error)
        else:
            logger.info("Server shutdown complete")


# Create MCP server with lifespan management
mcp = FastMCP(
    "illustrator_mcp",
    lifespan=server_lifespan
)
