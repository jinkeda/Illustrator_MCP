"""
Path Boolean and Execute Task tools.

Contains the structured task protocol tool (execute_task) and the
Python-Clipper-backed path boolean tool (path_boolean).
"""

import json
import logging
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import Field
from mcp.types import ImageContent, TextContent

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_envelope
from illustrator_mcp.protocol import TaskPayload, TaskReport, format_task_report
from illustrator_mcp.tools.base import ToolInputBase
from illustrator_mcp.tools.cadence import (
    _counter, VLM_QA_CADENCE, VLM_CHECKPOINT_INSTRUCTION,
)
from illustrator_mcp.tools.preview import (
    _capture_artboard, _annotate_preview,
)

logger = logging.getLogger("illustrator_mcp")



# ==================== Task Protocol Tool ====================


class ExecuteTaskInput(ToolInputBase):
    """Input for executing a structured task (Task Protocol v2.1)."""
    
    payload: TaskPayload = Field(..., description="Task payload with targets, params, and options")
    
    includes: List[str] = Field(
        default_factory=list,
        description="Additional library includes (e.g. ['ops_core', 'ops_element']). polyfills is always included."
    )
    
    collect_fn: str = Field(
        default="collectTargets",
        description="Collector function name (use standard 'collectTargets' or provide custom)"
    )
    
    compute_fn: str = Field(
        ...,
        description="JSX code for compute logic. Receives (items, params, report), must return actions array."
    )
    
    apply_fn: str = Field(
        ...,
        description="JSX code for apply logic. Receives (actions, report), modifies items."
    )

    return_preview: Optional[bool] = Field(
        default=None,
        description="Request a visual preview. Leave unset to use VLM QA cadence."
    )
    preview_mode: Literal["artboard", "annotated"] = Field(
        default="annotated",
        description="'artboard': raw preview. 'annotated': numbered bounding boxes + annotation map."
    )
    final_step: bool = Field(
        default=False,
        description="Force annotated preview on last SOC task, regardless of cadence. Does NOT override dryRun."
    )


