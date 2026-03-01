"""
Tests for the execute.py module (core script execution).

These tests verify the PRIMARY tool of the MCP - illustrator_execute_script.
"""

import pytest
from unittest.mock import AsyncMock, patch

from illustrator_mcp.tools.execute import (
    illustrator_execute_script,
    ExecuteScriptInput,
    reset_mutation_count,
)


@pytest.fixture(autouse=True)
def _reset_vlm_counter():
    """Reset VLM cadence counter before each test to prevent cross-test pollution."""
    reset_mutation_count()
    yield
    reset_mutation_count()


@pytest.fixture
def mock_execute():
    """Mock the execute_script_with_context function."""
    with patch('illustrator_mcp.tools.execute.execute_script_with_context') as mock:
        yield mock


@pytest.fixture
def mock_format():
    """Mock the format_envelope function."""
    with patch('illustrator_mcp.tools.execute.format_envelope') as mock:
        mock.side_effect = lambda response=None, **kwargs: str(response.get('result', response)) if isinstance(response, dict) else str(response)
        yield mock


class TestExecuteScriptInput:
    """Tests for input validation."""
    
    def test_valid_script(self):
        """Test valid script input."""
        input_data = ExecuteScriptInput(script="var x = 1;")
        assert input_data.script == "var x = 1;"
        assert input_data.description == ""
    
    def test_script_with_description(self):
        """Test script with description."""
        input_data = ExecuteScriptInput(
            script="var doc = app.activeDocument;",
            description="Get active document"
        )
        assert input_data.description == "Get active document"
    
    def test_empty_script_fails(self):
        """Test that empty script is rejected."""
        with pytest.raises(ValueError):
            ExecuteScriptInput(script="")
    
    def test_whitespace_only_fails(self):
        """Test that whitespace-only script is rejected after stripping."""
        with pytest.raises(ValueError):
            ExecuteScriptInput(script="   ")


class TestExecuteScript:
    """Tests for the execute_script tool."""
    
    @pytest.mark.asyncio
    async def test_simple_script(self, mock_execute, mock_format):
        """Test executing a simple script."""
        mock_execute.return_value = {"result": "success"}
        
        result = await illustrator_execute_script(
            ExecuteScriptInput(script="alert('test');")
        )
        
        # Find the user script call (not the auto_tag precount call)
        user_calls = [
            c for c in mock_execute.call_args_list
            if c.kwargs.get('command_type') != 'auto_tag_precount'
               and c.kwargs.get('command_type') != 'auto_tag'
        ]
        assert len(user_calls) >= 1, "Expected at least one user script call"
        call_kwargs = user_calls[0].kwargs
        assert call_kwargs['script'] == "alert('test');"
        assert call_kwargs['tool_name'] == "illustrator_execute_script"
    
    @pytest.mark.asyncio
    async def test_script_with_description(self, mock_execute, mock_format):
        """Test that description is passed to command_type."""
        mock_execute.return_value = {"result": "done"}
        
        await illustrator_execute_script(
            ExecuteScriptInput(
                script="doc.pathItems.rectangle(-100, 50, 200, 100);",
                description="Draw rectangle"
            )
        )
        
        # Find the user script call (not auto_tag internal calls)
        user_calls = [
            c for c in mock_execute.call_args_list
            if c.kwargs.get('command_type') not in ('auto_tag_precount', 'auto_tag')
        ]
        call_kwargs = user_calls[0].kwargs
        assert call_kwargs['command_type'] == "Draw rectangle"
    
    @pytest.mark.asyncio
    async def test_multiline_script(self, mock_execute, mock_format):
        """Test multiline script execution."""
        mock_execute.return_value = {"result": "created"}
        
        script = """
        var doc = app.activeDocument;
        var rect = doc.pathItems.rectangle(-100, 50, 200, 100);
        var c = new RGBColor();
        c.red = 255;
        rect.fillColor = c;
        """
        
        await illustrator_execute_script(ExecuteScriptInput(script=script))
        
        # Find the user script call (not auto_tag internal calls)
        user_calls = [
            c for c in mock_execute.call_args_list
            if c.kwargs.get('command_type') not in ('auto_tag_precount', 'auto_tag')
        ]
        call_kwargs = user_calls[0].kwargs
        assert "pathItems.rectangle" in call_kwargs['script']
    
    @pytest.mark.asyncio
    async def test_error_handling(self, mock_execute, mock_format):
        """Test error handling in script execution."""
        mock_execute.side_effect = Exception("Connection failed")
        
        with pytest.raises(Exception) as exc_info:
            await illustrator_execute_script(
                ExecuteScriptInput(script="invalid();")
            )
        
        assert "Connection failed" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_script_result_formatting(self, mock_execute, mock_format):
        """Test that results are properly formatted."""
        mock_execute.return_value = {"result": '{"success": true, "count": 5}'}
        mock_format.return_value = '{"success": true, "count": 5}'
        
        result = await illustrator_execute_script(
            ExecuteScriptInput(script="JSON.stringify({success: true, count: 5});")
        )
        
        assert "success" in result
        mock_format.assert_called()
