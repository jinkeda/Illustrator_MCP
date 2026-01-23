"""
Task Protocol Models for Illustrator MCP v2.3.

Defines Pydantic models for the standardized task payload/report protocol.
Includes:
- Standardized error codes (V/R/S categories)
- Compound target selectors with ordering
- Stable references (locator/identity/tag separation)
- Safe retry semantics with idempotency tracking
"""

from enum import Enum
from typing import Literal, Optional, List, Dict, Any, Union, Annotated
from pydantic import BaseModel, Field, model_validator


# ==================== Error Codes ====================

class ErrorCode(str, Enum):
    """
    Standardized error codes matching task_executor.jsx.
    
    Categories:
    - V (Validation): Fail before execution
    - R (Runtime): Fail during execution
    - S (System): Illustrator/environment issues
    """
    # Validation errors (fail before execution)
    V_NO_DOCUMENT = "V001"
    V_NO_SELECTION = "V002"
    V_INVALID_PAYLOAD = "V003"
    V_INVALID_TARGETS = "V004"
    V_UNKNOWN_TARGET_TYPE = "V005"
    V_MISSING_REQUIRED_PARAM = "V006"
    V_INVALID_PARAM_TYPE = "V007"
    V_SCHEMA_MISMATCH = "V008"
    
    # Runtime errors (fail during execution)
    R_COLLECT_FAILED = "R001"
    R_COMPUTE_FAILED = "R002"
    R_APPLY_FAILED = "R003"
    R_ITEM_OPERATION_FAILED = "R004"
    R_TIMEOUT = "R005"
    R_OUT_OF_BOUNDS = "R006"
    
    # System errors
    S_APP_ERROR = "S001"
    S_SCRIPT_ERROR = "S002"
    S_IO_ERROR = "S003"
    S_MEMORY_ERROR = "S004"


# ==================== Ordering & Filtering ====================

class OrderBy(str, Enum):
    """Deterministic ordering modes for target results."""
    Z_ORDER = "zOrder"              # Illustrator stacking order (back to front)
    Z_ORDER_REVERSE = "zOrderReverse"  # Front to back
    READING = "reading"             # Left-to-right, top-to-bottom (row-major)
    COLUMN = "column"               # Top-to-bottom, left-to-right (column-major)
    NAME = "name"                   # Alphabetical by item.name
    POSITION_X = "positionX"        # Left edge ascending
    POSITION_Y = "positionY"        # Top edge ascending (remember Y is negative!)
    AREA = "area"                   # Smallest to largest


class ExcludeFilter(BaseModel):
    """Filter to exclude items from results."""
    locked: bool = Field(default=False, description="Exclude locked items")
    hidden: bool = Field(default=False, description="Exclude hidden items")
    guides: bool = Field(default=False, description="Exclude guides")
    clipped: bool = Field(default=False, description="Exclude items inside clipping masks")


# ==================== Target Selectors ====================

class SelectionTarget(BaseModel):
    """Target: current selection."""
    type: Literal["selection"] = "selection"


class LayerTarget(BaseModel):
    """Target: all items on a layer."""
    type: Literal["layer"] = "layer"
    layer: str = Field(..., min_length=1, description="Layer name")
    recursive: bool = Field(default=False)


class AllTarget(BaseModel):
    """Target: all items in document."""
    type: Literal["all"] = "all"
    recursive: bool = Field(default=False)


class QueryTarget(BaseModel):
    """Target: items matching query filters."""
    type: Literal["query"] = "query"
    itemType: Optional[str] = Field(None, description="PathItem, TextFrame, etc.")
    pattern: Optional[str] = Field(None, description="Name pattern with * wildcard")
    layer: Optional[str] = None
    recursive: bool = Field(default=False)
    
    @model_validator(mode='after')
    def require_at_least_one_filter(self):
        if not self.itemType and not self.pattern and not self.layer:
            raise ValueError("Query target requires at least one filter (itemType, pattern, or layer)")
        return self


# Compound selector
SimpleTarget = Union[SelectionTarget, LayerTarget, AllTarget, QueryTarget]


class CompoundTarget(BaseModel):
    """
    Compound target selector with boolean logic.
    
    Examples:
        # Union of multiple sources
        {"type": "compound", "anyOf": [{"type": "layer", "layer": "Panels"}, {"type": "selection"}]}
        
        # With exclusions
        {"type": "compound", "anyOf": [...], "exclude": {"locked": true, "hidden": true}}
    """
    type: Literal["compound"] = "compound"
    anyOf: List[SimpleTarget] = Field(..., min_length=1, description="Union of targets")
    exclude: Optional[ExcludeFilter] = Field(default=None, description="Exclusion filter")


