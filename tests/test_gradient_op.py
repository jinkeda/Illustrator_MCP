"""
Guard tests for style_set_gradient SOC operation.

Verifies handler registration, stop validation, gradient reuse by name,
MUTATING_OPS membership, and contracts schema presence.
"""

import pathlib
import pytest

# --------------- paths ---------------

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / \
    "illustrator_mcp" / "resources" / "scripts"
OPS_STYLE = SCRIPTS_DIR / "ops_style.jsx"
OPS_CORE = SCRIPTS_DIR / "ops_core.jsx"
CONTRACTS_PATH = pathlib.Path(__file__).resolve().parent.parent / \
    "illustrator_mcp" / "schemas" / "contracts.py"


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


# ==================== Handler Registration ====================

class TestGradientRegistration:
    """style_set_gradient must be registered as an op handler."""

    def test_handler_registered(self):
        src = _read(OPS_STYLE)
        assert 'registerOpHandler("style_set_gradient"' in src


# ==================== Validation Guards ====================

class TestGradientValidation:
    """Gradient handler must validate inputs."""

    def test_requires_minimum_2_stops(self):
        """Prevents divide-by-zero in rampPoint calculation."""
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_set_gradient"')
        section = src[start:start + 1500]
        assert "params.stops.length < 2" in section

    def test_returns_error_on_insufficient_stops(self):
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_set_gradient"')
        section = src[start:start + 1500]
        assert "V_MISSING_REQUIRED_PARAM" in section


# ==================== Gradient Reuse ====================

class TestGradientReuse:
    """Gradient handler must reuse existing gradients by name."""

    def test_checks_existing_gradient(self):
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_set_gradient"')
        section = src[start:start + 2000]
        assert "getByName" in section

    def test_creates_new_if_not_found(self):
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_set_gradient"')
        section = src[start:start + 2000]
        assert "gradients.add()" in section

    def test_returns_gradient_name(self):
        """Response must include the gradient name for reuse."""
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_set_gradient"')
        section = src[start:start + 3000]
        assert "gradientName" in section


# ==================== Gradient Type ====================

class TestGradientType:
    """Handler must support both linear and radial gradients."""

    def test_supports_linear(self):
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_set_gradient"')
        section = src[start:start + 1500]
        assert "GradientType.LINEAR" in section

    def test_supports_radial(self):
        src = _read(OPS_STYLE)
        start = src.index('registerOpHandler("style_set_gradient"')
        section = src[start:start + 1500]
        assert "GradientType.RADIAL" in section


# ==================== MUTATING_OPS ====================

class TestGradientMutatingOps:
    """style_set_gradient must be in MUTATING_OPS for undo tracking."""

    def test_in_mutating_ops(self):
        src = _read(OPS_CORE)
        start = src.index("MUTATING_OPS")
        section = src[start:start + 800]
        assert '"style_set_gradient"' in section


# ==================== Contracts Schema ====================

class TestGradientContract:
    """style_set_gradient must have a schema in contracts.py."""

    def test_schema_present(self):
        content = _read(CONTRACTS_PATH)
        assert 'name="style_set_gradient"' in content

    def test_type_param_required(self):
        content = _read(CONTRACTS_PATH)
        start = content.index('name="style_set_gradient"')
        section = content[start:start + 400]
        assert '"type"' in section
        assert "required=True" in section

    def test_stops_param_required(self):
        content = _read(CONTRACTS_PATH)
        start = content.index('name="style_set_gradient"')
        section = content[start:start + 400]
        assert '"stops"' in section
        assert "required=True" in section

    def test_name_param_optional(self):
        content = _read(CONTRACTS_PATH)
        start = content.index('name="style_set_gradient"')
        section = content[start:start + 400]
        assert '"name"' in section
