"""
VLM Grounding Module — Hybrid DOM metadata, hypothesis verification, and DOM diffing.

Provides the infrastructure for three VLM QA pipeline features:
  Feature 2: Hybrid Grounding (build_dom_map, build_relationship_map)
  Feature 5: VLM-as-Proposer / ExtendScript-as-Verifier (VLMHypothesis, verify_hypothesis)
  Feature 6: Before/After DOM Diffing (capture_dom_snapshot, diff_dom_snapshots)

Design decisions from two review rounds:
  - mcp_id is the primary key everywhere; overlay IDs are a view layer (Fix A)
  - Spatial binning for O(n) relationship generation (Fix B)
  - IoU + confidence scoring for destructive-op matching (Fix C)
  - Tolerance emitted in evidence; per-hypothesis override via align_tol (Fix D)
  - Basic style verification for collected fields (Fix E)
  - All bounds are screen-space Y-down [x, y, w, h] (Fix #2)
  - visibleBounds only (Fix #1)
"""

from __future__ import annotations

import copy
import math
from collections import defaultdict
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator


# ==================== Constants ====================

PROXIMITY_THRESHOLD_PT: float = 200.0
ALIGNMENT_TOLERANCE_PT: float = 1.0
DESTRUCTIVE_MATCH_RADIUS_PT: float = 5.0
MAX_RELATIONSHIPS: int = 2000
MAX_ITEMS_COLLECTED: int = 300


# ==================== Coordinate Helpers ====================

def _to_screen_bounds(
    bounds_pt: List[float],
    artboard_rect: List[float],
) -> List[float]:
    """Convert Illustrator [left, top, right, bottom] (Y-up) to
    screen-space [x, y, width, height] (Y-down) relative to artboard origin.
    """
    ab_left, ab_top = artboard_rect[0], artboard_rect[1]
    screen_x = bounds_pt[0] - ab_left
    screen_y = ab_top - bounds_pt[1]       # flip Y
    screen_w = bounds_pt[2] - bounds_pt[0]
    screen_h = bounds_pt[1] - bounds_pt[3]  # top - bottom in AI coords
    return [round(screen_x, 2), round(screen_y, 2),
            round(screen_w, 2), round(screen_h, 2)]


def _center_of(bounds_screen: List[float]) -> Tuple[float, float]:
    """Center from screen-space [x, y, w, h]."""
    return (bounds_screen[0] + bounds_screen[2] / 2,
            bounds_screen[1] + bounds_screen[3] / 2)


