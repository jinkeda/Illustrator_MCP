"""Bounded, process-local operation facts and deterministic reporting (OR11).

The execution coordinator owns retention. Facts contain plain JSON only; native
DOM handles never cross an execution boundary. Legacy reporting is an explicit
compatibility fact, not a second implementation of the recovery/effects rules.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
import functools
import json
import threading
from typing import Any
from uuid import uuid4

MAX_HOST_CALLS = 128
MAX_JOURNAL_BYTES = 256 * 1024
active_journal: ContextVar["OperationJournal | None"] = ContextVar("operation_journal", default=None)

# Values are reporting semantics; the real-producer contract test checks every
# state assigned by ownership.jsx against these keys.
OWNERSHIP_OUTCOMES = {
    "owned": "unfinished", "removal_failed": "unfinished",
    "committed": "retained", "released": "retained",
    "absorbed": "container", "removed": "removed", "disposed": "removed",
}


def _sequence(value):
    return type(value) is int and value > 0


def _copy(value):
    # No default=str: a native handle must fail instead of becoming a trusted
    # identity by stringification. JSON also severs mutable caller references.
    return json.loads(json.dumps(value, allow_nan=False))


def _key(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _ownership_records(raw):
    """Validate fields before they can alter effects; retain valid siblings.

    The journal keeps the original JSON for audit. Replay uses this sanitized
    view, so an invalid ID is neither coerced into an identity nor allowed to
    erase a successfully completed host call with a model validation error.
    """
    if not isinstance(raw, list):
        return [], True
    records, malformed = [], False
    for allocation in raw:
        if not isinstance(allocation, dict):
            malformed = True
            continue
        record = dict(allocation)
        identity = record.get("mcpId")
        if identity is not None and (not isinstance(identity, str) or not identity.strip()):
            record["mcpId"] = None
            malformed = True
        outcome = record.get("outcome")
        if not isinstance(outcome, str) or outcome not in OWNERSHIP_OUTCOMES:
            record["outcome"] = None
            malformed = True
        transfer = record.get("transferredTo")
        if transfer is not None and (not isinstance(transfer, str) or not transfer.strip()):
            record["transferredTo"] = None
            malformed = True
        for field_name in ("allocationSequence", "removalSequence"):
            if field_name in record and not _sequence(record[field_name]):
                record.pop(field_name)
                malformed = True
        records.append(record)
    return records, malformed


def _effect_steps(raw):
    """Retain ordered identities, never arbitrary per-operation data."""
    from illustrator_mcp.results import _declared_effects
    if raw is None:
        return [], False
    if not isinstance(raw, list):
        return [], True
    steps, malformed = [], False
    for value in raw:
        if not isinstance(value, dict):
            malformed = True
            continue
        effects = _declared_effects({"diagnostics":{"effects":value}})
        step = effects.model_dump()
        if "eventSequence" in value:
            if _sequence(value["eventSequence"]):
                step["eventSequence"] = value["eventSequence"]
            else:
                malformed = True
        steps.append(step)
    return steps, malformed


def _call_events(record, ownership):
    """Merge allocation lifetimes with mutation observations in this call.

    A retained allocation contributes at birth, even if an ancestor commits
    after its deletion. Removal events carry allocation identity, so an older
    scope cannot erase a new object that reused its MCP ID.
    """
    steps, malformed = _effect_steps(record.get("effectSteps"))
    summary = record.get("effects") or {}
    if not steps:
        steps = [summary] if any(summary.get(field) for field in ("created", "modified", "deleted")) else []
    else:
        # Preserve independent summary evidence when operation detail is partial.
        residual = {field:[identity for identity in summary.get(field, [])
                           if not any(identity in step.get(field, []) for step in steps)]
                    for field in ("created", "modified", "deleted")}
        if any(residual.values()):
            steps.append(dict(residual, complete=False))
            malformed = True
    events = []
    timed = bool(steps) and all(_sequence(step.get("eventSequence")) for step in steps)
    clocks = [step["eventSequence"] for step in steps if _sequence(step.get("eventSequence"))]
    if clocks and (not timed or clocks != sorted(set(clocks))):
        malformed = True
    for index, step in enumerate(steps):
        order = step["eventSequence"] if timed else index + 1
        events.append((order, "effects", step))
    mutations = {identity for step in steps for field in ("created", "deleted")
                 for identity in step.get(field, [])}
    # Legacy snapshots have no event clock. Allocation suffixes still identify
    # successive births; never let an earlier allocation's cleanup win over a
    # later allocation solely because the parent scope was serialized first.
    latest = {}
    for allocation in ownership:
        alloc_id = allocation.get("allocId")
        if isinstance(alloc_id, str) and alloc_id.startswith("alloc_") and alloc_id[6:].isdigit():
            identity = allocation.get("mcpId")
            latest[identity] = max(latest.get(identity, 0), int(alloc_id[6:]))
    for allocation in ownership:
        if allocation.get("transferredTo"):
            continue
        action = OWNERSHIP_OUTCOMES.get(allocation.get("outcome"))
        if action not in {"retained", "unfinished", "removed"}:
            continue  # Absorbed children are accounted for by their container.
        identity = allocation.get("mcpId")
        if not identity:
            continue
        birth = allocation.get("allocationSequence")
        removal = allocation.get("removalSequence")
        if _sequence(birth) and (timed or not steps):
            events.append((birth, "allocation", allocation))
            if action == "removed":
                if _sequence(removal):
                    events.append((removal, "removal", allocation))
                else:
                    malformed = True
        else:
            # A legacy commit is a fallback only. Explicit mutation observations
            # carry chronology that the scope's disposition cannot supersede.
            if identity not in mutations and action != "removed":
                events.append((0, "allocation", allocation))
            if action == "removed":
                alloc_id = allocation.get("allocId")
                if isinstance(alloc_id, str) and alloc_id.startswith("alloc_") and alloc_id[6:].isdigit():
                    if int(alloc_id[6:]) < latest.get(identity, 0):
                        continue
                events.append(((max(clocks) if timed else len(steps)) + 1, "removal", allocation))
    return sorted(events, key=lambda event:event[0]), malformed


@dataclass
class OperationJournal:
    operation_id: str = field(default_factory=lambda: "op_" + uuid4().hex)
    tool: str = ""
    records: list[dict] = field(default_factory=list)
    incomplete: bool = False
    _bytes: int = 0
    _lock: Any = field(default_factory=threading.RLock, repr=False)

    def record_host(self, response: dict, *, command: str, read_only: bool = False):
        try:
            self._record_host(response, command=command, read_only=read_only)
        except (TypeError, ValueError, AttributeError, KeyError):
            # Reporting cannot erase a completed host call when a legacy peer
            # supplies malformed facts. Keep the operation explicitly partial.
            self.incomplete = True

    def _record_host(self, response: dict, *, command: str, read_only: bool = False):
        from illustrator_mcp.proxy_client import build_envelope_dict
        from illustrator_mcp.results import _executor_result_overrides, _batch_report_from_envelope
        envelope = build_envelope_dict(response, context=command)
        overrides = _executor_result_overrides(envelope)
        batch = _batch_report_from_envelope(envelope) or {}
        raw_steps = batch.get("effectSteps")
        if raw_steps is None and isinstance(batch.get("ops"), list):
            raw_steps = [op["effects"] for op in batch["ops"]
                         if isinstance(op, dict) and isinstance(op.get("effects"), dict)]
        steps, malformed_steps = _effect_steps(raw_steps)
        if malformed_steps:
            self.incomplete = True
        raw = response.get("result")
        if isinstance(raw, str):
            try: raw = json.loads(raw)
            except ValueError: raw = {}
        raw = raw if isinstance(raw, dict) else {}
        host_facts = raw.get("hostFacts", {})
        ownership = host_facts.get("ownership", []) if isinstance(host_facts, dict) else host_facts
        descriptor = (response.get("integrity") or {}).get("descriptor") or {}
        fact = {"kind":"host", "operationId":self.operation_id,
                "hostCall":response.get("requestToken") or response.get("trace_id") or "local_" + uuid4().hex,
                "jobId":response.get("jobId"), "command":command, "readOnly":read_only,
                "documentId":descriptor.get("documentId"), "hostSession":descriptor.get("hostSession"),
                "execution":response.get("execution"),
                "integrity":response.get("integrity") or {"status":"unknown", "reason":"legacy_peer"},
                "truncation":envelope["diagnostics"].get("truncation") or [],
                "ownership":ownership,
                "effects":overrides["effects"].model_dump() if "effects" in overrides else None,
                "effectSteps":steps,
                "recovery":overrides["recovery"].model_dump(mode="json") if "recovery" in overrides else None}
        self.append(fact)

    def append(self, fact: dict):
        with self._lock:
            try:
                frozen = _copy(fact)
                if not isinstance(frozen, dict) or not isinstance(frozen.get("hostCall"), str):
                    raise ValueError("host fact requires a call identity")
                encoded = _key(frozen)
            except (TypeError, ValueError):
                self.incomplete = True
                return
            if _ownership_records(frozen.get("ownership", []))[1]:
                self.incomplete = True
            existing = next((r for r in self.records if r["hostCall"] == frozen["hostCall"]), None)
            if existing:
                compare = dict(existing)
                compare.pop("sequence", None)
                if compare != frozen:
                    # A timeout observation may be refined by the correlated
                    # eventual host completion. Conflicting completed facts are
                    # retained as uncertainty, never silently last-write wins.
                    if existing.get("execution") == "unknown" and frozen.get("execution") != "unknown":
                        previous_bytes = len(_key(compare).encode("utf-8"))
                        new_bytes = len(encoded.encode("utf-8"))
                        if self._bytes - previous_bytes + new_bytes > MAX_JOURNAL_BYTES:
                            self.incomplete = True
                            return
                        frozen["sequence"] = existing["sequence"]
                        self.records[self.records.index(existing)] = frozen
                        self._bytes += new_bytes - previous_bytes
                    else:
                        self.incomplete = True
                return
            if len(self.records) >= MAX_HOST_CALLS or self._bytes + len(encoded.encode("utf-8")) > MAX_JOURNAL_BYTES:
                self.incomplete = True
                return
            frozen["sequence"] = len(self.records)
            self._bytes += len(encoded.encode("utf-8"))
            self.records.append(frozen)

    def snapshot(self):
        with self._lock:
            return {"version":1, "operationId":self.operation_id, "tool":self.tool,
                    "incomplete":self.incomplete, "records":_copy(self.records)}


def reduce_journal(snapshot: dict, canonical):
    """Replay final facts without changing execution on recovery success.

    Existing canonical output supplies the tool's explicit compatibility
    account (including filesystem effects not observed by the host). Host facts
    add earlier effects/disclosures that multi-call tools previously dropped.
    Ownership snapshots remove only temporary creations whose final outcome is
    known; absence of an ownership record never means an object was removed.
    """
    from illustrator_mcp.results import Effects, ExecutionStatus, Truncation, RecoveryAttempt, reduce_recovery_attempts
    result = canonical.model_copy(deep=True)
    records = sorted(snapshot.get("records", []), key=lambda r:r["sequence"])
    created, modified, deleted = list(result.effects.created), list(result.effects.modified), list(result.effects.deleted)
    born = set(created)
    incomplete = snapshot.get("incomplete", True)
    complete = bool(result.effects.complete) and not incomplete
    notes, recoveries, integrities = [], [], []
    seen_calls = set()
    recovery_signatures = set()
    def raw_attempt(attempt):
        detail = attempt.get("detail")
        raw = dict(detail) if isinstance(detail, dict) else {"detail":detail}
        raw.update({k:v for k,v in attempt.items() if k != "detail" and v is not None})
        return raw
    def signature(raw):
        return _key({k:v for k,v in raw.items() if k not in {"source", "hostCall"}})
    for record in records:
        call = record["hostCall"]
        if call in seen_calls:
            continue
        seen_calls.add(call)
        integrity = record.get("integrity") or {"status":"unknown"}
        integrities.append({"hostCall":call, **integrity})
        if integrity.get("status") == "failed" or record.get("execution") == "unknown":
            complete = False
            result.execution = ExecutionStatus.UNKNOWN
        effects = record.get("effects")
        if effects:
            complete = complete and bool(effects.get("complete"))
        ownership, malformed = _ownership_records(record.get("ownership", []))
        events, malformed_events = _call_events(record, ownership)
        malformed = malformed or malformed_events
        if malformed:
            incomplete, complete = True, False
        for allocation in ownership:
            if allocation.get("transferredTo"):
                continue
            action = OWNERSHIP_OUTCOMES.get(allocation.get("outcome"))
            if action == "unfinished" or (action == "retained" and not allocation.get("mcpId")):
                complete = False
        active_allocations = {}
        for _, kind, event in events:
            if kind == "allocation":
                identity = event["mcpId"]
                active_allocations[identity] = event.get("allocId")
                born.add(identity)
                if identity not in created: created.append(identity)
                if identity in deleted: deleted.remove(identity)
            elif kind == "removal":
                identity = event["mcpId"]
                if identity in active_allocations and active_allocations[identity] != event.get("allocId"):
                    continue
                if identity in created: created.remove(identity)
                if identity in modified: modified.remove(identity)
                if identity in born and identity in deleted: deleted.remove(identity)
                active_allocations.pop(identity, None)
            else:
                complete = complete and bool(event.get("complete"))
                # A single unordered summary cannot prove which incarnation
                # survives when it contains the same ID on both sides.
                if set(event.get("created", [])) & set(event.get("deleted", [])):
                    complete = False
                for identity in event.get("created", []):
                    born.add(identity)
                    if identity not in created: created.append(identity)
                    if identity in deleted: deleted.remove(identity)
                for identity in event.get("modified", []):
                    if identity not in modified: modified.append(identity)
                for identity in event.get("deleted", []):
                    if identity in created: created.remove(identity)
                    if identity in modified: modified.remove(identity)
                    if identity in born:
                        if identity in deleted: deleted.remove(identity)
                    elif identity not in deleted: deleted.append(identity)
                    active_allocations.pop(identity, None)
        for note in record.get("truncation", []):
            note = dict(note, hostCall=call) if isinstance(note, dict) else {"detail":note, "hostCall":call}
            if note not in notes: notes.append(note)
        for attempt in (record.get("recovery") or {}).get("attempts", []):
            raw = raw_attempt(attempt)
            recovery_signatures.add(signature(raw))
            raw["hostCall"] = call
            if raw.get("scopeKey"): raw["scopeKey"] = call + "/" + str(raw["scopeKey"])
            if raw.get("recoveryId"): raw["recoveryId"] = call + "/" + str(raw["recoveryId"])
            recoveries.append(raw)
    for attempt in result.recovery.attempts:
        raw = raw_attempt(attempt.model_dump(mode="json"))
        if signature(raw) not in recovery_signatures:
            recoveries.append(raw)
    result.effects = Effects(created=created, modified=[i for i in modified if i not in deleted], deleted=deleted, complete=complete, coverageReason=result.effects.coverageReason)
    if recoveries:
        # Reuse the one canonical recovery reducer, including its final-scope
        # retry ordering. The final adapter's duplicate host summary is not
        # reduced as a second independent recovery attempt.
        result.recovery = reduce_recovery_attempts([RecoveryAttempt(
            status=raw["status"], scope=raw.get("scope"), requested=raw.get("requested"),
            detail={k:v for k,v in raw.items() if k not in {"status", "scope", "requested"}},
        ) for raw in recoveries]) or result.recovery
    for note in result.truncation.notes:
        # note_host_truncation already attaches a request token. Match copied
        # notes without erasing equal disclosures from different host calls.
        if not any(all(candidate.get(k) == v for k,v in note.items()) for candidate in notes):
            notes.append(note)
    if notes:
        result.truncation = Truncation(truncated=True, notes=notes, retrieval_hint="Inspect the retained job and narrow read-only retrieval; do not replay mutations.")
    statuses = [i.get("status", "unknown") for i in integrities]
    integrity_status = "failed" if "failed" in statuses else (
        "verified" if statuses and all(s == "verified" for s in statuses) and not incomplete else "unknown")
    result.diagnostics["operationJournal"] = {"version":1, "operationId":snapshot["operationId"],
                                               "hostCalls":len(records), "incomplete":incomplete}
    if records:
        result.diagnostics["integrity"] = {"status":integrity_status, "calls":integrities}
    object.__setattr__(result, "ok", result.execution is ExecutionStatus.SUCCEEDED)
    return result


def wrap_registered_tool(fn, name):
    if getattr(fn, "_operation_journal_wrapped", False):
        return fn
    @functools.wraps(fn)
    async def call(*args, **kwargs):
        from mcp.types import CallToolResult
        from illustrator_mcp.results import CanonicalResult, build_call_result
        if active_journal.get() is not None:
            return await fn(*args, **kwargs)
        journal = OperationJournal(tool=name)
        token = active_journal.set(journal)
        from illustrator_mcp.execution import progress
        progress_token = progress.begin()
        try:
            value = await fn(*args, **kwargs)
            if isinstance(value, CallToolResult) and value.structuredContent and "schemaVersion" in value.structuredContent:
                canonical = CanonicalResult.model_validate(value.structuredContent)
                params = kwargs.get("params") or (args[0] if args else None)
                if canonical.diagnostics.get("deduplicated"):
                    if getattr(params, "detail", None) == "summary":
                        from illustrator_mcp.results import summarize_result
                        value = summarize_result(value)
                    await progress.outcome(value)
                    return value  # Keep the original job facts and evidence.
                reduced = reduce_journal(journal.snapshot(), canonical)
                differences = [name for name in ("effects", "recovery", "truncation")
                               if getattr(canonical,name) != getattr(reduced,name)]
                reduced.diagnostics["operationJournal"]["adapterDifferences"] = differences
                from illustrator_mcp.execution import get_coordinator
                # Save the adapter account, not an already reduced result.
                # Late facts must replay from the same base without counting
                # earlier journal effects a second time.
                get_coordinator().record_journal_report(journal, canonical.effects.model_dump())
                result = build_call_result(reduced, list(value.content[2:]))
                from illustrator_mcp.execution.logical_job import retain_presented_result
                retain_presented_result(result, source_result=value)
                if getattr(params, "detail", None) == "summary":
                    from illustrator_mcp.results import summarize_result
                    result = summarize_result(result)
                await progress.outcome(result)
                return result
            await progress.outcome(value)
            return value
        finally:
            progress.active_progress.reset(progress_token)
            active_journal.reset(token)
    call._operation_journal_wrapped = True
    return call
