#!/usr/bin/env python3
"""
Adobe Illustrator MCP Server.

This server provides tools to interact with Adobe Illustrator via the 
Model Context Protocol, enabling AI assistants to control Illustrator
using natural language.

Architecture:
- All specific tools use execute_script internally
- execute_script sends JavaScript to Illustrator via the proxy server
- The proxy server communicates with the UXP plugin via WebSocket

Tool Count: 94 tools across 15 categories
"""

import logging

# Configure logging to stderr (required for stdio transport)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Import the shared mcp instance
from illustrator_mcp.shared import mcp

# Import all tool modules (this registers tools via decorators)
from illustrator_mcp.tools import (
    execute,      # Core execute_script (1 tool)
    documents,    # Document operations (7 tools)
    artboards,    # Artboard management (5 tools)
    shapes,       # Shape drawing (6 tools)
    paths,        # Path operations (10 tools)
    pathfinder,   # Boolean operations (8 tools)
    text,         # Text basics (4 tools)
    typography,   # Advanced typography (6 tools)
    layers,       # Layer management (6 tools)
    objects,      # Object operations (10 tools)
    selection,    # Selection & transform (7 tools)
    styling,      # Color & styling (5 tools)
    effects,      # Effects & gradients (7 tools)
    arrange,      # Alignment & grouping (8 tools)
    transform     # Advanced transforms (4 tools)
)


def main():
    """Entry point for the MCP server."""
    logger.info("Starting Adobe Illustrator MCP Server...")
    logger.info("Tools: 94 total across 15 categories")
    mcp.run()


if __name__ == "__main__":
    main()