class TargetSelector(BaseModel):
    """
    Complete target selector with ordering.
    
    The 'target' field can be a simple selector or compound.
    The 'orderBy' field ensures deterministic result ordering.
    """
    target: Annotated[
        Union[SelectionTarget, LayerTarget, AllTarget, QueryTarget, CompoundTarget],
        Field(discriminator='type')
    ]
    orderBy: OrderBy = Field(
        default=OrderBy.Z_ORDER,
        description="Result ordering (critical for layout reproducibility)"
    )
    exclude: Optional[ExcludeFilter] = Field(
        default=None,
        description="Global exclusion filter (applied after target resolution)"
    )


# ==================== Stable References ====================

class IdSource(str, Enum):
    """Source of item identity."""
    NONE = "none"       # No identity assigned
    NOTE = "note"       # ID stored in item.note field
    NAME = "name"       # ID derived from item.name


class IdPolicy(str, Enum):
    """Policy for assigning identities."""
    NONE = "none"                 # Never assign IDs (default)
    OPT_IN = "opt_in"             # Only assign when explicitly requested
    ALWAYS = "always"             # Always assign (with conflict detection)
    PRESERVE = "preserve"         # Keep existing IDs, don't assign new ones


class ItemLocator(BaseModel):
    """
    Positional locator (volatile - changes when structure changes).
    Use for one-shot operations where you don't need to re-find the item.
    """
    layerPath: str = Field(..., description="Layer path: 'Layer 1/Group A'")
    indexPath: List[int] = Field(default_factory=list, description="Index path: [0, 2, 5]")


class ItemIdentity(BaseModel):
    """
    Stable identity (mutates document when assigned).
    Use for operations that need to re-find items across sessions.
    """
    itemId: Optional[str] = Field(None, description="Unique ID (e.g., 'mcp_1705834200_42')")
    idSource: IdSource = Field(default=IdSource.NONE, description="Where the ID is stored")


class ItemTags(BaseModel):
    """
    User-controlled tags (parsed from name or note).
    Use for semantic selection without forcing UUID assignment.
    
    Example: item.name = "Panel A @mcp:role=header @mcp:order=1"
    Parsed as: {role: "header", order: "1"}
    """
    tags: Dict[str, str] = Field(default_factory=dict, description="Parsed @mcp:key=value pairs")


class ItemRef(BaseModel):
    """
    Complete item reference with separated concerns.
    
    - locator: Volatile positional reference
    - identity: Stable ID (opt-in, mutates document)
    - tags: User-controlled semantic tags
    - metadata: Item type and name for debugging
    """
    locator: ItemLocator = Field(..., description="Positional locator")
    identity: ItemIdentity = Field(default_factory=ItemIdentity, description="Stable identity")
    tags: ItemTags = Field(default_factory=ItemTags, description="User-defined tags")
    
    # Metadata (read-only, for debugging)
    itemType: str = Field(..., description="PathItem, TextFrame, etc.")
    itemName: Optional[str] = Field(None, description="item.name value")


# Legacy ItemRef for backward compatibility
class ItemRefLegacy(BaseModel):
    """
    Legacy item reference (for backward compatibility).
    
    .. deprecated:: 2.3.0
        Use :class:`ItemRef` with locator/identity/tags structure instead.
        Will be removed in v3.0.
    """
    layerPath: str = Field(..., description="Layer path: 'Layer 1/Group A'")
    indexPath: List[int] = Field(default_factory=list, description="Index path: [0, 2, 5]")
    itemId: Optional[str] = Field(None, description="Unique ID written into note")
    itemName: Optional[str] = Field(None, description="item.name")
    itemType: str = Field(..., description="PathItem, TextFrame, etc.")


# ==================== Retry Semantics ====================

class Idempotency(str, Enum):
    """Idempotency classification for operations."""
    SAFE = "safe"           # Safe to retry (query, dry-run)
    UNKNOWN = "unknown"     # Idempotency not proven
    UNSAFE = "unsafe"       # Definitely not idempotent (e.g., create, delete)


class RetryableStage(str, Enum):
    """Stages that can be retried."""
    COLLECT = "collect"
    COMPUTE = "compute"
    # NOTE: 'apply' is NOT in this list - never auto-retry apply


class RetryPolicy(BaseModel):
    """Stage-specific retry configuration."""
    maxAttempts: int = Field(default=3, ge=1, le=5, description="Max retry attempts")
    retryableStages: List[RetryableStage] = Field(
        default=[RetryableStage.COLLECT],
        description="Which stages can be retried (default: collect only)"
    )
    retryOnCodes: List[str] = Field(
        default=["R001", "R002"],  # COLLECT_FAILED, COMPUTE_FAILED
        description="Error codes that trigger retry"
    )
    requireIdempotent: bool = Field(
        default=True,
        description="Only retry if operation is marked idempotent"
    )


