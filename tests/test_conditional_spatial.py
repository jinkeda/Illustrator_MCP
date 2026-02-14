"""
test_conditional_spatial.py — Guard + behavioral tests for C2: Conditional Ops & C3: Spatial Targets

Tests:
  Guard (1-6): Static code/schema checks
  Behavioral (7-16): Logic verification
"""
import json
import pathlib
import re

import pytest

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "illustrator_mcp" / "resources" / "scripts"
OPS_CORE = (SCRIPTS_DIR / "ops_core.jsx").read_text(encoding="utf-8")
TARGETS_JSX = (SCRIPTS_DIR / "targets.jsx").read_text(encoding="utf-8")
TASK_PIPELINE = (SCRIPTS_DIR / "task_pipeline.jsx").read_text(encoding="utf-8")
CONTRACTS_PY = (SCRIPTS_DIR.parent.parent.parent / "illustrator_mcp" / "schemas" / "contracts.py").read_text(encoding="utf-8")
CONTRACTS_JSX = (SCRIPTS_DIR / "contracts.jsx").read_text(encoding="utf-8")


# ======================== Guard Tests (1-6) ========================

class TestGuardErrorCodes:
    """Test 1: G001-G003 and SP01-SP03 error codes exist in contracts."""

    @pytest.mark.parametrize("code,name", [
        ("G001", "G_UNKNOWN_PROPERTY"),
        ("G002", "G_INVALID_COMPARATOR"),
        ("G003", "G_MALFORMED"),
    ])
    def test_guard_code_in_contracts_py(self, code, name):
        assert f'{name} = "{code}"' in CONTRACTS_PY

    @pytest.mark.parametrize("code,name", [
        ("SP01", "SP_MISSING_PREDICATE"),
        ("SP02", "SP_INVALID_RECT"),
        ("SP03", "SP_REF_NOT_FOUND"),
    ])
    def test_spatial_code_in_contracts_py(self, code, name):
        assert f'{name} = "{code}"' in CONTRACTS_PY

    @pytest.mark.parametrize("code", ["G001", "G002", "G003", "SP01", "SP02", "SP03"])
    def test_codes_in_contracts_jsx(self, code):
        """Compiled contracts.jsx must also contain the error codes."""
        assert code in CONTRACTS_JSX


class TestGuardFunctionsExist:
    """Test 2: Guard functions exist in ops_core.jsx."""

    @pytest.mark.parametrize("fn", [
        "readGuardProperty",
        "evalComparator",
        "validateGuard",
        "filterByGuard",
    ])
    def test_function_exists(self, fn):
        assert f"function {fn}(" in OPS_CORE


class TestGuardPlacement:
    """Test 3: Guard evaluation is in executeSubOps between resolveTargets and handler."""

    def test_guard_in_execute_sub_ops(self):
        start = OPS_CORE.index("function executeSubOps(")
        # Find next top-level section
        end = OPS_CORE.index("// ==================== Batch Execution", start)
        body = OPS_CORE[start:end]
        assert "filterByGuard" in body

    def test_guard_after_resolve_before_handler(self):
        """Guard eval must come after resolveTargets and before handler invocation."""
        start = OPS_CORE.index("function executeSubOps(")
        end = OPS_CORE.index("// ==================== Batch Execution", start)
        body = OPS_CORE[start:end]
        resolve_pos = body.index("resolveTargets(")
        guard_pos = body.index("filterByGuard(")
        # Find first handler call after guard
        handler_pos = body.index("handlerResult", guard_pos)
        assert resolve_pos < guard_pos < handler_pos


class TestGuardSkippedResult:
    """Test 4: Skipped ops produce skipped: true in result."""

    def test_skipped_flag_exists(self):
        start = OPS_CORE.index("function executeSubOps(")
        end = OPS_CORE.index("// ==================== Batch Execution", start)
        body = OPS_CORE[start:end]
        assert "skipped: true" in body

    def test_skipped_reason(self):
        start = OPS_CORE.index("function executeSubOps(")
        end = OPS_CORE.index("// ==================== Batch Execution", start)
        body = OPS_CORE[start:end]
        assert "guard_filtered" in body


