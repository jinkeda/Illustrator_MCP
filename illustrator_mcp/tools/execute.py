"""
Core execute_script tool for Adobe Illustrator.

This is the PRIMARY tool for interacting with Illustrator.
Following the "Scripting First" pattern (like blender-mcp), most operations
should be done via this tool rather than specialized atomic tools.
"""

import logging
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response

# Set up logging for telemetry
logger = logging.getLogger("illustrator_mcp")


def inject_libraries(script: str, includes: List[str]) -> str:
    """Prepend standard library code to a script.
    
    Args:
        script: The user's ExtendScript code
        includes: List of library names ["geometry", "selection", "layout"]
    
    Returns:
        Combined script with libraries prepended
    
    Raises:
        ValueError: If a requested library file is not found
    """
    if not includes:
        return script
        
    resources_dir = Path(__file__).parent.parent / "resources" / "scripts"
    library_code = []
    
    for lib_name in includes:
        lib_path = resources_dir / f"{lib_name}.jsx"
        if not lib_path.exists():
            raise ValueError(f"Library not found: {lib_name}.jsx (looked in {resources_dir})")
        library_code.append(lib_path.read_text(encoding="utf-8"))
    
    return "\n".join(library_code) + "\n" + script



class ExecuteScriptInput(BaseModel):
    """Input for executing raw JavaScript in Illustrator."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    script: str = Field(
        ...,
        description="JavaScript/ExtendScript code to execute in Illustrator",
        min_length=1
    )
    
    description: str = Field(
        default="",
        description="Brief description of what the script does (e.g., 'Draw graphene lattice', 'Add axis labels'). Shown in CEP panel log for debugging."
    )
    
    includes: Optional[List[str]] = Field(
        default=None,
        description="List of standard libraries to inject (e.g., ['geometry', 'selection', 'layout'])"
    )


@mcp.tool(
    name="illustrator_execute_script",
    annotations={
        "title": "Execute JavaScript in Illustrator",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False
    }
)
async def illustrator_execute_script(params: ExecuteScriptInput) -> str:
    """
    Execute raw JavaScript/ExtendScript code in Adobe Illustrator.
    
    This is the PRIMARY tool for all Illustrator operations. Use get_scripting_reference
    for syntax help if needed.
    
    COORDINATE SYSTEM:
    - Origin: Top-left of artboard
    - Y-axis: NEGATIVE downward. Use -y for visual y positions.
    - Units: Points (1 pt = 1/72 inch)
    
    COMMON OPERATIONS:
    
    Shapes:
    - Rectangle: doc.pathItems.rectangle(top, left, width, height)
    - Ellipse: doc.pathItems.ellipse(top, left, width, height)
    - Line: var p = doc.pathItems.add(); p.setEntirePath([[x1,-y1], [x2,-y2]])
    
    Colors:
    - var c = new RGBColor(); c.red=255; c.green=0; c.blue=0;
    - shape.fillColor = c; shape.strokeColor = c;
    
    Text:
    - var tf = doc.textFrames.add(); tf.contents = "text"; tf.position = [x, -y];
    
    Selection:
    - var sel = doc.selection; // Array of selected items
    - item.selected = true; // Select an item
    
    Args:
        params.script: Valid ExtendScript code to execute
    
    Returns:
        JSON result from script execution, or error details if failed
    
    Example:
        // Draw a red rectangle
        var doc = app.activeDocument;
        var rect = doc.pathItems.rectangle(-100, 50, 200, 100);
        var c = new RGBColor(); c.red = 255; c.green = 0; c.blue = 0;
        rect.fillColor = c;
    
    IMPORTANT: Always use -y for Y coordinates when positioning objects.
    Call get_scripting_reference for more detailed syntax examples.
    """
    # Log script execution for telemetry
    script_len = len(params.script)
    desc = params.description.strip() if params.description else None
    
    # Inject standard libraries if requested
    final_script = params.script
    if params.includes:
        try:
            final_script = inject_libraries(params.script, params.includes)
            logger.info(f"Injected libraries: {params.includes}")
        except ValueError as e:
            return f"Error importing libraries: {str(e)}"
    
    # Create a descriptive command_type for CEP panel
    # Priority: description > script snippet
    if desc:
        command_type = desc[:50]  # Limit length for display
    else:
        # Extract first meaningful line from script as fallback
        lines = [l.strip() for l in params.script.split('\n') if l.strip() and not l.strip().startswith('//')]
        preview = lines[0][:40] if lines else "script"
        command_type = f"script: {preview}..."
    
    logger.info(f"execute_script: {command_type} ({script_len} chars)")
    
    try:
        response = await execute_script_with_context(
            script=final_script,
            command_type=command_type,
            tool_name="illustrator_execute_script",
            params={"description": desc or "raw script", "length": script_len}
        )
        
        # Log errors for debugging
        result = format_response(response)
        if "error" in result.lower() or "eval error" in result.lower():
            logger.warning(f"Script error: {result[:200]}")
        
        return result
        
    except Exception as e:
        logger.error(f"Script execution failed: {str(e)}")
        raise
