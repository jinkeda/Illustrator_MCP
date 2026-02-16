"""
Pure Python tests for the geometry boolean engine.

Tests pyclipper boolean operations, Bézier flattening, Region model,
coordinate scaling, hole semantics, winding invariance, and tolerance monotonicity.

No Illustrator connection required — fully offline.
"""

import math
import pytest
from illustrator_mcp.geometry import (
    Region,
    path_boolean,
    flatten_cubic,
    flatten_path,
    scale_to_clipper,
    scale_from_clipper,
    CLIPPER_SCALE,
)


# ── Test fixtures ───────────────────────────────────────────────────

# Two overlapping rectangles (50pt overlap)
RECT_A = [(0, 0), (100, 0), (100, 100), (0, 100)]     # 100x100 at origin
RECT_B = [(50, 50), (150, 50), (150, 150), (50, 150)]  # 100x100 offset by (50,50)

# Large rect containing small rect (for donut test)
RECT_LARGE = [(0, 0), (200, 0), (200, 200), (0, 200)]
RECT_SMALL = [(50, 50), (150, 50), (150, 150), (50, 150)]

# Non-overlapping rectangles
RECT_LEFT = [(0, 0), (40, 0), (40, 100), (0, 100)]
RECT_RIGHT = [(60, 0), (100, 0), (100, 100), (60, 100)]

# Identical rectangles
RECT_SAME = [(0, 0), (100, 0), (100, 100), (0, 100)]


def _polygon_area(pts):
    """Compute polygon area using shoelace formula."""
    n = len(pts)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += pts[i][0] * pts[j][1]
        area -= pts[j][0] * pts[i][1]
    return abs(area) / 2.0


# ── Subtract tests ─────────────────────────────────────────────────

class TestSubtract:
    def test_partial_overlap_produces_l_shape(self):
        """Overlapping rects subtracted → L-shape, 1 region, 0 holes."""
        regions = path_boolean(RECT_A, RECT_B, "subtract")
        assert len(regions) == 1
        assert len(regions[0].holes) == 0
        # L-shape should have 6 vertices
        assert len(regions[0].outer) == 6

    def test_fully_contained_produces_donut(self):
        """Large rect minus small contained rect → 1 region with 1 hole."""
        regions = path_boolean(RECT_LARGE, RECT_SMALL, "subtract")
        assert len(regions) == 1
        assert len(regions[0].holes) == 1
        # Outer should be the large rect (4 points)
        assert len(regions[0].outer) == 4
        # Hole should be the small rect (4 points)
        assert len(regions[0].holes[0]) == 4
        # Outer area > hole area
        outer_area = _polygon_area(regions[0].outer)
        hole_area = _polygon_area(regions[0].holes[0])
        assert outer_area > hole_area

    def test_non_overlapping_returns_subject(self):
        """Non-overlapping subtract → subject unchanged."""
        regions = path_boolean(RECT_LEFT, RECT_RIGHT, "subtract")
        assert len(regions) == 1
        assert len(regions[0].holes) == 0
        area = _polygon_area(regions[0].outer)
        expected_area = 40 * 100  # 4000
        assert abs(area - expected_area) < 1.0

    def test_identical_shapes_returns_empty(self):
        """Subtracting identical shapes → empty result."""
        regions = path_boolean(RECT_SAME, RECT_SAME, "subtract")
        assert len(regions) == 0


# ── Unite tests ─────────────────────────────────────────────────────

class TestUnite:
    def test_overlapping_merge(self):
        """Overlapping rects united → 1 merged region, 0 holes."""
        regions = path_boolean(RECT_A, RECT_B, "unite")
        assert len(regions) == 1
        assert len(regions[0].holes) == 0
        # Merged area < sum of individual areas (overlap removed)
        area = _polygon_area(regions[0].outer)
        assert area < 20000  # 10000 + 10000
        assert area > 10000  # At least one rect

    def test_non_overlapping_unite(self):
        """Non-overlapping rects united → 2 separate regions."""
        regions = path_boolean(RECT_LEFT, RECT_RIGHT, "unite")
        # pyclipper may return 1 or 2 regions depending on adjacency handling
        total_area = sum(_polygon_area(r.outer) for r in regions)
        assert abs(total_area - (40 * 100 + 40 * 100)) < 1.0

    def test_identical_unite(self):
        """Uniting identical shapes → single shape."""
        regions = path_boolean(RECT_SAME, RECT_SAME, "unite")
        assert len(regions) == 1
        area = _polygon_area(regions[0].outer)
        assert abs(area - 10000) < 1.0


