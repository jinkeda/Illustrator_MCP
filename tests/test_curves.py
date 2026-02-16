"""
Tests for curves.py — Python source-of-truth for Bézier curve helpers.

Tests cover:
- Catmull-Rom: endpoint duplication, wrapping, degenerate cases, tension
- Circular/elliptical arcs: kappa accuracy, segmentation, full circle
- Rounded polygon: fillet clamping, degenerate edges
- IR serialization: to_ir() output structure
- Golden values: deterministic outputs for cross-language parity with curves.jsx
"""

from __future__ import annotations

import math
import unittest

from illustrator_mcp.curves import (
    BezierPath,
    BezierPoint,
    catmull_rom_to_bezier,
    circular_arc,
    elliptical_arc,
    rounded_polygon,
)


def _dist(a, b):
    """Euclidean distance between two points."""
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _radial_error(cx, cy, r, point):
    """Absolute radial deviation from circle."""
    return abs(math.hypot(point[0] - cx, point[1] - cy) - r)


# ── Catmull-Rom tests ──────────────────────────────────────────────


class TestCatmullRomDegenerate(unittest.TestCase):
    """Degenerate input cases: 0-2 points."""

    def test_empty(self):
        bp = catmull_rom_to_bezier([])
        self.assertEqual(len(bp.points), 0)
        self.assertFalse(bp.closed)

    def test_single_point(self):
        bp = catmull_rom_to_bezier([(10, 20)])
        self.assertEqual(len(bp.points), 1)
        self.assertEqual(bp.points[0].anchor, (10, 20))
        self.assertEqual(bp.points[0].point_type, "corner")
        self.assertIsNone(bp.points[0].in_handle)
        self.assertIsNone(bp.points[0].out_handle)

    def test_two_points_straight_line(self):
        """2 points → straight line, no handles."""
        bp = catmull_rom_to_bezier([(0, 0), (100, 50)])
        self.assertEqual(len(bp.points), 2)
        for p in bp.points:
            self.assertEqual(p.point_type, "corner")
            self.assertIsNone(p.in_handle)
            self.assertIsNone(p.out_handle)

    def test_two_points_closed(self):
        """2 points closed → still corner (degenerate)."""
        bp = catmull_rom_to_bezier([(0, 0), (100, 0)], closed=True)
        self.assertEqual(len(bp.points), 2)
        self.assertTrue(bp.closed)


class TestCatmullRomOpen(unittest.TestCase):
    """Open curve with 3+ points."""

    def test_three_points_endpoints(self):
        """First point has no in_handle, last has no out_handle."""
        bp = catmull_rom_to_bezier([(0, 0), (50, 100), (100, 0)])
        self.assertEqual(len(bp.points), 3)
        # First: no in, has out
        self.assertIsNone(bp.points[0].in_handle)
        self.assertIsNotNone(bp.points[0].out_handle)
        # Last: has in, no out
        self.assertIsNotNone(bp.points[2].in_handle)
        self.assertIsNone(bp.points[2].out_handle)

    def test_four_points_interior_handles(self):
        """Interior points have both in and out handles."""
        pts = [(0, 0), (30, 80), (70, 80), (100, 0)]
        bp = catmull_rom_to_bezier(pts)
        self.assertEqual(len(bp.points), 4)
        for i in [1, 2]:
            self.assertIsNotNone(bp.points[i].in_handle)
            self.assertIsNotNone(bp.points[i].out_handle)
            self.assertEqual(bp.points[i].point_type, "smooth")

    def test_endpoint_duplication_symmetry(self):
        """Symmetric 3-point curve should have symmetric handles."""
        pts = [(0, 0), (50, 100), (100, 0)]
        bp = catmull_rom_to_bezier(pts, tension=0.5)
        mid = bp.points[1]
        # For symmetric input, in/out handles should be mirrored around anchor
        dx_in = mid.anchor[0] - mid.in_handle[0]
        dy_in = mid.anchor[1] - mid.in_handle[1]
        dx_out = mid.out_handle[0] - mid.anchor[0]
        dy_out = mid.out_handle[1] - mid.anchor[1]
        self.assertAlmostEqual(dx_in, dx_out, places=10)
        self.assertAlmostEqual(dy_in, dy_out, places=10)


