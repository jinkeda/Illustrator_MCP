"""
Shared test fixtures and configuration for Illustrator MCP tests.
"""

import pytest
from unittest.mock import AsyncMock, patch


# All tool modules that import execute_script
TOOL_MODULES = [
    'illustrator_mcp.tools.shapes',
    'illustrator_mcp.tools.documents',
    'illustrator_mcp.tools.objects',
    'illustrator_mcp.tools.effects',
    'illustrator_mcp.tools.pathfinder',
    'illustrator_mcp.tools.paths',
    'illustrator_mcp.tools.text',
    'illustrator_mcp.tools.typography',
    'illustrator_mcp.tools.layers',
    'illustrator_mcp.tools.selection',
    'illustrator_mcp.tools.styling',
    'illustrator_mcp.tools.arrange',
    'illustrator_mcp.tools.transform',
    'illustrator_mcp.tools.artboards',
    'illustrator_mcp.tools.execute',
]


@pytest.fixture
def mock_execute_script():
    """Mock the execute_script and execute_script_with_context functions to capture generated JavaScript."""
    mock = AsyncMock()
    mock.return_value = {"result": {"success": True}}

    # Patch both execute_script and execute_script_with_context in all tool modules
    patches = []
    for module in TOOL_MODULES:
        patches.append(patch(f'{module}.execute_script', mock))
    
    # Also patch execute_script_with_context in shapes module where it's used
    patches.append(patch('illustrator_mcp.tools.shapes.execute_script_with_context', mock))

    for p in patches:
        p.start()

    yield mock

    for p in patches:
        p.stop()


@pytest.fixture
def mock_proxy_success():
    """Mock successful proxy responses."""
    mock = AsyncMock()
    mock.return_value = {"result": '{"success": true}'}

    patches = [patch(f'{module}.execute_script', mock) for module in TOOL_MODULES]

    for p in patches:
        p.start()

    yield mock

    for p in patches:
        p.stop()


@pytest.fixture
def mock_proxy_error():
    """Mock proxy error responses."""
    mock = AsyncMock()
    mock.return_value = {"error": "Connection refused"}

    patches = [patch(f'{module}.execute_script', mock) for module in TOOL_MODULES]

    for p in patches:
        p.start()

    yield mock

    for p in patches:
        p.stop()
