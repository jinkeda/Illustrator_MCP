"""
Place file and reference overlay tools for Adobe Illustrator.

Extracted from documents.py for readability.
"""

import json
import logging
import os
import uuid
from typing import Literal, Optional

from illustrator_mcp.tools.base import MutationInputBase
from pydantic import ConfigDict, Field, model_validator

from mcp.types import CallToolResult
from illustrator_mcp.shared import mcp
from illustrator_mcp import templates
from illustrator_mcp.tools.base import execute_jsx_tool, ToolInputBase, TOOL_ANNOTATIONS, canonical_tool, forbid_extra_tool_arguments
from illustrator_mcp.proxy_client import build_envelope_dict, execute_script_with_context
from illustrator_mcp.utils import escape_path_for_jsx
from illustrator_mcp.utils.response import unwrap_jsx_result

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
    mcp_id: str | None = None,
) -> str:
    """Shared implementation for placing files (images, EPS, AI, PDF) into the document.

    Placement and tracing are two host scripts but **one job**: they are run
    inside a single coordinator reservation so nothing else can execute against
    the document between placing the image and tracing it, and so a failed
    trace is attributed to the job that placed the artwork.

    Args:
        embed_editable: If True, opens the file (PDF) and copies content as editable vectors
                       instead of placing as a linked/embedded item.
        mcp_id: Identity to stamp on the resulting artwork. Generated when not
                given, and always reported back, so a caller can address what it
                just imported instead of guessing.
    """
    path = escape_path_for_jsx(file_path)
    placed_id = mcp_id or f"img_{uuid.uuid4().hex[:10]}"
    trace_marker = f"@mcp:trace_target={uuid.uuid4().hex[:12]}" if trace else None

    # Both the ID and the trace marker are stamped on the item that SURVIVES an
    # embed(), never on the pre-embed reference: embed() discards `note`, and
    # the old reference lives on as a zombie that keeps reporting the note it
    # no longer has. Writing the marker through it is why tracing an embedded
    # image always failed to find its target.
    marker_line = (
        f'item.note = (item.note ? item.note + " " : "") + "{trace_marker}";'
        if trace_marker else ""
    )

    if embed_editable:
        script = templates.EMBED_EDITABLE.substitute(
            path=path,
            x=x,
            neg_y=-y,
            y=y,
            id_line=f'setMcpId(group, "{placed_id}");',
            id_json=json.dumps(placed_id),
        )
    else:
        embed_line = "" if linked else "placed.embed(); embedded = true;"
        script = templates.PLACE_ITEM.substitute(
            path=path,
            x=x,
            neg_y=-y,
            y=y,
            linked=str(linked).lower(),
            embed_line=embed_line,
            marker_line=marker_line,
            error_prefix=error_prefix,
            id_line=f'setMcpId(item, "{placed_id}");',
            id_json=json.dumps(placed_id),
            tmp_name=f"__mcp_placing_{uuid.uuid4().hex[:8]}__",
        )

    place_result = await execute_jsx_tool(
        script=script,
        command_type=command_type,
        tool_name=tool_name,
        params={"file_path": file_path, "x": x, "y": y, "linked": linked,
                "embed_editable": embed_editable, "id": placed_id},
        includes=["mcp_id"],
    )

    if not trace or not trace_marker:
        return place_result

    # Step 2: Image Trace. Only reached when step 1 placed something,
    # so a failure here must say the artwork already exists rather than
    # inviting a retry that places a second copy.
    if not _envelope_ok(place_result):
        return place_result

    preset_json = json.dumps(trace_preset)  # null or '"6 Colors"'
    trace_script = templates.TRACE_PLACED_IMAGE.substitute(
        marker=trace_marker,
        preset=preset_json,
        expand=str(expand).lower(),
        placed_id=placed_id,
    )
    trace_result = await execute_jsx_tool(
        script=trace_script,
        command_type="trace_image",
        tool_name=tool_name,
        params={"trace_preset": trace_preset, "expand": expand, "id": placed_id},
    )
    return _annotate_placement(trace_result, placed_id)


def _envelope_ok(raw: str) -> bool:
    """Whether a host envelope string reports success."""
    try:
        return bool(json.loads(raw).get("ok"))
    except (ValueError, TypeError, AttributeError):
        return False


def _annotate_placement(raw: str, placed_id: str) -> str:
    """Record the placed artwork's identity on a trace result.

    The placement is durable whether or not the trace succeeded, so both
    outcomes must carry the ID: on success it identifies the traced artwork, on
    failure it is what stops a retry from importing the image twice.
    """
    try:
        envelope = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if not isinstance(envelope, dict):
        return raw

    ok = bool(envelope.get("ok"))
    result = envelope.get("result")
    if not isinstance(result, dict):
        result = {} if result is None else {"detail": result}
        envelope["result"] = result

    result.setdefault("id", placed_id)
    if ok:
        # Tracing consumed the placed raster; the traced artwork carries the
        # requested ID and no separate placed item remains to report.
        result["placementRetained"] = False
    else:
        result.setdefault("placedId", placed_id)
        result["placementRetained"] = True

    if not envelope.get("ok"):
        warnings = envelope.get("warnings")
        if not isinstance(warnings, list):
            warnings = []
        warnings.append(
            f"The image was placed as {placed_id} and is still in the document. "
            f"Retry the trace against it rather than placing the file again."
        )
        envelope["warnings"] = warnings
    return json.dumps(envelope)


