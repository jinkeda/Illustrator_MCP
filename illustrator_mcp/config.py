"""
Configuration management for Illustrator MCP.

Loads settings from environment variables or .env file.
"""

import os
from pathlib import Path
from typing import Optional


def _load_env_file():
    """Load .env file if it exists."""
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key not in os.environ:  # Don't override existing env vars
                        os.environ[key] = value


# Load .env file on module import
_load_env_file()


class Config:
    """Configuration settings for Illustrator MCP."""
    
    # Proxy server settings
    PROXY_HOST: str = os.getenv("PROXY_HOST", "localhost")
    HTTP_PORT: int = int(os.getenv("HTTP_PORT", "8080"))
    WS_PORT: int = int(os.getenv("WS_PORT", "8081"))
    
    # Timeout settings
    TIMEOUT: float = float(os.getenv("TIMEOUT", "30"))
    
    @classmethod
    def get_proxy_url(cls) -> str:
        """Get the full proxy URL."""
        return f"http://{cls.PROXY_HOST}:{cls.HTTP_PORT}"
    
    @classmethod
    def get_ws_url(cls) -> str:
        """Get the WebSocket URL for the proxy."""
        return f"ws://{cls.PROXY_HOST}:{cls.WS_PORT}"


# Singleton instance
config = Config()
