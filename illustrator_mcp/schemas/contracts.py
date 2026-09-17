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


class OperationDocumentation(BaseModel):
    """Audited human guidance; not an additional execution schema."""
    targets: str
    coordinates: str
    defaults: Dict[str, Any]
    result: str
    constraints: List[str]
    example_params: Dict[str, Any]
    example_targets: Optional[Dict[str, Any]] = None
    prerequisites: str = "An open Illustrator document."


class OpSchema(BaseModel):
    """Schema for a single operation."""
    name: str
    route: Literal["typed_batch", "compatibility_payload", "python_tool"]
    requires_targets: bool
    documentation: OperationDocumentation
    params: Dict[str, ParamDef] = Field(default_factory=dict)
    description: Optional[str] = None

    @property
    def backend(self) -> str:
        return "python" if self.route == "python_tool" else "jsx"

    @property
    def public_route(self) -> str:
        if self.route == "python_tool":
            return "illustrator_path_boolean"
        if self.route == "typed_batch":
            return "illustrator_execute_task.params.batch.operations"
        return "illustrator_execute_task.params.payload.params.ops"

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


def _d(targets: str, coordinates: str, result: str, example: dict, *,
       defaults: Optional[dict] = None, constraints: Optional[list] = None,
       select: bool = False, prerequisites: str = "An open Illustrator document.") -> OperationDocumentation:
    return OperationDocumentation(
        targets=targets, coordinates=coordinates, result=result,
        defaults=defaults or {}, constraints=constraints or [], example_params=example,
        example_targets={"type": "selection"} if select else None,
        prerequisites=prerequisites,
    )


_ARTBOARD_FRAME = "Input positions/IR: points, active-artboard top-left, Y-down; DOM = [ab[0]+x, ab[1]-y]."
_DOM_FRAME = "Output geometry: Illustrator document points, Y-up; not artboard-relative."
_NO_COORDINATES = "No coordinate parameters."


# ==================== Op Definitions (SSOT) ====================

