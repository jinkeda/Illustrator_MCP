"""
Shared test fixtures and configuration for Illustrator MCP tests.
"""

import pytest
from contextlib import ExitStack
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
    """Mock the execute_script function to capture generated JavaScript."""
    mock = AsyncMock()
    mock.return_value = {"result": {"success": True}}

    with ExitStack() as stack:
        for module in TOOL_MODULES:
            stack.enter_context(patch(f'{module}.execute_script', mock))
        yield mock


@pytest.fixture
def mock_proxy_success():
    """Mock successful proxy responses."""
    mock = AsyncMock()
    mock.return_value = {"result": '{"success": true}'}

    with ExitStack() as stack:
        for module in TOOL_MODULES:
            stack.enter_context(patch(f'{module}.execute_script', mock))
        yield mock


@pytest.fixture
def mock_proxy_error():
    """Mock proxy error responses."""
    mock = AsyncMock()
    mock.return_value = {"error": "Connection refused"}

    with ExitStack() as stack:
        for module in TOOL_MODULES:
            stack.enter_context(patch(f'{module}.execute_script', mock))
        yield mock

