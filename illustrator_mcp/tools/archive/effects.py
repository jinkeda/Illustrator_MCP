"""
Effects tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response


# Pydantic models
class DropShadowInput(BaseModel):
    """Input for drop shadow effect."""
    model_config = ConfigDict(str_strip_whitespace=True)
    offset_x: float = Field(default=5, description="Horizontal offset")
    offset_y: float = Field(default=5, description="Vertical offset")
    blur: float = Field(default=5, description="Blur radius", ge=0)
    opacity: float = Field(default=75, description="Shadow opacity (0-100)", ge=0, le=100)
    red: int = Field(default=0, description="Red (0-255)", ge=0, le=255)
    green: int = Field(default=0, description="Green (0-255)", ge=0, le=255)
    blue: int = Field(default=0, description="Blue (0-255)", ge=0, le=255)


class BlurInput(BaseModel):
    """Input for Gaussian blur."""
    model_config = ConfigDict(str_strip_whitespace=True)
    radius: float = Field(..., description="Blur radius in points", ge=0, le=250)


class GlowInput(BaseModel):
    """Input for glow effect."""
    model_config = ConfigDict(str_strip_whitespace=True)
    blur: float = Field(default=5, description="Blur amount", ge=0)
    opacity: float = Field(default=75, description="Glow opacity (0-100)", ge=0, le=100)
    red: int = Field(default=255, description="Red (0-255)", ge=0, le=255)
    green: int = Field(default=255, description="Green (0-255)", ge=0, le=255)
    blue: int = Field(default=0, description="Blue (0-255)", ge=0, le=255)


class GradientInput(BaseModel):
    """Input for gradient."""
    model_config = ConfigDict(str_strip_whitespace=True)
    start_r: int = Field(..., description="Start color red (0-255)", ge=0, le=255)
    start_g: int = Field(..., description="Start color green (0-255)", ge=0, le=255)
    start_b: int = Field(..., description="Start color blue (0-255)", ge=0, le=255)
    end_r: int = Field(..., description="End color red (0-255)", ge=0, le=255)
    end_g: int = Field(..., description="End color green (0-255)", ge=0, le=255)
    end_b: int = Field(..., description="End color blue (0-255)", ge=0, le=255)
    angle: float = Field(default=0, description="Gradient angle (degrees)")


class RadialGradientInput(BaseModel):
    """Input for radial gradient."""
    model_config = ConfigDict(str_strip_whitespace=True)
    start_r: int = Field(..., description="Center color red (0-255)", ge=0, le=255)
    start_g: int = Field(..., description="Center color green (0-255)", ge=0, le=255)
    start_b: int = Field(..., description="Center color blue (0-255)", ge=0, le=255)
    end_r: int = Field(..., description="Edge color red (0-255)", ge=0, le=255)
    end_g: int = Field(..., description="Edge color green (0-255)", ge=0, le=255)
    end_b: int = Field(..., description="Edge color blue (0-255)", ge=0, le=255)


# Tool implementations
@mcp.tool(
    name="illustrator_apply_drop_shadow",
    annotations={"title": "Apply Drop Shadow", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_apply_drop_shadow(params: DropShadowInput) -> str:
    """Add drop shadow effect to selection."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        // Apply via menu - actual effect requires Effect menu
        app.executeMenuCommand("Adobe Drop Shadow");
        return JSON.stringify({{
            success: true,
            message: "Drop shadow dialog opened - configure manually",
            params: {{offsetX: {params.offset_x}, offsetY: {params.offset_y}, blur: {params.blur}}}
        }});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="apply_drop_shadow",
        tool_name="illustrator_apply_drop_shadow",
        params={"offset_x": params.offset_x, "offset_y": params.offset_y, "blur": params.blur, "opacity": params.opacity}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_apply_blur",
    annotations={"title": "Apply Gaussian Blur", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_apply_blur(params: BlurInput) -> str:
    """Apply Gaussian blur to selection."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        app.executeMenuCommand("Adobe Gaussian Blur");
        return JSON.stringify({{
            success: true,
            message: "Blur dialog opened - configure manually",
            radius: {params.radius}
        }});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="apply_blur",
        tool_name="illustrator_apply_blur",
        params={"radius": params.radius}
    )
    return format_response(response)


# DISABLED: Tool limit reduction for Antigravity
# @mcp.tool(
#     name="illustrator_apply_inner_glow",
#     annotations={"title": "Apply Inner Glow", "readOnlyHint": False, "destructiveHint": False}
# )
async def illustrator_apply_inner_glow(params: GlowInput) -> str:
    """Add inner glow effect to selection."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        app.executeMenuCommand("Adobe Inner Glow");
        return JSON.stringify({{
            success: true,
            message: "Inner glow dialog opened",
            blur: {params.blur},
            opacity: {params.opacity}
        }});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="apply_inner_glow",
        tool_name="illustrator_apply_inner_glow",
        params={"blur": params.blur, "opacity": params.opacity}
    )
    return format_response(response)


