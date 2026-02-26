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


# ── Polar & Relative Handle Resolution (Level 3) ──────────────────

def _resolve_single_handle(
    anchor: Point,
    spec: dict,
) -> Point:
    """Resolve a single handle spec to an absolute coordinate.

    Spec formats:
        {"angle": degrees, "length": float}   → Polar
        {"dx": float, "dy": float}            → Relative delta

    Coordinate convention (same frame as points — no axis flipping):
        angle=0   → +X (rightward)
        angle=90  → +Y (in whichever direction +Y means in the point frame)
        CCW positive in standard math convention.
    """
    ax, ay = anchor

    if "angle" in spec and "length" in spec:
        angle = float(spec["angle"])
        length = float(spec["length"])
        if not math.isfinite(angle) or not math.isfinite(length):
            raise ValueError(f"Non-finite angle ({angle}) or length ({length})")
        rad = math.radians(angle)
        # Vanilla cos/sin — no axis flip; matches coordinate frame of points
        return (ax + length * math.cos(rad), ay + length * math.sin(rad))

    if "dx" in spec or "dy" in spec:
        dx = float(spec.get("dx", 0.0))
        dy = float(spec.get("dy", 0.0))
        if not math.isfinite(dx) or not math.isfinite(dy):
            raise ValueError(f"Non-finite dx ({dx}) or dy ({dy})")
        return (ax + dx, ay + dy)

    raise ValueError(f"Handle spec must have (angle+length) or (dx/dy), got: {spec}")


def resolve_polar_handles(
    points: Sequence[Sequence[float]],
    handles_spec: Sequence[Optional[dict]],
) -> list:
    """Convert polar/relative handle specs to absolute triplet format.

    Always returns triplets [[ax,ay],[inH],[outH]] for every point
    (including corners, where handles are coincident with anchor).

    For each point, handles_spec[i] can be:
      - None → corner: triplet with coincident handles
      - {"angle": deg, "length": float, "symmetric": bool}
          → Polar: out-handle at (angle, length) from anchor.
            If symmetric=True, in-handle auto-mirrored (angle+180, same length).
      - {"dx": float, "dy": float, "symmetric": bool}
          → Relative: out-handle = anchor + (dx, dy).
            If symmetric=True, in-handle = anchor - (dx, dy).
      - {"in": spec_dict, "out": spec_dict}
          → Independent in/out handles. 'symmetric' is ignored.

    Returns:
        List of [[ax,ay],[inX,inY],[outX,outY]] triplets.
        Compatible with _createPathWithHandles in ops_element.jsx.
    """
    if len(handles_spec) != len(points):
        raise ValueError(
            f"handles_spec length ({len(handles_spec)}) must match "
            f"points length ({len(points)})"
        )

    result = []
    for i, (pt, spec) in enumerate(zip(points, handles_spec)):
        anchor = (float(pt[0]), float(pt[1]))
        a_list = list(anchor)

        if spec is None:
            # Corner point — coincident handles (triplet for consistency)
            result.append([a_list, list(anchor), list(anchor)])
            continue

        # Independent in/out handles
        if "in" in spec and "out" in spec:
            in_h = _resolve_single_handle(anchor, spec["in"])
            out_h = _resolve_single_handle(anchor, spec["out"])
            result.append([a_list, list(in_h), list(out_h)])
            continue

        # Single spec → defines out-handle, optionally symmetric in-handle
        out_h = _resolve_single_handle(anchor, spec)

        symmetric = spec.get("symmetric", False)
        if symmetric:
            # Mirror: in-handle = anchor - (out - anchor)
            dx = out_h[0] - anchor[0]
            dy = out_h[1] - anchor[1]
            in_h = (anchor[0] - dx, anchor[1] - dy)
            result.append([a_list, list(in_h), list(out_h)])
        else:
            # Asymmetric: only out-handle, in is coincident (sharp on incoming)
            result.append([a_list, list(anchor), list(out_h)])

    return result


# ── Symmetry Modifiers (Level 4) ──────────────────────────────────

# Valid mirror modes
_MIRROR_MODES = frozenset({
    "mirror_y_bottom", "mirror_y_top",
    "mirror_x_right", "mirror_x_left",
})


def _is_on_axis(value: float, axis_coord: float, epsilon: float) -> bool:
    """Check if a coordinate lies on the mirror axis within tolerance."""
    return abs(value - axis_coord) < epsilon


def _mirror_coord(value: float, origin: float) -> float:
    """Reflect a coordinate across the origin: v' = 2*origin - v."""
    return 2.0 * origin - value


