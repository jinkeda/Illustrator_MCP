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


# ── Recovery steps, named once ─────────────────────────────────────
# Both the connection error raised mid-call and the status tool's report hand
# the caller the same instructions. They were previously only in the error
# string below, which meant the status tool would have had to restate them and
# they would have drifted apart.

SERVER_RECOVERY_STEPS: Tuple[str, ...] = (
    "The local WebSocket server is not running in this process.",
    "Check the owning MCP client's server logs for the startup identity and bind error.",
    "Release the integration through its owning client, then reconnect the destination "
    "client. Retrying a tool does not restart a failed bridge.",
)

PANEL_RECOVERY_STEPS: Tuple[str, ...] = (
    "Open Adobe Illustrator if it is not running",
    "Window > Extensions > MCP Control",
    "Click 'Connect' in the panel",
)

ILLUSTRATOR_RECOVERY_STEPS: Tuple[str, ...] = (
    "The panel is connected but Illustrator did not answer.",
    "Check whether Illustrator is busy with a modal dialog and dismiss it.",
    "If it is unresponsive, restart Illustrator and reconnect the panel.",
)


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
            + "".join(f"{i}. {step}\n"
                      for i, step in enumerate(PANEL_RECOVERY_STEPS, start=1))
            + "\n"
            f"(WebSocket server running on port {port})\n"
            "Call illustrator_connection_status for a full report.")
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
            "3. Check server logs for connection details")
    }


def check_connection_or_error(
    bridge_accessor: Callable,
    port: int,
    context: str = "",
) -> Tuple[bool, Optional[ExecutionResponse]]:
    """
    Check bridge connection and return error response if disconnected.
    
    Uses dependency injection: callers supply a bridge_accessor callable
    (e.g., ``_get_bridge``) instead of this module importing runtime.
    
    Args:
        bridge_accessor: Callable that returns the WebSocketBridge instance.
        port: The WebSocket port number.
        context: Optional context string for error message.
        
    Returns:
        Tuple of (is_connected, error_response_or_none).
        If connected: (True, None)
        If disconnected: (False, ExecutionResponse with error)
    """
    try:
        bridge = bridge_accessor()
    except Exception as e:
        logger.warning(f"Bridge accessor failed: {e}")
        return False, create_connection_error(port, context)

    info = bridge.get_connection_info()
    if isinstance(info, dict) and info.get("startup_error"):
        endpoint = str(info.get("host", "localhost")) + ":" + str(info.get("port", port))
        return False, {"error": format_code(ErrorCode.C_BRIDGE_ERROR,
            "Listener startup failed at " + endpoint + ": " + str(info["startup_error"]) +
            ". Another process may own the endpoint. Call illustrator_connection_status for details.")}
    if not bridge.is_connected():
        return False, create_connection_error(port, context)
    
    return True, None
