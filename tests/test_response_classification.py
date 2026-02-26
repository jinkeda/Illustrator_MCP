"""
Snapshot tests for format_response and format_envelope.

These tests capture the EXACT current behavior of both formatters.
They must pass BEFORE and AFTER the B1 refactor to ensure no behavioral drift.
"""

import json
import pytest

from illustrator_mcp.proxy_client import format_response, format_envelope
from illustrator_mcp.errors import make_envelope


# =============================================================================
# format_response snapshots — strict string equality
# =============================================================================

class TestFormatResponseSnapshots:
    """Strict string-equality snapshots of format_response output."""

    def test_top_level_error(self):
        """Top-level error key in response triggers structured error formatting."""
        response = {"error": "Script syntax error at line 5"}
        result = format_response(response)
        # classify_error matches 'syntax error' → S005 code
        assert isinstance(result, str)
        assert "S005" in result

    def test_connection_error_prominent(self):
        """Connection error gets structured error formatting."""
        import warnings
        response = {"error": "[C001] DISCONNECTED: panel offline"}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = format_response(response)
        assert "C001" in result
        assert isinstance(result, str)

    def test_success_json_result(self):
        """Result dict with success envelope is unwrapped to inner result."""
        response = {"result": {"success": True, "result": {"data": [1, 2, 3]}}}
        result = format_response(response)
        parsed = json.loads(result)
        assert parsed == {"data": [1, 2, 3]}

    def test_success_envelope_unwrapped(self):
        """Success envelope {success:true, result:...} is unwrapped."""
        response = {"result": json.dumps({"success": True, "result": {"count": 5}})}
        result = format_response(response)
        parsed = json.loads(result)
        assert parsed == {"count": 5}

    def test_double_wrapped_result(self):
        """Double-wrapped JSON string is fully unwrapped."""
        inner = json.dumps({"success": True, "result": {"actual": "data"}})
        response = {"result": inner}
        result = format_response(response)
        parsed = json.loads(result)
        assert parsed == {"actual": "data"}

    def test_failure_envelope(self):
        """success:false in result is treated as error."""
        response = {"result": json.dumps({"success": False, "error": "Operation failed"})}
        result = format_response(response)
        assert "error" in result.lower() or "Error" in result

    def test_error_in_unwrapped_result(self):
        """Error key in unwrapped result dict."""
        response = {"result": json.dumps({"success": True, "result": {"error": "Inner error"}})}
        result = format_response(response)
        assert "Inner error" in result or "error" in result.lower()

    def test_string_error_prefix(self):
        """Plain-text string starting with error prefix."""
        response = {"result": "TypeError: undefined is not a function"}
        result = format_response(response)
        assert "TypeError" in result or "error" in result.lower()

    def test_string_error_syntax(self):
        """SyntaxError prefix detected."""
        response = {"result": "SyntaxError: unexpected token }"}
        result = format_response(response)
        assert "SyntaxError" in result or "error" in result.lower()

    def test_plain_string_result(self):
        """Plain string result that is not an error."""
        response = {"result": "Hello World"}
        result = format_response(response)
        assert result == "Hello World"

    def test_numeric_result(self):
        """Numeric result is stringified."""
        response = {"result": 42}
        result = format_response(response)
        assert result == "42"

    def test_json_array_result(self):
        """JSON array result is pretty-printed."""
        response = {"result": "[1, 2, 3]"}
        result = format_response(response)
        parsed = json.loads(result)
        assert parsed == [1, 2, 3]

    def test_no_result_key(self):
        """Response without result or error uses whole response as result."""
        import warnings
        response = {"data": "value"}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = format_response(response)
        # format_response uses response.get("result", response)
        parsed = json.loads(result)
        assert parsed == {"data": "value"}

    def test_format_response_emits_deprecation(self):
        """format_response emits DeprecationWarning."""
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            format_response({"result": "hello"})
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(dep_warnings) >= 1
            assert "format_envelope" in str(dep_warnings[0].message)

    def test_shim_parity_success_dict(self):
        """Shim produces identical output for success dict."""
        import warnings
        r = {"result": json.dumps({"key": "value"})}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = format_response(r)
        assert json.loads(result) == {"key": "value"}

    def test_shim_parity_error(self):
        """Shim produces same output as format_error_response for errors."""
        import warnings
        from illustrator_mcp.errors import format_error_response
        r = {"error": "Something went wrong"}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            result = format_response(r)
        expected = format_error_response("Something went wrong", "")
        assert result == expected


