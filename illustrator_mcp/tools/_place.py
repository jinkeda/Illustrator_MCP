"""
Place file and reference overlay tools for Adobe Illustrator.

Extracted from documents.py for readability.
"""

import json
import logging
import os
import uuid
from typing import Optional

from pydantic import Field

from illustrator_mcp.shared import mcp
from illustrator_mcp import templates
from illustrator_mcp.tools.base import execute_jsx_tool, ToolInputBase, TOOL_ANNOTATIONS
from illustrator_mcp.utils import escape_path_for_jsx

logger = logging.getLogger(__name__)


# ==================== Place File ====================

_TRACEABLE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".psd"}


async def _place_item_impl(
    file_path: str,
    x: float,
    y: float,
    linked: bool,
    command_type: str,
    tool_name: str,
    error_prefix: str = "File",
    embed_editable: bool = False,
    trace: bool = False,
    trace_preset: str | None = None,
    expand: bool = True,
) -> str:
    """Shared implementation for placing files (images, EPS, AI, PDF) into the document.
    
    Args:
        embed_editable: If True, opens the file (PDF) and copies content as editable vectors
                       instead of placing as a linked/embedded item.
    """
    path = escape_path_for_jsx(file_path)
    trace_marker = f"@mcp:trace_target={uuid.uuid4().hex[:12]}" if trace else None
    marker_line = f'placed.note = "{trace_marker}";' if trace_marker else ""
    
    if embed_editable:
        script = templates.EMBED_EDITABLE.substitute(
            path=path,
            x=x,
            neg_y=-y,
            y=y,
        )
    else:
        embed_line = "" if linked else "placed.embed();"
        script = templates.PLACE_ITEM.substitute(
            path=path,
            x=x,
            neg_y=-y,
            y=y,
            linked=str(linked).lower(),
            embed_line=embed_line,
            marker_line=marker_line,
            error_prefix=error_prefix
        )
    
    place_result = await execute_jsx_tool(
        script=script,
        command_type=command_type,
        tool_name=tool_name,
        params={"file_path": file_path, "x": x, "y": y, "linked": linked, "embed_editable": embed_editable}
    )

    # Step 2: Image Trace (if requested)
    if trace and trace_marker:
        preset_json = json.dumps(trace_preset)  # null or '"6 Colors"'
        trace_script = templates.TRACE_PLACED_IMAGE.substitute(
            marker=trace_marker,
            preset=preset_json,
            expand=str(expand).lower(),
        )
        return await execute_jsx_tool(
            script=trace_script,
            command_type="trace_image",
            tool_name=tool_name,
            params={"trace_preset": trace_preset, "expand": expand},
        )

    return place_result


class PlaceFileInput(ToolInputBase):
    """Input for placing a file."""
    file_path: str = Field(..., description="Full path to file (EPS, AI, PDF, PNG, etc.)", min_length=1)
    x: float = Field(default=0, description="X position")
    y: float = Field(default=0, description="Y position")
    linked: bool = Field(default=True, description="Keep linked (True) or embed immediately (False)")
    embed_editable: bool = Field(default=False, description="Open PDF and paste as editable vectors (slower but fully editable)")
    trace: bool = Field(default=False, description="Run Image Trace on placed raster to convert to vectors")
    trace_preset: Optional[str] = Field(
        default=None,
        description="Image Trace preset: '3 Colors', '6 Colors', '16 Colors', 'High Fidelity Photo', "
                    "'Low Fidelity Photo', 'Black and White Logo', 'Silhouettes', 'Line Art', "
                    "'Technical Drawing', 'Sketched Art'. None = Illustrator default."
    )
    expand: bool = Field(
        default=True,
        description="Expand traced result to editable paths (True, more DOM but fully editable) "
                    "or keep as live trace PluginItem (False, lighter but limited editability)"
    )

    def model_post_init(self, __context) -> None:
        """Validate trace-specific constraints."""
        if self.trace and self.embed_editable:
            raise ValueError("Cannot use both trace=True and embed_editable=True")
        if self.trace:
            ext = os.path.splitext(self.file_path)[1].lower()
            if ext not in _TRACEABLE_EXTENSIONS:
                raise ValueError(
                    f"trace=True requires a raster image "
                    f"({', '.join(sorted(_TRACEABLE_EXTENSIONS))}), got '{ext}'"
                )


