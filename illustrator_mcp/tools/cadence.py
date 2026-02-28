"""
VLM QA Cadence — mutation counter and checkpoint constants.

Tracks the number of mutating tool calls so the VLM QA pipeline can
auto-inject annotated previews at regular intervals.

This module is the SINGLE SOURCE OF TRUTH for cadence state.
Other tool modules import from here (never the reverse).
"""

import threading

# ── VLM QA Cadence ──────────────────────────────────────────────────
# Auto-inject annotated preview every N execute_script calls.
# The counter is module-level and resets on server restart.
VLM_QA_CADENCE: int = 5
# CONTRACT: any new mutating tool MUST call _counter.increment().


class _MutationCounter:
    """Thread-safe mutation counter for VLM QA cadence.

    Uses a lock so increment/decrement are safe under free-threaded
    Python (PEP 703 / --disable-gil).
    TODO: scope to connection/session if scaling to multi-agent SSE/HTTP.
    """

    def __init__(self) -> None:
        self._count: int = 0
        self._lock = threading.Lock()

    def increment(self) -> int:
        """Atomically increment and return the new value."""
        with self._lock:
            self._count += 1
            return self._count

    def decrement(self) -> None:
        """Atomically decrement (floor at 0)."""
        with self._lock:
            self._count = max(0, self._count - 1)

    @property
    def value(self) -> int:
        with self._lock:
            return self._count

    def reset(self) -> None:
        with self._lock:
            self._count = 0


_counter = _MutationCounter()

# Cognitive Forcing Function: injected as the LAST TextContent element
# when cadence fires, forcing the AI to produce reasoning tokens about
# the visual state before it can formulate its next action.
VLM_CHECKPOINT_INSTRUCTION: str = (
    "⚠️ VLM QA CHECKPOINT (mutation #{count})\n"
    "An annotated preview was auto-injected by the VLM QA cadence system.\n"
    "Before proceeding with further edits OR concluding your workflow, you MUST:\n"
    "1. Describe what you see in the preview image (layout, colors, positions)\n"
    "2. Compare against the intended design — note any discrepancies\n"
    "3. List corrections needed (if any) for the next step\n"
    "\n"
    "If no annotated preview image is attached above, proceed using the textual "
    "report and request a manual preview via return_preview=True on your next call.\n"
    "\n"
    "In your immediate next response, DO NOT call any tools. "
    "You must output ONLY your text analysis."
)


def format_z_telemetry(telemetry: dict) -> str:
    """Format z-order telemetry as compact text for VLM checkpoint.

    Designed for maximum information density in minimal tokens.
    Two-tier cover markers:
      🚨  cover ≥ 0.90  (abort-class / extreme)
      ⚡  cover ≥ 0.70  (high suspicion)

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

        flag = "  ← 🚨" if cover >= 0.90 else ("  ← ⚡" if cover >= 0.70 else "")
        lines.append(
            f"  #{i+1} \"{name}\" {tn} L={layer} op={op} "
            f"blend={blend} fill={fill_hex} cover={cover}{flag}"
        )

    # Total
    total = telemetry.get("totalItemCount", "?")
    lines.append(f"Total items: {total}")

    return "\n".join(lines)


def get_mutation_count() -> int:
    """Return the current mutation counter value."""
    return _counter.value


def reset_mutation_count() -> None:
    """Reset the mutation counter to 0."""
    _counter.reset()
