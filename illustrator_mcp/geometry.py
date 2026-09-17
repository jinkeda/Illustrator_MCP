"""
Python-side boolean geometry engine for path_boolean SOC op.

Uses pyclipper (Clipper library) for polygon boolean operations.
All coordinates are in SOC convention: artboard-relative, Y-down.

Fully unit-testable without Illustrator.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Sequence, Tuple

# ── pyclipper import guard ──────────────────────────────────────────
try:
    import pyclipper
except ImportError:
    pyclipper = None  # type: ignore[assignment]

# ── Constants ───────────────────────────────────────────────────────
CLIPPER_SCALE = 1000  # float pts → int64 for Clipper (sub-point precision)
DEFAULT_FLATTEN_TOLERANCE = 0.5  # points
DEFAULT_MAX_SEGMENTS = 500  # per curve segment, safety cap

# T05: independent work budgets.  max_segments bounds the *emitted* polyline,
# not the subdivision work, so on its own it cannot stop a branch that never
# reaches the flat-enough test.  These bound the work itself.
DEFAULT_MAX_DEPTH = 32
"""Maximum De Casteljau subdivision depth for one curve segment.

At depth 32 a segment spans 2^-32 of the original parameter range — far below
any meaningful drawing tolerance.  Reaching it means the flatness test is not
converging, which is a bug or a pathological input, not a curve worth drawing.
"""

MAX_SUBDIVISION_FACTOR = 8
"""Subdivision budget per allowed output segment.

A well-behaved adaptive flattener performs O(n) splits for n emitted points.
A factor of 8 leaves generous headroom while still bounding total work."""

MIN_SUBDIVISION_BUDGET = 1024

ABSOLUTE_SUBDIVISION_CAP = 250_000
"""Hard ceiling on split operations for one curve, whatever the caller asks.

A depth cap alone does NOT bound total work: with a tolerance far below the
curve's scale every branch converges just under the depth limit, so the tree
still has O(2^depth) leaves — a tolerance of 1e-12 on a 1e6-wide curve
converges around depth 30, i.e. ~10^9 segments.  Deriving the budget from
`max_segments` does not help either, since an absurd `max_segments` yields an
absurd budget.

The value is chosen for *latency*, not geometry: this work runs synchronously
on the server's event loop, so the worst case must stay around a second.  It
is ~60x the budget a default 500-segment flatten uses, so real paths never
approach it.  Pass `max_subdivisions` explicitly to raise it deliberately."""

Point = Tuple[float, float]
Contour = List[Point]

# ── Operation name mapping ──────────────────────────────────────────
_OP_MAP = None  # lazy-init after pyclipper import check


def _get_op_map():
    global _OP_MAP
    if _OP_MAP is None:
        _ensure_pyclipper()
        _OP_MAP = {
            "subtract": pyclipper.CT_DIFFERENCE,
            "unite": pyclipper.CT_UNION,
            "intersect": pyclipper.CT_INTERSECTION,
            "xor": pyclipper.CT_XOR,
        }
    return _OP_MAP


def _ensure_pyclipper():
    """Raise a helpful error if pyclipper is not installed.

    Retries the import if it was None at module load time (e.g., installed after
    server start). Updates the module-level variable on success.
    """
    global pyclipper
    if pyclipper is None:
        try:
            import pyclipper as _pc
            pyclipper = _pc
        except ImportError as orig:
            raise ImportError(
                f"path_boolean requires pyclipper. "
                f"Install with: pip install pyclipper "
                f"(original error: {orig})"
            )


# ── Data structures ─────────────────────────────────────────────────

@dataclass
class Region:
    """A boolean result region: one outer contour + zero or more holes.

    Outer contour has CCW winding (positive area in Clipper).
    Holes have CW winding (negative area in Clipper).
    """
    outer: Contour
    holes: List[Contour] = field(default_factory=list)


# ── Coordinate scaling ──────────────────────────────────────────────

def scale_to_clipper(
    points: Contour,
    scale: int = CLIPPER_SCALE,
) -> List[Tuple[int, int]]:
    """Convert float coordinates to Clipper integer space."""
    return [(round(x * scale), round(y * scale)) for x, y in points]


def scale_from_clipper(
    points: Sequence[Tuple[int, int]],
    scale: int = CLIPPER_SCALE,
) -> Contour:
    """Convert Clipper integer coordinates back to float space."""
    return [(x / scale, y / scale) for x, y in points]


# ── Input validation (T05) ─────────────────────────────────────────

def _validate_tolerance(tolerance: float, name: str = "tolerance") -> float:
    """Require a strictly positive, finite tolerance.

    A non-positive or NaN tolerance makes ``flatness <= tolerance`` unsatisfiable
    (flatness is always a non-negative real), so adaptive subdivision never
    terminates.  Rejecting it up front turns a hang into an immediate error.
    """
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)):
        raise ValueError(
            f"{name} must be a positive finite number, got "
            f"{type(tolerance).__name__}"
        )
    value = float(tolerance)
    if math.isnan(value):
        raise ValueError(f"{name} must be a positive finite number, got NaN")
    if math.isinf(value):
        raise ValueError(f"{name} must be a positive finite number, got {value}")
    if value <= 0:
        raise ValueError(
            f"{name} must be greater than 0, got {value}. A tolerance of 0 or "
            f"less can never be satisfied, so subdivision would not terminate."
        )
    return value


def _validate_positive_int(value: int, name: str) -> int:
    """Require a strictly positive integer budget."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{name} must be a positive integer, got {type(value).__name__}"
        )
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0, got {value}")
    return value


