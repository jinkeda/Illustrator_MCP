"""Versioned host runtime bootstrap and handshake (T10).

Establishes *which* runtime the host is currently running before any work is
sent to it, so a version or hash mismatch fails before mutation rather than
halfway through a batch.

Design is grounded in the T08 live findings (Illustrator 30.7.0), not
assumption — see ``docs/HOST_PERSISTENCE_FINDINGS.md``:

* Top-level ``function``/``var`` declarations do **not** survive between
  ``evalScript`` calls, but anything on ``$.global`` does, including nested
  namespaces and callable functions. Persistent loading is therefore viable,
  with full re-injection as the proven fallback.
* ``$.global`` also survives the CEP panel reconnecting. **A reconnect is not
  a new runtime**, so the session epoch is generated host-side and rotates only
  on an actual (re)initialisation.

The Python side deliberately holds no authority over runtime identity: it asks
the host and believes the answer. The epoch it caches is only ever used to
notice that the host's epoch has *changed*.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from illustrator_mcp.schemas.contracts import TASK_PROTOCOL_VERSION

logger = logging.getLogger(__name__)

#: Library that must be injected for the handshake helpers to exist.
BOOTSTRAP_LIBRARY = "host_runtime"


class HandshakeStatus(str, Enum):
    """Outcome of reconciling the host runtime with what we expect."""

    READY = "ready"
    """Installed and matching. Safe to dispatch work."""

    INITIALIZED = "initialized"
    """Nothing was installed; we installed it. Safe to dispatch work."""

    REINITIALIZED = "reinitialized"
    """A mismatched runtime was replaced. Safe to dispatch work, but the epoch
    rotated — see :attr:`HandshakeResult.displaced_job_ids`."""

    BUSY = "busy"
    """A mismatched runtime is holding unfinished jobs. Nothing was changed and
    no work may be dispatched: replacing it would move the runtime identity out
    from under jobs that may still be running in Illustrator."""

    UNAVAILABLE = "unavailable"
    """The host could not be reached or did not answer usefully. The runtime
    state is unknown; no work may be dispatched."""


@dataclass(frozen=True)
class HostRuntimeState:
    """What the host says it is running."""

    present: bool
    bootstrap_version: Optional[str] = None
    protocol_version: Optional[str] = None
    runtime_hash: Optional[str] = None
    session_epoch: Optional[str] = None
    capabilities: Dict[str, Any] = field(default_factory=dict)
    installed_at: Optional[int] = None
    active_jobs: int = 0
    active_job_ids: List[str] = field(default_factory=list)
    retained_jobs: int = 0
    retained_job_ids: List[str] = field(default_factory=list)

    @classmethod
    def from_host(cls, data: Dict[str, Any]) -> "HostRuntimeState":
        return cls(
            present=bool(data.get("present")),
            bootstrap_version=data.get("bootstrapVersion"),
            protocol_version=data.get("protocolVersion"),
            runtime_hash=data.get("runtimeHash"),
            session_epoch=data.get("sessionEpoch"),
            capabilities=data.get("capabilities") or {},
            installed_at=data.get("installedAt"),
            active_jobs=int(data.get("activeJobs") or 0),
            active_job_ids=list(data.get("activeJobIds") or []),
            retained_jobs=int(data.get("retainedJobs") or 0),
            retained_job_ids=list(data.get("retainedJobIds") or []),
        )


@dataclass(frozen=True)
class HandshakeResult:
    """Result of :meth:`HostSession.handshake`."""

    status: HandshakeStatus
    state: HostRuntimeState
    mismatches: List[str] = field(default_factory=list)
    displaced_job_ids: List[str] = field(default_factory=list)
    previous_epoch: Optional[str] = None
    epoch_rotated: bool = False
    detail: Optional[str] = None

    @property
    def ok(self) -> bool:
        """Whether work may be dispatched after this handshake."""
        return self.status in (
            HandshakeStatus.READY,
            HandshakeStatus.INITIALIZED,
            HandshakeStatus.REINITIALIZED,
        )

    @property
    def unresolved_jobs_are_unknown(self) -> bool:
        """True when jobs were displaced by a reinitialisation.

        Those jobs are **unknown**, never "not applied": the host may have
        completed them before the runtime was replaced. Callers must reconcile
        rather than assume nothing happened.
        """
        return bool(self.displaced_job_ids)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "ok": self.ok,
            "sessionEpoch": self.state.session_epoch,
            "protocolVersion": self.state.protocol_version,
            "runtimeHash": self.state.runtime_hash,
            "capabilities": self.state.capabilities,
            "activeJobs": self.state.active_jobs,
            "mismatches": self.mismatches,
            "displacedJobIds": self.displaced_job_ids,
            "epochRotated": self.epoch_rotated,
            "detail": self.detail,
        }


def _unwrap(response: Any) -> Optional[Dict[str, Any]]:
    """Pull the JSX payload out of a bridge response, or None if unusable.

    Mirrors the T01 rule: a missing, null, or unparseable result establishes
    nothing and must not be read as success.
    """
    if not isinstance(response, dict) or response.get("error"):
        return None
    if "result" not in response:
        return None
    raw = response["result"]
    if raw is None:
        return None
    if isinstance(raw, dict):
        if "ok" in raw:
            if raw.get("ok") is False:
                return None
            raw = raw.get("data")
        elif "data" in raw:
            raw = raw["data"]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    return raw if isinstance(raw, dict) else None


class HostSession:
    """Tracks the identity of the runtime installed in Illustrator."""

    def __init__(
        self,
        protocol_version: str = TASK_PROTOCOL_VERSION,
        executor=None,
    ) -> None:
        self.protocol_version = protocol_version
        self._session_epoch: Optional[str] = None
        self._runtime_hash: Optional[str] = None
        # Injected for testing; defaults to the real bridge call.
        self._executor = executor

    # ── plumbing ───────────────────────────────────────────────────

    async def _run(self, script: str, label: str) -> Optional[Dict[str, Any]]:
        if self._executor is not None:
            response = await self._executor(script=script, label=label)
        else:
            from illustrator_mcp.proxy_client import execute_script_with_context

            response = await execute_script_with_context(
                script=script,
                command_type=f"host_runtime:{label}",
                tool_name="host_runtime",
                includes=[BOOTSTRAP_LIBRARY],
            )
        return _unwrap(response)

    @property
    def session_epoch(self) -> Optional[str]:
        """The epoch observed at the last successful handshake."""
        return self._session_epoch

    # ── operations ─────────────────────────────────────────────────

    async def read_state(self) -> Optional[HostRuntimeState]:
        """Ask the host what runtime it has, changing nothing."""
        data = await self._run("JSON.stringify(mcpRuntimeState())", "state")
        return None if data is None else HostRuntimeState.from_host(data)

    async def handshake(
        self,
        runtime_hash: Optional[str] = None,
        capabilities: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> HandshakeResult:
        """Reconcile the host runtime with what this server expects.

        Repeatable: calling it when the runtime already matches is a no-op that
        returns ``READY`` without touching the host's state or epoch.

        Args:
            runtime_hash: Expected library-prelude hash. A different hash means
                the host is running different code and is replaced.
            capabilities: Recorded on the host when (re)initialising.
            force: Replace even when the host holds unfinished jobs. Their IDs
                come back in ``displaced_job_ids`` and are **unknown**, not
                unapplied.
        """
        expected = {
            "protocolVersion": self.protocol_version,
            "runtimeHash": runtime_hash,
        }
        # Only pin the epoch once we have actually seen one.
        if self._session_epoch:
            expected["sessionEpoch"] = self._session_epoch

        data = await self._run(
            f"JSON.stringify(mcpRuntimeHandshake({json.dumps(expected)}))",
            "handshake",
        )
        if data is None:
            return HandshakeResult(
                status=HandshakeStatus.UNAVAILABLE,
                state=HostRuntimeState(present=False),
                detail=(
                    "The host did not return a usable runtime state. Its "
                    "runtime is unknown; no work was dispatched."
                ),
            )

        state = HostRuntimeState.from_host(data.get("state") or {})
        mismatches = list(data.get("mismatches") or [])
        host_status = data.get("status")

        if host_status == "ready":
            previous = self._session_epoch
            self._session_epoch = state.session_epoch
            self._runtime_hash = state.runtime_hash
            return HandshakeResult(
                status=HandshakeStatus.READY,
                state=state,
                previous_epoch=previous,
                epoch_rotated=bool(previous and previous != state.session_epoch),
            )

        # Absent or mismatched — (re)initialise.
        return await self._initialize(
            state_before=state,
            mismatches=mismatches,
            runtime_hash=runtime_hash,
            capabilities=capabilities,
            force=force,
        )

    async def _initialize(
        self,
        state_before: HostRuntimeState,
        mismatches: List[str],
        runtime_hash: Optional[str],
        capabilities: Optional[Dict[str, Any]],
        force: bool,
    ) -> HandshakeResult:
        spec = {
            "protocolVersion": self.protocol_version,
            "runtimeHash": runtime_hash,
            "capabilities": capabilities or {},
            "force": bool(force),
        }
        data = await self._run(
            f"JSON.stringify(mcpRuntimeInit({json.dumps(spec)}))", "init"
        )
        if data is None:
            return HandshakeResult(
                status=HandshakeStatus.UNAVAILABLE,
                state=state_before,
                mismatches=mismatches,
                detail=(
                    "Runtime initialisation returned no usable result. Whether "
                    "it took effect is unknown; no work was dispatched."
                ),
            )

        if not data.get("ok"):
            # The host refused — almost always because jobs are still open.
            displaced = list(data.get("displacedJobIds") or [])
            return HandshakeResult(
                status=HandshakeStatus.BUSY,
                state=HostRuntimeState.from_host(data.get("state") or {}),
                mismatches=mismatches,
                displaced_job_ids=displaced,
                previous_epoch=data.get("previousEpoch"),
                detail=data.get("message"),
            )

        new_state = HostRuntimeState.from_host(data.get("state") or {})
        previous_epoch = data.get("previousEpoch")
        displaced = list(data.get("displacedJobIds") or [])

        self._session_epoch = new_state.session_epoch
        self._runtime_hash = new_state.runtime_hash

        reinit = data.get("status") == "reinitialised"
        if displaced:
            logger.warning(
                "Host runtime reinitialised over %d unfinished job(s): %s. "
                "Their outcome is UNKNOWN — reconcile, do not assume they were "
                "not applied.",
                len(displaced), displaced,
            )

        return HandshakeResult(
            status=HandshakeStatus.REINITIALIZED if reinit else HandshakeStatus.INITIALIZED,
            state=new_state,
            mismatches=mismatches,
            displaced_job_ids=displaced,
            previous_epoch=previous_epoch,
            epoch_rotated=bool(previous_epoch and previous_epoch != new_state.session_epoch),
        )

    async def begin_work(
        self,
        job_id: str,
        digest: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Open a managed job and its retained host record.

        ``digest`` and ``context`` are optional for compatibility with the T10
        caller. Managed T16 callers supply both so a duplicate can be returned
        without replay and conflicting reuse can be rejected.
        """
        spec: Any = job_id
        if digest is not None or context is not None:
            spec = {"jobId": job_id}
            if digest is not None:
                spec["digest"] = digest
            if context is not None:
                spec["context"] = context
        data = await self._run(
            f"JSON.stringify(mcpRuntimeBeginWork({json.dumps(spec)}))", "begin"
        )
        return data or {"ok": False, "status": "unavailable"}

    async def complete_work(
        self,
        job_id: str,
        outcome: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Finalise and retain a managed host outcome."""
        data = await self._run(
            "JSON.stringify(mcpRuntimeCompleteWork(" +
            f"{json.dumps(job_id)}, {json.dumps(outcome)}))",
            "complete",
        )
        return data or {"ok": False, "status": "unavailable"}

    async def job_status(self, job_id: str) -> Dict[str, Any]:
        """Read a retained host record without replaying the job."""
        data = await self._run(
            f"JSON.stringify(mcpRuntimeJobStatus({json.dumps(job_id)}))",
            "job_status",
        )
        return data or {
            "ok": False,
            "status": "unknown",
            "reason": "host_unavailable",
        }

    async def end_work(self, job_id: str) -> Dict[str, Any]:
        """Close a job on the host."""
        data = await self._run(
            f"JSON.stringify(mcpRuntimeEndWork({json.dumps(job_id)}))", "end"
        )
        return data or {"ok": False, "status": "unavailable"}

    async def reset(self) -> Dict[str, Any]:
        """Tear the runtime down; the next handshake reports ``absent``."""
        data = await self._run("JSON.stringify(mcpRuntimeReset())", "reset")
        self._session_epoch = None
        self._runtime_hash = None
        return data or {"ok": False, "status": "unavailable"}
