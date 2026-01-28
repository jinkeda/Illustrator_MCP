# Illustrator MCP Architecture

## Overview

This document explains the import architecture and module dependencies to help avoid circular import issues.

## Module Graph

```
                    ┌─────────────┐
                    │   server    │ (entry point)
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   runtime   │ (dependency injection)
                    └──────┬──────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
  ┌──────────┐      ┌─────────────┐    ┌──────────┐
  │  shared  │◄────►│    tools    │───►│  config  │
  └────┬─────┘      └──────┬──────┘    └──────────┘
       │                   │
       │            ┌──────▼──────┐
       └───────────►│proxy_client │
                    └──────┬──────┘
                           │
                ┌──────────▼──────────┐
                │  websocket_bridge   │
                └──────────┬──────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                                 ▼
   ┌────────────┐                    ┌──────────────┐
   │bridge/server│                   │bridge/registry│
   └─────────────┘                   └───────────────┘
```

## Circular Import Solutions

### Pattern 1: Local Imports in Functions

**Files:** `runtime.py`, `proxy_client.py`, `shared.py`

```python
# runtime.py:33 - Avoids circular with websocket_bridge
def get_bridge():
    from illustrator_mcp.websocket_bridge import WebSocketBridge
    ...

# proxy_client.py:43-46 - Avoids circular with runtime
def _get_bridge():
    from illustrator_mcp.runtime import get_runtime
    return get_runtime().get_bridge()

# shared.py:89 - Avoids circular with tools
async def server_lifespan(server: FastMCP):
    from illustrator_mcp.runtime import get_runtime
    ...
```

### Pattern 2: Type-Only Imports

Use `TYPE_CHECKING` for type hints that would cause cycles:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from illustrator_mcp.websocket_bridge import WebSocketBridge
```

## Import Rules

1. **Config imports nothing** - Pure data module
2. **Shared imports only config** - MCP server instance
3. **Tools import shared, proxy_client** - Business logic
4. **Proxy imports config, shared** - Script execution
5. **Bridge imports config, shared** - WebSocket handling
6. **Runtime uses local imports** - Avoids all cycles

## Dependency Injection via RuntimeContext

The `RuntimeContext` in `runtime.py` provides lazy initialization:

```python
class RuntimeContext:
    _bridge: Optional[WebSocketBridge] = None
    
    def get_bridge(self) -> WebSocketBridge:
        if self._bridge is None:
            from illustrator_mcp.websocket_bridge import WebSocketBridge
            self._bridge = WebSocketBridge()
            self._bridge.start()
        return self._bridge
```

This avoids eager imports and enables testing with mock bridges.

## Testing Implications

- Mock at `runtime.get_runtime()` for complete isolation
- Mock at `proxy_client.execute_script_with_context` for tool tests
- Avoid importing tools before mocking proxy client
