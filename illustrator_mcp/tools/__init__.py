"""
Tool module imports for illustrator_mcp.

SCRIPTING FIRST ARCHITECTURE:
This MCP uses a minimal toolset following the blender-mcp pattern.
Most operations should be done via illustrator_execute_script.

Consolidated tool inventory (12 tools):
- execute_script: Run any ExtendScript code
- execute_task: Structured task protocol operations
- document: Create/open/save/close documents (unified)
- export_document: Multi-format export
- history: Undo/redo/checkpoints
- place_file: Place external files
- set_reference: Reference image overlay
- get_document: Document structure + app info (scope param)
- query_items: Declarative item queries
- preflight_check: Validation checks
- path_boolean: Boolean path operations
- path_import_svg: SVG path data import
"""

# Authoritative list of expected tool names (single source of truth).
# Registry snapshot test imports this to prevent drift.
EXPECTED_TOOL_NAMES = {
    "illustrator_execute_script",
    "illustrator_execute_task",
    "illustrator_document",
    "illustrator_export_document",
    "illustrator_history",
    "illustrator_place_file",
    "illustrator_set_reference",
    "illustrator_get_document",
    "illustrator_query_items",
    "illustrator_preflight_check",
    "illustrator_path_boolean",
    "illustrator_path_import_svg",
}


def register_tools(mcp):
    """
    Explicitly register tools with the MCP instance.
    This replaces side-effect imports in server.py.
    """
    # Core tool - the primary way to interact with Illustrator
    from illustrator_mcp.tools import execute

    # Document operations (essential file I/O)
    from illustrator_mcp.tools import documents

    # Context tools (for document structure)
    from illustrator_mcp.tools import context

    # Task Protocol tools (pilot refactor)
    from illustrator_mcp.tools import query

    # SVG import tool (path_import_svg)
    from illustrator_mcp.tools import import_svg

    return [execute, documents, context, query, import_svg]

__all__ = ["register_tools", "EXPECTED_TOOL_NAMES"]
