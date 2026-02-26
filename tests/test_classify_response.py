"""
Direct integration tests for classify_response.

Tests the actual classification chain rather than snapshot strings —
verifies ResponseClassification fields directly.
"""

import pytest
from illustrator_mcp.response_classification import (
    classify_response,
    ClassifyOptions,
    ResponseClassification,
)


class TestClassifyResponseTopLevel:
    """Test top-level error detection (priority 1)."""

    def test_top_level_error(self):
        """Top-level 'error' key produces ok=False with error_code."""
        resp = {"error": "[S005] Script execution failed"}
        c = classify_response(resp)

        assert c.ok is False
        assert c.error_message == "[S005] Script execution failed"
        assert c.error_code is not None
        assert c.raw is resp

    def test_connection_error_flagged(self):
        """Connection errors set is_connection_error=True."""
        resp = {"error": "[C001] CEP panel is not connected"}
        c = classify_response(resp)

        assert c.ok is False
        assert c.is_connection_error is True


class TestClassifyResponseSuccess:
    """Test success classification (priority 7)."""

    def test_simple_success_dict(self):
        """Dict result with no error keys is success."""
        resp = {"result": '{"layers": []}'}
        c = classify_response(resp)

        assert c.ok is True
        assert c.result == {"layers": []}

    def test_success_envelope_unwrapped(self):
        """Success envelope {success:true, result:...} is unwrapped."""
        inner = {"data": [1, 2, 3]}
        resp = {"result": {"success": True, "result": inner}}
        c = classify_response(resp)

        assert c.ok is True
        assert c.result == inner

    def test_double_wrapped_fully_unwrapped(self):
        """Double-wrapped JSON string is fully unwrapped to final value."""
        import json
        inner = {"key": "value"}
        mid = json.dumps({"success": True, "result": inner})
        resp = {"result": {"success": True, "result": mid}}
        c = classify_response(resp)

        assert c.ok is True
        assert c.result == inner

    def test_plain_string_result(self):
        """Non-error plain string result is success."""
        resp = {"result": "Hello World"}
        c = classify_response(resp)

        assert c.ok is True
        assert c.result == "Hello World"

    def test_list_result_preserved(self):
        """List result is preserved exactly."""
        resp = {"result": "[1, 2, 3]"}
        c = classify_response(resp)

        assert c.ok is True
        assert c.result == [1, 2, 3]


class TestClassifyResponseInnerErrors:
    """Test inner error detection (priorities 3-5)."""

    def test_inner_error_key(self):
        """Error key in unwrapped dict is detected."""
        resp = {"result": '{"error": "No document open"}'}
        c = classify_response(resp)

        assert c.ok is False
        assert c.error_message == "No document open"

    def test_success_false_envelope(self):
        """success:false produces ok=False."""
        resp = {"result": '{"success": false, "error": "Operation failed"}'}
        c = classify_response(resp)

        assert c.ok is False
        assert "Operation failed" in c.error_message

    def test_string_error_prefix(self):
        """Plain-text with error prefix is detected."""
        resp = {"result": "Error: Cannot find layer"}
        c = classify_response(resp)

        assert c.ok is False
        assert c.error_message == "Error: Cannot find layer"

    def test_syntax_error_prefix(self):
        """SyntaxError prefix is detected."""
        resp = {"result": "SyntaxError: Unexpected token }"}
        c = classify_response(resp)

        assert c.ok is False


class TestClassifyResponseSentinel:
    """Test MCP_LIBS_NOT_READY sentinel (priority 6)."""

    def test_libs_not_ready_sentinel(self):
        """MCP_LIBS_NOT_READY sentinel produces specific error_code."""
        resp = {"result": "MCP_LIBS_NOT_READY:1.2.3"}
        c = classify_response(resp)

        assert c.ok is False
        assert c.error_code == "MCP_LIBS_NOT_READY"
        assert c.error_message == "MCP_LIBS_NOT_READY:1.2.3"


class TestClassifyOptions:
    """Test option-controlled behavior."""

    def test_disable_string_error_detection(self):
        """With treat_string_error_as_error=False, error-prefixed strings pass."""
        opts = ClassifyOptions(treat_string_error_as_error=False)
        resp = {"result": "Error: this is just data"}
        c = classify_response(resp, options=opts)

        assert c.ok is True

    def test_disable_unwrap(self):
        """With unwrap_success_envelope=False, envelopes are not unwrapped."""
        opts = ClassifyOptions(unwrap_success_envelope=False)
        resp = {"result": {"success": True, "result": {"data": 42}}}
        c = classify_response(resp, options=opts)

        assert c.ok is True
        # Result should still be the raw dict with success key
        assert c.result.get("success") is True


