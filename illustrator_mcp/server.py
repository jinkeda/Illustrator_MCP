#!/usr/bin/env python3
"""
Adobe Illustrator MCP Server.

This server provides tools to interact with Adobe Illustrator via the
Model Context Protocol, enabling AI assistants to control Illustrator
using natural language.

Architecture (SIMPLIFIED - Single Process!):
- MCP server runs as main process (stdio transport for Claude Code)
- Integrated WebSocket server (port 8081) for CEP panel connection
- NO separate Node.js proxy server needed!

How it works:
1. Claude Code connects to this server via stdio
2. CEP panel in Illustrator connects via WebSocket (port 8081)
3. MCP tools send scripts through the WebSocket bridge to Illustrator

Lifecycle:
- WebSocket bridge starts via lifespan management (see shared.py)
- Bridge is automatically shut down when server stops

SCRIPTING FIRST ARCHITECTURE:
Following the blender-mcp pattern, this server exposes a minimal toolset.
Most Illustrator operations should be done via the illustrator_execute_script tool.

Core tools (~15 total):
- execute: Run any ExtendScript code (PRIMARY tool)
- documents: Create, open, save, export, import, undo/redo
- context: Get document structure, selection info, app info
"""

import logging
from illustrator_mcp.log_config import configure_logging

# Configure logging
configure_logging()
logger = logging.getLogger(__name__)

# Import the shared mcp instance (includes lifespan management)
from illustrator_mcp.shared import mcp

# Import tool registration function
from illustrator_mcp.tools import register_tools

# Register tools explicitly
# Only essential tools are enabled - use execute_script for everything else
register_tools(mcp)


def main():
    """Entry point for the MCP server."""
    logger.info("Starting Adobe Illustrator MCP Server...")
    logger.info("(WebSocket bridge will start via lifespan management)")
    logger.info("")
    
    # Run the MCP server (lifespan handles bridge startup/shutdown)
    mcp.run()


if __name__ == "__main__":
    main()
