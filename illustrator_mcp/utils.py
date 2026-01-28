"""
Utility functions for Illustrator MCP.

This module provides common utilities used across the codebase.
"""

from pathlib import Path
from typing import Union


def escape_path_for_jsx(path: str) -> str:
    """Escape a file path for use in ExtendScript strings.
    
    Converts backslashes to double backslashes for Windows paths.
    
    Args:
        path: File path to escape.
        
    Returns:
        Escaped path safe for ExtendScript string literals.
        
    Example:
        >>> escape_path_for_jsx("C:\\Users\\file.ai")
        'C:\\\\Users\\\\file.ai'
    """
    return path.replace("\\", "\\\\")


def validate_file_path(path: Union[str, Path]) -> str:
    """Validate and sanitize a file path.
    
    Checks for suspicious characters and resolves to absolute path
    to prevent directory traversal attacks.
    
    Args:
        path: File path to validate.
        
    Returns:
        Validated absolute path as string.
        
    Raises:
        ValueError: If path contains invalid characters.
    """
    path_str = str(path)
    
    # Check for suspicious patterns
    invalid_chars = ['<', '>', '|', '\0']
    for char in invalid_chars:
        if char in path_str:
            raise ValueError(f"Invalid character '{char}' in path: {path_str}")
    
    # Resolve to absolute path to prevent directory traversal
    resolved = Path(path_str).resolve()
    
    return str(resolved)


def escape_string_for_jsx(text: str) -> str:
    """Escape a string for use in ExtendScript string literals.
    
    Escapes backslashes, quotes, and newlines.
    
    Args:
        text: Text to escape.
        
    Returns:
        Escaped text safe for ExtendScript string literals.
    """
    return (text
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "\\r"))