def _distance(c1: Tuple[float, float], c2: Tuple[float, float]) -> float:
    return math.sqrt((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2)


def _close(a: float, b: float, tol: float = ALIGNMENT_TOLERANCE_PT) -> bool:
    return math.isclose(a, b, abs_tol=tol)


def _iou(a: List[float], b: List[float]) -> float:
    """Intersection-over-union of two screen-space bounds [x,y,w,h]."""
    ax1, ay1, aw, ah = a
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx1, by1, bw, bh = b
    bx2, by2 = bx1 + bw, by1 + bh

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0

    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = aw * ah
    area_b = bw * bh
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


# ==================== Feature 2: Hybrid Grounding ====================

class DOMMapResult(BaseModel):
    """Triple-view DOM map: primary key is mcp_id, overlay IDs are view layer."""
    by_id: Dict[str, dict] = Field(
        default_factory=dict,
        description="mcp_id → metadata dict with bounds_screen, type, name, etc."
    )
    overlay_to_id: Dict[str, str] = Field(
        default_factory=dict,
        description="'[1]' → mcp_id"
    )
    id_to_overlay: Dict[str, str] = Field(
        default_factory=dict,
        description="mcp_id → '[1]'"
    )


def build_dom_map(
    items: List[dict],
    artboard_rect: List[float],
) -> DOMMapResult:
    """Build mcp_id-keyed DOM metadata with overlay ID mappings.

    Items must already be filtered and ordered the same way they were
    annotated, so indices match overlay labels.

    Args:
        items: List of dicts from _COLLECT_ITEMS_JSX.
        artboard_rect: [left, top, right, bottom] in Illustrator coords.

    Returns:
        DOMMapResult with by_id, overlay_to_id, id_to_overlay.
    """
    result = DOMMapResult()

    for i, item in enumerate(items):
        label = f"[{i + 1}]"
        bounds_pt = item.get("bounds", [0, 0, 0, 0])
        mcp_id = (item.get("mcp_id") or "").strip()

        # Generate a fallback ID if no mcp_id
        effective_id = mcp_id or f"__anon_{i}"

        entry: Dict[str, Any] = {
            "type": item.get("type", "Item"),
            "name": item.get("name", ""),
            "bounds_screen": _to_screen_bounds(bounds_pt, artboard_rect),
            "overlay_label": label,
        }
        if mcp_id:
            entry["mcp_id"] = mcp_id

        # Enriched fields (qa mode)
        for key in ("contents", "font", "fontSize", "fill"):
            if item.get(key):
                entry[key] = item[key]

        result.by_id[effective_id] = entry
        result.overlay_to_id[label] = effective_id
        result.id_to_overlay[effective_id] = label

    return result


def build_relationship_map(
    dom_map: DOMMapResult,
    proximity_threshold: float = PROXIMITY_THRESHOLD_PT,
    max_relationships: int = MAX_RELATIONSHIPS,
) -> dict:
    """Compute pairwise spatial relationships using spatial binning.

    Uses a grid of cell_size=proximity_threshold. Only compares items
    within the same or adjacent cells (9-cell neighbourhood). Emits at
    most max_relationships pairs.

    Returns:
        Dict with "pairs" (keyed by "[i]-[j]") and optional
        "relationships_truncated" flag.
    """
    entries = list(dom_map.by_id.items())
    if len(entries) < 2:
        return {"pairs": {}}

    cell_size = max(proximity_threshold, 1.0)

    # ── Spatial binning ──
    bins: Dict[Tuple[int, int], List[Tuple[str, dict]]] = defaultdict(list)
    for mid, meta in entries:
        bs = meta["bounds_screen"]
        cx, cy = _center_of(bs)
        bx, by = int(cx // cell_size), int(cy // cell_size)
        bins[(bx, by)].append((mid, meta))

    pairs: Dict[str, dict] = {}
    truncated = False

    # ── Compare within 9-cell neighbourhood ──
    visited_cells: set = set()
    for (bx, by), cell_items in bins.items():
        neighbours: List[Tuple[str, dict]] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                key = (bx + dx, by + dy)
                if key in bins:
                    neighbours.extend(bins[key])

        for ia in range(len(cell_items)):
            mid_a, meta_a = cell_items[ia]
            a = meta_a["bounds_screen"]
            ca = _center_of(a)
            label_a = meta_a.get("overlay_label", "")

            for mid_b, meta_b in neighbours:
                if mid_b <= mid_a:  # avoid duplicates + self
                    continue
                b = meta_b["bounds_screen"]
                cb = _center_of(b)

                if _distance(ca, cb) > proximity_threshold:
                    continue

                if len(pairs) >= max_relationships:
                    truncated = True
                    break

                label_b = meta_b.get("overlay_label", "")
                pair_key = f"{label_a}-{label_b}" if label_a < label_b else f"{label_b}-{label_a}"

                if pair_key in pairs:
                    continue

                # Compute relationship
                a_left, a_top, a_w, a_h = a
                a_right, a_bottom = a_left + a_w, a_top + a_h
                b_left, b_top, b_w, b_h = b
                b_right, b_bottom = b_left + b_w, b_top + b_h

                gap_x = max(b_left - a_right, a_left - b_right)
                gap_y = max(b_top - a_bottom, a_top - b_bottom)

                overlap = not (a_right < b_left or b_right < a_left or
                               a_bottom < b_top or b_bottom < a_top)

                aligned: List[str] = []
                if _close(a_top, b_top):
                    aligned.append("top")
                if _close(a_bottom, b_bottom):
                    aligned.append("bottom")
                if _close(a_left, b_left):
                    aligned.append("left")
                if _close(a_right, b_right):
                    aligned.append("right")
                if _close(ca[0], cb[0]):
                    aligned.append("center_x")
                if _close(ca[1], cb[1]):
                    aligned.append("center_y")

                pairs[pair_key] = {
                    "gap_x": round(gap_x, 2),
                    "gap_y": round(gap_y, 2),
                    "aligned_edges": aligned,
                    "overlap": overlap,
                }

            if truncated:
                break
        if truncated:
            break

    result: Dict[str, Any] = {"pairs": pairs}
    if truncated:
        result["relationships_truncated"] = True
    return result


# ==================== Feature 5: Proposer / Verifier ====================

class VLMHypothesis(BaseModel):
    """A structured observation from the VLM about a potential design issue."""
    suspected_issue: Literal[
        "misalignment", "overlap", "spacing",
        "off_artboard", "style_mismatch",
    ]
    elements: List[str] = Field(
        ..., description="Overlay IDs like '[1]', '[2]'", min_length=1)
    detail: Optional[str] = None
    expected_gap: Optional[float] = Field(
        default=None, description="Required for spacing with <3 elements")
    edge: Optional[Literal[
        "top", "bottom", "left", "right", "center_x", "center_y"
    ]] = Field(default=None, description="Specific edge for alignment checks")
    align_tol: Optional[float] = Field(
        default=None, description="Override tolerance (pt) for this hypothesis")

    @model_validator(mode="after")
    def validate_spacing(self) -> "VLMHypothesis":
        if (self.suspected_issue == "spacing"
                and len(self.elements) < 3
                and self.expected_gap is None):
            raise ValueError(
                "spacing hypothesis with <3 elements requires expected_gap")
        return self


class VerificationResult(BaseModel):
    """Result of verifying a VLM hypothesis against DOM data."""
    confirmed: Optional[bool] = Field(
        ..., description="True=confirmed, False=discarded, None=unverifiable")
    hypothesis: VLMHypothesis
    evidence: dict = Field(default_factory=dict)
    message: str = ""


def _resolve_elements(
    hypothesis: VLMHypothesis,
    dom_map: DOMMapResult,
) -> Tuple[List[Tuple[str, dict]], List[str]]:
    """Resolve overlay IDs to DOM entries. Returns (found, missing)."""
    found: List[Tuple[str, dict]] = []
    missing: List[str] = []
    for el in hypothesis.elements:
        mid = dom_map.overlay_to_id.get(el)
        if mid and mid in dom_map.by_id:
            found.append((el, dom_map.by_id[mid]))
        else:
            missing.append(el)
    return found, missing


def verify_hypothesis(
    hypothesis: VLMHypothesis,
    dom_map: DOMMapResult,
    artboard_screen: Optional[List[float]] = None,
) -> VerificationResult:
    """Verify a VLM hypothesis using pure-Python bounds math.

    Does NOT call Illustrator. All verification is on already-collected data.
    """
    found, missing = _resolve_elements(hypothesis, dom_map)
    if missing:
        return VerificationResult(
            confirmed=None, hypothesis=hypothesis,
            evidence={"missing_elements": missing},
            message=f"Cannot verify: elements {missing} not found in DOM map",
        )

    issue = hypothesis.suspected_issue
    tol = hypothesis.align_tol if hypothesis.align_tol is not None else ALIGNMENT_TOLERANCE_PT

    if issue == "misalignment":
        return _verify_misalignment(hypothesis, found, tol)
    elif issue == "overlap":
        return _verify_overlap(hypothesis, found)
    elif issue == "spacing":
        return _verify_spacing(hypothesis, found, tol)
    elif issue == "off_artboard":
        return _verify_off_artboard(hypothesis, found, artboard_screen)
    elif issue == "style_mismatch":
        return _verify_style(hypothesis, found)
    else:
        return VerificationResult(
            confirmed=None, hypothesis=hypothesis,
            message=f"Unknown issue type: {issue}",
        )


def _verify_misalignment(
    hyp: VLMHypothesis,
    elements: List[Tuple[str, dict]],
    tol: float,
) -> VerificationResult:
    """Check if elements have misaligned edges."""
    if len(elements) < 2:
        return VerificationResult(
            confirmed=None, hypothesis=hyp,
            message="Need ≥2 elements for misalignment check",
        )

    bs = [e[1]["bounds_screen"] for e in elements]
    names = [e[0] for e in elements]

    def _edge_val(b: List[float], edge: str) -> float:
        if edge == "left": return b[0]
        if edge == "top": return b[1]
        if edge == "right": return b[0] + b[2]
        if edge == "bottom": return b[1] + b[3]
        if edge == "center_x": return b[0] + b[2] / 2
        if edge == "center_y": return b[1] + b[3] / 2
        return 0.0

    # If a specific edge was requested, check only that one
    edges_to_check = [hyp.edge] if hyp.edge else [
        "left", "top", "right", "bottom", "center_x", "center_y"
    ]

    any_aligned = False
    misaligned: Dict[str, List[float]] = {}
    for edge_name in edges_to_check:
        ref = _edge_val(bs[0], edge_name)
        vals = [_edge_val(b, edge_name) for b in bs]
        if all(_close(ref, v, tol) for v in vals):
            any_aligned = True
        else:
            misaligned[edge_name] = [round(v, 2) for v in vals]

    confirmed = not any_aligned
    return VerificationResult(
        confirmed=confirmed, hypothesis=hyp,
        evidence={
            "elements": names,
            "misaligned_edges": misaligned if confirmed else {},
            "any_edge_aligned": any_aligned,
            "tolerance_pt": tol,
        },
        message=(
            f"Misalignment confirmed: no shared edge alignment within {tol}pt"
            if confirmed else
            "Discarded: elements share at least one aligned edge"
        ),
    )


def _verify_overlap(
    hyp: VLMHypothesis,
    elements: List[Tuple[str, dict]],
) -> VerificationResult:
    if len(elements) < 2:
        return VerificationResult(
            confirmed=None, hypothesis=hyp,
            message="Need ≥2 elements for overlap check",
        )

    pairs: List[List[str]] = []
    for i in range(len(elements)):
        for j in range(i + 1, len(elements)):
            a = elements[i][1]["bounds_screen"]
            b = elements[j][1]["bounds_screen"]
            ar, ab_ = a[0] + a[2], a[1] + a[3]
            br, bb_ = b[0] + b[2], b[1] + b[3]
            if not (ar < b[0] or br < a[0] or ab_ < b[1] or bb_ < a[1]):
                pairs.append([elements[i][0], elements[j][0]])

    confirmed = len(pairs) > 0
    return VerificationResult(
        confirmed=confirmed, hypothesis=hyp,
        evidence={"overlapping_pairs": pairs},
        message=(f"Overlap confirmed: {len(pairs)} pair(s)"
                 if confirmed else "Discarded: no overlapping bounds"),
    )


def _verify_spacing(
    hyp: VLMHypothesis,
    elements: List[Tuple[str, dict]],
    tol: float,
) -> VerificationResult:
    sorted_elems = sorted(elements, key=lambda e: e[1]["bounds_screen"][0])
    names = [e[0] for e in sorted_elems]
    bs = [e[1]["bounds_screen"] for e in sorted_elems]

    gaps = []
    for k in range(len(bs) - 1):
        right_k = bs[k][0] + bs[k][2]
        left_next = bs[k + 1][0]
        gaps.append(round(left_next - right_k, 2))

    if len(elements) >= 3:
        ref_gap = gaps[0]
        inconsistent = [(i, g) for i, g in enumerate(gaps) if not _close(g, ref_gap, tol)]
        confirmed = len(inconsistent) > 0
        return VerificationResult(
            confirmed=confirmed, hypothesis=hyp,
            evidence={"elements": names, "gaps": gaps,
                      "reference_gap": ref_gap, "tolerance_pt": tol},
            message=(f"Spacing inconsistency: gaps={gaps}" if confirmed
                     else f"Discarded: gaps consistent ({gaps})"),
        )
    else:
        actual_gap = gaps[0]
        expected = hyp.expected_gap
        confirmed = not _close(actual_gap, expected, tol)  # type: ignore
        return VerificationResult(
            confirmed=confirmed, hypothesis=hyp,
            evidence={"elements": names, "actual_gap": actual_gap,
                      "expected_gap": expected, "tolerance_pt": tol},
            message=(f"Spacing mismatch: actual={actual_gap}, expected={expected}"
                     if confirmed
                     else f"Discarded: gap ({actual_gap}) matches expected ({expected})"),
        )


def _verify_off_artboard(
    hyp: VLMHypothesis,
    elements: List[Tuple[str, dict]],
    artboard_screen: Optional[List[float]],
) -> VerificationResult:
    if not artboard_screen:
        return VerificationResult(
            confirmed=None, hypothesis=hyp,
            message="Cannot verify: artboard bounds not provided",
        )

    ab_w, ab_h = artboard_screen[2], artboard_screen[3]
    off_items = []
    for name, meta in elements:
        b = meta["bounds_screen"]
        cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
        if cx < 0 or cx > ab_w or cy < 0 or cy > ab_h:
            off_items.append(name)

    confirmed = len(off_items) > 0
    return VerificationResult(
        confirmed=confirmed, hypothesis=hyp,
        evidence={"off_artboard_items": off_items, "artboard_size": [ab_w, ab_h]},
        message=(f"Off-artboard confirmed: {off_items}" if confirmed
                 else "Discarded: all within artboard"),
    )


def _verify_style(
    hyp: VLMHypothesis,
    elements: List[Tuple[str, dict]],
) -> VerificationResult:
    """Basic style verification for collected fields (Fix E).

    Verifies consistency of fill, font, fontSize across elements.
    Returns confirmed=None only for uncollected/complex style claims.
    """
    if len(elements) < 2:
        return VerificationResult(
            confirmed=None, hypothesis=hyp,
            message="Need ≥2 elements for style comparison",
        )

    # Collect style fields that are actually present
    style_fields = ("fill", "font", "fontSize")
    inconsistencies: Dict[str, List] = {}
    any_field_checked = False

    for field in style_fields:
        values = []
        for name, meta in elements:
            val = meta.get(field)
            if val is not None:
                values.append((name, val))

        if len(values) < 2:
            continue  # Not enough data for this field

        any_field_checked = True
        ref_val = values[0][1]
        mismatches = [(n, v) for n, v in values if v != ref_val]
        if mismatches:
            inconsistencies[field] = [
                {"element": n, "value": v} for n, v in values
            ]

    if not any_field_checked:
        return VerificationResult(
            confirmed=None, hypothesis=hyp,
            evidence={"reason": "no style data collected for these elements"},
            message="style_mismatch unverifiable: no style fields available",
        )

    confirmed = len(inconsistencies) > 0
    return VerificationResult(
        confirmed=confirmed, hypothesis=hyp,
        evidence={"inconsistencies": inconsistencies},
        message=(f"Style mismatch confirmed: {list(inconsistencies.keys())}"
                 if confirmed
                 else "Discarded: checked style fields are consistent"),
    )


# ==================== Feature 6: Before/After DOM Diffing ====================

class DOMDiff(BaseModel):
    """Structural diff between two DOM snapshots."""
    added: List[str] = Field(default_factory=list)
    removed: List[str] = Field(default_factory=list)
    moved: List[dict] = Field(default_factory=list)
    resized: List[dict] = Field(default_factory=list)
    mutations: List[dict] = Field(default_factory=list)
    unchanged: int = 0


def capture_dom_snapshot(items: List[dict]) -> List[dict]:
    """Deep-copy items list for later diffing."""
    return copy.deepcopy(items)


def diff_dom_snapshots(
    before: List[dict],
    after: List[dict],
    move_threshold: float = ALIGNMENT_TOLERANCE_PT,
    destructive_radius: float = DESTRUCTIVE_MATCH_RADIUS_PT,
) -> DOMDiff:
    """Compute structural diff with two-pass matching.

    Pass 1: Match by mcp_id (stable for non-destructive ops).
    Pass 2: Score unmatched by IoU + center proximity + size ratio (Fix C).
            Accept only if score > 0.5. Emit confidence per mutation.
    """
    def _key(item: dict) -> str:
        return (item.get("mcp_id") or "").strip()

    def _center(item: dict) -> Tuple[float, float]:
        b = item.get("bounds", [0, 0, 0, 0])
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    def _size(item: dict) -> Tuple[float, float]:
        b = item.get("bounds", [0, 0, 0, 0])
        return (abs(b[2] - b[0]), abs(b[1] - b[3]))

    def _screen(item: dict) -> List[float]:
        """Raw bounds as [x, y, w, h] for IoU (Illustrator coords, approximate)."""
        b = item.get("bounds", [0, 0, 0, 0])
        return [b[0], b[3], abs(b[2] - b[0]), abs(b[1] - b[3])]

    # Index by mcp_id
    before_by_id: Dict[str, dict] = {}
    before_nokey: List[dict] = []
    for item in before:
        k = _key(item)
        if k:
            before_by_id[k] = item
        else:
            before_nokey.append(item)

    after_by_id: Dict[str, dict] = {}
    after_nokey: List[dict] = []
    for item in after:
        k = _key(item)
        if k:
            after_by_id[k] = item
        else:
            after_nokey.append(item)

    diff = DOMDiff()
    matched_b: set = set()
    matched_a: set = set()

    # ── Pass 1: mcp_id matching ──
    for mid, b_item in before_by_id.items():
        if mid in after_by_id:
            a_item = after_by_id[mid]
            matched_b.add(mid)
            matched_a.add(mid)

            bc, ac = _center(b_item), _center(a_item)
            bs, as_ = _size(b_item), _size(a_item)
            name = b_item.get("name") or a_item.get("name") or mid[:8]

            pos_changed = not (_close(bc[0], ac[0], move_threshold)
                               and _close(bc[1], ac[1], move_threshold))
            size_changed = not (_close(bs[0], as_[0], move_threshold)
                                and _close(bs[1], as_[1], move_threshold))

            if pos_changed:
                diff.moved.append({
                    "name": name, "mcp_id": mid,
                    "from": b_item.get("bounds", []),
                    "to": a_item.get("bounds", []),
                    "delta": [round(ac[0] - bc[0], 2), round(ac[1] - bc[1], 2)],
                })
            elif size_changed:
                diff.resized.append({
                    "name": name, "mcp_id": mid,
                    "from_size": [round(bs[0], 2), round(bs[1], 2)],
                    "to_size": [round(as_[0], 2), round(as_[1], 2)],
                })
            else:
                diff.unchanged += 1

    # Gather unmatched
    unmatched_b = [b for mid, b in before_by_id.items()
                   if mid not in matched_b] + before_nokey
    unmatched_a = [a for mid, a in after_by_id.items()
                   if mid not in matched_a] + after_nokey

    # ── Pass 2: IoU + center + size scoring (Fix C) ──
    p2_matched_a: set = set()
    p2_matched_b: set = set()

    for ai, a_item in enumerate(unmatched_a):
        if ai in p2_matched_a:
            continue
        a_center = _center(a_item)
        a_scr = _screen(a_item)
        a_area = a_scr[2] * a_scr[3] if a_scr[2] * a_scr[3] > 0 else 1.0

        best_score = 0.0
        best_bis: List[int] = []

        for bi, b_item in enumerate(unmatched_b):
            if bi in p2_matched_b:
                continue
            b_center = _center(b_item)
            dist = _distance(a_center, b_center)
            if dist > destructive_radius:
                continue

            b_scr = _screen(b_item)
            iou_val = _iou(a_scr, b_scr)
            b_area = b_scr[2] * b_scr[3] if b_scr[2] * b_scr[3] > 0 else 1.0
            size_ratio = min(a_area, b_area) / max(a_area, b_area)

            # Composite score
            dist_score = max(0, 1 - dist / destructive_radius) if destructive_radius > 0 else 1.0
            score = 0.4 * dist_score + 0.4 * iou_val + 0.2 * size_ratio

            if score > 0.5:
                best_bis.append(bi)
                best_score = max(best_score, score)

        if best_bis:
            from_names = [unmatched_b[bi].get("name", f"item_{bi}")
                          for bi in best_bis]
            diff.mutations.append({
                "type": "merge" if len(best_bis) > 1 else "replace",
                "from": from_names,
                "to": a_item.get("name", ""),
                "confidence": round(best_score, 3),
                "center_delta": [
                    round(a_center[0] - _center(unmatched_b[best_bis[0]])[0], 2),
                    round(a_center[1] - _center(unmatched_b[best_bis[0]])[1], 2),
                ],
            })
            for bi in best_bis:
                p2_matched_b.add(bi)
            p2_matched_a.add(ai)

    # Remaining → added / removed
    for bi, b_item in enumerate(unmatched_b):
        if bi not in p2_matched_b:
            diff.removed.append(
                b_item.get("name") or b_item.get("type", "unknown"))

    for ai, a_item in enumerate(unmatched_a):
        if ai not in p2_matched_a:
            diff.added.append(
                a_item.get("name") or a_item.get("type", "unknown"))

    return diff
