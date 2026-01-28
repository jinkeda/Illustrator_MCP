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
        
        id1 = registry.create_request()
        id2 = registry.create_request()
        id3 = registry.create_request()
        
        assert id1 != id2 != id3
        assert id1 == 1
        assert id2 == 2
        assert id3 == 3
    
    def test_create_request_with_trace_id(self):
        """Test that trace_id is preserved in pending request."""
        registry = RequestRegistry()
        
        request_id = registry.create_request(trace_id="test_trace_123")
        
        pending = registry._pending.get(request_id)
        assert pending is not None
        assert pending.trace_id == "test_trace_123"
    
    def test_complete_request_resolves_future(self):
        """Test that complete_request sets the result on the future."""
        registry = RequestRegistry()
        
        request_id = registry.create_request()
        pending = registry._pending.get(request_id)
        
        result = {"success": True, "data": "test"}
        registry.complete_request(request_id, result)
        
        assert pending.future.done()
        assert pending.future.result() == result
    
    def test_complete_request_unknown_id(self):
        """Test that completing an unknown ID logs but doesn't crash."""
        registry = RequestRegistry()
        
        # Should not raise
        registry.complete_request(999, {"result": "orphan"})
    
    def test_fail_request_sets_exception(self):
        """Test that fail_request sets an exception on the future."""
        registry = RequestRegistry()
        
        request_id = registry.create_request()
        pending = registry._pending.get(request_id)
        
        registry.fail_request(request_id, "Connection lost")
        
        assert pending.future.done()
        with pytest.raises(ConnectionError):
            pending.future.result()
    
    def test_cancel_all_pending(self):
        """Test that cancel_all_pending cancels all futures."""
        registry = RequestRegistry()
        
        id1 = registry.create_request()
        id2 = registry.create_request()
        id3 = registry.create_request()
        
        pending1 = registry._pending.get(id1)
        pending2 = registry._pending.get(id2)
        pending3 = registry._pending.get(id3)
        
        registry.cancel_all_pending("Shutdown")
        
        # All should be done (cancelled)
        assert pending1.future.done()
        assert pending2.future.done()
        assert pending3.future.done()
        
        # Registry should be empty
        assert len(registry._pending) == 0


@pytest.mark.unit
class TestWebSocketBridge:
    """Tests for WebSocketBridge (requires mocking)."""
    
    def test_is_connected_initially_false(self):
        """Test that is_connected returns False initially."""
        with patch('illustrator_mcp.websocket_bridge.WebSocketBridge._start_bridge_thread'):
            from illustrator_mcp.websocket_bridge import WebSocketBridge
            bridge = WebSocketBridge(port=8081)
            
            assert bridge.is_connected() is False
    
    def test_bridge_has_registry(self):
        """Test that bridge has a RequestRegistry instance."""
        with patch('illustrator_mcp.websocket_bridge.WebSocketBridge._start_bridge_thread'):
            from illustrator_mcp.websocket_bridge import WebSocketBridge
            bridge = WebSocketBridge(port=8081)
            
            assert bridge.registry is not None
            assert isinstance(bridge.registry, RequestRegistry)
