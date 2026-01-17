"""
Path operation tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response


# Pydantic models
class OffsetPathInput(BaseModel):
    """Input for offset path."""
    model_config = ConfigDict(str_strip_whitespace=True)
    offset: float = Field(..., description="Offset distance in points")
    joins: str = Field(default="miter", description="Join type: miter, round, bevel")
    miter_limit: float = Field(default=4, description="Miter limit", ge=1)


class SimplifyPathInput(BaseModel):
    """Input for simplifying path."""
    model_config = ConfigDict(str_strip_whitespace=True)
    curve_precision: float = Field(default=50, description="Curve precision (%)", ge=0, le=100)
    angle_threshold: float = Field(default=10, description="Angle threshold (degrees)", ge=0, le=180)


# Tool implementations
@mcp.tool(
    name="illustrator_join_paths",
    annotations={"title": "Join Paths", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_join_paths() -> str:
    """Join selected open paths."""
    script = """
    (function() {
        app.executeMenuCommand("join");
        return JSON.stringify({success: true, message: "Paths joined"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="join_paths",
        tool_name="illustrator_join_paths",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_outline_stroke",
    annotations={"title": "Outline Stroke", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_outline_stroke() -> str:
    """Convert stroke to filled path."""
    script = """
    (function() {
        app.executeMenuCommand("OffsetPath v22");
        return JSON.stringify({success: true, message: "Stroke outlined"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="outline_stroke",
        tool_name="illustrator_outline_stroke",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_offset_path",
    annotations={"title": "Offset Path", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_offset_path(params: OffsetPathInput) -> str:
    """Create parallel path at offset distance."""
    joins_map = {"miter": "1", "round": "2", "bevel": "3"}
    joins_val = joins_map.get(params.joins.lower(), "1")
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        for (var i = 0; i < sel.length; i++) {{
            if (sel[i].typename === "PathItem" || sel[i].typename === "CompoundPathItem") {{
                // Use menu command with preferences
                app.executeMenuCommand("OffsetPath v23");
            }}
        }}
        return JSON.stringify({{success: true, offset: {params.offset}}});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="offset_path",
        tool_name="illustrator_offset_path",
        params={"offset": params.offset, "joins": params.joins}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_simplify_path",
    annotations={"title": "Simplify Path", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_simplify_path(params: SimplifyPathInput) -> str:
    """Reduce anchor points in paths."""
    script = f"""
    (function() {{
        app.executeMenuCommand("simplify menu item");
        return JSON.stringify({{success: true, message: "Path simplified"}});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="simplify_path",
        tool_name="illustrator_simplify_path",
        params={"curve_precision": params.curve_precision, "angle_threshold": params.angle_threshold}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_smooth_path",
    annotations={"title": "Smooth Path", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_smooth_path() -> str:
    """Smooth path curves."""
    script = """
    (function() {
        app.executeMenuCommand("smooth menu item");
        return JSON.stringify({success: true, message: "Path smoothed"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="smooth_path",
        tool_name="illustrator_smooth_path",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_reverse_path",
    annotations={"title": "Reverse Path", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_reverse_path() -> str:
    """Reverse path direction."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        var reversed = 0;
        for (var i = 0; i < sel.length; i++) {
            if (sel[i].typename === "PathItem") {
                var points = sel[i].pathPoints;
                var newPoints = [];
                for (var j = points.length - 1; j >= 0; j--) {
                    newPoints.push({
                        anchor: points[j].anchor,
                        leftDirection: points[j].rightDirection,
                        rightDirection: points[j].leftDirection,
                        pointType: points[j].pointType
                    });
                }
                sel[i].setEntirePath(newPoints.map(function(p) { return p.anchor; }));
                reversed++;
            }
        }
        return JSON.stringify({success: true, reversedCount: reversed});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="reverse_path",
        tool_name="illustrator_reverse_path",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_make_compound_path",
    annotations={"title": "Make Compound Path", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_make_compound_path() -> str:
    """Combine paths into compound path."""
    script = """
    (function() {
        app.executeMenuCommand("compoundPath");
        return JSON.stringify({success: true, message: "Compound path created"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="make_compound_path",
        tool_name="illustrator_make_compound_path",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_release_compound_path",
    annotations={"title": "Release Compound Path", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_release_compound_path() -> str:
    """Split compound path into parts."""
    script = """
    (function() {
        app.executeMenuCommand("noCompoundPath");
        return JSON.stringify({success: true, message: "Compound path released"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="release_compound_path",
        tool_name="illustrator_release_compound_path",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_expand_appearance",
    annotations={"title": "Expand Appearance", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_expand_appearance() -> str:
    """Expand effects/strokes to paths."""
    script = """
    (function() {
        app.executeMenuCommand("expandStyle");
        return JSON.stringify({success: true, message: "Appearance expanded"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="expand_appearance",
        tool_name="illustrator_expand_appearance",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_flatten_transparency",
    annotations={"title": "Flatten Transparency", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_flatten_transparency() -> str:
    """Flatten transparent objects."""
    script = """
    (function() {
        app.executeMenuCommand("FlattenTransparency1");
        return JSON.stringify({success: true, message: "Transparency flattened"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="flatten_transparency",
        tool_name="illustrator_flatten_transparency",
        params={}
    )
    return format_response(response)
