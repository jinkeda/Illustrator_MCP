"""
Document operation tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.tools.base import execute_jsx_tool
from illustrator_mcp.utils import escape_path_for_jsx
from illustrator_mcp import templates


class ExportFormat(str, Enum):
    """Export file formats."""
    PNG = "png"
    JPG = "jpg"
    SVG = "svg"
    PDF = "pdf"


# Pydantic models
class CreateDocumentInput(BaseModel):
    """Input for creating a new document."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    width: float = Field(default=800, description="Width in points", ge=1, le=16383)
    height: float = Field(default=600, description="Height in points", ge=1, le=16383)
    name: Optional[str] = Field(default=None, description="Document name", max_length=255)
    color_mode: str = Field(default="RGB", description="RGB or CMYK")


class OpenDocumentInput(BaseModel):
    """Input for opening a document."""
    model_config = ConfigDict(str_strip_whitespace=True)
    file_path: str = Field(..., description="Full path to the file", min_length=1)


class SaveDocumentInput(BaseModel):
    """Input for saving a document."""
    model_config = ConfigDict(str_strip_whitespace=True)
    file_path: Optional[str] = Field(default=None, description="Path for Save As")


class ExportDocumentInput(BaseModel):
    """Input for exporting a document."""
    model_config = ConfigDict(str_strip_whitespace=True)
    file_path: str = Field(..., description="Export path with extension", min_length=1)
    format: ExportFormat = Field(default=ExportFormat.PNG, description="Export format")
    scale: float = Field(default=1.0, description="Scale factor", ge=0.1, le=10.0)


class CloseDocumentInput(BaseModel):
    """Input for closing a document."""
    model_config = ConfigDict(str_strip_whitespace=True)
    save_before_close: bool = Field(default=False, description="Save before closing")


# ==================== Helper Functions ====================

async def _place_item_impl(
    file_path: str,
    x: float,
    y: float,
    linked: bool,
    command_type: str,
    tool_name: str,
    error_prefix: str = "File"
) -> str:
    """Shared implementation for import_image and place_file operations."""
    path = escape_path_for_jsx(file_path)
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
        params={"file_path": file_path, "x": x, "y": y, "linked": linked}
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
    
    # Config-driven export (consolidates 4 branches into 1)
    export_configs = {
        ExportFormat.PNG: {"options": "ExportOptionsPNG24", "type": "ExportType.PNG24", "scales": True},
        ExportFormat.JPG: {"options": "ExportOptionsJPEG", "type": "ExportType.JPEG", "scales": True},
        ExportFormat.SVG: {"options": "ExportOptionsSVG", "type": "ExportType.SVG", "scales": False},
        ExportFormat.PDF: {"options": "PDFSaveOptions", "type": None, "scales": False},  # Uses saveAs
    }
    
    config = export_configs[params.format]
    fmt_name = params.format.value.upper()
    
    if config["type"]:  # Standard exportFile
        scale_opts = f"""
            opts.horizontalScale = {scale};
            opts.verticalScale = {scale};""" if config["scales"] else ""
        
        script = f"""
        (function() {{
            var doc = app.activeDocument;
            var file = new File("{path}");
            var opts = new {config["options"]}();{scale_opts}
            doc.exportFile(file, {config["type"]}, opts);
            return JSON.stringify({{success: true, path: "{path}", format: "{fmt_name}"}});
        }})()
        """
    else:  # PDF uses saveAs
        script = f"""
        (function() {{
            var doc = app.activeDocument;
            var file = new File("{path}");
            var opts = new {config["options"]}();
            doc.saveAs(file, opts);
            return JSON.stringify({{success: true, path: "{path}", format: "{fmt_name}"}});
        }})()
        """

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
    script = """
    (function() {
        if (app.documents.length === 0) {
            throw new Error("No document is open");
        }
        var doc = app.activeDocument;
        return JSON.stringify({
            name: doc.name,
            width: doc.width,
            height: doc.height,
            colorMode: doc.documentColorSpace == DocumentColorSpace.CMYK ? "CMYK" : "RGB",
            layerCount: doc.layers.length,
            saved: doc.saved
        });
    })()
    """
    return await execute_jsx_tool(
        script=script,
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
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        doc.close({save_option});
        return JSON.stringify({{success: true, message: "Document closed"}});
    }})()
    """
    return await execute_jsx_tool(
        script=script,
        command_type="close_document",
        tool_name="illustrator_close_document",
        params={"save_before_close": params.save_before_close}
    )


# Pydantic model for import
class ImportImageInput(BaseModel):
    """Input for importing an image."""
    model_config = ConfigDict(str_strip_whitespace=True)
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
class PlaceFileInput(BaseModel):
    """Input for placing a file."""
    model_config = ConfigDict(str_strip_whitespace=True)
    file_path: str = Field(..., description="Full path to file (EPS, AI, PDF, PNG, etc.)", min_length=1)
    x: float = Field(default=0, description="X position")
    y: float = Field(default=0, description="Y position")
    linked: bool = Field(default=True, description="Keep linked (True) or embed immediately (False)")


@mcp.tool(
    name="illustrator_place_file",
    annotations={"title": "Place File", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_place_file(params: PlaceFileInput) -> str:
    """Place an external file (EPS, AI, PDF, image) into the document.
    
    Workflow:
    - linked=True (drafting): File updates automatically when source changes
    - linked=False (final): File is embedded and fully editable
    
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
        error_prefix="File"
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
    script = """
    (function() {
        var doc = app.activeDocument;
        var embedded = 0;
        // Iterate backwards since embedding changes the collection
        for (var i = doc.placedItems.length - 1; i >= 0; i--) {
            try {
                doc.placedItems[i].embed();
                embedded++;
            } catch(e) {}
        }
        return JSON.stringify({success: true, embeddedCount: embedded});
    })()
    """
    return await execute_jsx_tool(
        script=script,
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
    script = """
    (function() {
        var doc = app.activeDocument;
        var updated = 0;
        for (var i = 0; i < doc.placedItems.length; i++) {
            try {
                // Relink to same file forces update
                var file = doc.placedItems[i].file;
                if (file && file.exists) {
                    doc.placedItems[i].relink(file);
                    updated++;
                }
            } catch(e) {}
        }
        return JSON.stringify({success: true, updatedCount: updated});
    })()
    """
    return await execute_jsx_tool(
        script=script,
        command_type="update_linked_items",
        tool_name="illustrator_update_linked_items",
        params={}
    )
