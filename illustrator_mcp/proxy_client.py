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
from illustrator_mcp.shared import (
    CommandMetadata, 
    ExecutionResponse, 
    check_connection_or_error,
    create_connection_error
)
from illustrator_mcp.errors import IllustratorError

# Configure logging
logger = logging.getLogger(__name__)


# ==================== Request ID Generation ====================

def generate_trace_id() -> str:
    """Generate a unique trace ID for request tracing.
    
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

    async def execute_script(self, script: str) -> ExecutionResponse:
        """
        Execute a JavaScript/ExtendScript in Illustrator.

        This is the core method that all tools use internally.
        Uses the integrated WebSocket bridge via the centralized helper.

        Args:
            script: JavaScript code to execute in Illustrator

        Returns:
            Response from Illustrator containing result or error
        """
        return await _execute_via_bridge(script=script, timeout=self.timeout)

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
    command: Optional[CommandMetadata] = None,
    trace_id: Optional[str] = None
) -> ExecutionResponse:
    """
    Centralized helper to execute scripts via the WebSocket bridge.
    
    Handles:
    - Connection checking (via shared helper)
    - Thread-safe bridging (run_coroutine_threadsafe)
    - Timeout management
    - Error handling
    
    Args:
        script: JavaScript code to execute
        timeout: Execution timeout in seconds
        command: Optional CommandMetadata for context
        trace_id: Optional trace ID for request tracing
        
    Returns:
        ExecutionResponse dictionary with result/error
    """
    context = command.command_type if command else "execute_script"
    
    # Use centralized connection check
    is_connected, error_response = check_connection_or_error(config.ws_port, context)
    if not is_connected:
        return error_response

    bridge = _get_bridge()
    
    try:
        # Direct async call via thread-safe future wrapping
        conc_future = asyncio.run_coroutine_threadsafe(
            bridge.execute_script_async(
                script=script,
                timeout=timeout,
                command=command,
                trace_id=trace_id
            ),
            bridge.loop
        )
        return await asyncio.wrap_future(conc_future)
        
    except TimeoutError:
        return {"error": f"TIMEOUT: Script execution timed out after {timeout}s"}
    except ConnectionError as e:
        logger.warning(f"CONNECTION_ERROR [{context}]: {e}")
        return {"error": f"CONNECTION_ERROR: {str(e)}"}
    except Exception as e:
        logger.exception(f"PROXY_ERROR [{context}]: Unexpected error")
        return {"error": f"PROXY_ERROR: {str(e)}"}


async def execute_script(script: str) -> ExecutionResponse:
    """
    Execute a JavaScript script in Illustrator.

    This is the core function that all specific tools use internally.

    Args:
        script: JavaScript/ExtendScript code to execute

    Returns:
        ExecutionResponse with 'result' or 'error' key
    """
    return await get_proxy().execute_script(script)


async def execute_script_with_context(
    script: str,
    command_type: str,
    tool_name: str = None,
    params: dict = None,
    trace_id: str = None
) -> ExecutionResponse:
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
        trace_id: Optional trace ID for tracing (auto-generated if not provided)

    Returns:
        ExecutionResponse with 'result' or 'error' key
    """
    # Generate trace_id if not provided
    tid = trace_id or generate_trace_id()
    
    # Build CommandMetadata
    command = CommandMetadata(
        command_type=command_type,
        tool_name=tool_name,
        params=params or {},
        trace_id=tid
    )
    
    # Use centralized connection check
    is_connected, error_response = check_connection_or_error(config.ws_port, command_type)
    if not is_connected:
        logger.warning(f"[{tid}] {command_type}: DISCONNECTED")
        error_response["trace_id"] = tid
        return error_response

    start_time = time.time()
    logger.info(f"[{tid}] {command_type}: starting")
    
    # Execute via centralized helper
    response = await _execute_via_bridge(
        script=script,
        timeout=config.timeout,
        command=command,
        trace_id=tid
    )
    
    duration = time.time() - start_time
    
    # Log success/error with timing
    if response.get("error"):
        logger.warning(f"[{tid}] {command_type}: error in {duration:.3f}s")
    else:
        logger.info(f"[{tid}] {command_type}: completed in {duration:.3f}s")
    
    # Add trace_id and elapsed_ms to response for tracing
    response["trace_id"] = tid
    response["elapsed_ms"] = duration * 1000
    
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
