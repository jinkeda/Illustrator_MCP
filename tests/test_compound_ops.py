"""
test_compound_ops.py — Guard + behavioral tests for C1: Compound Operations

Tests:
  Guard (1-7): Static code/schema checks
  Behavioral (8-11): SOC harness integration tests
"""
import json
import pathlib
import re

import pytest

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "illustrator_mcp" / "resources" / "scripts"
OPS_CORE = (SCRIPTS_DIR / "ops_core.jsx").read_text(encoding="utf-8")
OPS_COMPOUND = (SCRIPTS_DIR / "ops_compound.jsx").read_text(encoding="utf-8")
CONTRACTS_PY = (SCRIPTS_DIR.parent.parent.parent / "illustrator_mcp" / "schemas" / "contracts.py").read_text(encoding="utf-8")
ERRORS_PY = (SCRIPTS_DIR.parent.parent.parent / "illustrator_mcp" / "errors.py").read_text(encoding="utf-8")
CONTRACTS_JSX = (SCRIPTS_DIR / "contracts.jsx").read_text(encoding="utf-8")
MANIFEST = json.loads((SCRIPTS_DIR / "manifest.json").read_text(encoding="utf-8"))


# ======================== Guard Tests (1-7) ========================

class TestGuardCompoundSchema:
    """Test 1: compound schema exists with ops required, atomic optional."""

    def test_compound_schema_exists(self):
        assert 'name="compound"' in CONTRACTS_PY

    def test_ops_required(self):
        # Find the compound schema block
        match = re.search(
            r'OpSchema\(name="compound".*?\)',
            CONTRACTS_PY, re.DOTALL
        )
        assert match, "compound schema not found"
        block = match.group()
        assert "required=True" in block
        assert '"ops"' in block

    def test_atomic_optional(self):
        # Find the compound schema definition — check that "atomic" is present
        # and does NOT have required=True
        lines = CONTRACTS_PY.splitlines()
        in_compound = False
        found_atomic = False
        for line in lines:
            if 'name="compound"' in line:
                in_compound = True
            if in_compound:
                if '"atomic"' in line:
                    found_atomic = True
                    assert "required=True" not in line, "atomic must not be required"
                    break
                if line.strip() == "])," or line.strip() == "]":
                    break
        assert found_atomic, "compound schema must include 'atomic' param"


class TestGuardCompoundInMutatingOps:
    """Test 2: compound is in OP_CLASS as 'doc'."""

    def test_compound_in_op_class(self):
        assert '"compound": "doc"' in OPS_CORE or '"compound":"doc"' in OPS_CORE


class TestGuardExecuteSubOps:
    """Test 3: executeSubOps function exists in ops_core.jsx."""

    def test_function_exists(self):
        assert "function executeSubOps(" in OPS_CORE

    def test_does_not_call_heap_txn(self):
        """executeSubOps must NOT start/commit heap txns."""
        # Extract the function body
        start = OPS_CORE.index("function executeSubOps(")
        # Find the matching closing brace (approximate: look for next top-level function)
        end = OPS_CORE.index("// ==================== Batch Execution", start)
        body = OPS_CORE[start:end]
        assert "heapBeginTxn" not in body
        assert "heapCommitTxn" not in body

    def test_returns_structured_result(self):
        """Return value must include ok, results, createdIds, passed, failed."""
        start = OPS_CORE.index("function executeSubOps(")
        end = OPS_CORE.index("// ==================== Batch Execution", start)
        body = OPS_CORE[start:end]
        for field in ["ok:", "results:", "createdIds:", "passed:", "failed:", "undoCount:", "rolledBackCount:"]:
            assert field in body, f"Missing return field: {field}"

    def test_executeOpBatch_delegates_to_executeSubOps(self):
        """executeOpBatch must call executeSubOps instead of inline loop."""
        batch_start = OPS_CORE.index("function executeOpBatch(")
        batch_body = OPS_CORE[batch_start:]
        assert "executeSubOps(ops, ctx," in batch_body


class TestGuardResolvePrevTokens:
    """Test 4: resolvePrevTokens exists in ops_compound.jsx and is pure."""

    def test_function_exists(self):
        assert "function resolvePrevTokens(" in OPS_COMPOUND

    def test_returns_new_op(self):
        """Must return {ok: true, op: ...} — shallow clone, not mutation."""
        assert "op:" in OPS_COMPOUND
        # Must not assign to op.targets directly
        assert "op.targets.ids =" not in OPS_COMPOUND
        assert "op.targets =" not in OPS_COMPOUND


