"""
test_clip_ops.py — Tests for clip_create SOC operation.

Tests schema validation, static analysis of the ExtendScript handler,
and behavioral contracts for the duplicate_mask feature.
Run: python -m pytest tests/test_clip_ops.py -v
"""

import json
import os
import re
import pytest

from illustrator_mcp.schemas.contracts import OP_SCHEMA_MAP, get_op_schema


# ── Schema tests ──────────────────────────────────────────────────────


class TestClipCreateSchema:
    def test_schema_valid(self):
        """clip_create exists in contracts with required params."""
        schema = get_op_schema("clip_create")
        assert schema is not None
        assert schema.name == "clip_create"
        assert "mask" in schema.params
        assert "contents" in schema.params
        assert schema.params["mask"].required is True
        assert schema.params["contents"].required is True

    def test_optional_params(self):
        """id, name, dryRun, duplicate_mask are optional."""
        schema = get_op_schema("clip_create")
        assert schema.params["id"].required is False
        assert schema.params["name"].required is False
        assert schema.params["dryRun"].required is False
        assert schema.params["duplicate_mask"].required is False

    def test_dryrun_in_schema(self):
        """dryRun param exists and is boolean type."""
        schema = get_op_schema("clip_create")
        assert schema.params["dryRun"].type.value == "boolean"

    def test_mask_is_string(self):
        """mask param is string type (MCP ID)."""
        schema = get_op_schema("clip_create")
        assert schema.params["mask"].type.value == "string"

    def test_contents_is_array(self):
        """contents param is array type."""
        schema = get_op_schema("clip_create")
        assert schema.params["contents"].type.value == "array"

    def test_duplicate_mask_in_schema(self):
        """duplicate_mask param exists, is boolean, and has description."""
        schema = get_op_schema("clip_create")
        dm = schema.params["duplicate_mask"]
        assert dm.type.value == "boolean"
        assert dm.description is not None
        assert "duplicate" in dm.description.lower()


# ── Static handler guard tests ────────────────────────────────────────


class TestClipCreateStaticGuards:
    """Verify the ExtendScript handler source contains critical guards."""

    @pytest.fixture(autouse=True)
    def load_handler_source(self):
        """Load ops_group.jsx source for static analysis."""
        handler_path = os.path.join(
            os.path.dirname(__file__), "..",
            "illustrator_mcp", "resources", "scripts", "ops_group.jsx"
        )
        with open(handler_path, "r", encoding="utf-8") as f:
            self.source = f.read()

    def test_mask_type_guard(self):
        """Handler checks mask type is PathItem or CompoundPathItem."""
        assert "PathItem" in self.source
        assert "CompoundPathItem" in self.source
        assert 'maskType !== "PathItem"' in self.source
        assert 'maskType !== "CompoundPathItem"' in self.source

    def test_parent_aware_guard(self):
        """Handler uses mask.parent (not mask.layer) for placement."""
        assert "maskItem.parent" in self.source

    def test_mask_in_contents_guard(self):
        """Handler rejects mask ID appearing in contents."""
        assert "contentIds[ci] === maskId" in self.source

    def test_dryryn_early_return(self):
        """Handler has dryRun early return without mutation."""
        assert "dryRun" in self.source
        assert "parentType" in self.source
        assert "parentName" in self.source

    def test_reverse_content_stacking(self):
        """Handler moves content in reverse order to preserve stacking."""
        assert "contents.length - 1" in self.source


# ── duplicate_mask static guards ──────────────────────────────────────


