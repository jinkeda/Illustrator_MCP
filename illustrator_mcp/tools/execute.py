"""
Core execute_script tool for Adobe Illustrator.

This is the PRIMARY tool for interacting with Illustrator.
Following the "Scripting First" pattern (like blender-mcp), most operations
should be done via this tool rather than specialized atomic tools.
"""

import json
import logging
import os
import tempfile
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import Field, model_validator
from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_envelope
from illustrator_mcp.protocol import TaskPayload, TaskReport, format_task_report
from illustrator_mcp.libraries import get_injection_metadata
from illustrator_mcp.tools.base import ToolInputBase
from mcp.types import ImageContent, TextContent

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
    return_preview: bool = Field(
        default=False,
        description="After execution, auto-export a thumbnail and return as ImageContent."
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


async def _capture_artboard_png(
    max_dim: int = 1024,
    timeout: Optional[float] = None,
) -> Optional[bytes]:
    """Export the active artboard as PNG bytes.

    Standalone helper — no dependency on ExecuteScriptInput.
    Returns raw PNG bytes, or None on failure.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_path = tmp.name.replace("\\", "/")
    tmp.close()

    try:
        export_script = f"""
(function() {{
    var doc = app.activeDocument;
    var abIdx = doc.artboards.getActiveArtboardIndex();
    var abRect = doc.artboards[abIdx].artboardRect;
    var abW = abRect[2] - abRect[0];
    var abH = Math.abs(abRect[3] - abRect[1]);
    var maxDim = Math.max(abW, abH);
    var scale = Math.min({max_dim} / maxDim * 100, 100);

    var opts = new ExportOptionsPNG24();
    opts.horizontalScale = scale;
    opts.verticalScale = scale;
    opts.artBoardClipping = true;

    var file = new File("{tmp_path}");
    doc.exportFile(file, ExportType.PNG24, opts);
    return JSON.stringify({{success: true}});
}})();
"""
        resp = await execute_script_with_context(
            script=export_script,
            command_type="preview_export",
            tool_name="_capture_artboard_png",
            timeout=timeout or 30.0,
        )
        if resp.get("error"):
            return None

        if not os.path.isfile(tmp.name):
            return None

        with open(tmp.name, "rb") as f:
            img_bytes = f.read()

        return img_bytes if img_bytes else None
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


async def _generate_preview(
    params: 'ExecuteScriptInput',
    timeout: Optional[float] = None
) -> Optional[ImageContent]:
    """Auto-export a thumbnail for the execute-and-preview feature (P4).

    Delegates to _capture_artboard_png, then wraps result as ImageContent.
    Supports PNG and JPG via params.preview_format.
    """
    import base64

    fmt = params.preview_format
    max_dim = params.preview_max_dim

    if fmt == "jpg":
        # JPG path — can't reuse _capture_artboard_png (PNG-only)
        suffix = ".jpg"
        mime = "image/jpeg"
        opts_class = "ExportOptionsJPEG"
        export_type = "ExportType.JPEG"

        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp_path = tmp.name.replace("\\", "/")
        tmp.close()
        try:
            export_script = f"""
(function() {{
    var doc = app.activeDocument;
    var abIdx = doc.artboards.getActiveArtboardIndex();
    var abRect = doc.artboards[abIdx].artboardRect;
    var abW = abRect[2] - abRect[0];
    var abH = Math.abs(abRect[3] - abRect[1]);
    var maxDim = Math.max(abW, abH);
    var scale = Math.min({max_dim} / maxDim * 100, 100);
    var opts = new {opts_class}();
    opts.horizontalScale = scale;
    opts.verticalScale = scale;
    opts.artBoardClipping = true;
    var file = new File("{tmp_path}");
    doc.exportFile(file, {export_type}, opts);
    return JSON.stringify({{success: true}});
}})();
"""
            resp = await execute_script_with_context(
                script=export_script,
                command_type="preview_export",
                tool_name="illustrator_execute_script",
                timeout=timeout or 30.0,
            )
            if resp.get("error"):
                return None
            if not os.path.isfile(tmp.name):
                return None
            with open(tmp.name, "rb") as f:
                img_bytes = f.read()
            if not img_bytes:
                return None
            return ImageContent(
                type="image",
                data=base64.b64encode(img_bytes).decode('utf-8'),
                mimeType=mime,
            )
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
    else:
        # PNG path — delegate to _capture_artboard_png
        img_bytes = await _capture_artboard_png(max_dim=max_dim, timeout=timeout)
        if not img_bytes:
            return None
        return ImageContent(
            type="image",
            data=base64.b64encode(img_bytes).decode('utf-8'),
            mimeType="image/png",
        )


# JSX script to collect visible item bounds for annotation overlay
_COLLECT_ITEMS_JSX = """
(function() {
    var doc = app.activeDocument;
    var abIdx = doc.artboards.getActiveArtboardIndex();
    var ab = doc.artboards[abIdx].artboardRect;
    var abL = ab[0], abT = ab[1], abR = ab[2], abB = ab[3];
    var MAX = %d;
    var items = [];
    for (var i = 0; i < doc.pageItems.length && items.length < MAX; i++) {
        var it = doc.pageItems[i];
        if (it.hidden) continue;
        try { if (it.guides) continue; } catch(e) {}
        var vb;
        try { vb = it.visibleBounds; } catch(e) { continue; }
        if (vb[2] - vb[0] < 0.5 || vb[1] - vb[3] < 0.5) continue;
        if (vb[2] < abL || vb[0] > abR || vb[3] > abT || vb[1] < abB) continue;
        var mcpId = "";
        var note = "";
        try { note = it.note || ""; } catch(e) {}
        var idx = note.indexOf("@mcp:id:");
        if (idx >= 0) mcpId = note.substring(idx + 8, idx + 44);
        items.push({
            name: it.name || it.typename,
            type: it.typename,
            bounds: [vb[0], vb[1], vb[2], vb[3]],
            mcp_id: mcpId
        });
    }
    return JSON.stringify({artboard: ab, items: items});
})();
"""


def _filter_items(items: list, artboard_rect: list) -> tuple:
    """Filter low-value items before annotation.

    Type-aware rules:
    - Canvas-span: skip items covering ≥90% of artboard area (any type).
    - Thin stroke: skip PathItem/CompoundPathItem/GroupItem < 5pt in
      either dimension.  TextFrames are IMMUNE (small text is meaningful).

    Returns:
        (kept_items, filtered_count)
    """
    ab_w = abs(artboard_rect[2] - artboard_rect[0])
    ab_h = abs(artboard_rect[1] - artboard_rect[3])
    ab_area = ab_w * ab_h

    kept = []
    for item in items:
        b = item.get("bounds", [0, 0, 0, 0])
        w = abs(b[2] - b[0])
        h = abs(b[1] - b[3])
        typ = item.get("type", "")

        # Rule 1: Canvas-span — skip if ≥90% of artboard area
        if ab_area > 0 and (w * h) / ab_area >= 0.9:
            continue

        # Rule 2: Thin stroke — TextFrames are immune
        if typ != "TextFrame" and (w < 5 or h < 5):
            continue

        kept.append(item)

    return kept, len(items) - len(kept)


async def _annotate_preview(
    img_bytes: bytes,
    max_items: int = 200,
    timeout: Optional[float] = None,
) -> tuple:
    """Generate annotated preview with numbered bounding boxes.

    Args:
        img_bytes: Raw PNG bytes of the artboard export.
        max_items: Maximum number of items to annotate.
        timeout: Script execution timeout.

    Returns:
        (annotated_png_bytes, result_dict)
        result_dict always has: {"meta": {...}, "annotations": [...], "warnings": [...]}
    """
    from illustrator_mcp.overlay import (
        composite_overlay,
        get_png_dimensions,
        map_bounds_to_pixels,
        HAS_PILLOW,
    )

    def _result(annotations=None, warnings=None, **meta_extra):
        """Build structured result dict."""
        meta = {
            "bounds_kind": "visibleBounds",
            "max_items": max_items,
            "input_count": meta_extra.pop("input_count", 0),
            "annotated_count": len(annotations) if annotations else 0,
            "filtered_count": meta_extra.pop("filtered_count", 0),
        }
        meta.update(meta_extra)
        return {
            "meta": meta,
            "annotations": annotations or [],
            "warnings": warnings or [],
        }

    if not HAS_PILLOW:
        return img_bytes, _result(
            warnings=["Pillow not installed. Run: pip install illustrator-mcp[overlay]"]
        )

    # 1. Decode PNG dimensions
    png_size = get_png_dimensions(img_bytes)
    if not png_size:
        return img_bytes, _result(warnings=["Could not decode PNG dimensions"])

    # 2. Collect item bounds from Illustrator
    collect_script = _COLLECT_ITEMS_JSX % max_items

    try:
        collect_response = await execute_script_with_context(
            script=collect_script,
            command_type="annotate_collect",
            tool_name="illustrator_execute_script",
            timeout=timeout or 30.0,
        )
    except Exception as e:
        return img_bytes, _result(warnings=[f"Item collection failed: {e}"])

    # 3. Parse response
    raw_result = collect_response.get("result")
    if not raw_result:
        return img_bytes, _result(warnings=["Item collection returned empty"])

    try:
        if isinstance(raw_result, str):
            snapshot = json.loads(raw_result)
        else:
            snapshot = raw_result
    except (json.JSONDecodeError, TypeError):
        return img_bytes, _result(warnings=["Could not parse item collection result"])

    artboard_rect = snapshot.get("artboard")
    if not artboard_rect or len(artboard_rect) != 4:
        return img_bytes, _result(
            warnings=["Missing or invalid artboard bounds — cannot map coordinates"]
        )

    raw_items = snapshot.get("items", [])
    if not raw_items:
        return img_bytes, _result(
            warnings=["No visible items found on artboard"],
            png_px=list(png_size),
            artboard_pt=artboard_rect,
        )

    # 4. Filter low-value items, then map bounds and build annotations
    items, filtered_count = _filter_items(raw_items, artboard_rect)

    pixel_annotations = []
    annotation_entries = []
    warn_list = []

    for i, item in enumerate(items):
        label = str(i + 1)
        bounds_pt = item.get("bounds", [0, 0, 0, 0])
        mcp_id = item.get("mcp_id", "") or ""

        bounds_px = map_bounds_to_pixels(bounds_pt, artboard_rect, png_size)

        pixel_annotations.append({
            "label": label,
            "bounds_px": bounds_px,
        })

        annotation_entries.append({
            "label": label,
            "mcp_id": mcp_id if mcp_id else None,
            "has_mcp_id": bool(mcp_id),
            "name": item.get("name", ""),
            "type": item.get("type", "Item"),
            "bounds_pt": bounds_pt,
        })

    # 5. Composite overlay
    annotated_bytes = composite_overlay(img_bytes, pixel_annotations)

    return annotated_bytes, _result(
        annotations=annotation_entries,
        warnings=warn_list if warn_list else None,
        input_count=len(raw_items),
        filtered_count=filtered_count,
        png_px=list(png_size),
        artboard_pt=artboard_rect,
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
    
    IMPORTANT: Always use -y for Y coordinates when positioning objects.
    Call get_scripting_reference for more detailed syntax examples.
    """
    # Log script execution for telemetry
    script = params.script  # Already resolved by model_validator
    script_len = len(script)
    desc = params.description.strip() if params.description else None

    warnings = []

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
        "artboard_index": params.artboard_index
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
                        )
                        ann_b64 = _b64.b64encode(annotated_bytes).decode('utf-8')
                        return [
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
                    else:
                        return [
                            {"type": "text", "text": envelope},
                            preview_result
                        ]
                else:
                    warnings.append("Preview generation returned empty")
                    return format_envelope(
                        response=response,
                        context=context,
                        warnings=warnings,
                        diagnostics=diagnostics
                    )
            except Exception as e:
                warnings.append(f"Preview failed: {e}")
                return format_envelope(
                    response=response,
                    context=context,
                    warnings=warnings,
                    diagnostics=diagnostics
                )

        return envelope

    except Exception as e:
        logger.error(f"Script execution failed: {str(e)}")
        raise


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
    
    diagnostics = {
        "task": params.payload.task,
        "includes": all_includes
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
            envelope = json.dumps({
                "ok": True,
                "warnings": [],
                "error": None,
                "diagnostics": diagnostics,
                "result": {"formatted": formatted, "report": report_data}
            })

            # ── Auto-Grounding: forcibly inject annotated preview ──
            # The LLM doesn't choose this — every SOC report comes with
            # a visual map so the agent can't skip spatial verification.
            try:
                import base64 as _b64
                raw_png = await _capture_artboard_png(max_dim=1024, timeout=30.0)
                if raw_png:
                    annotated_bytes, annotation_result = await _annotate_preview(
                        img_bytes=raw_png,
                        max_items=200,
                        timeout=30.0,
                    )
                    ann_b64 = _b64.b64encode(annotated_bytes).decode('utf-8')
                    return [
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
            except Exception as e:
                logger.warning(f"Auto-grounding overlay failed (non-fatal): {e}")

            # Fallback: return text-only envelope if overlay failed
            return envelope

        except (json.JSONDecodeError, Exception) as parse_error:
            # Fallback: return raw result in envelope
            logger.warning(f"Failed to parse TaskReport: {parse_error}")
            return format_envelope(
                response=response,
                context=context,
                diagnostics=diagnostics
            )

    except Exception as e:
        logger.error(f"Task execution failed: {str(e)}")
        raise

