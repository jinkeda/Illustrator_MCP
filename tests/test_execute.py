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


# ── Canary tests for phase refactor invariants ─────────────────────


class TestPhaseRefactorInvariants:
    """Canary tests ensuring post-execution hooks run exactly once."""

    @pytest.fixture
    def mock_execute(self):
        """Mock execute_script_with_context."""
        with patch('illustrator_mcp.tools.execute.execute_script_with_context') as m:
            yield m

    @pytest.fixture
    def mock_format(self):
        """Mock format_envelope."""
        with patch('illustrator_mcp.tools.execute.format_envelope') as m:
            m.return_value = '{"ok": true}'
            yield m

    @pytest.mark.asyncio
    async def test_guard_abort_still_runs_auto_tag(self, mock_execute, mock_format):
        """Canary: auto-tag must run even when guard aborts.

        Pre-refactor bug: guard abort returned early before auto-tag.
        """
        from dataclasses import dataclass, field
        from illustrator_mcp.tools.preview import GuardCheckpointResult

        # Guard will abort
        abort_gcp = GuardCheckpointResult(
            guard_result=None,
            guard_telemetry={},
            should_abort=True,
            guard_status="aborted",
            abort_message="Occlusion detected",
            diag_extras={"occlusion": True},
            warn_messages=[],
        )

        mock_execute.return_value = {"result": "done"}

        with patch(
            'illustrator_mcp.tools.execute._guard_checkpoint',
            new_callable=AsyncMock,
            return_value=abort_gcp,
        ), patch(
            'illustrator_mcp.tools.execute._run_auto_tag',
            new_callable=AsyncMock,
            return_value={"tagged": 2, "cap_hit": False, "assigned": []},
        ) as mock_auto_tag, patch(
            'illustrator_mcp.tools.execute._generate_preview',
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            'illustrator_mcp.tools.execute.VLM_QA_CADENCE', 1,  # Force checkpoint
        ):
            result = await illustrator_execute_script(
                ExecuteScriptInput(
                    script="var x = 1;",
                    auto_assign_ids="delta",
                )
            )

            # Auto-tag must have been called despite guard abort
            assert mock_auto_tag.called, (
                "auto_tag must run even when guard aborts"
            )
            # The diagnostics in the envelope should contain auto-tag info
            format_call = mock_format.call_args
            diagnostics = format_call.kwargs.get('diagnostics', {})
            assert "auto_assign_ids" in diagnostics, (
                "auto_tag diagnostics must appear in envelope even on guard abort"
            )

    @pytest.mark.asyncio
    async def test_counter_decrement_on_exception(self, mock_execute, mock_format):
        """Canary: counter must decrement even when execution throws.

        Ensures try/finally safety prevents counter leaks.
        """
        from illustrator_mcp.tools.cadence import _counter

        initial = _counter.value
        mock_execute.side_effect = Exception("Bridge timeout")

        with pytest.raises(Exception, match="Bridge timeout"):
            await illustrator_execute_script(
                ExecuteScriptInput(script="crash();")
            )

        # Counter must be back to initial (increment + decrement in finally)
        assert _counter.value == initial, (
            f"Counter leaked: was {initial}, now {_counter.value}"
        )