class TestDuplicateMaskStaticGuards:
    """Verify the duplicate_mask code paths in ops_group.jsx."""

    @pytest.fixture(autouse=True)
    def load_handler_source(self):
        handler_path = os.path.join(
            os.path.dirname(__file__), "..",
            "illustrator_mcp", "resources", "scripts", "ops_group.jsx"
        )
        with open(handler_path, "r", encoding="utf-8") as f:
            self.source = f.read()

    def test_duplicate_mask_default_true(self):
        """Handler defaults duplicate_mask to true (params.duplicate_mask !== false)."""
        assert "params.duplicate_mask !== false" in self.source

    def test_handler_calls_duplicate(self):
        """duplicate_mask=true path calls maskItem.duplicate()."""
        assert "maskItem.duplicate()" in self.source

    def test_strip_appearance_function_exists(self):
        """stripAppearance helper is defined."""
        assert "function stripAppearance" in self.source

    def test_strip_handles_compound_path(self):
        """stripAppearance iterates pathItems children for CompoundPathItem."""
        # Find the stripAppearance function body
        match = re.search(
            r'function stripAppearance\(item\)\s*\{(.+?)\n\s*\}',
            self.source, re.DOTALL
        )
        assert match, "stripAppearance function not found"
        body = match.group(1)
        assert 'CompoundPathItem' in body, "Must handle CompoundPathItem"
        assert '.pathItems' in body, "Must iterate child pathItems"
        assert '.filled = false' in body, "Must set filled=false"
        assert '.stroked = false' in body, "Must set stroked=false"

    def test_no_mcp_id_on_duplicate(self):
        """Duplicate clip path should NOT get an MCP ID — cleared to empty string."""
        assert 'dupMask.note = ""' in self.source

    def test_duplicate_placed_as_topmost_in_group(self):
        """dupMask moves into group at PLACEATBEGINNING (topmost)."""
        assert "dupMask.move(group, ElementPlacement.PLACEATBEGINNING)" in self.source

    def test_original_moved_below_group(self):
        """Original mask moves below group (PLACEAFTER) so clipped content is visible on top."""
        # In the duplicate_mask=true branch:
        # maskItem.move(group, ElementPlacement.PLACEAFTER)
        # This appears AFTER dupMask.move, so it's the z-positioning step
        lines = self.source.split('\n')
        dup_move_idx = None
        original_move_idx = None
        for i, line in enumerate(lines):
            if 'dupMask.move(group' in line:
                dup_move_idx = i
            if dup_move_idx is not None and 'maskItem.move(group, ElementPlacement.PLACEAFTER)' in line:
                original_move_idx = i
                break
        assert dup_move_idx is not None, "dupMask.move not found"
        assert original_move_idx is not None, "maskItem move below group not found"
        assert original_move_idx > dup_move_idx, \
            "Original mask z-reposition must happen AFTER duplicate move"

    def test_duplicate_clipping_true(self):
        """dupMask.clipping = true is set (not maskItem.clipping)."""
        assert "dupMask.clipping = true" in self.source

    def test_diagnostic_flag_in_result(self):
        """Result includes duplicate_mask_applied flag."""
        assert "duplicate_mask_applied" in self.source

    def test_dryrun_exposes_action_field(self):
        """dryRun result includes action: 'duplicate_mask' or 'move_mask'."""
        assert '"duplicate_mask"' in self.source
        assert '"move_mask"' in self.source

    def test_false_path_preserves_original_behavior(self):
        """When duplicate_mask=false, handler uses original move pattern."""
        # Find the else branch (duplicate_mask=false)
        # It should still have maskItem.move(group, ElementPlacement.PLACEATBEGINNING)
        assert "maskItem.move(group, ElementPlacement.PLACEATBEGINNING)" in self.source
        # And maskItem.clipping = true
        assert "maskItem.clipping = true" in self.source


# ── element_create schema tests (d param removed) ─────────────────────


class TestElementCreateDParam:
    def test_d_param_removed_from_schema(self):
        """element_create no longer has 'd' param (burned escape hatch)."""
        schema = get_op_schema("element_create")
        assert "d" not in schema.params

    def test_geometry_param_in_schema(self):
        """element_create has 'geometry' param for IR input."""
        schema = get_op_schema("element_create")
        assert "geometry" in schema.params
        assert schema.params["geometry"].type.value == "object"

    def test_multi_mode_removed_from_schema(self):
        """element_create no longer has 'multi_mode' param."""
        schema = get_op_schema("element_create")
        assert "multi_mode" not in schema.params
