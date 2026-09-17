"""Canonical MCP result boundary (T11).

One place that decides what an MCP client is told about a call, so a tool
cannot independently invent its own answer.

The problem this replaces: the registered handler returned ``isError: false``
for a tool result whose own JSON said ``ok: false``, and ``structuredContent``
held a wrapper around a JSON *string* rather than the result object. An agent
had to parse nested strings to discover that its edit had failed.

Three outcomes are tracked separately, because collapsing them is what made
results untrustworthy:

``execution``
    Did the requested work run to completion? This alone sets ``isError``.
``verification``
    Was the result visually checked? A preview that failed to render says
    nothing about whether the edit applied — ``VerificationStatus.UNAVAILABLE``
    is not ``FAILED``, and neither one turns a successful mutation into a
    failure.
``recovery``
    Was anything rolled back, and did that succeed? A failed job that was
    restored is still a failed job with a successful recovery.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Literal

from mcp.types import CallToolResult, ContentBlock, ImageContent, TextContent
from pydantic import BaseModel, Field, model_validator, computed_field

#: Bumped when the shape below changes incompatibly. Clients may branch on it.
RESULT_SCHEMA_VERSION = "1.1"

# OR07: reporting semantics, separate from the wire schema. Nested typed fields
# inherit their root's category; the coverage gate still inventories every leaf
# explicitly, so adding a nested field cannot inherit a coverage waiver.
CANONICAL_REPORTING_SEMANTICS = {
    "schemaVersion": ("constant", "The published result contract version."),
    "tool": ("constant", "The registered tool that served this request."),
    "execution": ("observed", "Completion established from execution evidence; absence is not success."),
    "jobId": ("optional", "Retained execution identity when the coordinator provides one."),
    "data": ("optional", "Tool-specific result, preserved when available; not an effects inventory."),
    "effects": ("observed", "Known final document changes; coverage derives from completeness and retained evidence."),
    "verification": ("observed", "Independent check outcome, scope and explanation."),
    "recovery": ("observed", "Final scoped recovery summary and original attempts; independent of execution."),
    "error": ("optional", "Primary failure and available location/remediation information."),
    "warnings": ("observed", "Disclosed limitations and nonfatal problems, retained across boundaries."),
    "diagnostics": ("optional", "Available execution and transport evidence; no invented observations."),
    "truncation": ("observed", "Explicit disclosure of withheld detail, its notes and retrieval route."),
    "ok": ("derived", "True exactly when execution is succeeded; ignores a contradictory input ok."),
    "isError": ("derived", "MCP wire flag: false exactly when execution is succeeded, independent of recovery/verification."),
}


class ExecutionStatus(str, Enum):
    """Did the requested work happen?"""

    SUCCEEDED = "succeeded"
    """Every required operation completed its documented postconditions."""

    FAILED = "failed"
    """The request did not succeed. Inspect ``effects`` for what did happen."""

    PARTIAL = "partial"
    """Some requested effects occurred; the batch did not complete."""

    UNKNOWN = "unknown"
    """The available evidence cannot establish the outcome — a timeout, a lost
    response, a reinitialised runtime. NOT a synonym for "nothing happened"."""

    def is_error(self) -> bool:
        """Only a clean success is not an error.

        ``UNKNOWN`` counts as an error: the caller must not treat an
        unestablished outcome as a completed one.
        """
        return self is not ExecutionStatus.SUCCEEDED


class VerificationStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    """A check was wanted but could not be performed (preview export failed,
    Pillow missing, empty canvas). Explicitly NOT ``FAILED``."""


class RecoveryStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    NOT_NEEDED = "not_needed"
    UNSUPPORTED = "unsupported"
    RESTORED = "restored"
    PARTIAL = "partial"
    FAILED = "failed"
    UNKNOWN = "unknown"


class Effects(BaseModel):
    """What is known to have changed in the document.

    ``complete`` is the important field: it says whether this list is the whole
    story. A raw script's effects are never complete — nothing inspects an
    arbitrary script to find out what it touched — so it must not be presented
    as an exhaustive account.
    """

    created: List[str] = Field(default_factory=list)
    modified: List[str] = Field(default_factory=list)
    deleted: List[str] = Field(default_factory=list)
    complete: bool = Field(
        default=False,
        description=(
            "True only when these lists are known to be exhaustive. False for "
            "raw scripts and for any job whose outcome is unknown."
        ),
    )

    @computed_field
    @property
    def coverage(self) -> Literal["exhaustive", "partial", "untracked"]:
        if self.complete:
            return "exhaustive"
        return "partial" if self.created or self.modified or self.deleted else "untracked"

    coverageReason: Optional[str] = None


class Verification(BaseModel):
    status: VerificationStatus = VerificationStatus.NOT_REQUESTED
    scope: Optional[str] = None
    detail: Optional[str] = None


class RecoveryAttempt(BaseModel):
    """One producer's recovery outcome, retained at its original scope."""

    status: RecoveryStatus
    scope: Optional[str] = None
    requested: Optional[str] = None
    detail: Optional[Any] = None


