"""
Static guard tests for path_boolean infrastructure.

Verifies that all required components are properly wired:
- geo_boolean.jsx registered in manifest with correct exports
- path_boolean schema exists in contracts
- pyclipper import is guarded with helpful error message
- Python handler exists in path_boolean.py
"""

import json
import re
import pytest
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "illustrator_mcp" / "resources" / "scripts"
MANIFEST_PATH = SCRIPTS_DIR / "manifest.json"
GEO_BOOLEAN_PATH = SCRIPTS_DIR / "geo_boolean.jsx"
EXECUTE_PATH = ROOT / "illustrator_mcp" / "tools" / "execute.py"
PATH_BOOLEAN_PATH = ROOT / "illustrator_mcp" / "tools" / "path_boolean.py"
CONTRACTS_PATH = ROOT / "illustrator_mcp" / "schemas" / "contracts.py"
GEOMETRY_PY_PATH = ROOT / "illustrator_mcp" / "geometry.py"
PYPROJECT_PATH = ROOT / "pyproject.toml"


class TestManifestRegistration:
    """Verify geo_boolean.jsx is properly registered in manifest."""

    @pytest.fixture(autouse=True)
    def load_manifest(self):
        self.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.libs = self.manifest["libraries"]

    def test_geo_boolean_registered(self):
        assert "geo_boolean" in self.libs, "geo_boolean missing from manifest"

    def test_geo_boolean_file_reference(self):
        assert self.libs["geo_boolean"]["file"] == "geo_boolean.jsx"

    def test_geo_boolean_dependencies(self):
        deps = self.libs["geo_boolean"]["dependencies"]
        assert "ops_core" in deps, "geo_boolean needs ops_core for generateUUID"

    def test_geo_boolean_exports(self):
        exports = self.libs["geo_boolean"]["exports"]
        assert "extractPathGeometry" in exports
        assert "reconstructRegions" in exports
        assert "deleteByMcpIds" in exports

    def test_geometry_jsx_not_overwritten(self):
        """Original geometry.jsx should still have its own exports."""
        assert "geometry" in self.libs
        geo_exports = self.libs["geometry"]["exports"]
        assert "getContext" in geo_exports, "Original geometry.jsx exports must be intact"
        assert "pointXY" in geo_exports


class TestGeoBoooleanJSX:
    """Verify geo_boolean.jsx contains required functions."""

    @pytest.fixture(autouse=True)
    def load_jsx(self):
        self.source = GEO_BOOLEAN_PATH.read_text(encoding="utf-8")

    def test_extract_function_exists(self):
        assert "function extractPathGeometry" in self.source

    def test_reconstruct_function_exists(self):
        assert "function reconstructRegions" in self.source

    def test_delete_function_exists(self):
        assert "function deleteByMcpIds" in self.source

    def test_coordinate_helpers(self):
        assert "function _toSOC" in self.source
        assert "function _fromSOC" in self.source

    def test_dependency_guard(self):
        assert "generateUUID" in self.source, "Must reference generateUUID from ops_core"

    def test_compound_path_handling(self):
        """reconstructRegions must handle holes via CompoundPathItem."""
        assert "compoundPath" in self.source

    def test_locked_hidden_validation(self):
        """extractPathGeometry must check locked and hidden items."""
        assert "item.locked" in self.source
        assert "item.hidden" in self.source


class TestContractsSchema:
    """Verify path_boolean schema is in contracts."""

    @pytest.fixture(autouse=True)
    def load_contracts(self):
        self.source = CONTRACTS_PATH.read_text(encoding="utf-8")

    def test_path_boolean_schema_exists(self):
        assert 'name="path_boolean"' in self.source

    def test_required_params(self):
        assert '"operation"' in self.source
        assert '"subject"' in self.source
        assert '"clip"' in self.source

    def test_operation_enum(self):
        assert '"subtract"' in self.source
        assert '"unite"' in self.source
        assert '"intersect"' in self.source
        assert '"xor"' in self.source

    def test_schema_version_updated(self):
        assert "1.6" in self.source


class TestPythonGeometryModule:
    """Verify geometry.py has proper structure."""

    @pytest.fixture(autouse=True)
    def load_module(self):
        self.source = GEOMETRY_PY_PATH.read_text(encoding="utf-8")

    def test_import_guard(self):
        """pyclipper import should be guarded with try/except."""
        assert "try:" in self.source
        assert "import pyclipper" in self.source
        assert "pyclipper = None" in self.source

    def test_region_dataclass(self):
        assert "class Region" in self.source
        assert "outer" in self.source
        assert "holes" in self.source

    def test_path_boolean_function(self):
        assert "def path_boolean" in self.source

    def test_flatten_functions(self):
        assert "def flatten_cubic" in self.source
        assert "def flatten_path" in self.source

    def test_polytree_conversion(self):
        assert "def _polytree_to_regions" in self.source

    def test_max_segments_parameter(self):
        """max_segments cap must be documented."""
        assert "max_segments" in self.source


class TestPythonHandler:
    """Verify path_boolean.py has the path_boolean handler."""

    @pytest.fixture(autouse=True)
    def load_execute(self):
        self.source = PATH_BOOLEAN_PATH.read_text(encoding="utf-8")

    def test_handler_exists(self):
        assert "async def illustrator_path_boolean" in self.source

    def test_input_class_exists(self):
        assert "class PathBooleanInput" in self.source

    def test_mcp_tool_decorator(self):
        # Check there's a @mcp.tool() before illustrator_path_boolean
        idx = self.source.index("async def illustrator_path_boolean")
        before = self.source[max(0, idx - 200):idx]
        assert "@mcp.tool()" in before

    def test_three_step_pipeline(self):
        """Handler should call extract, reconstruct, and delete steps."""
        assert "path_boolean:extract" in self.source
        assert "path_boolean:reconstruct" in self.source
        assert "path_boolean:delete" in self.source

    def test_delete_after_success(self):
        """Delete originals should occur AFTER reconstruction in the main flow."""
        # Find the reconstruct step and the delete step that follows it
        reconstruct_idx = self.source.index("path_boolean:reconstruct")
        # The main success-path delete is the one AFTER reconstruct
        delete_after_recon = self.source.index("path_boolean:delete", reconstruct_idx)
        assert delete_after_recon > reconstruct_idx

    def test_includes_geo_boolean(self):
        """Handler should include geo_boolean library."""
        assert 'includes=["geo_boolean"]' in self.source


class TestPyprojectToml:
    """Verify pyclipper is in optional dependencies."""

    @pytest.fixture(autouse=True)
    def load_toml(self):
        self.source = PYPROJECT_PATH.read_text(encoding="utf-8")

    def test_geometry_extras(self):
        assert "pyclipper" in self.source

    def test_geometry_group(self):
        assert "geometry" in self.source