# ── Bézier flattening ──────────────────────────────────────────────

def _de_casteljau_flatness(
    p0: Point, p1: Point, p2: Point, p3: Point,
) -> float:
    """Estimate flatness of a cubic Bézier segment.

    Returns the maximum distance of the control points from the chord
    **segment** p0→p3.

    T05: this used the distance to the infinite *line* through p0 and p3, which
    reports zero for any control point that happens to be collinear with the
    chord — however far past its ends it lies.  The curve
    ``(0,0) (100,0) (100,0) (1,0)`` was therefore judged perfectly flat and
    flattened straight to ``(1,0)``, discarding an excursion out to x ≈ 75.

    Measuring against the segment adds the longitudinal overshoot, so a control
    point beyond an endpoint is correctly reported as far from flat.  For
    ordinary curves, whose control points project inside the chord, the
    overshoot term is zero and the result is unchanged.
    """
    # Vector from p0 to p3
    dx = p3[0] - p0[0]
    dy = p3[1] - p0[1]
    chord_len_sq = dx * dx + dy * dy

    if chord_len_sq < 1e-12:
        # Degenerate chord: the endpoints coincide, so there is no direction to
        # project onto. Fall back to plain distance from the shared endpoint —
        # this already accounts for any excursion.
        d1 = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        d2 = math.hypot(p2[0] - p0[0], p2[1] - p0[1])
        return max(d1, d2)

    chord_len = math.sqrt(chord_len_sq)
    inv_len = 1.0 / chord_len

    def _distance_to_chord(p: Point) -> float:
        ux = p[0] - p0[0]
        uy = p[1] - p0[1]
        # Perpendicular offset from the chord line
        perpendicular = abs(ux * dy - uy * dx) * inv_len
        # Position along the chord, normalised to [0, 1] between the endpoints
        t = (ux * dx + uy * dy) / chord_len_sq
        if t < 0.0:
            overshoot = -t * chord_len
        elif t > 1.0:
            overshoot = (t - 1.0) * chord_len
        else:
            return perpendicular
        return math.hypot(perpendicular, overshoot)

    return max(_distance_to_chord(p1), _distance_to_chord(p2))


