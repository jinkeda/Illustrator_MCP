"""
Tests for proxy_client module.

Tests for _unwrap_result, _try_parse_json, format_response edge cases.
"""

import pytest
import json

from illustrator_mcp.proxy_client import (
    _try_parse_json,
    _unwrap_result,
    format_response,
)


class TestTryParseJson:
    """Tests for _try_parse_json helper."""
    
    def test_valid_json_object(self):
        """Test parsing valid JSON object."""
        result = _try_parse_json('{"key": "value"}')
        assert result == {"key": "value"}
    
    def test_valid_json_array(self):
        """Test parsing valid JSON array."""
        result = _try_parse_json('[1, 2, 3]')
        assert result == [1, 2, 3]
    
    def test_invalid_json_returns_original(self):
        """Test that invalid JSON returns original string."""
        result = _try_parse_json("not json")
        assert result == "not json"
    
    def test_empty_string(self):
        """Test empty string returns empty string."""
        result = _try_parse_json("")
        assert result == ""


class TestUnwrapResult:
    """Tests for _unwrap_result recursive unwrapper."""
    
    def test_non_dict_returns_as_is(self):
        """Test that non-dict values pass through."""
        assert _unwrap_result("string") == "string"
        assert _unwrap_result(123) == 123
        assert _unwrap_result([1, 2, 3]) == [1, 2, 3]
        assert _unwrap_result(None) is None
    
    def test_simple_success_envelope(self):
        """Test unwrapping simple success envelope."""
        result = {"success": True, "result": {"data": "value"}}
        assert _unwrap_result(result) == {"data": "value"}
    
    def test_double_wrapped_json_string(self):
        """Test unwrapping double-wrapped JSON string."""
        inner = json.dumps({"success": True, "result": {"actual": "data"}})
        outer = {"success": True, "result": inner}
        assert _unwrap_result(outer) == {"actual": "data"}
    
    def test_triple_nested_unwrapping(self):
        """Test deeply nested result unwrapping."""
        deepest = {"final": "value"}
        level2 = json.dumps({"success": True, "result": deepest})
        level1 = {"success": True, "result": level2}
        assert _unwrap_result(level1) == {"final": "value"}
    
    def test_error_stops_unwrapping(self):
        """Test that error in result stops unwrapping."""
        result = {"success": True, "result": {"error": "Something failed"}}
        unwrapped = _unwrap_result(result)
        assert unwrapped.get("error") == "Something failed"
    
    def test_success_false_stops_unwrapping(self):
        """Test that success:false stops unwrapping."""
        result = {"success": False, "error": "Failed", "result": "ignored"}
        unwrapped = _unwrap_result(result)
        assert unwrapped.get("success") is False
    
    def test_no_result_key_returns_as_is(self):
        """Test dict without result key returns as-is."""
        result = {"success": True, "data": "value"}
        assert _unwrap_result(result) == result


class TestFormatResponse:
    """Tests for format_response function."""
    
    def test_error_response(self):
        """Test error response formatting."""
        response = {"error": "Script failed"}
        result = format_response(response)
        assert "Error: Script failed" in result
    
    def test_connection_error_prominent(self):
        """Test connection errors are prominently displayed."""
        response = {"error": "DISCONNECTED"}
        result = format_response(response)
        assert "⚠️" in result
        assert "STOP" in result
    
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
        assert "Error:" in result
