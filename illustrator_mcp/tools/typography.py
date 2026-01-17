"""
Advanced typography tools for Adobe Illustrator.

These tools use execute_script internally to run JavaScript in Illustrator.
"""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response


# Pydantic models
class TextOnPathInput(BaseModel):
    """Input for text on path."""
    model_config = ConfigDict(str_strip_whitespace=True)
    text: str = Field(..., description="Text content", min_length=1)
    font_size: float = Field(default=12, description="Font size", gt=0)


class AreaTextInput(BaseModel):
    """Input for area text."""
    model_config = ConfigDict(str_strip_whitespace=True)
    text: str = Field(..., description="Text content", min_length=1)
    font_size: float = Field(default=12, description="Font size", gt=0)


class ParagraphAlignmentInput(BaseModel):
    """Input for paragraph alignment."""
    model_config = ConfigDict(str_strip_whitespace=True)
    alignment: str = Field(..., description="Alignment: left, center, right, justify")


class CharacterSpacingInput(BaseModel):
    """Input for character spacing."""
    model_config = ConfigDict(str_strip_whitespace=True)
    tracking: int = Field(default=0, description="Tracking (space between all chars)")
    kerning: Optional[int] = Field(default=None, description="Kerning (space between pairs)")


class LineHeightInput(BaseModel):
    """Input for line height."""
    model_config = ConfigDict(str_strip_whitespace=True)
    leading: float = Field(..., description="Leading (line spacing) in points", gt=0)


# Tool implementations
# DISABLED: Tool limit reduction for Antigravity
# @mcp.tool(
#     name="illustrator_create_text_on_path",
#     annotations={"title": "Create Text on Path", "readOnlyHint": False, "destructiveHint": False}
# )
async def illustrator_create_text_on_path(params: TextOnPathInput) -> str:
    """Create text following a selected path."""
    content = params.text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No path selected");
        if (sel[0].typename !== "PathItem") throw new Error("Selection must be a path");
        
        var pathText = doc.textFrames.pathText(sel[0]);
        pathText.contents = "{content}";
        pathText.textRange.characterAttributes.size = {params.font_size};
        
        return JSON.stringify({{
            success: true,
            text: "{content}",
            fontSize: {params.font_size}
        }});
    }})()
    """
    response = await execute_script_with_context(
        script=script,
        command_type="create_text_on_path",
        tool_name="illustrator_create_text_on_path",
        params={"text": params.text, "font_size": params.font_size}
    )
    return format_response(response)


# DISABLED: Tool limit reduction for Antigravity
# @mcp.tool(
#     name="illustrator_create_area_text",
#     annotations={"title": "Create Area Text", "readOnlyHint": False, "destructiveHint": False}
# )
async def illustrator_create_area_text(params: AreaTextInput) -> str:
    """Create text inside a selected shape."""
    content = params.text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No shape selected");
        if (sel[0].typename !== "PathItem") throw new Error("Selection must be a closed path");
        
        var areaText = doc.textFrames.areaText(sel[0]);
        areaText.contents = "{content}";
        areaText.textRange.characterAttributes.size = {params.font_size};
        
        return JSON.stringify({{
            success: true,
            text: "{content}",
            fontSize: {params.font_size}
        }});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_convert_text_to_outlines",
    annotations={"title": "Convert Text to Outlines", "readOnlyHint": False, "destructiveHint": True}
)
async def illustrator_convert_text_to_outlines() -> str:
    """Convert selected text to vector paths."""
    script = """
    (function() {
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        
        var converted = 0;
        for (var i = 0; i < sel.length; i++) {
            if (sel[i].typename === "TextFrame") {
                sel[i].createOutline();
                converted++;
            }
        }
        
        return JSON.stringify({success: true, convertedCount: converted});
    })()
    """
    response = await execute_script(script)
    return format_response(response)


@mcp.tool(
    name="illustrator_set_paragraph_alignment",
    annotations={"title": "Set Paragraph Alignment", "readOnlyHint": False, "destructiveHint": False}
)
async def illustrator_set_paragraph_alignment(params: ParagraphAlignmentInput) -> str:
    """Set text alignment for selected text frames."""
    align_map = {
        "left": "Justification.LEFT",
        "center": "Justification.CENTER",
        "right": "Justification.RIGHT",
        "justify": "Justification.FULLJUSTIFY"
    }
    align_const = align_map.get(params.alignment.lower(), "Justification.LEFT")
    
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        
        var aligned = 0;
        for (var i = 0; i < sel.length; i++) {{
            if (sel[i].typename === "TextFrame") {{
                for (var j = 0; j < sel[i].paragraphs.length; j++) {{
                    sel[i].paragraphs[j].paragraphAttributes.justification = {align_const};
                }}
                aligned++;
            }}
        }}
        
        return JSON.stringify({{success: true, alignment: "{params.alignment}", framesAligned: aligned}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


# DISABLED: Tool limit reduction for Antigravity
# @mcp.tool(
#     name="illustrator_set_character_spacing",
#     annotations={"title": "Set Character Spacing", "readOnlyHint": False, "destructiveHint": False}
# )
async def illustrator_set_character_spacing(params: CharacterSpacingInput) -> str:
    """Set tracking/kerning for selected text."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        
        for (var i = 0; i < sel.length; i++) {{
            if (sel[i].typename === "TextFrame") {{
                sel[i].textRange.characterAttributes.tracking = {params.tracking};
            }}
        }}
        
        return JSON.stringify({{success: true, tracking: {params.tracking}}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)


# DISABLED: Tool limit reduction for Antigravity
# @mcp.tool(
#     name="illustrator_set_line_height",
#     annotations={"title": "Set Line Height", "readOnlyHint": False, "destructiveHint": False}
# )
async def illustrator_set_line_height(params: LineHeightInput) -> str:
    """Set leading (line spacing) for selected text."""
    script = f"""
    (function() {{
        var doc = app.activeDocument;
        var sel = doc.selection;
        if (!sel || sel.length === 0) throw new Error("No selection");
        
        for (var i = 0; i < sel.length; i++) {{
            if (sel[i].typename === "TextFrame") {{
                sel[i].textRange.characterAttributes.leading = {params.leading};
            }}
        }}
        
        return JSON.stringify({{success: true, leading: {params.leading}}});
    }})()
    """
    response = await execute_script(script)
    return format_response(response)
