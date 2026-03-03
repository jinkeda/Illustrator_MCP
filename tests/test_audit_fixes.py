"""
Tests for audit fixes (PR-D, PR-E, PR-F).

Covers:
- PR-D: Fan-out normalization, OP_CLASS module scope + warning dedup, color != null
- PR-E: Imports at top, orphan files deleted, glossary comment
- PR-F: Heap rebuild cap + rebuildComplete flag, _CREATION_OPS frozenset + sync
"""

import re
from pathlib import Path

import pytest


SCRIPTS_DIR = (
    Path(__file__).resolve().parent.parent
    / "illustrator_mcp" / "resources" / "scripts"
)

OPS_CORE = SCRIPTS_DIR / "ops_core.jsx"
OPS_STYLE = SCRIPTS_DIR / "ops_style.jsx"
HEAP_JSX = SCRIPTS_DIR / "heap.jsx"


# ==================== PR-D Tests ====================


class TestFanOutNormalization:
    """Fan-out path normalizes unconditionally."""

    def test_fanout_normalizes_unconditionally(self):
        """normalizeHandlerResult called inside fan-out, no typeof gate."""
        content = OPS_CORE.read_text(encoding="utf-8")

        # Find the fan-out block
        fan_start = content.find("// Fan-out: call handler once per target")
        assert fan_start != -1, "Fan-out block not found"
        # Check that normalizeHandlerResult is called after handler
        fan_chunk = content[fan_start:fan_start + 1000]
        assert "normalizeHandlerResult(op.task, singleResult)" in fan_chunk, (
            "Fan-out must normalize each per-target result unconditionally"
        )

    def test_fanout_no_typeof_gate(self):
        """Fan-out should NOT have typeof gate around result consumption."""
        content = OPS_CORE.read_text(encoding="utf-8")
        fan_start = content.find("// Fan-out: call handler once per target")
        fan_end = content.find("handlerResult = { ok: fanOk", fan_start)
        fan_block = content[fan_start:fan_end]
        # Should NOT have the old typeof check
        assert 'typeof singleResult === "object"' not in fan_block, (
            "Fan-out should use normalizer, not manual typeof check"
        )

    def test_fanout_all_targets_have_entries(self):
        """Every target gets an entry in fanData — no else branch skipping."""
        content = OPS_CORE.read_text(encoding="utf-8")
        fan_start = content.find("// Fan-out: call handler once per target")
        fan_end = content.find("handlerResult = { ok: fanOk", fan_start)
        fan_block = content[fan_start:fan_end]
        # Should have exactly one fanData.push, not conditioned on typeof
        push_count = fan_block.count("fanData.push(")
        assert push_count == 1, (
            f"Expected exactly 1 fanData.push (unconditional), got {push_count}"
        )


class TestNormalizerContract:
    """normalizeHandlerResult output contract: always has ok, data, warnings, error, id."""

    def test_normalizer_null_input_returns_canonical(self):
        """Normalizer returns {ok:true, data:null} for null input."""
        content = OPS_CORE.read_text(encoding="utf-8")
        fn_match = re.search(
            r"function normalizeHandlerResult\(.*?\n\}",
            content,
            re.DOTALL,
        )
        assert fn_match, "normalizeHandlerResult not found"
        body = fn_match.group(0)
        assert "ok: true" in body
        assert "warnings: []" in body
        assert "error: null" in body
        assert "id: null" in body


