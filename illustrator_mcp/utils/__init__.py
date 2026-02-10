"""
Utility modules for Illustrator MCP.
"""

from illustrator_mcp.utils.chunking import (
    ChunkConfig,
    chunk_ops,
    merge_chunk_results,
    should_chunk,
    estimate_chunk_count
)

# Re-export functions from utils.py (the module, not the package)
# These are commonly imported via `from illustrator_mcp.utils import ...`
from illustrator_mcp.utils_funcs import (
    escape_path_for_jsx,
    validate_file_path,
    escape_string_for_jsx
)

__all__ = [
    # Chunking
    "ChunkConfig",
    "chunk_ops",
    "merge_chunk_results",
    "should_chunk",
    "estimate_chunk_count",
    # Path/string utilities
    "escape_path_for_jsx",
    "validate_file_path",
    "escape_string_for_jsx"
]
