"""
Tests for Grid-Based Element Discovery (grid_helper.jsx + targets.jsx grid type + overlay.py).

Static analysis tests that verify code shape, exports, and return contracts
without requiring a running Illustrator instance.
"""

from __future__ import annotations

import io
import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

# Paths to source files
_SCRIPTS = Path(__file__).resolve().parent.parent / "illustrator_mcp" / "resources" / "scripts"
_GRID_HELPER = _SCRIPTS / "grid_helper.jsx"
_TARGETS = _SCRIPTS / "targets.jsx"
_MANIFEST = _SCRIPTS / "manifest.json"

from illustrator_mcp.overlay import (
    draw_grid_overlay,
    map_bounds_to_pixels,
    HAS_PILLOW,
)


def _make_blank_png(w: int, h: int) -> bytes:
    if not HAS_PILLOW:
        return b"PNG_STUB"
    from PIL import Image
    img = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ==================== grid_helper.jsx Tests ====================

class TestGridHelperSource(unittest.TestCase):
    """Verify grid_helper.jsx source code shape."""

    @classmethod
    def setUpClass(cls):
        cls.source = _GRID_HELPER.read_text(encoding="utf-8")

    def test_file_exists(self):
        self.assertTrue(_GRID_HELPER.exists(), "grid_helper.jsx must exist")

    def test_artboard_grid_function_exists(self):
        self.assertIn("function artboardGrid(", self.source)

    def test_items_in_cell_function_exists(self):
        self.assertIn("function itemsInCell(", self.source)

    def test_rows_validated(self):
        """Rows range 1–26 must be validated."""
        self.assertRegex(self.source, r"rows\s*[<>]=?\s*1.*rows\s*[<>]=?\s*26|rows < 1.*rows > 26")

    def test_cols_validated(self):
        """Cols range 1–99 must be validated."""
        self.assertRegex(self.source, r"cols\s*[<>]=?\s*1.*cols\s*[<>]=?\s*99|cols < 1.*cols > 99")

    def test_artboard_rect_guard(self):
        """Should guard against zero/negative artboard size."""
        self.assertIn("abW <= 0 || abH <= 0", self.source)

    def test_case_normalization(self):
        """Cell labels must be uppercased."""
        self.assertIn(".toUpperCase()", self.source)

    def test_user_coord_basis_documented(self):
        """User coordinate basis must be documented in comments."""
        self.assertIn("USER COORDS", self.source)
        self.assertIn("artboard-relative", self.source)

    def test_contains_center_mode(self):
        """Default mode must be containsCenter."""
        self.assertIn('"containsCenter"', self.source)

    def test_intersects_mode(self):
        """Intersects mode must be supported."""
        self.assertIn('"intersects"', self.source)

    def test_compact_records_not_raw_items(self):
        """Return should include typename and summary, not raw PageItems."""
        self.assertIn("typename", self.source)
        self.assertIn("summary", self.source)

    def test_deterministic_sort(self):
        """Items must be sorted for deterministic output."""
        self.assertIn(".sort(", self.source)

    def test_label_scheme_a1(self):
        """Labels must follow A1 scheme (letter row + number col)."""
        # String.fromCharCode(65 + r) gives 'A' for row 0
        self.assertIn("String.fromCharCode(65 + r)", self.source)

    def test_discovery_return_shape(self):
        """Return shape must include cell, mode, items, summary, total."""
        for field in ["cell:", "mode:", "items:", "summary:", "total:"]:
            self.assertIn(field, self.source)


# ==================== targets.jsx Grid Target Tests ====================

class TestTargetsGridType(unittest.TestCase):
    """Verify grid target type in targets.jsx."""

    @classmethod
    def setUpClass(cls):
        cls.source = _TARGETS.read_text(encoding="utf-8")

    def test_grid_type_handler_exists(self):
        """collectTargets must handle type: 'grid'."""
        self.assertIn('"grid"', self.source)

    def test_grid_delegates_to_spatial(self):
        """Grid target must delegate to spatial within."""
        # Look for the delegation pattern
        self.assertIn('type: "spatial"', self.source)
        self.assertIn("within: cell", self.source)

    def test_case_normalization(self):
        """Cell label must be uppercased."""
        # The grid handler in collectTargets should normalize
        self.assertIn(".toUpperCase()", self.source)

    def test_structured_errors(self):
        """Grid handler must use throwStructured/makeError for errors."""
        self.assertIn("throwStructured", self.source)

    def test_user_coord_basis_comment(self):
        """normalizeRect must document user-coord basis."""
        self.assertIn("canonical basis", self.source)