class PlaceFileInput(MutationInputBase):
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
    id: Optional[str] = Field(
        default=None,
        description="MCP ID to stamp on the imported artwork so it can be targeted "
                    "afterwards. Generated when omitted; always returned."
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
@canonical_tool(_PLACE_NAME, reserve=True)
async def illustrator_place_file(params: PlaceFileInput) -> CallToolResult:
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
      Place a linked image:
        {"params": {"file_path": "C:/img/photo.png", "x": 100, "y": 50, "linked": true}}
      Place and auto-trace:
        {"params": {"file_path": "C:/img/photo.png", "trace": true, "trace_preset": "6 Colors"}}

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
        mcp_id=params.id,
    )


# ==================== Reference Overlay ====================

_REFERENCE_LAYER_NAME = "__reference__"

# Backward-compat alias (moved to templates.SET_REFERENCE)
_SET_REFERENCE_JSX = templates.SET_REFERENCE


class SetReferenceInput(MutationInputBase):
    """Input for setting or clearing a reference overlay image."""
    model_config = ConfigDict(extra="forbid")

    action: Literal["set", "clear"] = Field(
        default="set",
        description="Use set with a file, or clear alone to remove the reference. "
                    "A legacy nonempty file_path without action still means set."
    )
    file_path: Optional[str] = Field(
        default=None,
        description="Nonempty path to reference image (PNG/JPG), required for set."
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

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "clear":
            conflicts = self.model_fields_set & {"file_path", "opacity", "fit"}
            if conflicts:
                raise ValueError(
                    "action='clear' accepts no placement arguments; omit "
                    + ", ".join(sorted(conflicts))
                )
        elif not self.file_path:
            raise ValueError(
                "Setting a reference requires a nonempty file_path. Empty calls "
                "no longer clear artwork; use action='clear' alone to remove it."
            )
        return self


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


@forbid_extra_tool_arguments(mcp, _REF_NAME)
@mcp.tool(name=_REF_NAME, annotations=TOOL_ANNOTATIONS[_REF_NAME])
@canonical_tool(_REF_NAME, reserve=True)
async def illustrator_set_reference(params: SetReferenceInput) -> CallToolResult:
    """Set or clear a reference image on a locked background layer for tracing.

    CONTRACT: readOnly=False, destructive=True, idempotent=True, openWorld=True

    WHEN TO USE:
      - Preparing a reference image overlay before manual or automated tracing
      - Clearing a previous reference (action="clear")

    KEY CONCEPTS:
      Places image on a dedicated '__reference__' layer at the bottom of the stack.
      Layer is locked, dimmed, and non-printable to prevent accidental edits.
      Calling again with the same file replaces the previous reference (idempotent).

    EXAMPLES:
      Set a dimmed tracing reference:
        {"params": {"action": "set", "file_path": "C:/ref/sketch.png", "opacity": 50}}
      Legacy set (still accepted):
        {"params": {"file_path": "C:/ref/sketch.png"}}
      Clear the reference layer:
        {"params": {"action": "clear"}}

    NOTES:
      - Clear deletes the reference layer; omit file_path, opacity and fit
      - Empty calls now reject; migrate old empty clears to action="clear"
      - Legacy nonempty file_path without action still means set
      - Uses the active artboard for fit/center calculations
      - Extracts dominant colors from reference image if Pillow is available
    """
    payload = params.model_dump() if params.action == "set" else {"action": "clear"}
    payload["layer_name"] = _REFERENCE_LAYER_NAME
    payload_json = json.dumps(payload)

    script = templates.SET_REFERENCE % payload_json

    response = await execute_script_with_context(
        script=script,
        command_type="set_reference",
        tool_name="illustrator_set_reference",
        params=payload
    )
    envelope = build_envelope_dict(response, context="set_reference", diagnostics={
        "tool": _REF_NAME, "command": "set_reference", "includes": [],
    })
    # The generic formatter drops domain data on error. Retain this producer's
    # explicit cleanup/effects report without changing unrelated tool adapters.
    host_result = unwrap_jsx_result(response, context="set_reference")
    if not envelope["ok"] and host_result.get("ok") is False:
        failure_data = host_result.get("data")
        if isinstance(failure_data, dict):
            envelope["result"] = failure_data
    result = json.dumps(envelope)

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