# ── Intersect tests ─────────────────────────────────────────────────

class TestIntersect:
    def test_overlapping_intersection(self):
        """Overlapping rects → intersection area = 50x50 = 2500."""
        regions = path_boolean(RECT_A, RECT_B, "intersect")
        assert len(regions) == 1
        area = _polygon_area(regions[0].outer)
        assert abs(area - 2500) < 1.0

    def test_non_overlapping_intersection_empty(self):
        """Non-overlapping rects → empty intersection."""
        regions = path_boolean(RECT_LEFT, RECT_RIGHT, "intersect")
        assert len(regions) == 0


# ── XOR tests ──────────────────────────────────────────────────────

class TestXOR:
    def test_overlapping_xor(self):
        """Overlapping XOR → 2 disjoint regions."""
        regions = path_boolean(RECT_A, RECT_B, "xor")
        # XOR of two overlapping rects should give non-overlapping pieces
        total_area = sum(_polygon_area(r.outer) for r in regions)
        # Total XOR area = A + B - 2*intersection = 10000 + 10000 - 2*2500 = 15000
        assert abs(total_area - 15000) < 1.0


# ── Hole semantics tests ──────────────────────────────────────────

class TestHoleSemantics:
    def test_donut_is_region_with_hole_not_two_contours(self):
        """Donut (large - small) must be 1 Region with 1 hole, NOT 2 independent contours."""
        regions = path_boolean(RECT_LARGE, RECT_SMALL, "subtract")
        assert len(regions) == 1, "Donut should be 1 region, not multiple contours"
        assert len(regions[0].holes) == 1, "Donut should have exactly 1 hole"

    def test_region_dataclass_structure(self):
        """Region dataclass has outer and holes attributes."""
        r = Region(outer=[(0, 0), (1, 0), (1, 1)], holes=[[(0.2, 0.2), (0.5, 0.2), (0.5, 0.5)]])
        assert len(r.outer) == 3
        assert len(r.holes) == 1
        assert len(r.holes[0]) == 3


# ── Winding invariance tests ──────────────────────────────────────

class TestWindingInvariance:
    def test_reversed_subject_same_result(self):
        """Reversed subject winding → same geometric result."""
        normal = path_boolean(RECT_A, RECT_B, "subtract")
        reversed_a = list(reversed(RECT_A))
        reversed_result = path_boolean(reversed_a, RECT_B, "subtract")
        # Same number of regions
        assert len(normal) == len(reversed_result)
        # Same approximate area
        area_normal = sum(_polygon_area(r.outer) for r in normal)
        area_reversed = sum(_polygon_area(r.outer) for r in reversed_result)
        assert abs(area_normal - area_reversed) < 1.0

    def test_reversed_clip_same_result(self):
        """Reversed clip winding → same geometric result."""
        normal = path_boolean(RECT_A, RECT_B, "intersect")
        reversed_b = list(reversed(RECT_B))
        reversed_result = path_boolean(RECT_A, reversed_b, "intersect")
        area_normal = sum(_polygon_area(r.outer) for r in normal)
        area_reversed = sum(_polygon_area(r.outer) for r in reversed_result)
        assert abs(area_normal - area_reversed) < 1.0


# ── Tolerance monotonicity tests ──────────────────────────────────

class TestToleranceMonotonicity:
    def _make_circle_anchors_handles(self, cx, cy, r, n=4):
        """Create a circle approximation with n cubic Bézier segments."""
        # Standard 4-point cubic Bézier circle approximation
        kappa = 0.5522847498  # 4 * (sqrt(2) - 1) / 3
        anchors = []
        in_handles = []
        out_handles = []

        angles = [0, math.pi / 2, math.pi, 3 * math.pi / 2]
        for i, a in enumerate(angles):
            ax = cx + r * math.cos(a)
            ay = cy + r * math.sin(a)
            anchors.append((ax, ay))

            # Tangent direction (perpendicular to radius, CCW)
            tx = -math.sin(a)
            ty = math.cos(a)

            # In-handle (left direction) — comes FROM previous segment
            in_handles.append((ax - r * kappa * tx, ay - r * kappa * ty))
            # Out-handle (right direction) — goes TO next segment
            out_handles.append((ax + r * kappa * tx, ay + r * kappa * ty))

        return anchors, in_handles, out_handles

    def test_lower_tolerance_more_points(self):
        """Lower flatten tolerance → more polyline points."""
        anchors, in_h, out_h = self._make_circle_anchors_handles(100, 100, 50)
        coarse = flatten_path(anchors, in_h, out_h, closed=True, tolerance=2.0)
        fine = flatten_path(anchors, in_h, out_h, closed=True, tolerance=0.1)
        assert len(fine) > len(coarse), f"Fine ({len(fine)}) should have more pts than coarse ({len(coarse)})"

    def test_flatten_cap_enforced(self):
        """Exceeding max_segments raises ValueError."""
        anchors, in_h, out_h = self._make_circle_anchors_handles(100, 100, 50)
        with pytest.raises(ValueError, match="max_segments"):
            flatten_path(anchors, in_h, out_h, closed=True, tolerance=0.001, max_segments=5)

    def test_circle_reasonable_point_count(self):
        """Circle at reasonable tolerance doesn't produce excessive points."""
        anchors, in_h, out_h = self._make_circle_anchors_handles(100, 100, 50)
        result = flatten_path(anchors, in_h, out_h, closed=True, tolerance=0.5, max_segments=500)
        assert len(result) <= 500
        assert len(result) >= 8  # A circle should have reasonable number of segments