# =============================================================================
# format_envelope snapshots — strict dict structure equality
# =============================================================================

class TestFormatEnvelopeSnapshots:
    """Strict dict-equality snapshots of format_envelope output."""

    def _parse(self, result: str) -> dict:
        """Parse envelope JSON and return dict."""
        return json.loads(result)

    def test_top_level_error(self):
        """Top-level error produces {ok:false, error:{...}, result:null}."""
        response = {"error": "Script failed"}
        result = self._parse(format_envelope(response))
        assert result["ok"] is False
        assert result["result"] is None
        assert result["error"]["code"] is not None
        assert isinstance(result["error"]["message"], str)
        assert isinstance(result["error"]["suggestions"], list)
        assert result["warnings"] == []

    def test_success_simple(self):
        """Simple success produces {ok:true, result:..., error:null}."""
        response = {"result": "done"}
        result = self._parse(format_envelope(response))
        assert result["ok"] is True
        assert result["error"] is None
        assert result["result"] == "done"
        assert result["warnings"] == []

    def test_success_envelope_unwrapped(self):
        """Success envelope is unwrapped in result field."""
        response = {"result": json.dumps({"success": True, "result": {"count": 5}})}
        result = self._parse(format_envelope(response))
        assert result["ok"] is True
        assert result["result"] == {"count": 5}

    def test_failure_envelope(self):
        """success:false produces {ok:false}."""
        response = {"result": json.dumps({"success": False, "error": "Op failed"})}
        result = self._parse(format_envelope(response))
        assert result["ok"] is False
        assert result["result"] is None
        assert "Op failed" in result["error"]["message"] or result["error"]["code"] is not None

    def test_error_in_unwrapped_result(self):
        """Error key in unwrapped result dict."""
        response = {"result": json.dumps({"success": True, "result": {"error": "Inner"}})}
        result = self._parse(format_envelope(response))
        assert result["ok"] is False
        assert result["result"] is None

    def test_string_error_prefix(self):
        """Error prefix in plain string result."""
        response = {"result": "TypeError: bad type"}
        result = self._parse(format_envelope(response))
        assert result["ok"] is False
        assert result["result"] is None

    def test_warnings_passed_through(self):
        """Warnings list is included in envelope."""
        response = {"result": "ok"}
        result = self._parse(format_envelope(response, warnings=["Warn 1"]))
        assert result["ok"] is True
        assert result["warnings"] == ["Warn 1"]

    def test_diagnostics_passed_through(self):
        """Diagnostics dict is included in envelope."""
        response = {"result": "ok"}
        result = self._parse(format_envelope(response, diagnostics={"key": "val"}))
        assert result["ok"] is True
        assert result["diagnostics"]["key"] == "val"

    def test_trace_id_in_diagnostics(self):
        """trace_id from response appears in diagnostics."""
        response = {"result": "ok", "trace_id": "abc-123"}
        result = self._parse(format_envelope(response))
        assert result["diagnostics"]["trace_id"] == "abc-123"

    def test_elapsed_ms_in_diagnostics(self):
        """elapsed_ms from response appears in diagnostics."""
        response = {"result": "ok", "elapsed_ms": 123.4}
        result = self._parse(format_envelope(response))
        assert result["diagnostics"]["elapsed_ms"] == 123.4

    def test_json_object_result(self):
        """JSON object results are preserved, not stringified."""
        response = {"result": json.dumps({"data": [1, 2, 3]})}
        result = self._parse(format_envelope(response))
        assert result["ok"] is True
        assert result["result"] == {"data": [1, 2, 3]}

    def test_envelope_has_all_keys(self):
        """Every envelope response has exactly {ok, warnings, error, diagnostics, result}."""
        response = {"result": "test"}
        result = self._parse(format_envelope(response))
        assert set(result.keys()) == {"ok", "warnings", "error", "diagnostics", "result"}

    def test_error_envelope_has_all_keys(self):
        """Error envelopes also have all 5 keys."""
        response = {"error": "fail"}
        result = self._parse(format_envelope(response))
        assert set(result.keys()) == {"ok", "warnings", "error", "diagnostics", "result"}


