"""Process-wide execution coordinator (T12).

Illustrator is a single shared application with one active document and one
selection. Two jobs interleaving their host calls corrupt each other's
assumptions, so *all* Illustrator-dependent work goes through one bounded
queue — raw scripts, structured batches and legacy tools alike.

Four problems this exists to solve:

**Interleaving.** A logical job can span several host calls (boolean extract →
Python compute → commit). Between them, another request could previously run
and change the active document. ``reserve()`` holds the slot across the whole
job.

**Timeout is not "nothing happened".** A Python timeout removed the pending
request but did nothing to the evaluation still running inside Illustrator. An
agent that retried could duplicate a mutation that completed late. Here the
*client's* wait deadline is separate from the job's lifetime: a timeout marks
the job ``UNKNOWN`` and quarantines host dispatch until the host reports back,
so a late result is discoverable rather than silently dropped.

**Replay.** Re-submitting the same ``job_id`` with the same request digest
returns the existing record instead of re-executing. A *different* digest under
the same id is a conflict and is refused.

**Stale callbacks.** Each connection gets a generation number. A callback that
arrives from a previous connection cannot resolve or unlock a job belonging to
the current one.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: How long a finished job's record is kept for reconciliation and dedup.
DEFAULT_RETENTION_SECONDS = 900.0

#: Maximum number of finished records kept, whatever their age.
DEFAULT_MAX_RECORDS = 500

#: Maximum jobs allowed to wait for the slot before submission is refused.
DEFAULT_MAX_QUEUE_DEPTH = 32


class JobStatus(str, Enum):
    """Lifecycle of a logical job."""

    QUEUED = "queued"
    """Accepted, waiting for the slot. Nothing has run; safe to cancel."""

    RUNNING = "running"
    """Holding the slot. Cancellation cannot undo what it has already done."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"

    UNKNOWN = "unknown"
    """The client stopped waiting, or evidence was lost, while the host may
    still have been working. **Not** a synonym for "nothing happened" — the
    job must be reconciled, never blindly retried."""

    CANCELLED = "cancelled"
    """Cancelled before it ever started. Nothing ran."""

    @property
    def is_terminal(self) -> bool:
        return self in (
            JobStatus.SUCCEEDED, JobStatus.FAILED,
            JobStatus.UNKNOWN, JobStatus.CANCELLED,
        )

    @property
    def is_settled(self) -> bool:
        """Whether the outcome is actually known."""
        return self in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


class JobConflictError(Exception):
    """A job id was reused with a different request digest."""