_PLACE_NAME = "illustrator_place_file"


@mcp.tool(name=_PLACE_NAME, annotations=TOOL_ANNOTATIONS[_PLACE_NAME])
async def illustrator_place_file(params: PlaceFileInput) -> str:
    """Place an external file (EPS, AI, PDF, image) into the document.

    CONTRACT: readOnly=False, destructive=True, idempotent=False, openWorld=True

    WHEN TO USE:
      - Importing raster images (PNG, JPG) into Illustrator
      - Placing vector files (EPS, AI, PDF, SVG)
      - Vectorizing raster images via Image Trace (trace=True)

    KEY CONCEPTS:
      linked=True (drafting) — file updates automatically when source changes
      linked=False (final) — file is embedded and fully editable
      embed_editable=True — opens PDF, copies content as editable vectors (slower)
      trace=True — place raster, then run Image Trace to vectorize

    EXAMPLES:
      illustrator_place_file(file_path="C:/img/photo.png", x=100, y=50, linked=True)
      illustrator_place_file(file_path="C:/img/photo.png", trace=True, trace_preset="6 Colors")

    NOTES:
      - trace + expand=True: editable paths, higher DOM complexity
      - trace + expand=False: live trace PluginItem, lighter but limited editability
      - High-complexity images may produce >2000 paths (warning emitted)
      - Reads external files from filesystem (openWorld)
    """
    return await _place_item_impl(
        file_path=params.file_path,
        x=params.x,
        y=params.y,
        linked=params.linked,
        command_type="place_file",
        tool_name="illustrator_place_file",
        error_prefix="File",
        embed_editable=params.embed_editable,
        trace=params.trace,
        trace_preset=params.trace_preset,
        expand=params.expand,
    )


# ==================== Reference Overlay ====================

_REFERENCE_LAYER_NAME = "__reference__"

# Backward-compat alias (moved to templates.SET_REFERENCE)
_SET_REFERENCE_JSX = templates.SET_REFERENCE


class SetReferenceInput(ToolInputBase):
    """Input for setting or clearing a reference overlay image."""
    file_path: Optional[str] = Field(
        default=None,
        description="Path to reference image (PNG/JPG). Omit to remove existing reference."
    )
    opacity: float = Field(
        default=40.0,
        description="Image opacity 0-100 (default 40 for dim tracing)",
        ge=0, le=100
    )
    fit: bool = Field(
        default=True,
        description="Scale image proportionally to fit active artboard"
    )


