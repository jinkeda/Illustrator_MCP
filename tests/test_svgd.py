"""
test_svgd.py — Unit tests for SVG path data parser.

Pure Python tests (no Illustrator needed).
Run: python -m pytest tests/test_svgd.py -v
"""

import math
import pytest
from illustrator_mcp.svgd import (
    parse_svg_d, tokenize_d, arc_to_cubics,
    MAX_D_LENGTH, MAX_SEGMENTS, MAX_SUBPATHS, MAX_COORD_ABS, MAX_TOKENS,
)


# ── Basic command tests ────────────────────────────────────────────────


class TestBasicCommands:
    def test_moveto_lineto(self):
        """M L Z → 3 points, closed."""
        ir = parse_svg_d("M 0,0 L 100,0 L 100,100 Z")
        assert ir["ir"] == "path"
        assert ir["closed"] is True
        assert len(ir["points"]) == 3
        assert ir["points"][0] == [0, 0]
        assert ir["points"][1] == [100, 0]
        assert ir["points"][2] == [100, 100]

    def test_cubic_bezier(self):
        """C command → handles with in/out keys, kind=bezier."""
        ir = parse_svg_d("M 0,0 C 25,50 75,50 100,0")
        assert ir["kind"] == "bezier"
        assert len(ir["points"]) == 2
        assert len(ir["handles"]) == 2
        # First point's out-handle should be cp1
        assert ir["handles"][0]["out"] == [25, 50]
        # Second point's in-handle should be cp2
        assert ir["handles"][1]["in"] == [75, 50]

    def test_relative_commands(self):
        """m l → correct absolute coordinates."""
        ir = parse_svg_d("m 10,10 l 50,0 l 0,50 z")
        assert ir["closed"] is True
        assert ir["points"][0] == [10, 10]
        assert ir["points"][1] == [60, 10]   # 10+50
        assert ir["points"][2] == [60, 60]   # 10+50, 10+0+50

    def test_shorthand_cubic(self):
        """S command reflects previous control point."""
        ir = parse_svg_d("M 0,0 C 0,50 50,100 100,100 S 200,50 200,0")
        assert len(ir["points"]) == 3
        # S reflects cp2 of previous C around current point
        # Previous cp2 = [50,100], current = [100,100]
        # Reflected = [2*100-50, 2*100-100] = [150, 100]
        assert ir["handles"][1]["out"] == [150, 100]

    def test_quadratic_elevation(self):
        """Q → cubic handles with correct degree elevation."""
        ir = parse_svg_d("M 0,0 Q 50,100 100,0")
        assert ir["kind"] == "bezier"
        assert len(ir["points"]) == 2
        # Elevated: cp1 = p0 + 2/3*(p1-p0), cp2 = p2 + 2/3*(p1-p2)
        cp1_expected = [0 + 2 / 3 * 50, 0 + 2 / 3 * 100]
        cp2_expected = [100 + 2 / 3 * (50 - 100), 0 + 2 / 3 * 100]
        assert abs(ir["handles"][0]["out"][0] - cp1_expected[0]) < 0.01
        assert abs(ir["handles"][0]["out"][1] - cp1_expected[1]) < 0.01
        assert abs(ir["handles"][1]["in"][0] - cp2_expected[0]) < 0.01
        assert abs(ir["handles"][1]["in"][1] - cp2_expected[1]) < 0.01

    def test_horizontal_vertical(self):
        """H V → correct coordinates."""
        ir = parse_svg_d("M 0,0 H 100 V 200")
        assert ir["points"][1] == [100, 0]
        assert ir["points"][2] == [100, 200]

    def test_arc_converts_to_cubic(self):
        """A command → produces cubic Bézier handles."""
        ir = parse_svg_d("M 0,0 A 50,50 0 1,1 100,0")
        assert ir["ir"] == "path"
        assert ir["kind"] == "bezier"
        # Arc should produce at least one segment with handles
        has_handles = any(
            h["in"] is not None or h["out"] is not None
            for h in ir["handles"]
        )
        assert has_handles
        # Endpoint should be at (100, 0)
        last_pt = ir["points"][-1]
        assert abs(last_pt[0] - 100) < 0.1
        assert abs(last_pt[1] - 0) < 0.1

    def test_implicit_lineto_after_M(self):
        """M 0 0 10 10 20 20 → M + 2 implicit L's."""
        ir = parse_svg_d("M 0 0 10 10 20 20")
        assert len(ir["points"]) == 3
        assert ir["points"][0] == [0, 0]
        assert ir["points"][1] == [10, 10]
        assert ir["points"][2] == [20, 20]


# ── Error handling tests ──────────────────────────────────────────────


class TestErrorHandling:
    def test_empty_errors(self):
        """Empty string → ValueError."""
        with pytest.raises(ValueError, match="Empty"):
            parse_svg_d("")

    def test_whitespace_only(self):
        """Whitespace-only → ValueError."""
        with pytest.raises(ValueError, match="Empty"):
            parse_svg_d("   \t\n  ")

    def test_no_moveto(self):
        """L without M → error."""
        with pytest.raises(ValueError, match="before MoveTo"):
            parse_svg_d("L 10,10")


