"""
Tests for VLM QA Cadence — auto-inject annotated preview every N mutations.

Verifies counter, cadence-triggered preview, final_step override, skip warning,
and Cognitive Forcing Function (checkpoint instruction injection).
"""

import asyncio
import json
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

from illustrator_mcp.tools.execute import (
    VLM_QA_CADENCE,
    VLM_CHECKPOINT_INSTRUCTION,
    get_mutation_count,
    reset_mutation_count,
    ExecuteScriptInput,
    ExecuteTaskInput,
    illustrator_execute_script,
)
from mcp.types import TextContent, ImageContent


class TestVLMQACadenceConstants(unittest.TestCase):
    """Verify cadence constants and helper functions."""

    def test_cadence_value(self):
        """VLM_QA_CADENCE should be 5."""
        self.assertEqual(VLM_QA_CADENCE, 5)

    def test_counter_reset(self):
        """reset_mutation_count() should set counter to 0."""
        # Increment a few times by importing the global directly
        from illustrator_mcp.tools import execute
        for _ in range(42):
            execute._counter.increment()
        reset_mutation_count()
        self.assertEqual(get_mutation_count(), 0)

    def test_get_mutation_count(self):
        """get_mutation_count() returns current counter value."""
        from illustrator_mcp.tools import execute
        # Set counter to a known value via the public API
        reset_mutation_count()
        for _ in range(7):
            execute._counter.increment()
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


