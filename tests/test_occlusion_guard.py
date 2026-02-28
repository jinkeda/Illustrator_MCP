"""
Tests for the OcclusionGuard module.

Static tests — no live Illustrator required.
"""

import pytest
from illustrator_mcp.occlusion_guard import (
    check_occlusion,
    format_abort_message,
    OcclusionResult,
    OcclusionFinding,
    _intersection_area,
    _artboard_area,
    COVER_THRESHOLD,
    OPACITY_THRESHOLD,
    DEFAULT_BG_LAYER_NAMES,
)


# ── Fixtures ─────────────────────────────────────────────────────────

# Standard artboard: 800x400, Y-up (top=0, bottom=-400)
AB_RECT = [0, 0, 800, -400]

def _make_layers(*specs):
    """Quick layer builder: (name, visible, locked, itemCount)."""
    return [
        {"name": n, "index": i, "visible": v, "locked": lk, "itemCount": ic}
        for i, (n, v, lk, ic) in enumerate(specs)
    ]

def _make_item(name="item", typename="PathItem", layer="Layer 1", layerIndex=0,
               opacity=100, filled=True, stroked=False, blend="Normal",
               clipped=False, bounds=None, coverRatio=None, mcpId=None):
    """Quick item builder."""
    if bounds is None:
        bounds = [0, 0, 100, -100]  # 100x100 small item
    return {
        "name": name, "typename": typename, "layerName": layer,
        "layerIndex": layerIndex, "opacity": opacity, "filled": filled,
        "stroked": stroked, "blendingMode": blend, "clipped": clipped,
        "bounds": bounds, "coverRatio": coverRatio, "mcpId": mcpId,
    }


# ── Test A: Sky topmost + 99% cover ─────────────────────────────────

def test_sky_topmost_with_full_cover():
    """Q003 + Q001: Sky layer topmost AND item covers 99%."""
    layers = _make_layers(
        ("Sky", True, False, 1),
        ("Body", True, False, 3),
    )
    items = [
        _make_item("sky_bg", bounds=[0, 0, 800, -400], coverRatio=0.99,
                    layer="Sky", layerIndex=0),
    ]
    result = check_occlusion(layers, items, AB_RECT, total_item_count=5)

    assert not result.ok
    codes = [f.code for f in result.findings]
    assert "Q003" in codes, "Should detect bg layer on top"
    assert "Q001" in codes, "Should detect full cover"
    assert all(f.severity == "abort" for f in result.findings if f.code in ("Q001", "Q003"))
    assert len(result.suggested_fix) > 0


# ── Test B: Correct order ────────────────────────────────────────────

def test_correct_order():
    """Sky at bottom — should pass."""
    layers = _make_layers(
        ("Windows", True, False, 2),
        ("Body", True, False, 3),
        ("Sky", True, False, 1),
    )
    items = [
        _make_item("fuselage", bounds=[100, -50, 700, -350], coverRatio=0.35,
                    layer="Windows", layerIndex=0),
    ]
    result = check_occlusion(layers, items, AB_RECT, total_item_count=6)

    assert result.ok
    assert len(result.findings) == 0


# ── Test C: Single item bypass ───────────────────────────────────────

def test_single_item_bypass():
    """Only 1 item in document — nothing to occlude."""
    layers = _make_layers(("Sky", True, False, 1))
    items = [
        _make_item("sky_bg", bounds=[0, 0, 800, -400], coverRatio=0.99,
                    layer="Sky", layerIndex=0),
    ]
    result = check_occlusion(layers, items, AB_RECT, total_item_count=1)

    assert result.ok
    assert result.diagnostics.get("bypass") == "single_item"


# ── Test D: GroupItem large bbox (skip) ──────────────────────────────

def test_group_item_large_bbox_skipped():
    """Plain GroupItem with large bbox — should be skipped."""
    layers = _make_layers(("Layer 1", True, False, 2))
    items = [
        _make_item("big_group", typename="GroupItem",
                    bounds=[0, 0, 800, -400], coverRatio=0.99,
                    filled=False, clipped=False),
    ]
    result = check_occlusion(layers, items, AB_RECT, total_item_count=5)

    assert result.ok