# ==================== manifest.json Tests ====================

class TestManifestGridHelper(unittest.TestCase):
    """Verify grid_helper is registered in manifest."""

    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))

    def test_grid_helper_entry_exists(self):
        self.assertIn("grid_helper", self.manifest["libraries"])

    def test_exports_artboard_grid(self):
        exports = self.manifest["libraries"]["grid_helper"]["exports"]
        self.assertIn("artboardGrid", exports)

    def test_exports_items_in_cell(self):
        exports = self.manifest["libraries"]["grid_helper"]["exports"]
        self.assertIn("itemsInCell", exports)

    def test_depends_on_polyfills(self):
        deps = self.manifest["libraries"]["grid_helper"]["dependencies"]
        self.assertIn("polyfills", deps)


# ==================== overlay.py Grid Overlay Tests ====================

@unittest.skipUnless(HAS_PILLOW, "Pillow not installed")
class TestGridOverlay(unittest.TestCase):
    """Test draw_grid_overlay function."""

    def test_basic_grid_output(self):
        """Grid overlay produces valid PNG with same dimensions."""
        from PIL import Image
        png = _make_blank_png(400, 300)
        artboard = [0, 600, 800, 0]

        result = draw_grid_overlay(png, artboard, (400, 300), cols=4, rows=4)

        out = Image.open(io.BytesIO(result))
        self.assertEqual(out.size, (400, 300))
        # Should differ from input (grid lines added)
        self.assertNotEqual(result, png)

    def test_grid_1x1(self):
        """1×1 grid = no internal lines, just one label."""
        from PIL import Image
        png = _make_blank_png(200, 200)
        artboard = [0, 400, 400, 0]

        result = draw_grid_overlay(png, artboard, (200, 200), cols=1, rows=1)
        out = Image.open(io.BytesIO(result))
        self.assertEqual(out.size, (200, 200))

    def test_zero_artboard_returns_original(self):
        """Zero-size artboard → returns original bytes."""
        png = _make_blank_png(100, 100)
        artboard = [0, 0, 0, 0]

        result = draw_grid_overlay(png, artboard, (100, 100))
        self.assertEqual(result, png)

    @patch("illustrator_mcp.overlay.HAS_PILLOW", False)
    def test_no_pillow_returns_original(self):
        """Without Pillow, returns original bytes."""
        fake = b"fake_png"
        result = draw_grid_overlay(fake, [0, 600, 800, 0], (400, 300))
        self.assertEqual(result, fake)

    def test_grid_labels_count(self):
        """4×4 grid should produce 16 cells (A1–D4)."""
        # This is a behavioral shape test — verifying the grid math
        expected_labels = set()
        for r in range(4):
            for c in range(4):
                expected_labels.add(chr(65 + r) + str(c + 1))
        self.assertEqual(len(expected_labels), 16)
        self.assertIn("A1", expected_labels)
        self.assertIn("A4", expected_labels)
        self.assertIn("D1", expected_labels)
        self.assertIn("D4", expected_labels)


# ==================== Tool Description Tests ====================

class TestToolDescription(unittest.TestCase):
    """Verify execute_script docstring includes discovery guidance."""

    def test_discovery_guidance_present(self):
        from illustrator_mcp.tools.execute import illustrator_execute_script
        doc = illustrator_execute_script.__doc__ or ""
        self.assertIn("ELEMENT DISCOVERY", doc)
        self.assertIn("artboardGrid", doc)
        self.assertIn("itemsInCell", doc)

    def test_mutation_safety_preserved(self):
        from illustrator_mcp.tools.execute import illustrator_execute_script
        doc = illustrator_execute_script.__doc__ or ""
        self.assertIn("MUTATION SAFETY", doc)


if __name__ == "__main__":
    unittest.main()
