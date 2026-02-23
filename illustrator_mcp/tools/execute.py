"""
Core execute_script tool for Adobe Illustrator.

This is the PRIMARY tool for interacting with Illustrator.
Following the "Scripting First" pattern (like blender-mcp), most operations
should be done via this tool rather than specialized atomic tools.
"""

import json
import logging
import os
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import Field, model_validator
from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_envelope
from illustrator_mcp.libraries import get_injection_metadata
from illustrator_mcp.tools.base import ToolInputBase
from mcp.types import ImageContent, TextContent

# Import from sibling modules
from illustrator_mcp.tools.cadence import (
    _MutationCounter, _counter, VLM_QA_CADENCE, VLM_CHECKPOINT_INSTRUCTION,
    get_mutation_count, reset_mutation_count,
)
from illustrator_mcp.tools.preview import (
    _build_export_script, _capture_artboard, _capture_artboard_png,
    _generate_preview, _COLLECT_ITEMS_JSX, _filter_items, _annotate_preview,
)

# Set up logging for telemetry
logger = logging.getLogger("illustrator_mcp")


class ExecuteScriptInput(ToolInputBase):
    """Input for executing raw JavaScript in Illustrator."""

    script: Optional[str] = Field(
        default=None,
        description="JavaScript/ExtendScript code to execute in Illustrator"
    )

    file_path: Optional[str] = Field(
        default=None,
        description="Path to a .jsx file to execute (alternative to inline script). Mutually exclusive with 'script'."
    )

    params: Optional[Dict[str, Any]] = Field(
        default=None,
        description="JSON-serializable variables to inject before script execution. "
                    "Values must be JSON-compatible (string, number, bool, array, plain object)."
    )

    params_mode: Literal["__PARAMS_ONLY__", "EXPOSE_VARS"] = Field(
        default="__PARAMS_ONLY__",
        description="__PARAMS_ONLY__: inject single __PARAMS__ object. "
                    "EXPOSE_VARS: also declare top-level vars for each key."
    )

    # Reserved param keys that would collide with injection mechanism
    _RESERVED_PARAM_KEYS = {"__PARAMS__"}

    @model_validator(mode='after')
    def resolve_script_source(self):
        """Ensure either script or file_path is provided, resolve file_path, and inject params."""
        if not self.script and not self.file_path:
            raise ValueError("Provide either 'script' or 'file_path'")
        if self.script and self.file_path:
            raise ValueError("Provide 'script' or 'file_path', not both")
        if self.file_path:
            path = self.file_path
            if not os.path.isfile(path):
                raise ValueError(f"Script file not found: {path}")
            with open(path, 'r', encoding='utf-8') as f:
                self.script = f.read()
            if not self.script.strip():
                raise ValueError(f"Script file is empty: {path}")

        # Inject params as JS object literal preamble
        if self.params:
            bad_keys = set(self.params.keys()) & self._RESERVED_PARAM_KEYS
            if bad_keys:
                raise ValueError(f"Reserved param key(s): {bad_keys}")
            # JSON is valid JS for JSON-serializable values (no undefined, no functions)
            params_literal = json.dumps(self.params, ensure_ascii=False)
            lines = [f"var __PARAMS__ = {params_literal};"]
            if self.params_mode == "EXPOSE_VARS":
                for key in self.params:
                    if not key.isidentifier():
                        raise ValueError(f"Param key is not a valid JS identifier: {key!r}")
                    lines.append(f"var {key} = __PARAMS__[{json.dumps(key)}];")
            preamble = "// Injected by MCP params:\n" + "\n".join(lines) + "\n\n"
            self.script = preamble + self.script

        return self

    description: str = Field(
        default="",
        description="Brief description of what the script does (e.g., 'Draw graphene lattice', 'Add axis labels'). Shown in CEP panel log for debugging."
    )

    includes: Optional[List[str]] = Field(
        default=None,
        description="List of standard libraries to inject (e.g., ['geometry', 'selection', 'layout', 'validate'])"
    )

    # Validation parameters
    validate_bounds: bool = Field(
        default=False,
        description="Check if items are on artboard after execution"
    )

    bounds_type: str = Field(
        default="visible",
        description="Bounds type for validation: 'visible' (includes strokes/effects) or 'geometric' (path only)"
    )

    artboard_index: Optional[int] = Field(
        default=None,
        description="Artboard index for validation (None = active artboard)"
    )

    ignore_hidden: bool = Field(
        default=True,
        description="Skip hidden items in validation"
    )

    ignore_locked: bool = Field(
        default=True,
        description="Skip locked items in validation"
    )

    bounds_scope: str = Field(
        default="document",
        description="Scope: 'document' (all items) or 'artboard' (items on target artboard)"
    )

    bounds_source: str = Field(
        default="group_visible",
        description="Bounds source: 'group_visible' (default) or 'clipping_path' (use clipping path bounds for clipped groups)"
    )

    timeout: Optional[float] = Field(
        default=None, le=300.0,
        description="Execution timeout in seconds. Default 30s, max 300s. Set higher for generative scripts."
    )

    # Preview fields (P4)
    # None = not specified (VLM cadence will auto-inject at checkpoints)
    # True = explicitly requested
    # False = explicitly declined (cadence will skip with warning)
    return_preview: Optional[bool] = Field(
        default=None,
        description="After execution, auto-export a thumbnail and return as ImageContent. "
                    "Leave unset to allow VLM QA cadence to auto-inject at checkpoints."
    )

    preview_mode: Literal["artboard", "bounds", "annotated"] = Field(
        default="artboard",
        description="'artboard': preview active artboard. 'bounds': preview specified bounds. "
                    "'annotated': artboard with numbered bounding boxes and annotation map for VLM grounding."
    )

    preview_max_items: int = Field(
        default=200,
        description="Max items to annotate in 'annotated' preview mode.",
        ge=1,
        le=500
    )

    preview_bounds: Optional[List[float]] = Field(
        default=None,
        description="[x, y, w, h] crop bounds for preview_mode='bounds'. Ignored for 'artboard'."
    )

    preview_max_dim: int = Field(
        default=1024,
        description="Max dimension (width or height) of preview thumbnail in pixels.",
        ge=64,
        le=4096
    )

    preview_format: Literal["png", "jpg"] = Field(
        default="png",
        description="Preview image format."
    )

    final_step: bool = Field(
        default=False,
        description="Set to True on the last mutation to force an annotated VLM QA preview, "
                    "regardless of the cadence counter."
    )

    max_ops: int = Field(
        default=500000,
        ge=1000,
        le=5000000,
        description="Maximum iteration guard count. A watchdog counter (__mcp_check()) is "
                    "injected into scripts; when called more than max_ops times it throws "
                    "to prevent infinite-loop crashes. Raise for legitimately large batch scripts."
    )

    max_ms: int = Field(
        default=25000,
        ge=1000,
        le=120000,
        description="Maximum wall-clock time in milliseconds. __mcp_check() also monitors "
                    "elapsed time (checked every 1000 ops) and throws if exceeded."
    )

    probe_points: Optional[List[dict]] = Field(
        default=None,
        description="Coordinate probe markers to render on the annotated preview. "
                    "Each dict has: x (float, pts screen-space), y (float, pts Y-down), "
                    "label (str, optional). Only drawn when preview_mode='annotated'."
    )