class TestFormatEnvelopeNewShapes:
    """End-to-end tests for {ok, data/value} unwrapping through format_envelope."""

    def _parse(self, result: str) -> dict:
        return json.loads(result)

    def test_scalar_via_value(self):
        """SOC {ok:true, value:42} unwraps to result=42."""
        resp = {"result": '{"ok": true, "value": 42}'}
        env = self._parse(format_envelope(resp))
        assert env["ok"] is True
        assert env["result"] == 42

    def test_scalar_via_data(self):
        """{ok:true, data:42} unwraps to result=42."""
        resp = {"result": '{"ok": true, "data": 42}'}
        env = self._parse(format_envelope(resp))
        assert env["ok"] is True
        assert env["result"] == 42

    def test_dict_data_unwrapped(self):
        """{ok:true, data:{...}} unwraps to result={...} (no inner ok leak)."""
        resp = {"result": '{"ok": true, "data": {"width": 800}, "operation": "test"}'}
        env = self._parse(format_envelope(resp))
        assert env["ok"] is True
        assert env["result"] == {"width": 800}

    def test_error_surfaces_line_and_operation(self):
        """Structured error line/operation surfaces in external envelope."""
        resp = {"result": '{"ok":false,"error":{"message":"bad","line":7,"operation":"draw"}}'}
        env = self._parse(format_envelope(resp))
        assert env["ok"] is False
        assert env["error"]["line"] == 7
        assert env["error"]["operation"] == "draw"

    def test_warnings_always_present(self):
        """warnings is always a list, never omitted."""
        env = self._parse(format_envelope({"result": '{"ok":true,"data":"x"}'}))
        assert "warnings" in env
        assert isinstance(env["warnings"], list)


class TestBridgeShapePostPhase2:
    """Verify format_envelope handles Phase 2 host.jsx response shapes."""

    def _parse(self, result: str) -> dict:
        return json.loads(result)

    def test_passthrough_not_double_wrapped(self):
        """wrap_script JSON arrives as {"result": {ok:true, data:...}} after CEP parse."""
        # CEP panel does JSON.parse on host.jsx output, then sends parsedResult
        # as result (since parsedResult.result is undefined for new shape)
        resp = {"result": {"ok": True, "data": {"x": 1}, "operation": "test"}}
        env = self._parse(format_envelope(resp))
        assert env["ok"] is True
        assert env["result"] == {"x": 1}

    def test_bare_value_wrapped_by_host(self):
        """Bare return wrapped by host.jsx: {ok:true, data:42}."""
        resp = {"result": {"ok": True, "data": 42}}
        env = self._parse(format_envelope(resp))
        assert env["ok"] is True
        assert env["result"] == 42

    def test_host_error_structured_top_level(self):
        """host.jsx catch: top-level error is a dict {message, line, name}."""
        resp = {"error": {"message": "ReferenceError: foo", "line": 5, "name": "ReferenceError"}}
        env = self._parse(format_envelope(resp))
        assert env["ok"] is False
        assert "ReferenceError" in env["error"]["message"]
        assert env["error"]["line"] == 5

    def test_host_error_via_result_path(self):
        """host.jsx catch also arrives as result (CEP panel fallback)."""
        resp = {"result": {"ok": False, "error": {"message": "bad", "line": 7}}}
        env = self._parse(format_envelope(resp))
        assert env["ok"] is False
        assert env["error"]["line"] == 7


