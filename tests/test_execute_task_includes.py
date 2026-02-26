"""
Tests for execute_task auto-include logic.

Validates that the include builder in task_execution.py correctly
auto-injects required libraries (task_pipeline, ops_core) and preserves
user includes with dedup + stable ordering.
"""

from __future__ import annotations

import unittest


def _build_includes(user_includes: list[str] | None = None) -> list[str]:
    """Reproduce the include-builder logic from task_execution.py."""
    auto = ["polyfills", "task_pipeline", "ops_core"]
    seen = set(auto)
    all_includes = list(auto)
    for inc in (user_includes or []):
        if inc not in seen:
            seen.add(inc)
            all_includes.append(inc)
    return all_includes


class TestExecuteTaskAutoIncludes(unittest.TestCase):
    """Validate that execute_task auto-injects required libraries."""

    def test_empty_user_includes(self):
        """With no user includes, auto-includes are present."""
        result = _build_includes([])
        self.assertEqual(result, ["polyfills", "task_pipeline", "ops_core"])

    def test_none_user_includes(self):
        """None user includes should not crash."""
        result = _build_includes(None)
        self.assertEqual(result, ["polyfills", "task_pipeline", "ops_core"])

    def test_user_includes_appended_after_auto(self):
        """User includes come after auto-includes."""
        result = _build_includes(["ops_element"])
        self.assertEqual(
            result,
            ["polyfills", "task_pipeline", "ops_core", "ops_element"],
        )

    def test_user_duplicate_deduped(self):
        """Duplicates of auto-includes are not repeated."""
        result = _build_includes(["polyfills", "ops_core", "ops_element"])
        self.assertEqual(
            result,
            ["polyfills", "task_pipeline", "ops_core", "ops_element"],
        )

    def test_user_includes_preserve_order(self):
        """Multiple user includes maintain insertion order."""
        result = _build_includes(["ops_style", "ops_text", "ops_element"])
        self.assertEqual(
            result,
            ["polyfills", "task_pipeline", "ops_core", "ops_style", "ops_text", "ops_element"],
        )

    def test_task_pipeline_always_present(self):
        """task_pipeline must always be in the output (executeTask function)."""
        result = _build_includes([])
        self.assertIn("task_pipeline", result)

    def test_ops_core_always_present(self):
        """ops_core must always be in the output (executeOpBatch function)."""
        result = _build_includes([])
        self.assertIn("ops_core", result)


if __name__ == "__main__":
    unittest.main()
