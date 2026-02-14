"""
Pure data types for Illustrator MCP.

This module defines shared data structures used across the codebase.
It has ZERO internal dependencies, making it a safe base layer that
can never participate in circular import chains.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, TypedDict


@dataclass
class CommandMetadata:
    """Metadata for a command execution request."""
    command_type: str
    tool_name: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.command_type,
            "tool": self.tool_name or self.command_type,
            "params": self.params,
            "trace_id": self.trace_id
        }


class ExecutionResponse(TypedDict, total=False):
    """Canonical response shape for script execution."""
    result: Any
    error: str
    trace_id: str
    elapsed_ms: float
    command: str
