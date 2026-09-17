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

from mcp.types import CallToolResult
from illustrator_mcp.shared import mcp
from illustrator_mcp.tools.base import ToolInputBase, execute_jsx_tool, TOOL_ANNOTATIONS, canonical_tool
from illustrator_mcp.errors import make_envelope
from illustrator_mcp import templates

logger = logging.getLogger(__name__)

# ==================== Resource Paths ====================

_RESOURCES_DIR = Path(__file__).parent.parent / "resources"
_REFERENCE_PATH = _RESOURCES_DIR / "docs" / "extendscript_reference.md"
_MANIFEST_PATH = _RESOURCES_DIR / "scripts" / "manifest.json"
_LIBRARY_REFERENCE_PATH = _RESOURCES_DIR / "docs" / "library_reference.json"


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
            lines.append(f"**Details:** illustrator://libraries/{name} (active)")
            lines.append("")

    return "\n".join(lines)


# ==================== MCP Resources ====================

def _operation_summary(schema) -> dict:
    from illustrator_mcp.tools.evidence import classify_operation

    reason = classify_operation(schema.name)
    return {
        "name": schema.name,
        "purpose": schema.description,
        "backend": schema.backend,
        "route": schema.route,
        "publicRoute": schema.public_route,
        "requiresTargets": schema.requires_targets,
        "evidenceReason": reason.value if reason else None,
        "detailUri": f"illustrator://ops/{schema.name}",
    }


_OP_AVAILABILITY = (
    "Static support in this release, not live connection or dependency health. "
    "Use illustrator_connection_status for runtime health. JSX dispatch still "
    "requires a registered handler; catalogue membership never enables dispatch. "
    "The separate Python boolean tool requires the optional geometry extra."
)


@mcp.resource("illustrator://ops", mime_type="application/json")
def operation_catalog_resource() -> str:
    """Operation routes and purpose; read detailUri for parameters and examples."""
    from illustrator_mcp.schemas.contracts import OP_SCHEMAS

    return json.dumps({
        "availability": _OP_AVAILABILITY,
        "targetRequirement": "requiresTargets means nonempty, not full cardinality; read each detail.",
        "evidencePolicy": "evidenceReason is the existing single-operation classifier; batch policy can add requirements.",
        "operations": [_operation_summary(s) for s in OP_SCHEMAS],
    }, indent=2)


@mcp.resource("illustrator://ops/{name}", mime_type="application/json")
def operation_detail_resource(name: str) -> str:
    """Operation constraints, coordinates, results and a complete public tool call."""
    from typing import get_args
    from illustrator_mcp.schemas.contracts import get_op_schema
    from illustrator_mcp.tools.examples import operation_example

    schema = get_op_schema(name)
    if schema is None:
        raise ValueError(f"Unknown operation {name!r}; read illustrator://ops for available names.")
    detail = _operation_summary(schema)
    detail.update(schema.documentation.model_dump(exclude={"example_params", "example_targets"}))
    detail.update({
        "availability": _OP_AVAILABILITY,
        "parameters": {key: value.model_dump(mode="json", exclude_none=True)
                       for key, value in schema.params.items()},
        "parameterContract": (
            "The existing broad SOC contract; nested rules and handler defaults are described below. "
            "For typed/Python routes, inputSchema comes from the actual input model; "
            "custom validation described in constraints also applies. "
            "SOC parameters are checked in Python and JSX for availability, required fields, broad types, enums and unknown keys. Pilot nested checks remain stronger."
        ),
        "example": operation_example(name),
        "resultEnvelope": "illustrator://schema/result; JSX success per-op data is under data.report.batchReport.ops[].data (or data.batchReport when the report is unwrapped). Failure reports can be in diagnostics.batchReport. Inspect execution, errors, warnings and effects.",
    })
    if schema.route == "typed_batch":
        from illustrator_mcp.tools.task_execution import PilotOperation

        # Read the actual discriminated union rather than maintain a second map.
        for model in get_args(get_args(PilotOperation)[0]):
            if name in get_args(model.model_fields["task"].annotation):
                detail["inputSchema"] = model.model_json_schema()
                break
        detail["inputSchemaScope"] = "One batch.operations[] object (including task, params and targets)."
        detail["alsoSupportedRoute"] = "illustrator_execute_task.params.payload.params.ops"
    elif schema.route == "python_tool":
        from illustrator_mcp.tools.task_execution import PathBooleanInput

        detail["inputSchema"] = PathBooleanInput.model_json_schema()
        detail["parameters"] = {key: {**value, "required": key in detail["inputSchema"].get("required", [])}
                                for key, value in detail["inputSchema"]["properties"].items()}
        detail["parameterContract"] = "Python-tool parameters derive from the actual input model below; $ref values resolve within inputSchema. This operation has no JSX batch route."
        detail["inputSchemaScope"] = "The params object of illustrator_path_boolean. Operands are MCP ID strings or canonical {target:{...}} selectors; clip also accepts a nonempty ordered list. Each selector must match exactly one path."
        detail["resultEnvelope"] = "illustrator://schema/result; Python boolean result is in canonical data; inspect effects and warnings."
    return json.dumps(detail, indent=2)


