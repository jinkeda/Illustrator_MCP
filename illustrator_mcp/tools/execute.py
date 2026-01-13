"""
Core execute_script tool for Adobe Illustrator.

This module provides the base execute_script tool that sends raw JavaScript
to Illustrator. All specific tools in other modules use this internally.
"""

from pydantic import BaseModel, Field, ConfigDict
from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script, format_response


class ExecuteScriptInput(BaseModel):
    """Input for executing raw JavaScript in Illustrator."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    script: str = Field(
        ...,
        description="JavaScript/ExtendScript code to execute in Illustrator",
        min_length=1
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
    
    This is a low-level tool that allows executing any valid Illustrator
    JavaScript code. Use this for operations not covered by specific tools.
    
    Args:
        params: Contains the JavaScript code to execute:
            - script (str): Valid JavaScript/ExtendScript code
    
    Returns:
        str: JSON result from script execution or error message
    
    Examples:
        - "alert('Hello from Illustrator!')"
        - "app.activeDocument.pathItems.rectangle(0, 0, 100, 100)"
        - "app.activeDocument.layers[0].name"
    
    Note:
        The script runs in Illustrator's ExtendScript environment.
        Use app.activeDocument to access the current document.
        Results are returned as JSON when possible.
    
    Common Objects:
        - app: Application object
        - app.activeDocument: Current document
        - app.documents: All open documents
        - RGBColor, CMYKColor: Color objects
    """
    response = await execute_script(params.script)
    return format_response(response)
