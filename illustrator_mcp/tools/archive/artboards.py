"""
Artboard management tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response


# Pydantic models
class CreateArtboardInput(BaseModel):
    """Input for creating an artboard."""
    model_config = ConfigDict(str_strip_whitespace=True)
    x: float = Field(default=0, description="X position")
    y: float = Field(default=0, description="Y position")
    width: float = Field(..., description="Width in points", gt=0)
    height: float = Field(..., description="Height in points", gt=0)
    name: Optional[str] = Field(default=None, description="Artboard name")


class DeleteArtboardInput(BaseModel):
    """Input for deleting an artboard."""
    model_config = ConfigDict(str_strip_whitespace=True)
    index: int = Field(..., description="Artboard index (0-based)", ge=0)


class SetActiveArtboardInput(BaseModel):
    """Input for setting active artboard."""
    model_config = ConfigDict(str_strip_whitespace=True)
    index: int = Field(..., description="Artboard index (0-based)", ge=0)


class ResizeArtboardInput(BaseModel):
    """Input for resizing an artboard."""
    model_config = ConfigDict(str_strip_whitespace=True)
    index: int = Field(..., description="Artboard index (0-based)", ge=0)
    width: float = Field(..., description="New width", gt=0)
    height: float = Field(..., description="New height", gt=0)


# Tool implementations
@mcp.tool(
    name="illustrator_list_artboards",
    annotations={"title": "List Artboards", "readOnlyHint": True, "destructiveHint": False}
)
async def illustrator_list_artboards() -> str:
    """List all artboards with their properties."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var artboards = [];
        for (var i = 0; i < doc.artboards.length; i++) {
            var ab = doc.artboards[i];
            var rect = ab.artboardRect;
            artboards.push({
                index: i,
                name: ab.name,
                x: rect[0],
                y: -rect[1],
                width: rect[2] - rect[0],
                height: rect[1] - rect[3],
                isActive: i === doc.artboards.getActiveArtboardIndex()
            });
        }
        return JSON.stringify({artboards: artboards, count: artboards.length});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="list_artboards",
        tool_name="illustrator_list_artboards",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_create_artboard",
    annotations={"title": "Create Artboard", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_create_artboard(params: CreateArtboardInput) -> str:
    """Create a new artboard."""
    name_code = f'ab.name = "{params.name}";' if params.name else ""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var rect = [{params.x}, {-params.y}, {params.x + params.width}, {-params.y - params.height}];
        var ab = doc.artboards.add(rect);
        {name_code}
        return JSON.stringify({{
            success: true,
            index: doc.artboards.length - 1,
            name: ab.name,
            width: {params.width},
            height: {params.height}
        }});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="create_artboard",
        tool_name="illustrator_create_artboard",
        params={"x": params.x, "y": params.y, "width": params.width, "height": params.height, "name": params.name}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_delete_artboard",
    annotations={"title": "Delete Artboard", "readOnlyHint": False, "destructiveHint": True}
)
async def illustrator_delete_artboard(params: DeleteArtboardInput) -> str:
    """Delete an artboard by index."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        if ({params.index} >= doc.artboards.length) {{
            throw new Error("Artboard index out of range");
        }}
        doc.artboards.remove({params.index});
        return JSON.stringify({{success: true, message: "Artboard deleted"}});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="delete_artboard",
        tool_name="illustrator_delete_artboard",
        params={"index": params.index}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_set_active_artboard",
    annotations={"title": "Set Active Artboard", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_set_active_artboard(params: SetActiveArtboardInput) -> str:
    """Set the active artboard."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        if ({params.index} >= doc.artboards.length) {{
            throw new Error("Artboard index out of range");
        }}
        doc.artboards.setActiveArtboardIndex({params.index});
        return JSON.stringify({{success: true, activeArtboard: {params.index}}});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="set_active_artboard",
        tool_name="illustrator_set_active_artboard",
        params={"index": params.index}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_resize_artboard",
    annotations={"title": "Resize Artboard", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_resize_artboard(params: ResizeArtboardInput) -> str:
    """Resize an artboard."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        if ({params.index} >= doc.artboards.length) {{
            throw new Error("Artboard index out of range");
        }}
        var ab = doc.artboards[{params.index}];
        var rect = ab.artboardRect;
        var x = rect[0];
        var y = rect[1];
        ab.artboardRect = [x, y, x + {params.width}, y - {params.height}];
        return JSON.stringify({{success: true, width: {params.width}, height: {params.height}}});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="resize_artboard",
        tool_name="illustrator_resize_artboard",
        params={"index": params.index, "width": params.width, "height": params.height}
    )
    return format_response(response)
