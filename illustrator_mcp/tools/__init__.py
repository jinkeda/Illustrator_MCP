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
    
    return [execute, documents, context, query]

__all__ = ["register_tools"]

