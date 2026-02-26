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

# Path utilities
from illustrator_mcp.utils.path import (
    escape_path_for_jsx,
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
]
