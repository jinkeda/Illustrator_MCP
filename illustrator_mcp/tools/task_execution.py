"""
Path Boolean and Execute Task tools.

Contains the structured task protocol tool (execute_task) and the
Python-Clipper-backed path boolean tool (path_boolean).
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional, Union, get_args

from illustrator_mcp.tools.base import MutationInputBase
from illustrator_mcp.protocol import TaskOptions
from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator
from mcp.types import CallToolResult, ImageContent, TextContent

from illustrator_mcp.shared import mcp
from illustrator_mcp.execution.coordinator import HostUnresolvedError
from illustrator_mcp.execution import (
    DuplicateJobError,
    JobCancelledError,
    JobConflictError,
    JobStatus,
    get_coordinator,
    request_digest,
)
from illustrator_mcp.proxy_client import (
    note_host_truncation,
    build_envelope_dict,
    format_envelope,
    clear_reserved_job,
    execute_script_with_context,
    mark_reserved_job,
)
from illustrator_mcp.errors import make_envelope
from illustrator_mcp.results import (
    CanonicalResult,
    Effects,
    ExecutionStatus,
    build_call_result,
    finalize_tool_result,
)
from illustrator_mcp.protocol import TaskPayload, TaskReport, TargetSelector, format_task_report
from illustrator_mcp.utils.response import describe_truncation
from illustrator_mcp.tools import evidence
from illustrator_mcp.tools.base import (
    ToolInputBase, TOOL_ANNOTATIONS, declare_effects,
    forbid_extra_tool_arguments,
)
from illustrator_mcp.tools.cadence import (
    _counter, VLM_QA_CADENCE,
    format_z_telemetry,
)
from illustrator_mcp.tools.preview import (
    _capture_artboard, _annotate_preview, CaptureOptions, capture_frame,
    _guard_checkpoint, GuardCheckpointResult,
)

logger = logging.getLogger("illustrator_mcp")

_TEMPLATES_DIR = Path(__file__).parent.parent / "resources" / "templates"

#: Bytes of per-operation ``op.data`` a single batch report may carry (T11).
#: Identities, statuses and errors are ALWAYS kept and are not counted against
#: this; only the optional per-op payload is budgeted. When it is exceeded the
#: affected ops are marked ``dataOmitted`` and the report carries a
#: ``truncation`` block — detail is never dropped silently.
_OP_DATA_BUDGET_BYTES = 60000


def _taskreport_first_error(report_data: dict, task_name: str) -> dict:
    """Extract first TaskReport error into canonical {code, message, suggestions} shape.

    Handles nested ``{ok, error:{...}}`` shapes from ``makeError()``
    and falls back to :func:`create_structured_error` for unknown formats.
    """
    from illustrator_mcp.errors import create_structured_error

    errors = report_data.get("errors", [])
    if not errors:
        return {"code": "R009", "message": f"Task '{task_name}' failed", "suggestions": []}

    first = errors[0]
    # Unwrap nested {ok, error:{...}} shape from makeError()
    if isinstance(first, dict) and "error" in first and isinstance(first["error"], dict):
        first = first["error"]

    if isinstance(first, dict) and "code" in first and "message" in first:
        out = {
            "code": first["code"],
            "message": first["message"],
            "suggestions": first.get("suggestions", []),
        }
        out["operation"] = first.get("operation", task_name)
        return out

    # Fallback: classify via create_structured_error
    msg = first.get("message", str(first)) if isinstance(first, dict) else str(first)
    s = create_structured_error(msg)
    return {
        "code": s.code, "message": s.message,
        "suggestions": s.suggestions, "operation": task_name,
    }


def _host_payload(response: Any, step: str) -> tuple[Optional[dict], Optional[str]]:
    """Validate a bridge response and return the JSX payload it carries.

    Returns ``(payload, None)`` **only** when the host demonstrably returned a
    well-formed, successful result for *step*.  Every other case — transport
    error, timeout, missing ``result`` key, null result, unparseable JSON,
    non-object payload, or an in-band ``error`` flag — returns
    ``(None, message)``.

    T01: a missing or unparseable response is an *uncertain* outcome, never
    proof of success.  Callers must not perform destructive follow-up work
    (deleting originals) on anything but a ``(payload, None)`` return.
    """
    if not isinstance(response, dict):
        return None, (
            f"{step}: malformed transport response "
            f"({type(response).__name__}) — outcome unknown"
        )

    # Transport / injection / bridge-level failure (includes R_TIMEOUT).
    top_error = response.get("error")
    if top_error:
        msg = top_error.get("message", str(top_error)) if isinstance(top_error, dict) else str(top_error)
        return None, f"{step}: {msg}"

    # A response with no 'result' key tells us nothing about what the host did.
    if "result" not in response:
        return None, f"{step}: host returned no result — outcome unknown"

    raw = response["result"]
    if raw is None:
        return None, f"{step}: host returned a null result — outcome unknown"

    # Unwrap until stable.
    #
    # The host envelope can arrive at any depth of encoding: the bridge may
    # hand back the {ok, data} envelope already parsed, or as a JSON *string*,
    # and `data` itself is frequently another JSON string because the JSX
    # helper returned JSON.stringify(...). A single pass only handles one of
    # those shapes — it skipped the envelope unwrap whenever `result` arrived
    # as a string, and returned {"ok": true, "data": "{...}"} as though it
    # were the payload. Loop instead, with a bound so a pathological value
    # cannot spin.
    for _ in range(6):
        if isinstance(raw, str):
            stripped = raw.strip()
            if not stripped:
                return None, f"{step}: host returned an empty result — outcome unknown"
            # `"` is allowed because a JSON-encoded JSON string is itself
            # valid JSON; the loop simply unwraps one more layer.
            if stripped[0] not in '[{"':
                return None, (
                    f"{step}: host result is not JSON: {stripped[:200]}"
                )
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:
                # Ask the shared decoder first. This is the path the large
                # boolean geometry extraction takes, and it was reporting a
                # cut transfer as a script syntax error long after the
                # decoder existed, because nothing here called it.
                cut = describe_truncation(stripped)
                if cut:
                    return None, f"{step}: {cut}"
                return None, (
                    f"{step}: could not parse host result ({exc}): "
                    f"{stripped[:200]}"
                )
            continue

        if isinstance(raw, dict):
            # A host envelope, not the payload — step inside it.
            if "ok" in raw and "data" in raw:
                if raw.get("ok") is False:
                    inner = raw.get("error")
                    msg = (
                        inner.get("message", str(inner))
                        if isinstance(inner, dict)
                        else str(inner or "unknown host error")
                    )
                    return None, f"{step}: {msg}"
                raw = raw.get("data")
                continue
            if raw.get("ok") is False:
                inner = raw.get("error")
                msg = (
                    inner.get("message", str(inner))
                    if isinstance(inner, dict)
                    else str(inner or "unknown host error")
                )
                return None, f"{step}: {msg}"
        break

    if not isinstance(raw, dict):
        return None, (
            f"{step}: host result is {type(raw).__name__}, expected an object "
            f"— outcome unknown"
        )

    # In-band error flag emitted by geo_boolean.jsx helpers.
    if raw.get("error"):
        msg = raw.get("message", "host reported an error")
        code = raw.get("errorCode")
        detail = f"[{code}] {msg}" if code else msg
        return None, f"{step}: {detail}"

    return raw, None


def _op_level_warnings(report_data: dict) -> list:
    """Surface per-operation warnings on the top-level result.

    A warning buried in ``batchReport.ops[i].warnings`` is invisible to an
    agent that reads the summary — which is the normal case. The one that
    matters most here is a requested target that matched nothing: without
    lifting it, styling ["S0", "GHOST"] reported success with an empty
    top-level warnings list and no mention of GHOST anywhere a caller looks.
    """
    lifted: list = []
    if not isinstance(report_data, dict):
        return lifted
    batch = report_data.get("batchReport")
    if not isinstance(batch, dict):
        return lifted
    for op in batch.get("ops") or []:
        if not isinstance(op, dict):
            continue
        label = op.get("task") or f"op {op.get('index')}"
        for warning in op.get("warnings") or []:
            lifted.append(f"[{label}] {warning}")
    return lifted


def _dedup_warnings(*warning_lists: list) -> list:
    """Merge warning lists preserving order, removing duplicates."""
    seen: set = set()
    result: list = []
    for wl in warning_lists:
        for w in (wl or []):
            if w not in seen:
                seen.add(w)
                result.append(w)
    return result


_jsx_template_cache: dict[str, tuple[int, str]] = {}  # name → (mtime_ns, content)


def _load_jsx_template(name: str) -> str:
    """Load a .jsx template from resources/templates/ (mtime-cached).

    Uses st_mtime_ns for cache invalidation so template changes are
    picked up without server restart. One stat() call per load (~0.1ms).
    """
    path = _TEMPLATES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"JSX template not found: {path}")
    mtime_ns = path.stat().st_mtime_ns
    cached = _jsx_template_cache.get(name)
    if cached and cached[0] == mtime_ns:
        return cached[1]
    content = path.read_text(encoding="utf-8")
    _jsx_template_cache[name] = (mtime_ns, content)
    return content


def _batch_operation_names(params) -> list:
    """The operations this call will run, for the evidence policy.

    A structured batch carries them under ``params.ops``; the compatibility
    payload names a single task. Both forms end up in the same place, so the
    policy sees the same operations regardless of which the caller used.
    """
    payload = getattr(params, "payload", None)
    if payload is None:
        return []
    ops = (payload.params or {}).get("ops")
    if isinstance(ops, list):
        names = [op.get("task") for op in ops if isinstance(op, dict)]
        found = [n for n in names if isinstance(n, str)]
        if found:
            return found
    return [payload.task] if isinstance(payload.task, str) else []


def _uncontracted_params(task: str, params) -> list:
    """Parameter names the contract SSOT does not define for *task*.

    Audited empty catalogues accept no parameter keys.
    """
    from illustrator_mcp.schemas.contracts import get_op_schema

    schema = get_op_schema(task)
    if schema is None:
        return []
    return sorted(name for name in params if name not in schema.params)


def _unknown_param_error(task: str, unknown: list) -> str:
    """Explain unknown parameters, suggesting the name that was probably meant.

    An agent that gets "unknown parameter" alone tends to retry with another
    guess.  Naming the near miss usually ends the exchange in one turn.
    """
    from illustrator_mcp.schemas.contracts import unknown_param_message

    return unknown_param_message(task, unknown)


class _CreatePilotParams(BaseModel):
    """Typed pilot surface; extra fields are checked against the contract SSOT.

    ``extra="allow"`` keeps the ~25 catalogued element_create parameters this
    model does not spell out (star and polygon geometry, smoothing, mirroring,
    text, clipTo) reachable without duplicating the catalogue here.  The
    validator below is what makes that safe: an extra the contract does not
    define is rejected rather than passed through.  It used to be passed
    through on the claim that the SSOT checked it, and the SSOT did not.
    """

    model_config = ConfigDict(extra="allow")
    type: Literal[
        "rect", "ellipse", "line", "path", "polyline", "polygon", "star",
        "roundedRect", "text",
    ]
    id: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    points: Optional[List[Any]] = None
    geometry: Optional[Dict[str, Any]] = None
    closed: Optional[bool] = None
    layer: Optional[str] = None
    name: Optional[str] = None
    fill: Optional[Any] = None
    stroke: Optional[Any] = None
    opacity: Optional[float] = Field(None, ge=0, le=100)

    @model_validator(mode="after")
    def _reject_uncontracted_params(self):
        unknown = _uncontracted_params("element_create", self.__pydantic_extra__ or {})
        if unknown:
            raise ValueError(_unknown_param_error("element_create", unknown))
        return self

    @model_validator(mode="after")
    def _validate_path_geometry(self):
        if self.type in ("path", "polyline") and self.points is None and self.geometry is None:
            raise ValueError("path and polyline creation require points or geometry")
        return self


class _OpacityPilotParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    opacity: float = Field(..., ge=0, le=100)


class _NoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _CreateMultiParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    geometry: Dict[str, Any]
    layer: Optional[str] = None
    name: Optional[str] = None
    fill: Optional[Any] = None
    stroke: Optional[Any] = None
    styles: Optional[List[Dict[str, Any]]] = None
    styleScalars: Optional[List[float]] = None
    palette: Optional[Dict[str, Any]] = None
    offset: int = Field(0, ge=0)
    limit: Optional[int] = Field(None, gt=0)


class _CreateMultiByRefParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    irKey: str = Field(..., min_length=1)
    offset: int = Field(0, ge=0)
    limit: Optional[int] = Field(None, gt=0)
    layer: Optional[str] = None
    name: Optional[str] = None
    fill: Optional[Any] = None
    stroke: Optional[Any] = None
    styles: Optional[List[Dict[str, Any]]] = None
    styleScalars: Optional[List[float]] = None
    palette: Optional[Dict[str, Any]] = None


#: Exactly what each reader in ops_element.jsx looks at, per shape. These are
#: transcribed from the reader, not from the docstring: the first version of
#: this was derived from a grep and got three of them wrong, which broke input
#: that had been working.
#:
#: Item shapes (the heterogeneous `items` list).
_BATCH_ITEM_COMMON = frozenset({"type", "style"})
_BATCH_ITEM_KEYS_BY_TYPE = {
    "rect": frozenset({"x", "y", "w", "h"}),
    "ellipse": frozenset({"cx", "cy", "r", "rx", "ry"}),
    "line": frozenset({"points", "closed"}),
    "path": frozenset({"points", "closed"}),
    "polyline": frozenset({"points", "closed"}),
}
_BATCH_ITEM_KEYS = _BATCH_ITEM_COMMON.union(*_BATCH_ITEM_KEYS_BY_TYPE.values())

#: Template shapes. A template supports polygon and star, which items do not,
#: and its polygon branch reads ``radius`` — so the ellipse-only alias from
#: ``radius`` to ``r`` must never reach it.
_BATCH_TEMPLATE_COMMON = frozenset({
    "type", "fill", "stroke", "opacity", "noFill", "noStroke",
})
_BATCH_TEMPLATE_KEYS_BY_TYPE = {
    "rect": frozenset({"w", "h"}),
    "ellipse": frozenset({"r", "rx", "ry"}),
    "line": frozenset({"points"}),
    "path": frozenset({"points", "closed"}),
    "polyline": frozenset({"points", "closed"}),
    "polygon": frozenset({"sides", "radius"}),
    "star": frozenset({"numPoints", "points", "outerRadius", "innerRadius"}),
}
_BATCH_TEMPLATE_KEYS = _BATCH_TEMPLATE_COMMON.union(
    *_BATCH_TEMPLATE_KEYS_BY_TYPE.values()
)

#: Per-instance overrides the template reader honours. It reads scale, fill,
#: stroke and opacity as well as position; allowing only x and y rejected four
#: working overrides.
_BATCH_INSTANCE_KEYS = frozenset({"x", "y", "scale", "fill", "stroke", "opacity"})
_BATCH_ARRAY_KEYS = frozenset({
    "count", "cols", "startX", "startY", "spacingX", "spacingY",
})

#: The reader's own default radius for an ellipse, needed to convert a
#: top-left position when no size was given.
_ELLIPSE_DEFAULT_RADIUS = 5


def _rename(out: dict, source: str, target: str, label: str, halve=False) -> None:
    """Move one field onto its batch spelling, refusing a contradiction."""
    if source not in out:
        return
    if target in out:
        raise ValueError(
            f"{label} sets both {source!r} and {target!r}; they mean the same "
            f"thing, so pass only one"
        )
    value = out.pop(source)
    if halve:
        try:
            value = value / 2
        except TypeError:
            raise ValueError(
                f"{label}: {source!r} must be a number to convert to {target!r}"
            ) from None
    out[target] = value


def _ellipse_to_centre(out: dict, label: str) -> None:
    """Convert a top-left x/y into the centre the ellipse reader expects.

    Single-element creation positions an ellipse by its top-left corner, and
    the batch reader positions it by its centre: it computes the left edge as
    ``cx - rx``. Renaming x to cx therefore moved the shape by one radius,
    which is how ``x=100, width=40`` landed at 80. The two conventions have to
    be reconciled by arithmetic, not by spelling.
    """
    # No early return when both are absent. Single creation defaults the
    # corner to zero and puts the top-left edge at zero; leaving cx and cy
    # unset let the reader default the *centre* to zero, which puts that edge
    # at minus the radius. Omitting both coordinates has to mean the same
    # place in either API, so the default is converted like any other value.
    rx = out.get("rx", out.get("r", _ELLIPSE_DEFAULT_RADIUS))
    ry = out.get("ry", out.get("r", _ELLIPSE_DEFAULT_RADIUS))
    # Each axis is settled on its own, so a half-given position behaves like a
    # full one and an omitted one lands where single creation puts it.
    for axis, radius, target in (("x", rx, "cx"), ("y", ry, "cy")):
        if target in out:
            # The caller used centre semantics for this axis; leave it alone.
            if axis in out:
                raise ValueError(
                    f"{label} sets both {axis!r} and {target!r}. {axis!r} is "
                    f"the top-left corner and {target!r} is the centre, so "
                    f"pass only one"
                )
            continue
        try:
            out[target] = out.pop(axis, 0) + radius
        except TypeError:
            raise ValueError(
                f"{label}: {axis!r} and the radius must be numbers"
            ) from None


def _normalise_batch_spec(spec: dict, allowed: frozenset, label: str) -> dict:
    """Map the single-element spellings onto batch ones, then reject leftovers.

    Rejecting matters more than aliasing: the batch reader resolves each field
    with a fallback chain, so an unknown key silently becomes a default. The
    batch then reports success and the artwork is quietly wrong, which is far
    harder to notice than an error.

    Aliasing is per shape because the readers differ. A polygon template reads
    ``radius`` directly, so mapping it to ``r`` there breaks a working input
    rather than fixing one.
    """
    out = dict(spec)
    shape = str(out.get("type", "")).lower()
    is_template = allowed is _BATCH_TEMPLATE_KEYS

    if shape in ("ellipse", "circle"):
        _rename(out, "radius", "r", label)
        _rename(out, "width", "rx", label, halve=True)
        _rename(out, "height", "ry", label, halve=True)
        if not is_template:
            # Only items carry a position; a template is positioned by its
            # instances or its array.
            _ellipse_to_centre(out, label)
    elif shape in ("polygon", "star"):
        # These read `radius`, `outerRadius` and `innerRadius` as they are.
        pass
    else:
        _rename(out, "width", "w", label)
        _rename(out, "height", "h", label)

    by_type = (
        _BATCH_TEMPLATE_KEYS_BY_TYPE if is_template else _BATCH_ITEM_KEYS_BY_TYPE
    )
    common = _BATCH_TEMPLATE_COMMON if is_template else _BATCH_ITEM_COMMON
    if shape in by_type and allowed in (_BATCH_ITEM_KEYS, _BATCH_TEMPLATE_KEYS):
        allowed = common | by_type[shape]

    unknown = sorted(k for k in out if k not in allowed)
    if unknown:
        from difflib import get_close_matches

        # Suggest against what a caller may legitimately type, which includes
        # the single-element spellings normalised above. Offering only the
        # post-alias names meant "hieght" matched nothing at all.
        spellings = set(allowed) | {"width", "height", "radius"}
        parts = []
        for name in unknown:
            near = get_close_matches(name, sorted(spellings), n=1, cutoff=0.7)
            parts.append(f"{name!r} (did you mean {near[0]!r}?)" if near else repr(name))
        raise ValueError(
            f"Unknown field(s) in {label}: {', '.join(parts)}. "
            f"Allowed: {', '.join(sorted(allowed))}"
        )
    return out


class _CreateBatchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template: Optional[Dict[str, Any]] = None
    instances: Optional[List[Dict[str, Any]]] = None
    items: Optional[List[Dict[str, Any]]] = None
    array: Optional[Dict[str, Any]] = None
    defaultStyle: Optional[Dict[str, Any]] = None
    layer: Optional[str] = None
    name: Optional[str] = None

    @model_validator(mode="after")
    def _check_nested_specs(self):
        if self.items is not None:
            self.items = [
                _normalise_batch_spec(item, _BATCH_ITEM_KEYS, f"items[{n}]")
                for n, item in enumerate(self.items)
            ]
        if self.template is not None:
            self.template = _normalise_batch_spec(
                self.template, _BATCH_TEMPLATE_KEYS, "template"
            )
        if self.instances is not None:
            self.instances = [
                _normalise_batch_spec(inst, _BATCH_INSTANCE_KEYS, f"instances[{n}]")
                for n, inst in enumerate(self.instances)
            ]
        if self.array is not None:
            self.array = _normalise_batch_spec(
                self.array, _BATCH_ARRAY_KEYS, "array"
            )
        return self

    @model_validator(mode="after")
    def _one_batch_shape(self):
        template_mode = self.template is not None and (self.instances is not None or self.array is not None)
        items_mode = self.items is not None
        if template_mode == items_mode:
            raise ValueError("Use either items, or template with instances/array")
        return self


class _ElementModifyParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = Field(None, gt=0)
    height: Optional[float] = Field(None, gt=0)
    rotation: Optional[float] = None
    scale: Optional[float] = Field(None, gt=0)
    scaleX: Optional[float] = Field(None, gt=0)
    scaleY: Optional[float] = Field(None, gt=0)
    name: Optional[str] = None
    fill: Optional[Any] = None
    stroke: Optional[Any] = None
    opacity: Optional[float] = Field(None, ge=0, le=100)
    layer: Optional[str] = None


class _ElementReplaceParams(_CreatePilotParams):
    inheritPosition: bool = True


class _PilotOperationBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: Optional[TargetSelector] = None
    id: Optional[str] = None
    comment: Optional[str] = None
    when: Optional[Dict[str, Any]] = None
    unless: Optional[Dict[str, Any]] = None


class CreatePilotOperation(_PilotOperationBase):
    task: Literal["element_create"]
    params: _CreatePilotParams


class OpacityPilotOperation(_PilotOperationBase):
    task: Literal["style_set_opacity"]
    targets: TargetSelector
    params: _OpacityPilotParams


class MeasurePilotOperation(_PilotOperationBase):
    task: Literal["measure_bounds"]
    targets: TargetSelector
    params: _NoParams = Field(default_factory=_NoParams)


class DeletePilotOperation(_PilotOperationBase):
    task: Literal["element_delete"]
    targets: TargetSelector
    params: _NoParams = Field(default_factory=_NoParams)


class CreateMultiOperation(_PilotOperationBase):
    task: Literal["element_create_multi"]
    params: _CreateMultiParams


class CreateMultiByRefOperation(_PilotOperationBase):
    task: Literal["element_create_multi_by_ref"]
    params: _CreateMultiByRefParams


class CreateBatchOperation(_PilotOperationBase):
    task: Literal["element_create_batch"]
    params: _CreateBatchParams


class ElementModifyOperation(_PilotOperationBase):
    task: Literal["element_modify"]
    targets: TargetSelector
    params: _ElementModifyParams


class ElementReplaceOperation(_PilotOperationBase):
    task: Literal["element_replace"]
    targets: TargetSelector
    params: _ElementReplaceParams


class _ContractOperation(_PilotOperationBase):
    """SSOT broad parameter validation; nested values retain handler contracts."""

    params: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self):
        from illustrator_mcp.schemas.contracts import validate_op_params

        result = validate_op_params(self.task, self.params)
        if not result["ok"]:
            raise ValueError("; ".join(error["message"] for error in result["errors"]))
        return self


def _batch_operation_models():
    """Derive the vocabulary from the SSOT, retaining stronger pilot models."""
    from illustrator_mcp.schemas.contracts import OP_SCHEMAS

    pilots = [CreatePilotOperation, OpacityPilotOperation, MeasurePilotOperation,
              DeletePilotOperation, CreateMultiOperation, CreateMultiByRefOperation,
              CreateBatchOperation, ElementModifyOperation, ElementReplaceOperation]
    by_name = {get_args(model.model_fields["task"].annotation)[0]: model for model in pilots}
    models = []
    for schema in OP_SCHEMAS:
        if schema.backend != "jsx":
            continue
        model = by_name.get(schema.name)
        if model is None:
            fields = {"task": (Literal[schema.name], ...)}
            if schema.requires_targets:
                fields["targets"] = (TargetSelector, ...)
            model = create_model(
                "".join(word.title() for word in schema.name.split("_")) + "Operation",
                __base__=_ContractOperation, __module__=__name__, **fields,
            )
        models.append(model)
    return tuple(models)


# Retain the old import name for consumers; it now describes every JSX op.
PilotOperation = Annotated[Union[_batch_operation_models()], Field(discriminator="task")]


class StructuredPilotBatch(BaseModel):
    """Versioned batch contract for the full JSX operation vocabulary."""
    model_config = ConfigDict(extra="forbid")

    version: Literal["1.0"] = "1.0"
    operations: List[PilotOperation] = Field(..., min_length=1)
    mode: Literal["apply", "validate"] = "apply"
    stopOnError: bool = False
    options: Optional[TaskOptions] = Field(default=None, description="Additional Task Protocol options retained during migration. mode and stopOnError must agree with explicitly supplied top-level values.")


class ExecuteTaskInput(ToolInputBase):
    """Input for executing a structured task (Task Protocol v2.1)."""
    model_config = ConfigDict(extra="forbid")

    detail: Literal["summary", "full"] = Field(
        "full", description="Presentation only: summary factors common explicit defaults for successful, non-skipped operations into diagnostics.presentation.operationDefaults and hides their timing. Small batches may grow. Full evidence is available via illustrator_job_status while retained; jobs may expire or be evicted. Host-budget omissions cannot be recovered."
    )

    @model_validator(mode="before")
    @classmethod
    def bound_request(cls, value):
        _check_request_limits(value)
        return value
    
    payload: Optional[TaskPayload] = Field(
        default=None,
        description=(
            "Compatibility Task Protocol route for supported SOC operations "
            "using the same operation vocabulary as batch, or "
            "for ordered mixed sequences in payload.params.ops. Operation "
            "names and parameters are statically checked before dispatch; "
            "runtime targets and fields remain deferred. Provide exactly one of payload or batch."
        ),
    )
    batch: Optional[StructuredPilotBatch] = Field(
        default=None,
        description=(
            "Preferred route for all 48 JSX operations "
            "listed in the tool description. Operations are discriminated by "
            "task and validated before any host call. Provide exactly one of "
            "batch or payload."
        ),
    )
    job_id: Optional[str] = Field(
        default=None,
        alias="jobId",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        description=(
            "Optional stable logical-job ID. Reusing it with the same request "
            "returns the retained outcome without replay; different content "
            "under the same ID is rejected. The generated ID is returned when omitted."
        ),
    )
    
    includes: List[str] = Field(
        default_factory=list,
        description="Additional library includes (e.g. ['ops_core', 'ops_element']). polyfills is always included."
    )
    
    collect_fn: str = Field(
        default="collectTargets",
        description=(
            "Collector callable used by the compatibility callback pipeline. "
            "Use standard 'collectTargets' or provide a custom callable made "
            "available through includes. Custom callbacks execute with raw "
            "ExtendScript capabilities."
        ),
    )
    
    compute_fn: Optional[str] = Field(
        default=None,
        description=(
            "Arbitrary JSX callback body for compute logic. Receives "
            "(items, params, report), "
            "must return actions array. Omit for SOC batch-only mode."
        ),
    )
    
    apply_fn: Optional[str] = Field(
        default=None,
        description=(
            "Arbitrary JSX callback body for apply logic. Receives "
            "(actions, report), modifies items. "
            "Omit for SOC batch-only mode (ops in the payload are the apply step)."
        ),
    )
    
    @model_validator(mode="after")
    def _check_fn_consistency(self):
        self.clip_box = CaptureOptions(clip_box=self.clip_box).clip_box
        if (self.payload is None) == (self.batch is None):
            raise ValueError("Provide exactly one of payload or batch")
        if self.batch is not None:
            if self.compute_fn is not None or self.apply_fn is not None:
                raise ValueError("batch uses the structured executor; custom functions are not allowed")
            options = self.batch.options.model_copy(deep=True) if self.batch.options else TaskOptions(kind="creation")
            for key in ("mode", "stopOnError"):
                if self.batch.options and key in self.batch.model_fields_set and getattr(options, key) != getattr(self.batch, key):
                    raise ValueError(f"batch.{key} conflicts with batch.options.{key}")
                if key in self.batch.model_fields_set or self.batch.options is None:
                    setattr(options, key, getattr(self.batch, key))
            self.payload = TaskPayload(
                task="structured_pilot_v1",
                params={
                    "ops": [
                        op.model_dump(mode="json", exclude_none=True)
                        for op in self.batch.operations
                    ]
                },
                options=options,
            )
        if self.compute_fn is not None and self.apply_fn is None:
            raise ValueError(
                "compute_fn requires apply_fn. If you are running SOC ops batches, "
                "omit both compute_fn and apply_fn."
            )
        if self.compute_fn is None:
            self.payload = _normalize_operation_payload(self.payload, typed=self.batch is not None)
        return self

    return_preview: Optional[bool] = Field(
        default=None,
        description="Request a visual preview. Leave unset to use VLM QA cadence."
    )
    preview_mode: Literal["artboard", "annotated"] = Field(
        default="annotated",
        description="'artboard': raw preview. 'annotated': numbered bounding boxes + annotation map."
    )
    final_step: bool = Field(
        default=False,
        description="Force annotated preview on last SOC task, regardless of cadence. Does NOT override dryRun."
    )

    clip_box: Optional[List[float]] = Field(
        default=None,
        description=(
            "Optional high-resolution crop region: [xmin, ymin, xmax, ymax] in "
            "screen-space Y-down points.  See illustrator_execute_script for details."
        ),
    )


# ── Level 3/4 preprocessing helper ──────────────────────────────

def _preprocess_element_create(payload_data: dict) -> None:
    """Preprocess polar handles and mirror modifiers (mutates in-place).

    Pipeline order:
      1. Validate guards (type, mutual exclusion)
      2. If 'handles': resolve polar/relative → absolute triplets
      3. If 'mirror': mirror resolved points (including handles) + dedup seam
      4. Strip preprocess-only keys (handles, mirror, mirrorOrigin)
    """
    params = payload_data.get("params", {})

    if params.get("handles") or params.get("mirror"):
        pending = [params.get(key) for key in ("type", "points", "handles", "mirror", "mirrorOrigin")]
        while pending:
            value = pending.pop()
            if _is_field(value):
                raise ValueError("Path handles/mirror preprocessing requires static values; resolve field values first")
            if isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)

    # Guard: only for path type with points
    ptype = params.get("type")
    if ptype != "path":
        # Clean up orphan preprocess keys on non-path types
        params.pop("handles", None)
        params.pop("mirror", None)
        params.pop("mirrorOrigin", None)
        return
    if "points" not in params:
        return

    # Mutual exclusion: handles + smooth
    if params.get("handles") and params.get("smooth"):
        raise ValueError(
            "handles and smooth are mutually exclusive. "
            "Use handles for explicit Bézier control, or smooth for auto Catmull-Rom."
        )

    # Orphan mirrorOrigin without mirror
    if params.get("mirrorOrigin") is not None and not params.get("mirror"):
        params.pop("mirrorOrigin", None)

    from illustrator_mcp.curves import resolve_polar_handles, mirror_points

    # Step 1: Resolve polar/relative handles → absolute triplets
    if params.get("handles"):
        params["points"] = resolve_polar_handles(params["points"], params["handles"])
        del params["handles"]

    # Step 2: Mirror resolved points (including handles) + dedup seam
    if params.get("mirror"):
        params["points"] = mirror_points(
            params["points"], params["mirror"], params.get("mirrorOrigin")
        )
        params["closed"] = True  # mirrored paths are always closed
        del params["mirror"]
        params.pop("mirrorOrigin", None)


# Bounds are whole-request limits, not per-op allowances. Array creation's
# existing host cap is 10,000; explicit geometry is also bounded before mirror
# expansion. Referenced stash contents and dynamic fields remain runtime data.
MAX_REQUEST_OPERATIONS = 1000
MAX_REQUEST_ITEMS = 10000
MAX_REQUEST_POINTS = 100000
MAX_REQUEST_DEPTH = 32


def _check_request_limits(value):
    import math

    stack = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if depth > MAX_REQUEST_DEPTH or nodes > 1_000_000:
            raise ValueError("Request exceeds depth 32 or 1000000 JSON-value limit")
        if isinstance(current, float) and not math.isfinite(current):
            raise ValueError("Request numbers must be finite")
        if isinstance(current, dict):
            stack.extend((v, depth + 1) for v in current.values())
        elif isinstance(current, (list, tuple)):
            if len(current) > MAX_REQUEST_POINTS:
                raise ValueError("Request array exceeds 100000 entries")
            stack.extend((v, depth + 1) for v in current)


def _validate_guard(guard, label):
    if not isinstance(guard, dict) or not isinstance(guard.get("property"), str) or not guard["property"]:
        raise ValueError(f"{label}: guard requires a property string")
    allowed_properties = {"width", "height", "left", "top", "opacity", "name", "locked", "typename"}
    if guard["property"] not in allowed_properties:
        raise ValueError(f"{label}: unknown guard property; allowed: {', '.join(sorted(allowed_properties))}")
    comparators = set(guard) - {"property"}
    if len(comparators) != 1 or not comparators <= {"eq", "neq", "gt", "gte", "lt", "lte", "contains", "matches"}:
        raise ValueError(f"{label}: guard requires exactly one comparator: eq,neq,gt,gte,lt,lte,contains,matches")
    comparator = next(iter(comparators))
    expected = guard[comparator]
    if comparator in {"gt", "gte", "lt", "lte"} and (isinstance(expected, bool) or not isinstance(expected, (int, float))):
        raise ValueError(f"{label}.{comparator}: expected number")
    if comparator in {"matches", "contains"} and not isinstance(expected, str):
        raise ValueError(f"{label}.{comparator}: expected string")
    if comparator in {"matches", "contains"} and guard["property"] not in {"name", "typename"}:
        raise ValueError(f"{label}.{comparator}: requires a string property")
    if comparator == "matches":
        import re
        try:
            re.compile(expected)
        except re.error as exc:
            raise ValueError(f"{label}.matches: invalid regular expression: {exc}") from exc


def _point_count(points, label):
    def pair(p):
        return isinstance(p, list) and len(p) == 2 and all(
            _is_field(n) or (isinstance(n, (int, float)) and not isinstance(n, bool)) for n in p)

    if not isinstance(points, list) or len(points) < 2:
        raise ValueError(f"{label}: expected at least two points")
    for point in points:
        valid = pair(point)
        if isinstance(point, list) and len(point) == 3:
            valid = all(pair(p) for p in point)
        elif isinstance(point, dict):
            valid = (set(point) <= {"anchor", "left", "right"} and pair(point.get("anchor"))
                     and all(pair(point[k]) for k in ("left", "right") if k in point))
        if not valid:
            raise ValueError(f"{label}: expected XY pairs, handle triplets, or anchor/left/right point objects")
    return len(points)


def _is_field(value):
    return isinstance(value, dict) and isinstance(value.get("$field"), str)


def _generated_vertex_count(spec, label):
    """Count polygon/star anchors using the factory's defaults and star alias."""
    shape = spec.get("type")
    if shape == "polygon":
        value, field, multiplier = spec.get("sides") or 6, "sides", 1
    elif shape == "star":
        value, field, multiplier = spec.get("numPoints") or spec.get("points") or 5, "numPoints/points", 2
    else:
        return 0
    if _is_field(value):
        return 0  # Dynamic values remain runtime data.
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 1 or value % 1:
        raise ValueError(f"{label}.{field}: expected a positive integer vertex count")
    return int(value) * multiplier