class Recovery(BaseModel):
    status: RecoveryStatus = RecoveryStatus.NOT_REQUESTED
    scope: Optional[str] = None
    detail: Optional[str] = None
    attempts: List[RecoveryAttempt] = Field(default_factory=list)


class Truncation(BaseModel):
    """Detail that was withheld, and how to get it."""

    truncated: bool = False
    notes: List[Dict[str, Any]] = Field(default_factory=list)
    retrieval_hint: Optional[str] = None


class ToolError(BaseModel):
    code: str
    message: str
    suggestions: List[str] = Field(default_factory=list)
    nextStep: Optional[Any] = None
    details: Optional[Any] = None
    operation: Optional[str] = None
    line: Optional[int] = None


class CanonicalResult(BaseModel):
    """The single result shape every migrated tool returns."""

    schema_version: str = Field(default=RESULT_SCHEMA_VERSION, alias="schemaVersion")
    execution: ExecutionStatus
    tool: str
    job_id: Optional[str] = Field(default=None, alias="jobId")
    data: Optional[Any] = None
    effects: Effects = Field(default_factory=Effects)
    verification: Verification = Field(default_factory=Verification)
    recovery: Recovery = Field(default_factory=Recovery)
    error: Optional[ToolError] = None
    warnings: List[str] = Field(default_factory=list)
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
    truncation: Truncation = Field(default_factory=Truncation)

    #: Retained so existing clients keep working. ALWAYS derived from
    #: `execution` — a tool cannot assign it independently, which is how
    #: `ok: false` results used to reach MCP as `isError: false`.
    ok: bool = True

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _derive_ok(self) -> "CanonicalResult":
        object.__setattr__(self, "ok", not self.execution.is_error())
        return self

    @classmethod
    def from_envelope(
        cls,
        envelope: Dict[str, Any],
        tool: str,
        execution: Optional[ExecutionStatus] = None,
        **overrides: Any,
    ) -> "CanonicalResult":
        """Build from the legacy ``{ok, result, error, warnings, diagnostics}``.

        Used by the compatibility adapters while tools migrate. ``ok`` is read
        as the execution outcome unless one is given explicitly.
        """
        if execution is None:
            execution = (
                ExecutionStatus.UNKNOWN
                if (envelope.get("diagnostics") or {}).get("execution") == "unknown"
                else
                ExecutionStatus.SUCCEEDED if envelope.get("ok")
                else ExecutionStatus.FAILED
            )

        error = None
        raw_error = envelope.get("error")
        if isinstance(raw_error, dict):
            error = ToolError(
                code=raw_error.get("code", "E999"),
                message=raw_error.get("message", "Unknown error"),
                suggestions=list(raw_error.get("suggestions") or []),
                operation=raw_error.get("operation"),
                line=raw_error.get("line"),
                details=raw_error.get("details"),
                nextStep=raw_error.get("nextStep") or (raw_error["details"].get("nextStep") if isinstance(raw_error.get("details"), dict) else None),
            )
        elif raw_error:
            error = ToolError(code="E999", message=str(raw_error))

        warnings = [
            w if isinstance(w, str) else str(w.get("message", w))
            for w in (envelope.get("warnings") or [])
        ]

        result = cls(
            execution=execution,
            tool=tool,
            job_id=(envelope.get("diagnostics") or {}).get("jobId"),
            data=envelope.get("result"),
            error=error,
            warnings=warnings,
            diagnostics=dict(envelope.get("diagnostics") or {}),
        )
        for key, value in overrides.items():
            setattr(result, key, value)
        # Re-derive after any override touched `execution`.
        object.__setattr__(result, "ok", not result.execution.is_error())
        return result

    def to_structured(self) -> Dict[str, Any]:
        """The object placed in ``structuredContent`` — never a JSON string."""
        return self.model_dump(mode="json", by_alias=True, exclude_none=False)

    def summary_line(self) -> str:
        """A short human-readable header for the text block."""
        if self.execution is ExecutionStatus.SUCCEEDED:
            head = f"{self.tool}: succeeded"
        elif self.error:
            head = f"{self.tool}: {self.execution.value} — [{self.error.code}] {self.error.message}"
        else:
            head = f"{self.tool}: {self.execution.value}"

        extras = []
        if not self.effects.complete:
            extras.append("effects " + self.effects.coverage)
        if self.effects.created:
            extras.append(f"created {len(self.effects.created)}")
        if self.effects.modified:
            extras.append(f"modified {len(self.effects.modified)}")
        if self.effects.deleted:
            extras.append(f"deleted {len(self.effects.deleted)}")
        if self.verification.status not in (
            VerificationStatus.NOT_REQUESTED, VerificationStatus.PASSED
        ):
            extras.append(f"verification {self.verification.status.value}")
        if self.recovery.status not in (
            RecoveryStatus.NOT_REQUESTED, RecoveryStatus.NOT_NEEDED
        ):
            extras.append(f"recovery {self.recovery.status.value}")
        if self.truncation.truncated:
            extras.append("detail truncated")
        return head + (f" ({', '.join(extras)})" if extras else "")


