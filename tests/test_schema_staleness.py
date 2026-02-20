"""
test_schema_staleness.py - CI guard: fail if op_schemas.json drifts from contracts.py.

Compares parsed JSON dicts (not string equality) to avoid brittleness
from whitespace, ordering, and formatting differences.
"""

import json
from pathlib import Path

import pytest

# Path relative to repo root
SCRIPTS_DIR = Path(__file__).parent.parent / "illustrator_mcp" / "resources" / "scripts"
JSON_PATH = SCRIPTS_DIR / "op_schemas.json"


def _generate_expected() -> dict:
    """Import from gen_schemas and build expected dict."""
    from scripts.gen_schemas import build_schema_dict
    return build_schema_dict()


class TestSchemaStaleness:
    """Ensure generated JSX/JSON schemas stay in sync with contracts.py SSOT."""

    def test_op_schemas_json_exists(self):
        assert JSON_PATH.exists(), (
            f"op_schemas.json not found at {JSON_PATH}. "
            "Run: python -m scripts.gen_schemas"
        )

    def test_op_schemas_json_not_stale(self):
        """Golden-file test: parsed JSON must match contracts.py."""
        if not JSON_PATH.exists():
            pytest.skip("op_schemas.json not generated yet")

        current = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        expected = _generate_expected()

        # Compare as dicts — insensitive to key ordering/whitespace
        assert current == expected, (
            "op_schemas.json is stale (differs from contracts.py). "
            "Run: python -m scripts.gen_schemas\n"
            f"  Current ops: {sorted(current.keys())}\n"
            f"  Expected ops: {sorted(expected.keys())}"
        )

    def test_schema_count_sanity(self):
        """Ensure we didn't accidentally filter out too many ops."""
        expected = _generate_expected()
        # We should have at least 30 ops (the old count). This is a safety
        # net against accidental mass-exclusion.
        assert len(expected) >= 30, (
            f"Only {len(expected)} schemas generated — expected >= 30. "
            "Check SERVER_SIDE_OPS filter."
        )

    def test_server_side_ops_excluded(self):
        """Verify server-side-only ops are not in the JSX schema."""
        from scripts.gen_schemas import SERVER_SIDE_OPS
        expected = _generate_expected()
        for op in SERVER_SIDE_OPS:
            assert op not in expected, (
                f"Server-side op '{op}' should not appear in JSX schemas"
            )
