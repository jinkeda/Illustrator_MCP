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
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


# ==================== Error Codes ====================

from illustrator_mcp.errors import ErrorCode  # noqa: F401 — single source of truth
from illustrator_mcp.schemas.contracts import TASK_PROTOCOL_VERSION  # noqa: F401


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


class _SelectorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ExcludeFilter(_SelectorModel):
    """Filter to exclude items from results."""
    locked: StrictBool = Field(default=False, description="Exclude locked items")
    hidden: StrictBool = Field(default=False, description="Exclude hidden items")
    guides: StrictBool = Field(default=False, description="Exclude guides")
    clipped: StrictBool = Field(default=False, description="Exclude items inside clipping masks")


# ==================== Target Selectors ====================

class SelectionTarget(_SelectorModel):
    """Target: current selection."""
    type: Literal["selection"] = "selection"


class LayerTarget(_SelectorModel):
    """Target: all items on a layer."""
    type: Literal["layer"] = "layer"
    layer: str = Field(..., min_length=1, description="Layer name")
    recursive: StrictBool = Field(default=False)


class AllTarget(_SelectorModel):
    """Target: all items in document."""
    type: Literal["all"] = "all"
    recursive: StrictBool = Field(default=False)


class QueryTarget(_SelectorModel):
    """Target: items matching query filters."""
    type: Literal["query"] = "query"
    itemType: Optional[str] = Field(None, description="PathItem, TextFrame, etc.")
    pattern: Optional[str] = Field(None, description="Name pattern with * wildcard")
    contents: Optional[str] = Field(None, description="Exact TextFrame contents; CRLF/LF match Illustrator CR.")
    layer: Optional[str] = None
    recursive: StrictBool = Field(default=False)
    
    @model_validator(mode='after')
    def require_at_least_one_filter(self):
        if not self.itemType and not self.pattern and not self.layer and self.contents is None:
            raise ValueError("Query target requires at least one filter (itemType, pattern, layer, or contents)")
        return self


class IdTarget(_SelectorModel):
    """Target one or more explicitly stamped item identities."""
    type: Literal["id"] = "id"
    ids: List[str] = Field(..., min_length=1)


class HandleTarget(_SelectorModel):
    """Target exact untagged artwork through an expiring host handle."""
    type: Literal["handle"] = "handle"
    handles: List[str] = Field(..., min_length=1)


class SpatialRect(_SelectorModel):
    x: float
    y: float
    width: float
    height: float


class NearTarget(_SelectorModel):
    id: str = Field(..., min_length=1)
    radius: float = Field(..., ge=0)


class SpatialTarget(_SelectorModel):
    type: Literal["spatial"] = "spatial"
    within: Optional[SpatialRect] = None
    outside: Optional[SpatialRect] = None
    nearTo: Optional[NearTarget] = None
    coord: Literal["user", "ai"] = "user"
    layer: Optional[str] = None

    @model_validator(mode="after")
    def require_predicate(self):
        if self.within is None and self.outside is None and self.nearTo is None:
            raise ValueError("Spatial target requires within, outside, or nearTo")
        return self


class GridTarget(_SelectorModel):
    type: Literal["grid"] = "grid"
    cell: str = Field(..., min_length=1)
    cols: int = Field(default=4, ge=1, le=99, strict=True)
    rows: int = Field(default=4, ge=1, le=26, strict=True)
    layer: Optional[str] = None


# Compound selector
SimpleTarget = Union[
    SelectionTarget, LayerTarget, AllTarget, QueryTarget,
    IdTarget, HandleTarget, SpatialTarget, GridTarget,
]


class CompoundTarget(_SelectorModel):
    """
    Compound target selector with boolean logic.
    
    Examples:
        # Union of multiple sources
        {"type": "compound", "anyOf": [{"type": "layer", "layer": "Panels"}, {"type": "selection"}]}
        
        # With exclusions
        {"type": "compound", "anyOf": [...], "exclude": {"locked": true, "hidden": true}}
    """
    type: Literal["compound"] = "compound"
    anyOf: List[Union[SimpleTarget, "CompoundTarget"]] = Field(..., min_length=1, description="Union of targets (nested compounds supported)")
    exclude: Optional[ExcludeFilter] = Field(default=None, description="Exclusion filter")


