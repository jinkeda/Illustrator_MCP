"""
Task Protocol Models for Illustrator MCP.

Defines Pydantic models for the standardized task payload/report protocol.
"""

from typing import Literal, Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ItemRef(BaseModel):
    """Stable item reference for locating errors."""
    layerPath: str = Field(..., description="Layer path: 'Layer 1/Group A'")
    indexPath: List[int] = Field(default_factory=list, description="Index path: [0, 2, 5]")
    itemId: Optional[str] = Field(None, description="Unique ID written into note")
    itemName: Optional[str] = Field(None, description="item.name")
    itemType: str = Field(..., description="PathItem, TextFrame, etc.")


class TimingInfo(BaseModel):
    """Stage timings."""
    collect_ms: float = Field(0, description="Target collection time")
    compute_ms: float = Field(0, description="Computation/validation time")
    apply_ms: float = Field(0, description="Apply/modification time")
    export_ms: Optional[float] = Field(None, description="Export time (if applicable)")
    total_ms: float = Field(0, description="Total time")


class TaskWarning(BaseModel):
    """Warning information."""
    stage: Literal["collect", "compute", "apply", "export"]
    message: str
    itemRef: Optional[ItemRef] = None
    suggestion: Optional[str] = None


class TaskError(BaseModel):
    """Error information with full context."""
    stage: Literal["collect", "compute", "apply", "export"]
    code: str = Field(..., description="ERROR_NO_SELECTION, ERROR_INVALID_BOUNDS, etc.")
    message: str
    itemRef: Optional[ItemRef] = None
    line: Optional[int] = Field(None, description="ExtendScript error line number")
    reproduce: Optional[str] = Field(None, description="Reproduction steps")


class TaskStats(BaseModel):
    """Statistics."""
    itemsProcessed: int = 0
    itemsModified: int = 0
    itemsSkipped: int = 0


class TaskReport(BaseModel):
    """Standard task report."""
    ok: bool = Field(..., description="Whether the task succeeded")
    stats: TaskStats = Field(default_factory=TaskStats)
    timing: TimingInfo = Field(default_factory=TimingInfo)
    warnings: List[TaskWarning] = Field(default_factory=list)
    errors: List[TaskError] = Field(default_factory=list)
    artifacts: Optional[Dict[str, Any]] = Field(
        None,
        description="Task artifacts: {exportedPath: '/path/to/file.svg'}"
    )
    trace: Optional[List[str]] = Field(
        None,
        description="Detailed execution trace (only when options.trace=true)"
    )


class TaskPayload(BaseModel):
    """Standard task payload."""
    task: str = Field(..., description="Task type: draw_shapes, apply_styles, query_items")
    version: str = Field(default="2.1.0", description="Protocol version")
    targets: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Target selector: {type: 'selection'} | {type: 'layer', layer: 'Layer 1'} | {type: 'query', ...}"
    )
    params: Dict[str, Any] = Field(default_factory=dict, description="Task parameters")
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Options: {dryRun: true, timeout: 60, trace: true, assignIds: false}"
    )