def _subdivide_cubic(
    p0: Point, p1: Point, p2: Point, p3: Point,
) -> tuple:
    """Split cubic Bézier at t=0.5 using De Casteljau."""
    m01 = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
    m12 = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    m23 = ((p2[0] + p3[0]) / 2, (p2[1] + p3[1]) / 2)

    m012 = ((m01[0] + m12[0]) / 2, (m01[1] + m12[1]) / 2)
    m123 = ((m12[0] + m23[0]) / 2, (m12[1] + m23[1]) / 2)

    mid = ((m012[0] + m123[0]) / 2, (m012[1] + m123[1]) / 2)

    # Left half: p0, m01, m012, mid
    # Right half: mid, m123, m23, p3
    return (p0, m01, m012, mid), (mid, m123, m23, p3)


def flatten_cubic(
    p0: Point,
    p1: Point,
    p2: Point,
    p3: Point,
    tolerance: float = DEFAULT_FLATTEN_TOLERANCE,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_subdivisions: Optional[int] = None,
) -> Contour:
    """Flatten a single cubic Bézier to a polyline via adaptive subdivision.

    Args:
        p0: Start anchor
        p1: Control point 1 (out-handle of p0)
        p2: Control point 2 (in-handle of p3)
        p3: End anchor
        tolerance: Maximum allowed deviation, in points. Must be > 0 and finite.
        max_segments: Cap on *emitted* points.
        max_depth: Cap on subdivision depth for any single branch.
        max_subdivisions: Cap on total split operations. Defaults to
            ``max(MIN_SUBDIVISION_BUDGET, max_segments * MAX_SUBDIVISION_FACTOR)``.

    Returns:
        List of points (excluding p0, including p3)

    Raises:
        ValueError: on an invalid tolerance or budget, or when a budget is
            exhausted. T05: ``max_segments`` alone bounds only the output, and
            output grows only when a segment tests flat — so a branch that
            never tests flat (an unsatisfiable tolerance, a pathological curve)
            would subdivide forever while ``len(result)`` stayed at 0. The
            depth and subdivision budgets bound the work itself.
    """
    tolerance = _validate_tolerance(tolerance)
    max_segments = _validate_positive_int(max_segments, "max_segments")
    max_depth = _validate_positive_int(max_depth, "max_depth")
    if max_subdivisions is None:
        max_subdivisions = min(
            ABSOLUTE_SUBDIVISION_CAP,
            max(MIN_SUBDIVISION_BUDGET, max_segments * MAX_SUBDIVISION_FACTOR),
        )
    else:
        max_subdivisions = _validate_positive_int(max_subdivisions, "max_subdivisions")

    result: Contour = []
    subdivisions = 0
    # Stack-based iteration (avoids recursion depth issues); depth travels
    # with each segment so one deep branch cannot hide behind a shallow one.
    stack = [(p0, p1, p2, p3, 0)]

    while stack:
        if len(result) >= max_segments:
            raise ValueError(
                f"Bézier flattening exceeded max_segments={max_segments}. "
                f"Increase max_segments or raise flatten_tolerance."
            )
        s0, s1, s2, s3, depth = stack.pop()
        flatness = _de_casteljau_flatness(s0, s1, s2, s3)

        if flatness <= tolerance:
            # Flat enough — emit endpoint
            result.append(s3)
            continue

        if depth >= max_depth:
            raise ValueError(
                f"Bézier flattening exceeded max_depth={max_depth} without "
                f"reaching tolerance={tolerance} (flatness={flatness:.6g}). "
                f"The curve is degenerate or the tolerance is too tight."
            )

        subdivisions += 1
        if subdivisions > max_subdivisions:
            raise ValueError(
                f"Bézier flattening exceeded max_subdivisions="
                f"{max_subdivisions}. Raise flatten_tolerance or simplify "
                f"the path."
            )

        # Subdivide and push right half first (so left is processed first)
        left, right = _subdivide_cubic(s0, s1, s2, s3)
        stack.append(right + (depth + 1,))
        stack.append(left + (depth + 1,))

    return result