@mcp.resource("illustrator://reference/extendscript")
def extendscript_reference_resource() -> str:
    """Static ExtendScript scripting reference (cached by client)."""
    return _get_scripting_reference()


@mcp.resource("illustrator://reference/libraries")
def library_catalog_resource() -> str:
    """Helper library catalog auto-generated from manifest.json."""
    return _generate_library_catalog()


@mcp.resource("illustrator://libraries/{name}", mime_type="application/json")
def library_detail_resource(name: str) -> str:
    """Verified helper signatures and examples; inventory comes from the manifest."""
    libraries = _load_manifest().get("libraries", {})
    if name not in libraries:
        raise ValueError(
            f"Unknown library {name!r}; read illustrator://reference/libraries for available names."
        )
    info = libraries[name]
    reference = json.loads(_LIBRARY_REFERENCE_PATH.read_text(encoding="utf-8")).get(name, {})
    exports = []
    for symbol in info.get("exports", []):
        documentation = reference.get("exports", {}).get(symbol)
        exports.append({"name": symbol, **({
            "status": "verified", "deprecated": bool(info.get("deprecated", False)),
            **documentation,
        } if documentation else {
            "status": "unavailable", "reason": "This export has not been verified."
        })})
    return json.dumps({
        "name": name,
        "version": info.get("version"),
        "description": info.get("description"),
        "deprecated": bool(info.get("deprecated", False)),
        "includes": [name],
        "dependencies": info.get("dependencies", []),
        "source": "resources/scripts/" + info["file"],
        "verification": "Authored against the shipped JSX; not a live Illustrator certification. "
                        "Dependencies are resolved by the existing library resolver.",
        "coordinates": reference.get("coordinates", "unavailable"),
        "notes": reference.get("notes", "Details have not been verified."),
        "example": ({"includes": [name], **reference["example"],
                     "code": "(function () {\n" + reference["example"]["code"] + "\n})();"}
                    if "example" in reference else None),
        "exports": exports,
    }, indent=2)


@mcp.resource("extendscript://snippets/update_linked_items")
def update_linked_items_snippet() -> str:
    """JSX snippet for updating all linked items from source files."""
    return templates.UPDATE_LINKED_ITEMS


@mcp.resource("illustrator://schema/result")
def canonical_result_schema_resource() -> str:
    """JSON Schema for the canonical result in ``structuredContent`` (T11).

    Published as a resource rather than as each tool's MCP ``outputSchema``:
    in mcp 1.25.0 a tool that returns ``CallToolResult`` — which is how it
    controls ``isError`` and attaches preview images — cannot also declare an
    output schema, because FastMCP derives that from the return annotation.
    Exposing it here keeps the contract discoverable and machine-readable, and
    every result carries a matching ``schemaVersion``.
    """
    import json

    from illustrator_mcp.results import RESULT_SCHEMA_VERSION, CanonicalResult

    schema = CanonicalResult.model_json_schema(by_alias=True, mode="serialization")
    schema["$id"] = "illustrator://schema/result"
    schema["x-schema-version"] = RESULT_SCHEMA_VERSION
    return json.dumps(schema, indent=2)


