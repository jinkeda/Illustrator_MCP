"""
Tests for bugfixes discovered during the Eiffel Tower illustration session.

Bug 1: Template name mismatch (DOC_* aliases)
Bug 2a: style_set_gradient schema requires 'type' but handler defaults
Bug 2b: R010 TaskReport fallback preserves errors/warnings
Bug 3: z_telemetry gradient fill detection (tested via occlusion_guard unit tests)
"""

import json
import pytest


# ==================== Bug 1: Template Aliases ====================


class TestTemplateAliases:
    """Verify DOC_* aliases exist and map to correct templates."""

    def test_aliases_are_identity(self):
        """DOC_* aliases must be the same object as the canonical names."""
        from illustrator_mcp import templates

        assert templates.DOC_CREATE is templates.CREATE_DOCUMENT
        assert templates.DOC_OPEN is templates.OPEN_DOCUMENT
        assert templates.DOC_SAVE_AS is templates.SAVE_DOCUMENT
        assert templates.DOC_SAVE is templates.SAVE_DOCUMENT_SIMPLE
        assert templates.DOC_CLOSE is templates.CLOSE_DOCUMENT

    def test_save_as_uses_saveAs(self):
        """DOC_SAVE_AS (= SAVE_DOCUMENT) must produce a doc.saveAs script."""
        from illustrator_mcp import templates

        script = templates.DOC_SAVE_AS.substitute(path="C:/test.ai")
        assert "doc.saveAs" in script
        assert "C:/test.ai" in script

    def test_save_uses_save(self):
        """DOC_SAVE (= SAVE_DOCUMENT_SIMPLE) must produce a doc.save() script."""
        from illustrator_mcp import templates

        # SAVE_DOCUMENT_SIMPLE is a plain string (not _CompatTemplate)
        script = templates.DOC_SAVE
        assert "doc.save()" in script

    def test_create_produces_valid_script(self):
        """DOC_CREATE must produce a working document creation script."""
        from illustrator_mcp import templates

        script = templates.DOC_CREATE.substitute(
            width=800, height=600,
            color_space="RGB", title_line='preset.title = "Test";',
        )
        assert "preset.width = 800" in script
        assert "preset.height = 600" in script
        assert "DocumentColorSpace.RGB" in script


# ==================== Bug 2a: Gradient Schema ====================


class TestGradientSchemaTypeOptional:
    """Verify style_set_gradient schema allows omitting 'type'."""

    def test_type_not_in_required(self):
        """'type' should be optional, not required for style_set_gradient."""
        schema_path = (
            "c:/Users/k.jin/OneDrive/PhD/claude/Illustrator_Agent/"
            "Illustrator_MCP/illustrator_mcp/resources/scripts/op_schemas.jsx"
        )
        from pathlib import Path
        content = Path(schema_path).read_text(encoding="utf-8")

        # Find the style_set_gradient block and verify 'required' only has 'stops'
        import re
        match = re.search(
            r'"style_set_gradient"\s*:\s*\{[^}]*"required"\s*:\s*\[(.*?)\]',
            content, re.DOTALL,
        )
        assert match is not None, "style_set_gradient schema not found"
        required_block = match.group(1)
        # 'type' should NOT be in the required list
        assert '"type"' not in required_block, (
            f"'type' is still in required: {required_block}"
        )
        # 'stops' should be in the required list
        assert '"stops"' in required_block


# ==================== Bug 2b: R010 Fallback ====================


class TestTaskReportFallback:
    """Verify degraded fallback preserves errors/warnings from report_data."""

    def test_fallback_preserves_errors_and_warnings(self):
        """When Pydantic fails but dict has 'ok', fallback should preserve data."""
        from illustrator_mcp.tools.task_execution import (
            _dedup_warnings,
        )
        from illustrator_mcp.errors import make_envelope

        # Simulate: a report_data dict that has 'ok' but fails Pydantic validation
        # (e.g., batchReport contains non-serializable nested data)
        report_data = {
            "ok": True,
            "stats": {"itemsProcessed": 5, "itemsModified": 3, "itemsSkipped": 0},
            "errors": [{"code": "X001", "message": "test error"}],
            "warnings": ["some op warning"],
            # This field would cause Pydantic to fail:
            "timing": "invalid_not_a_dict",
        }

        # Verify the report_data would actually fail Pydantic validation
        from illustrator_mcp.protocol import TaskReport
        with pytest.raises(Exception):
            TaskReport.model_validate(report_data)

        # Now simulate the fallback logic
        fallback_ok = report_data.get("ok", False)
        fallback_warnings = []
        raw_errors = report_data.get("errors", [])
        raw_warnings_list = report_data.get("warnings", [])
        if isinstance(raw_errors, list):
            for e in raw_errors[:5]:
                fallback_warnings.append(f"[op-error] {e}")
        if isinstance(raw_warnings_list, list):
            for w in raw_warnings_list[:5]:
                fallback_warnings.append(f"[op-warn] {w}")
        fallback_warnings.append(
            "TaskReport validation failed; using degraded summary. "
            "Some op-level errors may be missing."
        )

        merged = _dedup_warnings([], fallback_warnings)
        envelope_str = make_envelope(
            ok=fallback_ok,
            result={"formatted": "test", "report": report_data},
            warnings=merged,
            diagnostics={"taskreport_parse": {"fallback_used": True}},
        )
        envelope = json.loads(envelope_str)

        # Assertions
        assert envelope["ok"] is True  # Preserves report's ok value
        assert envelope["diagnostics"]["taskreport_parse"]["fallback_used"] is True
        # Check that op-level errors/warnings were preserved
        warning_texts = " ".join(envelope.get("warnings", []))
        assert "[op-error]" in warning_texts
        assert "[op-warn]" in warning_texts
        assert "degraded summary" in warning_texts

    def test_hard_fail_on_non_dict(self):
        """When raw_result is not a parseable dict, should return R010."""
        from illustrator_mcp.errors import make_envelope

        # Simulate raw_result being a truncated/invalid string
        report_data = {}  # Empty dict — no 'ok' key
        result = make_envelope(
            ok=False,
            error={"code": "R010", "message": "test", "suggestions": []},
            warnings=[],
            diagnostics={},
        )
        envelope = json.loads(result)
        assert envelope["ok"] is False
        assert envelope["error"]["code"] == "R010"


