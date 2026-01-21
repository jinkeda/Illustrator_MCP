"""
Configuration management for Illustrator MCP.
"""
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Configuration with validation and .env support."""
    
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore'
    )
    
    proxy_host: str = Field(default="localhost", description="Proxy host")
    http_port: int = Field(default=8080, ge=1024, le=65535, description="HTTP port for MCP server")
    ws_port: int = Field(default=8081, ge=1024, le=65535, description="WebSocket port for bridge")
    timeout: float = Field(default=30.0, ge=1.0, le=300.0, description="Operation timeout in seconds")
    
    @field_validator('ws_port')
    @classmethod
    def ports_must_differ(cls, v: int, info) -> int:
        # Check against http_port if it's already validated/present in info.data
        if info.data and 'http_port' in info.data and v == info.data['http_port']:
            raise ValueError('WS_PORT must differ from HTTP_PORT')
        return v
    
    @property
    def proxy_url(self) -> str:
        return f"http://{self.proxy_host}:{self.http_port}"
    
    @property
    def ws_url(self) -> str:
        return f"ws://{self.proxy_host}:{self.ws_port}"


# Global config instance
config = Config()
