"""
Object operation tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response


# Pydantic models
class DuplicateSelectionInput(BaseModel):
    """Input for duplicating selection."""
    model_config = ConfigDict(str_strip_whitespace=True)
    offset_x: float = Field(default=10, description="Horizontal offset")
    offset_y: float = Field(default=10, description="Vertical offset")


class CopyToLayerInput(BaseModel):
    """Input for copying to layer."""
    model_config = ConfigDict(str_strip_whitespace=True)
    layer_name: str = Field(..., description="Target layer name", min_length=1)


class RenameObjectInput(BaseModel):
    """Input for renaming object."""
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., description="New name", min_length=1, max_length=255)


class SetOpacityInput(BaseModel):
    """Input for setting opacity."""
    model_config = ConfigDict(str_strip_whitespace=True)
    opacity: float = Field(..., description="Opacity percentage (0-100)", ge=0, le=100)


class SetBlendModeInput(BaseModel):
    """Input for setting blend mode."""
    model_config = ConfigDict(str_strip_whitespace=True)
    mode: str = Field(..., description="Blend mode (normal, multiply, screen, overlay, etc.)")


# Tool implementations
@mcp.tool(
    name="illustrator_duplicate_selection",
    annotations={"title": "Duplicate Selection", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_duplicate_selection(params: DuplicateSelectionInput) -> str:
    """Duplicate selected objects with offset."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        var duplicates = [];
        for (var i = 0; i < sel.length; i++) {{
            var dup = sel[i].duplicate();
            dup.translate({params.offset_x}, {-params.offset_y});
            duplicates.push(dup);
        }}
        doc.selection = duplicates;
        return JSON.stringify({{success: true, duplicatedCount: duplicates.length}});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="duplicate_selection",
        tool_name="illustrator_duplicate_selection",
        params={"offset_x": params.offset_x, "offset_y": params.offset_y}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_copy_to_layer",
    annotations={"title": "Copy to Layer", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_copy_to_layer(params: CopyToLayerInput) -> str:
    """Copy selection to another layer."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        var targetLayer = doc.layers.getByName("{params.layer_name}");
        var copied = 0;
        for (var i = 0; i < sel.length; i++) {{
            var dup = sel[i].duplicate();
            dup.move(targetLayer, ElementPlacement.PLACEATEND);
            copied++;
        }}
        return JSON.stringify({{success: true, copiedCount: copied, targetLayer: "{params.layer_name}"}});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="copy_to_layer",
        tool_name="illustrator_copy_to_layer",
        params={"layer_name": params.layer_name}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_lock_selection",
    annotations={"title": "Lock Selection", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_lock_selection() -> str:
    """Lock selected objects."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        var locked = 0;
        for (var i = 0; i < sel.length; i++) {
            sel[i].locked = true;
            locked++;
        }
        doc.selection = null;
        return JSON.stringify({success: true, lockedCount: locked});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="lock_selection",
        tool_name="illustrator_lock_selection",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_unlock_all",
    annotations={"title": "Unlock All", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_unlock_all() -> str:
    """Unlock all locked objects in the document."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var unlocked = 0;
        function unlockItems(items) {
            for (var i = 0; i < items.length; i++) {
                if (items[i].locked) {
                    items[i].locked = false;
                    unlocked++;
                }
                if (items[i].typename === "GroupItem") {
                    unlockItems(items[i].pageItems);
                }
            }
        }
        for (var i = 0; i < doc.layers.length; i++) {
            doc.layers[i].locked = false;
            unlockItems(doc.layers[i].pageItems);
        }
        return JSON.stringify({success: true, unlockedCount: unlocked});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="unlock_all",
        tool_name="illustrator_unlock_all",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_hide_selection",
    annotations={"title": "Hide Selection", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_hide_selection() -> str:
    """Hide selected objects."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        var hidden = 0;
        for (var i = 0; i < sel.length; i++) {
            sel[i].hidden = true;
            hidden++;
        }
        doc.selection = null;
        return JSON.stringify({success: true, hiddenCount: hidden});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="hide_selection",
        tool_name="illustrator_hide_selection",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_show_all",
    annotations={"title": "Show All", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_show_all() -> str:
    """Show all hidden objects."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var shown = 0;
        function showItems(items) {
            for (var i = 0; i < items.length; i++) {
                if (items[i].hidden) {
                    items[i].hidden = false;
                    shown++;
                }
                if (items[i].typename === "GroupItem") {
                    showItems(items[i].pageItems);
                }
            }
        }
        for (var i = 0; i < doc.layers.length; i++) {
            showItems(doc.layers[i].pageItems);
        }
        return JSON.stringify({success: true, shownCount: shown});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="show_all",
        tool_name="illustrator_show_all",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_get_object_bounds",
    annotations={"title": "Get Object Bounds", "readOnlyHint": True, "destructiveHint": False}
)
async def illustrator_get_object_bounds() -> str:
    """Get bounding box of selection."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        var bounds = [];
        for (var i = 0; i < sel.length; i++) {
            var b = sel[i].geometricBounds;
            bounds.push({
                index: i,
                name: sel[i].name || "",
                left: b[0],
                top: -b[1],
                right: b[2],
                bottom: -b[3],
                width: b[2] - b[0],
                height: b[1] - b[3]
            });
        }
        return JSON.stringify({objects: bounds, count: bounds.length});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="get_object_bounds",
        tool_name="illustrator_get_object_bounds",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_rename_object",
    annotations={"title": "Rename Object", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_rename_object(params: RenameObjectInput) -> str:
    """Rename selected object."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        sel[0].name = "{params.name}";
        return JSON.stringify({{success: true, newName: "{params.name}"}});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="rename_object",
        tool_name="illustrator_rename_object",
        params={"name": params.name}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_set_opacity",
    annotations={"title": "Set Opacity", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_set_opacity(params: SetOpacityInput) -> str:
    """Set transparency of selected objects."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        for (var i = 0; i < sel.length; i++) {{
            sel[i].opacity = {params.opacity};
        }}
        return JSON.stringify({{success: true, opacity: {params.opacity}}});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="set_opacity",
        tool_name="illustrator_set_opacity",
        params={"opacity": params.opacity}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_set_blend_mode",
    annotations={"title": "Set Blend Mode", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_set_blend_mode(params: SetBlendModeInput) -> str:
    """Set blend mode of selected objects."""
    # Map common blend mode names to Illustrator constants
    mode_map = {
        "normal": "BlendModes.NORMAL",
        "multiply": "BlendModes.MULTIPLY",
        "screen": "BlendModes.SCREEN",
        "overlay": "BlendModes.OVERLAY",
        "softlight": "BlendModes.SOFTLIGHT",
        "hardlight": "BlendModes.HARDLIGHT",
        "colordodge": "BlendModes.COLORDODGE",
        "colorburn": "BlendModes.COLORBURN",
        "darken": "BlendModes.DARKEN",
        "lighten": "BlendModes.LIGHTEN",
        "difference": "BlendModes.DIFFERENCE",
        "exclusion": "BlendModes.EXCLUSION",
        "hue": "BlendModes.HUE",
        "saturation": "BlendModes.SATURATION",
        "color": "BlendModes.COLOR",
        "luminosity": "BlendModes.LUMINOSITY"
    }
    mode_const = mode_map.get(params.mode.lower().replace(" ", ""), "BlendModes.NORMAL")
    
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        for (var i = 0; i < sel.length; i++) {{
            sel[i].blendingMode = {mode_const};
        }}
        return JSON.stringify({{success: true, blendMode: "{params.mode}"}});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="set_blend_mode",
        tool_name="illustrator_set_blend_mode",
        params={"mode": params.mode}
    )
    return format_response(response)