class TargetExpectation(_SelectorModel):
    count: int = Field(..., ge=0, strict=True)


class TargetSelector(_SelectorModel):
    """
    Complete target selector with ordering.
    
    The 'target' field can be a simple selector or compound.
    The 'orderBy' field ensures deterministic result ordering.
    """
    target: Annotated[
        Union[
            SelectionTarget, LayerTarget, AllTarget, QueryTarget,
            IdTarget, HandleTarget, SpatialTarget, GridTarget, CompoundTarget,
        ],
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
    maxScan: Optional[int] = Field(
        default=None,
        ge=1,
        strict=True,
        description=(
            "Optional selector scan cap. If the cap prevents a complete result, "
            "resolution fails explicitly instead of returning a partial/no-match result."
        ),
    )
    expect: Optional[TargetExpectation] = None

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        """Publish both accepted shapes, deriving flat fields from the models."""
        from copy import deepcopy

        wrapped = handler.resolve_ref_schema(handler(core_schema))
        variants = [deepcopy(wrapped)]
        controls = {key: value for key, value in wrapped["properties"].items() if key != "target"}
        for ref in wrapped["properties"]["target"]["oneOf"]:
            flat = deepcopy(handler.resolve_ref_schema(ref))
            flat["properties"].update(deepcopy(controls))
            # Only an omitted type on a flat selection has default semantics.
            # Without this requirement several defaulted variants match {}.
            if flat["properties"]["type"]["const"] != "selection":
                flat["required"] = list(dict.fromkeys([*flat.get("required", []), "type"]))
            variants.append(flat)
        return {"title": "TargetSelector", "description": cls.__doc__, "oneOf": variants}

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, value):
        pending = [(value, 0)]
        while pending:
            node, depth = pending.pop()
            if depth > 16:
                raise ValueError("Selector exceeds 16 compound levels")
            if isinstance(node, dict):
                if node is not value and "expect" in node:
                    raise ValueError("Move expect to the outer TargetSelector; it is not allowed inside target or anyOf.")
                if "target" in node:
                    pending.append((node["target"], depth))
                children = node.get("anyOf")
                if isinstance(children, list):
                    pending.extend((child, depth + 1) for child in children)
        if not isinstance(value, dict) or "target" in value:
            return value
        target = dict(value)
        outer = {key: target.pop(key) for key in ("orderBy", "maxScan", "expect") if key in target}
        # Compound exclusions belong to the compound; other flat exclusions
        # are global. Never drop unknown keys: strict models reject them.
        if target.get("type") != "compound" and "exclude" in target:
            outer["exclude"] = target.pop("exclude")
        target.setdefault("type", "selection")
        return {"target": target, **outer}


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
    model_config = ConfigDict(extra="forbid")

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
    itemsCreated: int = 0
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


# ==================== Task Kind ====================

class TaskKind(str, Enum):
    """Task kind determines collect behavior.
    
    - SELECTION: Normal collect; empty selection → early-return (default)
    - CREATION: Skip collect; items=[]; compute/apply must handle empty input
    """
    SELECTION = "selection"
    CREATION = "creation"


# ==================== Task Options ====================

