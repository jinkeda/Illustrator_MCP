"""
test_contracts_jsx_staleness.py – verify contracts.jsx stays in sync with contracts.py.

Uses compile_contracts --check which compares the embedded CONTRACTS_CHECKSUM
against the current state of contracts.py.
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def test_contracts_jsx_not_stale():
    """contracts.jsx checksum must match the contracts.py SSOT."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "illustrator_mcp.tools.compile_contracts",
            "--check",
        ],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, (
        f"contracts.jsx is stale — recompile with:\n"
        f"  python -m illustrator_mcp.tools.compile_contracts\n"
        f"stdout: {result.stdout.strip()}\n"
        f"stderr: {result.stderr.strip()}"
    )
