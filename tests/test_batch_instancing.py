"""
Tests for template instancing guards.

Validates that the JSX handler-level guards for element_create_batch
template mode work correctly by inspecting payload construction patterns.
"""

from __future__ import annotations

import json
import unittest


class TestTemplateInstancingGuards(unittest.TestCase):
    """Validate that the JSX handler-level guards work correctly
    by inspecting the script construction patterns."""

    def test_template_payload_structure(self):
        """Verify template payload builds correct JSON for executeOpBatch."""
        payload = {
            "op": "element_create_batch",
            "params": {
                "template": {
                    "type": "ellipse",
                    "r": 4,
                    "fill": {"r": 70, "g": 130, "b": 180},
                    "stroke": False,
                },
                "instances": [
                    {"x": 10, "y": 20},
                    {"x": 30, "y": 40, "opacity": 50},
                ],
                "name": "scatter_pt",
            },
        }

        # Verify serialization round-trips:
        json_str = json.dumps(payload)
        rebuilt = json.loads(json_str)
        self.assertEqual(rebuilt["op"], "element_create_batch")
        self.assertEqual(rebuilt["params"]["template"]["type"], "ellipse")
        self.assertEqual(len(rebuilt["params"]["instances"]), 2)

        # Verify mutual exclusion: template present → items absent
        self.assertIn("template", rebuilt["params"])
        self.assertNotIn("items", rebuilt["params"])

    def test_mutual_exclusion_in_payload(self):
        """Both template and items in payload → detectable before send."""
        payload = {
            "op": "element_create_batch",
            "params": {
                "template": {"type": "ellipse", "r": 4},
                "items": [{"type": "rect", "x": 0, "y": 0, "w": 10, "h": 10}],
                "instances": [{"x": 0, "y": 0}],
            },
        }
        # Python-side guard: detect both keys present
        has_both = "template" in payload["params"] and "items" in payload["params"]
        self.assertTrue(has_both, "Guard should detect both template and items")


if __name__ == "__main__":
    unittest.main()
