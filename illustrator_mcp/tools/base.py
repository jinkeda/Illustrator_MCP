"""
Base utilities for tool implementations.

Provides common patterns for JSX tool execution to reduce boilerplate.
Also contains canonical constants (SSOT) for tool annotations, coordinate
system, abstraction ladder, and docstring schema.
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from illustrator_mcp.proxy_client import (
    execute_script_with_context,
    format_envelope,
)


# ══════════════════════════════════════════════════════════════════
# P1 + P2: Canonical Annotation Registry (SSOT)
#
# Semantic definitions (P1):
#   readOnlyHint    — True if tool cannot mutate Illustrator state
#                     AND cannot write to filesystem/network.
#   destructiveHint — True if tool can delete/overwrite/close/replace,
#                     OR is state-changing, OR failure may lose work.
#   idempotentHint  — True if repeated identical call yields same
#                     resulting state (doc + filesystem) or is a no-op.
#   openWorldHint   — True if tool can interact with resources outside
#                     document/app state (filesystem, network, OS).
#
# P6: Hints reflect worst-case capability over all actions/inputs.
# ══════════════════════════════════════════════════════════════════

TOOL_ANNOTATIONS: dict[str, dict] = {
    "illustrator_execute_script":  {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False, "openWorldHint": True },
    "illustrator_execute_task":    {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False, "openWorldHint": False},
    "illustrator_path_boolean":    {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False, "openWorldHint": False},
    "illustrator_document":        {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False, "openWorldHint": True },
    "illustrator_export_document": {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False, "openWorldHint": True },
    "illustrator_history":         {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False, "openWorldHint": False},
    "illustrator_place_file":      {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": False, "openWorldHint": True },
    "illustrator_set_reference":   {"readOnlyHint": False, "destructiveHint": True,  "idempotentHint": True,  "openWorldHint": True },
    "illustrator_get_document":    {"readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True,  "openWorldHint": False},
    "illustrator_query_items":     {"readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True,  "openWorldHint": False},
    "illustrator_preflight_check": {"readOnlyHint": True,  "destructiveHint": False, "idempotentHint": True,  "openWorldHint": False},
    "illustrator_path_import_svg": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
}

_REQUIRED_HINT_KEYS = {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}


# ══════════════════════════════════════════════════════════════════
# P3: Docstring Schema — allowed section headers
# ══════════════════════════════════════════════════════════════════

ALLOWED_DOCSTRING_SECTIONS = frozenset({
    "WHEN TO USE:",
    "KEY CONCEPTS:",
    "DECISION RULES:",
    "COORDINATE SYSTEM:",
    "ABSTRACTION LADDER:",
    "PIPELINE:",
    "TARGET SELECTORS:",
    "OPTIONS:",
    "EXAMPLES:",
    "NOTES:",
    "SAFETY:",
})

# Characters banned from docstrings (box-drawing)
_BANNED_CHARS = set("═║─│┌┐└┘├┤┬┴┼╔╗╚╝╠╣╦╩╬")


# ══════════════════════════════════════════════════════════════════
# P4: Canonical Coordinate System Block
# ══════════════════════════════════════════════════════════════════

COORDINATE_SYSTEM_BLOCK = """\
COORDINATE SYSTEM:
  - API coordinates use top-left origin with y increasing downward (screen space)
  - ExtendScript expects Y-up internally; use -y when calling Illustrator DOM methods
  - Units: points (1 pt = 1/72 inch)
  - Example: to place at visual position (100, 200), use position = [100, -200]"""


# ══════════════════════════════════════════════════════════════════
# P5: Abstraction Ladder (uses registry names only)
# ══════════════════════════════════════════════════════════════════

ABSTRACTION_LADDER = """\
ABSTRACTION LADDER — prefer higher levels before using raw script:
  Level 5 — illustrator_path_boolean: boolean sculpt (unite/subtract/intersect/xor)
  Level 4 — illustrator_execute_task + element_create_batch: batch-create identical shapes
  Level 3 — illustrator_path_import_svg: import SVG d-string paths
  Level 2 — illustrator_execute_task + element_create: smooth curves, handles, mirror
  Level 1 — illustrator_execute_script (THIS tool): raw ExtendScript"""


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
    # Execute with context (library injection handled by pipeline)
    response = await execute_script_with_context(
        script=script,
        command_type=command_type,
        tool_name=tool_name,
        params=params or {},
        includes=includes
    )

    # Return standardized envelope for consistent API contract
    diagnostics = {
        "tool": tool_name,
        "command": command_type,
        "includes": includes or []
    }
    return format_envelope(response, context=command_type, diagnostics=diagnostics)
