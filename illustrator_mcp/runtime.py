"""
Centralized runtime state management.

This module replaces scattered global singletons with a unified RuntimeContext.
"""

import threading
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from illustrator_mcp.websocket_bridge import WebSocketBridge
    from illustrator_mcp.proxy_client import IllustratorProxy
    from illustrator_mcp.tools.execute import LibraryResolver


@dataclass
class RuntimeContext:
    """Centralized runtime state management."""
    bridge: Optional['WebSocketBridge'] = None
    proxy: Optional['IllustratorProxy'] = None

    def get_bridge(self) -> 'WebSocketBridge':

        """Get or create the WebSocketBridge singleton."""
        if self.bridge:
            return self.bridge
            
        with self._lock:
            # Double check locking
            if self.bridge is None:
                # Import here to avoid circular imports
                from illustrator_mcp.websocket_bridge import WebSocketBridge
                self.bridge = WebSocketBridge()
                # Auto-start bridge when accessed via runtime
                self.bridge.start()
            return self.bridge
    
    def get_proxy(self) -> 'IllustratorProxy':
        """Get or create the IllustratorProxy singleton."""
        if self.proxy:
            return self.proxy
            
        with self._lock:
            if self.proxy is None:
                from illustrator_mcp.proxy_client import IllustratorProxy
                self.proxy = IllustratorProxy()
            return self.proxy


# Single global context
_runtime = RuntimeContext()


def get_runtime() -> RuntimeContext:
    """Get the global runtime context."""
    return _runtime