# ── IR contract tests ─────────────────────────────────────────────────


class TestIRContract:
    def test_ir_contract_fields(self):
        """Output has v, ir, kind, handleSpace, points, handles, closed."""
        ir = parse_svg_d("M 0,0 L 100,0 L 100,100 Z")
        assert ir["v"] == 1
        assert ir["ir"] == "path"
        assert ir["kind"] == "bezier"
        assert ir["handleSpace"] == "absolute"
        assert isinstance(ir["points"], list)
        assert isinstance(ir["handles"], list)
        assert isinstance(ir["closed"], bool)

    def test_handles_format(self):
        """Each handle has in/out/type keys."""
        ir = parse_svg_d("M 0,0 C 25,50 75,50 100,0")
        for h in ir["handles"]:
            assert "in" in h
            assert "out" in h
            assert "type" in h
            assert h["type"] in ("smooth", "corner")

    def test_closed_default_false(self):
        """No Z → closed=False."""
        ir = parse_svg_d("M 0,0 L 100,0 L 100,100")
        assert ir["closed"] is False


# ── Multi-subpath tests ───────────────────────────────────────────────


class TestMultiSubpath:
    def test_multi_subpath(self):
        """Two M...Z segments → ir: 'multi'."""
        ir = parse_svg_d("M 0,0 L 100,0 L 100,100 Z M 200,200 L 300,200 L 300,300 Z")
        assert ir["ir"] == "multi"
        assert len(ir["subpaths"]) == 2
        assert ir["subpaths"][0]["closed"] is True
        assert ir["subpaths"][1]["closed"] is True

    def test_multi_subpath_all_closed(self):
        """Both closed → all_closed = True."""
        ir = parse_svg_d("M 0,0 L 10,0 L 10,10 Z M 20,20 L 30,20 L 30,30 Z")
        assert ir["all_closed"] is True

    def test_multi_subpath_mixed(self):
        """One closed, one open → all_closed = False."""
        ir = parse_svg_d("M 0,0 L 10,0 L 10,10 Z M 20,20 L 30,20 L 30,30")
        assert ir["ir"] == "multi"
        assert ir["all_closed"] is False


# ── Tokenizer edge case tests ─────────────────────────────────────────


class TestTokenizer:
    def test_tokenizer_sign_separated(self):
        """M10-20 → (10, -20)."""
        ir = parse_svg_d("M10-20 L30-40")
        assert ir["points"][0] == [10, -20]
        assert ir["points"][1] == [30, -40]

    def test_tokenizer_decimal_shorthand(self):
        """.5.3 → (0.5, 0.3)."""
        ir = parse_svg_d("M.5.3 L1.5 2.5")
        assert abs(ir["points"][0][0] - 0.5) < 0.001
        assert abs(ir["points"][0][1] - 0.3) < 0.001

    def test_tokenizer_scientific(self):
        """1.5e-3 → 0.0015."""
        tokens = tokenize_d("M 1.5e-3 2.5e2")
        nums = [t for t in tokens if isinstance(t, float)]
        assert abs(nums[0] - 0.0015) < 1e-6
        assert abs(nums[1] - 250.0) < 0.01

    def test_tokenizer_comma_space_mix(self):
        """Mixed separators."""
        ir = parse_svg_d("M 10, 20 L30 40 L 50,60")
        assert ir["points"][0] == [10, 20]
        assert ir["points"][1] == [30, 40]
        assert ir["points"][2] == [50, 60]


# ── Real-world path test ──────────────────────────────────────────────


class TestRealWorld:
    def test_heart_icon(self):
        """Real-world heart shape SVG path with arcs (now supported)."""
        d = ("M 10,30 A 20,20 0,0,1 50,30 A 20,20 0,0,1 90,30 "
             "Q 90,60 50,80 Q 10,60 10,30 Z")
        ir = parse_svg_d(d)
        assert ir["ir"] == "path"
        assert ir["closed"] is True
        assert ir["kind"] == "bezier"
        # Should have handles from both arcs and Q commands
        has_handles = any(
            h["in"] is not None or h["out"] is not None
            for h in ir["handles"]
        )
        assert has_handles

    def test_cubic_heart(self):
        """Heart shape using only cubic Béziers (no arcs)."""
        d = ("M 50,80 C 50,80 10,60 10,30 "
             "C 10,10 30,0 50,20 "
             "C 70,0 90,10 90,30 "
             "C 90,60 50,80 50,80 Z")
        ir = parse_svg_d(d)
        assert ir["ir"] == "path"
        assert ir["closed"] is True
        assert ir["kind"] == "bezier"
        # Should have smooth curves
        has_handles = any(
            h["in"] is not None or h["out"] is not None
            for h in ir["handles"]
        )
        assert has_handles

    def test_cloud_shape(self):
        """Complex cloud-like multi-curve path."""
        d = ("M 25,60 C 25,60 5,50 10,35 "
             "C 15,20 30,15 40,25 "
             "C 45,10 65,10 70,25 "
             "C 80,15 95,20 90,40 "
             "C 100,50 85,60 75,60 Z")
        ir = parse_svg_d(d)
        assert ir["ir"] == "path"
        assert ir["closed"] is True
        assert len(ir["points"]) >= 5


