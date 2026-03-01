"""
Tests for PR-A: Schema Consolidation + Handler Normalizer.

Covers:
- Compat forwarder for op_schemas.jsx
- normalizeHandlerResult() in ops_core.jsx
- Runtime schema regression test for gradient 'type' optional
- contracts.jsx contains all required exports
"""

import re
from pathlib import Path

import pytest


SCRIPTS_DIR = (
    Path(__file__).resolve().parent.parent
    / "illustrator_mcp" / "resources" / "scripts"
)


class TestCompatForwarder:
    """Tests for op_schemas.jsx compat forwarder."""

    OP_SCHEMAS_JSX = SCRIPTS_DIR / "op_schemas.jsx"
    CONTRACTS_JSX = SCRIPTS_DIR / "contracts.jsx"

    def test_op_schemas_is_compat_forwarder(self):
        """op_schemas.jsx is a thin compat forwarder, not full schemas."""
        content = self.OP_SCHEMAS_JSX.read_text(encoding="utf-8")
        # Should be small (< 50 lines vs the original 886)
        lines = content.strip().split("\n")
        assert len(lines) < 50, (
            f"op_schemas.jsx should be a thin forwarder, got {len(lines)} lines"
        )

    def test_op_schemas_has_deprecation_banner(self):
        """op_schemas.jsx contains deprecation notice."""
        content = self.OP_SCHEMAS_JSX.read_text(encoding="utf-8")
        assert "DEPRECATED" in content
        assert "contracts.jsx" in content

    def test_op_schemas_has_guard(self):
        """op_schemas.jsx checks if contracts.jsx was loaded."""
        content = self.OP_SCHEMAS_JSX.read_text(encoding="utf-8")
        assert "OP_PARAM_SCHEMAS" in content
        assert "undefined" in content

    def test_op_schemas_does_not_define_schemas(self):
        """op_schemas.jsx must NOT define its own OP_PARAM_SCHEMAS object."""
        content = self.OP_SCHEMAS_JSX.read_text(encoding="utf-8")
        # Should not have 'var OP_PARAM_SCHEMAS = {' (the old definition)
        assert "var OP_PARAM_SCHEMAS" not in content, (
            "op_schemas.jsx must not define OP_PARAM_SCHEMAS — contracts.jsx owns it"
        )

    def test_contracts_has_all_required_exports(self):
        """contracts.jsx defines all required symbols."""
        content = self.CONTRACTS_JSX.read_text(encoding="utf-8")
        for symbol in ["OP_PARAM_SCHEMAS", "validateOpParams", "getOpSchema", "listSchemaOps"]:
            assert f"function {symbol}" in content or f"var {symbol}" in content, (
                f"contracts.jsx must define {symbol}"
            )


class TestNormalizeHandlerResult:
    """Tests for normalizeHandlerResult() in ops_core.jsx."""

    OPS_CORE_JSX = SCRIPTS_DIR / "ops_core.jsx"

    def _get_normalizer_fn(self):
        """Extract the normalizeHandlerResult function body."""
        content = self.OPS_CORE_JSX.read_text(encoding="utf-8")
        match = re.search(
            r"function normalizeHandlerResult\(.*?\n\}",
            content,
            re.DOTALL,
        )
        assert match, "normalizeHandlerResult function not found in ops_core.jsx"
        return match.group(0)

    def test_normalizer_exists(self):
        """normalizeHandlerResult is defined in ops_core.jsx."""
        self._get_normalizer_fn()  # Asserts internally

    def test_normalizer_handles_null(self):
        """Normalizer handles null/undefined input."""
        body = self._get_normalizer_fn()
        assert "!raw" in body, "Normalizer must handle null/undefined"
        assert "ok: true" in body, "Null input should produce ok:true"

    def test_normalizer_extracts_modified(self):
        """Normalizer extracts modified count from data."""
        body = self._get_normalizer_fn()
        assert "d.modified" in body, "Normalizer must extract modified field"

    def test_normalizer_canonicalizes_ids(self):
        """Normalizer converts data.ids to data.createdIds."""
        body = self._get_normalizer_fn()
        assert "d.ids" in body, "Normalizer must check for ids field"
        assert "createdIds" in body, "Normalizer must output createdIds"

    def test_normalizer_preserves_extra_fields(self):
        """Normalizer preserves unknown data fields."""
        body = self._get_normalizer_fn()
        assert "hasOwnProperty" in body, (
            "Normalizer must iterate and preserve extra fields"
        )

    def test_normalizer_wired_at_handler_site(self):
        """normalizeHandlerResult is called after handler invocation."""
        content = self.OPS_CORE_JSX.read_text(encoding="utf-8")
        # Should have: handlerResult = normalizeHandlerResult(op.task, handlerResult);
        assert "normalizeHandlerResult(op.task, handlerResult)" in content, (
            "normalizeHandlerResult must be wired at the handler call site"
        )

    def test_normalizer_documented(self):
        """normalizeHandlerResult has JSDoc with input/output shapes."""
        content = self.OPS_CORE_JSX.read_text(encoding="utf-8")
        # Find the doc block before the function
        idx = content.index("function normalizeHandlerResult")
        doc_block = content[max(0, idx - 1000):idx]
        assert "@param" in doc_block, "Normalizer must have @param documentation"
        assert "@returns" in doc_block, "Normalizer must have @returns documentation"


class TestGradientSchemaRegression:
    """Regression test: style_set_gradient 'type' must be optional at runtime."""

    CONTRACTS_JSX = SCRIPTS_DIR / "contracts.jsx"

    def test_style_set_gradient_type_optional(self):
        """style_set_gradient schema must NOT require 'type' field."""
        content = self.CONTRACTS_JSX.read_text(encoding="utf-8")

        # Find the style_set_gradient schema entry and its required array
        idx = content.find('"style_set_gradient"')
        assert idx != -1, "style_set_gradient schema not found in contracts.jsx"

        # Extract the required array from the schema block
        schema_chunk = content[idx:idx + 300]  # enough to cover the schema
        req_match = re.search(r'"required"\s*:\s*\[(.*?)\]', schema_chunk, re.DOTALL)
        assert req_match, "required array not found in style_set_gradient schema"

        required_str = req_match.group(1)
        # 'type' should NOT be in the required list
        assert '"type"' not in required_str, (
            "style_set_gradient 'type' must be optional (not in required). "
            "This was the original gradient drift bug."
        )
