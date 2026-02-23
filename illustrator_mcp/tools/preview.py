"""
Preview and annotation pipeline for VLM QA.

Handles artboard export, item collection, filtering, and overlay annotation.
Used by execute_script and execute_task for auto-preview injection.
"""

import json
import logging
import os
import tempfile
from typing import Optional

from mcp.types import ImageContent

from illustrator_mcp.proxy_client import execute_script_with_context

logger = logging.getLogger("illustrator_mcp")


def _build_export_script(tmp_path: str, max_dim: int, fmt: str = "png") -> str:
    """Build ExtendScript for artboard export.

    Centralizes the export JSX template (DRY for PNG/JPG).
    tmp_path is embedded as a JSON string literal to prevent path injection.

    Args:
        tmp_path: Forward-slash OS path for the temp file.
        max_dim: Maximum pixel dimension for scaling.
        fmt: ``"png"`` or ``"jpg"``.
    """
    _FMT_MAP = {
        "png": ("ExportOptionsPNG24", "ExportType.PNG24"),
        "jpg": ("ExportOptionsJPEG", "ExportType.JPEG"),
    }
    opts_class, export_type = _FMT_MAP[fmt]
    # json.dumps produces a valid JS string literal including quotes.
    # This is the canonical pattern; documents.py uses escape_path_for_jsx
    # (which also wraps json.dumps) for pre-quoted contexts.
    path_literal = json.dumps(tmp_path)
    return f"""
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
    var file = new File({path_literal});
    doc.exportFile(file, {export_type}, opts);
    return JSON.stringify({{success: true}});
}})();
"""


async def _capture_artboard(
    max_dim: int = 1024,
    timeout: Optional[float] = None,
    fmt: str = "png",
) -> Optional[bytes]:
    """Export the active artboard as image bytes (PNG or JPG).

    Standalone helper — no dependency on ExecuteScriptInput.
    Returns raw image bytes, or None on failure.
    """
    suffix = ".jpg" if fmt == "jpg" else ".png"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_path = tmp.name.replace("\\", "/")
    tmp.close()

    try:
        export_script = _build_export_script(tmp_path, max_dim, fmt)
        resp = await execute_script_with_context(
            script=export_script,
            command_type="preview_export",
            tool_name="_capture_artboard",
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


async def _capture_artboard_png(
    max_dim: int = 1024,
    timeout: Optional[float] = None,
) -> Optional[bytes]:
    """Backward-compat alias. Will be removed in a future release."""
    return await _capture_artboard(max_dim=max_dim, timeout=timeout, fmt="png")


async def _generate_preview(
    params,
    timeout: Optional[float] = None
) -> Optional[ImageContent]:
    """Auto-export a thumbnail for the execute-and-preview feature (P4).

    Delegates to _capture_artboard, then wraps result as ImageContent.
    Supports PNG and JPG via params.preview_format.
    """
    import base64

    fmt = params.preview_format
    max_dim = params.preview_max_dim
    mime = "image/jpeg" if fmt == "jpg" else "image/png"

    img_bytes = await _capture_artboard(max_dim=max_dim, timeout=timeout, fmt=fmt)
    if not img_bytes:
        return None
    return ImageContent(
        type="image",
        data=base64.b64encode(img_bytes).decode('utf-8'),
        mimeType=mime,
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
        var idx = note.indexOf("@mcp:id=");
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
        # Threshold: 0.5% of the smaller artboard dimension, clamped to [2, 10] pt.
        # - 2 pt floor: prevents filtering of fine but intentional detail
        # - 10 pt ceiling: avoids over-filtering on very large artboards
        # - 0.5% scaling: adapts to artboard size (e.g., 4 pt on 800-pt artboard)
        min_dim = min(10.0, max(2.0, min(ab_w, ab_h) * 0.005))
        if typ != "TextFrame" and (w < min_dim or h < min_dim):
            continue

        kept.append(item)

    return kept, len(items) - len(kept)


async def _annotate_preview(
    img_bytes: bytes,
    max_items: int = 200,
    timeout: Optional[float] = None,
    probe_points: Optional[list] = None,
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
        draw_probe_overlay,
        draw_ruler_overlay,
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
            warnings=["Pillow not installed. Run: pip install illustrator-mcp"]
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

    # 5. Draw ruler overlay (behind ID pills) then composite bounding boxes
    ab_w_pt = abs(artboard_rect[2] - artboard_rect[0])
    ab_h_pt = abs(artboard_rect[1] - artboard_rect[3])
    ruled_bytes = draw_ruler_overlay(img_bytes, ab_w_pt, ab_h_pt)
    annotated_bytes = composite_overlay(ruled_bytes, pixel_annotations)

    # 6. Draw probe-point markers (on top of everything)
    if probe_points:
        annotated_bytes = draw_probe_overlay(
            annotated_bytes, probe_points, ab_w_pt, ab_h_pt
        )

    return annotated_bytes, _result(
        annotations=annotation_entries,
        warnings=warn_list if warn_list else None,
        input_count=len(raw_items),
        filtered_count=filtered_count,
        png_px=list(png_size),
        artboard_pt=artboard_rect,
    )
