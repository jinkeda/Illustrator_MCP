"""
Registry snapshot test — ensures tool and resource inventories match expectations.

Intentionally inspects FastMCP internals for tool listing;
update if FastMCP API changes.
"""

import pytest

# Authoritative list — single source of truth for expected tool names.
# Imported from tools/__init__.py to avoid drift.
from illustrator_mcp.tools import EXPECTED_TOOL_NAMES, register_tools


EXPECTED_RESOURCE_URIS = {
    "illustrator://reference/extendscript",
    "illustrator://reference/libraries",
    "extendscript://snippets/update_linked_items",
}


@pytest.fixture(autouse=True, scope="module")
def _ensure_tools_registered():
    """Ensure all tools are registered via side-effect imports."""
    from illustrator_mcp.shared import mcp
    register_tools(mcp)


class TestToolRegistry:
    """Snapshot test: exactly 12 tools registered."""

    def test_tool_count(self):
        from illustrator_mcp.shared import mcp
        # Intentionally uses FastMCP internals; update if FastMCP changes.
        tools = mcp._tool_manager._tools
        assert len(tools) == len(EXPECTED_TOOL_NAMES), (
            f"Expected {len(EXPECTED_TOOL_NAMES)} tools, got {len(tools)}: "
            f"extra={set(tools.keys()) - EXPECTED_TOOL_NAMES}, "
            f"missing={EXPECTED_TOOL_NAMES - set(tools.keys())}"
        )

    def test_tool_names_match(self):
        from illustrator_mcp.shared import mcp
        tools = mcp._tool_manager._tools
        assert set(tools.keys()) == EXPECTED_TOOL_NAMES


class TestResourceRegistry:
    """Ensure critical resources are registered."""

    def test_expected_resources_exist(self):
        from illustrator_mcp.shared import mcp
        # FastMCP resource manager internals
        try:
            resources = mcp._resource_manager._resources
            resource_uris = set(resources.keys())
        except AttributeError:
            pytest.skip("FastMCP resource manager internals changed; update test")

        for uri in EXPECTED_RESOURCE_URIS:
            assert uri in resource_uris, f"Missing resource: {uri}"
