"""
Tests for templates module.

Tests that templates render correctly with various inputs.
"""

import pytest
from string import Template

from illustrator_mcp import templates
from illustrator_mcp.tools.documents import PlaceFileInput, _TRACEABLE_EXTENSIONS


class TestTemplateRendering:
    """Tests for template rendering."""
    
    def test_place_item_template_basic(self):
        """Test PLACE_ITEM template renders correctly."""
        result = templates.PLACE_ITEM.substitute(
            path="/test/path.png",
            x=100,
            neg_y=-50,
            y=50,
            linked="true",
            embed_line="",
            marker_line="",
            error_prefix="Image file"
        )
        assert "/test/path.png" in result
        assert "Image file" in result
        assert "100" in result
        assert "-50" in result
    
    def test_place_item_with_embed(self):
        """Test PLACE_ITEM with embed option."""
        result = templates.PLACE_ITEM.substitute(
            path="/test/file.eps",
            x=0,
            neg_y=0,
            y=0,
            linked="false",
            embed_line="placed.embed();",
            marker_line="",
            error_prefix="File"
        )
        assert "placed.embed();" in result
        assert "linked: false" in result
    
    def test_create_document_template(self):
        """Test CREATE_DOCUMENT template renders correctly."""
        result = templates.CREATE_DOCUMENT.substitute(
            width=800,
            height=600,
            color_space="RGB",
            title_line='preset.title = "Test Doc";'
        )
        assert "800" in result
        assert "600" in result
        assert "RGB" in result
        assert "Test Doc" in result
    
    def test_open_document_template(self):
        """Test OPEN_DOCUMENT template renders correctly."""
        result = templates.OPEN_DOCUMENT.substitute(path="C:/test/doc.ai")
        assert "C:/test/doc.ai" in result
        assert "File not found" in result
    
    def test_close_document_template(self):
        """Test CLOSE_DOCUMENT template renders correctly."""
        result = templates.CLOSE_DOCUMENT.substitute(
            save_option="SaveOptions.DONOTSAVECHANGES"
        )
        assert "SaveOptions.DONOTSAVECHANGES" in result
    
    def test_save_document_template(self):
        """Test SAVE_DOCUMENT template renders correctly."""
        result = templates.SAVE_DOCUMENT.substitute(path="/path/to/save.ai")
        assert "/path/to/save.ai" in result


class TestStaticTemplates:
    """Tests for static (non-parameterized) templates."""
    
    def test_undo_template_is_valid_js(self):
        """Test UNDO template is valid JS structure."""
        assert "(function()" in templates.UNDO
        assert "app.undo()" in templates.UNDO
        assert "success" in templates.UNDO
    
    def test_redo_template_is_valid_js(self):
        """Test REDO template is valid JS structure."""
        assert "(function()" in templates.REDO
        assert "app.redo()" in templates.REDO
        assert "success" in templates.REDO
    
    def test_get_app_info_template(self):
        """Test GET_APP_INFO template structure."""
        assert "app.name" in templates.GET_APP_INFO
        assert "app.version" in templates.GET_APP_INFO
        assert "JSON.stringify" in templates.GET_APP_INFO
    
    def test_get_document_info_template(self):
        """Test GET_DOCUMENT_INFO template structure."""
        assert "activeDocument" in templates.GET_DOCUMENT_INFO
        assert "colorMode" in templates.GET_DOCUMENT_INFO


class TestSpecialCharacters:
    """Tests for templates with special characters."""
    
    def test_path_with_backslashes(self):
        """Test template handles Windows paths."""
        # Note: Paths should be escaped before passing to template
        result = templates.OPEN_DOCUMENT.substitute(
            path="C:/Users/test/Documents/file.ai"
        )
        assert "C:/Users/test/Documents/file.ai" in result
    
    def test_path_with_spaces(self):
        """Test template handles paths with spaces."""
        result = templates.OPEN_DOCUMENT.substitute(
            path="/path with spaces/file.ai"
        )
        assert "/path with spaces/file.ai" in result