class HostUnresolvedError(RuntimeError):
    """No host call is safe until a dispatched request is reconciled."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__(f"Illustrator job {job_id} is unresolved; inspect job status, do not retry.")


class DuplicateJobError(Exception):
    """This job has already run; its retained record is on the exception.

    Raised rather than returned because an ``async with`` body *always*
    executes once the context manager yields — there is no way to "skip" it.
    Signalling by exception is the only way ``reserve()`` can guarantee the
    work is not repeated, and it forces the caller to decide explicitly what
    to return for a duplicate submission.
    """

    def __init__(self, record: "JobRecord") -> None:
        self.record = record
        super().__init__(
            f"Job {record.job_id!r} already completed with status "
            f"{record.status.value}; returning the retained record instead of "
            f"re-executing."
        )


class JobCancelledError(Exception):
    """The job was cancelled before it started; its body never ran."""

    def __init__(self, record: "JobRecord") -> None:
        self.record = record
        super().__init__(
            f"Job {record.job_id!r} was cancelled before execution started. "
            f"Nothing ran."
        )


def request_digest(payload: Any) -> str:
    """Stable digest of a request, for duplicate detection."""
    try:
        blob = json.dumps(payload, sort_keys=True, default=str)
    except (TypeError, ValueError):
        blob = repr(payload)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass
class JobRecord:
    """What is known about one logical job.

    Retained after completion so a client that timed out can still find out
    what happened, rather than assuming it did not happen.
    """

    job_id: str
    digest: str
    status: JobStatus = JobStatus.QUEUED
    label: str = ""
    connection_generation: int = 0
    created_at: float = field(default_factory=time.monotonic)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Any = None
    error: Optional[str] = None
    host_session_epoch: Optional[str] = None
    outcome_source: str = "python"
    #: Known effects. ``complete`` stays False unless the job can prove
    #: otherwise — a raw script never can.
    effects: Dict[str, Any] = field(
        default_factory=lambda: {"created": [], "modified": [], "deleted": [],
                                 "complete": False}
    )
    #: Set when the waiter gave up but the host may still be running.
    awaiting_host: bool = False
    export_files: Any = None
    trusted_probe: bool = False
    probe_retired: bool = False
    document_target: Optional[str] = None
    input_digest: Optional[str] = None
    host_request_active: Optional[bool] = None
    active_request_token: Optional[str] = None
    active_request_generation: Optional[int] = None
    retained_call: Any = field(default=None, repr=False)
    presentation_source: Any = field(default=None, repr=False)
    source_snapshot: Any = field(default=None, repr=False)
    journal: Any = None  # Process-local, bounded plain facts; same retention as this job.
    _journal_effects_base: Optional[Dict[str, Any]] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "jobId": self.job_id,
            "digest": self.digest,
            "documentTarget": self.document_target,
            "requestToken": self.active_request_token,
            "requestConnectionGeneration": self.active_request_generation,
            "status": self.status.value,
            "label": self.label,
            "connectionGeneration": self.connection_generation,
            "awaitingHost": self.awaiting_host,
            "trustedProbe": self.trusted_probe,
            "probeRetired": self.probe_retired,
            "effects": self.effects,
            "error": self.error,
            "hostSessionEpoch": self.host_session_epoch,
            "outcomeSource": self.outcome_source,
            "durationMs": (
                int((self.finished_at - self.started_at) * 1000)
                if self.started_at and self.finished_at else None
            ),
        }
        if self.result is not None:
            data["result"] = self.result
        if self.export_files is not None:
            data["exportFiles"] = self.export_files.snapshot()
            if self.export_files.retained:
                data["nextStep"] = {"tool": "illustrator_job_status", "params": {
                    "jobId": self.job_id, "finalize_export": True}}
        if self.journal is not None:
            data["journal"] = self.journal.snapshot()
        return data


class ExecutionCoordinator:
    """Serialises all Illustrator-dependent work in this process."""

    def __init__(
        self,
        retention_seconds: float = DEFAULT_RETENTION_SECONDS,
        max_records: int = DEFAULT_MAX_RECORDS,
        max_queue_depth: int = DEFAULT_MAX_QUEUE_DEPTH,
    ) -> None:
        self.retention_seconds = retention_seconds
        self.max_records = max_records
        self.max_queue_depth = max_queue_depth

        self._records: Dict[str, JobRecord] = {}
        self._order: List[str] = []
        self._lock = threading.Lock()

        # asyncio primitives are created lazily so the coordinator can be
        # constructed outside a running loop.
        self._slot: Optional[asyncio.Semaphore] = None
        self._slot_loop: Optional[asyncio.AbstractEventLoop] = None
        self._waiting = 0
        self._active_job: Optional[str] = None
        self._connection_generation = 0
        self.probe_fence = None
        self.probe_readiness = None

    # ── connection generations ─────────────────────────────────────

    @property
    def connection_generation(self) -> int:
        with self._lock:
            return self._connection_generation

    def bump_connection_generation(self) -> int:
        """Called when the panel (re)connects.

        Anything still running from the previous connection becomes
        unverifiable: its callbacks must not resolve current jobs.
        """
        with self._lock:
            self._connection_generation += 1
            if self.probe_readiness is not None:
                self.probe_fence = dict(self.probe_readiness)
                self.probe_readiness = None
            generation = self._connection_generation
            stranded = [
                r for r in self._records.values()
                if r.status is JobStatus.RUNNING
                and r.host_request_active is not False
                and r.connection_generation != generation
            ]
        for record in stranded:
            self.mark_unknown(
                record.job_id, (
                    "The CEP panel reconnected while this job was running. "
                    "Whether Illustrator completed it is unknown — reconcile "
                    "before retrying."
                ),
            )
        if stranded:
            logger.warning(
                "Connection generation %d: %d running job(s) became UNKNOWN",
                generation, len(stranded),
            )
        return generation

    def is_current_generation(self, generation: int) -> bool:
        """Whether a callback from *generation* may still act on state."""
        with self._lock:
            return generation == self._connection_generation

    # ── records ────────────────────────────────────────────────────

    def _prune(self) -> None:
        """Drop expired records. Caller holds the lock."""
        now = time.monotonic()
        keep: List[str] = []
        for job_id in self._order:
            record = self._records.get(job_id)
            if record is None:
                continue
            expired = (
                record.status.is_terminal
                and not record.awaiting_host
                and not (self.probe_fence and self.probe_fence["jobId"] == record.job_id)
                and not (record.export_files and record.export_files.retained)
                and record.finished_at is not None
                and (now - record.finished_at) > self.retention_seconds
            )
            if expired:
                self._records.pop(job_id, None)
            else:
                keep.append(job_id)

        # Bound by count as well as age, oldest terminal records first.
        while len(keep) > self.max_records:
            for index, job_id in enumerate(keep):
                if (self._records[job_id].status.is_terminal
                        and not (self.probe_fence and self.probe_fence["jobId"] == job_id)
                        and not (self._records[job_id].export_files and self._records[job_id].export_files.retained)
                        and not self._records[job_id].awaiting_host):
                    self._records.pop(job_id, None)
                    keep.pop(index)
                    break
            else:
                break
        self._order = keep

    def get(self, job_id: str) -> Optional[JobRecord]:
        """Look up a job. Readable while the host is busy."""
        with self._lock:
            self._prune()
            return self._records.get(job_id)

    def status_of(self, job_id: str) -> Dict[str, Any]:
        """Status for a job id, including ones we no longer know about."""
        record = self.get(job_id)
        if record is not None:
            return record.to_dict()
        return {
            "jobId": job_id,
            "status": JobStatus.UNKNOWN.value,
            "detail": (
                "No record for this job id. It may never have been submitted, "
                "or its record may have expired. Its effect on the document "
                "is unknown; inspect the document rather than retrying."
            ),
        }

    def register(
        self,
        job_id: Optional[str],
        digest: str,
        label: str = "",
    ) -> JobRecord:
        """Create a job record, or return the existing one for a repeat.

        Raises:
            JobConflictError: same id, different digest.
        """
        job_id = job_id or f"job_{uuid.uuid4().hex[:12]}"
        with self._lock:
            self._prune()
            existing = self._records.get(job_id)
            if existing is not None:
                if existing.digest != digest and existing.input_digest != digest:
                    raise JobConflictError(
                        f"Job id {job_id!r} was already used for a different "
                        f"request (digest {existing.digest} vs {digest}). "
                        f"Use a new job id."
                    )
                return existing

            record = JobRecord(
                job_id=job_id, digest=digest, label=label,
                connection_generation=self._connection_generation,
            )
            self._records[job_id] = record
            self._order.append(job_id)
            return record

    def _settle(
        self,
        job_id: str,
        status: JobStatus,
        result: Any = None,
        error: Optional[str] = None,
    ) -> Optional[JobRecord]:
        with self._lock:
            record = self._records.get(job_id)
            if record is None or record.status.is_terminal:
                return record
            record.status = status
            record.finished_at = time.monotonic()
            if result is not None:
                record.result = result
            if error is not None:
                record.error = error
            record.awaiting_host = False
            return record

    def record_effects(
        self,
        job_id: str,
        created: Optional[List[str]] = None,
        modified: Optional[List[str]] = None,
        deleted: Optional[List[str]] = None,
        complete: Optional[bool] = None,
    ) -> None:
        """Record what a job is known to have changed, as it happens.

        Recorded incrementally so a job that fails part-way still reports the
        effects it had already produced.
        """
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return
            for key, values in (
                ("created", created), ("modified", modified), ("deleted", deleted)
            ):
                if values:
                    record.effects[key].extend(values)
            if complete is not None:
                record.effects["complete"] = complete

    def complete(
        self,
        job_id: str,
        status: JobStatus,
        *,
        result: Any = None,
        error: Optional[str] = None,
        effects: Optional[Dict[str, Any]] = None,
        host_session_epoch: Optional[str] = None,
        source: str = "python",
    ) -> Optional[JobRecord]:
        """Store a known outcome, including one recovered from the host.

        A retained host completion may refine a local ``UNKNOWN`` record after
        the original waiter lost its response. It may never overwrite a
        cancelled job, because cancellation establishes that its body did not
        run, or a different already-settled outcome.
        """
        if status not in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.UNKNOWN):
            raise ValueError(f"Unsupported completion status: {status}")
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return None
            # A tool's error envelope is not evidence that evalScript stopped.
            if record.status is JobStatus.UNKNOWN and source in ("python", "direct_response"):
                return record
            if record.status is JobStatus.CANCELLED:
                return record
            if record.status.is_settled and record.status is not status:
                return record
            record.status = status
            record.finished_at = time.monotonic()
            record.result = result
            record.error = error
            record.awaiting_host = status is JobStatus.UNKNOWN
            record.host_session_epoch = host_session_epoch
            record.outcome_source = source
            if effects is not None:
                record.effects = {
                    "created": list(effects.get("created") or []),
                    "modified": list(effects.get("modified") or []),
                    "deleted": list(effects.get("deleted") or []),
                    "complete": bool(effects.get("complete", False)),
                }
            return record

    def record_journal_report(self, journal, effects: Optional[Dict[str, Any]] = None) -> None:
        """Refresh retained effects from current facts and the original adapter.

        Both final presentation and late completion use the same reducer. The
        coordinator lock prevents an older presentation snapshot overwriting
        a newer callback's effects. No execution status is inferred here.
        """
        from illustrator_mcp.execution.journal import reduce_journal
        from illustrator_mcp.results import CanonicalResult, Effects
        with self._lock:
            snapshot = journal.snapshot()
            for record in self._records.values():
                if record.journal is journal:
                    if effects is not None:
                        record._journal_effects_base = Effects.model_validate(effects).model_dump()
                    base = CanonicalResult(tool=journal.tool or "host_request", execution="unknown",
                        effects=Effects.model_validate(record._journal_effects_base or {}))
                    record.effects = reduce_journal(snapshot, base).effects.model_dump()

    def mark_unknown(self, job_id: str, detail: str) -> Optional[JobRecord]:
        """Mark a dispatched job unresolved and retain it for reconciliation."""
        with self._lock:
            record = self._records.get(job_id)
            if record is not None and record.probe_retired:
                return record
            if record is not None and record.outcome_source == "late_host_callback":
                return record  # A late callback raced the caller's error handling.
        return self.complete(
            job_id,
            JobStatus.UNKNOWN,
            error=detail,
            source="python_timeout",
        )

    def retire_probe(self, job_id, request_id, token, generation):
        with self._lock:
            record = self._records.get(job_id)
            if record is None or not record.trusted_probe:
                raise ValueError("Only internal trusted probes may be retired")
            record.status = JobStatus.UNKNOWN
            record.awaiting_host = False
            record.probe_retired = True
            record.finished_at = time.monotonic()
            record.error = "Trusted probe wait retired; host completion remains unknown."
            record.effects = {"created": [], "modified": [], "deleted": [], "complete": True}
            if self.probe_fence is None or self.probe_fence.get("priorCompletionObserved"):
                self.probe_fence = {"jobId": job_id, "requestId": request_id,
                    "requestToken": token, "connectionGeneration": generation,
                    "trustedProbe": True, "retiredAt": record.finished_at,
                    "priorCompletionObserved": False}

    def assert_host_available(self) -> None:
        with self._lock:
            unresolved = next((r.job_id for r in self._records.values() if r.awaiting_host), None)
        if unresolved:
            raise HostUnresolvedError(unresolved)

    def host_request_started(self, job_id: str, generation: int, token: str) -> None:
        """Bind completion authority to this dispatch, not job admission."""
        with self._lock:
            record = self._records[job_id]
            record.host_request_active = True
            record.active_request_token = token
            record.active_request_generation = generation

    def matches_host_request(self, job_id: str, generation: int, token: str) -> bool:
        with self._lock:
            record = self._records.get(job_id)
            return bool(record and record.active_request_generation == generation
                        and record.active_request_token == token)

    def host_request_finished(self, job_id: str, generation: int, result: Any,
                              *, request_token: str) -> bool:
        """Retain a late step result without claiming an entire multi-step job ran.

        A phase may dispatch after a reconnect within the same logical job.
        Match its retained dispatch generation AND token, even if another
        reconnect has since happened. Never authorize a different phase.
        """
        with self._lock:
            record = self._records.get(job_id)
            if (record is None or record.active_request_generation != generation
                    or record.active_request_token != request_token):
                return False
            record.host_request_active = False
            if record.status is JobStatus.UNKNOWN:
                record.awaiting_host = False
                record.finished_at = time.monotonic()
                record.result = {"hostRequestResult": result}
                record.outcome_source = "late_host_callback"
                record.error = "Host request completed; remaining logical job steps were not replayed."
            return True

    def register_host_request(self, token: str) -> JobRecord:
        """Give direct bridge calls a queryable identity as well."""
        record = self.register(f"host_{token}", token, label="direct_host_request")
        with self._lock:
            record.status = JobStatus.RUNNING
            record.started_at = time.monotonic()
        return record

    def mirror_host_record(self, host_record: Dict[str, Any]) -> JobRecord:
        """Merge a retained host completion into the Python ledger.

        Digest conflicts are refused even during reconciliation. A host record
        from a different runtime epoch is still useful evidence when its own
        record says it completed; the epoch is preserved so the caller can see
        where that evidence came from.
        """
        job_id = str(host_record.get("jobId") or "")
        digest = str(host_record.get("digest") or "")
        if not job_id:
            raise ValueError("Host record has no jobId")
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                record = JobRecord(job_id=job_id, digest=digest, label="reconciled")
                self._records[job_id] = record
                self._order.append(job_id)
            elif record.digest and digest and record.digest != digest:
                raise JobConflictError(
                    f"Host record for {job_id!r} has digest {digest}, but the "
                    f"Python record has {record.digest}. Refusing to merge them."
                )

        completed = host_record.get("completed") is True
        host_status = host_record.get("status")
        if completed and host_status == "succeeded":
            status = JobStatus.SUCCEEDED
        elif completed and host_status in ("failed", "partial"):
            status = JobStatus.FAILED
        else:
            status = JobStatus.UNKNOWN

        errors = host_record.get("errors") or []
        error = None
        if errors:
            first = errors[0]
            error = str(first.get("message", first)) if isinstance(first, dict) else str(first)
        if status is JobStatus.UNKNOWN and error is None:
            error = "The host record has no completed finalizer; outcome remains unknown."

        phase_finalized = (not completed and host_status == "unknown" and
            (host_record.get("context") or {}).get("lastPhase", {}).get("finalized") is True)
        if phase_finalized:
            error = "Host phase finalized; remaining logical job steps were not replayed."
        merged = self.complete(
            job_id,
            status,
            result=host_record.get("result"),
            error=error,
            effects=host_record.get("effects") or {},
            host_session_epoch=host_record.get("sessionEpoch"),
            source="host_phase_finalizer" if phase_finalized else "host_ledger",
        )
        if phase_finalized and merged is not None and merged.status is JobStatus.UNKNOWN:
            # A finalizer proves eval ended, not that the logical job succeeded.
            with self._lock:
                merged.awaiting_host = False
        assert merged is not None
        return merged

    # ── cancellation ───────────────────────────────────────────────

    def cancel(self, job_id: str) -> Dict[str, Any]:
        """Cancel a job that has not started.

        A RUNNING job is **not** cancelled: this process cannot preempt an
        ``evalScript`` already executing inside Illustrator, and pretending
        otherwise would imply mutations were undone.
        """
        with self._lock:
            record = self._records.get(job_id)
            if record is None:
                return {"ok": False, "status": "unknown_job", "jobId": job_id}
            status = record.status

        if status is JobStatus.QUEUED:
            self._settle(job_id, JobStatus.CANCELLED,
                         error="Cancelled before execution started")
            return {"ok": True, "status": JobStatus.CANCELLED.value,
                    "jobId": job_id, "detail": "Nothing ran."}

        if status is JobStatus.RUNNING:
            return {
                "ok": False,
                "status": JobStatus.RUNNING.value,
                "jobId": job_id,
                "detail": (
                    "Already running in Illustrator and cannot be preempted. "
                    "Any mutations it has made stand; cancelling would not "
                    "undo them."
                ),
            }

        return {"ok": False, "status": status.value, "jobId": job_id,
                "detail": "Already finished."}

    # ── the slot ───────────────────────────────────────────────────

    def _get_slot(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._slot is None or self._slot_loop is not loop:
                self._slot = asyncio.Semaphore(1)
                self._slot_loop = loop
            return self._slot

    @property
    def active_job_id(self) -> Optional[str]:
        with self._lock:
            return self._active_job

    @property
    def queue_depth(self) -> int:
        with self._lock:
            return self._waiting

    @asynccontextmanager
    async def reserve(
        self,
        job_id: Optional[str] = None,
        digest: Optional[str] = None,
        label: str = "",
        wait_timeout: Optional[float] = None,
    ):
        """Hold the execution slot for one whole logical job.

        Everything inside the ``async with`` body — however many host calls it
        makes — runs without another job interleaving.

        Yields the :class:`JobRecord`, so the body can record effects as it
        goes.

        Raises:
            DuplicateJobError: this job already ran. Its retained record is on
                the exception; the body is NOT executed.
            JobCancelledError: cancelled while queued. The body is NOT executed.
            JobConflictError: the id was reused with a different digest.
        """
        digest = digest or request_digest({"label": label, "job": job_id})
        record = self.register(job_id, digest, label=label)

        # A repeat submission of a settled job must not reapply the work.
        # Raising is the only way to skip an `async with` body.
        if record.status.is_terminal:
            logger.info(
                "Job %s already %s — not re-executing",
                record.job_id, record.status.value,
            )
            raise DuplicateJobError(record)

        try:
            self.assert_host_available()
        except HostUnresolvedError:
            self._settle(record.job_id, JobStatus.CANCELLED, error="Host unresolved; nothing dispatched")
            raise

        slot = self._get_slot()

        with self._lock:
            if self._waiting >= self.max_queue_depth:
                raise RuntimeError(
                    f"Execution queue is full ({self._waiting} waiting). "
                    f"Retry once current work completes."
                )
            self._waiting += 1

        try:
            from illustrator_mcp.execution.progress import milestone
            await milestone(f"queued: {label} ({record.job_id}); duration unknown")
            if wait_timeout is not None:
                await asyncio.wait_for(slot.acquire(), timeout=wait_timeout)
            else:
                await slot.acquire()
        except (asyncio.TimeoutError, asyncio.CancelledError):
            with self._lock:
                self._waiting -= 1
            self._settle(
                record.job_id, JobStatus.CANCELLED,
                error=f"Timed out after {wait_timeout}s waiting for the "
                      f"execution slot; the job never started.",
            )
            raise
        else:
            with self._lock:
                self._waiting -= 1

        # Cancelled while queued — release the slot and do NOT run the body.
        if record.status is JobStatus.CANCELLED:
            slot.release()
            raise JobCancelledError(record)
        # A duplicate may have queued while the original was RUNNING. Recheck
        # after acquisition; it must not replay even if completion arrived late.
        if record.status.is_terminal:
            slot.release()
            raise DuplicateJobError(record)

        try:
            self.assert_host_available()
        except HostUnresolvedError:
            self._settle(record.job_id, JobStatus.CANCELLED, error="Host unresolved; nothing dispatched")
            slot.release()
            raise

        with self._lock:
            record.status = JobStatus.RUNNING
            record.started_at = time.monotonic()
            record.connection_generation = self._connection_generation
            self._active_job = record.job_id

        try:
            await milestone(f"started: {label} ({record.job_id}); duration unknown")
            yield record
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            # The waiter gave up. The host may still be working, so the
            # outcome is UNKNOWN — never "did not happen".
            self.mark_unknown(
                record.job_id,
                f"The client stopped waiting ({exc}). Illustrator may still "
                f"be executing this job. Its effect is unknown — reconcile "
                f"before retrying.",
            )
            raise
        except Exception as exc:
            self._settle(record.job_id, JobStatus.FAILED, error=str(exc))
            raise
        else:
            if not record.status.is_terminal:
                self._settle(record.job_id, JobStatus.SUCCEEDED)
        finally:
            with self._lock:
                if self._active_job == record.job_id:
                    self._active_job = None
            slot.release()

    # ── introspection ──────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            self._prune()
            records = [r.to_dict() for r in self._records.values()]
            return {
                "activeJob": self._active_job,
                "waiting": self._waiting,
                "connectionGeneration": self._connection_generation,
                "records": records,
            }

    def reset(self) -> None:
        """Drop all state. For tests and shutdown."""
        with self._lock:
            self._records.clear()
            self._order.clear()
            self._slot = None
            self._slot_loop = None
            self._waiting = 0
            self._active_job = None
            self.probe_fence = None
            self.probe_readiness = None


_coordinator: Optional[ExecutionCoordinator] = None
_coordinator_lock = threading.Lock()


def get_coordinator() -> ExecutionCoordinator:
    """The process-wide coordinator.

    Owned by ``RuntimeContext``; this accessor exists so call sites do not
    need a runtime reference just to reach it.
    """
    global _coordinator
    with _coordinator_lock:
        if _coordinator is None:
            _coordinator = ExecutionCoordinator()
        return _coordinator