class TestCatmullRomClosed(unittest.TestCase):
    """Closed curve with wrapping indices."""

    def test_closed_all_handles(self):
        """Closed curve: every point has both in and out handles."""
        pts = [(0, 0), (100, 0), (100, 100), (0, 100)]
        bp = catmull_rom_to_bezier(pts, closed=True)
        self.assertTrue(bp.closed)
        for p in bp.points:
            self.assertIsNotNone(p.in_handle)
            self.assertIsNotNone(p.out_handle)
            self.assertEqual(p.point_type, "smooth")

    def test_closed_no_duplicate_anchor(self):
        """Last point should NOT equal first point."""
        pts = [(0, 0), (100, 0), (50, 100)]
        bp = catmull_rom_to_bezier(pts, closed=True)
        self.assertNotEqual(bp.points[-1].anchor, bp.points[0].anchor)


class TestCatmullRomTension(unittest.TestCase):
    """Tension parameter effects."""

    def test_zero_tension_straight(self):
        """tension=0 → handles coincide with anchors (straight segments)."""
        pts = [(0, 0), (50, 100), (100, 0)]
        bp = catmull_rom_to_bezier(pts, tension=0.0)
        mid = bp.points[1]
        if mid.in_handle:
            self.assertAlmostEqual(mid.in_handle[0], mid.anchor[0], places=10)
            self.assertAlmostEqual(mid.in_handle[1], mid.anchor[1], places=10)
        if mid.out_handle:
            self.assertAlmostEqual(mid.out_handle[0], mid.anchor[0], places=10)
            self.assertAlmostEqual(mid.out_handle[1], mid.anchor[1], places=10)

    def test_higher_tension_longer_handles(self):
        """Higher tension → handles further from anchor."""
        pts = [(0, 0), (50, 100), (100, 0)]
        bp_low = catmull_rom_to_bezier(pts, tension=0.3)
        bp_high = catmull_rom_to_bezier(pts, tension=0.8)
        mid_low = bp_low.points[1]
        mid_high = bp_high.points[1]
        dist_low = _dist(mid_low.anchor, mid_low.out_handle)
        dist_high = _dist(mid_high.anchor, mid_high.out_handle)
        self.assertGreater(dist_high, dist_low)


# ── Arc tests ──────────────────────────────────────────────────────


class TestCircularArc(unittest.TestCase):
    """Circular arc creation."""

    def test_quarter_arc_endpoints(self):
        """90° arc: start at 0°, end at π/2."""
        bp = circular_arc(0, 0, 100, 0, math.pi / 2)
        self.assertEqual(len(bp.points), 2)  # 1 segment = 2 points
        # Start at (100, 0)
        self.assertAlmostEqual(bp.points[0].anchor[0], 100, places=5)
        self.assertAlmostEqual(bp.points[0].anchor[1], 0, places=5)
        # End at (0, 100)
        self.assertAlmostEqual(bp.points[1].anchor[0], 0, places=5)
        self.assertAlmostEqual(bp.points[1].anchor[1], 100, places=5)

    def test_auto_segmentation_180(self):
        """180° arc → 2 segments (≤90° each)."""
        bp = circular_arc(0, 0, 100, 0, math.pi)
        # 2 segments → 3 points
        self.assertEqual(len(bp.points), 3)

    def test_auto_segmentation_full(self):
        """Full circle → 4 segments, closed."""
        bp = circular_arc(0, 0, 100, 0, 2 * math.pi)
        self.assertEqual(len(bp.points), 4)
        self.assertTrue(bp.closed)

    def test_radial_accuracy(self):
        """All anchor points should lie on the circle within 0.27% error."""
        r = 100
        bp = circular_arc(50, 50, r, 0, 2 * math.pi)
        for p in bp.points:
            err = _radial_error(50, 50, r, p.anchor)
            self.assertLess(err, r * 0.003)  # < 0.3%

    def test_zero_arc(self):
        """Zero-span arc → single point."""
        bp = circular_arc(0, 0, 100, 0, 0)
        self.assertEqual(len(bp.points), 1)
        self.assertEqual(bp.points[0].point_type, "corner")


class TestEllipticalArc(unittest.TestCase):
    """Elliptical arc creation."""

    def test_quarter_ellipse(self):
        """90° elliptical arc with rx ≠ ry."""
        bp = elliptical_arc(0, 0, 200, 100, 0, math.pi / 2)
        self.assertEqual(len(bp.points), 2)
        # Start at (200, 0)
        self.assertAlmostEqual(bp.points[0].anchor[0], 200, places=5)
        self.assertAlmostEqual(bp.points[0].anchor[1], 0, places=5)
        # End at (0, 100)
        self.assertAlmostEqual(bp.points[1].anchor[0], 0, places=5)
        self.assertAlmostEqual(bp.points[1].anchor[1], 100, places=5)

    def test_explicit_segments_override(self):
        """Explicit segment count overrides auto."""
        bp = elliptical_arc(0, 0, 100, 100, 0, math.pi / 2, segments=3)
        self.assertEqual(len(bp.points), 4)  # 3 segments → 4 points


