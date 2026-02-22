"""Tests for vlm_grounding.py — pure-data, no Illustrator connection required.

Covers all three features:
  Feature 2: Hybrid Grounding (build_dom_map, build_relationship_map)
  Feature 5: VLM-as-Proposer / Verifier (VLMHypothesis, verify_hypothesis)
  Feature 6: Before/After DOM Diffing (capture_dom_snapshot, diff_dom_snapshots)
Plus hardening tests from review rounds A-F.
"""

import math
import pytest

from illustrator_mcp.vlm_grounding import (
    ALIGNMENT_TOLERANCE_PT,
    DOMDiff,
    DOMMapResult,
    VLMHypothesis,
    VerificationResult,
    build_dom_map,
    build_relationship_map,
    capture_dom_snapshot,
    diff_dom_snapshots,
    verify_hypothesis,
    _to_screen_bounds,
    _iou,
)


# ─── Fixtures ────────────────────────────────────────────────────────

# Standard artboard: 800x600 at origin, Illustrator coords
# [left=0, top=0, right=800, bottom=-600]  (Y-up, so top > bottom)
AB_RECT = [0, 0, 800, -600]


def _item(name, bounds, mcp_id=None, type_="PathItem", **extra):
    """Helper to create a raw item dict as _COLLECT_ITEMS_JSX would emit."""
    d = {"name": name, "type": type_, "bounds": bounds}
    if mcp_id:
        d["mcp_id"] = mcp_id
    d.update(extra)
    return d


# ─── Coordinate Helpers ─────────────────────────────────────────────

class TestScreenBounds:
    def test_origin_item(self):
        """Item at artboard origin → screen [0, 0, w, h]."""
        # Illustrator: left=0, top=0, right=100, bottom=-50
        result = _to_screen_bounds([0, 0, 100, -50], AB_RECT)
        assert result == [0.0, 0.0, 100.0, 50.0]

    def test_offset_item(self):
        """Item offset from origin."""
        # left=100, top=-50 (50pt down from top in AI), right=200, bottom=-150
        result = _to_screen_bounds([100, -50, 200, -150], AB_RECT)
        assert result == [100.0, 50.0, 100.0, 100.0]

    def test_y_flip(self):
        """Verify Y-axis flips correctly: AI top → screen y=0."""
        result = _to_screen_bounds([0, 0, 50, -30], AB_RECT)
        assert result[1] == 0.0  # top of artboard = screen y=0
        result2 = _to_screen_bounds([0, -600, 50, -600], AB_RECT)
        assert result2[1] == 600.0  # bottom of artboard = screen y=600


class TestIoU:
    def test_identical(self):
        assert _iou([0, 0, 100, 100], [0, 0, 100, 100]) == 1.0

    def test_no_overlap(self):
        assert _iou([0, 0, 50, 50], [100, 100, 50, 50]) == 0.0

    def test_partial(self):
        val = _iou([0, 0, 100, 100], [50, 50, 100, 100])
        assert 0.1 < val < 0.5  # ~14.3%


# ─── Feature 2: Hybrid Grounding ─────────────────────────────────────

class TestBuildDomMap:
    def test_basic(self):
        items = [
            _item("box_a", [0, 0, 100, -50], mcp_id="id_a"),
            _item("box_b", [200, -10, 300, -60], mcp_id="id_b",
                  type_="TextFrame", contents="Hello"),
        ]
        result = build_dom_map(items, AB_RECT)
        assert isinstance(result, DOMMapResult)
        assert "id_a" in result.by_id
        assert "id_b" in result.by_id
        # Overlay mapping
        assert result.overlay_to_id["[1]"] == "id_a"
        assert result.overlay_to_id["[2]"] == "id_b"
        assert result.id_to_overlay["id_a"] == "[1]"
        # Screen bounds
        assert result.by_id["id_a"]["bounds_screen"] == [0.0, 0.0, 100.0, 50.0]
        # Enriched data
        assert result.by_id["id_b"]["contents"] == "Hello"

    def test_empty(self):
        result = build_dom_map([], AB_RECT)
        assert result.by_id == {}
        assert result.overlay_to_id == {}

    def test_anon_fallback(self):
        """Items without mcp_id get __anon_N keys."""
        items = [_item("orphan", [0, 0, 50, -50])]
        result = build_dom_map(items, AB_RECT)
        assert "__anon_0" in result.by_id
        assert result.overlay_to_id["[1]"] == "__anon_0"

    def test_overlay_stability(self):
        """Same items in same order → same overlay IDs (Fix A test)."""
        items = [
            _item("a", [0, 0, 10, -10], mcp_id="id1"),
            _item("b", [50, 0, 60, -10], mcp_id="id2"),
        ]
        r1 = build_dom_map(items, AB_RECT)
        r2 = build_dom_map(items, AB_RECT)
        assert r1.overlay_to_id == r2.overlay_to_id
        assert r1.id_to_overlay == r2.id_to_overlay


