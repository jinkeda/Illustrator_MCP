"""Where the connection to Illustrator stands, and what to do about it.

Every other tool in this server is useless until a chain of four things is up:
this process, a local WebSocket server, a CEP panel connected to it, and
Illustrator itself with a document open. Until now that chain could only be
inspected by calling some unrelated tool and reading the error code it
happened to return, which says what failed for that call but not where the
chain is broken or how to repair it.

Two design rules follow from what this tool is for.

It must answer when Illustrator is absent. That is the case it exists to
diagnose, so it reads process-local state directly and never routes through
the bridge it is reporting on. The optional probe is the one exception, and it
is skipped when the panel is already known to be down.

It must not start or reconnect the server as a side effect. Reading ``runtime.bridge``
directly rather than through the accessor matters here: the accessor starts
the server when it finds none, which would make "the server is not running"
unobservable by asking. Explicit probes participate in local wait retirement
and readiness reconciliation; they never unlock unknown mutations.
"""

import logging
from typing import Optional

from pydantic import Field

from mcp.types import CallToolResult

from illustrator_mcp.config import config
from illustrator_mcp.connection_helpers import (
    ILLUSTRATOR_RECOVERY_STEPS, PANEL_RECOVERY_STEPS, SERVER_RECOVERY_STEPS,
)
from illustrator_mcp.execution import get_coordinator
from illustrator_mcp.results import (
    CanonicalResult, ExecutionStatus, Verification, VerificationStatus,
    build_call_result,
)
from illustrator_mcp.runtime import get_runtime
from illustrator_mcp.shared import mcp
from illustrator_mcp.tools.base import TOOL_ANNOTATIONS, ToolInputBase
from illustrator_mcp.tools.cadence import get_active_cadence_document
from illustrator_mcp.utils.response import JsxPayloadError, require_jsx_payload

logger = logging.getLogger("illustrator_mcp")

#: The layers, outermost first. The first one that is not "ok" is what the
#: caller has to fix; everything past it is reported "unknown" rather than
#: guessed at, because a broken link makes the ones behind it unobservable.
_LAYERS = ("server", "panel", "illustrator", "document")

_PROBE_SCRIPT = """
(function () {
    var docs = app.documents.length;
    return JSON.stringify({
        app: app.name,
        version: app.version,
        documentCount: docs,
        activeDocument: docs > 0 ? app.activeDocument.name : null
    });
})()
"""


class ConnectionStatusInput(ToolInputBase):
    """Options for a connection status report."""

    probe: bool = Field(
        default=False,
        description=(
            "Round-trip a tiny read-only script to confirm Illustrator itself "
            "answers, and to read the live document name. Off by default so "
            "the report stays instant and cannot block on a busy panel."
        ),
    )
    timeout: float = Field(
        default=5.0, gt=0, le=30,
        description="Seconds to wait for the probe. Ignored when probe=false.",
    )


def _state_name(state) -> str:
    """The bridge's connection state as a readable name.

    ``get_connection_info`` reports ``ConnectionState.value``, and that enum
    uses ``auto()``, so the value is an integer. A report whose whole purpose
    is legibility should not hand back "state: 3", and comparing that integer
    against the string "ERROR" would never have matched.
    """
    from illustrator_mcp.websocket_bridge import ConnectionState

    if isinstance(state, ConnectionState):
        return state.name
    try:
        return ConnectionState(state).name
    except (ValueError, TypeError):
        return str(state)


def _server_layer() -> dict:
    """The local WebSocket server, read without starting one."""
    bridge = get_runtime().bridge
    if bridge is None:
        return {
            "status": "not_started",
            "port": config.ws_port,
            "detail": (
                "No WebSocket server has been started in this process. It "
                "starts during MCP initialization. Restart the integration "
                "through its owning client and check its startup logs."
            ),
        }
    info = bridge.get_connection_info()
    running = info.get("is_running", False)
    state = _state_name(info.get("state"))
    healthy = running and state == "LISTENING"
    return {
        "status": "ok" if healthy else "down",
        "host": info.get("host", config.ws_host),
        "startup_error": info.get("startup_error"),
        "port": info.get("port", config.ws_port),
        "endpoint": info.get("endpoint", config.ws_url),
        "requested_endpoint": info.get("requested_endpoint", config.ws_url),
        "bound_endpoint": info.get("bound_endpoint"),
        "state": state,
        "detail": (
            None if healthy
            else (f"Listener {info.get('host', config.ws_host)}:{info.get('port', config.ws_port)} failed: {info['startup_error']}. Another process may own the endpoint." if info.get("startup_error") else f"The bridge is not serving requests (state {state}).")
        ),
    }


