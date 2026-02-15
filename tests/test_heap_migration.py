"""
Test P2: Heap Migration – Stale ID Index Guard

Ensures no .jsx file references the removed legacy ID index functions:
  invalidateIdIndex, registerIdInIndex, buildIDIndex, resolveById (as a function definition),
  removeFromIdIndex, mcpIdIndex

These were deleted as part of P2 (Smarter ID Index Lifecycle) and replaced by
heap.jsx's transactional API (heapBeginTxn/heapCommitTxn/heapRollbackTxn/heapResolveMany).
"""

import os
import re
import pytest

SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..",
    "illustrator_mcp", "resources", "scripts"
)

# Functions/symbols that must NOT appear as live code (ignoring comments)
BANNED_SYMBOLS = [
    "invalidateIdIndex",
    "registerIdInIndex",
    "buildIDIndex",
    "removeFromIdIndex",
    "mcpIdIndex",
]


def _is_comment_line(line: str) -> bool:
    """Check if a line is a single-line comment or inside a JSDoc block."""
    stripped = line.strip()
    return stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*")


def _scan_jsx_files_for_banned(banned: list[str]) -> list[str]:
    """Scan all .jsx files for banned symbol references in non-comment lines."""
    violations = []
    scripts_dir = os.path.normpath(SCRIPTS_DIR)

    for fname in os.listdir(scripts_dir):
        if not fname.endswith(".jsx"):
            continue
        filepath = os.path.join(scripts_dir, fname)
        with open(filepath, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if _is_comment_line(line):
                    continue
                for sym in banned:
                    if sym in line:
                        violations.append(f"{fname}:{lineno}: {sym} — {line.strip()}")
    return violations


class TestHeapMigrationGuard:
    """Guard tests ensuring the legacy ID index code is fully removed."""

    def test_no_stale_id_index_references(self):
        """No .jsx file should reference removed ID index functions outside comments."""
        violations = _scan_jsx_files_for_banned(BANNED_SYMBOLS)
        assert violations == [], (
            "Stale references to removed ID index functions found:\n"
            + "\n".join(violations)
        )

    def test_manifest_no_stale_exports(self):
        """manifest.json should not export removed functions."""
        import json

        manifest_path = os.path.join(SCRIPTS_DIR, "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        ops_core = manifest["libraries"]["ops_core"]
        exports = ops_core.get("exports", [])

        stale = {"resolveById", "invalidateIdIndex", "registerIdInIndex", "removeFromIdIndex"}
        found = stale & set(exports)
        assert found == set(), f"Stale exports in ops_core manifest: {found}"

    def test_heap_dependency_present(self):
        """ops_core must depend on heap for the transactional index."""
        import json

        manifest_path = os.path.join(SCRIPTS_DIR, "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        deps = manifest["libraries"]["ops_core"].get("dependencies", [])
        assert "heap" in deps, f"'heap' not in ops_core dependencies: {deps}"

    def test_ops_core_uses_heap_txn_lifecycle(self):
        """ops_core.jsx should contain heapBeginTxn, heapCommitTxn, heapRollbackTxn calls."""
        ops_core_path = os.path.join(SCRIPTS_DIR, "ops_core.jsx")
        with open(ops_core_path, "r", encoding="utf-8") as f:
            content = f.read()

        for fn in ["heapBeginTxn", "heapCommitTxn", "heapRollbackTxn"]:
            assert fn in content, f"{fn} not found in ops_core.jsx"

    def test_ops_core_uses_heap_resolve(self):
        """ops_core.jsx should use heapResolveMany for ID resolution."""
        ops_core_path = os.path.join(SCRIPTS_DIR, "ops_core.jsx")
        with open(ops_core_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "heapResolveMany" in content, "heapResolveMany not found in ops_core.jsx"

    def test_element_delete_uses_heap_tombstone(self):
        """element_delete handler should use heapTombstone, not removeFromIdIndex."""
        ops_elem_path = os.path.join(SCRIPTS_DIR, "ops_element.jsx")
        with open(ops_elem_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "heapTombstone" in content, "heapTombstone not found in ops_element.jsx"
        assert "removeFromIdIndex" not in content, "removeFromIdIndex still in ops_element.jsx"
