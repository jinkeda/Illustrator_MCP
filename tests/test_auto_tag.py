"""
Tests for auto-tag MCP IDs feature.

Verifies that execute_script can auto-assign @mcp:id= tags
to items created by raw scripts (delta/converge/off modes).
"""

import json
import pytest
from unittest.mock import AsyncMock, patch, call

from illustrator_mcp.tools.execute import (
    ExecuteScriptInput,
    illustrator_execute_script,
    reset_mutation_count,
    _run_auto_tag,
)


@pytest.fixture(autouse=True)
def _reset_vlm_counter():
    """Reset VLM cadence counter before each test."""
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
        mock.side_effect = lambda response=None, **kwargs: json.dumps({
            "result": response.get("result") if isinstance(response, dict) else response,
            "diagnostics": kwargs.get("diagnostics", {}),
            "warnings": kwargs.get("warnings", []),
        })
        yield mock


# ── ExecuteScriptInput field tests ─────────────────────────────────


class TestAutoAssignIdsFields:
    """Verify the new auto_assign_ids fields on ExecuteScriptInput."""

    def test_default_auto_assign_ids_is_delta(self):
        """Default mode should be 'delta' for bounded tagging."""
        inp = ExecuteScriptInput(script="var x = 1;")
        assert inp.auto_assign_ids == "delta"

    def test_default_max_auto_tag(self):
        """Default cap should be 200."""
        inp = ExecuteScriptInput(script="var x = 1;")
        assert inp.max_auto_tag == 200

    def test_default_scope(self):
        """Default scope should be activeLayer."""
        inp = ExecuteScriptInput(script="var x = 1;")
        assert inp.auto_tag_scope == "activeLayer"

    def test_off_mode(self):
        """Can set mode to 'off'."""
        inp = ExecuteScriptInput(script="var x = 1;", auto_assign_ids="off")
        assert inp.auto_assign_ids == "off"

    def test_converge_mode(self):
        """Can set mode to 'converge'."""
        inp = ExecuteScriptInput(script="var x = 1;", auto_assign_ids="converge")
        assert inp.auto_assign_ids == "converge"

    def test_invalid_mode_rejected(self):
        """Invalid mode should be rejected by pydantic."""
        with pytest.raises(Exception):
            ExecuteScriptInput(script="var x = 1;", auto_assign_ids="invalid")

    def test_custom_cap(self):
        """Can override the cap."""
        inp = ExecuteScriptInput(script="var x = 1;", max_auto_tag=50)
        assert inp.max_auto_tag == 50

    def test_document_scope(self):
        """Can scope to full document."""
        inp = ExecuteScriptInput(script="var x = 1;", auto_tag_scope="document")
        assert inp.auto_tag_scope == "document"


# ── _run_auto_tag helper tests ─────────────────────────────────────


