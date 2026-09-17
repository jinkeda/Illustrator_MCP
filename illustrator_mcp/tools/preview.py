"""
Preview and annotation pipeline for VLM QA.

Handles artboard export, item collection, filtering, and overlay annotation.
Used by execute_script and execute_task for auto-preview injection.
"""

import io
import json
import logging
import math
import os
import tempfile
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import List, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mcp.types import ImageContent

from illustrator_mcp.errors import ErrorCode
from illustrator_mcp.proxy_client import execute_script_with_context

logger = logging.getLogger("illustrator_mcp")
capture_metadata = ContextVar("capture_metadata", default=None)
ClipSpace = Literal["artboard_relative_y_down", "illustrator_native_y_up"]


def validate_clip_space(box, space):
    if box is None:
        return None
    if space == "illustrator_native_y_up":
        if len(box) != 4 or not all(math.isfinite(v) for v in box) or box[0] >= box[2] or box[1] <= box[3]:
            raise ValueError(f"{ErrorCode.V_INVALID_COORDINATE_SPACE.value}: native clip_box requires finite [left, top, right, bottom], left < right and top > bottom; nextStep: correct native ordering")
        return list(box)
    return _validate_clip_box(box)


def canonical_clip(box, space, artboard):
    if box is None or space == "artboard_relative_y_down":
        return box
    left, top, right, bottom = validate_clip_space(box, space)
    return _validate_clip_box([left-artboard[0], artboard[1]-top, right-artboard[0], artboard[1]-bottom])



