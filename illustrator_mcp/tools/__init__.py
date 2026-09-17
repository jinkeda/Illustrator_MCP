"""
Tool module imports for illustrator_mcp.

SCRIPTING FIRST ARCHITECTURE:
This MCP uses a minimal toolset following the blender-mcp pattern.
Most operations should be done via illustrator_execute_script.

Consolidated tool inventory (15 tools):
- execute_script: Run any ExtendScript code
- execute_task: Structured task protocol operations
- job_status: Reconcile retained structured-job outcomes without replay
- observe: Coordinated preview, context, annotation map, and exact handles
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
- connection_status: Which link in the chain to Illustrator is broken
"""

# Authoritative list of expected tool names (single source of truth).
# Registry snapshot test imports this to prevent drift.
EXPECTED_TOOL_NAMES = {
    "illustrator_execute_script",
    "illustrator_execute_task",
    "illustrator_job_status",
    "illustrator_observe",
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
    "illustrator_connection_status",
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

    # Task execution (execute_task) + path boolean (split from execute.py)
    from illustrator_mcp.tools import task_execution
    from illustrator_mcp.tools import observe

    # Connection diagnostics — importable and callable with
    # Illustrator closed, which is the case it reports on.
    from illustrator_mcp.tools import connection

    from illustrator_mcp.execution.journal import wrap_registered_tool
    for name, tool in mcp._tool_manager._tools.items():
        tool.fn = wrap_registered_tool(tool.fn, name)

    return [execute, documents, context, query, import_svg,
            task_execution, observe, connection]

__all__ = ["register_tools", "EXPECTED_TOOL_NAMES"]