# ── Rounded polygon tests ──────────────────────────────────────────


class TestRoundedPolygon(unittest.TestCase):
    """Rounded polygon corner fillets."""

    def test_triangle(self):
        """Rounded triangle: 3 corners → 6 Bézier points (2 per corner)."""
        verts = [(50, 0), (100, 100), (0, 100)]
        bp = rounded_polygon(verts, radius=10)
        self.assertEqual(len(bp.points), 6)  # 2 points per rounded corner
        self.assertTrue(bp.closed)

    def test_radius_clamping(self):
        """Radius clamped to half shortest edge — no overlap."""
        verts = [(0, 0), (10, 0), (10, 100)]  # short edge = 10
        bp = rounded_polygon(verts, radius=100)
        # All fillet points should be within the bounding box
        for p in bp.points:
            self.assertGreaterEqual(p.anchor[0], -1)  # small tolerance
            self.assertLessEqual(p.anchor[0], 11)

    def test_open_polygon(self):
        """Open polygon: first and last vertices preserved as corners."""
        verts = [(0, 0), (50, 100), (100, 0)]
        bp = rounded_polygon(verts, radius=10, closed=False)
        self.assertFalse(bp.closed)
        self.assertEqual(bp.points[0].anchor, (0, 0))
        self.assertEqual(bp.points[-1].anchor, (100, 0))

    def test_degenerate_two_points(self):
        """2 points → no corners to round."""
        bp = rounded_polygon([(0, 0), (100, 0)], radius=10)
        self.assertEqual(len(bp.points), 2)

    def test_hexagon_kappa_accuracy(self):
        """Per-vertex kappa scales with corner angle, not fixed at 90°.

        For a regular hexagon (120° interior angle, 60° fillet arc), kappa
        should be (4/3)*tan(60°/4) ≈ 0.357, NOT the 90° constant 0.552.
        This means handle lengths are ~35.7% of r, not ~55.2%.
        """
        r = 15

        # Square (90° fillet arcs) — for comparison
        sq = [(0, 0), (100, 0), (100, 100), (0, 100)]
        bp_sq = rounded_polygon(sq, radius=r)
        # Fillet start point → its out_handle gives handle length
        p0_sq = bp_sq.points[0]
        hl_sq = _dist(p0_sq.anchor, p0_sq.out_handle)
        kappa_sq = hl_sq / r

        # Hexagon (60° fillet arcs)
        hex_v = [
            (100 * math.cos(2 * math.pi * i / 6),
             100 * math.sin(2 * math.pi * i / 6))
            for i in range(6)
        ]
        bp_hex = rounded_polygon(hex_v, radius=r)
        p0_hex = bp_hex.points[0]
        hl_hex = _dist(p0_hex.anchor, p0_hex.out_handle)
        kappa_hex = hl_hex / r

        # Expected kappa values
        expected_kappa_90 = (4.0 / 3.0) * math.tan(math.pi / 8)   # ≈ 0.5523
        expected_kappa_60 = (4.0 / 3.0) * math.tan(math.pi / 12)  # ≈ 0.3573

        # Verify square uses ~90° kappa
        self.assertAlmostEqual(kappa_sq, expected_kappa_90, places=3,
                               msg=f"Square kappa {kappa_sq:.4f} != expected {expected_kappa_90:.4f}")

        # Verify hexagon uses ~60° kappa (significantly smaller than 90°)
        self.assertAlmostEqual(kappa_hex, expected_kappa_60, places=3,
                               msg=f"Hexagon kappa {kappa_hex:.4f} != expected {expected_kappa_60:.4f}")

        # Hexagon kappa must be less than square kappa
        self.assertLess(kappa_hex, kappa_sq)


# ── IR serialization tests ─────────────────────────────────────────


