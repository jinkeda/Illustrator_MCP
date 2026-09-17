"""Bounded logical-job outcome handling shared by mutation producers.

The coordinator owns scheduling; this adapter owns canonical direct outcomes.
A late host reply is only phase evidence and never replays the body.
"""
from __future__ import annotations

from illustrator_mcp.execution import (
    DuplicateJobError, HostUnresolvedError, JobCancelledError, JobConflictError,
    JobStatus, get_coordinator, request_digest,
)
from illustrator_mcp.results import CanonicalResult, Effects, ExecutionStatus, build_call_result, finalize_tool_result


def intent_digest(tool, params):
    """Version the descriptor so existing structured-job digests stay distinct."""
    value = params.model_dump(mode="json", by_alias=True, exclude={"job_id"})
    if tool == "illustrator_execute_task":
        from illustrator_mcp.tools.migration import task_intent
        value = task_intent(params)
        value["expected_document_token"] = getattr(params, "expected_document_token", None)
    # Presentation-only options cannot cause a second mutation. Repeats retain
    # the first call's evidence, including content blocks.
    for key in ("return_preview", "preview_mode", "final_step", "clip_box", "return_image"):
        value.pop(key, None)
    value.pop("description", None)  # Diagnostic label, not execution intent.
    if value.get("file_path"):
        import hashlib
        from pathlib import Path
        path = Path(value["file_path"]).resolve()
        value["file_path"] = str(path)
        is_source = (tool in {"illustrator_place_file", "illustrator_set_reference", "illustrator_execute_script"}
                     or tool == "illustrator_document" and value.get("action") == "open")
        if is_source:
            existing = get_coordinator().get(getattr(params, "job_id", None))
            snapshot = existing.source_snapshot if existing is not None else None
            if not snapshot or snapshot.get("path") != str(path):
                snapshot = {"path": str(path)}
                try:
                    content = (params._script_source.encode("utf-8")
                               if tool == "illustrator_execute_script" and hasattr(params, "_script_source")
                               else path.read_bytes())
                    snapshot.update(sha256=hashlib.sha256(content).hexdigest(), size=len(content))
                    if tool == "illustrator_execute_script":
                        snapshot["scriptSource"] = getattr(params, "_script_source", content.decode("utf-8"))
                except OSError:
                    snapshot["unavailable"] = True  # The producer reports the file error.
            params._job_source = snapshot
            value["source"] = {k: v for k, v in snapshot.items() if k != "scriptSource"}
    if "includes" in value:
        import hashlib
        from pathlib import Path
        from illustrator_mcp.libraries import LibraryResolver
        resolver = LibraryResolver(Path(__file__).resolve().parents[1] / "resources" / "scripts")
        source, order = resolver.resolve_with_order(value.get("includes") or [])
        value["includes"] = {"order": order, "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest()}
    return request_digest({"version": "logical-intent-v1", "tool": tool, "params": value})


def retain_presented_result(result, *, executing_job=None, source_result=None):
    """Retain only the executing call's result and its one journal reduction.

    A job ID identifies a record, not the authority to replace its outcome.
    Carry process-local object identity from the reserved body to the outer
    registered handler; no caller-controlled response field grants authority.
    """
    coordinator = get_coordinator()
    data = result.structuredContent or {}
    job = coordinator.get(data.get("jobId")) if data.get("jobId") else None
    if job is None or not job.status.is_settled or job.outcome_source != "direct_response":
        return
    if executing_job is not None:
        if executing_job is not job or coordinator.active_job_id != job.job_id:
            return
        job.presentation_source = result
    elif source_result is not None and job.presentation_source is source_result:
        job.presentation_source = None  # Consume the originating call's authority.
    else:
        return
    job.retained_call = result.model_copy(deep=True)
    job.result = job.retained_call.structuredContent


async def run_logical_job(tool, params, body, *, digest=None):
    """Reserve exactly once, never enter a duplicate body, retain honest outcomes."""
    from illustrator_mcp.proxy_client import mark_reserved_job, clear_reserved_job
    coordinator = get_coordinator()
    caller_id = getattr(params, "job_id", None)
    digest = digest or intent_digest(tool, params)
    from illustrator_mcp.execution import document_intent
    intent_token = document_intent.begin(tool, params)
    try:
        async with coordinator.reserve(job_id=caller_id, digest=digest, label=tool) as job:
            job.host_request_active = False
            document_intent.active.get()["job"] = job
            job.source_snapshot = getattr(params, "_job_source", None)
            token = mark_reserved_job()
            from illustrator_mcp.execution import host_phases
            phase_token = host_phases.begin(job) if tool != "illustrator_execute_task" else None
            try:
                raw = await body(job)
                result = finalize_tool_result(raw, tool=tool)
                canonical = CanonicalResult.model_validate(result.structuredContent)
                canonical.job_id = job.job_id
                document_intent.annotate(canonical)
                if tool == "illustrator_execute_task" and (getattr(params, "compute_fn", None) is not None or getattr(params, "apply_fn", None) is not None):
                    canonical.warnings.append("Callback pipelines are deprecated but remain supported. Use batch.operations for SOC work or execute_script with explicit includes for arbitrary JSX; raw host-phase evidence cannot prove later Python phases completed.")
                if (job.status is JobStatus.UNKNOWN or
                        canonical.diagnostics.get("jobOutcomeUnknown")):
                    canonical.execution = ExecutionStatus.UNKNOWN
                    object.__setattr__(canonical, "ok", False)
                if canonical.execution == "unknown":
                    if job.status is not JobStatus.UNKNOWN:
                        coordinator.mark_unknown(job.job_id, "Logical job outcome is unknown; reconcile before retrying.")
                    canonical.effects.complete = False
                # Incrementally recorded effects survive an error in a later phase.
                # A registered handler reduces its journal after this adapter.
                # Do not feed already reduced facts back as the adapter's base:
                # a later callback must be able to replace those facts. Recovered
                # host effects, however, predate the new process's journal.
                if job.journal is None or job.outcome_source == "host_phase_finalizer":
                    for kind in ("created", "modified", "deleted"):
                        values = getattr(canonical.effects, kind)
                        setattr(canonical.effects, kind, list(dict.fromkeys(values + job.effects[kind])))
                result = build_call_result(canonical, list(result.content[2:]))
                if canonical.execution != "unknown":
                    coordinator.complete(job.job_id,
                        JobStatus.SUCCEEDED if canonical.execution == "succeeded" else JobStatus.FAILED,
                        result=result.structuredContent, effects=canonical.effects.model_dump(),
                        error=canonical.error.message if canonical.error else None,
                        source="direct_response")
                    retain_presented_result(result, executing_job=job)
                else:
                    coordinator.record_effects(job.job_id,
                        **{kind: [v for v in getattr(canonical.effects, kind) if v not in job.effects[kind]]
                           for kind in ("created", "modified", "deleted")}, complete=False)
                return result
            finally:
                if phase_token is not None:
                    host_phases.active_phases.reset(phase_token)
                clear_reserved_job(token)
    except DuplicateJobError as exc:
        record = exc.record
        if record.retained_call is not None:
            result = record.retained_call.model_copy(deep=True)
            canonical = CanonicalResult.model_validate(result.structuredContent)
        elif isinstance(record.result, dict) and "schemaVersion" in record.result:
            result = None
            canonical = CanonicalResult.model_validate(record.result)
        else:
            result = None
            canonical = CanonicalResult(tool=tool, jobId=record.job_id,
                execution="unknown" if record.status is JobStatus.UNKNOWN else "failed",
                effects=Effects.model_validate(record.effects), data=record.result,
                error={"code": "E999", "message": record.error or "Retained job has no complete direct outcome."})
        canonical.diagnostics.update(deduplicated=True, replayed=False, outcomeSource=record.outcome_source)
        return build_call_result(canonical, list(result.content[2:]) if result else [])
    except HostUnresolvedError as exc:
        return build_call_result(CanonicalResult(tool=tool, jobId=exc.job_id, execution="unknown",
            error={"code": "R_TIMEOUT", "message": str(exc)}))
    except (JobConflictError, JobCancelledError) as exc:
        return build_call_result(CanonicalResult(tool=tool, jobId=caller_id, execution="failed",
            error={"code": "E999", "message": str(exc)}, diagnostics={"replayed": False}))
    finally:
        document_intent.active.reset(intent_token)