def _panel_layer(server_ok: bool) -> dict:
    """The CEP panel's socket and heartbeat."""
    if not server_ok:
        return {"status": "unknown",
                "detail": "Cannot tell: the local server is not running."}
    bridge = get_runtime().bridge
    info = bridge.get_connection_info()
    health = bridge.get_panel_health()
    connected = info.get("is_connected", False)
    layer = {
        "status": "ok" if connected else "down",
        "client": info.get("client_info"),
        "lastHeartbeatAgoMs": health.get("last_heartbeat_ago_ms"),
        "busy": health.get("busy"),
        "activeRequestId": health.get("active_request_id"),
        "heartbeatStale": health.get("stale"),
        "detail": None,
    }
    if not connected:
        layer["detail"] = "The panel is not connected to this server."
    elif health.get("stale"):
        # Connected but silent: the socket is open and nothing is coming back.
        layer["status"] = "degraded"
        layer["detail"] = (
            "The socket is open but no heartbeat has arrived within "
            f"{config.watchdog_stale_threshold:g}s. The panel may be frozen."
        )
    elif health.get("busy"):
        layer["detail"] = (
            "The panel is executing a request. This is not a fault; calls "
            "will queue behind it."
        )
    return layer


async def _probe(timeout: float) -> tuple:
    """Ask Illustrator to identify itself. Returns (illustrator, document)."""
    from illustrator_mcp.proxy_client import execute_script_with_context

    try:
        from illustrator_mcp.execution.trusted_probe import active
        authority = active.set(True)
        try:
            response = await execute_script_with_context(
                script=_PROBE_SCRIPT, command_type="connection_probe",
                tool_name="illustrator_connection_status", timeout=timeout)
        finally:
            active.reset(authority)
    except Exception as exc:  # a probe must never fail the report
        return ({"status": "unreachable", "detail": str(exc)},
                {"status": "unknown", "detail": "Illustrator did not answer."})

    if isinstance(response, dict) and response.get("error"):
        return ({"status": "unreachable", "detail": str(response["error"])},
                {"status": "unknown", "detail": "Illustrator did not answer."})

    try:
        payload = require_jsx_payload(
            response, context="connection_probe",
            required_keys=("app", "documentCount"),
        )
    except JsxPayloadError as exc:
        return ({"status": "unknown", "detail": f"Unreadable reply: {exc}"},
                {"status": "unknown", "detail": "Illustrator did not answer."})

    illustrator = {
        "status": "ok",
        "app": payload.get("app"),
        "version": payload.get("version"),
        "detail": None,
    }
    name = payload.get("activeDocument")
    document = {
        "status": "ok" if name else "none_open",
        "name": name,
        "openCount": payload.get("documentCount"),
        "source": "probe",
        "detail": None if name else "Illustrator is running with no document open.",
    }
    return illustrator, document


def _document_from_local_state() -> dict:
    """The document name the host reported on its last reply.

    This is what the mutation counter is keyed by, so it is the same answer
    the rest of the server is already acting on. It is last-known, not live.
    """
    name = get_active_cadence_document()
    known = bool(name) and not name.startswith("<")
    return {
        "status": "last_known" if known else "unknown",
        "name": name if known else None,
        "source": "last host reply",
        "detail": (
            None if known else
            "No document has been named by the host in this session. "
            "Pass probe=true to ask Illustrator directly."
        ),
    }


def _recovery_for(blocked_at: Optional[str], layers: dict) -> list:
    """The steps that address the first broken link, and only those."""
    if blocked_at is None:
        return []
    if blocked_at == "server":
        return list(SERVER_RECOVERY_STEPS)
    if blocked_at == "panel":
        if layers["panel"].get("status") == "degraded":
            return [
                "The socket is open but the panel has stopped responding.",
                *PANEL_RECOVERY_STEPS,
            ]
        return list(PANEL_RECOVERY_STEPS)
    if blocked_at == "illustrator":
        return list(ILLUSTRATOR_RECOVERY_STEPS)
    if blocked_at == "document":
        return ["Create or open a document with illustrator_document "
                "before running edits."]
    return []


_NAME = "illustrator_connection_status"


