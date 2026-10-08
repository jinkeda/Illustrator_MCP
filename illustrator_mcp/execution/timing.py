"""Request-local, monotonic diagnostics; never execution or reconciliation facts.

Spans partition the measured Python call (including awaits). They do not
measure host evaluation separately from transport, and byte counts are not
model tokens. No scripts, results, or retained job objects are stored here.
"""
from __future__ import annotations

import time
from typing import Callable


class ExecutionTiming:
    def __init__(self, trace_id: str, *, clock: Callable[[], int] = time.perf_counter_ns):
        self._clock = clock
        self._start = self._last = clock()
        self._phase = "preparation"
        self._spans: list[dict] = []
        self.fields: dict = {
            "schema_version": 1,
            "trace_id": trace_id,
            "scope": "execute_script_with_context",
            "job_id": None,
            "request_token": None,
            "connection_generation": None,
        }

    def phase(self, name: str) -> None:
        now = self._clock()
        self._spans.append({
            "name": self._phase,
            "start_ms": (self._last - self._start) / 1_000_000,
            "duration_ms": (now - self._last) / 1_000_000,
        })
        self._last = now
        self._phase = name

    def finish(self) -> dict:
        self.phase("finished")
        return {
            **self.fields,
            "spans": self._spans,
            "end_to_end_ms": (self._last - self._start) / 1_000_000,
        }
