"""
contracts.py - Single Source of Truth for SOC Operation Contracts.

All op schemas, error codes, and parameter definitions live here.
The ES3 compiler (compile_contracts.py) reads this module and emits
contracts.jsx for the JSX runtime.

DO NOT define schemas in JSX files directly. This is the SSOT.

IMPORTANT: After editing this file, run:
  python -m illustrator_mcp.tools.compile_contracts
to regenerate contracts.jsx. Changes take effect only after MCP server restart
(JSX libraries are loaded at startup and cached in memory).

Schema version: 1.7 — added handles (polar/relative), mirror, mirrorOrigin for Level 3/4
"""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ==================== Protocol Version (SSOT) ====================
# Compiled into contracts.jsx so JSX and Python share the same constant.

TASK_PROTOCOL_VERSION = "3.0.0"
"""Current task protocol version (Python default for TaskPayload.version)."""

TASK_PROTOCOL_MAJOR_VERSIONS = ["2", "3"]
"""Accepted major versions (JSX validatePayload checks against this list)."""


# ==================== Batch Report Schema (documentation) ====================
# executeOpBatch() return shape — Python code depends on these fields.

BATCH_REPORT_SCHEMA = {
    "ok": "bool — true if all ops passed",
    "stats": {
        "total": "int — total ops attempted",
        "passed": "int — ops that succeeded",
        "failed": "int — ops that failed",
    },
    "createdIds": "list[str] — IDs of created elements",
    "ops": "list[dict] — per-op results with {ok, task, id, error?}",
}
"""
Documents the return shape of executeOpBatch() in ops_core.jsx.

Python SOC batch compute depends on:
  - result.stats.passed → report.stats.itemsModified
  - result (full) → report.batchReport
"""


# ==================== Error Codes ====================
# Canonical enum lives in errors.py — imported here for SOC use.

from illustrator_mcp.errors import ErrorCode

# Backward-compat alias so existing ``from contracts import OpErrorCode``
# continues to work.  New code should import ErrorCode directly.
OpErrorCode = ErrorCode


def retryable_codes() -> list:
    """Return the list of retryable error codes (collect/compute only, NOT apply)."""
    return [ErrorCode.R_COLLECT_FAILED, ErrorCode.R_COMPUTE_FAILED]


# ==================== Param Types ====================

class ParamType(str, Enum):
    """Types supported in op parameter schemas."""
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"


# ==================== Op Schema Model ====================

class ParamDef(BaseModel):
    """Definition of a single parameter."""
    type: ParamType
    required: bool = False
    enum_values: Optional[List[str]] = None
    description: Optional[str] = None


class OpSchema(BaseModel):
    """Schema for a single operation."""
    name: str
    params: Dict[str, ParamDef] = Field(default_factory=dict)
    description: Optional[str] = None

    @property
    def required_params(self) -> List[str]:
        return [k for k, v in self.params.items() if v.required]

    @property
    def optional_params(self) -> List[str]:
        return [k for k, v in self.params.items() if not v.required]

    @property
    def types_dict(self) -> Dict[str, str]:
        return {k: v.type.value for k, v in self.params.items()}

    @property
    def enum_values_dict(self) -> Dict[str, List[str]]:
        return {
            k: v.enum_values
            for k, v in self.params.items()
            if v.enum_values
        }


# ==================== Helper factories ====================

def _p(ptype: ParamType, required: bool = False,
       enum: Optional[List[str]] = None, desc: Optional[str] = None) -> ParamDef:
    """Shorthand param definition."""
    return ParamDef(type=ptype, required=required, enum_values=enum, description=desc)

S = ParamType.STRING
N = ParamType.NUMBER
B = ParamType.BOOLEAN
O = ParamType.OBJECT
A = ParamType.ARRAY


# ==================== Op Definitions (SSOT) ====================