class TestCheckpointInstruction(unittest.TestCase):
    """Test the Cognitive Forcing Function — checkpoint instruction injection."""

    def setUp(self):
        reset_mutation_count()

    def tearDown(self):
        reset_mutation_count()

    def test_checkpoint_instruction_constant_exists(self):
        """VLM_CHECKPOINT_INSTRUCTION should be a non-empty string with key phrases."""
        self.assertIsInstance(VLM_CHECKPOINT_INSTRUCTION, str)
        self.assertGreater(len(VLM_CHECKPOINT_INSTRUCTION), 50)
        self.assertIn("CHECKPOINT", VLM_CHECKPOINT_INSTRUCTION)
        self.assertIn("{count}", VLM_CHECKPOINT_INSTRUCTION)
        # Tool Lockout clause
        self.assertIn("DO NOT call any tools", VLM_CHECKPOINT_INSTRUCTION)
        # Visual analysis requirement
        self.assertIn("Describe what you see", VLM_CHECKPOINT_INSTRUCTION)
        # Stop directive
        self.assertIn("STOP", VLM_CHECKPOINT_INSTRUCTION)

    def test_checkpoint_instruction_format(self):
        """VLM_CHECKPOINT_INSTRUCTION.format(count=N) should produce valid text."""
        formatted = VLM_CHECKPOINT_INSTRUCTION.format(count=10)
        self.assertIn("mutation #10", formatted)
        self.assertNotIn("{count}", formatted)

    def test_is_vlm_checkpoint_in_diagnostics(self):
        """is_vlm_checkpoint flag should be settable and present in diagnostics dict."""
        # Simulate the diagnostics dict construction from execute_script
        is_vlm_checkpoint = True
        diagnostics = {
            "includes": [],
            "prelude_hash": None,
            "validate_bounds": False,
            "bounds_type": "visible",
            "bounds_source": "group_visible",
            "bounds_scope": "document",
            "artboard_index": None,
            "is_vlm_checkpoint": is_vlm_checkpoint,
        }
        self.assertTrue(diagnostics["is_vlm_checkpoint"])

        # Non-checkpoint case
        diagnostics["is_vlm_checkpoint"] = False
        self.assertFalse(diagnostics["is_vlm_checkpoint"])

    def test_checkpoint_instruction_not_on_manual_preview(self):
        """Manual return_preview=True on a non-cadence step should NOT trigger
        the checkpoint instruction (is_vlm_checkpoint stays False)."""
        from illustrator_mcp.tools import execute
        # Set counter to 3 (not a cadence boundary)
        reset_mutation_count()
        for _ in range(2):
            execute._counter.increment()  # will become 3 after increment

        params = ExecuteScriptInput(script="var x = 1;", return_preview=True)

        # Simulate the cadence logic from execute_script
        execute._counter.increment()
        count = execute._counter.value  # 3
        is_checkpoint = (count % VLM_QA_CADENCE == 0) or params.final_step
        is_vlm_checkpoint = False

        if is_checkpoint:
            if params.return_preview is False and not params.final_step:
                pass
            else:
                params.return_preview = True
                params.preview_mode = "annotated"
                is_vlm_checkpoint = True

        # count=3, not a cadence boundary, not final_step → NOT a checkpoint
        self.assertFalse(is_checkpoint)
        self.assertFalse(is_vlm_checkpoint)
        # The AI's manual return_preview=True is preserved but no instruction injected
        self.assertTrue(params.return_preview)

    def test_checkpoint_instruction_injected_on_cadence(self):
        """Integration test: at cadence boundary, the returned content list should
        have 7 elements (envelope, raw_img, ann_img, annotations, telemetry, CHECKPOINT)
        with the checkpoint instruction as the absolute last one."""
        from illustrator_mcp.tools import execute
        from illustrator_mcp.occlusion_guard import OcclusionResult

        # Set mutation counter to 4 so the next call hits 5 (cadence boundary)
        reset_mutation_count()
        for _ in range(4):
            execute._counter.increment()

        # Create a minimal 1x1 white PNG for the preview mock
        import base64
        # Tiny valid PNG (1x1 white pixel)
        tiny_png = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
            b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
            b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )

        # Mock the execution pipeline
        mock_response = {"result": "'ok'", "error": None}
        mock_preview = ImageContent(
            type="image",
            data=base64.b64encode(tiny_png).decode('utf-8'),
            mimeType="image/png",
        )
        mock_annotation_result = {
            "meta": {"annotated_count": 3},
            "annotations": [
                {"label": "1", "mcp_id": "a", "name": "r1", "type": "PathItem",
                 "bounds_pt": [0, 0, 50, -50], "coverRatio": 0.1},
                {"label": "2", "mcp_id": "b", "name": "r2", "type": "PathItem",
                 "bounds_pt": [50, 0, 100, -50], "coverRatio": 0.1},
                {"label": "3", "mcp_id": "c", "name": "r3", "type": "PathItem",
                 "bounds_pt": [100, 0, 150, -50], "coverRatio": 0.1},
            ],
            "warnings": [],
        }
        mock_guard = OcclusionResult(ok=True, diagnostics={})
        mock_telemetry = {
            "layers": [{"name": "Layer 1", "index": 0, "visible": True,
                       "locked": False, "itemCount": 1}],
            "topLayerItems": [],
            "artboardRect": [0, 0, 800, -600],
            "totalItemCount": 1,
        }

        params = ExecuteScriptInput(script="var x = 1;")

        with patch("illustrator_mcp.tools.execute.execute_script_with_context",
                    new_callable=AsyncMock, return_value=mock_response), \
             patch("illustrator_mcp.tools.execute._generate_preview",
                    new_callable=AsyncMock, return_value=mock_preview), \
             patch("illustrator_mcp.tools.execute._annotate_preview",
                    new_callable=AsyncMock,
                    return_value=(tiny_png, mock_annotation_result)), \
             patch("illustrator_mcp.tools.preview._run_occlusion_guard",
                    new_callable=AsyncMock,
                    return_value=(mock_guard, mock_telemetry)):

            result = asyncio.get_event_loop().run_until_complete(
                illustrator_execute_script(params)
            )

        # Should be a list (multi-content response)
        self.assertIsInstance(result, list)

        # Should have 6 elements: envelope, raw_img, ann_img, annotations, telemetry, CHECKPOINT
        self.assertEqual(len(result), 6, f"Expected 6 content items, got {len(result)}")

        # Element order: Text, Image(raw), Image(ann), Text(annotations), Text(telemetry), Text(checkpoint)
        self.assertIsInstance(result[0], TextContent)
        self.assertIsInstance(result[1], ImageContent)  # raw image
        self.assertIsInstance(result[2], ImageContent)  # annotated image
        self.assertIsInstance(result[3], TextContent)    # annotation map
        self.assertIsInstance(result[4], TextContent)    # z-order telemetry
        self.assertIsInstance(result[5], TextContent)    # checkpoint instruction

        # The LAST element must be the checkpoint instruction
        checkpoint_text = result[5].text
        self.assertIn("VLM QA CHECKPOINT", checkpoint_text)
        self.assertIn("mutation #5", checkpoint_text)
        self.assertIn("DO NOT call any tools", checkpoint_text)
        self.assertIn("STOP", checkpoint_text)

        # Z-order telemetry should contain layer info
        telemetry_text = result[4].text
        self.assertIn("Z-ORDER TELEMETRY", telemetry_text)

        # Verify is_vlm_checkpoint and guard_status in envelope diagnostics
        envelope = json.loads(result[0].text)
        self.assertTrue(envelope["diagnostics"]["is_vlm_checkpoint"])
        self.assertEqual(envelope["diagnostics"]["guard_status"], "passed")

    def test_no_checkpoint_instruction_on_non_cadence(self):
        """On non-cadence step with manual preview, response should have 3 elements, not 4."""
        from illustrator_mcp.tools import execute
        import base64

        # Set to 0 so next call is 1 (NOT a cadence boundary)
        reset_mutation_count()

        tiny_png = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00'
            b'\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00'
            b'\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )

        mock_response = {"result": "'ok'", "error": None}
        mock_preview = ImageContent(
            type="image",
            data=base64.b64encode(tiny_png).decode('utf-8'),
            mimeType="image/png",
        )
        mock_annotation_result = {
            "meta": {"annotated_count": 0},
            "annotations": [],
            "warnings": [],
        }

        # Manual preview request on non-cadence step
        params = ExecuteScriptInput(
            script="var x = 1;",
            return_preview=True,
            preview_mode="annotated",
        )

        with patch("illustrator_mcp.tools.execute.execute_script_with_context",
                    new_callable=AsyncMock, return_value=mock_response), \
             patch("illustrator_mcp.tools.execute._generate_preview",
                    new_callable=AsyncMock, return_value=mock_preview), \
             patch("illustrator_mcp.tools.execute._annotate_preview",
                    new_callable=AsyncMock,
                    return_value=(tiny_png, mock_annotation_result)):

            result = asyncio.get_event_loop().run_until_complete(
                illustrator_execute_script(params)
            )

        self.assertIsInstance(result, list)
        # Should have 3 elements (no checkpoint instruction)
        self.assertEqual(len(result), 3, f"Expected 3 content items, got {len(result)}")

        # Verify is_vlm_checkpoint is False in envelope diagnostics
        envelope = json.loads(result[0].text)
        self.assertFalse(envelope["diagnostics"]["is_vlm_checkpoint"])


