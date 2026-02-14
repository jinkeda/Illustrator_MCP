"""
Tests for centralized library injection in the execution pipeline.

Verifies that:
1. Library injection happens in execute_script_with_context (proxy_client.py)
2. No tool file directly imports inject_libraries
3. includes parameter works correctly (None, [], valid, invalid)
4. Double-injection sentinel prevents re-injection
5. Response includes injection metadata when libraries are used
"""

import ast
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

from illustrator_mcp.libraries import INJECTION_SENTINEL, inject_libraries


# ==================== Regression: no tool file imports inject_libraries ====================

TOOL_FILES = [
    "illustrator_mcp/tools/base.py",
    "illustrator_mcp/tools/execute.py",
    "illustrator_mcp/tools/query.py",
    "illustrator_mcp/tools/documents.py",
]

PROJECT_ROOT = Path(__file__).parent.parent


def _get_imports(filepath: Path) -> list[str]:
    """Parse a Python file's AST and return all imported names."""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
    return names


@pytest.mark.unit
class TestNoToolFileImportsInjectLibraries:
    """Verify that tool files no longer directly import inject_libraries."""

    @pytest.mark.parametrize("tool_file", TOOL_FILES)
    def test_tool_file_does_not_import_inject_libraries(self, tool_file):
        filepath = PROJECT_ROOT / tool_file
        assert filepath.exists(), f"Tool file not found: {filepath}"
        imported_names = _get_imports(filepath)
        assert "inject_libraries" not in imported_names, (
            f"{tool_file} still imports inject_libraries — "
            f"injection should be delegated to execute_script_with_context"
        )


# ==================== Pipeline injection behavior ====================

@pytest.fixture
def mock_bridge_execute():
    """Mock _execute_via_bridge to return success without Illustrator."""
    async def fake_execute(script, timeout, command=None, trace_id=None):
        return {"result": '{"success": true}'}

    with patch("illustrator_mcp.proxy_client._execute_via_bridge", side_effect=fake_execute) as mock:
        yield mock


@pytest.fixture
def mock_bridge_capture():
    """Mock _execute_via_bridge that captures the script sent."""
    captured = {}

    async def fake_execute(script, timeout, command=None, trace_id=None):
        captured["script"] = script
        return {"result": '{"success": true}'}

    with patch("illustrator_mcp.proxy_client._execute_via_bridge", side_effect=fake_execute) as mock:
        mock.captured = captured
        yield mock


@pytest.mark.unit
class TestPipelineInjection:
    """Test that execute_script_with_context handles includes correctly."""

    @pytest.mark.asyncio
    async def test_includes_none_no_injection(self, mock_bridge_execute):
        """includes=None should not inject anything or add injection key."""
        from illustrator_mcp.proxy_client import execute_script_with_context

        response = await execute_script_with_context(
            script="var x = 1;",
            command_type="test",
            includes=None
        )
        assert "injection" not in response
        assert response.get("trace_id") is not None

    @pytest.mark.asyncio
    async def test_includes_empty_list_no_injection(self, mock_bridge_execute):
        """includes=[] should behave same as None — no injection."""
        from illustrator_mcp.proxy_client import execute_script_with_context

        response = await execute_script_with_context(
            script="var x = 1;",
            command_type="test",
            includes=[]
        )
        assert "injection" not in response

    @pytest.mark.asyncio
    async def test_includes_valid_library(self, mock_bridge_capture):
        """includes=["geometry"] should inject library and return metadata."""
        from illustrator_mcp.proxy_client import execute_script_with_context

        response = await execute_script_with_context(
            script="var x = 1;",
            command_type="test",
            includes=["geometry"]
        )

        # Response should have injection metadata
        assert "injection" in response
        inj = response["injection"]
        assert "geometry" in inj["includes_requested"]
        assert len(inj["includes_resolved"]) >= 1
        assert isinstance(inj["prelude_hash"], str) and len(inj["prelude_hash"]) > 0
        assert inj["prelude_length"] > 0
        assert isinstance(inj["library_versions"], dict)
        assert isinstance(inj["manifest_version"], str)

        # The script sent to bridge should contain the sentinel and library code
        sent_script = mock_bridge_capture.captured["script"]
        assert INJECTION_SENTINEL in sent_script
        assert "var x = 1;" in sent_script

    @pytest.mark.asyncio
    async def test_includes_nonexistent_library(self, mock_bridge_execute):
        """includes=["nonexistent"] should return V_LIBRARY_NOT_FOUND error."""
        from illustrator_mcp.proxy_client import execute_script_with_context

        response = await execute_script_with_context(
            script="var x = 1;",
            command_type="test",
            includes=["nonexistent_lib_xyz"]
        )

        assert response.get("ok") is False
        assert "V009" in response.get("error", "")
        # Bridge should NOT have been called
        mock_bridge_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_double_injection_sentinel_skips(self, mock_bridge_capture):
        """Script already containing sentinel should skip injection."""
        from illustrator_mcp.proxy_client import execute_script_with_context

        # Pre-inject manually to simulate already-injected script
        pre_injected = inject_libraries("var x = 1;", ["geometry"])
        assert INJECTION_SENTINEL in pre_injected

        response = await execute_script_with_context(
            script=pre_injected,
            command_type="test",
            includes=["geometry"]
        )

        # Should still succeed (sentinel guard skips double injection)
        assert response.get("error") is None
        # No injection metadata since injection was skipped
        assert "injection" not in response

    @pytest.mark.asyncio
    async def test_injection_metadata_schema(self, mock_bridge_capture):
        """Verify the full injection metadata schema."""
        from illustrator_mcp.proxy_client import execute_script_with_context

        response = await execute_script_with_context(
            script="var x = 1;",
            command_type="test",
            includes=["geometry"]
        )

        inj = response["injection"]
        expected_keys = {
            "includes_requested",
            "includes_resolved",
            "prelude_hash",
            "prelude_length",
            "library_versions",
            "manifest_version",
        }
        assert set(inj.keys()) == expected_keys


# ==================== Error classification ====================

@pytest.mark.unit
class TestErrorClassification:
    """Test that pipeline-formatted error codes are properly classified."""

    def test_v009_pattern(self):
        from illustrator_mcp.errors import classify_error, ErrorCode
        assert classify_error("[V009] Unknown library: foo") == ErrorCode.V_LIBRARY_NOT_FOUND

    def test_v010_pattern(self):
        from illustrator_mcp.errors import classify_error, ErrorCode
        assert classify_error("[V010] Symbol collision: bar") == ErrorCode.V_LIBRARY_CONFLICT

    def test_s010_pattern(self):
        from illustrator_mcp.errors import classify_error, ErrorCode
        assert classify_error("[S010] Library file I/O failure") == ErrorCode.S_LIBRARY_IO

    def test_s011_pattern(self):
        from illustrator_mcp.errors import classify_error, ErrorCode
        assert classify_error("[S011] Manifest parse error") == ErrorCode.S_MANIFEST_ERROR

    def test_r010_pattern(self):
        from illustrator_mcp.errors import classify_error, ErrorCode
        assert classify_error("[R010] injection failed unexpectedly") == ErrorCode.R_INJECTION_FAILED

    def test_unknown_library_text_pattern(self):
        from illustrator_mcp.errors import classify_error, ErrorCode
        assert classify_error("Unknown library: geometry") == ErrorCode.V_LIBRARY_NOT_FOUND
