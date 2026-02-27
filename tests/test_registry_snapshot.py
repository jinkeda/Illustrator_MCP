"""
Registry snapshot test — ensures tool and resource inventories match expectations.

Also enforces canonical policies:
- P1/P2: Every tool has all 4 annotation hint keys (TOOL_ANNOTATIONS SSOT)
- P3: Docstrings follow the allowed-section schema with CONTRACT lines
- P5: CONTRACT booleans match decorator annotation values

Intentionally inspects FastMCP internals for tool listing;
update if FastMCP API changes.
"""

import re
import pytest

# Authoritative list — single source of truth for expected tool names.
# Imported from tools/__init__.py to avoid drift.
from illustrator_mcp.tools import EXPECTED_TOOL_NAMES, register_tools
from illustrator_mcp.tools.base import (
    TOOL_ANNOTATIONS, _REQUIRED_HINT_KEYS, ALLOWED_DOCSTRING_SECTIONS, _BANNED_CHARS,
)


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


class TestAnnotationsComplete:
    """P1/P2: Every tool in TOOL_ANNOTATIONS has all 4 hint keys."""

    def test_all_tools_have_annotations(self):
        """Every expected tool name must appear in TOOL_ANNOTATIONS."""
        for name in EXPECTED_TOOL_NAMES:
            assert name in TOOL_ANNOTATIONS, (
                f"Tool '{name}' missing from TOOL_ANNOTATIONS in base.py"
            )

    def test_all_hint_keys_present(self):
        """Every annotation dict must contain exactly the 4 required hint keys."""
        for name, ann in TOOL_ANNOTATIONS.items():
            missing = _REQUIRED_HINT_KEYS - set(ann.keys())
            assert not missing, (
                f"Tool '{name}' missing hint keys: {missing}"
            )

    def test_hint_values_are_bool(self):
        """All hint values must be booleans."""
        for name, ann in TOOL_ANNOTATIONS.items():
            for key in _REQUIRED_HINT_KEYS:
                assert isinstance(ann[key], bool), (
                    f"Tool '{name}' hint '{key}' is {type(ann[key])}, expected bool"
                )


# ── Regex for parsing CONTRACT lines ──────────────────────────────
_CONTRACT_RE = re.compile(
    r"CONTRACT:\s*"
    r"readOnly=(?P<readOnly>True|False),\s*"
    r"destructive=(?P<destructive>True|False),\s*"
    r"idempotent=(?P<idempotent>True|False),\s*"
    r"openWorld=(?P<openWorld>True|False)"
)

# Map CONTRACT field names to annotation key names
_CONTRACT_TO_HINT = {
    "readOnly": "readOnlyHint",
    "destructive": "destructiveHint",
    "idempotent": "idempotentHint",
    "openWorld": "openWorldHint",
}


def _get_tool_functions():
    """Collect all registered tool async functions by name."""
    from illustrator_mcp.shared import mcp
    tools = mcp._tool_manager._tools
    return {name: tool.fn for name, tool in tools.items()}


class TestDocstringSchemaLint:
    """P3: Docstrings follow the canonical schema."""

    def test_all_caps_headers_are_allowed(self):
        """Any ALL_CAPS_WORD: header in a docstring must be in the allowed set."""
        header_re = re.compile(r"^\s{0,4}([A-Z][A-Z _]+:)\s*$", re.MULTILINE)
        funcs = _get_tool_functions()
        for name, fn in funcs.items():
            doc = fn.__doc__ or ""
            for match in header_re.finditer(doc):
                header = match.group(1).strip()
                assert header in ALLOWED_DOCSTRING_SECTIONS, (
                    f"Tool '{name}' has unknown section header '{header}'. "
                    f"Allowed: {sorted(ALLOWED_DOCSTRING_SECTIONS)}"
                )

    def test_contract_line_present(self):
        """Every tool docstring must contain a CONTRACT: line."""
        funcs = _get_tool_functions()
        for name, fn in funcs.items():
            doc = fn.__doc__ or ""
            assert "CONTRACT:" in doc, (
                f"Tool '{name}' is missing CONTRACT: line in docstring"
            )

    def test_no_banned_chars(self):
        """Docstrings must not contain box-drawing characters."""
        funcs = _get_tool_functions()
        for name, fn in funcs.items():
            doc = fn.__doc__ or ""
            found = set(doc) & _BANNED_CHARS
            assert not found, (
                f"Tool '{name}' docstring contains banned chars: {found}"
            )

    def test_no_markdown_headings(self):
        """Docstrings must not contain markdown # headings."""
        heading_re = re.compile(r"^\s*#{1,6}\s", re.MULTILINE)
        funcs = _get_tool_functions()
        for name, fn in funcs.items():
            doc = fn.__doc__ or ""
            assert not heading_re.search(doc), (
                f"Tool '{name}' docstring contains markdown heading (#)"
            )


class TestContractMatchesAnnotations:
    """P5: CONTRACT line booleans must match decorator annotation values."""

    def test_contract_consistency(self):
        """Parse CONTRACT: from docstring and compare to TOOL_ANNOTATIONS."""
        funcs = _get_tool_functions()
        for name, fn in funcs.items():
            doc = fn.__doc__ or ""
            m = _CONTRACT_RE.search(doc)
            if m is None:
                pytest.fail(f"Tool '{name}': CONTRACT line not parseable")

            ann = TOOL_ANNOTATIONS.get(name, {})
            for contract_field, hint_key in _CONTRACT_TO_HINT.items():
                doc_val = m.group(contract_field) == "True"
                ann_val = ann.get(hint_key)
                assert doc_val == ann_val, (
                    f"Tool '{name}': CONTRACT {contract_field}={doc_val} "
                    f"but annotation {hint_key}={ann_val}"
                )

