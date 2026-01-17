"""
Script execution for Adobe Illustrator.

This module provides the core execute_script functionality that sends
JavaScript/ExtendScript to Illustrator via the integrated WebSocket bridge.
All specific tools use this as their underlying implementation.

Architecture (simplified):
- MCP server includes an integrated WebSocket server
- CEP panel connects directly to MCP server's WebSocket (port 8081)
- No separate Node.js proxy server needed!
"""

import asyncio
import json
import logging
from typing import Any, Optional

from illustrator_mcp.config import config

# Configure logging
logger = logging.getLogger(__name__)


# Lazy import to avoid circular dependencies
_bridge = None


def _get_bridge():
    """Get the WebSocket bridge instance, ensuring it's running.

    Uses ensure_bridge_running() to check if the bridge thread is alive
    and restart it if needed (e.g., if it failed due to port conflict).
    """
    global _bridge
    from illustrator_mcp.websocket_bridge import ensure_bridge_running
    _bridge = ensure_bridge_running()
    return _bridge


class IllustratorProxy:
    """Client for communicating with Illustrator via WebSocket bridge."""

    def __init__(self, timeout: Optional[float] = None):
        self.timeout = timeout or config.TIMEOUT

    async def execute_script(self, script: str) -> dict[str, Any]:
        """
        Execute a JavaScript/ExtendScript in Illustrator.

        This is the core method that all tools use internally.
        Uses the integrated WebSocket bridge (no separate proxy needed).

        IMPORTANT: The WebSocket bridge runs in a SEPARATE THREAD with its own
        event loop. We must use run_in_executor to call the bridge's synchronous
        execute_script method (which internally uses run_coroutine_threadsafe
        to properly coordinate with the bridge's event loop).

        Args:
            script: JavaScript code to execute in Illustrator

        Returns:
            Response from Illustrator containing result or error
        """
        bridge = _get_bridge()

        if not bridge.is_connected():
            return {
                "error": "ILLUSTRATOR_DISCONNECTED: CEP panel is not connected. "
                         "Please open Illustrator and ensure the MCP Control panel shows 'Connected'. "
                         f"(WebSocket server running on port {config.WS_PORT})"
            }

        try:
            # Use run_in_executor to call the bridge's SYNC method which properly
            # coordinates with the bridge's event loop via run_coroutine_threadsafe
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,  # Use default thread pool
                lambda: bridge.execute_script(script, timeout=self.timeout)
            )
            return result

        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return {"error": f"UNEXPECTED_ERROR: {str(e)}"}

    async def check_connection(self) -> dict[str, Any]:
        """Check if Illustrator is connected."""
        bridge = _get_bridge()
        return {
            "connected": bridge.is_connected(),
            "ws_port": config.WS_PORT
        }


# Global proxy instance
_proxy: Optional[IllustratorProxy] = None


def get_proxy() -> IllustratorProxy:
    """Get the global proxy instance."""
    global _proxy
    if _proxy is None:
        _proxy = IllustratorProxy()
    return _proxy


async def execute_script(script: str) -> dict[str, Any]:
    """
    Execute a JavaScript script in Illustrator.

    This is the core function that all specific tools use internally.

    Args:
        script: JavaScript/ExtendScript code to execute

    Returns:
        Dictionary with 'result' or 'error' key
    """
    return await get_proxy().execute_script(script)


async def execute_script_with_context(
    script: str,
    command_type: str,
    tool_name: str = None,
    params: dict = None
) -> dict[str, Any]:
    """
    Execute a JavaScript script with command context for hybrid protocol.

    This provides better logging and debugging by including metadata
    about what operation is being performed.

    IMPORTANT: The WebSocket bridge runs in a SEPARATE THREAD with its own
    event loop. We must use run_in_executor to call the bridge's synchronous
    execute_script method.

    Args:
        script: JavaScript/ExtendScript code to execute
        command_type: Type of command (e.g., "draw_rectangle", "create_layer")
        tool_name: Name of the MCP tool (e.g., "illustrator_draw_rectangle")
        params: Parameters passed to the tool (for debugging, not execution)

    Returns:
        Dictionary with 'result' or 'error' key
    """
    bridge = _get_bridge()

    if not bridge.is_connected():
        return {
            "error": f"ILLUSTRATOR_DISCONNECTED [{command_type}]: CEP panel is not connected. "
                     "Please open Illustrator and ensure the MCP Control panel shows 'Connected'. "
                     f"(WebSocket server running on port {config.WS_PORT})"
        }

    try:
        # Use run_in_executor to call the bridge's SYNC method which properly
        # coordinates with the bridge's event loop via run_coroutine_threadsafe
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,  # Use default thread pool
            lambda: bridge.execute_script(
                script=script,
                timeout=config.TIMEOUT,
                command_type=command_type,
                tool_name=tool_name,
                params=params
            )
        )
        return result

    except Exception as e:
        logger.error(f"[{command_type}] Unexpected error: {e}")
        return {"error": f"UNEXPECTED_ERROR [{command_type}]: {str(e)}"}


def format_response(response: dict[str, Any]) -> str:
    """
    Format the response from Illustrator for MCP output.

    Args:
        response: Response dictionary from execute_script

    Returns:
        Formatted string for MCP tool response
    """
    if response.get("error"):
        error = response['error']
        # Make connection errors very prominent
        if "DISCONNECTED" in error or "not connected" in error.lower():
            return f"⚠️ {error}\n\n[STOP: Do not retry until connection is restored]"
        return f"Error: {error}"

    result = response.get("result", response)

    # Handle nested result from ExtendScript
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict) and parsed.get("error"):
                return f"Error: {parsed['error']}"
            if isinstance(parsed, dict) and parsed.get("success") is False:
                return f"Error: {parsed.get('error', 'Operation failed')}"
            result = parsed
        except json.JSONDecodeError:
            pass

    if isinstance(result, (dict, list)):
        return json.dumps(result, indent=2)
    return str(result)
