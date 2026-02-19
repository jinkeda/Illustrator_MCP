"""
Centralized runtime state management.

This module replaces scattered global singletons with a unified RuntimeContext.
"""

import threading
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from illustrator_mcp.websocket_bridge import WebSocketBridge
    from illustrator_mcp.proxy_client import IllustratorProxy


@dataclass
class RuntimeContext:
    """Centralized runtime state management."""
    bridge: Optional['WebSocketBridge'] = None
    proxy: Optional['IllustratorProxy'] = None
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def get_bridge(self) -> 'WebSocketBridge':
        """Get or create the WebSocketBridge singleton.

        Uses lock consistently (no unlocked outer read) so this is safe
        under free-threaded Python (--disable-gil) and PyPy.
        """
        with self._lock:
            if self.bridge is None:
                # Import here to avoid circular imports
                from illustrator_mcp.websocket_bridge import WebSocketBridge
                self.bridge = WebSocketBridge()
                # Auto-start bridge when accessed via runtime
                self.bridge.start()
            return self.bridge
    
    def get_proxy(self) -> 'IllustratorProxy':
        """Get or create the IllustratorProxy singleton."""
        with self._lock:
            if self.proxy is None:
                from illustrator_mcp.proxy_client import IllustratorProxy
                self.proxy = IllustratorProxy()
            return self.proxy

    def shutdown(self) -> None:
        """Stop the bridge (if running) and clear all references.

        I8: Explicit cleanup instead of relying on garbage collection.
        Safe to call multiple times.
        """
        with self._lock:
            if self.bridge is not None:
                try:
                    self.bridge.stop()
                except Exception:
                    pass  # best-effort
                self.bridge = None
            self.proxy = None


# Single global context
_runtime = RuntimeContext()


def get_runtime() -> RuntimeContext:
    """Get the global runtime context."""
    return _runtime
