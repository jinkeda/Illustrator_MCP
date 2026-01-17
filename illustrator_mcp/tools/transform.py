"""
Advanced transform tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response


# Pydantic models
class ReflectInput(BaseModel):
    """Input for reflecting selection."""
    model_config = ConfigDict(str_strip_whitespace=True)
    axis: str = Field(..., description="Axis: 'horizontal' or 'vertical'")
    copy: bool = Field(default=False, description="Create a reflected copy")


class ShearInput(BaseModel):
    """Input for shearing selection."""
    model_config = ConfigDict(str_strip_whitespace=True)
    angle: float = Field(..., description="Shear angle (-359 to 359)", ge=-359, le=359)
    axis: str = Field(default="horizontal", description="Axis: 'horizontal' or 'vertical'")


class TransformEachInput(BaseModel):
    """Input for transforming each object."""
    model_config = ConfigDict(str_strip_whitespace=True)
    scale_x: float = Field(default=100, description="Horizontal scale %", gt=0)
    scale_y: float = Field(default=100, description="Vertical scale %", gt=0)
    rotate: float = Field(default=0, description="Rotation angle (degrees)")
    move_x: float = Field(default=0, description="Horizontal move")
    move_y: float = Field(default=0, description="Vertical move")


# Tool implementations
@mcp.tool(
    name="illustrator_reflect_selection",
    annotations={"title": "Reflect Selection", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_reflect_selection(params: ReflectInput) -> str:
    """Mirror objects horizontally or vertically."""
    if params.axis.lower() == "horizontal":
        angle = 0
    else:
        angle = 90
    
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        
        var matrix = app.getRotationMatrix(0);
        matrix = app.concatenateMatrix(matrix, app.getScaleMatrix({'-1' if params.axis.lower() == 'horizontal' else '1'}, {'1' if params.axis.lower() == 'horizontal' else '-1'}));
        
        for (var i = 0; i < sel.length; i++) {{
            var item = {'sel[i].duplicate()' if params.copy else 'sel[i]'};
            var bounds = item.geometricBounds;
            var cx = (bounds[0] + bounds[2]) / 2;
            var cy = (bounds[1] + bounds[3]) / 2;
            item.transform(matrix, true, true, true, true, Transformation.CENTER);
        }}
        
        return JSON.stringify({{
            success: true,
            axis: "{params.axis}",
            copied: {str(params.copy).lower()}
        }});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="reflect_selection",
        tool_name="illustrator_reflect_selection",
        params={"axis": params.axis, "copy": params.copy}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_shear_selection",
    annotations={"title": "Shear Selection", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_shear_selection(params: ShearInput) -> str:
    """Skew/shear selected objects."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        
        for (var i = 0; i < sel.length; i++) {{
            sel[i].shear({params.angle}, undefined, undefined, undefined, Transformation.CENTER);
        }}
        
        return JSON.stringify({{success: true, angle: {params.angle}, axis: "{params.axis}"}});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="shear_selection",
        tool_name="illustrator_shear_selection",
        params={"angle": params.angle, "axis": params.axis}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_transform_each",
    annotations={"title": "Transform Each", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_transform_each(params: TransformEachInput) -> str:
    """Transform multiple objects individually."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        
        for (var i = 0; i < sel.length; i++) {{
            sel[i].resize({params.scale_x}, {params.scale_y}, true, true, true, true, Transformation.CENTER);
            sel[i].rotate({params.rotate}, true, true, true, true, Transformation.CENTER);
            sel[i].translate({params.move_x}, {-params.move_y});
        }}
        
        return JSON.stringify({{
            success: true,
            transformed: sel.length,
            scale: {{x: {params.scale_x}, y: {params.scale_y}}},
            rotation: {params.rotate},
            move: {{x: {params.move_x}, y: {params.move_y}}}
        }});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="transform_each",
        tool_name="illustrator_transform_each",
        params={"scale_x": params.scale_x, "scale_y": params.scale_y, "rotate": params.rotate, "move_x": params.move_x, "move_y": params.move_y}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_reset_bounding_box",
    annotations={"title": "Reset Bounding Box", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_reset_bounding_box() -> str:
    """Reset the bounding box rotation."""
    script = """
    (function() {
        app.executeMenuCommand("Redefine Bounding Box");
        return JSON.stringify({success: true, message: "Bounding box reset"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="reset_bounding_box",
        tool_name="illustrator_reset_bounding_box",
        params={}
    )
    return format_response(response)
