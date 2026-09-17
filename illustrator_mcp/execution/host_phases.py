"""Managed host-phase evidence for multi-call jobs; never a workflow replay."""
import contextvars
import json
import uuid
from string import Template

active_phases = contextvars.ContextVar("logical_host_phases", default=None)


def begin(job):
    return active_phases.set({"job": job, "owner": uuid.uuid4().hex, "phase": 0})


def wrap_phase(script, command):
    state = active_phases.get()
    if state is None:
        return script
    state["phase"] += 1
    job, phase = state["job"], state["phase"]
    from illustrator_mcp.execution.document_intent import active as active_intent
    intent = active_intent.get()
    target = job.document_target
    if intent and (intent["lifecycle"] or intent["read"] and not intent["explicit"]):
        target = None
    target_js = json.dumps(target) if intent else "mcpDocBind().token"
    spec = json.dumps({"jobId": job.job_id, "digest": job.digest, "phase": phase,
        "context": {"owner": state["owner"], "tool": job.label}})
    # All injected helper declarations remain outside the eval. Eval preserves
    # the last-expression return convention and rejects bare top-level return.
    return Template("""(function () {
    var spec = $spec;
    if (!mcpRuntimeState().present) {
        mcpRuntimeInit({protocolVersion: "3.0", force: false, capabilities: {hostJobLedger: true}});
    }
    var begin = mcpRuntimeBeginWork(spec);
    if (!begin.ok) return JSON.stringify({__mcpPhaseRefusal: {
        owner: spec.context.owner, status: begin.status, record: begin.record || null}});
    var context = begin.record.context;
    var value, status = "failed", effects = _mcpCopyEffects(begin.record.effects), phaseResult = null, phaseError = null;
    var known = $effects;
    var effectKinds = ["created", "modified", "deleted"];
    for (var ki = 0; ki < effectKinds.length; ki++) {
        var kind = effectKinds[ki], seen = {}, merged = [];
        var all = effects[kind].concat(known[kind] || []);
        for (var ai = 0; ai < all.length; ai++) {
            if (!seen["id:" + all[ai]]) {seen["id:" + all[ai]] = true; merged.push(all[ai]);}
        }
        effects[kind] = merged;
    }
    try {
        if (spec.phase === 1) context.documentToken = $target;
        else if (context.documentToken && !mcpDocValidate(context.documentToken).ok) {
            throw new Error("DOCUMENT_MISMATCH[" + $guard_nonce + "]: " + JSON.stringify({
                expectedToken: context.documentToken, active: mcpDocBind(),
                validation: mcpDocValidate(context.documentToken)}));
        }
        value = (function () { return eval($script); })();
        status = "succeeded";
        return value;
    } catch (executionError) {
        phaseError = String(executionError);
        throw executionError;
    } finally {
        try {
            var serialized = JSON.stringify(value);
            phaseResult = typeof serialized === "string" ? serialized.substring(0, 65536) : null;
            if (spec.context.tool !== "illustrator_execute_script") {
                var domain = typeof value === "string" ? JSON.parse(value) : value;
                if (domain && domain.data) domain = domain.data;
                if (domain && domain.ok !== false && typeof domain.id === "string" &&
                        (spec.context.tool === "illustrator_place_file" || spec.context.tool === "illustrator_path_import_svg")) {
                    effects.created.push(domain.id);
                }
                if (domain && domain.effects) {
                    var kinds = ["created", "modified", "deleted"];
                    for (var k = 0; k < kinds.length; k++) {
                        var ids = domain.effects[kinds[k]] || [];
                        for (var i = 0; i < ids.length; i++) {
                            if (typeof ids[i] === "string") effects[kinds[k]].push(ids[i]);
                        }
                    }
                }
            }
        } catch (serializationError) { phaseResult = null; }
        mcpRuntimeCompleteWork(spec.jobId, {status: status, phase: spec.phase,
            phaseName: $command, context: context, effects: effects,
            errors: phaseError ? [{message: phaseError}] : [],
            result: {phase: spec.phase, command: $command, hostOnly: true,
                     returned: typeof value !== "undefined", phaseResult: phaseResult,
                     resultTruncated: !!(serialized && serialized.length > 65536)}});
    }
})()""").substitute(spec=spec, script=json.dumps(script), command=json.dumps(command), effects=json.dumps(job.effects), target=target_js, guard_nonce=json.dumps(intent["guard_nonce"] if intent else "legacy"))


def interpret_phase_refusal(response):
    """Retain prior host evidence when a fresh Python owner is refused."""
    from illustrator_mcp.utils.response import try_parse_json
    from illustrator_mcp.execution import get_coordinator, JobConflictError
    state = active_phases.get()
    if state is None:
        return response
    value = try_parse_json(response.get("result"))
    if isinstance(value, dict) and value.get("ok") is True and "data" in value:
        value = try_parse_json(value["data"])
    refusal = value.get("__mcpPhaseRefusal") if isinstance(value, dict) else None
    if not isinstance(refusal, dict) or refusal.get("owner") != state["owner"]:
        return response
    coordinator, job = get_coordinator(), state["job"]
    record = refusal.get("record")
    if isinstance(record, dict) and record.get("jobId") == job.job_id:
        try:
            coordinator.mirror_host_record(record)
        except JobConflictError:
            return {**response, "error": "Host job ID conflicts with a different retained intent", "execution": "failed"}
    else:
        coordinator.mark_unknown(job.job_id, "Host phase history is missing; do not resume automatically.")
        # This direct refusal proves no host script is still running.
        job.awaiting_host = False
    return {**response, "error": "Logical job host phase refused: " + str(refusal.get("status")),
            "execution": "unknown", "jobId": job.job_id}
