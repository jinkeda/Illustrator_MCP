"""
Tests for Issue #6: Reference resources and injection observability.

Tests:
- Library catalog generation
- Enriched injection metadata
- Deterministic prelude hash
- MCP resource registration
"""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ==================== Catalog Tests ====================

class TestLibraryCatalog:
    """Tests for library catalog generation from manifest."""

    def test_catalog_includes_non_deprecated_libraries(self):
        """Catalog should include active libraries and exclude deprecated ones."""
        from illustrator_mcp.tools.context import _generate_library_catalog

        catalog = _generate_library_catalog()

        # Active libraries should appear
        assert "`geometry`" in catalog
        assert "`layout`" in catalog
        assert "`selection`" in catalog

        # Deprecated libraries should NOT appear
        assert "### `task_executor`" not in catalog
        assert "### `op_schemas`" not in catalog

    def test_catalog_shows_version(self):
        """Each library entry should include its version."""
        from illustrator_mcp.tools.context import _generate_library_catalog

        catalog = _generate_library_catalog()

        # Check version format
        assert "v2.0.0" in catalog  # geometry
        assert "v1.0.0" in catalog  # selection

    def test_catalog_shows_exports(self):
        """Library entries should list their exports."""
        from illustrator_mcp.tools.context import _generate_library_catalog

        catalog = _generate_library_catalog()

        assert "getContext" in catalog  # geometry export
        assert "arrangeInGrid" in catalog  # layout export

    def test_catalog_truncates_long_exports(self):
        """Libraries with 8+ exports should show truncation marker."""
        from illustrator_mcp.tools.context import _generate_library_catalog

        catalog = _generate_library_catalog()

        # generative has 22 exports, should show "more"
        assert "more)" in catalog

    def test_catalog_categories(self):
        """Libraries should be grouped by category."""
        from illustrator_mcp.tools.context import _generate_library_catalog

        catalog = _generate_library_catalog()

        assert "## Geometry & Layout" in catalog
        assert "## SOC Operations" in catalog

    def test_catalog_manifest_version(self):
        """Catalog header should show manifest version."""
        from illustrator_mcp.tools.context import _generate_library_catalog

        catalog = _generate_library_catalog()

        assert "manifest v" in catalog

    def test_catalog_handles_missing_manifest(self):
        """Catalog should return fallback text if manifest not found."""
        from illustrator_mcp.tools.context import _generate_library_catalog, _MANIFEST_PATH

        with patch.object(Path, 'read_text', side_effect=FileNotFoundError):
            catalog = _generate_library_catalog()
            assert "No libraries found" in catalog


# ==================== Enriched Metadata Tests ====================

class TestEnrichedMetadata:
    """Tests for enriched library injection metadata."""

    def test_metadata_has_requested_vs_resolved(self):
        """Metadata should distinguish requested from resolved includes."""
        from illustrator_mcp.libraries import get_injection_metadata

        # layout depends on geometry — requesting layout should resolve geometry too
        meta = get_injection_metadata(["layout"])

        assert "includes_requested" in meta
        assert "includes_resolved" in meta
        assert meta["includes_requested"] == ["layout"]
        assert "geometry" in meta["includes_resolved"]
        assert "layout" in meta["includes_resolved"]
        # geometry should come before layout in resolved order
        geom_idx = meta["includes_resolved"].index("geometry")
        layout_idx = meta["includes_resolved"].index("layout")
        assert geom_idx < layout_idx

    def test_metadata_has_library_versions(self):
        """Metadata should include per-library version strings."""
        from illustrator_mcp.libraries import get_injection_metadata

        meta = get_injection_metadata(["geometry"])

        assert "library_versions" in meta
        assert "geometry" in meta["library_versions"]
        # Version should be a semver-like string
        assert meta["library_versions"]["geometry"].count(".") == 2

    def test_metadata_has_manifest_version(self):
        """Metadata should include the manifest version."""
        from illustrator_mcp.libraries import get_injection_metadata

        meta = get_injection_metadata(["geometry"])

        assert "manifest_version" in meta
        assert meta["manifest_version"] is not None
        assert meta["manifest_version"].count(".") == 2  # e.g. "3.0.0"

    def test_metadata_has_prelude_length(self):
        """Metadata should include prelude_length in bytes."""
        from illustrator_mcp.libraries import get_injection_metadata

        meta = get_injection_metadata(["geometry"])

        assert "prelude_length" in meta
        assert isinstance(meta["prelude_length"], int)
        assert meta["prelude_length"] > 0

    def test_metadata_backward_compat(self):
        """includes_canonical should still be present for backward compat."""
        from illustrator_mcp.libraries import get_injection_metadata

        meta = get_injection_metadata(["geometry"])

        assert "includes_canonical" in meta
        assert meta["includes_canonical"] == meta["includes_requested"]

    def test_metadata_empty_includes(self):
        """Empty includes should return empty metadata with correct keys."""
        from illustrator_mcp.libraries import get_injection_metadata

        meta = get_injection_metadata([])

        assert meta["includes_requested"] == []
        assert meta["includes_resolved"] == []
        assert meta["prelude_hash"] is None
        assert meta["prelude_length"] == 0
        assert meta["library_versions"] == {}
        assert meta["manifest_version"] is None


# ==================== Deterministic Hash Tests ====================

class TestDeterministicHash:
    """Prelude hash must be deterministic across repeated calls."""

    def test_repeated_hash_is_identical(self):
        """Same includes → same hash and canonical list, every time."""
        from illustrator_mcp.libraries import get_injection_metadata

        meta1 = get_injection_metadata(["geometry", "layout"])
        meta2 = get_injection_metadata(["geometry", "layout"])
        meta3 = get_injection_metadata(["layout", "geometry"])  # reversed order

        assert meta1["prelude_hash"] == meta2["prelude_hash"]
        assert meta1["includes_canonical"] == meta2["includes_canonical"]
        # Same libraries regardless of input order → same hash
        assert meta1["prelude_hash"] == meta3["prelude_hash"]

    def test_different_includes_different_hash(self):
        """Different includes → different hash."""
        from illustrator_mcp.libraries import get_injection_metadata

        meta1 = get_injection_metadata(["geometry"])
        meta2 = get_injection_metadata(["layout"])

        assert meta1["prelude_hash"] != meta2["prelude_hash"]


# ==================== Resource Registration Tests ====================

class TestResourceRegistration:
    """Verify MCP resources are registered."""

    def test_resources_are_registered(self):
        """Both resources should be registered on the MCP server."""
        from illustrator_mcp.shared import mcp

        # FastMCP stores resources internally — check they exist
        # by verifying the resource functions are accessible
        from illustrator_mcp.tools.context import (
            extendscript_reference_resource,
            library_catalog_resource,
        )

        assert callable(extendscript_reference_resource)
        assert callable(library_catalog_resource)

    def test_extendscript_resource_returns_content(self):
        """Extendscript reference resource should return non-empty content."""
        from illustrator_mcp.tools.context import extendscript_reference_resource

        content = extendscript_reference_resource()
        assert isinstance(content, str)
        assert len(content) > 100  # Should be a substantial reference doc

    def test_library_catalog_resource_returns_catalog(self):
        """Library catalog resource should return formatted catalog."""
        from illustrator_mcp.tools.context import library_catalog_resource

        content = library_catalog_resource()
        assert isinstance(content, str)
        assert "# Helper Library Catalog" in content
        assert "`geometry`" in content
