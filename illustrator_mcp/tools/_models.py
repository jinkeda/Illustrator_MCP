"""
Shared Pydantic models and enums for document tools.

Extracted from documents.py to avoid circular imports between sub-modules.
"""

from enum import Enum
from typing import Literal, Optional

from illustrator_mcp.tools.base import MutationInputBase
from pydantic import Field, field_validator

from illustrator_mcp.tools.base import ToolInputBase

from pydantic import BaseModel


# ── Shared appearance models ──────────────────────────────────────────


class ColorRGB(BaseModel):
    """RGB color with validated 0–255 channels."""
    r: int = Field(..., ge=0, le=255, description="Red channel (0-255)")
    g: int = Field(..., ge=0, le=255, description="Green channel (0-255)")
    b: int = Field(..., ge=0, le=255, description="Blue channel (0-255)")


class StrokeSpec(BaseModel):
    """Stroke color with optional width."""
    r: int = Field(..., ge=0, le=255, description="Red channel (0-255)")
    g: int = Field(..., ge=0, le=255, description="Green channel (0-255)")
    b: int = Field(..., ge=0, le=255, description="Blue channel (0-255)")
    width: Optional[float] = Field(
        default=None, gt=0,
        description="Stroke width in points. None = use pipeline default."
    )


class ExportFormat(str, Enum):
    """Export file formats."""
    PNG = "png"
    JPG = "jpg"
    SVG = "svg"
    PDF = "pdf"


class DocumentInput(MutationInputBase):
    """Unified input for document create/open/save/close operations."""
    action: Literal["create", "open", "save", "close", "list", "activate"] = Field(
        ..., description="Action: create/open/activate sets the shared pin. list returns live tokens without changing the pin. save/close require the expected token or shared pin."
    )
    # create params
    width: float = Field(default=800, description="Width in points (create)", ge=1, le=16383)
    height: float = Field(default=600, description="Height in points (create)", ge=1, le=16383)
    name: Optional[str] = Field(default=None, description="Document name (create)", max_length=255)
    color_mode: str = Field(default="RGB", description="RGB or CMYK (create)")
    # open/save params
    file_path: Optional[str] = Field(default=None, description="File path (required for open, optional for save-as)")
    # close params
    save_before_close: bool = Field(default=False, description="Save before closing (close)")

    def model_post_init(self, __context) -> None:
        """Validate action-specific required fields."""
        if self.action == "open" and not self.file_path:
            raise ValueError("file_path is required for action='open'")


class ExportDocumentInput(MutationInputBase):
    """Input for exporting a document."""
    file_path: str = Field(..., description="Full output path with extension (e.g. C:/output/figure.png)", min_length=1)

    @field_validator("file_path")
    @classmethod
    def validate_output_path(cls, value):
        import os
        from pathlib import PureWindowsPath
        if "\x00" in value:
            raise ValueError("Export path must not contain NUL characters")
        if os.name == "nt":
            path = PureWindowsPath(value)
            for part in path.parts:
                if part == path.anchor or part in (".", ".."):
                    continue
                if (any(c in part for c in '<>:"|?*') or part.endswith((" ", "."))
                        or PureWindowsPath(part).is_reserved()):
                    raise ValueError("Invalid or reserved Windows export path component: " + part)
        return value
    format: ExportFormat = Field(default=ExportFormat.PNG, description="PNG or JPG. SVG and PDF are parseable only for explicit refusal: native export cannot safely preserve source association/state. Use a separate working copy for manual SVG/PDF export.")
    scale: float = Field(default=1.0, description="Scale factor", ge=0.1, le=10.0)
    artboard_only: bool = Field(default=False, description="Clip export to artboard bounds")
    artboard_index: Optional[int] = Field(default=None, ge=0, description="Artboard index (None = active artboard)")
    return_image: bool = Field(default=False, description="Return image bytes for Claude visualization (PNG/JPG only)")
    # Illustrator asks before replacing a file, and that question is a modal
    # dialog on the host thread. Nothing the server does afterwards can
    # dismiss it: the call times out while Illustrator sits waiting, and a
    # human has to click. So the decision is made here, before dispatch,
    # where a filesystem check costs nothing and cannot block.
    overwrite: Literal["replace", "fail", "version"] = Field(
        default="replace",
        description=(
            "What to do when file_path already exists. 'replace' (default) "
            "retains a sibling backup until known completion, so Illustrator never asks. "
            "'fail' refuses without writing or dispatching. 'version' writes "
            "alongside it as name-2.ext, name-3.ext and so on."
        ),
    )
