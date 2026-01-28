"""
Base utilities for tool implementations.

Provides common patterns for JSX tool execution to reduce boilerplate.
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from illustrator_mcp.proxy_client import (
    execute_script_with_context,
    format_response,
)
from illustrator_mcp.libraries import inject_libraries


# ==================== Shared Pydantic Base ====================

class ToolInputBase(BaseModel):
    """Base class for all tool input models.
    
    Provides shared configuration:
    - str_strip_whitespace: Auto-strip whitespace from string fields
    """
    model_config = ConfigDict(str_strip_whitespace=True)


async def execute_jsx_tool(
    script: str,
    command_type: str,
    tool_name: str,
    params: Optional[dict[str, Any]] = None,
    includes: Optional[list[str]] = None
) -> str:
    """
    Standard JSX tool execution wrapper.
    
    Reduces boilerplate in each tool from ~10 lines to 1-2 lines.
    
    Args:
        script: JavaScript/ExtendScript code to execute
        command_type: Type of command (e.g., "create_document")
        tool_name: Name of the MCP tool (e.g., "illustrator_create_document")
        params: Parameters passed to the tool (for debugging)
        includes: Optional list of libraries to inject (e.g., ["geometry", "layout"])
    
    Returns:
        Formatted string for MCP tool response
    
    Example:
        @mcp.tool(name="illustrator_my_tool")
        async def illustrator_my_tool(params: MyInput) -> str:
            script = f'''
            (function() {{
                // ... JavaScript code ...
            }})()
            '''
            return await execute_jsx_tool(
                script=script,
                command_type="my_operation",
                tool_name="illustrator_my_tool",
                params={"key": params.key}
            )
    """
    # Inject libraries if requested
    if includes:
        script = inject_libraries(script, includes)
    
    # Execute with context
    response = await execute_script_with_context(
        script=script,
        command_type=command_type,
        tool_name=tool_name,
        params=params or {}
    )
    
    # Format and return
    return format_response(response)