def _normalize_operation_payload(payload, *, typed=False):
    """Copy, validate and lower an entire SOC request once, before dispatch."""
    from copy import deepcopy
    from illustrator_mcp.schemas.contracts import validate_op_params

    data = payload.model_dump(mode="json", exclude_none=True)
    _check_request_limits(data)
    explicit = "ops" in data["params"] and data["task"] != "compound"
    operations = data["params"]["ops"] if explicit else [
        {"task": data["task"], "params": data["params"], **({"targets": data["targets"]} if "targets" in data else {})}
    ]
    operations = deepcopy(operations)
    counts = {"ops": 0, "items": 0, "points": 0}
    preprocess = []

    def geometry_count(geometry, label):
        import math

        def ir_pair(point, field):
            # IR anchors are XY arrays, not the legacy raw-point objects or
            # handle triplets accepted by _point_count. Extra coordinates are
            # ignored by the host validator. Scalar fields resolve at runtime.
            if not isinstance(point, list) or len(point) < 2 or any(
                not _is_field(value) and (
                    isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                ) for value in point[:2]
            ):
                raise ValueError(f"{field}: expected [finite number, finite number] IR coordinates")

        if _is_field(geometry):
            return 0, 0  # Runtime geometry cannot be expanded or counted here.
        if not isinstance(geometry, dict) or geometry.get("ir") not in ("path", "multi"):
            raise ValueError(f"{label}: expected path or multi geometry IR")
        if type(geometry.get("v", 1)) not in (int, float) or geometry.get("v", 1) != 1:
            raise ValueError(f"{label}: unsupported geometry IR version")
        if geometry["ir"] == "multi":
            paths = geometry.get("paths")
            if not isinstance(paths, list) or not paths:
                raise ValueError(f"{label}: multi geometry requires nonempty paths")
            result = [geometry_count(path, f"{label}.paths[{i}]") for i, path in enumerate(paths)]
            return sum(n for n, _ in result), sum(n for _, n in result)
        points = geometry.get("points")
        if not isinstance(points, list) or len(points) < 2:
            raise ValueError(f"{label}.points: expected at least two IR points")
        count = len(points)
        for i, point in enumerate(points):
            ir_pair(point, f"{label}.points[{i}]")
        if "closed" in geometry and not _is_field(geometry["closed"]) and type(geometry["closed"]) is not bool:
            raise ValueError(f"{label}.closed: expected boolean")
        if geometry.get("kind", "polyline") not in ("polyline", "bezier"):
            raise ValueError(f"{label}: unsupported geometry kind")
        if geometry.get("kind") == "bezier":
            handles = geometry.get("handles")
            if not isinstance(handles, list) or len(handles) != count:
                raise ValueError(f"{label}: Bezier handles must parallel points")
            for i, handle in enumerate(handles):
                if not isinstance(handle, dict) or not {"in", "out"} <= handle.keys():
                    raise ValueError(f"{label}: Bezier handle requires in and out")
                for key in ("in", "out"):
                    if handle[key] is not None:
                        ir_pair(handle[key], f"{label}.handles[{i}].{key}")
            if geometry.get("handleSpace", "absolute") != "absolute":
                raise ValueError(f"{label}.handleSpace: v1 requires 'absolute'")
            if geometry.get("closed") is True:
                if count < 3:
                    raise ValueError(f"{label}.points: closed bezier requires at least three points")
                if not any(_is_field(v) for point in (points[0], points[-1]) for v in point[:2]) and all(
                    abs(points[0][axis] - points[-1][axis]) < 1e-10 for axis in (0, 1)
                ):
                    raise ValueError(f"{label}.points: closed bezier must not duplicate first/last anchor")
        return 1, count

    def visit(ops, nested=False):
        if not isinstance(ops, list) or not ops:
            raise ValueError("ops must be a nonempty array")
        counts["ops"] += len(ops)
        if counts["ops"] > MAX_REQUEST_OPERATIONS:
            raise ValueError("Request exceeds 1000 total operations")
        for index, op in enumerate(ops):
            label = f"{'compound.' if nested else ''}ops[{index}]"
            if not isinstance(op, dict) or not isinstance(op.get("task"), str):
                raise ValueError(f"{label}: expected operation object with task string")
            unknown = set(op) - {"task", "params", "targets", "id", "comment", "when", "unless"}
            if unknown:
                raise ValueError(f"{label}: unknown operation fields {sorted(unknown)}")
            task = op["task"]
            result = validate_op_params(task, op.get("params"))
            if not result["ok"]:
                raise ValueError(label + ": " + "; ".join(e["message"] for e in result["errors"]))
            params = op.setdefault("params", {})
            if params is None:
                params = op["params"] = {}
            if params.get("geometry") is not None:
                required_ir = "multi" if task == "element_create_multi" else (
                    "path" if task == "element_create" and params.get("type") in ("path", "polyline") else None
                )
                if required_ir and not _is_field(params["geometry"]) and (
                    not isinstance(params["geometry"], dict) or params["geometry"].get("ir") != required_ir
                ):
                    raise ValueError(f"{label}: {task}.geometry requires ir:'{required_ir}'")
                nitems, npoints = geometry_count(params["geometry"], f"{label}.{task}.geometry")
                counts["points"] += npoints
                if task == "element_create_multi":
                    counts["items"] += nitems
            for guard in ("when", "unless"):
                if guard in op:
                    _validate_guard(op[guard], label + "." + guard)
            for field in ("id", "comment"):
                if field in op and not isinstance(op[field], str):
                    raise ValueError(f"{label}.{field}: expected string")
            if op.get("targets") is not None:
                op["targets"] = TargetSelector.model_validate(op["targets"]).model_dump(mode="json", exclude_none=True)
                has_prev = any(token in json.dumps(op["targets"]) for token in ('"$prev"', '"$prevAll"'))
                target = op["targets"]["target"]
                if has_prev and (not nested or target["type"] != "id"):
                    raise ValueError(f"{label}: $prev/$prevAll require direct ID targets in compound sub-operations")
                if target["type"] == "id" and any(v.startswith("$") and v not in {"$prev", "$prevAll"} for v in target["ids"]):
                    raise ValueError(f"{label}: unknown previous-result token")
            if task == "compound":
                if nested:
                    raise ValueError(f"{label}: compound operations cannot be nested")
                if params.get("atomic"):
                    raise ValueError(f"{label}: compound atomic recovery is not supported")
                visit(params.get("ops"), True)
            if task == "element_create_batch":
                if not typed or nested:
                    params = op["params"] = _CreateBatchParams.model_validate(params).model_dump(exclude_none=True)
                template = params.get("template")
                items = params.get("items")
                instances = params.get("instances")
                array = params.get("array")
                if instances is not None and array is not None:
                    raise ValueError(f"{label}: instances and array are mutually exclusive")
                count = len(items) if items is not None else len(instances) if instances is not None else (array or {}).get("count")
                if _is_field(count):
                    count = 0  # Runtime array count remains subject to host cap.
                elif isinstance(count, bool) or not isinstance(count, int) or count < 0:
                    raise ValueError(f"{label}: array.count must be a nonnegative integer")
                if count == 0 and array is None:
                    raise ValueError(f"{label}: items/instances must be nonempty (array.count=0 is supported)")
                if array is not None and "cols" in array and not _is_field(array["cols"]) and (type(array["cols"]) is not int or array["cols"] < 1):
                    raise ValueError(f"{label}: array.cols must be a positive integer")
                counts["items"] += count
                for spec in ([template] if template is not None else items or []):
                    shape = spec.get("type")
                    supported = _BATCH_TEMPLATE_KEYS_BY_TYPE if template is not None else _BATCH_ITEM_KEYS_BY_TYPE
                    if not _is_field(shape) and shape not in supported:
                        raise ValueError(f"{label}: unsupported {'template' if template else 'item'} type {shape!r}")
                    for key in {"x", "y", "cx", "cy", "w", "h", "r", "rx", "ry", "radius", "sides", "numPoints", "outerRadius", "innerRadius", "opacity"} & spec.keys():
                        value = spec[key]
                        if not _is_field(value) and (isinstance(value, bool) or not isinstance(value, (int, float))):
                            raise ValueError(f"{label}.{key}: expected number")
                    if isinstance(shape, str) and shape in {"path", "polyline", "line"}:
                        counts["points"] += _point_count(spec.get("points"), label) * (count if template is not None else 1)
                    counts["points"] += _generated_vertex_count(spec, label) * (count if template is not None else 1)
                for inst in instances or []:
                    for key in ("x", "y", "scale", "opacity"):
                        if key in inst and not _is_field(inst[key]) and (isinstance(inst[key], bool) or not isinstance(inst[key], (int, float))):
                            raise ValueError(f"{label}.instances.{key}: expected number")
                for key, value in (array or {}).items():
                    if not _is_field(value) and (isinstance(value, bool) or not isinstance(value, (int, float))):
                        raise ValueError(f"{label}.array.{key}: expected number")
            elif task in {"element_create", "element_replace"}:
                counts["items"] += 1
                counts["points"] += _generated_vertex_count(params, label)
                if isinstance(params.get("type"), str) and params["type"] in {"path", "polyline", "line"} and "points" in params and not _is_field(params["points"]):
                    count = _point_count(params["points"], label)
                    counts["points"] += count * (2 if params.get("mirror") else 1)
                if counts["points"] > MAX_REQUEST_POINTS:
                    raise ValueError("Request exceeds 100000 expanded geometry points")
                preprocess.append(op)
            if counts["items"] > MAX_REQUEST_ITEMS or counts["points"] > MAX_REQUEST_POINTS:
                raise ValueError("Request exceeds 10000 expanded items or 100000 expanded geometry points")

    visit(operations)
    # All budgets and static branches are checked before the first expansion.
    for op in preprocess:
        _preprocess_element_create(op)
    if explicit:
        data["params"]["ops"] = operations
    else:
        data["params"] = operations[0]["params"]
        if "targets" in operations[0]:
            data["targets"] = operations[0]["targets"]
    return TaskPayload.model_validate(data)


