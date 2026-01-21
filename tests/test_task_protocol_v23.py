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
        assert payload.version == "2.3.0"

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
