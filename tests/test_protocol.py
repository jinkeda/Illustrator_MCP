"""
Tests for the Task Protocol models and integration.
"""

import pytest
from pydantic import ValidationError

from illustrator_mcp.protocol import (
    TaskPayload,
    TaskReport,
    ItemRef,
    TaskError,
    TaskWarning,
    TaskStats,
    TimingInfo,
)


class TestItemRef:
    """Tests for ItemRef model."""
    
    def test_minimal_item_ref(self):
        """Test minimal valid ItemRef."""
        ref = ItemRef(
            layerPath="Layer 1",
            itemType="PathItem"
        )
        assert ref.layerPath == "Layer 1"
        assert ref.itemType == "PathItem"
        assert ref.indexPath == []
        assert ref.itemId is None
        
    def test_full_item_ref(self):
        """Test ItemRef with all fields."""
        ref = ItemRef(
            layerPath="Layer 1/Group A",
            indexPath=[0, 2, 5],
            itemId="i1234567890_1234",
            itemName="my_rectangle",
            itemType="PathItem"
        )
        assert ref.layerPath == "Layer 1/Group A"
        assert ref.indexPath == [0, 2, 5]
        assert ref.itemId == "i1234567890_1234"
        assert ref.itemName == "my_rectangle"


class TestTaskPayload:
    """Tests for TaskPayload model."""
    
    def test_minimal_payload(self):
        """Test minimal valid payload."""
        payload = TaskPayload(task="test_task")
        assert payload.task == "test_task"
        assert payload.version == "2.1.0"
        assert payload.targets is None
        assert payload.params == {}
        assert payload.options is None
    
    def test_full_payload(self):
        """Test payload with all fields."""
        payload = TaskPayload(
            task="apply_fill_color",
            version="2.1.0",
            targets={"type": "selection"},
            params={"color": {"r": 255, "g": 0, "b": 0}},
            options={"dryRun": True, "trace": True}
        )
        assert payload.task == "apply_fill_color"
        assert payload.targets["type"] == "selection"
        assert payload.params["color"]["r"] == 255
        assert payload.options["dryRun"] is True
        
    def test_query_targets(self):
        """Test query-type target selector."""
        payload = TaskPayload(
            task="style_axes",
            targets={
                "type": "query",
                "layer": "Plot",
                "itemType": "PathItem",
                "pattern": "axis_*"
            },
            params={"strokeWidth": 2}
        )
        assert payload.targets["type"] == "query"
        assert payload.targets["pattern"] == "axis_*"


class TestTaskReport:
    """Tests for TaskReport model."""
    
    def test_success_report(self):
        """Test successful task report."""
        report = TaskReport(
            ok=True,
            stats=TaskStats(itemsProcessed=10, itemsModified=8, itemsSkipped=2),
            timing=TimingInfo(collect_ms=5, compute_ms=10, apply_ms=20, total_ms=35)
        )
        assert report.ok is True
        assert report.stats.itemsProcessed == 10
        assert report.timing.total_ms == 35
        assert report.warnings == []
        assert report.errors == []
    
    def test_error_report(self):
        """Test task report with errors."""
        report = TaskReport(
            ok=False,
            stats=TaskStats(itemsProcessed=5, itemsModified=0, itemsSkipped=5),
            timing=TimingInfo(collect_ms=5, compute_ms=0, apply_ms=0, total_ms=5),
            errors=[
                TaskError(
                    stage="collect",
                    code="ERROR_NO_DOCUMENT",
                    message="No active document"
                )
            ]
        )
        assert report.ok is False
        assert len(report.errors) == 1
        assert report.errors[0].code == "ERROR_NO_DOCUMENT"
        
    def test_warning_report(self):
        """Test task report with warnings."""
        report = TaskReport(
            ok=True,
            stats=TaskStats(itemsProcessed=0, itemsModified=0, itemsSkipped=0),
            timing=TimingInfo(total_ms=10),
            warnings=[
                TaskWarning(
                    stage="collect",
                    message="No items matched the target selector",
                    suggestion="Check targets parameter"
                )
            ]
        )
        assert report.ok is True
        assert len(report.warnings) == 1
        assert report.warnings[0].suggestion == "Check targets parameter"
        
    def test_report_with_trace(self):
        """Test task report with trace enabled."""
        report = TaskReport(
            ok=True,
            stats=TaskStats(itemsProcessed=2, itemsModified=2, itemsSkipped=0),
            timing=TimingInfo(collect_ms=1, compute_ms=2, apply_ms=3, total_ms=6),
            trace=[
                "[COLLECT] Starting target collection",
                "[COLLECT] Found 2 items",
                "[COMPUTE] Computing actions",
                "[APPLY] Complete"
            ]
        )
        assert report.trace is not None
        assert len(report.trace) == 4
        assert "[COLLECT]" in report.trace[0]


class TestTaskError:
    """Tests for TaskError model."""
    
    def test_minimal_error(self):
        """Test minimal error."""
        error = TaskError(
            stage="apply",
            code="ERROR_ITEM_FAILED",
            message="Cannot set fill color on locked item"
        )
        assert error.stage == "apply"
        assert error.code == "ERROR_ITEM_FAILED"
        assert error.itemRef is None
        
    def test_error_with_item_ref(self):
        """Test error with item reference."""
        error = TaskError(
            stage="apply",
            code="ERROR_ITEM_FAILED",
            message="Cannot set fill color",
            itemRef=ItemRef(layerPath="Layer 1", indexPath=[0, 2], itemType="PathItem"),
            line=42
        )
        assert error.itemRef is not None
        assert error.itemRef.layerPath == "Layer 1"
        assert error.line == 42


class TestModelSerialization:
    """Tests for JSON serialization/deserialization."""
    
    def test_payload_round_trip(self):
        """Test payload serialization and parsing."""
        payload = TaskPayload(
            task="test",
            targets={"type": "selection"},
            params={"value": 123}
        )
        json_str = payload.model_dump_json()
        parsed = TaskPayload.model_validate_json(json_str)
        assert parsed.task == payload.task
        assert parsed.targets == payload.targets
        
    def test_report_from_jsx_json(self):
        """Test parsing report from JSX-style JSON."""
        jsx_json = '''
        {
            "ok": true,
            "stats": {"itemsProcessed": 3, "itemsModified": 3, "itemsSkipped": 0},
            "timing": {"collect_ms": 5, "compute_ms": 10, "apply_ms": 15, "total_ms": 30},
            "warnings": [],
            "errors": []
        }
        '''
        report = TaskReport.model_validate_json(jsx_json)
        assert report.ok is True
        assert report.stats.itemsProcessed == 3
        assert report.timing.total_ms == 30
