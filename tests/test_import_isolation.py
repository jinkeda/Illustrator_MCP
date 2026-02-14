"""
Import isolation tests.

Enforces architectural layer boundaries:
- types.py must never import runtime or bridge
- connection_helpers.py must never import runtime (DI-based)
- Import order must not matter (tools-first vs runtime-first)
"""

import subprocess
import sys

import pytest


class TestImportIsolation:
    """Verify that base layers do not pull higher layers."""

    def test_types_does_not_import_runtime(self):
        """types.py must never pull runtime or bridge."""
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; import illustrator_mcp.types; "
             "assert 'illustrator_mcp.runtime' not in sys.modules, "
             "'types.py pulled runtime'; "
             "assert 'illustrator_mcp.websocket_bridge' not in sys.modules, "
             "'types.py pulled websocket_bridge'"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Import isolation violated:\n{result.stderr}"

    def test_connection_helpers_does_not_import_runtime(self):
        """connection_helpers.py must never pull runtime (DI-based)."""
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; import illustrator_mcp.connection_helpers; "
             "assert 'illustrator_mcp.runtime' not in sys.modules, "
             "'connection_helpers.py pulled runtime'; "
             "assert 'illustrator_mcp.websocket_bridge' not in sys.modules, "
             "'connection_helpers.py pulled websocket_bridge'; "
             "assert 'illustrator_mcp.proxy_client' not in sys.modules, "
             "'connection_helpers.py pulled proxy_client'"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Import isolation violated:\n{result.stderr}"

    def test_import_order_tools_first(self):
        """Import tools before runtime — must not crash."""
        result = subprocess.run(
            [sys.executable, "-c",
             "import illustrator_mcp.tools; import illustrator_mcp.runtime"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Import order (tools first) failed:\n{result.stderr}"

    def test_import_order_runtime_first(self):
        """Import runtime before tools — must not crash."""
        result = subprocess.run(
            [sys.executable, "-c",
             "import illustrator_mcp.runtime; import illustrator_mcp.tools"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Import order (runtime first) failed:\n{result.stderr}"
