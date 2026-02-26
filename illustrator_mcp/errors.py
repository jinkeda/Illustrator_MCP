"""
Unified error codes and structured error handling for Illustrator MCP.

Single source of truth for all error classification. Every error-emitting
module imports from here — no duplicate enums allowed.

Taxonomy (non-overlapping):
- C_*  Connection/Transport — WebSocket, CEP panel, protocol issues
- V_*  Validation — fail before execution
- R_*  Runtime — fail during execution  
- S_*  Script/System — ExtendScript engine failures AND host environment errors
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# Error prefixes recognized in plain-text result strings (single source of truth).
# Imported by response_classification.py and proxy_client.py.
ERROR_PREFIXES = (
    "Error:", "error:", "ERROR:",
    "ReferenceError:", "TypeError:", "SyntaxError:",
)


# =============================================================================
# ERROR CODE ENUM — SINGLE SOURCE OF TRUTH
# =============================================================================

class ErrorCode(str, Enum):
    """
    Unified error codes for all Illustrator MCP operations.

    **Single source of truth** — contracts.py imports from here;
    contracts.jsx is generated from this enum.

    Naming / padding conventions:
    - C_xxx  (3-digit): Connection/transport errors
    - V_xxx  (3-digit): Validation errors (fail before execution)
    - R_xxx  (3-digit): Runtime errors (fail during execution)
    - S_xxx  (3-digit): Script/system errors (ExtendScript engine + host)
    - E_xxx  (3-digit): Execution infrastructure errors
    - G_xxx  (3-digit): Guard / conditional op errors
    - SP_xxx (3-digit): Spatial target errors

    Codes are append-only and immutable — never reuse a retired value.
    """
    # === CONNECTION / TRANSPORT (C001–C004) ===
    # Covers all communication-layer failures.
    # C_DISCONNECTED covers: not connected, connection dropped, network reset.
    C_DISCONNECTED = "C001"
    C_TIMEOUT = "C002"           # Transport-layer timeout (send/receive)
    C_BRIDGE_ERROR = "C003"      # Internal bridge error
    C_PROTOCOL = "C004"          # Valid JSON but violates envelope/contract shape
    C_JSON_PARSE = "C005"        # Payload is not valid JSON / parse failure

    # === CONNECTION / COMPOUND OPS (C006–C009) ===
    # SOC compound operation errors (renumbered from legacy C001–C004).
    C_NESTING_NOT_ALLOWED = "C006"
    C_PREV_UNAVAILABLE = "C007"
    C_INVALID_TOKEN_POSITION = "C008"
    C_UNKNOWN_TOKEN = "C009"

    # === VALIDATION (V) — fail before execution ===
    V_NO_DOCUMENT = "V001"
    V_NO_SELECTION = "V002"
    V_INVALID_PAYLOAD = "V003"
    V_INVALID_TARGETS = "V004"
    V_UNKNOWN_TARGET_TYPE = "V005"
    V_MISSING_REQUIRED_PARAM = "V006"
    V_INVALID_PARAM_TYPE = "V007"
    V_SCHEMA_MISMATCH = "V008"
    V_LIBRARY_NOT_FOUND = "V009"
    V_LIBRARY_CONFLICT = "V010"
    V_INVALID_PARAM_VALUE = "V011"  # Parameter value out of range / invalid

    # === RUNTIME (R) — fail during execution ===
    R_COLLECT_FAILED = "R001"
    R_COMPUTE_FAILED = "R002"
    R_APPLY_FAILED = "R003"
    R_ITEM_OPERATION_FAILED = "R004"
    R_TIMEOUT = "R005"           # Script execution timeout
    R_OUT_OF_BOUNDS = "R006"
    R_LAYER_NOT_FOUND = "R007"
    R_ELEMENT_NOT_FOUND = "R008"
    R_UNKNOWN = "R009"           # Catch-all for unexpected runtime errors
    R_INJECTION_FAILED = "R010"  # Library injection failed (catch-all)
    R_BUSY = "R011"              # Panel busy — previous script still executing
    R_QUERY_FAILED = "R012"      # Query tool execution failed
    R_PREFLIGHT_FAILED = "R013"  # Preflight check execution failed

    # === EXECUTION INFRASTRUCTURE (E) ===
    E_EXECUTION = "E001"         # Generic execution infrastructure error

    # === SCRIPT / SYSTEM (S) ===
    # Covers both ExtendScript engine failures (syntax, reference, type errors)
    # and host environment issues (app crashes, I/O, memory).
    S_APP_ERROR = "S001"
    S_SCRIPT_ERROR = "S002"
    S_IO_ERROR = "S003"
    S_MEMORY_ERROR = "S004"
    S_SYNTAX_ERROR = "S005"
    S_REFERENCE_ERROR = "S006"
    S_TYPE_ERROR = "S007"
    S_RANGE_ERROR = "S008"
    S_PERMISSION_DENIED = "S009"
    S_LIBRARY_IO = "S010"        # Library file I/O failure
    S_MANIFEST_ERROR = "S011"    # Manifest parse/load failure

    # === GUARD (G) — conditional op guard errors ===
    G_UNKNOWN_PROPERTY = "G001"
    G_INVALID_COMPARATOR = "G002"
    G_MALFORMED = "G003"

    # === SPATIAL (SP) — spatial target errors ===
    SP_MISSING_PREDICATE = "SP001"
    SP_INVALID_RECT = "SP002"
    SP_REF_NOT_FOUND = "SP003"

    # === SVG IMPORT (SVG) — svgd.py safety-limit violations ===
    SVG_D_TOO_LONG = "SVG001"         # d attribute exceeds MAX_D_LENGTH
    SVG_TOO_MANY_SEGMENTS = "SVG002"  # Total segments exceed MAX_SEGMENTS
    SVG_TOO_MANY_SUBPATHS = "SVG003" # Subpath count exceeds MAX_SUBPATHS
    SVG_COORD_OVERFLOW = "SVG004"     # Coordinate exceeds ±MAX_COORD_ABS
    SVG_TOO_MANY_TOKENS = "SVG005"   # Tokenizer output exceeds MAX_TOKENS


# =============================================================================
# LEGACY CODE MAP — ad-hoc string identifiers → canonical codes
# =============================================================================

LEGACY_CODE_MAP: Dict[str, str] = {
    "QUERY_ERROR": ErrorCode.R_QUERY_FAILED.value,
    "JSON_PARSE_ERROR": ErrorCode.C_JSON_PARSE.value,
    "PREFLIGHT_ERROR": ErrorCode.R_PREFLIGHT_FAILED.value,
    "LIB_NOT_LOADED": ErrorCode.E_EXECUTION.value,
    "MCP_LIBS_NOT_READY": ErrorCode.E_EXECUTION.value,
}


# =============================================================================
# FORMATTING HELPER
# =============================================================================

def format_code(code: ErrorCode, message: str) -> str:
    """
    Format an error code with a message string.

    Produces: ``[C001] CEP panel is not connected...``

    This is the single formatting entry point. All error-emitting code
    must use this instead of f-string interpolation.
    """
    return f"[{code.value}] {message}"


# =============================================================================
# ERROR SUGGESTIONS DATABASE
# =============================================================================

ERROR_SUGGESTIONS: Dict[str, Dict[str, Any]] = {
    # Connection errors
    ErrorCode.C_DISCONNECTED.value: {
        "message": "Illustrator is not connected",
        "recoverable": True,
        "suggestions": [
            "Ensure Adobe Illustrator is running",
            "Check that the CEP panel (IllustratorMCP) is loaded",
            "Open Window > Extensions > IllustratorMCP in Illustrator",
            "Verify the WebSocket connection on port 8081",
        ],
    },
    ErrorCode.C_TIMEOUT.value: {
        "message": "Transport timeout",
        "recoverable": True,
        "suggestions": [
            "Check if Illustrator is responding (not frozen)",
            "Verify the WebSocket connection is alive",
            "Restart the CEP panel if connection seems stuck",
        ],
    },
    ErrorCode.C_PROTOCOL.value: {
        "message": "Malformed response from Illustrator",
        "recoverable": False,
        "suggestions": [
            "Check CEP panel logs at http://localhost:8088",
            "Verify CEP panel version matches MCP server version",
            "Restart Illustrator and reconnect",
        ],
    },

    # Validation errors
    ErrorCode.V_NO_DOCUMENT.value: {
        "message": "No document is open",
        "recoverable": True,
        "suggestions": [
            "Create a new document with illustrator_create_document",
            "Open an existing document with illustrator_open_document",
        ],
    },
    ErrorCode.V_NO_SELECTION.value: {
        "message": "No items are selected",
        "recoverable": True,
        "suggestions": [
            "Select items in Illustrator before running this operation",
            "Use targets: {type: 'layer', layer: 'Layer 1'} instead of selection",
            "Use targets: {type: 'all'} to target all items",
        ],
    },
    ErrorCode.V_LIBRARY_NOT_FOUND.value: {
        "message": "Requested library not found",
        "recoverable": False,
        "suggestions": [
            "Check library name spelling (available: polyfills, contracts, targets, task_pipeline, geometry)",
            "Ensure the library file exists in resources/scripts/",
        ],
    },
    ErrorCode.V_LIBRARY_CONFLICT.value: {
        "message": "Library symbol collision detected",
        "recoverable": False,
        "suggestions": [
            "Two requested libraries export the same symbol",
            "Remove one of the conflicting includes",
        ],
    },
    ErrorCode.S_LIBRARY_IO.value: {
        "message": "Library file I/O error",
        "recoverable": False,
        "suggestions": [
            "Ensure library files exist in resources/scripts/",
            "Check file permissions on the library directory",
        ],
    },
    ErrorCode.S_MANIFEST_ERROR.value: {
        "message": "Library manifest error",
        "recoverable": False,
        "suggestions": [
            "Check manifest.json in resources/scripts/ for syntax errors",
            "Ensure manifest version is compatible",
        ],
    },
    ErrorCode.R_INJECTION_FAILED.value: {
        "message": "Library injection failed",
        "recoverable": False,
        "suggestions": [
            "An unexpected error occurred during library injection",
            "Check server logs for details",
        ],
    },
    ErrorCode.R_BUSY.value: {
        "message": "Panel busy — previous script still executing",
        "recoverable": True,
        "suggestions": [
            "Wait for the current operation to finish before sending another",
            "Increase timeout if the operation is expected to take long",
            "Check server logs for panel health details",
        ],
    },

    # Runtime errors
    ErrorCode.R_TIMEOUT.value: {
        "message": "Script execution timed out",
        "recoverable": True,
        "suggestions": [
            "The script may be too complex - try breaking it into smaller operations",
            "Check if Illustrator is responding (not frozen)",
            "Increase timeout if processing large documents",
        ],
    },
    ErrorCode.R_LAYER_NOT_FOUND.value: {
        "message": "Layer not found",
        "recoverable": True,
        "suggestions": [
            "Check the layer name spelling (case-sensitive)",
            "Use illustrator_get_document_structure to see available layers",
            "Create the layer first if it doesn't exist",
        ],
    },
    ErrorCode.R_ELEMENT_NOT_FOUND.value: {
        "message": "Element not found",
        "recoverable": True,
        "suggestions": [
            "The item may have been deleted or renamed",
            "Use illustrator_get_document_structure to verify item exists",
            "Check item name spelling (case-sensitive)",
        ],
    },
    ErrorCode.R_UNKNOWN.value: {
        "message": "Unexpected runtime error",
        "recoverable": False,
        "suggestions": [
            "Check the error message for details",
            "See server logs for the full traceback",
            "Report the issue if it persists",
        ],
    },

    # Script/system errors
    ErrorCode.S_SCRIPT_ERROR.value: {
        "message": "Script evaluation error",
        "recoverable": False,
        "suggestions": [
            "Check JavaScript syntax in your script",
            "Verify all variables are defined before use",
            "Use illustrator_get_scripting_reference for correct API usage",
        ],
    },
    ErrorCode.S_SYNTAX_ERROR.value: {
        "message": "JavaScript syntax error",
        "recoverable": False,
        "suggestions": [
            "Check for missing brackets, parentheses, or semicolons",
            "Verify string quotes are properly closed",
            "Look for typos in keywords (var, function, if, etc.)",
        ],
    },
    ErrorCode.S_REFERENCE_ERROR.value: {
        "message": "Undefined variable or function",
        "recoverable": False,
        "suggestions": [
            "Check that all variables are declared with 'var'",
            "Verify function names are spelled correctly",
            "If using library functions, ensure includes: ['geometry'] is set",
        ],
    },
    ErrorCode.S_TYPE_ERROR.value: {
        "message": "Type error in script",
        "recoverable": False,
        "suggestions": [
            "Check that you're calling methods on the correct object type",
            "Verify the object exists before accessing its properties",
            "Use typeof checks for defensive programming",
        ],
    },
}

# --- New codes from SOC / query centralization ---
ERROR_SUGGESTIONS.update({
    ErrorCode.V_INVALID_PARAM_VALUE.value: {
        "message": "Invalid parameter value",
        "recoverable": True,
        "suggestions": [
            "Check that parameter values are within expected ranges",
            "Verify enum parameters use allowed values",
        ],
    },
    ErrorCode.C_JSON_PARSE.value: {
        "message": "JSON parse failure",
        "recoverable": False,
        "suggestions": [
            "The response payload is not valid JSON",
            "Check CEP panel logs for malformed output",
        ],
    },
    ErrorCode.C_NESTING_NOT_ALLOWED.value: {
        "message": "Compound op nesting not allowed",
        "recoverable": False,
        "suggestions": ["Flatten nested compound operations into a single batch"],
    },
    ErrorCode.E_EXECUTION.value: {
        "message": "Execution infrastructure error",
        "recoverable": True,
        "suggestions": [
            "The execution environment encountered an error",
            "Retry the operation or check server logs",
        ],
    },
    ErrorCode.R_QUERY_FAILED.value: {
        "message": "Query execution failed",
        "recoverable": True,
        "suggestions": [
            "Check query target selectors and parameters",
            "Verify the document is open and accessible",
        ],
    },
    ErrorCode.R_PREFLIGHT_FAILED.value: {
        "message": "Preflight check failed",
        "recoverable": True,
        "suggestions": [
            "An error occurred during preflight validation",
            "Check server logs for details",
        ],
    },
    # SVG import safety limits
    ErrorCode.SVG_D_TOO_LONG.value: {
        "message": "SVG path data too long",
        "recoverable": False,
        "suggestions": [
            "Simplify the SVG path or split into multiple import calls",
            f"Maximum d attribute length is 50,000 characters",
        ],
    },
    ErrorCode.SVG_TOO_MANY_SEGMENTS.value: {
        "message": "SVG path has too many segments",
        "recoverable": False,
        "suggestions": [
            "Simplify the path geometry or split into multiple paths",
            f"Maximum segment count is 5,000",
        ],
    },
    ErrorCode.SVG_TOO_MANY_SUBPATHS.value: {
        "message": "SVG path has too many subpaths",
        "recoverable": False,
        "suggestions": [
            "Split the SVG into multiple import calls",
            f"Maximum subpath count is 100",
        ],
    },
    ErrorCode.SVG_COORD_OVERFLOW.value: {
        "message": "SVG coordinate out of range",
        "recoverable": False,
        "suggestions": [
            "Scale down coordinates to within ±100,000",
            "Check for malformed path data with extreme values",
        ],
    },
    ErrorCode.SVG_TOO_MANY_TOKENS.value: {
        "message": "SVG path data too complex",
        "recoverable": False,
        "suggestions": [
            "Simplify the SVG path data",
            f"Maximum token count is 50,000",
        ],
    },
})


# =============================================================================
# STRUCTURED ERROR RESPONSE
# =============================================================================

@dataclass
class StructuredError:
    """
    Structured error response with context and suggestions.

    Matches the schema proposed in the improvement report.
    """
    code: str
    message: str
    recoverable: bool = True
    context: str = ""
    suggestions: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "recoverable": self.recoverable,
                "context": self.context,
                "suggestions": self.suggestions,
                "details": self.details if self.details else None,
            }
        }

    def format(self) -> str:
        """Format as human-readable error message."""
        lines = [f"Error [{self.code}]: {self.message}"]

        if self.context:
            lines.append(f"Context: {self.context}")

        if self.suggestions:
            lines.append("\nSuggestions:")
            for suggestion in self.suggestions:
                lines.append(f"  - {suggestion}")

        if not self.recoverable:
            lines.append("\n[!] This error requires code changes to fix.")

        return "\n".join(lines)


# =============================================================================
# ERROR DETECTION AND CLASSIFICATION
# =============================================================================

# Patterns for detecting error types from raw error messages.
# Matches both new format "[C001] ..." and legacy "DISCONNECTED ..." strings.
ERROR_PATTERNS = [
    # Connection errors (new bracketed format)
    (r"\[C001\]|DISCONNECTED|not connected|connection.*failed", ErrorCode.C_DISCONNECTED),
    (r"\[C002\]|transport.*timeout", ErrorCode.C_TIMEOUT),
    (r"\[C004\]|PROTOCOL_ERROR|Invalid JSON", ErrorCode.C_PROTOCOL),

    # Timeouts
    (r"\[R005\]|TIMEOUT|timed out", ErrorCode.R_TIMEOUT),

    # Validation errors
    (r"\[V001\]|No documents? open|No active document", ErrorCode.V_NO_DOCUMENT),
    (r"\[V002\]|No selection|Nothing selected|selection is empty", ErrorCode.V_NO_SELECTION),

    # Runtime errors
    (r"\[R007\]|Layer.*not found|no layer named", ErrorCode.R_LAYER_NOT_FOUND),
    (r"\[R008\]|No such element|Element not found|item not found", ErrorCode.R_ELEMENT_NOT_FOUND),
    (r"\[R009\]|Unexpected error", ErrorCode.R_UNKNOWN),

    # Script errors — includes ExtendScript-native messages (no class prefix)
    (r"\[S005\]|SyntaxError|syntax error|Unexpected token", ErrorCode.S_SYNTAX_ERROR),
    (r"\[S006\]|ReferenceError|is not defined|is undefined", ErrorCode.S_REFERENCE_ERROR),
    (r"\[S007\]|TypeError|is not a function|cannot read property|is not an object", ErrorCode.S_TYPE_ERROR),
    (r"RangeError|Invalid array length|out of range|stack overflow", ErrorCode.S_RANGE_ERROR),
    # ExtendScript bare syntax errors (no "SyntaxError:" prefix)
    (r"\bexpected\b|unterminated string", ErrorCode.S_SYNTAX_ERROR),

    # Library errors
    (r"\[V009\]|Library not found|library.*not found|Unknown library", ErrorCode.V_LIBRARY_NOT_FOUND),
    (r"\[V010\]|Symbol collision|symbol.*collision", ErrorCode.V_LIBRARY_CONFLICT),
    (r"\[S010\]|Library file.*I/O|library.*io error", ErrorCode.S_LIBRARY_IO),
    (r"\[S011\]|Manifest.*error|manifest.*parse", ErrorCode.S_MANIFEST_ERROR),
    (r"\[R010\]|injection failed", ErrorCode.R_INJECTION_FAILED),

    # SVG import safety limits
    (r"\[SVG001\]|E_D_TOO_LONG", ErrorCode.SVG_D_TOO_LONG),
    (r"\[SVG002\]|E_TOO_MANY_SEGMENTS", ErrorCode.SVG_TOO_MANY_SEGMENTS),
    (r"\[SVG003\]|E_TOO_MANY_SUBPATHS", ErrorCode.SVG_TOO_MANY_SUBPATHS),
    (r"\[SVG004\]|E_COORD_OVERFLOW", ErrorCode.SVG_COORD_OVERFLOW),
    (r"\[SVG005\]|E_TOO_MANY_TOKENS", ErrorCode.SVG_TOO_MANY_TOKENS),
]


def classify_error(error_message: str) -> Optional[ErrorCode]:
    """
    Classify an error message into an error code.

    Recognizes both new ``[C001] ...`` format and legacy string patterns.

    Args:
        error_message: Raw error message string

    Returns:
        ErrorCode if pattern matches, None otherwise
    """
    for pattern, code in ERROR_PATTERNS:
        if re.search(pattern, error_message, re.IGNORECASE):
            return code

    return None


def create_structured_error(
    error_message: str,
    context: str = "",
    code: Optional[ErrorCode] = None,
    details: Optional[Dict[str, Any]] = None
) -> StructuredError:
    """
    Create a structured error from a raw error message.

    Args:
        error_message: Raw error message
        context: Additional context about the operation
        code: Optional explicit error code (auto-detected if not provided)
        details: Optional additional details

    Returns:
        StructuredError with suggestions
    """
    # Auto-detect code if not provided
    if code is None:
        code = classify_error(error_message)

    # Get suggestions from database
    if code and code.value in ERROR_SUGGESTIONS:
        info = ERROR_SUGGESTIONS[code.value]
        # For script errors, preserve the original message as detail
        # so callers see "Type error in script: X is not a function"
        # instead of losing the actual error text.
        message = info.get("message", error_message)
        _SCRIPT_CODES = {"S005", "S006", "S007", "S008"}
        if code.value in _SCRIPT_CODES and error_message and error_message != message:
            message = f"{message}: {error_message}"
        return StructuredError(
            code=code.value,
            message=message,
            recoverable=info.get("recoverable", True),
            context=context,
            suggestions=info.get("suggestions", []),
            details=details or {}
        )

    # Fallback for unknown errors
    return StructuredError(
        code="E999",
        message=error_message,
        recoverable=False,
        context=context,
        suggestions=["Check the error message for details", "Review script syntax"],
        details=details or {}
    )


def format_error_response(
    error_message: str,
    context: str = "",
    include_suggestions: bool = True
) -> str:
    """
    Format an error message with suggestions for MCP output.

    This is the main entry point for formatting errors in tool responses.

    Args:
        error_message: Raw error message
        context: Additional context
        include_suggestions: Whether to include suggestions

    Returns:
        Formatted error string
    """
    structured = create_structured_error(error_message, context)

    if include_suggestions:
        return structured.format()
    else:
        return f"Error [{structured.code}]: {structured.message}"


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def is_connection_error(error_message: str) -> bool:
    """Check if error is a connection-related error."""
    code = classify_error(error_message)
    return code in (ErrorCode.C_DISCONNECTED, ErrorCode.C_TIMEOUT,
                    ErrorCode.C_BRIDGE_ERROR, ErrorCode.C_PROTOCOL)


def is_recoverable(error_message: str) -> bool:
    """Check if error is potentially recoverable."""
    code = classify_error(error_message)
    if code and code.value in ERROR_SUGGESTIONS:
        return ERROR_SUGGESTIONS[code.value].get("recoverable", True)
    return False


def get_suggestions(error_message: str) -> List[str]:
    """Get suggestions for an error message."""
    code = classify_error(error_message)
    if code and code.value in ERROR_SUGGESTIONS:
        return ERROR_SUGGESTIONS[code.value].get("suggestions", [])
    return []


# =============================================================================
# ENVELOPE BUILDER (pre-classified data → canonical JSON envelope)
# =============================================================================


def make_envelope(
    *,
    ok: bool,
    result: Any = None,
    error: Any = None,
    error_code: Optional[str] = None,
    warnings: Optional[List[str]] = None,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> str:
    """Build a standardized envelope JSON string from pre-classified data.

    Unlike ``format_envelope`` in :mod:`proxy_client`, this does NOT run
    ``classify_response``.  Use it when the tool already knows whether
    the operation succeeded or failed (e.g., Python-side import guards,
    validation errors, computed results).

    Error normalisation
    ~~~~~~~~~~~~~~~~~~~
    * ``str``  → ``{code, message, suggestions}`` via
      :func:`create_structured_error`.  *error_code* overrides the
      auto-detected code if supplied.
    * ``dict`` → normalised to always contain ``code``, ``message``, and
      ``suggestions`` (defaults to ``[]``).  Optional ``line`` and
      ``operation`` are preserved.  *error_code* is **ignored** when
      *error* is a dict; embed the code in the dict instead.

    Args:
        ok:          Whether the operation succeeded.
        result:      Payload for success envelopes (ignored when *ok* is
                     ``False``).
        error:       Error description — a string or pre-structured dict
                     with at least ``code`` and ``message`` keys.
        error_code:  Override for the auto-detected error code (string
                     errors only; ignored when *error* is a dict).
        warnings:    List of warning strings.
        diagnostics: Diagnostic metadata dict.

    Returns:
        JSON string with canonical
        ``{ok, warnings, error, diagnostics, result}`` envelope.

    Raises:
        ValueError: If *error* is a dict missing ``code`` or ``message``.
    """
    import json as _json

    warnings = warnings or []
    diagnostics = diagnostics or {}

    # Guard: ok=True with error is a caller bug
    if ok and error is not None:
        raise ValueError(
            "make_envelope(ok=True, error=...) is contradictory; "
            "pass error only when ok=False"
        )

    error_out: Any = None
    if not ok and error is not None:
        if isinstance(error, dict):
            # Validate required keys
            if "code" not in error or "message" not in error:
                raise ValueError(
                    "error dict must include 'code' and 'message'; "
                    f"got keys: {sorted(error.keys())}"
                )
            # Normalise: guarantee suggestions exists + preserve optional fields
            error_out = {
                "code": error["code"],
                "message": error["message"],
                "suggestions": error.get("suggestions", []),
            }
            if "line" in error:
                error_out["line"] = error["line"]
            if "operation" in error:
                error_out["operation"] = error["operation"]
        else:
            structured = create_structured_error(str(error))
            error_out = {
                "code": error_code or structured.code,
                "message": structured.message,
                "suggestions": structured.suggestions,
            }

    return _json.dumps({
        "ok": ok,
        "warnings": warnings,
        "error": error_out,
        "diagnostics": diagnostics,
        "result": result if ok else None,
    })

