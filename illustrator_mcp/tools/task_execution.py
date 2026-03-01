"""
Path Boolean and Execute Task tools.

Contains the structured task protocol tool (execute_task) and the
Python-Clipper-backed path boolean tool (path_boolean).
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import Field, model_validator
from mcp.types import ImageContent, TextContent

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, build_envelope_dict
from illustrator_mcp.errors import make_envelope
from illustrator_mcp.protocol import TaskPayload, TaskReport, format_task_report
from illustrator_mcp.tools.base import ToolInputBase, TOOL_ANNOTATIONS
from illustrator_mcp.tools.cadence import (
    _counter, VLM_QA_CADENCE, VLM_CHECKPOINT_INSTRUCTION,
    format_z_telemetry,
)
from illustrator_mcp.tools.preview import (
    _capture_artboard, _annotate_preview,
    _guard_checkpoint, GuardCheckpointResult,
)

logger = logging.getLogger("illustrator_mcp")

# Ops that create new items and don't need target collection.
# Must stay in sync with OP_CLASS "doc" entries in ops_core.jsx.
_CREATION_OPS = frozenset({
    "element_create", "element_create_batch", "element_create_multi",
    "text_create", "layer_create",
})

_TEMPLATES_DIR = Path(__file__).parent.parent / "resources" / "templates"


def _taskreport_first_error(report_data: dict, task_name: str) -> dict:
    """Extract first TaskReport error into canonical {code, message, suggestions} shape.

    Handles nested ``{ok, error:{...}}`` shapes from ``makeError()``
    and falls back to :func:`create_structured_error` for unknown formats.
    """
    from illustrator_mcp.errors import create_structured_error

    errors = report_data.get("errors", [])
    if not errors:
        return {"code": "R009", "message": f"Task '{task_name}' failed", "suggestions": []}

    first = errors[0]
    # Unwrap nested {ok, error:{...}} shape from makeError()
    if isinstance(first, dict) and "error" in first and isinstance(first["error"], dict):
        first = first["error"]

    if isinstance(first, dict) and "code" in first and "message" in first:
        out = {
            "code": first["code"],
            "message": first["message"],
            "suggestions": first.get("suggestions", []),
        }
        out["operation"] = first.get("operation", task_name)
        return out

    # Fallback: classify via create_structured_error
    msg = first.get("message", str(first)) if isinstance(first, dict) else str(first)
    s = create_structured_error(msg)
    return {
        "code": s.code, "message": s.message,
        "suggestions": s.suggestions, "operation": task_name,
    }


def _dedup_warnings(*warning_lists: list) -> list:
    """Merge warning lists preserving order, removing duplicates."""
    seen: set = set()
    result: list = []
    for wl in warning_lists:
        for w in (wl or []):
            if w not in seen:
                seen.add(w)
                result.append(w)
    return result


_jsx_template_cache: dict[str, tuple[int, str]] = {}  # name → (mtime_ns, content)


def _load_jsx_template(name: str) -> str:
    """Load a .jsx template from resources/templates/ (mtime-cached).

    Uses st_mtime_ns for cache invalidation so template changes are
    picked up without server restart. One stat() call per load (~0.1ms).
    """
    path = _TEMPLATES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"JSX template not found: {path}")
    mtime_ns = path.stat().st_mtime_ns
    cached = _jsx_template_cache.get(name)
    if cached and cached[0] == mtime_ns:
        return cached[1]
    content = path.read_text(encoding="utf-8")
    _jsx_template_cache[name] = (mtime_ns, content)
    return content


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
    
    compute_fn: Optional[str] = Field(
        default=None,
        description=(
            "JSX code for compute logic. Receives (items, params, report), "
            "must return actions array. Omit for SOC batch-only mode."
        ),
    )
    
    apply_fn: Optional[str] = Field(
        default=None,
        description=(
            "JSX code for apply logic. Receives (actions, report), modifies items. "
            "Omit for SOC batch-only mode (ops in the payload are the apply step)."
        ),
    )
    
    @model_validator(mode="after")
    def _check_fn_consistency(self):
        if self.compute_fn is not None and self.apply_fn is None:
            raise ValueError(
                "compute_fn requires apply_fn. If you are running SOC ops batches, "
                "omit both compute_fn and apply_fn."
            )
        return self

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

    clip_box: Optional[List[float]] = Field(
        default=None,
        description=(
            "Optional high-resolution crop region: [xmin, ymin, xmax, ymax] in "
            "screen-space Y-down points.  See illustrator_execute_script for details."
        ),
    )


# ── Level 3/4 preprocessing helper ──────────────────────────────

def _preprocess_element_create(payload_data: dict) -> None:
    """Preprocess polar handles and mirror modifiers (mutates in-place).

    Pipeline order:
      1. Validate guards (type, mutual exclusion)
      2. If 'handles': resolve polar/relative → absolute triplets
      3. If 'mirror': mirror resolved points (including handles) + dedup seam
      4. Strip preprocess-only keys (handles, mirror, mirrorOrigin)
    """
    params = payload_data.get("params", {})

    # Guard: only for path type with points
    ptype = params.get("type")
    if ptype != "path":
        # Clean up orphan preprocess keys on non-path types
        params.pop("handles", None)
        params.pop("mirror", None)
        params.pop("mirrorOrigin", None)
        return
    if "points" not in params:
        return

    # Mutual exclusion: handles + smooth
    if params.get("handles") and params.get("smooth"):
        raise ValueError(
            "handles and smooth are mutually exclusive. "
            "Use handles for explicit Bézier control, or smooth for auto Catmull-Rom."
        )

    # Orphan mirrorOrigin without mirror
    if params.get("mirrorOrigin") is not None and not params.get("mirror"):
        params.pop("mirrorOrigin", None)

    from illustrator_mcp.curves import resolve_polar_handles, mirror_points

    # Step 1: Resolve polar/relative handles → absolute triplets
    if params.get("handles"):
        params["points"] = resolve_polar_handles(params["points"], params["handles"])
        del params["handles"]

    # Step 2: Mirror resolved points (including handles) + dedup seam
    if params.get("mirror"):
        params["points"] = mirror_points(
            params["points"], params["mirror"], params.get("mirrorOrigin")
        )
        params["closed"] = True  # mirrored paths are always closed
        del params["mirror"]
        params.pop("mirrorOrigin", None)


_TASK_NAME = "illustrator_execute_task"


@mcp.tool(name=_TASK_NAME, annotations=TOOL_ANNOTATIONS[_TASK_NAME])
async def illustrator_execute_task(params: ExecuteTaskInput) -> Union[str, list]:
    """Execute a structured task using the Task Protocol v2.1.

    CONTRACT: readOnly=False, destructive=True, idempotent=False, openWorld=False

    WHEN TO USE:
      - Creating/modifying elements with declarative ops (element_create, style_set, etc.)
      - Batch element creation (element_create_batch)
      - Any operation that benefits from structured error reports and target selectors

    EXAMPLES:
      Smooth curve: illustrator_execute_task(payload={task: "element_create", params: {
        type: "path", points: [[0,50],[50,0],[100,50],[150,0]],
        smooth: true, tension: 0.5, fill: {r: 0, g: 150, b: 136}}})
      Batch shapes: illustrator_execute_task(payload={task: "element_create_batch", params: {
        template: {type: "ellipse", rx: 4, ry: 3}, array: {count: 47, startX: 180, spacingX: 15}}})
      Grid layout: illustrator_execute_task(payload={task: "element_create_batch", params: {
        template: {type: "rect", w: 8, h: 8}, array: {count: 50, cols: 10, spacingX: 15, spacingY: 15}}})

    TARGET SELECTORS:
      {type: "selection"} — current selection (default)
      {type: "layer", layer: "Layer 1"} — all items on layer
      {type: "query", itemType: "PathItem", pattern: "axis_*"} — pattern match
      {type: "all", recursive: true} — all items in document
      {type: "id", ids: ["A1", "A2"]} — stable MCP ID targeting

    OPTIONS:
      dryRun: true — compute actions without applying
      trace: true — include execution trace in report
      assignIds: true — write unique IDs to item.note (opt-in)

    NOTES:
      - All task+params must be wrapped in a 'payload' field
      - For boolean ops use illustrator_path_boolean, not execute_task
      - For raw SVG path data use illustrator_path_import_svg
    """
    # ── SVG d-param removed — redirect to path_import_svg ──────
    payload = params.payload
    if payload.task == "element_create" and "d" in payload.params:
        return make_envelope(
            ok=False,
            error=(
                "SVG 'd' attribute is no longer accepted in element_create. "
                "Use 'path_import_svg' for existing SVG data, or "
                "'drawPathPoints' (in execute_script with includes: ['geometry']) for new paths."
            ),
            diagnostics={"task": payload.task},
        )

    # Build the execution script
    # SOC batch mode: force kind="creation" so pipeline skips collect
    # and doesn't early-return before reaching compute stage.
    payload_data = params.payload.model_dump(mode="json")

    # ── Level 3/4 preprocessing: polar handles + mirror ──────
    if payload.task == "element_create":
        _preprocess_element_create(payload_data)

    # Auto-detect creation ops that don't need target collection
    # (must stay in sync with OP_CLASS "doc" entries in ops_core.jsx)
    is_creation_op = payload.task in _CREATION_OPS
    if params.compute_fn is None and (not payload.targets or is_creation_op):
        if "options" not in payload_data:
            payload_data["options"] = {}
        payload_data["options"]["kind"] = "creation"
        logger.debug(
            "execute_task: injected kind=creation for task=%s (targets=%s)",
            payload.task, payload.targets,
        )
    payload_json = json.dumps(payload_data)
    
    # Build compute/apply function blocks
    if params.compute_fn is not None:
        compute_block = f"function compute(items, params, report) {{\n{params.compute_fn}\n}}"
    else:
        # SOC batch mode: load template from .jsx file (IDE-checkable, no inline strings)
        compute_block = _load_jsx_template("compute_soc_batch.jsx")

    if params.apply_fn is not None:
        apply_block = f"function apply(actions, report) {{\n{params.apply_fn}\n}}"
    else:
        apply_block = "var apply = null;  // SOC batch mode: no apply step"

    script = f"""
