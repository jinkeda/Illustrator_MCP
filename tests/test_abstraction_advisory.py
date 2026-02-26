"""Tests for _abstraction_advisory() runtime hints."""

import pytest
from illustrator_mcp.tools.execute import _abstraction_advisory, _MAX_ADVISORY_HINTS


class TestAbstractionAdvisory:
    """Verify conservative heuristics emit the right hints."""

    # ── Batch creation: for-loop + shape API ──────────────────────

    def test_loop_with_shape_api_hits(self):
        """for-loop + ≥2 shape API calls → batch hint."""
        script = """
        for (var i = 0; i < 47; i++) {
            doc.pathItems.ellipse(-y, x + i*15, 8, 6);
            doc.pathItems.rectangle(-y, x, 2, 2);
        }
        """
        hints = _abstraction_advisory(script)
        assert len(hints) == 1
        assert "element_create_batch" in hints[0]

    def test_loop_without_shape_api_no_hit(self):
        """for-loop but no shape creation → no hint."""
        script = """
        for (var i = 0; i < 10; i++) {
            items[i].fillColor = c;
        }
        """
        hints = _abstraction_advisory(script)
        assert len(hints) == 0

    def test_shape_api_without_loop_no_hit(self):
        """Single shape call, no loop → no hint."""
        script = "doc.pathItems.ellipse(-100, 50, 200, 100);"
        hints = _abstraction_advisory(script)
        assert len(hints) == 0

    # ── Large setEntirePath ───────────────────────────────────────

    def test_large_set_entire_path_hits(self):
        """setEntirePath with >12 coordinate pairs → path hint."""
        # 15 coordinate pairs
        points = ", ".join([f"[{i*10}, {i*5}]" for i in range(15)])
        script = f"path.setEntirePath([{points}]);"
        hints = _abstraction_advisory(script)
        assert len(hints) == 1
        assert "smooth:true" in hints[0]
        assert "~15" in hints[0] or "path_import_svg" in hints[0]

    def test_small_set_entire_path_no_hit(self):
        """setEntirePath with ≤12 pairs → no hint."""
        points = ", ".join([f"[{i*10}, {i*5}]" for i in range(5)])
        script = f"path.setEntirePath([{points}]);"
        hints = _abstraction_advisory(script)
        assert len(hints) == 0

    # ── Pathfinder menu commands ──────────────────────────────────

    def test_pathfinder_menu_command_hits(self):
        """executeMenuCommand with pathfinder → boolean hint."""
        script = 'app.executeMenuCommand("Live Pathfinder Add");'
        hints = _abstraction_advisory(script)
        assert len(hints) == 1
        assert "path_boolean" in hints[0]

    def test_pathfinder_substring_no_false_positive(self):
        """The word 'pathfinder' in a comment should NOT trigger."""
        script = "// This uses pathfinder-like logic\nvar x = 1;"
        hints = _abstraction_advisory(script)
        assert len(hints) == 0

    # ── Cap at max hints ──────────────────────────────────────────

    def test_max_hints_cap(self):
        """Even with multiple triggers, cap at _MAX_ADVISORY_HINTS."""
        # Trigger all three: loop+shape, large path, pathfinder
        points = ", ".join([f"[{i*10}, {i*5}]" for i in range(20)])
        script = f"""
        for (var i = 0; i < 10; i++) {{
            doc.pathItems.ellipse(-y, x, 8, 6);
            doc.pathItems.rectangle(-y, x, 2, 2);
        }}
        path.setEntirePath([{points}]);
        app.executeMenuCommand("Live Pathfinder Add");
        """
        hints = _abstraction_advisory(script)
        assert len(hints) <= _MAX_ADVISORY_HINTS

    # ── Clean scripts: no false positives ─────────────────────────

    def test_clean_script_no_hints(self):
        """Simple script with no patterns → no hints."""
        script = """
        var doc = app.activeDocument;
        var rect = doc.pathItems.rectangle(-100, 50, 200, 100);
        var c = new RGBColor(); c.red = 255;
        rect.fillColor = c;
        """
        hints = _abstraction_advisory(script)
        assert len(hints) == 0
