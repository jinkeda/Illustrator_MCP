"""
Unit tests for document operation tools.

Tests verify that the correct JavaScript is generated for each tool.
"""

import pytest
from unittest.mock import AsyncMock, patch

from illustrator_mcp.tools.documents import (
    illustrator_document,
    illustrator_export_document,
    DocumentInput,
    ExportDocumentInput,
    ExportFormat
)


class TestDocument:
    """Tests for the unified illustrator_document tool."""

    # ---- create action ----

    @pytest.mark.asyncio
    async def test_create_default_params(self, mock_execute_script):
        """Test document creation with default parameters."""
        params = DocumentInput(action="create")
        await illustrator_document(params)

        mock_execute_script.assert_called_once()
        script = mock_execute_script.call_args.kwargs['script']
        assert "preset.width = 800" in script
        assert "preset.height = 600" in script
        assert "DocumentColorSpace.RGB" in script

    @pytest.mark.asyncio
    async def test_create_custom_size(self, mock_execute_script):
        """Test document creation with custom dimensions."""
        params = DocumentInput(action="create", width=1920, height=1080)
        await illustrator_document(params)

        script = mock_execute_script.call_args.kwargs['script']
        assert "preset.width = 1920" in script
        assert "preset.height = 1080" in script

    @pytest.mark.asyncio
    async def test_create_cmyk(self, mock_execute_script):
        """Test document creation in CMYK color mode."""
        params = DocumentInput(action="create", color_mode="CMYK")
        await illustrator_document(params)

        script = mock_execute_script.call_args.kwargs['script']
        assert "DocumentColorSpace.CMYK" in script

    @pytest.mark.asyncio
    async def test_create_with_name(self, mock_execute_script):
        """Test document creation with custom name."""
        params = DocumentInput(action="create", name="My Design")
        await illustrator_document(params)

        script = mock_execute_script.call_args.kwargs['script']
        assert 'preset.title = "My Design"' in script

    # ---- open action ----

    @pytest.mark.asyncio
    async def test_open_document_path(self, mock_execute_script):
        """Test opening document with file path."""
        params = DocumentInput(action="open", file_path="C:/designs/logo.ai")
        await illustrator_document(params)

        script = mock_execute_script.call_args.kwargs['script']
        assert "C:/designs/logo.ai" in script
        assert "new File" in script
        assert "app.open" in script

    @pytest.mark.asyncio
    async def test_open_document_backslash_escape(self, mock_execute_script):
        """Test that backslashes are properly escaped."""
        params = DocumentInput(action="open", file_path="C:\\Users\\test\\design.ai")
        await illustrator_document(params)

        script = mock_execute_script.call_args.kwargs['script']
        assert "\\\\" in script or "/" in script

    def test_open_requires_file_path(self):
        """Test that open action requires file_path."""
        with pytest.raises(ValueError, match="file_path is required"):
            DocumentInput(action="open")

    # ---- save action ----

    @pytest.mark.asyncio
    async def test_save_simple(self, mock_execute_script):
        """Test save without path (in-place save)."""
        params = DocumentInput(action="save")
        await illustrator_document(params)

        script = mock_execute_script.call_args.kwargs['script']
        assert "doc.save()" in script

    @pytest.mark.asyncio
    async def test_save_as(self, mock_execute_script):
        """Test save-as with file path."""
        params = DocumentInput(action="save", file_path="C:/output.ai")
        await illustrator_document(params)

        script = mock_execute_script.call_args.kwargs['script']
        assert "doc.saveAs" in script
        assert "C:/output.ai" in script

    # ---- close action ----

    @pytest.mark.asyncio
    async def test_close_without_save(self, mock_execute_script):
        """Test closing document without saving."""
        params = DocumentInput(action="close", save_before_close=False)
        await illustrator_document(params)

        script = mock_execute_script.call_args.kwargs['script']
        assert "SaveOptions.DONOTSAVECHANGES" in script

    @pytest.mark.asyncio
    async def test_close_with_save(self, mock_execute_script):
        """Test closing document with save."""
        params = DocumentInput(action="close", save_before_close=True)
        await illustrator_document(params)

        script = mock_execute_script.call_args.kwargs['script']
        assert "SaveOptions.SAVECHANGES" in script


class TestExportDocument:
    """Tests for illustrator_export_document tool.

    export_document calls execute_script_with_context directly (not execute_jsx_tool),
    so we use a dedicated fixture.
    """

    @pytest.fixture
    def mock_esc(self):
        """Mock execute_script_with_context and format_envelope for export tests."""
        from unittest.mock import MagicMock
        esc_mock = AsyncMock(return_value={"result": '{"success": true}'})
        fmt_mock = MagicMock(return_value='{"success": true}')
        with patch('illustrator_mcp.tools.documents.execute_script_with_context', esc_mock), \
             patch('illustrator_mcp.tools.documents.format_envelope', fmt_mock):
            yield esc_mock

    @pytest.mark.asyncio
    async def test_export_png(self, mock_esc):
        """Test PNG export."""
        params = ExportDocumentInput(file_path="C:/output/image.png", format=ExportFormat.PNG)
        await illustrator_export_document(params)

        for call in mock_esc.call_args_list:
            if call.kwargs.get('command_type') == 'export_document':
                script = call.kwargs['script']
                assert "ExportOptionsPNG24" in script
                assert "ExportType.PNG24" in script
                return
        script = mock_esc.call_args.kwargs['script']
        assert "ExportOptionsPNG24" in script

    @pytest.mark.asyncio
    async def test_export_jpg(self, mock_esc):
        """Test JPG export."""
        params = ExportDocumentInput(file_path="C:/output/image.jpg", format=ExportFormat.JPG)
        await illustrator_export_document(params)

        for call in mock_esc.call_args_list:
            if call.kwargs.get('command_type') == 'export_document':
                script = call.kwargs['script']
                assert "ExportOptionsJPEG" in script
                assert "ExportType.JPEG" in script
                return
        script = mock_esc.call_args.kwargs['script']
        assert "ExportOptionsJPEG" in script

    @pytest.mark.asyncio
    async def test_export_svg(self, mock_esc):
        """Test SVG export."""
        params = ExportDocumentInput(file_path="C:/output/image.svg", format=ExportFormat.SVG)
        await illustrator_export_document(params)

        for call in mock_esc.call_args_list:
            if call.kwargs.get('command_type') == 'export_document':
                script = call.kwargs['script']
                assert "ExportOptionsSVG" in script
                assert "ExportType.SVG" in script
                return
        script = mock_esc.call_args.kwargs['script']
        assert "ExportOptionsSVG" in script

    @pytest.mark.asyncio
    async def test_export_with_scale(self, mock_esc):
        """Test export with custom scale."""
        params = ExportDocumentInput(file_path="C:/output/image.png", scale=2.0)
        await illustrator_export_document(params)

        for call in mock_esc.call_args_list:
            if call.kwargs.get('command_type') == 'export_document':
                script = call.kwargs['script']
                assert "horizontalScale = 200" in script
                assert "verticalScale = 200" in script
                return
        script = mock_esc.call_args.kwargs['script']
        assert "horizontalScale = 200" in script
