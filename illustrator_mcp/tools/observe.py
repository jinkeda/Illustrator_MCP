"""First-class coordinated visual observation for Illustrator (T19)."""

import base64
import json
import time
import uuid
from typing import Any, Dict, List, Literal, Optional, Union

from mcp.types import CallToolResult, ImageContent
from pydantic import Field, model_validator

from illustrator_mcp.execution import get_coordinator, request_digest
from illustrator_mcp.execution.document_intent import observation_context
from illustrator_mcp.proxy_client import (
    clear_reserved_job,
    execute_script_with_context,
    mark_reserved_job,
)
from illustrator_mcp.results import (
    CanonicalResult,
    ExecutionStatus,
    Verification,
    VerificationStatus,
    build_call_result,
)
from illustrator_mcp.shared import mcp
from illustrator_mcp.tools.base import TOOL_ANNOTATIONS, ToolInputBase
from illustrator_mcp.tools.preview import (
    CaptureOptions, capture_frame, ClipSpace, validate_clip_space, capture_metadata,
    PREVIEW_BACKGROUNDS,
    _annotate_preview,
    _capture_artboard,
    _capture_artboards,
    artboard_count,
    composite_background,
    contact_sheet,
    contact_sheet_capture_max_dim,
    resolve_artboards,
)


class ObserveInput(ToolInputBase):
    """Options for a coordinated raw/annotated Illustrator observation."""

    mode: Literal["raw", "annotated", "both"] = "annotated"
    max_dim: int = Field(1024, ge=128, le=4096)
    max_items: int = Field(200, ge=1, le=2000)
    clip_box: Optional[List[float]] = Field(
        default=None,
        description="Optional [xmin,ymin,xmax,ymax] artboard-relative crop in points.",
    )
    include_map: Optional[bool] = None
    map_detail: Literal["compact", "full"] = "full"
    clip_space: ClipSpace = "artboard_relative_y_down"
    exact_visible_count: bool = Field(False, description="Scan all pageItems for exact visible totals; default bounds the scan at 10,000 items or max_items+1 visible matches.")
    timeout: float = Field(30.0, gt=0, le=300,
        description="Queue wait and each host call timeout in seconds, not a total deadline. Capture/annotation may make several calls.")
    detail: Literal["summary", "full"] = Field("full", description="Opt-in compact diagnostics; maps and handles remain available. Full results are retained through job_status until job expiry.")

    artboards: Union[Literal["active", "all"], List[int]] = Field(
        default="active",
        description=(
            "Which artboards to capture. 'active' (default) is a single "
            "board. 'all', or an explicit list of indices, returns one "
            "labelled contact sheet instead, so several boards can be "
            "compared without building an overview artboard by hand."
        ),
    )
    background: Literal["transparent", "white", "checkerboard"] = Field(
        default="white",
        description=(
            "What to flatten the preview onto. Illustrator exports with "
            "transparency, which hides dark strokes against a dark viewer, so "
            "'white' is the default. 'checkerboard' shows where the artwork "
            "is genuinely transparent. 'transparent' keeps the raw export."
        ),
    )

    @model_validator(mode="after")
    def _validate_crop(self):
        if self.clip_box is not None:
            self.clip_box = validate_clip_space(self.clip_box, self.clip_space)
            if self.clip_space == "illustrator_native_y_up" and self.artboards != "active":
                raise ValueError("V016: native clip_box requires one active artboard; nextStep: select one artboard")
        if self.include_map is None:
            self.include_map = self.mode != "raw"
        return self


def _observation_payload(response: Any, *, end=False) -> Dict[str, Any]:
    from illustrator_mcp.utils.response import require_jsx_payload
    return require_jsx_payload(response, context="observation", allow_domain_failure=end)


_OBSERVE_NAME = "illustrator_observe"


