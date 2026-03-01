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


# ── Collection-error guard ─────────────────────────────────────────
# Catches import failures that silently block entire test modules.
# Without this, a test file with a broken import is quietly skipped
# and only shows as "1 error" in the summary — easy to miss.

_collection_errors: list = []


def pytest_collectreport(report):
    """Record collection errors so we can fail loudly at session end."""
    if report.outcome == "failed":
        _collection_errors.append(report)


def pytest_sessionfinish(session, exitstatus):
    """Fail the session if any test modules failed to collect."""
    if _collection_errors:
        import sys
        print("\n" + "=" * 70, file=sys.stderr)
        print("COLLECTION ERROR GUARD: The following test modules failed to import:",
              file=sys.stderr)
        for report in _collection_errors:
            print(f"  ✗ {report.nodeid}", file=sys.stderr)
            if report.longrepr:
                # Print just the last line (the actual ImportError)
                lines = str(report.longrepr).strip().split("\n")
                for line in lines[-3:]:
                    print(f"    {line.strip()}", file=sys.stderr)
        print("=" * 70, file=sys.stderr)
        print("Fix these imports or delete the test files. Silent skips are not allowed.",
              file=sys.stderr)
        # pytest already sets exitstatus=2 for collection errors,
        # but this makes the failure message impossible to miss.


# Modules that use execute_jsx_tool (from base.py)
JSX_TOOL_MODULES = [
    'illustrator_mcp.tools.documents',
    'illustrator_mcp.tools._export',
    'illustrator_mcp.tools._place',
    'illustrator_mcp.tools._history',
    'illustrator_mcp.tools.context',
    'illustrator_mcp.tools.query',
]


@pytest.fixture
def mock_execute_script():
    """Mock execute_jsx_tool and execute_script_with_context for all tool modules.
    
    Uses the same mock for both so test assertions work with either code path.
    Access the script via: mock.call_args.kwargs['script']
    """
    mock = AsyncMock()
    mock.return_value = '{"success": true}'

    with ExitStack() as stack:
        for module in JSX_TOOL_MODULES:
            try:
                stack.enter_context(patch(f'{module}.execute_jsx_tool', mock))
            except AttributeError:
                pass
        # Patch execute_script_with_context in both documents.py and _export.py
        esc_mock = AsyncMock(return_value={"result": '{"success": true}'})
        stack.enter_context(patch(
            'illustrator_mcp.tools.documents.execute_script_with_context', esc_mock
        ))
        stack.enter_context(patch(
            'illustrator_mcp.tools._export.execute_script_with_context', esc_mock
        ))
        from unittest.mock import MagicMock
        fmt_mock = MagicMock(return_value='{"success": true}')
        stack.enter_context(patch(
            'illustrator_mcp.tools.documents.format_envelope', fmt_mock
        ))
        stack.enter_context(patch(
            'illustrator_mcp.tools._export.format_envelope', fmt_mock
        ))
        yield mock


@pytest.fixture
def mock_proxy_success():
    """Mock successful proxy responses."""
    mock = AsyncMock()
    mock.return_value = '{"success": true}'

    with ExitStack() as stack:
        for module in JSX_TOOL_MODULES:
            try:
                stack.enter_context(patch(f'{module}.execute_jsx_tool', mock))
            except AttributeError:
                pass
        yield mock


@pytest.fixture
def mock_proxy_error():
    """Mock proxy error responses."""
    mock = AsyncMock()
    mock.return_value = '{"error": "Connection refused"}'

    with ExitStack() as stack:
        for module in JSX_TOOL_MODULES:
            try:
                stack.enter_context(patch(f'{module}.execute_jsx_tool', mock))
            except AttributeError:
                pass
        yield mock