class TestSpatialInValidatePayload:
    """Test 5: 'spatial' is in validatePayload valid target types."""

    def test_spatial_in_valid_types(self):
        assert '"spatial"' in TASK_PIPELINE
        # Find the valid types array
        match = re.search(r'validTypes.*?\[([^\]]+)\]', TASK_PIPELINE)
        assert match, "validTypes array not found"
        assert '"spatial"' in match.group(1)


class TestSpatialBranchExists:
    """Test 6: Spatial branch exists in collectTargets in targets.jsx."""

    def test_spatial_branch(self):
        start = TARGETS_JSX.index("function collectTargets(")
        body = TARGETS_JSX[start:]
        assert 'type === "spatial"' in body

    def test_spatial_helpers_exist(self):
        for fn in ["normalizeRect", "itemCenter", "spatialScanFilter", "collectSpatialCandidates"]:
            assert f"function {fn}(" in TARGETS_JSX


# ======================== Behavioral Tests (7-16) ========================

class TestGuardPropertyAllowlist:
    """Test 7: readGuardProperty uses bounds-derived values for geometry."""

    def test_width_from_bounds(self):
        """width must be computed as bounds[2] - bounds[0]."""
        start = OPS_CORE.index("function readGuardProperty(")
        fn_end = OPS_CORE.index("function evalComparator(")
        body = OPS_CORE[start:fn_end]
        assert "b[2] - b[0]" in body

    def test_height_from_bounds(self):
        """height must be b[1] - b[3] (Illustrator Y convention: top > bottom)."""
        start = OPS_CORE.index("function readGuardProperty(")
        fn_end = OPS_CORE.index("function evalComparator(")
        body = OPS_CORE[start:fn_end]
        assert "b[1] - b[3]" in body

    def test_no_item_width_direct(self):
        """Must NOT use item.width directly — unreliable in Illustrator."""
        start = OPS_CORE.index("function readGuardProperty(")
        fn_end = OPS_CORE.index("function evalComparator(")
        body = OPS_CORE[start:fn_end]
        assert "item.width" not in body
        assert "item.height" not in body

    def test_hidden_not_in_allowlist(self):
        """hidden property should NOT be in the allowlist."""
        start = OPS_CORE.index("function readGuardProperty(")
        fn_end = OPS_CORE.index("function evalComparator(")
        body = OPS_CORE[start:fn_end]
        assert 'case "hidden"' not in body

    def test_all_allowed_properties(self):
        """Check exhaustive allowlist."""
        start = OPS_CORE.index("function readGuardProperty(")
        fn_end = OPS_CORE.index("function evalComparator(")
        body = OPS_CORE[start:fn_end]
        for prop in ["width", "height", "left", "top", "opacity", "name", "locked", "typename"]:
            assert f'case "{prop}"' in body


class TestComparatorTypeSafety:
    """Test 8: evalComparator enforces type checking."""

    def test_numeric_type_check(self):
        """Numeric comparators (gt, gte, lt, lte) must check typeof === 'number'."""
        start = OPS_CORE.index("function evalComparator(")
        fn_end = OPS_CORE.index("function validateGuard(")
        body = OPS_CORE[start:fn_end]
        assert 'typeof value !== "number"' in body

    def test_contains_string_check(self):
        """contains comparator must check typeof === 'string'."""
        start = OPS_CORE.index("function evalComparator(")
        fn_end = OPS_CORE.index("function validateGuard(")
        body = OPS_CORE[start:fn_end]
        # Find "contains" case and verify string check nearby
        contains_pos = body.index('case "contains"')
        after = body[contains_pos:contains_pos + 200]
        assert 'typeof value !== "string"' in after

    def test_matches_uses_regexp(self):
        """matches comparator must construct a RegExp."""
        start = OPS_CORE.index("function evalComparator(")
        fn_end = OPS_CORE.index("function validateGuard(")
        body = OPS_CORE[start:fn_end]
        assert "new RegExp(" in body


class TestGuardValidation:
    """Test 9: validateGuard checks structure."""

    def test_requires_property(self):
        start = OPS_CORE.index("function validateGuard(")
        fn_end = OPS_CORE.index("function filterByGuard(")
        body = OPS_CORE[start:fn_end]
        assert "guard.property" in body
        assert "G_MALFORMED" in body

    def test_requires_comparator(self):
        start = OPS_CORE.index("function validateGuard(")
        fn_end = OPS_CORE.index("function filterByGuard(")
        body = OPS_CORE[start:fn_end]
        assert "!comparator" in body


