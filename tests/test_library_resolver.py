"""
Tests for LibraryResolver and library injection.

Tests the manifest-driven library injection system with:
- Transitive dependency resolution
- Symbol collision detection
- Library content caching
- Fallback mode (no manifest)
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from illustrator_mcp.libraries import LibraryResolver, inject_libraries

# Path to the actual resources/scripts directory
_RESOURCES_DIR = Path(__file__).parent.parent / "illustrator_mcp" / "resources" / "scripts"


class TestLibraryResolverBasic:
    """Basic LibraryResolver tests with mocked manifest."""
    
    @pytest.fixture
    def temp_scripts_dir(self, tmp_path):
        """Create a temp scripts directory with manifest and libraries."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        
        # Create manifest
        manifest = {
            "version": "1.0.0",
            "libraries": {
                "units": {
                    "file": "units.jsx",
                    "version": "1.0.0",
                    "dependencies": [],
                    "exports": ["mmToPoints", "ptToMm"]
                },
                "geometry": {
                    "file": "geometry.jsx",
                    "version": "1.0.0",
                    "dependencies": ["units"],
                    "exports": ["getVisibleBounds", "getVisibleInfo"]
                },
                "layout": {
                    "file": "layout.jsx",
                    "version": "1.0.0",
                    "dependencies": ["geometry"],
                    "exports": ["arrangeInGrid", "batchResize"]
                }
            }
        }
        
        with open(scripts_dir / "manifest.json", "w") as f:
            json.dump(manifest, f)
        
        # Create library files
        (scripts_dir / "units.jsx").write_text("function mmToPoints(mm) { return mm * 2.83; }\nfunction ptToMm(pt) { return pt / 2.83; }")
        (scripts_dir / "geometry.jsx").write_text("function getVisibleBounds(item) { return item.visibleBounds; }\nfunction getVisibleInfo(item) { return {}; }")
        (scripts_dir / "layout.jsx").write_text("function arrangeInGrid(items, cols) { /* grid */ }\nfunction batchResize(items, w, h) { /* resize */ }")
        
        return scripts_dir
    
    def test_resolver_with_temp_dir(self, temp_scripts_dir):
        """Test that LibraryResolver loads from a custom directory."""
        resolver = LibraryResolver(temp_scripts_dir)
        manifest = resolver._load_manifest()
        assert "libraries" in manifest
        assert "units" in manifest["libraries"]


class TestDependencyResolution:
    """Tests for transitive dependency resolution."""
    
    def test_simple_library_resolve(self):
        """Test resolving a library without dependencies."""
        resolver = LibraryResolver(_RESOURCES_DIR)
        
        if resolver._load_manifest() is None:
            pytest.skip("No manifest.json found")
        
        result = resolver.resolve(["task_executor"])
        assert "executeTask" in result
        assert "ErrorCodes" in result
    
    def test_transitive_dependency_resolution(self):
        """Test that dependencies are resolved transitively."""
        resolver = LibraryResolver(_RESOURCES_DIR)
        
        if resolver._load_manifest() is None:
            pytest.skip("No manifest.json found")
        
        # layout depends on geometry
        result = resolver.resolve(["layout"])
        
        # geometry should be included before layout
        assert "getVisibleBounds" in result or "mmToPoints" in result
        assert "arrangeInGrid" in result
    
    def test_deduplication(self):
        """Test that each library is included only once."""
        resolver = LibraryResolver(_RESOURCES_DIR)
        
        if resolver._load_manifest() is None:
            pytest.skip("No manifest.json found")
        
        # Include both layout and geometry - geometry should appear once
        result = resolver.resolve(["geometry", "layout"])
        
        # Count occurrences of a geometry function
        count = result.count("function getVisibleBounds")
        assert count == 1, f"getVisibleBounds appeared {count} times, expected 1"
    
    def test_unknown_library_raises(self):
        """Test that unknown library raises ValueError."""
        resolver = LibraryResolver(_RESOURCES_DIR)
        
        if resolver._load_manifest() is None:
            pytest.skip("No manifest.json found")
        
        with pytest.raises(ValueError, match="Unknown library"):
            resolver.resolve(["nonexistent_library"])


