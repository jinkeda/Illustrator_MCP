"""
Test: element_replace static guards and withTransaction helper.

Verifies:
1. element_replace handler is registered in ops_element.jsx
2. Sandbox pattern (__mcp_replace_sandbox__) is present
3. Tombstone call for old MCP IDs
4. Z-order uses PLACEAFTER / PLACEBEFORE
5. Failure path cleans up sandbox
6. withTransaction function exists in ops_core.jsx
7. element_replace is in MUTATING_OPS
8. element_replace schema is in contracts.py
"""

import os
import re
import pytest

SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..",
    "illustrator_mcp", "resources", "scripts"
)

OPS_ELEMENT_PATH = os.path.normpath(os.path.join(SCRIPTS_DIR, "ops_element.jsx"))
OPS_CORE_PATH = os.path.normpath(os.path.join(SCRIPTS_DIR, "ops_core.jsx"))
CONTRACTS_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..",
                 "illustrator_mcp", "schemas", "contracts.py")
)


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class TestElementReplaceHandler:
    """Guard tests for element_replace in ops_element.jsx."""

    def test_handler_registered(self):
        """element_replace handler should be registered."""
        content = _read(OPS_ELEMENT_PATH)
        assert 'registerOpHandler("element_replace"' in content, (
            "element_replace handler not registered in ops_element.jsx"
        )

    def test_sandbox_pattern(self):
        """Should use __mcp_replace_sandbox__ group pattern."""
        content = _read(OPS_ELEMENT_PATH)
        assert "__mcp_replace_sandbox__" in content, (
            "Sandbox group name not found in element_replace"
        )

    def test_tombstone_call(self):
        """Should tombstone old MCP ID before removal."""
        content = _read(OPS_ELEMENT_PATH)
        assert "heapTombstone" in content, (
            "heapTombstone call not found in element_replace"
        )

    def test_z_order_placement(self):
        """Should use ElementPlacement.PLACEAFTER for z-order."""
        # Find the element_replace section
        content = _read(OPS_ELEMENT_PATH)
        replace_section = content[content.index('"element_replace"'):]
        assert "ElementPlacement.PLACEAFTER" in replace_section, (
            "PLACEAFTER not used for z-order anchoring"
        )
        assert "ElementPlacement.PLACEBEFORE" in replace_section, (
            "PLACEBEFORE not used for unpacking from sandbox"
        )

    def test_sandbox_cleanup_on_failure(self):
        """Failure path should remove sandbox."""
        content = _read(OPS_ELEMENT_PATH)
        replace_section = content[content.index('"element_replace"'):]
        assert "sandbox.remove()" in replace_section, (
            "sandbox.remove() not found in failure path"
        )

    def test_single_target_validation(self):
        """Should validate exactly 1 target."""
        content = _read(OPS_ELEMENT_PATH)
        replace_section = content[content.index('"element_replace"'):]
        assert "targets.length !== 1" in replace_section, (
            "Single-target validation not found"
        )

    def test_inherit_position_default(self):
        """inheritPosition should default to true."""
        content = _read(OPS_ELEMENT_PATH)
        replace_section = content[content.index('"element_replace"'):]
        assert "params.inheritPosition !== false" in replace_section, (
            "inheritPosition default-true logic not found"
        )

    def test_locked_restore_on_failure(self):
        """Should restore locked state if we unlocked old item and creation fails."""
        content = _read(OPS_ELEMENT_PATH)
        replace_section = content[content.index('"element_replace"'):]
        # The catch block should re-lock if oldLocked
        assert "oldItem.locked = true" in replace_section, (
            "Locked state restore not found in failure path"
        )


class TestWithTransaction:
    """Guard tests for withTransaction in ops_core.jsx."""

    def test_function_exists(self):
        """withTransaction should be defined in ops_core.jsx."""
        content = _read(OPS_CORE_PATH)
        assert "function withTransaction(" in content, (
            "withTransaction function not found in ops_core.jsx"
        )

    def test_captures_snapshot(self):
        """withTransaction should call captureSnapshot."""
        content = _read(OPS_CORE_PATH)
        # Find the withTransaction section
        tx_start = content.index("function withTransaction(")
        tx_section = content[tx_start:tx_start + 500]
        assert "captureSnapshot" in tx_section, (
            "captureSnapshot not called in withTransaction"
        )

    def test_restores_on_error(self):
        """withTransaction should restoreSnapshot on error."""
        content = _read(OPS_CORE_PATH)
        tx_start = content.index("function withTransaction(")
        tx_section = content[tx_start:tx_start + 500]
        assert "restoreSnapshot" in tx_section, (
            "restoreSnapshot not called in withTransaction error path"
        )

    def test_returns_structured_envelope(self):
        """withTransaction should return ok/rolledBack envelope."""
        content = _read(OPS_CORE_PATH)
        tx_start = content.index("function withTransaction(")
        tx_section = content[tx_start:tx_start + 500]
        assert "rolledBack" in tx_section, (
            "Structured envelope (rolledBack) not in withTransaction"
        )

    def test_doc_explicit_parameter(self):
        """withTransaction should take doc as first param (multi-doc safe)."""
        content = _read(OPS_CORE_PATH)
        assert "function withTransaction(doc, fn, opts)" in content, (
            "withTransaction signature should be (doc, fn, opts)"
        )


class TestMutatingOpsInclusion:
    """Verify element_replace is in MUTATING_OPS."""

    def test_element_replace_in_mutating_ops(self):
        """element_replace should be in MUTATING_OPS."""
        content = _read(OPS_CORE_PATH)
        assert '"element_replace": true' in content, (
            "element_replace not in MUTATING_OPS"
        )


class TestContractsSchema:
    """Verify element_replace schema exists in contracts.py."""

    def test_schema_defined(self):
        """element_replace schema should be in OP_SCHEMAS."""
        content = _read(CONTRACTS_PATH)
        assert 'name="element_replace"' in content, (
            "element_replace schema not found in contracts.py"
        )

    def test_type_required(self):
        """type param should be required for element_replace."""
        content = _read(CONTRACTS_PATH)
        # Find the element_replace section
        start = content.index('name="element_replace"')
        section = content[start:start + 800]
        assert "required=True" in section, (
            "type param not marked required in element_replace schema"
        )

    def test_inherit_position_param(self):
        """inheritPosition param should be in the schema."""
        content = _read(CONTRACTS_PATH)
        start = content.index('name="element_replace"')
        section = content[start:start + 1500]
        assert '"inheritPosition"' in section, (
            "inheritPosition param not found in element_replace schema"
        )