@mcp.tool(
    name="illustrator_execute_task",
    annotations={
        "title": "Execute Structured Task",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False
    }
)
async def illustrator_execute_task(params: ExecuteTaskInput) -> Union[str, list]:
    """
    Execute a structured task using the Task Protocol v2.1.
    
    Benefits over raw execute_script:
    - Standardized payload/report format
    - Automatic timing and error context
    - Declarative target selection (no manual selection micro-ops)
    - Supports dryRun and trace modes
    - Per-item error localization via itemRef
    
    TARGET SELECTORS:
    - {type: "selection"} - Current selection (default)
    - {type: "layer", layer: "Layer 1"} - All items in layer
    - {type: "query", itemType: "PathItem", pattern: "axis_*"} - Pattern match
    - {type: "all", recursive: true} - All items in document
    
    OPTIONS:
    - dryRun: true - Compute actions but don't apply
    - trace: true - Include execution trace in report
    - assignIds: true - Write unique IDs to item.note (opt-in)
    
    Example payload:
        {
            "task": "apply_fill_color",
            "targets": {"type": "selection"},
            "params": {"color": {"r": 255, "g": 0, "b": 0}},
            "options": {"trace": true}
        }
    """
    # ── SVG d-param removed — redirect to path_import_svg ──────
    payload = params.payload
    if payload.task == "element_create" and "d" in payload.params:
        return json.dumps({
            "ok": False,
            "error": (
                "SVG 'd' attribute is no longer accepted in element_create. "
                "Use 'path_import_svg' for existing SVG data, or "
                "'drawPathPoints' (in execute_script with includes: ['geometry']) for new paths."
            ),
            "diagnostics": {"task": payload.task},
        })

    # Build the execution script
    payload_json = json.dumps(params.payload.model_dump())
    
    script = f"""
// Compute function
function compute(items, params, report) {{
{params.compute_fn}
}}

// Apply function  
function apply(actions, report) {{
{params.apply_fn}
}}

// Execute task
var payload = {payload_json};
var report = executeTask(
    payload,
    {params.collect_fn},
    compute,
    apply
);

JSON.stringify(report);
"""
    
    # Dedup + stable-order: polyfills first, then user includes
    seen = {"polyfills"}
    all_includes = ["polyfills"]
    for inc in params.includes:
        if inc not in seen:
            seen.add(inc)
            all_includes.append(inc)
    
    # ── VLM QA Cadence: track mutations for execute_task too ──
    count = _counter.increment()
    is_task_checkpoint = (count % VLM_QA_CADENCE == 0) or params.final_step

    diagnostics = {
        "task": params.payload.task,
        "includes": all_includes,
        "is_vlm_checkpoint": is_task_checkpoint,
    }

    logger.info(f"execute_task: {params.payload.task}")

    try:
        response = await execute_script_with_context(
            script=script,
            command_type=f"task:{params.payload.task}",
            tool_name="illustrator_execute_task",
            params=params.payload.model_dump(),
            includes=all_includes
        )

        context = f"execute_task: {params.payload.task}"

        # Check for pipeline-level errors (connection, library injection, etc.)
        if response.get("error"):
            return format_envelope(response, context=context, diagnostics=diagnostics)

        # Try to parse TaskReport for formatted output
        try:
            result = response.get("result", "{}")
            if isinstance(result, str):
                report_data = json.loads(result)
            else:
                report_data = result

            report = TaskReport.model_validate(report_data)
            formatted = format_task_report(report, params.payload.task)

            # Return envelope with formatted report as result
            is_dry_run = params.payload.options.dryRun if params.payload.options else False
            if is_dry_run:
                diagnostics["preview_state"] = "pre_execution"
            else:
                diagnostics["preview_state"] = "post_execution" if report.ok else "error"

            # ── VLM QA Cadence: soft-override for execute_task ──────────
            # return_preview tri-state semantics:
            #   None  → allow checkpoint preview (default)
            #   True  → force preview (unless dryRun)
            #   False → suppress checkpoint preview (unless final_step)
            warnings = []

            if is_task_checkpoint and params.return_preview is False and not params.final_step:
                warnings.append(
                    f"VLM QA checkpoint skipped (mutation #{count}). "
                    "Consider using return_preview=True to visually verify."
                )
                is_task_checkpoint = False

            # Normalize preview mode with fallback
            mode = params.preview_mode or "annotated"
            if mode not in ("annotated", "artboard"):
                warnings.append(f"Unknown preview_mode '{mode}', defaulting to 'annotated'")
                mode = "annotated"

            envelope = json.dumps({
                "ok": True,
                "warnings": warnings,
                "error": None,
                "diagnostics": diagnostics,
                "result": {"formatted": formatted, "report": report_data}
            })

            # ── Auto-Grounding: preview at cadence, manual request, or final_step ──
            should_preview = (is_task_checkpoint or params.return_preview is True) and not is_dry_run
            if should_preview:
                try:
                    import base64 as _b64
                    raw_png = await _capture_artboard(max_dim=1024, timeout=30.0)
                    if raw_png:
                        if mode == "annotated":
                            annotated_bytes, annotation_result = await _annotate_preview(
                                img_bytes=raw_png,
                                max_items=200,
                                timeout=30.0,
                            )
                            ann_b64 = _b64.b64encode(annotated_bytes).decode('utf-8')
                            result_parts = [
                                TextContent(type="text", text=envelope),
                                ImageContent(
                                    type="image",
                                    data=ann_b64,
                                    mimeType="image/png",
                                ),
                                TextContent(
                                    type="text",
                                    text=json.dumps(annotation_result, indent=2),
                                ),
                            ]
                        else:
                            # "artboard" mode — raw PNG, no overlay
                            raw_b64 = _b64.b64encode(raw_png).decode('utf-8')
                            result_parts = [
                                TextContent(type="text", text=envelope),
                                ImageContent(
                                    type="image",
                                    data=raw_b64,
                                    mimeType="image/png",
                                ),
                            ]
                        # Cognitive Forcing Function for SOC tasks too
                        if is_task_checkpoint:
                            result_parts.append(TextContent(
                                type="text",
                                text=VLM_CHECKPOINT_INSTRUCTION.format(
                                    count=_counter.value
                                ),
                            ))
                        return result_parts
                except Exception as e:
                    logger.warning(f"Auto-grounding overlay failed (non-fatal): {e}")

            # Fallback: text-only envelope (+ checkpoint instruction if cadence)
            if is_task_checkpoint:
                return [
                    TextContent(type="text", text=envelope),
                    TextContent(type="text", text=VLM_CHECKPOINT_INSTRUCTION.format(count=_counter.value)),
                ]
            return envelope

        except Exception as parse_error:
            # Fallback: return raw result in envelope
            logger.warning(f"Failed to parse TaskReport: {parse_error}")
            return format_envelope(
                response=response,
                context=context,
                diagnostics=diagnostics
            )

    except Exception as e:
        # B3: Decrement counter so failed tasks don't pollute cadence
        _counter.decrement()
        logger.error(f"Task execution failed: {str(e)}")
        # Include checkpoint name for recovery if available
        if checkpoint_name:
            raise RuntimeError(
                f"{e}\n\nRecovery: restore checkpoint '{checkpoint_name}' "
                f"via illustrator_history(action='checkpoint_restore', name='{checkpoint_name}')"
            ) from e
        raise


