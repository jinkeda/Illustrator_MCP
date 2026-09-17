"""Document session binding and coordinate context (T13).

A job says "operate on THIS document" once, and every later phase of that job
checks the binding still holds before it mutates anything.

The identity is an opaque token bound host-side to a live document
*reference*, not to a name. Measured on Illustrator 30.7.0 (see
``docs/HOST_PERSISTENCE_FINDINGS.md`` and the T13 probes):

===============================  ==========================================
``ref === app.activeDocument``   works — strict identity comparison
another document becomes active  ref stays readable; comparison returns False
``doc.saveAs(...)`` renames it   name changes, **reference identity does not**
the document is closed           reading through the ref throws
                                 ``"Object is invalid"`` — cleanly detectable
===============================  ==========================================

So a token survives a rename and a focus change, and invalidates itself on
close. That is the contract T13 asks for, and none of it is available from a
document name.

**This is not a sandbox.** A token identifies a document; it does not stop a
raw script reaching another one. What it provides is the ability to *detect*
that the document a job was bound to is no longer the one in front of it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: Library providing the host-side helpers.
DOC_SESSION_LIBRARY = "doc_session"


def editing_scope_from_host(data: Any) -> Dict[str, Any]:
    """Preserve evidence without promoting missing or malformed scope to whole."""
    scope = dict(data) if isinstance(data, dict) else {}
    if scope.get("kind") not in ("whole_document", "isolated", "unknown"):
        scope["kind"] = "unknown"
    scope.setdefault("qualification", "unqualified")
    scope.setdefault("rootIdentity", None)
    return scope


def editing_scope_warning(scope: Dict[str, Any]) -> Optional[str]:
    kind = scope.get("kind", "unknown")
    if kind == "whole_document":
        return None
    return (
        "EDITING_SCOPE_" + ("ISOLATED" if kind == "isolated" else "UNKNOWN")
        + ": " + ("Isolation was observed." if kind == "isolated" else "Editing scope is not established.")
        + " Document-wide lookups may be incomplete. Check the Illustrator editing mode "
        "and use smaller targeted reads. This observation does not enforce scope."
    )


class DocumentBindingStatus(str, Enum):
    """Whether a document binding still holds."""

    VALID = "valid"
    """Bound document is open and active. Safe to mutate."""

    VALID_INACTIVE = "valid_inactive"
    """Open but not the active document. Reads may be fine; a mutation that
    assumes the active document must not proceed."""

    NOT_ACTIVE = "not_active"
    """Open, but something else is active and the caller required active."""

    CLOSED = "closed"
    """The bound document was closed. A reopened document is a different
    document — the token is void, never silently re-pointed."""

    UNKNOWN_TOKEN = "unknown_token"
    """Never issued by this runtime, or the runtime was reset."""

    NO_DOCUMENT = "no_document"
    """Nothing is open. A legitimate state for an app-level request."""

    UNAVAILABLE = "unavailable"
    """The host could not be reached or gave no usable answer."""

    def may_mutate(self) -> bool:
        """Only a live, active, verified binding may be mutated through."""
        return self is DocumentBindingStatus.VALID


@dataclass(frozen=True)
class CoordinateContext:
    """The coordinate frame a job is working in, stated explicitly.

    Two conventions coexist in this codebase and disagree on any artboard
    whose origin is not (0,0): placement uses raw document coordinates
    (``left = x, top = -y``) while the element/geometry helpers offset by the
    active artboard. The same apparent input lands somewhere different on a
    second artboard.

    Rather than silently picking one, this carries the artboard rect *and* the
    offset needed to convert, so callers can agree on what a coordinate means:

        x_doc = artboard_offset[0] + x_soc
        y_doc = artboard_offset[1] - y_soc
    """

    units: str = "pt"
    y_axis: str = "down"
    origin: str = "artboard"
    artboard_index: Optional[int] = None
    artboard_name: Optional[str] = None
    artboard_rect: Optional[list] = None
    artboard_offset: Optional[tuple] = None
    artboard_size: Optional[Dict[str, float]] = None
    document_size: Optional[Dict[str, float]] = None
    editing_scope: Dict[str, Any] = field(default_factory=lambda: editing_scope_from_host(None))

    @classmethod
    def from_host(cls, data: Optional[Dict[str, Any]]) -> "CoordinateContext":
        data = data or {}
        offset = data.get("artboardOffset")
        return cls(
            units=data.get("units", "pt"),
            y_axis=data.get("yAxis", "down"),
            origin=data.get("origin", "artboard"),
            artboard_index=data.get("artboardIndex"),
            artboard_name=data.get("artboardName"),
            artboard_rect=data.get("artboardRect"),
            artboard_offset=(
                (offset["x"], offset["y"]) if isinstance(offset, dict) else None
            ),
            artboard_size=data.get("artboardSize"),
            document_size=data.get("documentSize"),
            editing_scope=editing_scope_from_host(data.get("editingScope")),
        )

    def soc_to_document(self, x: float, y: float) -> tuple:
        """Artboard-relative Y-down → Illustrator document coordinates."""
        if self.artboard_offset is None:
            raise ValueError(
                "No artboard offset in this context; cannot convert "
                "coordinates without knowing the artboard origin."
            )
        return (self.artboard_offset[0] + x, self.artboard_offset[1] - y)

    def document_to_soc(self, x: float, y: float) -> tuple:
        """Illustrator document coordinates → artboard-relative Y-down."""
        if self.artboard_offset is None:
            raise ValueError(
                "No artboard offset in this context; cannot convert "
                "coordinates without knowing the artboard origin."
            )
        return (x - self.artboard_offset[0], self.artboard_offset[1] - y)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "editingScope": dict(self.editing_scope),
            "units": self.units,
            "yAxis": self.y_axis,
            "origin": self.origin,
            "artboardIndex": self.artboard_index,
            "artboardName": self.artboard_name,
            "artboardRect": self.artboard_rect,
            "artboardOffset": (
                {"x": self.artboard_offset[0], "y": self.artboard_offset[1]}
                if self.artboard_offset else None
            ),
            "artboardSize": self.artboard_size,
            "documentSize": self.document_size,
        }


@dataclass
class DocumentBinding:
    """A job's binding to one document."""

    token: Optional[str]
    status: DocumentBindingStatus
    bound_name: Optional[str] = None
    current_name: Optional[str] = None
    active_name: Optional[str] = None
    renamed: bool = False
    context: CoordinateContext = field(default_factory=CoordinateContext)
    detail: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status in (
            DocumentBindingStatus.VALID, DocumentBindingStatus.VALID_INACTIVE
        )

    def require_mutable(self) -> None:
        """Raise unless it is safe to mutate through this binding.

        Called before every mutating host phase, so a document switch fails
        *before* a write rather than redirecting it.
        """
        if not self.status.may_mutate():
            raise StaleDocumentError(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token": self.token,
            "status": self.status.value,
            "boundName": self.bound_name,
            "currentName": self.current_name,
            "activeName": self.active_name,
            "renamed": self.renamed,
            "context": self.context.to_dict(),
            "detail": self.detail,
        }


