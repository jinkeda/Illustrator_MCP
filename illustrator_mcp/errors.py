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


# =============================================================================
# ERROR CODE ENUM — SINGLE SOURCE OF TRUTH
# =============================================================================

class ErrorCode(str, Enum):
    """
    Unified error codes for all Illustrator MCP operations.

    Naming convention:
    - C_xxx: Connection/transport errors
    - V_xxx: Validation errors (fail before execution)
    - R_xxx: Runtime errors (fail during execution)
    - S_xxx: Script/system errors (ExtendScript engine + host environment)

    Imported by protocol.py — do not define a second enum elsewhere.
    """
    # === CONNECTION / TRANSPORT (C) ===
    # Covers all communication-layer failures.
    # C_DISCONNECTED covers: not connected, connection dropped, network reset.
    C_DISCONNECTED = "C001"
    C_TIMEOUT = "C002"           # Transport-layer timeout (send/receive)
    C_BRIDGE_ERROR = "C003"      # Internal bridge error
    C_PROTOCOL = "C004"          # Malformed response (missing keys, invalid JSON)

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
            "Check library name spelling (available: geometry, layout, selection, task_executor)",
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

    # Script errors
    (r"\[S005\]|SyntaxError|syntax error|Unexpected token", ErrorCode.S_SYNTAX_ERROR),
    (r"\[S006\]|ReferenceError|is not defined|is undefined", ErrorCode.S_REFERENCE_ERROR),
    (r"\[S007\]|TypeError|is not a function|cannot read property", ErrorCode.S_TYPE_ERROR),
    (r"RangeError|Invalid array length|out of range", ErrorCode.S_RANGE_ERROR),

    # Library errors
    (r"\[V009\]|Library not found|library.*not found|Unknown library", ErrorCode.V_LIBRARY_NOT_FOUND),
    (r"\[V010\]|Symbol collision|symbol.*collision", ErrorCode.V_LIBRARY_CONFLICT),
    (r"\[S010\]|Library file.*I/O|library.*io error", ErrorCode.S_LIBRARY_IO),
    (r"\[S011\]|Manifest.*error|manifest.*parse", ErrorCode.S_MANIFEST_ERROR),
    (r"\[R010\]|injection failed", ErrorCode.R_INJECTION_FAILED),
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
        return StructuredError(
            code=code.value,
            message=info.get("message", error_message),
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