OP_SCHEMAS: List[OpSchema] = [
    # --- Element ops ---
    OpSchema(name="element_create", route="typed_batch", requires_targets=False,
        documentation=_d('No selector required; creates artwork on params.layer, then batch default layer, then active layer.',
            _ARTBOARD_FRAME + " Bounds are DOM [left,top,width,height].",
            'Per-op id plus data {typename, bounds:[left,top,width,height], clippedTo, clipGroupId}; clipping can add ids and movedIds.',
            {'type': 'rect', 'x': 20, 'y': 20, 'width': 80, 'height': 40, 'fill': {'r': 40, 'g': 100, 'b': 180}}, defaults={'x': 0, 'y': 0, 'width': 100, 'height': 100, 'id': 'generated'},
            constraints=['Specify positive dimensions for sized shapes. Path geometry must have valid finite points. Existing explicit layer names must resolve. Fill/stroke support false/null disable sentinels; absent appearance may use Illustrator defaults.'], select=False, prerequisites='An open Illustrator document.'), description="Create a new element", params={
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
        "opacity":      _p(N),
        "strokeWidth":  _p(N),
        "noFill":       _p(B),
        "noStroke":     _p(B),
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
    OpSchema(name="element_modify", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor.',
            _ARTBOARD_FRAME + " Position echo is {x,y,width,height} in the same artboard frame, rounded to 0.01 pt; dimensions are axis-aligned bounds. Rotation is degrees; scale is a multiplier (1=100%).",
            'data {modified,total,failed,position}; position echoes the first target after modification.',
            {'opacity': 60}, defaults={},
            constraints=['Only supplied properties change; failure may leave earlier targets modified. Both typed batch and compatibility payload accept scaleX/scaleY, but the handler ignores them. Use uniform scale, a multiplier (1 preserves size, 2 doubles it).'], select=True, prerequisites='An open document with the intended editable artwork selected.'), description="Modify element properties", params={
        "x":        _p(N),
        "y":        _p(N),
        "width":    _p(N),
        "height":   _p(N),
        "rotation": _p(N),
        "scaleX":   _p(N, desc="Accepted by both routes but ignored by the handler; use uniform scale"),
        "scaleY":   _p(N, desc="Accepted by both routes but ignored by the handler; use uniform scale"),
        "scale":    _p(N, desc="Uniform multiplier: 1 preserves size, 2 doubles it; unlike batch instance scale percentages"),
        "name":     _p(S),
        "fill":     _p(O),
        "stroke":   _p(O),
        "opacity":  _p(N),
        "layer":    _p(S),
    }),
    OpSchema(name="element_delete", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor.',
            _NO_COORDINATES,
            'data {deleted,total,failed}; inspect effects for actual deleted identities.',
            {}, defaults={},
            constraints=[], select=True, prerequisites='An open document with the intended editable artwork selected.'), description="Delete targeted elements"),
    OpSchema(name="element_create_multi", route="typed_batch", requires_targets=False,
        documentation=_d('No selector required; creates artwork on params.layer, then batch default layer, then active layer.',
            _ARTBOARD_FRAME,
            'data {created,skipped,ids,totalPoints,stylingMode,pagination:{offset,limit,total,hasMore}}.',
            {'geometry': {'v': 1, 'ir': 'multi', 'paths': [{'v': 1, 'ir': 'path', 'kind': 'polyline', 'points': [[20, 20], [80, 20], [50, 70]], 'closed': True, 'meta': {}}], 'meta': {}}}, defaults={'offset': 0, 'limit': 'all remaining paths', 'styling': 'shared unless styles/styleScalars supplied'},
            constraints=['Requires multi IR v1 containing path IR objects; a bare path IR is rejected. Per-path handles must match points. Bad paths may be skipped; inspect counts and warnings.'], select=False, prerequisites='An open Illustrator document.'), description="Create multiple paths from Geometry IR", params={
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
    OpSchema(name="element_replace", route="typed_batch", requires_targets=True,
        documentation=_d('Exactly one resolved target. Replacement is verified before removing the old item.',
            _ARTBOARD_FRAME + " Returned bounds use DOM left/top and positive width/height.",
            'Per-op new id; data {typename,bounds:[left,top,width,height],oldId,ids,deletedIds}; failures can report retained/partial effects.',
            {'type': 'ellipse', 'width': 80, 'height': 40}, defaults={'inheritPosition': True, 'type': 'rect', 'width': 100, 'height': 100},
            constraints=['Select exactly one editable item. Inherited position applies when x and y are both omitted; replacement stays on the original layer. type is required by the public contract.'], select=True, prerequisites='An open document with exactly one editable item selected.'), description="Replace a single target element", params={
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
        "geometry":         _p(O),
        "sides":            _p(N),
        "radius":           _p(N),
        "outerRadius":      _p(N),
        "innerRadius":      _p(N),
        "numPoints":        _p(N, desc="Number of points for star (avoids 'points' array collision)"),
        "cornerRadius":     _p(N),
        "closed":           _p(B),
        "smooth":           _p(B),
        "tension":          _p(N),
        "handles":          _p(A),
        "x2":               _p(N),
        "y2":               _p(N),
        "contents":         _p(S),
        "text":             _p(S),
        "fontSize":         _p(N),
        "fontName":         _p(S),
        "opacity":          _p(N),
        "inheritPosition":  _p(B),
    }),
    OpSchema(name="element_create_multi_by_ref", route="typed_batch", requires_targets=False,
        documentation=_d('No selector required; creates artwork on params.layer, then batch default layer, then active layer.',
            _ARTBOARD_FRAME,
            'Same per-op data as element_create_multi.',
            {'irKey': 'catalogue_ir'}, defaults={'offset': 0, 'limit': 'all remaining paths'},
            constraints=['The stash key must contain multi IR in the current session; missing keys fail.'], select=False, prerequisites="An open document; first call illustrator_execute_script with includes ['session','geo_ir'] and script stashPutIR('catalogue_ir',irMulti([irPath([[20,20],[80,20],[50,70]],true)]));"), description="Create paths from stash IR", params={
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
    OpSchema(name="element_create_batch", route="typed_batch", requires_targets=False,
        documentation=_d('No selector required; creates artwork on params.layer, then batch default layer, then active layer.',
            _ARTBOARD_FRAME,
            'data includes created,skipped,failed,ids,bounds and mode; optional per-item outcomes depend on the batch mode.',
            {'items': [{'type': 'rect', 'x': 20, 'y': 20, 'width': 40, 'height': 30}, {'type': 'ellipse', 'x': 80, 'y': 20, 'width': 40, 'height': 30}]},
            defaults={'rect w/h': 50, 'ellipse r/rx/ry': 5, 'path closed': False, 'instance scale': 100, 'array startX/startY/spacingX/spacingY': 0, 'array cols': 'count'},
            constraints=[
                'Use either a nonempty items array, or template with instances/array. Inspect partial failures; batch is not atomic.',
                'items supports rect {x,y,w,h}, ellipse {cx,cy,r or rx/ry}, and line/path/polyline {points,closed?}; per-item appearance is nested in style {fill,stroke,opacity}, falling back to defaultStyle.',
                'template supports the same shapes plus polygon {sides,radius} and star {numPoints,outerRadius,innerRadius}; appearance is directly on template. instances contain {x,y,scale,fill,stroke,opacity}. array contains {count,cols,startX,startY,spacingX,spacingY}; count is an integer 0..10000 and cols is an integer >=1.',
                'Instance scale is a percentage on both routes: omitted or 100 preserves size, 1 requests 1%, and 50 requests half size. This differs from element_modify.scale, which is a multiplier. Supplied instance scales are passed directly to Illustrator resize about the center.',
                'Typed input normalizes width/height to w/h or ellipse diameters, radius to ellipse r, and ellipse top-left x/y to center cx/cy; conflicting aliases fail. Compatibility payload callers must use the native nested spellings above.',
            ], select=False, prerequisites='An open Illustrator document.'), description="Batch-create items (template or items mode)", params={
        "template":     _p(O, desc="Template shape {type, fill?, stroke?, ...}"),
        "instances":    _p(A, desc="Array of {x, y, fill?, stroke?, scale?}"),
        "items":        _p(A, desc="Heterogeneous batch [{type, ...}, ...]"),
        "array":        _p(O, desc="Array generation {count, startX, startY, spacingX?, spacingY?, cols?}"),
        "defaultStyle": _p(O, desc="Default style for items without explicit style"),
        "layer":        _p(S),
        "name":         _p(S),
    }),

    # --- Layer ops ---
    OpSchema(name="layer_create", route="typed_batch", requires_targets=False,
        documentation=_d('No selector; identifies a layer by name.',
            _NO_COORDINATES,
            'data {name,existed,index}; index is Illustrator layer.zOrderPosition. Existing layers also report positioningApplied:false and ignoredParams.',
            {'name': 'Catalogue layer'}, defaults={'placement': 'new layer at Illustrator default position'},
            constraints=['Idempotent by name; an existing layer returns without restacking. Use layer_reorder to move it. placement conflicts with above/below; above and below conflict.'], select=False, prerequisites='An open Illustrator document.'), description="Create a new layer", params={
        "name":      _p(S, required=True),
        "color":     _p(O),
        "visible":   _p(B),
        "locked":    _p(B),
        "above":     _p(S, desc="Place above this layer (name)"),
        "below":     _p(S, desc="Place below this layer (name)"),
        "placement": _p(S, enum=["top", "bottom"], desc="Pin to stack edge"),
    }),
    OpSchema(name="layer_reorder", route="typed_batch", requires_targets=False,
        documentation=_d('No selector; name and any relative layer name must exist.',
            _NO_COORDINATES,
            'data {name,movedFrom,movedTo,moved,order}.',
            {'name': 'Catalogue layer', 'placement': 'bottom'}, defaults={},
            constraints=['Exactly one of placement (top/bottom), above, below. Cannot move a layer relative to itself.'], select=False, prerequisites='An open document with a layer named Catalogue layer (create with layer_create first).'),
             description="Move an existing layer within the stack",
             params={
        "name":      _p(S, required=True),
        "placement": _p(S, enum=["top", "bottom"], desc="Pin to stack edge"),
        "above":     _p(S, desc="Move above this layer (name)"),
        "below":     _p(S, desc="Move below this layer (name)"),
    }),
    OpSchema(name="layer_activate", route="typed_batch", requires_targets=False,
        documentation=_d('No selector; exactly one named layer is looked up.',
            _NO_COORDINATES,
            'data {activatedLayer}.',
            {'name': 'Catalogue layer'}, defaults={},
            constraints=[], select=False, prerequisites='An open document with a layer named Catalogue layer (create with layer_create first).'), description="Activate a layer", params={
        "name": _p(S, required=True),
    }),
    OpSchema(name="layer_lock", route="typed_batch", requires_targets=False,
        documentation=_d('No selector; exactly one named layer is looked up.',
            _NO_COORDINATES,
            'data {layer,locked}.',
            {'name': 'Catalogue layer', 'locked': True}, defaults={'locked': True},
            constraints=[], select=False, prerequisites='An open document with a layer named Catalogue layer (create with layer_create first).'), description="Lock/unlock a layer", params={
        "name":   _p(S, required=True),
        "locked": _p(B, required=True),
    }),
    OpSchema(name="layer_visible", route="typed_batch", requires_targets=False,
        documentation=_d('No selector; exactly one named layer is looked up.',
            _NO_COORDINATES,
            'data {layer,visible}.',
            {'name': 'Catalogue layer', 'visible': True}, defaults={'visible': True},
            constraints=[], select=False, prerequisites='An open document with a layer named Catalogue layer (create with layer_create first).'), description="Show/hide a layer", params={
        "name":    _p(S, required=True),
        "visible": _p(B, required=True),
    }),
    OpSchema(name="layer_delete", route="typed_batch", requires_targets=False,
        documentation=_d('No selector; exactly one named layer is looked up.',
            _NO_COORDINATES,
            'data {deleted:layerName}; removes the layer and its contents.',
            {'name': 'Catalogue layer'}, defaults={},
            constraints=['Layer must exist; Illustrator can refuse locked or last-layer deletion.'], select=False, prerequisites='An open document with a layer named Catalogue layer (create with layer_create first).'), description="Delete a layer", params={
        "name": _p(S, required=True),
    }),
    OpSchema(name="layer_list", route="typed_batch", requires_targets=False,
        documentation=_d('No selector; all document layers.',
            _NO_COORDINATES,
            'data {layers:[{name,index,visible,locked,itemCount}],count}; topmost layer has index 0.',
            {}, defaults={},
            constraints=[], select=False, prerequisites='An open Illustrator document.'), description="List all layers (read-only)"),

    # --- Style ops ---
    OpSchema(name="style_set_fill", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor.',
            _NO_COORDINATES,
            'data {modified}; inspect warnings/effects for declined items.',
            {'fill': {'r': 50, 'g': 100, 'b': 180}}, defaults={},
            constraints=['Provide nested RGB fill or flat r/g/b. false/null disables fill; an empty color object is invalid.'], select=True, prerequisites='An open document with the intended editable artwork selected.'), description="Set fill color", params={
        "fill": _p(O, desc='Color {r,g,b} e.g. {"r":255,"g":0,"b":0}, or false to disable'),
        "r": _p(N, desc="Red 0-255 (compat — prefer fill.r)"),
        "g": _p(N, desc="Green 0-255 (compat — prefer fill.g)"),
        "b": _p(N, desc="Blue 0-255 (compat — prefer fill.b)"),
    }),
    OpSchema(name="style_set_stroke", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor.',
            _NO_COORDINATES,
            'data {modified}; inspect warnings/effects for declined items.',
            {'stroke': {'r': 0, 'g': 0, 'b': 0, 'width': 2}}, defaults={'width': 1},
            constraints=['Nested stroke.width overrides flat width. With no color, existing stroke color is retained and stroke enabled. false/null disables stroke.'], select=True, prerequisites='An open document with the intended editable artwork selected.'), description="Set stroke properties", params={
        "stroke": _p(O, desc='Stroke {r,g,b,width?} e.g. {"r":0,"g":0,"b":0,"width":2}, or false to disable'),
        "r":     _p(N, desc="Red 0-255 (compat — prefer stroke.r)"),
        "g":     _p(N, desc="Green 0-255 (compat — prefer stroke.g)"),
        "b":     _p(N, desc="Blue 0-255 (compat — prefer stroke.b)"),
        "width": _p(N, desc="Width in pt (compat — prefer stroke.width)"),
    }),
    OpSchema(name="style_set_opacity", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor.',
            _NO_COORDINATES,
            'data {modified}.',
            {'opacity': 50}, defaults={'handler opacity': 100},
            constraints=['The public contract requires opacity. Typed batch constrains it to 0..100; compatibility handler clamps outside that range.'], select=True, prerequisites='An open document with the intended editable artwork selected.'), description="Set opacity", params={
        "opacity": _p(N, required=True),
    }),
    OpSchema(name="style_remove_fill", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor.',
            _NO_COORDINATES,
            'data {modified}.',
            {}, defaults={},
            constraints=[], select=True, prerequisites='An open document with the intended editable artwork selected.'), description="Remove fill"),
    OpSchema(name="style_remove_stroke", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor.',
            _NO_COORDINATES,
            'data {modified}.',
            {}, defaults={},
            constraints=[], select=True, prerequisites='An open document with the intended editable artwork selected.'), description="Remove stroke"),
    OpSchema(name="style_snapshot", route="typed_batch", requires_targets=False,
        documentation=_d('Zero or more targets; empty targets return items:[] with a warning.',
            _NO_COORDINATES,
            'data {items:[{type,id?,opacity?,fill?,stroke?,strokeWidth?,text?}]}; color descriptors use type; mixed text can report uniform:false.',
            {}, defaults={},
            constraints=[], select=True, prerequisites='An open document with the intended editable artwork selected.'), description="Read computed style from targets"),
    OpSchema(name="style_clone", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor. params.from separately resolves one source MCP ID.',
            _NO_COORDINATES,
            'data {modified,total}; warnings describe incompatible/failed properties.',
            {'from': 'catalogue_source', 'properties': ['fill', 'stroke', 'opacity']}, defaults={'properties': 'all compatible fill/stroke/opacity/text properties'},
            constraints=[], select=True, prerequisites='An open document containing MCP ID catalogue_source; select the destination artwork.'), description="Copy style from source to targets", params={
        "from":       _p(S, required=True),
        "properties": _p(A),
    }),
    OpSchema(name="style_set_gradient", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor.',
            _DOM_FRAME + " origin:{x,y} is passed directly to GradientColor (DOM Y-up); angle is degrees, length is points.",
            'data {modified,gradientName}.',
            {'type': 'linear', 'stops': [{'r': 0, 'g': 0, 'b': 0, 'pos': 0}, {'r': 255, 'g': 255, 'b': 255, 'pos': 100}]}, defaults={'type': 'linear', 'angle': 0, 'name': 'generated', 'stop positions': 'evenly spaced if omitted'},
            constraints=['At least two RGB stops. A supplied existing gradient name reconfigures that document resource; failure can retain partial reconfiguration.'], select=True, prerequisites='An open document with the intended editable artwork selected.'), description="Apply gradient fill", params={
        "type":   _p(S),
        "stops":  _p(A, required=True),
        "angle":  _p(N),
        "origin": _p(O),
        "length": _p(N),
        "name":   _p(S),
    }),

    # --- Group ops ---
    OpSchema(name="group_create", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor.',
            _NO_COORDINATES,
            'Per-op group id; data {itemCount,movedIds,moved,unnamedMoves,failed}.',
            {'name': 'Catalogue group'}, defaults={},
            constraints=['Creates on first target layer. Failed member moves may leave a partial group; inspect failed count.'], select=True, prerequisites='An open document with the intended editable artwork selected.'), description="Group targeted items", params={
        "name": _p(S),
    }),
    OpSchema(name="group_ungroup", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor.',
            _NO_COORDINATES,
            'data {ungrouped}; non-group targets are skipped with warnings.',
            {}, defaults={},
            constraints=[], select=True, prerequisites='An open document with intended GroupItems selected.'), description="Ungroup targeted groups"),
    OpSchema(name="clip_create", route="typed_batch", requires_targets=False,
        documentation=_d('Selector ignored; params.mask is one PathItem/CompoundPathItem MCP ID and params.contents is a nonempty ID array.',
            _NO_COORDINATES,
            'Per-op group id; data {itemCount,maskType,parentType,duplicate_mask_applied,movedIds}; failure can retain a partial group.',
            {'mask': 'catalogue_mask', 'contents': ['catalogue_content'], 'duplicate_mask': True}, defaults={'duplicate_mask': True, 'dryRun': False},
            constraints=['Mask and contents must be distinct and all IDs must resolve. Cross-parent contents produce warnings and are moved to the mask parent; that parent must support groupItems.add(). duplicate_mask=false moves the original mask into the group. params.dryRun returns a placement plan without mutation, distinct from forbidden task options.dryRun.'], select=False, prerequisites='An open document with mask ID catalogue_mask and content ID catalogue_content on the same layer.'), description="Create clipping mask group", params={
        "mask":           _p(S, required=True, desc="MCP ID of the clipping path"),
        "contents":       _p(A, required=True, desc="Array of MCP IDs to clip"),
        "id":             _p(S, desc="ID for the clipping group"),
        "name":           _p(S, desc="Name for the clipping group"),
        "dryRun":         _p(B, desc="Preview without mutation"),
        "duplicate_mask": _p(B, desc="Duplicate mask as invisible clip; keep original visible (default true)"),
    }),

    # --- Z-order ops ---
    OpSchema(name="zorder_front", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor.',
            _NO_COORDINATES,
            'data {moved}; counts successful stacking changes.',
            {}, defaults={},
            constraints=[], select=True, prerequisites='An open document with the intended editable artwork selected.'), description="Bring to front"),
    OpSchema(name="zorder_back", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor.',
            _NO_COORDINATES,
            'data {moved}; counts successful stacking changes.',
            {}, defaults={},
            constraints=[], select=True, prerequisites='An open document with the intended editable artwork selected.'), description="Send to back"),
    OpSchema(name="zorder_forward", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor.',
            _NO_COORDINATES,
            'data {moved}; counts successful stacking changes.',
            {}, defaults={},
            constraints=[], select=True, prerequisites='An open document with the intended editable artwork selected.'), description="Bring forward one step"),
    OpSchema(name="zorder_backward", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor.',
            _NO_COORDINATES,
            'data {moved}; counts successful stacking changes.',
            {}, defaults={},
            constraints=[], select=True, prerequisites='An open document with the intended editable artwork selected.'), description="Send backward one step"),

    # --- Text ops ---
    OpSchema(name="text_create", route="typed_batch", requires_targets=False,
        documentation=_d('No selector required; creates artwork on params.layer, then batch default layer, then active layer.',
            _ARTBOARD_FRAME + ' Point text uses Illustrator position (bounds placement), not an explicit baseline anchor. Run baselineShift is a relative typographic offset in points, positive upward.',
            'Per-op text id; data {typename:"TextFrame",position:[x,y],contents}; position echoes artboard-relative input.',
            {'contents': 'Hello', 'x': 20, 'y': 40, 'fontSize': 18}, defaults={'x': 0, 'y': 0, 'fontSize': 12, 'id': 'generated'},
            constraints=['contents or runs is required; when both are supplied their text must match. Styled empty text is rejected before creation. fontName is an exact installed PostScript name; fontFamily resolves installed family metadata with optional fontStyle. Default style precedence: Regular, Roman, Book, Normal; ambiguous or absent defaults fail. fontName/fontFamily conflict; fontStyle requires fontFamily. Legacy PostScript fontFamily aliases warn and only work without fontStyle.'], select=False, prerequisites='An open Illustrator document.'), description="Create a text frame", params={
        "contents": _p(S, desc="Required without runs; must equal concatenated runs when both supplied"),
        "runs": _p(A, desc="Nonempty array of {text,fontName|fontFamily,fontStyle?,fontSize?,baselineShift?,fill?}; fontSize and baselineShift in points; no surrogate-pair splits. Fonts resolve before writes. Host character coverage is checked at runtime."),
        "id":       _p(S),
        "x":        _p(N),
        "y":        _p(N),
        "layer":    _p(S),
        "name":     _p(S),
        "fontSize": _p(N),
        "fontName": _p(S, desc="Exact installed PostScript name"),
        "fontFamily": _p(S, desc="Installed family; defaults to Regular, Roman, Book, Normal in order"),
        "fontStyle": _p(S, desc="Exact style label within fontFamily, trimmed and case-insensitive"),
        "fill":     _p(O, desc='Text fill color {r,g,b}'),
        "r":        _p(N, desc="Red 0-255 (compat — prefer fill.r)"),
        "g":        _p(N, desc="Green 0-255 (compat — prefer fill.g)"),
        "b":        _p(N, desc="Blue 0-255 (compat — prefer fill.b)"),
    }),
    OpSchema(name="text_set_content", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor. Non-TextFrames are skipped with warnings.',
            _NO_COORDINATES,
            'data {modified,modifiedIds,skippedIds?}.',
            {'contents': 'Updated text'}, defaults={},
            constraints=[], select=True, prerequisites='An open document with intended TextFrames selected.'), description="Replace text; native formatting inheritance is not a mixed-style preservation guarantee. Runs apply supplied attributes explicitly", params={
        "contents": _p(S, desc="Required without runs; must equal concatenated runs when both supplied"),
        "runs": _p(A, desc="Nonempty array of {text,fontName|fontFamily,fontStyle?,fontSize?,baselineShift?,fill?}; fontSize and baselineShift in points; no surrogate-pair splits. Fonts resolve before writes. Host character coverage is checked at runtime."),
    }),
    OpSchema(name="text_set_style", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor. Non-TextFrames are skipped with warnings.',
            _NO_COORDINATES,
            'data includes modified,modifiedIds,skippedIds? and resolved font details when requested.',
            {'fontSize': 18}, defaults={'unspecified attributes': 'retained'},
            constraints=['fontName and fontFamily are mutually exclusive. fontStyle requires fontFamily. Family default precedence: Regular, Roman, Book, Normal; ambiguous or absent defaults fail. Legacy PostScript aliases warn. Tracking is in 1/1000 em.'], select=True, prerequisites='An open document with intended TextFrames selected.'), description="Set text style", params={
        "fontSize":   _p(N),
        "fontName":   _p(S, desc="PostScript font name; unresolvable names fail"),
        "fontFamily": _p(S, desc="Installed font family; cannot combine with fontName"),
        "fontStyle": _p(S, desc="Style label within fontFamily; trimmed case-insensitive exact match"),
        "runs": _p(A, desc="Run text must exactly match every target before any styling. Attributes omitted from a run retain existing style; host character boundaries are verified before mutation."),
        "tracking":   _p(N, desc="Letter spacing, in 1/1000 em"),
        "fill":     _p(O, desc='Text fill color {r,g,b}'),
        "r":        _p(N, desc="Red 0-255 (compat — prefer fill.r)"),
        "g":        _p(N, desc="Green 0-255 (compat — prefer fill.g)"),
        "b":        _p(N, desc="Blue 0-255 (compat — prefer fill.b)"),
    }),

    # --- Alignment ops ---
    OpSchema(name="align_horizontal", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor. At least two targets to perform alignment; one produces aligned:0 with a warning.',
            _DOM_FRAME + " Explicit coordinate is a DOM X or Y value; no input artboard conversion is applied.",
            'data {aligned,source?}; source is coordinate/key_id/artboard/targets.',
            {'mode': 'center', 'reference': 'artboard'}, defaults={'mode': 'center', 'reference': 'targets'},
            constraints=['Reference precedence: explicit coordinate, key_id, reference. Missing key_id fails.'], select=True, prerequisites='An open document with at least two editable items selected.'), description="Align items horizontally", params={
        "mode":       _p(S, enum=["left", "center", "right"], desc="Alignment edge/center"),
        "reference":  _p(S, enum=["targets", "artboard"], desc="Reference source"),
        "key_id":     _p(S, desc="MCP ID of key object (others align to it)"),
        "coordinate": _p(N, desc="Explicit X coordinate (doc space, overrides key_id/reference)"),
    }),
    OpSchema(name="align_vertical", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor. At least two targets to perform alignment; one produces aligned:0 with a warning.',
            _DOM_FRAME + " Explicit coordinate is a DOM X or Y value; no input artboard conversion is applied.",
            'data {aligned,source?}; source is coordinate/key_id/artboard/targets.',
            {'mode': 'middle', 'reference': 'artboard'}, defaults={'mode': 'middle', 'reference': 'targets'},
            constraints=['Reference precedence: explicit coordinate, key_id, reference. Missing key_id fails.'], select=True, prerequisites='An open document with at least two editable items selected.'), description="Align items vertically", params={
        "mode":       _p(S, enum=["top", "middle", "bottom"], desc="Alignment edge/center"),
        "reference":  _p(S, enum=["targets", "artboard"], desc="Reference source"),
        "key_id":     _p(S, desc="MCP ID of key object (others align to it)"),
        "coordinate": _p(N, desc="Explicit Y coordinate (doc space, overrides key_id/reference)"),
    }),
    OpSchema(name="distribute_horizontal", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor. At least three targets to distribute; fewer produce distributed:0 and a warning.',
            'Spacing is a distance in points; existing DOM item geometry determines ordering.',
            'data {distributed,mode?}.',
            {'mode': 'gap'}, defaults={'mode': 'gap', 'spacing': 'automatic within target span'},
            constraints=['mode=center distributes centers; mode=gap distributes edge gaps.'], select=True, prerequisites='An open document with at least three editable items selected.'), description="Distribute items horizontally", params={
        "mode":    _p(S, enum=["gap", "center"], desc="Gap between edges or center-to-center"),
        "spacing": _p(N, desc="Fixed spacing; omit to auto-distribute within span"),
    }),
    OpSchema(name="distribute_vertical", route="typed_batch", requires_targets=True,
        documentation=_d('One or more resolved selector targets; an empty match fails in the executor. At least three targets to distribute; fewer produce distributed:0 and a warning.',
            'Spacing is a distance in points; existing DOM item geometry determines ordering.',
            'data {distributed,mode?}.',
            {'mode': 'gap'}, defaults={'mode': 'gap', 'spacing': 'automatic within target span'},
            constraints=['mode=center distributes centers; mode=gap distributes edge gaps.'], select=True, prerequisites='An open document with at least three editable items selected.'), description="Distribute items vertically", params={
        "mode":    _p(S, enum=["gap", "center"], desc="Gap between edges or center-to-center"),
        "spacing": _p(N, desc="Fixed spacing; omit to auto-distribute within span"),
    }),

    # --- Assert ops ---
    OpSchema(name="assert_count", route="typed_batch", requires_targets=False,
        documentation=_d('Zero or more selected targets; counts the resolved set.',
            _NO_COORDINATES,
            'data {expected,actual,operator,layer}.',
            {'expected': 1}, defaults={'operator': 'eq'},
            constraints=[], select=True, prerequisites='An open document with exactly one item selected for this passing example.'), description="Assert item count", params={
        "expected": _p(N, required=True),
        "operator": _p(S, enum=["eq", "gte", "lte", "gt", "lt"]),
    }),
    OpSchema(name="assert_bounds", route="typed_batch", requires_targets=False,
        documentation=_d('Zero or more targets; checks each axis-aligned left/top/width/height box.',
            _DOM_FRAME,
            'data {inBounds,outOfBounds,artboardBounds,details}; details limited to first five failures.',
            {}, defaults={'artboardIndex': 'active artboard'},
            constraints=['Current handler uses a truthy fallback: explicit 0 selects the active artboard if another is active.'], select=True, prerequisites='An open document with selected artwork inside the active artboard.'), description="Assert items within bounds", params={
        "artboardIndex": _p(N),
    }),
    OpSchema(name="assert_exists", route="typed_batch", requires_targets=False,
        documentation=_d('Selector ignored; params.ids names MCP IDs to find in the document.',
            _NO_COORDINATES,
            'data {found,missing}.',
            {'ids': ['catalogue_item']}, defaults={},
            constraints=[], select=False, prerequisites='An open document containing an item with MCP ID catalogue_item.'), description="Assert items exist by ID", params={
        "ids": _p(A, required=True),
    }),
    OpSchema(name="assert_style", route="typed_batch", requires_targets=False,
        documentation=_d('Zero or more targets; checks only supplied style properties.',
            _NO_COORDINATES,
            'data {passed,failed,details}; repair adds violations_before,repaired,violations_after and postcondition information.',
            {'opacity': 100}, defaults={'tolerance': 1, 'repair': False},
            constraints=['Supports RGB/CMYK comparisons. repair=true mutates artwork; inspect postconditions. Failure details limited to ten.'], select=True, prerequisites='An open document with selected artwork at 100 percent opacity.'), description="Assert style properties", params={
        "fill":        _p(O),
        "stroke":      _p(O),
        "strokeWidth": _p(N),
        "opacity":     _p(N),
        "tolerance":   _p(N),
        "repair":      _p(B),
    }),
    OpSchema(name="assert_text", route="typed_batch", requires_targets=False,
        documentation=_d('Zero or more targets; verifies TextFrames; non-text targets fail the assertion.',
            _NO_COORDINATES,
            'data {passed,failed,details}; details limited to ten failures.',
            {'contents': 'Hello'}, defaults={'matchMode': 'exact', 'caseSensitive': True},
            constraints=['matchMode supports exact/contains/regex; invalid regex fails.'], select=True, prerequisites='An open document with TextFrames containing Hello selected.'), description="Assert text content", params={
        "contents":      _p(S, required=True),
        "matchMode":     _p(S, enum=["exact", "contains", "regex"]),
        "caseSensitive": _p(B),
    }),
    OpSchema(name="assert_alignment", route="typed_batch", requires_targets=False,
        documentation=_d('Zero or one target is vacuously aligned; two or more enable positional checking.',
            _DOM_FRAME,
            'data {mode,referenceValue?,aligned,misaligned,details}; optional repair/spacing reports.',
            {'mode': 'left'}, defaults={'tolerance': 1, 'repair': False},
            constraints=['repair=true can move artwork. The nonempty-target flag does not imply a two-item minimum here.'], select=True, prerequisites='An open document with left-aligned artwork selected.'), description="Assert alignment", params={
        "mode":      _p(S, required=True, enum=["left", "centerX", "right",
                         "top", "centerY", "bottom"]),
        "tolerance": _p(N),
        "spacing":   _p(N),
        "repair":    _p(B),
    }),
    OpSchema(name="assert_z_order", route="typed_batch", requires_targets=False,
        documentation=_d('Selector ignored; above/below or each pair names two existing MCP IDs.',
            _NO_COORDINATES,
            'data {total,passed,failed,details?}.',
            {'above': 'catalogue_top', 'below': 'catalogue_bottom'}, defaults={},
            constraints=['Supply above and below together or a nonempty pairs array. Lower layer/item index is above.'], select=False, prerequisites='An open document with catalogue_top above catalogue_bottom (MCP IDs).'), description="Assert z-order between items", params={
        "above": _p(S, desc="MCP ID that should be above"),
        "below": _p(S, desc="MCP ID that should be below"),
        "pairs": _p(A, desc="Array of [aboveId, belowId] pairs for batch check"),
    }),
    OpSchema(name="assert_layer_order", route="typed_batch", requires_targets=False,
        documentation=_d('Selector ignored; order requires at least two distinct existing layer names, listed from top to bottom.',
            _NO_COORDINATES,
            'data {expectedOrder,actualOrder,missing?,violations?}.',
            {'order': ['Catalogue top', 'Catalogue bottom']}, defaults={'strict': False},
            constraints=['At least two layer names are required; shorter arrays fail with V006. Default checks monotonicity, permitting other layers; strict=true additionally checks layer count.'], select=False, prerequisites='An open document with layers named Catalogue top and Catalogue bottom, with Catalogue top above Catalogue bottom.'), description="Assert layer stacking order (monotonicity check)", params={
        "order":  _p(A, required=True, desc="At least two existing layer names, top-to-bottom"),
        "strict": _p(B, desc="Exact match (no extra layers) if true"),
    }),

    # --- Measure/snapshot ops ---
    OpSchema(name="measure_bounds", route="typed_batch", requires_targets=False,
        documentation=_d('Zero or more targets; typed route requires a targets field, but an empty resolved set is valid.',
            _DOM_FRAME,
            'data {bounds:null} when empty; otherwise {bounds:{left,top,right,bottom,width,height},itemCount}.',
            {}, defaults={},
            constraints=[], select=True, prerequisites='An open document with the intended editable artwork selected.'), description="Measure item bounds"),
    OpSchema(name="snapshot_structure", route="typed_batch", requires_targets=False,
        documentation=_d('Selector ignored; captures document-level layer structure.',
            _NO_COORDINATES,
            'data {documentName,artboards:number,selection:number,timestamp,layers:[{name,visible,locked,itemCount,items?}]}; items contain name,typename,bounds:[left,top,width,height] in document points, Y-up.',
            {'includeItems': False}, defaults={'includeItems': False},
            constraints=[], select=False, prerequisites='An open Illustrator document.'), description="Capture document structure", params={
        "includeItems": _p(B),
    }),
    OpSchema(name="hash_structure", route="typed_batch", requires_targets=False,
        documentation=_d('Selector ignored; hashes document-level structure.',
            _NO_COORDINATES,
            'data {hash:string,components:number}; non-cryptographic structural digest.',
            {}, defaults={},
            constraints=[], select=False, prerequisites='An open Illustrator document.'), description="Hash document structure"),

    # --- Compound ops ---
    OpSchema(name="compound", route="typed_batch", requires_targets=False,
        documentation=_d('Top-level selector is not inherited; each sub-operation supplies its own targets.',
            'Each sub-operation uses its own documented coordinate frame.',
            'data {lastId,createdIds,passed,failed,results,recovery}; inspect each nested result.',
            {'ops': [{'task': 'layer_list', 'params': {}}]}, defaults={'atomic': False},
            constraints=['No nested compounds. atomic=true is unsupported and rejects before sub-operations. $prev/$prevAll are allowed only inside type:id targets.ids; previous operation must have produced matching IDs. Failures can retain earlier edits.'], select=False, prerequisites='An open Illustrator document.'), description="Sequence sub-ops with $prev ID forwarding", params={
        "ops":    _p(A, required=True),
        "atomic": _p(B),
    }),

    # --- Boolean ops ---
    OpSchema(name="path_boolean", route="python_tool", requires_targets=False,
        documentation=_d('Subject is one MCP ID or canonical {target:{...}} selector; clip is one operand or an ordered list of 1..100 operands. Each selector must resolve exactly one path. Handle selectors support untagged artwork without note writes.',
            _DOM_FRAME + " Curves are flattened in points by the Python geometry engine.",
            'Canonical data {ids,itemTypes,regionCount,originals,effects,status,atomic:false,message}; originals reports retained/deleted/partial status and deleted/failed/missing IDs. Canonical effects reports known edits.',
            {'operation': 'unite', 'subject': 'catalogue_subject', 'clip': ['catalogue_clip'], 'delete_originals': False}, defaults={'flatten_tolerance': 0.5, 'max_segments': 500, 'delete_originals': True, 'style': 'subject'},
            constraints=['Separate Python tool only; not dispatchable in JSX batches. Requires optional geometry dependency pyclipper; static availability is not installation/connection health. Tolerance must be finite, >0 and <=100; max_segments is 1..100000.', 'Selector operands are captured as exact handles at extraction and revalidated at commit. Duplicate/overlapping operands, expired handles and changed geometry/style/context are refused. Use inputSchema for the full Python operand union; broad SOC parameter types do not define this Python-only route.'], select=False, prerequisites='An open document with valid paths catalogue_subject and catalogue_clip (MCP IDs); install the geometry extra.'), description="Boolean op on paths (via Python Clipper engine)", params={
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


def unknown_param_message(task: str, unknown: list) -> str:
    """Shared near-miss guidance for broad and typed validation."""
    from difflib import get_close_matches

    allowed = list(get_op_schema(task).params)
    parts = []
    for name in unknown:
        near = get_close_matches(name, allowed, n=1, cutoff=0.7)
        parts.append(f"{name!r} (did you mean {near[0]!r}?)" if near else repr(name))
    return f"Unknown parameter(s) for {task}: {', '.join(parts)}. Allowed: {', '.join(sorted(allowed))}"


def validate_op_params(task: str, params=None) -> dict:
    """Validate the static JSX contract without resolving DOM targets.

    Optional nulls and object false sentinels preserve compatibility. Fields
    defer value checks. Audited empty catalogues take no parameters.
    """
    import math

    errors = []

    def error(code, field, message):
        errors.append({"code": code, "operation": task, "field": field,
                       "message": f"{task}.{field}: {message}", "stage": "validate"})

    schema = get_op_schema(task) if isinstance(task, str) else None
    if schema is None or schema.backend != "jsx":
        error("V008", "task", "Expected a supported JSX operation; read illustrator://ops")
    elif params is not None and not isinstance(params, dict):
        error("V007", "params", "Expected object")
    else:
        params = params or {}
        for key in schema.required_params:
            if params.get(key) is None:
                error("V006", key, "Missing required parameter")
        for key, value in params.items():
            definition = schema.params.get(key)
            if definition is None:
                error("V008", key, unknown_param_message(task, [key]))
                continue
            if value is None or (isinstance(value, dict) and isinstance(value.get("$field"), str)):
                continue
            expected = definition.type.value
            actual = ("boolean" if isinstance(value, bool) else "number" if isinstance(value, (int, float))
                      else "string" if isinstance(value, str) else "object" if isinstance(value, dict)
                      else "array" if isinstance(value, list) else "invalid")
            if expected == "object" and value is False:
                continue
            if actual != expected or (actual == "number" and not math.isfinite(value)):
                error("V007", key, f"Expected finite {expected}, got {actual}")
            elif definition.enum_values and value not in definition.enum_values:
                error("V008", key, "Expected one of: " + ", ".join(definition.enum_values))
    return {"ok": not errors, "errors": errors}


def render_operation_index() -> str:
    """Compact description index; metadata does not register host handlers."""
    typed = sorted(op.name for op in OP_SCHEMAS if op.route == "typed_batch")
    lines = ["      SUPPORTED_BATCH_OPERATIONS: [" + ", ".join(typed) + "]",
             "      Operation catalogue: illustrator://ops; details: illustrator://ops/{name}.",
             "      Routes: B=batch.operations (also payload); P=payload.params.ops; Y=illustrator_path_boolean.",
             "      Target flag *=nonempty selector required; absence does not specify cardinality."]
    for op in OP_SCHEMAS:
        route = {"typed_batch": "B", "compatibility_payload": "P", "python_tool": "Y"}[op.route]
        lines.append(f"      {route}{'*' if op.requires_targets else ' '} {op.name}: {op.description}")
    lines.append("      Catalogue membership does not enable dispatch; a runtime handler is required.")
    return "\n".join(lines)
