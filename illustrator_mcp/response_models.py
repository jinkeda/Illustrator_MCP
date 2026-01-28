"""
Response models for ExtendScript tool outputs.

These models provide type-safe parsing of responses from basic Illustrator operations.
They complement the Task Protocol models in protocol.py by handling simpler tool responses.
"""

from typing import Optional, Literal, List
from pydantic import BaseModel, Field


# ==================== Basic Responses ====================

class OperationResult(BaseModel):
    """Generic success/failure response from any operation."""
    success: bool
    message: Optional[str] = None
    error: Optional[str] = None


# ==================== Document Responses ====================

class DocumentInfo(BaseModel):
    """Response from get_document_info."""
    name: str
    width: float
    height: float
    colorMode: Literal["RGB", "CMYK"]
    layerCount: int
    saved: bool


class DocumentCreated(BaseModel):
    """Response from create_document."""
    success: bool
    name: str
    width: float
    height: float


class DocumentOpened(BaseModel):
    """Response from open_document."""
    success: bool
    name: str
    path: str


# ==================== Export Responses ====================

class ExportResult(BaseModel):
    """Response from export_document."""
    success: bool
    path: str
    format: str


# ==================== Placement Responses ====================

class PlacementPosition(BaseModel):
    """Position information for placed items."""
    x: float
    y: float


class PlaceItemResult(BaseModel):
    """Response from import_image or place_file."""
    success: bool
    path: str
    linked: bool
    position: PlacementPosition
    width: float
    height: float


class EditablePlaceResult(BaseModel):
    """Response from place_file with embed_editable=True."""
    success: bool
    type: Literal["editable"]
    position: List[float]
    width: float
    height: float


# ==================== Linked Item Responses ====================

class EmbedResult(BaseModel):
    """Response from embed_placed_items."""
    success: bool
    embeddedCount: int


class UpdateLinkedResult(BaseModel):
    """Response from update_linked_items."""
    success: bool
    updatedCount: int