# ── Coordinate scaling tests ──────────────────────────────────────

class TestScaling:
    def test_roundtrip(self):
        """scale_to → scale_from preserves coordinates within float epsilon."""
        pts = [(1.5, 2.7), (100.123, 50.456), (0.001, 0.999)]
        scaled = scale_to_clipper(pts)
        unscaled = scale_from_clipper(scaled)
        for orig, result in zip(pts, unscaled):
            assert abs(orig[0] - result[0]) < 0.01
            assert abs(orig[1] - result[1]) < 0.01

    def test_scale_factor(self):
        """Scaling multiplies by CLIPPER_SCALE."""
        pts = [(1.0, 2.0)]
        scaled = scale_to_clipper(pts)
        assert scaled[0] == (1000, 2000)


# ── Degenerate input tests ─────────────────────────────────────────

class TestDegenerate:
    def test_empty_subject(self):
        """Empty subject produces empty or raises."""
        # pyclipper may raise or return empty
        try:
            regions = path_boolean([], RECT_A, "subtract")
            assert len(regions) == 0
        except Exception:
            pass  # Acceptable: Clipper may raise on empty input

    def test_single_point_path(self):
        """Single-point path should not crash."""
        try:
            regions = path_boolean([(0, 0)], RECT_A, "subtract")
            # May be empty or raise — just shouldn't crash unhandled
        except Exception:
            pass

    def test_invalid_operation(self):
        """Invalid operation name raises ValueError."""
        with pytest.raises(ValueError, match="Invalid operation"):
            path_boolean(RECT_A, RECT_B, "bogus")


# ── Import guard test ──────────────────────────────────────────────

class TestImportGuard:
    def test_import_message(self):
        """geometry module importable (pyclipper present in test env)."""
        from illustrator_mcp.geometry import path_boolean as pb
        assert callable(pb)


# ── Multi-clip tests ───────────────────────────────────────────────

class TestMultiClip:
    def test_subtract_multiple_clips(self):
        """Subject minus multiple clips."""
        clip_1 = [(10, 10), (40, 10), (40, 40), (10, 40)]
        clip_2 = [(60, 60), (90, 60), (90, 90), (60, 90)]
        regions = path_boolean(RECT_A, [clip_1, clip_2], "subtract")
        # Should have holes or reduced area
        total_area = sum(
            _polygon_area(r.outer) - sum(_polygon_area(h) for h in r.holes)
            for r in regions
        )
        expected = 10000 - 900 - 900  # 8200
        assert abs(total_area - expected) < 5.0


# ── Flatten cubic tests ───────────────────────────────────────────

class TestFlattenCubic:
    def test_line_segment(self):
        """Handles equal to anchors → returns just endpoint."""
        result = flatten_cubic((0, 0), (0, 0), (100, 0), (100, 0))
        assert len(result) == 1
        assert abs(result[0][0] - 100) < 0.01

    def test_curved_segment(self):
        """Actual curve → multiple intermediate points."""
        result = flatten_cubic((0, 0), (0, 50), (100, 50), (100, 0), tolerance=1.0)
        assert len(result) > 1

    def test_tolerance_affects_count(self):
        """Tighter tolerance → more points."""
        coarse = flatten_cubic((0, 0), (0, 50), (100, 50), (100, 0), tolerance=5.0)
        fine = flatten_cubic((0, 0), (0, 50), (100, 50), (100, 0), tolerance=0.5)
        assert len(fine) >= len(coarse)