def _mirror_single_point(
    pt: Union[list, Sequence],
    axis: str,
    origin: float,
) -> list:
    """Mirror a single point (simple or triplet) across the axis.

    For triplets [[ax,ay], in_h, out_h]:
      - Anchor is mirrored
      - In-handle and out-handle are mirrored AND swapped
        (because path direction reverses in the mirrored half)

    axis: "y" (mirror Y coords) or "x" (mirror X coords)
    """
    is_y = axis == "y"

    # Detect if triplet: [[ax,ay], in_h_or_None, out_h_or_None]
    if (
        isinstance(pt, (list, tuple))
        and len(pt) == 3
        and isinstance(pt[0], (list, tuple))
        and len(pt[0]) == 2
    ):
        anchor = pt[0]
        in_h = pt[1]
        out_h = pt[2]

        if is_y:
            m_anchor = [anchor[0], _mirror_coord(anchor[1], origin)]
            m_in = [in_h[0], _mirror_coord(in_h[1], origin)] if in_h else None
            m_out = [out_h[0], _mirror_coord(out_h[1], origin)] if out_h else None
        else:
            m_anchor = [_mirror_coord(anchor[0], origin), anchor[1]]
            m_in = [_mirror_coord(in_h[0], origin), in_h[1]] if in_h else None
            m_out = [_mirror_coord(out_h[0], origin), out_h[1]] if out_h else None

        # Swap in/out handles (path reversal)
        return [m_anchor, m_out, m_in]

    # Simple [x, y] point
    if is_y:
        return [pt[0], _mirror_coord(pt[1], origin)]
    else:
        return [_mirror_coord(pt[0], origin), pt[1]]


def _get_anchor(pt: Union[list, Sequence]) -> Tuple[float, float]:
    """Extract the anchor coordinates from a point (simple or triplet)."""
    if (
        isinstance(pt, (list, tuple))
        and len(pt) == 3
        and isinstance(pt[0], (list, tuple))
    ):
        return (float(pt[0][0]), float(pt[0][1]))
    return (float(pt[0]), float(pt[1]))


def _detect_origin(
    points: Sequence,
    axis: str,
) -> float:
    """Auto-detect mirror origin from point data.

    Rules:
      1. If first or last anchor lies on a coordinate shared between them
         (on the axis dimension), use that.
      2. Else: bbox center of anchors on the axis dimension.
    """
    if not points:
        return 0.0

    idx = 1 if axis == "y" else 0  # which coord to examine

    first = _get_anchor(points[0])
    last = _get_anchor(points[-1])

    # If first and last share the same axis coord, that's the symmetry line
    if abs(first[idx] - last[idx]) < 1e-6:
        return first[idx]

    # Fallback: bbox center
    coords = [_get_anchor(p)[idx] for p in points]
    return (min(coords) + max(coords)) / 2.0


def mirror_points(
    points: Sequence,
    mode: str,
    origin: Optional[float] = None,
    epsilon: float = 1e-6,
) -> list:
    """Duplicate and flip points to create bilateral symmetry.

    Operates on resolved points (simple [x,y] or triplets [[ax,ay],in,out]).
    Handles are mirrored and in/out swapped for correct path direction.

    Seam deduplication: if first/last anchor is on the axis (within epsilon),
    it is not duplicated in the mirrored half.

    Args:
        points: Sequence of [x,y] or [[ax,ay],[inH],[outH]] points.
        mode: Mirror mode enum string.
        origin: Axis coordinate. Auto-detected if None.
        epsilon: Tolerance for seam deduplication.

    Returns:
        List of points forming a closed path (original + reversed mirrored).

    Raises:
        ValueError: If mode is not recognized or points is empty.
    """
    if mode not in _MIRROR_MODES:
        raise ValueError(
            f"Unknown mirror mode '{mode}'. "
            f"Valid: {sorted(_MIRROR_MODES)}"
        )
    if not points:
        raise ValueError("Cannot mirror empty points list")

    # Determine axis direction
    axis = "y" if mode.startswith("mirror_y") else "x"

    # Auto-detect origin
    if origin is None:
        origin = _detect_origin(points, axis)

    # Determine if we need to flip the input (e.g., mirror_y_top means
    # input is bottom, generate top; we still mirror around origin)
    # The mirroring math is the same — the "direction" is just for semantics.
    # mirror_y_bottom: input=top, generate bottom → result = original + mirrored
    # mirror_y_top:    input=bottom, generate top → result = mirrored + original
    prepend = mode in ("mirror_y_top", "mirror_x_left")

    # Mirror all points
    idx = 1 if axis == "y" else 0
    mirrored = []
    for pt in points:
        mirrored.append(_mirror_single_point(pt, axis, origin))

    # Reverse mirrored half (path direction)
    mirrored.reverse()

    # Seam deduplication: check first/last of original against axis
    first_anchor = _get_anchor(points[0])
    last_anchor = _get_anchor(points[-1])

    first_on_axis = _is_on_axis(first_anchor[idx], origin, epsilon)
    last_on_axis = _is_on_axis(last_anchor[idx], origin, epsilon)

    if prepend:
        # mirrored (reversed) + original
        # Seam is at: end of mirrored = mirror of points[0],
        #             start of original = points[0]
        # If points[0] is on axis, drop last of mirrored (it's a duplicate)
        if first_on_axis and mirrored:
            mirrored = mirrored[:-1]
        # Also check: start of mirrored = mirror of points[-1],
        # if points[-1] is on axis, it mirrors to itself → drop first of mirrored
        if last_on_axis and mirrored:
            mirrored = mirrored[1:]
        return list(mirrored) + list(points)
    else:
        # original + mirrored (reversed)
        # Seam at: end of original = points[-1],
        #          start of mirrored = mirror of points[-1]
        # If points[-1] is on axis, drop first of mirrored (duplicate)
        if last_on_axis and mirrored:
            mirrored = mirrored[1:]
        # Also: end of mirrored = mirror of points[0],
        # if points[0] is on axis, drop last of mirrored
        if first_on_axis and mirrored:
            mirrored = mirrored[:-1]
        return list(points) + list(mirrored)
