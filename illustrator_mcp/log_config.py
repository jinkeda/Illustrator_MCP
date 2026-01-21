"""
Centralized logging configuration for Illustrator MCP.
"""

import logging
import sys


def configure_logging(level=logging.INFO):
    """
    Configure logging to stderr (required for stdio transport).
    
    Args:
        level: Logging level (default: logging.INFO)
    """
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler(sys.stderr)],
        force=True  # Ensure we override any existing config
    )