class TestGuardNonPageItemError:
    """Test 10: Non-PageItem target produces G001 error."""

    def test_geometric_bounds_check(self):
        """readGuardProperty must check for geometricBounds."""
        start = OPS_CORE.index("function readGuardProperty(")
        fn_end = OPS_CORE.index("function evalComparator(")
        body = OPS_CORE[start:fn_end]
        assert "geometricBounds" in body
        assert "G_UNKNOWN_PROPERTY" in body


class TestFilterByGuardLogic:
    """Test 11: filterByGuard implements when/unless correctly."""

    def test_when_keeps_true(self):
        """when: keep targets where guard is true."""
        start = OPS_CORE.index("function filterByGuard(")
        # Search enough to cover the full function
        fn_end_marker = "// ==================== Sub-Op Execution"
        end = OPS_CORE.index(fn_end_marker, start)
        body = OPS_CORE[start:end]
        assert "isUnless" in body
        assert "!cmpResult.result" in body  # unless inverts

    def test_hard_error_on_property_fail(self):
        """If readGuardProperty fails, the entire op fails (not filtered)."""
        start = OPS_CORE.index("function filterByGuard(")
        fn_end_marker = "// ==================== Sub-Op Execution"
        end = OPS_CORE.index(fn_end_marker, start)
        body = OPS_CORE[start:end]
        # Check that propResult error is returned directly, not swallowed
        assert "propResult.ok" in body


class TestSpatialRectNormalization:
    """Test 12: normalizeRect converts {x,y,width,height} to L,T,R,B with coord mode."""

    def test_rect_formula(self):
        """Supports coord='ai' (raw) and default 'user' (artboard-relative)."""
        start = TARGETS_JSX.index("function normalizeRect(")
        fn_end = TARGETS_JSX.index("function itemCenter(")
        body = TARGETS_JSX[start:fn_end]
        assert "Math.abs(rect.width)" in body     # negative width handling
        assert "Math.abs(rect.height)" in body    # negative height handling
        assert 'coord === "ai"' in body           # AI coord mode branch
        assert "artboardRect" in body             # artboard-relative conversion

    def test_validates_required_fields(self):
        start = TARGETS_JSX.index("function normalizeRect(")
        fn_end = TARGETS_JSX.index("function itemCenter(")
        body = TARGETS_JSX[start:fn_end]
        for field in ["rect.x", "rect.y", "rect.width", "rect.height"]:
            assert field in body


class TestSpatialItemCenter:
    """Test 13: itemCenter uses geometricBounds midpoint."""

    def test_center_calculation(self):
        start = TARGETS_JSX.index("function itemCenter(")
        fn_end = TARGETS_JSX.index("function spatialScanFilter(")
        body = TARGETS_JSX[start:fn_end]
        assert "b[0] + b[2]" in body  # x midpoint
        assert "b[1] + b[3]" in body  # y midpoint


class TestSpatialScanRules:
    """Test 14: Spatial scan skips hidden items/layers."""

    def test_hidden_items_skipped(self):
        start = TARGETS_JSX.index("function spatialScanFilter(")
        fn_end = TARGETS_JSX.index("function collectSpatialCandidates(")
        body = TARGETS_JSX[start:fn_end]
        assert "item.hidden" in body

    def test_hidden_layers_skipped(self):
        start = TARGETS_JSX.index("function collectSpatialCandidates(")
        body = TARGETS_JSX[start:start + 400]
        assert "layers[i].visible" in body or "layer.visible" in body

    def test_guides_skipped(self):
        start = TARGETS_JSX.index("function spatialScanFilter(")
        fn_end = TARGETS_JSX.index("function collectSpatialCandidates(")
        body = TARGETS_JSX[start:fn_end]
        assert "item.guides" in body


def _get_spatial_branch():
    """Extract the full spatial branch from collectTargets."""
    start = TARGETS_JSX.index('type === "spatial"')
    # Find the end of the spatial branch (next else if or else)
    end = TARGETS_JSX.index('type === "compound"', start)
    return TARGETS_JSX[start:end]


