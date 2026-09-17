"""
VLM QA Cadence — mutation counter and checkpoint constants.

Tracks the number of mutating tool calls. The count is one input to the
evidence policy in ``tools/evidence.py``, which decides what verification an
edit requires; it is no longer a trigger in its own right.

This module is the SINGLE SOURCE OF TRUTH for cadence state.
Other tool modules import from here (never the reverse).
"""

import threading

from illustrator_mcp.occlusion_guard import (
    COVER_THRESHOLD, SUSPICION_THRESHOLD,
)

# ── VLM QA Cadence ──────────────────────────────────────────────────
# Auto-inject annotated preview every N execute_script calls.
# The counter is module-level and resets on server restart.
VLM_QA_CADENCE: int = 5

# Mutations counted before any document has been named by the host.
_UNKNOWN_DOCUMENT: str = "<unknown document>"
# CONTRACT: any new mutating tool MUST call _counter.increment().


class _MutationCounter:
    """Thread-safe mutation counters, one per document.

    This was a single process-wide integer. Editing two documents in one
    session therefore advanced ONE cadence across both: the checkpoint fired
    after five mutations spread over two documents and asked for evidence
    about whichever document happened to be active, while each document
    individually might have had only two or three unverified changes.

    Counts are keyed by document name, which is what the host can cheaply
    report on every call (see ``wrap_script``). ``_UNKNOWN_DOCUMENT`` holds
    calls made before any document has been seen; when the host then names the
    document, :meth:`reattribute` moves the count to the right key so the
    unknown bucket does not accumulate.

    Uses a lock so increment/decrement are safe under free-threaded
    Python (PEP 703 / --disable-gil).
    """

    def __init__(self) -> None:
        self._counts: dict = {}
        self._active: str = _UNKNOWN_DOCUMENT
        self._lock = threading.Lock()

    # ── The document a mutation is attributed to ────────────────────

    def set_active_document(self, name) -> None:
        """Record which document subsequent mutations belong to.

        Called with what the host reported on the last response, and with
        ``None`` when the active document is gone (closed).
        """
        with self._lock:
            self._active = name or _UNKNOWN_DOCUMENT

    @property
    def active_document(self) -> str:
        with self._lock:
            return self._active

    def reattribute(self, name) -> None:
        """Move the most recent unknown-document count onto a real document.

        The count has to be taken before the script runs, but the host only
        names the document in its reply. Rather than leave that first mutation
        on an anonymous pile, it is moved once the answer arrives.
        """
        if not name:
            return
        with self._lock:
            self._active = name
            pending = self._counts.get(_UNKNOWN_DOCUMENT, 0)
            if pending > 0 and name not in self._counts:
                self._counts[name] = pending
                self._counts[_UNKNOWN_DOCUMENT] = 0

    def forget(self, name) -> None:
        """Drop a document's cadence, e.g. when it is closed."""
        with self._lock:
            self._counts.pop(name or _UNKNOWN_DOCUMENT, None)
            if self._active == (name or _UNKNOWN_DOCUMENT):
                self._active = _UNKNOWN_DOCUMENT

    # ── The counts themselves ───────────────────────────────────────

    def increment(self, document=None) -> int:
        """Atomically increment the document's counter and return it."""
        with self._lock:
            key = document or self._active
            self._counts[key] = self._counts.get(key, 0) + 1
            return self._counts[key]

    def decrement(self, document=None) -> None:
        """Atomically decrement (floor at 0)."""
        with self._lock:
            key = document or self._active
            self._counts[key] = max(0, self._counts.get(key, 0) - 1)

    @property
    def value(self) -> int:
        """The active document's count."""
        with self._lock:
            return self._counts.get(self._active, 0)

    def value_for(self, document) -> int:
        with self._lock:
            return self._counts.get(document or _UNKNOWN_DOCUMENT, 0)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._counts)

    def reset(self) -> None:
        with self._lock:
            self._counts = {}
            self._active = _UNKNOWN_DOCUMENT


