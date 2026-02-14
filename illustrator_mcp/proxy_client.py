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
from typing import Any, Dict, List, Optional

from illustrator_mcp.config import config
from illustrator_mcp.types import CommandMetadata, ExecutionResponse
from illustrator_mcp.connection_helpers import check_connection_or_error
from illustrator_mcp.errors import ErrorCode, format_code
from illustrator_mcp.log_config import log_command
from illustrator_mcp.logging import log_request as log_request_to_file
from illustrator_mcp.utils.chunking import (
    ChunkConfig,
    chunk_ops,
    merge_chunk_results,
    should_chunk,
    estimate_chunk_count,
)

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
    
    Uses 3-tier error handling:
    - Tier 1 (Connection): C001-C003 codes - Check CEP panel connection
    - Tier 2 (Timeout): Operation took too long - May need to simplify script
    - Tier 3 (Runtime): R001-R008 codes - Script execution errors
    
    Handles:
    - Connection checking (via shared helper)
    - Thread-safe bridging (run_coroutine_threadsafe)
    - Timeout management
    - Error tier separation
    
    Args:
        script: JavaScript code to execute
        timeout: Execution timeout in seconds
        command: Optional CommandMetadata for context
        trace_id: Optional trace ID for request tracing
        
    Returns:
        ExecutionResponse dictionary with result/error
    """
    context = command.command_type if command else "execute_script"
    
    # ===== TIER 1: Connection Check =====
    # Uses health-check to detect stale connections
    is_connected, error_response = check_connection_or_error(
        _get_bridge,
        config.ws_port, 
        context,
        health_check=False  # Skip health-check here, done at higher level
    )
    if not is_connected:
        # Connection errors: C001 (disconnected), C002 (refused), C003 (timeout on connect)
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
        # ===== TIER 2: Script Execution Timeout =====
        return {
            "error": format_code(ErrorCode.R_TIMEOUT,
                f"Script execution timed out after {timeout}s. "
                "Consider breaking into smaller operations or increasing timeout.")
        }
    except ConnectionError as e:
        # ===== TIER 1: Connection Lost During Execution =====
        # C_DISCONNECTED covers: not connected, dropped, network reset
        logger.warning(format_code(ErrorCode.C_DISCONNECTED, f"Connection lost [{context}]: {e}"))
        return {
            "error": format_code(ErrorCode.C_DISCONNECTED,
                f"Connection lost during execution: {str(e)}. "
                "The CEP panel may have disconnected. Try reconnecting.")
        }
    except json.JSONDecodeError as e:
        # ===== TIER 3: Protocol Error =====
        logger.error(format_code(ErrorCode.C_PROTOCOL, f"Invalid JSON [{context}]: {e}"))
        return {
            "error": format_code(ErrorCode.C_PROTOCOL,
                f"Invalid response from Illustrator: {str(e)}. "
                "Check CEP panel logs at http://localhost:8088")
        }
    except Exception as e:
        # ===== TIER 3: Unexpected Runtime Error =====
        logger.exception(format_code(ErrorCode.R_UNKNOWN, f"Unexpected error [{context}]"))
        return {
            "error": format_code(ErrorCode.R_UNKNOWN,
                f"Unexpected error: {str(e)}. See server logs for details.")
        }


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
    tool_name: Optional[str] = None,
    params: Optional[dict] = None,
    trace_id: Optional[str] = None,
    timeout: Optional[float] = None,
    includes: Optional[List[str]] = None
) -> ExecutionResponse:
    """
    Execute a JavaScript script with command context for hybrid protocol.

    This is the single point of library injection. Tools declare intent via
    ``includes=["geometry", ...]`` and this function handles resolution,
    injection, metadata, and logging.
    
    Delegates to _execute_via_bridge for actual execution.

    Args:
        script: JavaScript/ExtendScript code to execute
        command_type: Type of command (e.g., "draw_rectangle", "create_layer")
        tool_name: Name of the MCP tool (e.g., "illustrator_draw_rectangle")
        params: Parameters passed to the tool (for debugging, not execution)
        trace_id: Optional trace ID for tracing (auto-generated if not provided)
        timeout: Optional timeout override
        includes: Optional list of library names to inject (e.g., ["geometry"])

    Returns:
        ExecutionResponse with 'result' or 'error' key
    """
    from illustrator_mcp.libraries import (
        inject_libraries, get_injection_metadata, INJECTION_SENTINEL
    )

    # Generate trace_id if not provided
    tid = trace_id or generate_trace_id()
    
    # Build CommandMetadata
    command = CommandMetadata(
        command_type=command_type,
        tool_name=tool_name,
        params=params or {},
        trace_id=tid
    )
    
    # --- Library injection (centralized) ---
    injection_meta = None
    if includes:
        # Sentinel guard: detect already-injected scripts
        if INJECTION_SENTINEL in script:
            logger.warning(
                f"[{tid}] Script already contains injection sentinel — "
                f"skipping double injection (includes={includes})"
            )
        else:
            try:
                script = inject_libraries(script, includes)
                injection_meta = get_injection_metadata(includes)
            except ValueError as e:
                err_msg = str(e)
                # Refined error classification
                if "Unknown library" in err_msg or "not found" in err_msg.lower():
                    code = ErrorCode.V_LIBRARY_NOT_FOUND
                elif "collision" in err_msg.lower() or "conflict" in err_msg.lower():
                    code = ErrorCode.V_LIBRARY_CONFLICT
                else:
                    code = ErrorCode.V_LIBRARY_NOT_FOUND  # default for ValueError
                logger.error(f"[{tid}] Library injection failed: {err_msg}")
                return {
                    "ok": False,
                    "error": format_code(code, err_msg),
                    "trace_id": tid,
                }
            except (OSError, json.JSONDecodeError) as e:
                err_msg = str(e)
                if isinstance(e, json.JSONDecodeError):
                    code = ErrorCode.S_MANIFEST_ERROR
                else:
                    code = ErrorCode.S_LIBRARY_IO
                logger.error(f"[{tid}] Library system error: {err_msg}")
                return {
                    "ok": False,
                    "error": format_code(code, err_msg),
                    "trace_id": tid,
                }
            except Exception as e:
                err_msg = str(e)
                logger.error(f"[{tid}] Unexpected injection failure: {err_msg}")
                return {
                    "ok": False,
                    "error": format_code(ErrorCode.R_INJECTION_FAILED, err_msg),
                    "trace_id": tid,
                }
    
    # Note: Connection check is done in _execute_via_bridge, avoiding duplication
    start_time = time.time()
    log_command(logger, tid, command_type, "starting")
    
    # Execute via centralized helper
    response = await _execute_via_bridge(
        script=script,
        timeout=timeout or config.timeout,
        command=command,
        trace_id=tid
    )
    
    duration_ms = (time.time() - start_time) * 1000
    
    # Log success/error with timing
    if response.get("error"):
        log_command(logger, tid, command_type, "error", duration_ms, logging.WARNING)
    else:
        log_command(logger, tid, command_type, "completed", duration_ms)
    
    # Log to persistent file (for debugging/replay)
    try:
        log_request_to_file(
            trace_id=tid,
            script=script,
            includes=includes,
            result=response,
            duration_ms=duration_ms
        )
    except Exception as e:
        logger.debug(f"Request logging failed: {e}")
    
    # Add trace_id and elapsed_ms to response for tracing
    response["trace_id"] = tid
    response["elapsed_ms"] = duration_ms
    
    # Attach normalized injection metadata
    if injection_meta:
        response["injection"] = {
            "includes_requested": injection_meta.get("includes_requested", []),
            "includes_resolved": injection_meta.get("includes_resolved", []),
            "prelude_hash": injection_meta.get("prelude_hash", ""),
            "prelude_length": injection_meta.get("prelude_length", 0),
            "library_versions": injection_meta.get("library_versions", {}),
            "manifest_version": injection_meta.get("manifest_version", ""),
        }
    
    return response



async def execute_op_batch_chunked(
    ops: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    chunk_config: Optional[ChunkConfig] = None,
    timeout: Optional[float] = None
) -> ExecutionResponse:
    """
    Execute an operation batch with automatic chunking for large batches.
    
    If the batch is small enough, executes directly.
    If chunking is needed, splits the batch and merges results.
    
    Args:
        ops: List of SOC operations
        options: executeOpBatch options (strict, trace, rollback, etc.)
        chunk_config: Chunking configuration
        timeout: Per-chunk execution timeout
        
    Returns:
        Merged ExecutionResponse with aggregated stats
    """
    chunk_config = chunk_config or ChunkConfig()
    options = options or {}
    timeout = timeout or config.timeout
    
    # If chunking not needed, execute directly
    if not should_chunk(ops, chunk_config):
        script = f"executeOpBatch({json.dumps(ops)}, {json.dumps(options)})"
        return await execute_script_with_context(
            script=script,
            command_type="op_batch",
            params={"op_count": len(ops)},
            timeout=timeout
        )
    
    # Execute in chunks
    chunk_count = estimate_chunk_count(ops, chunk_config)
    logger.info(f"Chunking {len(ops)} ops into {chunk_count} chunks")
    
    results = []
    created_ids = []
    
    for i, chunk in enumerate(chunk_ops(ops, chunk_config)):
        # Add summaryOnly to reduce response size
        chunk_options = {**options, "summaryOnly": chunk_config.use_summary_only}
        
        script = f"executeOpBatch({json.dumps(chunk)}, {json.dumps(chunk_options)})"
        trace_id = f"chunk_{i+1}_{chunk_count}"
        
        response = await execute_script_with_context(
            script=script,
            command_type="op_batch_chunk",
            params={"chunk": i + 1, "total": chunk_count, "ops": len(chunk)},
            trace_id=trace_id,
            timeout=timeout
        )
        
        if response.get("error"):
            # Chunk failed - return error or continue based on strict mode
            if chunk_config.strict:
                return {
                    "ok": False,
                    "error": f"Chunk {i+1}/{chunk_count} failed: {response['error']}",
                    "chunks_completed": i,
                    "createdIds": created_ids
                }
            results.append({"ok": False, "error": response["error"]})
            continue
        
        # Parse result and accumulate created IDs
        result = _unwrap_result(response.get("result", response))
        if isinstance(result, dict):
            results.append(result)
            created_ids.extend(result.get("createdIds", []))
        
        # Stop on first failure in strict mode
        if chunk_config.strict and isinstance(result, dict) and not result.get("ok", True):
            return merge_chunk_results(results, created_ids)
    
    return merge_chunk_results(results, created_ids)


def _try_parse_json(value: Any) -> Any:
    """Attempt JSON parse, return original on failure."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _unwrap_result(result: Any) -> Any:
    """
    Recursively unwrap nested success/result envelopes.

    Handles double-wrapped results like:
    {success: true, result: "{\"success\": true, \"result\": ...}"}
    """
    if not isinstance(result, dict):
        return result

    # Check for error in current level
    if result.get("error"):
        return result
    if result.get("success") is False:
        return result

    # Unwrap success envelope
    if result.get("success") and "result" in result:
        inner = result["result"]
        # Parse if string, then recurse
        parsed = _try_parse_json(inner) if isinstance(inner, str) else inner
        return _unwrap_result(parsed)

    return result


