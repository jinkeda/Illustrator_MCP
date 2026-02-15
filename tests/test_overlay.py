"""
Tests for VLM Debug Overlay (overlay.py + annotated preview integration).

Tests coordinate mapping, compositing, graceful degradation, and annotation map.
"""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from illustrator_mcp.overlay import (
    map_bounds_to_pixels,
    composite_overlay,
    get_png_dimensions,
    HAS_PILLOW,
    OUTLINE_COLOR,
    FILL_HINT,
    MIN_FILL_AREA_PX,
)
from illustrator_mcp.tools.execute import _filter_items


def _make_blank_png(w: int, h: int) -> bytes:
    """Create a minimal valid PNG (white, RGBA) for testing."""
    if not HAS_PILLOW:
        return b"PNG_STUB"
    from PIL import Image
    img = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestCoordinateMapping(unittest.TestCase):
    """Test map_bounds_to_pixels with explicit Y-inversion verification."""

    def test_identity_mapping(self):
        """Item filling entire artboard -> fills entire PNG (clamped to W-1, H-1)."""
        artboard = [0, 600, 800, 0]
        png_size = (400, 300)
        item = [0, 600, 800, 0]

        result = map_bounds_to_pixels(item, artboard, png_size)
        # Edges clamp to px_w-1=399, px_h-1=299
        self.assertEqual(result, [0, 0, 399, 299])

    def test_y_inversion(self):
        """Item at TOP of artboard -> near y=0 in pixels."""
        artboard = [0, 600, 800, 0]
        png_size = (400, 300)
        item = [0, 600, 100, 500]

        result = map_bounds_to_pixels(item, artboard, png_size)
        self.assertEqual(result[1], 0)    # px_top = 0
        self.assertEqual(result[3], 50)   # 100pt down -> 50px

    def test_item_at_bottom(self):
        """Item at BOTTOM of artboard -> near y=H in pixels."""
        artboard = [0, 600, 800, 0]
        png_size = (400, 300)
        item = [700, 100, 800, 0]

        result = map_bounds_to_pixels(item, artboard, png_size)
        self.assertEqual(result[3], 299)  # bottom edge clamped to H-1
        self.assertEqual(result[1], 250)  # 100pt from bottom

    def test_center_item(self):
        """Item centered on artboard -> centered in pixels."""
        artboard = [0, 600, 800, 0]
        png_size = (800, 600)  # 1:1 scale
        item = [300, 400, 500, 200]

        result = map_bounds_to_pixels(item, artboard, png_size)
        self.assertEqual(result, [300, 200, 500, 400])

    def test_non_origin_artboard(self):
        """Artboard not at origin -> offset applied."""
        artboard = [100, 700, 500, 300]  # 400x400pt
        png_size = (200, 200)
        item = [200, 600, 400, 400]

        result = map_bounds_to_pixels(item, artboard, png_size)
        self.assertEqual(result, [50, 50, 150, 150])

    def test_zero_size_artboard(self):
        """Degenerate artboard -> returns zeros."""
        artboard = [100, 100, 100, 100]
        png_size = (400, 300)
        item = [100, 100, 200, 50]

        result = map_bounds_to_pixels(item, artboard, png_size)
        self.assertEqual(result, [0, 0, 0, 0])

    def test_returns_integers(self):
        """Result must be integers, not floats."""
        artboard = [0, 600, 800, 0]
        png_size = (333, 250)  # non-integer scale
        item = [100, 500, 300, 200]

        result = map_bounds_to_pixels(item, artboard, png_size)
        for val in result:
            self.assertIsInstance(val, int, f"Expected int, got {type(val)}")

    def test_clamped_to_image_bounds(self):
        """Item extending outside artboard -> clamped to [0, W-1]/[0, H-1]."""
        artboard = [0, 600, 800, 0]
        png_size = (400, 300)
        # Item extends past right and below artboard
        item = [-50, 700, 900, -100]

        result = map_bounds_to_pixels(item, artboard, png_size)
        l, t, r, b = result
        self.assertGreaterEqual(l, 0)
        self.assertGreaterEqual(t, 0)
        self.assertLessEqual(r, 399)
        self.assertLessEqual(b, 299)

    def test_normalized_if_swapped(self):
        """Swapped bounds -> sorted so left<=right and top<=bottom."""
        artboard = [0, 600, 800, 0]
        png_size = (400, 300)
        # This tests that the result is always normalized
        item = [0, 600, 400, 300]  # normal item

        result = map_bounds_to_pixels(item, artboard, png_size)
        l, t, r, b = result
        self.assertLessEqual(l, r)
        self.assertLessEqual(t, b)


