"""
Document operation tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

import json
import logging
import os
import uuid
from typing import Literal, Optional, Union
from enum import Enum

from pydantic import Field

from mcp.types import ImageContent
from illustrator_mcp.shared import mcp
from illustrator_mcp import templates
from illustrator_mcp.tools.base import execute_jsx_tool, ToolInputBase
from illustrator_mcp.utils import escape_path_for_jsx
from illustrator_mcp.proxy_client import execute_script_with_context, format_envelope
from illustrator_mcp.errors import make_envelope
from illustrator_mcp.libraries import get_injection_metadata

logger = logging.getLogger(__name__)


class ExportFormat(str, Enum):
    """Export file formats."""
    PNG = "png"
    JPG = "jpg"
    SVG = "svg"
    PDF = "pdf"


# Pydantic models - inherit from ToolInputBase for shared config
class DocumentInput(ToolInputBase):
    """Unified input for document create/open/save/close operations."""
    action: Literal["create", "open", "save", "close"] = Field(
        ..., description="Action: 'create', 'open', 'save', or 'close'"
    )
    # create params
    width: float = Field(default=800, description="Width in points (create)", ge=1, le=16383)
    height: float = Field(default=600, description="Height in points (create)", ge=1, le=16383)
    name: Optional[str] = Field(default=None, description="Document name (create)", max_length=255)
    color_mode: str = Field(default="RGB", description="RGB or CMYK (create)")
    # open/save params
    file_path: Optional[str] = Field(default=None, description="File path (required for open, optional for save-as)")
    # close params
    save_before_close: bool = Field(default=False, description="Save before closing (close)")

    def model_post_init(self, __context) -> None:
        """Validate action-specific required fields."""
        if self.action == "open" and not self.file_path:
            raise ValueError("file_path is required for action='open'")


class ExportDocumentInput(ToolInputBase):
    """Input for exporting a document."""
    file_path: str = Field(..., description="Full output path with extension (e.g. C:/output/figure.png)", min_length=1)
    format: ExportFormat = Field(default=ExportFormat.PNG, description="Export format")
    scale: float = Field(default=1.0, description="Scale factor", ge=0.1, le=10.0)
    artboard_only: bool = Field(default=False, description="Clip export to artboard bounds")
    artboard_index: Optional[int] = Field(default=None, description="Artboard index (None = active artboard)")
    return_image: bool = Field(default=False, description="Return image bytes for Claude visualization (PNG/JPG only)")


# ==================== Helper Functions ====================

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


# Unified document CRUD tool
@mcp.tool(
    name="illustrator_document",
    annotations={"title": "Document", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_document(params: DocumentInput) -> str:
    """Create, open, save, or close an Illustrator document.

    Args:
        params.action: 'create', 'open', 'save', or 'close'
        params.width/height/name/color_mode: create params
        params.file_path: required for open, optional for save-as
        params.save_before_close: close param
    """
    action = params.action

    if action == "create":
        color_space = 'CMYK' if params.color_mode == 'CMYK' else 'RGB'
        title_line = f'preset.title = "{params.name}";' if params.name else ''
        script = templates.CREATE_DOCUMENT.substitute(
            width=params.width,
            height=params.height,
            color_space=color_space,
            title_line=title_line
        )
        return await execute_jsx_tool(
            script=script,
            command_type="create_document",
            tool_name="illustrator_document",
            params={"action": action, "width": params.width, "height": params.height,
                    "name": params.name, "color_mode": params.color_mode}
        )

    elif action == "open":
        path = escape_path_for_jsx(params.file_path)
        script = templates.OPEN_DOCUMENT.substitute(path=path)
        return await execute_jsx_tool(
            script=script,
            command_type="open_document",
            tool_name="illustrator_document",
            params={"action": action, "file_path": params.file_path}
        )

    elif action == "save":
        if params.file_path:
            path = escape_path_for_jsx(params.file_path)
            script = templates.SAVE_DOCUMENT.substitute(path=path)
        else:
            script = templates.SAVE_DOCUMENT_SIMPLE
        return await execute_jsx_tool(
            script=script,
            command_type="save_document",
            tool_name="illustrator_document",
            params={"action": action, "file_path": params.file_path}
        )

    elif action == "close":
        save_option = "SaveOptions.SAVECHANGES" if params.save_before_close else "SaveOptions.DONOTSAVECHANGES"
        script = templates.CLOSE_DOCUMENT.substitute(save_option=save_option)
        return await execute_jsx_tool(
            script=script,
            command_type="close_document",
            tool_name="illustrator_document",
            params={"action": action, "save_before_close": params.save_before_close}
        )


@mcp.tool(
    name="illustrator_export_document",
    annotations={"title": "Export Document", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_export_document(params: ExportDocumentInput) -> Union[str, list]:
    """Export the document to PNG, JPG, SVG, or PDF."""
    path = escape_path_for_jsx(params.file_path)
    scale = params.scale * 100
    fmt_name = params.format.value.upper()

    warnings = []

    # Ensure parent directory exists
    parent_dir = os.path.dirname(os.path.abspath(params.file_path))
    if not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)
        warnings.append(f"Created directory: {parent_dir}")

    # Get canonicalized includes metadata (for precheck)
    export_meta = get_injection_metadata(["validate"])
    diagnostics = {
        "file_path": params.file_path,
        "format": params.format.value,
        "scale": params.scale,
        "artboard_only": params.artboard_only,
        "artboard_index": params.artboard_index,
        "precheck_includes": export_meta["includes_canonical"],
        "precheck_prelude_hash": export_meta["prelude_hash"]
    }

    # Pre-export bounds check if artboard_only
    if params.artboard_only:
        ab_idx = params.artboard_index if params.artboard_index is not None else 'null'
        check_script = f"""
        countItemsOnArtboard({{
            artboardIndex: {ab_idx},
            boundsType: "visible",
            ignoreHidden: true,
            ignoreLocked: true,
            policy: "intersects",
            scope: "artboard"
        }});
        """
        try:
            check_response = await execute_script_with_context(
                script=check_script,
                command_type="export_precheck",
                tool_name="illustrator_export_document",
                includes=["validate"]
            )
            if check_response.get("error"):
                warnings.append(f"Pre-export check failed: {check_response['error']}")
            else:
                # CEP returns {"success": bool, "result": "JSON string"}
                cep_result = check_response.get("result", {})
                if isinstance(cep_result, str):
                    cep_result = json.loads(cep_result)

                # Extract inner result (the actual validation data)
                inner_result = cep_result.get("result", "{}")
                if isinstance(inner_result, str):
                    count = json.loads(inner_result)
                else:
                    count = inner_result

                if count.get('on_artboard', 0) == 0:
                    warnings.append("Nothing intersects artboard - export will be blank")
                diagnostics["precheck_result"] = count
        except Exception as e:
            warnings.append(f"Pre-export check failed: {e}")

    # Config-driven export
    export_configs = {
        ExportFormat.PNG: {"options": "ExportOptionsPNG24", "type": "ExportType.PNG24", "scales": True},
        ExportFormat.JPG: {"options": "ExportOptionsJPEG", "type": "ExportType.JPEG", "scales": True},
        ExportFormat.SVG: {"options": "ExportOptionsSVG", "type": "ExportType.SVG", "scales": False},
        ExportFormat.PDF: {"options": "PDFSaveOptions", "type": None, "scales": False},
    }

    fmt_config = export_configs[params.format]

    # Build export script with artboard clipping support
    if fmt_config["type"]:  # Standard exportFile (PNG, JPG, SVG)
        ab_index_js = params.artboard_index if params.artboard_index is not None else 'doc.artboards.getActiveArtboardIndex()'
        artboard_clip = "true" if params.artboard_only else "false"

        scale_opts = ""
        if fmt_config["scales"]:
            scale_opts = f"""
            opts.horizontalScale = {scale};
            opts.verticalScale = {scale};"""

        # For PNG, add artBoardClipping option
        clip_opt = ""
        if params.format == ExportFormat.PNG:
            clip_opt = f"opts.artBoardClipping = {artboard_clip};"

        script = templates.EXPORT_STANDARD.substitute(
            ab_index_js=ab_index_js,
            options_class=fmt_config["options"],
            scale_opts=scale_opts,
            clip_opt=clip_opt,
            path=path,
            export_type=fmt_config["type"],
            scale=scale,
            fmt_name=fmt_name,
            artboard_clip=artboard_clip,
        )
    else:  # PDF uses saveAs
        script = templates.EXPORT_PDF.substitute(path=path)

    # Execute export (PDF gets longer timeout due to complexity)
    response = await execute_script_with_context(
        script=script,
        command_type="export_document",
        tool_name="illustrator_export_document",
        params={"file_path": params.file_path, "format": params.format.value, "scale": params.scale},
        timeout=60.0 if params.format == ExportFormat.PDF else None
    )

    envelope = format_envelope(
        response=response,
        context="export_document",
        warnings=warnings,
        diagnostics=diagnostics
    )

    # Return image bytes for visual feedback if requested
    if params.return_image and params.format in [ExportFormat.PNG, ExportFormat.JPG]:
        try:
            import base64
            with open(params.file_path, 'rb') as f:
                img_bytes = f.read()
            mime_type = "image/png" if params.format == ExportFormat.PNG else "image/jpeg"
            # Return both envelope JSON and image content
            return [
                {"type": "text", "text": envelope},
                ImageContent(
                    type="image",
                    data=base64.b64encode(img_bytes).decode('utf-8'),
                    mimeType=mime_type
                )
            ]
        except Exception as e:
            # Image read is best-effort; return the original text envelope
            logger.warning(f"Failed to read exported image for return: {e}")
            return envelope

    return envelope






# Combined Undo/Redo tool
class HistoryInput(ToolInputBase):
    """Input for undo/redo and named checkpoint operations."""
    action: Literal[
        "undo", "redo",
        "checkpoint_save", "checkpoint_restore",
        "checkpoint_list", "checkpoint_delete"
    ] = Field(default="undo", description="Action to perform")
    count: int = Field(default=1, description="Number of times to undo/redo", ge=1, le=100)
    name: Optional[str] = Field(
        default=None,
        description="Checkpoint name (required for save/restore/delete)",
        max_length=64
    )

    @classmethod
    def model_validate(cls, *args, **kwargs):
        instance = super().model_validate(*args, **kwargs)
        if instance.action.startswith("checkpoint_") and instance.action != "checkpoint_list":
            if not instance.name or not instance.name.strip():
                raise ValueError(f"{instance.action} requires a non-empty 'name'")
        return instance


async def _handle_checkpoint(params: HistoryInput) -> str:
    """Dispatch checkpoint actions to checkpoint.jsx functions."""
    action_map = {
        "checkpoint_save": "checkpointSave",
        "checkpoint_restore": "checkpointRestore",
        "checkpoint_list": "checkpointList",
        "checkpoint_delete": "checkpointDelete",
    }
    if params.action not in action_map:
        return make_envelope(ok=False, error=f"Unknown checkpoint action: {params.action}")

    jsx_fn = action_map[params.action]

    if params.action == "checkpoint_list":
        name_arg = ""
    else:
        escaped_name = params.name.replace("\\", "\\\\").replace('"', '\\"')
        name_arg = f'"{ escaped_name}", '

    script = templates.CHECKPOINT_ACTION.substitute(
        jsx_fn=jsx_fn,
        name_arg=name_arg,
    )

    return await execute_jsx_tool(
        script=script,
        command_type=params.action,
        tool_name="illustrator_history",
        params={"action": params.action, "name": params.name},
        includes=["polyfills", "checkpoint"]
    )


@mcp.tool(
    name="illustrator_history",
    annotations={"title": "Undo/Redo History", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_history(params: HistoryInput) -> str:
    """Undo or redo actions in Illustrator.
    
    Args:
        action: 'undo' to revert changes, 'redo' to restore undone changes
        count: Number of times to perform the action (default 1)
    
    Use this to revert mistakes or restore undone changes.
    
    Checkpoint actions:
        checkpoint_save: Save current state as a named checkpoint (requires 'name')
        checkpoint_restore: Restore document to a saved checkpoint (requires 'name')
        checkpoint_list: List all checkpoints for the current document
        checkpoint_delete: Delete a named checkpoint (requires 'name')
    
    Note: Checkpoints capture MCP-managed items only (those with @mcp:id).
    Restore is mutate-in-place and may require multiple undo steps to revert.
    """
    # Dispatch checkpoint actions
    if params.action.startswith("checkpoint_"):
        return await _handle_checkpoint(params)

    # Original undo/redo logic
    if params.action not in ("undo", "redo"):
        return make_envelope(ok=False, error="Invalid action. Use 'undo' or 'redo'")
    
    template = templates.UNDO if params.action == "undo" else templates.REDO
    
    # For count > 1, we need to modify the script to loop
    if params.count > 1:
        script = templates.HISTORY_MULTI.substitute(
            action_method="undo" if params.action == "undo" else "redo",
            count=params.count,
            action_name=params.action
        )
    else:
        script = template
    
    return await execute_jsx_tool(
        script=script,
        command_type=params.action,
        tool_name="illustrator_history",
        params={"action": params.action, "count": params.count}
    )


# Pydantic models for place/embed
_TRACEABLE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".psd"}


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


@mcp.tool(
    name="illustrator_place_file",
    annotations={"title": "Place File", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_place_file(params: PlaceFileInput) -> str:
    """Place an external file (EPS, AI, PDF, image) into the document.
    
    Supports all placeable formats: PNG, JPG, EPS, AI, PDF, SVG, etc.
    For raster images (PNG, JPG), this is the standard way to import them.
    
    Workflow:
    - linked=True (drafting): File updates automatically when source changes
    - linked=False (final): File is embedded and fully editable
    - embed_editable=True: Opens PDF, copies content as editable vectors (slower)
    - trace=True: Place raster image, then run Image Trace to vectorize it.
      The AI acts as art director (selecting presets, recoloring, simplifying)
      rather than manually computing paths.
    
    Trace notes:
    - expand=True (default): Converts to editable PathItem/CompoundPathItem group.
      Higher DOM complexity, but paths are fully editable and support boolean ops.
    - expand=False: Keeps live trace PluginItem. Lighter DOM, but limited editability.
    - High-complexity images may produce thousands of paths. A warning is emitted
      if the expanded group exceeds 2000 items.
    
    Use linked=True during iterative work (e.g., updating MATLAB plots),
    then embed when ready for submission.
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


@mcp.tool(
    name="illustrator_set_reference",
    annotations={"title": "Set Reference Overlay", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_set_reference(params: SetReferenceInput) -> str:
    """Set or clear a reference image on a locked background layer for tracing.

    Places a reference image on a dedicated '__reference__' layer at the bottom
    of the layer stack. The layer is locked, dimmed, and non-printable to prevent
    accidental edits or export contamination.

    Modes:
    - Set: Provide file_path to place/replace a reference image
    - Clear: Omit file_path (or pass null) to remove the reference layer

    Idempotent: calling again replaces the previous reference automatically.
    Uses the active artboard for fit/center calculations.
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

