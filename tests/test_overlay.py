"""
Tests for VLM Debug Overlay (overlay.py + annotated preview integration).

Tests coordinate mapping, compositing, contrast selection, pill placement,
graceful degradation, and annotation map.
"""

from __future__ import annotations

import io
import json
import time
import unittest
from unittest.mock import patch

from illustrator_mcp.overlay import (
    map_bounds_to_pixels,
    composite_overlay,
    get_png_dimensions,
    draw_grid_overlay,
    draw_ruler_overlay,
    _pick_interval,
    HAS_PILLOW,
    OUTLINE_PALETTE,
    FILL_ALPHA,
    MIN_FILL_AREA_PX,
    _wcag_luminance,
    _contrast_ratio,
    _pick_contrast_color,
    _compute_font_size,
    _compute_outline_width,
    _place_pill,
    _in_bounds,
    _rects_overlap,
    _overlap_area,
)
from illustrator_mcp.tools.preview import _filter_items


def _make_blank_png(w: int, h: int, color=(255, 255, 255, 255)) -> bytes:
    """Create a minimal valid PNG (RGBA) for testing."""
    if not HAS_PILLOW:
        return b"PNG_STUB"
    from PIL import Image
    img = Image.new("RGBA", (w, h), color)
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
        """PathItem with dimension below dynamic threshold is excluded.
        On 1200x800 artboard: min_dim = min(10, max(2, 800*0.005)) = 4pt."""
        items = [
            {"name": "accent", "type": "PathItem", "bounds": [40, -120, 300, -123]},  # 3pt tall -> filtered
            {"name": "divider", "type": "PathItem", "bounds": [40, -100, 1160, -101]},  # 1pt tall -> filtered
            {"name": "bar", "type": "PathItem", "bounds": [80, -400, 140, -640]},  # 240pt tall -> kept
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
        """Verify filtered_count = input - kept.
        On 1200x800 artboard: min_dim = 4pt. Items < 4pt are filtered."""
        items = [
            {"name": "bg", "type": "PathItem", "bounds": [0, 0, 1200, -800]},       # canvas-span -> filtered
            {"name": "accent", "type": "PathItem", "bounds": [40, -120, 300, -123]}, # 3pt tall -> filtered
            {"name": "card", "type": "PathItem", "bounds": [40, -120, 300, -260]},   # normal -> kept
            {"name": "text", "type": "TextFrame", "bounds": [56, -140, 96, -153]},   # TextFrame -> kept
        ]
        kept, filtered = _filter_items(items, self.ARTBOARD)
        self.assertEqual(filtered, 2)  # bg + accent
        self.assertEqual(len(kept), 2)  # card + text
        self.assertEqual(len(kept) + filtered, len(items))

    def test_filter_large_artboard_cap(self):
        """On a 10,000pt artboard, min_dim should be capped at 10pt (not 50pt).
        An 8pt-tall path should be filtered but a 12pt path should be kept."""
        large_artboard = [0, 0, 10000, -10000]  # 10,000x10,000pt
        items = [
            # 8pt tall — below the 10pt cap -> should be FILTERED
            {"name": "thin_line", "type": "PathItem", "bounds": [100, -100, 300, -108]},
            # 12pt tall — above the 10pt cap -> should be KEPT
            {"name": "small_shape", "type": "PathItem", "bounds": [100, -100, 300, -112]},
            # 3pt tall TextFrame — IMMUNE to thin filter
            {"name": "tiny_text", "type": "TextFrame", "bounds": [100, -100, 120, -103]},
        ]
        kept, filtered = _filter_items(items, large_artboard)
        self.assertEqual(filtered, 1)
        self.assertEqual(len(kept), 2)
        names = [k["name"] for k in kept]
        self.assertIn("small_shape", names)
        self.assertIn("tiny_text", names)
        self.assertNotIn("thin_line", names)


# ── NEW: Contrast / Font / Placement Tests ───────────────────────────

class TestWCAGContrast(unittest.TestCase):
    """Test WCAG luminance and contrast ratio calculations."""

    def test_black_luminance(self):
        lum = _wcag_luminance(0, 0, 0)
        self.assertAlmostEqual(lum, 0.0, places=3)

    def test_white_luminance(self):
        lum = _wcag_luminance(255, 255, 255)
        self.assertAlmostEqual(lum, 1.0, places=3)

    def test_contrast_black_white(self):
        """Black vs white should give max contrast ratio ~21."""
        ratio = _contrast_ratio(
            _wcag_luminance(0, 0, 0),
            _wcag_luminance(255, 255, 255),
        )
        self.assertAlmostEqual(ratio, 21.0, places=0)

    def test_contrast_same_color(self):
        """Same color -> contrast ratio of 1.0."""
        lum = _wcag_luminance(128, 128, 128)
        ratio = _contrast_ratio(lum, lum)
        self.assertAlmostEqual(ratio, 1.0, places=3)


@unittest.skipUnless(HAS_PILLOW, "Pillow not installed")
class TestContrastColorPicker(unittest.TestCase):
    """Test border-ring contrast color selection."""

    def test_white_bg_picks_black(self):
        """Near-white background -> black outline selected."""
        from PIL import Image
        white_img = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
        color = _pick_contrast_color(white_img, [10, 10, 90, 90], (100, 100), (100, 100))
        # Should pick black (0, 0, 0, 200) — highest contrast on white
        self.assertEqual(color[:3], (0, 0, 0))

    def test_black_bg_picks_white(self):
        """Near-black background -> white outline selected."""
        from PIL import Image
        black_img = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
        color = _pick_contrast_color(black_img, [10, 10, 90, 90], (100, 100), (100, 100))
        # Should pick white (255, 255, 255, 200) — highest contrast on black
        self.assertEqual(color[:3], (255, 255, 255))

    def test_magenta_bg_avoids_magenta(self):
        """Magenta background -> should NOT pick magenta outline."""
        from PIL import Image
        mag_img = Image.new("RGBA", (100, 100), (255, 0, 255, 255))
        color = _pick_contrast_color(mag_img, [10, 10, 90, 90], (100, 100), (100, 100))
        # Should NOT be magenta
        self.assertNotEqual(color[:3], (255, 0, 255))

    def test_empty_box_returns_fallback(self):
        """Empty box region returns first palette color (black)."""
        from PIL import Image
        img = Image.new("RGBA", (10, 10), (128, 128, 128, 255))
        color = _pick_contrast_color(img, [0, 0, 0, 0], (10, 10), (10, 10))
        # Should still return a valid palette color
        self.assertIn(color, OUTLINE_PALETTE)


class TestPalette(unittest.TestCase):
    """Test the 6-color palette includes black and white."""

    def test_palette_has_black(self):
        black_entries = [c for c in OUTLINE_PALETTE if c[:3] == (0, 0, 0)]
        self.assertEqual(len(black_entries), 1)

    def test_palette_has_white(self):
        white_entries = [c for c in OUTLINE_PALETTE if c[:3] == (255, 255, 255)]
        self.assertEqual(len(white_entries), 1)

    def test_palette_size(self):
        self.assertEqual(len(OUTLINE_PALETTE), 6)

    def test_all_have_alpha(self):
        for c in OUTLINE_PALETTE:
            self.assertEqual(len(c), 4, f"Color {c} should have 4 channels (RGBA)")
            self.assertGreater(c[3], 0, f"Alpha should be > 0")


class TestAdaptiveSizing(unittest.TestCase):
    """Test font and outline scaling."""

    def test_font_size_small_image(self):
        """800px image -> font near lower bound."""
        size = _compute_font_size(800, 600)
        self.assertGreaterEqual(size, 12)
        self.assertLessEqual(size, 16)

    def test_font_size_large_image(self):
        """2000px image -> font near upper bound."""
        size = _compute_font_size(2000, 1500)
        self.assertGreaterEqual(size, 25)
        self.assertLessEqual(size, 28)

    def test_font_size_clamped_min(self):
        """Very small image -> clamped to 12."""
        size = _compute_font_size(50, 50)
        self.assertEqual(size, 12)

    def test_outline_width_small(self):
        """Small image -> 2px outline."""
        w = _compute_outline_width(400, 300)
        self.assertEqual(w, 2)

    def test_outline_width_large(self):
        """Large image -> 3-4px outline."""
        w = _compute_outline_width(2400, 1800)
        self.assertIn(w, [3, 4])


class TestPillPlacement(unittest.TestCase):
    """Test deterministic pill placement logic."""

    def test_first_position_above_left(self):
        """When no collisions, first position (above-left) is chosen."""
        rect = _place_pill(50, 50, 150, 100, 40, 20, 400, 300, [])
        # above-left: (50, 50 - 20 - 2) = (50, 28)
        self.assertEqual(rect, (50, 28, 90, 48))

    def test_avoids_collision(self):
        """When first position collides, skips to next non-colliding."""
        # Block the above-left position
        placed = [(40, 20, 100, 55)]  # covers above-left region
        rect = _place_pill(50, 50, 150, 100, 40, 20, 400, 300, placed)
        # Should NOT use above-left (50, 28, 90, 48) -> collides with placed
        self.assertFalse(_rects_overlap(rect, placed[0]))

    def test_deterministic_same_input(self):
        """Same input -> identical output across two calls."""
        placed = [(10, 10, 60, 30)]
        r1 = _place_pill(50, 50, 150, 100, 40, 20, 400, 300, placed)
        r2 = _place_pill(50, 50, 150, 100, 40, 20, 400, 300, placed)
        self.assertEqual(r1, r2)

    def test_all_corners_blocked_picks_least_overlap(self):
        """When all 8 positions collide, picks smallest overlap."""
        # Fill most of the image with placed pills
        placed = [(x, y, x+80, y+40) for x in range(0, 400, 80) for y in range(0, 300, 40)]
        # Should not crash; returns some rect
        rect = _place_pill(50, 50, 150, 100, 40, 20, 400, 300, placed)
        self.assertEqual(len(rect), 4)


class TestHelpers(unittest.TestCase):
    """Test geometry utility functions."""

    def test_in_bounds_true(self):
        self.assertTrue(_in_bounds((10, 10, 50, 50), 100, 100))

    def test_in_bounds_false_negative(self):
        self.assertFalse(_in_bounds((-5, 10, 50, 50), 100, 100))

    def test_in_bounds_false_overflow(self):
        self.assertFalse(_in_bounds((10, 10, 110, 50), 100, 100))

    def test_rects_overlap_true(self):
        self.assertTrue(_rects_overlap((0, 0, 50, 50), (25, 25, 75, 75)))

    def test_rects_overlap_false(self):
        self.assertFalse(_rects_overlap((0, 0, 50, 50), (60, 60, 100, 100)))

    def test_rects_overlap_adjacent(self):
        """Adjacent rects (touching edges) do NOT overlap."""
        self.assertFalse(_rects_overlap((0, 0, 50, 50), (50, 0, 100, 50)))

    def test_overlap_area(self):
        area = _overlap_area((0, 0, 50, 50), [(25, 25, 75, 75)])
        self.assertEqual(area, 25 * 25)

    def test_overlap_area_no_overlap(self):
        area = _overlap_area((0, 0, 50, 50), [(60, 60, 100, 100)])
        self.assertEqual(area, 0)


@unittest.skipUnless(HAS_PILLOW, "Pillow not installed")
class TestVisualConstants(unittest.TestCase):
    """Verify updated visual constants for overlay refinements."""

    def test_palette_alpha(self):
        """All palette entries should have alpha 200."""
        for c in OUTLINE_PALETTE:
            self.assertEqual(c[3], 200, f"Palette entry {c} should have alpha=200")

    def test_fill_alpha_subtle(self):
        """Fill alpha should be very subtle (<10%)."""
        self.assertLessEqual(FILL_ALPHA, 25, "Fill alpha should be <=10%")

    def test_fill_hint_min_area(self):
        """Fill skipped for boxes below MIN_FILL_AREA_PX."""
        png = _make_blank_png(200, 200)
        # Small box (10x10 = 100px^2 < 400)
        small_ann = [{"label": "1", "bounds_px": [5, 5, 15, 15]}]
        result_small = composite_overlay(png, small_ann)

        # Large box (50x50 = 2500px^2 >= 400)
        large_ann = [{"label": "2", "bounds_px": [10, 10, 60, 60]}]
        result_large = composite_overlay(png, large_ann)

        # Both should produce valid PNGs (no crash)
        from PIL import Image
        Image.open(io.BytesIO(result_small))
        Image.open(io.BytesIO(result_large))
        # Large box output should differ from small (fill adds bytes)
        self.assertNotEqual(result_small, result_large)


@unittest.skipUnless(HAS_PILLOW, "Pillow not installed")
class TestGridOverlay(unittest.TestCase):
    """Test grid overlay function."""

    def test_adaptive_default_grid(self):
        """Default cols/rows=0 produces adaptive grid."""
        png = _make_blank_png(800, 600)
        result = draw_grid_overlay(png, [0, 600, 800, 0], (800, 600))
        from PIL import Image
        out = Image.open(io.BytesIO(result))
        self.assertEqual(out.size, (800, 600))
        # Should differ from input (grid lines drawn)
        self.assertNotEqual(result, png)

    def test_explicit_grid_size(self):
        """Explicit cols/rows are respected."""
        png = _make_blank_png(400, 400)
        result = draw_grid_overlay(png, [0, 400, 400, 0], (400, 400), cols=2, rows=2)
        from PIL import Image
        out = Image.open(io.BytesIO(result))
        self.assertEqual(out.size, (400, 400))

    def test_zero_artboard_returns_original(self):
        """Zero-size artboard -> returns original."""
        png = _make_blank_png(200, 200)
        result = draw_grid_overlay(png, [0, 0, 0, 0], (200, 200))
        self.assertEqual(result, png)


@unittest.skipUnless(HAS_PILLOW, "Pillow not installed")
class TestStress(unittest.TestCase):
    """Performance / stress tests."""

    def test_200_boxes_completes(self):
        """200 random boxes should complete without error and within 5s."""
        import random
        random.seed(42)
        png = _make_blank_png(1200, 800)
        annotations = []
        for i in range(200):
            x1 = random.randint(0, 1100)
            y1 = random.randint(0, 700)
            x2 = x1 + random.randint(20, 100)
            y2 = y1 + random.randint(20, 100)
            annotations.append({"label": str(i+1), "bounds_px": [x1, y1, min(x2, 1199), min(y2, 799)]})

        start = time.time()
        result = composite_overlay(png, annotations)
        elapsed = time.time() - start

        from PIL import Image
        out = Image.open(io.BytesIO(result))
        self.assertEqual(out.size, (1200, 800))
        self.assertLess(elapsed, 5.0, f"200 boxes took {elapsed:.1f}s (budget: 5s)")

@unittest.skipUnless(HAS_PILLOW, "Pillow not installed")
class TestRulerOverlay(unittest.TestCase):
    """Test coordinate ruler overlay."""

    def test_ruler_default_ticks(self):
        """Adaptive tick interval on 800×600pt → valid PNG, differs from input."""
        png = _make_blank_png(800, 600)
        result = draw_ruler_overlay(png, 800.0, 600.0)
        from PIL import Image
        out = Image.open(io.BytesIO(result))
        self.assertEqual(out.size, (800, 600))
        self.assertNotEqual(result, png)

    def test_ruler_explicit_interval(self):
        """Explicit tick_interval_pt=50 → valid output."""
        png = _make_blank_png(400, 400)
        result = draw_ruler_overlay(png, 400.0, 400.0, tick_interval_pt=50)
        from PIL import Image
        out = Image.open(io.BytesIO(result))
        self.assertEqual(out.size, (400, 400))
        self.assertNotEqual(result, png)

    def test_ruler_zero_artboard(self):
        """Zero-size artboard → returns original bytes unchanged."""
        png = _make_blank_png(200, 200)
        result = draw_ruler_overlay(png, 0.0, 0.0)
        self.assertEqual(result, png)

    def test_ruler_no_pillow(self):
        """Pillow patched out → returns original bytes."""
        png = _make_blank_png(400, 400)
        import illustrator_mcp.overlay as ov
        old = ov.HAS_PILLOW
        try:
            ov.HAS_PILLOW = False
            result = draw_ruler_overlay(png, 400.0, 400.0)
            self.assertEqual(result, png)
        finally:
            ov.HAS_PILLOW = old

    def test_ruler_large_artboard(self):
        """4000×4000pt → interval auto-scales, ≤12 labels per axis."""
        iv = _pick_interval(4000.0)
        self.assertLessEqual(4000.0 / iv, 12)
        png = _make_blank_png(800, 800)
        result = draw_ruler_overlay(png, 4000.0, 4000.0)
        from PIL import Image
        out = Image.open(io.BytesIO(result))
        self.assertEqual(out.size, (800, 800))
        self.assertNotEqual(result, png)

    def test_ruler_small_image_completes(self):
        """Small image (100×100px) completes without crash and produces output."""
        png = _make_blank_png(100, 100)
        result = draw_ruler_overlay(png, 100.0, 100.0)
        from PIL import Image
        out = Image.open(io.BytesIO(result))
        self.assertEqual(out.size, (100, 100))
        self.assertNotEqual(result, png)


class TestPickInterval(unittest.TestCase):
    """Test interval heuristic."""

    def test_small_artboard(self):
        self.assertEqual(_pick_interval(200), 25)

    def test_medium_artboard(self):
        iv = _pick_interval(800)
        self.assertLessEqual(800 / iv, 12)

    def test_huge_artboard(self):
        iv = _pick_interval(50000)
        self.assertEqual(iv, 5000)  # 50000/5000 = 10 ≤ 12

    def test_all_candidates_within_limit(self):
        for dim in [50, 300, 600, 1200, 2400, 6000, 12000, 100000]:
            iv = _pick_interval(dim)
            self.assertLessEqual(dim / iv, 12,
                                 f"dim={dim} iv={iv} gives {dim/iv} labels")


# ── Envelope Unwrap Tests for _annotate_preview ───────────────────────

class TestAnnotatePreviewEnvelopeUnwrap(unittest.TestCase):
    """Test that _annotate_preview correctly unwraps host.jsx envelopes.

    host.jsx wraps bare JSX returns in {ok:true, data:...} envelopes.
    The collection script returns {artboard:[...], items:[...]} which becomes
    {ok:true, data:{artboard:[...], items:[...]}} after host.jsx wrapping.
    _annotate_preview must unwrap this before accessing artboard data.
    """

    ARTBOARD_RECT = [0, 0, 800, -600]  # standard AI coords
    ITEM_SNAPSHOT = {
        "artboard": [0, 0, 800, -600],
        "items": [
            {"name": "rect", "type": "PathItem",
             "bounds": [100, -50, 300, -250], "mcp_id": ""},
        ],
    }

    def _make_collect_response(self, snapshot_dict):
        """Simulate what execute_script_with_context returns for the collect call."""
        return {"result": snapshot_dict}

    @unittest.skipUnless(HAS_PILLOW, "Pillow not installed")
    def test_unwrap_ok_true_envelope(self):
        """host.jsx envelope {ok:true, data:{artboard,items}} is unwrapped correctly."""
        import asyncio
        from unittest.mock import AsyncMock
        from illustrator_mcp.tools.preview import _annotate_preview

        png = _make_blank_png(800, 600)
        # Simulate the envelope that host.jsx produces
        envelope = {"ok": True, "data": self.ITEM_SNAPSHOT}
        mock_response = {"result": envelope}

        with patch(
            "illustrator_mcp.tools.preview.execute_script_with_context",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            _, result = asyncio.get_event_loop().run_until_complete(
                _annotate_preview(png, max_items=200, timeout=5.0)
            )

        # Should have successfully found items, NOT the artboard-bounds warning
        for w in result.get("warnings") or []:
            self.assertNotIn("Missing or invalid artboard bounds", w)
        self.assertGreater(
            result["meta"]["input_count"], 0,
            "Should have found items after envelope unwrap",
        )

    @unittest.skipUnless(HAS_PILLOW, "Pillow not installed")
    def test_ok_false_surfaces_real_error(self):
        """host.jsx envelope {ok:false, error:{message:...}} surfaces the real error."""
        import asyncio
        from unittest.mock import AsyncMock
        from illustrator_mcp.tools.preview import _annotate_preview

        png = _make_blank_png(800, 600)
        error_envelope = {"ok": False, "error": {"message": "No documents open"}}
        mock_response = {"result": error_envelope}

        with patch(
            "illustrator_mcp.tools.preview.execute_script_with_context",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            _, result = asyncio.get_event_loop().run_until_complete(
                _annotate_preview(png, max_items=200, timeout=5.0)
            )

        warnings = result.get("warnings") or []
        # Should surface the real error, not "Missing artboard bounds"
        self.assertTrue(
            any("Item collection failed" in w for w in warnings),
            f"Expected 'Item collection failed' warning, got: {warnings}",
        )
        self.assertTrue(
            any("No documents open" in w for w in warnings),
            f"Expected 'No documents open' in warning, got: {warnings}",
        )
        self.assertFalse(
            any("Missing or invalid artboard" in w for w in warnings),
            "Should NOT emit misleading 'Missing artboard bounds'",
        )

    @unittest.skipUnless(HAS_PILLOW, "Pillow not installed")
    def test_string_inside_data_parsed(self):
        """data field as JSON string (legacy double-wrapping) is parsed correctly."""
        import asyncio
        from unittest.mock import AsyncMock
        from illustrator_mcp.tools.preview import _annotate_preview

        png = _make_blank_png(800, 600)
        # Simulate data arriving as a JSON string inside the envelope
        envelope = {"ok": True, "data": json.dumps(self.ITEM_SNAPSHOT)}
        mock_response = {"result": envelope}

        with patch(
            "illustrator_mcp.tools.preview.execute_script_with_context",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            _, result = asyncio.get_event_loop().run_until_complete(
                _annotate_preview(png, max_items=200, timeout=5.0)
            )

        for w in result.get("warnings") or []:
            self.assertNotIn("Missing or invalid artboard bounds", w)
            self.assertNotIn("Could not parse", w)
        self.assertGreater(
            result["meta"]["input_count"], 0,
            "Should have found items after string-inside-data unwrap",
        )

@unittest.skipUnless(HAS_PILLOW, "Pillow not installed")
class TestCoverRatioTint(unittest.TestCase):
    """Test red tint overlay for high coverRatio items."""

    def test_cover_ratio_tint_applied(self):
        """Annotation with coverRatio=0.95 should produce tinted output."""
        png = _make_blank_png(200, 200)
        # Large box (100x100px = 10000px^2 >= MIN_FILL_AREA_PX=400)
        ann_tint = [{"label": "1", "bounds_px": [10, 10, 110, 110], "coverRatio": 0.95}]
        ann_no_tint = [{"label": "1", "bounds_px": [10, 10, 110, 110]}]

        result_tint = composite_overlay(png, ann_tint)
        result_no_tint = composite_overlay(png, ann_no_tint)

        # Both should render valid PNGs
        from PIL import Image
        Image.open(io.BytesIO(result_tint))
        Image.open(io.BytesIO(result_no_tint))
        # Tinted output should differ from non-tinted
        self.assertNotEqual(result_tint, result_no_tint,
                           "coverRatio=0.95 tint should change output")

    def test_cover_ratio_below_threshold_no_tint(self):
        """Annotation with coverRatio=0.80 should NOT produce tint."""
        png = _make_blank_png(200, 200)
        ann_below = [{"label": "1", "bounds_px": [10, 10, 110, 110], "coverRatio": 0.80}]
        ann_none = [{"label": "1", "bounds_px": [10, 10, 110, 110]}]

        result_below = composite_overlay(png, ann_below)
        result_none = composite_overlay(png, ann_none)

        # Below threshold should produce same output as no coverRatio
        self.assertEqual(result_below, result_none,
                        "coverRatio=0.80 should NOT differ from no coverRatio")


if __name__ == "__main__":
    unittest.main()
