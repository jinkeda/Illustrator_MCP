"""
Tool module imports for illustrator_mcp.

This package contains all MCP tools organized by category.
All tools use execute_script internally to run JavaScript in Illustrator.
"""

# Core tool
from illustrator_mcp.tools import execute

# Document and file operations
from illustrator_mcp.tools import documents
from illustrator_mcp.tools import artboards

# Drawing and shapes
from illustrator_mcp.tools import shapes
from illustrator_mcp.tools import paths
from illustrator_mcp.tools import pathfinder

# Text
from illustrator_mcp.tools import text
from illustrator_mcp.tools import typography

# Layers and objects
from illustrator_mcp.tools import layers
from illustrator_mcp.tools import objects
from illustrator_mcp.tools import selection

# Styling and effects
from illustrator_mcp.tools import styling
from illustrator_mcp.tools import effects

# Arrangement and transforms
from illustrator_mcp.tools import arrange
from illustrator_mcp.tools import transform

__all__ = [
    "execute",
    "documents",
    "artboards",
    "shapes",
    "paths",
    "pathfinder",
    "text",
    "typography",
    "layers",
    "objects",
    "selection",
    "styling",
    "effects",
    "arrange",
    "transform"
]
