"""Execution coordination (T12+).

Owns *logical jobs* — units of work that may span several host calls — as
opposed to ``bridge/request_registry.py``, which owns individual in-flight
WebSocket requests. The two are deliberately separate: a job outlives any one
request, and must survive the waiter that started it going away.
"""

from illustrator_mcp.execution.coordinator import (
    DuplicateJobError,
    ExecutionCoordinator,
    HostUnresolvedError,
    JobCancelledError,
    JobConflictError,
    JobRecord,
    JobStatus,
    get_coordinator,
    request_digest,
)

__all__ = [
    "DuplicateJobError",
    "ExecutionCoordinator",
    "HostUnresolvedError",
    "JobCancelledError",
    "JobConflictError",
    "JobRecord",
    "JobStatus",
    "get_coordinator",
    "request_digest",
]