_counter = _MutationCounter()

def format_z_telemetry(telemetry: dict) -> str:
    """Format z-order telemetry as compact text for VLM checkpoint.

    Designed for maximum information density in minimal tokens.
    Two-tier cover markers:
      🚨  cover ≥ COVER_THRESHOLD      (abort-class / extreme)
      ⚡  cover ≥ SUSPICION_THRESHOLD  (high suspicion)

    Args:
        telemetry: Raw telemetry dict from z_telemetry.jsx
            {layers, topLayerItems, artboardRect, totalItemCount}

    Returns:
        Compact multi-line text string.
    """
    lines = ["Z-ORDER TELEMETRY"]

    # Layers
    layers = telemetry.get("layers", [])
    lines.append(f"Layers ({len(layers)} total, 0=top):")
    for lyr in layers[:8]:  # Cap display at 8
        vis = "1" if lyr.get("visible") else "0"
        lock = "1" if lyr.get("locked") else "0"
        items = lyr.get("itemCount", 0)
        lines.append(
            f"  {lyr.get('index', '?')} {lyr.get('name', '?')} "
            f"vis={vis} lock={lock} items={items}"
        )

    # Top items
    top_items = telemetry.get("topLayerItems", [])
    lines.append(f"Top items ({len(top_items)}, topmost visible layers):")
    for i, item in enumerate(top_items[:10]):  # Cap at 10
        name = item.get("name", "?")
        tn = item.get("typename", "?")
        layer = item.get("layerName", "?")
        op = item.get("opacity", 100)
        blend = item.get("blendingMode", "Normal")
        cover = item.get("coverRatio", 0)
        fill_hex = item.get("fillColorHex", "none")

        flag = "  ← 🚨" if cover >= COVER_THRESHOLD else (
            "  ← ⚡" if cover >= SUSPICION_THRESHOLD else ""
        )
        lines.append(
            f"  #{i+1} \"{name}\" {tn} L={layer} op={op} "
            f"blend={blend} fill={fill_hex} cover={cover}{flag}"
        )

    # Ghosts: items that exist but have no artboard overlap (Fix 10)
    ghosts = [
        item for item in top_items
        if item.get("coverRatio", 0) == 0
        and not item.get("hidden", False)
    ]
    if ghosts:
        lines.append(f"Ghosts ({len(ghosts)}, cover=0, bounds outside artboard):")
        for item in ghosts[:5]:  # Cap at 5
            name = item.get("name", "?")
            tn = item.get("typename", "?")
            layer = item.get("layerName", "?")
            op = item.get("opacity", 100)
            lines.append(
                f"  👻 \"{name}\" {tn} L={layer} op={op}"
                " — no artboard overlap"
            )

    # Total
    total = telemetry.get("totalItemCount", "?")
    lines.append(f"Total items: {total}")

    return "\n".join(lines)


def get_mutation_count(document=None) -> int:
    """Return the mutation count for a document (default: the active one)."""
    if document is None:
        return _counter.value
    return _counter.value_for(document)


def reset_mutation_count() -> None:
    """Reset every document's mutation counter to 0."""
    _counter.reset()


def set_active_document(name) -> None:
    """Tell the cadence which document subsequent mutations belong to."""
    _counter.set_active_document(name)


def note_active_document(name) -> None:
    """Record the document the host reported on its reply.

    Also moves a count taken before the document was known onto that document,
    so the first mutation of a session is not stranded on the unknown pile.
    """
    _counter.reattribute(name)


def forget_document(name) -> None:
    """Drop a closed document's cadence rather than carrying it forward."""
    _counter.forget(name)


def get_active_cadence_document() -> str:
    """The document mutations are currently attributed to."""
    return _counter.active_document


def mutation_counts() -> dict:
    """All per-document counts, for diagnostics."""
    return _counter.snapshot()
