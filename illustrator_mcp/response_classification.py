"""
Response classification module — single source of truth for interpreting
Illustrator bridge responses.

Separates "what happened?" (classification) from "how to display it?"
(formatting in format_response / format_envelope in proxy_client).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ClassifyOptions:
    """Tool-specific classification behavior.

    Frozen so the default singleton is safe to share.
    """
    treat_string_error_as_error: bool = True
    unwrap_success_envelope: bool = True
    allow_raw_string_result: bool = True


@dataclass
class ResponseClassification:
    """Result of classifying a bridge response.

    Attributes:
        ok: Whether the response represents success.
        result: Normalized result value (post-unwrap).
        error_message: Raw error message string if an error was detected.
        error_code: Error code if classified (e.g. "S005", "C001").
        is_connection_error: True if the error is connection-related.
        raw: Original response dict, preserved for debugging.
    """
    ok: bool
    result: Any = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    is_connection_error: bool = False
    raw: Any = None



from illustrator_mcp.errors import ERROR_PREFIXES as _ERROR_PREFIXES



def classify_response(
    response: dict,
    context: str = "",
    options: ClassifyOptions = ClassifyOptions(),
) -> ResponseClassification:
    """Classify a bridge response into success or error.

    This is the single source of truth for determining whether a response
    represents success or failure. Both format_response and format_envelope
    delegate to this function.

    The classification follows a priority chain:
      1. Top-level "error" key → error
      2. Parse/unwrap result
      3. Inner "error" key in unwrapped dict → error
      4. Inner "success": False → error
      5. String error prefix detection → error
      6. MCP_LIBS_NOT_READY sentinel → error (C1-3)
      7. Otherwise → success

    Args:
        response: Response dict from bridge execution.
        context: Optional operation context for error reporting.
        options: Tool-specific classification options.

    Returns:
        ResponseClassification with normalized result or error info.
    """
    # Lazy import to avoid circular dependency
    from illustrator_mcp.errors import classify_error, is_connection_error
    from illustrator_mcp.utils.response import try_parse_json, unwrap_result

    raw = response

    # 1. Top-level error key
    if response.get("error"):
        error_msg = response["error"]
        code_obj = classify_error(error_msg)
        return ResponseClassification(
            ok=False,
            error_message=error_msg,
            error_code=code_obj.value if code_obj else "E999",
            is_connection_error=is_connection_error(error_msg),
            raw=raw,
        )

    # 2. Get and unwrap result
    result = response.get("result", response)

    if isinstance(result, str):
        result = try_parse_json(result)

    if options.unwrap_success_envelope:
        result = unwrap_result(result)

    # 3. Error key in unwrapped dict
    if isinstance(result, dict):
        if result.get("error"):
            error_msg = str(result["error"])
            code_obj = classify_error(error_msg)
            return ResponseClassification(
                ok=False,
                error_message=error_msg,
                error_code=code_obj.value if code_obj else "E999",
                raw=raw,
            )
        # 4. success: False envelope
        if result.get("success") is False:
            error_msg = str(result.get("error", "Operation failed"))
            code_obj = classify_error(error_msg)
            return ResponseClassification(
                ok=False,
                error_message=error_msg,
                error_code=code_obj.value if code_obj else "E999",
                raw=raw,
            )
        # 4b. Batch report with explicit ok: false (no singular 'error' key)
        if result.get("ok") is False:
            errors = result.get("errors") or []
            stats = result.get("stats") or {}
            if errors:
                parts = []
                for e in errors[:3]:
                    parts.append(
                        str(e.get("error", e)) if isinstance(e, dict) else str(e)
                    )
                error_msg = "; ".join(parts)
            elif stats.get("failed", 0) > 0:
                error_msg = (
                    f"Batch: {stats['failed']}/{stats.get('total', '?')} ops failed"
                )
            else:
                error_msg = "Batch reported ok:false with no error details"
            code_obj = classify_error(error_msg)
            return ResponseClassification(
                ok=False,
                error_message=error_msg,
                error_code=code_obj.value if code_obj else "BATCH_FAILURE",
                raw=raw,
            )

    # 5. MCP_LIBS_NOT_READY sentinel (C1-3) — must check before generic prefix
    if isinstance(result, str) and result.startswith("MCP_LIBS_NOT_READY:"):
        return ResponseClassification(
            ok=False,
            error_message=result,
            error_code="MCP_LIBS_NOT_READY",
            raw=raw,
        )

    # 6. String error prefix detection (skip JSON payloads)
    if (
        options.treat_string_error_as_error
        and isinstance(result, str)
        and not result.lstrip().startswith(("{", "["))
    ):
        code_obj = classify_error(result)
        if result.startswith(_ERROR_PREFIXES) or code_obj is not None:
            return ResponseClassification(
                ok=False,
                error_message=result,
                error_code=code_obj.value if code_obj else "E999",
                raw=raw,
            )

    # 7. Success
    return ResponseClassification(
        ok=True,
        result=result,
        raw=raw,
    )
