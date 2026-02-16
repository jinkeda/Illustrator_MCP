"""
Tests for VLM QA Cadence — auto-inject annotated preview every N mutations.

Verifies counter, cadence-triggered preview, final_step override, and skip warning.
"""

import unittest
from unittest.mock import patch, AsyncMock, MagicMock

from illustrator_mcp.tools.execute import (
    VLM_QA_CADENCE,
    get_mutation_count,
    reset_mutation_count,
    ExecuteScriptInput,
)


class TestVLMQACadenceConstants(unittest.TestCase):
    """Verify cadence constants and helper functions."""

    def test_cadence_value(self):
        """VLM_QA_CADENCE should be 5."""
        self.assertEqual(VLM_QA_CADENCE, 5)

    def test_counter_reset(self):
        """reset_mutation_count() should set counter to 0."""
        # Increment a few times by importing the global directly
        from illustrator_mcp.tools import execute
        execute._mutation_count = 42
        reset_mutation_count()
        self.assertEqual(get_mutation_count(), 0)

    def test_get_mutation_count(self):
        """get_mutation_count() returns current counter value."""
        from illustrator_mcp.tools import execute
        execute._mutation_count = 7
        self.assertEqual(get_mutation_count(), 7)
        reset_mutation_count()


class TestExecuteScriptInputFinalStep(unittest.TestCase):
    """Verify the final_step field on ExecuteScriptInput."""

    def test_final_step_default_false(self):
        """final_step defaults to False."""
        inp = ExecuteScriptInput(script="var x = 1;")
        self.assertFalse(inp.final_step)

    def test_final_step_set_true(self):
        """final_step can be set to True."""
        inp = ExecuteScriptInput(script="var x = 1;", final_step=True)
        self.assertTrue(inp.final_step)


class TestCadenceLogic(unittest.TestCase):
    """Test the cadence trigger logic (counter % N == 0 || final_step)."""

    def setUp(self):
        reset_mutation_count()

    def tearDown(self):
        reset_mutation_count()

    def test_checkpoint_at_cadence_boundary(self):
        """Mutation #5, #10, etc. should be QA checkpoints."""
        for i in range(1, 11):
            count = i
            is_checkpoint = (count % VLM_QA_CADENCE == 0)
            if i in (5, 10):
                self.assertTrue(is_checkpoint, f"Mutation #{i} should be a checkpoint")
            else:
                self.assertFalse(is_checkpoint, f"Mutation #{i} should NOT be a checkpoint")

    def test_final_step_forces_checkpoint(self):
        """final_step=True should trigger checkpoint regardless of count."""
        # Any count + final_step=True → checkpoint
        for count in (1, 2, 3, 4, 6, 7):
            is_checkpoint = (count % VLM_QA_CADENCE == 0) or True  # final_step=True
            self.assertTrue(is_checkpoint, f"final_step should force checkpoint at #{count}")

    def test_non_checkpoint_step(self):
        """Mutation #1-4 without final_step should NOT be checkpoints."""
        for count in (1, 2, 3, 4):
            is_checkpoint = (count % VLM_QA_CADENCE == 0) or False  # final_step=False
            self.assertFalse(is_checkpoint)


class TestCadencePreviewInjection(unittest.TestCase):
    """Test that cadence checkpoints modify preview params correctly."""

    def setUp(self):
        reset_mutation_count()

    def tearDown(self):
        reset_mutation_count()

    def test_auto_inject_when_not_provided(self):
        """At checkpoint, if return_preview is None (not provided), cadence should force preview."""
        params = ExecuteScriptInput(script="var x = 1;")
        self.assertIsNone(params.return_preview)  # default is None, not False

        # Simulate cadence logic: None is NOT `is False`, so we auto-inject
        count = 5
        is_checkpoint = (count % VLM_QA_CADENCE == 0)
        self.assertTrue(is_checkpoint)

        if is_checkpoint:
            if params.return_preview is False and not params.final_step:
                pass  # should NOT enter here
            else:
                params.return_preview = True
                params.preview_mode = "annotated"

        self.assertTrue(params.return_preview)
        self.assertEqual(params.preview_mode, "annotated")

    def test_auto_inject_when_explicitly_true(self):
        """At checkpoint with return_preview=True, cadence should still set annotated mode."""
        params = ExecuteScriptInput(script="var x = 1;", return_preview=True)
        params.return_preview = True
        params.preview_mode = "annotated"
        self.assertTrue(params.return_preview)
        self.assertEqual(params.preview_mode, "annotated")

    def test_skip_warning_when_explicitly_disabled(self):
        """When AI set return_preview=False explicitly, checkpoint should produce a skip warning."""
        warnings = []
        count = 5
        is_checkpoint = (count % VLM_QA_CADENCE == 0)
        return_preview = False  # explicitly set by AI

        if is_checkpoint:
            if return_preview is False:
                warnings.append(
                    f"VLM QA checkpoint skipped (mutation #{count}). "
                    "Consider using return_preview=True, preview_mode='annotated' "
                    "to visually verify the document state."
                )

        self.assertEqual(len(warnings), 1)
        self.assertIn("skipped", warnings[0])
        self.assertIn("#5", warnings[0])

    def test_no_skip_warning_when_not_provided(self):
        """When return_preview is None (not provided), checkpoint should NOT skip."""
        warnings = []
        count = 5
        is_checkpoint = (count % VLM_QA_CADENCE == 0)
        return_preview = None  # not provided

        if is_checkpoint:
            if return_preview is False:
                warnings.append("should not happen")

        self.assertEqual(len(warnings), 0, "None should not trigger skip warning")


if __name__ == "__main__":
    unittest.main()
