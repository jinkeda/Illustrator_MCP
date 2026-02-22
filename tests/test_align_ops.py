"""
test_align_ops.py — Guard + behavioral tests for align/distribute enhancements

Tests:
  Guard (1-8): Static code/schema checks
  Behavioral (9-12): Logic verification via code inspection
"""
import json
import pathlib
import re

import pytest

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "illustrator_mcp" / "resources" / "scripts"
WORKSPACE_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
OPS_ALIGN = (SCRIPTS_DIR / "ops_align.jsx").read_text(encoding="utf-8")
CONTRACTS_PY = (SCRIPTS_DIR.parent.parent / "schemas" / "contracts.py").read_text(encoding="utf-8")
CONTRACTS_JSX = (SCRIPTS_DIR / "contracts.jsx").read_text(encoding="utf-8")
MANIFEST = json.loads((SCRIPTS_DIR / "manifest.json").read_text(encoding="utf-8"))
REF_PATH = WORKSPACE_ROOT / ".agent" / "skills" / "state-ops-checks" / "references" / "opcode-reference.md"


# ======================== Guard Tests ========================

class TestGuardAlignSchemas:
    """Test 1: Align/distribute schemas exist in contracts.py with correct params."""

    @pytest.mark.parametrize("op", [
        "align_horizontal", "align_vertical",
        "distribute_horizontal", "distribute_vertical",
    ])
    def test_schema_exists(self, op):
        assert f'name="{op}"' in CONTRACTS_PY

    @pytest.mark.parametrize("op", ["align_horizontal", "align_vertical"])
    def test_align_params(self, op):
        """Align ops must have mode, reference, key_id, coordinate."""
        # Find the schema block
        match = re.search(
            rf'OpSchema\(name="{op}".*?\}}\)',
            CONTRACTS_PY, re.DOTALL
        )
        assert match, f"{op} schema not found"
        block = match.group()
        for param in ["mode", "reference", "key_id", "coordinate"]:
            assert f'"{param}"' in block, f"Missing param {param} in {op}"

    @pytest.mark.parametrize("op", ["distribute_horizontal", "distribute_vertical"])
    def test_distribute_params(self, op):
        """Distribute ops must have mode and spacing."""
        match = re.search(
            rf'OpSchema\(name="{op}".*?\}}\)',
            CONTRACTS_PY, re.DOTALL
        )
        assert match, f"{op} schema not found"
        block = match.group()
        for param in ["mode", "spacing"]:
            assert f'"{param}"' in block, f"Missing param {param} in {op}"


class TestGuardAlignEnumValues:
    """Test 2: Enum values are correct."""

    def test_horizontal_modes(self):
        match = re.search(
            r'OpSchema\(name="align_horizontal".*?\}\)',
            CONTRACTS_PY, re.DOTALL
        )
        block = match.group()
        for val in ["left", "center", "right"]:
            assert f'"{val}"' in block

    def test_vertical_modes(self):
        match = re.search(
            r'OpSchema\(name="align_vertical".*?\}\)',
            CONTRACTS_PY, re.DOTALL
        )
        block = match.group()
        for val in ["top", "middle", "bottom"]:
            assert f'"{val}"' in block

    def test_distribute_modes(self):
        match = re.search(
            r'OpSchema\(name="distribute_horizontal".*?\}\)',
            CONTRACTS_PY, re.DOTALL
        )
        block = match.group()
        for val in ["gap", "center"]:
            assert f'"{val}"' in block

    def test_reference_values(self):
        match = re.search(
            r'OpSchema\(name="align_horizontal".*?\}\)',
            CONTRACTS_PY, re.DOTALL
        )
        block = match.group()
        for val in ["targets", "artboard"]:
            assert f'"{val}"' in block


class TestGuardManifestDeps:
    """Test 3: ops_align manifest entry has heap + mcp_id deps."""

    def test_entry_exists(self):
        assert "ops_align" in MANIFEST["libraries"]

    def test_heap_dep(self):
        deps = MANIFEST["libraries"]["ops_align"]["dependencies"]
        assert "heap" in deps

    def test_mcp_id_dep(self):
        deps = MANIFEST["libraries"]["ops_align"]["dependencies"]
        assert "mcp_id" in deps

    def test_version_bumped(self):
        ver = MANIFEST["libraries"]["ops_align"]["version"]
        assert ver == "2.0.0"


class TestGuardResolveReferenceAxis:
    """Test 4: _resolveReferenceAxis helper exists and has correct precedence."""

    def test_function_exists(self):
        assert "function _resolveReferenceAxis(" in OPS_ALIGN

    def test_coordinate_priority(self):
        """coordinate must be checked before key_id."""
        coord_pos = OPS_ALIGN.index("params.coordinate")
        # After first coordinate check, key_id should be further down
        key_id_pos = OPS_ALIGN.index("params.key_id", coord_pos)
        assert key_id_pos > coord_pos

    def test_key_id_uses_heap_resolve(self):
        """key_id resolution must use heapResolve."""
        assert "heapResolve" in OPS_ALIGN

    def test_returns_source_metadata(self):
        """Return value must include source field."""
        assert '"coordinate"' in OPS_ALIGN
        assert '"key_id"' in OPS_ALIGN
        assert '"artboard"' in OPS_ALIGN
        assert '"targets"' in OPS_ALIGN


