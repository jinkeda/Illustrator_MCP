"""
Text operation tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script, format_response


# Pydantic models
class AddTextInput(BaseModel):
    """Input for adding text."""
    model_config = ConfigDict(str_strip_whitespace=True)
    content: str = Field(..., description="Text content", min_length=1)
    x: float = Field(..., description="X position")
    y: float = Field(..., description="Y position")
    font_family: Optional[str] = Field(default=None, description="Font family name")
    font_size: float = Field(default=12, description="Font size in points", gt=0, le=1296)


class SetTextFontInput(BaseModel):
    """Input for setting text font."""
    model_config = ConfigDict(str_strip_whitespace=True)
    font_family: Optional[str] = Field(default=None, description="Font family")
    font_size: Optional[float] = Field(default=None, description="Font size", gt=0, le=1296)
    font_style: Optional[str] = Field(default=None, description="Font style (Bold, Italic, etc.)")


class SetTextColorInput(BaseModel):
    """Input for setting text color."""
    model_config = ConfigDict(str_strip_whitespace=True)
    red: int = Field(..., description="Red (0-255)", ge=0, le=255)
    green: int = Field(..., description="Green (0-255)", ge=0, le=255)
    blue: int = Field(..., description="Blue (0-255)", ge=0, le=255)


# Tool implementations
@mcp.tool(
    name="illustrator_add_text",
    annotations={"title": "Add Text", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_add_text(params: AddTextInput) -> str:
    """Add a text frame with content."""
    content_escaped = params.content.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    font_code = ""
    if params.font_family:
        font_code = f"""
        try {{
            textRange.characterAttributes.textFont = app.textFonts.getByName("{params.font_family}");
        }} catch(e) {{}}
        """
    
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var textFrame = doc.textFrames.add();
        textFrame.contents = "{content_escaped}";
        textFrame.left = {params.x};
        textFrame.top = {-params.y};
        var textRange = textFrame.textRange;
        textRange.characterAttributes.size = {params.font_size};
        {font_code}
        return JSON.stringify({{
            success: true,
            content: "{content_escaped}",
            position: {{x: {params.x}, y: {params.y}}}
        }});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_set_text_font",
    annotations={"title": "Set Text Font", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_set_text_font(params: SetTextFontInput) -> str:
    """Change font properties of selected text."""
    size_code = f"textRange.characterAttributes.size = {params.font_size};" if params.font_size else ""
    font_code = ""
    if params.font_family:
        font_name = f"{params.font_family}-{params.font_style}" if params.font_style else params.font_family
        font_code = f"""
        try {{
            textRange.characterAttributes.textFont = app.textFonts.getByName("{font_name}");
        }} catch(e) {{
            try {{
                textRange.characterAttributes.textFont = app.textFonts.getByName("{params.font_family}");
            }} catch(e2) {{}}
        }}
        """
    
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        for (var i = 0; i < sel.length; i++) {{
            if (sel[i].typename === "TextFrame") {{
                var textRange = sel[i].textRange;
                {size_code}
                {font_code}
            }}
        }}
        return JSON.stringify({{success: true, message: "Font updated"}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_set_text_color",
    annotations={"title": "Set Text Color", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_set_text_color(params: SetTextColorInput) -> str:
    """Change color of selected text."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        var color = new RGBColor();
        color.red = {params.red};
        color.green = {params.green};
        color.blue = {params.blue};
        for (var i = 0; i < sel.length; i++) {{
            if (sel[i].typename === "TextFrame") {{
                sel[i].textRange.characterAttributes.fillColor = color;
            }}
        }}
        return JSON.stringify({{success: true, color: {{r: {params.red}, g: {params.green}, b: {params.blue}}}}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_get_text_content",
    annotations={"title": "Get Text Content", "readOnlyHint": True, "destructiveHint": False}
)
async def illustrator_get_text_content() -> str:
    """Get text content from selected text frame."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        var item = sel[0];
        if (item.typename !== "TextFrame") throw new Error("Selection is not a text frame");
        return JSON.stringify({
            content: item.contents,
            fontSize: item.textRange.characterAttributes.size,
            fontFamily: item.textRange.characterAttributes.textFont ? item.textRange.characterAttributes.textFont.name : "Unknown"
        });
    })()
    """
    response = await execute_script(script)
    return format_response(response)