def format_response(response: dict[str, Any], context: str = "") -> str:
    """
    Format the response from Illustrator for MCP output.

    Uses structured error handling with suggestions for better developer experience.

    Args:
        response: Response dictionary from execute_script
        context: Optional context about the operation for better error messages

    Returns:
        Formatted string for MCP tool response
    """
    from illustrator_mcp.errors import (
        format_error_response,
        is_connection_error,
        classify_error,
    )

    # Handle top-level errors with structured formatting
    if response.get("error"):
        error = response['error']

        # Make connection errors very prominent
        if is_connection_error(error):
            formatted = format_error_response(error, context)
            return f"⚠️ {formatted}\n\n[STOP: Do not retry until connection is restored]"

        # Format other errors with suggestions
        return format_error_response(error, context)

    # Get and unwrap result
    result = response.get("result", response)

    # Parse string results
    if isinstance(result, str):
        result = _try_parse_json(result)

    # Unwrap nested envelopes
    result = _unwrap_result(result)

    # Check for errors in unwrapped result
    if isinstance(result, dict):
        if result.get("error"):
            return format_error_response(result['error'], context)
        if result.get("success") is False:
            error_msg = result.get('error', 'Operation failed')
            return format_error_response(error_msg, context)

    # Check for error patterns in string results (skip JSON payloads)
    if isinstance(result, str) and not result.lstrip().startswith(("{", "[")):
        # Detect common error patterns in plain-text result strings
        error_prefixes = ("Error:", "error:", "ERROR:", "ReferenceError:", "TypeError:", "SyntaxError:")
        if result.startswith(error_prefixes) or classify_error(result) is not None:
            return format_error_response(result, context)

    # Format output
    if isinstance(result, (dict, list)):
        return json.dumps(result, indent=2)
    return str(result)


