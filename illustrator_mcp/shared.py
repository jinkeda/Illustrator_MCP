"""
Shared MCP server instance for all tool modules.

This module provides the shared FastMCP instance that is used by all tool modules.
Import `mcp` from this module to register tools.

Uses lifespan management for proper WebSocket bridge startup/shutdown.
"""

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, Any, Optional, TypedDict, Tuple

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


# ==================== Shared Types ====================

@dataclass
class CommandMetadata:
    """Metadata for a command execution request."""
    command_type: str
    tool_name: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.command_type,
            "tool": self.tool_name or self.command_type,
            "params": self.params,
            "trace_id": self.trace_id
        }


class ExecutionResponse(TypedDict, total=False):
    """Canonical response shape for script execution."""
    result: Any
    error: str
    trace_id: str
    elapsed_ms: float
    command: str


# ==================== Connection Helpers ====================

def create_connection_error(port: int, context: str = "") -> ExecutionResponse:
    """
    Create a standardized connection error response with actionable suggestions.
    
    Args:
        port: The WebSocket port number.
        context: Optional context string (e.g., command type).
        
    Returns:
        ExecutionResponse with error message and quick fixes.
    """
    prefix = f" [{context}]" if context else ""
    return {
        "error": (
            f"ILLUSTRATOR_DISCONNECTED{prefix}: CEP panel is not connected.\n\n"
            "Quick Fixes:\n"
            "1. Open Adobe Illustrator if not running\n"
            "2. Window > Extensions > MCP Control\n"
            "3. Click 'Connect' in the panel\n\n"
            f"(WebSocket server running on port {port})"
        )
    }


def check_connection_or_error(
    port: int,
    context: str = ""
) -> Tuple[bool, Optional[ExecutionResponse]]:
    """
    Check bridge connection and return error response if disconnected.
    
    Centralizes the connection check logic used by both proxy_client
    and websocket_bridge to avoid duplicate code.
    
    Args:
        port: The WebSocket port number.
        context: Optional context string for error message.
        
    Returns:
        Tuple of (is_connected, error_response_or_none).
        If connected: (True, None)
        If disconnected: (False, ExecutionResponse with error)
    """
    from illustrator_mcp.runtime import get_runtime
    
    bridge = get_runtime().get_bridge()
    if bridge.is_connected():
        return True, None
    return False, create_connection_error(port, context)


# ==================== Server Lifespan ====================

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
