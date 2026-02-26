"""Tests for execute_task canonical envelope wrapping.

Verifies the three-phase response handling:
  Phase 1: build_envelope_dict short-circuit
  Phase 2: TaskReport parsing
  Phase 3: make_envelope construction
"""

import json
import pytest

from illustrator_mcp.proxy_client import build_envelope_dict
from illustrator_mcp.tools.task_execution import (
    _taskreport_first_error,
    _dedup_warnings,
)


# ── build_envelope_dict stability ─────────────────────────────────


class TestBuildEnvelopeDict:
    """Ensure build_envelope_dict is importable and returns canonical shape."""

    CANONICAL_KEYS = {"ok", "warnings", "error", "diagnostics", "result"}

    def test_importable(self):
        """build_envelope_dict is importable from proxy_client."""
        assert callable(build_envelope_dict)

    def test_keyset_on_error(self):
        """Returns exactly 5 canonical keys on error input."""
        response = {"error": "something broke"}
        result = build_envelope_dict(response, context="test")
        assert set(result.keys()) == self.CANONICAL_KEYS
        assert result["ok"] is False
        assert result["result"] is None
        # error is a dict with code/message/suggestions
        assert isinstance(result["error"], dict)
        assert "code" in result["error"]
        assert "message" in result["error"]
        assert "suggestions" in result["error"]

    def test_keyset_on_success(self):
        """Returns exactly 5 canonical keys on success input."""
        response = {"result": '{"ok": true, "data": "hello"}'}
        result = build_envelope_dict(response, context="test")
        assert set(result.keys()) == self.CANONICAL_KEYS
        assert result["ok"] is True
        assert result["error"] is None

    def test_serializable(self):
        """Result is JSON-serializable."""
        response = {"error": "timeout", "trace_id": "req_abc"}
        result = build_envelope_dict(response, context="test", diagnostics={"tool": "t"})
        serialized = json.dumps(result)  # should not raise
        parsed = json.loads(serialized)
        assert parsed["ok"] is False
        assert parsed["diagnostics"]["trace_id"] == "req_abc"


# ── _taskreport_first_error ───────────────────────────────────────


class TestTaskreportFirstError:
    """Test error extraction from various shapes."""

    def test_flat_error(self):
        report = {"errors": [{"code": "V011", "message": "bad count"}]}
        err = _taskreport_first_error(report, "element_create_batch")
        assert err["code"] == "V011"
        assert err["message"] == "bad count"
        assert err["operation"] == "element_create_batch"
        assert "suggestions" in err

    def test_nested_makeerror_shape(self):
        report = {"errors": [{"ok": False, "error": {"code": "E001", "message": "inner"}}]}
        err = _taskreport_first_error(report, "my_task")
        assert err["code"] == "E001"
        assert err["message"] == "inner"

    def test_no_errors(self):
        report = {"errors": []}
        err = _taskreport_first_error(report, "my_task")
        assert err["code"] == "R009"
        assert "my_task" in err["message"]

    def test_missing_errors_key(self):
        report = {}
        err = _taskreport_first_error(report, "my_task")
        assert err["code"] == "R009"

    def test_string_error_fallback(self):
        report = {"errors": ["something went wrong"]}
        err = _taskreport_first_error(report, "my_task")
        assert "code" in err
        assert "message" in err
        assert err["operation"] == "my_task"

    def test_dict_without_code(self):
        report = {"errors": [{"message": "no code here"}]}
        err = _taskreport_first_error(report, "my_task")
        # Should fall back to create_structured_error
        assert "code" in err
        assert "message" in err

    def test_preserves_original_operation(self):
        report = {"errors": [{"code": "X", "message": "m", "operation": "orig_op"}]}
        err = _taskreport_first_error(report, "fallback_task")
        assert err["operation"] == "orig_op"


# ── _dedup_warnings ───────────────────────────────────────────────


class TestDedupWarnings:

    def test_basic_dedup(self):
        assert _dedup_warnings(["a", "b"], ["b", "c"]) == ["a", "b", "c"]

    def test_preserves_order(self):
        assert _dedup_warnings(["c", "a"], ["b", "a"]) == ["c", "a", "b"]

    def test_empty_lists(self):
        assert _dedup_warnings([], []) == []
        assert _dedup_warnings() == []

    def test_none_handling(self):
        assert _dedup_warnings(None, ["a"]) == ["a"]

    def test_single_list(self):
        assert _dedup_warnings(["a", "b", "a"]) == ["a", "b"]


# ── Phase 1 short-circuit ─────────────────────────────────────────


class TestPhase1ShortCircuit:
    """When build_envelope_dict returns ok=False, execute_task should
    return it unchanged without attempting TaskReport parse."""

    def test_bridge_error_produces_canonical_envelope(self):
        """Simulates a bridge-level error response."""
        response = {"error": "executeTask is not a function"}
        base = build_envelope_dict(response, context="execute_task: test")
        assert base["ok"] is False
        assert "executeTask" in base["error"]["message"]
        # Verify it's JSON-serializable (as execute_task does json.dumps(base))
        serialized = json.dumps(base)
        parsed = json.loads(serialized)
        assert parsed["ok"] is False


# ── Phase 2 parse failure → R010 ──────────────────────────────────


class TestPhase2ParseFailure:
    """When result is not valid JSON, should return R010 error."""

    def test_non_json_result(self):
        """build_envelope_dict passes through non-JSON strings;
        execute_task should catch the json.loads failure."""
        response = {"result": "this is not json"}
        base = build_envelope_dict(response, context="test")
        # build_envelope_dict treats string result as opaque data
        assert base["ok"] is True
        assert base["result"] == "this is not json"
        # execute_task would then try json.loads and fail → R010
        # (The actual R010 path is in the async handler;
        #  here we verify the prerequisite condition)


# ── Phase 3: report.ok=false → outer ok=false ─────────────────────


class TestPhase3ReportOkFalse:
    """When TaskReport.ok is false, outer envelope should be ok=false."""

    def test_report_ok_false_produces_error_envelope(self):
        """Verify the error extraction pipeline."""
        report_data = {
            "ok": False,
            "stats": {"itemsProcessed": 1, "itemsModified": 0, "itemsSkipped": 1},
            "errors": [{"code": "V011", "message": "bad count", "stage": "validate"}],
        }
        err = _taskreport_first_error(report_data, "element_create_batch")
        assert err["code"] == "V011"
        assert err["operation"] == "element_create_batch"

        # verify make_envelope produces correct shape
        from illustrator_mcp.errors import make_envelope
        envelope = json.loads(make_envelope(
            ok=False,
            error=err,
            diagnostics={"stats": {
                k: report_data["stats"].get(k, 0)
                for k in ("itemsProcessed", "itemsModified", "itemsSkipped")
            }},
        ))
        assert envelope["ok"] is False
        assert envelope["result"] is None
        assert envelope["error"]["code"] == "V011"
        assert envelope["error"]["operation"] == "element_create_batch"
        assert envelope["diagnostics"]["stats"]["itemsSkipped"] == 1
