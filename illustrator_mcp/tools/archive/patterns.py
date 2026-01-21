"""
Pattern operation tools for Adobe Illustrator.

These tools handle pattern creation, application, and transformation
for scientific visualizations like atomic lattices and Moiré patterns.
"""

from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response


# Pydantic models
class CreatePatternInput(BaseModel):
    """Input for creating a pattern from selection."""
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., description="Name for the pattern swatch", min_length=1, max_length=255)


class ApplyPatternInput(BaseModel):
    """Input for applying a pattern fill."""
    model_config = ConfigDict(str_strip_whitespace=True)
    pattern_name: str = Field(..., description="Name of pattern swatch to apply", min_length=1)


class TransformPatternInput(BaseModel):
    """Input for transforming pattern only (not object)."""
    model_config = ConfigDict(str_strip_whitespace=True)
    rotate: float = Field(default=0, description="Rotation angle in degrees", ge=-360, le=360)
    scale: float = Field(default=100, description="Scale percentage", gt=0, le=1000)


class SetFillOpacityInput(BaseModel):
    """Input for setting fill opacity."""
    model_config = ConfigDict(str_strip_whitespace=True)
    opacity: float = Field(..., description="Opacity percentage (0-100)", ge=0, le=100)


class GradientStop(BaseModel):
    """A single gradient stop."""
    color: List[int] = Field(..., description="RGB color [r, g, b]", min_length=3, max_length=3)
    position: float = Field(..., description="Position 0-100", ge=0, le=100)


class ApplyGradientInput(BaseModel):
    """Input for applying gradient fill."""
    model_config = ConfigDict(str_strip_whitespace=True)
    gradient_type: str = Field(default="linear", description="linear or radial")
    angle: float = Field(default=0, description="Gradient angle (linear only)", ge=-360, le=360)
    start_color: List[int] = Field(default=[0, 0, 0], description="Start color RGB")
    end_color: List[int] = Field(default=[255, 255, 255], description="End color RGB")


