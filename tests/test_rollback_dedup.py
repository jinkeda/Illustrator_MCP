"""
Test A2: Rollback Code Deduplication

Verifies:
1. rollbackBatch helper function exists in ops_core.jsx
2. Only single-line calls remain (no duplicated rollback blocks)
3. Old patterns (cidSet2, createdDeleted2) removed
"""

import os
import re
import pytest

SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..",
    "illustrator_mcp", "resources", "scripts"
)

OPS_CORE_PATH = os.path.normpath(os.path.join(SCRIPTS_DIR, "ops_core.jsx"))


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class TestRollbackDedup:
    """Guard tests for A2 rollback code deduplication."""

    def test_rollback_batch_function_exists(self):
        """rollbackBatch helper function should be defined."""
        content = _read(OPS_CORE_PATH)
        assert "function rollbackBatch(" in content, (
            "rollbackBatch function definition not found in ops_core.jsx"
        )

    def test_rollback_batch_called_twice(self):
        """rollbackBatch should be called exactly twice in executeOpBatch."""
        content = _read(OPS_CORE_PATH)
        calls = re.findall(r'rollbackBatch\(doc,', content)
        # One in the function definition's body, two at call sites
        # Actually the definition uses different var names, so calls are the ones matching 'rollbackBatch(doc,'
        # But the definition is 'function rollbackBatch(doc,' which also matches
        # Let's count non-definition calls
        call_count = content.count("= rollbackBatch(")
        assert call_count == 2, (
            f"Expected 2 call sites for rollbackBatch, found {call_count}"
        )

    def test_no_duplicated_cidset_variables(self):
        """Old duplicated variable names (cidSet2, createdDeleted2) should be gone."""
        content = _read(OPS_CORE_PATH)
        assert "cidSet2" not in content, (
            "Old duplicated variable cidSet2 still present"
        )
        assert "createdDeleted2" not in content, (
            "Old duplicated variable createdDeleted2 still present"
        )

    def test_no_duplicated_loop_variables(self):
        """Old duplicated loop variables (lx2, px2, pi2, pn2, pm2) should be gone."""
        content = _read(OPS_CORE_PATH)
        for var in ["lx2", "px2", "pi2", "pn2", "pm2"]:
            assert var not in content, (
                f"Old duplicated variable {var} still present in ops_core.jsx"
            )

    def test_rollback_helper_has_jsdoc(self):
        """rollbackBatch should have a JSDoc comment."""
        content = _read(OPS_CORE_PATH)
        assert "Rollback Helper (A2)" in content, (
            "rollbackBatch section header not found"
        )