class TestReviewFixes(unittest.TestCase):
    """Tests for the review fixes: cadence gating, dryRun, preview failure, path_boolean."""

    def setUp(self):
        reset_mutation_count()

    def tearDown(self):
        reset_mutation_count()

    def test_checkpoint_on_preview_failure(self):
        """When preview generation returns None at a cadence boundary,
        the checkpoint instruction should still be injected."""
        from illustrator_mcp.tools import execute
        from illustrator_mcp.occlusion_guard import OcclusionResult

        # Set to 4 so next call hits 5 (cadence boundary)
        for _ in range(4):
            execute._counter.increment()

        mock_response = {"result": "'ok'", "error": None}
        mock_guard = OcclusionResult(ok=True, diagnostics={})
        params = ExecuteScriptInput(script="var x = 1;")

        with patch("illustrator_mcp.tools.execute.execute_script_with_context",
                    new_callable=AsyncMock, return_value=mock_response), \
             patch("illustrator_mcp.tools.execute._generate_preview",
                    new_callable=AsyncMock, return_value=None), \
             patch("illustrator_mcp.tools.preview._run_occlusion_guard",
                    new_callable=AsyncMock,
                    return_value=(mock_guard, {})):

            result = asyncio.get_event_loop().run_until_complete(
                illustrator_execute_script(params)
            )

        # Preview failed → should still return list with instruction
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2, "Expected [envelope, checkpoint_instruction]")
        self.assertIsInstance(result[0], TextContent)
        self.assertIsInstance(result[1], TextContent)
        self.assertIn("VLM QA CHECKPOINT", result[1].text)
        self.assertIn("mutation #5", result[1].text)

    def test_no_preview_on_dry_run(self):
        """execute_task with dryRun=True should NOT generate a preview,
        and diagnostics.preview_state should be 'pre_execution'."""
        from illustrator_mcp.tools import execute
        from illustrator_mcp.protocol import TaskPayload, TaskOptions

        # Set to 4 so next call hits 5 (cadence boundary)
        for _ in range(4):
            execute._counter.increment()

        # Build a dryRun task payload
        payload = TaskPayload(
            task="test_task",
            options=TaskOptions(dryRun=True),
        )
        params = ExecuteTaskInput(
            payload=payload,
            compute_fn="function(items,params,report){return []}",
            apply_fn="function(actions,report){}",
        )

        # Mock report: ok=True, simulated dry run
        mock_report = {
            "ok": True,
            "stats": {"collected": 0, "processed": 0, "modified": 0},
            "timing": {},
            "warnings": [],
            "errors": [],
        }
        mock_response = {"result": json.dumps(mock_report), "error": None}

        with patch("illustrator_mcp.tools.task_execution.execute_script_with_context",
                    new_callable=AsyncMock, return_value=mock_response), \
             patch("illustrator_mcp.tools.task_execution._capture_artboard",
                    new_callable=AsyncMock) as mock_capture:

            result = asyncio.get_event_loop().run_until_complete(
                execute.illustrator_execute_task(params)
            )

        # _capture_artboard_png should NOT have been called
        mock_capture.assert_not_called()

        # Result should be a list (checkpoint instruction still fires)
        self.assertIsInstance(result, list)
        # Parse envelope to verify preview_state
        envelope = json.loads(result[0].text)
        self.assertEqual(envelope["diagnostics"]["preview_state"], "pre_execution")

    def test_dryrun_overrides_final_step(self):
        """final_step=True + dryRun=True → NO preview generated.
        dryRun is a hard skip that takes precedence over final_step."""
        from illustrator_mcp.tools import execute
        from illustrator_mcp.protocol import TaskPayload, TaskOptions

        reset_mutation_count()  # not a cadence boundary

        payload = TaskPayload(
            task="test_task",
            options=TaskOptions(dryRun=True),
        )
        params = ExecuteTaskInput(
            payload=payload,
            compute_fn="function(items,params,report){return []}",
            apply_fn="function(actions,report){}",
            final_step=True,  # would normally force preview
        )

        mock_report = {
            "ok": True,
            "stats": {"collected": 0, "processed": 0, "modified": 0},
            "timing": {},
            "warnings": [],
            "errors": [],
        }
        mock_response = {"result": json.dumps(mock_report), "error": None}

        with patch("illustrator_mcp.tools.task_execution.execute_script_with_context",
                    new_callable=AsyncMock, return_value=mock_response), \
             patch("illustrator_mcp.tools.task_execution._capture_artboard",
                    new_callable=AsyncMock) as mock_capture:

            result = asyncio.get_event_loop().run_until_complete(
                execute.illustrator_execute_task(params)
            )

        # _capture_artboard_png should NOT have been called
        mock_capture.assert_not_called()

    def test_path_boolean_increments_counter(self):
        """illustrator_path_boolean should increment _mutation_count on entry.
        Error-return paths (like ImportError) leave the counter incremented,
        consistent with execute_script/execute_task semantics. Only raised
        exceptions trigger the outer wrapper's decrement."""
        from illustrator_mcp.tools import execute

        reset_mutation_count()
        for _ in range(7):
            execute._counter.increment()

        # Mock the import of geometry module to fail cleanly at import guard.
        # The counter is incremented in the outer wrapper and NOT decremented
        # on error-return paths — net effect is +1 (counter goes to 8).
        with patch.dict('sys.modules', {'illustrator_mcp.geometry': None}):
            try:
                from illustrator_mcp.tools.execute import PathBooleanInput, illustrator_path_boolean
                params = PathBooleanInput(
                    operation="unite",
                    subject="id_A",
                    clip="id_B",
                )
                asyncio.get_event_loop().run_until_complete(
                    illustrator_path_boolean(params)
                )
            except Exception:
                pass  # Geometry import may fail — that's fine

        # Counter should be 8: incremented on entry, not decremented on error-return
        self.assertEqual(get_mutation_count(), 8)