# ==================== Path Boolean Tool ====================


class PathBooleanInput(ToolInputBase):
    """Input for path boolean operations via Python Clipper engine."""
    operation: Literal["subtract", "unite", "intersect", "xor"] = Field(
        ..., description="Boolean operation type"
    )
    subject: str = Field(
        ..., description="MCP ID of subject path (the 'kept' shape)"
    )
    clip: Union[str, List[str]] = Field(
        ..., description="MCP ID(s) of clip path(s) (the 'cutting' shape(s))"
    )
    flatten_tolerance: float = Field(
        default=0.5,
        description="Bézier flatten precision in points (default 0.5pt)"
    )
    max_segments: int = Field(
        default=500,
        description="Max polyline segments per curve (safety cap)"
    )
    delete_originals: bool = Field(
        default=True,
        description="Remove input paths after successful boolean"
    )
    style: str = Field(
        default="subject",
        description="Style transfer: 'subject' (copy from subject), 'none' (no fill/stroke)"
    )
    layer: Optional[str] = Field(
        default=None,
        description="Target layer for result path"
    )
    name: Optional[str] = Field(
        default=None,
        description="Name for result item(s)"
    )


@mcp.tool()
async def illustrator_path_boolean(params: PathBooleanInput) -> str:
    """
    Perform boolean operations (subtract, unite, intersect, xor) on paths.

    Uses Python Clipper (pyclipper) for boolean computation.
    Operates on fill geometry only — strokes are ignored (warning emitted).

    Pipeline:
    1. Extract geometry from Illustrator paths (ExtendScript)
    2. Flatten Bézier curves if present (Python)
    3. Run boolean operation via Clipper (Python)
    4. Reconstruct result as PathItem or CompoundPathItem (ExtendScript)
    5. Delete originals on success (if delete_originals=True)

    Result types:
    - Simple shapes → PathItem
    - Shapes with holes (e.g., donut from subtract) → CompoundPathItem

    Args:
        operation: "subtract", "unite", "intersect", or "xor"
        subject: MCP ID of the subject (kept) path
        clip: MCP ID(s) of the clip (cutting) path(s)
        flatten_tolerance: Bézier flattening precision (points)
        delete_originals: Whether to remove input paths after boolean
        style: "subject" (copy subject's style) or "none"
    """
    # ── Track mutation cadence before any early return ──────────
    # B3: Decremented in except block if execution fails
    _counter.increment()

    try:  # B18: ensure counter is decremented on any early-return error
        return await _path_boolean_impl(params)
    except Exception:
        _counter.decrement()
        raise


