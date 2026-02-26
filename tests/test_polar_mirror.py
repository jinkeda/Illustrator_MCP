"""
Tests for Level 3 (Polar & Relative Handles) and Level 4 (Symmetry Modifiers).

Covers:
- Polar handle resolution (angle/length, symmetric, independent)
- Relative handle resolution (dx/dy)
- Coordinate convention: angle in same frame as points, vanilla cos/sin
- Always-triplet output (including corners)
- NaN/finite guards
- Mirror with seam deduplication
- Mirror with handle preservation + in/out swap
- Auto-origin detection
- Preprocessing guards (smooth/handles mutual exclusion, type guard)
"""

from __future__ import annotations

import math
import unittest

from illustrator_mcp.curves import (
    resolve_polar_handles,
    mirror_points,
)


# ── Level 3: Polar Handle Resolution ─────────────────────────────


class TestPolarSymmetric(unittest.TestCase):
    """Symmetric polar handles."""

    def test_angle_0_horizontal(self):
        """angle=0, length=25 → out-handle at (125, 50), in at (75, 50)."""
        points = [[100, 50]]
        specs = [{"angle": 0, "length": 25, "symmetric": True}]
        result = resolve_polar_handles(points, specs)

        self.assertEqual(len(result), 1)
        triplet = result[0]
        # Triplet: [anchor, in_handle, out_handle]
        self.assertEqual(triplet[0], [100.0, 50.0])  # anchor
        self.assertAlmostEqual(triplet[2][0], 125.0)  # out X
        self.assertAlmostEqual(triplet[2][1], 50.0)   # out Y
        # Symmetric: in = anchor - (out - anchor)
        self.assertAlmostEqual(triplet[1][0], 75.0)   # in X
        self.assertAlmostEqual(triplet[1][1], 50.0)   # in Y

    def test_angle_90_plus_y(self):
        """angle=90 → +Y direction (vanilla cos/sin, same frame as points).

        With anchor (100, 50), length 25:
          out = (100 + 25*cos(90°), 50 + 25*sin(90°)) = (100, 75)
        """
        points = [[100, 50]]
        specs = [{"angle": 90, "length": 25, "symmetric": True}]
        result = resolve_polar_handles(points, specs)

        out_h = result[0][2]
        self.assertAlmostEqual(out_h[0], 100.0, places=10)
        self.assertAlmostEqual(out_h[1], 75.0, places=10)


class TestPolarAsymmetric(unittest.TestCase):
    """Independent in/out handles."""

    def test_independent_handles(self):
        """in and out specified separately."""
        points = [[50, 50]]
        specs = [{
            "in": {"angle": 180, "length": 10},
            "out": {"angle": 0, "length": 25},
        }]
        result = resolve_polar_handles(points, specs)

        triplet = result[0]
        # Out: (50 + 25*cos(0), 50 + 25*sin(0)) = (75, 50)
        self.assertAlmostEqual(triplet[2][0], 75.0)
        self.assertAlmostEqual(triplet[2][1], 50.0)
        # In: (50 + 10*cos(180), 50 + 10*sin(180)) = (40, 50)
        self.assertAlmostEqual(triplet[1][0], 40.0)
        self.assertAlmostEqual(triplet[1][1], 50.0)

    def test_symmetric_ignored_with_independent(self):
        """symmetric flag is ignored when both in/out are given."""
        points = [[50, 50]]
        specs = [{
            "in": {"angle": 180, "length": 10},
            "out": {"angle": 45, "length": 20},
            "symmetric": True,  # should be ignored
        }]
        result = resolve_polar_handles(points, specs)

        # Out should be at 45°, not mirrored from in
        out_h = result[0][2]
        expected_x = 50 + 20 * math.cos(math.radians(45))
        expected_y = 50 + 20 * math.sin(math.radians(45))
        self.assertAlmostEqual(out_h[0], expected_x, places=10)
        self.assertAlmostEqual(out_h[1], expected_y, places=10)


class TestRelativeHandles(unittest.TestCase):
    """Relative dx/dy handle specs."""

    def test_dx_dy(self):
        """dx=10, dy=0, symmetric → out at anchor+(10,0), in at anchor-(10,0)."""
        points = [[50, 50]]
        specs = [{"dx": 10, "dy": 0, "symmetric": True}]
        result = resolve_polar_handles(points, specs)

        self.assertAlmostEqual(result[0][2][0], 60.0)  # out X
        self.assertAlmostEqual(result[0][2][1], 50.0)  # out Y
        self.assertAlmostEqual(result[0][1][0], 40.0)  # in X
        self.assertAlmostEqual(result[0][1][1], 50.0)  # in Y


class TestCornerPoints(unittest.TestCase):
    """None in handles_spec → corner triplet."""

    def test_none_is_coincident_triplet(self):
        """None → triplet with all three components equal (coincident handles)."""
        points = [[100, 50]]
        specs = [None]
        result = resolve_polar_handles(points, specs)

        triplet = result[0]
        self.assertEqual(len(triplet), 3)
        # All three should be the same point
        self.assertEqual(triplet[0], [100.0, 50.0])
        self.assertEqual(triplet[1], [100.0, 50.0])
        self.assertEqual(triplet[2], [100.0, 50.0])


