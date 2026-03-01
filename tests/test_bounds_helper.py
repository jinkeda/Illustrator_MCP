"""Tests for bounds_intersects_artboard() shared helper."""

import pytest
from illustrator_mcp.utils.bounds import (
    bounds_intersects_artboard,
    BOUNDS_SPACE_ILLUSTRATOR_Y_UP,
)


class TestBoundsIntersectsArtboard:
    """Pure Python tests — no Illustrator dependency."""

    # Artboard: 800×600 at origin
    # Illustrator Y-up: [left=0, top=0, right=800, bottom=-600]
    AB = [0.0, 0.0, 800.0, -600.0]

    def test_fully_inside(self):
        """Item fully inside artboard → intersects=True."""
        item = [100.0, -100.0, 300.0, -300.0]
        ok, details = bounds_intersects_artboard(item, self.AB)
        assert ok is True
        assert details["overlap_area"] > 0
        assert details["bounds_space"] == BOUNDS_SPACE_ILLUSTRATOR_Y_UP

    def test_fully_outside(self):
        """Item fully outside artboard → intersects=False."""
        item = [1000.0, -100.0, 1200.0, -300.0]
        ok, details = bounds_intersects_artboard(item, self.AB)
        assert ok is False
        assert details["overlap_area"] == 0
        assert details["overlap_rect"] is None

    def test_tiny_overlap_below_epsilon(self):
        """Overlap area < epsilon → intersects=False (edge-touching)."""
        # Item barely touches right edge: 0.5 pt overlap width, 200 pt height
        # overlap area = 0.5 * 200 = 100 — but let's make it truly tiny
        item = [799.9, -100.0, 800.1, -100.1]  # 0.1 × 0.1 = 0.01 pt²
        ok, details = bounds_intersects_artboard(item, self.AB, epsilon=1.0)
        assert ok is False
        assert 0 < details["overlap_area"] < 1.0

    def test_overlap_above_epsilon(self):
        """Overlap area > epsilon → intersects=True."""
        # Bottom-right corner overlap
        item = [700.0, -500.0, 900.0, -700.0]
        ok, details = bounds_intersects_artboard(item, self.AB)
        assert ok is True
        assert details["overlap_area"] >= 1.0
        assert details["overlap_rect"] is not None

    def test_edge_touching_zero_area(self):
        """Item touching edge exactly (zero overlap area) → False."""
        # Item sits exactly at right edge of artboard
        item = [800.0, -100.0, 900.0, -300.0]
        ok, details = bounds_intersects_artboard(item, self.AB)
        assert ok is False
        assert details["overlap_area"] == 0

    def test_item_above_artboard(self):
        """Item above artboard (positive Y in Y-up) → no intersection."""
        # Artboard top is 0, item is at Y=100 to Y=200 (above)
        item = [100.0, 200.0, 300.0, 100.0]
        ok, details = bounds_intersects_artboard(item, self.AB)
        assert ok is False
        assert details["overlap_area"] == 0

    def test_details_always_present(self):
        """Details dict always has all required keys."""
        item = [100.0, -100.0, 300.0, -300.0]
        _, details = bounds_intersects_artboard(item, self.AB)
        assert "created_bounds" in details
        assert "artboard_bounds" in details
        assert "bounds_space" in details
        assert "overlap_area" in details
        assert "overlap_rect" in details