class TestSpatialNearToValidation:
    """Test 15: nearTo validates ref resolution and single-item constraint."""

    def test_missing_ref_error(self):
        body = _get_spatial_branch()
        assert "SP_REF_NOT_FOUND" in body

    def test_multi_ref_error(self):
        """nearTo with multiple resolved items must error."""
        body = _get_spatial_branch()
        assert "refItems.length > 1" in body

    def test_excludes_ref_from_results(self):
        """nearTo must not include the reference item itself in results."""
        body = _get_spatial_branch()
        assert "refItems[0]" in body
        assert "continue" in body  # Skip ref item


class TestSpatialPredicateLogic:
    """Test 16: within/outside are complementary using LTRB bounds."""

    def test_within_uses_ltrb(self):
        body = _get_spatial_branch()
        assert "norm.L" in body
        assert "norm.R" in body
        assert "norm.T" in body
        assert "norm.B" in body

    def test_outside_is_complement(self):
        """outside uses !inside — exact complement of within."""
        body = _get_spatial_branch()
        assert "hasWithin && inside" in body or "hasWithin \x26\x26 inside" in body
        assert "hasOutside && !inside" in body or "hasOutside \x26\x26 !inside" in body

    def test_distance_squared_for_nearTo(self):
        """nearTo should use squared distance to avoid sqrt."""
        body = _get_spatial_branch()
        assert "dx * dx + dy * dy" in body


# ======================== Spatial Validation Tests (17-20) ========================

def _get_validate_spatial_block():
    """Extract the spatial validation branch from validatePayload."""
    start = TASK_PIPELINE.index('target.type === "spatial"')
    # Find the closing of the spatial block — ends at "// Validate options"
    end_marker = TASK_PIPELINE.index("// Validate options", start)
    return TASK_PIPELINE[start:end_marker]


class TestV009ErrorCode:
    """Test 17: V_INVALID_PARAM_VALUE (V009) exists and is distinct from V007."""

    def test_v009_in_contracts_py(self):
        assert "V_INVALID_PARAM_VALUE" in CONTRACTS_PY
        assert '"V009"' in CONTRACTS_PY

    def test_v009_in_contracts_jsx(self):
        assert "V_INVALID_PARAM_VALUE" in CONTRACTS_JSX
        assert '"V009"' in CONTRACTS_JSX

    def test_v009_distinct_from_v007(self):
        """V009 (invalid value) is semantically different from V007 (invalid type)."""
        assert "V_INVALID_PARAM_TYPE" in CONTRACTS_PY
        assert "V_INVALID_PARAM_VALUE" in CONTRACTS_PY
        # They must have different codes
        assert '"V007"' in CONTRACTS_PY
        assert '"V009"' in CONTRACTS_PY


class TestSpatialValidation:
    """Test 18: validatePayload checks spatial sub-fields with correct error codes."""

    def test_predicate_null_check(self):
        """Missing predicate uses null-safe == null check, not truthy."""
        body = _get_validate_spatial_block()
        assert "target.within == null" in body
        assert "target.outside == null" in body
        assert "target.nearTo == null" in body

    def test_predicate_error_code(self):
        """Missing predicate uses V_MISSING_REQUIRED_PARAM."""
        body = _get_validate_spatial_block()
        assert "V_MISSING_REQUIRED_PARAM" in body

    def test_coord_type_before_enum(self):
        """coord validation checks typeof string first, then enum."""
        body = _get_validate_spatial_block()
        type_check_pos = body.index('typeof target.coord !== "string"')
        enum_check_pos = body.index("V_INVALID_PARAM_VALUE")
        assert type_check_pos < enum_check_pos, "type check must precede enum check"

    def test_coord_enum_uses_v009(self):
        """Invalid coord enum value uses V009, not V007."""
        body = _get_validate_spatial_block()
        assert "V_INVALID_PARAM_VALUE" in body
        assert "'user'" in body or '"user"' in body
        assert "'ai'" in body or '"ai"' in body

    def test_coord_type_error_uses_v007(self):
        """Non-string coord uses V_INVALID_PARAM_TYPE (V007)."""
        body = _get_validate_spatial_block()
        assert "V_INVALID_PARAM_TYPE" in body

    def test_layer_type_check(self):
        """layer must be validated as string type."""
        body = _get_validate_spatial_block()
        assert 'typeof target.layer !== "string"' in body

    def test_error_stage_is_validate(self):
        """All spatial validation errors report stage = 'validate'."""
        body = _get_validate_spatial_block()
        # Count occurrences of '"validate"' — should match number of makeError calls
        validate_count = body.count('"validate"')
        make_error_count = body.count("makeError(")
        assert validate_count == make_error_count, (
            f"Expected {make_error_count} 'validate' stage strings, found {validate_count}"
        )