def format_envelope(
    response: Dict[str, Any],
    context: str = "",
    warnings: Optional[List[str]] = None,
    diagnostics: Optional[Dict[str, Any]] = None
) -> str:
    """
    Format response as standardized JSON envelope. ALL tools should use this.

    Returns a JSON string with consistent structure:
    {
        "ok": true/false,
        "warnings": [...],
        "error": null or {code, message, suggestions},
        "diagnostics": {...},
        "result": ...
    }

    Args:
        response: Response dictionary from execute_script_with_context
        context: Optional context for error messages
        warnings: List of warning messages
        diagnostics: Dictionary of diagnostic info (includes, bounds_type, etc.)

    Returns:
        JSON string with standardized envelope
    """
    from illustrator_mcp.errors import create_structured_error, classify_error

    warnings = warnings or []
    diagnostics = diagnostics or {}

    # Add trace info to diagnostics if present in response
    if response.get("trace_id"):
        diagnostics["trace_id"] = response["trace_id"]
    if response.get("elapsed_ms"):
        diagnostics["elapsed_ms"] = response["elapsed_ms"]

    # Handle errors
    if response.get("error"):
        error_msg = response["error"]
        structured = create_structured_error(error_msg, context)
        return json.dumps({
            "ok": False,
            "warnings": warnings,
            "error": {
                "code": structured.code,
                "message": structured.message,
                "suggestions": structured.suggestions
            },
            "diagnostics": diagnostics,
            "result": None
        })

    # Get and unwrap result
    result = response.get("result", response)

    # Parse string results
    if isinstance(result, str):
        result = _try_parse_json(result)

    # Unwrap nested envelopes
    result = _unwrap_result(result)

    # Check for errors in unwrapped result
    if isinstance(result, dict):
        if result.get("error"):
            structured = create_structured_error(str(result["error"]), context)
            return json.dumps({
                "ok": False,
                "warnings": warnings,
                "error": {
                    "code": structured.code,
                    "message": structured.message,
                    "suggestions": structured.suggestions
                },
                "diagnostics": diagnostics,
                "result": None
            })
        if result.get("success") is False:
            error_msg = result.get("error", "Operation failed")
            structured = create_structured_error(str(error_msg), context)
            return json.dumps({
                "ok": False,
                "warnings": warnings,
                "error": {
                    "code": structured.code,
                    "message": structured.message,
                    "suggestions": structured.suggestions
                },
                "diagnostics": diagnostics,
                "result": None
            })

    # Check for error patterns in string results (skip JSON payloads)
    if isinstance(result, str) and not result.lstrip().startswith(("{", "[")):
        error_prefixes = ("Error:", "error:", "ERROR:", "ReferenceError:", "TypeError:", "SyntaxError:")
        if result.startswith(error_prefixes) or classify_error(result) is not None:
            structured = create_structured_error(result, context)
            return json.dumps({
                "ok": False,
                "warnings": warnings,
                "error": {
                    "code": structured.code,
                    "message": structured.message,
                    "suggestions": structured.suggestions
                },
                "diagnostics": diagnostics,
                "result": None
            })

    # Success case
    return json.dumps({
        "ok": True,
        "warnings": warnings,
        "error": None,
        "diagnostics": diagnostics,
        "result": result
    })