OP_SCHEMAS: List[OpSchema] = [
    # --- Element ops ---
    OpSchema(name="element_create", description="Create a new element", params={
        "type":         _p(S, required=True, enum=["rect", "ellipse", "line", "path",
                            "polyline", "polygon", "star", "roundedRect", "text"]),
        "id":           _p(S),
        "x":            _p(N),
        "y":            _p(N),
        "width":        _p(N),
        "height":       _p(N),
        "layer":        _p(S),
        "name":         _p(S),
        "fill":         _p(O),
        "stroke":       _p(O),
        "points":       _p(A),
        "geometry":     _p(O, desc="Geometry IR (auto-injected by SVG d parser)"),
        "sides":        _p(N),
        "radius":       _p(N),
        "outerRadius":  _p(N),
        "innerRadius":  _p(N),
        "numPoints":    _p(N, desc="Number of points for star (avoids 'points' array collision)"),
        "cornerRadius": _p(N),
        "closed":       _p(B),
        "smooth":       _p(B, desc="Auto-smooth points via Catmull-Rom spline"),
        "tension":      _p(N, desc="Smooth tension 0-1 (0=straight, 0.5=Catmull-Rom, 1.0=loose)"),
        "handles":      _p(A, desc="Per-point handle specs: polar {angle,length,symmetric} or relative {dx,dy}"),
        "mirror":       _p(S, desc="Symmetry modifier",
                            enum=["mirror_y_bottom", "mirror_y_top", "mirror_x_right", "mirror_x_left"]),
        "mirrorOrigin": _p(N, desc="Mirror axis coordinate (auto-detected if omitted)"),
        "x2":           _p(N),
        "y2":           _p(N),
        "contents":     _p(S),
        "text":         _p(S),
        "fontSize":     _p(N),
        "fontName":     _p(S),
        "clipTo":       _p(S, desc="MCP ID of clip target: PathItem/CompoundPathItem consumed into new clip group; existing clipping GroupItem appends to it"),
    }),
    OpSchema(name="element_modify", description="Modify element properties", params={
        "x":        _p(N),
        "y":        _p(N),
        "width":    _p(N),
        "height":   _p(N),
        "rotation": _p(N),
        "scaleX":   _p(N),
        "scaleY":   _p(N),
        "name":     _p(S),
    }),
    OpSchema(name="element_delete", description="Delete targeted elements"),
    OpSchema(name="element_create_multi", description="Create multiple paths from Geometry IR", params={
        "geometry":     _p(O, required=True, desc="Geometry IR multi object"),
        "layer":        _p(S),
        "name":         _p(S),
        "fill":         _p(O),
        "stroke":       _p(O),
        "styles":       _p(A, desc="Per-path style overrides"),
        "styleScalars": _p(A, desc="Per-path scalar t for palette lerp"),
        "palette":      _p(O, desc="Palette for scalar-based styling"),
        "offset":       _p(N, desc="Start index for chunked creation"),
        "limit":        _p(N, desc="Max paths per chunk"),
    }),
    OpSchema(name="element_replace", description="Atomically replace a single target element", params={
        "type":             _p(S, required=True, enum=["rect", "ellipse", "line", "path",
                                "polyline", "polygon", "star", "roundedRect", "text"]),
        "id":               _p(S),
        "x":                _p(N),
        "y":                _p(N),
        "width":            _p(N),
        "height":           _p(N),
        "name":             _p(S),
        "fill":             _p(O),
        "stroke":           _p(O),
        "points":           _p(A),
        "sides":            _p(N),
        "radius":           _p(N),
        "outerRadius":      _p(N),
        "innerRadius":      _p(N),
        "numPoints":        _p(N, desc="Number of points for star (avoids 'points' array collision)"),
        "cornerRadius":     _p(N),
        "closed":           _p(B),
        "x2":               _p(N),
        "y2":               _p(N),
        "contents":         _p(S),
        "text":             _p(S),
        "fontSize":         _p(N),
        "fontName":         _p(S),
        "opacity":          _p(N),
        "inheritPosition":  _p(B),
    }),
    OpSchema(name="element_create_multi_by_ref", description="Create paths from stash IR", params={
        "irKey":        _p(S, required=True, desc="Session stash key"),
        "offset":       _p(N, desc="Start index for chunked creation"),
        "limit":        _p(N, desc="Max paths per chunk"),
        "layer":        _p(S),
        "name":         _p(S),
        "fill":         _p(O),
        "stroke":       _p(O),
        "styles":       _p(A, desc="Per-path style overrides"),
        "styleScalars": _p(A, desc="Per-path scalar t for palette lerp"),
        "palette":      _p(O, desc="Palette for scalar-based styling"),
    }),
    OpSchema(name="element_create_batch", description="Batch-create items (template or items mode)", params={
        "template":     _p(O, desc="Template shape {type, fill?, stroke?, ...}"),
        "instances":    _p(A, desc="Array of {x, y, fill?, stroke?, scale?}"),
        "items":        _p(A, desc="Heterogeneous batch [{type, ...}, ...]"),
        "array":        _p(O, desc="Array generation {count, startX, startY, spacingX?, spacingY?, cols?}"),
        "defaultStyle": _p(O, desc="Default style for items without explicit style"),
        "layer":        _p(S),
        "name":         _p(S),
    }),

    # --- Layer ops ---
    OpSchema(name="layer_create", description="Create a new layer", params={
        "name":      _p(S, required=True),
        "color":     _p(O),
        "visible":   _p(B),
        "locked":    _p(B),
        "above":     _p(S, desc="Place above this layer (name)"),
        "below":     _p(S, desc="Place below this layer (name)"),
        "placement": _p(S, enum=["top", "bottom"], desc="Pin to stack edge"),
    }),
    OpSchema(name="layer_activate", description="Activate a layer", params={
        "name": _p(S, required=True),
    }),
    OpSchema(name="layer_lock", description="Lock/unlock a layer", params={
        "name":   _p(S, required=True),
        "locked": _p(B, required=True),
    }),
    OpSchema(name="layer_visible", description="Show/hide a layer", params={
        "name":    _p(S, required=True),
        "visible": _p(B, required=True),
    }),
    OpSchema(name="layer_delete", description="Delete a layer", params={
        "name": _p(S, required=True),
    }),
    OpSchema(name="layer_list", description="List all layers (read-only)"),

    # --- Style ops ---
    OpSchema(name="style_set_fill", description="Set fill color", params={
        "fill": _p(O, desc='Color {r,g,b} e.g. {"r":255,"g":0,"b":0}, or false to disable'),
        "r": _p(N, desc="Red 0-255 (compat — prefer fill.r)"),
        "g": _p(N, desc="Green 0-255 (compat — prefer fill.g)"),
        "b": _p(N, desc="Blue 0-255 (compat — prefer fill.b)"),
    }),
    OpSchema(name="style_set_stroke", description="Set stroke properties", params={
        "stroke": _p(O, desc='Stroke {r,g,b,width?} e.g. {"r":0,"g":0,"b":0,"width":2}, or false to disable'),
        "r":     _p(N, desc="Red 0-255 (compat — prefer stroke.r)"),
        "g":     _p(N, desc="Green 0-255 (compat — prefer stroke.g)"),
        "b":     _p(N, desc="Blue 0-255 (compat — prefer stroke.b)"),
        "width": _p(N, desc="Width in pt (compat — prefer stroke.width)"),
    }),
    OpSchema(name="style_set_opacity", description="Set opacity", params={
        "opacity": _p(N, required=True),
    }),
    OpSchema(name="style_remove_fill", description="Remove fill"),
    OpSchema(name="style_remove_stroke", description="Remove stroke"),
    OpSchema(name="style_snapshot", description="Read computed style from targets"),
    OpSchema(name="style_clone", description="Copy style from source to targets", params={
        "from":       _p(S, required=True),
        "properties": _p(A),
    }),
    OpSchema(name="style_set_gradient", description="Apply gradient fill", params={
        "type":   _p(S),
        "stops":  _p(A, required=True),
        "angle":  _p(N),
        "origin": _p(O),
        "length": _p(N),
        "name":   _p(S),
    }),

    # --- Group ops ---
    OpSchema(name="group_create", description="Group targeted items", params={
        "name": _p(S),
    }),
    OpSchema(name="group_ungroup", description="Ungroup targeted groups"),
    OpSchema(name="clip_create", description="Create clipping mask group", params={
        "mask":           _p(S, required=True, desc="MCP ID of the clipping path"),
        "contents":       _p(A, required=True, desc="Array of MCP IDs to clip"),
        "id":             _p(S, desc="ID for the clipping group"),
        "name":           _p(S, desc="Name for the clipping group"),
        "dryRun":         _p(B, desc="Preview without mutation"),
        "duplicate_mask": _p(B, desc="Duplicate mask as invisible clip; keep original visible (default true)"),
    }),

    # --- Z-order ops ---
    OpSchema(name="zorder_front", description="Bring to front"),
    OpSchema(name="zorder_back", description="Send to back"),
    OpSchema(name="zorder_forward", description="Bring forward one step"),
    OpSchema(name="zorder_backward", description="Send backward one step"),

    # --- Text ops ---
    OpSchema(name="text_create", description="Create a text frame", params={
        "contents": _p(S, required=True),
        "id":       _p(S),
        "x":        _p(N),
        "y":        _p(N),
        "layer":    _p(S),
        "name":     _p(S),
        "fontSize": _p(N),
        "fontName": _p(S),
        "fill":     _p(O, desc='Text fill color {r,g,b}'),
        "r":        _p(N, desc="Red 0-255 (compat — prefer fill.r)"),
        "g":        _p(N, desc="Green 0-255 (compat — prefer fill.g)"),
        "b":        _p(N, desc="Blue 0-255 (compat — prefer fill.b)"),
    }),
    OpSchema(name="text_set_content", description="Set text content", params={
        "contents": _p(S, required=True),
    }),
    OpSchema(name="text_set_style", description="Set text style", params={
        "fontSize": _p(N),
        "fontName": _p(S),
        "fill":     _p(O, desc='Text fill color {r,g,b}'),
        "r":        _p(N, desc="Red 0-255 (compat — prefer fill.r)"),
        "g":        _p(N, desc="Green 0-255 (compat — prefer fill.g)"),
        "b":        _p(N, desc="Blue 0-255 (compat — prefer fill.b)"),
    }),

    # --- Alignment ops ---
    OpSchema(name="align_horizontal", description="Align items horizontally", params={
        "mode":       _p(S, enum=["left", "center", "right"], desc="Alignment edge/center"),
        "reference":  _p(S, enum=["targets", "artboard"], desc="Reference source"),
        "key_id":     _p(S, desc="MCP ID of key object (others align to it)"),
        "coordinate": _p(N, desc="Explicit X coordinate (doc space, overrides key_id/reference)"),
    }),
    OpSchema(name="align_vertical", description="Align items vertically", params={
        "mode":       _p(S, enum=["top", "middle", "bottom"], desc="Alignment edge/center"),
        "reference":  _p(S, enum=["targets", "artboard"], desc="Reference source"),
        "key_id":     _p(S, desc="MCP ID of key object (others align to it)"),
        "coordinate": _p(N, desc="Explicit Y coordinate (doc space, overrides key_id/reference)"),
    }),
    OpSchema(name="distribute_horizontal", description="Distribute items horizontally", params={
        "mode":    _p(S, enum=["gap", "center"], desc="Gap between edges or center-to-center"),
        "spacing": _p(N, desc="Fixed spacing; omit to auto-distribute within span"),
    }),
    OpSchema(name="distribute_vertical", description="Distribute items vertically", params={
        "mode":    _p(S, enum=["gap", "center"], desc="Gap between edges or center-to-center"),
        "spacing": _p(N, desc="Fixed spacing; omit to auto-distribute within span"),
    }),

    # --- Assert ops ---
    OpSchema(name="assert_count", description="Assert item count", params={
        "expected": _p(N, required=True),
        "operator": _p(S, enum=["eq", "gte", "lte", "gt", "lt"]),
    }),
    OpSchema(name="assert_bounds", description="Assert items within bounds", params={
        "artboardIndex": _p(N),
    }),
    OpSchema(name="assert_exists", description="Assert items exist by ID", params={
        "ids": _p(A, required=True),
    }),
    OpSchema(name="assert_style", description="Assert style properties", params={
        "fill":        _p(O),
        "stroke":      _p(O),
        "strokeWidth": _p(N),
        "opacity":     _p(N),
        "tolerance":   _p(N),
        "repair":      _p(B),
    }),
    OpSchema(name="assert_text", description="Assert text content", params={
        "contents":      _p(S, required=True),
        "matchMode":     _p(S, enum=["exact", "contains", "regex"]),
        "caseSensitive": _p(B),
    }),
    OpSchema(name="assert_alignment", description="Assert alignment", params={
        "mode":      _p(S, required=True, enum=["left", "centerX", "right",
                         "top", "centerY", "bottom"]),
        "tolerance": _p(N),
        "spacing":   _p(N),
        "repair":    _p(B),
    }),
    OpSchema(name="assert_z_order", description="Assert z-order between items", params={
        "above": _p(S, desc="MCP ID that should be above"),
        "below": _p(S, desc="MCP ID that should be below"),
        "pairs": _p(A, desc="Array of [aboveId, belowId] pairs for batch check"),
    }),
    OpSchema(name="assert_layer_order", description="Assert layer stacking order (monotonicity check)", params={
        "order":  _p(A, required=True, desc="Layer names top-to-bottom"),
        "strict": _p(B, desc="Exact match (no extra layers) if true"),
    }),

    # --- Measure/snapshot ops ---
    OpSchema(name="measure_bounds", description="Measure item bounds"),
    OpSchema(name="snapshot_structure", description="Capture document structure", params={
        "includeItems": _p(B),
    }),
    OpSchema(name="hash_structure", description="Hash document structure"),

    # --- Compound ops ---
    OpSchema(name="compound", description="Sequence sub-ops with $prev ID forwarding", params={
        "ops":    _p(A, required=True),
        "atomic": _p(B),
    }),

    # --- Boolean ops ---
    OpSchema(name="path_boolean", description="Boolean op on paths (via Python Clipper engine)", params={
        "operation":         _p(S, required=True, enum=["subtract", "unite", "intersect", "xor"]),
        "subject":           _p(S, required=True),
        "clip":              _p(A, required=True),
        "flatten_tolerance": _p(N),
        "max_segments":      _p(N),
        "delete_originals":  _p(B),
        "style":             _p(S),
        "layer":             _p(S),
        "name":              _p(S),
    }),
]

# Build lookup dict
OP_SCHEMA_MAP: Dict[str, OpSchema] = {op.name: op for op in OP_SCHEMAS}


def get_op_schema(name: str) -> Optional[OpSchema]:
    """Get schema for an operation by name."""
    return OP_SCHEMA_MAP.get(name)


def list_op_names() -> List[str]:
    """List all operation names."""
    return [op.name for op in OP_SCHEMAS]
