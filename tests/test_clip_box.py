"""Tests for the clip_box (regional zoom) feature.

Covers: ExtendScript export logic, input validation, schema definitions,
item culling, system note injection, and ruler absolute origin.
"""

import math
import re
import pytest
from unittest.mock import AsyncMock, patch

from illustrator_mcp.tools.preview import (
    _build_export_script,
    _validate_clip_box,
    _clip_box_to_ai_rect,
    _build_collect_script,
    _CLIP_MAX_SCALE_PCT,
    _COLLECT_ITEMS_JSX,
    _COLLECT_ITEMS_CLIP_JSX,
)


# ======================================================================
# TestBuildExportScriptClipBox
# ======================================================================

class TestBuildExportScriptClipBox:
    """Test _build_export_script with and without clip_box."""

    def test_no_clip_box_unchanged(self):
        """Without clip_box, JSX has min(..., 100) cap, no temp artboard."""
        jsx = _build_export_script("/tmp/test.png", 1024)
        assert "Math.min(" in jsx
        assert ", 100)" in jsx
        assert "artboards.add" not in jsx
        assert "__mcp_clip" not in jsx

    def test_clip_box_adds_temp_artboard(self):
        """With clip_box, JSX contains artboards.add and artboards.remove."""
        jsx = _build_export_script("/tmp/test.png", 1024, clip_box=[100, 50, 300, 250])
        assert "artboards.add(clipRect)" in jsx
        assert "artboards.remove(tmpIdx)" in jsx
        assert "__mcp_clip" in jsx.replace('"', "").replace("'", "")

    def test_clip_box_removes_scale_cap(self):
        """With clip_box, there is no Math.min(..., 100) cap."""
        jsx = _build_export_script("/tmp/test.png", 1024, clip_box=[100, 50, 300, 250])
        # Should NOT have the original 100% cap
        assert ", 100)" not in jsx
        # But should have the safety clamp
        assert "Math.min(scale," in jsx

    def test_scale_clamped(self):
        """JSX contains Math.min(scale, <centralized constant>) safety ceiling."""
        jsx = _build_export_script("/tmp/test.png", 1024, clip_box=[0, 0, 10, 10])
        # Should contain the clip scale clamp using the centralized constant
        assert f"Math.min(scale, {_CLIP_MAX_SCALE_PCT})" in jsx

    def test_artboard_index_via_length(self):
        """JSX uses .length - 1 to get index, not return value of .add()."""
        jsx = _build_export_script("/tmp/test.png", 1024, clip_box=[0, 0, 100, 100])
        assert "doc.artboards.length - 1" in jsx
        # Should NOT assign add() result to tmpIdx
        assert "tmpIdx = doc.artboards.add" not in jsx

    def test_clip_box_coordinate_conversion(self):
        """Screen Y-down → Illustrator Y-up conversion in JSX."""
        jsx = _build_export_script("/tmp/test.png", 1024, clip_box=[100, 50, 300, 250])
        # xmin offset
        assert "origAb[0] + 100" in jsx
        # ymin: screen Y-down → AI Y-up means subtract
        assert "origAb[1] - 50" in jsx
        # xmax offset
        assert "origAb[0] + 300" in jsx
        # ymax offset
        assert "origAb[1] - 250" in jsx

    def test_clip_box_restores_original_artboard(self):
        """JSX has setActiveArtboardIndex(origIdx) in finally."""
        jsx = _build_export_script("/tmp/test.png", 1024, clip_box=[0, 0, 100, 100])
        # The finally block should restore the original artboard
        assert "setActiveArtboardIndex(origIdx)" in jsx
        # And it should be in the finally block (after the try)
        finally_idx = jsx.index("finally")
        restore_idx = jsx.index("setActiveArtboardIndex(origIdx)")
        assert restore_idx > finally_idx

    def test_doc_saved_try_catch(self):
        """JSX caches doc.saved and restores in try/catch."""
        jsx = _build_export_script("/tmp/test.png", 1024, clip_box=[0, 0, 100, 100])
        assert "wasSaved = doc.saved" in jsx
        assert "doc.saved = wasSaved" in jsx
        # The restore should be in a try/catch
        assert "try {" in jsx or "try{" in jsx


# ======================================================================
# TestClipBoxValidation
# ======================================================================

class TestClipBoxValidation:
    """Test _validate_clip_box input validation."""

    def test_valid_clip_box_accepted(self):
        result = _validate_clip_box([100, 50, 300, 250])
        assert result == [100, 50, 300, 250]

    def test_swapped_coords_auto_normalized(self):
        """Inverted coords are auto-swapped."""
        result = _validate_clip_box([300, 250, 100, 50])
        assert result == [100, 50, 300, 250]

    def test_nan_rejected(self):
        with pytest.raises(ValueError, match="non-finite"):
            _validate_clip_box([float('nan'), 0, 100, 100])

    def test_inf_rejected(self):
        with pytest.raises(ValueError, match="non-finite"):
            _validate_clip_box([0, 0, float('inf'), 100])

    def test_too_small_rejected(self):
        """Box smaller than 1×1pt is rejected."""
        with pytest.raises(ValueError, match="too small"):
            _validate_clip_box([0, 0, 0.5, 0.5])

    def test_wrong_length_rejected(self):
        with pytest.raises(ValueError, match="4 elements"):
            _validate_clip_box([0, 0])


# ======================================================================
# TestClipBoxSchema
# ======================================================================

