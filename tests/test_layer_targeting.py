"""
Guard tests for deterministic layer targeting.

Verifies that _resolveTargetLayer helper exists, all refactored sites use it,
ctx.defaultLayer/warn are wired, and text_create uses findLayer fallback.
"""

import pathlib
import pytest

# --------------- paths ---------------

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / \
    "illustrator_mcp" / "resources" / "scripts"
OPS_ELEMENT = SCRIPTS_DIR / "ops_element.jsx"
OPS_TEXT = SCRIPTS_DIR / "ops_text.jsx"
OPS_CORE = SCRIPTS_DIR / "ops_core.jsx"
MANIFEST = SCRIPTS_DIR / "manifest.json"


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


# ==================== _resolveTargetLayer Helper ====================

class TestResolveTargetLayer:
    """The deterministic layer resolution helper must exist and be correct."""

    def test_helper_function_exists(self):
        src = _read(OPS_ELEMENT)
        assert "function _resolveTargetLayer(" in src

    def test_checks_params_layer_first(self):
        """Explicit params.layer has highest priority."""
        src = _read(OPS_ELEMENT)
        start = src.index("function _resolveTargetLayer(")
        section = src[start:start + 600]
        assert "params.layer" in section

    def test_checks_ctx_defaultLayer(self):
        """ctx.defaultLayer is the second-priority fallback."""
        src = _read(OPS_ELEMENT)
        start = src.index("function _resolveTargetLayer(")
        section = src[start:start + 600]
        assert "ctx.defaultLayer" in section

    def test_warns_on_activeLayer_fallback(self):
        """Falling back to doc.activeLayer should trigger a warning."""
        src = _read(OPS_ELEMENT)
        start = src.index("function _resolveTargetLayer(")
        section = src[start:start + 600]
        assert "ctx.warn" in section or "warn" in section


# ==================== Refactored Call Sites ====================

class TestRefactoredSites:
    """All 4 element creation sites must call _resolveTargetLayer."""

    def test_element_create_uses_helper(self):
        src = _read(OPS_ELEMENT)
        start = src.index('registerOpHandler("element_create",')
        section = src[start:start + 1200]
        assert "_resolveTargetLayer(" in section

    def test_element_create_multi_uses_findLayer(self):
        """element_create_multi uses findLayer directly with fallback logic."""
        src = _read(OPS_ELEMENT)
        start = src.index('registerOpHandler("element_create_multi"')
        section = src[start:start + 1200]
        assert "findLayer" in section or "_resolveTargetLayer" in section

    def test_createFromTemplate_uses_helper(self):
        src = _read(OPS_ELEMENT)
        start = src.index("function _createFromTemplate(")
        section = src[start:start + 700]
        assert "_resolveTargetLayer(" in section

    def test_element_create_batch_uses_helper(self):
        src = _read(OPS_ELEMENT)
        start = src.index('registerOpHandler("element_create_batch"')
        section = src[start:start + 2000]
        assert "_resolveTargetLayer(" in section


# ==================== Context Wiring ====================

class TestContextWiring:
    """ctx must include defaultLayer and warn function."""

    def test_ctx_has_defaultLayer(self):
        src = _read(OPS_CORE)
        assert "defaultLayer" in src

    def test_ctx_has_warn_function(self):
        src = _read(OPS_CORE)
        assert "ctx.warn" in src or "warn:" in src

    def test_ctx_has_warnings_array(self):
        src = _read(OPS_CORE)
        assert "warnings" in src

    def test_warnings_surfaced_in_report(self):
        """ctx.warnings should be seeded into reportWarnings."""
        src = _read(OPS_CORE)
        assert "ctx.warnings" in src


# ==================== text_create Layer Support ====================

class TestTextCreateLayer:
    """text_create must use findLayer with deterministic fallback."""

    def test_uses_findLayer(self):
        src = _read(OPS_TEXT)
        start = src.index('registerOpHandler("text_create"')
        section = src[start:start + 700]
        assert "findLayer" in section

    def test_ctx_defaultLayer_fallback(self):
        src = _read(OPS_TEXT)
        start = src.index('registerOpHandler("text_create"')
        section = src[start:start + 700]
        assert "ctx.defaultLayer" in section

    def test_manifest_has_targets_dependency(self):
        """ops_text must declare targets as a dependency in manifest."""
        import json
        manifest = json.loads(_read(MANIFEST))
        deps = manifest["libraries"]["ops_text"]["dependencies"]
        assert "targets" in deps
