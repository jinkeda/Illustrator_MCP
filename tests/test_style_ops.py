"""
Guard tests for style_snapshot and style_clone SOC operations.

Tests handler registration, helper function existence, MUTATING_OPS
membership, schema presence, and structural patterns in the JSX source.
"""

import os
import pathlib
import pytest

# --------------- paths ---------------

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / \
    "illustrator_mcp" / "resources" / "scripts"
OPS_STYLE = SCRIPTS_DIR / "ops_style.jsx"
OPS_CORE = SCRIPTS_DIR / "ops_core.jsx"
CONTRACTS_PATH = pathlib.Path(__file__).resolve().parent.parent / \
    "illustrator_mcp" / "schemas" / "contracts.py"


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


# ==================== Handler Registration ====================

class TestHandlerRegistration:
    """Both style_snapshot and style_clone must be registered."""

    def test_style_snapshot_registered(self):
        src = _read(OPS_STYLE)
        assert 'registerOpHandler("style_snapshot"' in src

    def test_style_clone_registered(self):
        src = _read(OPS_STYLE)
        assert 'registerOpHandler("style_clone"' in src


# ==================== Helper Functions ====================

class TestHelpers:
    """Shared helpers must exist in ops_style.jsx."""

    def test_serialize_color_exists(self):
        src = _read(OPS_STYLE)
        assert "function _serializeColor(" in src

    def test_is_text_uniform_exists(self):
        src = _read(OPS_STYLE)
        assert "function _isTextUniform(" in src

    def test_serialize_text_style_exists(self):
        src = _read(OPS_STYLE)
        assert "function _serializeTextStyle(" in src


# ==================== Color Serialization ====================

class TestColorSerialization:
    """_serializeColor must handle all Illustrator color types."""

    def test_handles_rgb(self):
        src = _read(OPS_STYLE)
        assert '"RGBColor"' in src
        assert '"rgb"' in src

    def test_handles_cmyk(self):
        src = _read(OPS_STYLE)
        assert '"CMYKColor"' in src
        assert '"cmyk"' in src

    def test_handles_spot(self):
        src = _read(OPS_STYLE)
        assert '"SpotColor"' in src
        assert '"spot"' in src

    def test_handles_gradient(self):
        src = _read(OPS_STYLE)
        assert '"GradientColor"' in src
        assert '"gradient"' in src

    def test_handles_pattern(self):
        src = _read(OPS_STYLE)
        assert '"PatternColor"' in src
        assert '"pattern"' in src

    def test_handles_no_color(self):
        src = _read(OPS_STYLE)
        assert '"NoColor"' in src
        assert '"none"' in src


# ==================== Text Uniformity ====================

class TestTextUniformity:
    """Text uniformity detection must use characterAttributes."""

    def test_checks_character_attributes(self):
        src = _read(OPS_STYLE)
        assert "characterAttributes" in src

    def test_checks_text_font_name(self):
        src = _read(OPS_STYLE)
        assert "textFont.name" in src

    def test_returns_uniform_flag(self):
        src = _read(OPS_STYLE)
        assert "uniform" in src

    def test_serialize_text_includes_justification(self):
        src = _read(OPS_STYLE)
        assert "justification" in src


# ==================== Style Snapshot ====================

class TestStyleSnapshot:
    """style_snapshot must extract type, fill, stroke, opacity, and text."""

    def test_returns_item_type(self):
        src = _read(OPS_STYLE)
        # Within style_snapshot handler
        start = src.index('registerOpHandler("style_snapshot"')
        section = src[start:start + 2000]
        assert "item.typename" in section

    def test_extracts_mcp_id(self):
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_snapshot"')
        section = src[start:start + 2000]
        assert "extractMcpId" in section

    def test_extracts_opacity(self):
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_snapshot"')
        section = src[start:start + 2000]
        assert "opacity" in section

    def test_warns_on_gradient(self):
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_snapshot"')
        section = src[start:start + 2000]
        assert "gradient" in section

    def test_warns_on_non_uniform_text(self):
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_snapshot"')
        section = src[start:start + 2000]
        assert "mixed text formatting" in section


# ==================== Style Clone ====================

class TestStyleClone:
    """style_clone must resolve source, validate properties, apply to targets."""

    def test_requires_from_param(self):
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_clone"')
        section = src[start:start + 3000]
        assert "params.from" in section
        assert "V_MISSING_REQUIRED_PARAM" in section

    def test_uses_heap_resolve(self):
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_clone"')
        section = src[start:start + 3000]
        assert "heapResolve" in section

    def test_validates_properties_enum(self):
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_clone"')
        section = src[start:start + 3000]
        # Valid properties must be listed
        assert "fill" in section
        assert "stroke" in section
        assert "opacity" in section
        assert "text" in section

    def test_skips_text_on_non_textframe(self):
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_clone"')
        section = src[start:start + 4000]
        assert "text attrs skipped" in section

    def test_copies_absence(self):
        """If source has filled=false, clone should set target.filled=false."""
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_clone"')
        section = src[start:start + 4000]
        assert "target.filled = srcFilled" in section

    def test_warns_mixed_source_text(self):
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_clone"')
        section = src[start:start + 4000]
        assert "mixed formatting" in section


# ==================== OP_CLASS ====================

class TestMutatingOps:
    """style_clone should be in OP_CLASS, style_snapshot should NOT."""

    def test_style_clone_in_op_class(self):
        src = _read(OPS_CORE)
        start = src.index("OP_CLASS")
        section = src[start:start + 800]
        assert '"style_clone"' in section

    def test_style_snapshot_not_in_op_class(self):
        src = _read(OPS_CORE)
        start = src.index("OP_CLASS")
        section = src[start:start + 800]
        assert '"style_snapshot"' not in section


# ==================== Contracts Schema ====================

class TestContractsSchema:
    """Both ops must be in OP_SCHEMAS in contracts.py."""

    def test_style_snapshot_schema_present(self):
        content = _read(CONTRACTS_PATH)
        assert 'name="style_snapshot"' in content

    def test_style_clone_schema_present(self):
        content = _read(CONTRACTS_PATH)
        assert 'name="style_clone"' in content

    def test_from_param_required(self):
        content = _read(CONTRACTS_PATH)
        start = content.index('name="style_clone"')
        section = content[start:start + 300]
        assert '"from"' in section
        assert "required=True" in section

    def test_properties_param_optional(self):
        content = _read(CONTRACTS_PATH)
        start = content.index('name="style_clone"')
        section = content[start:start + 300]
        assert '"properties"' in section


# ==================== File Header ====================

class TestFileHeader:
    """ops_style.jsx header must declare new deps and ops."""

    def test_version_bumped(self):
        src = _read(OPS_STYLE)
        assert "1.1.0" in src[:700]

    def test_declares_heap_dependency(self):
        src = _read(OPS_STYLE)
        assert "heap" in src[:700]

    def test_declares_style_snapshot(self):
        src = _read(OPS_STYLE)
        assert "style_snapshot" in src[:700]

    def test_declares_style_clone(self):
        src = _read(OPS_STYLE)
        assert "style_clone" in src[:700]