class CaptureOptions(BaseModel):
    """Internal capture contract, independent of evidence requirements.

    Public routes retain their names and tighter limits. In particular task
    uses fixed PNG/1024 defaults; execute adapts preview_*; observe uses
    max_dim and owns background/contact-sheet/map presentation separately.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_dim: int = Field(1024, ge=64, le=4096)
    timeout: Optional[float] = Field(None, gt=0)
    fmt: Literal["png", "jpg"] = "png"
    clip_box: Optional[List[float]] = None
    artboard_index: Optional[int] = Field(None, ge=0)
    clip_space: ClipSpace = "artboard_relative_y_down"

    @model_validator(mode="after")
    def validate_crop(self):
        object.__setattr__(self, "clip_box", validate_clip_space(self.clip_box, self.clip_space))
        return self

    @classmethod
    def from_execute(cls, params, timeout=None):
        return cls(max_dim=params.preview_max_dim, fmt=params.preview_format,
                   timeout=timeout, clip_box=getattr(params, "clip_box", None),
                   clip_space=getattr(params, "clip_space", "artboard_relative_y_down"))

    @property
    def mime_type(self):
        return "image/jpeg" if self.fmt == "jpg" else "image/png"


# ── Occlusion guard runner ─────────────────────────────────────────

async def _run_occlusion_guard(
    timeout: Optional[float] = None,
    bg_layer_names: Optional[set] = None,
) -> tuple:
    """Execute z_telemetry.jsx and run OcclusionGuard checks.

    Returns:
        (OcclusionResult, raw_telemetry_dict)
        raw_telemetry_dict is the parsed JSON from z_telemetry.jsx, or {}
        on failure.
    """
    from illustrator_mcp.occlusion_guard import check_occlusion, OcclusionResult

    # Read the JSX script
    script_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "resources", "scripts", "z_telemetry.jsx",
    )
    # Fallback if path doesn't exist yet (import guard)
    if not os.path.isfile(script_path):
        logger.warning("z_telemetry.jsx not found at %s", script_path)
        return OcclusionResult(ok=True, diagnostics={"bypass": "no_script"}), {}

    with open(script_path, "r", encoding="utf-8") as f:
        jsx_code = f.read()

    try:
        resp = await execute_script_with_context(
            script=jsx_code,
            command_type="z_telemetry",
            tool_name="_run_occlusion_guard",
            timeout=timeout or 15.0,
        )
    except Exception as e:
        logger.warning("z_telemetry execution failed: %s", e)
        return OcclusionResult(ok=True, diagnostics={"bypass": "exec_error", "error": str(e)}), {}

    # Parse response
    raw = resp.get("result")
    if not raw:
        return OcclusionResult(ok=True, diagnostics={"bypass": "empty_response"}), {}

    try:
        if isinstance(raw, str):
            parsed = json.loads(raw)
        else:
            parsed = raw
    except (json.JSONDecodeError, TypeError):
        return OcclusionResult(ok=True, diagnostics={"bypass": "parse_error"}), {}

    # Unwrap {ok: true, data: {...}} envelope
    telemetry = parsed
    if isinstance(parsed, dict) and "data" in parsed:
        telemetry = parsed["data"]

    layers = telemetry.get("layers", [])
    top_items = telemetry.get("topLayerItems", [])
    artboard = telemetry.get("artboardRect", [0, 0, 0, 0])
    total = telemetry.get("totalItemCount", 0)

    result = check_occlusion(layers, top_items, artboard, total,
                             bg_layer_names=bg_layer_names)
    return result, telemetry


# ── Guard checkpoint helper ────────────────────────────────────────

@dataclass
class GuardCheckpointResult:
    """Result of a guard checkpoint — consumed by execute_script and execute_task."""
    guard_result: object  # Optional[OcclusionResult]
    guard_telemetry: dict
    should_abort: bool
    guard_status: str = "skipped"     # "skipped" | "passed" | "aborted"
    abort_message: str = ""           # empty if not aborting
    diag_extras: dict = field(default_factory=dict)
    # Preview policy (callers don't re-encode)
    should_preview: bool = True
    preview_mode: Optional[str] = None  # "annotated" at checkpoints
    # Formatted telemetry text (both paths append identically)
    telemetry_text: Optional[str] = None
    # Q004 warn-level warnings for callers to append
    warn_messages: List[str] = field(default_factory=list)


async def _guard_checkpoint(
    *,
    timeout: float,
    bg_layer_names: Optional[set] = None,
    auto_fix: bool = False,
    max_retries: int = 1,
    checkpoint_label: str,
) -> GuardCheckpointResult:
    """Run the occlusion guard and return a structured result.

    Encapsulates guard check + abort message + diagnostics + telemetry
    so both execute_script and execute_task get identical behavior.

    Args:
        timeout: Bridge call timeout in seconds.
        bg_layer_names: Optional override for background layer name matching.
        auto_fix: If True, attempt to execute suggested_fix ops (NOT YET IMPLEMENTED).
        max_retries: Max fix-retry attempts (only used when auto_fix=True).
        checkpoint_label: "execute_script" or "execute_task" for logging.

    Returns:
        GuardCheckpointResult with abort/pass state, diagnostics, and
        preview policy pre-computed.
    """
    from illustrator_mcp.occlusion_guard import format_abort_message
    from illustrator_mcp.tools.cadence import format_z_telemetry

    guard_result = None
    guard_telemetry = {}

    try:
        guard_result, guard_telemetry = await _run_occlusion_guard(
            timeout=timeout,
            bg_layer_names=bg_layer_names,
        )
    except Exception as e:
        logger.warning("Occlusion guard failed in %s: %s", checkpoint_label, e)
        return GuardCheckpointResult(
            guard_result=None,
            guard_telemetry={},
            should_abort=False,
            guard_status="skipped",
            should_preview=True,
            preview_mode="annotated",
        )

    # Compute formatted telemetry text
    telemetry_text = None
    if guard_telemetry:
        telemetry_text = format_z_telemetry(guard_telemetry)

    if guard_result and not guard_result.ok:
        # ABORT: occlusion detected
        abort_msg = format_abort_message(guard_result)
        diag_extras = {
            "occlusion_guard": guard_result.diagnostics,
            "suggested_fix": [
                f.__dict__ if hasattr(f, '__dict__') else f
                for f in guard_result.suggested_fix
            ],
            "occlusion_findings": [
                {"code": f.code, "severity": f.severity,
                 "message": f.message, "offender": f.offender}
                for f in guard_result.findings
            ],
        }
        logger.warning(
            "Occlusion guard ABORT in %s: %s",
            checkpoint_label, [f.code for f in guard_result.findings]
        )
        return GuardCheckpointResult(
            guard_result=guard_result,
            guard_telemetry=guard_telemetry,
            should_abort=True,
            guard_status="aborted",
            abort_message=abort_msg,
            diag_extras=diag_extras,
            should_preview=False,
            preview_mode=None,
            telemetry_text=telemetry_text,
        )

    # PASS (possibly with Q004 warnings)
    warn_messages = []
    if guard_result and guard_result.findings:
        for f in guard_result.findings:
            if f.severity == "warn":
                warn_messages.append(f"⚠️ {f.code}: {f.message}")

    return GuardCheckpointResult(
        guard_result=guard_result,
        guard_telemetry=guard_telemetry,
        should_abort=False,
        guard_status="passed",
        should_preview=True,
        preview_mode="annotated",
        telemetry_text=telemetry_text,
        warn_messages=warn_messages,
    )

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
    artboard_index: Optional[int] = None,
    clip_space: ClipSpace = "artboard_relative_y_down",
) -> str:
    """Build nonmutating imageCapture JSX for an existing artboard.

    Capture PNG on the host; crop/downsample and convert JPEG in Pillow.
    tmp_path is embedded as a JSON string literal to prevent path injection.

    When *clip_box* is provided (``[xmin, ymin, xmax, ymax]`` in screen-space
    Y-down points), export the existing artboard at the required detail.
    The host captures the intersected region; Python only downsamples within
    the actual raster size. No temporary artboard or saved-state assignment is used.

    Args:
        tmp_path: Forward-slash OS path for the temp file.
        max_dim: Maximum pixel dimension for scaling.
        fmt: ``"png"`` or ``"jpg"``.
        clip_box: Optional ``[xmin, ymin, xmax, ymax]`` crop region.
    """
    path_literal = json.dumps(tmp_path)
    index_js = "doc.artboards.getActiveArtboardIndex()" if artboard_index is None else str(int(artboard_index))
    crop_js = json.dumps(clip_box) if clip_box is not None else "null"
    return f"""
