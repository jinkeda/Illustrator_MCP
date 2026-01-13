"""
Shared MCP server instance for all tool modules.

This module provides the shared FastMCP instance that is used by all tool modules.
Import `mcp` from this module to register tools.
"""

from mcp.server.fastmcp import FastMCP

# Shared MCP server instance
mcp = FastMCP("illustrator_mcp")
