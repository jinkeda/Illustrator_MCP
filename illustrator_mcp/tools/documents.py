"""
Document operation tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script, format_response


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


# Tool implementations using execute_script
@mcp.tool(
    name="illustrator_create_document",
    annotations={"title": "Create Document", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_create_document(params: CreateDocumentInput) -> str:
    """Create a new Illustrator document with specified dimensions."""
    script = f"""
    (function() {{
        var preset = new DocumentPreset();
        preset.width = {params.width};
        preset.height = {params.height};
        preset.colorMode = DocumentColorSpace.{'CMYK' if params.color_mode == 'CMYK' else 'RGB'};
        {f'preset.title = "{params.name}";' if params.name else ''}
        var doc = app.documents.add(DocumentColorSpace.{'CMYK' if params.color_mode == 'CMYK' else 'RGB'}, {params.width}, {params.height});
        return JSON.stringify({{
            success: true,
            name: doc.name,
            width: doc.width,
            height: doc.height
        }});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_open_document",
    annotations={"title": "Open Document", "readOnlyHint": True, "destructiveHint": False}
)
async def illustrator_open_document(params: OpenDocumentInput) -> str:
    """Open an existing Illustrator document."""
    # Escape backslashes for JavaScript
    path = params.file_path.replace("\\", "\\\\")
    script = f"""
    (function() {{
        var file = new File("{path}");
        if (!file.exists) {{
            throw new Error("File not found: {path}");
        }}
        var doc = app.open(file);
        return JSON.stringify({{success: true, name: doc.name, path: "{path}"}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_save_document",
    annotations={"title": "Save Document", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_save_document(params: SaveDocumentInput) -> str:
    """Save the current Illustrator document."""
    if params.file_path:
        path = params.file_path.replace("\\", "\\\\")
        script = f"""
        (function() {{
            var doc = app.activeDocument;
            var file = new File("{path}");
            doc.saveAs(file);
            return JSON.stringify({{success: true, path: "{path}"}});
        }})()
        """
    else:
        script = """
        (function() {
            var doc = app.activeDocument;
            doc.save();
            return JSON.stringify({success: true, message: "Document saved"});
        })()
        """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_export_document",
    annotations={"title": "Export Document", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_export_document(params: ExportDocumentInput) -> str:
    """Export the document to PNG, JPG, SVG, or PDF."""
    path = params.file_path.replace("\\", "\\\\")
    fmt = params.format.value.upper()
    scale = params.scale * 100
    
    if params.format == ExportFormat.PNG:
        script = f"""
        (function() {{
            var doc = app.activeDocument;
            var file = new File("{path}");
            var opts = new ExportOptionsPNG24();
            opts.horizontalScale = {scale};
            opts.verticalScale = {scale};
            doc.exportFile(file, ExportType.PNG24, opts);
            return JSON.stringify({{success: true, path: "{path}", format: "PNG"}});
        }})()
        """
    elif params.format == ExportFormat.JPG:
        script = f"""
        (function() {{
            var doc = app.activeDocument;
            var file = new File("{path}");
            var opts = new ExportOptionsJPEG();
            opts.horizontalScale = {scale};
            opts.verticalScale = {scale};
            doc.exportFile(file, ExportType.JPEG, opts);
            return JSON.stringify({{success: true, path: "{path}", format: "JPG"}});
        }})()
        """
    elif params.format == ExportFormat.SVG:
        script = f"""
        (function() {{
            var doc = app.activeDocument;
            var file = new File("{path}");
            var opts = new ExportOptionsSVG();
            doc.exportFile(file, ExportType.SVG, opts);
            return JSON.stringify({{success: true, path: "{path}", format: "SVG"}});
        }})()
        """
    else:  # PDF
        script = f"""
        (function() {{
            var doc = app.activeDocument;
            var file = new File("{path}");
            var opts = new PDFSaveOptions();
            doc.saveAs(file, opts);
            return JSON.stringify({{success: true, path: "{path}", format: "PDF"}});
        }})()
        """
    
    response = await execute_script(script)
    return format_response(response)


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
    response = await execute_script(script)
    return format_response(response)


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
    response = await execute_script(script)
    return format_response(response)


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
    
    Args:
        params: Import parameters:
            - file_path: Full path to the image file
            - x: X position to place the image (default: 0)
            - y: Y position to place the image (default: 0)
            - link: Link (True) or embed (False) the image
    
    Returns:
        str: JSON with placed image information
    """
    path = params.file_path.replace("\\", "\\\\")
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var file = new File("{path}");
        if (!file.exists) {{
            throw new Error("Image file not found: {path}");
        }}
        var placed = doc.placedItems.add();
        placed.file = file;
        placed.left = {params.x};
        placed.top = {-params.y};
        {"" if params.link else "placed.embed();"}
        return JSON.stringify({{
            success: true,
            path: "{path}",
            linked: {str(params.link).lower()},
            position: {{x: {params.x}, y: {params.y}}},
            width: placed.width,
            height: placed.height
        }});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)