_TASK_NAME = "illustrator_execute_task"


def _with_operation_index(fn):
    from illustrator_mcp.schemas.contracts import render_operation_index
    fn.__doc__ = fn.__doc__.replace("      {operation_index}", render_operation_index())
    return fn


@forbid_extra_tool_arguments(mcp, _TASK_NAME)
@mcp.tool(name=_TASK_NAME, annotations=TOOL_ANNOTATIONS[_TASK_NAME])
@_with_operation_index
async def illustrator_execute_task(params: ExecuteTaskInput) -> CallToolResult:
    """Execute structured SOC operations or a compatibility callback pipeline.

    CONTRACT: readOnly=False, destructive=True, idempotent=False, openWorld=True

    WHEN TO USE:
      - Prefer params.batch for all 48 JSX operations; the nine pilot models retain stronger nested typing.
      {operation_index}
      - Compatibility params.payload remains supported for ordered mixed sequences
        under payload.params.ops; it uses the same static validation pipeline.
      - The payload route also accepts compatibility callback hooks: collect_fn
        selects a callable, while compute_fn and apply_fn are arbitrary
        ExtendScript callback bodies. They have the same File, Folder, and OS
        access as raw ExtendScript, so this tool is open-world while they exist.
      - Provide exactly one of params.batch or params.payload.

    EXAMPLES:
      Explicit scientific runs through the compatibility route (choose installed faces; inspect runVerification.fonts):
        {
          "params": {
            "payload": {
              "task": "text_create",
              "params": {
                "x": 20,
                "y": 40,
                "runs": [
                  {
                    "text": "B",
                    "fontName": "AcuminConcept-Black",
                    "fontSize": 12
                  },
                  {
                    "text": "ex",
                    "fontName": "AcuminConcept-BlackItalic",
                    "fontSize": 8.4,
                    "baselineShift": -3
                  }
                ]
              }
            }
          }
        }
      One structured operation (the preferred form):
        {
          "params": {
            "batch": {
              "operations": [
                {
                  "task": "element_create",
                  "params": {
                    "type": "rect",
                    "x": 40,
                    "y": 40,
                    "width": 200,
                    "height": 120,
                    "fill": {
                      "r": 0,
                      "g": 150,
                      "b": 136
                    }
                  }
                }
              ]
            }
          }
        }
      Several operations, stopping at the first failure:
        {
          "params": {
            "batch": {
              "operations": [
                {
                  "task": "element_create",
                  "params": {
                    "type": "ellipse",
                    "x": 0,
                    "y": 0,
                    "width": 60,
                    "height": 60,
                    "id": "dot"
                  }
                },
                {
                  "task": "element_modify",
                  "targets": {
                    "type": "id",
                    "ids": [
                      "dot"
                    ]
                  },
                  "params": {
                    "x": 120
                  }
                }
              ],
              "stopOnError": true
            }
          }
        }
      Validate a batch without applying it:
        {
          "params": {
            "batch": {
              "operations": [
                {
                  "task": "element_create",
                  "params": {
                    "type": "star",
                    "x": 100,
                    "y": 100,
                    "numPoints": 5,
                    "outerRadius": 40,
                    "innerRadius": 18
                  }
                }
              ],
              "mode": "validate"
            }
          }
        }
      Create a layer through the compatibility route:
        {"params": {"payload": {"task": "layer_create", "params": {"name": "Background"}}}}
      Create a layer, then a rectangle on it, in one batch:
        {
          "params": {
            "batch": {
              "operations": [
                {
                  "task": "layer_create",
                  "params": {
                    "name": "Background"
                  }
                },
                {
                  "task": "element_create",
                  "params": {
                    "type": "rect",
                    "x": 0,
                    "y": 0,
                    "width": 800,
                    "height": 600,
                    "layer": "Background"
                  }
                }
              ],
              "stopOnError": true
            }
          }
        }

    TARGET SELECTORS:
      {type: "selection"} — current selection (default)
      {type: "layer", layer: "Layer 1"} — all items on layer
      {type: "query", itemType: "PathItem", pattern: "axis_*"} — pattern match
      {type: "all", recursive: true} — all items in document
      {type: "id", ids: ["A1", "A2"]} — stable MCP ID targeting

    OPTIONS:
      batch.stopOnError and payload.options.stopOnError stop after the first
        failed operation. They preserve earlier edits and do not provide
        transactional rollback.
      payload.options.mode and stopOnError are honored by the default structured
        SOC route. trace is honored by both structured and callback routes.
      payload.options.kind, skipCollect, minCreated, idPolicy, and the deprecated
        assignIds alias are callback-pipeline controls. The default SOC route
        forces kind="creation", resolves per-op targets, and has no apply callback.
      retry, idempotency, and timeout are compatibility fields that still
        validate but are currently ignored by this executor. It does not call
        the retry wrapper or use payload.options.timeout as its host deadline.
      dryRun — NOT SUPPORTED; rejected before execution. It could not
        prevent mutation (batch ops run during compute) and reported
        otherwise. To inspect without changing anything, use query_items,
        preflight_check, or get_document.
      rollback, snapshot, and recompute — NOT SUPPORTED; enabled requests are
        rejected before host dispatch. Explicit false/null disabled forms remain valid.
      Unknown task, payload, batch, operation, option, and nested retry fields
        are rejected. Use stopOnError instead of the internal strict spelling.

    RESULT:
      structuredContent carries the canonical result object: execution status,
      data, effects, verification, recovery, warnings and truncation. isError
      reflects the EXECUTION outcome only — a failed or unavailable visual
      check never turns a successful edit into a tool error.

    NOTES:
      - With the default SOC executor (no custom compute function), the server
        injects payload.options.kind="creation" so outer collection is skipped
        while each operation resolves its own targets. Callers may omit kind.
      - Both SOC routes validate the complete operation tree before dispatch.
        Availability, required fields, broad types, enums and unknown keys are
        checked from the shared contract. Pilot nested models remain stronger.
      - Path handles and mirror modifiers normalize once for single operations,
        batch operations and compound children. Runtime fields and targets stay
        deferred; stopOnError does not promise rollback or successful assertions.
      - Static request limits: 1000 operations, JSON depth 32, selector depth 16,
        10000 expanded items and 100000 expanded geometry points. Dynamic values
        remain subject to host limits when evaluated.
      - For boolean ops use illustrator_path_boolean, not execute_task
      - For raw SVG path data use illustrator_path_import_svg
    """
    # T11: one chokepoint decides what the client is told. It derives isError
    # from the envelope's `ok` and puts the result OBJECT in structuredContent.
    # Previously a result whose own JSON said `ok: false` reached the client as
    # `isError: false`, with structuredContent wrapping a JSON string.
    from illustrator_mcp.execution.logical_job import run_logical_job
    from illustrator_mcp.execution.logical_job import intent_digest
    digest = intent_digest(_TASK_NAME, params)
    return await run_logical_job(_TASK_NAME, params,
        lambda job: _execute_task_impl(params, job_id=job.job_id, request_digest_value=digest),
        digest=digest)


