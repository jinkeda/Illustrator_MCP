"""
contracts.py - Single Source of Truth for SOC Operation Contracts.

All op schemas, error codes, and parameter definitions live here.
The ES3 compiler (compile_contracts.py) reads this module and emits
contracts.jsx for the JSX runtime.

DO NOT define schemas in JSX files directly. This is the SSOT.
"""

from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ==================== Error Codes ====================

class ErrorCode(str, Enum):
    """Standardized error codes mirrored to JSX runtime."""

    # Validation (V) - fail before execution
    V_NO_DOCUMENT = "V001"
    V_NO_SELECTION = "V002"
    V_INVALID_PAYLOAD = "V003"
    V_INVALID_TARGETS = "V004"
    V_UNKNOWN_TARGET_TYPE = "V005"
    V_MISSING_REQUIRED_PARAM = "V006"
    V_INVALID_PARAM_TYPE = "V007"
    V_SCHEMA_MISMATCH = "V008"

    # Runtime (R) - fail during execution
    R_COLLECT_FAILED = "R001"
    R_COMPUTE_FAILED = "R002"
    R_APPLY_FAILED = "R003"
    R_ITEM_OPERATION_FAILED = "R004"
    R_TIMEOUT = "R005"
    R_OUT_OF_BOUNDS = "R006"

    # Execution (E) - infrastructure/dependency issues
    E_EXECUTION = "E001"

    # System (S) - Illustrator/environment issues
    S_APP_ERROR = "S001"
    S_SCRIPT_ERROR = "S002"
    S_IO_ERROR = "S003"
    S_MEMORY_ERROR = "S004"

    # Retryable codes (collect/compute only, NOT apply)
    @classmethod
    def retryable(cls) -> list:
        return [cls.R_COLLECT_FAILED, cls.R_COMPUTE_FAILED]


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
        "sides":        _p(N),
        "radius":       _p(N),
        "outerRadius":  _p(N),
        "innerRadius":  _p(N),
        "cornerRadius": _p(N),
        "closed":       _p(B),
        "x2":           _p(N),
        "y2":           _p(N),
        "contents":     _p(S),
        "text":         _p(S),
        "fontSize":     _p(N),
        "fontName":     _p(S),
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

    # --- Layer ops ---
    OpSchema(name="layer_create", description="Create a new layer", params={
        "name":    _p(S, required=True),
        "color":   _p(O),
        "visible": _p(B),
        "locked":  _p(B),
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

    # --- Style ops ---
    OpSchema(name="style_set_fill", description="Set fill color", params={
        "r": _p(N, required=True),
        "g": _p(N, required=True),
        "b": _p(N, required=True),
    }),
    OpSchema(name="style_set_stroke", description="Set stroke properties", params={
        "r":     _p(N),
        "g":     _p(N),
        "b":     _p(N),
        "width": _p(N),
    }),
    OpSchema(name="style_set_opacity", description="Set opacity", params={
        "opacity": _p(N, required=True),
    }),
    OpSchema(name="style_remove_fill", description="Remove fill"),
    OpSchema(name="style_remove_stroke", description="Remove stroke"),

    # --- Group ops ---
    OpSchema(name="group_create", description="Group targeted items", params={
        "name": _p(S),
    }),
    OpSchema(name="group_ungroup", description="Ungroup targeted groups"),

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
        "fontSize": _p(N),
        "fontName": _p(S),
        "r":        _p(N),
        "g":        _p(N),
        "b":        _p(N),
    }),
    OpSchema(name="text_set_content", description="Set text content", params={
        "contents": _p(S, required=True),
    }),
    OpSchema(name="text_set_style", description="Set text style", params={
        "fontSize": _p(N),
        "fontName": _p(S),
        "r":        _p(N),
        "g":        _p(N),
        "b":        _p(N),
    }),

    # --- Alignment ops ---
    OpSchema(name="align_horizontal", description="Align items horizontally", params={
        "mode": _p(S, required=True, enum=["left", "center", "right"]),
    }),
    OpSchema(name="align_vertical", description="Align items vertically", params={
        "mode": _p(S, required=True, enum=["top", "middle", "bottom"]),
    }),
    OpSchema(name="distribute_horizontal", description="Distribute items horizontally"),
    OpSchema(name="distribute_vertical", description="Distribute items vertically"),

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

    # --- Measure/snapshot ops ---
    OpSchema(name="measure_bounds", description="Measure item bounds"),
    OpSchema(name="snapshot_structure", description="Capture document structure", params={
        "includeItems": _p(B),
    }),
    OpSchema(name="hash_structure", description="Hash document structure"),
]

# Build lookup dict
OP_SCHEMA_MAP: Dict[str, OpSchema] = {op.name: op for op in OP_SCHEMAS}


def get_op_schema(name: str) -> Optional[OpSchema]:
    """Get schema for an operation by name."""
    return OP_SCHEMA_MAP.get(name)


def list_op_names() -> List[str]:
    """List all operation names."""
    return [op.name for op in OP_SCHEMAS]
