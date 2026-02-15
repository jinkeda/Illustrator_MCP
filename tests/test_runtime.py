"""
Tests for RuntimeContext singleton and thread-safety.
"""

import threading
from unittest.mock import patch, MagicMock

from illustrator_mcp.runtime import RuntimeContext


class TestGetBridge:
    """Test RuntimeContext.get_bridge singleton behavior."""

    def test_creates_singleton(self):
        """First call creates a bridge, second returns the same instance."""
        ctx = RuntimeContext()
        mock_bridge = MagicMock()
        mock_bridge.start = MagicMock()

        # Patch where the lazy import resolves: the module-level class
        with patch(
            'illustrator_mcp.websocket_bridge.WebSocketBridge',
            return_value=mock_bridge,
        ):
            bridge1 = ctx.get_bridge()
            bridge2 = ctx.get_bridge()

        assert bridge1 is bridge2
        assert bridge1 is mock_bridge
        # start() should only be called once (first creation)
        mock_bridge.start.assert_called_once()


class TestGetProxy:
    """Test RuntimeContext.get_proxy singleton behavior."""

    def test_creates_singleton(self):
        """First call creates a proxy, second returns the same instance."""
        ctx = RuntimeContext()
        mock_proxy = MagicMock()

        with patch(
            'illustrator_mcp.proxy_client.IllustratorProxy',
            return_value=mock_proxy,
        ):
            proxy1 = ctx.get_proxy()
            proxy2 = ctx.get_proxy()

        assert proxy1 is proxy2
        assert proxy1 is mock_proxy


class TestThreadSafety:
    """Test that get_bridge is safe under concurrent access."""

    def test_concurrent_get_bridge_creates_one_instance(self):
        """4 threads calling get_bridge — only one bridge created."""
        ctx = RuntimeContext()
        num_threads = 4
        barrier = threading.Barrier(num_threads)
        results = [None] * num_threads
        creation_count = {"value": 0}
        creation_lock = threading.Lock()

        original_mock = MagicMock()
        original_mock.start = MagicMock()

        def counting_constructor(**kwargs):
            with creation_lock:
                creation_count["value"] += 1
            return original_mock

        def worker(idx):
            barrier.wait()  # synchronize all threads
            results[idx] = ctx.get_bridge()

        with patch(
            'illustrator_mcp.websocket_bridge.WebSocketBridge',
            side_effect=counting_constructor,
        ):
            threads = [
                threading.Thread(target=worker, args=(i,))
                for i in range(num_threads)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5.0)

        # Only one bridge was constructed
        assert creation_count["value"] == 1
        # All threads got the same instance
        assert all(r is results[0] for r in results)
        assert all(r is original_mock for r in results)