class TestClassifyResponseBatchReport:
    """Test batch report classification (step 4b)."""

    def test_batch_ok_false_passed_through(self):
        """Batch report with ok:false + ops/stats is passed through (not error)."""
        resp = {"result": {
            "ok": False,
            "ops": [
                {"index": 0, "task": "element_create", "ok": False, "error": "Layer locked"},
                {"index": 1, "task": "style_set_fill", "ok": True},
            ],
            "stats": {"total": 2, "passed": 1, "failed": 1},
        }}
        c = classify_response(resp)

        assert c.ok is True  # pass-through — NOT classified as error
        assert c.result["ok"] is False  # batch's own ok preserved
        assert len(c.result["ops"]) == 2  # per-op details preserved

    def test_batch_ok_false_empty_ops_passed_through(self):
        """Batch with ok:false, empty ops, and stats is still passed through."""
        resp = {"result": {
            "ok": False,
            "ops": [],
            "stats": {"total": 5, "failed": 1},
        }}
        c = classify_response(resp)

        assert c.ok is True
        assert c.result["stats"]["failed"] == 1

    def test_non_batch_ok_false_still_errors(self):
        """Dict with ok:false but NO ops/stats is NOT a batch — falls through to step 5+."""
        resp = {"result": {
            "ok": False,
            "error": "Something failed",
        }}
        c = classify_response(resp)

        # step 3 catches this via the inner "error" key
        assert c.ok is False
        assert "Something failed" in c.error_message

    def test_batch_ok_true_passes(self):
        """Batch report {ok:true} passes through as success."""
        resp = {"result": {
            "ok": True,
            "ops": [{"index": 0, "task": "element_create", "ok": True}],
            "stats": {"total": 5, "passed": 5, "failed": 0},
            "createdIds": ["id1", "id2"],
        }}
        c = classify_response(resp)

        assert c.ok is True
        assert c.result["ok"] is True

    def test_batch_ok_true_with_errors_trusts_ok(self):
        """Batch with ok:true AND non-empty errors trusts ok (partial success)."""
        resp = {"result": {
            "ok": True,
            "ops": [
                {"index": 0, "ok": True},
                {"index": 1, "ok": True},
                {"index": 2, "task": "style_set_fill", "ok": False, "error": "skipped"},
            ],
            "errors": [{"index": 2, "task": "style_set_fill", "error": "skipped"}],
            "stats": {"total": 5, "passed": 4, "failed": 1},
        }}
        c = classify_response(resp)

        assert c.ok is True

    def test_no_ok_field_passes(self):
        """Dict with no 'ok' key is treated as success (backward compat)."""
        resp = {"result": {"data": "some result", "stats": {"total": 1}}}
        c = classify_response(resp)

        assert c.ok is True


class TestClassifyStructuredErrors:
    """Tests for structured error object preservation (Phase 1b)."""

    def test_dict_error_preserves_line(self):
        """Structured error {message, line} preserves line number."""
        resp = {"result": '{"ok": false, "error": {"message": "fail", "line": 42}}'}
        c = classify_response(resp)
        assert c.ok is False
        assert c.error_line == 42

    def test_dict_error_preserves_operation_nested(self):
        """wrap_script shape: operation inside error dict."""
        resp = {"result": '{"ok": false, "error": {"message": "f", "operation": "draw"}}'}
        c = classify_response(resp)
        assert c.error_operation == "draw"

    def test_legacy_line_as_sibling(self):
        """host.jsx puts line as sibling of error string."""
        resp = {"result": '{"error": "fail", "line": 10}'}
        c = classify_response(resp)
        assert c.error_line == 10

    def test_legacy_operation_as_sibling(self):
        """Template shape: operation as sibling of error."""
        resp = {"result": '{"error": "fail", "operation": "export"}'}
        c = classify_response(resp)
        assert c.error_operation == "export"

    def test_string_error_no_metadata(self):
        """Simple string error has no line or operation."""
        resp = {"result": '{"error": "No document open"}'}
        c = classify_response(resp)
        assert c.ok is False
        assert c.error_line is None
        assert c.error_operation is None
