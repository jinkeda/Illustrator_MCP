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