async def _execute_task_impl(
    params: ExecuteTaskInput,
    *,
    job_id: Optional[str] = None,
    request_digest_value: Optional[str] = None,
) -> Union[str, list]:
    """Run the task and produce a legacy envelope / content-block list.

    Kept separate from the registered tool so the MCP presentation lives in
    exactly one place (``finalize_tool_result``) rather than in each of this
    function's many return paths.
    """
    payload = params.payload

    # ── T03: reject dry runs BEFORE any host call ───────────────
    # `dryRun` used to mean "skip the apply stage", but in SOC batch mode the
    # mutating operation executor runs during *compute* — so the document was
    # already changed by the time the flag was checked, and the caller was told
    # "no changes applied".  Rejecting here, before the script is even built,
    # is the only way to honour that promise: nothing reaches Illustrator, so
    # artwork, notes, selection, active layer and active artboard are untouched.
    # A real validation-only mode belongs in the unified executor (T15).
    if payload.options is not None and payload.options.dryRun:
        return make_envelope(
            ok=False,
            error=(
                "dryRun (validation-only execution) is not supported by "
                "execute_task. It was previously accepted but did NOT prevent "
                "mutation: batch operations execute during the compute stage, "
                "before the dryRun check. No changes have been made by this "
                "call. Omit dryRun to apply the task, or use a read-only tool "
                "(query_items, preflight_check, get_document) to inspect first."
            ),
            error_code="V011",
            diagnostics={
                "task": payload.task,
                "rejected_option": "dryRun",
                "jobId": job_id,
            },
        )

    # ── SVG d-param removed — redirect to path_import_svg ──────
    if payload.task == "element_create" and "d" in payload.params:
        return make_envelope(
            ok=False,
            error=(
                "SVG 'd' attribute is no longer accepted in element_create. "
                "Use 'path_import_svg' for existing SVG data, or "
                "'drawPathPoints' (in execute_script with includes: ['geometry']) for new paths."
            ),
            diagnostics={"task": payload.task, "jobId": job_id},
        )

    # Build the execution script
    # SOC batch mode: force kind="creation" so pipeline skips collect
    # and doesn't early-return before reaching compute stage.
    payload_data = params.payload.model_dump(mode="json")

    # ── Level 3/4 preprocessing: polar handles + mirror ──────
    # Whole-request normalization already ran at the input boundary.

    # SOC mode always delegates target resolution to executeOpBatch. Running
    # the outer collect stage as well would select one executor for collection
    # and another for apply, and could early-return before an empty query reaches
    # a read-only op. Custom compute/apply pipelines retain legacy collection.
    if params.compute_fn is None:
        if "options" not in payload_data:
            payload_data["options"] = {}
        payload_data["options"]["kind"] = "creation"
        logger.debug(
            "execute_task: injected kind=creation for task=%s (targets=%s)",
            payload.task, payload.targets,
        )
    payload_json = json.dumps(payload_data)
    
    # Build compute/apply function blocks
    if params.compute_fn is not None:
        compute_block = f"function compute(items, params, report) {{\n{params.compute_fn}\n}}"
    else:
        # SOC batch mode: load template from .jsx file (IDE-checkable, no inline strings)
        compute_block = _load_jsx_template("compute_soc_batch.jsx")

    if params.apply_fn is not None:
        apply_block = f"function apply(actions, report) {{\n{params.apply_fn}\n}}"
    else:
        apply_block = "var apply = null;  // SOC batch mode: no apply step"

    host_job_id = job_id or "job_unmanaged"
    host_job_spec = json.dumps({
        "jobId": host_job_id,
        "digest": request_digest_value,
        "context": {"task": payload.task},
    })

    script = f"""
(function() {{
var _mcpExpectedRuntime = {{protocolVersion: "3.0.0"}};
var _mcpRuntimeCheck = mcpRuntimeHandshake(_mcpExpectedRuntime);
if (_mcpRuntimeCheck.status !== "ready") {{
    var _mcpRuntimeInitResult = mcpRuntimeInit({{
        protocolVersion: "3.0.0", runtimeHash: null,
        capabilities: {{hostLedger: "1.0"}}, force: false
    }});
    if (!_mcpRuntimeInitResult.ok) {{
        return JSON.stringify({{
            ok: false,
            stats: {{itemsProcessed: 0, itemsCreated: 0, itemsModified: 0, itemsSkipped: 0}},
            timing: {{total_ms: 0}}, warnings: [],
            errors: [{{code: "R_RUNTIME_BUSY", message: _mcpRuntimeInitResult.message || "Host runtime is unavailable"}}],
            job: {{jobId: {json.dumps(host_job_id)}, hostCompletion: "not_started"}}
        }});
    }}
}}

var _mcpDocument = mcpDocBind({{label: "execute_task"}});
var _mcpJobSpec = {host_job_spec};
if (typeof __mcpEffectiveDigest === "string") _mcpJobSpec.digest = __mcpEffectiveDigest;
_mcpJobSpec.context.document = _mcpDocument;
var _mcpJobStart = mcpRuntimeBeginWork(_mcpJobSpec);
if (!_mcpJobStart.ok) {{
    if (_mcpJobStart.status === "duplicate_completed" &&
            _mcpJobStart.record && _mcpJobStart.record.result) {{
        var _mcpRetainedReport = JSON.parse(JSON.stringify(_mcpJobStart.record.result));
        _mcpRetainedReport.job = {{
            jobId: _mcpJobSpec.jobId,
            digest: _mcpJobSpec.digest,
            sessionEpoch: _mcpJobStart.record.sessionEpoch,
            status: _mcpJobStart.record.status,
            disposition: "duplicate_completed",
            hostCompletion: "retained",
            deduplicated: true,
            replayed: false
        }};
        return JSON.stringify(_mcpRetainedReport);
    }}
    return JSON.stringify({{
        ok: false,
        stats: {{itemsProcessed: 0, itemsCreated: 0, itemsModified: 0, itemsSkipped: 0}},
        timing: {{total_ms: 0}}, warnings: [],
        errors: [{{
            code: _mcpJobStart.status === "conflict" ? "V_JOB_CONFLICT" : "R_JOB_DUPLICATE",
            message: _mcpJobStart.message || "Host refused the logical job"
        }}],
        job: {{
            jobId: _mcpJobSpec.jobId,
            status: _mcpJobStart.status,
            hostCompletion: _mcpJobStart.record && _mcpJobStart.record.completed === true ? "retained" : "not_started"
        }}
    }});
}}

try {{
// Compute function
{compute_block}

// Apply function
{apply_block}

// Execute task
var payload = {payload_json};
var report = executeTask(
    payload,
    {params.collect_fn},
    compute,
    apply
);

// ── Budget the batchReport at the wire boundary (T11) ──
// The previous version replaced every per-op result with a fixed 5-field
// summary that DISCARDED op.data outright. That is the payload: bounds from
// a measurement, IDs from a creation, style snapshots, layer listings. A
// successful measure_bounds therefore returned no bounds at all.
//
// Response size is still bounded — but by dropping the LEAST valuable detail
// last, and by REPORTING what was dropped instead of silently flattening
// everything. Identities and errors are preserved even when detail is not.
if (report.batchReport) {{
    var _br = report.batchReport;
    var _budget = {_OP_DATA_BUDGET_BYTES};
    var _used = 0;
    var _ops = _br.ops || [];
    var _kept = [];
    var _dataDropped = 0;

    for (var _oi = 0; _oi < _ops.length; _oi++) {{
        __mcp_check();
        var _op = _ops[_oi];
        // Always keep identity, status and error — these are what the agent
        // needs to know what happened and what it may target next.
        var _entry = {{
            index: _op.index,
            task: _op.task,
            ok: _op.ok,
            // Both counts, so "asked for 3, found 2" is visible. Reporting
            // only the resolved count made a partially-satisfied request
            // indistinguishable from a fully satisfied one.
            targets_requested: (typeof _op.targets_requested === "number")
                ? _op.targets_requested : (_op.targets_resolved || 0),
            targets_resolved: _op.targets_resolved || 0,
            id: _op.id || null,
            error: _op.error || null
        }};
        // Bounded execution metadata must survive even when op.data is omitted.
        if (typeof _op.targets_unidentified === "number") {{
            _entry.targets_unidentified = _op.targets_unidentified;
        }}
        if (typeof _op.duration_ms === "number") _entry.duration_ms = _op.duration_ms;
        if (_op.unresolvedIds && _op.unresolvedIds.length) {{
            _entry.unresolvedIds = _op.unresolvedIds;
        }}
        if (_op.skipped) _entry.skipped = true;
        // Targets the op was asked to act on but did not. Survives the data
        // budget: it is the difference between "did all of it" and "did some".
        if (_op.unapplied && _op.unapplied.length) _entry.unapplied = _op.unapplied;
        if (_op.warnings && _op.warnings.length) _entry.warnings = _op.warnings;
        // Recovery is bounded outcome metadata, not optional handler payload.
        // Keep it even when op.data crosses the response budget.
        if (_op.recovery) _entry.recovery = _op.recovery;
        if (_op.effects) _entry.effects = _op.effects;
        if (_op.postcondition) _entry.postcondition = _op.postcondition;

        // Keep op.data while the budget allows.
        if (_op.data !== null && _op.data !== undefined) {{
            var _json = "";
            try {{ _json = JSON.stringify(_op.data); }} catch (_e) {{ _json = ""; }}
            if (_json && (_used + _json.length) <= _budget) {{
                _entry.data = _op.data;
                _used += _json.length;
            }} else {{
                _entry.dataOmitted = true;
                _dataDropped++;
            }}
        }}
        _kept.push(_entry);
    }}

    _br.ops = _kept;
    if (_dataDropped > 0) {{
        _br.truncation = {{
            reason: "op_data_budget",
            opsWithDataOmitted: _dataDropped,
            budgetBytes: _budget,
            note: "Per-op identities, status and errors are complete; " +
                  "op.data was omitted for the listed ops. Re-run a narrower " +
                  "batch to retrieve it."
        }};
    }}
}}

var _mcpEffects = report.batchReport && report.batchReport.effects ?
    report.batchReport.effects : {{created: [], modified: [], deleted: [], complete: false}};
var _mcpHasEffects = (_mcpEffects.created && _mcpEffects.created.length > 0) ||
    (_mcpEffects.modified && _mcpEffects.modified.length > 0) ||
    (_mcpEffects.deleted && _mcpEffects.deleted.length > 0) ||
    (_mcpEffects.unidentified && _mcpEffects.unidentified > 0);
// A batch that skipped requested targets is not a clean success, even when
// every handler returned ok: "succeeded" is defined as "every required
// operation completed its documented postconditions". Targets the executor
// recorded as unapplied did not get theirs, so the status degrades to
// "partial" when something else did change and "failed" when nothing did.
var _mcpUnapplied = (_mcpEffects.unapplied instanceof Array) ? _mcpEffects.unapplied : [];
var _mcpOutcomeStatus = (report.ok && _mcpUnapplied.length === 0) ? "succeeded" :
    (_mcpHasEffects ? "partial" : "failed");
var _mcpCompletion = mcpRuntimeCompleteWork(_mcpJobSpec.jobId, {{
    status: _mcpOutcomeStatus,
    result: report,
    effects: _mcpEffects,
    errors: report.errors || [],
    context: _mcpJobSpec.context
}});
report.job = {{
    jobId: _mcpJobSpec.jobId,
    digest: _mcpJobSpec.digest,
    sessionEpoch: _mcpCompletion.sessionEpoch || null,
    hostCompletion: _mcpCompletion.ok ? "retained" : "unavailable"
}};
if (!_mcpCompletion.ok) {{
    report.warnings = report.warnings || [];
    report.warnings.push("The edit returned directly, but its host completion record could not be retained. Reconciliation may be unavailable.");
}}
return JSON.stringify(report);
}} catch (_mcpJobError) {{
    mcpRuntimeCompleteWork(_mcpJobSpec.jobId, {{
        status: "failed",
        result: null,
        effects: {{created: [], modified: [], deleted: [], complete: false}},
        errors: [{{message: _mcpJobError.message || String(_mcpJobError), line: _mcpJobError.line || null}}],
        context: _mcpJobSpec.context
    }});
    throw _mcpJobError;
}}
}})();
"""
    
    # ── Auto-includes: inject libraries the generated script requires ──
    # executeTask() needs task_pipeline; SOC batch mode needs ops_core
    # for executeOpBatch(). The ops_* modules register handlers via
    # registerOpHandler(); without them, JSX returns V003 "Unknown op".
    auto = [
        "polyfills", "host_runtime", "doc_session", "task_pipeline", "ops_core",
        "ops_element", "ops_layer", "ops_style", "ops_text",
        "ops_group", "ops_align", "ops_measure", "ops_compound",
    ]

    # Dedup + stable-order: auto includes first, then user includes
    seen = set(auto)
    all_includes = list(auto)
    for inc in (params.includes or []):
        if inc not in seen:
            seen.add(inc)
            all_includes.append(inc)
    
    # ── VLM QA Cadence: track mutations for execute_task too ──
    is_validation = payload.options is not None and payload.options.mode == "validate"
    count = _counter.value if is_validation else _counter.increment()

    # Unlike a raw script, a structured batch says what it did, so the
    # requirement follows the operations rather than a counter. Validation
    # runs mutate nothing and need no evidence.
    evidence_decision = evidence.limit_to_available(
        evidence.decide(
            operations=_batch_operation_names(params),
            mutation_count=0 if is_validation else count,
            final_step=params.final_step,
        ) if not is_validation else evidence.NO_EVIDENCE,
        ("annotated", "raw"),
    )
    is_task_checkpoint = evidence_decision.required

    diagnostics = {
        "task": params.payload.task,
        "includes": all_includes,
        "is_vlm_checkpoint": is_task_checkpoint,
        "evidence": evidence.diagnostics(
            evidence_decision, evidence_supplied=False
        ),
        "jobId": job_id,
        "requestDigest": request_digest_value,
    }

    logger.info(f"execute_task: {params.payload.task}")

    try:
        response = await execute_script_with_context(
            script=script,
            command_type=f"task:{params.payload.task}",
            tool_name="illustrator_execute_task",
            params=params.payload.model_dump(),
            includes=all_includes
        )

        context = f"execute_task: {params.payload.task}"

        transport_error = response.get("error") if isinstance(response, dict) else None
        transport_text = str(transport_error or "").lower()
        if (
            "timed out" in transport_text
            or "timeout" in transport_text
            or "connection lost during execution" in transport_text
        ):
            diagnostics["jobOutcomeUnknown"] = True
            diagnostics["reconciliationHint"] = (
                f"Call illustrator_job_status with jobId {job_id!r}; do not replay blindly."
            )

        # ── Phase 1: Canonical unwrap + classify ──
        base = build_envelope_dict(response, context=context, diagnostics=diagnostics)
        if not base["ok"]:
            return json.dumps(base)  # short-circuit: bridge/injection/JSX error

        # ── Phase 2: Parse TaskReport from classified result ──
        local_warnings = []
        is_dry_run = params.payload.options.dryRun if params.payload.options else False
        if is_dry_run:
            diagnostics["preview_state"] = "pre_execution"

        # VLM QA Cadence: soft-override for execute_task
        # return_preview tri-state: None=allow, True=force, False=suppress
        evidence_declined = (
            is_task_checkpoint
            and evidence.capture_declined(params.return_preview, final_step=params.final_step)
        )
        if evidence_declined:
            # Capture is suppressed; the requirement is still reported, with
            # evidenceSupplied false, so a skipped check leaves a trace.
            local_warnings.append(
                "Verification required (" +
                ", ".join(evidence_decision.reason_values) +
                ") but evidence was declined with return_preview=False."
            )
            is_task_checkpoint = False

        mode = params.preview_mode or "annotated"
        if mode not in ("annotated", "artboard"):
            local_warnings.append(f"Unknown preview_mode '{mode}', defaulting to 'annotated'")
            mode = "annotated"

        merged_warnings = _dedup_warnings(base.get("warnings", []), local_warnings)
        merged_diag = {**base.get("diagnostics", {}), **diagnostics}
        # Per-op warnings are lifted after the report parses, below.

        _envelope_built = False  # Track if fallback already built the envelope
        report_data = {}  # Initialize before try so except-handler can inspect it

        try:
            raw_result = base.get("result")
            if isinstance(raw_result, str):
                report_data = json.loads(raw_result)
            elif isinstance(raw_result, dict):
                report_data = raw_result
            else:
                report_data = {}
            job_meta = report_data.get("job") if isinstance(report_data, dict) else None
            if isinstance(job_meta, dict):
                if job_meta.get("disposition") == "duplicate_completed":
                    merged_diag["deduplicated"] = True
                    merged_diag["replayed"] = False
                if job_meta.get("status") in ("duplicate_running", "duplicate_unknown"):
                    merged_diag["jobOutcomeUnknown"] = True
                    merged_diag["reconciliationHint"] = (
                        f"Call illustrator_job_status with jobId {job_id!r}; do not replay blindly."
                    )
            report = TaskReport.model_validate(report_data)
            formatted = format_task_report(report, params.payload.task)
        except Exception as exc:
            logger.warning(f"Failed to parse TaskReport: {exc}")
            parse_diag = {**merged_diag, "taskreport_parse": {"type": type(raw_result).__name__}}
            if isinstance(raw_result, str):
                parse_diag["taskreport_parse"]["excerpt"] = raw_result[:200]

            # ── Degraded fallback: JSON parsed but Pydantic validation failed ──
            # Preserve top-level ok/errors/warnings from report_data instead of
            # silently erasing them. Adds fallback_used diagnostic flag.
            if isinstance(report_data, dict) and "ok" in report_data:
                fallback_ok = report_data.get("ok", False)
                fallback_warnings = []
                # Preserve op-level errors/warnings even if types are imperfect
                raw_errors = report_data.get("errors", [])
                raw_warnings_list = report_data.get("warnings", [])
                if isinstance(raw_errors, list):
                    for e in raw_errors[:5]:
                        fallback_warnings.append(f"[op-error] {e}")
                if isinstance(raw_warnings_list, list):
                    for w in raw_warnings_list[:5]:
                        fallback_warnings.append(f"[op-warn] {w}")
                fallback_warnings.append(
                    "TaskReport validation failed; using degraded summary. "
                    "Some op-level errors may be missing."
                )
                parse_diag["taskreport_parse"]["fallback_used"] = True
                stats = report_data.get("stats", {})
                formatted = (
                    f"{'✓' if fallback_ok else '✗'} Task: {params.payload.task}\n"
                    f"  Stats: {stats.get('itemsProcessed', '?')} ops, "
                    f"{stats.get('itemsCreated', '?')} created, "
                    f"{stats.get('itemsModified', '?')} modified"
                )
                # Create minimal report-like object for guard/preview
                report = type('FallbackReport', (), {
                    'ok': fallback_ok,
                    'warnings': [],
                    'errors': [],
                })()
                merged_warnings = _dedup_warnings(merged_warnings, fallback_warnings)
                merged_diag = parse_diag
                envelope = make_envelope(
                    ok=fallback_ok,
                    result={"formatted": formatted, "report": report_data},
                    warnings=merged_warnings,
                    diagnostics=merged_diag,
                )
                _envelope_built = True
            else:
                # Raw string truncated / unparseable — hard fail with R010
                return make_envelope(
                    ok=False,
                    error={"code": "R010",
                           "message": f"Could not parse TaskReport: {exc}",
                           "suggestions": ["Check JSX script output format"]},
                    warnings=merged_warnings,
                    diagnostics=parse_diag,
                )

        # Lift per-op warnings so they reach a caller reading the summary.
        merged_warnings = _dedup_warnings(
            merged_warnings, _op_level_warnings(report_data)
        )

        # ── Phase 3: Final envelope via make_envelope ──
        if not is_dry_run:
            merged_diag["preview_state"] = "post_execution" if report.ok else "error"

        if not _envelope_built:
            if report.ok:
                envelope = make_envelope(
                    ok=True,
                    result={"formatted": formatted, "report": report_data},
                    warnings=merged_warnings,
                    diagnostics=merged_diag,
                )
            else:
                err = _taskreport_first_error(report_data, params.payload.task)
                stats = report_data.get("stats", {})
                merged_diag["stats"] = {
                    k: stats.get(k, 0)
                    for k in ("itemsProcessed", "itemsCreated", "itemsModified", "itemsSkipped")
                }
                if isinstance(report_data.get("batchReport"), dict):
                    # Preserve effect/postcondition evidence on failed and
                    # partial batches. make_envelope intentionally omits
                    # result when ok=False, so diagnostics is the durable path.
                    merged_diag["batchReport"] = report_data["batchReport"]
                envelope = make_envelope(
                    ok=False,
                    error=err,
                    warnings=merged_warnings,
                    diagnostics=merged_diag,
                )

        # ── Occlusion guard: run AFTER task execution, BEFORE preview ──
        guard_telemetry = {}
        gcp = None
        if is_task_checkpoint:
            gcp = await _guard_checkpoint(
                timeout=30.0,
                checkpoint_label="execute_task",
            )
            guard_telemetry = gcp.guard_telemetry
            merged_diag["guard_status"] = gcp.guard_status

            # Suspicious geometry raises the requirement even when the
            # operations themselves looked cheap.
            evidence_decision = evidence.escalate_for_geometry(
                evidence_decision, guard_telemetry
            )
            is_task_checkpoint = is_task_checkpoint or evidence_decision.required
            merged_diag["evidence"] = evidence.diagnostics(
                evidence_decision, evidence_supplied=False
            )

            if gcp.should_abort:
                merged_diag.update(gcp.diag_extras)
                merged_warnings.append(gcp.abort_message)
                # Rebuild envelope with abort info
                envelope = make_envelope(
                    ok=report.ok if 'report' in dir() else False,
                    result=envelope if isinstance(envelope, str) else None,
                    warnings=merged_warnings,
                    diagnostics=merged_diag,
                )
                # Return abort parts: envelope + evidence + telemetry + checkpoint
                abort_parts = [TextContent(type="text", text=envelope)]
                try:
                    evidence_png = await _capture_artboard(
                        max_dim=800, timeout=15.0,
                    )
                    if evidence_png:
                        import base64 as _b64
                        abort_parts.append(TextContent(
                            type="text",
                            text="Evidence preview (raw) — guard aborted before annotation.",
                        ))
                        abort_parts.append(ImageContent(
                            type="image",
                            data=_b64.b64encode(evidence_png).decode('utf-8'),
                            mimeType="image/png",
                        ))
                except Exception as e:
                    logger.debug("Evidence preview skipped: %s", e)
                if gcp.telemetry_text:
                    abort_parts.append(TextContent(
                        type="text", text=gcp.telemetry_text,
                    ))
                if evidence_decision.required:
                    abort_parts.append(TextContent(
                        type="text",
                        text=evidence.requirement_text(
                            evidence_decision,
                            evidence_supplied=any(
                                isinstance(b, ImageContent) for b in abort_parts
                            ),
                        ),
                    ))
                return abort_parts
            else:
                merged_warnings.extend(gcp.warn_messages)
        else:
            merged_diag["guard_status"] = "skipped"

        # ── Auto-Grounding: preview at cadence, manual request, or final_step ──
        should_preview = (
            (is_task_checkpoint or params.return_preview is True)
            and not is_dry_run
            and not is_validation
            and not (gcp and gcp.should_abort)
        )
        if should_preview:
            try:
                import base64 as _b64
                raw_png, annotated_bytes, annotation_result = await capture_frame(
                    CaptureOptions(timeout=30.0, clip_box=params.clip_box),
                    annotate=mode == "annotated", capture=_capture_artboard,
                    annotator=_annotate_preview,
                )
                if raw_png:
                    # The envelope was serialised before this capture, so the
                    # fact that evidence exists has to be stamped onto it here
                    # rather than into the dict it was built from.
                    if is_task_checkpoint:
                        envelope = evidence.stamp_supplied(
                            envelope, evidence_decision, supplied=True
                        )
                    if mode == "annotated":
                        ann_b64 = _b64.b64encode(annotated_bytes).decode('utf-8')
                        result_parts = [
                            TextContent(type="text", text=envelope),
                            ImageContent(
                                type="image",
                                data=ann_b64,
                                mimeType="image/png",
                            ),
                            TextContent(
                                type="text",
                                text=json.dumps(annotation_result, indent=2),
                            ),
                        ]
                        if params.clip_box:
                            result_parts.append(TextContent(
                                type="text",
                                text=(
                                    f"\u26a0\ufe0f CLIP BOX ACTIVE: This preview shows a "
                                    f"high-resolution crop of region "
                                    f"{params.clip_box} (screen-space Y-down, points). "
                                    f"All element IDs and coordinates in the annotation "
                                    f"map are in GLOBAL document coordinates. "
                                    f"Use global coordinates for all subsequent edits."
                                ),
                            ))
                    else:
                        raw_b64 = _b64.b64encode(raw_png).decode('utf-8')
                        result_parts = [
                            TextContent(type="text", text=envelope),
                            ImageContent(
                                type="image",
                                data=raw_b64,
                                mimeType="image/png",
                            ),
                        ]
                    if is_task_checkpoint:
                        # Z-order telemetry (task checkpoints)
                        if gcp and gcp.telemetry_text:
                            result_parts.append(TextContent(
                                type="text",
                                text=gcp.telemetry_text,
                            ))
                        result_parts.append(TextContent(
                            type="text",
                            text=evidence.requirement_text(
                                evidence_decision, evidence_supplied=True
                            ),
                        ))
                    return result_parts
            except Exception as e:
                logger.warning(f"Auto-grounding overlay failed (non-fatal): {e}")

        # Fallback: text-only envelope (+ telemetry + checkpoint instruction if cadence)
        if is_task_checkpoint:
            fallback_parts = [TextContent(type="text", text=envelope)]
            if gcp and gcp.telemetry_text:
                fallback_parts.append(TextContent(type="text", text=gcp.telemetry_text))
            fallback_parts.append(TextContent(
                type="text",
                text=evidence.requirement_text(
                    evidence_decision, evidence_supplied=False
                ),
            ))
            return fallback_parts
        return envelope

    except Exception as e:
        # B3: Decrement counter so failed tasks don't pollute cadence
        _counter.decrement()
        logger.error(f"Task execution failed: {str(e)}")
        raise


