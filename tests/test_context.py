"""
Tests for the context.py module (document state inspection tools).

Tests verify the context tools that help AI understand document state.
"""

import pytest
from unittest.mock import AsyncMock, patch
import json

from illustrator_mcp.tools.context import (
    illustrator_get_document,
    GetDocumentInput,
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
        """Test that document structure is returned (default scope='document')."""
        mock_result = json.dumps({
            "document": {"name": "Test.ai", "width": 800, "height": 600},
            "layers": [{"name": "Layer 1", "visible": True, "items": []}]
        })
        mock_execute.return_value = mock_result

        result = await illustrator_get_document(params=GetDocumentInput())

        mock_execute.assert_called_once()
        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs['command_type'] == "get_document"
        assert call_kwargs['tool_name'] == "illustrator_get_document"

    @pytest.mark.asyncio
    async def test_script_contains_layer_iteration(self, mock_execute):
        """Test that script iterates over layers."""
        mock_execute.return_value = "{}"

        await illustrator_get_document(params=GetDocumentInput())

        script = mock_execute.call_args.kwargs['script']
        assert "doc.layers" in script or "getLayerInfo" in script

    @pytest.mark.asyncio
    async def test_scope_app(self, mock_execute):
        """Test scope='app' returns app info without requiring active document."""
        mock_execute.return_value = json.dumps({
            "name": "Adobe Illustrator",
            "version": "30.0",
            "documentsOpen": 1
        })

        await illustrator_get_document(params=GetDocumentInput(scope="app"))

        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs['command_type'] == "get_app_info"
        assert call_kwargs['tool_name'] == "illustrator_get_document"

    @pytest.mark.asyncio
    async def test_scope_both(self, mock_execute):
        """Test scope='both' returns canonical envelope with {document, app} in result."""
        # execute_jsx_tool returns canonical envelope JSON strings
        mock_execute.side_effect = [
            json.dumps({"ok": True, "result": {"name": "Test.ai"}, "error": None, "warnings": [], "diagnostics": {}}),
            json.dumps({"ok": True, "result": {"name": "Adobe Illustrator", "version": "30.0"}, "error": None, "warnings": [], "diagnostics": {}})
        ]

        result = await illustrator_get_document(params=GetDocumentInput(scope="both"))

        assert mock_execute.call_count == 2
        parsed = json.loads(result)
        # Canonical 5-key envelope
        assert parsed["ok"] is True
        assert "document" in parsed["result"]
        assert "app" in parsed["result"]

    @pytest.mark.asyncio
    async def test_scope_defaults_to_document(self, mock_execute):
        """Test that scope defaults to 'document'."""
        mock_execute.return_value = "{}"

        params = GetDocumentInput()
        assert params.scope == "document"
