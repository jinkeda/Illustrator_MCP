"""
Context and state inspection tools for Adobe Illustrator.

These tools help agents understand the current document state before writing scripts.
Also registers MCP resources for static reference content (Issue #6).
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Literal, Optional

from pydantic import Field

from illustrator_mcp.shared import mcp
from illustrator_mcp.tools.base import ToolInputBase, execute_jsx_tool
from illustrator_mcp.errors import make_envelope
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
        elif name in ("generative", "geo_ir", "session", "snapshot", "curves"):
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


@mcp.resource("extendscript://snippets/update_linked_items")
def update_linked_items_snippet() -> str:
    """JSX snippet for updating all linked items from source files."""
    return templates.UPDATE_LINKED_ITEMS


class GetDocumentInput(ToolInputBase):
    """Input parameters for get_document with pagination and scope support."""
    scope: Literal["document", "app", "both"] = Field(
        "document",
        description="What to return: 'document' (default), 'app' (Illustrator info), or 'both'"
    )
    max_items: int = Field(200, ge=1, le=5000, description="Max items per layer (default 200)")
    max_layers: int = Field(50, ge=1, le=200, description="Max layers to return (default 50)")
    offset: int = Field(0, ge=0, description="Skip first N items per layer (for paging)")
    layer_name: Optional[str] = Field(None, description="Filter to single layer by name")
    layer_index: Optional[int] = Field(None, ge=0, description="Filter to single layer by index")


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
async def illustrator_get_document(params: GetDocumentInput) -> str:
    """
    Get complete document information and structure as a JSON tree.

    Returns layers, sublayers, and items with their names, types, positions, and properties.
    Essential for understanding canvas state before writing modification scripts.

    SCOPE:
    - "document" (default): document structure with layers and items
    - "app": Illustrator application info (works without an open document)
    - "both": returns {document: {...}, app: {...}} (document may be null)

    PAGINATION:
    By default returns up to 200 items per layer and 50 layers.
    If a layer is truncated, the response includes:
      - truncated: true
      - totalItems: total item count
      - nextOffset: use as 'offset' in next call
    To page through a single layer:
      get_document({layer_name: "Layer 1", offset: 200, max_items: 200})

    Args:
        scope: 'document', 'app', or 'both' (default: 'document')
        max_items: Max items per layer (1-5000, default 200)
        max_layers: Max layers to return (1-200, default 50)
        offset: Skip first N items per layer for paging (default 0)
        layer_name: Filter to a single layer by name
        layer_index: Filter to a single layer by index

    Returns:
        JSON with:
        - document: name, width, height, colorMode, saved, layerCount, artboards
        - layers: array of layer objects with:
            - name, visible, locked, itemCount, offset, nextOffset
            - items: array of {name, type, position, bounds}
    """
    scope = params.scope

    # App-only scope: no active document required
    if scope == "app":
        return await execute_jsx_tool(
            script=templates.GET_APP_INFO,
            command_type="get_app_info",
            tool_name="illustrator_get_document",
            params={"scope": "app"}
        )

    # Document scope: standard document structure
    # Determine layer filter: name takes priority over index
    if params.layer_name is not None:
        layer_filter = json.dumps(params.layer_name)  # JS string
    elif params.layer_index is not None:
        layer_filter = str(params.layer_index)  # JS number
    else:
        layer_filter = "null"  # JS null → show all layers

    doc_script = templates.GET_DOCUMENT_STRUCTURE.substitute(
        max_items=params.max_items,
        max_layers=params.max_layers,
        offset=params.offset,
        layer_filter=layer_filter,
    )

    if scope == "document":
        return await execute_jsx_tool(
            script=doc_script,
            command_type="get_document",
            tool_name="illustrator_get_document",
            params={
                "scope": "document",
                "max_items": params.max_items,
                "offset": params.offset,
                "layer_filter": layer_filter,
            }
        )

    # scope == "both": run both and combine
    doc_result = await execute_jsx_tool(
        script=doc_script,
        command_type="get_document",
        tool_name="illustrator_get_document",
        params={"scope": "both", "part": "document"}
    )
    app_result = await execute_jsx_tool(
        script=templates.GET_APP_INFO,
        command_type="get_app_info",
        tool_name="illustrator_get_document",
        params={"scope": "both", "part": "app"}
    )

    # Parse sub-results (execute_jsx_tool returns canonical envelope JSON strings)
    # Extract inner result to avoid nesting envelopes
    warnings = []
    doc_env = None
    app_env = None
    try:
        doc_env = json.loads(doc_result) if isinstance(doc_result, str) else doc_result
    except (json.JSONDecodeError, TypeError):
        warnings.append("Failed to parse document info (no active document?)")
    try:
        app_env = json.loads(app_result) if isinstance(app_result, str) else app_result
    except (json.JSONDecodeError, TypeError):
        warnings.append("Failed to parse app info")

    doc_ok = bool(doc_env and isinstance(doc_env, dict) and doc_env.get("ok") is True)
    app_ok = bool(app_env and isinstance(app_env, dict) and app_env.get("ok") is True)
    doc_data = doc_env.get("result") if isinstance(doc_env, dict) else doc_env
    app_data = app_env.get("result") if isinstance(app_env, dict) else app_env

    if doc_ok and app_ok:
        return make_envelope(
            ok=True,
            result={"document": doc_data, "app": app_data},
            warnings=warnings,
        )

    # Partial or full failure — strict semantics: ok=false, partials in diagnostics
    if not doc_ok and not app_ok:
        msg = "Failed to collect document and app context."
    elif not doc_ok:
        msg = "Failed to collect document context (no active document?)."
    else:
        msg = "Failed to collect app context."

    return make_envelope(
        ok=False,
        error=msg,
        warnings=warnings,
        diagnostics={"partials": {"document": doc_data, "app": app_data}},
    )


def _get_scripting_reference() -> str:
    """Load ExtendScript reference from markdown file."""
    try:
        return _REFERENCE_PATH.read_text(encoding='utf-8')
    except FileNotFoundError:
        return "Error: ExtendScript reference file not found."


