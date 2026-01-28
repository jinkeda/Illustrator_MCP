"""
Selection and transformation tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response


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
    response = await execute_script_with_context(
        script=script,
        command_type="select_all",
        tool_name="illustrator_select_all",
        params={}
    )
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


# Pydantic models for new selection tools
class SelectByNameInput(BaseModel):
    """Input for selecting by name pattern."""
    model_config = ConfigDict(str_strip_whitespace=True)
    pattern: str = Field(..., description="Name pattern to match (supports * wildcard)", min_length=1)
    case_sensitive: bool = Field(default=False, description="Whether matching is case-sensitive")


class FindObjectsInput(BaseModel):
    """Input for finding objects."""
    model_config = ConfigDict(str_strip_whitespace=True)
    object_type: str = Field(
        default="all",
        description="Object type filter: all, PathItem, TextFrame, GroupItem, etc."
    )
    layer_name: str = Field(default="", description="Limit search to specific layer (empty = all layers)")


class SelectOnLayerInput(BaseModel):
    """Input for selecting on a layer."""
    model_config = ConfigDict(str_strip_whitespace=True)
    layer_name: str = Field(..., description="Name of the layer", min_length=1)


@mcp.tool(
    name="illustrator_select_by_name",
    annotations={"title": "Select By Name", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_select_by_name(params: SelectByNameInput) -> str:
    """Select objects whose names match a pattern. 
    
    Use * as wildcard. For example:
    - "axis_*" matches "axis_x", "axis_y", "axis_label"
    - "*_label" matches "x_label", "y_label"
    - "bar_1" matches exactly "bar_1"
    """
    case_flag = "i" if not params.case_sensitive else ""
    # Convert simple wildcard pattern to regex
    pattern_escaped = params.pattern.replace(".", "\\.").replace("*", ".*")
    
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var pattern = new RegExp("^{pattern_escaped}$", "{case_flag}");
        var matched = [];
        
        function findInItems(items) {{
            for (var i = 0; i < items.length; i++) {{
                var item = items[i];
                if (item.name && pattern.test(item.name)) {{
                    matched.push(item);
                }}
                if (item.typename === "GroupItem") {{
                    findInItems(item.pageItems);
                }}
            }}
        }}
        
        for (var i = 0; i < doc.layers.length; i++) {{
            if (!doc.layers[i].locked && doc.layers[i].visible) {{
                findInItems(doc.layers[i].pageItems);
            }}
        }}
        
        doc.selection = matched;
        var names = [];
        for (var j = 0; j < matched.length; j++) {{
            names.push(matched[j].name);
        }}
        return JSON.stringify({{success: true, count: matched.length, matchedNames: names}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_find_objects",
    annotations={"title": "Find Objects", "readOnlyHint": True, "destructiveHint": False}
)
async def illustrator_find_objects(params: FindObjectsInput) -> str:
    """Find and list objects by type and/or layer without selecting them.
    
    Returns object names, types, and positions for reference.
    """
    layer_filter = f'"{params.layer_name}"' if params.layer_name else "null"
    type_filter = f'"{params.object_type}"' if params.object_type != "all" else "null"
    
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var typeFilter = {type_filter};
        var layerFilter = {layer_filter};
        var found = [];
        
        function scanItems(items, layerName) {{
            for (var i = 0; i < items.length; i++) {{
                var item = items[i];
                var matchType = !typeFilter || item.typename === typeFilter;
                if (matchType) {{
                    found.push({{
                        name: item.name || "(unnamed)",
                        type: item.typename,
                        layer: layerName,
                        left: item.left,
                        top: item.top,
                        width: item.width,
                        height: item.height
                    }});
                }}
                if (item.typename === "GroupItem") {{
                    scanItems(item.pageItems, layerName);
                }}
            }}
        }}
        
        for (var i = 0; i < doc.layers.length; i++) {{
            var layer = doc.layers[i];
            if (!layerFilter || layer.name === layerFilter) {{
                scanItems(layer.pageItems, layer.name);
            }}
        }}
        
        return JSON.stringify({{success: true, count: found.length, objects: found}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_select_on_layer",
    annotations={"title": "Select On Layer", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_select_on_layer(params: SelectOnLayerInput) -> str:
    """Select all objects on a specific layer."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var layer = doc.layers.getByName("{params.layer_name}");
        if (!layer) throw new Error("Layer not found: {params.layer_name}");
        
        var items = [];
        function collectItems(pageItems) {{
            for (var i = 0; i < pageItems.length; i++) {{
                items.push(pageItems[i]);
                if (pageItems[i].typename === "GroupItem") {{
                    collectItems(pageItems[i].pageItems);
                }}
            }}
        }}
        collectItems(layer.pageItems);
        
        doc.selection = items;
        return JSON.stringify({{success: true, count: items.length, layer: "{params.layer_name}"}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)
