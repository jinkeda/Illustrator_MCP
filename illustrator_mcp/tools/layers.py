"""
Layer management tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script, format_response


# Pydantic models
class CreateLayerInput(BaseModel):
    """Input for creating a layer."""
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., description="Layer name", min_length=1, max_length=255)


class DeleteLayerInput(BaseModel):
    """Input for deleting a layer."""
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., description="Layer name to delete", min_length=1)


class SetActiveLayerInput(BaseModel):
    """Input for setting active layer."""
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., description="Layer name", min_length=1)


class RenameLayerInput(BaseModel):
    """Input for renaming a layer."""
    model_config = ConfigDict(str_strip_whitespace=True)
    current_name: str = Field(..., description="Current name", min_length=1)
    new_name: str = Field(..., description="New name", min_length=1, max_length=255)


class ToggleLayerVisibilityInput(BaseModel):
    """Input for toggling layer visibility."""
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., description="Layer name", min_length=1)
    visible: Optional[bool] = Field(default=None, description="Set visibility (or toggle if null)")


# Tool implementations
@mcp.tool(
    name="illustrator_list_layers",
    annotations={"title": "List Layers", "readOnlyHint": True, "destructiveHint": False}
)
async def illustrator_list_layers() -> str:
    """List all layers in the document."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var layers = [];
        for (var i = 0; i < doc.layers.length; i++) {
            var layer = doc.layers[i];
            layers.push({
                name: layer.name,
                visible: layer.visible,
                locked: layer.locked,
                isActive: layer === doc.activeLayer,
                itemCount: layer.pageItems.length
            });
        }
        return JSON.stringify({layers: layers});
    })()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_create_layer",
    annotations={"title": "Create Layer", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_create_layer(params: CreateLayerInput) -> str:
    """Create a new layer."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var layer = doc.layers.add();
        layer.name = "{params.name}";
        return JSON.stringify({{success: true, name: layer.name}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_delete_layer",
    annotations={"title": "Delete Layer", "readOnlyHint": False, "destructiveHint": True}
)
async def illustrator_delete_layer(params: DeleteLayerInput) -> str:
    """Delete a layer by name."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var layer = doc.layers.getByName("{params.name}");
        layer.remove();
        return JSON.stringify({{success: true, message: "Layer deleted"}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_set_active_layer",
    annotations={"title": "Set Active Layer", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_set_active_layer(params: SetActiveLayerInput) -> str:
    """Set the active layer."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var layer = doc.layers.getByName("{params.name}");
        doc.activeLayer = layer;
        return JSON.stringify({{success: true, activeLayer: "{params.name}"}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_rename_layer",
    annotations={"title": "Rename Layer", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_rename_layer(params: RenameLayerInput) -> str:
    """Rename a layer."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var layer = doc.layers.getByName("{params.current_name}");
        layer.name = "{params.new_name}";
        return JSON.stringify({{success: true, oldName: "{params.current_name}", newName: "{params.new_name}"}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_toggle_layer_visibility",
    annotations={"title": "Toggle Layer Visibility", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_toggle_layer_visibility(params: ToggleLayerVisibilityInput) -> str:
    """Show or hide a layer."""
    if params.visible is not None:
        visibility_code = f"layer.visible = {'true' if params.visible else 'false'};"
    else:
        visibility_code = "layer.visible = !layer.visible;"
    
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var layer = doc.layers.getByName("{params.name}");
        {visibility_code}
        return JSON.stringify({{success: true, name: "{params.name}", visible: layer.visible}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)
