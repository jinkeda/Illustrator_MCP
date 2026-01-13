"""
Unit tests for object operation tools.

Tests verify that the correct JavaScript is generated for each tool.
"""

import pytest
from unittest.mock import AsyncMock, patch

from illustrator_mcp.tools.objects import (
    illustrator_duplicate_selection,
    illustrator_copy_to_layer,
    illustrator_lock_selection,
    illustrator_unlock_all,
    illustrator_hide_selection,
    illustrator_show_all,
    illustrator_get_object_bounds,
    illustrator_rename_object,
    illustrator_set_opacity,
    illustrator_set_blend_mode,
    DuplicateSelectionInput,
    CopyToLayerInput,
    RenameObjectInput,
    SetOpacityInput,
    SetBlendModeInput
)


class TestDuplicateSelection:
    """Tests for illustrator_duplicate_selection tool."""
    
    @pytest.mark.asyncio
    async def test_duplicate_default_offset(self, mock_execute_script):
        """Test duplication with default offset."""
        params = DuplicateSelectionInput()
        await illustrator_duplicate_selection(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "duplicate()" in script
        assert "translate" in script
    
    @pytest.mark.asyncio
    async def test_duplicate_custom_offset(self, mock_execute_script):
        """Test duplication with custom offset."""
        params = DuplicateSelectionInput(offset_x=50, offset_y=100)
        await illustrator_duplicate_selection(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "duplicate()" in script
        assert "50" in script
        assert "100" in script


class TestCopyToLayer:
    """Tests for illustrator_copy_to_layer tool."""
    
    @pytest.mark.asyncio
    async def test_copy_to_layer(self, mock_execute_script):
        """Test copying selection to another layer."""
        params = CopyToLayerInput(layer_name="Background")
        await illustrator_copy_to_layer(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "layers.getByName" in script
        assert "Background" in script
        assert "duplicate()" in script
        assert "move" in script


class TestLockUnlock:
    """Tests for lock/unlock tools."""
    
    @pytest.mark.asyncio
    async def test_lock_selection(self, mock_execute_script):
        """Test locking selected objects."""
        await illustrator_lock_selection()
        
        script = mock_execute_script.call_args[0][0]
        assert "locked = true" in script
    
    @pytest.mark.asyncio
    async def test_unlock_all(self, mock_execute_script):
        """Test unlocking all objects."""
        await illustrator_unlock_all()
        
        script = mock_execute_script.call_args[0][0]
        assert "locked = false" in script


class TestHideShow:
    """Tests for hide/show tools."""
    
    @pytest.mark.asyncio
    async def test_hide_selection(self, mock_execute_script):
        """Test hiding selected objects."""
        await illustrator_hide_selection()
        
        script = mock_execute_script.call_args[0][0]
        assert "hidden = true" in script
    
    @pytest.mark.asyncio
    async def test_show_all(self, mock_execute_script):
        """Test showing all hidden objects."""
        await illustrator_show_all()
        
        script = mock_execute_script.call_args[0][0]
        assert "hidden = false" in script


class TestGetObjectBounds:
    """Tests for illustrator_get_object_bounds tool."""
    
    @pytest.mark.asyncio
    async def test_get_bounds(self, mock_execute_script):
        """Test getting object bounds."""
        await illustrator_get_object_bounds()
        
        script = mock_execute_script.call_args[0][0]
        assert "geometricBounds" in script


class TestRenameObject:
    """Tests for illustrator_rename_object tool."""
    
    @pytest.mark.asyncio
    async def test_rename_object(self, mock_execute_script):
        """Test renaming an object."""
        params = RenameObjectInput(name="Logo Icon")
        await illustrator_rename_object(params)
        
        script = mock_execute_script.call_args[0][0]
        assert 'name = "Logo Icon"' in script


class TestSetOpacity:
    """Tests for illustrator_set_opacity tool."""
    
    @pytest.mark.asyncio
    async def test_set_opacity_50(self, mock_execute_script):
        """Test setting 50% opacity."""
        params = SetOpacityInput(opacity=50)
        await illustrator_set_opacity(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "opacity = 50" in script
    
    @pytest.mark.asyncio
    async def test_set_opacity_full(self, mock_execute_script):
        """Test setting 100% opacity."""
        params = SetOpacityInput(opacity=100)
        await illustrator_set_opacity(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "opacity = 100" in script


class TestSetBlendMode:
    """Tests for illustrator_set_blend_mode tool."""
    
    @pytest.mark.asyncio
    async def test_set_multiply(self, mock_execute_script):
        """Test setting multiply blend mode."""
        params = SetBlendModeInput(mode="multiply")
        await illustrator_set_blend_mode(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "BlendModes.MULTIPLY" in script
    
    @pytest.mark.asyncio
    async def test_set_screen(self, mock_execute_script):
        """Test setting screen blend mode."""
        params = SetBlendModeInput(mode="screen")
        await illustrator_set_blend_mode(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "BlendModes.SCREEN" in script
    
    @pytest.mark.asyncio
    async def test_set_overlay(self, mock_execute_script):
        """Test setting overlay blend mode."""
        params = SetBlendModeInput(mode="overlay")
        await illustrator_set_blend_mode(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "BlendModes.OVERLAY" in script