def flatten_path(
    anchors: Contour,
    left_handles: Contour,
    right_handles: Contour,
    closed: bool = True,
    tolerance: float = DEFAULT_FLATTEN_TOLERANCE,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> Contour:
    """Flatten an entire path (sequence of cubic Bézier segments) to a polyline.

    Args:
        anchors: Anchor points [(x,y), ...]
        left_handles: Left (in-direction) handles (absolute coords), same length as anchors
        right_handles: Right (out-direction) handles (absolute coords), same length as anchors
        closed: Whether path is closed
        tolerance: Bézier flatten precision. Must be > 0 and finite.
        max_segments: Max total segments for entire path
        max_depth: Max subdivision depth per curve segment

    Returns:
        Polyline as list of (x,y) tuples

    Raises:
        ValueError: on invalid inputs or exhausted budgets. Inputs are checked
            before any work so a bad tolerance fails promptly rather than after
            partial flattening (T05).
    """
    tolerance = _validate_tolerance(tolerance)
    max_segments = _validate_positive_int(max_segments, "max_segments")
    max_depth = _validate_positive_int(max_depth, "max_depth")

    n = len(anchors)
    if n < 2:
        return list(anchors)

    if len(left_handles) != n or len(right_handles) != n:
        raise ValueError(
            f"handle arrays must match anchors: got {n} anchors, "
            f"{len(left_handles)} left handles, {len(right_handles)} right handles"
        )

    result: Contour = [anchors[0]]
    total_segments = 0
    segments_to_process = n if closed else n - 1

    for i in range(segments_to_process):
        j = (i + 1) % n
        p0 = anchors[i]
        p1 = right_handles[i]    # right (out) handle of current point
        p2 = left_handles[j]     # left (in) handle of next point
        p3 = anchors[j]

        # Check if this segment is actually a line (handles == anchors)
        is_line = (
            abs(p1[0] - p0[0]) < 1e-6 and abs(p1[1] - p0[1]) < 1e-6 and
            abs(p2[0] - p3[0]) < 1e-6 and abs(p2[1] - p3[1]) < 1e-6
        )

        if is_line:
            if not closed or j != 0:  # Don't duplicate start point for closed paths
                result.append(p3)
            total_segments += 1
        else:
            remaining = max_segments - total_segments
            if remaining <= 0:
                raise ValueError(
                    f"Path flattening exceeded max_segments={max_segments}. "
                    f"Increase max_segments or raise flatten_tolerance."
                )
            sub_points = flatten_cubic(
                p0, p1, p2, p3, tolerance, remaining, max_depth=max_depth
            )
            # Skip last point if this closes back to start
            if closed and j == 0 and sub_points:
                sub_points = sub_points[:-1]
            result.extend(sub_points)
            total_segments += len(sub_points)

    return result


# ── PolyTree → Region conversion ───────────────────────────────────

def _polytree_to_regions(polytree) -> List[Region]:
    """Walk a pyclipper PolyTree and convert to Region list.

    PolyTree structure:
    - Top-level children are outer contours
    - Their children are holes
    - Hole's children are nested outer contours (islands inside holes)
    - Recurse for nested structures

    Each outer contour + its direct hole children form one Region.
    Nested islands become separate Regions (recursive).
    """
    _ensure_pyclipper()
    regions: List[Region] = []

    def _walk_outer(node):
        """Process an outer contour node and its hole children."""
        outer_pts = scale_from_clipper(node.Contour)
        holes = []
        for hole_node in node.Childs:
            hole_pts = scale_from_clipper(hole_node.Contour)
            holes.append(hole_pts)
            # Holes may contain nested islands — those are new outer contours
            for nested_outer in hole_node.Childs:
                _walk_outer(nested_outer)
        regions.append(Region(outer=outer_pts, holes=holes))

    # Top-level PolyTree children are outer contours
    for top_child in polytree.Childs:
        _walk_outer(top_child)

    return regions


# ── Main boolean function ──────────────────────────────────────────

def path_boolean(
    subject: Contour,
    clips: Contour | List[Contour],
    operation: Literal["subtract", "unite", "intersect", "xor"],
) -> List[Region]:
    """Perform a boolean operation on 2D polygon contours.

    Args:
        subject: Subject polygon as [(x,y), ...] — the "kept" shape
        clips: One or more clip polygons — the "cutting" shape(s)
        operation: Boolean operation type

    Returns:
        List of Region objects, each with an outer contour and optional holes.
        Empty list if result is empty (e.g., subtract identical shapes).

    Raises:
        ImportError: If pyclipper is not installed
        ValueError: If operation is invalid
        pyclipper.ClipperException: On degenerate geometry
    """
    _ensure_pyclipper()

    op_map = _get_op_map()
    if operation not in op_map:
        raise ValueError(
            f"Invalid operation '{operation}'. "
            f"Valid: {list(op_map.keys())}"
        )

    # Normalize clips to list of contours
    # A contour looks like [(x,y), (x,y), ...] — a list/tuple of 2-tuples
    # A list of contours looks like [[(x,y),...], [(x,y),...]]
    # If clips[0] is a point (tuple of 2 numbers), clips is a single contour
    if clips and isinstance(clips[0], tuple) and len(clips[0]) == 2:
        clips = [clips]

    # Scale to Clipper integer space
    subject_scaled = scale_to_clipper(subject)
    clips_scaled = [scale_to_clipper(c) for c in clips]

    # Build Clipper object
    pc = pyclipper.Pyclipper()
    pc.AddPath(subject_scaled, pyclipper.PT_SUBJECT, True)
    for clip_scaled in clips_scaled:
        pc.AddPath(clip_scaled, pyclipper.PT_CLIP, True)

    # Execute with PolyTree output for hole detection
    result_tree = pc.Execute2(
        op_map[operation],
        pyclipper.PFT_NONZERO,
        pyclipper.PFT_NONZERO,
    )

    return _polytree_to_regions(result_tree)


def path_boolean_compound(
    subject_contours: List[Contour],
    clip_contours: List[Contour],
    operation: Literal["subtract", "unite", "intersect", "xor"],
    *,
    subject_fill_rule: Literal["nonzero", "evenodd"] = "nonzero",
    clip_fill_rule: Literal["nonzero", "evenodd"] = "nonzero",
) -> List[Region]:
    """Boolean one or more filled subject/clip contours without discarding holes.

    Illustrator compound paths are represented by several contours.  Sending
    only the first contour fills their holes and makes a chained boolean
    geometrically incorrect.  This entry point adds every contour to Clipper
    under the appropriate role and preserves the supported Illustrator fill
    rule explicitly.
    """
    _ensure_pyclipper()
    op_map = _get_op_map()
    if operation not in op_map:
        raise ValueError(f"Invalid operation '{operation}'. Valid: {list(op_map.keys())}")
    if not subject_contours:
        raise ValueError("subject_contours must contain at least one contour")
    if not clip_contours:
        raise ValueError("clip_contours must contain at least one contour")

    fill_types = {
        "nonzero": pyclipper.PFT_NONZERO,
        "evenodd": pyclipper.PFT_EVENODD,
    }
    if subject_fill_rule not in fill_types or clip_fill_rule not in fill_types:
        raise ValueError("fill rule must be 'nonzero' or 'evenodd'")

    pc = pyclipper.Pyclipper()
    pc.AddPaths(
        [scale_to_clipper(contour) for contour in subject_contours],
        pyclipper.PT_SUBJECT,
        True,
    )
    pc.AddPaths(
        [scale_to_clipper(contour) for contour in clip_contours],
        pyclipper.PT_CLIP,
        True,
    )
    result_tree = pc.Execute2(
        op_map[operation],
        fill_types[subject_fill_rule],
        fill_types[clip_fill_rule],
    )
    return _polytree_to_regions(result_tree)
