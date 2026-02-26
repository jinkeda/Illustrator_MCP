"""
Preview and annotation pipeline for VLM QA.

Handles artboard export, item collection, filtering, and overlay annotation.
Used by execute_script and execute_task for auto-preview injection.
"""

import glob
import json
import logging
import math
import os
import tempfile
from typing import List, Optional

from mcp.types import ImageContent

from illustrator_mcp.proxy_client import execute_script_with_context

logger = logging.getLogger("illustrator_mcp")

# Illustrator's ExportOptionsPNG24.horizontalScale has an empirical
# engine limit of ~776%.  Centralised here so tests & JSX both reference
# the same value.
_CLIP_MAX_SCALE_PCT: float = 776.0


def _validate_clip_box(clip_box: List[float]) -> List[float]:
    """Validate and normalize clip_box [xmin, ymin, xmax, ymax].

    Screen-space Y-down points.  Auto-swaps inverted coords.
    Raises ValueError on non-finite values or boxes < 1×1pt.
    """
    if len(clip_box) != 4:
        raise ValueError(f"clip_box must have 4 elements, got {len(clip_box)}")
    for v in clip_box:
        if not math.isfinite(v):
            raise ValueError(f"clip_box contains non-finite value: {v}")
    xmin, ymin, xmax, ymax = clip_box
    if xmin > xmax:
        xmin, xmax = xmax, xmin
    if ymin > ymax:
        ymin, ymax = ymax, ymin
    w, h = xmax - xmin, ymax - ymin
    if w < 1.0 or h < 1.0:
        raise ValueError(f"clip_box too small: {w}×{h}pt (min 1×1)")
    return [xmin, ymin, xmax, ymax]


def _build_export_script(
    tmp_path: str,
    max_dim: int,
    fmt: str = "png",
    clip_box: Optional[List[float]] = None,
) -> str:
    """Build ExtendScript for artboard export.

    Centralizes the export JSX template (DRY for PNG/JPG).
    tmp_path is embedded as a JSON string literal to prevent path injection.

    When *clip_box* is provided (``[xmin, ymin, xmax, ymax]`` in screen-space
    Y-down points), a temporary artboard is created for the crop region,
    the export is scaled up (capped at ``_CLIP_MAX_SCALE_PCT`` to respect
    Illustrator's engine limit), and the temp artboard is cleaned up in a
    ``finally`` block.

    Args:
        tmp_path: Forward-slash OS path for the temp file.
        max_dim: Maximum pixel dimension for scaling.
        fmt: ``"png"`` or ``"jpg"``.
        clip_box: Optional ``[xmin, ymin, xmax, ymax]`` crop region.
    """
    _FMT_MAP = {
        "png": ("ExportOptionsPNG24", "ExportType.PNG24"),
        "jpg": ("ExportOptionsJPEG", "ExportType.JPEG"),
    }
    opts_class, export_type = _FMT_MAP[fmt]
    path_literal = json.dumps(tmp_path)

    if clip_box is not None:
        xmin, ymin, xmax, ymax = clip_box
        return f"""
(function() {{
    var doc = app.activeDocument;
    var origIdx = doc.artboards.getActiveArtboardIndex();
    var origAb = doc.artboards[origIdx].artboardRect;
    var wasSaved = doc.saved;
    var clipRect = [
        Math.max(origAb[0], origAb[0] + {xmin}),
        Math.min(origAb[1], origAb[1] - {ymin}),
        Math.min(origAb[2], origAb[0] + {xmax}),
        Math.max(origAb[3], origAb[1] - {ymax})
    ];
    doc.artboards.add(clipRect);
    var tmpIdx = doc.artboards.length - 1;
    doc.artboards[tmpIdx].name = "__mcp_clip";
    doc.artboards.setActiveArtboardIndex(tmpIdx);
    try {{
        var abW = clipRect[2] - clipRect[0];
        var abH = Math.abs(clipRect[3] - clipRect[1]);
        var maxDim = Math.max(abW, abH);
        if (maxDim < 1) maxDim = 1;
        var scale = ({max_dim} / maxDim) * 100;
        scale = Math.min(scale, {_CLIP_MAX_SCALE_PCT});
        var opts = new {opts_class}();
        opts.horizontalScale = scale;
        opts.verticalScale = scale;
        opts.artBoardClipping = true;
        var file = new File({path_literal});
        doc.exportFile(file, {export_type}, opts);
        var suffixed = new File(file.fsName.replace(/\\.png$/i, "___mcp_clip.png"));
        if (suffixed.exists) {{
            if (file.exists) file.remove();
            suffixed.rename(file.name);
        }}
        if (!file.exists) {{
            var dir = file.parent;
            var base = file.name.replace(/\\.png$/i, "");
            var found = dir.getFiles(base + "*.png");
            if (found.length > 0) {{ found[0].rename(file.name); }}
        }}
    }} finally {{
        doc.artboards.remove(tmpIdx);
        doc.artboards.setActiveArtboardIndex(origIdx);
        try {{ doc.saved = wasSaved; }} catch(e) {{}}
    }}
    return JSON.stringify({{success: true}});
}})();
"""

    # Non-clip path: original behavior (scale ≤ 100%)
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
    clip_box: Optional[List[float]] = None,
) -> Optional[bytes]:
    """Export the active artboard (or clip region) as image bytes.

    Standalone helper — no dependency on ExecuteScriptInput.
    Returns raw image bytes, or None on failure.

    When *clip_box* is set, a high-resolution crop is exported via a
    temporary artboard.  See ``_build_export_script`` for details.
    """
    if clip_box is not None:
        clip_box = _validate_clip_box(clip_box)

    suffix = ".jpg" if fmt == "jpg" else ".png"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_path = tmp.name.replace("\\", "/")
    tmp.close()

    try:
        export_script = _build_export_script(tmp_path, max_dim, fmt, clip_box=clip_box)
        resp = await execute_script_with_context(
            script=export_script,
            command_type="preview_export",
            tool_name="_capture_artboard",
            timeout=timeout or 30.0,
        )
        if resp.get("error"):
            return None

        # Fallback: if expected file missing (artboard-name suffix bug),
        # search temp dir for any matching file.
        if not os.path.isfile(tmp.name) and clip_box is not None:
            base = os.path.splitext(tmp.name)[0]
            candidates = glob.glob(base + "*" + suffix)
            if candidates:
                os.rename(candidates[0], tmp.name)

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
    clip_box = getattr(params, "clip_box", None)

    img_bytes = await _capture_artboard(
        max_dim=max_dim, timeout=timeout, fmt=fmt, clip_box=clip_box,
    )
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

