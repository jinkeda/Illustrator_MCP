"""
Connection check and error helpers for Illustrator MCP.

This module provides standardized connection error responses and
connection-checking logic. It depends only on types.py.

Uses dependency injection (bridge_accessor callable) instead of
importing runtime, keeping this layer free of upward dependencies.
"""

import logging
from typing import Callable, Optional, Tuple

from illustrator_mcp.types import ExecutionResponse
from illustrator_mcp.errors import ErrorCode, format_code

logger = logging.getLogger(__name__)


def create_connection_error(port: int, context: str = "") -> ExecutionResponse:
    """
    Create a standardized connection error response with actionable suggestions.
    
    Args:
        port: The WebSocket port number.
        context: Optional context string (e.g., command type).
        
    Returns:
        ExecutionResponse with error message and quick fixes.
    """
    ctx = f" ({context})" if context else ""
    return {
        "error": format_code(ErrorCode.C_DISCONNECTED,
            f"CEP panel is not connected{ctx}.\n\n"
            "Quick Fixes:\n"
            "1. Open Adobe Illustrator if not running\n"
            "2. Window > Extensions > MCP Control\n"
            "3. Click 'Connect' in the panel\n\n"
            f"(WebSocket server running on port {port})")
    }


def create_duplicate_connection_error(port: int) -> ExecutionResponse:
    """
    Create a standardized error for duplicate connection attempts.
    
    Args:
        port: The WebSocket port number.
        
    Returns:
        ExecutionResponse with error message and quick fixes.
    """
    return {
        "error": format_code(ErrorCode.C_BRIDGE_ERROR,
            f"Another MCP client is already connected on port {port}.\n\n"
            "Quick Fixes:\n"
            "1. Close other Claude Code instances using Illustrator MCP\n"
            "2. Restart Illustrator if the connection seems stuck\n"
            "3. Use 'illustrator_get_connection_info' tool to check connection status")
    }


def check_connection_or_error(
    bridge_accessor: Callable,
    port: int,
    context: str = "",
    health_check: bool = False
) -> Tuple[bool, Optional[ExecutionResponse]]:
    """
    Check bridge connection and return error response if disconnected.
    
    Uses dependency injection: callers supply a bridge_accessor callable
    (e.g., ``_get_bridge``) instead of this module importing runtime.
    
    Args:
        bridge_accessor: Callable that returns the WebSocketBridge instance.
        port: The WebSocket port number.
        context: Optional context string for error message.
        health_check: Reserved for future use. Currently does nothing.
        
    Returns:
        Tuple of (is_connected, error_response_or_none).
        If connected: (True, None)
        If disconnected: (False, ExecutionResponse with error)
    """
    bridge = bridge_accessor()
    
    if not bridge.is_connected():
        return False, create_connection_error(port, context)
    
    # TODO: Implement proper async health_check using bridge.execute_script_async()
    # when needed for stale connection detection.
    
    return True, None
