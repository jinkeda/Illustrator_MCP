"""
Centralized logging configuration for Illustrator MCP.
"""

import logging
import sys
from pathlib import Path
from typing import Optional


def configure_logging(
    level: str = "INFO",
    log_file: Optional[Path] = None,
    structured: bool = False
):
    """Configure logging with options for file output and structured logging."""
    
    # Base configuration
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    if structured:
        # Use JSON formatting for structured logs
        log_format = '{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}'
    
    handlers = [logging.StreamHandler(sys.stderr)]
    
    if log_file:
        from logging.handlers import RotatingFileHandler
        # Ensure log directory exists
        if hasattr(log_file, 'parent'):
            log_file.parent.mkdir(parents=True, exist_ok=True)
            
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        handlers.append(file_handler)
    
    # Convert string level to int if needed
    if isinstance(level, str):
        level_val = getattr(logging, level.upper(), logging.INFO)
    else:
        level_val = level

    logging.basicConfig(
        level=level_val,
        format=log_format,
        handlers=handlers,
        force=True
    )


def log_command(
    logger: logging.Logger,
    trace_id: str,
    command_type: str,
    status: str,
    duration_ms: Optional[float] = None,
    level: int = logging.INFO
) -> None:
    """
    Log a command execution event with consistent formatting.
    
    This centralizes the logging format for command tracing across
    proxy_client, websocket_bridge, and other modules.
    
    Args:
        logger: Logger instance to use
        trace_id: Request trace ID
        command_type: Type of command being executed
        status: Current status (starting, completed, error, etc.)
        duration_ms: Optional duration in milliseconds
        level: Log level (default INFO)
    """
    if duration_ms is not None:
        message = f"[{trace_id}] {command_type}: {status} ({duration_ms:.1f}ms)"
    else:
        message = f"[{trace_id}] {command_type}: {status}"
    
    logger.log(level, message)