# ── Arc conversion tests (H6) ─────────────────────────────────────────


class TestArcConversion:
    def test_arc_zero_radius_becomes_line(self):
        """[H6] rx=0 → degenerate arc treated as lineTo."""
        ir = parse_svg_d("M 0,0 A 0,50 0 1,1 100,0")
        # Should be a line to (100,0), no crash
        assert ir["points"][-1] == [100, 0]
        # Handle should be corner (no curves)
        assert ir["handles"][-1]["type"] == "corner"

    def test_arc_out_of_range_radii_scaled(self):
        """Too-small radii → scaled up per W3C §F.6.6.3."""
        # Very small radii that can't reach endpoint
        cubics = arc_to_cubics(0, 0, 1, 1, 0, 0, 1, 100, 0)
        # Should still produce valid cubics (radii scaled up)
        assert len(cubics) > 0
        # Endpoint should be at (100, 0)
        end = cubics[-1][2]
        assert abs(end[0] - 100) < 0.1
        assert abs(end[1] - 0) < 0.1

    def test_arc_sweep_and_large_arc_flags(self):
        """Different flag combinations produce different paths."""
        # Same arc, different flags → different results
        c1 = arc_to_cubics(0, 0, 50, 50, 0, 0, 1, 100, 0)
        c2 = arc_to_cubics(0, 0, 50, 50, 0, 1, 1, 100, 0)
        c3 = arc_to_cubics(0, 0, 50, 50, 0, 0, 0, 100, 0)
        c4 = arc_to_cubics(0, 0, 50, 50, 0, 1, 0, 100, 0)
        # All should produce valid cubics
        for cubics in [c1, c2, c3, c4]:
            assert len(cubics) > 0
            end = cubics[-1][2]
            assert abs(end[0] - 100) < 0.1
            assert abs(end[1] - 0) < 0.1

    def test_arc_rotated_ellipse(self):
        """[H6] Golden vector: x_rotation != 0."""
        cubics = arc_to_cubics(0, 0, 50, 30, 45.0, 1, 1, 100, 0)
        assert len(cubics) > 0
        end = cubics[-1][2]
        assert abs(end[0] - 100) < 0.1
        assert abs(end[1] - 0) < 0.1

    def test_arc_cos_clamp(self):
        """[H6] Input that would cause acos > 1.0 without clamping."""
        # Near-coincident points with large radii
        cubics = arc_to_cubics(0, 0, 1000, 1000, 0, 1, 1, 0.001, 0)
        # Should not crash with math domain error
        assert isinstance(cubics, list)

    def test_arc_coincident_endpoints(self):
        """[H6] Coincident endpoints → empty (degenerate)."""
        cubics = arc_to_cubics(50, 50, 30, 30, 0, 0, 1, 50, 50)
        assert cubics == []

    def test_relative_arc(self):
        """Relative a command works correctly."""
        ir = parse_svg_d("M 0,0 a 50,50 0 1,1 100,0")
        last_pt = ir["points"][-1]
        assert abs(last_pt[0] - 100) < 0.1
        assert abs(last_pt[1] - 0) < 0.1


# ── Safety limit tests (H7) ──────────────────────────────────────────


class TestSafetyLimits:
    def test_d_too_long(self):
        """[H7] d string exceeding MAX_D_LENGTH → E_D_TOO_LONG."""
        d = "M 0,0 " + "L 1,1 " * (MAX_D_LENGTH // 4)
        with pytest.raises(ValueError, match="E_D_TOO_LONG"):
            parse_svg_d(d)

    def test_max_coord_abs(self):
        """[H7] Coordinates exceeding ±MAX_COORD_ABS → E_COORD_OVERFLOW."""
        d = f"M 0,0 L {MAX_COORD_ABS + 1},0"
        with pytest.raises(ValueError, match="E_COORD_OVERFLOW"):
            parse_svg_d(d)

    def test_too_many_subpaths(self):
        """[H7] Too many M commands → E_TOO_MANY_SUBPATHS."""
        segments = " ".join(
            f"M {i},{i} L {i+1},{i+1}" for i in range(MAX_SUBPATHS + 1)
        )
        with pytest.raises(ValueError, match="E_TOO_MANY_SUBPATHS"):
            parse_svg_d(segments)

    def test_too_many_segments(self):
        """[H7] Too many segments → E_TOO_MANY_SEGMENTS."""
        # Generate enough L commands to exceed MAX_SEGMENTS
        segments = "M 0,0 " + " ".join(
            f"L {i % 100},{(i+1) % 100}" for i in range(MAX_SEGMENTS + 1)
        )
        with pytest.raises(ValueError, match="E_TOO_MANY_SEGMENTS"):
            parse_svg_d(segments)

