"""
Document operation tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

import json
import os
from typing import Optional, Union
from enum import Enum

from pydantic import Field

from mcp.types import ImageContent
from illustrator_mcp.shared import mcp
from illustrator_mcp.tools.base import execute_jsx_tool, ToolInputBase
from illustrator_mcp.utils import escape_path_for_jsx
from illustrator_mcp.proxy_client import execute_script_with_context, format_envelope
from illustrator_mcp.libraries import inject_libraries, get_injection_metadata
from illustrator_mcp import templates


class ExportFormat(str, Enum):
    """Export file formats."""
    PNG = "png"
    JPG = "jpg"
    SVG = "svg"
    PDF = "pdf"


# Pydantic models - inherit from ToolInputBase for shared config
class CreateDocumentInput(ToolInputBase):
    """Input for creating a new document."""
    width: float = Field(default=800, description="Width in points", ge=1, le=16383)
    height: float = Field(default=600, description="Height in points", ge=1, le=16383)
    name: Optional[str] = Field(default=None, description="Document name", max_length=255)
    color_mode: str = Field(default="RGB", description="RGB or CMYK")


class OpenDocumentInput(ToolInputBase):
    """Input for opening a document."""
    file_path: str = Field(..., description="Full path to the file", min_length=1)


class SaveDocumentInput(ToolInputBase):
    """Input for saving a document."""
    file_path: Optional[str] = Field(default=None, description="Path for Save As")


class ExportDocumentInput(ToolInputBase):
    """Input for exporting a document."""
    file_path: str = Field(..., description="Full output path with extension (e.g. C:/output/figure.png)", min_length=1)
    format: ExportFormat = Field(default=ExportFormat.PNG, description="Export format")
    scale: float = Field(default=1.0, description="Scale factor", ge=0.1, le=10.0)
    artboard_only: bool = Field(default=False, description="Clip export to artboard bounds")
    artboard_index: Optional[int] = Field(default=None, description="Artboard index (None = active artboard)")
    return_image: bool = Field(default=False, description="Return image bytes for Claude visualization (PNG/JPG only)")


class CloseDocumentInput(ToolInputBase):
    """Input for closing a document."""
    save_before_close: bool = Field(default=False, description="Save before closing")


# ==================== Helper Functions ====================

async def _place_item_impl(
    file_path: str,
    x: float,
    y: float,
    linked: bool,
    command_type: str,
    tool_name: str,
    error_prefix: str = "File",
    embed_editable: bool = False
) -> str:
    """Shared implementation for import_image and place_file operations.
    
    Args:
        embed_editable: If True, opens the file (PDF) and copies content as editable vectors
                       instead of placing as a linked/embedded item.
    """
    path = escape_path_for_jsx(file_path)
    
    if embed_editable:
        # Open/copy/paste workflow for editable content
        script = f'''
(function() {{
    var targetDoc = app.activeDocument;
    var targetDocName = targetDoc.name;
    
    try {{
        // Open PDF as new document
        var pdfFile = new File("{path}");
        var pdfDoc = app.open(pdfFile);
        
        // Select all and copy
        pdfDoc.selectObjectsOnActiveArtboard();
        app.executeMenuCommand('copy');
        
        // Close PDF without saving
        pdfDoc.close(SaveOptions.DONOTSAVECHANGES);
        
        // Find and activate target document
        for (var d = 0; d < app.documents.length; d++) {{
            if (app.documents[d].name === targetDocName) {{
                app.activeDocument = app.documents[d];
                targetDoc = app.documents[d];
                break;
            }}
        }}
        
        // Paste
        app.executeMenuCommand('paste');
        
        // Get pasted selection and group
        var sel = targetDoc.selection;
        if (sel && sel.length > 0) {{
            var group;
            if (sel.length > 1) {{
                app.executeMenuCommand('group');
                group = targetDoc.selection[0];
            }} else {{
                group = sel[0];
            }}
            
            // Position
            group.position = [{x}, {-y}];
            
            var bounds = group.geometricBounds;
            targetDoc.selection = null;
            
            return JSON.stringify({{
                success: true,
                type: "editable",
                position: [{x}, {y}],
                width: bounds[2] - bounds[0],
                height: bounds[1] - bounds[3]
            }});
        }}
        throw new Error("No content pasted");
    }} catch(e) {{
        return JSON.stringify({{success: false, error: e.message}});
    }}
}})();
'''
    else:
        embed_line = "" if linked else "placed.embed();"
        script = templates.PLACE_ITEM.substitute(
            path=path,
            x=x,
            neg_y=-y,
            y=y,
            linked=str(linked).lower(),
            embed_line=embed_line,
            error_prefix=error_prefix
        )
    
    return await execute_jsx_tool(
        script=script,
        command_type=command_type,
        tool_name=tool_name,
        params={"file_path": file_path, "x": x, "y": y, "linked": linked, "embed_editable": embed_editable}
    )


# Tool implementations using execute_script
@mcp.tool(
    name="illustrator_create_document",
    annotations={"title": "Create Document", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_create_document(params: CreateDocumentInput) -> str:
    """Create a new Illustrator document with specified dimensions."""
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
        tool_name="illustrator_create_document",
        params={"width": params.width, "height": params.height, "name": params.name, "color_mode": params.color_mode}
    )


@mcp.tool(
    name="illustrator_open_document",
    annotations={"title": "Open Document", "readOnlyHint": True, "destructiveHint": False}
)
async def illustrator_open_document(params: OpenDocumentInput) -> str:
    """Open an existing Illustrator document."""
    path = escape_path_for_jsx(params.file_path)
    script = templates.OPEN_DOCUMENT.substitute(path=path)
    return await execute_jsx_tool(
        script=script,
        command_type="open_document",
        tool_name="illustrator_open_document",
        params={"file_path": params.file_path}
    )


@mcp.tool(
    name="illustrator_save_document",
    annotations={"title": "Save Document", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_save_document(params: SaveDocumentInput) -> str:
    """Save the current Illustrator document."""
    if params.file_path:
        path = escape_path_for_jsx(params.file_path)
        script = templates.SAVE_DOCUMENT.substitute(path=path)
    else:
        script = templates.SAVE_DOCUMENT_SIMPLE
    return await execute_jsx_tool(
        script=script,
        command_type="save_document",
        tool_name="illustrator_save_document",
        params={"file_path": params.file_path}
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
            check_with_lib = inject_libraries(check_script, ["validate"])
            check_response = await execute_script_with_context(
                script=check_with_lib,
                command_type="export_precheck",
                tool_name="illustrator_export_document"
            )
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

    config = export_configs[params.format]

    # Build export script with artboard clipping support
    if config["type"]:  # Standard exportFile (PNG, JPG, SVG)
        ab_index_js = params.artboard_index if params.artboard_index is not None else 'doc.artboards.getActiveArtboardIndex()'
        artboard_clip = "true" if params.artboard_only else "false"

        scale_opts = ""
        if config["scales"]:
            scale_opts = f"""
            opts.horizontalScale = {scale};
            opts.verticalScale = {scale};"""

        # For PNG, add artBoardClipping option
        clip_opt = ""
        if params.format == ExportFormat.PNG:
            clip_opt = f"opts.artBoardClipping = {artboard_clip};"

        script = f"""
