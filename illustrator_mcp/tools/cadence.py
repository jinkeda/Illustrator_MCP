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


def get_mutation_count() -> int:
    """Return the current mutation counter value."""
    return _counter.value


def reset_mutation_count() -> None:
    """Reset the mutation counter to 0."""
    _counter.reset()
