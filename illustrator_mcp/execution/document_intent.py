"""Pinned document intent shared by public document-bound calls (SR03)."""
from contextvars import ContextVar
import json
import uuid

active = ContextVar("document_intent", default=None)
READ_TOOLS = {"illustrator_observe", "illustrator_get_document", "illustrator_query_items", "illustrator_preflight_check"}


def begin(tool, params, job=None):
    from illustrator_mcp.runtime import get_runtime
    explicit = getattr(params, "expected_document_token", None)
    lifecycle = tool == "illustrator_document" and params.action in ("create", "open", "activate", "list")
    read = tool in READ_TOOLS or bool(getattr(params, "read_only", False))
    return active.set({"target": explicit or get_runtime().document_pin,
        "guard_nonce": uuid.uuid4().hex,
        "pin_transition": tool == "illustrator_document" and params.action in ("create", "open", "activate"),
        "explicit": bool(explicit), "read": read, "lifecycle": lifecycle,
        "tool": tool, "job": job, "prepared": False, "observed": None})


async def prepare():
    state = active.get()
    if state is None or state["prepared"]:
        return None
    from illustrator_mcp.proxy_client import _execute_via_bridge
    from illustrator_mcp.libraries import inject_libraries
    from illustrator_mcp.utils.response import require_jsx_payload, JsxPayloadError
    from illustrator_mcp.runtime import get_runtime
    from illustrator_mcp.execution import request_digest
    response = await _execute_via_bridge(
        script=inject_libraries("JSON.stringify({documentCount:app.documents.length, active:mcpDocBind()})", ["doc_session"]), timeout=10.0)
    try:
        facts = require_jsx_payload(response, required_keys=("documentCount", "active"))
    except JsxPayloadError:
        return response if response.get("error") else {"error": "Document intent could not be established", "execution": "failed", "dispatched": False}
    observed = facts["active"]
    state["observed"] = observed
    runtime = get_runtime()
    if not state["target"] and not state["lifecycle"] and facts["documentCount"] == 1:
        # Never substitute a new pin for intent already captured by this call.
        state["target"] = observed.get("token")
        if runtime.document_pin is None:
            runtime.document_pin = state["target"]
    state["prepared"] = True
    job = state["job"]
    if job is not None:
        job.document_target = state["target"]
        job.input_digest = job.input_digest or job.digest
        job.digest = request_digest({"intent": job.input_digest, "documentToken": state["target"]})
    return None


def guard(script):
    state = active.get()
    if state is None:
        return script
    if state["lifecycle"]:
        return "(function(){var value=eval(" + json.dumps(script) + "); return JSON.stringify({__mcpLifecycleResult:value, binding:mcpDocBind()});})()"
    if state["read"] and not state["explicit"]:
        return "(function(){var binding=mcpDocBind();var value=eval(" + json.dumps(script) + "); return JSON.stringify({__mcpLifecycleResult:value, binding:binding});})()"
    target = json.dumps(state["target"])
    # Validate inside the SAME evaluation as the action. No auto-activation.
    prefix = ""
    if state["tool"] == "illustrator_execute_task" and state["job"] is not None:
        prefix = "var __mcpEffectiveDigest = " + json.dumps(state["job"].digest) + ";\n"
    return (prefix + "var __mcpTargetCheck = mcpDocValidate(" + target + ");\n"
            "if (!__mcpTargetCheck.ok) throw new Error('DOCUMENT_MISMATCH[" + state["guard_nonce"] + "]: ' + JSON.stringify({expectedToken:" + target + ",active:mcpDocBind(),validation:__mcpTargetCheck}));\n" + script)


def accept_lifecycle(response):
    if response.get("error") or response.get("execution") == "unknown":
        return response
    state = active.get()
    if state is None or not (state["lifecycle"] or state["read"] and not state["explicit"]):
        return response
    from illustrator_mcp.utils.response import try_parse_json
    from illustrator_mcp.runtime import get_runtime
    value = try_parse_json(response.get("result"))
    if isinstance(value, dict) and value.get("ok") is True and "data" in value:
        value = try_parse_json(value["data"])
    if not isinstance(value, dict) or "__mcpLifecycleResult" not in value:
        return response
    raw = value["__mcpLifecycleResult"]
    result = try_parse_json(raw)
    state["observed"] = value.get("binding") or {}
    if isinstance(result, dict) and result.get("ok") is True:
        binding = value.get("binding") or {}
        if state.get("pin_transition"):
            get_runtime().document_pin = binding.get("token")
            state["target"] = binding.get("token")
        state["observed"] = binding
    return {**response, "result": raw}


def annotate(canonical):
    state = active.get()
    if state is None:
        return
    canonical.diagnostics["documentIntent"] = {"effectiveTarget": state["target"], "observed": state["observed"]}
    observed = state["observed"] or {}
    if state["read"] and not state["explicit"] and state["target"] and observed.get("token") != state["target"]:
        canonical.warnings.append("DOCUMENT_MISMATCH: exploratory read observed " + str(observed.get("name")) + " (" + str(observed.get("token")) + ") while the pin remains " + state["target"])
    if observed.get("token"):
        from illustrator_mcp.document_session import editing_scope_from_host, editing_scope_warning
        context = observed.get("context")
        scope = editing_scope_from_host(context.get("editingScope") if isinstance(context, dict) else None)
        canonical.diagnostics["editingScope"] = {
            "documentToken": observed["token"], "observation": scope,
            "timing": "binding_observation",
        }
        warning = editing_scope_warning(scope)
        if warning and warning not in canonical.warnings:
            canonical.warnings.append(warning)
    marker = "DOCUMENT_MISMATCH[" + state["guard_nonce"] + "]: "
    if canonical.error and marker in canonical.error.message:
        canonical.error.code = "DOCUMENT_MISMATCH"
        try:
            detail = canonical.error.message.split(marker, 1)[1]
            canonical.diagnostics["documentMismatch"] = json.JSONDecoder().raw_decode(detail)[0]
        except (ValueError, IndexError):
            pass
        canonical.error.message = canonical.error.message.replace(marker, "DOCUMENT_MISMATCH: ")
        from illustrator_mcp.execution.host_phases import active_phases
        phases = active_phases.get()
        if phases and phases["phase"] == 1:
            canonical.effects.complete = True
        validation = canonical.diagnostics.get("documentMismatch", {}).get("validation", {})
        correction = ({"action": "activate", "expected_document_token": state["target"]}
                      if state["target"] and validation.get("status") == "not_active"
                      else {"action": "list"})
        canonical.diagnostics["nextStep"] = {"tool": "illustrator_document", "params": correction}


def observation_context(fn):
    """Observation already owns its reservation; add intent without another slot."""
    import functools
    @functools.wraps(fn)
    async def wrapped(params):
        from illustrator_mcp.results import CanonicalResult, build_call_result
        token = begin("illustrator_observe", params)
        try:
            result = await fn(params)
            canonical = CanonicalResult.model_validate(result.structuredContent)
            annotate(canonical)
            updated = build_call_result(canonical, list(result.content[2:]))
            # Preserve the originating result identity used by journal retention.
            result.content = updated.content
            result.structuredContent = updated.structuredContent
            result.isError = updated.isError
            return result
        finally:
            active.reset(token)
    return wrapped