@mcp.tool(
    name="illustrator_execute_script",
    annotations={
        "title": "Execute JavaScript in Illustrator",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False
    }
)
async def illustrator_execute_script(params: ExecuteScriptInput) -> Union[str, list]:
    """
    Execute raw JavaScript/ExtendScript code in Adobe Illustrator.
    
    This is the PRIMARY tool for all Illustrator operations. Use get_scripting_reference
    for syntax help if needed.
    
    COORDINATE SYSTEM:
    - Origin: Top-left of artboard
    - Y-axis: NEGATIVE downward. Use -y for visual y positions.
    - Units: Points (1 pt = 1/72 inch)
    
    COMMON OPERATIONS:
    
    Shapes:
    - Rectangle: doc.pathItems.rectangle(top, left, width, height)
    - Ellipse: doc.pathItems.ellipse(top, left, width, height)
    - Line: var p = doc.pathItems.add(); p.setEntirePath([[x1,-y1], [x2,-y2]])
    
    Colors:
    - var c = new RGBColor(); c.red=255; c.green=0; c.blue=0;
    - shape.fillColor = c; shape.strokeColor = c;
    
    Text:
    - var tf = doc.textFrames.add(); tf.contents = "text"; tf.position = [x, -y];
    
    Selection:
    - var sel = doc.selection; // Array of selected items
    - item.selected = true; // Select an item
    
    Args:
        params.script: Valid ExtendScript code to execute (inline)
        params.file_path: Path to a .jsx file to execute (alternative)
    
    Returns:
        JSON result from script execution, or error details if failed
    
    Example:
        // Draw a red rectangle
        var doc = app.activeDocument;
        var rect = doc.pathItems.rectangle(-100, 50, 200, 100);
        var c = new RGBColor(); c.red = 255; c.green = 0; c.blue = 0;
        rect.fillColor = c;
    
    ELEMENT DISCOVERY:
    Use grid helpers to locate items on the artboard:
    - artboardGrid(cols, rows) — divide artboard into labeled cells (A1, B2, ...)
    - itemsInCell(cell, mode) — find items in a grid cell ("containsCenter" or "intersects")
    
    MUTATION SAFETY:
    Every execute_script call increments a mutation counter. An annotated preview
    is auto-injected every VLM_QA_CADENCE calls for visual verification.
    Set final_step=true on the last mutation to force a checkpoint.
    
    KNOWN LIMITATIONS:
    
    Boolean path ops (subtract/unite/intersect):
      Not available via ExtendScript. Use these patterns instead:
      - Crescent moon: Compute arc points on two offset circles, filter by angle
      - Donut/ring: Create two circles, select both, Object > Compound Path > Make
      - Cutout: Use clipping mask (group + clip path) to simulate subtraction
      - app.executeMenuCommand("pathfinder") exists but is fragile and UI-dependent
    
    Bézier curves:
      setEntirePath() creates corner points only. For smooth curves, use extended
      point format in element_create: [x, y, leftDirX, leftDirY, rightDirX, rightDirY]
      Or manually set handles after path creation:
        path.pathPoints[0].leftDirection = [lx0, -ly0];
        path.pathPoints[0].rightDirection = [rx0, -ry0];
      Handle coordinates are absolute, not relative to the anchor.
    
    SAFETY:
      A watchdog is injected before every script with dual limits:
      - Op count: __mcp_check() throws after max_ops (default 500K)
      - Wall clock: __mcp_check() throws after max_ms (default 25s)
      Call __mcp_check() as the FIRST line inside every for/while body.
      
      CRITICAL: Never iterate a live Illustrator collection if you add/remove
      items in the loop. Use the injected snapshot helpers instead:
        __mcp_forEachSnapshot(doc.pathItems, function(item, i) { ... });
        var snap = __mcp_snapshot(doc.pathItems);
      
      NOTE: Scripts that never call __mcp_check() (e.g. bare while(true){})
      are NOT protected by this guard. The only robust fix for non-cooperative
      loops is chunked execution (future work).
    
    IMPORTANT: Always use -y for Y coordinates when positioning objects.
    Call get_scripting_reference for more detailed syntax examples.
    """
    # Log script execution for telemetry
    script = params.script  # Already resolved by model_validator

    # ── Safety guard: inject max_ops / max_ms overrides if non-default ──
    safety_overrides = []
    if params.max_ops != 500000:
        safety_overrides.append(f"var __MCP_MAX_OPS = {params.max_ops};")
    if params.max_ms != 25000:
        safety_overrides.append(f"var __MCP_MAX_MS = {params.max_ms};")
    if safety_overrides:
        script = "\n".join(safety_overrides) + "\n" + script

    script_len = len(script)
    desc = params.description.strip() if params.description else None

    warnings = []

    # ── VLM QA Cadence: auto-inject annotated preview ──────────
    # B3: Increment counter here; decremented in outer except if execution fails
    count = _counter.increment()
    is_checkpoint = (count % VLM_QA_CADENCE == 0) or params.final_step
    is_vlm_checkpoint = False  # True only when cadence auto-injects

    if is_checkpoint:
        if params.return_preview is False and not params.final_step:
            # AI explicitly disabled preview — soft override: warn but respect
            warnings.append(
                f"VLM QA checkpoint skipped (mutation #{count}). "
                "Consider using return_preview=True, preview_mode='annotated' "
                "to visually verify the document state."
            )
        else:
            # Auto-inject annotated preview
            params.return_preview = True
            params.preview_mode = "annotated"
            is_vlm_checkpoint = True
            logger.info(
                f"VLM QA cadence: auto-injecting annotated preview "
                f"(mutation #{count}, final_step={params.final_step})"
            )

    # Get canonicalized includes metadata
    if params.includes:
        meta = get_injection_metadata(params.includes)
        includes_canonical = meta["includes_canonical"]
        prelude_hash = meta["prelude_hash"]
    else:
        includes_canonical = []
        prelude_hash = None

    diagnostics = {
        "includes": includes_canonical,
        "prelude_hash": prelude_hash,
        "validate_bounds": params.validate_bounds,
        "bounds_type": params.bounds_type,
        "bounds_source": params.bounds_source,
        "bounds_scope": params.bounds_scope,
        "artboard_index": params.artboard_index,
        "is_vlm_checkpoint": is_vlm_checkpoint,
    }

    # Create a descriptive command_type for CEP panel
    # Priority: description > script snippet
    if desc:
        command_type = desc[:50]  # Limit length for display
    else:
        # Extract first meaningful line from script as fallback
        lines = [l.strip() for l in script.split('\n') if l.strip() and not l.strip().startswith('//')]
        preview = lines[0][:40] if lines else "script"
        command_type = f"script: {preview}..."

    logger.info(f"execute_script: {command_type} ({script_len} chars)")

    try:
        response = await execute_script_with_context(
            script=script,
            command_type=command_type,
            tool_name="illustrator_execute_script",
            params={"description": desc or "raw script", "length": script_len},
            timeout=params.timeout,
            includes=params.includes
        )

        # Optional bounds validation after execution
        if params.validate_bounds:
            ab_idx = params.artboard_index if params.artboard_index is not None else 'null'
            check_script = f"""
            countItemsOnArtboard({{
                artboardIndex: {ab_idx},
                boundsType: "{params.bounds_type}",
                boundsSource: "{params.bounds_source}",
                ignoreHidden: {str(params.ignore_hidden).lower()},
                ignoreLocked: {str(params.ignore_locked).lower()},
                policy: "fully-contained",
                scope: "{params.bounds_scope}"
            }});
            """
            try:
                check_response = await execute_script_with_context(
                    script=check_script,
                    command_type="bounds_validation",
                    tool_name="illustrator_execute_script",
                    includes=["validate"]
                )
                # CEP returns {"success": bool, "result": "JSON string"}
                cep_result = check_response.get("result", {})
                if isinstance(cep_result, str):
                    cep_result = json.loads(cep_result)

                # Check for validation errors (e.g., invalid artboard index)
                if cep_result.get("ok") is False or cep_result.get("error"):
                    error_info = cep_result.get("error", {})
                    error_msg = error_info.get("message", "unknown error") if isinstance(error_info, dict) else str(error_info)
                    warnings.append(f"Bounds validation failed: {error_msg}")
                else:
                    # Extract inner result (the actual validation data)
                    inner_result = cep_result.get("result", "{}")
                    if isinstance(inner_result, str):
                        bounds = json.loads(inner_result)
                    else:
                        bounds = inner_result

                    # Always include validation result in diagnostics when validation runs
                    if bounds:
                        diagnostics["validation_result"] = bounds

                        # Add warning if items are off-artboard
                        if bounds.get('off_artboard', 0) > 0:
                            warnings.append(
                                f"{bounds['off_artboard']} items outside artboard bounds "
                                f"(policy: fully-contained, {params.bounds_type}Bounds)"
                            )
            except Exception as e:
                warnings.append(f"Bounds validation failed: {e}")

        # Log errors for debugging
        context = f"execute_script: {desc}" if desc else "execute_script"

        # B1: Inject preview_state into diagnostics BEFORE serialization
        # (eliminates the old json.loads→mutate→json.dumps roundtrip)
        has_error = response.get("error") is not None
        diagnostics["preview_state"] = "pre_execution" if has_error else "post_execution"

        # Return standardized envelope
        envelope = format_envelope(
            response=response,
            context=context,
            warnings=warnings,
            diagnostics=diagnostics
        )

        # Auto-preview: export thumbnail and return as ImageContent
        if params.return_preview:
            try:
                preview_result = await _generate_preview(
                    params=params,
                    timeout=params.timeout
                )
                if preview_result:
                    # Annotated mode: overlay numbered boxes + return annotation map
                    if params.preview_mode == "annotated":
                        import base64 as _b64
                        raw_bytes = _b64.b64decode(preview_result.data)
                        annotated_bytes, annotation_result = await _annotate_preview(
                            img_bytes=raw_bytes,
                            max_items=params.preview_max_items,
                            timeout=params.timeout,
                            probe_points=params.probe_points,
                        )
                        ann_b64 = _b64.b64encode(annotated_bytes).decode('utf-8')
                        result_parts = [
                            TextContent(type="text", text=envelope),
                            ImageContent(
                                type="image",
                                data=ann_b64,
                                mimeType=preview_result.mimeType,
                            ),
                            TextContent(
                                type="text",
                                text=json.dumps(annotation_result, indent=2),
                            ),
                        ]
                        # Cognitive Forcing Function: append checkpoint
                        # instruction as absolute LAST element so it has
                        # maximum recency weight in the LLM's attention.
                        if is_vlm_checkpoint:
                            result_parts.append(TextContent(
                                type="text",
                                text=VLM_CHECKPOINT_INSTRUCTION.format(
                                    count=_counter.value
                                ),
                            ))
                        return result_parts
                    else:
                        return [
                            TextContent(type="text", text=envelope),
                            preview_result
                        ]
                else:
                    # B2: Rebuild envelope with added warning (reuse diagnostics,
                    # don't call format_envelope a second time with stale state)
                    warnings.append("Preview generation returned empty")
                    env_text = format_envelope(
                        response=response,
                        context=context,
                        warnings=warnings,
                        diagnostics=diagnostics
                    )
                    if is_vlm_checkpoint:
                        return [
                            TextContent(type="text", text=env_text),
                            TextContent(type="text", text=VLM_CHECKPOINT_INSTRUCTION.format(count=_counter.value)),
                        ]
                    return env_text
            except Exception as e:
                # B2: Single rebuild with the preview failure warning
                warnings.append(f"Preview failed: {e}")
                env_text = format_envelope(
                    response=response,
                    context=context,
                    warnings=warnings,
                    diagnostics=diagnostics
                )
                if is_vlm_checkpoint:
                    return [
                        TextContent(type="text", text=env_text),
                        TextContent(type="text", text=VLM_CHECKPOINT_INSTRUCTION.format(count=_counter.value)),
                    ]
                return env_text

        return envelope

    except Exception as e:
        # B3: Decrement counter so failed executions don't pollute cadence
        _counter.decrement()
        logger.error(f"Script execution failed: {str(e)}")
        raise


# ── Backward-compatible re-exports ──────────────────────────────────
# These ensure existing imports like `from illustrator_mcp.tools.execute import X`
# continue to work from tests and import_svg.py.
from illustrator_mcp.tools.path_boolean import (  # noqa: E402, F401
    ExecuteTaskInput,
    PathBooleanInput,
    illustrator_execute_task,
    illustrator_path_boolean,
)

__all__ = [
    # Cadence
    "_MutationCounter", "_counter", "VLM_QA_CADENCE", "VLM_CHECKPOINT_INSTRUCTION",
    "get_mutation_count", "reset_mutation_count",
    # Preview
    "_build_export_script", "_capture_artboard", "_capture_artboard_png",
    "_generate_preview", "_COLLECT_ITEMS_JSX", "_filter_items", "_annotate_preview",
    # Execute script
    "ExecuteScriptInput", "illustrator_execute_script",
    # Re-exports from path_boolean
    "ExecuteTaskInput", "PathBooleanInput",
    "illustrator_execute_task", "illustrator_path_boolean",
]