class TestHandleValidation(unittest.TestCase):
    """Validation and edge cases."""

    def test_length_mismatch_raises(self):
        """handles_spec must match points length."""
        with self.assertRaises(ValueError):
            resolve_polar_handles([[0, 0], [10, 10]], [None])

    def test_nan_angle_raises(self):
        """NaN angle should raise."""
        with self.assertRaises(ValueError):
            resolve_polar_handles([[0, 0]], [{"angle": float("nan"), "length": 10}])

    def test_nan_length_raises(self):
        """NaN length should raise."""
        with self.assertRaises(ValueError):
            resolve_polar_handles([[0, 0]], [{"angle": 0, "length": float("inf")}])

    def test_invalid_spec_raises(self):
        """Spec without angle/length or dx/dy raises."""
        with self.assertRaises(ValueError):
            resolve_polar_handles([[0, 0]], [{"foo": "bar"}])


# ── Level 4: Symmetry Modifiers ──────────────────────────────────


class TestMirrorYBottom(unittest.TestCase):
    """mirror_y_bottom: input=top half, generate bottom."""

    def test_basic_mirror(self):
        """4 points with first/last on axis → 6-point closed path
        (seam dedup removes 2 duplicates).

        Points: [0,100], [30,85], [80,85], [120,100]
        Mirror Y around origin=100.
        First and last on axis (y=100) → not duplicated.
        """
        points = [[0, 100], [30, 85], [80, 85], [120, 100]]
        result = mirror_points(points, "mirror_y_bottom", origin=100)

        # Original 4 + mirrored 4, minus 2 seam dedup = 6
        self.assertEqual(len(result), 6)
        # First point should be original first
        self.assertEqual(result[0], [0, 100])
        # Last original
        self.assertEqual(result[3], [120, 100])

    def test_mirrored_y_values_flipped(self):
        """Mirrored points should have y' = 2*origin - y."""
        points = [[0, 100], [50, 80]]
        result = mirror_points(points, "mirror_y_bottom", origin=100)

        # Original: [0,100], [50,80]
        # Mirrored (reversed): mirror([50,80])=[50,120], mirror([0,100])=[0,100]
        # Seam dedup: first on axis → last mirrored dropped, last not on axis
        # Result: [0,100], [50,80], [50,120]
        self.assertEqual(len(result), 3)
        self.assertEqual(result[2], [50, 120])

    def test_no_dedup_off_axis(self):
        """Points not on axis → no deduplication, all mirrored points kept."""
        points = [[10, 90], [50, 80], [90, 90]]
        result = mirror_points(points, "mirror_y_bottom", origin=100)

        # None on axis → no dedup → 3 + 3 = 6
        self.assertEqual(len(result), 6)


class TestMirrorXRight(unittest.TestCase):
    """mirror_x_right: input=left half, generate right."""

    def test_basic_x_mirror(self):
        """Mirror across X axis.

        3 points all on axis (x=0):
        - Seam dedup removes first/last duplicates (2 removed)
        - Middle point still gets mirrored (to itself) and included
        - 3 original + 3 mirrored - 2 dedup = 4
        """
        points = [[0, 0], [0, 50], [0, 100]]
        result = mirror_points(points, "mirror_x_right", origin=0)

        self.assertEqual(len(result), 4)


class TestMirrorAutoOrigin(unittest.TestCase):
    """Auto-origin detection."""

    def test_auto_from_endpoints(self):
        """First and last anchor share same Y → that becomes origin."""
        points = [[0, 100], [50, 80], [100, 100]]
        result = mirror_points(points, "mirror_y_bottom")

        # Auto-origin should be 100 (first.y == last.y == 100)
        # Both endpoints on axis → mirrored copies deduped
        self.assertEqual(len(result), 4)  # 3 + 3 - 2 = 4

    def test_auto_bbox_fallback(self):
        """First/last anchors differ → bbox center used."""
        points = [[0, 80], [50, 60], [100, 100]]
        result = mirror_points(points, "mirror_y_bottom")

        # Auto-origin = (60 + 100) / 2 = 80.0
        # First at y=80 == origin → seam dedup applies for first
        # Last at y=100 ≠ 80 → no dedup for last
        # 3 original + 3 mirrored - 1 (first on axis) = 5
        self.assertEqual(len(result), 5)


