"""
Shared response parsing utilities.

Pure functions for JSON parsing and envelope unwrapping — used by both
proxy_client and response_classification without creating circular imports.
"""

import json
from typing import Any


def try_parse_json(value: Any) -> Any:
    """Attempt JSON parse, return original on failure."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def unwrap_result(result: Any, _depth: int = 0) -> Any:
    """
    Recursively unwrap nested success/result envelopes.

    Handles double-wrapped results like:
    {success: true, result: "{\"success\": true, \"result\": ...}"}

    Has a depth guard (max 10) to prevent infinite recursion on
    malformed responses with circular nesting.
    """
    if _depth > 10:
        return result

    if not isinstance(result, dict):
        return result

    # Error takes priority: stop unwrapping if this level has an error
    if result.get("error"):
        return result
    # Handle {success: false} without 'error' key (edge case, rare)
    if result.get("success") is False:
        return result

    # Unwrap success envelope
    if result.get("success") and "result" in result:
        inner = result["result"]
        # Parse if string, then recurse
        parsed = try_parse_json(inner) if isinstance(inner, str) else inner
        return unwrap_result(parsed, _depth + 1)

    return result