@mcp.tool(name=_NAME, annotations=TOOL_ANNOTATIONS[_NAME])
async def illustrator_connection_status(
    params: ConnectionStatusInput,
) -> CallToolResult:
    """Report whether Illustrator is reachable, and what to fix if not.

    CONTRACT: readOnly=True, destructive=False, idempotent=True, openWorld=False

    WHEN TO USE:
      - A call failed with a connection error and you need to know which link broke
      - Before a session, to confirm the panel is connected
      - To check whether the panel is busy rather than gone

    KEY CONCEPTS:
      Four layers, outermost first: this server's WebSocket listener, the CEP
      panel's socket, Illustrator itself, and the active document. The first
      one that is not ok is reported as blockedAt, and the recovery steps
      address that link only. Layers behind a broken one read 'unknown'
      rather than being guessed at.

    OPTIONS:
      probe=false (default) — instant, reads process-local state only
      probe=true — also round-trips a tiny read-only script to Illustrator

    EXAMPLES:
      Instant report, no host call:
        {"params": {}}
      Also confirm Illustrator itself answers:
        {"params": {"probe": true}}

    RESULT:
      data.ready is true only when every layer is up. data.blockedAt names the
      first broken layer, or is null. data.recovery lists the steps for it.
      execution reports whether this report was produced, never whether the
      connection is healthy — a successful report of a dead panel is a success.

    NOTES:
      - Never starts the server and never reconnects
      - Trusted probe timeouts retire local waits and require a readiness fence;
        blocking names the retained job and exact job_status call
      - Answers normally when Illustrator is closed, which is the point
      - Without probe, the document name is last-known, not live
    """
    layers = {}
    layers["server"] = _server_layer()
    server_ok = layers["server"]["status"] == "ok"
    layers["panel"] = _panel_layer(server_ok)
    panel_usable = layers["panel"]["status"] in ("ok", "degraded")

    if not params.probe:
        layers["illustrator"] = {
            "status": "not_probed",
            "detail": "Pass probe=true to confirm Illustrator answers.",
        }
        layers["document"] = _document_from_local_state()
    elif not panel_usable:
        layers["illustrator"] = {
            "status": "unknown",
            "detail": "Cannot probe: the panel is not connected.",
        }
        layers["document"] = _document_from_local_state()
    else:
        layers["illustrator"], layers["document"] = await _probe(params.timeout)

    # The first layer that is neither ok nor merely unprobed is the blocker.
    blocked_at = None
    for name in _LAYERS:
        status = layers[name].get("status")
        if status in ("ok", "not_probed", "last_known"):
            continue
        blocked_at = name
        break

    ready = blocked_at is None
    coordinator = get_coordinator()
    snap = coordinator.snapshot()
    unresolved = [
        r.get("jobId") for r in snap.get("records", [])
        if r.get("awaitingHost")
    ]

    data = {
        "ready": ready,
        "blockedAt": blocked_at,
        "layers": layers,
        "execution": {
            "activeJob": snap.get("activeJob"),
            "waiting": snap.get("waiting"),
            "connectionGeneration": snap.get("connectionGeneration"),
            "unresolvedJobs": unresolved,
        },
        "recovery": _recovery_for(blocked_at, layers),
        "probed": params.probe,
    }
    from illustrator_mcp.execution.trusted_probe import blocking
    data["blocking"] = blocking(coordinator)
    if data["blocking"]:
        data["blocking"]["panelBusy"] = layers["panel"].get("busy")
        data["ready"] = ready = False
        data["blockedAt"] = blocked_at = "probe_fence"
    elif unresolved:
        record = coordinator.get(unresolved[0])
        data["blocking"] = {"jobId": record.job_id, "trustedProbe": record.trusted_probe,
            "requestToken": record.active_request_token,
            "awaitingHost": record.awaiting_host, "probeFenceRequired": False,
            "panelBusy": layers["panel"].get("busy"),
            "nextStep": {"tool": "illustrator_job_status", "params": {"jobId": record.job_id}}}
        data["ready"] = ready = False
        data["blockedAt"] = blocked_at = "unresolved_job"
    if data["blocking"]:
        import time
        record = coordinator.get(data["blocking"]["jobId"])
        data["blocking"]["ageSeconds"] = time.monotonic() - record.created_at if record else None

    # The report succeeded even when what it reports is a dead connection.
    # Collapsing those two would make a diagnostic unusable in exactly the
    # situation it exists for.
    return build_call_result(CanonicalResult(
        execution=ExecutionStatus.SUCCEEDED,
        tool=_NAME,
        data=data,
        verification=Verification(
            status=VerificationStatus.PASSED if ready else VerificationStatus.FAILED,
            scope="connection_chain",
            detail=(
                "Server, panel, Illustrator and document are all reachable."
                if ready else
                f"First unavailable layer: {blocked_at}."
            ),
        ),
        warnings=(
            [] if ready else
            [f"Illustrator is not reachable: {blocked_at} is unavailable."]
        ),
    ))
