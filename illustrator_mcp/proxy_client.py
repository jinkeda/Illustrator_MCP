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
            return create_connection_error(config.ws_port)

        try:
            # Direct async call via thread-safe future wrapping
            # This avoids the double-wrap of run_in_executor -> blocking wait
            conc_future = asyncio.run_coroutine_threadsafe(
                bridge.execute_script_async(script, timeout=config.timeout),
                bridge.loop
            )
            return await asyncio.wrap_future(conc_future)
            
        except TimeoutError:
            return {"error": f"TIMEOUT: Script execution timed out after {config.timeout}s"}
        except Exception as e:
            logger.error(f"PROXY_ERROR: {e}")
            return {"error": f"PROXY_ERROR: {str(e)}"}

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

    IMPORTANT: The WebSocket bridge runs in a SEPARATE THREAD with its own
    event loop. We must use run_in_executor to call the bridge's synchronous
    execute_script method.

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
    
    bridge = _get_bridge()

    if not bridge.is_connected():
        logger.warning(f"[{req_id}] {command_type}: DISCONNECTED")
        error_response = create_connection_error(config.ws_port, command_type)
        error_response["request_id"] = req_id
        return error_response

    start_time = time.time()
    logger.info(f"[{req_id}] {command_type}: starting")
    
    try:
        # Direct async call via thread-safe future wrapping
        conc_future = asyncio.run_coroutine_threadsafe(
            bridge.execute_script_async(
                script=script,
                timeout=config.timeout,
                command_type=command_type,
                tool_name=tool_name,
                params=params
            ),
            bridge.loop
        )
        response = await asyncio.wrap_future(conc_future)
        
        duration = time.time() - start_time
        
        # Log success with timing
        if response.get("error"):
            logger.warning(f"[{req_id}] {command_type}: error in {duration:.3f}s")
        else:
            logger.info(f"[{req_id}] {command_type}: completed in {duration:.3f}s")
        
        # Add request_id and elapsed_ms to response for tracing
        response["request_id"] = req_id
        response["elapsed_ms"] = duration * 1000 # Convert to milliseconds
        
        return response

    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.error(f"[{req_id}] {command_type}: exception in {elapsed_ms:.0f}ms - {e}")
        return {
            "error": f"UNEXPECTED_ERROR [{command_type}]: {str(e)}",
            "request_id": req_id,
            "elapsed_ms": elapsed_ms
        }


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
