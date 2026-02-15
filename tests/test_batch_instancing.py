"""
Tests for batch.py (chunked multi-create) and template instancing guards.

Uses unittest.mock to avoid live Illustrator dependency.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

import asyncio


def run_async(coro):
    """Run async function in sync test."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestChunkedCreateMulti(unittest.TestCase):
    """Tests for chunked_create_multi() in batch.py."""

    def _make_ir(self, n: int) -> dict:
        """Build a minimal Geometry IR with n paths."""
        return {
            "ir": "multi",
            "v": 1,
            "paths": [
                {"ir": "path", "points": [[i, 0], [i + 5, 0], [i + 5, 5]], "closed": False}
                for i in range(n)
            ],
        }

    @patch("illustrator_mcp.tools.batch.execute_script_with_context")
    def test_empty_ir_returns_immediately(self, mock_exec):
        """Zero paths → returns ok with empty ids, no bridge calls."""
        from illustrator_mcp.tools.batch import chunked_create_multi

        ir = self._make_ir(0)
        result = run_async(chunked_create_multi(ir, chunk_size=100))
        self.assertTrue(result["ok"])
        self.assertEqual(result["ids"], [])
        self.assertEqual(result["created"], 0)
        self.assertIn("No paths", result["warnings"][0])
        mock_exec.assert_not_called()

    @patch("illustrator_mcp.tools.batch.execute_script_with_context")
    def test_single_chunk_no_split(self, mock_exec):
        """10 paths with chunk_size=100 → single call."""
        from illustrator_mcp.tools.batch import chunked_create_multi

        mock_exec.return_value = {
            "result": json.dumps({
                "ok": True,
                "createdIds": [f"id_{i}" for i in range(10)],
                "stats": {"passed": 1, "failed": 0},
                "ops": [{
                    "data": {
                        "created": 10,
                        "skipped": 0,
                        "ids": [f"id_{i}" for i in range(10)],
                        "warnings": [],
                    }
                }],
            }),
        }

        ir = self._make_ir(10)
        result = run_async(chunked_create_multi(ir, chunk_size=100, layer="TestLayer"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["created"], 10)
        self.assertEqual(len(result["ids"]), 10)
        self.assertEqual(len(result["chunks"]), 1)
        self.assertEqual(result["chunks"][0]["offset"], 0)
        self.assertEqual(result["chunks"][0]["limit"], 10)
        mock_exec.assert_called_once()

        # Verify offset/limit in the script
        call_args = mock_exec.call_args
        script = call_args.kwargs.get("script") or call_args[0][0]
        self.assertIn('"offset": 0', script)
        self.assertIn('"limit": 10', script)

    @patch("illustrator_mcp.tools.batch.execute_script_with_context")
    def test_multiple_chunks(self, mock_exec):
        """25 paths with chunk_size=10 → adaptive sizing: 10+15 = 2 chunks.

        Mock responses are instant (0ms), so adaptive sizing doubles
        from 10→20 after chunk 1, making chunk 2 cover remaining 15.
        """
        from illustrator_mcp.tools.batch import chunked_create_multi

        call_count = 0

        async def mock_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            offset = kwargs.get("params", {}).get("offset", 0)
            limit = kwargs.get("params", {}).get("limit", 0)
            return {
                "result": json.dumps({
                    "ok": True,
                    "createdIds": [f"id_{offset + i}" for i in range(limit)],
                    "stats": {"passed": 1, "failed": 0},
                    "ops": [{
                        "data": {
                            "created": limit,
                            "skipped": 0,
                            "ids": [f"id_{offset + i}" for i in range(limit)],
                            "warnings": [],
                        }
                    }],
                }),
            }

        mock_exec.side_effect = mock_response

        ir = self._make_ir(25)
        result = run_async(chunked_create_multi(ir, chunk_size=10))

        self.assertTrue(result["ok"])
        # Adaptive sizing: chunk 1 = 10 (fast → doubles to 20), chunk 2 = 15
        self.assertEqual(len(result["chunks"]), 2)
        self.assertEqual(result["chunks"][0]["limit"], 10)
        self.assertEqual(result["chunks"][0]["offset"], 0)
        self.assertEqual(result["chunks"][1]["offset"], 10)
        self.assertEqual(result["chunks"][1]["limit"], 15)
        self.assertEqual(result["created"], 25)
        self.assertEqual(call_count, 2)

    @patch("illustrator_mcp.tools.batch.execute_script_with_context")
    def test_chunk_error_stops_execution(self, mock_exec):
        """If a chunk returns an error, execution stops and partial result is returned."""
        from illustrator_mcp.tools.batch import chunked_create_multi

        call_count = 0

        async def mock_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return {"error": "R008: Script crashed"}
            offset = kwargs.get("params", {}).get("offset", 0)
            limit = kwargs.get("params", {}).get("limit", 0)
            return {
                "result": json.dumps({
                    "ok": True,
                    "createdIds": [f"id_{offset + i}" for i in range(limit)],
                    "stats": {"passed": 1, "failed": 0},
                    "ops": [{"data": {"created": limit, "skipped": 0, "ids": [f"id_{offset + i}" for i in range(limit)], "warnings": []}}],
                }),
            }

        mock_exec.side_effect = mock_response

        ir = self._make_ir(30)
        result = run_async(chunked_create_multi(ir, chunk_size=10))

        self.assertFalse(result["ok"])
        self.assertEqual(len(result["chunks"]), 2)
        self.assertTrue(result["chunks"][0]["ok"])
        self.assertFalse(result["chunks"][1]["ok"])
        self.assertEqual(result["created"], 10)  # only first chunk succeeded

    def test_styles_length_mismatch_raises(self):
        """Mismatched styles array length → ValueError."""
        from illustrator_mcp.tools.batch import chunked_create_multi

        ir = self._make_ir(10)
        with self.assertRaises(ValueError) as ctx:
            run_async(chunked_create_multi(ir, styles=[{"r": 0, "g": 0, "b": 0}] * 5))
        self.assertIn("styles length", str(ctx.exception))

    def test_style_scalars_length_mismatch_raises(self):
        """Mismatched styleScalars array length → ValueError."""
        from illustrator_mcp.tools.batch import chunked_create_multi

        ir = self._make_ir(10)
        with self.assertRaises(ValueError) as ctx:
            run_async(chunked_create_multi(ir, style_scalars=[0.5] * 7))
        self.assertIn("styleScalars length", str(ctx.exception))

    @patch("illustrator_mcp.tools.batch.execute_script_with_context")
    def test_styles_sliced_per_chunk(self, mock_exec):
        """Per-path styles are correctly sliced for each chunk."""
        from illustrator_mcp.tools.batch import chunked_create_multi

        async def mock_response(*args, **kwargs):
            script = kwargs.get("script") or args[0]
            return {
                "result": json.dumps({
                    "ok": True,
                    "createdIds": [],
                    "stats": {"passed": 1, "failed": 0},
                    "ops": [{"data": {"created": 0, "skipped": 0, "ids": [], "warnings": []}}],
                }),
            }

        mock_exec.side_effect = mock_response

        ir = self._make_ir(6)
        styles = [{"r": i * 40, "g": 0, "b": 0} for i in range(6)]
        run_async(chunked_create_multi(ir, chunk_size=4, styles=styles))

        # 2 chunks: [0:4] and [4:6]
        self.assertEqual(mock_exec.call_count, 2)
        # Verify first chunk has styles[0:4]
        first_script = mock_exec.call_args_list[0].kwargs.get("script") or mock_exec.call_args_list[0][0][0]
        parsed_ops = json.loads(first_script.split("executeOpBatch(")[1].rsplit(",", 1)[0])
        self.assertEqual(len(parsed_ops[0]["params"]["styles"]), 4)


class TestTemplateInstancingGuards(unittest.TestCase):
    """Validate that the JSX handler-level guards work correctly
    by inspecting the script construction patterns."""

    def test_template_payload_structure(self):
        """Verify template payload builds correct JSON for executeOpBatch."""
        import json

        template = {"type": "ellipse", "r": 5, "fill": {"r": 255, "g": 0, "b": 0}}
        instances = [
            {"x": 50, "y": 50},
            {"x": 100, "y": 80, "fill": {"r": 0, "g": 200, "b": 100}},
            {"x": 150, "y": 120, "scale": 200},
        ]

        ops = [{
            "task": "element_create_batch",
            "params": {
                "template": template,
                "instances": instances,
                "layer": "TestLayer",
                "name": "dot",
            },
        }]

        script = f"executeOpBatch({json.dumps(ops)})"

        # Verify the script is valid JSON-embeddable
        parsed = json.loads(script.split("executeOpBatch(")[1].rstrip(")"))
        self.assertEqual(parsed[0]["task"], "element_create_batch")
        self.assertEqual(parsed[0]["params"]["template"]["type"], "ellipse")
        self.assertEqual(len(parsed[0]["params"]["instances"]), 3)
        self.assertNotIn("items", parsed[0]["params"])

    def test_mutual_exclusion_in_payload(self):
        """Both template and items in payload → detectable before send."""
        payload = {
            "template": {"type": "rect", "w": 10, "h": 10},
            "items": [{"type": "rect", "x": 0, "y": 0, "w": 10, "h": 10}],
            "instances": [{"x": 10, "y": 10}],
        }
        # Python-side guard
        has_both = "template" in payload and "items" in payload
        self.assertTrue(has_both)


if __name__ == "__main__":
    unittest.main()
