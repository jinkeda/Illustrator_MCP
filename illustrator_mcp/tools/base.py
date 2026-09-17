"""
Base utilities for tool implementations.

Provides common patterns for JSX tool execution to reduce boilerplate.
Also contains canonical constants (SSOT) for tool annotations, coordinate
system, abstraction ladder, and docstring schema.
"""

from typing import Any, Optional

from mcp.types import CallToolResult

from pydantic import BaseModel, ConfigDict, Field

from illustrator_mcp.proxy_client import (
    execute_script_with_context,
    format_envelope,
)


# ══════════════════════════════════════════════════════════════════
# P1 + P2: Canonical Annotation Registry (SSOT)
#
# Semantic definitions (P1):
#   readOnlyHint    — True if tool cannot mutate Illustrator state
#                     AND cannot write to filesystem/network.
#   destructiveHint — True if tool can delete/overwrite/close/replace,
#                     OR is state-changing, OR failure may lose work.
#   idempotentHint  — True if repeated identical call yields same
#                     resulting state (doc + filesystem) or is a no-op.
#   openWorldHint   — True if tool can interact with resources outside
#                     document/app state (filesystem, network, OS).
#
# P6: Hints reflect worst-case capability over all actions/inputs.
# ══════════════════════════════════════════════════════════════════

