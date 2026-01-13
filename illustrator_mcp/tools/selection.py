"""
Selection and transformation tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script, format_response


# Pydantic models
class MoveSelectionInput(BaseModel):
    """Input for moving selection."""
    model_config = ConfigDict(str_strip_whitespace=True)
    delta_x: float = Field(default=0, description="Horizontal displacement (+ = right)")
    delta_y: float = Field(default=0, description="Vertical displacement (+ = up)")


class ScaleSelectionInput(BaseModel):
    """Input for scaling selection."""
    model_config = ConfigDict(str_strip_whitespace=True)
    scale_x: float = Field(default=100, description="Horizontal scale %", gt=0, le=1000)
    scale_y: float = Field(default=100, description="Vertical scale %", gt=0, le=1000)


class RotateSelectionInput(BaseModel):
    """Input for rotating selection."""
    model_config = ConfigDict(str_strip_whitespace=True)
    angle: float = Field(..., description="Rotation angle in degrees", ge=-360, le=360)


# Tool implementations
@mcp.tool(
    name="illustrator_select_all",
    annotations={"title": "Select All", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_select_all() -> str:
    """Select all objects in the document."""
    script = """
    (function() {
        var doc = app.activeDocument;
        doc.selectObjectsOnActiveArtboard();
        return JSON.stringify({success: true, count: doc.selection.length});
    })()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_deselect_all",
    annotations={"title": "Deselect All", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_deselect_all() -> str:
    """Clear the selection."""
    script = """
    (function() {
        var doc = app.activeDocument;
        doc.selection = null;
        return JSON.stringify({success: true, message: "Selection cleared"});
    })()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_get_selection",
    annotations={"title": "Get Selection Info", "readOnlyHint": True, "destructiveHint": False}
)
async def illustrator_get_selection() -> str:
    """Get information about selected objects."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        var items = [];
        for (var i = 0; i < sel.length; i++) {
            var item = sel[i];
            items.push({
                type: item.typename,
                name: item.name || "",
                bounds: {
                    left: item.left,
                    top: item.top,
                    width: item.width,
                    height: item.height
                }
            });
        }
        return JSON.stringify({count: sel.length, items: items});
    })()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_delete_selection",
    annotations={"title": "Delete Selection", "readOnlyHint": False, "destructiveHint": True}
)
async def illustrator_delete_selection() -> str:
    """Delete all selected objects."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        var count = sel.length;
        for (var i = sel.length - 1; i >= 0; i--) {
            sel[i].remove();
        }
        return JSON.stringify({success: true, deletedCount: count});
    })()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_move_selection",
    annotations={"title": "Move Selection", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_move_selection(params: MoveSelectionInput) -> str:
    """Move selected objects by specified amount."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        for (var i = 0; i < sel.length; i++) {{
            sel[i].translate({params.delta_x}, {-params.delta_y});
        }}
        return JSON.stringify({{success: true, moved: {{deltaX: {params.delta_x}, deltaY: {params.delta_y}}}}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_scale_selection",
    annotations={"title": "Scale Selection", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_scale_selection(params: ScaleSelectionInput) -> str:
    """Scale selected objects."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        for (var i = 0; i < sel.length; i++) {{
            sel[i].resize({params.scale_x}, {params.scale_y});
        }}
        return JSON.stringify({{success: true, scaled: {{scaleX: {params.scale_x}, scaleY: {params.scale_y}}}}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_rotate_selection",
    annotations={"title": "Rotate Selection", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_rotate_selection(params: RotateSelectionInput) -> str:
    """Rotate selected objects."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        for (var i = 0; i < sel.length; i++) {{
            sel[i].rotate({params.angle});
        }}
        return JSON.stringify({{success: true, rotated: {params.angle}}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)
