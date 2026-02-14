"""
Tests for WebSocket bridge state management fixes.

P0: Disconnect → cancel propagation
P1: Response validation / C_PROTOCOL
P2: State transitions with locking + transition table
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from illustrator_mcp.bridge.request_registry import RequestRegistry
from illustrator_mcp.bridge.server import WebSocketServer


# ── P0: Disconnect → cancel ─────────────────────────────────────────


class TestDisconnectCancel:
    """P0: Disconnect must cancel all pending requests."""

    def test_on_disconnect_callback_fires(self):
        """Server calls on_disconnect when client disconnects."""
        callback = AsyncMock()
        server = WebSocketServer(port=0, on_message=AsyncMock(), on_disconnect=callback)

        # Simulate: client connects then disconnects (async for exits)
        mock_ws = AsyncMock()
        async def empty_iter():
            return
            yield  # make it an async generator
        mock_ws.__aiter__ = lambda *a: empty_iter()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(server._handle_client(mock_ws))
        loop.close()

        callback.assert_awaited_once()

    def test_disconnect_cancels_pending(self):
        """All pending futures get ConnectionError on disconnect."""
        registry = RequestRegistry()
        loop = asyncio.new_event_loop()

        _, f1 = registry.create_request(loop, "s1")
        _, f2 = registry.create_request(loop, "s2")

        registry.cancel_all("CEP panel disconnected")

        assert f1.done()
        assert f2.done()
        with pytest.raises(ConnectionError, match="CEP panel disconnected"):
            f1.result()
        with pytest.raises(ConnectionError, match="CEP panel disconnected"):
            f2.result()

        loop.close()

    @pytest.mark.asyncio
    async def test_disconnect_cancels_streaming(self):
        """Streaming queues get cancel sentinel on disconnect."""
        registry = RequestRegistry()
        req_id, queue = registry.create_streaming_request(
            asyncio.get_event_loop(), "streaming_script"
        )

        registry.cancel_all("CEP panel disconnected")

        # Queue should have the cancel sentinel
        # cancel_all clears _streaming, so we check the queue directly
        msg = queue.get_nowait()
        assert msg["type"] == "complete"
        assert msg["cancelled"] is True
        assert msg["reason"] == "CEP panel disconnected"

    def test_cancel_all_idempotent(self):
        """Second cancel_all() is a no-op, no exceptions."""
        registry = RequestRegistry()
        loop = asyncio.new_event_loop()

        _, f1 = registry.create_request(loop, "s1")

        registry.cancel_all("first cancel")
        assert f1.done()

        # Second call — must not raise
        registry.cancel_all("second cancel")

        # Future still has original exception
        with pytest.raises(ConnectionError, match="first cancel"):
            f1.result()

        loop.close()

    def test_disconnect_during_send(self):
        """Disconnect after create_request but before send still cancels."""
        registry = RequestRegistry()
        loop = asyncio.new_event_loop()

        req_id, future = registry.create_request(loop, "unsent_script")

        # Simulate: disconnect happens before send completes
        registry.cancel_all("CEP panel disconnected")

        assert future.done()
        with pytest.raises(ConnectionError):
            future.result()

        loop.close()

    def test_late_result_after_cancel(self):
        """complete_request returns False for cancelled request, future unchanged."""
        registry = RequestRegistry()
        loop = asyncio.new_event_loop()

        req_id, future = registry.create_request(loop, "s1")

        # Cancel first
        registry.cancel_all("CEP panel disconnected")
        assert future.done()

        # Late result arrives — must be rejected
        accepted = registry.complete_request(req_id, {"result": "late_data"})
        assert accepted is False

        # Future still has the ConnectionError, not the late result
        with pytest.raises(ConnectionError, match="CEP panel disconnected"):
            future.result()

        loop.close()


# ── P1: Response validation ──────────────────────────────────────────


class TestResponseValidation:
    """P1: Malformed responses must produce C_PROTOCOL error."""

    def test_malformed_response_becomes_protocol_error(self):
        """Missing 'result'/'error' keys → [C004] in result."""
        registry = RequestRegistry()
        loop = asyncio.new_event_loop()

        req_id, future = registry.create_request(loop, "s1")

        # Malformed: has id but no result/error
        malformed = {"id": req_id, "status": "unknown", "data": 42}
        registry.complete_request(req_id, malformed)

        assert future.done()
        result = future.result()
        assert "error" in result
        assert "[C004]" in result["error"]

        loop.close()

    def test_valid_result_passes_through(self):
        """Dict with 'result' key passes unchanged."""
        registry = RequestRegistry()
        loop = asyncio.new_event_loop()

        req_id, future = registry.create_request(loop, "s1")

        valid = {"result": "some_data", "elapsed_ms": 42}
        registry.complete_request(req_id, valid)

        assert future.result() == valid
        loop.close()

    def test_valid_error_passes_through(self):
        """Dict with 'error' key passes unchanged."""
        registry = RequestRegistry()
        loop = asyncio.new_event_loop()

        req_id, future = registry.create_request(loop, "s1")

        valid = {"error": "Script execution failed"}
        registry.complete_request(req_id, valid)

        assert future.result() == valid
        loop.close()


# ── P2: State transitions ───────────────────────────────────────────


class TestStateTransitions:
    """P2: _transition() with locking and transition table enforcement."""

    def _make_bridge(self):
        """Create a WebSocketBridge with mocked internals."""
        with patch('illustrator_mcp.websocket_bridge.WebSocketServer'):
            from illustrator_mcp.websocket_bridge import WebSocketBridge, ConnectionState
            bridge = WebSocketBridge(port=8099)
            return bridge, ConnectionState

    def test_transition_updates_state(self):
        """_transition() changes self.state on valid transition."""
        bridge, CS = self._make_bridge()
        assert bridge.state == CS.DISCONNECTED

        ok = bridge._transition(CS.CONNECTING, "test start")
        assert ok is True
        assert bridge.state == CS.CONNECTING

    def test_illegal_transition_rejected(self):
        """Illegal transition is rejected, state unchanged."""
        bridge, CS = self._make_bridge()
        assert bridge.state == CS.DISCONNECTED

        # DISCONNECTED → LISTENING is not in ALLOWED_TRANSITIONS
        ok = bridge._transition(CS.LISTENING, "illegal jump")
        assert ok is False
        assert bridge.state == CS.DISCONNECTED

    def test_error_transition_cancels_and_unblocks(self):
        """→ ERROR calls cancel_all and sets _ready."""
        bridge, CS = self._make_bridge()
        bridge._transition(CS.CONNECTING, "setup")

        loop = asyncio.new_event_loop()
        _, f1 = bridge.registry.create_request(loop, "s1")

        assert not bridge._ready.is_set()

        bridge._transition(CS.ERROR, "server crash")

        assert bridge.state == CS.ERROR
        assert bridge._ready.is_set()
        assert f1.done()
        with pytest.raises(ConnectionError, match="server crash"):
            f1.result()
        loop.close()

    def test_shutting_down_cancels_and_unblocks(self):
        """→ SHUTTING_DOWN calls cancel_all and sets _ready."""
        bridge, CS = self._make_bridge()
        bridge._transition(CS.CONNECTING, "setup")
        bridge._transition(CS.LISTENING, "ready")

        loop = asyncio.new_event_loop()
        _, f1 = bridge.registry.create_request(loop, "s1")

        bridge._transition(CS.SHUTTING_DOWN, "shutdown")

        assert bridge.state == CS.SHUTTING_DOWN
        assert bridge._ready.is_set()
        assert f1.done()
        with pytest.raises(ConnectionError, match="shutdown"):
            f1.result()
        loop.close()