# ==================== Logical Job Status Tool ====================


class JobStatusInput(ToolInputBase):
    """Input for retained logical-job reconciliation."""

    detail: Literal["summary", "full"] = Field("full", description="Full retained evidence by default; summary omits the nested full result only.")

    finalize_export: bool = Field(default=False, description="Explicitly verify/restore/delete files owned by this retained export job after known completion. Default status inspection never changes files. Never replays an export; ownership is lost on process restart.")

    job_id: str = Field(
        ...,
        alias="jobId",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        description="Retained logical job ID returned by a mutation or connection-status blocking report.",
    )


_JOB_STATUS_NAME = "illustrator_job_status"


@mcp.tool(name=_JOB_STATUS_NAME, annotations=TOOL_ANNOTATIONS[_JOB_STATUS_NAME])
async def illustrator_job_status(params: JobStatusInput) -> CallToolResult:
    """Inspect a retained Illustrator job; optionally finalize its export files.

    CONTRACT: readOnly=False, destructive=True, idempotent=True, openWorld=True

    WHEN TO USE:
      - After illustrator_execute_task returned an unknown/timeout outcome.
      - To inspect a retained job by its jobId before considering a retry.

    RESULT:
      Returns the Python record immediately for queued/running jobs. For an
      unresolved terminal record, queries the bounded host ledger when the CEP
      panel is available and idle, then mirrors a completed outcome locally.

    EXAMPLES:
      Reconcile a job whose reply was lost:
        {"params": {"jobId": "job_7f3a91c2"}}

    NOTES:
      - This tool never re-executes the original request.
      - Default inspection never changes files. finalize_export=true explicitly
        finalizes the selected export's owned backup after known completion.
        This can restore a destination or delete its backup, and is idempotent.
        Unknown completion retains both paths. In-memory ownership is lost on
        process restart; remaining backups then require manual recovery.
      - Explicit finalization succeeds only for verified output or restored
        backup. Conflict, pending completion/cleanup, and failure return failed
        execution with the retained file state; ordinary inspection may still
        successfully report those states.
      - A reset, expired record, missing finalizer, or busy host remains unknown.
    """
    coordinator = get_coordinator()
    if params.finalize_export:
        record = coordinator.get(params.job_id)
        owner = getattr(record, "export_files", None)
        if owner is not None:
            files = owner.finalize()
            finalized = files["state"] in ("verified", "restored")
            error = None
            if not finalized:
                kind = ("PENDING" if files["state"].startswith("pending") else
                        "CONFLICT" if files["state"] == "conflict" else "FAILED")
                error = {"code": "EXPORT_FINALIZATION_" + kind,
                         "message": files.get("detail") or
                         "Export file finalization did not complete: " + files["state"]}
            return build_call_result(CanonicalResult(
                execution=ExecutionStatus.SUCCEEDED if finalized else ExecutionStatus.FAILED,
                tool=_JOB_STATUS_NAME, error=error,
                jobId=params.job_id, data={"exportFiles": files, "replayed": False,
                                           "finalized": finalized},
            ))
        return build_call_result(CanonicalResult(execution=ExecutionStatus.FAILED,
            tool=_JOB_STATUS_NAME, jobId=params.job_id,
            error={"code": "E999", "message": "No retained export file owner for this job; no files changed. After restart, inspect backups manually."}))
    local = coordinator.status_of(params.job_id)
    if params.detail == "summary":
        local.pop("result", None)
    if local.get("probeRetired"):
        from illustrator_mcp.tools.connection import _probe
        from illustrator_mcp.execution.trusted_probe import blocking
        attempt = await _probe(5.0) if coordinator.probe_fence else None
        return build_call_result(CanonicalResult(execution=ExecutionStatus.SUCCEEDED,
            tool=_JOB_STATUS_NAME, jobId=params.job_id,
            data={"job": coordinator.status_of(params.job_id), "readinessAttempt": attempt,
                  "blocking": blocking(coordinator), "replayed": False}))
    local_status = local.get("status")

    if (local_status in (JobStatus.QUEUED.value, JobStatus.RUNNING.value)
            or local.get("outcomeSource") == "late_host_callback"):
        return build_call_result(CanonicalResult(
            execution=ExecutionStatus.SUCCEEDED,
            tool=_JOB_STATUS_NAME,
            jobId=params.job_id,
            data={
                "job": local,
                "reconciliation": {
                    "status": "not_attempted",
                    "reason": ("late_host_completion_retained"
                               if local.get("outcomeSource") == "late_host_callback"
                               else "job_is_still_active_locally"),
                    "replayed": False,
                },
            },
        ))

    # A direct, settled response is already stronger evidence than another
    # host query and can be returned without consuming the Illustrator slot.
    if local_status in (JobStatus.SUCCEEDED.value, JobStatus.FAILED.value) and (local.get("result") is not None or params.detail == "summary"):
        return build_call_result(CanonicalResult(
            execution=ExecutionStatus.SUCCEEDED,
            tool=_JOB_STATUS_NAME,
            jobId=params.job_id,
            data={
                "job": local,
                "reconciliation": {
                    "status": "already_settled",
                    "source": local.get("outcomeSource"),
                    "replayed": False,
                },
            },
        ))

    # A live evalScript cannot be preempted to ask the host about itself. The
    # Python record remains readable, but claiming that a host query ran would
    # be false and can tempt an unsafe retry.
    from illustrator_mcp.runtime import get_runtime

    runtime = get_runtime()
    bridge = runtime.bridge
    if bridge is not None:
        try:
            health = bridge.get_panel_health()
        except Exception:
            health = {}
        if health.get("busy"):
            return build_call_result(CanonicalResult(
                execution=ExecutionStatus.SUCCEEDED,
                tool=_JOB_STATUS_NAME,
                jobId=params.job_id,
                data={
                    "job": local,
                    "reconciliation": {
                        "status": "unavailable",
                        "reason": "host_busy",
                        "activeRequestId": health.get("active_request_id"),
                        "replayed": False,
                    },
                },
            ))

    from illustrator_mcp.execution.coordinator import HostUnresolvedError
    try:
        coordinator.assert_host_available()
    except HostUnresolvedError as exc:
        return build_call_result(CanonicalResult(
            execution=ExecutionStatus.SUCCEEDED, tool=_JOB_STATUS_NAME,
            jobId=params.job_id, data={"job": local, "reconciliation": {
                "status": "unavailable", "reason": "host_request_unresolved",
                "blockingJobId": exc.job_id, "replayed": False,
            }},
        ))

    from illustrator_mcp.host_session import HostSession

    host = await HostSession().job_status(params.job_id)
    host_record = host.get("record") if isinstance(host, dict) else None
    reconciliation: Dict[str, Any]
    if isinstance(host_record, dict):
        try:
            mirrored = coordinator.mirror_host_record(host_record)
            local = mirrored.to_dict()
            reconciliation = {
                "status": "reconciled" if host_record.get("completed") is True else "unknown",
                "source": "host_ledger",
                "replayed": False,
            }
        except (ValueError, JobConflictError) as exc:
            reconciliation = {
                "status": "conflict",
                "detail": str(exc),
                "replayed": False,
            }
    else:
        reconciliation = {
            "status": "unknown",
            "reason": host.get("reason", "host_unavailable") if isinstance(host, dict) else "host_unavailable",
            "detail": host.get("message") if isinstance(host, dict) else None,
            "replayed": False,
        }

    return build_call_result(CanonicalResult(
        execution=ExecutionStatus.SUCCEEDED,
        tool=_JOB_STATUS_NAME,
        jobId=params.job_id,
        data={"job": local, "host": host, "reconciliation": reconciliation},
    ))


