"""
Shared test fixtures and configuration for Illustrator MCP tests.
"""

import pytest
from unittest.mock import AsyncMock, patch


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "live: requires running Illustrator (deselect with -m 'not live')")
    config.addinivalue_line("markers", "unit: unit tests with mocks only")


# Active tool modules (archived modules removed in v2.0)
TOOL_MODULES = [
    'illustrator_mcp.tools.execute',
    'illustrator_mcp.tools.documents',
    'illustrator_mcp.tools.context',
    'illustrator_mcp.tools.query',
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