(function() {{
    var doc = app.activeDocument;
    var abIdx = {ab_index_js};
    doc.artboards.setActiveArtboardIndex(abIdx);

    var opts = new {config["options"]}();{scale_opts}
    {clip_opt}

    var file = new File("{path}");
    doc.exportFile(file, {config["type"]}, opts);

    var abRect = doc.artboards[abIdx].artboardRect;
    var exportWidth = Math.round((abRect[2] - abRect[0]) * {scale} / 100);
    var exportHeight = Math.round(Math.abs(abRect[3] - abRect[1]) * {scale} / 100);

    return JSON.stringify({{
        success: true,
        path: file.fsName,
        format: "{fmt_name}",
        artboard_index: abIdx,
        artboard_clipping: {artboard_clip},
        width: exportWidth,
        height: exportHeight
    }});
}})();
"""
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
            # Fall back to envelope if image read fails
            warnings.append(f"Failed to read image for return: {e}")
            return format_envelope(
                response=response,
                context="export_document",
                warnings=warnings,
                diagnostics=diagnostics
            )

    return envelope


# NOTE: get_document_info functionality is now in context.py as illustrator_get_document


@mcp.tool(
    name="illustrator_close_document",
    annotations={"title": "Close Document", "readOnlyHint": False, "destructiveHint": True}
)
async def illustrator_close_document(params: CloseDocumentInput) -> str:
    """Close the active document."""
    save_option = "SaveOptions.SAVECHANGES" if params.save_before_close else "SaveOptions.DONOTSAVECHANGES"
    script = templates.CLOSE_DOCUMENT.substitute(save_option=save_option)
    return await execute_jsx_tool(
        script=script,
        command_type="close_document",
        tool_name="illustrator_close_document",
        params={"save_before_close": params.save_before_close}
    )


# Pydantic model for import
class ImportImageInput(ToolInputBase):
    """Input for importing an image."""
    file_path: str = Field(..., description="Full path to the image file (PNG, JPG, etc.)", min_length=1)
    x: float = Field(default=0, description="X position to place the image")
    y: float = Field(default=0, description="Y position to place the image")
    link: bool = Field(default=True, description="Link the image (True) or embed it (False)")


@mcp.tool(
    name="illustrator_import_image",
    annotations={"title": "Import Image", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_import_image(params: ImportImageInput) -> str:
    """Import a PNG, JPG, or other image file into the document.
    
    Places the image at the specified position. By default, images are linked
    (referenced from the file). Set link=False to embed the image data.
    """
    return await _place_item_impl(
        file_path=params.file_path,
        x=params.x,
        y=params.y,
        linked=params.link,
        command_type="import_image",
        tool_name="illustrator_import_image",
        error_prefix="Image file"
    )


# Combined Undo/Redo tool
class HistoryInput(ToolInputBase):
    """Input for undo/redo operations."""
    action: str = Field(default="undo", description="Action: 'undo' or 'redo'")
    count: int = Field(default=1, description="Number of times to perform action", ge=1, le=100)


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
    """
    if params.action not in ("undo", "redo"):
        return json.dumps({"ok": False, "error": "Invalid action. Use 'undo' or 'redo'"})
    
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
class PlaceFileInput(ToolInputBase):
    """Input for placing a file."""
    file_path: str = Field(..., description="Full path to file (EPS, AI, PDF, PNG, etc.)", min_length=1)
    x: float = Field(default=0, description="X position")
    y: float = Field(default=0, description="Y position")
    linked: bool = Field(default=True, description="Keep linked (True) or embed immediately (False)")
    embed_editable: bool = Field(default=False, description="Open PDF and paste as editable vectors (slower but fully editable)")