# ==================== Path Boolean Tool ====================


class _BooleanSelector(TargetSelector):
    """A selector with one exact match. Use the canonical {target: {...}} form."""

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        # Preserve shared validation; publish the canonical wrapped form.
        # Flattening recursive variants during union/list reuse encounters
        # incomplete Pydantic definitions, before refs have been registered.
        return handler(core_schema)


class PathBooleanInput(MutationInputBase):
    """Input for path boolean operations via Python Clipper engine."""
    operation: Literal["subtract", "unite", "intersect", "xor"] = Field(
        ..., description="Boolean operation type"
    )
    subject: Union[str, _BooleanSelector] = Field(
        ..., description="Subject MCP ID or selector resolving exactly one PathItem/CompoundPathItem."
    )
    clip: Union[str, _BooleanSelector, List[Union[str, _BooleanSelector]]] = Field(
        ..., description="One clip operand or an ordered list of 1–100 clips. Each MCP ID or selector must resolve exactly one distinct path; handle selectors support untagged artwork."
    )
    # T05: a non-positive, NaN, or infinite tolerance makes the adaptive
    # subdivision termination test unsatisfiable — the engine would subdivide
    # without bound.  Constrain it here so it is rejected during input
    # validation, before any Illustrator call.
    flatten_tolerance: float = Field(
        default=0.5,
        gt=0.0,
        le=100.0,
        allow_inf_nan=False,
        description=(
            "Bézier flatten precision in points (default 0.5pt). "
            "Must be > 0 and finite; larger values flatten more coarsely."
        ),
    )
    max_segments: int = Field(
        default=500,
        gt=0,
        le=100_000,
        description="Max polyline segments per curve (safety cap)"
    )
    delete_originals: bool = Field(
        default=True,
        description="Remove input paths after successful boolean"
    )
    style: str = Field(
        default="subject",
        description="Style transfer: 'subject' (copy from subject), 'none' (no fill/stroke)"
    )
    layer: Optional[str] = Field(
        default=None,
        description="Target layer for result path"
    )
    name: Optional[str] = Field(
        default=None,
        description="Name for result item(s)"
    )

    @model_validator(mode="after")
    def _operand_bounds(self):
        clips = self.clip if isinstance(self.clip, list) else [self.clip]
        if not clips or len(clips) > 100:
            raise ValueError("Boolean requires between 1 and 100 clip operands")
        if any(isinstance(v, str) and not v.strip() for v in [self.subject, *clips]):
            raise ValueError("Boolean MCP IDs must not be empty")
        return self