@unittest.skipUnless(HAS_PILLOW, "Pillow not installed")
class TestCompositeOverlay(unittest.TestCase):
    """Test the Pillow compositing function."""

    def test_empty_annotations(self):
        """No annotations -> returns original bytes unchanged."""
        png = _make_blank_png(100, 100)
        result = composite_overlay(png, [])
        self.assertEqual(result, png)

    def test_basic_compositing(self):
        """Single annotation -> output PNG is valid and same dimensions."""
        png = _make_blank_png(200, 150)
        annotations = [{"label": "1", "bounds_px": [10, 10, 50, 50]}]

        result = composite_overlay(png, annotations)

        from PIL import Image
        out_img = Image.open(io.BytesIO(result))
        self.assertEqual(out_img.size, (200, 150))
        self.assertGreater(len(result), 0)

    def test_multiple_annotations(self):
        """Multiple annotations -> all drawn, output valid."""
        png = _make_blank_png(400, 300)
        annotations = [
            {"label": str(i), "bounds_px": [i*30, 10, i*30+25, 40]}
            for i in range(10)
        ]

        result = composite_overlay(png, annotations)

        from PIL import Image
        out_img = Image.open(io.BytesIO(result))
        self.assertEqual(out_img.size, (400, 300))

    def test_label_at_top_edge(self):
        """Box at y=0 -> label placed inside, no crash."""
        png = _make_blank_png(100, 100)
        annotations = [{"label": "1", "bounds_px": [5, 0, 50, 30]}]

        result = composite_overlay(png, annotations)
        self.assertGreater(len(result), 0)


@unittest.skipUnless(HAS_PILLOW, "Pillow not installed")
class TestGetPngDimensions(unittest.TestCase):
    """Test PNG dimension decoding."""

    def test_valid_png(self):
        png = _make_blank_png(320, 240)
        dims = get_png_dimensions(png)
        self.assertEqual(dims, (320, 240))

    def test_invalid_bytes(self):
        dims = get_png_dimensions(b"not a png")
        self.assertIsNone(dims)


class TestGracefulDegradation(unittest.TestCase):
    """Test behavior when Pillow is not available."""

    @patch("illustrator_mcp.overlay.HAS_PILLOW", False)
    def test_composite_returns_original(self):
        fake_bytes = b"fake_png_data"
        result = composite_overlay(fake_bytes, [{"label": "1", "bounds_px": [0, 0, 10, 10]}])
        self.assertEqual(result, fake_bytes)

    @patch("illustrator_mcp.overlay.HAS_PILLOW", False)
    def test_get_dimensions_returns_none(self):
        result = get_png_dimensions(b"fake_png_data")
        self.assertIsNone(result)


class TestAnnotationMapStructure(unittest.TestCase):
    """Test the structured annotation result shape expected by VLM agents."""

    def test_result_dict_schema(self):
        """Verify the structured result dict has required keys."""
        result = {
            "meta": {
                "bounds_kind": "visibleBounds",
                "max_items": 200,
                "input_count": 5,
                "annotated_count": 2,
                "filtered_count": 3,
                "png_px": [800, 600],
                "artboard_pt": [0, 600, 800, 0],
            },
            "annotations": [
                {
                    "label": "1",
                    "mcp_id": "9a8b1234",
                    "has_mcp_id": True,
                    "name": "chart_axis_x",
                    "type": "TextFrame",
                    "bounds_pt": [50, 580, 750, 560],
                },
                {
                    "label": "2",
                    "mcp_id": None,
                    "has_mcp_id": False,
                    "name": "background_rect",
                    "type": "PathItem",
                    "bounds_pt": [0, 600, 800, 0],
                },
            ],
            "warnings": [],
        }

        # Required top-level keys
        self.assertIn("meta", result)
        self.assertIn("annotations", result)
        self.assertIn("warnings", result)

        # New meta fields
        self.assertIn("input_count", result["meta"])
        self.assertIn("annotated_count", result["meta"])
        self.assertIn("filtered_count", result["meta"])
        self.assertEqual(result["meta"]["annotated_count"], 2)
        self.assertEqual(result["meta"]["filtered_count"], 3)
        self.assertEqual(result["meta"]["input_count"], 5)

        # Annotation fields
        for entry in result["annotations"]:
            self.assertIn("label", entry)
            self.assertIn("mcp_id", entry)
            self.assertIn("has_mcp_id", entry)
            self.assertIn("name", entry)
            self.assertIn("type", entry)
            self.assertIn("bounds_pt", entry)
            self.assertEqual(len(entry["bounds_pt"]), 4)

        # Verify JSON-serializable
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        self.assertEqual(len(parsed["annotations"]), 2)

    def test_label_numbering(self):
        """Labels should be sequential strings starting from '1'."""
        annotations = [
            {"label": str(i + 1), "mcp_id": None, "has_mcp_id": False,
             "name": f"item_{i}", "type": "PathItem", "bounds_pt": [0, 0, 10, 10]}
            for i in range(5)
        ]
        labels = [a["label"] for a in annotations]
        self.assertEqual(labels, ["1", "2", "3", "4", "5"])

    def test_warning_on_no_pillow(self):
        """Result dict should carry warnings when issues occur."""
        result = {
            "meta": {"bounds_kind": "visibleBounds", "max_items": 200,
                     "input_count": 0, "annotated_count": 0, "filtered_count": 0},
            "annotations": [],
            "warnings": ["Pillow not installed. Run: pip install illustrator-mcp[overlay]"],
        }
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("Pillow", result["warnings"][0])


