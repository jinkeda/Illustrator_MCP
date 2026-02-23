"""
Tests for draw_probe_overlay() in overlay.py.

Pure Python tests — no Illustrator connection needed.
"""

import io
import struct
import pytest

from PIL import Image

from illustrator_mcp.overlay import draw_probe_overlay, HAS_PILLOW


def _make_solid_png(w: int, h: int, color=(200, 200, 200)) -> bytes:
    """Create a solid-color PNG for testing."""
    img = Image.new("RGBA", (w, h), (*color, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _png_dimensions(data: bytes) -> tuple:
    """Read dimensions from PNG bytes."""
    img = Image.open(io.BytesIO(data))
    return img.size


class TestDrawProbeOverlay:
    """Tests for the probe-point overlay renderer."""

    def test_no_points_returns_original(self):
        """Empty probe list returns original bytes unchanged."""
        png = _make_solid_png(100, 100)
        result = draw_probe_overlay(png, [], 100.0, 100.0)
        assert result == png

    def test_none_points_returns_original(self):
        """None probe list is handled gracefully."""
        png = _make_solid_png(100, 100)
        result = draw_probe_overlay(png, None, 100.0, 100.0)
        assert result == png

    def test_single_probe_modifies_image(self):
        """A single probe changes the output bytes."""
        png = _make_solid_png(200, 200)
        probes = [{"x": 100, "y": 100, "label": "center"}]
        result = draw_probe_overlay(png, probes, 200.0, 200.0)
        assert result != png
        # Output is valid PNG
        w, h = _png_dimensions(result)
        assert w == 200 and h == 200

    def test_multiple_probes(self):
        """Multiple probes all render without error."""
        png = _make_solid_png(300, 300)
        probes = [
            {"x": 50, "y": 50, "label": "A"},
            {"x": 150, "y": 150, "label": "B"},
            {"x": 250, "y": 250, "label": "C"},
        ]
        result = draw_probe_overlay(png, probes, 300.0, 300.0)
        assert result != png

    def test_probe_at_edge(self):
        """Probes at image edges don't crash."""
        png = _make_solid_png(200, 200)
        probes = [
            {"x": 0, "y": 0, "label": "corner"},
            {"x": 200, "y": 200, "label": "opposite"},
        ]
        result = draw_probe_overlay(png, probes, 200.0, 200.0)
        assert _png_dimensions(result) == (200, 200)

    def test_probe_outside_bounds(self):
        """Probes outside artboard don't crash."""
        png = _make_solid_png(200, 200)
        probes = [{"x": 500, "y": -100, "label": "outside"}]
        result = draw_probe_overlay(png, probes, 200.0, 200.0)
        assert _png_dimensions(result) == (200, 200)

    def test_probe_without_label(self):
        """Probes without labels still render coordinates."""
        png = _make_solid_png(200, 200)
        probes = [{"x": 100, "y": 100}]
        result = draw_probe_overlay(png, probes, 200.0, 200.0)
        assert result != png

    def test_zero_artboard_returns_original(self):
        """Zero-size artboard returns original bytes."""
        png = _make_solid_png(100, 100)
        result = draw_probe_overlay(png, [{"x": 50, "y": 50}], 0.0, 0.0)
        assert result == png

    def test_negative_artboard_returns_original(self):
        """Negative artboard dimensions return original bytes."""
        png = _make_solid_png(100, 100)
        result = draw_probe_overlay(png, [{"x": 50, "y": 50}], -100.0, 100.0)
        assert result == png

    def test_output_is_valid_png(self):
        """Output is a valid PNG image."""
        png = _make_solid_png(100, 100)
        probes = [{"x": 50, "y": 50, "label": "test"}]
        result = draw_probe_overlay(png, probes, 100.0, 100.0)
        # Should be valid PNG (starts with PNG magic bytes)
        assert result[:4] == b'\x89PNG'

    def test_color_cycling(self):
        """More probes than palette colors doesn't crash (palette wraps)."""
        png = _make_solid_png(400, 400)
        # Create more probes than the 6-color palette
        probes = [{"x": i * 40, "y": i * 40, "label": f"P{i}"} for i in range(10)]
        result = draw_probe_overlay(png, probes, 400.0, 400.0)
        assert _png_dimensions(result) == (400, 400)

    def test_large_coordinates(self):
        """Very large coordinate values don't crash."""
        png = _make_solid_png(200, 200)
        probes = [{"x": 99999, "y": 99999, "label": "far"}]
        result = draw_probe_overlay(png, probes, 200.0, 200.0)
        assert _png_dimensions(result) == (200, 200)

    def test_float_coordinates(self):
        """Fractional coordinates work correctly."""
        png = _make_solid_png(200, 200)
        probes = [{"x": 100.5, "y": 50.75, "label": "fractional"}]
        result = draw_probe_overlay(png, probes, 200.0, 200.0)
        assert result != png