@mcp.tool(
    name="illustrator_place_file",
    annotations={"title": "Place File", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_place_file(params: PlaceFileInput) -> str:
    """Place an external file (EPS, AI, PDF, image) into the document.
    
    Workflow:
    - linked=True (drafting): File updates automatically when source changes
    - linked=False (final): File is embedded and fully editable
    - embed_editable=True: Opens PDF, copies content as editable vectors (slower)
    
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
        embed_editable=params.embed_editable
    )


# DISABLED: Tool limit reduction for Antigravity
# @mcp.tool(
#     name="illustrator_embed_placed_items",
#     annotations={"title": "Embed All Placed Items", "readOnlyHint": False, "destructiveHint": False}
# )
async def illustrator_embed_placed_items() -> str:
    """Embed all linked/placed items in the document.
    
    Use when finalizing a figure for submission.
    After embedding, all elements become editable paths and text.
    """
    return await execute_jsx_tool(
        script=templates.EMBED_PLACED_ITEMS,
        command_type="embed_placed_items",
        tool_name="illustrator_embed_placed_items",
        params={}
    )


@mcp.tool(
    name="illustrator_update_linked_items",
    annotations={"title": "Update Linked Items", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_update_linked_items() -> str:
    """Update all linked items from their source files.
    
    Use when source files (e.g., MATLAB exports) have been regenerated.
    """
    return await execute_jsx_tool(
        script=templates.UPDATE_LINKED_ITEMS,
        command_type="update_linked_items",
        tool_name="illustrator_update_linked_items",
        params={}
    )