class TestOpClassModuleScope:
    """OP_CLASS at module scope with deduped warnings."""

    def test_op_class_at_module_scope(self):
        """OP_CLASS is defined at module scope (outside any function body)."""
        content = OPS_CORE.read_text(encoding="utf-8")
        # Find OP_CLASS definition
        match = re.search(r"^var OP_CLASS = \{", content, re.MULTILINE)
        assert match, "OP_CLASS not found at module scope"
        # Ensure it's not inside a function — check no 'function' keyword
        # between the nearest '//' header and OP_CLASS
        before = content[:match.start()]
        last_section = before.rfind("// ====================")
        section = before[last_section:] if last_section != -1 else before[-200:]
        assert "function " not in section or "function getOpClass" in section, (
            "OP_CLASS should be at module scope, not inside a function"
        )

    def test_getopclass_accepts_ctx(self):
        """getOpClass signature includes ctx parameter."""
        content = OPS_CORE.read_text(encoding="utf-8")
        assert "function getOpClass(task, ctx)" in content

    def test_getopclass_dedupes_warnings(self):
        """getOpClass uses _OP_CLASS_WARNED cache to warn once per task."""
        content = OPS_CORE.read_text(encoding="utf-8")
        assert "_OP_CLASS_WARNED" in content
        assert "_OP_CLASS_WARNED[task] = true" in content

    def test_getopclass_callsite_passes_ctx(self):
        """All getOpClass call sites inside executeSubOps pass ctx."""
        content = OPS_CORE.read_text(encoding="utf-8")
        # Find all getOpClass calls
        calls = re.findall(r"getOpClass\(([^)]+)\)", content)
        for call in calls:
            # Skip the function definition itself
            if call.strip().startswith("task"):
                assert "ctx" in call, (
                    f"getOpClass call must pass ctx: getOpClass({call})"
                )


class TestColorChannelGuard:
    """Canonical color param parsing uses != null, not ||."""

    def test_parse_helper_exists(self):
        """_parseColorParam helper is defined in ops_style.jsx."""
        content = OPS_STYLE.read_text(encoding="utf-8")
        assert "function _parseColorParam(" in content

    def test_clamp_helper_exists(self):
        """_clampChannel helper is defined in ops_style.jsx."""
        content = OPS_STYLE.read_text(encoding="utf-8")
        assert "function _clampChannel(" in content

    def test_helper_uses_null_safe_checks(self):
        """_parseColorParam uses != null for channel extraction, not ||."""
        content = OPS_STYLE.read_text(encoding="utf-8")
        helper_start = content.find("function _parseColorParam(")
        assert helper_start != -1
        helper_end = content.find("\nfunction ", helper_start + 1)
        helper_block = content[helper_start:helper_end] if helper_end > 0 else content[helper_start:]

        # Should use != null pattern
        assert "!= null" in helper_block, "Must use != null for channel checks"
        # Should NOT have params.r || 0 pattern
        assert "params.r || 0" not in helper_block
        assert "src.r || 0" not in helper_block


# ==================== PR-E Tests ====================


class TestImportsAtTop:
    """execute.py has no mid-body imports outside functions."""

    EXECUTE_PY = (
        Path(__file__).resolve().parent.parent
        / "illustrator_mcp" / "tools" / "execute.py"
    )

    def test_no_mid_body_imports(self):
        """No top-level 'from ... import' after the import header block."""
        content = self.EXECUTE_PY.read_text(encoding="utf-8")
        lines = content.splitlines()
        # Find end of top import block: scan until first non-import,
        # non-comment, non-blank, non-continuation line after docstring.
        import_end = 0
        for i, line in enumerate(lines[:50]):
            stripped = line.strip()
            is_import = stripped.startswith(("from ", "import "))
            is_benign = (
                not stripped                      # blank
                or stripped.startswith("#")        # comment
                or stripped.startswith(")")        # close paren
                or stripped.startswith('"""')      # docstring
                or line.startswith((" ", "\t"))    # indented (continuation)
            )
            if is_import:
                import_end = i
            elif is_benign:
                continue
            elif i > 15 and import_end > 0:
                break
        # Check remaining lines for column-0 'from ... import'
        issues = []
        for i, line in enumerate(lines[import_end + 1:], start=import_end + 2):
            if (line.startswith("from ") and "import" in line
                    and "noqa" not in line):  # exclude deliberate re-exports
                issues.append(f"Line {i}: {line.strip()}")
        assert not issues, f"Mid-body imports found: {issues}"


