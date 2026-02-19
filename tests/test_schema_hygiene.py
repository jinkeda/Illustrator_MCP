"""
Schema hygiene guard tests.

Static source-analysis tests (no Illustrator connection required) that verify:
1. Color canonicalization — _extractStyle uses `model` discriminator for all types
2. Float quantization — output-facing scripts round position/bounds/style values
"""

import pathlib
import pytest

# --------------- paths ---------------

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / \
    "illustrator_mcp" / "resources" / "scripts"
GEO_BOOLEAN = SCRIPTS_DIR / "geo_boolean.jsx"
OPS_STYLE = SCRIPTS_DIR / "ops_style.jsx"
OPS_MEASURE = SCRIPTS_DIR / "ops_measure.jsx"
TEMPLATES_PATH = pathlib.Path(__file__).resolve().parent.parent / \
    "illustrator_mcp" / "templates.py"


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


# ==================== Color Canonicalization ====================

class TestExtractColorCanonical:
    """_extractColorCanonical must produce a `model` discriminator for every color type."""

    def _get_section(self):
        """Return the _extractColorCanonical function source."""
        src = _read(GEO_BOOLEAN)
        start = src.index("function _extractColorCanonical(")
        # Find end — next top-level function
        end = src.index("function _extractStyle(", start)
        return src[start:end]

    def test_rgb_has_model_key(self):
        section = self._get_section()
        assert 'model: "RGB"' in section

    def test_cmyk_has_model_key(self):
        section = self._get_section()
        assert 'model: "CMYK"' in section

    def test_gray_has_model_key(self):
        section = self._get_section()
        assert 'model: "Gray"' in section

    def test_spot_has_model_key(self):
        section = self._get_section()
        assert 'model: "Spot"' in section

    def test_gradient_has_model_key(self):
        section = self._get_section()
        assert 'model: "Gradient"' in section

    def test_pattern_has_model_key(self):
        section = self._get_section()
        assert 'model: "Pattern"' in section


class TestSpotColorDetails:
    """SpotColor branch must include name, tint, and base fields."""

    def _get_spot_section(self):
        src = _read(GEO_BOOLEAN)
        start = src.index('"SpotColor"')
        end = src.index('"GradientColor"', start)
        return src[start:end]

    def test_spot_has_name(self):
        assert "name:" in self._get_spot_section() or \
               "name :" in self._get_spot_section()

    def test_spot_has_tint(self):
        assert "tint:" in self._get_spot_section() or \
               "tint :" in self._get_spot_section()

    def test_spot_has_base(self):
        section = self._get_spot_section()
        assert "base" in section
        assert "_extractColorCanonical" in section


class TestExplicitStubs:
    """Gradient/Pattern stubs must include supported: false."""

    def _get_section(self):
        src = _read(GEO_BOOLEAN)
        start = src.index("function _extractColorCanonical(")
        end = src.index("function _extractStyle(", start)
        return src[start:end]

    def test_gradient_stub_unsupported(self):
        section = self._get_section()
        # Find the GradientColor case
        grad_start = section.index('"GradientColor"')
        grad_section = section[grad_start:grad_start + 200]
        assert "supported: false" in grad_section or \
               "supported:false" in grad_section

    def test_pattern_stub_unsupported(self):
        section = self._get_section()
        pat_start = section.index('"PatternColor"')
        pat_section = section[pat_start:pat_start + 200]
        assert "supported: false" in pat_section or \
               "supported:false" in pat_section


class TestNoNullColorRegression:
    """_extractColorCanonical must handle all 5 main color types without
    falling through to null. Only truly unknown types may return null."""

    def test_all_known_types_handled(self):
        src = _read(GEO_BOOLEAN)
        start = src.index("function _extractColorCanonical(")
        end = src.index("function _extractStyle(", start)
        section = src[start:end]

        required_types = ["RGBColor", "CMYKColor", "GrayColor",
                          "SpotColor", "GradientColor", "PatternColor"]
        for t in required_types:
            assert f'"{t}"' in section, \
                f"_extractColorCanonical missing handler for {t}"

    def test_extract_style_delegates_to_canonical(self):
        """_extractStyle must use _extractColorCanonical, not inline if-chains."""
        src = _read(GEO_BOOLEAN)
        start = src.index("function _extractStyle(")
        end_marker = src.index("// ── Appearance check", start)
        section = src[start:end_marker]
        assert "_extractColorCanonical" in section
        # Should NOT contain inline typename checks
        assert 'fc.typename === "RGBColor"' not in section
        assert 'sc.typename === "RGBColor"' not in section


