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
    """Raise a helpful error if pyclipper is not installed."""
    if pyclipper is None:
        raise ImportError(
            "path_boolean requires pyclipper. "
            "Install with: pip install illustrator-mcp[geometry]"
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


# ── Bézier flattening ──────────────────────────────────────────────

def _de_casteljau_flatness(
    p0: Point, p1: Point, p2: Point, p3: Point,
) -> float:
    """Estimate flatness of a cubic Bézier segment.

    Measures the maximum deviation of control points from the chord p0→p3.
    Uses the simple heuristic: max distance of p1,p2 from line(p0,p3).
    """
    # Vector from p0 to p3
    dx = p3[0] - p0[0]
    dy = p3[1] - p0[1]
    chord_len_sq = dx * dx + dy * dy

    if chord_len_sq < 1e-12:
        # Degenerate: all points coincide
        d1 = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        d2 = math.hypot(p2[0] - p0[0], p2[1] - p0[1])
        return max(d1, d2)

    inv_len = 1.0 / math.sqrt(chord_len_sq)
    # Perpendicular distance of p1 from chord
    d1 = abs((p1[0] - p0[0]) * dy - (p1[1] - p0[1]) * dx) * inv_len
    # Perpendicular distance of p2 from chord
    d2 = abs((p2[0] - p0[0]) * dy - (p2[1] - p0[1]) * dx) * inv_len
    return max(d1, d2)


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
) -> Contour:
    """Flatten a single cubic Bézier to a polyline via adaptive subdivision.

    Args:
        p0: Start anchor
        p1: Control point 1 (out-handle of p0)
        p2: Control point 2 (in-handle of p3)
        p3: End anchor
        tolerance: Maximum allowed deviation (in points)
        max_segments: Safety cap — raises ValueError if exceeded

    Returns:
        List of points (excluding p0, including p3)
    """
    result: Contour = []
    # Stack-based iteration (avoids recursion depth issues)
    stack = [(p0, p1, p2, p3)]

    while stack:
        if len(result) >= max_segments:
            raise ValueError(
                f"Bézier flattening exceeded max_segments={max_segments}. "
                f"Increase max_segments or raise flatten_tolerance."
            )
        seg = stack.pop()
        flatness = _de_casteljau_flatness(*seg)
        if flatness <= tolerance:
            # Flat enough — emit endpoint
            result.append(seg[3])
        else:
            # Subdivide and push right half first (so left is processed first)
            left, right = _subdivide_cubic(*seg)
            stack.append(right)
            stack.append(left)

    return result


def flatten_path(
    anchors: Contour,
    in_handles: Contour,
    out_handles: Contour,
    closed: bool = True,
    tolerance: float = DEFAULT_FLATTEN_TOLERANCE,
    max_segments: int = DEFAULT_MAX_SEGMENTS,
) -> Contour:
    """Flatten an entire path (sequence of cubic Bézier segments) to a polyline.

    Args:
        anchors: Anchor points [(x,y), ...]
        in_handles: Left direction handles (absolute coords), same length as anchors
        out_handles: Right direction handles (absolute coords), same length as anchors
        closed: Whether path is closed
        tolerance: Bézier flatten precision
        max_segments: Max total segments for entire path

    Returns:
        Polyline as list of (x,y) tuples
    """
    n = len(anchors)
    if n < 2:
        return list(anchors)

    result: Contour = [anchors[0]]
    total_segments = 0
    segments_to_process = n if closed else n - 1

    for i in range(segments_to_process):
        j = (i + 1) % n
        p0 = anchors[i]
        p1 = out_handles[i]    # out-handle of current point
        p2 = in_handles[j]     # in-handle of next point
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
            sub_points = flatten_cubic(p0, p1, p2, p3, tolerance, remaining)
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
