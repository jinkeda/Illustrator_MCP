"""
Unit tests for pathfinder operation tools.

Tests verify that the correct JavaScript is generated for each tool.
"""

import pytest
from unittest.mock import AsyncMock, patch

from illustrator_mcp.tools.pathfinder import (
    illustrator_pathfinder_unite,
    illustrator_pathfinder_minus_front,
    illustrator_pathfinder_minus_back,
    illustrator_pathfinder_intersect,
    illustrator_pathfinder_exclude,
    illustrator_pathfinder_divide,
    illustrator_pathfinder_trim,
    illustrator_pathfinder_merge
)


class TestPathfinderUnite:
    """Tests for pathfinder unite tool."""
    
    @pytest.mark.asyncio
    async def test_unite(self, mock_execute_script):
        """Test unite operation."""
        await illustrator_pathfinder_unite()
        
        script = mock_execute_script.call_args[0][0]
        assert "Live Pathfinder Add" in script
        assert "expandStyle" in script


class TestPathfinderSubtract:
    """Tests for pathfinder subtract tools."""
    
    @pytest.mark.asyncio
    async def test_minus_front(self, mock_execute_script):
        """Test minus front operation."""
        await illustrator_pathfinder_minus_front()
        
        script = mock_execute_script.call_args[0][0]
        assert "Live Pathfinder Subtract" in script
    
    @pytest.mark.asyncio
    async def test_minus_back(self, mock_execute_script):
        """Test minus back operation."""
        await illustrator_pathfinder_minus_back()
        
        script = mock_execute_script.call_args[0][0]
        assert "Live Pathfinder Back Minus Front" in script


class TestPathfinderIntersect:
    """Tests for pathfinder intersect tool."""
    
    @pytest.mark.asyncio
    async def test_intersect(self, mock_execute_script):
        """Test intersect operation."""
        await illustrator_pathfinder_intersect()
        
        script = mock_execute_script.call_args[0][0]
        assert "Live Pathfinder Intersect" in script


class TestPathfinderExclude:
    """Tests for pathfinder exclude tool."""
    
    @pytest.mark.asyncio
    async def test_exclude(self, mock_execute_script):
        """Test exclude operation."""
        await illustrator_pathfinder_exclude()
        
        script = mock_execute_script.call_args[0][0]
        assert "Live Pathfinder Exclude" in script


class TestPathfinderDivide:
    """Tests for pathfinder divide tool."""
    
    @pytest.mark.asyncio
    async def test_divide(self, mock_execute_script):
        """Test divide operation."""
        await illustrator_pathfinder_divide()
        
        script = mock_execute_script.call_args[0][0]
        assert "Live Pathfinder Divide" in script


class TestPathfinderTrim:
    """Tests for pathfinder trim tool."""
    
    @pytest.mark.asyncio
    async def test_trim(self, mock_execute_script):
        """Test trim operation."""
        await illustrator_pathfinder_trim()
        
        script = mock_execute_script.call_args[0][0]
        assert "Live Pathfinder Trim" in script


class TestPathfinderMerge:
    """Tests for pathfinder merge tool."""
    
    @pytest.mark.asyncio
    async def test_merge(self, mock_execute_script):
        """Test merge operation."""
        await illustrator_pathfinder_merge()
        
        script = mock_execute_script.call_args[0][0]
        assert "Live Pathfinder Merge" in script