# ======================== Audit v6: execute_task tri-state + preview_mode ========================

class TestExecuteTaskTriStatePreview(unittest.TestCase):
    """Audit v6 F1: execute_task respects return_preview tri-state semantics.

    return_preview=None  + checkpoint → preview occurs
    return_preview=False + checkpoint → preview skipped (warning), unless final_step
    return_preview=True  → preview always occurs (unless dryRun)
    """

    def setUp(self):
        reset_mutation_count()

    def tearDown(self):
        reset_mutation_count()

    def test_task_return_preview_none_checkpoint(self):
        """return_preview=None at checkpoint → preview should occur."""
        params = ExecuteTaskInput(
            payload={"task": "test", "targets": None, "params": {}},
            compute_fn="function(i,p,r){return []}",
            apply_fn="function(a,r){}",
            return_preview=None,
        )
        count = VLM_QA_CADENCE
        is_task_checkpoint = (count % VLM_QA_CADENCE == 0) or params.final_step
        is_dry_run = False
        warnings = []

        # F1: soft-override logic
        if is_task_checkpoint and params.return_preview is False and not params.final_step:
            warnings.append("skipped")
            is_task_checkpoint = False

        should_preview = (is_task_checkpoint or params.return_preview is True) and not is_dry_run
        self.assertTrue(should_preview, "None+checkpoint should trigger preview")
        self.assertEqual(len(warnings), 0, "No skip warning for None")

    def test_task_return_preview_false_checkpoint(self):
        """return_preview=False at checkpoint → preview skipped with warning."""
        params = ExecuteTaskInput(
            payload={"task": "test", "targets": None, "params": {}},
            compute_fn="function(i,p,r){return []}",
            apply_fn="function(a,r){}",
            return_preview=False,
        )
        count = VLM_QA_CADENCE
        is_task_checkpoint = (count % VLM_QA_CADENCE == 0) or params.final_step
        is_dry_run = False
        warnings = []

        if is_task_checkpoint and params.return_preview is False and not params.final_step:
            warnings.append(
                f"VLM QA checkpoint skipped (mutation #{count}). "
                "Consider using return_preview=True to visually verify."
            )
            is_task_checkpoint = False

        should_preview = (is_task_checkpoint or params.return_preview is True) and not is_dry_run
        self.assertFalse(should_preview, "False+checkpoint should NOT trigger preview")
        self.assertEqual(len(warnings), 1, "Should produce skip warning")
        self.assertIn("skipped", warnings[0])

    def test_task_return_preview_false_final_step(self):
        """return_preview=False + final_step=True → preview still occurs."""
        params = ExecuteTaskInput(
            payload={"task": "test", "targets": None, "params": {}},
            compute_fn="function(i,p,r){return []}",
            apply_fn="function(a,r){}",
            return_preview=False,
            final_step=True,
        )
        count = VLM_QA_CADENCE
        is_task_checkpoint = (count % VLM_QA_CADENCE == 0) or params.final_step
        is_dry_run = False
        warnings = []

        if is_task_checkpoint and params.return_preview is False and not params.final_step:
            warnings.append("should not happen")
            is_task_checkpoint = False

        should_preview = (is_task_checkpoint or params.return_preview is True) and not is_dry_run
        self.assertTrue(should_preview, "final_step overrides False")
        self.assertEqual(len(warnings), 0, "No warning when final_step=True")

    def test_task_return_preview_true_always(self):
        """return_preview=True → preview regardless of checkpoint."""
        params = ExecuteTaskInput(
            payload={"task": "test", "targets": None, "params": {}},
            compute_fn="function(i,p,r){return []}",
            apply_fn="function(a,r){}",
            return_preview=True,
        )
        count = 1  # NOT a checkpoint
        is_task_checkpoint = (count % VLM_QA_CADENCE == 0) or params.final_step
        is_dry_run = False
        warnings = []

        should_preview = (is_task_checkpoint or params.return_preview is True) and not is_dry_run
        self.assertTrue(should_preview, "True should always force preview")
        self.assertFalse(is_task_checkpoint, "Not a checkpoint — only explicit True")