async def _path_boolean_impl(params: PathBooleanInput) -> str:
    """Inner implementation of path_boolean, extracted for B18 counter safety."""

    # ── Step 0: Import guard ────────────────────────────────────
    try:
        from illustrator_mcp.geometry import (
            path_boolean, flatten_path, Region,
        )
    except ImportError as e:
        return json.dumps({
            "ok": False,
            "error": str(e),
            "diagnostics": {"tool": "path_boolean", "hint": "pip install illustrator-mcp[geometry]"}
        })

    context = f"path_boolean: {params.operation}"
    diagnostics: Dict[str, Any] = {"operation": params.operation, "tool": "path_boolean"}

    # Normalize clip to list
    clip_ids = params.clip if isinstance(params.clip, list) else [params.clip]
    all_ids = [params.subject] + clip_ids
    diagnostics["subject"] = params.subject
    diagnostics["clips"] = clip_ids

    # ── Step 1: Extract geometry via ExtendScript ───────────────
    extract_script = f"extractPathGeometry({json.dumps(all_ids)})"
    try:
        extract_response = await execute_script_with_context(
            script=extract_script,
            command_type="path_boolean:extract",
            tool_name="illustrator_path_boolean",
            includes=["geo_boolean"],
        )
    except Exception as e:
        return json.dumps({
            "ok": False,
            "error": f"Geometry extraction failed: {e}",
            "diagnostics": diagnostics,
        })

    # Parse extraction result
    extract_result = extract_response.get("result", "{}")
    if isinstance(extract_result, str):
        try:
            geo_data = json.loads(extract_result)
        except json.JSONDecodeError:
            return json.dumps({
                "ok": False,
                "error": f"Failed to parse geometry: {extract_result[:200]}",
                "diagnostics": diagnostics,
            })
    else:
        geo_data = extract_result

    if geo_data.get("error"):
        return json.dumps({
            "ok": False,
            "error": geo_data.get("message", "Geometry extraction error"),
            "errorCode": geo_data.get("errorCode"),
            "diagnostics": diagnostics,
        })

    warnings = geo_data.get("warnings", [])
    paths = geo_data.get("paths", [])

    if len(paths) < 2:
        return json.dumps({
            "ok": False,
            "error": f"Need at least 2 paths (subject + clip), got {len(paths)}",
            "diagnostics": diagnostics,
        })

    # ── Step 2: Flatten Bézier curves if needed ─────────────────
    subject_geo = paths[0]
    clip_geos = paths[1:]
    subject_style = subject_geo.get("style", {})

    def _to_contour(path_data):
        """Convert extracted path data to a flat contour for Clipper.

        Expects canonical per-point format (mcp.geometry.v1):
            points: [{anchor, left, right, pointType}, ...]
        """
        pts = path_data["points"]
        points = [tuple(p["anchor"]) for p in pts]
        if path_data.get("hasHandles"):
            # Default missing left/right to anchor (corner points)
            in_handles = [tuple(p.get("left", p["anchor"])) for p in pts]
            out_handles = [tuple(p.get("right", p["anchor"])) for p in pts]
            points = flatten_path(
                anchors=points,
                left_handles=in_handles,
                right_handles=out_handles,
                closed=path_data.get("closed", True),
                tolerance=params.flatten_tolerance,
                max_segments=params.max_segments,
            )
            warnings.append(
                f"Path '{path_data.get('name', path_data.get('mcpId', '?'))}' "
                f"had curves — flattened to {len(points)} points (tolerance={params.flatten_tolerance}pt)"
            )
        return points

    try:
        subject_contour = _to_contour(subject_geo)
        clip_contours = [_to_contour(cg) for cg in clip_geos]
    except ValueError as e:
        return json.dumps({
            "ok": False,
            "error": str(e),
            "diagnostics": diagnostics,
        })

    # ── Step 3: Run Clipper boolean ─────────────────────────────
    try:
        regions: list[Region] = path_boolean(
            subject=subject_contour,
            clips=clip_contours,
            operation=params.operation,
        )
    except Exception as e:
        return json.dumps({
            "ok": False,
            "error": f"Boolean operation failed: {e}",
            "diagnostics": diagnostics,
        })

    if not regions:
        # Empty result (e.g., subtracting identical shapes)
        if params.delete_originals:
            delete_script = f"deleteByMcpIds({json.dumps(all_ids)})"
            await execute_script_with_context(
                script=delete_script,
                command_type="path_boolean:delete",
                tool_name="illustrator_path_boolean",
                includes=["geo_boolean"],
            )
        return json.dumps({
            "ok": True,
            "result": {"ids": [], "regionCount": 0, "message": "Boolean result is empty"},
            "warnings": warnings,
            "diagnostics": diagnostics,
        })

    # ── Step 4: Reconstruct result in Illustrator ───────────────
    # Convert Region objects to JSON-serializable dicts
    regions_data = []
    for r in regions:
        rd = {"outer": [list(pt) for pt in r.outer]}
        if r.holes:
            rd["holes"] = [[list(pt) for pt in h] for h in r.holes]
        regions_data.append(rd)

    # Determine style to apply
    style_def = {}
    if params.style == "subject":
        style_def = subject_style
    # "none" → empty style_def (Illustrator defaults)

    reconstruct_params = {
        "regions": regions_data,
        "style": style_def,
    }
    if params.layer:
        reconstruct_params["layer"] = params.layer
    if params.name:
        reconstruct_params["name"] = params.name

    reconstruct_script = f"reconstructRegions({json.dumps(reconstruct_params)})"
    try:
        reconstruct_response = await execute_script_with_context(
            script=reconstruct_script,
            command_type="path_boolean:reconstruct",
            tool_name="illustrator_path_boolean",
            includes=["geo_boolean"],
        )
    except Exception as e:
        return json.dumps({
            "ok": False,
            "error": f"Reconstruction failed: {e}",
            "warnings": warnings + ["WARNING: Original paths were NOT deleted (reconstruct failed)"],
            "diagnostics": diagnostics,
        })

    # Parse reconstruction result
    recon_result = reconstruct_response.get("result", "{}")
    if isinstance(recon_result, str):
        try:
            recon_data = json.loads(recon_result)
        except json.JSONDecodeError:
            return json.dumps({
                "ok": False,
                "error": f"Failed to parse reconstruction result: {recon_result[:200]}",
                "warnings": warnings + ["WARNING: Original paths were NOT deleted"],
                "diagnostics": diagnostics,
            })
    else:
        recon_data = recon_result

    if recon_data.get("error"):
        return json.dumps({
            "ok": False,
            "error": recon_data.get("message", "Reconstruction error"),
            "warnings": warnings + ["WARNING: Original paths were NOT deleted"],
            "diagnostics": diagnostics,
        })

    # ── Step 5: Delete originals (only on success) ──────────────
    if params.delete_originals:
        delete_script = f"deleteByMcpIds({json.dumps(all_ids)})"
        try:
            delete_response = await execute_script_with_context(
                script=delete_script,
                command_type="path_boolean:delete",
                tool_name="illustrator_path_boolean",
                includes=["geo_boolean"],
            )
            delete_result = delete_response.get("result", "{}")
            if isinstance(delete_result, str):
                try:
                    del_data = json.loads(delete_result)
                    del_warnings = del_data.get("warnings", [])
                    warnings.extend(del_warnings)
                except json.JSONDecodeError:
                    warnings.append("Could not parse deletion result")
        except Exception as e:
            warnings.append(f"Deletion of originals failed: {e}")

    return json.dumps({
        "ok": True,
        "result": recon_data,
        "warnings": warnings,
        "diagnostics": diagnostics,
    })