class StaleDocumentError(Exception):
    """A document binding no longer holds; the operation was not attempted."""

    def __init__(self, binding: DocumentBinding) -> None:
        self.binding = binding
        super().__init__(
            f"Document binding is {binding.status.value}: "
            f"{binding.detail or 'the bound document is no longer usable'}. "
            f"No changes were made."
        )


def _unwrap(response: Any) -> Optional[Dict[str, Any]]:
    """Same rule as T01: an unusable response establishes nothing."""
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


class DocumentSessionManager:
    """Binds jobs to documents and re-checks the binding at each phase."""

    def __init__(self, executor=None) -> None:
        self._executor = executor

    async def _run(self, script: str, label: str) -> Optional[Dict[str, Any]]:
        if self._executor is not None:
            return _unwrap(await self._executor(script=script, label=label))

        from illustrator_mcp.proxy_client import execute_script_with_context

        return _unwrap(
            await execute_script_with_context(
                script=script,
                command_type=f"doc_session:{label}",
                tool_name="doc_session",
                includes=[DOC_SESSION_LIBRARY],
            )
        )

    async def bind(self, label: str = "") -> DocumentBinding:
        """Bind the active document, minting or reusing its token."""
        data = await self._run(
            f"JSON.stringify(mcpDocBind({json.dumps({'label': label})}))", "bind"
        )
        if data is None:
            return DocumentBinding(
                token=None,
                status=DocumentBindingStatus.UNAVAILABLE,
                detail=(
                    "The host did not return a usable document binding. "
                    "Which document a job would act on is unknown."
                ),
            )

        if data.get("status") == "no_document":
            return DocumentBinding(
                token=None,
                status=DocumentBindingStatus.NO_DOCUMENT,
                detail=data.get("detail"),
            )

        return DocumentBinding(
            token=data.get("token"),
            status=DocumentBindingStatus.VALID,
            bound_name=data.get("name"),
            current_name=data.get("name"),
            context=CoordinateContext.from_host(data.get("context")),
        )

    async def validate(
        self, token: Optional[str], require_active: bool = True
    ) -> DocumentBinding:
        """Re-check a binding. Called at job start and every later phase."""
        if not token:
            return DocumentBinding(
                token=None,
                status=DocumentBindingStatus.UNKNOWN_TOKEN,
                detail="No document session token supplied.",
            )

        opts = {"requireActive": require_active}
        data = await self._run(
            f"JSON.stringify(mcpDocValidate("
            f"{json.dumps(token)}, {json.dumps(opts)}))",
            "validate",
        )
        if data is None:
            return DocumentBinding(
                token=token,
                status=DocumentBindingStatus.UNAVAILABLE,
                detail=(
                    "The host did not answer the binding check. Whether the "
                    "bound document is still current is unknown."
                ),
            )

        try:
            status = DocumentBindingStatus(data.get("status"))
        except ValueError:
            status = DocumentBindingStatus.UNAVAILABLE

        return DocumentBinding(
            token=token,
            status=status,
            bound_name=data.get("boundName"),
            current_name=data.get("currentName"),
            active_name=data.get("activeName"),
            renamed=bool(data.get("renamed")),
            context=CoordinateContext.from_host(data.get("context")),
            detail=data.get("message"),
        )

    async def context(self, token: Optional[str] = None) -> CoordinateContext:
        """Coordinate context for a token, or for the active document."""
        script = (
            f"JSON.stringify(mcpDocContext({json.dumps(token)}))" if token
            else "JSON.stringify(mcpDocContext())"
        )
        data = await self._run(script, "context")
        if data is None or not data.get("ok"):
            return CoordinateContext()
        return CoordinateContext.from_host(data.get("context"))

    async def release(self, token: str) -> bool:
        data = await self._run(
            f"JSON.stringify(mcpDocRelease({json.dumps(token)}))", "release"
        )
        return bool(data and data.get("released"))

    async def sessions(self) -> Dict[str, Any]:
        return await self._run("JSON.stringify(mcpDocSessions())", "sessions") or {
            "count": 0, "sessions": []
        }
