"""
test_heap_invariants.py — Static analysis tests for heap invariant enforcement.

Tests H1 (creators use stampMcpId) and H2 (resolvers use heapResolve).
Run: python -m pytest tests/test_heap_invariants.py -v
"""

import os
import re
import json
import pytest

SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..",
    "illustrator_mcp", "resources", "scripts"
)

# SOC handler files that MUST use stampMcpId (not raw note assignment)
SOC_HANDLER_FILES = ["ops_element.jsx", "ops_group.jsx", "ops_text.jsx"]


def _is_comment_line(line: str) -> bool:
    """Check if a line is a comment or JSDoc."""
    stripped = line.strip()
    return stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*")


class TestHeapInvariantH1:
    """H1: Any op that stamps @mcp:id= MUST heapRegister (via stampMcpId)."""

    def test_all_creators_use_stampMcpId(self):
        """SOC handler files must not use raw note assignment for MCP IDs."""
        raw_pattern = re.compile(r'\.note\s*=\s*"@mcp:id="')
        violations = []

        for fname in SOC_HANDLER_FILES:
            filepath = os.path.join(SCRIPTS_DIR, fname)
            with open(filepath, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    if _is_comment_line(line):
                        continue
                    if raw_pattern.search(line):
                        violations.append(f"{fname}:{lineno}: {line.strip()}")

        assert violations == [], (
            "Raw note assignment found (should use stampMcpId):\n"
            + "\n".join(violations)
        )

    def test_stampMcpId_defined_in_heap(self):
        """heap.jsx must define the stampMcpId function."""
        heap_path = os.path.join(SCRIPTS_DIR, "heap.jsx")
        with open(heap_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "function stampMcpId(" in content, (
            "stampMcpId not defined in heap.jsx"
        )

    def test_stampMcpId_exported_in_manifest(self):
        """manifest.json must export stampMcpId from heap."""
        manifest_path = os.path.join(SCRIPTS_DIR, "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        exports = manifest["libraries"]["heap"]["exports"]
        assert "stampMcpId" in exports, (
            f"stampMcpId not in heap exports: {exports}"
        )


class TestHeapInvariantH2:
    """H2: Resolvers must use heapResolve, not O(N) scan."""

    def test_clip_create_uses_heap_resolve(self):
        """clip_create handler must use heapResolve for ID resolution."""
        ops_group_path = os.path.join(SCRIPTS_DIR, "ops_group.jsx")
        with open(ops_group_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "heapResolve(" in content, (
            "heapResolve not found in ops_group.jsx"
        )

    def test_clip_create_no_pageItems_scan(self):
        """clip_create must not use doc.pageItems linear scan for ID resolution."""
        ops_group_path = os.path.join(SCRIPTS_DIR, "ops_group.jsx")
        with open(ops_group_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find clip_create handler region
        clip_start = content.find('registerOpHandler("clip_create"')
        assert clip_start >= 0, "clip_create handler not found"

        # Find the end of clip_create (next registerOpHandler or EOF)
        next_handler = content.find("registerOpHandler(", clip_start + 1)
        clip_region = content[clip_start:next_handler] if next_handler > 0 else content[clip_start:]

        # Should NOT have pageItems scan pattern in clip_create region
        assert "doc.pageItems" not in clip_region, (
            "clip_create still uses doc.pageItems scan (should use heapResolve)"
        )

    def test_ops_group_depends_on_heap(self):
        """ops_group must list heap as a dependency in manifest.json."""
        manifest_path = os.path.join(SCRIPTS_DIR, "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        deps = manifest["libraries"]["ops_group"]["dependencies"]
        assert "heap" in deps, f"'heap' not in ops_group dependencies: {deps}"


class TestClipToSchema:
    """Tests for element_create.clipTo schema addition."""

    def test_clipTo_in_element_create_schema(self):
        """element_create schema must have clipTo param."""
        from illustrator_mcp.schemas.contracts import get_op_schema
        schema = get_op_schema("element_create")
        assert "clipTo" in schema.params, (
            f"clipTo not in element_create params: {list(schema.params.keys())}"
        )

    def test_clipTo_is_string_type(self):
        """clipTo param must be string type."""
        from illustrator_mcp.schemas.contracts import get_op_schema
        schema = get_op_schema("element_create")
        assert schema.params["clipTo"].type.value == "string"

    def test_clipTo_is_optional(self):
        """clipTo param must not be required."""
        from illustrator_mcp.schemas.contracts import get_op_schema
        schema = get_op_schema("element_create")
        assert schema.params["clipTo"].required is False


class TestClipToHandlerGuard:
    """Static analysis: clipTo delegation in element_create handler."""

    @pytest.fixture(autouse=True)
    def load_handler_source(self):
        """Load ops_element.jsx for static analysis."""
        handler_path = os.path.join(SCRIPTS_DIR, "ops_element.jsx")
        with open(handler_path, "r", encoding="utf-8") as f:
            self.source = f.read()

    def test_element_create_delegates_clipTo(self):
        """element_create handler must delegate clipTo to clip_create."""
        # Find element_create region
        ec_start = self.source.find('registerOpHandler("element_create"')
        assert ec_start >= 0
        next_handler = self.source.find("registerOpHandler(", ec_start + 1)
        ec_region = self.source[ec_start:next_handler] if next_handler > 0 else self.source[ec_start:]

        assert 'OP_HANDLERS["clip_create"]' in ec_region, (
            "element_create does not delegate clipTo to clip_create handler"
        )
        assert "params.clipTo" in ec_region, (
            "element_create does not check params.clipTo"
        )

