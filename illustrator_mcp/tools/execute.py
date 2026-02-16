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

# ── VLM QA Cadence ──────────────────────────────────────────────────
# Auto-inject annotated preview every N execute_script calls.
# The counter is module-level and resets on server restart.
VLM_QA_CADENCE: int = 5
_mutation_count: int = 0
# TODO: scope to connection/session if scaling to multi-agent SSE/HTTP.
# CONTRACT: any new mutating tool MUST increment this counter.

# Cognitive Forcing Function: injected as the LAST TextContent element
# when cadence fires, forcing the AI to produce reasoning tokens about
# the visual state before it can formulate its next action.
VLM_CHECKPOINT_INSTRUCTION: str = (
    "⚠️ VLM QA CHECKPOINT (mutation #{count})\n"
    "An annotated preview was auto-injected by the VLM QA cadence system.\n"
    "Before proceeding with further edits OR concluding your workflow, you MUST:\n"
    "1. Describe what you see in the preview image (layout, colors, positions)\n"
    "2. Compare against the intended design — note any discrepancies\n"
    "3. List corrections needed (if any) for the next step\n"
    "\n"
    "If no annotated preview image is attached above, proceed using the textual "
    "report and request a manual preview via return_preview=True on your next call.\n"
    "\n"
    "In your immediate next response, DO NOT call any tools. "
    "You must output ONLY your text analysis."
)


def get_mutation_count() -> int:
    """Return the current mutation counter value."""
    return _mutation_count


def reset_mutation_count() -> None:
    """Reset the mutation counter to 0."""
    global _mutation_count
    _mutation_count = 0




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
    if (maxDim < 1) maxDim = 1;
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
    if (maxDim < 1) maxDim = 1;
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
        min_dim = min(10.0, max(2.0, min(ab_w, ab_h) * 0.005))
        if typ != "TextFrame" and (w < min_dim or h < min_dim):
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
    
    IMPORTANT: Always use -y for Y coordinates when positioning objects.
    Call get_scripting_reference for more detailed syntax examples.
    """
    # Log script execution for telemetry
    script = params.script  # Already resolved by model_validator
    script_len = len(script)
    desc = params.description.strip() if params.description else None

    warnings = []

    # ── VLM QA Cadence: auto-inject annotated preview ──────────
    global _mutation_count
    _mutation_count += 1
    is_checkpoint = (_mutation_count % VLM_QA_CADENCE == 0) or params.final_step
    is_vlm_checkpoint = False  # True only when cadence auto-injects

    if is_checkpoint:
        if params.return_preview is False and not params.final_step:
            # AI explicitly disabled preview — soft override: warn but respect
            warnings.append(
                f"VLM QA checkpoint skipped (mutation #{_mutation_count}). "
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
                f"(mutation #{_mutation_count}, final_step={params.final_step})"
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

        # Return standardized envelope
        envelope = format_envelope(
            response=response,
            context=context,
            warnings=warnings,
            diagnostics=diagnostics
        )

        # Inject preview_state into diagnostics
        try:
            envelope_obj = json.loads(envelope)
            preview_state = "post_execution" if envelope_obj.get("ok") else "pre_execution"
            envelope_obj.setdefault("diagnostics", {})["preview_state"] = preview_state
            envelope = json.dumps(envelope_obj)
        except (json.JSONDecodeError, TypeError):
            pass

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
                                    count=_mutation_count
                                ),
                            ))
                        return result_parts
                    else:
                        return [
                            TextContent(type="text", text=envelope),
                            preview_result
                        ]
                else:
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
                            TextContent(type="text", text=VLM_CHECKPOINT_INSTRUCTION.format(count=_mutation_count)),
                        ]
                    return env_text
            except Exception as e:
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
                        TextContent(type="text", text=VLM_CHECKPOINT_INSTRUCTION.format(count=_mutation_count)),
                    ]
                return env_text

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
    # ── SVG d-param preprocessing ────────────────────────────────
    payload = params.payload
    if payload.task == "element_create" and "d" in payload.params:
        from illustrator_mcp.svgd import parse_svg_d

        d_str = payload.params.pop("d")
        multi_mode = payload.params.pop("multi_mode", None)

        try:
            ir = parse_svg_d(d_str)
        except ValueError as e:
            return json.dumps({
                "ok": False,
                "error": f"SVG path parse error: {e}",
                "diagnostics": {"task": payload.task},
            })

        if ir.get("ir") == "multi":
            # Multi-subpath cannot be handled by single execute_task
            # Reject closed override for multi-subpath
            if "closed" in payload.params:
                return json.dumps({
                    "ok": False,
                    "error": (
                        "closed override not supported for multi-subpath SVG. "
                        "Per-subpath closed state is inferred from Z commands."
                    ),
                    "diagnostics": {"task": payload.task},
                })
            # Return error directing to multi-op flow
            n_sub = len(ir.get("subpaths", []))
            return json.dumps({
                "ok": False,
                "error": (
                    f"SVG path contains {n_sub} subpaths. "
                    "Multi-subpath requires compound path creation. "
                    "Use illustrator_execute_script with the compound path "
                    "helper, or call element_create per subpath and then "
                    "clip_create/group_create to combine them."
                ),
                "diagnostics": {
                    "task": payload.task,
                    "subpath_count": n_sub,
                    "all_closed": ir.get("all_closed", False),
                    "multi_mode": multi_mode or ("compound" if ir.get("all_closed") else "group"),
                },
            })
        else:
            # Single subpath — inject geometry IR
            payload.params["geometry"] = ir
            # Closed precedence: explicit > Z-inferred > default False
            if "closed" not in payload.params:
                payload.params["closed"] = bool(ir.get("closed", False))

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
    global _mutation_count
    _mutation_count += 1
    is_task_checkpoint = (_mutation_count % VLM_QA_CADENCE == 0) or params.final_step

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
            envelope = json.dumps({
                "ok": True,
                "warnings": [],
                "error": None,
                "diagnostics": diagnostics,
                "result": {"formatted": formatted, "report": report_data}
            })

            # ── Auto-Grounding: preview at cadence, manual request, or final_step ──
            should_preview = (is_task_checkpoint or params.return_preview) and not is_dry_run
            if should_preview:
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
                        # Cognitive Forcing Function for SOC tasks too
                        if is_task_checkpoint:
                            result_parts.append(TextContent(
                                type="text",
                                text=VLM_CHECKPOINT_INSTRUCTION.format(
                                    count=_mutation_count
                                ),
                            ))
                        return result_parts
                except Exception as e:
                    logger.warning(f"Auto-grounding overlay failed (non-fatal): {e}")

            # Fallback: text-only envelope (+ checkpoint instruction if cadence)
            if is_task_checkpoint:
                return [
                    TextContent(type="text", text=envelope),
                    TextContent(type="text", text=VLM_CHECKPOINT_INSTRUCTION.format(count=_mutation_count)),
                ]
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
    global _mutation_count
    _mutation_count += 1

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
        """Convert extracted path data to a flat contour for Clipper."""
        points = [tuple(p) for p in path_data["points"]]
        if path_data.get("hasHandles"):
            in_handles = [tuple(h) for h in path_data["inHandles"]]
            out_handles = [tuple(h) for h in path_data["outHandles"]]
            points = flatten_path(
                anchors=points,
                in_handles=in_handles,
                out_handles=out_handles,
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