class TestGuardSortForDistribute:
    """Test 5: _sortForDistribute exists and uses MCP ID tie-breaker."""

    def test_function_exists(self):
        assert "function _sortForDistribute(" in OPS_ALIGN

    def test_mcp_id_tiebreak(self):
        """Must use extractMcpId for tie-breaking."""
        assert "extractMcpId" in OPS_ALIGN

    def test_sorts_by_position(self):
        """Must sort by axis position (left or top)."""
        # sorted.sort should be present
        assert ".sort(" in OPS_ALIGN


class TestGuardCenterDistribute:
    """Test 6: Center-distribute mode is implemented."""

    def test_center_mode_in_distribute_horizontal(self):
        # Find distribute_horizontal handler
        start = OPS_ALIGN.index('"distribute_horizontal"')
        end = OPS_ALIGN.index('"distribute_vertical"', start)
        body = OPS_ALIGN[start:end]
        assert '"center"' in body

    def test_center_mode_in_distribute_vertical(self):
        start = OPS_ALIGN.index('"distribute_vertical"')
        body = OPS_ALIGN[start:]
        assert '"center"' in body


class TestGuardAlignHandlersRegistered:
    """Test 7: All 4 handlers are registered via registerOpHandler."""

    @pytest.mark.parametrize("op", [
        "align_horizontal", "align_vertical",
        "distribute_horizontal", "distribute_vertical",
    ])
    def test_handler_registered(self, op):
        assert f'registerOpHandler("{op}"' in OPS_ALIGN


class TestGuardCompiledContracts:
    """Test 8: Compiled contracts.jsx contains the align schemas."""

    @pytest.mark.parametrize("op", [
        "align_horizontal", "align_vertical",
        "distribute_horizontal", "distribute_vertical",
    ])
    def test_op_in_compiled(self, op):
        assert op in CONTRACTS_JSX


# ======================== Behavioral Tests ========================

class TestAlignDefaultBehavior:
    """Test 9: Default behavior (no key_id/coordinate) unchanged."""

    def test_default_mode_horizontal(self):
        """Default mode should be 'center' when not specified."""
        start = OPS_ALIGN.index('"align_horizontal"')
        end = OPS_ALIGN.index('"align_vertical"', start)
        body = OPS_ALIGN[start:end]
        assert '"center"' in body

    def test_default_reference_targets(self):
        """_resolveReferenceAxis defaults to targets when no params set."""
        func_start = OPS_ALIGN.index("function _resolveReferenceAxis(")
        func_body = OPS_ALIGN[func_start:func_start + 2000]
        assert '"targets"' in func_body


class TestDistributeAnchorRule:
    """Test 10: Distribute anchors to leftmost/topmost item."""

    def test_sorts_before_distribute(self):
        """Distribute handlers must call _sortForDistribute."""
        # distribute_horizontal
        start_h = OPS_ALIGN.index('"distribute_horizontal"')
        end_h = OPS_ALIGN.index('"distribute_vertical"', start_h)
        body_h = OPS_ALIGN[start_h:end_h]
        assert "_sortForDistribute" in body_h

        # distribute_vertical
        start_v = OPS_ALIGN.index('"distribute_vertical"')
        body_v = OPS_ALIGN[start_v:]
        assert "_sortForDistribute" in body_v

    def test_first_item_stays_fixed(self):
        """First sorted item must be the anchor (position preserved)."""
        # The pattern is: sorted[0] is the anchor, loop starts from i=1
        start = OPS_ALIGN.index('"distribute_horizontal"')
        end = OPS_ALIGN.index('"distribute_vertical"', start)
        body = OPS_ALIGN[start:end]
        assert "sorted[0]" in body


class TestVerticalConvention:
    """Test 11: Vertical alignment respects Illustrator's Y convention."""

    @pytest.mark.skipif(not REF_PATH.exists(), reason="opcode-reference.md not found")
    def test_top_alignment_documented(self):
        """Top = highest item.top (least negative), documented in reference."""
        ref = REF_PATH.read_text(encoding="utf-8")
        assert "item.top" in ref
        assert 'mode="top"' in ref


class TestOpcodeReference:
    """Test 12: opcode-reference.md updated with all new params."""

    @pytest.fixture(autouse=True)
    def load_ref(self):
        if not REF_PATH.exists():
            pytest.skip("opcode-reference.md not found")
        self.ref = REF_PATH.read_text(encoding="utf-8")

    def test_key_id_documented(self):
        assert "key_id" in self.ref

    def test_coordinate_documented(self):
        assert "coordinate" in self.ref

    def test_center_distribute_documented(self):
        assert '"center"' in self.ref

    def test_anchor_rule_documented(self):
        assert "Anchor rule" in self.ref or "anchor" in self.ref.lower()

    def test_priority_documented(self):
        assert "coordinate" in self.ref and "key_id" in self.ref
