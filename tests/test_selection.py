"""
Unit tests for selection tools.

Tests verify that the correct JavaScript is generated for each tool.
"""

import pytest
from unittest.mock import AsyncMock, patch

from illustrator_mcp.tools.selection import (
    illustrator_select_all,
    illustrator_deselect_all,
    illustrator_get_selection,
    illustrator_delete_selection,
    illustrator_move_selection,
    illustrator_scale_selection,
    illustrator_rotate_selection,
    illustrator_select_by_name,
    illustrator_find_objects,
    illustrator_select_on_layer,
    MoveSelectionInput,
    ScaleSelectionInput,
    RotateSelectionInput,
    SelectByNameInput,
    FindObjectsInput,
    SelectOnLayerInput
)


class TestSelectAll:
    """Tests for illustrator_select_all tool."""
    
    @pytest.mark.asyncio
    async def test_select_all(self, mock_execute_script):
        """Test selecting all objects."""
        await illustrator_select_all()
        
        script = mock_execute_script.call_args[0][0]
        assert "selectObjectsOnActiveArtboard" in script


class TestDeselectAll:
    """Tests for illustrator_deselect_all tool."""
    
    @pytest.mark.asyncio
    async def test_deselect_all(self, mock_execute_script):
        """Test clearing selection."""
        await illustrator_deselect_all()
        
        script = mock_execute_script.call_args[0][0]
        assert "selection = null" in script


class TestGetSelection:
    """Tests for illustrator_get_selection tool."""
    
    @pytest.mark.asyncio
    async def test_get_selection(self, mock_execute_script):
        """Test getting selection info."""
        await illustrator_get_selection()
        
        script = mock_execute_script.call_args[0][0]
        assert "selection" in script
        assert "typename" in script


class TestDeleteSelection:
    """Tests for illustrator_delete_selection tool."""
    
    @pytest.mark.asyncio
    async def test_delete_selection(self, mock_execute_script):
        """Test deleting selection."""
        await illustrator_delete_selection()
        
        script = mock_execute_script.call_args[0][0]
        assert "remove()" in script


class TestMoveSelection:
    """Tests for illustrator_move_selection tool."""
    
    @pytest.mark.asyncio
    async def test_move_default(self, mock_execute_script):
        """Test moving with default offset."""
        params = MoveSelectionInput()
        await illustrator_move_selection(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "translate" in script
    
    @pytest.mark.asyncio
    async def test_move_custom_offset(self, mock_execute_script):
        """Test moving with custom offset."""
        params = MoveSelectionInput(delta_x=50, delta_y=100)
        await illustrator_move_selection(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "50" in script
        assert "translate" in script


class TestScaleSelection:
    """Tests for illustrator_scale_selection tool."""
    
    @pytest.mark.asyncio
    async def test_scale_selection(self, mock_execute_script):
        """Test scaling selection."""
        params = ScaleSelectionInput(scale_x=150, scale_y=75)
        await illustrator_scale_selection(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "resize" in script
        assert "150" in script
        assert "75" in script


class TestRotateSelection:
    """Tests for illustrator_rotate_selection tool."""
    
    @pytest.mark.asyncio
    async def test_rotate_selection(self, mock_execute_script):
        """Test rotating selection."""
        params = RotateSelectionInput(angle=45)
        await illustrator_rotate_selection(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "rotate" in script
        assert "45" in script


class TestSelectByName:
    """Tests for illustrator_select_by_name tool."""
    
    @pytest.mark.asyncio
    async def test_select_by_exact_name(self, mock_execute_script):
        """Test selecting by exact name."""
        params = SelectByNameInput(pattern="axis_x")
        await illustrator_select_by_name(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "RegExp" in script
        assert "axis_x" in script
    
    @pytest.mark.asyncio
    async def test_select_by_wildcard(self, mock_execute_script):
        """Test selecting by wildcard pattern."""
        params = SelectByNameInput(pattern="bar_*")
        await illustrator_select_by_name(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "RegExp" in script
        assert "bar_" in script
        assert ".*" in script  # Wildcard converted to regex
    
    @pytest.mark.asyncio
    async def test_select_case_insensitive(self, mock_execute_script):
        """Test case-insensitive selection."""
        params = SelectByNameInput(pattern="Label", case_sensitive=False)
        await illustrator_select_by_name(params)
        
        script = mock_execute_script.call_args[0][0]
        assert '"i"' in script  # Case-insensitive flag
    
    @pytest.mark.asyncio
    async def test_select_case_sensitive(self, mock_execute_script):
        """Test case-sensitive selection."""
        params = SelectByNameInput(pattern="Label", case_sensitive=True)
        await illustrator_select_by_name(params)
        
        script = mock_execute_script.call_args[0][0]
        # Should not have 'i' flag
        assert 'case_sensitive' not in script or '""' in script


class TestFindObjects:
    """Tests for illustrator_find_objects tool."""
    
    @pytest.mark.asyncio
    async def test_find_all_objects(self, mock_execute_script):
        """Test finding all objects."""
        params = FindObjectsInput()
        await illustrator_find_objects(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "scanItems" in script
        assert "typename" in script
    
    @pytest.mark.asyncio
    async def test_find_by_type(self, mock_execute_script):
        """Test finding by object type."""
        params = FindObjectsInput(object_type="TextFrame")
        await illustrator_find_objects(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "TextFrame" in script
    
    @pytest.mark.asyncio
    async def test_find_on_layer(self, mock_execute_script):
        """Test finding on specific layer."""
        params = FindObjectsInput(layer_name="Data")
        await illustrator_find_objects(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "Data" in script
        assert "layerFilter" in script


class TestSelectOnLayer:
    """Tests for illustrator_select_on_layer tool."""
    
    @pytest.mark.asyncio
    async def test_select_on_layer(self, mock_execute_script):
        """Test selecting all objects on a layer."""
        params = SelectOnLayerInput(layer_name="Annotations")
        await illustrator_select_on_layer(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "getByName" in script
        assert "Annotations" in script
        assert "collectItems" in script