(function() {{
    var doc = app.activeDocument;
    var abIdx = {index_js};
    if (abIdx < 0 || abIdx >= doc.artboards.length) throw new Error("Artboard index is out of range");
    var abRect = doc.artboards[abIdx].artboardRect;
    var abW = abRect[2] - abRect[0], abH = Math.abs(abRect[3] - abRect[1]);
    var crop = {crop_js};
    if (crop && {json.dumps(clip_space)} === "illustrator_native_y_up")
        crop = [crop[0]-abRect[0], abRect[1]-crop[1], crop[2]-abRect[0], abRect[1]-crop[3]];
    if (crop && (crop[2]-crop[0] < 1 || crop[3]-crop[1] < 1)) throw new Error("V011: crop minimum is 1 x 1 pt");
    var maxDim = Math.max(abW, abH);
    var scale = Math.min({max_dim} / maxDim * 100, 100);
    if (crop) {{
        crop = [Math.max(0,crop[0]),Math.max(0,crop[1]),Math.min(abW,crop[2]),Math.min(abH,crop[3])];
        if (crop[2] <= crop[0] || crop[3] <= crop[1]) throw new Error("{ErrorCode.V_CAPTURE_EMPTY_REGION.value}: Crop does not intersect the artboard; nextStep: choose an intersecting crop");
        scale = {max_dim} / Math.max(crop[2]-crop[0],crop[3]-crop[1]) * 100;
    }}
    var region = crop ? [abRect[0]+crop[0],abRect[1]-crop[1],abRect[0]+crop[2],abRect[1]-crop[3]] : abRect;
    var rw = region[2]-region[0], rh = region[1]-region[3];
    var feasible = Math.min({_CLIP_MAX_SCALE_PCT}, 8192/rw*100, 8192/rh*100, Math.sqrt(16777216/(rw*rh))*100);
    while (Math.ceil(rw*feasible/100)*Math.ceil(rh*feasible/100) > 16777216) feasible *= 0.9999;
    if (feasible < 100) throw new Error("{ErrorCode.V_CAPTURE_MINIMUM_BUDGET_EXCEEDED.value}: Capture minimum exceeds budget; nextStep: use a smaller region");
    var requestedScale = scale;
    scale = Math.min(scale, feasible);
    var captureScale = Math.max(100, scale);
    var constraint = requestedScale <= feasible ? null : (feasible === {_CLIP_MAX_SCALE_PCT} ? "inherited_776_percent_limit" : "raster_pixel_budget");
    var opts = new ImageCaptureOptions();
    opts.resolution = captureScale * 72 / 100;
    opts.transparency = true;
    opts.antiAliasing = true;
    opts.matte = false;
    doc.imageCapture(new File({path_literal}), region, opts);
    return JSON.stringify({{success:true,artboardIndex:abIdx,artboardWidth:abW,artboardHeight:abH,scale:scale,captureScale:captureScale,
        route:"imageCapture_region",capture_region:region,space:"illustrator_native_y_up",units:"pt",artboard_rect:abRect,
        requested_max_dim:{max_dim},requested_scale_pct:requestedScale,actual_scale_pct:scale,
        scale_clamped:requestedScale>feasible,max_feasible_dim:Math.floor(Math.max(rw,rh)*feasible/100),limiting_constraint:constraint}});
}})();
"""


# ── Multi-artboard capture and compositing ─────────────────────────

#: Backgrounds a preview can be flattened onto before it is returned.
#: Illustrator exports PNG24 with transparency, so a dark stroke on an empty
#: board arrives as dark-on-nothing and disappears against a dark viewer.
PREVIEW_BACKGROUNDS = ("transparent", "white", "checkerboard")

#: Checker square size in pixels, big enough to read behind thin artwork
#: without competing with it.
_CHECKER_PX = 16


def composite_background(png_bytes: bytes, background: str) -> bytes:
    """Flatten a preview onto an opaque background.

    Returns the input unchanged for "transparent", when Pillow is missing, or
    when the image has no alpha to flatten — a background is a readability
    aid and must never cost the caller their evidence.
    """
    if background == "transparent" or not png_bytes:
        return png_bytes
    try:
        from PIL import Image
    except ImportError:
        logger.debug("Pillow unavailable; returning preview unflattened")
        return png_bytes

    try:
        with Image.open(io.BytesIO(png_bytes)) as src:
            img = src.convert("RGBA")
            if background == "white":
                back = Image.new("RGBA", img.size, (255, 255, 255, 255))
            else:
                back = _checkerboard(img.size)
            back.alpha_composite(img)
            out = io.BytesIO()
            back.convert("RGB").save(out, format="PNG")
            return out.getvalue()
    except Exception as exc:  # pragma: no cover - defensive
        # Degrading to the unflattened image is deliberate: a readability aid
        # must never cost the caller their evidence. But this is not an
        # expected path, and a missing import once hid here silently, so it
        # is logged loudly enough to notice.
        logger.warning("Background compositing failed, returning raw preview: %s", exc)
        return png_bytes


def _checkerboard(size):
    """A light checkerboard, so both dark and light artwork stay visible."""
    from PIL import Image, ImageDraw

    back = Image.new("RGBA", size, (255, 255, 255, 255))
    draw = ImageDraw.Draw(back)
    for y in range(0, size[1], _CHECKER_PX):
        for x in range(0, size[0], _CHECKER_PX):
            if ((x // _CHECKER_PX) + (y // _CHECKER_PX)) % 2:
                draw.rectangle(
                    [x, y, x + _CHECKER_PX - 1, y + _CHECKER_PX - 1],
                    fill=(219, 219, 219, 255),
                )
    return back


async def artboard_count(timeout: Optional[float] = None, *, strict: bool = False) -> Optional[int]:
    """How many artboards the active document has, or None if unreadable."""
    from illustrator_mcp.utils.response import (
        JsxPayloadError, require_jsx_payload,
    )

    try:
        resp = await execute_script_with_context(
            script=(
                "(function () { return JSON.stringify("
                "{count: app.activeDocument.artboards.length}); })()"
            ),
            command_type="artboard_count",
            tool_name="_capture_artboards",
            timeout=timeout or 10.0,
        )
        payload = require_jsx_payload(
            resp, context="artboard_count", required_keys=("count",)
        )
    except Exception as exc:
        if strict:
            raise
        logger.debug("Could not read artboard count: %s", exc)
        return None
    count = payload.get("count")
    if strict and (type(count) is not int or count <= 0):
        raise ValueError("No valid artboard count was returned")
    return count if isinstance(count, int) and not isinstance(count, bool) else None


def resolve_artboards(selection, count: Optional[int]) -> "list[int] | None":
    """Turn an artboard selection into concrete indices.

    ``"active"`` returns None, meaning "whatever is active", which keeps the
    single-board path exactly as it was. ``"all"`` needs the count and gives
    up rather than guessing when it cannot be read.
    """
    if selection == "active":
        return None
    if selection == "all":
        return list(range(count)) if count else None
    indices = [i for i in selection if isinstance(i, int) and i >= 0]
    if count is not None:
        indices = [i for i in indices if i < count]
    # Preserve caller order, drop repeats: a contact sheet with the same
    # board twice is a mistake, not a request.
    seen, ordered = set(), []
    for i in indices:
        if i not in seen:
            seen.add(i)
            ordered.append(i)
    return ordered or None


async def _capture_artboards(
    indices: "list[int]",
    max_dim: int = 1024,
    timeout: Optional[float] = None,
    fmt: str = "png",
    strict: bool = False,
) -> "list[tuple]":
    """Capture several artboards. Returns [(index, bytes), ...], skipping failures."""
    captured = []
    metadata = []
    for index in indices:
        capture_metadata.set(None)
        png = await _capture_artboard(
            max_dim=max_dim, timeout=timeout, fmt=fmt, artboard_index=index, strict=strict,
        )
        if png:
            captured.append((index, png))
            metadata.append({"artboard_index": index, "capture": capture_metadata.get()})
        else:
            logger.debug("Artboard %s could not be captured", index)
    capture_metadata.set({"artboards": metadata})
    return captured


def contact_sheet(
    captures: "list[tuple]", max_dim: int = 1024, background: str = "white",
) -> "tuple":
    """Compose captured artboards into one labelled grid.

    Returns ``(png_bytes, layout)``, or ``(None, layout)`` when Pillow is
    missing or nothing was captured. The layout names which cell holds which
    artboard, so a caller can say "the third one" and mean something.
    """
    layout = {"artboards": [c[0] for c in captures], "columns": 0, "rows": 0}
    if not captures:
        return None, layout
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        logger.debug("Pillow unavailable; cannot build a contact sheet")
        return None, {**layout, "unavailable": "Pillow is not installed"}

    try:
        images = []
        for index, png in captures:
            with Image.open(io.BytesIO(png)) as src:
                images.append((index, src.convert("RGBA").copy()))

        columns = math.ceil(math.sqrt(len(images)))
        rows = math.ceil(len(images) / columns)
        cell_w = max(img.width for _, img in images)
        cell_h = max(img.height for _, img in images)

        # Scale the whole sheet, not each cell, so relative sizes stay honest.
        label_h = 18
        sheet_w, sheet_h = columns * cell_w, rows * (cell_h + label_h)
        scale = min(1.0, max_dim / max(sheet_w, sheet_h)) if max(sheet_w, sheet_h) else 1.0

        sheet = Image.new("RGBA", (sheet_w, sheet_h), (255, 255, 255, 255))
        draw = ImageDraw.Draw(sheet)
        placed = []
        for n, (index, img) in enumerate(images):
            col, row = n % columns, n // columns
            x, y = col * cell_w, row * (cell_h + label_h)
            draw.rectangle([x, y, x + cell_w - 1, y + label_h - 1],
                           fill=(40, 40, 40, 255))
            draw.text((x + 4, y + 4), f"[{index}]", fill=(255, 255, 255, 255))
            # Centre each board in its cell so uneven sizes stay readable.
            ox = x + (cell_w - img.width) // 2
            oy = y + label_h + (cell_h - img.height) // 2
            sheet.alpha_composite(img, (ox, oy))
            placed.append({"artboard": index, "column": col, "row": row})
            img.close()

        if scale < 1.0:
            sheet = sheet.resize(
                (max(1, int(sheet_w * scale)), max(1, int(sheet_h * scale))),
                Image.LANCZOS,
            )
        out = io.BytesIO()
        sheet.convert("RGB").save(out, format="PNG")
        sheet.close()
        return composite_background(out.getvalue(), background), {
            "artboards": [c[0] for c in captures],
            "columns": columns,
            "rows": rows,
            "cells": placed,
        }
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Contact sheet composition failed: %s", exc)
        return None, {**layout, "unavailable": str(exc)}


def _crop_raster(raw, clip_box, metadata, fmt="png"):
    """Map fractional point edges to measured pixels, preserving exact extent."""
    import io
    import math
    from PIL import Image
    w, h = metadata["artboardWidth"], metadata["artboardHeight"]
    left, top, right, bottom = clip_box
    left, top, right, bottom = max(0, left), max(0, top), min(w, right), min(h, bottom)
    if right <= left or bottom <= top:
        raise ValueError("Crop does not intersect the artboard")
    if metadata.get("capture_region"):
        region = metadata["capture_region"]
        w, h = region[2]-region[0], region[1]-region[3]
        left, top, right, bottom = 0, 0, w, h
    scale = metadata["scale"] / 100
    size = (max(1, math.ceil((right-left)*scale)), max(1, math.ceil((bottom-top)*scale)))
    with Image.open(io.BytesIO(raw)) as source:
        if max(source.size) > 8192 or source.width * source.height > 16777216:
            raise ValueError("Raster exceeds capture budget")
        source.load()
        size = (min(size[0], source.width), min(size[1], source.height))
        metadata["actual_dimensions_px"] = list(size)
        metadata["actual_scale_pct"] = min(size[0]/(right-left), size[1]/(bottom-top))*100
        metadata["measured_scale_pct_xy"] = [size[0]/(right-left)*100, size[1]/(bottom-top)*100]
        extent = (left/w*source.width, top/h*source.height, right/w*source.width, bottom/h*source.height)
        cropped = source.transform(size, Image.Transform.EXTENT, extent, resample=Image.Resampling.BICUBIC)
        output = io.BytesIO()
        if fmt == "jpg":
            rgba = cropped.convert("RGBA")
            matte = Image.new("RGB", rgba.size, "white")
            matte.paste(rgba, mask=rgba.getchannel("A"))
            cropped = matte
        cropped.save(output, format="JPEG" if fmt == "jpg" else "PNG")
        return output.getvalue()


async def _capture_artboard(
    max_dim: int = 1024,
    timeout: Optional[float] = None,
    fmt: str = "png",
    clip_box: Optional[List[float]] = None,
    artboard_index: Optional[int] = None,
    strict: bool = False,
    clip_space: ClipSpace = "artboard_relative_y_down",
) -> Optional[bytes]:
    """Export the active artboard (or clip region) as image bytes.

    Standalone helper — no dependency on ExecuteScriptInput.
    Returns raw image bytes, or None on failure.

    Crops use a bounded native imageCapture rectangle, without source edits.
    """
    options = CaptureOptions(max_dim=max_dim, timeout=timeout, fmt=fmt,
                             clip_box=clip_box, artboard_index=artboard_index, clip_space=clip_space)
    clip_box = options.clip_box
    suffix = ".png"  # imageCapture always emits PNG; Pillow handles JPEG.
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_path = tmp.name.replace("\\", "/")
    tmp.close()

    try:
        export_script = _build_export_script(
            tmp_path, max_dim, fmt, clip_box=clip_box,
            artboard_index=artboard_index, clip_space=clip_space,
        )
        resp = await execute_script_with_context(
            script=export_script,
            command_type="preview_export",
            tool_name="_capture_artboard",
            timeout=timeout or 30.0,
        )
        if strict:
            from illustrator_mcp.utils.response import require_jsx_payload
            require_jsx_payload(resp, context="preview export")
        elif resp.get("error"):
            return None

        if not os.path.isfile(tmp.name):
            return None

        with open(tmp.name, "rb") as f:
            img_bytes = f.read()

        if img_bytes:
            from illustrator_mcp.utils.response import require_jsx_payload
            metadata = require_jsx_payload(resp, context="preview crop", required_keys=("artboardWidth", "artboardHeight", "scale"))
            effective_clip = canonical_clip(clip_box, clip_space, metadata.get("artboard_rect", [0, 0, 0, 0]))
            img_bytes = _crop_raster(img_bytes, effective_clip or [0, 0, metadata["artboardWidth"], metadata["artboardHeight"]], metadata, fmt)
            capture_metadata.set(metadata)
        if strict and not img_bytes:
            raise ValueError("Preview export produced no image bytes")
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


async def capture_frame(options: CaptureOptions, *, annotate=False, max_items=200,
                        background="transparent", capture=None, annotator=None, render_annotation=True):
    """Capture once and optionally annotate the same crop inside the caller's job.

    No reservation or evidence decision is made here. Observe retains its
    preservation guard, multi-artboard orchestration and map presentation.
    """
    capture_metadata.set(None)
    capture_args = options.model_dump(exclude_none=True)
    if options.clip_space == "artboard_relative_y_down":
        capture_args.pop("clip_space", None)
    raw = await (capture or _capture_artboard)(**capture_args)
    raw = composite_background(raw, background)
    annotated, mapping = None, {"meta": {}, "annotations": [], "warnings": []}
    if raw and annotate:
        annotated, mapping = await (annotator or _annotate_preview)(
            img_bytes=raw, max_items=max_items, timeout=options.timeout,
            clip_box=options.clip_box, clip_space=options.clip_space,
            render=render_annotation,
        )
    return raw, annotated, mapping


async def _generate_preview(
    params,
    timeout: Optional[float] = None
) -> Optional[ImageContent]:
    """Auto-export a thumbnail for the execute-and-preview feature (P4).

    Delegates to _capture_artboard, then wraps result as ImageContent.
    Supports PNG and JPG via params.preview_format.
    """
    import base64

    options = CaptureOptions.from_execute(params, timeout)
    img_bytes, _, _ = await capture_frame(options)
    if not img_bytes:
        return None
    return ImageContent(
        type="image",
        data=base64.b64encode(img_bytes).decode('utf-8'),
        mimeType=options.mime_type,
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
        // T02: exact tag parse via mcp_id.jsx.  The previous fixed 36-char
        // slice truncated the 40-char generated IDs (mcp_ + UUID) and made
        // short custom IDs absorb the note text that followed them, so the
        // agent was handed an editing handle that did not resolve — or, with
        // prefix matching, resolved to the wrong object.
        mcpId = extractMcpId(note) || "";
        var handleResult = typeof mcpIssueHandle === "function" ? mcpIssueHandle(it) : null;
        items.push({
            name: it.name || it.typename,
            type: it.typename,
            bounds: [vb[0], vb[1], vb[2], vb[3]],
            mcp_id: mcpId,
            handle: handleResult && handleResult.ok ? handleResult.record.handle : null,
            handleExpiresAt: handleResult && handleResult.ok ? handleResult.record.expiresAt : null
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
        // T02: exact tag parse via mcp_id.jsx.  The previous fixed 36-char
        // slice truncated the 40-char generated IDs (mcp_ + UUID) and made
        // short custom IDs absorb the note text that followed them, so the
        // agent was handed an editing handle that did not resolve — or, with
        // prefix matching, resolved to the wrong object.
        mcpId = extractMcpId(note) || "";
        var handleResult = typeof mcpIssueHandle === "function" ? mcpIssueHandle(it) : null;
        items.push({
            name: it.name || it.typename,
            type: it.typename,
            bounds: [vb[0], vb[1], vb[2], vb[3]],
            mcp_id: mcpId,
            handle: handleResult && handleResult.ok ? handleResult.record.handle : null,
            handleExpiresAt: handleResult && handleResult.ok ? handleResult.record.expiresAt : null
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
    clip_space: ClipSpace = "artboard_relative_y_down",
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
    if clip_space == "illustrator_native_y_up":
        return _COLLECT_ITEMS_CLIP_JSX % (str(xmin), str(ymin), str(xmax), str(ymax), max_items)
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
    strict: bool = False,
    clip_space: ClipSpace = "artboard_relative_y_down",
    render: bool = True,
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
            "bounds_pt_space": "illustrator_native_y_up",
            "bounds_pt_units": "pt",
            "bounds_px_space": "image_pixels_y_down",
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
        return (img_bytes if render else None), _result(
            warnings=["Pillow not installed. Run: pip install illustrator-mcp"]
        )

    # 1. Decode PNG dimensions
    png_size = get_png_dimensions(img_bytes)
    if not png_size:
        return (img_bytes if render else None), _result(warnings=["Could not decode PNG dimensions"])

    # 2. Collect item bounds from Illustrator
    #    When clip_box is active, use the clip-aware variant that culls
    #    against the clip region AABB so max_items is not wasted on
    #    off-region items.
    # clip_box is already validated upstream by _capture_artboard.
    # _build_collect_script handles None clip_box gracefully.
    try:
        collect_response = await execute_script_with_context(
            script=_build_collect_script(max_items, clip_box, clip_space),
            command_type="annotate_collect",
            tool_name="illustrator_execute_script",
            timeout=timeout or 30.0,
            # T02: the collector parses @mcp:id tags with the shared exact
            # parser rather than a second, divergent implementation.
            includes=["mcp_id", "handles"],
        )
    except Exception as e:
        if strict:
            raise
        return (img_bytes if render else None), _result(warnings=[f"Item collection failed: {e}"])

    from illustrator_mcp.utils.response import require_jsx_payload
    try:
        snapshot = require_jsx_payload(collect_response, context="annotation collection", required_keys=("artboard", "items"))
    except Exception as exc:
        if strict:
            raise
        return (img_bytes if render else None), _result(warnings=["Item collection failed: " + str(exc)])

    artboard_rect = snapshot.get("artboard")
    if not artboard_rect or len(artboard_rect) != 4:
        return (img_bytes if render else None), _result(
            warnings=["Missing or invalid artboard bounds — cannot map coordinates"]
        )

    clip_box = canonical_clip(clip_box, clip_space, artboard_rect)

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
        return (img_bytes if render else None), _result(
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

        # Compute coverRatio from bounds vs effective artboard rect (Python-side)
        from illustrator_mcp.occlusion_guard import _intersection_area, _artboard_area
        ab_area = _artboard_area(effective_rect)
        cover_ratio = (
            _intersection_area(bounds_pt, effective_rect) / ab_area
            if ab_area > 0 else 0.0
        )
        cover_ratio = round(cover_ratio, 3)

        # map_bounds_to_pixels uses effective_rect as the "artboard" origin,
        # so when clip_box is active, pixel positions are crop-relative.
        bounds_px = map_bounds_to_pixels(bounds_pt, effective_rect, png_size)

        pixel_annotations.append({
            "label": label,
            "bounds_px": bounds_px,
            "coverRatio": cover_ratio,
        })

        # bounds_pt stays in GLOBAL Illustrator coords for follow-up edits
        annotation_entries.append({
            "label": label,
            "mcp_id": mcp_id if mcp_id else None,
            "has_mcp_id": bool(mcp_id),
            "handle": item.get("handle"),
            "handleExpiresAt": item.get("handleExpiresAt"),
            "name": item.get("name", ""),
            "type": item.get("type", "Item"),
            "bounds_pt": bounds_pt,
            "bounds_px": list(bounds_px),
            "coverRatio": cover_ratio,
        })

    eff_w_pt = abs(effective_rect[2] - effective_rect[0])
    eff_h_pt = abs(effective_rect[1] - effective_rect[3])
    annotated_bytes = None
    if render:
        # 5. Draw ruler overlay (behind ID pills) then composite bounding boxes
        eff_w_pt = abs(effective_rect[2] - effective_rect[0])
        eff_h_pt = abs(effective_rect[1] - effective_rect[3])
        if clip_box is not None:
            ruled_bytes = draw_ruler_overlay(
                img_bytes, eff_w_pt, eff_h_pt,
                origin_x_pt=effective_rect[0]-artboard_rect[0], origin_y_pt=artboard_rect[1]-effective_rect[1],
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
                        "x": pp.get("x", 0) - (effective_rect[0]-artboard_rect[0]),
                        "y": pp.get("y", 0) - (artboard_rect[1]-effective_rect[1]),
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
        "artboard_pt_space": "illustrator_native_y_up",
        "artboard_index": (capture_metadata.get() or {}).get("artboardIndex"),
    }
    if clip_box is not None:
        extra_meta["clip_box"] = clip_box
        extra_meta["clip_size_pt"] = [eff_w_pt, eff_h_pt]
        extra_meta["clip_artboard_rect_ai"] = effective_rect
        extra_meta["capture"] = capture_metadata.get()
        extra_meta["measured_pixels_per_point"] = [png_size[0]/eff_w_pt, png_size[1]/eff_h_pt]

    return annotated_bytes, _result(
        annotations=annotation_entries,
        warnings=warn_list if warn_list else None,
        **extra_meta,
    )
