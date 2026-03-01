"""
Tests for PR-B: Heap Eviction Policy + Template Hot-Reload.

Covers:
- Suspect-before-evict heap policy
- _heapWarnings accumulator
- st_mtime_ns template cache
"""

import os
import re
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# ==================== Heap Suspect-Before-Evict Tests ====================


class TestHeapSuspectPolicy:
    """Tests for the suspect-before-evict heap eviction policy."""

    HEAP_JSX = (
        Path(__file__).resolve().parent.parent
        / "illustrator_mcp" / "resources" / "scripts" / "heap.jsx"
    )

    def test_heap_has_warnings_accumulator(self):
        """_heapWarnings module-level accumulator exists."""
        content = self.HEAP_JSX.read_text(encoding="utf-8")
        assert "var _heapWarnings = [];" in content

    def test_heap_warnings_cleared_on_begin_txn(self):
        """heapBeginTxn resets _heapWarnings for each batch."""
        content = self.HEAP_JSX.read_text(encoding="utf-8")
        # Find heapBeginTxn function body
        begin_match = re.search(
            r"function heapBeginTxn\b.*?\{(.*?)\n\}",
            content,
            re.DOTALL,
        )
        assert begin_match, "heapBeginTxn function not found"
        body = begin_match.group(1)
        assert "_heapWarnings = []" in body, (
            "heapBeginTxn must reset _heapWarnings"
        )

    def test_heap_resolve_marks_suspect_on_first_com_error(self):
        """First COM error marks entry suspect, does NOT evict."""
        content = self.HEAP_JSX.read_text(encoding="utf-8")
        resolve_match = re.search(
            r"function heapResolve\b.*?\n\}",
            content,
            re.DOTALL,
        )
        assert resolve_match, "heapResolve function not found"
        body = resolve_match.group(0)

        # Must mark suspect on first failure
        assert "__mcpSuspect = true" in body, (
            "heapResolve must mark ref.__mcpSuspect on first COM error"
        )
        # Must NOT immediately evict on first COM error
        # The code path for first failure should set suspect, not delete
        assert 'First failure' in body or 'mark suspect' in body, (
            "heapResolve should have a 'first failure' code path"
        )

    def test_heap_resolve_evicts_on_second_com_error(self):
        """Second COM error (suspect already set) evicts the entry."""
        content = self.HEAP_JSX.read_text(encoding="utf-8")
        resolve_match = re.search(
            r"function heapResolve\b.*?\n\}",
            content,
            re.DOTALL,
        )
        body = resolve_match.group(0)

        # Must evict on second failure
        assert "confirmed stale" in body, (
            "heapResolve must evict on second COM error with 'confirmed stale' message"
        )
        # Must delete from index
        assert "delete heap.index[uuid]" in body

    def test_heap_resolve_clears_suspect_on_success(self):
        """Successful access clears suspect flag."""
        content = self.HEAP_JSX.read_text(encoding="utf-8")
        resolve_match = re.search(
            r"function heapResolve\b.*?\n\}",
            content,
            re.DOTALL,
        )
        body = resolve_match.group(0)
        assert "delete ref.__mcpSuspect" in body, (
            "heapResolve must clear __mcpSuspect on successful identity verification"
        )

    def test_heap_resolve_evicts_identity_mismatch_immediately(self):
        """Identity mismatch (different ID) evicts immediately, not suspect."""
        content = self.HEAP_JSX.read_text(encoding="utf-8")
        resolve_match = re.search(
            r"function heapResolve\b.*?\n\}",
            content,
            re.DOTALL,
        )
        body = resolve_match.group(0)
        assert "identity mismatch" in body, (
            "heapResolve must evict immediately on identity mismatch"
        )

    def test_heap_diagnostics_includes_warnings(self):
        """heapDiagnostics() return value includes warnings field."""
        content = self.HEAP_JSX.read_text(encoding="utf-8")
        diag_match = re.search(
            r"function heapDiagnostics\b.*?\n\}",
            content,
            re.DOTALL,
        )
        assert diag_match, "heapDiagnostics function not found"
        body = diag_match.group(0)
        assert "warnings:" in body, (
            "heapDiagnostics must return warnings field"
        )
        assert "_heapWarnings" in body, (
            "heapDiagnostics warnings must reference _heapWarnings accumulator"
        )