class TestPositionEchoContract:
    """Test 19: element_modify returns position echo in response data."""

    def test_first_modified_item_tracked(self):
        """Position echo uses firstModifiedItem, not targets[0]."""
        ops_element = (SCRIPTS_DIR / "ops_element.jsx").read_text(encoding="utf-8")
        assert "firstModifiedItem" in ops_element
        assert "if (!firstModifiedItem) firstModifiedItem = item" in ops_element

    def test_position_in_data(self):
        """Response data includes position field."""
        ops_element = (SCRIPTS_DIR / "ops_element.jsx").read_text(encoding="utf-8")
        assert "position: posEcho" in ops_element

    def test_position_uses_artboard_coords(self):
        """Position echo converts to user coords via artboard offsets."""
        ops_element = (SCRIPTS_DIR / "ops_element.jsx").read_text(encoding="utf-8")
        assert "_artboardTop" in ops_element
        assert "_artboardLeft" in ops_element


# ======================== F4/F5/F1 Solidification Tests ========================


class TestRectShapeValidation:
    """Test 20: validatePayload checks within/outside rect shape (x, y, width, height)."""

    def test_rect_field_validation_exists(self):
        """Rect validation checks all four required fields."""
        body = _get_validate_spatial_block()
        for field in ["x", "y", "width", "height"]:
            assert f'"{field}"' in body or f"'{field}'" in body, (
                f"Field '{field}' not validated in spatial block"
            )

    def test_rect_missing_uses_v006(self):
        """Missing rect field uses V_MISSING_REQUIRED_PARAM."""
        body = _get_validate_spatial_block()
        # Look for the pattern: rect field null check + V_MISSING_REQUIRED_PARAM
        assert "V_MISSING_REQUIRED_PARAM" in body

    def test_rect_type_uses_v007(self):
        """Wrong-type rect field uses V_INVALID_PARAM_TYPE."""
        body = _get_validate_spatial_block()
        assert "V_INVALID_PARAM_TYPE" in body

    def test_rect_array_guard(self):
        """Rect validation rejects arrays passed as rect objects."""
        body = _get_validate_spatial_block()
        assert "instanceof Array" in body


class TestNearToShapeValidation:
    """Test 21: validatePayload checks nearTo shape (id, radius)."""

    def test_nearTo_id_required(self):
        body = _get_validate_spatial_block()
        assert "nearTo.id is required" in body

    def test_nearTo_radius_required(self):
        body = _get_validate_spatial_block()
        assert "nearTo.radius is required" in body

    def test_nearTo_id_type_check(self):
        body = _get_validate_spatial_block()
        assert "nearTo.id must be a string" in body

    def test_nearTo_radius_type_check(self):
        body = _get_validate_spatial_block()
        assert "nearTo.radius must be a number" in body


class TestDualGuardWarning:
    """Test 22: when+unless dual-presence warning in ops_core.jsx (F4)."""

    def test_warning_emitted(self):
        """ops_core.jsx emits a warning when both when and unless are present."""
        assert "Op has both 'when' and 'unless'" in OPS_CORE

    def test_when_takes_precedence(self):
        """Warning clarifies that when takes precedence."""
        assert "'when' takes precedence" in OPS_CORE


class TestThrowStructuredHelper:
    """Test 23: throwStructured helper exists and preserves structured error data (F1)."""

    def test_helper_exists(self):
        assert "function throwStructured" in TARGETS_JSX

    def test_preserves_code(self):
        assert "err.code" in TARGETS_JSX

    def test_preserves_stage(self):
        assert "err.stage" in TARGETS_JSX

    def test_preserves_meta(self):
        assert "err.meta" in TARGETS_JSX

