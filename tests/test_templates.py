"""
Tests for templates module.

Tests that templates render correctly with various inputs.
"""

import pytest
from string import Template

from illustrator_mcp import templates


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