// Compute function
{compute_block}

// Apply function
{apply_block}

// Execute task
var payload = {payload_json};
var report = executeTask(
    payload,
    {params.collect_fn},
    compute,
    apply
);

// ── Slim batchReport before serialization to prevent truncation ──
// Replace the verbose batchReport with a compact summary.
// ExtendScript's doScript return has a string length limit (~1KB for some
// bridge modes) and the full batchReport easily exceeds it.
if (report.batchReport) {{
    var _br = report.batchReport;
    var _slim = {{
        ok: _br.ok,
        createdIds: _br.createdIds || [],
        stats: _br.stats || {{}},
        warnings: _br.warnings || [],
        opSummary: [],
        opSummaryTruncated: false
    }};
    // Compact per-op summary (~50 bytes each, safe under truncation limit)
    if (_br.ops) {{
        var _maxSummary = 200;
        var _len = _br.ops.length < _maxSummary ? _br.ops.length : _maxSummary;
        for (var _oi = 0; _oi < _len; _oi++) {{
            __mcp_check();
            var _op = _br.ops[_oi];
            _slim.opSummary.push({{
                task: _op.task,
                ok: _op.ok,
                tr: _op.targets_resolved || 0,
                mod: (_op.data && typeof _op.data.modified === "number") ? _op.data.modified : null,
                err: (_op.error && _op.error.code) ? _op.error.code : null
            }});
        }}
        if (_br.ops.length > _maxSummary) {{
            _slim.opSummaryTruncated = true;
        }}
    }}
    // Preserve first op error if batch failed
    if (!_br.ok && _br.ops) {{
        for (var _ei = 0; _ei < _br.ops.length; _ei++) {{
            __mcp_check();
            if (!_br.ops[_ei].ok && _br.ops[_ei].error) {{
                _slim.firstError = _br.ops[_ei].error;
                break;
            }}
        }}
    }}
    report.batchReport = _slim;
}}
JSON.stringify(report);
"""
    
    # ── Auto-includes: inject libraries the generated script requires ──
    # executeTask() needs task_pipeline; SOC batch mode needs ops_core
    # for executeOpBatch(). The ops_* modules register handlers via
    # registerOpHandler(); without them, JSX returns V003 "Unknown op".
    auto = [
        "polyfills", "task_pipeline", "ops_core",
        "ops_element", "ops_layer", "ops_style", "ops_text",
        "ops_group", "ops_align", "ops_measure", "ops_compound",
    ]

    # Dedup + stable-order: auto includes first, then user includes
    seen = set(auto)
    all_includes = list(auto)
    for inc in (params.includes or []):
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

        # ── Phase 1: Canonical unwrap + classify ──
        base = build_envelope_dict(response, context=context, diagnostics=diagnostics)
        if not base["ok"]:
            return json.dumps(base)  # short-circuit: bridge/injection/JSX error

        # ── Phase 2: Parse TaskReport from classified result ──
        local_warnings = []
        is_dry_run = params.payload.options.dryRun if params.payload.options else False
        if is_dry_run:
            diagnostics["preview_state"] = "pre_execution"

        # VLM QA Cadence: soft-override for execute_task
        # return_preview tri-state: None=allow, True=force, False=suppress
        if is_task_checkpoint and params.return_preview is False and not params.final_step:
            local_warnings.append(
                f"VLM QA checkpoint skipped (mutation #{count}). "
                "Consider using return_preview=True to visually verify."
            )
            is_task_checkpoint = False

        mode = params.preview_mode or "annotated"
        if mode not in ("annotated", "artboard"):
            local_warnings.append(f"Unknown preview_mode '{mode}', defaulting to 'annotated'")
            mode = "annotated"

        merged_warnings = _dedup_warnings(base.get("warnings", []), local_warnings)
        merged_diag = {**base.get("diagnostics", {}), **diagnostics}

        _envelope_built = False  # Track if fallback already built the envelope
        report_data = {}  # Initialize before try so except-handler can inspect it

        try:
            raw_result = base.get("result")
            if isinstance(raw_result, str):
                report_data = json.loads(raw_result)
            elif isinstance(raw_result, dict):
                report_data = raw_result
            else:
                report_data = {}
            report = TaskReport.model_validate(report_data)
            formatted = format_task_report(report, params.payload.task)
        except Exception as exc:
            logger.warning(f"Failed to parse TaskReport: {exc}")
            parse_diag = {**merged_diag, "taskreport_parse": {"type": type(raw_result).__name__}}
            if isinstance(raw_result, str):
                parse_diag["taskreport_parse"]["excerpt"] = raw_result[:200]

            # ── Degraded fallback: JSON parsed but Pydantic validation failed ──
            # Preserve top-level ok/errors/warnings from report_data instead of
            # silently erasing them. Adds fallback_used diagnostic flag.
            if isinstance(report_data, dict) and "ok" in report_data:
                fallback_ok = report_data.get("ok", False)
                fallback_warnings = []
                # Preserve op-level errors/warnings even if types are imperfect
                raw_errors = report_data.get("errors", [])
                raw_warnings_list = report_data.get("warnings", [])
                if isinstance(raw_errors, list):
                    for e in raw_errors[:5]:
                        fallback_warnings.append(f"[op-error] {e}")
                if isinstance(raw_warnings_list, list):
                    for w in raw_warnings_list[:5]:
                        fallback_warnings.append(f"[op-warn] {w}")
                fallback_warnings.append(
                    "TaskReport validation failed; using degraded summary. "
                    "Some op-level errors may be missing."
                )
                parse_diag["taskreport_parse"]["fallback_used"] = True
                stats = report_data.get("stats", {})
                formatted = (
                    f"{'✓' if fallback_ok else '✗'} Task: {params.payload.task}\n"
                    f"  Stats: {stats.get('itemsProcessed', '?')} ops, "
                    f"{stats.get('itemsCreated', '?')} created, "
                    f"{stats.get('itemsModified', '?')} modified"
                )
                # Create minimal report-like object for guard/preview
                report = type('FallbackReport', (), {
                    'ok': fallback_ok,
                    'warnings': [],
                    'errors': [],
                })()
                merged_warnings = _dedup_warnings(merged_warnings, fallback_warnings)
                merged_diag = parse_diag
                envelope = make_envelope(
                    ok=fallback_ok,
                    result={"formatted": formatted, "report": report_data},
                    warnings=merged_warnings,
                    diagnostics=merged_diag,
                )
                _envelope_built = True
            else:
                # Raw string truncated / unparseable — hard fail with R010
                return make_envelope(
                    ok=False,
                    error={"code": "R010",
                           "message": f"Could not parse TaskReport: {exc}",
                           "suggestions": ["Check JSX script output format"]},
                    warnings=merged_warnings,
                    diagnostics=parse_diag,
                )

        # ── Phase 3: Final envelope via make_envelope ──
        if not is_dry_run:
            merged_diag["preview_state"] = "post_execution" if report.ok else "error"

        if not _envelope_built:
            if report.ok:
                envelope = make_envelope(
                    ok=True,
                    result={"formatted": formatted, "report": report_data},
                    warnings=merged_warnings,
                    diagnostics=merged_diag,
                )
            else:
                err = _taskreport_first_error(report_data, params.payload.task)
                stats = report_data.get("stats", {})
                merged_diag["stats"] = {
                    k: stats.get(k, 0)
                    for k in ("itemsProcessed", "itemsCreated", "itemsModified", "itemsSkipped")
                }
                envelope = make_envelope(
                    ok=False,
                    error=err,
                    warnings=merged_warnings,
                    diagnostics=merged_diag,
                )

        # ── Occlusion guard: run AFTER task execution, BEFORE preview ──
        guard_telemetry = {}
        gcp = None
        if is_task_checkpoint:
            gcp = await _guard_checkpoint(
                timeout=30.0,
                checkpoint_label="execute_task",
            )
            guard_telemetry = gcp.guard_telemetry
            merged_diag["guard_status"] = gcp.guard_status

            if gcp.should_abort:
                merged_diag.update(gcp.diag_extras)
                merged_warnings.append(gcp.abort_message)
                # Rebuild envelope with abort info
                envelope = make_envelope(
                    ok=report.ok if 'report' in dir() else False,
                    result=envelope if isinstance(envelope, str) else None,
                    warnings=merged_warnings,
                    diagnostics=merged_diag,
                )
                # Return abort parts: envelope + evidence + telemetry + checkpoint
                abort_parts = [TextContent(type="text", text=envelope)]
                try:
                    evidence_png = await _capture_artboard(
                        max_dim=800, timeout=15.0,
                    )
                    if evidence_png:
                        import base64 as _b64
                        abort_parts.append(TextContent(
                            type="text",
                            text="Evidence preview (raw) — guard aborted before annotation.",
                        ))
                        abort_parts.append(ImageContent(
                            type="image",
                            data=_b64.b64encode(evidence_png).decode('utf-8'),
                            mimeType="image/png",
                        ))
                except Exception as e:
                    logger.debug("Evidence preview skipped: %s", e)
                if gcp.telemetry_text:
                    abort_parts.append(TextContent(
                        type="text", text=gcp.telemetry_text,
                    ))
                abort_parts.append(TextContent(
                    type="text",
                    text=VLM_CHECKPOINT_INSTRUCTION.format(count=_counter.value),
                ))
                return abort_parts
            else:
                merged_warnings.extend(gcp.warn_messages)
        else:
            merged_diag["guard_status"] = "skipped"

        # ── Auto-Grounding: preview at cadence, manual request, or final_step ──
        should_preview = (
            (is_task_checkpoint or params.return_preview is True)
            and not is_dry_run
            and not (gcp and gcp.should_abort)
        )
        if should_preview:
            try:
                import base64 as _b64
                raw_png = await _capture_artboard(
                    max_dim=1024, timeout=30.0,
                    clip_box=params.clip_box,
                )
                if raw_png:
                    if mode == "annotated":
                        annotated_bytes, annotation_result = await _annotate_preview(
                            img_bytes=raw_png,
                            max_items=200,
                            timeout=30.0,
                            clip_box=params.clip_box,
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
                        if params.clip_box:
                            result_parts.append(TextContent(
                                type="text",
                                text=(
                                    f"\u26a0\ufe0f CLIP BOX ACTIVE: This preview shows a "
                                    f"high-resolution crop of region "
                                    f"{params.clip_box} (screen-space Y-down, points). "
                                    f"All element IDs and coordinates in the annotation "
                                    f"map are in GLOBAL document coordinates. "
                                    f"Use global coordinates for all subsequent edits."
                                ),
                            ))
                    else:
                        raw_b64 = _b64.b64encode(raw_png).decode('utf-8')
                        result_parts = [
                            TextContent(type="text", text=envelope),
                            ImageContent(
                                type="image",
                                data=raw_b64,
                                mimeType="image/png",
                            ),
                        ]
                    if is_task_checkpoint:
                        # Z-order telemetry (task checkpoints)
                        if gcp and gcp.telemetry_text:
                            result_parts.append(TextContent(
                                type="text",
                                text=gcp.telemetry_text,
                            ))
                        result_parts.append(TextContent(
                            type="text",
                            text=VLM_CHECKPOINT_INSTRUCTION.format(
                                count=_counter.value
                            ),
                        ))
                    return result_parts
            except Exception as e:
                logger.warning(f"Auto-grounding overlay failed (non-fatal): {e}")

        # Fallback: text-only envelope (+ telemetry + checkpoint instruction if cadence)
        if is_task_checkpoint:
            fallback_parts = [TextContent(type="text", text=envelope)]
            if gcp and gcp.telemetry_text:
                fallback_parts.append(TextContent(type="text", text=gcp.telemetry_text))
            fallback_parts.append(TextContent(
                type="text",
                text=VLM_CHECKPOINT_INSTRUCTION.format(count=_counter.value),
            ))
            return fallback_parts
        return envelope

    except Exception as e:
        # B3: Decrement counter so failed tasks don't pollute cadence
        _counter.decrement()
        logger.error(f"Task execution failed: {str(e)}")
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


_BOOL_NAME = "illustrator_path_boolean"


@mcp.tool(name=_BOOL_NAME, annotations=TOOL_ANNOTATIONS[_BOOL_NAME])
async def illustrator_path_boolean(params: PathBooleanInput) -> str:
    """Perform boolean operations (subtract, unite, intersect, xor) on paths.

    CONTRACT: readOnly=False, destructive=True, idempotent=False, openWorld=False

    WHEN TO USE:
      - Combining shapes (unite), cutting holes (subtract), finding overlaps (intersect)
      - Any shape sculpting that needs boolean geometry

    PIPELINE:
      1. Extract geometry from Illustrator paths (ExtendScript)
      2. Flatten Bezier curves if present (Python)
      3. Run boolean operation via Clipper (Python)
      4. Reconstruct result as PathItem or CompoundPathItem (ExtendScript)
      5. Delete originals on success (if delete_originals=True)

    EXAMPLES:
      illustrator_path_boolean(operation="unite", subject="body_id", clip=["wing_id"])
      illustrator_path_boolean(operation="subtract", subject="plate_id", clip=["hole_id"])

    NOTES:
      - Operates on fill geometry only — strokes are ignored (warning emitted)
      - Simple results produce PathItem; shapes with holes produce CompoundPathItem
      - Subject and clip identified by MCP ID (@mcp:id in item.note)
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
        # Verify pyclipper is actually available (not cached as None)
        from illustrator_mcp.geometry import pyclipper as _pc_check
        if _pc_check is None:
            raise ImportError("pyclipper cached as None — force reload")
    except ImportError:
        # Module may have been cached before pyclipper was installed.
        # Force-reload geometry to pick up newly installed pyclipper.
        try:
            import importlib
            import illustrator_mcp.geometry as _geo_mod
            importlib.reload(_geo_mod)
            path_boolean = _geo_mod.path_boolean
            flatten_path = _geo_mod.flatten_path
            Region = _geo_mod.Region
        except ImportError as e:
            return make_envelope(
                ok=False,
                error=str(e),
                diagnostics={"tool": "path_boolean", "hint": "pip install pyclipper"},
            )

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
        return make_envelope(
            ok=False,
            error=f"Geometry extraction failed: {e}",
            diagnostics=diagnostics,
        )

    # Parse extraction result
    # Bridge response may come as:
    #   {result: '{"paths":...}'}            — direct string
    #   {result: {ok:true, data:'...'}}       — host.jsx envelope
    #   {result: {paths:[...]}}              — already parsed dict
    extract_result = extract_response.get("result", "{}")
    logger.debug(
        "path_boolean extract_response keys=%s, result type=%s, result preview=%.200s",
        list(extract_response.keys()), type(extract_result).__name__,
        str(extract_result)[:200],
    )

    # Unwrap host.jsx {ok, data} envelope if present
    if isinstance(extract_result, dict) and "data" in extract_result:
        extract_result = extract_result["data"]
        logger.debug("path_boolean: unwrapped ok/data envelope, inner type=%s", type(extract_result).__name__)

    if isinstance(extract_result, str):
        try:
            geo_data = json.loads(extract_result)
        except json.JSONDecodeError:
            return make_envelope(
                ok=False,
                error=f"Failed to parse geometry: {extract_result[:200]}",
                diagnostics=diagnostics,
            )
    else:
        geo_data = extract_result

    if geo_data.get("error"):
        return make_envelope(
            ok=False,
            error=geo_data.get("message", "Geometry extraction error"),
            error_code=geo_data.get("errorCode"),
            diagnostics=diagnostics,
        )

    warnings = geo_data.get("warnings", [])
    paths = geo_data.get("paths", [])

    if len(paths) < 2:
        return make_envelope(
            ok=False,
            error=f"Need at least 2 paths (subject + clip), got {len(paths)}",
            diagnostics=diagnostics,
        )

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
        return make_envelope(
            ok=False,
            error=str(e),
            diagnostics=diagnostics,
        )

    # ── Step 3: Run Clipper boolean ─────────────────────────────
    try:
        regions: list[Region] = path_boolean(
            subject=subject_contour,
            clips=clip_contours,
            operation=params.operation,
        )
    except Exception as e:
        return make_envelope(
            ok=False,
            error=f"Boolean operation failed: {e}",
            diagnostics=diagnostics,
        )

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
        return make_envelope(
            ok=True,
            result={"ids": [], "regionCount": 0, "message": "Boolean result is empty"},
            warnings=warnings,
            diagnostics=diagnostics,
        )

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
        return make_envelope(
            ok=False,
            error=f"Reconstruction failed: {e}",
            warnings=warnings + ["WARNING: Original paths were NOT deleted (reconstruct failed)"],
            diagnostics=diagnostics,
        )

    # Parse reconstruction result
    recon_result = reconstruct_response.get("result", "{}")
    # Unwrap host.jsx {ok, data} envelope if present
    if isinstance(recon_result, dict) and "data" in recon_result:
        recon_result = recon_result["data"]
    if isinstance(recon_result, str):
        try:
            recon_data = json.loads(recon_result)
        except json.JSONDecodeError:
            return make_envelope(
                ok=False,
                error=f"Failed to parse reconstruction result: {recon_result[:200]}",
                warnings=warnings + ["WARNING: Original paths were NOT deleted"],
                diagnostics=diagnostics,
            )
    else:
        recon_data = recon_result

    if recon_data.get("error"):
        return make_envelope(
            ok=False,
            error=recon_data.get("message", "Reconstruction error"),
            warnings=warnings + ["WARNING: Original paths were NOT deleted"],
            diagnostics=diagnostics,
        )

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
            # Unwrap host.jsx {ok, data} envelope if present
            if isinstance(delete_result, dict) and "data" in delete_result:
                delete_result = delete_result["data"]
            if isinstance(delete_result, str):
                try:
                    del_data = json.loads(delete_result)
                    del_warnings = del_data.get("warnings", [])
                    warnings.extend(del_warnings)
                except json.JSONDecodeError:
                    warnings.append("Could not parse deletion result")
        except Exception as e:
            warnings.append(f"Deletion of originals failed: {e}")

    return make_envelope(
        ok=True,
        result=recon_data,
        warnings=warnings,
        diagnostics=diagnostics,
    )
