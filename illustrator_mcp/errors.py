"""
Standardized error codes and structured error handling for Illustrator MCP.

Provides:
- Error code enums matching task_executor.jsx
- Suggestions for common errors
- Structured error response model
- Helper functions for error formatting
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# =============================================================================
# ERROR CODE ENUMS
# =============================================================================

class IllustratorError(str, Enum):
    """High-level error categories for MCP operations."""

    DISCONNECTED = "ILLUSTRATOR_DISCONNECTED"
    NO_DOCUMENT = "NO_DOCUMENT"
    SCRIPT_ERROR = "SCRIPT_ERROR"
    TIMEOUT = "TIMEOUT_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PROXY_ERROR = "PROXY_ERROR"
    LIBRARY_ERROR = "LIBRARY_ERROR"

    def format(self, message: str) -> str:
        """Format an error message with this error code prefix."""
        return f"{self.value}: {message}"


class ErrorCode(str, Enum):
    """
    Detailed error codes matching task_executor.jsx ErrorCodes.

    Naming convention:
    - V_xxx: Validation errors (fail before execution)
    - R_xxx: Runtime errors (fail during execution)
    - C_xxx: Connection errors
    - S_xxx: Script errors
    """
    # === CONNECTION (C) ===
    C_DISCONNECTED = "C001"
    C_TIMEOUT = "C002"
    C_BRIDGE_ERROR = "C003"

    # === VALIDATION (V) - fail before execution ===
    V_NO_DOCUMENT = "V001"
    V_NO_SELECTION = "V002"
    V_INVALID_PAYLOAD = "V003"
    V_INVALID_TARGETS = "V004"
    V_UNKNOWN_TARGET_TYPE = "V005"
    V_MISSING_REQUIRED_PARAM = "V006"
    V_INVALID_PARAM_TYPE = "V007"
    V_SCHEMA_MISMATCH = "V008"
    V_LIBRARY_NOT_FOUND = "V009"

    # === RUNTIME (R) - fail during execution ===
    R_COLLECT_FAILED = "R001"
    R_COMPUTE_FAILED = "R002"
    R_APPLY_FAILED = "R003"
    R_ITEM_OPERATION_FAILED = "R004"
    R_LAYER_NOT_FOUND = "R005"
    R_ELEMENT_NOT_FOUND = "R006"
    R_SCRIPT_EVAL_ERROR = "R007"
    R_PERMISSION_DENIED = "R008"

    # === SCRIPT (S) - ExtendScript-specific errors ===
    S_SYNTAX_ERROR = "S001"
    S_REFERENCE_ERROR = "S002"
    S_TYPE_ERROR = "S003"
    S_RANGE_ERROR = "S004"


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
        "message": "Script execution timed out",
        "recoverable": True,
        "suggestions": [
            "The script may be too complex - try breaking it into smaller operations",
            "Check if Illustrator is responding (not frozen)",
            "Increase timeout if processing large documents",
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

    # Runtime errors
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
    ErrorCode.R_SCRIPT_EVAL_ERROR.value: {
        "message": "Script evaluation error",
        "recoverable": False,
        "suggestions": [
            "Check JavaScript syntax in your script",
            "Verify all variables are defined before use",
            "Use illustrator_get_scripting_reference for correct API usage",
        ],
    },

    # Script errors
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

# Patterns for detecting error types from raw error messages
ERROR_PATTERNS = [
    # Connection errors
    (r"DISCONNECTED|not connected|connection.*failed", ErrorCode.C_DISCONNECTED),
    (r"TIMEOUT|timed out", ErrorCode.C_TIMEOUT),

    # Validation errors
    (r"No documents? open|No active document", ErrorCode.V_NO_DOCUMENT),
    (r"No selection|Nothing selected|selection is empty", ErrorCode.V_NO_SELECTION),
    (r"Layer.*not found|no layer named", ErrorCode.R_LAYER_NOT_FOUND),
    (r"No such element|Element not found|item not found", ErrorCode.R_ELEMENT_NOT_FOUND),

    # Script errors
    (r"SyntaxError|syntax error|Unexpected token", ErrorCode.S_SYNTAX_ERROR),
    (r"ReferenceError|is not defined|is undefined", ErrorCode.S_REFERENCE_ERROR),
    (r"TypeError|is not a function|cannot read property", ErrorCode.S_TYPE_ERROR),
    (r"RangeError|Invalid array length|out of range", ErrorCode.S_RANGE_ERROR),

    # Library errors
    (r"Library not found|library.*not found", ErrorCode.V_LIBRARY_NOT_FOUND),
]


def classify_error(error_message: str) -> Optional[ErrorCode]:
    """
    Classify an error message into an error code.

    Args:
        error_message: Raw error message string

    Returns:
        ErrorCode if pattern matches, None otherwise
    """
    error_lower = error_message.lower()

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
    return code in (ErrorCode.C_DISCONNECTED, ErrorCode.C_TIMEOUT, ErrorCode.C_BRIDGE_ERROR)


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
