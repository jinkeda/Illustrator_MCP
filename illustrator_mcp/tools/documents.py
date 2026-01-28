"""
Document operation tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from typing import Optional
from enum import Enum

from pydantic import Field

from illustrator_mcp.shared import mcp
from illustrator_mcp.tools.base import execute_jsx_tool, ToolInputBase
from illustrator_mcp.utils import escape_path_for_jsx
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
    file_path: str = Field(..., description="Export path with extension", min_length=1)
    format: ExportFormat = Field(default=ExportFormat.PNG, description="Export format")
    scale: float = Field(default=1.0, description="Scale factor", ge=0.1, le=10.0)


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
async def illustrator_export_document(params: ExportDocumentInput) -> str:
    """Export the document to PNG, JPG, SVG, or PDF."""
    path = escape_path_for_jsx(params.file_path)
    scale = params.scale * 100
    fmt_name = params.format.value.upper()
    
    # Config-driven export
    export_configs = {
        ExportFormat.PNG: {"options": "ExportOptionsPNG24", "type": "ExportType.PNG24", "scales": True},
        ExportFormat.JPG: {"options": "ExportOptionsJPEG", "type": "ExportType.JPEG", "scales": True},
        ExportFormat.SVG: {"options": "ExportOptionsSVG", "type": "ExportType.SVG", "scales": False},
        ExportFormat.PDF: {"options": "PDFSaveOptions", "type": None, "scales": False},
    }
    
    config = export_configs[params.format]
    
    if config["type"]:  # Standard exportFile (PNG, JPG, SVG)
        scale_opts = f"""
            opts.horizontalScale = {scale};
            opts.verticalScale = {scale};""" if config["scales"] else ""
        script = templates.EXPORT_FILE.substitute(
            path=path,
            options_class=config["options"],
            scale_opts=scale_opts,
            export_type=config["type"],
            format_name=fmt_name
        )
    else:  # PDF uses saveAs
        script = templates.EXPORT_PDF.substitute(path=path)

    return await execute_jsx_tool(
        script=script,
        command_type="export_document",
        tool_name="illustrator_export_document",
        params={"file_path": params.file_path, "format": params.format.value, "scale": params.scale}
    )


@mcp.tool(
    name="illustrator_get_document_info",
    annotations={"title": "Get Document Info", "readOnlyHint": True, "destructiveHint": False}
)
async def illustrator_get_document_info() -> str:
    """Get information about the active document."""
    return await execute_jsx_tool(
        script=templates.GET_DOCUMENT_INFO,
        command_type="get_document_info",
        tool_name="illustrator_get_document_info",
        params={}
    )


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


# Undo/Redo tools
@mcp.tool(
    name="illustrator_undo",
    annotations={"title": "Undo", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_undo() -> str:
    """Undo the last action in Illustrator.
    
    Use this to revert mistakes or unwanted changes.
    Multiple calls will undo multiple actions.
    """
    return await execute_jsx_tool(
        script=templates.UNDO,
        command_type="undo",
        tool_name="illustrator_undo",
        params={}
    )


@mcp.tool(
    name="illustrator_redo",
    annotations={"title": "Redo", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_redo() -> str:
    """Redo the last undone action.
    
    Use this to restore an action after undo.
    """
    return await execute_jsx_tool(
        script=templates.REDO,
        command_type="redo",
        tool_name="illustrator_redo",
        params={}
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