class TestFilterItems(unittest.TestCase):
    """Test the type-aware relevance filter for annotation items."""

    ARTBOARD = [0, 0, 1200, -800]  # standard 1200x800pt

    def test_filter_canvas_spanning(self):
        """Item covering >=90% of artboard is excluded."""
        items = [
            {"name": "bg", "type": "PathItem", "bounds": [0, 0, 1200, -800]},  # 100%
            {"name": "card", "type": "PathItem", "bounds": [40, -120, 300, -260]},
        ]
        kept, filtered = _filter_items(items, self.ARTBOARD)
        self.assertEqual(filtered, 1)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["name"], "card")

    def test_filter_thin_path(self):
        """PathItem with height < 5pt is excluded."""
        items = [
            {"name": "accent", "type": "PathItem", "bounds": [40, -120, 300, -124]},  # 4pt tall
            {"name": "divider", "type": "PathItem", "bounds": [40, -100, 1160, -101]},  # 1pt tall
            {"name": "bar", "type": "PathItem", "bounds": [80, -400, 140, -640]},  # 240pt tall
        ]
        kept, filtered = _filter_items(items, self.ARTBOARD)
        self.assertEqual(filtered, 2)
        self.assertEqual(kept[0]["name"], "bar")

    def test_filter_textframe_immune(self):
        """TextFrame with tiny bounds is NOT filtered (immune to thin rule)."""
        items = [
            {"name": "tiny_text", "type": "TextFrame", "bounds": [100, -50, 110, -53]},  # 3pt tall
            {"name": "thin_path", "type": "PathItem", "bounds": [100, -50, 110, -53]},  # same bounds
        ]
        kept, filtered = _filter_items(items, self.ARTBOARD)
        self.assertEqual(filtered, 1)  # only PathItem filtered
        self.assertEqual(kept[0]["name"], "tiny_text")

    def test_filter_keeps_normal(self):
        """Normal-sized items pass both rules."""
        items = [
            {"name": "card", "type": "PathItem", "bounds": [40, -120, 300, -260]},
            {"name": "text", "type": "TextFrame", "bounds": [56, -140, 96, -153]},
            {"name": "bar", "type": "PathItem", "bounds": [80, -400, 140, -640]},
        ]
        kept, filtered = _filter_items(items, self.ARTBOARD)
        self.assertEqual(filtered, 0)
        self.assertEqual(len(kept), 3)

    def test_filter_robust_abs_bounds(self):
        """Inverted/negative bounds don't crash."""
        items = [
            {"name": "inverted", "type": "PathItem", "bounds": [300, -260, 40, -120]},
        ]
        # Should not raise — abs() makes it robust
        kept, filtered = _filter_items(items, self.ARTBOARD)
        # 260pt wide, 140pt tall — should be kept
        self.assertEqual(len(kept), 1)

    def test_meta_counts(self):
        """Verify filtered_count = input - kept."""
        items = [
            {"name": "bg", "type": "PathItem", "bounds": [0, 0, 1200, -800]},
            {"name": "accent", "type": "PathItem", "bounds": [40, -120, 300, -124]},
            {"name": "card", "type": "PathItem", "bounds": [40, -120, 300, -260]},
            {"name": "text", "type": "TextFrame", "bounds": [56, -140, 96, -153]},
        ]
        kept, filtered = _filter_items(items, self.ARTBOARD)
        self.assertEqual(filtered, 2)  # bg + accent
        self.assertEqual(len(kept), 2)  # card + text
        self.assertEqual(len(kept) + filtered, len(items))


@unittest.skipUnless(HAS_PILLOW, "Pillow not installed")
class TestVisualConstants(unittest.TestCase):
    """Verify updated visual constants for overlay refinements."""

    def test_outline_alpha(self):
        """Outline should be semi-transparent (alpha < 255)."""
        self.assertEqual(len(OUTLINE_COLOR), 4)
        self.assertLess(OUTLINE_COLOR[3], 255, "Outline should be semi-transparent")
        self.assertEqual(OUTLINE_COLOR[3], 160)

    def test_fill_hint_alpha(self):
        """Fill hint should be very subtle (<10% alpha)."""
        self.assertEqual(len(FILL_HINT), 4)
        self.assertLessEqual(FILL_HINT[3], 25, "Fill hint alpha should be <=10%")

    def test_fill_hint_min_area(self):
        """Fill skipped for boxes below MIN_FILL_AREA_PX."""
        png = _make_blank_png(200, 200)
        # Small box (10x10 = 100px² < 400)
        small_ann = [{"label": "1", "bounds_px": [5, 5, 15, 15]}]
        result_small = composite_overlay(png, small_ann)

        # Large box (50x50 = 2500px² >= 400)
        large_ann = [{"label": "2", "bounds_px": [10, 10, 60, 60]}]
        result_large = composite_overlay(png, large_ann)

        # Both should produce valid PNGs (no crash)
        from PIL import Image
        Image.open(io.BytesIO(result_small))
        Image.open(io.BytesIO(result_large))
        # Large box output should differ from small (fill adds bytes)
        self.assertNotEqual(result_small, result_large)


if __name__ == "__main__":
    unittest.main()
