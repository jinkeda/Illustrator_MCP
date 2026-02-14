"""
Context and state inspection tools for Adobe Illustrator.

These tools help agents understand the current document state before writing scripts.
Also registers MCP resources for static reference content (Issue #6).
"""

import json
import logging
from pathlib import Path
from typing import Dict, List

from illustrator_mcp.shared import mcp
from illustrator_mcp.tools.base import execute_jsx_tool
from illustrator_mcp import templates

logger = logging.getLogger(__name__)

# ==================== Resource Paths ====================

_RESOURCES_DIR = Path(__file__).parent.parent / "resources"
_REFERENCE_PATH = _RESOURCES_DIR / "docs" / "extendscript_reference.md"
_MANIFEST_PATH = _RESOURCES_DIR / "scripts" / "manifest.json"


# ==================== Internal Helpers ====================

def _load_manifest() -> dict:
    """Load library manifest JSON."""
    try:
        return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to load manifest: {e}")
        return {}


def _generate_library_catalog() -> str:
    """Generate a concise helper library catalog from manifest.json.

    Output constraints (per reviewer feedback):
    - 3-8 lines per library
    - Minimal function signatures
    - Always show version and deprecated status
    """
    manifest = _load_manifest()
    libs = manifest.get("libraries", {})

    if not libs:
        return "# Helper Library Catalog\n\nNo libraries found in manifest."

    # Categorize libraries
    categories: Dict[str, List[str]] = {
        "Geometry & Layout": [],
        "SOC Operations": [],
        "Data & Generation": [],
        "Task Pipeline": [],
        "Utilities": [],
    }

    for name, info in libs.items():
        if info.get("deprecated"):
            continue
        if name.startswith("ops_"):
            categories["SOC Operations"].append(name)
        elif name in ("geometry", "layout", "selection", "presets"):
            categories["Geometry & Layout"].append(name)
        elif name in ("generative", "geo_ir", "session", "snapshot"):
            categories["Data & Generation"].append(name)
        elif name in ("task_pipeline", "polyfills", "item_ref", "targets",
                       "contracts", "field_eval"):
            categories["Task Pipeline"].append(name)
        else:
            categories["Utilities"].append(name)

    lines = [
        f"# Helper Library Catalog (manifest v{manifest.get('version', '?')})",
        "",
        "Available libraries for `includes` parameter in `execute_script`.",
        "Dependencies are auto-resolved (transitive).",
        "",
    ]

    for category, lib_names in categories.items():
        if not lib_names:
            continue
        lines.append(f"## {category}")
        lines.append("")
        for name in sorted(lib_names):
            info = libs[name]
            version = info.get("version", "?")
            desc = info.get("description", "")
            exports = info.get("exports", [])
            deps = info.get("dependencies", [])

            lines.append(f"### `{name}` v{version}")
            if desc:
                lines.append(f"{desc}")
            if exports:
                # Show up to 8 exports, then truncate
                shown = exports[:8]
                suffix = f" (+{len(exports) - 8} more)" if len(exports) > 8 else ""
                lines.append(f"**Exports:** `{'`, `'.join(shown)}`{suffix}")
            if deps:
                lines.append(f"**Deps:** `{'`, `'.join(deps)}`")
            lines.append("")

    return "\n".join(lines)


# ==================== MCP Resources ====================

@mcp.resource("illustrator://reference/extendscript")
def extendscript_reference_resource() -> str:
    """Static ExtendScript scripting reference (cached by client)."""
    return _get_scripting_reference()


@mcp.resource("illustrator://reference/libraries")
def library_catalog_resource() -> str:
    """Helper library catalog auto-generated from manifest.json."""
    return _generate_library_catalog()


@mcp.tool(
    name="illustrator_get_document",
    annotations={
        "title": "Get Document",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def illustrator_get_document() -> str:
    """
    Get complete document information and structure as a JSON tree.
    
    Returns layers, sublayers, and items with their names, types, positions, and properties.
    Essential for understanding canvas state before writing modification scripts.
    
    Returns:
        JSON with:
        - document: name, width, height, colorMode, saved, layerCount, artboards
        - layers: array of layer objects with:
            - name, visible, locked
            - items: array of {name, type, position, bounds}
    
    Use this before writing scripts that modify existing objects.
    """
    return await execute_jsx_tool(
        script=templates.GET_DOCUMENT_STRUCTURE,
        command_type="get_document",
        tool_name="illustrator_get_document",
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
    try:
        return _REFERENCE_PATH.read_text(encoding='utf-8')
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


@mcp.tool(
    name="illustrator_get_connection_info",
    annotations={
        "title": "Get Connection Info",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def illustrator_get_connection_info() -> dict:
    """
    Get the current Illustrator MCP connection status.
    
    Useful for debugging connection issues when multiple clients are involved.
    Use this tool to check if another MCP client is already connected.
    
    Returns:
        Dictionary with:
        - is_connected: Whether the CEP panel is connected
        - port: WebSocket port number
        - state: Current connection state
        - is_running: Whether the bridge thread is running
        - client_info: Details about the connected client (if any)
    """
    from illustrator_mcp.runtime import get_runtime
    bridge = get_runtime().get_bridge()
    info = bridge.get_connection_info()
    info["panel_health"] = bridge.get_panel_health()
    return info