class TestIRSerialization(unittest.TestCase):
    """BezierPath.to_ir() output."""

    def test_ir_structure(self):
        """IR has correct kind, handleSpace, parallel arrays."""
        bp = catmull_rom_to_bezier([(0, 0), (50, 100), (100, 0)])
        ir = bp.to_ir()
        self.assertEqual(ir["v"], 1)
        self.assertEqual(ir["ir"], "path")
        self.assertEqual(ir["kind"], "bezier")
        self.assertEqual(ir["handleSpace"], "absolute")
        self.assertEqual(len(ir["points"]), 3)
        self.assertEqual(len(ir["handles"]), 3)

    def test_handles_parallel(self):
        """handles[i] corresponds to points[i]."""
        bp = catmull_rom_to_bezier([(0, 0), (50, 100), (100, 0)])
        ir = bp.to_ir()
        self.assertEqual(len(ir["handles"]), len(ir["points"]))

    def test_handle_entry_keys(self):
        """Each handle entry has {in, out, type} keys."""
        bp = catmull_rom_to_bezier([(0, 0), (50, 100), (100, 0)])
        ir = bp.to_ir()
        for h in ir["handles"]:
            self.assertIn("in", h)
            self.assertIn("out", h)
            self.assertIn("type", h)

    def test_null_handles_for_corners(self):
        """Corner points have null handles in IR."""
        bp = catmull_rom_to_bezier([(0, 0), (100, 0)])  # straight line
        ir = bp.to_ir()
        for h in ir["handles"]:
            self.assertIsNone(h["in"])
            self.assertIsNone(h["out"])
            self.assertEqual(h["type"], "corner")


# ── Golden value tests (for JSX parity) ────────────────────────────


class TestGoldenValues(unittest.TestCase):
    """Deterministic outputs for cross-language golden comparison."""

    def test_catmull_rom_3pt_golden(self):
        """3-point Catmull-Rom with tension=0.5: verify exact handle coords."""
        pts = [(0.0, 0.0), (50.0, 100.0), (100.0, 0.0)]
        bp = catmull_rom_to_bezier(pts, tension=0.5)
        ir = bp.to_ir()

        # Point 0: anchor=(0,0), in=null, out computed from endpoint dup
        self.assertEqual(ir["points"][0], [0.0, 0.0])
        self.assertIsNone(ir["handles"][0]["in"])
        # With endpoint duplication: P[-1]=P[0]=(0,0), P[1]=(50,100)
        # tangent = (50-0, 100-0) = (50, 100)
        # out = anchor + tangent * (0.5/3) = (0 + 50*1/6, 0 + 100*1/6)
        self.assertAlmostEqual(ir["handles"][0]["out"][0], 50 / 6, places=10)
        self.assertAlmostEqual(ir["handles"][0]["out"][1], 100 / 6, places=10)

        # Point 1 (midpoint): anchor=(50,100)
        # tangent = P[2]-P[0] = (100, 0)
        # out = (50 + 100/6, 100 + 0) = (50+100/6, 100)
        # in  = (50 - 100/6, 100 - 0) = (50-100/6, 100)
        self.assertAlmostEqual(ir["handles"][1]["out"][0], 50 + 100 / 6, places=10)
        self.assertAlmostEqual(ir["handles"][1]["out"][1], 100.0, places=10)
        self.assertAlmostEqual(ir["handles"][1]["in"][0], 50 - 100 / 6, places=10)
        self.assertAlmostEqual(ir["handles"][1]["in"][1], 100.0, places=10)

        # Point 2: anchor=(100,0), in computed, out=null
        self.assertIsNone(ir["handles"][2]["out"])

    def test_circular_arc_90_golden(self):
        """Quarter circle at origin, r=100: verify kappa handles."""
        bp = circular_arc(0, 0, 100, 0, math.pi / 2)
        ir = bp.to_ir()

        # Kappa for 90° = (4/3)*tan(π/8) ≈ 0.5522847498
        kappa = (4.0 / 3.0) * math.tan(math.pi / 8)

        # Point 0: anchor=(100, 0), out-handle tangent direction = (0, 1) * r * kappa
        self.assertAlmostEqual(ir["handles"][0]["out"][0], 100.0, places=5)
        self.assertAlmostEqual(ir["handles"][0]["out"][1], 100.0 * kappa, places=5)

        # Point 1: anchor=(0, 100), in-handle tangent direction = (1, 0) * r * kappa
        self.assertAlmostEqual(ir["handles"][1]["in"][0], 100.0 * kappa, places=5)
        self.assertAlmostEqual(ir["handles"][1]["in"][1], 100.0, places=5)


if __name__ == "__main__":
    unittest.main()
