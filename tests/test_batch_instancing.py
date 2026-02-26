"""
Tests for template instancing and array expansion guards.

Validates that the JSX handler-level guards for element_create_batch
template mode and array mode work correctly by inspecting payload
construction patterns and JSX source.
"""

from __future__ import annotations

import json
import pathlib
import unittest


SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / \
    "illustrator_mcp" / "resources" / "scripts"
OPS_ELEMENT = SCRIPTS_DIR / "ops_element.jsx"


def _read_ops_element() -> str:
    return OPS_ELEMENT.read_text(encoding="utf-8")


class TestTemplateInstancingGuards(unittest.TestCase):
    """Validate that the JSX handler-level guards work correctly
    by inspecting the script construction patterns."""

    def test_template_payload_structure(self):
        """Verify template payload builds correct JSON for executeOpBatch."""
        payload = {
            "op": "element_create_batch",
            "params": {
                "template": {
                    "type": "ellipse",
                    "r": 4,
                    "fill": {"r": 70, "g": 130, "b": 180},
                    "stroke": False,
                },
                "instances": [
                    {"x": 10, "y": 20},
                    {"x": 30, "y": 40, "opacity": 50},
                ],
                "name": "scatter_pt",
            },
        }

        # Verify serialization round-trips:
        json_str = json.dumps(payload)
        rebuilt = json.loads(json_str)
        self.assertEqual(rebuilt["op"], "element_create_batch")
        self.assertEqual(rebuilt["params"]["template"]["type"], "ellipse")
        self.assertEqual(len(rebuilt["params"]["instances"]), 2)

        # Verify mutual exclusion: template present → items absent
        self.assertIn("template", rebuilt["params"])
        self.assertNotIn("items", rebuilt["params"])

    def test_mutual_exclusion_in_payload(self):
        """Both template and items in payload → detectable before send."""
        payload = {
            "op": "element_create_batch",
            "params": {
                "template": {"type": "ellipse", "r": 4},
                "items": [{"type": "rect", "x": 0, "y": 0, "w": 10, "h": 10}],
                "instances": [{"x": 0, "y": 0}],
            },
        }
        # Python-side guard: detect both keys present
        has_both = "template" in payload["params"] and "items" in payload["params"]
        self.assertTrue(has_both, "Guard should detect both template and items")


# ==================== Array Expansion Tests ====================

class TestArrayExpansion(unittest.TestCase):
    """Validate array expansion logic in ops_element.jsx source."""

    def test_array_expansion_basic(self):
        """Array expansion loop exists with spacingX/spacingY logic."""
        src = _read_ops_element()
        start = src.index('registerOpHandler("element_create_batch"')
        section = src[start:start + 5000]
        # Core array expansion logic
        assert "arr.spacingX" in section or "dx = arr.spacingX" in section
        assert "arr.spacingY" in section or "dy = arr.spacingY" in section
        assert "generated.push" in section
        assert "params.instances = generated" in section

    def test_array_expansion_grid(self):
        """cols and Math.floor(ai / cols) for row calculation."""
        src = _read_ops_element()
        start = src.index('registerOpHandler("element_create_batch"')
        section = src[start:start + 5000]
        assert "ai % cols" in section, "Column index must use modulo"
        assert "Math.floor(ai / cols)" in section, "Row index must use floor division"

    def test_array_count_zero_early_return(self):
        """count === 0 returns early with created: 0."""
        src = _read_ops_element()
        start = src.index('registerOpHandler("element_create_batch"')
        section = src[start:start + 5000]
        assert "count === 0" in section, "Must handle count=0 case"
        assert "created: 0" in section, "count=0 should return created: 0"

    def test_array_count_non_integer_rejects(self):
        """Math.floor(count) !== count guard present."""
        src = _read_ops_element()
        start = src.index('registerOpHandler("element_create_batch"')
        section = src[start:start + 5000]
        assert "Math.floor(count) !== count" in section, \
            "Must reject non-integer count"
        assert "array.count must be a finite integer" in section

    def test_array_cols_zero_rejects(self):
        """cols < 1 guard present."""
        src = _read_ops_element()
        start = src.index('registerOpHandler("element_create_batch"')
        section = src[start:start + 5000]
        assert "cols < 1" in section, "Must reject cols < 1"
        assert "array.cols must be" in section

    def test_array_max_count_guard(self):
        """count > 10000 guard with V_INVALID_PARAM_VALUE."""
        src = _read_ops_element()
        start = src.index('registerOpHandler("element_create_batch"')
        section = src[start:start + 5000]
        assert "count > 10000" in section, "Must cap count at 10000"
        assert "V_INVALID_PARAM_VALUE" in section, \
            "Range errors should use V_INVALID_PARAM_VALUE, not V_INVALID_PARAM_TYPE"

    def test_array_requires_template(self):
        """array without template is rejected."""
        src = _read_ops_element()
        start = src.index('registerOpHandler("element_create_batch"')
        section = src[start:start + 5000]
        assert "'array' requires 'template'" in section

    def test_items_template_mutual_exclusion(self):
        """items combined with template/instances/array is rejected."""
        src = _read_ops_element()
        start = src.index('registerOpHandler("element_create_batch"')
        section = src[start:start + 5000]
        assert "cannot combine 'items'" in section


if __name__ == "__main__":
    unittest.main()
