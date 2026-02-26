"""
Path utilities for Illustrator MCP.

Helpers for escaping and normalizing file paths for ExtendScript consumption.
"""

import json


def escape_path_for_jsx(path: str) -> str:
    """Escape a file path for safe inclusion inside a DOUBLE-QUOTED JS string literal.

    Uses ``json.dumps`` internally, which correctly handles:
    - Backslashes (``\\`` → ``\\\\``)
    - Double quotes (``"`` → ``\\"``)
    - Control characters (``\\n``, ``\\r``, ``\\t``, etc.)
    - Unicode line separators (U+2028, U+2029)

    **Contract**: The returned value must be placed inside ``"..."``
    (double-quoted) JS/ExtendScript string literals.  Do NOT use with
    single-quoted or backtick-delimited strings.

    Args:
        path: File path to escape.

    Returns:
        Escaped path safe for double-quoted ExtendScript string literals.

    Example:
        >>> escape_path_for_jsx('C:\\\\Users\\\\file.ai')
        'C:\\\\\\\\Users\\\\\\\\file.ai'
        >>> escape_path_for_jsx('C:\\\\Users\\\\"evil\\\\path')
        'C:\\\\\\\\Users\\\\\\\\\\\\"evil\\\\\\\\path'
    """
    return json.dumps(path)[1:-1]