def build_call_result(
    result: CanonicalResult,
    extra_content: Optional[List[ContentBlock]] = None,
) -> CallToolResult:
    """Turn a :class:`CanonicalResult` into the MCP wire result.

    ``isError`` follows :meth:`ExecutionStatus.is_error` and nothing else —
    in particular, a failed or unavailable *verification* never turns a
    successful mutation into a tool error.
    """
    import json as _json

    if result.tool == "illustrator_execute_script":
        result.effects.complete = False
        result.effects.coverageReason = "raw_script_modifications_untracked" if result.effects.coverage == "partial" else "raw_script"
    else:
        result.effects.coverageReason = "producer_exhaustive" if result.effects.complete else "limited_producer_evidence"
    blocks: List[ContentBlock] = [
        TextContent(type="text", text=result.summary_line()),
        TextContent(
            type="text",
            text=_json.dumps(result.to_structured(), separators=(",", ":"), default=str),
        ),
    ]
    if extra_content:
        blocks.extend(extra_content)

    return CallToolResult(
        content=blocks,
        structuredContent=result.to_structured(),
        isError=result.execution.is_error(),
    )


def image_blocks(blocks: Optional[List[ContentBlock]]) -> List[ContentBlock]:
    """Filter to just the image blocks of a mixed content list."""
    return [b for b in (blocks or []) if isinstance(b, ImageContent)]


def _looks_like_envelope(value: Any) -> bool:
    return isinstance(value, dict) and "ok" in value and (
        "result" in value or "error" in value or "diagnostics" in value
    )


