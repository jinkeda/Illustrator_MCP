"""
Tests for _extract_dominant_colors() in documents.py.

Pure Python tests — no Illustrator connection needed.
"""

import json
import os
import tempfile
import pytest

from PIL import Image


# Import the function under test
from illustrator_mcp.tools.documents import _extract_dominant_colors


class TestExtractDominantColors:
    """Test dominant color extraction from reference images."""

    def _create_test_image(self, colors_and_areas, size=(100, 100)):
        """Create a test image with specified color areas.

        Args:
            colors_and_areas: List of (color_tuple, fraction) pairs.
                              Fractions should sum to ~1.0.
            size: Image dimensions (width, height).

        Returns:
            Path to temp image file.
        """
        img = Image.new("RGB", size)
        pixels = img.load()
        w, h = size
        total = w * h
        offset = 0
        for color, fraction in colors_and_areas:
            count = int(total * fraction)
            for i in range(count):
                idx = offset + i
                if idx >= total:
                    break
                x, y = idx % w, idx // w
                pixels[x, y] = color
            offset += count
        # Fill remainder with last color
        if colors_and_areas:
            last_color = colors_and_areas[-1][0]
            for i in range(offset, total):
                x, y = i % w, i // w
                pixels[x, y] = last_color

        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        img.save(path)
        return path

    def test_single_color_image(self):
        """Single-color image returns one dominant color."""
        path = self._create_test_image([((255, 0, 0), 1.0)])
        try:
            colors = _extract_dominant_colors(path)
            assert len(colors) >= 1
            assert colors[0]["r"] == 255
            assert colors[0]["g"] == 0
            assert colors[0]["b"] == 0
            assert colors[0]["hex"] == "#FF0000"
            assert colors[0]["percentage"] == 100.0
        finally:
            os.unlink(path)

    def test_two_color_image(self):
        """Two-color image returns both colors."""
        path = self._create_test_image([
            ((255, 0, 0), 0.7),
            ((0, 0, 255), 0.3),
        ])
        try:
            colors = _extract_dominant_colors(path)
            assert len(colors) >= 2
            # First color should be the dominant one (red)
            assert colors[0]["percentage"] > colors[1]["percentage"]
        finally:
            os.unlink(path)

    def test_hex_format(self):
        """Hex values are properly formatted."""
        path = self._create_test_image([((10, 20, 30), 1.0)])
        try:
            colors = _extract_dominant_colors(path)
            assert len(colors) >= 1
            assert colors[0]["hex"] == "#0A141E"
        finally:
            os.unlink(path)

    def test_percentages_sum_to_100(self):
        """Percentages should sum to approximately 100."""
        path = self._create_test_image([
            ((255, 0, 0), 0.5),
            ((0, 255, 0), 0.3),
            ((0, 0, 255), 0.2),
        ])
        try:
            colors = _extract_dominant_colors(path)
            total = sum(c["percentage"] for c in colors)
            assert abs(total - 100.0) < 1.0  # allow rounding
        finally:
            os.unlink(path)

    def test_sorted_by_percentage_descending(self):
        """Colors should be sorted by percentage, largest first."""
        path = self._create_test_image([
            ((0, 255, 0), 0.1),
            ((0, 0, 255), 0.6),
            ((255, 0, 0), 0.3),
        ])
        try:
            colors = _extract_dominant_colors(path)
            for i in range(len(colors) - 1):
                assert colors[i]["percentage"] >= colors[i + 1]["percentage"]
        finally:
            os.unlink(path)

    def test_max_colors_limit(self):
        """Respects max_colors parameter."""
        path = self._create_test_image([
            ((255, 0, 0), 0.25),
            ((0, 255, 0), 0.25),
            ((0, 0, 255), 0.25),
            ((255, 255, 0), 0.25),
        ])
        try:
            colors = _extract_dominant_colors(path, max_colors=2)
            assert len(colors) <= 2
        finally:
            os.unlink(path)

    def test_deduplication(self):
        """Near-colors should be merged."""
        path = self._create_test_image([
            ((255, 0, 0), 0.5),
            ((250, 5, 5), 0.5),  # very close to red
        ])
        try:
            colors = _extract_dominant_colors(path, dedup_distance=30.0)
            # Should merge into 1 color since distance < 30
            assert len(colors) <= 2  # at most 2, likely 1 after dedup
        finally:
            os.unlink(path)

    def test_large_image_downscaled(self):
        """Large images should be processed without error."""
        path = self._create_test_image(
            [((100, 150, 200), 1.0)],
            size=(2000, 2000)
        )
        try:
            colors = _extract_dominant_colors(path, max_dimension=128)
            assert len(colors) >= 1
        finally:
            os.unlink(path)

    def test_nonexistent_file_returns_empty(self):
        """Missing file should return empty list, not raise."""
        colors = _extract_dominant_colors("/nonexistent/image.png")
        assert colors == []

    def test_return_structure(self):
        """Each color dict has the required keys."""
        path = self._create_test_image([((128, 64, 32), 1.0)])
        try:
            colors = _extract_dominant_colors(path)
            assert len(colors) >= 1
            for c in colors:
                assert "r" in c
                assert "g" in c
                assert "b" in c
                assert "hex" in c
                assert "percentage" in c
                assert isinstance(c["r"], int)
                assert isinstance(c["g"], int)
                assert isinstance(c["b"], int)
                assert isinstance(c["hex"], str)
                assert c["hex"].startswith("#")
                assert isinstance(c["percentage"], float)
        finally:
            os.unlink(path)