# ── Test E: Multiply blend full cover → Q004 warn ────────────────────

def test_nonnormal_blend_cover_warns():
    """Multiply blend at full cover → Q004 warn, still ok."""
    layers = _make_layers(("Tint", True, False, 1), ("Body", True, False, 3))
    items = [
        _make_item("tint_overlay", bounds=[0, 0, 800, -400], coverRatio=0.95,
                    blend="Multiply", opacity=100, layer="Tint", layerIndex=0),
    ]
    result = check_occlusion(layers, items, AB_RECT, total_item_count=5)

    assert result.ok  # warn doesn't block
    assert len(result.findings) == 1
    assert result.findings[0].code == "Q004"
    assert result.findings[0].severity == "warn"


# ── Test F: 85% cover (below threshold) ──────────────────────────────

def test_below_cover_threshold():
    """Item covers 85% — below 90% threshold."""
    layers = _make_layers(("Layer 1", True, False, 2))
    items = [
        _make_item("big_rect", bounds=[0, 0, 680, -400], coverRatio=0.85),
    ]
    result = check_occlusion(layers, items, AB_RECT, total_item_count=3)

    assert result.ok
    assert len(result.findings) == 0


# ── Test G: Wireframe (no fill) ──────────────────────────────────────

def test_wireframe_no_fill():
    """Unfilled path covering full artboard — not an occluder."""
    layers = _make_layers(("Layer 1", True, False, 2))
    items = [
        _make_item("wireframe", bounds=[0, 0, 800, -400], coverRatio=0.99,
                    filled=False),
    ]
    result = check_occlusion(layers, items, AB_RECT, total_item_count=3)

    assert result.ok


# ── Test H: Multiple BG layers, one on top ───────────────────────────

def test_multiple_bg_layers_one_on_top():
    """'Background' layer topmost → Q003."""
    layers = _make_layers(
        ("Background", True, False, 1),
        ("Content", True, False, 5),
        ("BG", True, False, 1),
    )
    items = []
    result = check_occlusion(layers, items, AB_RECT, total_item_count=7)

    assert not result.ok
    assert any(f.code == "Q003" for f in result.findings)


# ── Test I: Clipping group covers 95% → Q001 ────────────────────────

def test_clipping_group_cover():
    """Clipping group covering 95% → Q001 abort."""
    layers = _make_layers(("Layer 1", True, False, 2))
    items = [
        _make_item("clip_group", typename="GroupItem", clipped=True,
                    bounds=[0, 0, 790, -395], coverRatio=0.95,
                    opacity=100),
    ]
    result = check_occlusion(layers, items, AB_RECT, total_item_count=5)

    assert not result.ok
    assert any(f.code == "Q001" for f in result.findings)


# ── Test J: Y-up coordinate math ─────────────────────────────────────

def test_y_up_intersection_area():
    """Verify Y-up intersection math (height = top - bottom)."""
    # Full artboard
    area_full = _intersection_area([0, 0, 800, -400], AB_RECT)
    assert area_full == pytest.approx(800 * 400)

    # Half artboard (left half)
    area_half = _intersection_area([0, 0, 400, -400], AB_RECT)
    assert area_half == pytest.approx(400 * 400)

    # No overlap (entirely off-artboard)
    area_none = _intersection_area([900, 0, 1000, -100], AB_RECT)
    assert area_none == 0

    # Artboard area
    ab_a = _artboard_area(AB_RECT)
    assert ab_a == pytest.approx(800 * 400)


# ── Test K: Suggested fix = layer_move ───────────────────────────────

def test_suggested_fix_format():
    """Verify suggested fix contains valid SOC-style ops."""
    layers = _make_layers(
        ("Sky", True, False, 1),
        ("Body", True, False, 3),
    )
    items = [
        _make_item("sky_bg", bounds=[0, 0, 800, -400], coverRatio=0.99,
                    layer="Sky", layerIndex=0, mcpId="sky_001"),
    ]
    result = check_occlusion(layers, items, AB_RECT, total_item_count=5)

    assert not result.ok
    assert len(result.suggested_fix) > 0

    for fix in result.suggested_fix:
        assert "task" in fix, "Each fix must have a 'task' key"
        assert "params" in fix or "targets" in fix, "Each fix must have params or targets"


