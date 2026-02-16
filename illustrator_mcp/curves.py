"""
Bézier curve creation helpers — Source of truth.

Pure-math functions that compute cubic Bézier anchors + handles.
No Illustrator DOM access. Mirrors curves.jsx for ExtendScript runtime.

All coordinates are in user-space: origin = top-left, +X right, +Y down.
Handle coordinates are ABSOLUTE (not relative to anchor).

Golden tests in test_curves.py ensure Python/JSX numerical parity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Literal, Optional, Sequence, Tuple, Union

Point = Tuple[float, float]

# ── Data structures ─────────────────────────────────────────────────

@dataclass(frozen=True)
class BezierPoint:
    """A single Bézier anchor with optional control handles.

    Attributes:
        anchor: The on-curve anchor point (x, y).
        in_handle: Incoming handle (absolute). None = coincident with anchor.
        out_handle: Outgoing handle (absolute). None = coincident with anchor.
        point_type: "smooth" or "corner".
            - "smooth": Illustrator sets PointType.SMOOTH (handles are collinear).
            - "corner": Illustrator sets PointType.CORNER (cusp allowed).
    """
    anchor: Point
    in_handle: Optional[Point] = None
    out_handle: Optional[Point] = None
    point_type: Literal["smooth", "corner"] = "smooth"


@dataclass(frozen=True)
class BezierPath:
    """A complete Bézier path — sequence of BezierPoints + closed flag.

    Can be converted to IR via to_ir() for SOC consumption.
    """
    points: Tuple[BezierPoint, ...]
    closed: bool = False

    def to_ir(self) -> dict:
        """Convert to Geometry IR dict (kind='bezier', handleSpace='absolute')."""
        anchors = []
        handles = []
        for bp in self.points:
            anchors.append(list(bp.anchor))
            handles.append({
                "in": list(bp.in_handle) if bp.in_handle else None,
                "out": list(bp.out_handle) if bp.out_handle else None,
                "type": bp.point_type,
            })
        return {
            "v": 1,
            "ir": "path",
            "kind": "bezier",
            "handleSpace": "absolute",
            "points": anchors,
            "handles": handles,
            "closed": self.closed,
            "meta": {},
        }


# ── Catmull-Rom → cubic Bézier ─────────────────────────────────────

def catmull_rom_to_bezier(
    waypoints: Sequence[Point],
    tension: float = 0.5,
    closed: bool = False,
) -> BezierPath:
    """Convert waypoints to a smooth cubic Bézier path via Catmull-Rom.

    For each interior anchor P[i], handles are computed from neighbors:
        out_handle(P[i]) = P[i] + (P[i+1] - P[i-1]) * tension / 3
        in_handle(P[i])  = P[i] - (P[i+1] - P[i-1]) * tension / 3

    Endpoint handling:
        Open curves:  endpoint duplication (P[-1]=P[0], P[n]=P[n-1])
        Closed curves: index wrapping (P[-1]=P[n-1], P[n]=P[0])

    Degenerate cases:
        0-1 points: returned as corner-only (no handles)
        2 points:   straight line (handles = None, point_type = "corner")

    Args:
        waypoints: Sequence of (x, y) anchor points.
        tension: Controls curve tightness. 0 = straight, 0.5 = Catmull-Rom,
                 1.0 = very loose. Default 0.5.
        closed: Whether the curve wraps back to the first point.

    Returns:
        BezierPath with computed handles.
    """
    n = len(waypoints)
    pts = [tuple(p) for p in waypoints]  # normalize

    # Degenerate: 0 or 1 points
    if n <= 1:
        return BezierPath(
            points=tuple(BezierPoint(anchor=p, point_type="corner") for p in pts),
            closed=False,
        )

    # Degenerate: 2 points → straight line
    if n == 2:
        return BezierPath(
            points=(
                BezierPoint(anchor=pts[0], point_type="corner"),
                BezierPoint(anchor=pts[1], point_type="corner"),
            ),
            closed=closed,
        )

    # General case: n >= 3
    result: List[BezierPoint] = []
    alpha = tension / 3.0

    for i in range(n):
        # Resolve neighbor indices with endpoint/wrap policy
        if closed:
            i_prev = (i - 1) % n
            i_next = (i + 1) % n
        else:
            # Endpoint duplication
            i_prev = max(0, i - 1)
            i_next = min(n - 1, i + 1)

        p_prev = pts[i_prev]
        p_curr = pts[i]
        p_next = pts[i_next]

        # Tangent direction: P[i+1] - P[i-1]
        dx = p_next[0] - p_prev[0]
        dy = p_next[1] - p_prev[1]

        # Compute handles
        out_h: Optional[Point] = (
            p_curr[0] + dx * alpha,
            p_curr[1] + dy * alpha,
        )
        in_h: Optional[Point] = (
            p_curr[0] - dx * alpha,
            p_curr[1] - dy * alpha,
        )

        # For open curves, endpoints have one-sided handles only
        if not closed:
            if i == 0:
                in_h = None  # first point: no incoming
            if i == n - 1:
                out_h = None  # last point: no outgoing

        # Determine point type
        if in_h is None and out_h is None:
            pt_type: Literal["smooth", "corner"] = "corner"
        else:
            pt_type = "smooth"

        result.append(BezierPoint(
            anchor=p_curr,
            in_handle=in_h,
            out_handle=out_h,
            point_type=pt_type,
        ))

    return BezierPath(points=tuple(result), closed=closed)


# ── Circular arc ────────────────────────────────────────────────────

def circular_arc(
    cx: float,
    cy: float,
    r: float,
    start_angle: float,
    end_angle: float,
    segments: Optional[int] = None,
) -> BezierPath:
    """Create a circular arc as cubic Bézier segments.

    Uses the kappa approximation: for a segment spanning angle θ,
    handle length = (4/3) * r * tan(θ/4).

    Auto-segments: ceil(|Δθ| / (π/2)) — never more than 90° per segment.

    Args:
        cx, cy: Center of circle.
        r: Radius.
        start_angle: Start angle in radians (0 = right, π/2 = down in Y-down).
        end_angle: End angle in radians.
        segments: Override auto-segmentation. None = auto.

    Returns:
        BezierPath (open, unless full circle detected).
    """
    return elliptical_arc(cx, cy, r, r, start_angle, end_angle, segments)


def elliptical_arc(
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    start_angle: float,
    end_angle: float,
    segments: Optional[int] = None,
) -> BezierPath:
    """Create an elliptical arc as cubic Bézier segments.

    Uses the kappa approximation per-segment: for a segment spanning θ_seg,
    kappa = (4/3) * tan(θ_seg / 4).

    Guarantees:
        - Each segment spans ≤ 90° (π/2)
        - Tangent continuity at segment junctions (shared handle)
        - Max radial error < 0.27% for 90° segments

    Args:
        cx, cy: Center of ellipse.
        rx, ry: Radii (horizontal, vertical).
        start_angle: Start angle in radians.
        end_angle: End angle in radians.
        segments: Override auto-segmentation. None = auto.

    Returns:
        BezierPath. Closed if |Δθ| ≈ 2π, else open.
    """
    delta = end_angle - start_angle
    if abs(delta) < 1e-10:
        # Zero arc — return single point
        px = cx + rx * math.cos(start_angle)
        py = cy + ry * math.sin(start_angle)
        return BezierPath(
            points=(BezierPoint(anchor=(px, py), point_type="corner"),),
            closed=False,
        )

    # Auto-segment: ceil(|Δθ| / (π/2))
    if segments is None:
        segments = max(1, math.ceil(abs(delta) / (math.pi / 2)))

    # Detect full circle (close within 1e-6 of 2π)
    is_full = abs(abs(delta) - 2 * math.pi) < 1e-6

    theta_seg = delta / segments
    kappa = (4.0 / 3.0) * math.tan(theta_seg / 4.0)

    result: List[BezierPoint] = []

    for i in range(segments + 1):
        a = start_angle + i * theta_seg
        cos_a = math.cos(a)
        sin_a = math.sin(a)
        x = cx + rx * cos_a
        y = cy + ry * sin_a

        # Tangent at this angle
        tx = -rx * sin_a * kappa
        ty = ry * cos_a * kappa

        # In-handle: arrives along -tangent (from previous segment)
        # Out-handle: departs along +tangent (to next segment)
        in_h: Optional[Point] = None
        out_h: Optional[Point] = None

        if i > 0 or is_full:
            # Has incoming segment
            in_h = (x - tx, y - ty)

        if i < segments or is_full:
            # Has outgoing segment
            out_h = (x + tx, y + ty)

        pt_type: Literal["smooth", "corner"] = "smooth"
        if in_h is None and out_h is None:
            pt_type = "corner"

        result.append(BezierPoint(
            anchor=(x, y),
            in_handle=in_h,
            out_handle=out_h,
            point_type=pt_type,
        ))

    # For full circle, last point duplicates first — remove it
    if is_full and len(result) > 1:
        # Transfer last point's in_handle to first point
        last = result[-1]
        first = result[0]
        result[0] = BezierPoint(
            anchor=first.anchor,
            in_handle=last.in_handle,
            out_handle=first.out_handle,
            point_type="smooth",
        )
        result = result[:-1]

    return BezierPath(points=tuple(result), closed=is_full)


# ── Rounded polygon ────────────────────────────────────────────────

def rounded_polygon(
    vertices: Sequence[Point],
    radius: float,
    closed: bool = True,
) -> BezierPath:
    """Round corners of a polygon with Bézier fillets.

    Each corner is replaced by a circular arc tangent to the two edges.
    The arc radius is clamped to half the shorter adjacent edge.

    Args:
        vertices: Polygon vertices as (x, y) sequence.
        radius: Corner rounding radius in points.
        closed: Whether the polygon is closed.

    Returns:
        BezierPath with rounded corners.
    """
    n = len(vertices)
    if n < 2 or (closed and n < 3):
        return BezierPath(
            points=tuple(BezierPoint(anchor=tuple(v), point_type="corner") for v in vertices),
            closed=closed,
        )

    verts = [tuple(v) for v in vertices]

    result: List[BezierPoint] = []

    corners = range(n) if closed else range(1, n - 1)

    for i in corners:
        i_prev = (i - 1) % n
        i_next = (i + 1) % n

        p = verts[i]
        p_prev = verts[i_prev]
        p_next = verts[i_next]

        # Edge vectors
        dx_in = p[0] - p_prev[0]
        dy_in = p[1] - p_prev[1]
        len_in = math.hypot(dx_in, dy_in)

        dx_out = p_next[0] - p[0]
        dy_out = p_next[1] - p[1]
        len_out = math.hypot(dx_out, dy_out)

        if len_in < 1e-10 or len_out < 1e-10:
            # Degenerate edge — sharp corner
            result.append(BezierPoint(anchor=p, point_type="corner"))
            continue

        # Clamp radius to half the shorter edge
        max_r = min(len_in, len_out) / 2.0
        r = min(radius, max_r)

        # Unit vectors along edges
        u_in = (dx_in / len_in, dy_in / len_in)
        u_out = (dx_out / len_out, dy_out / len_out)

        # Points where the fillet meets the edges
        fillet_start = (p[0] - u_in[0] * r, p[1] - u_in[1] * r)
        fillet_end = (p[0] + u_out[0] * r, p[1] + u_out[1] * r)

        # Per-vertex kappa: compute from actual corner half-angle
        # dot = cos(π - corner_angle) where corner_angle is between edges
        dot = u_in[0] * u_out[0] + u_in[1] * u_out[1]
        dot = max(-1.0, min(1.0, dot))  # clamp for numerical safety
        # half_angle = (π - corner_angle) / 2 = angle subtended by fillet / 2
        half_angle = math.acos(dot) / 2.0
        kappa = (4.0 / 3.0) * math.tan(half_angle / 2.0) if half_angle > 1e-10 else 0.0
        handle_len = r * kappa

        # Handles follow edge direction
        start_out = (
            fillet_start[0] + u_in[0] * handle_len,
            fillet_start[1] + u_in[1] * handle_len,
        )
        end_in = (
            fillet_end[0] - u_out[0] * handle_len,
            fillet_end[1] - u_out[1] * handle_len,
        )

        result.append(BezierPoint(
            anchor=fillet_start,
            in_handle=None,  # sharp from straight segment
            out_handle=start_out,
            point_type="smooth",
        ))
        result.append(BezierPoint(
            anchor=fillet_end,
            in_handle=end_in,
            out_handle=None,  # sharp to straight segment
            point_type="smooth",
        ))

    # For open curves, prepend first vertex and append last
    if not closed:
        result.insert(0, BezierPoint(anchor=verts[0], point_type="corner"))
        result.append(BezierPoint(anchor=verts[-1], point_type="corner"))

    return BezierPath(points=tuple(result), closed=closed)
