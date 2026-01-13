"""
Shape drawing tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script, format_response


# Pydantic models
class DrawRectangleInput(BaseModel):
    """Input for drawing a rectangle."""
    model_config = ConfigDict(str_strip_whitespace=True)
    x: float = Field(..., description="X position of top-left corner")
    y: float = Field(..., description="Y position of top-left corner")
    width: float = Field(..., description="Width in points", gt=0)
    height: float = Field(..., description="Height in points", gt=0)
    corner_radius: float = Field(default=0, description="Corner radius for rounded rectangles", ge=0)


class DrawEllipseInput(BaseModel):
    """Input for drawing an ellipse."""
    model_config = ConfigDict(str_strip_whitespace=True)
    x: float = Field(..., description="X position of center")
    y: float = Field(..., description="Y position of center")
    width: float = Field(..., description="Width (diameter for circles)", gt=0)
    height: Optional[float] = Field(default=None, description="Height (omit for circles)", gt=0)


class DrawPolygonInput(BaseModel):
    """Input for drawing a polygon."""
    model_config = ConfigDict(str_strip_whitespace=True)
    x: float = Field(..., description="X position of center")
    y: float = Field(..., description="Y position of center")
    radius: float = Field(..., description="Radius to vertices", gt=0)
    sides: int = Field(default=6, description="Number of sides", ge=3, le=100)


class DrawLineInput(BaseModel):
    """Input for drawing a line."""
    model_config = ConfigDict(str_strip_whitespace=True)
    x1: float = Field(..., description="X of start point")
    y1: float = Field(..., description="Y of start point")
    x2: float = Field(..., description="X of end point")
    y2: float = Field(..., description="Y of end point")


class PathPoint(BaseModel):
    """A point in a path."""
    x: float = Field(..., description="X coordinate")
    y: float = Field(..., description="Y coordinate")


class DrawPathInput(BaseModel):
    """Input for drawing a path."""
    model_config = ConfigDict(str_strip_whitespace=True)
    points: List[PathPoint] = Field(..., description="List of points", min_length=2)
    closed: bool = Field(default=False, description="Close the path")


class DrawStarInput(BaseModel):
    """Input for drawing a star."""
    model_config = ConfigDict(str_strip_whitespace=True)
    x: float = Field(..., description="X position of center")
    y: float = Field(..., description="Y position of center")
    outer_radius: float = Field(..., description="Outer radius (tips)", gt=0)
    inner_radius: float = Field(..., description="Inner radius (valleys)", gt=0)
    points: int = Field(default=5, description="Number of points", ge=3, le=100)


# Tool implementations
@mcp.tool(
    name="illustrator_draw_rectangle",
    annotations={"title": "Draw Rectangle", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_draw_rectangle(params: DrawRectangleInput) -> str:
    """Draw a rectangle at the specified position."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var rect = doc.pathItems.rectangle({-params.y}, {params.x}, {params.width}, {params.height});
        return JSON.stringify({{
            success: true,
            type: "rectangle",
            bounds: {{x: {params.x}, y: {params.y}, width: {params.width}, height: {params.height}}}
        }});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_draw_ellipse",
    annotations={"title": "Draw Ellipse", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_draw_ellipse(params: DrawEllipseInput) -> str:
    """Draw an ellipse or circle at the specified center."""
    height = params.height if params.height else params.width
    # Illustrator ellipse takes top, left, width, height
    top = -params.y + height/2
    left = params.x - params.width/2
    
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var ellipse = doc.pathItems.ellipse({top}, {left}, {params.width}, {height});
        return JSON.stringify({{
            success: true,
            type: "ellipse",
            center: {{x: {params.x}, y: {params.y}}},
            size: {{width: {params.width}, height: {height}}}
        }});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_draw_polygon",
    annotations={"title": "Draw Polygon", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_draw_polygon(params: DrawPolygonInput) -> str:
    """Draw a regular polygon (triangle, hexagon, etc.)."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var polygon = doc.pathItems.polygon({params.x}, {-params.y}, {params.radius}, {params.sides});
        return JSON.stringify({{
            success: true,
            type: "polygon",
            center: {{x: {params.x}, y: {params.y}}},
            sides: {params.sides}
        }});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_draw_line",
    annotations={"title": "Draw Line", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_draw_line(params: DrawLineInput) -> str:
    """Draw a line between two points."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var line = doc.pathItems.add();
        line.setEntirePath([[{params.x1}, {-params.y1}], [{params.x2}, {-params.y2}]]);
        line.filled = false;
        line.stroked = true;
        return JSON.stringify({{
            success: true,
            type: "line",
            from: {{x: {params.x1}, y: {params.y1}}},
            to: {{x: {params.x2}, y: {params.y2}}}
        }});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_draw_path",
    annotations={"title": "Draw Path", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_draw_path(params: DrawPathInput) -> str:
    """Draw a custom path from points."""
    points_js = ", ".join([f"[{p.x}, {-p.y}]" for p in params.points])
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var path = doc.pathItems.add();
        path.setEntirePath([{points_js}]);
        path.closed = {'true' if params.closed else 'false'};
        return JSON.stringify({{
            success: true,
            type: "path",
            pointCount: {len(params.points)},
            closed: {'true' if params.closed else 'false'}
        }});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_draw_star",
    annotations={"title": "Draw Star", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_draw_star(params: DrawStarInput) -> str:
    """Draw a star shape."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var star = doc.pathItems.star({params.x}, {-params.y}, {params.outer_radius}, {params.inner_radius}, {params.points});
        return JSON.stringify({{
            success: true,
            type: "star",
            center: {{x: {params.x}, y: {params.y}}},
            points: {params.points}
        }});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)