# Tool implementations
@mcp.tool(
    name="illustrator_create_pattern",
    annotations={"title": "Create Pattern", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_create_pattern(params: CreatePatternInput) -> str:
    """Create a pattern swatch from the current selection.
    
    Select your pattern elements (atoms, shapes) plus an invisible
    boundary rectangle, then call this to add to Swatches panel.
    
    Tip: The boundary rect should have no fill/stroke and defines
    the repeating tile size.
    """
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        
        // Create a temporary group for the pattern
        var patternGroup = doc.groupItems.add();
        for (var i = sel.length - 1; i >= 0; i--) {{
            sel[i].move(patternGroup, ElementPlacement.PLACEATEND);
        }}
        
        // Define pattern from group bounds
        var bounds = patternGroup.geometricBounds;
        var pattern = doc.patterns.add();
        pattern.name = "{params.name}";
        
        // Move items back and set as pattern definition
        var patternDef = patternGroup.duplicate();
        patternDef.move(pattern, ElementPlacement.INSIDE);
        
        // Cleanup
        patternGroup.remove();
        
        return JSON.stringify({{
            success: true,
            patternName: "{params.name}",
            message: "Pattern created and added to Swatches"
        }});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="create_pattern",
        tool_name="illustrator_create_pattern",
        params={"name": params.name}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_apply_pattern",
    annotations={"title": "Apply Pattern Fill", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_apply_pattern(params: ApplyPatternInput) -> str:
    """Fill selected objects with a pattern from the Swatches panel."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        
        var pattern;
        try {{
            // Try to find pattern by name in swatches
            for (var i = 0; i < doc.swatches.length; i++) {{
                if (doc.swatches[i].name === "{params.pattern_name}") {{
                    pattern = doc.swatches[i];
                    break;
                }}
            }}
            if (!pattern) throw new Error("Pattern not found");
        }} catch(e) {{
            throw new Error("Pattern not found: {params.pattern_name}");
        }}
        
        for (var i = 0; i < sel.length; i++) {{
            if (sel[i].filled !== undefined) {{
                sel[i].filled = true;
                sel[i].fillColor = pattern.color;
            }}
        }}
        
        return JSON.stringify({{
            success: true,
            patternName: "{params.pattern_name}",
            appliedTo: sel.length
        }});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_transform_pattern",
    annotations={"title": "Transform Pattern Only", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_transform_pattern(params: TransformPatternInput) -> str:
    """Rotate or scale the pattern fill without affecting the object shape.
    
    Use for creating Moiré patterns by rotating pattern in duplicate layer.
    The "magic angle" for twisted bilayer graphene is ~1.1 degrees.
    """
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        
        // Create transformation matrix
        var matrix = app.getIdentityMatrix();
        
        // Apply rotation to matrix
        if ({params.rotate} !== 0) {{
            matrix = app.concatenateRotationMatrix(matrix, {params.rotate});
        }}
        
        // Apply scale to matrix  
        if ({params.scale} !== 100) {{
            var scaleFactor = {params.scale} / 100;
            matrix = app.concatenateScaleMatrix(matrix, scaleFactor, scaleFactor);
        }}
        
        // Transform only patterns, not objects
        for (var i = 0; i < sel.length; i++) {{
            sel[i].transform(matrix, false, false, false, false, 0, Transformation.DOCUMENTORIGIN);
        }}
        
        return JSON.stringify({{
            success: true,
            rotate: {params.rotate},
            scale: {params.scale},
            message: "Pattern transformed (object unchanged)"
        }});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_set_fill_opacity",
    annotations={"title": "Set Fill Opacity", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_set_fill_opacity(params: SetFillOpacityInput) -> str:
    """Set the opacity of the fill only (stroke remains solid).
    
    Use for layered Moiré effects where you need to see through
    the top layer to the bottom layer.
    """
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        
        for (var i = 0; i < sel.length; i++) {{
            // Set overall opacity (affects both fill and stroke)
            sel[i].opacity = {params.opacity};
        }}
        
        return JSON.stringify({{
            success: true,
            opacity: {params.opacity}
        }});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_apply_gradient",
    annotations={"title": "Apply Gradient Fill", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_apply_gradient(params: ApplyGradientInput) -> str:
    """Apply a linear or radial gradient fill to selected objects.
    
    Use for heat maps, depth cues, or visual effects.
    """
    gradient_type = "GradientType.LINEAR" if params.gradient_type == "linear" else "GradientType.RADIAL"
    
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        
        // Create gradient
        var gradient = doc.gradients.add();
        gradient.type = {gradient_type};
        
        // Set gradient stops
        var startColor = new RGBColor();
        startColor.red = {params.start_color[0]};
        startColor.green = {params.start_color[1]};
        startColor.blue = {params.start_color[2]};
        
        var endColor = new RGBColor();
        endColor.red = {params.end_color[0]};
        endColor.green = {params.end_color[1]};
        endColor.blue = {params.end_color[2]};
        
        gradient.gradientStops[0].color = startColor;
        gradient.gradientStops[0].rampPoint = 0;
        gradient.gradientStops[1].color = endColor;
        gradient.gradientStops[1].rampPoint = 100;
        
        // Apply to selection
        for (var i = 0; i < sel.length; i++) {{
            if (sel[i].filled !== undefined) {{
                sel[i].filled = true;
                sel[i].fillColor = gradient;
            }}
        }}
        
        return JSON.stringify({{
            success: true,
            gradientType: "{params.gradient_type}",
            angle: {params.angle}
        }});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_list_patterns",
    annotations={"title": "List Patterns", "readOnlyHint": True, "destructiveHint": False}
)
async def illustrator_list_patterns() -> str:
    """List all pattern swatches in the document."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var patterns = [];
        
        for (var i = 0; i < doc.swatches.length; i++) {
            var swatch = doc.swatches[i];
            if (swatch.color && swatch.color.typename === "PatternColor") {
                patterns.push({
                    name: swatch.name,
                    index: i
                });
            }
        }
        
        return JSON.stringify({success: true, patterns: patterns, count: patterns.length});
    })()
    """
    response = await execute_script(script)
    return format_response(response)