class TestOrphanSchemasDeleted:
    """Orphan schema files should not exist."""

    def test_op_schemas_generated_absent(self):
        """op_schemas_generated.jsx must not exist."""
        path = SCRIPTS_DIR / "op_schemas_generated.jsx"
        assert not path.exists(), f"Orphan file still exists: {path}"

    def test_op_schemas_json_absent(self):
        """op_schemas.json must not exist."""
        path = SCRIPTS_DIR / "op_schemas.json"
        assert not path.exists(), f"Orphan file still exists: {path}"


class TestGlossaryComment:
    """results → ops glossary is documented."""

    def test_glossary_exists(self):
        """ops_core.jsx has field naming glossary."""
        content = OPS_CORE.read_text(encoding="utf-8")
        assert "Field naming glossary" in content
        assert '"results"' in content or "'results'" in content
        assert '"ops"' in content or "'ops'" in content


# ==================== PR-F Tests ====================


class TestHeapRebuildCap:
    """heapRebuildIndex has cap and incomplete-rebuild signal."""

    def test_rebuild_cap_constant(self):
        """_HEAP_REBUILD_CAP is defined."""
        content = HEAP_JSX.read_text(encoding="utf-8")
        assert "_HEAP_REBUILD_CAP" in content

    def test_rebuild_complete_flag(self):
        """_heapRebuildComplete flag is defined and used."""
        content = HEAP_JSX.read_text(encoding="utf-8")
        assert "var _heapRebuildComplete" in content

    def test_diagnostics_has_rebuild_complete(self):
        """heapDiagnostics returns rebuildComplete field."""
        content = HEAP_JSX.read_text(encoding="utf-8")
        diag_start = content.find("function heapDiagnostics")
        diag_block = content[diag_start:diag_start + 500]
        assert "rebuildComplete" in diag_block

    def test_cap_triggers_warning(self):
        """Cap hit pushes to _heapWarnings."""
        content = HEAP_JSX.read_text(encoding="utf-8")
        assert "index incomplete" in content


class TestCreationOpsFrozenset:
    """_CREATION_OPS is a module-level frozenset."""

    TASK_EXEC = (
        Path(__file__).resolve().parent.parent
        / "illustrator_mcp" / "tools" / "task_execution.py"
    )

    def test_is_frozenset_at_module_level(self):
        """_CREATION_OPS is defined as frozenset."""
        content = self.TASK_EXEC.read_text(encoding="utf-8")
        assert "_CREATION_OPS = frozenset(" in content

    def test_creation_ops_subset_of_op_class(self):
        """Python _CREATION_OPS ⊆ OP_CLASS doc entries in ops_core.jsx."""
        # Parse Python _CREATION_OPS
        py_content = self.TASK_EXEC.read_text(encoding="utf-8")
        match = re.search(
            r"_CREATION_OPS\s*=\s*frozenset\(\{(.*?)\}\)",
            py_content,
            re.DOTALL,
        )
        assert match, "_CREATION_OPS frozenset not found"
        py_ops = set(re.findall(r'"(\w+)"', match.group(1)))

        # Parse JSX OP_CLASS
        jsx_content = OPS_CORE.read_text(encoding="utf-8")
        class_match = re.search(
            r"var OP_CLASS = \{(.*?)\};",
            jsx_content,
            re.DOTALL,
        )
        assert class_match, "OP_CLASS not found in ops_core.jsx"
        # Extract all keys with "doc" classification
        doc_ops = set(re.findall(r'"(\w+)":\s*"doc"', class_match.group(1)))

        # _CREATION_OPS should be a subset of OP_CLASS doc entries
        missing = py_ops - doc_ops
        assert not missing, (
            f"_CREATION_OPS contains ops not in OP_CLASS 'doc': {sorted(missing)}"
        )
