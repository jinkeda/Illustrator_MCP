"""
Script execution and proxy communication for Adobe Illustrator.

This module provides the core execute_script functionality that sends
JavaScript/ExtendScript to Illustrator via the proxy server.
All specific tools use this as their underlying implementation.
"""

import json
import logging
from typing import Any, Optional

import httpx

from illustrator_mcp.config import config

# Configure logging
logger = logging.getLogger(__name__)


class IllustratorProxy:
    """Client for communicating with the Illustrator proxy server."""
    
    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        timeout: Optional[float] = None
    ):
        self.host = host or config.PROXY_HOST
        self.port = port or config.HTTP_PORT
        self.timeout = timeout or config.TIMEOUT
        self.base_url = f"http://{self.host}:{self.port}"
    
    async def execute_script(self, script: str) -> dict[str, Any]:
        """
        Execute a JavaScript/ExtendScript in Illustrator.
        
        This is the core method that all tools use internally.
        
        Args:
            script: JavaScript code to execute in Illustrator
            
        Returns:
            Response from Illustrator containing result or error
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/execute",
                    json={"script": script},
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                return response.json()
                
        except httpx.ConnectError as e:
            logger.error(f"Failed to connect to proxy: {e}")
            return {
                "error": f"Cannot connect to Illustrator proxy at {self.base_url}. "
                         "Ensure the proxy server is running (cd proxy-server && npm start)"
            }
            
        except httpx.TimeoutException as e:
            logger.error(f"Request timed out: {e}")
            return {
                "error": f"Request to Illustrator timed out after {self.timeout}s"
            }
            
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error: {e.response.status_code}")
            return {
                "error": f"Proxy error ({e.response.status_code}): {e.response.text}"
            }
        
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return {"error": str(e)}
    
    async def check_connection(self) -> dict[str, Any]:
        """Check if the proxy and Illustrator are connected."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/status")
                response.raise_for_status()
                return response.json()
        except Exception as e:
            return {"connected": False, "error": str(e)}


# Global proxy instance
_proxy: Optional[IllustratorProxy] = None


def get_proxy() -> IllustratorProxy:
    """Get the global proxy instance."""
    global _proxy
    if _proxy is None:
        _proxy = IllustratorProxy()
    return _proxy


async def execute_script(script: str) -> dict[str, Any]:
    """
    Execute a JavaScript script in Illustrator.
    
    This is the core function that all specific tools use internally.
    
    Args:
        script: JavaScript/ExtendScript code to execute
        
    Returns:
        Dictionary with 'result' or 'error' key
    """
    return await get_proxy().execute_script(script)


def format_response(response: dict[str, Any]) -> str:
    """
    Format the response from Illustrator for MCP output.
    
    Args:
        response: Response dictionary from execute_script
        
    Returns:
        Formatted string for MCP tool response
    """
    if response.get("error"):
        return f"Error: {response['error']}"
    
    result = response.get("result", response)
    
    if isinstance(result, (dict, list)):
        return json.dumps(result, indent=2)
    return str(result)
