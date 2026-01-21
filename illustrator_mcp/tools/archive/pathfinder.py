"""
Pathfinder operation tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response


@mcp.tool(
    name="illustrator_pathfinder_unite",
    annotations={"title": "Pathfinder: Unite", "readOnlyHint": False, "destructiveHint": True}
)
async def illustrator_pathfinder_unite() -> str:
    """Merge/combine selected shapes into one."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length < 2) throw new Error("Select at least 2 objects");
        app.executeMenuCommand("Live Pathfinder Add");
        app.executeMenuCommand("expandStyle");
        return JSON.stringify({success: true, message: "Shapes united"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="pathfinder_unite",
        tool_name="illustrator_pathfinder_unite",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_pathfinder_minus_front",
    annotations={"title": "Pathfinder: Minus Front", "readOnlyHint": False, "destructiveHint": True}
)
async def illustrator_pathfinder_minus_front() -> str:
    """Subtract front shape from back shape."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length < 2) throw new Error("Select at least 2 objects");
        app.executeMenuCommand("Live Pathfinder Subtract");
        app.executeMenuCommand("expandStyle");
        return JSON.stringify({success: true, message: "Front subtracted from back"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="pathfinder_minus_front",
        tool_name="illustrator_pathfinder_minus_front",
        params={}
    )
    return format_response(response)


# DISABLED: Tool limit reduction for Antigravity
# @mcp.tool(
#     name="illustrator_pathfinder_minus_back",
#     annotations={"title": "Pathfinder: Minus Back", "readOnlyHint": False, "destructiveHint": True}
# )
async def illustrator_pathfinder_minus_back() -> str:
    """Subtract back shape from front shape."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length < 2) throw new Error("Select at least 2 objects");
        app.executeMenuCommand("Live Pathfinder Back Minus Front");
        app.executeMenuCommand("expandStyle");
        return JSON.stringify({success: true, message: "Back subtracted from front"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="pathfinder_minus_back",
        tool_name="illustrator_pathfinder_minus_back",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_pathfinder_intersect",
    annotations={"title": "Pathfinder: Intersect", "readOnlyHint": False, "destructiveHint": True}
)
async def illustrator_pathfinder_intersect() -> str:
    """Keep only overlapping areas."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length < 2) throw new Error("Select at least 2 objects");
        app.executeMenuCommand("Live Pathfinder Intersect");
        app.executeMenuCommand("expandStyle");
        return JSON.stringify({success: true, message: "Shapes intersected"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="pathfinder_intersect",
        tool_name="illustrator_pathfinder_intersect",
        params={}
    )
    return format_response(response)


# DISABLED: Tool limit reduction for Antigravity
# @mcp.tool(
#     name="illustrator_pathfinder_exclude",
#     annotations={"title": "Pathfinder: Exclude", "readOnlyHint": False, "destructiveHint": True}
# )
async def illustrator_pathfinder_exclude() -> str:
    """Remove overlapping areas."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length < 2) throw new Error("Select at least 2 objects");
        app.executeMenuCommand("Live Pathfinder Exclude");
        app.executeMenuCommand("expandStyle");
        return JSON.stringify({success: true, message: "Overlap excluded"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="pathfinder_exclude",
        tool_name="illustrator_pathfinder_exclude",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_pathfinder_divide",
    annotations={"title": "Pathfinder: Divide", "readOnlyHint": False, "destructiveHint": True}
)
async def illustrator_pathfinder_divide() -> str:
    """Divide shapes at intersections."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length < 2) throw new Error("Select at least 2 objects");
        app.executeMenuCommand("Live Pathfinder Divide");
        app.executeMenuCommand("expandStyle");
        return JSON.stringify({success: true, message: "Shapes divided"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="pathfinder_divide",
        tool_name="illustrator_pathfinder_divide",
        params={}
    )
    return format_response(response)


# DISABLED: Tool limit reduction for Antigravity
# @mcp.tool(
#     name="illustrator_pathfinder_trim",
#     annotations={"title": "Pathfinder: Trim", "readOnlyHint": False, "destructiveHint": True}
# )
async def illustrator_pathfinder_trim() -> str:
    """Trim overlapping areas."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length < 2) throw new Error("Select at least 2 objects");
        app.executeMenuCommand("Live Pathfinder Trim");
        app.executeMenuCommand("expandStyle");
        return JSON.stringify({success: true, message: "Shapes trimmed"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="pathfinder_trim",
        tool_name="illustrator_pathfinder_trim",
        params={}
    )
    return format_response(response)


# DISABLED: Tool limit reduction for Antigravity
# @mcp.tool(
#     name="illustrator_pathfinder_merge",
#     annotations={"title": "Pathfinder: Merge", "readOnlyHint": False, "destructiveHint": True}
# )
async def illustrator_pathfinder_merge() -> str:
    """Merge adjacent same-color shapes."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length < 2) throw new Error("Select at least 2 objects");
        app.executeMenuCommand("Live Pathfinder Merge");
        app.executeMenuCommand("expandStyle");
        return JSON.stringify({success: true, message: "Shapes merged"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="pathfinder_merge",
        tool_name="illustrator_pathfinder_merge",
        params={}
    )
    return format_response(response)