@mcp.tool(name=_OBSERVE_NAME, annotations=TOOL_ANNOTATIONS[_OBSERVE_NAME])
@observation_context
async def illustrator_observe(params: ObserveInput) -> CallToolResult:
    """Capture coordinated visual evidence and precise follow-up handles.

    CONTRACT: readOnly=False, destructive=False, idempotent=True, openWorld=True

    WHEN TO USE:
      - Inspecting current artwork before or after managed edits
      - Obtaining raw or annotated previews and an annotation-to-handle map
      - Capturing a high-resolution crop without a dummy mutation
      - Visual verification instead of exporting a deliverable: capture uses
        imageCapture rather than exportFile. The isolated Illustrator 30.7.0
        CEP capture control preserved the saved flag; inspect the returned
        preservation verification rather than assuming every capture is safe.

    OPTIONS:
      mode: raw, annotated, or both
      clip_box: optional targeted crop in artboard-relative screen coordinates
      max_items: annotation-map cap; omissions are reported explicitly

    RESULT:
      Returns image content plus context, timing, annotation map, handle expiry,
      managed runtime generation, omissions, and preservation verification.

    EXAMPLES:
      Compact annotated evidence and handles:
        {"params": {"mode": "annotated", "detail": "summary", "map_detail": "compact"}}
      Look at the page and get handles for what is on it:
        {"params": {"mode": "both"}}
      Crop to a region, in artboard-relative points:
        {"params": {"mode": "raw", "clip_box": [0, 0, 200, 120]}}
      Compare every artboard on one contact sheet:
        {"params": {"artboards": "all"}}
      Three specific boards, on a checkerboard:
        {"params": {"artboards": [0, 2, 5], "background": "checkerboard"}}

    NOTES:
      - Handles are document/session scoped and never stamp notes
      - A sampled fingerprint is not used as a document revision
      - The coordinator prevents managed mutations from interleaving with capture
    """
    import asyncio
    from illustrator_mcp.execution import HostUnresolvedError
    coordinator = get_coordinator()
    started = time.perf_counter()
    dispatched = False
    try:
        async with coordinator.reserve(digest=request_digest(params.model_dump(mode="json")), label="observe", wait_timeout=params.timeout) as job:
            dispatched = True
            result = await _observe_impl(params, started)
            canonical = CanonicalResult.model_validate(result.structuredContent)
            canonical.job_id = job.job_id
            from illustrator_mcp.execution import JobStatus
            from illustrator_mcp.execution.logical_job import retain_presented_result
            if job.awaiting_host or job.status is JobStatus.UNKNOWN:
                canonical.execution = ExecutionStatus.UNKNOWN
                canonical.effects.complete = False
                canonical.diagnostics["nextStep"] = {"tool": "illustrator_job_status", "params": {"jobId": job.job_id}}
            full = build_call_result(canonical, list(result.content[2:]))
            if canonical.execution != ExecutionStatus.UNKNOWN:
                coordinator.complete(job.job_id, JobStatus.SUCCEEDED if canonical.execution == ExecutionStatus.SUCCEEDED else JobStatus.FAILED,
                    result=full.structuredContent, source="direct_response")
                retain_presented_result(full, executing_job=job)
            return full
    except (asyncio.TimeoutError, HostUnresolvedError, RuntimeError) as exc:
        if dispatched:
            raise
        snapshot = get_coordinator().snapshot()
        blocker = getattr(exc, "job_id", None) or snapshot.get("activeJob")
        diagnostics = {"phase": "queue", "dispatched": False, "blockingJob": blocker, "timing": {"queueMs": round((time.perf_counter()-started)*1000, 2)}}
        if blocker:
            diagnostics["nextStep"] = {"tool": "illustrator_job_status", "params": {"jobId": blocker}}
        return build_call_result(CanonicalResult(
            tool=_OBSERVE_NAME, execution=ExecutionStatus.FAILED,
            error={"code": "R_OBSERVATION_QUEUE", "message": str(exc) or "Observation queue wait expired; nothing dispatched."},
            diagnostics=diagnostics,
        ))