# ==================== Template Hot-Reload Tests ====================


class TestTemplateHotReload:
    """Tests for mtime_ns-based template caching."""

    def test_no_lru_cache_on_template_loader(self):
        """_load_jsx_template must NOT use @lru_cache."""
        from illustrator_mcp.tools import task_execution
        import inspect
        source = inspect.getsource(task_execution._load_jsx_template)
        assert "lru_cache" not in source, (
            "_load_jsx_template should use mtime-based cache, not @lru_cache"
        )

    def test_lru_cache_not_imported(self):
        """functools.lru_cache should not be imported in task_execution."""
        from illustrator_mcp.tools import task_execution
        import inspect
        source = inspect.getsource(task_execution)
        # Check module-level imports — lru_cache should not be there
        import_lines = [
            l for l in source.split("\n")
            if l.strip().startswith(("import ", "from "))
        ]
        for line in import_lines:
            assert "lru_cache" not in line, (
                f"lru_cache import found in task_execution.py: {line}"
            )

    def test_template_cache_dict_exists(self):
        """Module-level _jsx_template_cache dict exists."""
        from illustrator_mcp.tools import task_execution
        assert hasattr(task_execution, "_jsx_template_cache")
        assert isinstance(task_execution._jsx_template_cache, dict)

    def test_template_hot_reload(self):
        """Modifying a template on disk is picked up without restart."""
        from illustrator_mcp.tools.task_execution import (
            _load_jsx_template,
            _jsx_template_cache,
            _TEMPLATES_DIR,
        )

        # Create a temporary template file
        tmp_name = "__test_hot_reload_tmp.jsx"
        tmp_path = _TEMPLATES_DIR / tmp_name
        try:
            # Write initial content
            tmp_path.write_text("// version 1", encoding="utf-8")

            # Clear cache for this name
            _jsx_template_cache.pop(tmp_name, None)

            # First load
            content1 = _load_jsx_template(tmp_name)
            assert content1 == "// version 1"

            # Modify content (ensure mtime changes)
            time.sleep(0.05)  # small delay for filesystem timestamp
            tmp_path.write_text("// version 2", encoding="utf-8")

            # Second load — should pick up new content
            content2 = _load_jsx_template(tmp_name)
            assert content2 == "// version 2", (
                f"Expected '// version 2' but got '{content2}' — "
                "mtime cache not detecting changes"
            )

        finally:
            # Cleanup
            if tmp_path.exists():
                tmp_path.unlink()
            _jsx_template_cache.pop(tmp_name, None)

    def test_template_cache_returns_cached_on_same_mtime(self):
        """Cache returns cached content when mtime hasn't changed."""
        from illustrator_mcp.tools.task_execution import (
            _load_jsx_template,
            _jsx_template_cache,
            _TEMPLATES_DIR,
        )

        tmp_name = "__test_cache_hit_tmp.jsx"
        tmp_path = _TEMPLATES_DIR / tmp_name
        try:
            tmp_path.write_text("// cached content", encoding="utf-8")
            _jsx_template_cache.pop(tmp_name, None)

            # Load twice — second should be cached
            content1 = _load_jsx_template(tmp_name)
            content2 = _load_jsx_template(tmp_name)
            assert content1 == content2 == "// cached content"

            # Verify it's in cache
            assert tmp_name in _jsx_template_cache

        finally:
            if tmp_path.exists():
                tmp_path.unlink()
            _jsx_template_cache.pop(tmp_name, None)

    def test_template_not_found_raises(self):
        """Missing template raises FileNotFoundError."""
        from illustrator_mcp.tools.task_execution import _load_jsx_template
        with pytest.raises(FileNotFoundError):
            _load_jsx_template("__nonexistent_template.jsx")
