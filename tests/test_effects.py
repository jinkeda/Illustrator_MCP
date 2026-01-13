"""
Unit tests for effects and gradient tools.

Tests verify that the correct JavaScript is generated for each tool.
"""

import pytest
from unittest.mock import AsyncMock, patch

from illustrator_mcp.tools.effects import (
    illustrator_apply_drop_shadow,
    illustrator_apply_blur,
    illustrator_apply_inner_glow,
    illustrator_apply_outer_glow,
    illustrator_clear_effects,
    illustrator_apply_linear_gradient,
    illustrator_apply_radial_gradient,
    DropShadowInput,
    BlurInput,
    GlowInput,
    GradientInput,
    RadialGradientInput
)


class TestDropShadow:
    """Tests for drop shadow effect."""
    
    @pytest.mark.asyncio
    async def test_drop_shadow_default(self, mock_execute_script):
        """Test drop shadow with defaults."""
        params = DropShadowInput()
        await illustrator_apply_drop_shadow(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "Adobe Drop Shadow" in script


class TestBlur:
    """Tests for blur effect."""
    
    @pytest.mark.asyncio
    async def test_gaussian_blur(self, mock_execute_script):
        """Test Gaussian blur."""
        params = BlurInput(radius=10)
        await illustrator_apply_blur(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "Adobe Gaussian Blur" in script


class TestGlow:
    """Tests for glow effects."""
    
    @pytest.mark.asyncio
    async def test_inner_glow(self, mock_execute_script):
        """Test inner glow."""
        params = GlowInput(blur=5, opacity=75)
        await illustrator_apply_inner_glow(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "Adobe Inner Glow" in script
    
    @pytest.mark.asyncio
    async def test_outer_glow(self, mock_execute_script):
        """Test outer glow."""
        params = GlowInput(blur=10, opacity=50)
        await illustrator_apply_outer_glow(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "Adobe Outer Glow" in script


class TestClearEffects:
    """Tests for clear effects."""
    
    @pytest.mark.asyncio
    async def test_clear_effects(self, mock_execute_script):
        """Test clearing all effects."""
        await illustrator_clear_effects()
        
        script = mock_execute_script.call_args[0][0]
        assert "Clear Appearance" in script


class TestLinearGradient:
    """Tests for linear gradient."""
    
    @pytest.mark.asyncio
    async def test_linear_gradient_red_to_blue(self, mock_execute_script):
        """Test linear gradient from red to blue."""
        params = GradientInput(
            start_r=255, start_g=0, start_b=0,
            end_r=0, end_g=0, end_b=255,
            angle=45
        )
        await illustrator_apply_linear_gradient(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "GradientType.LINEAR" in script
        assert "gradients.add()" in script
        assert "startColor.red = 255" in script
        assert "endColor.blue = 255" in script


class TestRadialGradient:
    """Tests for radial gradient."""
    
    @pytest.mark.asyncio
    async def test_radial_gradient_white_to_black(self, mock_execute_script):
        """Test radial gradient from white to black."""
        params = RadialGradientInput(
            start_r=255, start_g=255, start_b=255,
            end_r=0, end_g=0, end_b=0
        )
        await illustrator_apply_radial_gradient(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "GradientType.RADIAL" in script
        assert "gradients.add()" in script
