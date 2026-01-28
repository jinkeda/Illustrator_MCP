"""
Composite tools for Adobe Illustrator.

These tools combine multiple atomic operations into single tool calls
to reduce latency and improve agent efficiency (following Advanced Tool Use best practices).
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response


# Pydantic models
class DrawFormattedTextInput(BaseModel):
    """Input for drawing formatted text in one step."""
    model_config = ConfigDict(str_strip_whitespace=True)
    content: str = Field(..., description="Text content")
    x: float = Field(..., description="X position")
    y: float = Field(..., description="Y position")
    font_family: str = Field(default="Helvetica", description="Font family name")
    font_size: float = Field(default=12, description="Font size in points")
    font_style: Optional[str] = Field(default=None, description="Font style (e.g. Bold, Italic)")
    align: Literal["left", "center", "right"] = Field(default="left", description="Text alignment")
    red: int = Field(default=0, description="Red component (0-255)")
    green: int = Field(default=0, description="Green component (0-255)")
    blue: int = Field(default=0, description="Blue component (0-255)")


class DrawArrowInput(BaseModel):
    """Input for drawing an arrow."""
    model_config = ConfigDict(str_strip_whitespace=True)
    x1: float = Field(..., description="Start X position")
    y1: float = Field(..., description="Start Y position")
    x2: float = Field(..., description="End (tip) X position")
    y2: float = Field(..., description="End (tip) Y position")
    stroke_width: float = Field(default=1.0, description="Line thickness")
    arrow_size: float = Field(default=10.0, description="Size of the arrow head")
    red: int = Field(default=0, description="Red component (0-255)")
    green: int = Field(default=0, description="Green component (0-255)")
    blue: int = Field(default=0, description="Blue component (0-255)")


# Tool implementations
@mcp.tool(
    name="illustrator_draw_formatted_text",
    annotations={"title": "Draw Formatted Text", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_draw_formatted_text(params: DrawFormattedTextInput) -> str:
    """Create text with font, size, alignment, and color in one step.
    
    This helps avoid multiple round-trips for setting properties separately.

    Example:
        {
          "content": "Figure 1A",
          "x": 100,
          "y": 500,
          "font_family": "Arial",
          "font_style": "Bold",
          "font_size": 14,
          "align": "left",
          "red": 0,
          "green": 0,
          "blue": 0
        }
    """
    content_escaped = params.content.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    
    # Handle font style concatenation
    font_name_search = f"{params.font_family}-{params.font_style}" if params.font_style else params.font_family
    
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var ab = doc.artboards[0].artboardRect;
        var artH = ab[1] - ab[3];
        
        // Create text frame
        var textFrame = doc.textFrames.add();
        textFrame.contents = "{content_escaped}";
        textFrame.position = [{params.x}, {-params.y}]; // Direct position logic (simplest)
        
        // Note: position usually means top-left for point text.
        // For accurate Y alignment relative to baseline, we might need adjustments,
        // but for now we stick to standard Top-Left anchor behavior.
        
        var charAttr = textFrame.textRange.characterAttributes;
        
        // Set Font
        try {{
            charAttr.textFont = app.textFonts.getByName("{font_name_search}");
        }} catch(e) {{
            try {{
                charAttr.textFont = app.textFonts.getByName("{params.font_family}");
            }} catch(e2) {{}}
        }}
        
        // Set Size
        charAttr.size = {params.font_size};
        
        // Set Color
        var col = new RGBColor();
        col.red = {params.red};
        col.green = {params.green};
        col.blue = {params.blue};
        charAttr.fillColor = col;
        
        // Alignment (Paragraph Attribute)
        // Justification.LEFT/CENTER/RIGHT
        var paraAttr = textFrame.textRange.paragraphAttributes;
        if ("{params.align}" === "center") paraAttr.justification = Justification.CENTER;
        else if ("{params.align}" === "right") paraAttr.justification = Justification.RIGHT;
        else paraAttr.justification = Justification.LEFT;
        
        return JSON.stringify({{
            success: true,
            content: "{content_escaped}",
            position: {{x: {params.x}, y: {params.y}}},
            color: {{r: {params.red}, g: {params.green}, b: {params.blue}}}
        }});
    }})()
    """
    
    response = await execute_script_with_context(
        script=script,
        command_type="draw_formatted_text",
        tool_name="illustrator_draw_formatted_text",
        params=params.model_dump()
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_draw_arrow",
    annotations={"title": "Draw Arrow", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_draw_arrow(params: DrawArrowInput) -> str:
    """Draw a line with an arrowhead at the end (x2, y2).
    
    Combines drawing the line, drawing the arrow head (polygon), coloring both,
    and grouping them into a single object.

    Example:
        {
          "x1": 10,
          "y1": 10,
          "x2": 100,
          "y2": 100,
          "stroke_width": 2,
          "arrow_size": 12,
          "red": 255,
          "green": 0,
          "blue": 0
        }
    """
    import math
    
    # Calculate arrow geometry in Python for simplicity
    # Visual coordinates (Y up)
    dx = params.x2 - params.x1
    dy = params.y2 - params.y1
    angle = math.atan2(dy, dx)
    
    # Arrow head points (triangle)
    head_len = params.arrow_size
    phi = math.pi / 6  # 30 degrees
    
    # Tip is at (x2, y2)
    p1x, p1y = params.x2, params.y2
    
    # Back corners
    p2x = params.x2 - head_len * math.cos(angle - phi)
    p2y = params.y2 - head_len * math.sin(angle - phi)
    
    p3x = params.x2 - head_len * math.cos(angle + phi)
    p3y = params.y2 - head_len * math.sin(angle + phi)
    
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var group = doc.groupItems.add();
        group.name = "Arrow";
        
        // Define Color
        var col = new RGBColor();
        col.red = {params.red};
        col.green = {params.green};
        col.blue = {params.blue};
        
        // Draw Line
        var line = group.pathItems.add();
        line.setEntirePath([[{params.x1}, {-params.y1}], [{params.x2}, {-params.y2}]]);
        line.stroked = true;
        line.filled = false;
        line.strokeColor = col;
        line.strokeWidth = {params.stroke_width};
        
        // Draw Arrowhead (as a filled path)
        var head = group.pathItems.add();
        head.setEntirePath([
            [{p1x}, {-p1y}],
            [{p2x}, {-p2y}],
            [{p3x}, {-p3y}]
        ]);
        head.closed = true;
        head.filled = true;
        head.stroked = false;
        head.fillColor = col;
        
        return JSON.stringify({{
            success: true,
            type: "arrow",
            from: {{x: {params.x1}, y: {params.y1}}},
            to: {{x: {params.x2}, y: {params.y2}}},
            groupName: group.name
        }});
    }})()
    """
    
    response = await execute_script_with_context(
        script=script,
        command_type="draw_arrow",
        tool_name="illustrator_draw_arrow",
        params=params.model_dump()
    )
    return format_response(response)


# ============================================================================
# Additional Composite Tools (Phase 2)
# ============================================================================

class DrawScaleBarInput(BaseModel):
    """Input for drawing a scale bar with label."""
    model_config = ConfigDict(str_strip_whitespace=True)
    x: float = Field(..., description="X position of scale bar left edge")
    y: float = Field(..., description="Y position of scale bar")
    width: float = Field(..., description="Width of scale bar in points")
    height: float = Field(default=5, description="Height/thickness of scale bar")
    label: str = Field(..., description="Label text (e.g. '10 μm', '100 nm')")
    font_size: float = Field(default=8, description="Font size for label")
    red: int = Field(default=0, description="Red component (0-255)")
    green: int = Field(default=0, description="Green component (0-255)")
    blue: int = Field(default=0, description="Blue component (0-255)")


@mcp.tool(
    name="illustrator_draw_scale_bar",
    annotations={"title": "Draw Scale Bar", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_draw_scale_bar(params: DrawScaleBarInput) -> str:
    """Draw a scale bar with label, grouped together.
    
    Creates a filled rectangle and centered label text, then groups them.
    Common in microscopy images and scientific figures.

    Example:
        {
          "x": 350,
          "y": 50,
          "width": 50,
          "height": 5,
          "label": "10 μm",
          "font_size": 8,
          "red": 0,
          "green": 0,
          "blue": 0
        }
    """
    label_escaped = params.label.replace("\\", "\\\\").replace('"', '\\"')
    label_x = params.x + params.width / 2  # Center label
    label_y = params.y + params.height + 2  # Below bar
    
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var group = doc.groupItems.add();
        group.name = "ScaleBar";
        
        var col = new RGBColor();
        col.red = {params.red};
        col.green = {params.green};
        col.blue = {params.blue};
        
        // Draw scale bar rectangle
        var bar = group.pathItems.rectangle({-params.y}, {params.x}, {params.width}, {params.height});
        bar.fillColor = col;
        bar.stroked = false;
        
        // Add label text
        var text = group.textFrames.add();
        text.contents = "{label_escaped}";
        text.position = [{label_x}, {-label_y}];
        text.textRange.characterAttributes.size = {params.font_size};
        text.textRange.characterAttributes.fillColor = col;
        text.textRange.paragraphAttributes.justification = Justification.CENTER;
        
        return JSON.stringify({{
            success: true,
            type: "scale_bar",
            position: {{x: {params.x}, y: {params.y}}},
            width: {params.width},
            label: "{label_escaped}"
        }});
    }})()
    """
    
    response = await execute_script_with_context(
        script=script,
        command_type="draw_scale_bar",
        tool_name="illustrator_draw_scale_bar",
        params=params.model_dump()
    )
    return format_response(response)


