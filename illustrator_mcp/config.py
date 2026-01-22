"""
Configuration management for Illustrator MCP.
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# Named constants for timeouts (avoids magic numbers)
BRIDGE_STARTUP_TIMEOUT: float = 10.0  # seconds to wait for bridge startup
BRIDGE_EXECUTION_BUFFER: float = 5.0  # extra timeout for thread coordination
RECONNECT_INTERVAL_MS: int = 3000     # CEP panel reconnect interval


class Config(BaseSettings):
    """Configuration with validation and .env support."""
    
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore'
    )
    
    # WebSocket settings
    ws_host: str = Field(default="localhost", description="WebSocket host")
    ws_port: int = Field(default=8081, ge=1024, le=65535, description="WebSocket port for bridge")
    
    # Timeout settings
    timeout: float = Field(default=30.0, ge=1.0, le=300.0, description="Operation timeout in seconds")
    
    @property
    def ws_url(self) -> str:
        """WebSocket URL for CEP panel connection."""
        return f"ws://{self.ws_host}:{self.ws_port}"


# Global config instance
config = Config()