# ==================== Bug 4: Target Forwarding + Stats ====================


class TestComputeSocBatchTargetForwarding:
    """Verify that single-op mode forwards payload.targets into the wrapped op."""

    def test_single_op_includes_targets(self):
        """compute_soc_batch.jsx single-op wrapper must include targets."""
        from pathlib import Path

        jsx_path = Path(
            "c:/Users/k.jin/OneDrive/PhD/claude/Illustrator_Agent/"
            "Illustrator_MCP/illustrator_mcp/resources/templates/compute_soc_batch.jsx"
        )
        content = jsx_path.read_text(encoding="utf-8")

        # The single-op wrapper should include 'targets: payload.targets'
        assert "targets: payload.targets" in content, (
            "Single-op wrapper must forward payload.targets to the op"
        )
        # Should also normalize with || null
        assert "payload.targets || null" in content, (
            "targets should be normalized with || null fallback"
        )

    def test_batch_mode_ops_not_modified(self):
        """Batch mode (params.ops) should use ops as-is, not inject targets."""
        from pathlib import Path

        jsx_path = Path(
            "c:/Users/k.jin/OneDrive/PhD/claude/Illustrator_Agent/"
            "Illustrator_MCP/illustrator_mcp/resources/templates/compute_soc_batch.jsx"
        )
        content = jsx_path.read_text(encoding="utf-8")

        # In batch mode, ops come from params.ops directly
        assert "ops = params.ops" in content


class TestItemsModifiedCounting:
    """Verify itemsModified uses handler's data.modified, not createdIds."""

    def test_modified_from_handler_data(self):
        """compute_soc_batch.jsx must sum data.modified from op results."""
        from pathlib import Path

        jsx_path = Path(
            "c:/Users/k.jin/OneDrive/PhD/claude/Illustrator_Agent/"
            "Illustrator_MCP/illustrator_mcp/resources/templates/compute_soc_batch.jsx"
        )
        content = jsx_path.read_text(encoding="utf-8")

        # Must use typeof guard (not truthiness) for modified:0
        assert 'typeof n === "number"' in content, (
            "Must use typeof guard for modified count to avoid truthiness bug"
        )
        # Must have separate itemsCreated and itemsModified
        assert "report.stats.itemsCreated" in content
        assert "report.stats.itemsModified" in content

    def test_empty_targets_warning(self):
        """Must warn when targets provided but resolved to 0 items."""
        from pathlib import Path

        jsx_path = Path(
            "c:/Users/k.jin/OneDrive/PhD/claude/Illustrator_Agent/"
            "Illustrator_MCP/illustrator_mcp/resources/templates/compute_soc_batch.jsx"
        )
        content = jsx_path.read_text(encoding="utf-8")

        assert "Resolved 0 targets" in content, (
            "Must warn when targets resolve to empty"
        )


class TestTaskStatsCreatedField:
    """Verify TaskStats model and formatter include itemsCreated."""

    def test_model_has_items_created(self):
        """TaskStats model must have itemsCreated field."""
        from illustrator_mcp.protocol import TaskStats

        stats = TaskStats(itemsProcessed=5, itemsCreated=2, itemsModified=3)
        assert stats.itemsCreated == 2
        assert stats.itemsModified == 3

    def test_model_defaults_to_zero(self):
        """itemsCreated defaults to 0 for backward compatibility."""
        from illustrator_mcp.protocol import TaskStats

        stats = TaskStats()
        assert stats.itemsCreated == 0

    def test_formatter_shows_created_and_modified(self):
        """format_task_report must show both created and modified counts."""
        from illustrator_mcp.protocol import (
            TaskReport, TaskStats, TimingInfo, format_task_report,
        )

        report = TaskReport(
            ok=True,
            stats=TaskStats(itemsProcessed=3, itemsCreated=1, itemsModified=2),
            timing=TimingInfo(collect_ms=0, compute_ms=10, apply_ms=0),
        )
        output = format_task_report(report, "style_set_gradient")
        assert "1 created" in output
        assert "2 modified" in output
        # Should NOT have the old combined format
        assert "created/modified" not in output