class CreateAxisInput(BaseModel):
    """Input for creating an axis with ticks and labels."""
    model_config = ConfigDict(str_strip_whitespace=True)
    orientation: Literal["horizontal", "vertical"] = Field(..., description="Axis direction")
    x: float = Field(..., description="X position of axis origin")
    y: float = Field(..., description="Y position of axis origin")
    length: float = Field(..., description="Length of axis in points")
    tick_count: int = Field(default=5, description="Number of tick marks", ge=2, le=20)
    tick_length: float = Field(default=5, description="Length of tick marks")
    labels: Optional[str] = Field(default=None, description="Comma-separated tick labels (e.g. '0,25,50,75,100')")
    axis_label: Optional[str] = Field(default=None, description="Axis title (e.g. 'Time (s)')")
    stroke_width: float = Field(default=1.0, description="Line thickness")
    font_size: float = Field(default=8, description="Font size for labels")


@mcp.tool(
    name="illustrator_create_axis",
    annotations={"title": "Create Axis", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_create_axis(params: CreateAxisInput) -> str:
    """Create a complete axis with line, ticks, and labels.
    
    Replaces multiple draw_line + add_text calls with a single operation.
    Useful for creating plot axes.

    Example (horizontal):
        {
          "orientation": "horizontal",
          "x": 100,
          "y": 100,
          "length": 200,
          "tick_count": 5,
          "labels": "0,25,50,75,100",
          "axis_label": "Time (s)"
        }
    """
    # Parse labels
    tick_labels = params.labels.split(",") if params.labels else []
    axis_label_escaped = params.axis_label.replace("\\", "\\\\").replace('"', '\\"') if params.axis_label else ""
    
    # Generate tick positions
    tick_spacing = params.length / (params.tick_count - 1) if params.tick_count > 1 else params.length
    
    if params.orientation == "horizontal":
        # Horizontal axis: ticks go down
        script = f"""
        (function() {{
            var doc = app.activeDocument;
            var group = doc.groupItems.add();
            group.name = "Axis_Horizontal";
            
            // Main axis line
            var axis = group.pathItems.add();
            axis.setEntirePath([[{params.x}, {-params.y}], [{params.x + params.length}, {-params.y}]]);
            axis.stroked = true;
            axis.strokeWidth = {params.stroke_width};
            axis.filled = false;
            
            // Ticks and labels
            var tickSpacing = {tick_spacing};
            var tickLabels = {tick_labels if tick_labels else '[]'};
            
            for (var i = 0; i < {params.tick_count}; i++) {{
                var tx = {params.x} + i * tickSpacing;
                
                // Tick mark
                var tick = group.pathItems.add();
                tick.setEntirePath([[tx, {-params.y}], [tx, {-(params.y - params.tick_length)}]]);
                tick.stroked = true;
                tick.strokeWidth = {params.stroke_width};
                tick.filled = false;
                
                // Label (if provided)
                if (tickLabels[i]) {{
                    var label = group.textFrames.add();
                    label.contents = tickLabels[i];
                    label.position = [tx - 5, {-(params.y - params.tick_length - 3)}];
                    label.textRange.characterAttributes.size = {params.font_size};
                    label.textRange.paragraphAttributes.justification = Justification.CENTER;
                }}
            }}
            
            // Axis title
            if ("{axis_label_escaped}") {{
                var title = group.textFrames.add();
                title.contents = "{axis_label_escaped}";
                title.position = [{params.x + params.length / 2 - 20}, {-(params.y - params.tick_length - 15)}];
                title.textRange.characterAttributes.size = {params.font_size + 2};
                title.textRange.paragraphAttributes.justification = Justification.CENTER;
            }}
            
            return JSON.stringify({{
                success: true,
                type: "axis",
                orientation: "horizontal",
                length: {params.length},
                ticks: {params.tick_count}
            }});
        }})()
        """
    else:
        # Vertical axis: ticks go left
        script = f"""
        (function() {{
            var doc = app.activeDocument;
            var group = doc.groupItems.add();
            group.name = "Axis_Vertical";
            
            // Main axis line
            var axis = group.pathItems.add();
            axis.setEntirePath([[{params.x}, {-params.y}], [{params.x}, {-(params.y + params.length)}]]);
            axis.stroked = true;
            axis.strokeWidth = {params.stroke_width};
            axis.filled = false;
            
            // Ticks and labels
            var tickSpacing = {tick_spacing};
            var tickLabels = {tick_labels if tick_labels else '[]'};
            
            for (var i = 0; i < {params.tick_count}; i++) {{
                var ty = {params.y} + i * tickSpacing;
                
                // Tick mark
                var tick = group.pathItems.add();
                tick.setEntirePath([[{params.x}, -ty], [{params.x - params.tick_length}, -ty]]);
                tick.stroked = true;
                tick.strokeWidth = {params.stroke_width};
                tick.filled = false;
                
                // Label (if provided)
                if (tickLabels[i]) {{
                    var label = group.textFrames.add();
                    label.contents = tickLabels[i];
                    label.position = [{params.x - params.tick_length - 15}, -ty + 3];
                    label.textRange.characterAttributes.size = {params.font_size};
                    label.textRange.paragraphAttributes.justification = Justification.RIGHT;
                }}
            }}
            
            // Axis title (rotated for vertical)
            if ("{axis_label_escaped}") {{
                var title = group.textFrames.add();
                title.contents = "{axis_label_escaped}";
                title.position = [{params.x - params.tick_length - 30}, {-(params.y + params.length / 2)}];
                title.textRange.characterAttributes.size = {params.font_size + 2};
                title.rotate(90);
            }}
            
            return JSON.stringify({{
                success: true,
                type: "axis",
                orientation: "vertical",
                length: {params.length},
                ticks: {params.tick_count}
            }});
        }})()
        """
    
    response = await execute_script_with_context(
        script=script,
        command_type="create_axis",
        tool_name="illustrator_create_axis",
        params=params.model_dump()
    )
    return format_response(response)
