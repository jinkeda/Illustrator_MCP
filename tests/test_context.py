"""
Tests for the context.py module (document state inspection tools).

These tests verify the context tools that help AI understand document state.
"""

import pytest
from unittest.mock import AsyncMock, patch
import json

from illustrator_mcp.tools.context import (
    illustrator_get_document,
    illustrator_get_selection_info,
    illustrator_get_app_info,
    illustrator_get_scripting_reference,
)


@pytest.fixture
def mock_execute():
    """Mock the execute_jsx_tool function used by context tools."""
    with patch('illustrator_mcp.tools.context.execute_jsx_tool') as mock:
        yield mock


class TestGetDocument:
    """Tests for get_document tool."""
    
    @pytest.mark.asyncio
    async def test_returns_document_info(self, mock_execute):
        """Test that document structure is returned."""
        mock_result = json.dumps({
            "document": {"name": "Test.ai", "width": 800, "height": 600},
            "layers": [{"name": "Layer 1", "visible": True, "items": []}]
        })
        mock_execute.return_value = mock_result
        
        result = await illustrator_get_document()
        
        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs['command_type'] == "get_document"
        assert call_kwargs['tool_name'] == "illustrator_get_document"
    
    @pytest.mark.asyncio
    async def test_script_contains_layer_iteration(self, mock_execute):
        """Test that script iterates over layers."""
        mock_execute.return_value = "{}"
        
        await illustrator_get_document()
        
        script = mock_execute.call_args.kwargs['script']
        assert "doc.layers" in script or "getLayerInfo" in script


class TestGetSelectionInfo:
    """Tests for get_selection_info tool."""
    
    @pytest.mark.asyncio
    async def test_returns_selection(self, mock_execute):
        """Test that selection info is returned."""
        mock_result = json.dumps({
            "selected": True,
            "count": 2,
            "items": [
                {"name": "Rect1", "type": "PathItem"},
                {"name": "Text1", "type": "TextFrame"}
            ]
        })
        mock_execute.return_value = mock_result
        
        result = await illustrator_get_selection_info()
        
        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs['command_type'] == "get_selection_info"
    
    @pytest.mark.asyncio
    async def test_empty_selection(self, mock_execute):
        """Test handling of empty selection."""
        mock_result = json.dumps({
            "selected": False,
            "count": 0,
            "items": []
        })
        mock_execute.return_value = mock_result
        
        result = await illustrator_get_selection_info()
        
        assert "selected" in result


class TestGetAppInfo:
    """Tests for get_app_info tool."""
    
    @pytest.mark.asyncio
    async def test_returns_app_info(self, mock_execute):
        """Test that app info is returned."""
        mock_result = json.dumps({
            "name": "Adobe Illustrator",
            "version": "30.0",
            "documentsOpen": 1
        })
        mock_execute.return_value = mock_result
        
        result = await illustrator_get_app_info()
        
        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs['command_type'] == "get_app_info"
        assert call_kwargs['tool_name'] == "illustrator_get_app_info"


class TestGetScriptingReference:
    """Tests for get_scripting_reference tool."""
    
    @pytest.mark.asyncio
    async def test_returns_reference(self):
        """Test that scripting reference is returned."""
        result = await illustrator_get_scripting_reference()
        
        assert isinstance(result, str)
        assert len(result) > 100  # Should be a substantial reference
    
    @pytest.mark.asyncio
    async def test_reference_contains_coordinate_info(self):
        """Test that reference contains coordinate system info."""
        result = await illustrator_get_scripting_reference()
        
        assert "Coordinate System" in result
        assert "NEGATIVE downward" in result or "-y" in result
    
    @pytest.mark.asyncio
    async def test_reference_contains_shape_examples(self):
        """Test that reference contains shape creation examples."""
        result = await illustrator_get_scripting_reference()
        
        assert "rectangle" in result.lower()
        assert "ellipse" in result.lower()
    
    @pytest.mark.asyncio
    async def test_reference_contains_color_examples(self):
        """Test that reference contains color examples."""
        result = await illustrator_get_scripting_reference()
        
        assert "RGBColor" in result
        assert "fillColor" in result
    
    @pytest.mark.asyncio
    async def test_reference_contains_common_mistakes(self):
        """Test that reference contains common mistakes section."""
        result = await illustrator_get_scripting_reference()
        
        assert "Common Mistakes" in result or "Avoid" in result