TOOL_ANNOTATIONS: dict[str, dict] = {
    "illustrator_execute_script":  {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False, "openWorldHint": True },
    "illustrator_execute_task":    {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False, "openWorldHint": True },
    "illustrator_job_status":      {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True,  "openWorldHint": True},
    "illustrator_observe":         {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True,  "openWorldHint": True },
    "illustrator_path_boolean":    {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False, "openWorldHint": False},
    "illustrator_document":        {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False, "openWorldHint": True },
    "illustrator_export_document": {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False, "openWorldHint": True },
    "illustrator_history":         {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False, "openWorldHint": False},
    "illustrator_place_file":      {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False, "openWorldHint": True },
    "illustrator_set_reference":   {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": True,  "openWorldHint": True },
    "illustrator_get_document":    {"readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True,  "openWorldHint": False},
    "illustrator_query_items":     {"readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True,  "openWorldHint": False},
    "illustrator_preflight_check": {"readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True,  "openWorldHint": False},
    "illustrator_path_import_svg": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
    # Observes process-local connection state; the optional probe only
    # reads app identity. It never starts the server or reconnects.
    "illustrator_connection_status": {"readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True,  "openWorldHint": False},
}

_REQUIRED_HINT_KEYS = {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}


# ══════════════════════════════════════════════════════════════════
# P3: Docstring Schema — allowed section headers
# ══════════════════════════════════════════════════════════════════

ALLOWED_DOCSTRING_SECTIONS = frozenset({
    "WHEN TO USE:",
    "KEY CONCEPTS:",
    "DECISION RULES:",
    "COORDINATE SYSTEM:",
    # How a script hands a value back. Raw execution evaluates the script at
    # the top level, so a bare `return` is a syntax error and the last
    # expression is the result. That was undocumented, and callers found it
    # by hitting "Illegal return outside of a function body".
    "EXECUTION CONTRACT:",
    "ABSTRACTION LADDER:",
    "ELEMENT DISCOVERY:",
    "MUTATION SAFETY:",
    "PIPELINE:",
    "TARGET SELECTORS:",
    "OPTIONS:",
    "EXAMPLES:",
    "NOTES:",
    "SAFETY:",
    # T11: what the caller gets back — structuredContent shape and the meaning
    # of isError. Worth stating on tools that return a canonical result, since
    # the distinction between execution and verification outcomes is the whole
    # point of that result.
    "RESULT:",
})

# Characters banned from docstrings (box-drawing)
_BANNED_CHARS = set("═║─│┌┐└┘├┤┬┴┼╔╗╚╝╠╣╦╩╬")


# ══════════════════════════════════════════════════════════════════
# P4: Canonical Coordinate System Block
# ══════════════════════════════════════════════════════════════════

COORDINATE_SYSTEM_BLOCK = """\
COORDINATE SYSTEM:
  - Geometry helpers use artboard-relative coordinates: origin at the active
    artboard's top-left, with y increasing downward (screen space)
  - Raw Illustrator DOM positions use document-space coordinates, with y
    increasing upward; do not assume that the active artboard starts at (0, 0)
  - Units: points (1 pt = 1/72 inch)

  HELPERS — ARTBOARD-RELATIVE, Y-DOWN (includes: ['geometry']):
    Use these to avoid manual conversion to raw document coordinates:
      rectXY(x, y, w, h)          — rectangle at screen-space (x,y)
      ellipseXY(x, y, w, h)       — ellipse at screen-space (x,y)
      lineXY(x1, y1, x2, y2)      — line between screen-space points
      polygonXY([[x,y],...], closed)— polygon from screen-space points
      pointXY(x, y)               — returns {left, top} for position assignments
      drawPathPoints(spec)         — full path with handles, UUID, heap registration
    Example: var rect = rectXY(100, 200, 50, 30);  // no -y needed

  RAW DOM — DOCUMENT-SPACE, Y-UP (only when helpers are insufficient):
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    position = [ab[0] + x, ab[1] - y];  // convert artboard-relative (x, y)
    // Nonzero-origin example: ab top-left (72, 720), (x, y) = (100, 200)
    // gives the raw DOM position [172, 520].
    PITFALL: rectangle(top,left,w,h) and ellipse() need POSITIVE width/height.
    Negative height places the shape ABOVE the artboard (invisible).
    rectangle(ab[1], ab[0], 1000, 600) \u2713 | negative height \u2717 ghost element"""


# ══════════════════════════════════════════════════════════════════
# P5: Abstraction Ladder (uses registry names only)
# ══════════════════════════════════════════════════════════════════

ABSTRACTION_LADDER = """\
ABSTRACTION LADDER — prefer higher levels before using raw script:
  Level 5 — illustrator_path_boolean: boolean sculpt (unite/subtract/intersect/xor)
  Level 4 — illustrator_execute_task + element_create_batch: batch-create identical shapes
  Level 3 — illustrator_path_import_svg: import SVG d-string paths
  Level 2 — illustrator_execute_task + element_create: smooth curves, handles, mirror
  Level 1 — illustrator_execute_script (THIS tool): raw ExtendScript"""


# ==================== Shared Pydantic Base ====================

def declare_effects(
    *,
    created=None,
    modified=None,
    deleted=None,
    complete: bool = True,
) -> dict:
    """State what a tool changed, for the canonical ``effects`` field.

    Put the result in a tool's ``diagnostics`` under ``effects``; the boundary
    lifts it into the canonical result. Only the structured executor used to
    populate that field, so every other mutating tool reported empty lists
    with ``complete`` false — a claim that its changes could not be accounted
    for, made by tools that knew exactly what they had done.

    ``complete`` defaults to true because a tool calling this normally does
    know. Pass false only where the effects genuinely cannot be enumerated,
    such as undo, and say so in a comment at the call site. Empty lists with
    ``complete`` true are a real answer: they mean nothing was created,
    modified or deleted, which is the honest report from an export.
    """
    return {
        "created": list(created or []),
        "modified": list(modified or []),
        "deleted": list(deleted or []),
        "complete": complete,
    }


class ToolInputBase(BaseModel):
    """Base class for all tool input models.
    
    Provides shared configuration:
    - str_strip_whitespace: Auto-strip whitespace from string fields
    """
    model_config = ConfigDict(str_strip_whitespace=True)
    expected_document_token: Optional[str] = Field(default=None, min_length=1,
        description="Optional live document token override. Mutations use the shared process pin when omitted; reads may inspect the active document with a mismatch warning. Explicit read targets must match. Use illustrator_document activate to change the shared pin. Names/paths are not identity; raw code is not sandboxed.")


class MutationInputBase(ToolInputBase):
    """Optional identity for bounded, process-local logical-job deduplication."""
    model_config = ConfigDict(populate_by_name=True)
    job_id: Optional[str] = Field(
        default=None, alias="jobId", pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        description="Optional logical-job ID. Same retained ID and intent returns the original outcome without replay; changed intent conflicts. Generated when omitted. Retention is bounded, not durable across server restarts.",
    )


def forbid_extra_tool_arguments(mcp_app: Any, tool_name: str):
    """Close one FastMCP-generated outer argument model.

    FastMCP builds an argument wrapper around a function signature in addition
    to any Pydantic model used by an individual parameter. Its wrapper ignores
    unknown sibling arguments by default and offers no decorator option to
    change that behavior. Apply this decorator outside ``@mcp.tool`` so the
    generated model rejects unknown keys both at runtime and in its published
    JSON Schema, without changing ``ToolInputBase`` or unrelated tools.
    """
    def decorator(fn):
        tool = mcp_app._tool_manager.get_tool(tool_name)
        if tool is None:  # pragma: no cover - decorator order is deterministic
            raise RuntimeError(
                f"Tool {tool_name!r} must be registered before its outer "
                "argument model can be made strict"
            )

        argument_model = tool.fn_metadata.arg_model
        config = dict(argument_model.model_config)
        config["extra"] = "forbid"
        argument_model.model_config = ConfigDict(**config)
        argument_model.model_rebuild(force=True)
        tool.parameters = argument_model.model_json_schema(by_alias=True)
        return fn

    return decorator


# ── The canonical tool boundary (T30) ────────────────────────────────

def canonical_tool(tool_name: str, *, reserve: bool = False):
    """Give a document-bound tool the canonical result boundary and slot.

    Applied *under* ``@mcp.tool`` so the wrapped function keeps its docstring,
    parameter model and tool name:

        @mcp.tool(name=_DOC_NAME, annotations=...)
        @canonical_tool(_DOC_NAME, reserve=True)
        async def illustrator_document(params: DocumentInput) -> CallToolResult:
            ...

    ``reserve`` remains accepted for decorator compatibility. SR03 requires the
    slot for reads as well as mutations so identity bootstrap is coordinated.

    Two things it guarantees, which nine tools previously each had to remember:

    * whatever the tool returns — an envelope string, a list of content blocks,
      an already-built result — leaves through ``finalize_tool_result``, so
      ``isError`` is derived from execution status and nothing else. A tool
      whose own JSON said ``ok: false`` could otherwise reach the client as
      ``isError: false``.
    * with ``reserve=True`` the whole call holds one execution slot, so a tool
      that makes several host round trips cannot have another job run between
      them. Nested calls are safe: the coordinator's reserved-job ContextVar
      keeps an inner call from waiting on the slot its own caller holds.
    """
    import functools
    import inspect

    from illustrator_mcp.results import finalize_tool_result

    def decorate(fn):
        @functools.wraps(fn)
        async def run_inner(params):
            from illustrator_mcp.execution.logical_job import run_logical_job
            return await run_logical_job(tool_name, params, lambda job: fn(params))

        @functools.wraps(fn)
        async def inner(params):
            from illustrator_mcp.execution.coordinator import HostUnresolvedError
            try:
                return await run_inner(params)
            except HostUnresolvedError as exc:
                return finalize_tool_result(format_envelope({
                    "error": str(exc), "execution": "unknown", "jobId": exc.job_id,
                }), tool=tool_name)

        # functools.wraps makes inspect.signature follow __wrapped__, which
        # would report the inner function's old return type to the schema
        # builder. State the boundary's actual return type instead.
        sig = inspect.signature(fn)
        inner.__signature__ = sig.replace(return_annotation=CallToolResult)
        inner.__annotations__ = dict(getattr(fn, "__annotations__", {}))
        inner.__annotations__["return"] = CallToolResult
        return inner

    return decorate


async def execute_jsx_tool(
    script: str,
    command_type: str,
    tool_name: str,
    params: Optional[dict[str, Any]] = None,
    includes: Optional[list[str]] = None,
    effects: Optional[dict] = None,
    canonical: bool = False,
) -> str | CallToolResult:
    """
    Standard JSX tool execution wrapper.
    
    Reduces boilerplate in each tool from ~10 lines to 1-2 lines.
    
    Args:
        script: JavaScript/ExtendScript code to execute
        command_type: Type of command (e.g., "create_document")
        tool_name: Name of the MCP tool (e.g., "illustrator_create_document")
        params: Parameters passed to the tool (for debugging)
        includes: Optional list of libraries to inject (e.g., ["geometry", "layout"])
    
    Returns:
        Formatted string for MCP tool response
    
    Example:
        @mcp.tool(name="illustrator_my_tool")
        async def illustrator_my_tool(params: MyInput) -> str:
            script = f'''
            (function() {{
                // ... JavaScript code ...
            }})()
            '''
            return await execute_jsx_tool(
                script=script,
                command_type="my_operation",
                tool_name="illustrator_my_tool",
                params={"key": params.key}
            )
    """
    # Execute with context (library injection handled by pipeline)
    response = await execute_script_with_context(
        script=script,
        command_type=command_type,
        tool_name=tool_name,
        params=params or {},
        includes=includes
    )

    # Return standardized envelope for consistent API contract
    diagnostics = {
        "tool": tool_name,
        "command": command_type,
        "includes": includes or []
    }
    # A tool that knows what it changed says so here, and the boundary lifts
    # it into the canonical `effects`. Without it the field stays empty with
    # `complete` false, which reads as "these changes cannot be accounted
    # for" — untrue for a tool that just placed one known item.
    if effects is not None:
        diagnostics["effects"] = effects
    if canonical:
        return canonical_jsx_result(response, tool=tool_name, context=command_type, diagnostics=diagnostics)
    return format_envelope(response, context=command_type, diagnostics=diagnostics)


def canonical_jsx_result(response, *, tool, context="", diagnostics=None, warnings=None):
    """Migrate a known producer without a serialize/parse presentation roundtrip."""
    from illustrator_mcp.proxy_client import build_envelope_dict
    from illustrator_mcp.results import finalize_tool_result
    return finalize_tool_result(build_envelope_dict(response, context=context,
        diagnostics=diagnostics, warnings=warnings), tool=tool)
