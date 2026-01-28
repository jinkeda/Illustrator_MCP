"""
Standardized error codes for Illustrator MCP.

Provides an enum of error codes for consistent error handling and messaging.
"""

from enum import Enum


class IllustratorError(str, Enum):
    """Standardized error codes for Illustrator MCP operations."""

    DISCONNECTED = "ILLUSTRATOR_DISCONNECTED"
    NO_DOCUMENT = "NO_DOCUMENT"
    SCRIPT_ERROR = "SCRIPT_ERROR"
    TIMEOUT = "TIMEOUT_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PROXY_ERROR = "PROXY_ERROR"

    def format(self, message: str) -> str:
        """Format an error message with this error code prefix.

        Args:
            message: The detailed error message.

        Returns:
            Formatted error string with code prefix.
        """
        return f"{self.value}: {message}"