class TestRunAutoTag:
    """Test the _run_auto_tag helper function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_script_loading_fails(self):
        """Should return None if load_script raises (e.g., library not found)."""
        with patch(
            'illustrator_mcp.tools.execute.load_script',
            side_effect=ValueError("Library 'auto_tag' not found"),
        ):
            result = await _run_auto_tag(
                mode="delta", scope="activeLayer", cap=200, pre_count=5
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_parsed_result(self):
        """Should parse and return the JSX result."""
        tag_result = {
            "tagged": 3,
            "cap_hit": False,
            "need": 5,
            "skipped": {"locked": 0, "error": 0},
            "assigned": [
                {"id": "mcp_123", "typename": "PathItem", "name": "rect", "layerName": "Layer 1"},
            ],
            "errors": [],
        }
        with patch(
            'illustrator_mcp.tools.execute.load_script',
            return_value="(function(){ return '{}'; })()",
        ), patch(
            'illustrator_mcp.tools.execute.execute_script_with_context',
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_exec.return_value = {"result": json.dumps(tag_result)}

            result = await _run_auto_tag(
                mode="delta", scope="activeLayer", cap=200, pre_count=5
            )
            assert result is not None
            assert result["tagged"] == 3
            assert result["cap_hit"] is False

    @pytest.mark.asyncio
    async def test_returns_none_on_exec_failure(self):
        """Should return None if JSX execution fails."""
        with patch(
            'illustrator_mcp.tools.execute.load_script',
            return_value="(function(){})()",
        ), patch(
            'illustrator_mcp.tools.execute.execute_script_with_context',
            new_callable=AsyncMock,
            side_effect=Exception("Bridge timeout"),
        ):
            result = await _run_auto_tag(
                mode="delta", scope="activeLayer", cap=200, pre_count=5
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_load_script_called_with_correct_params(self):
        """Regression: verify load_script receives 'auto_tag' name and params dict."""
        with patch(
            'illustrator_mcp.tools.execute.load_script',
            return_value="(function(){})()",
        ) as mock_load, patch(
            'illustrator_mcp.tools.execute.execute_script_with_context',
            new_callable=AsyncMock,
            return_value={"result": json.dumps({"tagged": 0, "assigned": []})},
        ):
            await _run_auto_tag(
                mode="delta", scope="activeLayer", cap=100, pre_count=5, cushion=3,
            )
            mock_load.assert_called_once_with("auto_tag", params={
                "mode": "delta",
                "scope": "activeLayer",
                "cap": 100,
                "preCount": 5,
                "cushion": 3,
            })


# ── Integration tests: execute_script with auto-tag ────────────────


class TestAutoTagIntegration:
    """Test auto-tag behavior within execute_script flow."""

    @pytest.mark.asyncio
    async def test_off_mode_skips_all_scanning(self, mock_execute, mock_format):
        """With auto_assign_ids='off', only the user script is executed."""
        mock_execute.return_value = {"result": "done"}

        await illustrator_execute_script(
            ExecuteScriptInput(script="var x = 1;", auto_assign_ids="off")
        )

        # Should be called exactly once (user script only, no precount, no auto_tag)
        assert mock_execute.call_count == 1
        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs['command_type'] != "auto_tag_precount"

    @pytest.mark.asyncio
    async def test_delta_captures_precount(self, mock_execute, mock_format):
        """Delta mode should execute a pre-count script before the user script."""
        mock_execute.return_value = {"result": json.dumps({"count": 5})}

        await illustrator_execute_script(
            ExecuteScriptInput(script="var x = 1;", auto_assign_ids="delta")
        )

        # First call should be pre-count
        assert mock_execute.call_count >= 2
        first_call = mock_execute.call_args_list[0]
        assert first_call.kwargs['command_type'] == "auto_tag_precount"

    @pytest.mark.asyncio
    async def test_delta_skips_on_zero_delta(self, mock_execute, mock_format):
        """Delta mode should skip auto-tag scan when pre-count == post-count."""
        # Pre-count returns 5
        precount_result = {"result": json.dumps({"count": 5})}
        # User script returns success
        script_result = {"result": "done"}

        # auto_tag.jsx would also see count 5 (no new items)
        # But the delta check happens INSIDE auto_tag.jsx which gets
        # preCount=5 as a param. The JSX computes need=min(cap, 5-5+2)=2
        # and returns tagged=0 if no untagged items found.
        auto_tag_result = {"result": json.dumps({
            "tagged": 0, "cap_hit": False, "need": 2,
            "skipped": {"locked": 0, "error": 0},
            "assigned": [], "errors": []
        })}

        mock_execute.side_effect = [precount_result, script_result, auto_tag_result]

        result = await illustrator_execute_script(
            ExecuteScriptInput(script="var x = 1;", auto_assign_ids="delta")
        )

        # Parse result to check diagnostics
        result_data = json.loads(result) if isinstance(result, str) else result
        auto_tag = result_data.get("diagnostics", {}).get("auto_assign_ids", {})
        assert auto_tag.get("tagged", 0) == 0

    @pytest.mark.asyncio
    async def test_delta_tags_new_items(self, mock_execute, mock_format):
        """Delta mode should tag newly created items."""
        precount_result = {"result": json.dumps({"count": 3})}
        script_result = {"result": "created rect"}
        auto_tag_result = {"result": json.dumps({
            "tagged": 2, "cap_hit": False, "need": 4,
            "skipped": {"locked": 0, "error": 0},
            "assigned": [
                {"id": "mcp_1", "typename": "PathItem", "name": "rect1", "layerName": "Layer 1"},
                {"id": "mcp_2", "typename": "PathItem", "name": "rect2", "layerName": "Layer 1"},
            ],
            "errors": []
        })}

        mock_execute.side_effect = [precount_result, script_result, auto_tag_result]

        result = await illustrator_execute_script(
            ExecuteScriptInput(script="doc.pathItems.rectangle(-100, 50, 200, 100);")
        )

        result_data = json.loads(result) if isinstance(result, str) else result
        auto_tag = result_data.get("diagnostics", {}).get("auto_assign_ids", {})
        assert auto_tag.get("tagged", 0) == 2
        assert len(auto_tag.get("assigned", [])) == 2

    @pytest.mark.asyncio
    async def test_cap_hit_warning(self, mock_execute, mock_format):
        """Cap hit should produce a warning."""
        precount_result = {"result": json.dumps({"count": 0})}
        script_result = {"result": "bulk create"}
        auto_tag_result = {"result": json.dumps({
            "tagged": 200, "cap_hit": True, "need": 200,
            "skipped": {"locked": 0, "error": 0},
            "assigned": [{"id": f"mcp_{i}", "typename": "PathItem", "name": f"item_{i}", "layerName": "Layer 1"} for i in range(200)],
            "errors": []
        })}

        mock_execute.side_effect = [precount_result, script_result, auto_tag_result]

        await illustrator_execute_script(
            ExecuteScriptInput(script="// bulk create script")
        )

        # Check that format_envelope was called with a cap hit warning
        last_call_kwargs = mock_format.call_args_list[-1].kwargs
        warnings = last_call_kwargs.get("warnings", [])
        assert any("cap hit" in w.lower() for w in warnings), f"Expected cap hit warning in {warnings}"

    @pytest.mark.asyncio
    async def test_converge_mode_scans_regardless_of_delta(self, mock_execute, mock_format):
        """Converge mode should always run auto-tag scan, even if delta == 0."""
        precount_result = {"result": json.dumps({"count": 10})}
        script_result = {"result": "done"}  # no new items
        auto_tag_result = {"result": json.dumps({
            "tagged": 5, "cap_hit": False, "need": 200,
            "skipped": {"locked": 0, "error": 0},
            "assigned": [{"id": f"mcp_{i}", "typename": "PathItem", "name": f"old_{i}", "layerName": "Layer 1"} for i in range(5)],
            "errors": []
        })}

        mock_execute.side_effect = [precount_result, script_result, auto_tag_result]

        result = await illustrator_execute_script(
            ExecuteScriptInput(script="var x = 1;", auto_assign_ids="converge")
        )

        # auto_tag should have been called (3 calls total)
        assert mock_execute.call_count == 3
        third_call = mock_execute.call_args_list[2]
        assert third_call.kwargs['command_type'] == "auto_tag"

    @pytest.mark.asyncio
    async def test_auto_tag_error_handling(self, mock_execute, mock_format):
        """Errors from auto_tag should be surfaced in diagnostics."""
        precount_result = {"result": json.dumps({"count": 0})}
        script_result = {"result": "done"}
        auto_tag_result = {"result": json.dumps({
            "tagged": 3, "cap_hit": False, "need": 5,
            "skipped": {"locked": 2, "error": 1},
            "assigned": [{"id": "mcp_1", "typename": "PathItem", "name": "r", "layerName": "L1"}],
            "errors": ["Cannot modify locked item 'bg_rect'"]
        })}

        mock_execute.side_effect = [precount_result, script_result, auto_tag_result]

        result = await illustrator_execute_script(
            ExecuteScriptInput(script="// create stuff")
        )

        result_data = json.loads(result) if isinstance(result, str) else result
        auto_tag = result_data.get("diagnostics", {}).get("auto_assign_ids", {})
        assert auto_tag.get("skipped", {}).get("locked") == 2
        assert len(auto_tag.get("errors", [])) == 1

    @pytest.mark.asyncio
    async def test_precount_failure_skips_autotag(self, mock_execute, mock_format):
        """If pre-count fails, auto-tag should be skipped gracefully."""
        # First call (precount) fails, second call (user script) succeeds
        mock_execute.side_effect = [
            Exception("No active document"),
            {"result": "done"},
        ]

        # Should not raise — graceful degradation
        result = await illustrator_execute_script(
            ExecuteScriptInput(script="var x = 1;", auto_assign_ids="delta")
        )

        # Should still return a result (precount failure is non-fatal)
        assert result is not None
