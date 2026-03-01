"""
History (undo/redo/checkpoint) tool for Adobe Illustrator.

Extracted from documents.py for readability.
"""

from typing import Literal, Optional

from pydantic import Field

from illustrator_mcp.shared import mcp
from illustrator_mcp import templates
from illustrator_mcp.tools.base import execute_jsx_tool, ToolInputBase, TOOL_ANNOTATIONS
from illustrator_mcp.errors import make_envelope


class HistoryInput(ToolInputBase):
    """Input for undo/redo and named checkpoint operations."""
    action: Literal[
        "undo", "redo",
        "checkpoint_save", "checkpoint_restore",
        "checkpoint_list", "checkpoint_delete"
    ] = Field(default="undo", description="Action to perform")
    count: int = Field(default=1, description="Number of times to undo/redo", ge=1, le=100)
    name: Optional[str] = Field(
        default=None,
        description="Checkpoint name (required for save/restore/delete)",
        max_length=64
    )

    @classmethod
    def model_validate(cls, *args, **kwargs):
        instance = super().model_validate(*args, **kwargs)
        if instance.action.startswith("checkpoint_") and instance.action != "checkpoint_list":
            if not instance.name or not instance.name.strip():
                raise ValueError(f"{instance.action} requires a non-empty 'name'")
        return instance


async def _handle_checkpoint(params: HistoryInput) -> str:
    """Dispatch checkpoint actions to checkpoint.jsx functions."""
    action_map = {
        "checkpoint_save": "checkpointSave",
        "checkpoint_restore": "checkpointRestore",
        "checkpoint_list": "checkpointList",
        "checkpoint_delete": "checkpointDelete",
    }
    if params.action not in action_map:
        return make_envelope(ok=False, error=f"Unknown checkpoint action: {params.action}")

    jsx_fn = action_map[params.action]

    if params.action == "checkpoint_list":
        name_arg = ""
    else:
        escaped_name = params.name.replace("\\", "\\\\").replace('"', '\\"')
        name_arg = f'"{ escaped_name}", '

    script = templates.CHECKPOINT_ACTION.substitute(
        jsx_fn=jsx_fn,
        name_arg=name_arg,
    )

    return await execute_jsx_tool(
        script=script,
        command_type=params.action,
        tool_name="illustrator_history",
        params={"action": params.action, "name": params.name},
        includes=["polyfills", "checkpoint"]
    )


_HISTORY_NAME = "illustrator_history"


@mcp.tool(name=_HISTORY_NAME, annotations=TOOL_ANNOTATIONS[_HISTORY_NAME])
async def illustrator_history(params: HistoryInput) -> str:
    """Undo or redo actions in Illustrator.

    CONTRACT: readOnly=False, destructive=True, idempotent=False, openWorld=False

    WHEN TO USE:
      - Reverting mistakes (action='undo', count=N)
      - Restoring undone changes (action='redo')
      - Saving/restoring named checkpoints for recovery

    EXAMPLES:
      illustrator_history(action="undo", count=3)
      illustrator_history(action="checkpoint_save", name="before_boolean")
      illustrator_history(action="checkpoint_restore", name="before_boolean")
      illustrator_history(action="checkpoint_list")

    NOTES:
      - Checkpoints capture MCP-managed items only (those with @mcp:id)
      - checkpoint_restore is mutate-in-place; may require multiple undo to revert
      - undo/redo change document state (destructive)
    """
    # Dispatch checkpoint actions
    if params.action.startswith("checkpoint_"):
        return await _handle_checkpoint(params)

    # Original undo/redo logic
    if params.action not in ("undo", "redo"):
        return make_envelope(ok=False, error="Invalid action. Use 'undo' or 'redo'")
    
    template = templates.UNDO if params.action == "undo" else templates.REDO
    
    # For count > 1, we need to modify the script to loop
    if params.count > 1:
        script = templates.HISTORY_MULTI.substitute(
            action_method="undo" if params.action == "undo" else "redo",
            count=params.count,
            action_name=params.action
        )
    else:
        script = template
    
    return await execute_jsx_tool(
        script=script,
        command_type=params.action,
        tool_name="illustrator_history",
        params={"action": params.action, "count": params.count}
    )
