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

    def test_clip_create_uses_compat_resolve(self):
        """clip_create handler must use resolveIdCompat for ID resolution."""
        ops_group_path = os.path.join(SCRIPTS_DIR, "ops_group.jsx")
        with open(ops_group_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "resolveIdCompat(" in content, (
            "resolveIdCompat not found in ops_group.jsx"
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

    def test_resolveIdCompat_defined_in_heap(self):
        """heap.jsx must define resolveIdCompat function."""
        heap_path = os.path.join(SCRIPTS_DIR, "heap.jsx")
        with open(heap_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "function resolveIdCompat(" in content

    def test_resolveIdCompat_exported(self):
        """manifest.json must export resolveIdCompat from heap."""
        manifest_path = os.path.join(SCRIPTS_DIR, "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        exports = manifest["libraries"]["heap"]["exports"]
        assert "resolveIdCompat" in exports


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

    def test_clipTo_rollback_guard(self):
        """element_create must rollback (remove item + tombstone) on clip failure."""
        ec_start = self.source.find('registerOpHandler("element_create"')
        next_handler = self.source.find("registerOpHandler(", ec_start + 1)
        ec_region = self.source[ec_start:next_handler] if next_handler > 0 else self.source[ec_start:]

        assert "item.remove()" in ec_region, (
            "element_create clipTo does not rollback item.remove() on failure"
        )
        assert "heapTombstone(" in ec_region, (
            "element_create clipTo does not call heapTombstone on failure"
        )

    def test_clipTo_append_guard(self):
        """element_create must detect existing clip groups and append."""
        ec_start = self.source.find('registerOpHandler("element_create"')
        next_handler = self.source.find("registerOpHandler(", ec_start + 1)
        ec_region = self.source[ec_start:next_handler] if next_handler > 0 else self.source[ec_start:]

        assert "clipTarget.clipped" in ec_region, (
            "element_create clipTo does not check for existing clipping group"
        )

    def test_clipTo_early_validation(self):
        """element_create must validate clipTo target before element creation."""
        ec_start = self.source.find('registerOpHandler("element_create"')
        next_handler = self.source.find("registerOpHandler(", ec_start + 1)
        ec_region = self.source[ec_start:next_handler] if next_handler > 0 else self.source[ec_start:]

        # Early validation must appear before the switch(type) block
        early_idx = ec_region.find("resolveIdCompat(params.clipTo")
        switch_idx = ec_region.find("switch (type)")
        assert early_idx >= 0, "clipTo early validation not found"
        assert switch_idx >= 0, "switch(type) not found"
        assert early_idx < switch_idx, (
            "clipTo validation must appear before element construction"
        )

    def test_clipTo_uses_duplicate_mask_false(self):
        """clipTo must pass duplicate_mask: false to clip_create."""
        ec_start = self.source.find('registerOpHandler("element_create"')
        next_handler = self.source.find("registerOpHandler(", ec_start + 1)
        ec_region = self.source[ec_start:next_handler] if next_handler > 0 else self.source[ec_start:]

        assert "duplicate_mask: false" in ec_region, (
            "clipTo should pass duplicate_mask: false to clip_create"
        )

    def test_clipTo_append_verifies_move(self):
        """clipTo append path must verify item.parent changed after move."""
        ec_start = self.source.find('registerOpHandler("element_create"')
        next_handler = self.source.find("registerOpHandler(", ec_start + 1)
        ec_region = self.source[ec_start:next_handler] if next_handler > 0 else self.source[ec_start:]

        assert "preMoveParent" in ec_region, (
            "clipTo append path must check preMoveParent to verify move succeeded"
        )


class TestHeapRebuildOnBatchStart:
    """Option A invariant: heapBeginTxn must rebuild index from live DOM."""

    def test_heapBeginTxn_calls_heapRebuildIndex(self):
        """heapBeginTxn must call heapRebuildIndex to refresh COM refs."""
        heap_path = os.path.join(SCRIPTS_DIR, "heap.jsx")
        with open(heap_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find heapBeginTxn region
        txn_start = content.find("function heapBeginTxn(")
        assert txn_start >= 0, "heapBeginTxn not found"
        # Find end of function (next top-level function or EOF)
        next_fn = content.find("\nfunction ", txn_start + 1)
        txn_region = content[txn_start:next_fn] if next_fn > 0 else content[txn_start:]

        assert "heapRebuildIndex(" in txn_region, (
            "heapBeginTxn must call heapRebuildIndex to rebuild COM refs at batch start"
        )

    def test_heapBeginTxn_handles_no_document(self):
        """heapBeginTxn must handle missing document gracefully."""
        heap_path = os.path.join(SCRIPTS_DIR, "heap.jsx")
        with open(heap_path, "r", encoding="utf-8") as f:
            content = f.read()

        txn_start = content.find("function heapBeginTxn(")
        next_fn = content.find("\nfunction ", txn_start + 1)
        txn_region = content[txn_start:next_fn] if next_fn > 0 else content[txn_start:]

        assert "catch" in txn_region, (
            "heapBeginTxn must try/catch around document access for no-doc safety"
        )


class TestClipToFreshScan:
    """element_create clipTo must use freshScan for consistent mutation safety."""

    def test_element_create_clipTo_uses_freshScan(self):
        """resolveIdCompat for clipTo must use freshScan: true."""
        handler_path = os.path.join(SCRIPTS_DIR, "ops_element.jsx")
        with open(handler_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find all resolveIdCompat calls with params.clipTo
        clipTo_calls = [
            line.strip() for line in content.split("\n")
            if "resolveIdCompat(params.clipTo" in line
            and not line.strip().startswith("//")
        ]
        assert len(clipTo_calls) >= 2, (
            f"Expected >= 2 clipTo resolveIdCompat calls, found {len(clipTo_calls)}"
        )
        for call in clipTo_calls:
            assert "freshScan" in call, (
                f"clipTo resolveIdCompat must use freshScan: true, found: {call}"
            )


class TestCanonicalColorParams:
    """Canonical color param standardization invariants."""

    COLOR_OPS = ["style_set_fill", "style_set_stroke", "text_create", "text_set_style"]

    @staticmethod
    def _read_style():
        with open(os.path.join(SCRIPTS_DIR, "ops_style.jsx"), encoding="utf-8") as f:
            return f.read()

    def test_all_color_ops_have_nested_param_in_schema(self):
        """Any op with flat r/g/b in schema must also have fill or stroke object param."""
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from illustrator_mcp.schemas.contracts import OP_SCHEMA_MAP

        for op_name in self.COLOR_OPS:
            schema = OP_SCHEMA_MAP.get(op_name)
            assert schema is not None, f"Op {op_name} not found in schema"
            param_names = set(schema.params.keys())

            # If flat r/g/b exist, nested fill or stroke must also exist
            has_flat = "r" in param_names and "g" in param_names and "b" in param_names
            has_nested = "fill" in param_names or "stroke" in param_names
            assert not has_flat or has_nested, (
                f"Op {op_name} has flat r/g/b but no nested fill/stroke param"
            )

    def test_parse_color_param_in_ops_style(self):
        """_parseColorParam helper is defined in ops_style.jsx."""
        content = self._read_style()
        assert "function _parseColorParam(params, key)" in content

    def test_disable_sentinel_logic(self):
        """_parseColorParam handles false sentinel (disable beats compat)."""
        content = self._read_style()
        helper_start = content.find("function _parseColorParam(")
        next_fn = content.find("\nfunction ", helper_start + 1)
        helper = content[helper_start:next_fn] if next_fn > 0 else content[helper_start:]

        assert "=== false" in helper, "Must check for false sentinel"
        assert "disable: true" in helper, "Must return disable:true for false sentinel"

    def test_nested_before_flat_priority(self):
        """_parseColorParam checks params[key] before flat r/g/b."""
        content = self._read_style()
        helper_start = content.find("function _parseColorParam(")
        next_fn = content.find("\nfunction ", helper_start + 1)
        helper = content[helper_start:next_fn] if next_fn > 0 else content[helper_start:]

        # nested check (params[key]) must appear before flat check (params.r)
        nested_pos = helper.find("typeof src")
        flat_pos = helper.find("params.r != null")
        assert nested_pos > 0 and flat_pos > 0, "Both nested and flat paths must exist"
        assert nested_pos < flat_pos, "Nested check must come before flat fallback"

    def test_stroke_width_null_safe(self):
        """style_set_stroke uses != null for width (so 0 is valid)."""
        content = self._read_style()
        stroke_start = content.find('registerOpHandler("style_set_stroke"')
        stroke_end = content.find("});", stroke_start) + 3
        stroke_block = content[stroke_start:stroke_end]

        assert "width != null" in stroke_block, (
            "Stroke width must use != null, not ||, so width=0 is valid"
        )

    def test_channel_clamping(self):
        """_clampChannel exists and clamps 0-255."""
        content = self._read_style()
        assert "function _clampChannel(" in content
        clamp_start = content.find("function _clampChannel(")
        next_fn = content.find("\nfunction ", clamp_start + 1)
        clamp = content[clamp_start:next_fn] if next_fn > 0 else content[clamp_start:]
        assert "255" in clamp, "Must clamp to max 255"
        assert "< 0" in clamp, "Must clamp to min 0"