_ORIGINALS_PRESERVED = (
    "Original paths were NOT deleted — the boolean result could not be verified"
)
_ORIGINALS_UNCERTAIN = (
    "Boolean commit outcome is unknown; original paths may or may not have been "
    "deleted. Inspect the document before retrying."
)


async def _delete_boolean_originals(all_ids: List[str]) -> tuple[dict, List[str]]:
    """Delete boolean input paths and report exactly what happened.

    T01: deletion is a mutation whose result must be validated like any other.
    Returns ``(originals, warnings)`` where ``originals.status`` is one of:

    ``deleted``  — every requested ID was removed
    ``partial``  — some IDs removed, others failed or were absent
    ``retained`` — nothing was removed
    ``unknown``  — the host response could not establish what happened
    """
    originals: Dict[str, Any] = {
        "requested": all_ids,
        "deleteRequested": True,
        "status": "unknown",
        "deletedIds": [],
    }
    warnings: List[str] = []

    delete_script = f"deleteByMcpIds({json.dumps(all_ids)})"
    try:
        delete_response = await execute_script_with_context(
            script=delete_script,
            command_type="path_boolean:delete",
            tool_name="illustrator_path_boolean",
            includes=["geo_boolean", "doc_session"],
        )
    except Exception as e:
        warnings.append(
            f"Deletion of originals failed: {e}. Original paths may still exist."
        )
        return originals, warnings

    del_data, del_error = _host_payload(delete_response, "Deletion of originals")
    if del_error:
        warnings.append(
            f"{del_error}. Whether the original paths were removed is unknown."
        )
        return originals, warnings

    warnings.extend(del_data.get("warnings", []))

    deleted_ids = del_data.get("deletedIds")
    if isinstance(deleted_ids, list):
        originals["deletedIds"] = [i for i in deleted_ids if isinstance(i, str)]
    for key in ("failedIds", "notFoundIds", "ambiguousIds"):
        value = del_data.get(key)
        if isinstance(value, list) and value:
            originals[key] = value

    # Prefer the explicit ID list; fall back to the numeric count for hosts
    # that predate the richer return shape.
    if isinstance(deleted_ids, list):
        removed = len(originals["deletedIds"])
    elif isinstance(del_data.get("deleted"), int):
        removed = del_data["deleted"]
    else:
        warnings.append(
            "Deletion result did not report what was removed — "
            "original paths may still exist."
        )
        return originals, warnings

    if removed == len(all_ids):
        originals["status"] = "deleted"
    elif removed == 0:
        originals["status"] = "retained"
        warnings.append(
            f"None of the {len(all_ids)} original path(s) were deleted."
        )
    else:
        originals["status"] = "partial"
        warnings.append(
            f"Only {removed} of {len(all_ids)} original path(s) were deleted."
        )
    return originals, warnings


_BOOL_NAME = "illustrator_path_boolean"


@mcp.tool(name=_BOOL_NAME, annotations=TOOL_ANNOTATIONS[_BOOL_NAME])
async def illustrator_path_boolean(params: PathBooleanInput) -> CallToolResult:
    """Perform boolean operations (subtract, unite, intersect, xor) on paths.

    CONTRACT: readOnly=False, destructive=True, idempotent=False, openWorld=False

    WHEN TO USE:
      - Combining shapes (unite), cutting holes (subtract), finding overlaps (intersect)
      - Any shape sculpting that needs boolean geometry

    PIPELINE:
      1. Extract geometry from Illustrator paths (ExtendScript)
      2. Flatten Bezier curves if present (Python)
      3. Run boolean operation via Clipper (Python)
      4. Reconstruct result as PathItem or CompoundPathItem (ExtendScript)
      5. Delete originals on success (if delete_originals=True)

    EXAMPLES:
      Unite:
        {"params": {"operation": "unite", "subject": "body_id", "clip": ["wing_id"]}}
      Subtract a hole:
        {"params": {"operation": "subtract", "subject": "plate_id", "clip": ["hole_id"]}}

    NOTES:
      - Operates on fill geometry only — strokes are ignored (warning emitted)
      - Simple results produce PathItem; shapes with holes produce CompoundPathItem
      - Each operand is an MCP ID or a selector resolving exactly one path.
      - Untagged paths use handle selectors from query/observe; notes are not stamped.
      - Duplicate/overlapping operands and stale handles are refused before commit.
    """
    # ── Track mutation cadence before any early return ──────────
    # B3: Decremented in except block if execution fails

    from illustrator_mcp.execution.logical_job import run_logical_job
    async def body(job):
        _counter.increment()
        return await _path_boolean_impl(params, job=job)
    try:
        return await run_logical_job(_BOOL_NAME, params, body)
    except Exception:
        _counter.decrement()
        raise


