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
import time
import uuid
from typing import Any, Optional

from illustrator_mcp.config import config
from illustrator_mcp.shared import create_connection_error

# Configure logging
logger = logging.getLogger(__name__)


# ==================== Request ID Generation ====================

def generate_request_id() -> str:
    """Generate a unique request ID for tracing.
    
    Format: req_<8-char-hex>
    Example: req_a1b2c3d4
    """
    return f"req_{uuid.uuid4().hex[:8]}"



def _get_bridge():
    """Get the WebSocket bridge instance."""
    from illustrator_mcp.runtime import get_runtime
    return get_runtime().get_bridge()



class IllustratorProxy:
    """Client for communicating with Illustrator via WebSocket bridge."""

    def __init__(self, timeout: Optional[float] = None):
        self.timeout = timeout or config.timeout

    async def execute_script(self, script: str) -> dict[str, Any]:
        """
        Execute a JavaScript/ExtendScript in Illustrator.

        This is the core method that all tools use internally.
        Uses the integrated WebSocket bridge via the centralized helper.

        Args:
            script: JavaScript code to execute in Illustrator

        Returns:
            Response from Illustrator containing result or error
        """
        return await _execute_via_bridge(
            script=script,
            timeout=self.timeout
        )

    async def check_connection(self) -> dict[str, Any]:
        """Check if Illustrator is connected."""
        bridge = _get_bridge()
        return {
            "connected": bridge.is_connected(),
            "ws_port": config.ws_port
        }


def get_proxy() -> IllustratorProxy:
    """Get the global proxy instance."""
    from illustrator_mcp.runtime import get_runtime
    return get_runtime().get_proxy()


async def _execute_via_bridge(
    script: str,
    timeout: float,
    command_type: str = "execute_script",
    tool_name: str = None,
    params: dict = None,
    request_id: str = None
) -> dict[str, Any]:
    """
    Centralized helper to execute scripts via the WebSocket bridge.
    
    Handles:
    - Connection checking
    - Thread-safe bridging (run_coroutine_threadsafe)
    - Timeout management
    - Error handling
    
    Args:
        script: JavaScript code to execute
        timeout: Execution timeout in seconds
        command_type: Type of command for logging
        tool_name: Optional tool name for context
        params: Optional parameters for context
        request_id: Optional request ID for tracing
        
    Returns:
        Response dictionary with result/error
    """
    bridge = _get_bridge()

    if not bridge.is_connected():
        # Only log warning if strictly needed, or let caller handle logging?
        # For simple execute_script, we usually just return error.
        # For context usage, duplicate logging is avoided by checking caller.
        return create_connection_error(config.ws_port, command_type)

    try:
        # Direct async call via thread-safe future wrapping
        # This avoids the double-wrap of run_in_executor -> blocking wait
        conc_future = asyncio.run_coroutine_threadsafe(
            bridge.execute_script_async(
                script=script,
                timeout=timeout,
                command_type=command_type,
                tool_name=tool_name,
                params=params,
                # Pass request_id if supported by bridge, else it's just context here
                # bridge.execute_script_async signature: 
                # (script, timeout, command_type, tool_name, params)
                # It doesn't take request_id explicitly in signature based on previous code usage
            ),
            bridge.loop
        )
        return await asyncio.wrap_future(conc_future)
        
    except TimeoutError:
        return {"error": f"TIMEOUT: Script execution timed out after {timeout}s"}
    except Exception as e:
        logger.error(f"PROXY_ERROR [{command_type}]: {e}")
        return {"error": f"PROXY_ERROR: {str(e)}"}


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
    params: dict = None,
    request_id: str = None
) -> dict[str, Any]:
    """
    Execute a JavaScript script with command context for hybrid protocol.

    This provides better logging and debugging by including metadata
    about what operation is being performed.
    
    Delegates to _execute_via_bridge for actual execution.

    Args:
        script: JavaScript/ExtendScript code to execute
        command_type: Type of command (e.g., "draw_rectangle", "create_layer")
        tool_name: Name of the MCP tool (e.g., "illustrator_draw_rectangle")
        params: Parameters passed to the tool (for debugging, not execution)
        request_id: Optional request ID for tracing (auto-generated if not provided)

    Returns:
        Dictionary with 'result' or 'error' key
    """
    # Generate request_id if not provided
    req_id = request_id or generate_request_id()
    
    # We check connection inside _execute_via_bridge, but we want to log unique warnings here
    # So we might duplicate the check or let the helper assume connected?
    # Let's check here for the Logging Aspect
    bridge = _get_bridge()
    if not bridge.is_connected():
        logger.warning(f"[{req_id}] {command_type}: DISCONNECTED")
        error_response = create_connection_error(config.ws_port, command_type)
        error_response["request_id"] = req_id
        return error_response

    start_time = time.time()
    logger.info(f"[{req_id}] {command_type}: starting")
    
    # Execute via centralized helper
    # We pass config.timeout or custom? usage implies config.timeout usually
    response = await _execute_via_bridge(
        script=script,
        timeout=config.timeout,
        command_type=command_type,
        tool_name=tool_name,
        params=params,
        request_id=req_id
    )
    
    duration = time.time() - start_time
    
    # Log success/error with timing
    if response.get("error"):
        logger.warning(f"[{req_id}] {command_type}: error in {duration:.3f}s")
    else:
        logger.info(f"[{req_id}] {command_type}: completed in {duration:.3f}s")
    
    # Add request_id and elapsed_ms to response for tracing
    response["request_id"] = req_id
    response["elapsed_ms"] = duration * 1000 # Convert to milliseconds
    
    return response


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
