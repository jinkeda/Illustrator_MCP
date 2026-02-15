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
