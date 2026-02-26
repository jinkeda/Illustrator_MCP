"""
test_error_centralization.py — Validate error code centralization.

Tests the unified ErrorCode enum, legacy code mapping, direct code lookup,
and contracts.jsx parity.
"""

import json
from collections import Counter
from pathlib import Path

import pytest


# =============================================================================
# ErrorCode integrity
# =============================================================================

class TestErrorCodeIntegrity:
    """Ensure ErrorCode enum has no collisions and correct assignments."""

    def test_no_code_collisions(self):
        """No two ErrorCode members should share the same value."""
        from illustrator_mcp.errors import ErrorCode

        values = [code.value for code in ErrorCode]
        dupes = [v for v, count in Counter(values).items() if count > 1]
        assert not dupes, f"ErrorCode value collision(s): {dupes}"

    def test_v009_is_library_not_found(self):
        """V009 must remain V_LIBRARY_NOT_FOUND (never reuse codes)."""
        from illustrator_mcp.errors import ErrorCode

        assert ErrorCode.V_LIBRARY_NOT_FOUND.value == "V009"

    def test_v011_is_invalid_param_value(self):
        """V011 should be the new V_INVALID_PARAM_VALUE (no V009 collision)."""
        from illustrator_mcp.errors import ErrorCode

        assert ErrorCode.V_INVALID_PARAM_VALUE.value == "V011"

    def test_compound_codes_dont_collide_with_connection(self):
        """Compound C006–C009 must not collide with connection C001–C004."""
        from illustrator_mcp.errors import ErrorCode

        connection_codes = {
            ErrorCode.C_DISCONNECTED.value,
            ErrorCode.C_TIMEOUT.value,
            ErrorCode.C_BRIDGE_ERROR.value,
            ErrorCode.C_PROTOCOL.value,
        }
        compound_codes = {
            ErrorCode.C_NESTING_NOT_ALLOWED.value,
            ErrorCode.C_PREV_UNAVAILABLE.value,
            ErrorCode.C_INVALID_TOKEN_POSITION.value,
            ErrorCode.C_UNKNOWN_TOKEN.value,
        }
        overlap = connection_codes & compound_codes
        assert not overlap, f"Connection/compound C_* collision: {overlap}"


# =============================================================================
# Legacy code mapping
# =============================================================================

class TestLegacyCodeMapping:
    """LEGACY_CODE_MAP maps ad-hoc strings to canonical codes."""

    def test_query_error_maps(self):
        from illustrator_mcp.errors import LEGACY_CODE_MAP, ErrorCode

        assert LEGACY_CODE_MAP["QUERY_ERROR"] == ErrorCode.R_QUERY_FAILED.value

    def test_json_parse_error_maps(self):
        from illustrator_mcp.errors import LEGACY_CODE_MAP, ErrorCode

        assert LEGACY_CODE_MAP["JSON_PARSE_ERROR"] == ErrorCode.C_JSON_PARSE.value

    def test_preflight_error_maps(self):
        from illustrator_mcp.errors import LEGACY_CODE_MAP, ErrorCode

        assert LEGACY_CODE_MAP["PREFLIGHT_ERROR"] == ErrorCode.R_PREFLIGHT_FAILED.value

    def test_legacy_map_values_are_valid_error_codes(self):
        """Every value in LEGACY_CODE_MAP must be a valid ErrorCode."""
        from illustrator_mcp.errors import LEGACY_CODE_MAP, ErrorCode

        valid_values = {code.value for code in ErrorCode}
        for key, val in LEGACY_CODE_MAP.items():
            assert val in valid_values, (
                f"LEGACY_CODE_MAP['{key}'] = '{val}' is not a valid ErrorCode value"
            )


# =============================================================================
# Direct code lookup in classify_response
# =============================================================================

class TestDirectCodeLookup:
    """classify_response should use code field before regex when available."""

    def test_structured_error_with_code_uses_enum(self):
        """A dict error with a valid code field should resolve by enum lookup."""
        from illustrator_mcp.response_classification import classify_response

        response = {
            "result": json.dumps({
                "ok": False,
                "error": {
                    "code": "V011",
                    "message": "Parameter 'x' is out of range",
                }
            })
        }
        result = classify_response(response)
        assert not result.ok
        assert result.error_code == "V011"

    def test_structured_error_without_code_falls_back_to_regex(self):
        """A dict error without code field should fall back to regex classify."""
        from illustrator_mcp.response_classification import classify_response

        response = {
            "result": json.dumps({
                "ok": False,
                "error": {
                    "message": "ReferenceError: foo is not defined",
                }
            })
        }
        result = classify_response(response)
        assert not result.ok
        assert result.error_code == "S006"  # S_REFERENCE_ERROR

    def test_legacy_string_code_is_mapped(self):
        """An error with a legacy string code should be mapped via LEGACY_CODE_MAP."""
        from illustrator_mcp.response_classification import classify_response

        response = {
            "result": json.dumps({
                "ok": False,
                "error": {
                    "code": "QUERY_ERROR",
                    "message": "Something went wrong",
                }
            })
        }
        result = classify_response(response)
        assert not result.ok
        assert result.error_code == "R012"  # R_QUERY_FAILED

    def test_unknown_code_falls_back_to_regex(self):
        """An error with an unknown code should fall back to regex classify."""
        from illustrator_mcp.response_classification import classify_response

        response = {
            "result": json.dumps({
                "ok": False,
                "error": {
                    "code": "UNKNOWN_CODE_XYZ",
                    "message": "SyntaxError: unexpected token",
                }
            })
        }
        result = classify_response(response)
        assert not result.ok
        assert result.error_code == "S005"  # S_SYNTAX_ERROR via regex


# =============================================================================
# Contracts parity
# =============================================================================

class TestContractsParity:
    """contracts.jsx ErrorCodes must have full parity with Python ErrorCode."""

    def test_contracts_jsx_parity(self):
        """Every ErrorCode (name, value) pair must appear in contracts.jsx."""
        from illustrator_mcp.errors import ErrorCode
        from illustrator_mcp.tools.compile_contracts import error_codes_to_dict

        jsx_dict = error_codes_to_dict()

        # Check every ErrorCode member is in the JSX dict
        for code in ErrorCode:
            assert code.name in jsx_dict, (
                f"ErrorCode.{code.name} missing from contracts.jsx export"
            )
            assert jsx_dict[code.name] == code.value, (
                f"ErrorCode.{code.name}: Python={code.value}, JSX={jsx_dict[code.name]}"
            )

    def test_jsx_dict_has_no_extra_keys(self):
        """JSX dict should not contain keys that aren't in ErrorCode."""
        from illustrator_mcp.errors import ErrorCode
        from illustrator_mcp.tools.compile_contracts import error_codes_to_dict

        jsx_dict = error_codes_to_dict()
        python_names = {code.name for code in ErrorCode}
        extra = set(jsx_dict.keys()) - python_names
        assert not extra, f"Extra keys in JSX export: {extra}"