class RetryInfo(BaseModel):
    """Retry execution details."""
    attempts: int = Field(..., description="Total attempts made")
    succeeded: bool
    retriedStages: List[str] = Field(default_factory=list, description="Stages that were retried")
    idempotency: Idempotency = Field(default=Idempotency.UNKNOWN)


# ==================== Timing & Stats ====================

class TimingInfo(BaseModel):
    """Stage timings."""
    collect_ms: float = Field(0, description="Target collection time")
    compute_ms: float = Field(0, description="Computation/validation time")
    apply_ms: float = Field(0, description="Apply/modification time")
    export_ms: Optional[float] = Field(None, description="Export time (if applicable)")
    total_ms: float = Field(0, description="Total time")


class TaskStats(BaseModel):
    """Statistics."""
    itemsProcessed: int = 0
    itemsModified: int = 0
    itemsSkipped: int = 0


# ==================== Warnings & Errors ====================

class TaskWarning(BaseModel):
    """Warning information."""
    stage: Literal["validate", "collect", "compute", "apply", "export"]
    message: str
    itemRef: Optional[ItemRef] = None
    suggestion: Optional[str] = None


class TaskError(BaseModel):
    """Error information with full context."""
    stage: Literal["validate", "collect", "compute", "apply", "export"]
    code: str = Field(..., description="Error code: V001-V008, R001-R006, S001-S004")
    message: str
    itemRef: Optional[ItemRef] = None
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error context")


# ==================== Task Options ====================

class TaskOptions(BaseModel):
    """Task execution options."""
    dryRun: bool = Field(default=False, description="Preview changes without applying")
    trace: bool = Field(default=False, description="Include execution trace")
    idPolicy: IdPolicy = Field(default=IdPolicy.NONE, description="ID assignment policy")
    timeout: int = Field(default=30, ge=1, le=300, description="Timeout in seconds")
    retry: Optional[RetryPolicy] = Field(default=None, description="Retry policy (null = no retry)")
    idempotency: Idempotency = Field(
        default=Idempotency.UNKNOWN,
        description="Caller-declared idempotency (affects retry behavior)"
    )


# ==================== Task Payload & Report ====================

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
    retryInfo: Optional[RetryInfo] = Field(
        None,
        description="Present if retry was attempted"
    )


class TaskPayload(BaseModel):
    """Standard task payload."""
    task: str = Field(..., description="Task type: draw_shapes, apply_styles, query_items")
    version: str = Field(default="2.3.1", description="Protocol version")
    targets: Optional[Union[TargetSelector, Dict[str, Any]]] = Field(
        default=None,
        description="Target selector (structured or legacy dict)"
    )
    params: Dict[str, Any] = Field(default_factory=dict, description="Task parameters")
    options: TaskOptions = Field(default_factory=TaskOptions)


# ==================== Output Formatting ====================

def format_task_report(report: TaskReport, task_name: str) -> str:
    """
    Format a TaskReport as human-readable output.
    
    Provides consistent formatting for all Task Protocol tools (execute_task, query_items, etc.)
    
    Args:
        report: The TaskReport to format
        task_name: Name/description of the task for the header
        
    Returns:
        Human-readable formatted string
    """
    status = "✓" if report.ok else "✗"
    lines = [f"{status} Task: {task_name}"]
    
    # Timing
    timing = report.timing
    lines.append(f"  Timing: collect={timing.collect_ms:.0f}ms, "
                 f"compute={timing.compute_ms:.0f}ms, "
                 f"apply={timing.apply_ms:.0f}ms")
    
    # Stats
    stats = report.stats
    lines.append(f"  Stats: {stats.itemsProcessed} processed, "
                 f"{stats.itemsModified} modified, "
                 f"{stats.itemsSkipped} skipped")
    
    # Warnings
    if report.warnings:
        lines.append(f"  ⚠ Warnings ({len(report.warnings)}):")
        for w in report.warnings:
            lines.append(f"    [{w.stage}] {w.message}")
    
    # Errors
    if report.errors:
        lines.append(f"  ✗ Errors ({len(report.errors)}):")
        for e in report.errors:
            loc = ""
            if e.itemRef:
                loc = f" at {e.itemRef.locator.layerPath}[{e.itemRef.locator.indexPath}]"
            lines.append(f"    [{e.stage}] {e.code}: {e.message}{loc}")
    
    # Trace
    if report.trace:
        lines.append("  Trace:")
        for t in report.trace:
            lines.append(f"    {t}")
    
    return "\n".join(lines)

