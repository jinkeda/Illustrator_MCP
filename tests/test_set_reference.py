"""
Unit tests for illustrator_set_reference tool.

Tests verify JSX generation, payload construction, and Pydantic validation.
No live Illustrator connection required.
"""

import json
import pytest
from pydantic import ValidationError

from illustrator_mcp.tools.documents import (
    illustrator_set_reference,
    SetReferenceInput,
    _SET_REFERENCE_JSX,
    _REFERENCE_LAYER_NAME,
)


class TestSetReferenceScript:
    """Tests for the generated JSX script content."""

    @pytest.mark.asyncio
    async def test_generates_layer_script(self, mock_execute_script):
        """JSX contains layer creation, placement, and locking."""
        params = SetReferenceInput(file_path="C:/ref/bird.png")
        await illustrator_set_reference(params)

        script = mock_execute_script.call_args.kwargs["script"]
        assert "layers.add()" in script
        assert "placedItems.add()" in script
        assert "refLayer.locked = true" in script
        assert "refLayer.printable = false" in script

    @pytest.mark.asyncio
    async def test_fit_proportional(self, mock_execute_script):
        """Fit mode uses Math.min for proportional scaling, not blind stretch."""
        params = SetReferenceInput(file_path="C:/ref/bird.png", fit=True)
        await illustrator_set_reference(params)

        script = mock_execute_script.call_args.kwargs["script"]
        assert "Math.min" in script
        assert "pItem.resize" in script

    @pytest.mark.asyncio
    async def test_clear_only(self, mock_execute_script):
        """file_path=None triggers clear-only mode without placement."""
        params = SetReferenceInput(file_path=None)
        await illustrator_set_reference(params)

        script = mock_execute_script.call_args.kwargs["script"]
        # Payload should encode file_path as null
        assert '"file_path": null' in script
        # Clear path should exist
        assert '"cleared"' in script

    @pytest.mark.asyncio
    async def test_custom_opacity(self, mock_execute_script):
        """Custom opacity is injected into the JSON payload."""
        params = SetReferenceInput(file_path="C:/ref/bird.png", opacity=25.0)
        await illustrator_set_reference(params)

        script = mock_execute_script.call_args.kwargs["script"]
        # The opacity should appear in the JSON payload
        assert '"opacity": 25.0' in script

    @pytest.mark.asyncio
    async def test_active_layer_restore_by_name(self, mock_execute_script):
        """JSX stores activeLayer name as string (not object ref) for safe restore."""
        params = SetReferenceInput(file_path="C:/ref/bird.png")
        await illustrator_set_reference(params)

        script = mock_execute_script.call_args.kwargs["script"]
        assert "originalActiveName" in script
        assert "doc.activeLayer.name" in script
        assert "safeLayerFound" in script

    @pytest.mark.asyncio
    async def test_unlocks_before_delete(self, mock_execute_script):
        """JSX unlocks existing layer before attempting removal."""
        params = SetReferenceInput(file_path="C:/ref/bird.png")
        await illustrator_set_reference(params)

        script = mock_execute_script.call_args.kwargs["script"]
        # locked = false must appear before .remove()
        lock_pos = script.index("existing.locked = false")
        remove_pos = script.index("existing.remove()")
        assert lock_pos < remove_pos

    @pytest.mark.asyncio
    async def test_zero_layer_guard(self, mock_execute_script):
        """JSX checks for single-layer doc before removal to prevent crash."""
        params = SetReferenceInput(file_path="C:/ref/bird.png")
        await illustrator_set_reference(params)

        script = mock_execute_script.call_args.kwargs["script"]
        assert "doc.layers.length === 1" in script

    @pytest.mark.asyncio
    async def test_file_preflight(self, mock_execute_script):
        """JSX checks file existence before placement."""
        params = SetReferenceInput(file_path="C:/ref/bird.png")
        await illustrator_set_reference(params)

        script = mock_execute_script.call_args.kwargs["script"]
        assert "imgFile.exists" in script
        # Pre-flight must happen before placedItems.add
        exists_pos = script.index("imgFile.exists")
        place_pos = script.index("placedItems.add()")
        assert exists_pos < place_pos


class TestSetReferencePayload:
    """Tests for payload construction and Pydantic validation."""

    def test_rejects_bad_opacity(self):
        """Pydantic rejects opacity outside 0-100 range."""
        with pytest.raises(ValidationError):
            SetReferenceInput(file_path="C:/ref/bird.png", opacity=150)
        with pytest.raises(ValidationError):
            SetReferenceInput(file_path="C:/ref/bird.png", opacity=-5)

    def test_windows_path_json(self):
        """Windows paths survive json.dumps round-trip without corruption."""
        params = SetReferenceInput(file_path=r"C:\Users\k.jin\ref\bird.png")
        payload = params.model_dump()
        payload["layer_name"] = _REFERENCE_LAYER_NAME
        payload_json = json.dumps(payload)

        # Must be valid JSON
        parsed = json.loads(payload_json)
        assert parsed["file_path"] == r"C:\Users\k.jin\ref\bird.png"
        assert parsed["layer_name"] == "__reference__"

    def test_layer_name_not_in_schema(self):
        """layer_name is NOT a field in the Pydantic schema."""
        fields = SetReferenceInput.model_fields
        assert "layer_name" not in fields

    def test_layer_name_injected_in_payload(self):
        """Python injects hardcoded layer_name into payload dict."""
        params = SetReferenceInput(file_path="C:/ref/bird.png")
        payload = params.model_dump()
        assert "layer_name" not in payload  # not from schema

        payload["layer_name"] = _REFERENCE_LAYER_NAME
        assert payload["layer_name"] == "__reference__"

    def test_no_fstring_brace_artifacts(self):
        """JSX template uses %s injection, no stray Python format artifacts."""
        # The template should have exactly one %s placeholder
        assert _SET_REFERENCE_JSX.count("%s") == 1
        # Should NOT contain Python f-string artifacts like {variable}
        # (but does contain JS braces — just verify no unmatched {})
        assert "{json" not in _SET_REFERENCE_JSX
        assert "{payload_json}" not in _SET_REFERENCE_JSX