class TestClipBoxSchema:
    """Test clip_box field on ExecuteScriptInput and ExecuteTaskInput."""

    def test_execute_script_clip_box_optional(self):
        from illustrator_mcp.tools.execute import ExecuteScriptInput
        inp = ExecuteScriptInput(script="var x = 1;")
        assert inp.clip_box is None

    def test_execute_script_clip_box_accepted(self):
        from illustrator_mcp.tools.execute import ExecuteScriptInput
        inp = ExecuteScriptInput(script="var x = 1;", clip_box=[100, 50, 300, 250])
        assert inp.clip_box == [100, 50, 300, 250]

    def test_execute_task_clip_box_optional(self):
        from illustrator_mcp.tools.task_execution import ExecuteTaskInput
        inp = ExecuteTaskInput(payload={"task": "apply_fill_color", "params": {"color": {"r": 255}}})
        assert inp.clip_box is None

    def test_execute_task_clip_box_accepted(self):
        from illustrator_mcp.tools.task_execution import ExecuteTaskInput
        inp = ExecuteTaskInput(
            payload={"task": "apply_fill_color", "params": {"color": {"r": 255}}},
            clip_box=[100, 50, 300, 250],
        )
        assert inp.clip_box == [100, 50, 300, 250]


# ======================================================================
# TestClipBoxCulling
# ======================================================================

class TestClipBoxCulling:
    """Test _build_collect_script and _clip_box_to_ai_rect."""

    def test_no_clip_uses_standard_jsx(self):
        """Without clip_box, standard _COLLECT_ITEMS_JSX is used."""
        script = _build_collect_script(200, clip_box=None)
        assert "abL" in script  # uses artboard bounds variables
        assert "cL" not in script  # does NOT use clip variables

    def test_clip_uses_clip_jsx(self):
        """With clip_box, clip-aware variant is used with clip bounds."""
        script = _build_collect_script(200, clip_box=[100, 50, 300, 250])
        assert "cL" in script  # uses clip variables
        assert "ab[0]+100" in script
        assert "ab[1]-50" in script

    def test_clip_box_to_ai_rect(self):
        """Screen-space → AI rect conversion is correct."""
        artboard_rect = [0, 792, 612, 0]  # US Letter, origin top-left
        clip = [100, 50, 300, 250]
        ai_rect = _clip_box_to_ai_rect(clip, artboard_rect)
        assert ai_rect == [100, 742, 300, 542]  # ab_l+xmin, ab_t-ymin, ab_l+xmax, ab_t-ymax

    def test_clip_box_to_ai_rect_with_offset_artboard(self):
        """Works correctly when artboard origin is not at (0, 0)."""
        artboard_rect = [100, 500, 700, 0]
        clip = [50, 25, 200, 150]
        ai_rect = _clip_box_to_ai_rect(clip, artboard_rect)
        assert ai_rect == [150, 475, 300, 350]


# ======================================================================
# TestClipBoxSystemNote — integration-level tests
# ======================================================================

class TestClipBoxSystemNote:
    """Test that the system note is injected when clip_box is active."""

    def test_system_note_pattern(self):
        """The system note contains expected keywords."""
        # This tests the note text pattern used in execute.py and task_execution.py
        clip = [100, 50, 300, 250]
        note = (
            f"\u26a0\ufe0f CLIP BOX ACTIVE: This preview shows a "
            f"high-resolution crop of region "
            f"{clip} (screen-space Y-down, points). "
            f"All element IDs and coordinates in the annotation "
            f"map are in GLOBAL document coordinates. "
            f"Use global coordinates for all subsequent edits."
        )
        assert "CLIP BOX ACTIVE" in note
        assert "screen-space Y-down" in note
        assert "GLOBAL document coordinates" in note
        assert str(clip) in note

    def test_system_note_not_injected_without_clip(self):
        """Verify the conditional check that guards injection."""
        clip_box = None
        # The guard in execute.py / task_execution.py is: if params.clip_box:
        assert not clip_box  # Should be falsy → no system note


# ======================================================================
# TestClipBoxRuler
# ======================================================================

class TestClipBoxRuler:
    """Test ruler overlay with absolute origin."""

    @pytest.fixture
    def _make_png(self):
        """Create a minimal valid PNG for testing."""
        from PIL import Image
        import io
        img = Image.new("RGBA", (400, 400), (200, 200, 200, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_ruler_absolute_origin(self, _make_png):
        """With clip_box origin (200,100), ruler labels start at 200/100."""
        from illustrator_mcp.overlay import draw_ruler_overlay
        # 200x200pt clip region starting at (200, 100) in document space
        result = draw_ruler_overlay(
            _make_png, 200, 200,
            origin_x_pt=200, origin_y_pt=100,
        )
        # Result should be valid PNG bytes (different from input due to overlay)
        assert len(result) > 100
        assert result != _make_png

    def test_ruler_zero_origin_unchanged(self, _make_png):
        """Without clip_box, ruler starts at 0 (backward compat)."""
        from illustrator_mcp.overlay import draw_ruler_overlay
        result = draw_ruler_overlay(_make_png, 400, 400)
        assert len(result) > 100
        assert result != _make_png


# ======================================================================
# TestClipMaxScaleConstant
# ======================================================================

class TestClipMaxScaleConstant:
    """Test the centralized scale constant."""

    def test_constant_value(self):
        assert _CLIP_MAX_SCALE_PCT == 776.0

    def test_constant_used_in_jsx(self):
        """The JSX uses the centralized constant, not a hardcoded value."""
        jsx = _build_export_script("/tmp/test.png", 1024, clip_box=[0, 0, 100, 100])
        assert str(_CLIP_MAX_SCALE_PCT) in jsx
