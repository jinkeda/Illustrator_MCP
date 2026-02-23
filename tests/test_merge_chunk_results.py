"""
Tests for merge_chunk_results utility.

Verifies chunk aggregation for batched OpBatch execution:
- ok = AND(all chunk ok values)
- createdIds = passed through from external accumulator
- stats accumulation
"""

import pytest
from illustrator_mcp.utils.chunking import merge_chunk_results


class TestMergeChunkResults:
    """Test chunk merging logic."""

    def test_merge_all_ok(self):
        """All chunks ok:true → merged ok:true."""
        chunks = [
            {"ok": True, "stats": {"total": 5, "executed": 5, "passed": 5, "failed": 0}},
            {"ok": True, "stats": {"total": 3, "executed": 3, "passed": 3, "failed": 0}},
            {"ok": True, "stats": {"total": 2, "executed": 2, "passed": 2, "failed": 0}},
        ]
        result = merge_chunk_results(chunks, created_ids=["a", "b", "c"])

        assert result["ok"] is True
        assert result["stats"]["total"] == 10
        assert result["stats"]["passed"] == 10
        assert result["stats"]["failed"] == 0
        assert result["chunks"] == 3

    def test_merge_one_failed(self):
        """One chunk ok:false → merged ok:false."""
        chunks = [
            {"ok": True, "stats": {"total": 5, "executed": 5, "passed": 5, "failed": 0}},
            {"ok": False, "stats": {"total": 5, "executed": 5, "passed": 3, "failed": 2},
             "errors": [{"index": 3, "task": "element_create", "error": "Layer locked"}]},
        ]
        result = merge_chunk_results(chunks, created_ids=["a"])

        assert result["ok"] is False
        assert result["stats"]["failed"] == 2
        assert result["errors"] is not None
        assert len(result["errors"]) == 1

    def test_merge_accumulates_ids(self):
        """createdIds from external accumulator are passed through."""
        chunks = [
            {"ok": True, "stats": {"total": 2, "executed": 2, "passed": 2, "failed": 0}},
            {"ok": True, "stats": {"total": 2, "executed": 2, "passed": 2, "failed": 0}},
        ]
        ids = ["id1", "id2", "id3", "id4"]
        result = merge_chunk_results(chunks, created_ids=ids)

        assert result["createdIds"] == ["id1", "id2", "id3", "id4"]

    def test_merge_empty_chunks(self):
        """Empty chunk list → ok:true, empty stats."""
        result = merge_chunk_results([], created_ids=[])

        assert result["ok"] is True
        assert result["createdIds"] == []
        assert result["stats"]["total"] == 0