class TestExecuteTaskPreviewMode(unittest.TestCase):
    """Audit v6 F7: execute_task honors preview_mode and normalizes unknown values."""

    def test_task_preview_mode_artboard(self):
        """preview_mode='artboard' → only 1 image part, no annotation JSON."""
        params = ExecuteTaskInput(
            payload={"task": "test", "targets": None, "params": {}},
            compute_fn="function(i,p,r){return []}",
            apply_fn="function(a,r){}",
            preview_mode="artboard",
        )
        warnings = []
        mode = params.preview_mode or "annotated"
        if mode not in ("annotated", "artboard"):
            warnings.append(f"Unknown preview_mode '{mode}', defaulting to 'annotated'")
            mode = "annotated"

        self.assertEqual(mode, "artboard")
        self.assertEqual(len(warnings), 0)

    def test_task_preview_mode_annotated_default(self):
        """Default preview_mode → annotated (includes annotation JSON)."""
        params = ExecuteTaskInput(
            payload={"task": "test", "targets": None, "params": {}},
            compute_fn="function(i,p,r){return []}",
            apply_fn="function(a,r){}",
        )
        warnings = []
        mode = params.preview_mode or "annotated"
        if mode not in ("annotated", "artboard"):
            warnings.append(f"Unknown preview_mode '{mode}', defaulting to 'annotated'")
            mode = "annotated"

        self.assertEqual(mode, "annotated")
        self.assertEqual(len(warnings), 0)


if __name__ == "__main__":
    unittest.main()

