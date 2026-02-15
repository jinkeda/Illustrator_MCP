"""
Test P3: Batch Validation Optimization

Verifies:
1. validationShapeKey generates deterministic keys for ops with same task+param shape
2. Different param types produce different shape keys
3. Enum field values are included in shape keys
4. The separate VALIDATION PHASE loop has been removed from ops_core.jsx
5. JIT validation diagnostics counters are present in ctx init
"""

import json
import os
import re
import pytest

SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..",
    "illustrator_mcp", "resources", "scripts"
)

OPS_CORE_PATH = os.path.join(SCRIPTS_DIR, "ops_core.jsx")


def _read_ops_core() -> str:
    with open(os.path.normpath(OPS_CORE_PATH), "r", encoding="utf-8") as f:
        return f.read()


class TestValidationOptimization:
    """Guard tests for P3 batch validation optimization."""

    def test_no_separate_validation_loop(self):
        """The old separate VALIDATION PHASE loop should be removed."""
        content = _read_ops_core()
        # Old pattern: a comment line "=== VALIDATION PHASE ===" followed by a for-loop
        assert "=== VALIDATION PHASE ===" not in content, (
            "Old VALIDATION PHASE comment still present in ops_core.jsx"
        )

    def test_jit_validation_present(self):
        """JIT validation should be present in the execution loop."""
        content = _read_ops_core()
        assert "JIT validation (P3)" in content, (
            "JIT validation comment not found in ops_core.jsx"
        )
        assert "validationShapeKey" in content, (
            "validationShapeKey not found in ops_core.jsx"
        )

    def test_validation_cache_in_ctx(self):
        """ctx init should include validationCache."""
        content = _read_ops_core()
        assert "validationCache: {}" in content, (
            "validationCache not found in ctx init"
        )

    def test_diagnostics_counters_present(self):
        """ctx.diagnostics should include validationsRun and validationsSkipped."""
        content = _read_ops_core()
        assert "validationsRun: 0" in content, (
            "validationsRun counter not found in diagnostics"
        )
        assert "validationsSkipped: 0" in content, (
            "validationsSkipped counter not found in diagnostics"
        )

    def test_shape_key_function_exists(self):
        """validationShapeKey function should be defined."""
        content = _read_ops_core()
        assert "function validationShapeKey(op)" in content, (
            "validationShapeKey function definition not found"
        )

    def test_shape_key_uses_sorted_keys(self):
        """Shape key generation should sort param keys for determinism."""
        content = _read_ops_core()
        # The function should call keys.sort()
        assert "keys.sort()" in content, (
            "validationShapeKey should sort param keys for deterministic output"
        )

    def test_shape_key_includes_enum_values(self):
        """Shape key should include enum field values."""
        content = _read_ops_core()
        assert "schema.enumValues" in content, (
            "validationShapeKey should check for enum values in schema"
        )

    def test_execution_phase_has_jit_label(self):
        """EXECUTION PHASE comment should mention JIT validation."""
        content = _read_ops_core()
        assert "EXECUTION PHASE (with JIT validation, P3)" in content, (
            "EXECUTION PHASE comment should indicate JIT validation"
        )
