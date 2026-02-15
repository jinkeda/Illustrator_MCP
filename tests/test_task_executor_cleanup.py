"""
Test A3: task_executor.jsx Deprecation Cleanup

Verifies:
1. No ops module in manifest depends on task_executor
2. Python files don't hardcode task_executor as include
3. task_executor.jsx is now a small shim (<30 lines)
4. Guard messages in .jsx files reference decomposed modules
"""

import json
import os
import pytest

BASE_DIR = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..",
    "illustrator_mcp"
))

SCRIPTS_DIR = os.path.join(BASE_DIR, "resources", "scripts")
MANIFEST_PATH = os.path.join(SCRIPTS_DIR, "manifest.json")
TASK_EXECUTOR_PATH = os.path.join(SCRIPTS_DIR, "task_executor.jsx")
OPS_CORE_PATH = os.path.join(SCRIPTS_DIR, "ops_core.jsx")
OPS_ELEMENT_PATH = os.path.join(SCRIPTS_DIR, "ops_element.jsx")
EXECUTE_PATH = os.path.join(BASE_DIR, "tools", "execute.py")
QUERY_PATH = os.path.join(BASE_DIR, "tools", "query.py")
ERRORS_PATH = os.path.join(BASE_DIR, "errors.py")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _load_manifest() -> dict:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# Modules that should NOT depend on task_executor
OPS_MODULES = [
    "ops_core", "ops_element", "ops_group", "ops_layer",
    "ops_style", "ops_text", "ops_align", "ops_measure",
    "op_schemas", "test_soc",
]


class TestManifestDeps:
    """Guard tests for manifest dependency rewiring."""

    def test_no_ops_module_depends_on_task_executor(self):
        """No ops module should list task_executor as a dependency."""
        manifest = _load_manifest()
        libs = manifest.get("libraries", {})
        for module in OPS_MODULES:
            if module not in libs:
                continue
            deps = libs[module].get("dependencies", [])
            assert "task_executor" not in deps, (
                f"Module '{module}' still depends on task_executor"
            )

    def test_task_executor_entry_still_exists(self):
        """task_executor should still exist in manifest (deprecated shim)."""
        manifest = _load_manifest()
        libs = manifest.get("libraries", {})
        assert "task_executor" in libs, (
            "task_executor entry missing from manifest"
        )
        assert libs["task_executor"].get("deprecated") is True


class TestTaskExecutorShim:
    """Guard tests for task_executor.jsx shim."""

    def test_shim_is_small(self):
        """task_executor.jsx should be <30 lines (compatibility shim)."""
        content = _read(TASK_EXECUTOR_PATH)
        line_count = len(content.strip().splitlines())
        assert line_count < 30, (
            f"task_executor.jsx is {line_count} lines, expected <30 (shim)"
        )

    def test_shim_has_deprecation_notice(self):
        """task_executor.jsx should contain deprecation notice."""
        content = _read(TASK_EXECUTOR_PATH)
        assert "@deprecated" in content


class TestPythonIncludes:
    """Guard tests for Python-side include updates."""

    def test_execute_py_no_task_executor(self):
        """execute.py should not hardcode task_executor as include."""
        content = _read(EXECUTE_PATH)
        assert '"task_executor"' not in content, (
            "execute.py still references task_executor"
        )

    def test_query_py_no_task_executor(self):
        """query.py should not hardcode task_executor as include."""
        content = _read(QUERY_PATH)
        assert 'includes=["task_executor"]' not in content, (
            "query.py still uses task_executor as include"
        )

    def test_errors_py_no_task_executor(self):
        """errors.py hint should not reference task_executor."""
        content = _read(ERRORS_PATH)
        assert "task_executor" not in content, (
            "errors.py still mentions task_executor in hints"
        )


class TestJSXGuardMessages:
    """Guard tests for JSX guard message updates."""

    def test_ops_core_guard_references_contracts(self):
        """ops_core.jsx guard should reference contracts.jsx, not task_executor."""
        content = _read(OPS_CORE_PATH)
        assert "requires contracts.jsx" in content
        assert "requires task_executor.jsx" not in content

    def test_ops_element_guard_references_targets(self):
        """ops_element.jsx guard should reference targets.jsx, not task_executor."""
        content = _read(OPS_ELEMENT_PATH)
        assert "requires targets.jsx" in content
        assert "requires task_executor.jsx" not in content