class TestMirrorWithHandles(unittest.TestCase):
    """Mirror preserves and correctly transforms handles."""

    def test_triplets_mirrored_and_swapped(self):
        """Triplet handles are mirrored AND in/out swapped."""
        # [anchor, in_handle, out_handle]
        points = [
            [[0, 100], [0, 100], [0, 100]],    # corner on axis
            [[50, 85], [40, 85], [60, 85]],     # smooth point
            [[100, 100], [100, 100], [100, 100]],  # corner on axis
        ]
        result = mirror_points(points, "mirror_y_bottom", origin=100)

        # Seam dedup: first & last on axis → mirrored copies dropped
        # Result: 3 original + 3 mirrored - 2 dedup = 4
        self.assertEqual(len(result), 4)

        # The mirrored version of point [50,85] should be at [50,115]
        # And handles swapped: in becomes mirrored out, out becomes mirrored in
        mirrored_pt = result[3]  # last point = mirror of middle
        anchor = mirrored_pt[0]
        self.assertAlmostEqual(anchor[0], 50)
        self.assertAlmostEqual(anchor[1], 115)  # 2*100 - 85

        # Original: in=[40,85], out=[60,85]
        # Mirrored: in'=mirror([60,85])=[60,115], out'=mirror([40,85])=[40,115]
        # (swapped because path reversal)
        in_h = mirrored_pt[1]
        out_h = mirrored_pt[2]
        self.assertAlmostEqual(in_h[0], 60)
        self.assertAlmostEqual(in_h[1], 115)
        self.assertAlmostEqual(out_h[0], 40)
        self.assertAlmostEqual(out_h[1], 115)


class TestMirrorAnchorOnly(unittest.TestCase):
    """Mirror with anchor-only points (for smooth:true + mirror interaction)."""

    def test_anchor_only_mirror(self):
        """Simple [x,y] points (no handles) mirror correctly."""
        points = [[0, 100], [30, 85], [80, 85], [120, 100]]
        result = mirror_points(points, "mirror_y_bottom", origin=100)

        # All results should be simple [x,y] (not triplets)
        for pt in result:
            self.assertEqual(len(pt), 2)
            self.assertNotIsInstance(pt[0], list)


class TestMirrorValidation(unittest.TestCase):
    """Error handling for mirror."""

    def test_invalid_mode_raises(self):
        """Unknown mirror mode raises ValueError."""
        with self.assertRaises(ValueError):
            mirror_points([[0, 0]], "invalid_mode")

    def test_empty_points_raises(self):
        """Empty points list raises ValueError."""
        with self.assertRaises(ValueError):
            mirror_points([], "mirror_y_bottom")


class TestMirrorYTop(unittest.TestCase):
    """mirror_y_top: input=bottom half, prepend top."""

    def test_prepend_mode(self):
        """In mirror_y_top, mirrored points come first."""
        points = [[0, 100], [50, 120], [100, 100]]
        result = mirror_points(points, "mirror_y_top", origin=100)

        # Mirrored (of bottom) prepended before original
        # First/last on axis → dedup
        # Result length: 3 + 3 - 2 = 4
        self.assertEqual(len(result), 4)

        # First point of result should be mirrored version of middle point
        # mirror of [50,120] around y=100 → [50, 80]
        self.assertAlmostEqual(result[0][0], 50)
        self.assertAlmostEqual(result[0][1], 80)


# ── Preprocessing Integration ────────────────────────────────────

class TestPreprocessGuards(unittest.TestCase):
    """Test _preprocess_element_create guards."""

    def test_smooth_and_handles_raises(self):
        """smooth + handles is mutually exclusive."""
        # Import the function directly
        import sys
        sys.path.insert(0, ".")
        from illustrator_mcp.tools.task_execution import _preprocess_element_create

        payload = {
            "params": {
                "type": "path",
                "points": [[0, 0], [50, 100], [100, 0]],
                "smooth": True,
                "handles": [None, {"angle": 0, "length": 25}, None],
            }
        }
        with self.assertRaises(ValueError):
            _preprocess_element_create(payload)

    def test_rect_type_no_preprocess(self):
        """type='rect' → no preprocessing, keys stripped."""
        from illustrator_mcp.tools.task_execution import _preprocess_element_create

        payload = {
            "params": {
                "type": "rect",
                "handles": [None],
                "mirror": "mirror_y_bottom",
                "mirrorOrigin": 100,
            }
        }
        _preprocess_element_create(payload)
        # All preprocess keys should be stripped
        self.assertNotIn("handles", payload["params"])
        self.assertNotIn("mirror", payload["params"])
        self.assertNotIn("mirrorOrigin", payload["params"])

    def test_orphan_mirror_origin_stripped(self):
        """mirrorOrigin without mirror should be stripped."""
        from illustrator_mcp.tools.task_execution import _preprocess_element_create

        payload = {
            "params": {
                "type": "path",
                "points": [[0, 0], [100, 0]],
                "mirrorOrigin": 50,
            }
        }
        _preprocess_element_create(payload)
        self.assertNotIn("mirrorOrigin", payload["params"])

    def test_full_round_trip(self):
        """handles + mirror → expanded points, closed=True, keys stripped."""
        from illustrator_mcp.tools.task_execution import _preprocess_element_create

        payload = {
            "params": {
                "type": "path",
                "points": [[0, 100], [50, 80], [100, 100]],
                "handles": [
                    None,
                    {"angle": 0, "length": 20, "symmetric": True},
                    None,
                ],
                "mirror": "mirror_y_bottom",
            }
        }
        _preprocess_element_create(payload)

        params = payload["params"]
        self.assertNotIn("handles", params)
        self.assertNotIn("mirror", params)
        self.assertTrue(params["closed"])
        # Points should be expanded (more than original 3)
        self.assertGreater(len(params["points"]), 3)


if __name__ == "__main__":
    unittest.main()