class TaskOptions(BaseModel):
    """Task execution options."""
    model_config = ConfigDict(extra="forbid")

    mode: Literal["apply", "validate"] = Field(
        default="apply",
        description=(
            "'apply' executes the batch. 'validate' checks operation contracts "
            "without invoking handlers or changing document state on the "
            "default structured SOC route; it is not applied to custom callbacks."
        ),
    )
    stopOnError: bool = Field(
        default=False,
        description=(
            "Stop the default structured SOC batch after the first failed "
            "operation. Custom callback pipelines do not consume this option."
        ),
    )
    kind: TaskKind = Field(
        default=TaskKind.SELECTION,
        description=(
            "Callback-pipeline collection mode: 'selection' collects items and "
            "'creation' skips collection. The default SOC executor forces creation."
        )
    )
    skipCollect: bool = Field(
        default=False,
        description=(
            "Low-level callback-pipeline control that skips collection; "
            "kind='creation' implies it. The default SOC executor already skips collection."
        )
    )
    minCreated: Optional[int] = Field(
        default=None, ge=0,
        description=(
            "Callback-pipeline safety rail checked after apply; warns when the "
            "reported modified count is below this value. Not applied to the "
            "default SOC route, whose apply callback is absent."
        )
    )
    dryRun: bool = Field(
        default=False,
        description=(
            "NOT SUPPORTED (T03). Setting this rejects the request before "
            "execution. It formerly claimed 'no changes applied' while batch "
            "operations had already mutated the document during the compute "
            "stage. Use a read-only tool to inspect state instead."
        ),
    )
    trace: bool = Field(default=False, description="Include execution trace")
    idPolicy: IdPolicy = Field(
        default=IdPolicy.NONE,
        description=(
            "ID assignment policy used during the callback pipeline's collect "
            "stage. The default SOC route skips that outer collection."
        ),
    )
    assignIds: bool = Field(
        default=False,
        description=(
            "Deprecated compatibility alias for opt-in ID assignment during "
            "the callback pipeline's collect stage. Prefer idPolicy='opt_in'."
        ),
    )
    timeout: int = Field(
        default=30,
        ge=1,
        le=300,
        description=(
            "Compatibility field retained and validated, but not currently "
            "used as illustrator_execute_task's host deadline."
        ),
    )
    retry: Optional[RetryPolicy] = Field(
        default=None,
        description=(
            "Compatibility field retained and validated, but currently ignored: "
            "illustrator_execute_task does not call the retry wrapper."
        ),
    )
    idempotency: Idempotency = Field(
        default=Idempotency.UNKNOWN,
        description=(
            "Compatibility field retained for retry metadata, but currently "
            "ignored because illustrator_execute_task does not call the retry wrapper."
        )
    )
    rollback: Optional[bool] = Field(
        default=False,
        exclude=True,
        description=(
            "Unsupported recovery request; true is rejected before dispatch. "
            "False and null are accepted as disabled compatibility forms."
        ),
    )
    snapshot: Optional[bool] = Field(
        default=False,
        exclude=True,
        description=(
            "Unsupported recovery request; true is rejected before dispatch. "
            "False and null are accepted as disabled compatibility forms."
        ),
    )
    recompute: Optional[Union[bool, Dict[str, Any]]] = Field(
        default=None,
        exclude=True,
        description="Unsupported destructive replay request; any enabled request is rejected.",
    )

    @model_validator(mode="after")
    def reject_unsupported_recovery(self):
        requested = []
        if self.rollback:
            requested.append("rollback")
        if self.snapshot:
            requested.append("snapshot")
        # JavaScript treats even an empty object as an enabled request. Preserve
        # that boundary while continuing to accept the explicit disabled forms.
        if isinstance(self.recompute, dict) or self.recompute is True:
            requested.append("recompute")
        if requested:
            names = ", ".join(f"options.{name}" for name in requested)
            raise ValueError(
                f"Unsupported recovery option(s): {names}. Whole-batch "
                "rollback, snapshot recovery, and destructive recompute are "
                "not supported; the request was rejected before host dispatch."
            )
        return self


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
    model_config = ConfigDict(extra="forbid")

    task: str = Field(..., description="Task type: draw_shapes, apply_styles, query_items")
    version: str = Field(default=TASK_PROTOCOL_VERSION, description="Protocol version")
    targets: Optional[TargetSelector] = Field(
        default=None,
        description="Strict target selector; accepts flat or wrapped forms"
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
    lines.append(f"  Stats: {stats.itemsProcessed} ops, "
                 f"{stats.itemsCreated} created, "
                 f"{stats.itemsModified} modified, "
                 f"{stats.itemsSkipped} failed")
    
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

