"""Private producer authority; never inferred from caller script/command/read_only."""
from contextvars import ContextVar

active = ContextVar("internal_trusted_probe", default=False)


async def readiness(coordinator):
    """One bounded attempt within the caller's reservation, never queued with work."""
    if coordinator.probe_fence is None or active.get():
        return None
    from illustrator_mcp.execution.document_intent import active as active_intent
    intent = active_intent.get()
    if intent is not None and intent.get("fence_attempted"):
        return {"error": "PROBE_FENCE_REQUIRED: this call already attempted readiness; ordinary dispatch refused.",
                "execution": "failed", "dispatched": False, "fence": blocking(coordinator)}
    if intent is not None:
        intent["fence_attempted"] = True
    from illustrator_mcp.proxy_client import _execute_via_bridge
    from illustrator_mcp.tools.connection import _PROBE_SCRIPT
    authority = active.set(True)
    try:
        response = await _execute_via_bridge(script=_PROBE_SCRIPT, timeout=5.0)
    finally:
        active.reset(authority)
    if coordinator.probe_fence is not None:
        return {"error": "PROBE_FENCE_REQUIRED: readiness is unproven; ordinary call not dispatched. Lost-callback panel-reload recovery requires measured host support.",
                "execution": "failed", "dispatched": False, "fence": blocking(coordinator),
                "readinessAttempt": response}
    return None


def blocking(coordinator):
    fence = coordinator.probe_fence
    if fence is None:
        return None
    return {**fence, "probeFenceRequired": True,
            "nextStep": {"tool": "illustrator_job_status", "params": {"jobId": fence["jobId"]}},
            "detail": "Readiness after lost callback/panel reload is unproven. A modal dialog may delay the host; this is a hypothesis, not a diagnosis."}
