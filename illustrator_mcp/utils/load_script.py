"""
Library script loading utilities.

Provides safe wrappers for loading ExtendScript library files with
manifest-driven dependency resolution vs. raw inline reads.
"""

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "resources", "scripts",
)


def load_script(name: str, *, params: Optional[Dict[str, Any]] = None) -> str:
    """Resolve a library script with all transitive deps via manifest.

    Returns executable JSX string with ``var __PARAMS__ = {...};`` preamble.
    ``params=None`` produces ``var __PARAMS__ = {};`` so JSX code never
    needs to guard against undefined.

    Raises:
        ValueError: If library not found or symbol collision detected.
    """
    from illustrator_mcp.libraries import get_resolver

    resolved_code = get_resolver().resolve(
        [name], skip_collision_check=True
    )
    params_json = json.dumps(params or {}, ensure_ascii=False)
    return f"var __PARAMS__ = {params_json};\n{resolved_code}"


def load_inline_script(path: str) -> str:
    """Raw file read, explicitly no dependency resolution.

    Use only for self-contained scripts that have no manifest dependencies
    (e.g., inline JSX snippets, templates).

    Args:
        path: Absolute or relative path to the .jsx file.
              Relative paths are resolved against the scripts directory.

    Raises:
        FileNotFoundError: If the script file does not exist.
    """
    if not os.path.isabs(path):
        path = os.path.join(_SCRIPTS_DIR, path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Script not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