# ── Test L: Severity abort blocks ok ─────────────────────────────────

def test_severity_abort_blocks_ok():
    """ok=False only when at least one abort-severity finding exists."""
    layers = _make_layers(("Tint", True, False, 1), ("Body", True, False, 3))

    # Only warn → ok=True
    items_warn = [
        _make_item("tint", bounds=[0, 0, 800, -400], coverRatio=0.95,
                    blend="Multiply", opacity=100, layer="Tint"),
    ]
    result_warn = check_occlusion(layers, items_warn, AB_RECT, total_item_count=5)
    assert result_warn.ok

    # Abort → ok=False
    items_abort = [
        _make_item("solid", bounds=[0, 0, 800, -400], coverRatio=0.95,
                    blend="Normal", opacity=100, layer="Tint"),
    ]
    result_abort = check_occlusion(layers, items_abort, AB_RECT, total_item_count=5)
    assert not result_abort.ok


# ── Test M: BG layer hidden → no Q003 ───────────────────────────────

def test_bg_layer_hidden_no_finding():
    """Hidden Sky layer should not trigger Q003."""
    layers = _make_layers(
        ("Sky", False, False, 1),  # hidden
        ("Body", True, False, 3),
    )
    items = []
    result = check_occlusion(layers, items, AB_RECT, total_item_count=4)

    assert result.ok
    assert not any(f.code == "Q003" for f in result.findings)


# ── Test N: Abort message formatting ─────────────────────────────────

def test_abort_message_format():
    """Verify abort message contains expected structure."""
    result = OcclusionResult(
        ok=False,
        findings=[
            OcclusionFinding(
                code="Q001", severity="abort",
                offender={"name": "sky_bg", "typename": "PathItem"},
                message="'sky_bg' covers 99% of artboard",
            ),
        ],
        diagnostics={},
        suggested_fix=[{"task": "zorder_back"}],
    )
    msg = format_abort_message(result)

    assert "PREVIEW ABORTED" in msg
    assert "Q001" in msg
    assert "ACTION REQUIRED" in msg


# ── Test O: RasterItem treated as filled ─────────────────────────────

def test_raster_item_as_filled():
    """RasterItem covering full artboard → Q001 (always considered filled)."""
    layers = _make_layers(("Layer 1", True, False, 2))
    items = [
        _make_item("photo", typename="RasterItem",
                    bounds=[0, 0, 800, -400], coverRatio=0.99,
                    filled=False),  # filled=False doesn't matter for rasters
    ]
    result = check_occlusion(layers, items, AB_RECT, total_item_count=3)

    assert not result.ok
    assert any(f.code == "Q001" for f in result.findings)


# ── Test P: Custom bg_layer_names detected ─────────────────────────────────

def test_custom_bg_names_detected():
    """Custom bg_layer_names with mixed case — normalized and Q003 fires."""
    layers = _make_layers(
        ("Ground", True, False, 1),
        ("Content", True, False, 5),
    )
    items = []
    # Pass mixed case — should be normalized to lowercase
    result = check_occlusion(
        layers, items, AB_RECT, total_item_count=6,
        bg_layer_names={"Ground", "Horizon"},
    )

    assert not result.ok
    assert any(f.code == "Q003" for f in result.findings)


# ── Test Q: Default fallback when bg_layer_names is None ───────────────

def test_default_bg_names_fallback():
    """When bg_layer_names is None, default set {'sky','background','bg'} is used."""
    # 'sky' is in the default set
    layers = _make_layers(
        ("sky", True, False, 1),
        ("Body", True, False, 3),
    )
    result = check_occlusion(layers, [], AB_RECT, total_item_count=4)
    assert not result.ok
    assert any(f.code == "Q003" for f in result.findings)

    # 'Ground' is NOT in the default set
    layers2 = _make_layers(
        ("Ground", True, False, 1),
        ("Body", True, False, 3),
    )
    result2 = check_occlusion(layers2, [], AB_RECT, total_item_count=4)
    assert result2.ok  # 'ground' not in default names
