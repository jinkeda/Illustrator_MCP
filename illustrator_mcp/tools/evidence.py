"""What verification an edit actually requires, and why.

This replaces a fixed narration checkpoint. The old policy fired every fifth
mutation and appended prose ordering the model to stop, describe the images,
and call no tools until it had written an analysis. Two things were wrong.

The trigger ignored what the edit did. A rename and a boolean reconstruction
each counted as one mutation, so evidence was demanded on a schedule unrelated
to risk, and a two hundred item batch could land with none.

The demand was unenforceable. A server cannot stop a client from calling a
tool, so the instruction was an order aimed at another model whose effect
varied by client. Structured requirements are data a caller can act on.

What replaces it: a decision derived from the operations actually performed,
the size of the batch, geometry the occlusion guard finds suspicious, and a
backlog counter kept as a backstop. The decision names its reasons, says which
evidence to look at and why, and lists the specific things to confirm.

Two questions stay separate throughout, because they fail independently:

* whether capture preserved document state, which the server checks and
  reports in the canonical ``verification`` block;
* whether the artwork meets the brief, which only the caller can judge, and
  which this module states as an explicit, unconfirmed obligation.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional, Sequence

from illustrator_mcp.occlusion_guard import SUSPICION_THRESHOLD

# ── Thresholds ─────────────────────────────────────────────────────

#: Operations in one batch beyond which the result is worth looking at. A
#: batch this size places enough artwork that a per-op report stops being a
#: practical substitute for seeing the page.
LARGE_BATCH_OPERATIONS: int = 12

#: Mutations that may accumulate with no evidence at all before evidence is
#: required regardless of what those mutations were. This is the backstop the
#: old cadence used as its only rule, kept because a long run of individually
#: cheap edits still drifts.
UNVERIFIED_BACKLOG: int = 5


class EvidenceReason(str, Enum):
    """Why verification is being asked for."""

    LAYOUT = "layout_change"
    CLIPPING = "clipping_change"
    BOOLEAN = "boolean_geometry"
    LARGE_BATCH = "large_batch"
    SUSPICIOUS_GEOMETRY = "suspicious_geometry"
    FINAL_DELIVERY = "final_delivery"
    UNVERIFIED_BACKLOG = "unverified_backlog"
    OPAQUE_SCRIPT = "opaque_script"


#: What the caller has to confirm, per reason. These are the questions the
#: server cannot answer for itself.
_CHECKS: dict = {
    EvidenceReason.LAYOUT:
        "items sit where intended, and nothing was displaced off the artboard",
    EvidenceReason.CLIPPING:
        "the mask crops the intended region and no content is unintentionally hidden",
    EvidenceReason.BOOLEAN:
        "the combined outline is the intended shape, with no stray fragments or holes",
    EvidenceReason.LARGE_BATCH:
        "the placed set is complete, evenly spaced, and free of unintended overlaps",
    EvidenceReason.SUSPICIOUS_GEOMETRY:
        "the flagged item is meant to cover what it covers",
    EvidenceReason.FINAL_DELIVERY:
        "the artwork matches the brief and is ready to deliver",
    EvidenceReason.UNVERIFIED_BACKLOG:
        "the accumulated edits still add up to the intended design",
    EvidenceReason.OPAQUE_SCRIPT:
        "the script changed what was intended and nothing else",
}

#: Operations that change nothing a picture would reveal. Everything else is
#: treated as a layout change, so an operation added to the contract without
#: being classified here errs toward asking for evidence rather than skipping
#: it silently.
#:
#: Every name here must exist in the contract SSOT. A misspelling would not
#: raise: it would simply never match, and the operation it was meant to
#: exempt would quietly demand evidence forever. A test pins the set against
#: the contract for exactly that reason.
_CHEAP_OPS: frozenset = frozenset({
    "style_set_fill", "style_set_stroke", "style_set_gradient",
    "style_remove_fill", "style_remove_stroke", "style_clone",
    "style_snapshot", "style_set_opacity",
    "text_set_content", "text_set_style",
    "layer_activate", "layer_list", "layer_lock", "layer_visible",
    "layer_create",
    "measure_bounds", "hash_structure", "snapshot_structure",
    "assert_alignment", "assert_bounds", "assert_count", "assert_exists",
    "assert_layer_order", "assert_style", "assert_text", "assert_z_order",
})

_CLIPPING_OPS: frozenset = frozenset({"clip_create", "compound"})
_BOOLEAN_OPS: frozenset = frozenset({"path_boolean"})


def classify_operation(task: str) -> Optional[EvidenceReason]:
    """The reason a single operation calls for visual evidence, if any."""
    if task in _CHEAP_OPS:
        return None
    if task in _CLIPPING_OPS:
        return EvidenceReason.CLIPPING
    if task in _BOOLEAN_OPS:
        return EvidenceReason.BOOLEAN
    return EvidenceReason.LAYOUT


@dataclass(frozen=True)
class EvidenceDecision:
    """Whether evidence is required for this edit, and what to look at."""

    required: bool
    mode: Optional[str]                 # "annotated" | "raw" | "both" | None
    reasons: tuple = ()
    crop: Optional[tuple] = None

    @property
    def checks(self) -> tuple:
        """The confirmations this edit calls for, in reason order."""
        seen: set = set()
        out: list = []
        for reason in self.reasons:
            text = _CHECKS.get(reason)
            if text and text not in seen:
                seen.add(text)
                out.append(text)
        return tuple(out)

    @property
    def reason_values(self) -> tuple:
        return tuple(r.value for r in self.reasons)


NO_EVIDENCE = EvidenceDecision(required=False, mode=None)


def capture_declined(requested: Optional[bool], *, final_step: bool) -> bool:
    """Automatic (None) and requested (True) allow capture; final delivery wins.

    This does not create a requirement or override caller-specific exclusions
    such as validation, dry runs, read-only scripts, or closing a document.
    """
    return requested is False and not final_step


def _mode_for(reasons: Iterable[EvidenceReason]) -> str:
    """Pick the cheapest evidence that answers the questions being asked.

    Annotated frames carry the numbered boxes that make follow-up targeting
    possible, so anything positional wants them. Appearance questions are
    answered better by an unannotated frame, because the boxes sit on top of
    the artwork being judged. When both are asked, ask for both.
    """
    reasons = set(reasons)
    positional = reasons & {
        EvidenceReason.LAYOUT, EvidenceReason.LARGE_BATCH,
        EvidenceReason.SUSPICIOUS_GEOMETRY, EvidenceReason.OPAQUE_SCRIPT,
    }
    appearance = reasons & {
        EvidenceReason.BOOLEAN, EvidenceReason.CLIPPING,
        EvidenceReason.FINAL_DELIVERY,
    }
    if positional and appearance:
        return "both"
    if appearance:
        return "raw"
    return "annotated"


def decide(
    *,
    operations: Optional[Sequence[str]] = None,
    opaque_script: bool = False,
    mutation_count: int = 0,
    final_step: bool = False,
) -> EvidenceDecision:
    """Decide what verification this edit requires.

    Args:
        operations: Structured operation names, when the server knows them.
        opaque_script: True for raw ExtendScript, whose effects the server
            cannot classify. Such a call falls back to the backlog rule rather
            than pretending to know what it did.
        mutation_count: Mutations recorded against this document.
        final_step: The caller says this completes the deliverable.

    Asking for a preview is deliberately not an input here. A caller who wants
    to see the page is not thereby obliged to confirm a list of checks, and a
    caller who declines one does not escape an obligation the edit created.
    Both are decisions about *capture*, made by the caller; this function
    decides only whether verification is owed.
    """
    reasons: list = []

    for task in operations or ():
        reason = classify_operation(task)
        if reason is not None and reason not in reasons:
            reasons.append(reason)

    if operations and len(operations) >= LARGE_BATCH_OPERATIONS:
        if EvidenceReason.LARGE_BATCH not in reasons:
            reasons.append(EvidenceReason.LARGE_BATCH)

    backlog_due = mutation_count > 0 and mutation_count % UNVERIFIED_BACKLOG == 0
    if opaque_script and backlog_due:
        reasons.append(EvidenceReason.OPAQUE_SCRIPT)
    elif backlog_due and not reasons:
        reasons.append(EvidenceReason.UNVERIFIED_BACKLOG)

    # Final delivery is appended last so it reads last, and always applies.
    if final_step and EvidenceReason.FINAL_DELIVERY not in reasons:
        reasons.append(EvidenceReason.FINAL_DELIVERY)

    if not reasons:
        return NO_EVIDENCE
    return EvidenceDecision(
        required=True, mode=_mode_for(reasons), reasons=tuple(reasons)
    )


def escalate_for_geometry(
    decision: EvidenceDecision, guard_telemetry: Optional[dict],
) -> EvidenceDecision:
    """Add a suspicious-geometry reason when the guard found one.

    Reuses the occlusion guard's own tiers rather than inventing a second set
    of numbers: a cover ratio at or above the suspicion tier, or a visible
    item with no artboard overlap at all.
    """
    if not isinstance(guard_telemetry, dict):
        return decision
    suspicious = False
    for item in guard_telemetry.get("topLayerItems") or ():
        if not isinstance(item, dict) or item.get("hidden"):
            continue
        cover = item.get("coverRatio")
        if isinstance(cover, bool) or not isinstance(cover, (int, float)):
            continue
        if cover >= SUSPICION_THRESHOLD or cover == 0:
            suspicious = True
            break
    if not suspicious:
        return decision
    if EvidenceReason.SUSPICIOUS_GEOMETRY in decision.reasons:
        return decision

    reasons = tuple(decision.reasons) + (EvidenceReason.SUSPICIOUS_GEOMETRY,)
    return EvidenceDecision(
        required=True, mode=_mode_for(reasons), reasons=reasons,
        crop=decision.crop,
    )


def limit_to_available(
    decision: EvidenceDecision, available: Sequence[str],
) -> EvidenceDecision:
    """Narrow a decision to evidence the calling tool can actually produce.

    Only ``illustrator_observe`` can return a raw and an annotated frame from
    one coordinated capture. The execution tools emit a single preview, so a
    decision asking for both is recorded as the one they can supply. Doing the
    downgrade here keeps the requirement text honest about what is attached.
    """
    if not decision.required or decision.mode in available:
        return decision
    if decision.mode == "both":
        for preferred in ("annotated", "raw"):
            if preferred in available:
                return EvidenceDecision(
                    required=True, mode=preferred, reasons=decision.reasons,
                    crop=decision.crop,
                )
    fallback = available[0] if available else None
    return EvidenceDecision(
        required=True, mode=fallback, reasons=decision.reasons,
        crop=decision.crop,
    )


def requirement_text(decision: EvidenceDecision, *, evidence_supplied: bool) -> str:
    """The requirement as one compact block, for clients that read only text.

    It states an obligation and its subject. It does not order the caller to
    stop or to withhold tool calls: a server cannot enforce that, and the
    previous attempt to do so was an instruction aimed at another model.
    """
    lines = [
        "VERIFICATION REQUIRED - " + ", ".join(
            r.value.replace("_", " ") for r in decision.reasons
        )
    ]
    if evidence_supplied:
        lines.append("Evidence: " + _evidence_label(decision.mode) + " (above).")
    else:
        lines.append(
            "Evidence: NOT AVAILABLE for this edit. Capture it with "
            "illustrator_observe before relying on the result."
        )
    lines.append("Confirm:")
    lines.extend("  - " + check for check in decision.checks)
    lines.append(
        "Status: unconfirmed. This is the caller's judgement, and is separate "
        "from the preservation check reported under verification."
    )
    return "\n".join(lines)


def _evidence_label(mode: Optional[str]) -> str:
    return {
        "annotated": "annotated preview, numbered for targeting",
        "raw": "raw preview, unannotated for judging appearance",
        "both": "raw preview for appearance, annotated preview for targeting",
    }.get(mode or "", "preview")


def stamp_supplied(
    envelope: str, decision: EvidenceDecision, *, supplied: bool,
) -> str:
    """Re-stamp a serialised envelope with whether evidence was attached.

    Both execution tools serialise their envelope before they capture the
    preview, so updating the diagnostics dict afterwards changes nothing the
    caller sees. Live testing caught the result of that: a requirement
    reporting evidence missing while the annotated image sat beside it in the
    same response, which tells the caller to go and fetch what they already
    have. Patching the built string keeps the correction next to the branch
    that knows the answer, rather than rebuilding an envelope from arguments
    assembled three branches earlier.

    Returns the envelope unchanged if it is not a JSON object, since a
    diagnostic detail is never worth failing a result over.
    """
    import json as _json

    try:
        data = _json.loads(envelope)
    except (TypeError, ValueError):
        return envelope
    if not isinstance(data, dict) or not isinstance(data.get("diagnostics"), dict):
        return envelope
    data["diagnostics"]["evidence"] = diagnostics(
        decision, evidence_supplied=supplied
    )
    return _json.dumps(data)


def diagnostics(decision: EvidenceDecision, *, evidence_supplied: bool) -> dict:
    """The decision as structured diagnostics, for clients that read those."""
    return {
        "required": decision.required,
        "reasons": list(decision.reason_values),
        "mode": decision.mode,
        "crop": list(decision.crop) if decision.crop else None,
        "evidenceSupplied": evidence_supplied,
        "confirmed": False,
        "checks": list(decision.checks),
    }
