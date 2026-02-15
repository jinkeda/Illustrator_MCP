"""
test_streaming_race.py — Unit test for the streaming race condition fix.

Tests that the sentinel-based completion pattern in RequestRegistry
guarantees no dropped messages, even under concurrent conditions.
"""
import asyncio
import pytest

from illustrator_mcp.bridge.request_registry import RequestRegistry


@pytest.fixture
def registry():
    """Fresh RequestRegistry for each test."""
    return RequestRegistry()


def _create_streaming(registry: RequestRegistry):
    """Helper to create a streaming request with a real event loop."""
    loop = asyncio.get_event_loop()
    req_id, queue = registry.create_streaming_request(loop, "test_script")
    return req_id


class TestStreamingRace:
    """Tests for sentinel-driven streaming completion."""

    def test_push_update_basic(self, registry):
        """push_update delivers message to queue."""
        req_id = _create_streaming(registry)
        assert registry.push_update(req_id, {"type": "progress", "value": 42})

    def test_push_update_unknown_id(self, registry):
        """push_update returns False for unknown request."""
        assert not registry.push_update(999, {"type": "progress"})

    def test_complete_streaming_sends_sentinel(self, registry):
        """complete_streaming puts {type: 'complete'} sentinel in queue."""
        req_id = _create_streaming(registry)
        assert registry.complete_streaming(req_id, {"result": "done"})

        # Entry remains in _streaming (cleanup by stream_updates)
        streaming = registry._streaming.get(req_id)
        assert streaming is not None
        msg = streaming.queue.get_nowait()
        assert msg["type"] == "complete"
        assert msg["result"] == "done"

    def test_no_completed_flag(self, registry):
        """StreamingRequest no longer has a `completed` field."""
        req_id = _create_streaming(registry)
        streaming = registry._streaming[req_id]
        assert not hasattr(streaming, "completed"), \
            "StreamingRequest should not have 'completed' flag — sentinel-only"

    @pytest.mark.asyncio
    async def test_stream_updates_receives_all_messages(self, registry):
        """stream_updates yields all updates then exits on sentinel."""
        req_id = _create_streaming(registry)

        async def producer():
            await asyncio.sleep(0.01)
            registry.push_update(req_id, {"type": "progress", "step": 1})
            await asyncio.sleep(0.01)
            registry.push_update(req_id, {"type": "progress", "step": 2})
            await asyncio.sleep(0.01)
            registry.complete_streaming(req_id, {"result": "ok"})

        collected = []

        async def consumer():
            async for update in registry.stream_updates(req_id, timeout=5.0):
                collected.append(update)

        await asyncio.gather(producer(), consumer())

        assert len(collected) == 3, f"Expected 3 messages, got {len(collected)}"
        assert collected[0] == {"type": "progress", "step": 1}
        assert collected[1] == {"type": "progress", "step": 2}
        assert collected[2]["type"] == "complete"
        assert collected[2]["result"] == "ok"

    @pytest.mark.asyncio
    async def test_stream_updates_no_message_loss_under_rapid_completion(self, registry):
        """
        Regression test for the race condition:
        If complete_streaming is called immediately after push_update,
        the consumer must still receive BOTH the update AND the sentinel.
        
        Previously, the consumer checked `streaming.completed` outside the lock,
        which could cause it to exit the loop before reading the sentinel.
        """
        req_id = _create_streaming(registry)

        # Rapid-fire: push + complete with no delay
        registry.push_update(req_id, {"type": "progress", "data": "important"})
        registry.complete_streaming(req_id, {"result": "final"})

        collected = []
        async for update in registry.stream_updates(req_id, timeout=2.0):
            collected.append(update)

        assert len(collected) == 2, f"Expected 2 messages (update + sentinel), got {len(collected)}"
        assert collected[0]["type"] == "progress"
        assert collected[0]["data"] == "important"
        assert collected[1]["type"] == "complete"
        assert collected[1]["result"] == "final"

    @pytest.mark.asyncio
    async def test_stream_updates_timeout(self, registry):
        """stream_updates yields timeout message if no updates arrive."""
        req_id = _create_streaming(registry)

        collected = []
        async for update in registry.stream_updates(req_id, timeout=0.1):
            collected.append(update)

        assert len(collected) == 1
        assert collected[0]["type"] == "timeout"

    @pytest.mark.asyncio
    async def test_stream_updates_cleanup(self, registry):
        """After stream_updates completes, streaming request is cleaned up."""
        req_id = _create_streaming(registry)
        registry.complete_streaming(req_id, {"result": "done"})

        async for _ in registry.stream_updates(req_id, timeout=2.0):
            pass

        # Should be cleaned up
        assert req_id not in registry._streaming

    def test_cancel_all_sends_sentinel(self, registry):
        """cancel_all sends {type: 'complete', cancelled: true} sentinel."""
        req_id = _create_streaming(registry)
        registry.cancel_all("test cancellation")

        # After cancel_all, _streaming is cleared
        assert req_id not in registry._streaming

    @pytest.mark.asyncio
    async def test_multiple_complete_calls_not_idempotent(self, registry):
        """Second complete_streaming returns False due to _completed flag."""
        req_id = _create_streaming(registry)

        # First complete succeeds and sets _completed flag
        assert registry.complete_streaming(req_id, {"result": "first"})
        # Second complete returns False (_completed flag blocks it)
        assert not registry.complete_streaming(req_id, {"result": "second"})