class TestTraceTemplate:
    """Tests for TRACE_PLACED_IMAGE template."""

    def test_trace_uses_marker_not_index(self):
        """Trace script finds item by marker, not by fragile index."""
        result = templates.TRACE_PLACED_IMAGE.substitute(
            marker="@mcp:trace_target=abc123", preset="null", expand="true"
        )
        assert "abc123" in result
        assert "indexOf(marker)" in result
        assert "placedItems[0]" not in result

    def test_trace_preset_fallback(self):
        """Preset failure is caught, not thrown."""
        result = templates.TRACE_PLACED_IMAGE.substitute(
            marker="@mcp:trace_target=x", preset='"6 Colors"', expand="true"
        )
        assert "loadFromPreset" in result
        assert "6 Colors" in result
        assert "catch(pe)" in result
        assert "warnings.push" in result

    def test_trace_type_guard(self):
        """JSX checks typename before tracing."""
        result = templates.TRACE_PLACED_IMAGE.substitute(
            marker="@mcp:trace_target=x", preset="null", expand="false"
        )
        assert "PlacedItem" in result
        assert "RasterItem" in result
        assert "not traceable" in result

    def test_trace_retry_expand(self):
        """Expand uses retry-around-expandTracing, not anchorCount."""
        result = templates.TRACE_PLACED_IMAGE.substitute(
            marker="@mcp:trace_target=x", preset="null", expand="true"
        )
        assert "expandTracing()" in result
        assert "$.sleep(500)" in result
        assert "maxRetries" in result
        assert "anchorCount" not in result

    def test_trace_marker_in_place_template(self):
        """PLACE_ITEM template includes marker after embed."""
        result = templates.PLACE_ITEM.substitute(
            path="/img.png", x=0, neg_y=0, y=0, linked="true",
            embed_line="", error_prefix="File",
            marker_line='placed.note = "@mcp:trace_target=abc";'
        )
        assert '@mcp:trace_target=abc' in result

    def test_trace_mcp_id_tagging(self):
        """Expanded trace result is tagged with MCP ID."""
        result = templates.TRACE_PLACED_IMAGE.substitute(
            marker="@mcp:trace_target=abc123", preset="null", expand="true"
        )
        assert '@mcp:id=' in result
        assert 'trace:' in result

    def test_trace_complexity_guardrail(self):
        """Warning emitted for high item counts."""
        result = templates.TRACE_PLACED_IMAGE.substitute(
            marker="@mcp:trace_target=x", preset="null", expand="true"
        )
        assert "2000" in result
        assert "High complexity" in result

    def test_trace_narrowed_collection_scan(self):
        """Scans placedItems/rasterItems before pageItems fallback."""
        result = templates.TRACE_PLACED_IMAGE.substitute(
            marker="@mcp:trace_target=x", preset="null", expand="true"
        )
        assert "doc.placedItems" in result
        assert "doc.rasterItems" in result
        assert "doc.pageItems" in result


class TestPlaceFileInputValidation:
    """Tests for PlaceFileInput model validation."""

    def test_trace_and_embed_editable_conflict(self):
        """trace=True and embed_editable=True should raise."""
        with pytest.raises(ValueError, match="Cannot use both"):
            PlaceFileInput(file_path="/test.png", trace=True, embed_editable=True)

    def test_trace_rejects_non_raster(self):
        """trace=True with non-raster extension should raise."""
        with pytest.raises(ValueError, match="requires a raster"):
            PlaceFileInput(file_path="/test.pdf", trace=True)

    def test_trace_rejects_ai_file(self):
        """trace=True with .ai extension should raise."""
        with pytest.raises(ValueError, match="requires a raster"):
            PlaceFileInput(file_path="/test.ai", trace=True)

    def test_trace_accepts_all_raster_extensions(self):
        """trace=True with supported raster formats should be accepted."""
        for ext in ("png", "jpg", "jpeg", "tif", "tiff", "bmp", "gif", "psd"):
            inp = PlaceFileInput(file_path=f"/test.{ext}", trace=True)
            assert inp.trace is True

    def test_trace_defaults(self):
        """Default values for trace params."""
        inp = PlaceFileInput(file_path="/test.png")
        assert inp.trace is False
        assert inp.trace_preset is None
        assert inp.expand is True

    def test_traceable_extensions_constant(self):
        """_TRACEABLE_EXTENSIONS covers common raster formats."""
        assert ".png" in _TRACEABLE_EXTENSIONS
        assert ".jpg" in _TRACEABLE_EXTENSIONS
        assert ".psd" in _TRACEABLE_EXTENSIONS
        assert ".pdf" not in _TRACEABLE_EXTENSIONS
        assert ".ai" not in _TRACEABLE_EXTENSIONS
