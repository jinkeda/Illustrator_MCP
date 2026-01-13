"""
Unit tests for shape drawing tools.

Tests verify that the correct JavaScript is generated for each tool.
"""

import pytest
from unittest.mock import AsyncMock, patch

from illustrator_mcp.tools.shapes import (
    illustrator_draw_rectangle,
    illustrator_draw_ellipse,
    illustrator_draw_polygon,
    illustrator_draw_line,
    illustrator_draw_star,
    DrawRectangleInput,
    DrawEllipseInput,
    DrawPolygonInput,
    DrawLineInput,
    DrawStarInput
)


class TestDrawRectangle:
    """Tests for illustrator_draw_rectangle tool."""
    
    @pytest.mark.asyncio
    async def test_draw_rectangle_basic(self, mock_execute_script):
        """Test basic rectangle drawing."""
        params = DrawRectangleInput(x=100, y=200, width=300, height=150)
        await illustrator_draw_rectangle(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "pathItems.rectangle" in script
        # Y is negated in Illustrator coordinate system
        assert "100" in script  # x position
        assert "300" in script  # width
        assert "150" in script  # height
    
    @pytest.mark.asyncio
    async def test_draw_rectangle_with_corner_radius(self, mock_execute_script):
        """Test rectangle with rounded corners."""
        params = DrawRectangleInput(x=0, y=0, width=100, height=100, corner_radius=10)
        await illustrator_draw_rectangle(params)
        
        script = mock_execute_script.call_args[0][0]
        # Should contain corner radius parameter
        assert "10" in script


class TestDrawEllipse:
    """Tests for illustrator_draw_ellipse tool."""
    
    @pytest.mark.asyncio
    async def test_draw_ellipse_basic(self, mock_execute_script):
        """Test basic ellipse drawing."""
        params = DrawEllipseInput(x=100, y=100, width=200, height=100)
        await illustrator_draw_ellipse(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "pathItems.ellipse" in script
        assert "200" in script  # width
        assert "100" in script  # height
    
    @pytest.mark.asyncio
    async def test_draw_circle(self, mock_execute_script):
        """Test drawing a circle (equal width/height)."""
        params = DrawEllipseInput(x=0, y=0, width=100, height=100)
        await illustrator_draw_ellipse(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "pathItems.ellipse" in script


class TestDrawPolygon:
    """Tests for illustrator_draw_polygon tool."""
    
    @pytest.mark.asyncio
    async def test_draw_polygon_default_sides(self, mock_execute_script):
        """Test polygon with default 6 sides (hexagon)."""
        params = DrawPolygonInput(x=100, y=100, radius=50)
        await illustrator_draw_polygon(params)

        script = mock_execute_script.call_args[0][0]
        assert "pathItems.polygon" in script
        assert "6" in script  # default 6 sides
    
    @pytest.mark.asyncio
    async def test_draw_polygon_triangle(self, mock_execute_script):
        """Test drawing a triangle (3 sides)."""
        params = DrawPolygonInput(x=100, y=100, radius=50, sides=3)
        await illustrator_draw_polygon(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "pathItems.polygon" in script
        assert "3" in script  # number of sides


class TestDrawLine:
    """Tests for illustrator_draw_line tool."""
    
    @pytest.mark.asyncio
    async def test_draw_line(self, mock_execute_script):
        """Test line drawing between two points."""
        params = DrawLineInput(x1=0, y1=0, x2=100, y2=100)
        await illustrator_draw_line(params)
        
        script = mock_execute_script.call_args[0][0]
        # Line uses setEntirePath with two points
        assert "setEntirePath" in script or "pathItems" in script


class TestDrawStar:
    """Tests for illustrator_draw_star tool."""
    
    @pytest.mark.asyncio
    async def test_draw_star_default(self, mock_execute_script):
        """Test star with default parameters."""
        params = DrawStarInput(x=100, y=100, outer_radius=50, inner_radius=25)
        await illustrator_draw_star(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "pathItems.star" in script
        assert "50" in script  # outer radius
        assert "25" in script  # inner radius
    
    @pytest.mark.asyncio
    async def test_draw_star_custom_points(self, mock_execute_script):
        """Test star with custom number of points."""
        params = DrawStarInput(x=0, y=0, outer_radius=100, inner_radius=40, points=8)
        await illustrator_draw_star(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "8" in script  # number of points