class TestGuardNestingDepth:
    """Test 5: Nesting guard uses try/finally with compoundDepth."""

    def test_compound_depth_guard(self):
        assert "ctx.compoundDepth" in OPS_COMPOUND

    def test_try_finally_pattern(self):
        """compoundDepth must be reset in a finally block."""
        # Find "ctx.compoundDepth = 1" and verify "finally" comes after
        set_depth = OPS_COMPOUND.index("ctx.compoundDepth = 1")
        assert "finally" in OPS_COMPOUND[set_depth:]
        finally_pos = OPS_COMPOUND.index("finally", set_depth)
        # After finally, compoundDepth must be reset to 0
        after_finally = OPS_COMPOUND[finally_pos:finally_pos + 200]
        assert "ctx.compoundDepth = 0" in after_finally


class TestGuardErrorCodes:
    """Test 6: Compound error codes C006-C009 exist in contracts."""

    @pytest.mark.parametrize("code,name", [
        ("C006", "C_NESTING_NOT_ALLOWED"),
        ("C007", "C_PREV_UNAVAILABLE"),
        ("C008", "C_INVALID_TOKEN_POSITION"),
        ("C009", "C_UNKNOWN_TOKEN"),
    ])
    def test_error_code_in_errors_py(self, code, name):
        assert f'{name} = "{code}"' in ERRORS_PY

    @pytest.mark.parametrize("code", ["C006", "C007", "C008", "C009"])
    def test_error_code_in_contracts_jsx(self, code):
        """Compiled contracts.jsx must also contain the error codes."""
        assert code in CONTRACTS_JSX


class TestGuardCompoundDepthInit:
    """Test 7: ctx.compoundDepth initialized to 0 in ops_core.jsx."""

    def test_ctx_init(self):
        assert "compoundDepth: 0" in OPS_CORE


# ======================== Behavioral Tests (8-11) ========================

class TestGuardManifest:
    """Manifest entry for ops_compound."""

    def test_ops_compound_entry_exists(self):
        assert "ops_compound" in MANIFEST["libraries"]

    def test_deps(self):
        deps = MANIFEST["libraries"]["ops_compound"]["dependencies"]
        assert "ops_core" in deps
        assert "contracts" in deps

    def test_test_soc_includes_ops_compound(self):
        deps = MANIFEST["libraries"]["test_soc"]["dependencies"]
        assert "ops_compound" in deps


class TestCompoundTokenResolution:
    """Test behavioral: token resolution logic in ops_compound.jsx."""

    def test_prev_exact_match_only(self):
        """$prev must be exact — $Prev, $PREV, $prev_ are NOT tokens."""
        assert '"$prev"' in OPS_COMPOUND
        # The function should check exact equality
        assert 'id === "$prev"' in OPS_COMPOUND

    def test_prevall_exact_match_only(self):
        assert 'id === "$prevAll"' in OPS_COMPOUND

    def test_unknown_dollar_token_handled(self):
        """Any $-prefixed string that isn't $prev or $prevAll should error."""
        assert "C_UNKNOWN_TOKEN" in OPS_COMPOUND
        assert 'id.charAt(0) === "$"' in OPS_COMPOUND

    def test_non_id_targets_checked(self):
        """Tokens in non-id target types should produce C003."""
        assert "C_INVALID_TOKEN_POSITION" in OPS_COMPOUND

    def test_type_safe_prevallids(self):
        """prevAllIds extraction normalizes string to array."""
        assert 'typeof rawIds === "string"' in OPS_COMPOUND


class TestCompoundAtomicRollback:
    """Test: atomic compound captures own snapshot and rolls back on failure."""

    def test_own_snapshot_captured(self):
        """Compound handler must capture its own preSnapshot, not reuse outer."""
        assert "compoundSnapshot" in OPS_COMPOUND
        assert "captureSnapshot" in OPS_COMPOUND

    def test_rollback_uses_own_snapshot(self):
        """rollbackBatch must use compoundSnapshot, not a shared preSnapshot."""
        # Find rollbackBatch calls in ops_compound and verify they use compoundSnapshot
        matches = [m.start() for m in re.finditer(r"rollbackBatch\(", OPS_COMPOUND)]
        assert len(matches) >= 1, "No rollbackBatch calls found in ops_compound"
        for m in matches:
            call = OPS_COMPOUND[m:m + 100]
            assert "compoundSnapshot" in call, f"rollbackBatch call should use compoundSnapshot: {call}"
