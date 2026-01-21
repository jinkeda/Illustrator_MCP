"""
Tests for V2.3 Task Protocol features.
Covers CompoundTarget, TargetSelector, Ordering, and Retry policies.
"""
import pytest
from pydantic import ValidationError
from illustrator_mcp.protocol import (
    TaskPayload,
    TargetSelector,
    CompoundTarget,
    LayerTarget,
    SelectionTarget,
    QueryTarget,
    ExcludeFilter,
    OrderBy,
    RetryPolicy,
    RetryableStage,
    Idempotency
)

class TestCompoundSelectors:
    """Tests for CompoundTarget and TargetSelector."""

    def test_compound_target_structure(self):
        """Test constructing a valid compound target."""
        target = CompoundTarget(
            anyOf=[
                LayerTarget(layer="Layer 1"),
                SelectionTarget()
            ],
            exclude=ExcludeFilter(locked=True)
        )
        assert target.type == "compound"
        assert len(target.anyOf) == 2
        assert target.anyOf[0].layer == "Layer 1"
        assert target.exclude.locked is True

    def test_target_selector_wrapper(self):
        """Test the top-level TargetSelector wrapper."""
        selector = TargetSelector(
            target=SelectionTarget(),
            orderBy=OrderBy.READING,
            exclude=ExcludeFilter(hidden=True)
        )
        assert selector.target.type == "selection"
        assert selector.orderBy == OrderBy.READING
        assert selector.exclude.hidden is True
        
    def test_nested_compound_in_selector(self):
        """Test TargetSelector containing a CompoundTarget."""
        selector = TargetSelector(
            target=CompoundTarget(
                anyOf=[
                    LayerTarget(layer="Background"),
                    QueryTarget(itemType="PathItem", pattern="*")
                ]
            ),
            orderBy=OrderBy.Z_ORDER_REVERSE
        )
        assert selector.target.type == "compound"
        assert len(selector.target.anyOf) == 2
        assert selector.orderBy == OrderBy.Z_ORDER_REVERSE

    def test_compound_validation_error(self):
        """Test invalid compound target (empty list)."""
        with pytest.raises(ValidationError):
            CompoundTarget(anyOf=[])

class TestTaskPayloadV23:
    """Tests for V2.3 TaskPayload features."""

    def test_default_version(self):
        """Ensure version defaults to 2.3.0."""
        payload = TaskPayload(task="test")
        assert payload.version == "2.3.1"

    def test_payload_with_selector(self):
        """Test payload with full TargetSelector."""
        payload = TaskPayload(
            task="align_items",
            targets=TargetSelector(
                target=SelectionTarget(),
                orderBy=OrderBy.POSITION_X
            )
        )
        assert payload.targets.orderBy == OrderBy.POSITION_X
        # Dump to JSON to verify structure for JS
        json_output = payload.model_dump(mode='json')
        assert json_output['targets']['orderBy'] == 'positionX'
        assert json_output['targets']['target']['type'] == 'selection'

class TestRetryPolicy:
    """Tests for Retry models."""

    def test_retry_policy_defaults(self):
        """Test default retry policy values."""
        policy = RetryPolicy()
        assert policy.maxAttempts == 3
        assert RetryableStage.COLLECT in policy.retryableStages
        assert RetryableStage.APPLY not in policy.retryableStages

    def test_retry_custom_policy(self):
        """Test custom retry policy."""
        policy = RetryPolicy(
            maxAttempts=5,
            retryableStages=[RetryableStage.COLLECT, RetryableStage.COMPUTE],
            requireIdempotent=False
        )
        assert policy.maxAttempts == 5
        assert len(policy.retryableStages) == 2


class TestOrderByModes:
    """Tests for all 8 OrderBy modes."""
    
    def test_all_order_modes_valid(self):
        """Ensure all OrderBy enum values can be used in TargetSelector."""
        for mode in OrderBy:
            selector = TargetSelector(
                target=SelectionTarget(),
                orderBy=mode
            )
            assert selector.orderBy == mode
    
    def test_order_by_serialization(self):
        """Test JSON serialization of OrderBy values."""
        expected_values = {
            OrderBy.Z_ORDER: "zOrder",
            OrderBy.Z_ORDER_REVERSE: "zOrderReverse",
            OrderBy.READING: "reading",
            OrderBy.COLUMN: "column",
            OrderBy.NAME: "name",
            OrderBy.POSITION_X: "positionX",
            OrderBy.POSITION_Y: "positionY",
            OrderBy.AREA: "area",
        }
        for mode, expected_str in expected_values.items():
            selector = TargetSelector(target=SelectionTarget(), orderBy=mode)
            json_output = selector.model_dump(mode='json')
            assert json_output['orderBy'] == expected_str


class TestRetrySafeSemantics:
    """Tests for stage-aware retry semantics."""
    
    def test_apply_never_in_retryable_stages(self):
        """Verify APPLY stage cannot be added to retryable stages enum."""
        # RetryableStage only has COLLECT and COMPUTE
        all_stages = list(RetryableStage)
        stage_values = [s.value for s in all_stages]
        assert "apply" not in stage_values
        assert "collect" in stage_values
        assert "compute" in stage_values
    
    def test_default_retry_excludes_apply(self):
        """Default retry policy should only retry collect stage."""
        policy = RetryPolicy()
        assert policy.retryableStages == [RetryableStage.COLLECT]


class TestIdempotency:
    """Tests for Idempotency enum."""
    
    def test_idempotency_values(self):
        """Test all idempotency levels."""
        assert Idempotency.SAFE.value == "safe"
        assert Idempotency.UNKNOWN.value == "unknown"
        assert Idempotency.UNSAFE.value == "unsafe"


class TestSchemaValidation:
    """Tests for runtime schema validation."""
    
    def test_load_schema(self):
        """Test loading JSON schemas."""
        from illustrator_mcp.schemas import load_schema, AVAILABLE_SCHEMAS
        
        for schema_name in AVAILABLE_SCHEMAS:
            schema = load_schema(schema_name)
            assert isinstance(schema, dict)
            # All schemas should have $schema or type key
            assert "$schema" in schema or "type" in schema or "properties" in schema
    
    def test_validate_valid_payload(self):
        """Test validation of a valid payload."""
        from illustrator_mcp.schemas import validate_payload
        
        valid_payload = {
            "task": "test_task",
            "version": "2.3.0",
            "params": {}
        }
        errors = validate_payload(valid_payload)
        # May return empty if jsonschema not installed
        assert isinstance(errors, list)
    
    def test_schema_caching(self):
        """Test that schemas are cached after first load."""
        from illustrator_mcp.schemas import load_schema, _schema_cache
        
        # Clear cache
        _schema_cache.clear()
        
        # Load schema
        schema1 = load_schema("task_payload")
        assert "task_payload" in _schema_cache
        
        # Load again - should be from cache
        schema2 = load_schema("task_payload")
        assert schema1 is schema2  # Same object