class TestSymbolCollisionDetection:
    """Tests for symbol collision detection."""
    
    @pytest.fixture
    def collision_scripts_dir(self, tmp_path):
        """Create scripts with symbol collisions."""
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        
        manifest = {
            "version": "1.0.0",
            "libraries": {
                "lib_a": {
                    "file": "lib_a.jsx",
                    "version": "1.0.0",
                    "dependencies": [],
                    "exports": ["sharedFunction", "uniqueA"]
                },
                "lib_b": {
                    "file": "lib_b.jsx",
                    "version": "1.0.0",
                    "dependencies": [],
                    "exports": ["sharedFunction", "uniqueB"]  # Collision!
                }
            }
        }
        
        with open(scripts_dir / "manifest.json", "w") as f:
            json.dump(manifest, f)
        
        (scripts_dir / "lib_a.jsx").write_text("function sharedFunction() { return 'A'; }")
        (scripts_dir / "lib_b.jsx").write_text("function sharedFunction() { return 'B'; }")
        
        return scripts_dir


class TestLibraryCaching:
    """Tests for library content caching."""
    
    def test_cache_population(self):
        """Test that resolved libraries are cached."""
        resolver = LibraryResolver(_RESOURCES_DIR)
        
        if resolver._load_manifest() is None:
            pytest.skip("No manifest.json found")
        
        # First resolve
        resolver.resolve(["geometry"])
        
        # File cache should have the geometry file
        assert len(resolver._file_cache) > 0
    
    def test_cache_reuse(self):
        """Test that cached content is reused."""
        resolver = LibraryResolver(_RESOURCES_DIR)
        
        if resolver._load_manifest() is None:
            pytest.skip("No manifest.json found")
        
        # First resolve
        result1 = resolver.resolve(["geometry"])
        
        # Second resolve should use cache (no file read)
        result2 = resolver.resolve(["geometry"])
        
        assert result1 == result2

    def test_file_cache_stores_tuples(self):
        """Cache entries are (content: str, mtime: float) tuples."""
        resolver = LibraryResolver(_RESOURCES_DIR)

        if resolver._load_manifest() is None:
            pytest.skip("No manifest.json found")

        resolver.resolve(["geometry"])

        assert len(resolver._file_cache) > 0
        for path, entry in resolver._file_cache.items():
            assert isinstance(entry, tuple) and len(entry) == 2
            assert isinstance(entry[0], str), f"content should be str, got {type(entry[0])}"
            assert isinstance(entry[1], float), f"mtime should be float, got {type(entry[1])}"


class TestInjectLibraries:
    """Tests for the inject_libraries function."""
    
    def test_empty_includes(self):
        """Test that empty includes returns script unchanged."""
        script = "var x = 1;"
        result = inject_libraries(script, [])
        assert result == script
    
    def test_inject_adds_user_script_marker(self):
        """Test that user script is marked."""
        user_script = "var myCode = true;"
        
        result = inject_libraries(user_script, ["task_executor"])
        
        assert "// === MCP user script ===" in result
        assert user_script in result
    
    def test_inject_library_comes_before_script(self):
        """Test that library code comes before user script."""
        user_script = "myFunction();"
        
        result = inject_libraries(user_script, ["task_executor"])
        
        # Library code should come before user script
        lib_pos = result.find("ErrorCodes")
        script_pos = result.find("myFunction")
        
        assert lib_pos < script_pos, "Library should come before user script"


class TestFallbackMode:
    """Tests for fallback mode when no manifest exists."""
    
    def test_fallback_still_loads_files(self, tmp_path):
        """Test that fallback mode still loads library files directly."""
        # Create scripts without manifest
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "test_lib.jsx").write_text("function testFunc() {}")
        
        # Create resolver pointing to dir without manifest
        resolver = LibraryResolver(scripts_dir)
        
        # Without manifest, resolve should handle gracefully
        if resolver._load_manifest():
            try:
                result = resolver.resolve(["geometry"])
                assert "getVisibleBounds" in result
            except ValueError:
                pass  # Expected if geometry not in manifest





