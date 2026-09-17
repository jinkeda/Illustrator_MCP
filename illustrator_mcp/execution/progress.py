"""Request-local SDK milestones; counts are boundaries, never percentages."""
import asyncio
import logging
from contextvars import ContextVar
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Progress:
    context: object
    count: int = 0


active_progress = ContextVar("active_progress", default=None)


def begin():
    from illustrator_mcp.shared import mcp
    context = mcp.get_context()
    try:
        meta = context.request_context.meta
        enabled = meta is not None and meta.progressToken is not None
    except ValueError:  # Direct Python calls have no MCP request.
        enabled = False
    return active_progress.set(Progress(context) if enabled else None)


async def milestone(message):
    state = active_progress.get()
    if state is None:
        return
    state.count += 1
    try:
        # A disconnected/slow progress consumer must not hold the host slot.
        await asyncio.wait_for(state.context.report_progress(
            state.count, total=None, message=message,
        ), timeout=0.25)
    except asyncio.CancelledError:
        if asyncio.current_task().cancelling():
            raise  # Preserve cancellation of the actual request.
        logger.debug("Progress consumer cancelled its notification")
    except Exception:
        logger.debug("Progress notification unavailable", exc_info=True)


async def outcome(value):
    data = getattr(value, "structuredContent", None) or {}
    if data.get("diagnostics", {}).get("deduplicated"):
        await milestone("retained outcome returned; no execution")
    elif data.get("execution") == "succeeded":
        await milestone("completed")
    elif data.get("execution"):
        await milestone("outcome: " + data["execution"])