# =============================================================================
# make_envelope — pre-classified envelope builder
# =============================================================================

class TestMakeEnvelope:
    """Tests for errors.make_envelope (pre-classified envelope builder)."""

    def _parse(self, result: str) -> dict:
        return json.loads(result)

    def test_success_canonical_keys(self):
        """Success envelope has exactly the 5 canonical keys."""
        env = self._parse(make_envelope(ok=True, result={"count": 5}))
        assert set(env.keys()) == {"ok", "warnings", "error", "diagnostics", "result"}
        assert env["ok"] is True
        assert env["result"] == {"count": 5}
        assert env["error"] is None
        assert env["warnings"] == []
        assert env["diagnostics"] == {}

    def test_error_string_structured(self):
        """String error is converted to {code, message, suggestions}."""
        env = self._parse(make_envelope(ok=False, error="Script syntax error"))
        assert env["ok"] is False
        assert env["result"] is None
        assert isinstance(env["error"], dict)
        assert "code" in env["error"]
        assert "message" in env["error"]
        assert isinstance(env["error"]["suggestions"], list)

    def test_error_dict_normalised(self):
        """Dict error gets suggestions default [] if not provided."""
        env = self._parse(make_envelope(
            ok=False,
            error={"code": "E001", "message": "something failed"}
        ))
        assert env["error"]["code"] == "E001"
        assert env["error"]["message"] == "something failed"
        assert env["error"]["suggestions"] == []

    def test_error_dict_missing_keys_raises(self):
        """ValueError if dict error lacks code or message."""
        with pytest.raises(ValueError, match="code.*message"):
            make_envelope(ok=False, error={"message": "no code"})
        with pytest.raises(ValueError, match="code.*message"):
            make_envelope(ok=False, error={"code": "X"})

    def test_error_code_override_string(self):
        """error_code overrides auto-detected code for string errors."""
        env = self._parse(make_envelope(
            ok=False,
            error="something happened",
            error_code="CUSTOM_001"
        ))
        assert env["error"]["code"] == "CUSTOM_001"

    def test_error_code_ignored_for_dict(self):
        """error_code is ignored when error is a dict."""
        env = self._parse(make_envelope(
            ok=False,
            error={"code": "DICT_CODE", "message": "m"},
            error_code="OVERRIDE_IGNORED"
        ))
        assert env["error"]["code"] == "DICT_CODE"

    def test_line_operation_preserved(self):
        """line and operation in error dict are passed through."""
        env = self._parse(make_envelope(
            ok=False,
            error={"code": "X", "message": "m", "line": 42, "operation": "draw"}
        ))
        assert env["error"]["line"] == 42
        assert env["error"]["operation"] == "draw"

    def test_defaults(self):
        """Missing optional args default to empty list/dict/None."""
        env = self._parse(make_envelope(ok=True))
        assert env["warnings"] == []
        assert env["diagnostics"] == {}
        assert env["error"] is None
        assert env["result"] is None

    def test_error_envelope_has_canonical_keys(self):
        """Error envelopes also have all 5 canonical keys."""
        env = self._parse(make_envelope(ok=False, error="fail"))
        assert set(env.keys()) == {"ok", "warnings", "error", "diagnostics", "result"}

    def test_warnings_and_diagnostics_passed(self):
        """Warnings and diagnostics are included in envelope."""
        env = self._parse(make_envelope(
            ok=True,
            result="done",
            warnings=["w1"],
            diagnostics={"tool": "test"}
        ))
        assert env["warnings"] == ["w1"]
        assert env["diagnostics"]["tool"] == "test"

    def test_ok_true_with_error_raises(self):
        """ok=True with error is contradictory and raises ValueError."""
        with pytest.raises(ValueError, match="contradictory"):
            make_envelope(ok=True, error="oops")
        with pytest.raises(ValueError, match="contradictory"):
            make_envelope(ok=True, error={"code": "X", "message": "m"})