async def _path_boolean_impl(params: PathBooleanInput, job=None) -> str | CallToolResult:
    """Inner implementation of path_boolean, extracted for B18 counter safety.

    Args:
        params: Tool input.
        job: Optional :class:`~illustrator_mcp.execution.JobRecord` for the
            reservation held across this whole multi-call sequence (T12).
            Effects are recorded on it as they occur, so a failure part-way
            through still reports what had already changed.
    """

    # ── Step 0: Import guard ────────────────────────────────────
    try:
        from illustrator_mcp.geometry import (
            path_boolean_compound, flatten_path, Region,
        )
        # Verify pyclipper is actually available (not cached as None)
        from illustrator_mcp.geometry import pyclipper as _pc_check
        if _pc_check is None:
            raise ImportError("pyclipper cached as None — force reload")
    except ImportError:
        # Module may have been cached before pyclipper was installed.
        # Force-reload geometry to pick up newly installed pyclipper.
        try:
            import importlib
            import illustrator_mcp.geometry as _geo_mod
            importlib.reload(_geo_mod)
            path_boolean_compound = _geo_mod.path_boolean_compound
            flatten_path = _geo_mod.flatten_path
            Region = _geo_mod.Region
        except ImportError as e:
            return make_envelope(
                ok=False,
                error=str(e),
                diagnostics={"tool": "path_boolean", "hint": "pip install pyclipper"},
            )

    context = f"path_boolean: {params.operation}"
    diagnostics: Dict[str, Any] = {"operation": params.operation, "tool": "path_boolean"}

    # Normalize clip to list
    clip_ids = params.clip if isinstance(params.clip, list) else [params.clip]
    all_ids = [v.model_dump(mode="json", exclude_none=True) if isinstance(v, TargetSelector) else v
               for v in [params.subject] + clip_ids]
    selector_route = any(isinstance(v, dict) for v in all_ids)
    diagnostics["subject"] = all_ids[0]
    diagnostics["clips"] = all_ids[1:]

    # ── Step 1: Extract geometry via ExtendScript ───────────────
    extract_script = f"extractPathGeometry({json.dumps(all_ids)})"
    try:
        extract_response = await execute_script_with_context(
            script=extract_script,
            command_type="path_boolean:extract",
            tool_name="illustrator_path_boolean",
            includes=["geo_boolean", "doc_session"],
        )
    except Exception as e:
        return make_envelope(
            ok=False,
            error=f"Geometry extraction failed: {e}",
            diagnostics=diagnostics,
        )

    # Parse extraction result.  Bridge response may come as:
    #   {result: '{"paths":...}'}            — direct string
    #   {result: {ok:true, data:'...'}}       — host.jsx envelope
    #   {result: {paths:[...]}}              — already parsed dict
    logger.debug(
        "path_boolean extract_response keys=%s",
        list(extract_response.keys()) if isinstance(extract_response, dict) else "n/a",
    )
    note_host_truncation(diagnostics, extract_response)
    geo_data, extract_error = _host_payload(extract_response, "Geometry extraction")
    if extract_error:
        return make_envelope(
            ok=False,
            error=extract_error,
            diagnostics=diagnostics,
        )

    integrity = extract_response.get("integrity") or {}
    if integrity.get("status") != "verified":
        # Legacy peers remain readable, but their geometry cannot authorize a
        # dependent commit. No reconstruction/deletion has been dispatched.
        return make_envelope(
            ok=False,
            error="[C014] Geometry integrity is unverified; reload a payload-v1 CEP panel before running Boolean operations.",
            warnings=["Original paths were NOT deleted; no Boolean commit was dispatched."],
            diagnostics={**diagnostics, "integrity":integrity or {"status":"unknown"},
                         "effects":declare_effects(complete=True)},
        )

    warnings = list(geo_data.get("warnings", []))
    paths = geo_data.get("paths", [])
    operand_handles = geo_data.get("operandHandles") if selector_route else None
    if selector_route:
        if (not isinstance(operand_handles, list) or len(operand_handles) != len(all_ids)
                or any(not isinstance(h, str) or not h.startswith("mcp_h_") for h in operand_handles)
                or len(set(operand_handles)) != len(operand_handles)):
            return make_envelope(ok=False, error="Boolean extraction did not return exact operand handles; no commit dispatched", diagnostics=diagnostics)
        all_ids = operand_handles

    if len(paths) < 2:
        return make_envelope(
            ok=False,
            error=f"Need at least 2 paths (subject + clip), got {len(paths)}",
            diagnostics=diagnostics,
        )

    # ── Step 2: Flatten Bézier curves if needed ─────────────────
    from illustrator_mcp.execution.progress import milestone
    await milestone("boolean: compute; duration unknown")
    subject_geo = paths[0]
    clip_geos = paths[1:]
    subject_style = subject_geo.get("style", {})

    def _to_contour(path_data):
        """Convert extracted path data to a flat contour for Clipper.

        Expects canonical per-point format (mcp.geometry.v1):
            points: [{anchor, left, right, pointType}, ...]
        """
        pts = path_data["points"]
        points = [tuple(p["anchor"]) for p in pts]
        if path_data.get("hasHandles"):
            # Default missing left/right to anchor (corner points)
            in_handles = [tuple(p.get("left", p["anchor"])) for p in pts]
            out_handles = [tuple(p.get("right", p["anchor"])) for p in pts]
            points = flatten_path(
                anchors=points,
                left_handles=in_handles,
                right_handles=out_handles,
                closed=path_data.get("closed", True),
                tolerance=params.flatten_tolerance,
                max_segments=params.max_segments,
            )
            warnings.append(
                f"Path '{path_data.get('name', path_data.get('mcpId', '?'))}' "
                f"had curves — flattened to {len(points)} points (tolerance={params.flatten_tolerance}pt)"
            )
        return points

    try:
        def _all_contours(path_data):
            raw_contours = path_data.get("contours") or [path_data]
            return [_to_contour(contour) for contour in raw_contours]

        subject_contours = _all_contours(subject_geo)
        clip_contours = [
            contour
            for clip_geo in clip_geos
            for contour in _all_contours(clip_geo)
        ]
    except ValueError as e:
        return make_envelope(
            ok=False,
            error=str(e),
            diagnostics=diagnostics,
        )

    # ── Step 3: Run Clipper boolean ─────────────────────────────
    try:
        clip_fill_rules = {cg.get("fillRule", "nonzero") for cg in clip_geos}
        if len(clip_fill_rules) > 1:
            raise ValueError(
                "Clip compound paths use mixed fill rules; split the boolean into supported steps"
            )
        regions: list[Region] = path_boolean_compound(
            subject_contours=subject_contours,
            clip_contours=clip_contours,
            operation=params.operation,
            subject_fill_rule=subject_geo.get("fillRule", "nonzero"),
            clip_fill_rule=next(iter(clip_fill_rules), "nonzero"),
        )
    except Exception as e:
        return make_envelope(
            ok=False,
            error=f"Boolean operation failed: {e}",
            diagnostics=diagnostics,
        )

    # ── Step 4: Guarded reconstruction + deletion commit ────────
    # Convert Region objects to JSON-serializable dicts
    regions_data = []
    for r in regions:
        rd = {
            "id": f"mcp_bool_{uuid.uuid4().hex}",
            "outer": [list(pt) for pt in r.outer],
        }
        if r.holes:
            rd["holes"] = [[list(pt) for pt in h] for h in r.holes]
        regions_data.append(rd)

    # Determine style to apply
    style_def = {}
    if params.style == "subject":
        style_def = subject_style
    # "none" → empty style_def (Illustrator defaults)

    commit_params = {
        "regions": regions_data,
        "style": style_def,
        "fillRule": subject_geo.get("fillRule", "nonzero"),
        "originalIds": all_ids,
        "preconditions": geo_data.get("preconditions") or [
            p.get("precondition") for p in paths
        ],
        "context": geo_data.get("context") or {},
        "deleteOriginals": params.delete_originals,
    }
    if params.layer:
        commit_params["layer"] = params.layer
    if operand_handles is not None:
        commit_params["operandHandles"] = operand_handles
    if params.name:
        commit_params["name"] = params.name

    commit_script = f"commitBooleanRegions({json.dumps(commit_params)})"
    try:
        commit_response = await execute_script_with_context(
            script=commit_script,
            command_type="path_boolean:commit",
            tool_name="illustrator_path_boolean",
            params={"transportDocumentId": (geo_data.get("context") or {}).get("documentToken")},
            includes=["geo_boolean", "doc_session"],
        )
    except Exception as e:
        return make_envelope(
            ok=False,
            error=f"Boolean commit failed: {e}",
            # The call crossed the commit boundary before it failed. Without a
            # structured host result, a completed commit and a rejected commit
            # are indistinguishable to Python.
            warnings=warnings + [_ORIGINALS_UNCERTAIN],
            diagnostics=diagnostics,
        )

    note_host_truncation(diagnostics, commit_response)
    raw_commit = commit_response.get("result") if isinstance(commit_response, dict) else None
    if isinstance(raw_commit, dict) and "ok" in raw_commit:
        if raw_commit.get("ok") is False:
            inner = raw_commit.get("error") or {}
            return make_envelope(
                ok=False,
                error=inner.get("message", str(inner)) if isinstance(inner, dict) else str(inner),
                warnings=warnings + [_ORIGINALS_UNCERTAIN],
                diagnostics=diagnostics,
            )
        raw_commit = raw_commit.get("data")
    if isinstance(raw_commit, str):
        try:
            commit_data = json.loads(raw_commit)
        except json.JSONDecodeError:
            commit_data = None
    else:
        commit_data = raw_commit
    if not isinstance(commit_data, dict):
        return make_envelope(
            ok=False,
            error="Boolean commit returned no usable result; its outcome is unknown",
            warnings=warnings + [_ORIGINALS_UNCERTAIN],
            diagnostics={**diagnostics, "effectsComplete": False},
        )

    commit_effects = commit_data.get("effects") or {
        "created": [], "modified": [], "deleted": [], "complete": False
    }
    created_ids = list(commit_effects.get("created") or commit_data.get("ids") or [])
    deleted_ids = list(commit_effects.get("deleted") or [])
    if job is not None:
        get_coordinator().record_effects(
            job.job_id,
            created=created_ids,
            deleted=deleted_ids,
            complete=bool(commit_effects.get("complete")),
        )

    if commit_data.get("error"):
        diagnostics["booleanCommit"] = commit_data
        originals = commit_data.get("originals") or {}
        if commit_data.get("phase") == "delete":
            # Deletion is required work. Preserve the verified replacements and
            # survivor evidence while classifying the whole request explicitly.
            return build_call_result(CanonicalResult(
                tool=_BOOL_NAME,
                execution="partial" if created_ids or deleted_ids else "failed",
                data=commit_data,
                error={"code": commit_data.get("errorCode", "BOOLEAN_DELETE_INCOMPLETE"),
                       "message": commit_data.get("message", "Required original deletion was incomplete")},
                warnings=warnings + list(originals.get("warnings") or []) + [
                    "Required original deletion was incomplete; verified replacements were retained"
                ],
                diagnostics=diagnostics,
                effects=Effects(created=created_ids, deleted=deleted_ids,
                                complete=bool(commit_effects.get("complete"))),
            ))
        if deleted_ids:
            preserved_warning = (
                "Some originals were deleted; verified replacements were retained"
            )
        elif (
            originals.get("status") == "retained"
            and originals.get("deletedIds", []) == []
        ):
            # A structured host result that explicitly accounts for the
            # originals is positive evidence that the guarded commit stopped
            # before deleting its inputs. Other effects can still be incomplete
            # when reconstruction rollback leaves unidentified artwork.
            preserved_warning = _ORIGINALS_PRESERVED
        else:
            preserved_warning = _ORIGINALS_UNCERTAIN
        commit_warnings = warnings + [preserved_warning]
        # Artwork a rollback could not remove is untagged and invisible to
        # every id-based tool, so the caller has to be told in the warnings
        # rather than only in diagnostics nothing routinely reads.
        rollback_failures = commit_data.get("cleanupFailures") or []
        if rollback_failures:
            diagnostics["rollbackFailures"] = rollback_failures
            commit_warnings.append(
                f"Rollback left artwork on the page for "
                f"{len(rollback_failures)} region(s); it carries no MCP id, so "
                f"it must be removed by hand before retrying"
            )
        return make_envelope(
            ok=False,
            error={
                "code": commit_data.get("errorCode", "R_APPLY_FAILED"),
                "message": commit_data.get("message", "Boolean commit failed"),
            },
            warnings=commit_warnings,
            diagnostics={
                **diagnostics,
                # A failed commit still changed things, and saying so is the
                # difference between a safe retry and a duplicate.
                "effects": declare_effects(
                    created=created_ids,
                    deleted=deleted_ids,
                    complete=bool(commit_effects.get("complete")),
                ),
            },
        )

    originals = commit_data.get("originals") or {}
    warnings.extend(originals.get("warnings") or [])
    if originals.get("status") == "partial":
        warnings.append(
            "Original deletion was partial; all verified boolean replacements were retained."
        )
    result = dict(commit_data)
    if not regions:
        result["message"] = "Boolean result is empty"
    # The ids were already known here and handed to the coordinator; they just
    # never reached the field a client is told to read. The host's own report
    # stays nested in `result` as detail.
    return make_envelope(
        ok=True,
        result=result,
        warnings=warnings,
        diagnostics={
            **diagnostics,
            "effects": declare_effects(
                created=created_ids,
                deleted=deleted_ids,
                complete=bool(commit_effects.get("complete")),
            ),
        },
    )
