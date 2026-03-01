"""
Tests for PR-C: Batch Diagnostics Improvements.

Covers:
- opSummary compact per-op summary in slimmed batchReport
- opSummaryTruncated flag when > 200 ops
- items param documentation in compute_soc_batch.jsx
"""

import re
from pathlib import Path

import pytest


class TestOpSummarySlimming:
    """Tests for compact opSummary in batchReport slimming."""

    TASK_EXEC = (
        Path(__file__).resolve().parent.parent
        / "illustrator_mcp" / "tools" / "task_execution.py"
    )

    def _get_slimming_block(self) -> str:
        """Extract the JSX slimming block from task_execution.py."""
        content = self.TASK_EXEC.read_text(encoding="utf-8")
        # Find the slimming block (between ── Slim and report.batchReport = _slim)
        match = re.search(
            r"// ── Slim batchReport.*?report\.batchReport = _slim;",
            content,
            re.DOTALL,
        )
        assert match, "Slimming block not found in task_execution.py"
        return match.group(0)

    def test_slim_has_op_summary_field(self):
        """Slimmed batchReport includes opSummary array."""
        block = self._get_slimming_block()
        assert "opSummary:" in block and "[]" in block

    def test_slim_has_truncation_flag(self):
        """Slimmed batchReport includes opSummaryTruncated flag."""
        block = self._get_slimming_block()
        assert "opSummaryTruncated:" in block

    def test_op_summary_has_required_fields(self):
        """Each opSummary entry includes task, ok, tr, mod, err."""
        block = self._get_slimming_block()
        for field in ["task:", "ok:", "tr:", "mod:", "err:"]:
            assert field in block, f"opSummary missing field: {field}"

    def test_op_summary_has_cap(self):
        """opSummary is capped at a max count (200)."""
        block = self._get_slimming_block()
        assert "_maxSummary" in block, "opSummary must have a max cap variable"
        # Verify the cap value
        cap_match = re.search(r"_maxSummary\s*=\s*(\d+)", block)
        assert cap_match, "Could not find _maxSummary value"
        cap = int(cap_match.group(1))
        assert cap == 200, f"Expected cap of 200, got {cap}"

    def test_op_summary_truncation_sets_flag(self):
        """When ops exceed cap, opSummaryTruncated is set to true."""
        block = self._get_slimming_block()
        # Should check if ops.length > _maxSummary
        assert "_maxSummary" in block
        assert "opSummaryTruncated = true" in block

    def test_op_summary_err_extracts_error_code(self):
        """err field extracts error.code, not the full error object."""
        block = self._get_slimming_block()
        assert ".error.code" in block, (
            "err field should extract error.code for compact representation"
        )

    def test_op_summary_mod_uses_typeof_guard(self):
        """mod field uses typeof guard to handle modified:0 correctly."""
        block = self._get_slimming_block()
        assert 'typeof _op.data.modified === "number"' in block, (
            "mod field must use typeof guard (modified:0 is falsy)"
        )

    def test_watchdog_in_summary_loop(self):
        """opSummary loop calls __mcp_check() (watchdog)."""
        block = self._get_slimming_block()
        # Should have __mcp_check inside the opSummary loop
        assert "__mcp_check()" in block


class TestComputeDocumentation:
    """Tests for compute_soc_batch.jsx documentation."""

    COMPUTE_JSX = (
        Path(__file__).resolve().parent.parent
        / "illustrator_mcp" / "resources" / "templates"
        / "compute_soc_batch.jsx"
    )

    def test_items_param_documented_as_intentional(self):
        """compute() documents that items param is intentionally unused."""
        content = self.COMPUTE_JSX.read_text(encoding="utf-8")
        assert "intentionally" in content.lower(), (
            "compute() should document that items is intentionally unused"
        )

    def test_o1_claim_qualified(self):
        """O(1) claim for heap lookup is properly qualified."""
        content = self.COMPUTE_JSX.read_text(encoding="utf-8")
        assert "typically O(1)" in content, (
            "O(1) claim should be qualified as 'typically O(1)'"
        )
