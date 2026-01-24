"""
Context and state inspection tools for Adobe Illustrator.

These tools help agents understand the current document state before writing scripts.
"""

from pathlib import Path

from illustrator_mcp.shared import mcp
from illustrator_mcp.tools.base import execute_jsx_tool
from illustrator_mcp import templates


@mcp.tool(
    name="illustrator_get_document_structure",
    annotations={
        "title": "Get Document Structure",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def illustrator_get_document_structure() -> str:
    """
    Get the complete document structure as a JSON tree.
    
    Returns layers, sublayers, and items with their names, types, positions, and properties.
    Essential for understanding canvas state before writing modification scripts.
    
    Returns:
        JSON with:
        - document: name, width, height, artboards
        - layers: array of layer objects with:
            - name, visible, locked
            - items: array of {name, type, position, bounds}
    
    Use this before writing scripts that modify existing objects.
    """
    return await execute_jsx_tool(
        script=templates.GET_DOCUMENT_STRUCTURE,
        command_type="get_document_structure",
        tool_name="illustrator_get_document_structure",
        params={}
    )


@mcp.tool(
    name="illustrator_get_selection_info",
    annotations={
        "title": "Get Selection Info",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def illustrator_get_selection_info() -> str:
    """
    Get detailed information about currently selected objects.
    
    Returns:
        JSON with array of selected items, each containing:
        - name, type, position, bounds
        - Fill/stroke info for paths
        - Text contents for text frames
    """
    return await execute_jsx_tool(
        script=templates.GET_SELECTION_INFO,
        command_type="get_selection_info",
        tool_name="illustrator_get_selection_info",
        params={}
    )


@mcp.tool(
    name="illustrator_get_app_info",
    annotations={
        "title": "Get Application Info",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def illustrator_get_app_info() -> str:
    """
    Get Illustrator application information.
    
    Returns:
        JSON with:
        - version: Illustrator version
        - documentsOpen: number of open documents
        - activeDocumentName: name of active document (if any)
        - scriptingVersion: ExtendScript version
    """
    return await execute_jsx_tool(
        script=templates.GET_APP_INFO,
        command_type="get_app_info",
        tool_name="illustrator_get_app_info",
        params={}
    )


def _get_scripting_reference() -> str:
    """Load ExtendScript reference from markdown file."""
    ref_path = Path(__file__).parent.parent / "resources" / "docs" / "extendscript_reference.md"
    try:
        return ref_path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return "Error: ExtendScript reference file not found."


@mcp.tool(
    name="illustrator_get_scripting_reference",
    annotations={
        "title": "Get Scripting Reference",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def illustrator_get_scripting_reference() -> str:
    """
    Get a quick reference guide for Illustrator ExtendScript.
    
    Call this before writing complex scripts to understand:
    - Coordinate system (Y is inverted!)
    - Shape creation syntax
    - Color application
    - Text formatting
    - Common mistakes to avoid
    
    Returns:
        Markdown-formatted scripting reference
    """
    return _get_scripting_reference()
