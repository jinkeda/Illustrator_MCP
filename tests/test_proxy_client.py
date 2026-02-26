"""
Tests for proxy_client module.

Tests for unwrap_result, try_parse_json, format_response edge cases.
"""

import pytest
import json

from illustrator_mcp.utils.response import (
    try_parse_json,
    unwrap_result,
)
from illustrator_mcp.proxy_client import format_response


class TestTryParseJson:
    """Tests for try_parse_json helper."""
    
    def test_valid_json_object(self):
        """Test parsing valid JSON object."""
        result = try_parse_json('{"key": "value"}')
        assert result == {"key": "value"}
    
    def test_valid_json_array(self):
        """Test parsing valid JSON array."""
        result = try_parse_json('[1, 2, 3]')
        assert result == [1, 2, 3]
    
    def test_invalid_json_returns_original(self):
        """Test that invalid JSON returns original string."""
        result = try_parse_json("not json")
        assert result == "not json"
    
    def test_empty_string(self):
        """Test empty string returns empty string."""
        result = try_parse_json("")
        assert result == ""


class TestUnwrapResult:
    """Tests for unwrap_result recursive unwrapper."""
    
    def test_non_dict_returns_as_is(self):
        """Test that non-dict values pass through."""
        assert unwrap_result("string") == "string"
        assert unwrap_result(123) == 123
        assert unwrap_result([1, 2, 3]) == [1, 2, 3]
        assert unwrap_result(None) is None
    
    def test_simple_success_envelope(self):
        """Test unwrapping simple success envelope."""
        result = {"success": True, "result": {"data": "value"}}
        assert unwrap_result(result) == {"data": "value"}
    
    def test_double_wrapped_json_string(self):
        """Test unwrapping double-wrapped JSON string."""
        inner = json.dumps({"success": True, "result": {"actual": "data"}})
        outer = {"success": True, "result": inner}
        assert unwrap_result(outer) == {"actual": "data"}
    
    def test_triple_nested_unwrapping(self):
        """Test deeply nested result unwrapping."""
        deepest = {"final": "value"}
        level2 = json.dumps({"success": True, "result": deepest})
        level1 = {"success": True, "result": level2}
        assert unwrap_result(level1) == {"final": "value"}
    
    def test_error_stops_unwrapping(self):
        """Test that error in result stops unwrapping."""
        result = {"success": True, "result": {"error": "Something failed"}}
        unwrapped = unwrap_result(result)
        assert unwrapped.get("error") == "Something failed"
    
    def test_success_false_stops_unwrapping(self):
        """Test that success:false stops unwrapping."""
        result = {"success": False, "error": "Failed", "result": "ignored"}
        unwrapped = unwrap_result(result)
        assert unwrapped.get("success") is False
    
    def test_no_result_key_returns_as_is(self):
        """Test dict without result key returns as-is."""
        result = {"success": True, "data": "value"}
        assert unwrap_result(result) == result


class TestUnwrapOkDataEnvelope:
    """Tests for {ok, data} envelope unwrapping (Phase 1a)."""

    def test_ok_data_unwrapped(self):
        """Standard {ok:true, data:…} is unwrapped to data."""
        result = {"ok": True, "data": {"width": 800}, "operation": "test"}
        assert unwrap_result(result) == {"width": 800}

    def test_ok_value_unwrapped(self):
        """SOC {ok:true, value:…} is unwrapped to value."""
        result = {"ok": True, "value": 42}
        assert unwrap_result(result) == 42

    def test_ok_false_not_unwrapped(self):
        """Error envelope {ok:false} passes through untouched."""
        result = {"ok": False, "error": {"message": "fail"}}
        assert unwrap_result(result) == result

    def test_ok_false_with_data_not_unwrapped(self):
        """Edge case: {ok:false, data:{...}} must NOT unwrap."""
        result = {"ok": False, "data": {"x": 1}, "error": "partial"}
        assert unwrap_result(result) == result

    def test_batch_report_not_unwrapped(self):
        """Batch {ok:true, stats:…, ops:…} (no data key) passes through."""
        result = {"ok": True, "stats": {"total": 5}, "ops": []}
        assert unwrap_result(result) == result

    def test_double_wrapped_ok_data(self):
        """{success:true, result: '{"ok":true, "data":{…}}'} fully unwraps."""
        inner = json.dumps({"ok": True, "data": {"key": "val"}, "operation": "x"})
        outer = {"success": True, "result": inner}
        assert unwrap_result(outer) == {"key": "val"}

    def test_empty_string_error_stops_unwrap(self):
        """Key presence, not truthiness: empty string error stops unwrapping."""
        result = {"error": "", "result": "should_not_reach"}
        assert unwrap_result(result) == result

    def test_empty_dict_error_stops_unwrap(self):
        """Key presence: empty dict error stops unwrapping."""
        result = {"error": {}, "result": "should_not_reach"}
        assert unwrap_result(result) == result


class TestFormatResponse:
    """Tests for format_response function."""
    
    def test_error_response(self):
        """Test error response formatting."""
        response = {"error": "Script failed"}
        result = format_response(response)
        assert "Script failed" in result
        assert "Error" in result
    
    def test_connection_error_prominent(self):
        """Test connection errors produce structured error formatting."""
        import warnings
        response = {"error": "DISCONNECTED"}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = format_response(response)
        assert "Error" in result
        assert isinstance(result, str)
    
    def test_success_json_formatted(self):
        """Test successful JSON is formatted."""
        response = {"result": {"success": True, "data": [1, 2, 3]}}
        result = format_response(response)
        # Should be valid JSON output
        parsed = json.loads(result)
        assert parsed["data"] == [1, 2, 3]
    
    def test_nested_error_detected(self):
        """Test that errors in nested result are detected."""
        response = {"result": json.dumps({"success": False, "error": "Inner error"})}
        result = format_response(response)
        assert "Error" in result or "error" in result.lower()
