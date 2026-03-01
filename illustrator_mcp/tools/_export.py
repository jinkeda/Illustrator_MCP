"""
Export tool for Adobe Illustrator.

Extracted from documents.py for readability.
"""

import base64
import json
import logging
import os
from typing import Union

from mcp.types import ImageContent
from illustrator_mcp.shared import mcp
from illustrator_mcp import templates
from illustrator_mcp.tools.base import ToolInputBase, TOOL_ANNOTATIONS
from illustrator_mcp.utils import escape_path_for_jsx
from illustrator_mcp.proxy_client import execute_script_with_context, format_envelope
from illustrator_mcp.libraries import get_injection_metadata

from illustrator_mcp.tools._models import ExportFormat, ExportDocumentInput

logger = logging.getLogger(__name__)


_EXPORT_NAME = "illustrator_export_document"


@mcp.tool(name=_EXPORT_NAME, annotations=TOOL_ANNOTATIONS[_EXPORT_NAME])
async def illustrator_export_document(params: ExportDocumentInput) -> Union[str, list]:
    """Export the active document to PNG, JPG, SVG, or PDF.

    CONTRACT: readOnly=False, destructive=True, idempotent=False, openWorld=True

    WHEN TO USE:
      - Generating raster output (PNG, JPG) with optional scale factor
      - Exporting vector formats (SVG, PDF)
      - Getting visual feedback by setting return_image=True (PNG/JPG only)

    EXAMPLES:
      illustrator_export_document(file_path="C:/out/fig.png", format="png", scale=2.0)
      illustrator_export_document(file_path="C:/out/fig.pdf", format="pdf")
      illustrator_export_document(file_path="C:/out/fig.png", return_image=True, artboard_only=True)

    NOTES:
      - artboard_only=True clips export to artboard; a pre-check warns if nothing is on it
      - PDF export uses saveAs (longer timeout)
      - return_image returns base64 image bytes as ImageContent for visual verification
      - Overwrites existing file at file_path (destructive to filesystem)
    """
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
                    bt = count.get('bounds_type', 'visible')
                    warnings.append(
                        f"Pre-check found 0 intersecting items using "
                        f"{bt}Bounds; SVG/gradient/pattern items may be "
                        f"undercounted. See diagnostics."
                    )
                # Structured pre-check diagnostics
                diagnostics["precheck_item_count"] = count.get('on_artboard', 0)
                diagnostics["precheck_method"] = f"{count.get('bounds_type', 'visible')}Bounds"
                diagnostics["precheck_artboard"] = {
                    "rect": count.get('artboard_rect'),
                    "space": "illustrator_native_y_up",
                }
                diagnostics["precheck_skipped_count"] = count.get('skipped', 0)
                diagnostics["precheck_off_artboard"] = count.get('off_artboard', 0)
                diagnostics["precheck_sample_misses"] = count.get('off_items_sample', [])
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