async def _observe_impl(params: ObserveInput, started: float) -> CallToolResult:
    coordinator = get_coordinator()
    observation_id = f"obs_{uuid.uuid4().hex}"

    timings = {"queueMs": round((time.perf_counter() - started) * 1000, 2)}
    phase = "begin"
    phase_started = time.perf_counter()
    token = mark_reserved_job()
    begin: Dict[str, Any] = {}
    end: Dict[str, Any] = {}
    raw_bytes: Optional[bytes] = None
    sheet_layout: Optional[dict] = None
    annotated_bytes: Optional[bytes] = None
    annotation_map: Dict[str, Any] = {"meta": {}, "annotations": [], "warnings": []}
    failure: Optional[str] = None
    async def capture(**kwargs):
        nonlocal raw_bytes
        raw_bytes = await _capture_artboard(**kwargs, strict=True)
        return raw_bytes

    async def annotate(**kwargs):
        nonlocal phase, phase_started
        timings["captureMs"] = round((time.perf_counter() - phase_started) * 1000, 2)
        phase = "annotation"
        phase_started = time.perf_counter()
        return await _annotate_preview(**kwargs, strict=True)

    capture_metadata.set(None)
    try:
        begin_response = await execute_script_with_context(
            script=(
                "JSON.stringify(mcpObservationBegin("
                f"{json.dumps(observation_id)}, {params.max_items}, "
                f"{json.dumps(params.clip_box)}, {json.dumps(params.exact_visible_count)}, {json.dumps(params.clip_space)}, {json.dumps(params.include_map)}))"
            ),
            command_type="observation:begin",
            tool_name=_OBSERVE_NAME,
            timeout=params.timeout,
            includes=["observation"],
        )
        begin = _observation_payload(begin_response)
        if not begin.get("ok"):
            raise RuntimeError(begin.get("message", "Observation could not start"))

        timings["beginMs"] = round((time.perf_counter() - phase_started) * 1000, 2)
        phase = "capture"
        phase_started = time.perf_counter()
        board_indices = resolve_artboards(
            params.artboards,
            await artboard_count(params.timeout, strict=True)
            if params.artboards != "active" else None,
        )

        if params.artboards != "active" and not board_indices:
            raise ValueError("No requested artboard index is available; nothing captured")

        if board_indices:
            # A contact sheet spans several coordinate systems, so the
            # annotation map — whose numbers address one artboard — would
            # be actively misleading over it. Capture is raw, and the
            # omission is reported rather than left for the caller to
            # discover.
            captures = await _capture_artboards(
                board_indices, max_dim=contact_sheet_capture_max_dim(
                    params.max_dim, len(board_indices)),
                timeout=params.timeout, fmt="png", strict=True,
            )
            raw_bytes, sheet_layout = contact_sheet(
                captures, max_dim=params.max_dim,
                background=params.background,
            )
            if raw_bytes is None and captures:
                # Compositing failed but the boards were captured; the
                # first one is better evidence than none.
                raw_bytes = composite_background(
                    captures[0][1], params.background
                )
        else:
            raw_bytes, annotated_bytes, annotation_map = await capture_frame(
                CaptureOptions(max_dim=params.max_dim, timeout=params.timeout,
                               clip_box=params.clip_box, clip_space=params.clip_space),
                annotate=params.mode in ("annotated", "both") or params.include_map,
                max_items=params.max_items, background=params.background,
                capture=capture, annotator=annotate, render_annotation=params.mode != "raw",
            )
    except Exception as exc:
        failure = str(exc)
        failure_phase = phase
        host_error = getattr(exc, "host_error", None)
        from illustrator_mcp.errors import ErrorCode
        for code, step in [(ErrorCode.V_CAPTURE_EMPTY_REGION, "Choose an intersecting crop"),
                           (ErrorCode.V_CAPTURE_MINIMUM_BUDGET_EXCEEDED, "Use a smaller region")]:
            if code.value + ":" in failure:
                host_error = {"code":code.value, "message":failure, "nextStep":step}
                break
    finally:
        timings[phase + "Ms"] = round((time.perf_counter() - phase_started) * 1000, 2)
        phase_started = time.perf_counter()
        if begin:
            try:
                coordinator.assert_host_available()
                end_response = await execute_script_with_context(
                    script=f"JSON.stringify(mcpObservationEnd({json.dumps(observation_id)}))",
                    command_type="observation:end",
                    tool_name=_OBSERVE_NAME,
                    timeout=params.timeout,
                    includes=["observation"],
                )
                end = _observation_payload(end_response, end=True)
            except Exception as exc:
                end = {"ok": False, "status": "unavailable", "message": str(exc), "hostError": getattr(exc, "host_error", None)}
        timings["endMs"] = round((time.perf_counter() - phase_started) * 1000, 2)
        clear_reserved_job(token)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    if failure:
        return build_call_result(CanonicalResult(
            execution=ExecutionStatus.FAILED,
            tool=_OBSERVE_NAME,
            error={"code": host_error.get("code", "R_OBSERVATION_FAILED") if isinstance(host_error, dict) else "R_OBSERVATION_FAILED", "message": host_error.get("message", failure) if isinstance(host_error, dict) else failure, "nextStep": host_error.get("nextStep") if isinstance(host_error, dict) else None},
            diagnostics={"phase": failure_phase, "hostError": host_error, "cleanup": end, "timing": timings, "captureSucceeded": raw_bytes is not None},
            verification=Verification(
                status=VerificationStatus.UNAVAILABLE,
                scope="visual_observation",
                detail="Observation did not produce consistent evidence.",
            ),
            data={"observationId": observation_id, "context": begin.get("context")},
        ))
    requested_image = raw_bytes if params.mode == "raw" or sheet_layout is not None else annotated_bytes
    if requested_image is None:
        verification = Verification(
            status=VerificationStatus.UNAVAILABLE,
            scope="visual_observation",
            detail="The requested preview image could not be captured.",
        )
        result = CanonicalResult(
            execution=ExecutionStatus.FAILED,
            tool=_OBSERVE_NAME,
            error={"code": "R_PREVIEW_UNAVAILABLE", "message": verification.detail},
            verification=verification,
            data={"observationId": observation_id, "context": begin.get("context")},
        )
        return build_call_result(result)

    if end.get("status") == "passed":
        verification_status = VerificationStatus.PASSED
        verification_detail = (
            "Selection, active layer, artboard, saved state, and observed artwork were preserved."
        )
    elif end.get("status") == "failed":
        verification_status = VerificationStatus.FAILED
        verification_detail = "Observation preservation check found: " + ", ".join(end.get("differences") or [])
    else:
        verification_status = VerificationStatus.UNAVAILABLE
        verification_detail = end.get("message", "Observation preservation check was unavailable")

    omissions = list(begin.get("omissions") or [])
    if not params.include_map:
        omissions.append({"kind": "annotation_map", "reason": "not_requested"})
    if sheet_layout is not None:
        omissions.append({
            "kind": "annotation_map",
            "reason": "contact_sheet_spans_multiple_artboards",
            "detail": (
                "Annotation numbers address one artboard's coordinates. Call "
                "observe again with artboards='active' on the board you want "
                "to edit, to get handles you can target."
            ),
        })
    if params.map_detail == "compact":
        annotation_map = compact_map(annotation_map)
    data = {
        "observationId": observation_id,
        "context": begin.get("context"),
        "runtime": {
            "host": begin.get("runtime"),
            "connectionGeneration": coordinator.connection_generation,
        },
        "timing": {**timings, "totalMs": elapsed_ms, "hostSpanMs": end.get("durationMs"), "hostGuardMs": end.get("durationMs")},
        "preservation": {"phase": "end", **end},
        "evidence": {
            "raw": raw_bytes is not None,
            "annotated": annotated_bytes is not None,
            "crop": params.clip_box,
            "crop_space": params.clip_space,
            "capture": capture_metadata.get(),
            "background": params.background,
            "contactSheet": sheet_layout,
        },
        "map": annotation_map if params.include_map else None,
        "omissions": omissions,
        "changeHints": {"sampledFingerprint": None, "completeRevision": False},
    }
    blocks = []
    if (params.mode in ("raw", "both") or sheet_layout is not None) and raw_bytes:
        blocks.append(ImageContent(type="image", data=base64.b64encode(raw_bytes).decode("ascii"), mimeType="image/png"))
    if params.mode in ("annotated", "both") and annotated_bytes:
        blocks.append(ImageContent(type="image", data=base64.b64encode(annotated_bytes).decode("ascii"), mimeType="image/png"))
    return build_call_result(
        CanonicalResult(
            execution=ExecutionStatus.SUCCEEDED,
            tool=_OBSERVE_NAME,
            data=data,
            verification=Verification(
                status=verification_status,
                scope="observation_guard" if end.get("complete") else "observed_items",
                detail=verification_detail,
            ),
            warnings=list(annotation_map.get("warnings") or []),
        ),
        extra_content=blocks,
    )


def compact_map(mapping):
    """Lossless targeting projection; common expiry is factored only when equal."""
    from copy import deepcopy
    result = deepcopy(mapping)
    entries = result.get("annotations", [])
    meta = result.setdefault("meta", {})
    expiries = [entry.get("handleExpiresAt") for entry in entries]
    common = expiries[0] if expiries and all(value == expiries[0] for value in expiries) else None
    if common is not None:
        meta["handleExpiresAt"] = common
    for entry in entries:
        if common is not None:
            entry.pop("handleExpiresAt", None)
        if not entry.get("mcp_id"):
            entry.pop("mcp_id", None)
        entry.pop("has_mcp_id", None)
        if not entry.get("name") or entry.get("name") == entry.get("type"):
            entry.pop("name", None)
    return result