def _extract_dominant_colors(
    file_path: str,
    max_colors: int = 8,
    max_dimension: int = 512,
    dedup_distance: float = 30.0,
) -> list[dict]:
    """Extract dominant colors from an image using Pillow quantization.

    Args:
        file_path: Path to the image file.
        max_colors: Maximum number of colors to extract (quantize target).
        max_dimension: Downscale longest side to this before quantizing.
        dedup_distance: Euclidean RGB distance threshold for deduplication.

    Returns:
        List of dicts sorted by percentage descending:
        [{"r": int, "g": int, "b": int, "hex": "#RRGGBB", "percentage": float}, ...]
    """
    try:
        from PIL import Image
    except ImportError:
        logger.debug("Pillow not available for dominant color extraction")
        return []

    try:
        img = Image.open(file_path)
        img = img.convert("RGB")

        # Downscale for performance
        w, h = img.size
        if max(w, h) > max_dimension:
            scale = max_dimension / max(w, h)
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.LANCZOS,
            )

        # Quantize to N colors
        quantized = img.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette()  # flat [R,G,B, R,G,B, ...]
        if not palette:
            return []

        # Count pixels per palette index
        pixel_counts = quantized.getdata()
        total_pixels = len(pixel_counts)
        counts: dict[int, int] = {}
        for idx in pixel_counts:
            counts[idx] = counts.get(idx, 0) + 1

        # Build raw color list
        raw_colors = []
        for idx, count in sorted(counts.items(), key=lambda x: -x[1]):
            if idx * 3 + 2 >= len(palette):
                continue
            r, g, b = palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2]
            pct = round(100.0 * count / total_pixels, 1)
            raw_colors.append({"r": r, "g": g, "b": b, "percentage": pct})

        # Deduplicate near-colors (merge into higher-percentage neighbor)
        deduped: list[dict] = []
        for c in raw_colors:
            merged = False
            for d in deduped:
                dist = ((c["r"] - d["r"]) ** 2 + (c["g"] - d["g"]) ** 2 + (c["b"] - d["b"]) ** 2) ** 0.5
                if dist < dedup_distance:
                    d["percentage"] = round(d["percentage"] + c["percentage"], 1)
                    merged = True
                    break
            if not merged:
                deduped.append(dict(c))

        # Add hex and sort
        for c in deduped:
            c["hex"] = f"#{c['r']:02X}{c['g']:02X}{c['b']:02X}"

        deduped.sort(key=lambda x: -x["percentage"])
        return deduped

    except Exception as e:
        logger.warning("Dominant color extraction failed: %s", e)
        return []


_REF_NAME = "illustrator_set_reference"


@mcp.tool(name=_REF_NAME, annotations=TOOL_ANNOTATIONS[_REF_NAME])
async def illustrator_set_reference(params: SetReferenceInput) -> str:
    """Set or clear a reference image on a locked background layer for tracing.

    CONTRACT: readOnly=False, destructive=True, idempotent=True, openWorld=True

    WHEN TO USE:
      - Preparing a reference image overlay before manual or automated tracing
      - Clearing a previous reference (omit file_path)

    KEY CONCEPTS:
      Places image on a dedicated '__reference__' layer at the bottom of the stack.
      Layer is locked, dimmed, and non-printable to prevent accidental edits.
      Calling again with the same file replaces the previous reference (idempotent).

    EXAMPLES:
      illustrator_set_reference(file_path="C:/ref/sketch.png", opacity=50)
      illustrator_set_reference()  -- clears the reference layer

    NOTES:
      - Removal mode (no file_path) is destructive — deletes the reference layer
      - Uses the active artboard for fit/center calculations
      - Extracts dominant colors from reference image if Pillow is available
    """
    payload = params.model_dump()
    payload["layer_name"] = _REFERENCE_LAYER_NAME
    payload_json = json.dumps(payload)

    script = templates.SET_REFERENCE % payload_json

    result = await execute_jsx_tool(
        script=script,
        command_type="set_reference",
        tool_name="illustrator_set_reference",
        params=payload
    )

    # Extract dominant colors from the reference image (if setting, not clearing)
    if params.file_path:
        resolved = os.path.abspath(params.file_path)
        if os.path.isfile(resolved):
            colors = _extract_dominant_colors(resolved)
            if colors:
                try:
                    parsed = json.loads(result)
                    # Inject into result (not top-level) to preserve 5-key envelope
                    if isinstance(parsed.get("result"), dict):
                        parsed["result"]["dominant_colors"] = colors
                    elif parsed.get("result") is None:
                        parsed["result"] = {"dominant_colors": colors}
                    else:
                        # result is a non-dict (string) — put in diagnostics instead
                        parsed.setdefault("diagnostics", {})["dominant_colors"] = colors
                    result = json.dumps(parsed)
                except (json.JSONDecodeError, TypeError):
                    pass  # Non-JSON response — skip color injection

    return result