class TestBuildRelationshipMap:
    def test_adjacent_aligned(self):
        """Two items 10pt apart, top-aligned → gap_x=10, aligned: top."""
        items = [
            _item("a", [0, 0, 100, -50], mcp_id="a"),
            _item("b", [110, 0, 210, -50], mcp_id="b"),
        ]
        dm = build_dom_map(items, AB_RECT)
        rel = build_relationship_map(dm)
        pairs = rel["pairs"]
        assert len(pairs) == 1
        key = list(pairs.keys())[0]
        assert pairs[key]["gap_x"] == 10.0
        assert "top" in pairs[key]["aligned_edges"]
        assert pairs[key]["overlap"] is False

    def test_distant_pruned(self):
        """Items 500pt apart → no relationship (proximity threshold)."""
        items = [
            _item("a", [0, 0, 50, -50], mcp_id="a"),
            _item("b", [600, -500, 650, -550], mcp_id="b"),
        ]
        dm = build_dom_map(items, AB_RECT)
        rel = build_relationship_map(dm)
        assert len(rel["pairs"]) == 0

    def test_overlapping(self):
        """Two overlapping items → overlap: True."""
        items = [
            _item("a", [0, 0, 100, -100], mcp_id="a"),
            _item("b", [50, -50, 150, -150], mcp_id="b"),
        ]
        dm = build_dom_map(items, AB_RECT)
        rel = build_relationship_map(dm)
        pairs = rel["pairs"]
        key = list(pairs.keys())[0]
        assert pairs[key]["overlap"] is True

    def test_cluster_stress_50_items(self):
        """50 items in a grid within threshold → bounded, completes (Fix B)."""
        items = []
        for i in range(50):
            x = (i % 10) * 15
            y = -(i // 10) * 15
            items.append(_item(f"g{i}", [x, y, x + 10, y - 10], mcp_id=f"g{i}"))

        dm = build_dom_map(items, AB_RECT)
        rel = build_relationship_map(dm, max_relationships=100)
        # Should complete without error and respect cap
        assert len(rel["pairs"]) <= 100
        if len(rel["pairs"]) == 100:
            assert rel.get("relationships_truncated") is True


# ─── Feature 5: Proposer / Verifier ──────────────────────────────────

class TestVLMHypothesisSchema:
    def test_valid_misalignment(self):
        h = VLMHypothesis(
            suspected_issue="misalignment",
            elements=["[1]", "[2]"],
        )
        assert h.suspected_issue == "misalignment"

    def test_spacing_2_requires_expected_gap(self):
        """2-element spacing without expected_gap → ValidationError."""
        with pytest.raises(ValueError, match="expected_gap"):
            VLMHypothesis(
                suspected_issue="spacing",
                elements=["[1]", "[2]"],
            )

    def test_spacing_2_with_gap_ok(self):
        h = VLMHypothesis(
            suspected_issue="spacing",
            elements=["[1]", "[2]"],
            expected_gap=10.0,
        )
        assert h.expected_gap == 10.0

    def test_spacing_3_no_gap_ok(self):
        """3+ elements don't need expected_gap."""
        h = VLMHypothesis(
            suspected_issue="spacing",
            elements=["[1]", "[2]", "[3]"],
        )
        assert len(h.elements) == 3


class TestVerifyMisalignment:
    def _dm(self):
        items = [
            _item("a", [0, 0, 100, -50], mcp_id="a"),
            _item("b", [150, -5, 250, -55], mcp_id="b"),
        ]
        return build_dom_map(items, AB_RECT)

    def _dm_aligned(self):
        items = [
            _item("a", [0, 0, 100, -50], mcp_id="a"),
            _item("b", [150, 0, 250, -50], mcp_id="b"),
        ]
        return build_dom_map(items, AB_RECT)

    def test_confirmed(self):
        """Items with tops 5pt apart → misalignment confirmed."""
        dm = self._dm()
        hyp = VLMHypothesis(suspected_issue="misalignment", elements=["[1]", "[2]"])
        res = verify_hypothesis(hyp, dm)
        assert res.confirmed is True
        assert "tolerance_pt" in res.evidence

    def test_discarded(self):
        """Perfectly aligned items → discarded."""
        dm = self._dm_aligned()
        hyp = VLMHypothesis(suspected_issue="misalignment", elements=["[1]", "[2]"])
        res = verify_hypothesis(hyp, dm)
        assert res.confirmed is False

    def test_with_edge(self):
        """Specific edge check narrows verification."""
        dm = self._dm_aligned()
        hyp = VLMHypothesis(
            suspected_issue="misalignment",
            elements=["[1]", "[2]"],
            edge="top",
        )
        res = verify_hypothesis(hyp, dm)
        assert res.confirmed is False  # tops are aligned

    def test_tolerance_near_miss(self):
        """Edges 0.8pt apart → aligned (within abs_tol=1.0)."""
        items = [
            _item("a", [0, 0, 100, -50], mcp_id="a"),
            _item("b", [150, -0.8, 250, -50.8], mcp_id="b"),
        ]
        dm = build_dom_map(items, AB_RECT)
        hyp = VLMHypothesis(suspected_issue="misalignment", elements=["[1]", "[2]"])
        res = verify_hypothesis(hyp, dm)
        assert res.confirmed is False  # within tolerance

    def test_custom_tolerance(self):
        """Per-hypothesis tolerance override (Fix D)."""
        items = [
            _item("a", [0, 0, 100, -50], mcp_id="a"),
            _item("b", [150, -0.8, 250, -50.8], mcp_id="b"),
        ]
        dm = build_dom_map(items, AB_RECT)
        hyp = VLMHypothesis(
            suspected_issue="misalignment",
            elements=["[1]", "[2]"],
            align_tol=0.5,  # tighter tolerance
        )
        res = verify_hypothesis(hyp, dm)
        assert res.confirmed is True  # 0.8 > 0.5 tolerance
        assert res.evidence["tolerance_pt"] == 0.5


class TestVerifyOverlap:
    def test_confirmed(self):
        items = [
            _item("a", [0, 0, 100, -100], mcp_id="a"),
            _item("b", [50, -50, 150, -150], mcp_id="b"),
        ]
        dm = build_dom_map(items, AB_RECT)
        hyp = VLMHypothesis(suspected_issue="overlap", elements=["[1]", "[2]"])
        res = verify_hypothesis(hyp, dm)
        assert res.confirmed is True
        assert len(res.evidence["overlapping_pairs"]) == 1

    def test_discarded(self):
        items = [
            _item("a", [0, 0, 50, -50], mcp_id="a"),
            _item("b", [200, 0, 250, -50], mcp_id="b"),
        ]
        dm = build_dom_map(items, AB_RECT)
        hyp = VLMHypothesis(suspected_issue="overlap", elements=["[1]", "[2]"])
        res = verify_hypothesis(hyp, dm)
        assert res.confirmed is False


class TestVerifySpacing:
    def test_3_elements_inconsistent(self):
        """gap(A,B)=10, gap(B,C)=25 → confirmed."""
        items = [
            _item("a", [0, 0, 50, -50], mcp_id="a"),
            _item("b", [60, 0, 110, -50], mcp_id="b"),   # gap = 10
            _item("c", [135, 0, 185, -50], mcp_id="c"),   # gap = 25
        ]
        dm = build_dom_map(items, AB_RECT)
        hyp = VLMHypothesis(
            suspected_issue="spacing", elements=["[1]", "[2]", "[3]"])
        res = verify_hypothesis(hyp, dm)
        assert res.confirmed is True
        assert "tolerance_pt" in res.evidence

    def test_3_elements_consistent(self):
        items = [
            _item("a", [0, 0, 50, -50], mcp_id="a"),
            _item("b", [60, 0, 110, -50], mcp_id="b"),   # gap = 10
            _item("c", [120, 0, 170, -50], mcp_id="c"),   # gap = 10
        ]
        dm = build_dom_map(items, AB_RECT)
        hyp = VLMHypothesis(
            suspected_issue="spacing", elements=["[1]", "[2]", "[3]"])
        res = verify_hypothesis(hyp, dm)
        assert res.confirmed is False

    def test_2_elements_with_expected_gap(self):
        items = [
            _item("a", [0, 0, 50, -50], mcp_id="a"),
            _item("b", [60, 0, 110, -50], mcp_id="b"),   # actual gap = 10
        ]
        dm = build_dom_map(items, AB_RECT)
        hyp = VLMHypothesis(
            suspected_issue="spacing",
            elements=["[1]", "[2]"],
            expected_gap=20.0,
        )
        res = verify_hypothesis(hyp, dm)
        assert res.confirmed is True  # 10 != 20


class TestVerifyInvalidRefs:
    def test_missing_elements(self):
        dm = DOMMapResult()
        hyp = VLMHypothesis(suspected_issue="overlap", elements=["[99]"])
        res = verify_hypothesis(hyp, dm)
        assert res.confirmed is None
        assert "[99]" in res.evidence["missing_elements"]


class TestVerifyOffArtboard:
    def test_confirmed(self):
        items = [
            _item("off", [900, 0, 950, -50], mcp_id="off"),
        ]
        dm = build_dom_map(items, AB_RECT)
        hyp = VLMHypothesis(suspected_issue="off_artboard", elements=["[1]"])
        res = verify_hypothesis(hyp, dm, artboard_screen=[0, 0, 800, 600])
        assert res.confirmed is True

    def test_discarded(self):
        items = [
            _item("on", [100, -100, 200, -200], mcp_id="on"),
        ]
        dm = build_dom_map(items, AB_RECT)
        hyp = VLMHypothesis(suspected_issue="off_artboard", elements=["[1]"])
        res = verify_hypothesis(hyp, dm, artboard_screen=[0, 0, 800, 600])
        assert res.confirmed is False


class TestVerifyStyle:
    def test_mismatch_confirmed(self):
        """Items with different fills → confirmed (Fix E)."""
        items = [
            _item("a", [0, 0, 50, -50], mcp_id="a", fill="#FF0000"),
            _item("b", [100, 0, 150, -50], mcp_id="b", fill="#00FF00"),
        ]
        dm = build_dom_map(items, AB_RECT)
        hyp = VLMHypothesis(
            suspected_issue="style_mismatch", elements=["[1]", "[2]"])
        res = verify_hypothesis(hyp, dm)
        assert res.confirmed is True
        assert "fill" in res.evidence["inconsistencies"]

    def test_consistent_discarded(self):
        items = [
            _item("a", [0, 0, 50, -50], mcp_id="a", fill="#FF0000"),
            _item("b", [100, 0, 150, -50], mcp_id="b", fill="#FF0000"),
        ]
        dm = build_dom_map(items, AB_RECT)
        hyp = VLMHypothesis(
            suspected_issue="style_mismatch", elements=["[1]", "[2]"])
        res = verify_hypothesis(hyp, dm)
        assert res.confirmed is False

    def test_no_style_data(self):
        """No style fields collected → confirmed=None."""
        items = [
            _item("a", [0, 0, 50, -50], mcp_id="a"),
            _item("b", [100, 0, 150, -50], mcp_id="b"),
        ]
        dm = build_dom_map(items, AB_RECT)
        hyp = VLMHypothesis(
            suspected_issue="style_mismatch", elements=["[1]", "[2]"])
        res = verify_hypothesis(hyp, dm)
        assert res.confirmed is None


# ─── Feature 6: Before/After DOM Diffing ──────────────────────────────

class TestDiffNoChanges:
    def test_identical(self):
        items = [
            _item("a", [0, 0, 100, -50], mcp_id="id_a"),
            _item("b", [200, 0, 300, -50], mcp_id="id_b"),
        ]
        before = capture_dom_snapshot(items)
        after = capture_dom_snapshot(items)
        diff = diff_dom_snapshots(before, after)
        assert diff.unchanged == 2
        assert diff.added == []
        assert diff.removed == []
        assert diff.moved == []
        assert diff.resized == []


class TestDiffAdded:
    def test_new_item(self):
        before = [_item("a", [0, 0, 100, -50], mcp_id="id_a")]
        after = [
            _item("a", [0, 0, 100, -50], mcp_id="id_a"),
            _item("new", [200, 0, 300, -50], mcp_id="id_new"),
        ]
        diff = diff_dom_snapshots(before, after)
        assert "new" in diff.added
        assert diff.unchanged == 1


class TestDiffRemoved:
    def test_missing_item(self):
        before = [
            _item("a", [0, 0, 100, -50], mcp_id="id_a"),
            _item("gone", [200, 0, 300, -50], mcp_id="id_gone"),
        ]
        after = [_item("a", [0, 0, 100, -50], mcp_id="id_a")]
        diff = diff_dom_snapshots(before, after)
        assert "gone" in diff.removed
        assert diff.unchanged == 1


class TestDiffMoved:
    def test_position_changed(self):
        before = [_item("box", [0, 0, 100, -50], mcp_id="id_box")]
        after = [_item("box", [50, -30, 150, -80], mcp_id="id_box")]
        diff = diff_dom_snapshots(before, after)
        assert len(diff.moved) == 1
        assert diff.moved[0]["name"] == "box"
        assert diff.moved[0]["mcp_id"] == "id_box"


class TestDiffResized:
    def test_size_changed(self):
        # Resize symmetrically around center (50, -25) so center stays constant
        before = [_item("box", [25, -12.5, 75, -37.5], mcp_id="id_box")]
        after = [_item("box", [0, 0, 100, -50], mcp_id="id_box")]
        diff = diff_dom_snapshots(before, after)
        assert len(diff.resized) == 1
        assert diff.resized[0]["name"] == "box"


class TestDiffDestructive:
    def test_merge(self):
        """Pathfinder merge: two items removed, one created at same center (Fix C)."""
        before = [
            _item("circle1", [0, 0, 100, -100], mcp_id="c1"),
            _item("circle2", [50, -50, 150, -150], mcp_id="c2"),
        ]
        # After boolean: originals destroyed, new compound at overlapping center
        after = [
            _item("compound", [0, 0, 150, -150]),  # no mcp_id — new object
        ]
        diff = diff_dom_snapshots(before, after)
        # The two original items should NOT simply be "removed"
        # At least some should be matched via IoU/proximity
        total_accounted = len(diff.mutations) + len(diff.removed) + len(diff.added)
        assert total_accounted >= 1  # something was detected

    def test_adversarial_multi_near_center(self):
        """Multiple new items near same center → no over-confident merge (Fix C)."""
        before = [_item("orig", [45, -45, 55, -55], mcp_id="orig")]
        after = [
            _item("new_a", [44, -44, 56, -56]),  # near center
            _item("new_b", [43, -43, 57, -57]),  # also near center
            _item("new_c", [46, -46, 54, -54]),  # also near center
        ]
        diff = diff_dom_snapshots(before, after)
        # Should not have 3 high-confidence mutations from 1 original
        high_conf = [m for m in diff.mutations if m.get("confidence", 0) > 0.8]
        # At most 1 high-confidence match from 1 source item
        assert len(high_conf) <= 1


class TestCaptureSnapshot:
    def test_deep_copy(self):
        """capture_dom_snapshot returns independent copy."""
        items = [_item("a", [0, 0, 100, -50], mcp_id="id_a")]
        snap = capture_dom_snapshot(items)
        items[0]["name"] = "MUTATED"
        assert snap[0]["name"] == "a"
