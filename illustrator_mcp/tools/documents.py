"""
Document operation tools for Adobe Illustrator.

This module is a thin facade that re-exports all document-related tools
from sub-modules. External code can continue to import from here.

Sub-modules:
  _models.py  — shared Pydantic models and enums
  _export.py  — illustrator_export_document
  _history.py — illustrator_history (undo/redo/checkpoints)
  _place.py   — illustrator_place_file, illustrator_set_reference

The document CRUD tool (illustrator_document) remains here since it is
small and has no shared dependencies.
"""

import json
import logging

from pydantic import Field

from illustrator_mcp.shared import mcp
from illustrator_mcp import templates
from illustrator_mcp.tools.base import execute_jsx_tool, TOOL_ANNOTATIONS
from illustrator_mcp.utils import escape_path_for_jsx
# Re-export for backward-compat: tests patch these at
# "illustrator_mcp.tools.documents.execute_script_with_context"
from illustrator_mcp.proxy_client import (            # noqa: F401
    execute_script_with_context,
    format_envelope,
)

logger = logging.getLogger(__name__)


# ── Re-exports from sub-modules ──────────────────────────────────────
# Importing triggers @mcp.tool() registration for each tool.

from illustrator_mcp.tools._models import (          # noqa: F401, E402
    ExportFormat,
    DocumentInput,
    ExportDocumentInput,
)
from illustrator_mcp.tools._export import (           # noqa: F401, E402
    illustrator_export_document,
)
from illustrator_mcp.tools._history import (          # noqa: F401, E402
    HistoryInput,
    illustrator_history,
)
from illustrator_mcp.tools._place import (            # noqa: F401, E402
    PlaceFileInput,
    SetReferenceInput,
    illustrator_place_file,
    illustrator_set_reference,
    _place_item_impl,
    _extract_dominant_colors,
    _SET_REFERENCE_JSX,
    _REFERENCE_LAYER_NAME,
    _TRACEABLE_EXTENSIONS,
)


# ── Document CRUD (kept here — small, no shared deps) ────────────────

_DOC_NAME = "illustrator_document"


@mcp.tool(name=_DOC_NAME, annotations=TOOL_ANNOTATIONS[_DOC_NAME])
async def illustrator_document(params: DocumentInput) -> str:
    """Create, open, save, or close an Illustrator document.

    CONTRACT: readOnly=False, destructive=True, idempotent=False, openWorld=True

    WHEN TO USE:
      - Starting a new illustration (action='create')
      - Opening an existing .ai file (action='open', file_path required)
      - Saving current work (action='save', file_path for save-as)
      - Closing the active document (action='close')

    EXAMPLES:
      illustrator_document(action="create", width=800, height=600, color_mode="RGB")
      illustrator_document(action="open", file_path="C:/art/figure.ai")
      illustrator_document(action="save", file_path="C:/art/figure_v2.ai")
      illustrator_document(action="close", save_before_close=True)

    NOTES:
      - close without save_before_close=True discards unsaved changes
      - open/save interact with the filesystem (openWorld)
    """
    action = params.action

    if action == "create":
        color_space = "RGB" if params.color_mode.upper() == "RGB" else "CMYK"
        name = params.name or "Untitled"
        title_line = f'preset.title = "{name}";'
        script = templates.DOC_CREATE.substitute(
            width=params.width,
            height=params.height,
            color_space=color_space,
            title_line=title_line,
        )
        return await execute_jsx_tool(
            script=script,
            command_type="create_document",
            tool_name="illustrator_document",
            params={"action": action, "width": params.width, "height": params.height,
                    "color_mode": params.color_mode, "name": name}
        )
    elif action == "open":
        path = escape_path_for_jsx(params.file_path)
        script = templates.DOC_OPEN.substitute(path=path)
        return await execute_jsx_tool(
            script=script,
            command_type="open_document",
            tool_name="illustrator_document",
            params={"action": action, "file_path": params.file_path}
        )
    elif action == "save":
        if params.file_path:
            path = escape_path_for_jsx(params.file_path)
            script = templates.DOC_SAVE_AS.substitute(path=path)
        else:
            script = templates.DOC_SAVE
        return await execute_jsx_tool(
            script=script,
            command_type="save_document",
            tool_name="illustrator_document",
            params={"action": action, "file_path": params.file_path}
        )
    elif action == "close":
        save_opt = "SaveOptions.SAVECHANGES" if params.save_before_close else "SaveOptions.DONOTSAVECHANGES"
        script = templates.DOC_CLOSE.substitute(save_option=save_opt)
        return await execute_jsx_tool(
            script=script,
            command_type="close_document",
            tool_name="illustrator_document",
            params={"action": action, "save_before_close": params.save_before_close}
        )
