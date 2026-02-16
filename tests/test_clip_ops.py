"""
test_clip_ops.py — Tests for clip_create SOC operation.

Tests schema validation and static analysis of the ExtendScript handler.
Run: python -m pytest tests/test_clip_ops.py -v
"""

import json
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
        """id, name, dryRun are optional."""
        schema = get_op_schema("clip_create")
        assert schema.params["id"].required is False
        assert schema.params["name"].required is False
        assert schema.params["dryRun"].required is False

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


# ── Static handler guard tests ────────────────────────────────────────


class TestClipCreateStaticGuards:
    """Verify the ExtendScript handler source contains critical guards."""

    @pytest.fixture(autouse=True)
    def load_handler_source(self):
        """Load ops_group.jsx source for static analysis."""
        import os
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
        # Verify the actual type check pattern
        assert 'maskType !== "PathItem"' in self.source
        assert 'maskType !== "CompoundPathItem"' in self.source

    def test_parent_aware_guard(self):
        """Handler uses mask.parent (not mask.layer) for placement."""
        # Should use maskItem.parent for group creation
        assert "maskItem.parent" in self.source
        # Should NOT hardcode mask.layer for group creation
        # (mask.layer is fine for other uses, but the group creation
        # should use parent which could be GroupItem)

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


# ── element_create schema tests for d param ───────────────────────────


class TestElementCreateDParam:
    def test_d_param_in_schema(self):
        """element_create has 'd' param for SVG path data."""
        schema = get_op_schema("element_create")
        assert "d" in schema.params
        assert schema.params["d"].type.value == "string"

    def test_geometry_param_in_schema(self):
        """element_create has 'geometry' param for IR input."""
        schema = get_op_schema("element_create")
        assert "geometry" in schema.params
        assert schema.params["geometry"].type.value == "object"

    def test_multi_mode_param(self):
        """element_create has 'multi_mode' param with correct enums."""
        schema = get_op_schema("element_create")
        assert "multi_mode" in schema.params
        assert schema.params["multi_mode"].enum_values == ["compound", "group", "explode"]
