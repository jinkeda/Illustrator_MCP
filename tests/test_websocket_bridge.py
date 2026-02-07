"""
Tests for WebSocket bridge components.

Tests for the WebSocketBridge and RequestRegistry classes.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from illustrator_mcp.bridge.request_registry import RequestRegistry


class TestRequestRegistry:
    """Tests for RequestRegistry."""
    
    def test_create_request_returns_unique_ids(self):
        """Test that create_request generates unique IDs."""
        registry = RequestRegistry()
        loop = asyncio.new_event_loop()
        
        id1, _ = registry.create_request(loop, "script1")
        id2, _ = registry.create_request(loop, "script2")
        id3, _ = registry.create_request(loop, "script3")
        
        loop.close()
        
        assert id1 != id2 != id3
        assert id1 == 1
        assert id2 == 2
        assert id3 == 3
    
    def test_create_request_with_trace_id(self):
        """Test that trace_id is preserved in pending request."""
        registry = RequestRegistry()
        loop = asyncio.new_event_loop()
        
        request_id, _ = registry.create_request(loop, "script", trace_id="test_trace_123")
        loop.close()
        
        pending = registry._pending.get(request_id)
        assert pending is not None
        assert pending.trace_id == "test_trace_123"
    
    def test_complete_request_resolves_future(self):
        """Test that complete_request sets the result on the future."""
        registry = RequestRegistry()
        loop = asyncio.new_event_loop()
        
        request_id, future = registry.create_request(loop, "script")
        
        result = {"success": True, "data": "test"}
        registry.complete_request(request_id, result)
        
        assert future.done()
        assert future.result() == result
        loop.close()
    
    def test_complete_request_unknown_id(self):
        """Test that completing an unknown ID logs but doesn't crash."""
        registry = RequestRegistry()
        
        # Should not raise
        registry.complete_request(999, {"result": "orphan"})
    
    def test_fail_request_sets_exception(self):
        """Test that fail_request sets an exception on the future."""
        registry = RequestRegistry()
        loop = asyncio.new_event_loop()
        
        request_id, future = registry.create_request(loop, "script")
        
        registry.fail_request(request_id, ConnectionError("Connection lost"))
        
        assert future.done()
        with pytest.raises(ConnectionError):
            future.result()
        loop.close()
    
    def test_cancel_all_pending(self):
        """Test that cancel_all_pending cancels all futures."""
        registry = RequestRegistry()
        loop = asyncio.new_event_loop()
        
        id1, future1 = registry.create_request(loop, "script1")
        id2, future2 = registry.create_request(loop, "script2")
        id3, future3 = registry.create_request(loop, "script3")
        
        registry.cancel_all("Shutdown")
        
        # All should be done (cancelled)
        assert future1.done()
        assert future2.done()
        assert future3.done()
        
        # Registry should be empty
        assert len(registry._pending) == 0
        loop.close()


@pytest.mark.unit
class TestWebSocketBridge:
    """Tests for WebSocketBridge (requires mocking)."""
    
    def test_is_connected_initially_false(self):
        """Test that is_connected returns False initially."""
        # Cleanly mock threading.Thread to prevent side effects
        with patch('threading.Thread'):
            from illustrator_mcp.websocket_bridge import WebSocketBridge
            
            # Mock RequestRegistry since it's instantiated in __init__
            with patch('illustrator_mcp.websocket_bridge.RequestRegistry'):
                bridge = WebSocketBridge(port=8081)
                assert bridge.is_connected() is False
    
    def test_bridge_has_registry(self):
        """Test that bridge has a RequestRegistry instance."""
        with patch('threading.Thread'):
            from illustrator_mcp.websocket_bridge import WebSocketBridge
            bridge = WebSocketBridge(port=8081)
            
            assert bridge.registry is not None
            assert isinstance(bridge.registry, RequestRegistry)


@pytest.mark.asyncio
class TestDuplicateConnectionRejection:
    """Tests for duplicate connection rejection behavior."""
    
    async def test_duplicate_connection_rejected(self):
        """Test that a second connection attempt is rejected when one is active."""
        from illustrator_mcp.bridge.server import WebSocketServer
        
        messages = []
        server = WebSocketServer(port=0, on_message=lambda m: messages.append(m))
        
        # Simulate first client connected (active)
        mock_client1 = AsyncMock()
        mock_client1.closed = False
        mock_client1.open = True
        server.client = mock_client1
        
        # Attempt second connection
        mock_client2 = AsyncMock()
        mock_client2.close = AsyncMock()
        
        await server._handle_client(mock_client2)
        
        # Second client should be closed with 4001
        mock_client2.close.assert_called_once()
        call_args = mock_client2.close.call_args
        assert call_args[0][0] == 4001
        assert "already connected" in call_args[0][1]
        
        # First client should remain connected
        assert server.client == mock_client1

    async def test_stale_connection_replaced(self):
        """Test that a stale (disconnected) connection is cleaned up."""
        from illustrator_mcp.bridge.server import WebSocketServer
        
        messages = []
        server = WebSocketServer(port=0, on_message=lambda m: messages.append(m))
        
        # Simulate first client that is already disconnected (stale)
        mock_client1 = AsyncMock()
        mock_client1.closed = True
        mock_client1.open = False
        mock_client1.close = AsyncMock()
        server.client = mock_client1
        
        # New connection - mock async iteration to raise ConnectionClosed
        mock_client2 = AsyncMock()
        
        # Make async for raise immediately to end the handler
        async def empty_iter():
            return
            yield  # make it a generator
        mock_client2.__aiter__ = lambda *args: empty_iter()
        
        # Run handler - should clean up stale and set new client
        await server._handle_client(mock_client2)
        
        # New client should be set (even though it disconnected immediately)
        # Check that stale cleanup happened
        mock_client1.close.assert_called_once()

