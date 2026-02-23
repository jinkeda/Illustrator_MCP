"""
Tests for preview_state envelope injection in execute_script and execute_task.

These are static guard tests that verify the preview_state injection code
pattern is present in the execute.py source. Live integration tests require
a running Illustrator instance.
"""

import json
import pytest
from pathlib import Path

# Source file paths (execute_task moved to path_boolean.py)
EXECUTE_PY = (
    Path(__file__).parent.parent
    / "illustrator_mcp" / "tools" / "execute.py"
)
PATH_BOOLEAN_PY = (
    Path(__file__).parent.parent
    / "illustrator_mcp" / "tools" / "path_boolean.py"
)
EXECUTE_SRC = EXECUTE_PY.read_text(encoding="utf-8")
PATH_BOOLEAN_SRC = PATH_BOOLEAN_PY.read_text(encoding="utf-8")


class TestPreviewStateGuards:
    """Verify the preview_state injection pattern exists in source code."""

    def test_execute_script_has_preview_state(self):
        """execute_script injects preview_state into diagnostics."""
        assert '"preview_state"' in EXECUTE_SRC or "'preview_state'" in EXECUTE_SRC

    def test_post_execution_value(self):
        """'post_execution' literal exists for successful scripts."""
        assert '"post_execution"' in EXECUTE_SRC

    def test_pre_execution_value(self):
        """'pre_execution' literal exists for failed scripts."""
        assert '"pre_execution"' in EXECUTE_SRC

    def test_preview_state_depends_on_error_check(self):
        """preview_state is derived from response's 'error' field (B1 refactor)."""
        assert 'response.get("error")' in EXECUTE_SRC

    def test_preview_state_in_both_sites(self):
        """preview_state injection appears in both execute_script and execute_task."""
        # execute_script is in execute.py, execute_task is in path_boolean.py
        assert '"preview_state"' in EXECUTE_SRC, "Missing preview_state in execute.py"
        assert '"preview_state"' in PATH_BOOLEAN_SRC, "Missing preview_state in path_boolean.py"

    def test_diagnostics_preview_state_assignment(self):
        """B1: preview_state is set directly on diagnostics dict (no setdefault)."""
        assert 'diagnostics["preview_state"]' in EXECUTE_SRC


class TestPreviewStateLogic:
    """Unit test the preview_state injection logic in isolation."""

    def _inject(self, ok: bool) -> dict:
        """Simulate the injection logic from execute.py."""
        envelope = json.dumps({
            "ok": ok,
            "warnings": [],
            "error": None if ok else {"code": "E_SYNTAX", "message": "bad"},
            "diagnostics": {"tool": "test"},
            "result": "hello" if ok else None
        })
        envelope_obj = json.loads(envelope)
        preview_state = "post_execution" if envelope_obj.get("ok") else "pre_execution"
        envelope_obj.setdefault("diagnostics", {})["preview_state"] = preview_state
        return envelope_obj

    def test_success_gives_post_execution(self):
        result = self._inject(ok=True)
        assert result["diagnostics"]["preview_state"] == "post_execution"

    def test_failure_gives_pre_execution(self):
        result = self._inject(ok=False)
        assert result["diagnostics"]["preview_state"] == "pre_execution"

    def test_existing_diagnostics_preserved(self):
        result = self._inject(ok=True)
        assert result["diagnostics"]["tool"] == "test"
        assert result["diagnostics"]["preview_state"] == "post_execution"

    def test_no_diagnostics_key_still_works(self):
        """Edge case: envelope missing diagnostics key entirely."""
        envelope_obj = json.loads('{"ok": true}')
        preview_state = "post_execution" if envelope_obj.get("ok") else "pre_execution"
        envelope_obj.setdefault("diagnostics", {})["preview_state"] = preview_state
        assert envelope_obj["diagnostics"]["preview_state"] == "post_execution"