# DISABLED: Tool limit reduction for Antigravity
# @mcp.tool(
#     name="illustrator_apply_outer_glow",
#     annotations={"title": "Apply Outer Glow", "readOnlyHint": False, "destructiveHint": False}
# )
async def illustrator_apply_outer_glow(params: GlowInput) -> str:
    """Add outer glow effect to selection."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        app.executeMenuCommand("Adobe Outer Glow");
        return JSON.stringify({{
            success: true,
            message: "Outer glow dialog opened",
            blur: {params.blur},
            opacity: {params.opacity}
        }});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="apply_outer_glow",
        tool_name="illustrator_apply_outer_glow",
        params={"blur": params.blur, "opacity": params.opacity}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_clear_effects",
    annotations={"title": "Clear Effects", "readOnlyHint": False, "destructiveHint": True}
)
async def illustrator_clear_effects() -> str:
    """Remove all effects from selection."""
    script = """
    (function() {
        app.executeMenuCommand("Clear Appearance");
        return JSON.stringify({success: true, message: "Effects cleared"});
    })()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="clear_effects",
        tool_name="illustrator_clear_effects",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_apply_linear_gradient",
    annotations={"title": "Apply Linear Gradient", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_apply_linear_gradient(params: GradientInput) -> str:
    """Apply linear gradient fill to selection."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        
        // Create gradient
        var gradient = doc.gradients.add();
        gradient.type = GradientType.LINEAR;
        
        // Start color
        var startColor = new RGBColor();
        startColor.red = {params.start_r};
        startColor.green = {params.start_g};
        startColor.blue = {params.start_b};
        gradient.gradientStops[0].color = startColor;
        gradient.gradientStops[0].rampPoint = 0;
        
        // End color
        var endColor = new RGBColor();
        endColor.red = {params.end_r};
        endColor.green = {params.end_g};
        endColor.blue = {params.end_b};
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
            message: "Linear gradient applied",
            angle: {params.angle}
        }});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="apply_linear_gradient",
        tool_name="illustrator_apply_linear_gradient",
        params={"start_r": params.start_r, "start_g": params.start_g, "start_b": params.start_b, "end_r": params.end_r, "end_g": params.end_g, "end_b": params.end_b, "angle": params.angle}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_apply_radial_gradient",
    annotations={"title": "Apply Radial Gradient", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_apply_radial_gradient(params: RadialGradientInput) -> str:
    """Apply radial gradient fill to selection."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        
        // Create gradient
        var gradient = doc.gradients.add();
        gradient.type = GradientType.RADIAL;
        
        // Center color
        var startColor = new RGBColor();
        startColor.red = {params.start_r};
        startColor.green = {params.start_g};
        startColor.blue = {params.start_b};
        gradient.gradientStops[0].color = startColor;
        gradient.gradientStops[0].rampPoint = 0;
        
        // Edge color
        var endColor = new RGBColor();
        endColor.red = {params.end_r};
        endColor.green = {params.end_g};
        endColor.blue = {params.end_b};
        gradient.gradientStops[1].color = endColor;
        gradient.gradientStops[1].rampPoint = 100;
        
        // Apply to selection
        for (var i = 0; i < sel.length; i++) {{
            if (sel[i].filled !== undefined) {{
                sel[i].filled = true;
                sel[i].fillColor = gradient;
            }}
        }}
        
        return JSON.stringify({{success: true, message: "Radial gradient applied"}});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="apply_radial_gradient",
        tool_name="illustrator_apply_radial_gradient",
        params={"start_r": params.start_r, "start_g": params.start_g, "start_b": params.start_b, "end_r": params.end_r, "end_g": params.end_g, "end_b": params.end_b}
    )
    return format_response(response)
