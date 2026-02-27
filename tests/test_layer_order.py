"""
Guard tests for layer ordering fixes.

Verifies that:
- layer_create fails loudly on missing above/below references
- layer_create validates placement param (whitelist + mutual exclusivity)
- assert_layer_order op exists with monotonicity check and strict mode
- layer_list op exists
"""

import pathlib
import pytest

# --------------- paths ---------------

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / \
    "illustrator_mcp" / "resources" / "scripts"
OPS_LAYER = SCRIPTS_DIR / "ops_layer.jsx"
OPS_MEASURE = SCRIPTS_DIR / "ops_measure.jsx"


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


# ==================== layer_create: Fail Loudly on Missing Refs ====================

class TestLayerCreateFailLoud:
    """above/below must fail with error when reference layer is missing."""

    def test_above_ref_not_found_returns_error(self):
        src = _read(OPS_LAYER)
        assert "Reference layer not found for 'above'" in src

    def test_below_ref_not_found_returns_error(self):
        src = _read(OPS_LAYER)
        assert "Reference layer not found for 'below'" in src

    def test_available_layers_in_diagnostics(self):
        """Error response includes list of available layer names."""
        src = _read(OPS_LAYER)
        assert "_layerNames(doc)" in src


# ==================== layer_create: Placement Param ====================

class TestPlacementParam:
    """placement param must be validated at schema level before add()."""

    def test_placement_validates_before_add(self):
        """Mutual exclusivity and whitelist checks appear before doc.layers.add()."""
        src = _read(OPS_LAYER)
        handler_start = src.index('registerOpHandler("layer_create"')
        add_pos = src.index("doc.layers.add()", handler_start)
        validation_section = src[handler_start:add_pos]
        assert "'placement' cannot be used with" in validation_section

    def test_placement_whitelist(self):
        """Unknown placement values are rejected."""
        src = _read(OPS_LAYER)
        assert "expected 'top' or 'bottom'" in src

    def test_placement_mutual_exclusivity(self):
        """placement + above/below together is an error."""
        src = _read(OPS_LAYER)
        assert "'placement' cannot be used with 'above'/'below'" in src


# ==================== assert_layer_order ====================

class TestAssertLayerOrder:
    """assert_layer_order must exist in ops_measure with monotonicity check."""

    def test_registered(self):
        src = _read(OPS_MEASURE)
        assert 'registerOpHandler("assert_layer_order"' in src

    def test_uses_monotonicity_check(self):
        """Algorithm uses an indexMap for monotonicity."""
        src = _read(OPS_MEASURE)
        start = src.index('"assert_layer_order"')
        section = src[start:start + 2000]
        assert "indexMap" in section

    def test_strict_mode_supported(self):
        """Supports strict: true for exact match."""
        src = _read(OPS_MEASURE)
        start = src.index('"assert_layer_order"')
        section = src[start:start + 2000]
        assert "params.strict" in section


# ==================== layer_list ====================

class TestLayerList:
    """layer_list read-only debugging op must exist."""

    def test_layer_list_registered(self):
        src = _read(OPS_LAYER)
        assert 'registerOpHandler("layer_list"' in src
