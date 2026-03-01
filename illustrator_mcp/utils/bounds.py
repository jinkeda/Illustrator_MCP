"""
bounds.py — Shared bounds intersection utilities.

Provides centralized artboard intersection checks for use by
import_svg, task_execution, and other element-creation tools.
"""

from typing import Any, Dict, List, Optional, Tuple

# Canonical coordinate space constant — use everywhere bounds are reported.
BOUNDS_SPACE_ILLUSTRATOR_Y_UP = "illustrator_native_y_up"


def bounds_intersects_artboard(
    item_bounds: List[float],
    artboard_rect: List[float],
    epsilon: float = 1.0,
) -> Tuple[bool, Dict[str, Any]]:
    """Check if item bounds intersect artboard.

    Both bounds use Illustrator's native coordinate space:
    [left, top, right, bottom] where Y increases upward (top > bottom).

    Args:
        item_bounds: [left, top, right, bottom] of the created item.
        artboard_rect: [left, top, right, bottom] of the artboard.
        epsilon: Minimum overlap area in pt² to count as intersection.
            Edge-touching (overlap_area < epsilon) = non-intersection.

    Returns:
        (intersects, details) where details contains:
        - created_bounds: the item bounds
        - artboard_bounds: the artboard rect
        - bounds_space: coordinate space identifier
        - overlap_area: clamped to max(0, ...)
        - overlap_rect: [l, t, r, b] of intersection region (if any)
    """
    # Illustrator Y-up: top > bottom
    # Intersection region
    inter_left = max(item_bounds[0], artboard_rect[0])
    inter_top = min(item_bounds[1], artboard_rect[1])  # Y-up: top is max Y
    inter_right = min(item_bounds[2], artboard_rect[2])
    inter_bottom = max(item_bounds[3], artboard_rect[3])  # Y-up: bottom is min Y

    # Width and height of intersection (Y-up: height = top - bottom)
    inter_width = max(0.0, inter_right - inter_left)
    inter_height = max(0.0, inter_top - inter_bottom)
    overlap_area = max(0.0, inter_width * inter_height)

    overlap_rect: Optional[List[float]] = None
    if overlap_area > 0:
        overlap_rect = [inter_left, inter_top, inter_right, inter_bottom]

    intersects = overlap_area >= epsilon

    details: Dict[str, Any] = {
        "created_bounds": item_bounds,
        "artboard_bounds": artboard_rect,
        "bounds_space": BOUNDS_SPACE_ILLUSTRATOR_Y_UP,
        "overlap_area": round(overlap_area, 2),
        "overlap_rect": overlap_rect,
    }

    return intersects, details
