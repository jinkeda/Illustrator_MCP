"""
Backward-compatibility facade.

Re-exports types, connection helpers, and the MCP app singleton so that
all existing ``from illustrator_mcp.shared import ...`` statements
continue to work without modification.

New code should import directly from the specific modules:
  - ``illustrator_mcp.types``          (CommandMetadata, ExecutionResponse)
  - ``illustrator_mcp.connection_helpers`` (check_connection_or_error, ...)
  - ``illustrator_mcp.app``            (mcp, server_lifespan)
"""

# Layer ⓪ — pure data types
from illustrator_mcp.types import CommandMetadata, ExecutionResponse  # noqa: F401

# Layer ① — connection helpers
from illustrator_mcp.connection_helpers import (  # noqa: F401
    create_connection_error,
    create_duplicate_connection_error,
    check_connection_or_error,
)

# Layer ② — application singleton (lazy to avoid app construction on import)
# D2: Tests that transitively import shared.py no longer trigger FastMCP
# singleton construction. The actual app objects are only created when
# explicitly accessed (e.g., ``from illustrator_mcp.shared import mcp``).
_LAZY_APP_ATTRS = {"mcp", "server_lifespan"}


def __getattr__(name):
    if name in _LAZY_APP_ATTRS:
        from illustrator_mcp.app import mcp, server_lifespan  # noqa: F811
        globals().update({"mcp": mcp, "server_lifespan": server_lifespan})
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