class TestCMYKClamping:
    """CMYK channels must be clamped to [0, 100]."""

    def test_clamp_function_exists(self):
        src = _read(GEO_BOOLEAN)
        assert "function _clamp(" in src

    def test_cmyk_uses_clamp(self):
        src = _read(GEO_BOOLEAN)
        start = src.index("function _extractColorCanonical(")
        end = src.index("function _extractStyle(", start)
        section = src[start:end]
        cmyk_start = section.index('"CMYKColor"')
        cmyk_section = section[cmyk_start:cmyk_start + 400]
        assert "_clamp(" in cmyk_section


# ==================== Float Quantization ====================

class TestTemplateQuantization:
    """GET_DOCUMENT_STRUCTURE and GET_SELECTION_INFO must use _q() for rounding."""

    def _get_template(self, name: str) -> str:
        src = _read(TEMPLATES_PATH)
        start = src.index(name)
        # Find the closing """) for the template
        end = src.index('""")', start) + 4
        return src[start:end]

    def test_document_structure_has_q_helper(self):
        section = self._get_template("GET_DOCUMENT_STRUCTURE")
        assert "function _q(" in section

    def test_document_structure_q_is_null_safe(self):
        section = self._get_template("GET_DOCUMENT_STRUCTURE")
        assert "typeof v" in section

    def test_document_structure_rounds_position(self):
        section = self._get_template("GET_DOCUMENT_STRUCTURE")
        assert "_q(item.position[0])" in section
        assert "_q(item.position[1])" in section

    def test_document_structure_rounds_bounds(self):
        section = self._get_template("GET_DOCUMENT_STRUCTURE")
        assert "_q(item.geometricBounds[0])" in section

    def test_selection_info_has_q_helper(self):
        section = self._get_template("GET_SELECTION_INFO")
        assert "function _q(" in section

    def test_selection_info_q_is_null_safe(self):
        section = self._get_template("GET_SELECTION_INFO")
        assert "typeof v" in section

    def test_selection_info_rounds_position(self):
        section = self._get_template("GET_SELECTION_INFO")
        assert "_q(item.position[0])" in section

    def test_selection_info_rounds_bounds(self):
        section = self._get_template("GET_SELECTION_INFO")
        assert "_q(item.geometricBounds[0])" in section


class TestStyleSnapshotQuantization:
    """style_snapshot must round strokeWidth and opacity."""

    def _get_snapshot_section(self):
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_snapshot"')
        end = src.index('registerOpHandler("style_clone"', start)
        return src[start:end]

    def test_rounds_stroke_width(self):
        section = self._get_snapshot_section()
        assert "Math.round(item.strokeWidth" in section

    def test_rounds_opacity(self):
        section = self._get_snapshot_section()
        assert "Math.round(item.opacity" in section


class TestMeasureBoundsQuantization:
    """measure_bounds must round all output fields."""

    def _get_section(self):
        src = _read(OPS_MEASURE)
        start = src.index('registerOpHandler("measure_bounds"')
        end = src.index('registerOpHandler("snapshot_structure"', start)
        return src[start:end]

    def test_has_q_helper(self):
        section = self._get_section()
        assert "function _q(" in section

    def test_q_is_null_safe(self):
        section = self._get_section()
        assert "typeof v" in section

    def test_rounds_bounds(self):
        section = self._get_section()
        assert "_q(minX)" in section
        assert "_q(maxY)" in section


class TestSnapshotStructureQuantization:
    """snapshot_structure must round bounds when includeItems is true."""

    def _get_section(self):
        src = _read(OPS_MEASURE)
        start = src.index('registerOpHandler("snapshot_structure"')
        end = src.index('registerOpHandler("hash_structure"', start)
        return src[start:end]

    def test_rounds_bounds(self):
        section = self._get_section()
        assert "_qm(item.left)" in section or "_q(item.left)" in section