class GetDocumentInput(ToolInputBase):
    """Input parameters for get_document with pagination and scope support."""
    scope: Literal["document", "app", "both", "symbols"] = Field(
        "document",
        description=(
            "What to return: 'document' (default), 'app' (Illustrator info), "
            "'both', or 'symbols' (symbol definitions and placed instances, "
            "read-only)"
        ),
    )
    max_items: int = Field(200, ge=1, le=5000, description="Max items per layer (default 200)")
    max_layers: int = Field(50, ge=1, le=200, description="Max layers to return (default 50)")
    offset: int = Field(0, ge=0, description="Skip first N items per layer (for paging)")
    layer_name: Optional[str] = Field(None, description="Filter to single layer by name")
    layer_index: Optional[int] = Field(None, ge=0, description="Filter to single layer by index")
    symbol_name: Optional[str] = Field(
        None,
        description="scope='symbols': report only this symbol, by name.",
    )
    symbol_contents: bool = Field(
        True,
        description=(
            "scope='symbols': walk each definition's artwork. Turn off for a "
            "faster name-and-count listing."
        ),
    )


_GETDOC_NAME = "illustrator_get_document"


@mcp.tool(name=_GETDOC_NAME, annotations=TOOL_ANNOTATIONS[_GETDOC_NAME])
@canonical_tool(_GETDOC_NAME, reserve=False)
async def illustrator_get_document(params: GetDocumentInput) -> CallToolResult:
    """Get complete document information and structure as a JSON tree.

    CONTRACT: readOnly=True, destructive=False, idempotent=True, openWorld=False

    WHEN TO USE:
      - Understanding canvas state before writing modification scripts
      - Inspecting layers, items, positions, and properties
      - Getting Illustrator application info (scope='app')
      - This reports structure, not appearance. For what the page looks like,
        call illustrator_observe; for whether it is fit to export, call
        illustrator_preflight_check

    OPTIONS:
      scope: 'document' (default), 'app', or 'both'
      max_items: items per layer, 1-5000 (default 200)
      max_layers: layers to return, 1-200 (default 50)
      offset: skip first N items per layer (for paging)
      layer_name / layer_index: filter to single layer

    EXAMPLES:
      Document structure:
        {"params": {}}
      Application info, with no document open:
        {"params": {"scope": "app"}}
      One layer, paginated:
        {"params": {"layer_name": "Layer 1", "offset": 200, "max_items": 200}}
      Symbol definitions and instances, without placing anything:
        {"params": {"scope": "symbols"}}
      One symbol, names and counts only:
        {"params": {"scope": "symbols", "symbol_name": "icon-star", "symbol_contents": false}}

    NOTES:
      - If a layer is truncated, response includes truncated=true and nextOffset
      - scope='both' returns {document: {...}, app: {...}}
    """
    scope = params.scope

    # Symbols: definitions and instances, without placing or expanding
    # anything. Inspecting a symbol used to mean instantiating it and
    # expanding a throwaway copy, which put artwork on the page and left an
    # audit duplicate to hunt down afterwards.
    if scope == "symbols":
        import json as _json
        name_arg = _json.dumps(params.symbol_name) if params.symbol_name else "null"
        script = f"""
        (function () {{
            var defs = JSON.parse(mcpSymbolDefinitions({{
                includeContents: {str(params.symbol_contents).lower()},
                maxItems: {params.max_items},
                name: {name_arg}
            }}));
            var inst = JSON.parse(mcpSymbolInstances({{
                name: {name_arg},
                maxInstances: {params.max_items}
            }}));
            return JSON.stringify({{
                ok: true,
                definitions: defs.definitions,
                definitionCount: defs.definitionCount,
                instances: inst.instances,
                instanceCount: inst.instanceCount,
                truncated: defs.definitions.length < defs.definitionCount || inst.truncated,
                note: inst.note
            }});
        }})()
        """
        return await execute_jsx_tool(
            script=script,
            command_type="get_symbols",
            tool_name=_GETDOC_NAME,
            params={"scope": "symbols", "symbol_name": params.symbol_name},
            includes=["polyfills", "symbols"],
        )

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


