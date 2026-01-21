"""
Tool module imports for illustrator_mcp.

SCRIPTING FIRST ARCHITECTURE:
This MCP uses a minimal toolset following the blender-mcp pattern.
Most operations should be done via illustrator_execute_script.

Core tools:
- execute_script: Run any ExtendScript code
- Document operations: create, open, save, close, export
- Context: get_document_info, get_document_structure, get_selection_info
- Utilities: undo, redo

Task Protocol tools (v2.1):
- query: Declarative item queries with structured reports
"""

# Core tool - the primary way to interact with Illustrator
from illustrator_mcp.tools import execute

# Document operations (essential file I/O)
from illustrator_mcp.tools import documents

# Context tools (NEW - for document structure)
from illustrator_mcp.tools import context

# Task Protocol tools (pilot refactor)
from illustrator_mcp.tools import query

# The following modules are DISABLED - use execute_script instead:
# from illustrator_mcp.tools import artboards
# from illustrator_mcp.tools import shapes
# from illustrator_mcp.tools import paths
# from illustrator_mcp.tools import pathfinder
# from illustrator_mcp.tools import text
# from illustrator_mcp.tools import typography
# from illustrator_mcp.tools import layers
# from illustrator_mcp.tools import objects
# from illustrator_mcp.tools import selection
# from illustrator_mcp.tools import styling
# from illustrator_mcp.tools import effects
# from illustrator_mcp.tools import arrange
# from illustrator_mcp.tools import transform
# from illustrator_mcp.tools import composite
# from illustrator_mcp.tools import patterns

__all__ = [
    "execute",
    "documents",
    "context",
    "query",
]

