"""
Unit tests for the panel health watchdog (E1).

Uses the extracted _watchdog_tick helper for deterministic testing
without timing dependencies.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from illustrator_mcp.websocket_bridge import WebSocketBridge


@pytest.fixture
def bridge():
    """Create a WebSocketBridge with mocked server to avoid real networking."""
    with patch('illustrator_mcp.websocket_bridge.WebSocketServer'):
        b = WebSocketBridge(port=9999)
        return b


class TestWatchdogTick:
    """Test _watchdog_tick in isolation via Option A (extracted helper)."""

    @pytest.mark.asyncio
    async def test_stale_and_not_busy_triggers_disconnect(self, bridge):
        """Watchdog tick triggers disconnect when panel is stale and not busy."""
        bridge.get_panel_health = MagicMock(return_value={
            "stale": True,
            "busy": False,
            "last_heartbeat_ago_ms": 45000,
            "active_request_id": None,
        })
        bridge.is_connected = MagicMock(return_value=True)
        bridge._handle_disconnect = AsyncMock()

        result = await bridge._watchdog_tick()

        assert result is True
        bridge._handle_disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_stale_does_not_disconnect(self, bridge):
        """Watchdog tick does nothing when panel is healthy."""
        bridge.get_panel_health = MagicMock(return_value={
            "stale": False,
            "busy": False,
            "last_heartbeat_ago_ms": 1000,
            "active_request_id": None,
        })
        bridge.is_connected = MagicMock(return_value=True)
        bridge._handle_disconnect = AsyncMock()

        result = await bridge._watchdog_tick()

        assert result is False
        bridge._handle_disconnect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stale_but_busy_does_not_disconnect(self, bridge):
        """Watchdog does not disconnect when panel is stale but busy."""
        bridge.get_panel_health = MagicMock(return_value={
            "stale": True,
            "busy": True,
            "last_heartbeat_ago_ms": 45000,
            "active_request_id": 42,
        })
        bridge.is_connected = MagicMock(return_value=True)
        bridge._handle_disconnect = AsyncMock()

        result = await bridge._watchdog_tick()

        assert result is False
        bridge._handle_disconnect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stale_but_not_connected_does_not_disconnect(self, bridge):
        """Watchdog does not disconnect when already disconnected."""
        bridge.get_panel_health = MagicMock(return_value={
            "stale": True,
            "busy": False,
            "last_heartbeat_ago_ms": 45000,
            "active_request_id": None,
        })
        bridge.is_connected = MagicMock(return_value=False)
        bridge._handle_disconnect = AsyncMock()

        result = await bridge._watchdog_tick()

        assert result is False
        bridge._handle_disconnect.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disconnect_handles_cancelled_error(self, bridge):
        """CancelledError during disconnect is caught gracefully."""
        bridge.get_panel_health = MagicMock(return_value={
            "stale": True,
            "busy": False,
            "last_heartbeat_ago_ms": 60000,
            "active_request_id": None,
        })
        bridge.is_connected = MagicMock(return_value=True)
        bridge._handle_disconnect = AsyncMock(side_effect=asyncio.CancelledError)

        # Should not raise
        result = await bridge._watchdog_tick()
        assert result is True