def _batch_report_from_envelope(envelope: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Locate a structured executor report in success or failure envelopes."""
    diagnostics = envelope.get("diagnostics") or {}
    if isinstance(diagnostics.get("batchReport"), dict):
        return diagnostics["batchReport"]
    payload = envelope.get("result")
    if not isinstance(payload, dict):
        return None
    report = payload.get("report", payload)
    if isinstance(report, dict) and isinstance(report.get("batchReport"), dict):
        return report["batchReport"]
    return None


def _effect_ids(raw: Any) -> "tuple[List[str], int, bool]":
    """Usable identities, how many entries were not, and whether the shape was.

    Returns ``(ids, dropped, malformed)``. Two different faults live here and
    conflating them cost a round:

    *Bad entries.* A batch keeps positional alignment by putting null where an
    instance failed, so a raw list can carry entries that are not identities.
    Handing those to ``Effects`` raised a ValidationError and failed the whole
    tool call, turning one skipped instance into no result at all.

    *A bad shape.* ``"created": "id-real"`` is not a list. The first version of
    this function returned ``([], 0)`` for anything that was not a list, and
    the zero meant neither caller reduced completeness — so a scalar or a
    mapping became an empty ``created`` reported as a complete account. That
    is silent data loss wearing a success, which is the defect this file is
    supposed to catch rather than commit.

    So a malformed shape is flagged rather than counted. No number is inferred
    from it: how many identities a string was meant to hold is not knowable,
    and guessing would be a second invention on top of the first. Absent and
    ``None`` are not malformed — an operation that created nothing is an
    ordinary, complete answer.
    """
    if raw is None:
        return [], 0, False
    if not isinstance(raw, (list, tuple)):
        return [], 0, True
    usable = [item for item in raw if isinstance(item, str) and item]
    return usable, len(raw) - len(usable), False


def _declared_effects(envelope: Dict[str, Any]) -> Optional["Effects"]:
    """Effects a tool stated directly, for the paths with no batch report.

    Only the structured executor produces a ``batchReport``, so until now it
    was the only tool whose effects reached the canonical field. Every other
    mutating tool left it empty with ``complete`` false — which is not a
    neutral default but a claim that the change cannot be accounted for, and
    the boolean was making that claim while listing the very ids it had
    created and deleted one level down in ``data``.

    A tool declares them under ``diagnostics.effects``; the raw host report
    stays where it is, as detail, and a test asserts the two agree.
    """
    diagnostics = envelope.get("diagnostics")
    raw = diagnostics.get("effects") if isinstance(diagnostics, dict) else None
    if not isinstance(raw, dict):
        return None
    created, bad_created, malformed_created = _effect_ids(raw.get("created"))
    deleted, bad_deleted, malformed_deleted = _effect_ids(raw.get("deleted"))
    modified, bad_modified, malformed_modified = _effect_ids(raw.get("modified"))
    return Effects(
        created=created,
        modified=modified,
        deleted=deleted,
        complete=bool(raw.get("complete", False)) and not any((
            bad_created, bad_deleted, bad_modified,
            malformed_created, malformed_deleted, malformed_modified,
        )),
    )


_RECOVERY_STATUS_MAP = {
    status.value: status for status in RecoveryStatus
}


def _recovery_attempt(raw: Any, location: str) -> Optional[RecoveryAttempt]:
    """Normalize one host recovery disclosure without upgrading its claim.

    ``withTransaction`` predates the canonical enum and uses ``none`` when it
    captured no properties and therefore attempted no restore.  That is
    ``not_requested`` with retained detail, not evidence that anything was
    restored.  Unknown producer statuses remain ``unknown``.
    """
    if not isinstance(raw, dict) or not raw.get("status"):
        return None

    raw_status = str(raw.get("status"))
    status = _RECOVERY_STATUS_MAP.get(raw_status, RecoveryStatus.UNKNOWN)
    detail = {
        key: value
        for key, value in raw.items()
        if key not in {"status", "scope", "requested"}
    }
    detail["source"] = location
    if raw_status == "none":
        status = RecoveryStatus.NOT_REQUESTED
        detail["legacyStatus"] = "none"
        detail["mapping"] = (
            "No captured properties were restored; this is not a restoration claim."
        )
    elif raw_status not in _RECOVERY_STATUS_MAP:
        detail["rawStatus"] = raw_status

    scope = raw.get("scope")
    requested = raw.get("requested")
    if scope is not None:
        scope = str(scope)
    if requested is not None:
        requested = str(requested)
    if status is RecoveryStatus.UNSUPPORTED and scope is None:
        scope = "structured batch request"

    return RecoveryAttempt(
        status=status,
        scope=scope,
        requested=requested,
        detail=detail or None,
    )


def _recovery_from_envelope(envelope: Dict[str, Any]) -> Optional[Recovery]:
    """Lift all known host recovery disclosures into one canonical value.

    Producers currently disclose recovery at four compatibility locations:
    the envelope/result, the batch report, an operation result, or an
    operation's data/error details.  The individual attempts are retained;
    only the summary status is reduced.
    """
    found: List[RecoveryAttempt] = []
    seen_recovery_events: set[tuple[str, ...]] = set()

    def add(raw: Any, location: str) -> None:
        if isinstance(raw, list):
            for index, item in enumerate(raw):
                add(item, f"{location}[{index}]")
            return
        attempt = _recovery_attempt(raw, location)
        if attempt is None:
            return

        # A current executor promotes the same bounded record from an
        # operation to its batch so summaryOnly can omit operation details.
        # That is one attempt serialized twice, not two attempts. Ownership
        # events can also be recognized by stable scope + chronology if a
        # compatibility wrapper copied the record without its transport id.
        event_key: Optional[tuple[str, ...]] = None
        if isinstance(raw, dict):
            if raw.get("scopeKey") is not None and isinstance(
                raw.get("eventSequence"), (int, float)
            ):
                event_key = (
                    "scope-sequence",
                    str(raw["scopeKey"]),
                    str(raw["eventSequence"]),
                )
            elif raw.get("recoveryId"):
                event_key = ("recovery-id", str(raw["recoveryId"]))
        if event_key is not None:
            if event_key in seen_recovery_events:
                return
            seen_recovery_events.add(event_key)
        found.append(attempt)

    add(envelope.get("recovery"), "envelope.recovery")
    diagnostics = envelope.get("diagnostics")
    if isinstance(diagnostics, dict):
        add(diagnostics.get("recovery"), "diagnostics.recovery")

    payload = envelope.get("result")
    if isinstance(payload, dict):
        add(payload.get("recovery"), "result.recovery")
        report = payload.get("report", payload)
        if isinstance(report, dict) and report is not payload:
            add(report.get("recovery"), "report.recovery")

    batch = _batch_report_from_envelope(envelope)
    if isinstance(batch, dict):
        add(batch.get("recovery"), "batchReport.recovery")
        def add_operation(op: Any, op_location: str) -> None:
            if not isinstance(op, dict):
                return
            if isinstance(op.get("recovery"), (dict, list)):
                # The normalized top-level location is authoritative and is
                # retained by response budgeting. Older reports may lack it;
                # those fall through to the supported data locations below.
                add(op.get("recovery"), f"{op_location}.recovery")
            else:
                data = op.get("data")
                if isinstance(data, dict):
                    add(data.get("recovery"), f"{op_location}.data.recovery")
                    for target_index, target in enumerate(data.get("perTarget") or []):
                        if isinstance(target, dict):
                            add(
                                target.get("recovery"),
                                f"{op_location}.data.perTarget[{target_index}].recovery",
                            )
                    # Compatibility with compound reports emitted before the
                    # host promoted child recovery to the compound operation.
                    for child_index, child in enumerate(data.get("results") or []):
                        add_operation(
                            child,
                            f"{op_location}.data.results[{child_index}]",
                        )
            error = op.get("error")
            details = error.get("details") if isinstance(error, dict) else None
            if isinstance(details, dict):
                add(details.get("recovery"), f"{op_location}.error.details.recovery")

        for index, op in enumerate(batch.get("ops") or []):
            add_operation(op, f"batchReport.ops[{index}]")

    return reduce_recovery_attempts(found)


def reduce_recovery_attempts(found: List[RecoveryAttempt]) -> Optional[Recovery]:
    """One final-scope reducer for compatibility envelopes and operation journals."""
    if not found:
        return None

    # Attempts are history; the summary describes current state. Producers
    # that support retries provide a stable scopeKey. Only the last record for
    # that machine identity participates in reduction, while all records stay
    # in `attempts`. Records without a key remain independent. In particular,
    # never infer identity from a human-readable scope label: labels may repeat
    # for unrelated ownership scopes.
    final_by_scope: Dict[
        tuple[str, str], tuple[Optional[float], RecoveryAttempt]
    ] = {}
    final_order: List[tuple[str, str]] = []
    for index, attempt in enumerate(found):
        attempt_detail = attempt.detail if isinstance(attempt.detail, dict) else {}
        scope_key = attempt_detail.get("scopeKey")
        raw_sequence = attempt_detail.get("eventSequence")
        event_sequence = (
            float(raw_sequence)
            if isinstance(raw_sequence, (int, float))
            else None
        )
        key = (
            ("scope", str(scope_key))
            if scope_key is not None
            else ("attempt", str(index))
        )
        if key not in final_by_scope:
            final_order.append(key)
            final_by_scope[key] = (event_sequence, attempt)
            continue

        previous_sequence, _ = final_by_scope[key]
        # Explicit handler recovery is merged before automatic events, so
        # serialization order is not chronology. A sequenced record replaces
        # only an older (or legacy unsequenced) state. Two legacy records keep
        # their historical last-write behavior for compatibility.
        if event_sequence is not None:
            if previous_sequence is None or event_sequence > previous_sequence:
                final_by_scope[key] = (event_sequence, attempt)
        elif previous_sequence is None:
            final_by_scope[key] = (None, attempt)

    final_attempts = [final_by_scope[key][1] for key in final_order]
    statuses = [attempt.status for attempt in final_attempts]
    effective = [
        status for status in statuses
        if status not in (RecoveryStatus.NOT_REQUESTED, RecoveryStatus.NOT_NEEDED)
    ]
    if not effective:
        summary = (
            RecoveryStatus.NOT_NEEDED
            if statuses and all(status is RecoveryStatus.NOT_NEEDED for status in statuses)
            else RecoveryStatus.NOT_REQUESTED
        )
    elif RecoveryStatus.UNKNOWN in effective:
        summary = RecoveryStatus.UNKNOWN
    elif RecoveryStatus.PARTIAL in effective:
        summary = RecoveryStatus.PARTIAL
    elif RecoveryStatus.RESTORED in effective and any(
        status in (RecoveryStatus.FAILED, RecoveryStatus.UNSUPPORTED)
        for status in effective
    ):
        summary = RecoveryStatus.PARTIAL
    elif all(status is RecoveryStatus.RESTORED for status in effective):
        summary = RecoveryStatus.RESTORED
    elif all(status is RecoveryStatus.FAILED for status in effective):
        summary = RecoveryStatus.FAILED
    elif all(status is RecoveryStatus.UNSUPPORTED for status in effective):
        summary = RecoveryStatus.UNSUPPORTED
    else:
        # Mixed attempted outcomes are not collapsed to the most optimistic
        # member. Their exact records remain available in ``attempts``.
        summary = RecoveryStatus.PARTIAL

    scopes = {attempt.scope for attempt in final_attempts if attempt.scope}
    scope = next(iter(scopes)) if len(scopes) == 1 else (
        "multiple scopes" if len(scopes) > 1 else None
    )
    detail = (
        f"{len(found)} recovery attempt(s) are retained; "
        f"{len(final_attempts)} final scope outcome(s) determine this summary."
    )
    return Recovery(status=summary, scope=scope, detail=detail, attempts=found)


def _executor_result_overrides(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Lift executor effects and postconditions into the canonical result."""
    batch = _batch_report_from_envelope(envelope)
    recovery = _recovery_from_envelope(envelope)
    if not batch:
        declared = _declared_effects(envelope)
        out: Dict[str, Any] = {}
        if declared is not None:
            out["effects"] = declared
        if recovery is not None:
            out["recovery"] = recovery
        return out

    raw_effects = batch.get("effects") or {}
    batch_created, bad_created, malformed_created = _effect_ids(
        raw_effects.get("created"))
    batch_deleted, bad_deleted, malformed_deleted = _effect_ids(
        raw_effects.get("deleted"))
    batch_modified, bad_modified, malformed_modified = _effect_ids(
        raw_effects.get("modified"))
    effects = Effects(
        created=batch_created,
        modified=batch_modified,
        deleted=batch_deleted,
        complete=bool(raw_effects.get("complete", False)) and not any((
            bad_created, bad_deleted, bad_modified,
            malformed_created, malformed_deleted, malformed_modified,
        )),
    )

    postconditions = [
        op.get("postcondition")
        for op in (batch.get("ops") or [])
        if isinstance(op, dict) and isinstance(op.get("postcondition"), dict)
    ]
    statuses = {p.get("status") for p in postconditions}
    if "failed" in statuses:
        verification = Verification(
            status=VerificationStatus.FAILED,
            scope="structured operation postconditions",
        )
    elif "unavailable" in statuses:
        verification = Verification(
            status=VerificationStatus.UNAVAILABLE,
            scope="structured operation postconditions",
        )
    elif postconditions and statuses.issubset({"passed", "not_requested"}):
        verification = Verification(
            status=VerificationStatus.PASSED,
            scope="structured operation postconditions",
        )
    else:
        verification = Verification()

    any_effect = bool(
        effects.created or effects.modified or effects.deleted
        or int(raw_effects.get("unidentified") or 0) > 0
    )

    execution = None
    if not envelope.get("ok") and any_effect:
        execution = ExecutionStatus.PARTIAL
    elif envelope.get("ok") and (raw_effects.get("unapplied") or []):
        # Handlers may return ok while declining individual targets — styling
        # a rectangle as if it were text, or an ID that resolved to nothing.
        # SUCCEEDED is defined as "every required operation completed its
        # documented postconditions", so a request the executor recorded as
        # partly unapplied must not claim it. Without this, `text_set_content`
        # aimed at a non-text object reported a confident success having
        # changed nothing at all.
        execution = (
            ExecutionStatus.PARTIAL if any_effect else ExecutionStatus.FAILED
        )

    out: Dict[str, Any] = {"effects": effects, "verification": verification}
    if recovery is not None:
        out["recovery"] = recovery
    if execution is not None:
        out["execution"] = execution
    return out


def finalize_tool_result(value: Any, tool: str) -> CallToolResult:
    """Convert whatever a tool returned into the canonical MCP result.

    This is the single chokepoint where MCP presentation is decided, so no
    tool can independently disagree with it. It accepts the shapes tools
    currently produce:

    * a JSON envelope string — the common case;
    * a list of content blocks (envelope text plus images and annotation maps),
      as the auto-grounding paths return;
    * an already-built :class:`CallToolResult`, passed through untouched;
    * anything else, which is carried as opaque data.

    ``isError`` is derived from the envelope's ``ok``, so a result whose own
    JSON says ``ok: false`` can no longer arrive at the client as
    ``isError: false``.
    """
    import json as _json

    if isinstance(value, CallToolResult):
        return value

    extra: List[ContentBlock] = []
    envelope: Optional[Dict[str, Any]] = None

    if isinstance(value, str):
        try:
            parsed = _json.loads(value)
            if _looks_like_envelope(parsed):
                envelope = parsed
        except (ValueError, TypeError):
            envelope = None
        if envelope is None:
            # Not an envelope — a plain string result.
            return build_call_result(
                CanonicalResult(
                    tool=tool, execution=ExecutionStatus.SUCCEEDED, data=value
                )
            )

    elif isinstance(value, list):
        for block in value:
            text = getattr(block, "text", None)
            if envelope is None and isinstance(text, str):
                try:
                    parsed = _json.loads(text)
                except (ValueError, TypeError):
                    parsed = None
                if _looks_like_envelope(parsed):
                    envelope = parsed
                    continue  # replaced by the canonical blocks
            extra.append(block)

        if envelope is None:
            # No envelope in the list: keep the blocks, report success, and do
            # not invent a structured result we cannot substantiate.
            return CallToolResult(content=list(value), isError=False)

    elif _looks_like_envelope(value):
        envelope = value

    else:
        return build_call_result(
            CanonicalResult(
                tool=tool, execution=ExecutionStatus.SUCCEEDED, data=value
            )
        )

    result = CanonicalResult.from_envelope(
        envelope, tool=tool, **_executor_result_overrides(envelope)
    )

    # Carry the host's explicit truncation notes through to the client.
    diagnostics = result.diagnostics or {}
    notes = diagnostics.get("truncation")
    if notes:
        result.truncation = Truncation(
            truncated=True,
            notes=notes if isinstance(notes, list) else [notes],
            retrieval_hint=(
                "Re-run with a narrower selection or fewer operations to "
                "retrieve the omitted detail."
            ),
        )

    return build_call_result(result, extra_content=extra)


def summarize_result(result):
    """Opt-in presentation projection after full journal reduction/retention.

    Target maps, warnings, effects, verification and recovery remain actionable.
    No additional result store is created, and jobs without retained results
    never receive a fabricated retrieval promise.
    """
    canonical = CanonicalResult.model_validate(result.structuredContent)
    if isinstance(canonical.data, dict):
        canonical.data.pop("runtime", None)
        canonical.data.pop("changeHints", None)
        if isinstance(canonical.data.get("timing"), dict):
            canonical.data["timing"].pop("hostGuardMs", None)
    from illustrator_mcp.execution import get_coordinator
    job = get_coordinator().get(canonical.job_id) if canonical.job_id else None
    if job is not None and job.retained_call is not None:
        canonical.diagnostics["fullResult"] = {
            "tool": "illustrator_job_status", "params": {"jobId": job.job_id, "detail": "full"}}
    return build_call_result(canonical, list(result.content[2:]))
