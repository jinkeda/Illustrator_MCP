"""
test_empty_canvas_checkpoint.py — Tests for VLM checkpoint skip on empty canvas (PR-B).

Verifies that when _annotate_preview returns 0 annotations (empty canvas),
the VLM checkpoint instruction is suppressed and a diagnostic flag is emitted.

Run: python -m pytest tests/test_empty_canvas_checkpoint.py -v
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from types import SimpleNamespace


# ── Test the _present() empty-canvas skip logic ──────────────────────


class TestEmptyCanvasCheckpointSkip:
    """Tests that VLM checkpoint is skipped when annotated_count is 0."""

    @pytest.fixture(autouse=True)
    def _patch_counter(self, monkeypatch):
        """Stub out mutation counter."""
        import illustrator_mcp.tools.execute as ex_mod
        monkeypatch.setattr(ex_mod, "_counter", MagicMock(value=5))

    @pytest.mark.asyncio
    async def test_checkpoint_skipped_on_zero_annotations(self):
        """0 annotated items → checkpoint instruction suppressed, diagnostic set."""
        import illustrator_mcp.tools.execute as ex_mod
        from illustrator_mcp.tools.execute import _present, _ExecContext

        # Build a minimal ctx that triggers VLM checkpoint path
        ctx = _ExecContext(
            context="execute_script",
            warnings=[],
            diagnostics={},
        )
        ctx.is_vlm_checkpoint = True
        ctx.guard_result = None  # No guard abort

        # Build minimal params that trigger preview
        params = MagicMock()
        params.return_preview = True
        params.preview_mode = "annotated"
        params.preview_max_items = 200
        params.timeout = 10.0
        params.probe_points = None
        params.clip_box = None
        params.preview_format = "png"
        params.preview_max_dim = 1024
        params.final_step = False

        # Mock response (successful script execution)
        response = {"result": json.dumps({"ok": True})}

        # Mock _generate_preview to return a dummy image
        import base64 as _b64
        dummy_png = _b64.b64encode(b"FAKE_PNG").decode("utf-8")
        mock_preview = MagicMock()
        mock_preview.data = dummy_png
        mock_preview.mimeType = "image/png"

        # Mock _annotate_preview to return 0 annotations (empty canvas)
        empty_annotation_result = {
            "meta": {
                "annotated_count": 0,
                "input_count": 0,
                "filtered_count": 0,
                "bounds_kind": "visibleBounds",
                "max_items": 200,
            },
            "annotations": [],
            "warnings": ["No visible items found on artboard"],
        }
        mock_annotate = AsyncMock(return_value=(b"ANNOTATED_PNG", empty_annotation_result))
        mock_gen_preview = AsyncMock(return_value=mock_preview)

        with patch("illustrator_mcp.tools.execute._generate_preview", mock_gen_preview), \
             patch("illustrator_mcp.tools.execute._annotate_preview", mock_annotate):
            result = await _present(response, params, ctx)

        # result should be a list of TextContent/ImageContent
        assert isinstance(result, list), f"Expected list, got {type(result)}"

        # Extract all text parts
        text_parts = [
            part.text for part in result
            if hasattr(part, 'text') and hasattr(part, 'type') and part.type == "text"
        ]
        full_text = "\n".join(text_parts)

        # VLM checkpoint instruction should NOT be present
        assert "VLM_CHECKPOINT" not in full_text or "skipped" in full_text, \
            "VLM checkpoint instruction should be suppressed on empty canvas"

        # The skip warning SHOULD be present
        assert "checkpoint skipped" in full_text.lower(), \
            "Expected 'checkpoint skipped' warning in output"

        # Diagnostic flag should be set
        assert ctx.diagnostics.get("checkpoint_skipped_empty_canvas") is True, \
            "diagnostic flag 'checkpoint_skipped_empty_canvas' should be True"

    @pytest.mark.asyncio
    async def test_checkpoint_emitted_on_nonempty_canvas(self):
        """Annotated items > 0 → checkpoint instruction IS emitted."""
        import illustrator_mcp.tools.execute as ex_mod
        from illustrator_mcp.tools.execute import _present, _ExecContext

        ctx = _ExecContext(
            context="execute_script",
            warnings=[],
            diagnostics={},
        )
        ctx.is_vlm_checkpoint = True
        ctx.guard_result = None

        params = MagicMock()
        params.return_preview = True
        params.preview_mode = "annotated"
        params.preview_max_items = 200
        params.timeout = 10.0
        params.probe_points = None
        params.clip_box = None
        params.preview_format = "png"
        params.preview_max_dim = 1024
        params.final_step = False

        response = {"result": json.dumps({"ok": True})}

        import base64 as _b64
        dummy_png = _b64.b64encode(b"FAKE_PNG").decode("utf-8")
        mock_preview = MagicMock()
        mock_preview.data = dummy_png
        mock_preview.mimeType = "image/png"

        # Non-empty annotation result (3 items)
        nonempty_annotation_result = {
            "meta": {
                "annotated_count": 3,
                "input_count": 5,
                "filtered_count": 2,
                "bounds_kind": "visibleBounds",
                "max_items": 200,
            },
            "annotations": [
                {"label": "1", "mcp_id": "abc", "name": "rect1", "type": "PathItem",
                 "bounds_pt": [0, 0, 100, -100], "coverRatio": 0.1},
                {"label": "2", "mcp_id": "def", "name": "rect2", "type": "PathItem",
                 "bounds_pt": [50, 0, 150, -100], "coverRatio": 0.1},
                {"label": "3", "mcp_id": "ghi", "name": "rect3", "type": "PathItem",
                 "bounds_pt": [100, 0, 200, -100], "coverRatio": 0.1},
            ],
            "warnings": [],
        }
        mock_annotate = AsyncMock(return_value=(b"ANNOTATED_PNG", nonempty_annotation_result))
        mock_gen_preview = AsyncMock(return_value=mock_preview)

        with patch("illustrator_mcp.tools.execute._generate_preview", mock_gen_preview), \
             patch("illustrator_mcp.tools.execute._annotate_preview", mock_annotate):
            result = await _present(response, params, ctx)

        assert isinstance(result, list)

        text_parts = [
            part.text for part in result
            if hasattr(part, 'text') and hasattr(part, 'type') and part.type == "text"
        ]
        full_text = "\n".join(text_parts)

        # VLM checkpoint instruction SHOULD be present
        assert "checkpoint skipped" not in full_text.lower(), \
            "Checkpoint should NOT be skipped when items exist"

        # Diagnostic flag should NOT be set
        assert "checkpoint_skipped_empty_canvas" not in ctx.diagnostics, \
            "diagnostic flag should not be set for non-empty canvas"

    @pytest.mark.asyncio
    async def test_function_returns_ok_on_empty_canvas(self):
        """Empty canvas skip still returns ok=True in envelope."""
        import illustrator_mcp.tools.execute as ex_mod
        from illustrator_mcp.tools.execute import _present, _ExecContext

        ctx = _ExecContext(
            context="execute_script",
            warnings=[],
            diagnostics={},
        )
        ctx.is_vlm_checkpoint = True
        ctx.guard_result = None

        params = MagicMock()
        params.return_preview = True
        params.preview_mode = "annotated"
        params.preview_max_items = 200
        params.timeout = 10.0
        params.probe_points = None
        params.clip_box = None
        params.preview_format = "png"
        params.preview_max_dim = 1024
        params.final_step = False

        response = {"result": json.dumps({"ok": True})}

        import base64 as _b64
        dummy_png = _b64.b64encode(b"FAKE_PNG").decode("utf-8")
        mock_preview = MagicMock()
        mock_preview.data = dummy_png
        mock_preview.mimeType = "image/png"

        empty_annotation_result = {
            "meta": {"annotated_count": 0, "input_count": 0,
                     "filtered_count": 0, "bounds_kind": "visibleBounds",
                     "max_items": 200},
            "annotations": [],
            "warnings": [],
        }
        mock_annotate = AsyncMock(return_value=(b"ANNOTATED", empty_annotation_result))
        mock_gen_preview = AsyncMock(return_value=mock_preview)

        with patch("illustrator_mcp.tools.execute._generate_preview", mock_gen_preview), \
             patch("illustrator_mcp.tools.execute._annotate_preview", mock_annotate):
            result = await _present(response, params, ctx)

        # Should still return a list (not crash)
        assert isinstance(result, list)

        # The JSON envelope should contain ok=True
        envelope_parts = [
            part.text for part in result
            if hasattr(part, 'text') and hasattr(part, 'type') and part.type == "text"
        ]
        # First text part should be the JSON envelope
        if envelope_parts:
            try:
                env = json.loads(envelope_parts[0])
                assert env.get("ok") is True, "Envelope should have ok=True"
            except json.JSONDecodeError:
                pass  # Non-JSON text part, that's fine
