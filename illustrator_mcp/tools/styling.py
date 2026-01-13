"""
Color and styling tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script, format_response


# Pydantic models
class SetFillColorInput(BaseModel):
    """Input for setting fill color."""
    model_config = ConfigDict(str_strip_whitespace=True)
    red: int = Field(..., description="Red (0-255)", ge=0, le=255)
    green: int = Field(..., description="Green (0-255)", ge=0, le=255)
    blue: int = Field(..., description="Blue (0-255)", ge=0, le=255)


class SetStrokeColorInput(BaseModel):
    """Input for setting stroke color."""
    model_config = ConfigDict(str_strip_whitespace=True)
    red: int = Field(..., description="Red (0-255)", ge=0, le=255)
    green: int = Field(..., description="Green (0-255)", ge=0, le=255)
    blue: int = Field(..., description="Blue (0-255)", ge=0, le=255)


class SetStrokeWidthInput(BaseModel):
    """Input for setting stroke width."""
    model_config = ConfigDict(str_strip_whitespace=True)
    width: float = Field(..., description="Stroke width in points", ge=0, le=1000)


# Tool implementations
@mcp.tool(
    name="illustrator_set_fill_color",
    annotations={"title": "Set Fill Color", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_set_fill_color(params: SetFillColorInput) -> str:
    """Set fill color of selected objects."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        var color = new RGBColor();
        color.red = {params.red};
        color.green = {params.green};
        color.blue = {params.blue};
        for (var i = 0; i < sel.length; i++) {{
            if (sel[i].filled !== undefined) {{
                sel[i].filled = true;
                sel[i].fillColor = color;
            }}
        }}
        return JSON.stringify({{success: true, color: {{r: {params.red}, g: {params.green}, b: {params.blue}}}}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_set_stroke_color",
    annotations={"title": "Set Stroke Color", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_set_stroke_color(params: SetStrokeColorInput) -> str:
    """Set stroke color of selected objects."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        var color = new RGBColor();
        color.red = {params.red};
        color.green = {params.green};
        color.blue = {params.blue};
        for (var i = 0; i < sel.length; i++) {{
            if (sel[i].stroked !== undefined) {{
                sel[i].stroked = true;
                sel[i].strokeColor = color;
            }}
        }}
        return JSON.stringify({{success: true, color: {{r: {params.red}, g: {params.green}, b: {params.blue}}}}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_set_stroke_width",
    annotations={"title": "Set Stroke Width", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_set_stroke_width(params: SetStrokeWidthInput) -> str:
    """Set stroke width of selected objects."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        for (var i = 0; i < sel.length; i++) {{
            if (sel[i].stroked !== undefined) {{
                sel[i].stroked = true;
                sel[i].strokeWidth = {params.width};
            }}
        }}
        return JSON.stringify({{success: true, strokeWidth: {params.width}}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_remove_fill",
    annotations={"title": "Remove Fill", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_remove_fill() -> str:
    """Remove fill from selected objects."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        for (var i = 0; i < sel.length; i++) {
            if (sel[i].filled !== undefined) {
                sel[i].filled = false;
            }
        }
        return JSON.stringify({success: true, message: "Fill removed"});
    })()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_remove_stroke",
    annotations={"title": "Remove Stroke", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_remove_stroke() -> str:
    """Remove stroke from selected objects."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        for (var i = 0; i < sel.length; i++) {
            if (sel[i].stroked !== undefined) {
                sel[i].stroked = false;
            }
        }
        return JSON.stringify({success: true, message: "Stroke removed"});
    })()
    """
    response = await execute_script(script)
    return format_response(response)
