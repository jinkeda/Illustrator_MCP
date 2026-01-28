"""
Alignment, grouping, and arrangement tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from enum import Enum
from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response


class AlignmentType(str, Enum):
    """Alignment types."""
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    TOP = "top"
    MIDDLE = "middle"
    BOTTOM = "bottom"


class DistributeType(str, Enum):
    """Distribution types."""
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


# Pydantic models
class AlignObjectsInput(BaseModel):
    """Input for aligning objects."""
    model_config = ConfigDict(str_strip_whitespace=True)
    alignment: AlignmentType = Field(..., description="Alignment type")
    to_artboard: bool = Field(default=False, description="Align to artboard")


class DistributeObjectsInput(BaseModel):
    """Input for distributing objects."""
    model_config = ConfigDict(str_strip_whitespace=True)
    distribution: DistributeType = Field(..., description="Distribution direction")


# Tool implementations
@mcp.tool(
    name="illustrator_align_objects",
    annotations={"title": "Align Objects", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_align_objects(params: AlignObjectsInput) -> str:
    """Align selected objects."""
    # Map alignment to Illustrator constants
    align_map = {
        "left": "Justification.LEFT",
        "center": "Justification.CENTER", 
        "right": "Justification.RIGHT",
        "top": "Justification.TOP",
        "middle": "Justification.CENTER",
        "bottom": "Justification.BOTTOM"
    }
    
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (sel.length < 2 && !{str(params.to_artboard).lower()}) {{
            throw new Error("Select at least 2 objects to align");
        }}
        // Use menu command for alignment
        app.executeMenuCommand("align{params.alignment.value.capitalize()}");
        return JSON.stringify({{success: true, alignment: "{params.alignment.value}"}});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="align_objects",
        tool_name="illustrator_align_objects",
        params={"alignment": params.alignment.value, "to_artboard": params.to_artboard}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_distribute_objects",
    annotations={"title": "Distribute Objects", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_distribute_objects(params: DistributeObjectsInput) -> str:
    """Distribute selected objects evenly."""
    cmd = "distributeHorizontalCenter" if params.distribution == DistributeType.HORIZONTAL else "distributeVerticalCenter"
    
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (sel.length < 3) {{
            throw new Error("Select at least 3 objects to distribute");
        }}
        app.executeMenuCommand("{cmd}");
        return JSON.stringify({{success: true, distribution: "{params.distribution.value}"}});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="distribute_objects",
        tool_name="illustrator_distribute_objects",
        params={"distribution": params.distribution.value}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_group_selection",
    annotations={"title": "Group Objects", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_group_selection() -> str:
    """Group selected objects."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (sel.length < 2) {
            throw new Error("Select at least 2 objects to group");
        }
        var group = doc.groupItems.add();
        for (var i = sel.length - 1; i >= 0; i--) {
            sel[i].move(group, ElementPlacement.PLACEATEND);
        }
        return JSON.stringify({success: true, itemCount: group.pageItems.length});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="group_selection",
        tool_name="illustrator_group_selection",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_ungroup_selection",
    annotations={"title": "Ungroup Objects", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_ungroup_selection() -> str:
    """Ungroup selected group."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        var ungrouped = 0;
        for (var i = sel.length - 1; i >= 0; i--) {
            if (sel[i].typename === "GroupItem") {
                var items = sel[i].pageItems;
                var itemCount = items.length;
                for (var j = itemCount - 1; j >= 0; j--) {
                    items[j].move(doc.activeLayer, ElementPlacement.PLACEATEND);
                }
                sel[i].remove();
                ungrouped++;
            }
        }
        return JSON.stringify({success: true, ungroupedCount: ungrouped});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="ungroup_selection",
        tool_name="illustrator_ungroup_selection",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_make_clipping_mask",
    annotations={"title": "Make Clipping Mask", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_make_clipping_mask() -> str:
    """Create clipping mask from selection (top object becomes mask)."""
    script = """
    (function() {
        app.executeMenuCommand("makeMask");
        return JSON.stringify({success: true, message: "Clipping mask created"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="make_clipping_mask",
        tool_name="illustrator_make_clipping_mask",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_release_clipping_mask",
    annotations={"title": "Release Clipping Mask", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_release_clipping_mask() -> str:
    """Release the selected clipping mask."""
    script = """
    (function() {
        app.executeMenuCommand("releaseMask");
        return JSON.stringify({success: true, message: "Clipping mask released"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="release_clipping_mask",
        tool_name="illustrator_release_clipping_mask",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_bring_to_front",
    annotations={"title": "Bring to Front", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_bring_to_front() -> str:
    """Bring selected objects to front."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        for (var i = 0; i < sel.length; i++) {
            sel[i].zOrder(ZOrderMethod.BRINGTOFRONT);
        }
        return JSON.stringify({success: true, message: "Brought to front"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="bring_to_front",
        tool_name="illustrator_bring_to_front",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_send_to_back",
    annotations={"title": "Send to Back", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_send_to_back() -> str:
    """Send selected objects to back."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        for (var i = 0; i < sel.length; i++) {
            sel[i].zOrder(ZOrderMethod.SENDTOBACK);
        }
        return JSON.stringify({success: true, message: "Sent to back"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="send_to_back",
        tool_name="illustrator_send_to_back",
        params={}
    )
    return format_response(response)
