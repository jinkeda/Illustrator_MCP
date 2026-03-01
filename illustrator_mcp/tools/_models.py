"""
Shared Pydantic models and enums for document tools.

Extracted from documents.py to avoid circular imports between sub-modules.
"""

from enum import Enum
from typing import Literal, Optional

from pydantic import Field

from illustrator_mcp.tools.base import ToolInputBase


class ExportFormat(str, Enum):
    """Export file formats."""
    PNG = "png"
    JPG = "jpg"
    SVG = "svg"
    PDF = "pdf"


class DocumentInput(ToolInputBase):
    """Unified input for document create/open/save/close operations."""
    action: Literal["create", "open", "save", "close"] = Field(
        ..., description="Action: 'create', 'open', 'save', or 'close'"
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


class ExportDocumentInput(ToolInputBase):
    """Input for exporting a document."""
    file_path: str = Field(..., description="Full output path with extension (e.g. C:/output/figure.png)", min_length=1)
    format: ExportFormat = Field(default=ExportFormat.PNG, description="Export format")
    scale: float = Field(default=1.0, description="Scale factor", ge=0.1, le=10.0)
    artboard_only: bool = Field(default=False, description="Clip export to artboard bounds")
    artboard_index: Optional[int] = Field(default=None, description="Artboard index (None = active artboard)")
    return_image: bool = Field(default=False, description="Return image bytes for Claude visualization (PNG/JPG only)")
