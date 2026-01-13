"""
Unit tests for document operation tools.

Tests verify that the correct JavaScript is generated for each tool.
"""

import pytest
from unittest.mock import AsyncMock, patch

from illustrator_mcp.tools.documents import (
    illustrator_create_document,
    illustrator_open_document,
    illustrator_save_document,
    illustrator_export_document,
    illustrator_get_document_info,
    illustrator_close_document,
    illustrator_import_image,
    CreateDocumentInput,
    OpenDocumentInput,
    SaveDocumentInput,
    ExportDocumentInput,
    CloseDocumentInput,
    ImportImageInput,
    ExportFormat
)


class TestCreateDocument:
    """Tests for illustrator_create_document tool."""
    
    @pytest.mark.asyncio
    async def test_create_document_default_params(self, mock_execute_script):
        """Test document creation with default parameters."""
        params = CreateDocumentInput()
        await illustrator_create_document(params)
        
        # Verify execute_script was called
        mock_execute_script.assert_called_once()
        script = mock_execute_script.call_args[0][0]
        
        # Verify script contains expected values
        assert "preset.width = 800" in script
        assert "preset.height = 600" in script
        assert "DocumentColorSpace.RGB" in script
    
    @pytest.mark.asyncio
    async def test_create_document_custom_size(self, mock_execute_script):
        """Test document creation with custom dimensions."""
        params = CreateDocumentInput(width=1920, height=1080)
        await illustrator_create_document(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "preset.width = 1920" in script
        assert "preset.height = 1080" in script
    
    @pytest.mark.asyncio
    async def test_create_document_cmyk(self, mock_execute_script):
        """Test document creation in CMYK color mode."""
        params = CreateDocumentInput(color_mode="CMYK")
        await illustrator_create_document(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "DocumentColorSpace.CMYK" in script
    
    @pytest.mark.asyncio
    async def test_create_document_with_name(self, mock_execute_script):
        """Test document creation with custom name."""
        params = CreateDocumentInput(name="My Design")
        await illustrator_create_document(params)
        
        script = mock_execute_script.call_args[0][0]
        assert 'preset.title = "My Design"' in script


class TestOpenDocument:
    """Tests for illustrator_open_document tool."""
    
    @pytest.mark.asyncio
    async def test_open_document_path(self, mock_execute_script):
        """Test opening document with file path."""
        params = OpenDocumentInput(file_path="C:/designs/logo.ai")
        await illustrator_open_document(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "C:/designs/logo.ai" in script
        assert "new File" in script
        assert "app.open" in script
    
    @pytest.mark.asyncio
    async def test_open_document_backslash_escape(self, mock_execute_script):
        """Test that backslashes are properly escaped."""
        params = OpenDocumentInput(file_path="C:\\Users\\test\\design.ai")
        await illustrator_open_document(params)
        
        script = mock_execute_script.call_args[0][0]
        # Backslashes should be doubled for JavaScript
        assert "\\\\" in script or "/" in script


class TestExportDocument:
    """Tests for illustrator_export_document tool."""
    
    @pytest.mark.asyncio
    async def test_export_png(self, mock_execute_script):
        """Test PNG export."""
        params = ExportDocumentInput(file_path="C:/output/image.png", format=ExportFormat.PNG)
        await illustrator_export_document(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "ExportOptionsPNG24" in script
        assert "ExportType.PNG24" in script
    
    @pytest.mark.asyncio
    async def test_export_jpg(self, mock_execute_script):
        """Test JPG export."""
        params = ExportDocumentInput(file_path="C:/output/image.jpg", format=ExportFormat.JPG)
        await illustrator_export_document(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "ExportOptionsJPEG" in script
        assert "ExportType.JPEG" in script
    
    @pytest.mark.asyncio
    async def test_export_svg(self, mock_execute_script):
        """Test SVG export."""
        params = ExportDocumentInput(file_path="C:/output/image.svg", format=ExportFormat.SVG)
        await illustrator_export_document(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "ExportOptionsSVG" in script
        assert "ExportType.SVG" in script
    
    @pytest.mark.asyncio
    async def test_export_with_scale(self, mock_execute_script):
        """Test export with custom scale."""
        params = ExportDocumentInput(file_path="C:/output/image.png", scale=2.0)
        await illustrator_export_document(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "horizontalScale = 200" in script
        assert "verticalScale = 200" in script


class TestImportImage:
    """Tests for illustrator_import_image tool."""
    
    @pytest.mark.asyncio
    async def test_import_image_linked(self, mock_execute_script):
        """Test importing image as linked."""
        params = ImportImageInput(file_path="C:/images/photo.jpg", x=100, y=200, link=True)
        await illustrator_import_image(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "placedItems.add()" in script
        assert "placed.file = file" in script
        assert "placed.left = 100" in script
        # Should NOT contain embed() for linked images
        assert "embed()" not in script
    
    @pytest.mark.asyncio
    async def test_import_image_embedded(self, mock_execute_script):
        """Test importing image as embedded."""
        params = ImportImageInput(file_path="C:/images/photo.jpg", link=False)
        await illustrator_import_image(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "placed.embed();" in script


class TestCloseDocument:
    """Tests for illustrator_close_document tool."""
    
    @pytest.mark.asyncio
    async def test_close_without_save(self, mock_execute_script):
        """Test closing document without saving."""
        params = CloseDocumentInput(save_before_close=False)
        await illustrator_close_document(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "SaveOptions.DONOTSAVECHANGES" in script
    
    @pytest.mark.asyncio
    async def test_close_with_save(self, mock_execute_script):
        """Test closing document with save."""
        params = CloseDocumentInput(save_before_close=True)
        await illustrator_close_document(params)
        
        script = mock_execute_script.call_args[0][0]
        assert "SaveOptions.SAVECHANGES" in script


class TestGetDocumentInfo:
    """Tests for illustrator_get_document_info tool."""
    
    @pytest.mark.asyncio
    async def test_get_document_info_script(self, mock_execute_script):
        """Test document info retrieval script."""
        await illustrator_get_document_info()
        
        script = mock_execute_script.call_args[0][0]
        assert "app.activeDocument" in script
        assert "doc.name" in script
        assert "doc.width" in script
        assert "doc.height" in script
        assert "documentColorSpace" in script