# Clip-aware variant: uses explicit AABB bounds for culling instead of
# the artboard rect.  This avoids the max_items paradox where off-region
# items exhaust the cap before in-region items are reached.
_COLLECT_ITEMS_CLIP_JSX = """
(function() {
    var doc = app.activeDocument;
    var abIdx = doc.artboards.getActiveArtboardIndex();
    var ab = doc.artboards[abIdx].artboardRect;
    var cL = %s, cT = %s, cR = %s, cB = %s;
    var MAX = %d;
    var items = [];
    for (var i = 0; i < doc.pageItems.length && items.length < MAX; i++) {
        var it = doc.pageItems[i];
        if (it.hidden) continue;
        try { if (it.guides) continue; } catch(e) {}
        var vb;
        try { vb = it.visibleBounds; } catch(e) { continue; }
        if (vb[2] - vb[0] < 0.5 || vb[1] - vb[3] < 0.5) continue;
        if (vb[2] < cL || vb[0] > cR || vb[3] > cT || vb[1] < cB) continue;
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


def _clip_box_to_ai_rect(
    clip_box: List[float], artboard_rect: List[float],
) -> List[float]:
    """Convert screen-space Y-down clip_box to Illustrator artboard rect.

    Returns ``[left, top, right, bottom]`` in Illustrator Y-up coords.
    """
    xmin, ymin, xmax, ymax = clip_box
    ab_l, ab_t = artboard_rect[0], artboard_rect[1]
    return [ab_l + xmin, ab_t - ymin, ab_l + xmax, ab_t - ymax]


def _build_collect_script(
    max_items: int,
    clip_box: Optional[List[float]] = None,
) -> str:
    """Return the JSX collection script, optionally clip-aware.

    When *clip_box* is ``None``, returns the standard artboard-culled
    collector.  When set, returns a variant that culls against the clip
    region AABB (in Illustrator Y-up coords derived from the artboard at
    runtime) so that ``max_items`` is not wasted on off-region items.

    Because the clip_box is in screen-space Y-down and can only be
    converted to Illustrator coords once we know the artboard rect (which
    is determined inside the JSX), the conversion is done in JSX:
    ``cL = ab[0]+xmin, cT = ab[1]-ymin, cR = ab[0]+xmax, cB = ab[1]-ymax``.
    """
    if clip_box is None:
        return _COLLECT_ITEMS_JSX % max_items

    xmin, ymin, xmax, ymax = clip_box
    # Build JSX expressions that compute clip bounds relative to artboard
    # at runtime.  Values are numeric literals (safe from injection).
    return _COLLECT_ITEMS_CLIP_JSX % (
        f"ab[0]+{xmin}", f"ab[1]-{ymin}",
        f"ab[0]+{xmax}", f"ab[1]-{ymax}",
        max_items,
    )


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
    clip_box: Optional[List[float]] = None,
) -> tuple:
    """Generate annotated preview with numbered bounding boxes.

    Args:
        img_bytes: Raw PNG bytes of the artboard export.
        max_items: Maximum number of items to annotate.
        timeout: Script execution timeout.
        probe_points: Optional list of probe points for visualization.
        clip_box: Optional ``[xmin, ymin, xmax, ymax]`` in screen-space
            Y-down points.  When set, item collection is culled to the
            clip region, coordinates are mapped relative to the crop,
            and the ruler shows absolute (global) tick labels.

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
    #    When clip_box is active, use the clip-aware variant that culls
    #    against the clip region AABB so max_items is not wasted on
    #    off-region items.
    # clip_box is already validated upstream by _capture_artboard.
    # _build_collect_script handles None clip_box gracefully.
    try:
        collect_response = await execute_script_with_context(
            script=_build_collect_script(max_items, clip_box),
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

    # Determine the effective artboard rect for coordinate mapping.
    # For clip_box, this is the clip region converted to Illustrator coords;
    # otherwise it's the real artboard rect.
    if clip_box is not None:
        effective_rect = _clip_box_to_ai_rect(clip_box, artboard_rect)
        # Clamp to artboard bounds (mirrors JSX-side clamping)
        ab_l, ab_t, ab_r, ab_b = artboard_rect
        effective_rect = [
            max(ab_l, effective_rect[0]),
            min(ab_t, effective_rect[1]),
            min(ab_r, effective_rect[2]),
            max(ab_b, effective_rect[3]),
        ]
    else:
        effective_rect = artboard_rect

    raw_items = snapshot.get("items", [])
    if not raw_items:
        return img_bytes, _result(
            warnings=["No visible items found on artboard"],
            png_px=list(png_size),
            artboard_pt=artboard_rect,
        )

    # 4. Filter low-value items, then map bounds and build annotations
    items, filtered_count = _filter_items(raw_items, effective_rect)

    pixel_annotations = []
    annotation_entries = []
    warn_list = []

    for i, item in enumerate(items):
        label = str(i + 1)
        bounds_pt = item.get("bounds", [0, 0, 0, 0])
        mcp_id = item.get("mcp_id", "") or ""

        # map_bounds_to_pixels uses effective_rect as the "artboard" origin,
        # so when clip_box is active, pixel positions are crop-relative.
        bounds_px = map_bounds_to_pixels(bounds_pt, effective_rect, png_size)

        pixel_annotations.append({
            "label": label,
            "bounds_px": bounds_px,
        })

        # bounds_pt stays in GLOBAL Illustrator coords for follow-up edits
        annotation_entries.append({
            "label": label,
            "mcp_id": mcp_id if mcp_id else None,
            "has_mcp_id": bool(mcp_id),
            "name": item.get("name", ""),
            "type": item.get("type", "Item"),
            "bounds_pt": bounds_pt,
        })

    # 5. Draw ruler overlay (behind ID pills) then composite bounding boxes
    eff_w_pt = abs(effective_rect[2] - effective_rect[0])
    eff_h_pt = abs(effective_rect[1] - effective_rect[3])
    if clip_box is not None:
        ruled_bytes = draw_ruler_overlay(
            img_bytes, eff_w_pt, eff_h_pt,
            origin_x_pt=clip_box[0], origin_y_pt=clip_box[1],
        )
    else:
        ruled_bytes = draw_ruler_overlay(img_bytes, eff_w_pt, eff_h_pt)
    annotated_bytes = composite_overlay(ruled_bytes, pixel_annotations)

    # 6. Draw probe-point markers (on top of everything)
    if probe_points:
        # When clip_box is active, probe points are in global screen-space
        # but draw_probe_overlay maps them against clip dimensions.
        # Remap to clip-relative coordinates.
        if clip_box is not None:
            remapped = []
            for pp in probe_points:
                remapped.append({
                    **pp,
                    "x": pp.get("x", 0) - clip_box[0],
                    "y": pp.get("y", 0) - clip_box[1],
                })
            annotated_bytes = draw_probe_overlay(
                annotated_bytes, remapped, eff_w_pt, eff_h_pt
            )
        else:
            annotated_bytes = draw_probe_overlay(
                annotated_bytes, probe_points, eff_w_pt, eff_h_pt
            )

    # 7. Build result with debug metadata
    extra_meta: dict = {
        "input_count": len(raw_items),
        "filtered_count": filtered_count,
        "png_px": list(png_size),
        "artboard_pt": artboard_rect,
    }
    if clip_box is not None:
        clip_w = clip_box[2] - clip_box[0]
        clip_h = clip_box[3] - clip_box[1]
        requested_scale = (_CLIP_MAX_SCALE_PCT + 1)  # sentinel
        max_dim_clip = max(clip_w, clip_h)
        if max_dim_clip >= 1:
            requested_scale = (1024.0 / max_dim_clip) * 100.0
        extra_meta["clip_box"] = clip_box
        extra_meta["clip_size_pt"] = [clip_w, clip_h]
        extra_meta["clip_artboard_rect_ai"] = effective_rect
        extra_meta["scale_clamped"] = requested_scale > _CLIP_MAX_SCALE_PCT

    return annotated_bytes, _result(
        annotations=annotation_entries,
        warnings=warn_list if warn_list else None,
        **extra_meta,
    )
