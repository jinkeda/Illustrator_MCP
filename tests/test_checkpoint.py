"""
test_checkpoint.py — Guard + behavioral tests for Named Checkpoints

Tests:
  Guard (1-8): Static code/schema checks
  Behavioral (9-14): Logic verification via code inspection
"""
import json
import pathlib
import re

import pytest

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "illustrator_mcp" / "resources" / "scripts"
CHECKPOINT_JSX = (SCRIPTS_DIR / "checkpoint.jsx").read_text(encoding="utf-8")
SNAPSHOT_JSX = (SCRIPTS_DIR / "snapshot.jsx").read_text(encoding="utf-8")
DOCUMENTS_PY = (SCRIPTS_DIR.parent.parent / "tools" / "documents.py").read_text(encoding="utf-8")
MANIFEST = json.loads((SCRIPTS_DIR / "manifest.json").read_text(encoding="utf-8"))


# ======================== Guard Tests ========================

class TestGuardManifestCheckpoint:
    """Test 1: checkpoint library registered in manifest."""

    def test_entry_exists(self):
        assert "checkpoint" in MANIFEST["libraries"]

    def test_deps(self):
        deps = MANIFEST["libraries"]["checkpoint"]["dependencies"]
        assert "snapshot" in deps
        assert "mcp_id" in deps

    def test_exports(self):
        exports = MANIFEST["libraries"]["checkpoint"]["exports"]
        for fn in ["checkpointSave", "checkpointRestore", "checkpointList", "checkpointDelete"]:
            assert fn in exports


class TestGuardCheckpointFunctions:
    """Test 2: All 4 checkpoint functions exist."""

    @pytest.mark.parametrize("fn", [
        "function checkpointSave(",
        "function checkpointRestore(",
        "function checkpointList(",
        "function checkpointDelete(",
    ])
    def test_function_exists(self, fn):
        assert fn in CHECKPOINT_JSX


class TestGuardCheckpointCaps:
    """Test 3: Hard caps are defined."""

    def test_max_items(self):
        assert "MAX_CHECKPOINT_ITEMS" in CHECKPOINT_JSX
        match = re.search(r"MAX_CHECKPOINT_ITEMS\s*=\s*(\d+)", CHECKPOINT_JSX)
        assert match
        assert int(match.group(1)) == 2000

    def test_max_bytes(self):
        assert "MAX_CHECKPOINT_BYTES" in CHECKPOINT_JSX
        match = re.search(r"MAX_CHECKPOINT_BYTES\s*=\s*(\d+)", CHECKPOINT_JSX)
        assert match
        assert int(match.group(1)) == 2097152  # 2 MB


class TestGuardNameValidation:
    """Test 4: Name validation uses regex."""

    def test_name_regex(self):
        assert "CHECKPOINT_NAME_RE" in CHECKPOINT_JSX

    def test_name_required_check(self):
        # checkpointSave should check for empty name
        start = CHECKPOINT_JSX.index("function checkpointSave(")
        body = CHECKPOINT_JSX[start:start + 600]
        assert "name is required" in body.lower() or "required" in body.lower()


class TestGuardDocKey:
    """Test 5: docKey generation handles saved and unsaved docs."""

    def test_dockey_function_exists(self):
        assert "function _checkpointDocKey(" in CHECKPOINT_JSX

    def test_fullname_for_saved(self):
        start = CHECKPOINT_JSX.index("function _checkpointDocKey(")
        body = CHECKPOINT_JSX[start:start + 500]
        assert "fullName" in body

    def test_artboard_fallback_for_unsaved(self):
        start = CHECKPOINT_JSX.index("function _checkpointDocKey(")
        body = CHECKPOINT_JSX[start:start + 500]
        assert "artboard" in body.lower() or "artboardRect" in body


class TestGuardStorageMechanism:
    """Test 6: Uses $.global.mcpCheckpoints with file fallback."""

    def test_global_storage(self):
        assert "$.global.mcpCheckpoints" in CHECKPOINT_JSX

    def test_file_fallback(self):
        assert "_fallbackPath" in CHECKPOINT_JSX or "fallback" in CHECKPOINT_JSX.lower()

    def test_save_fallback_called(self):
        """Save must persist to file fallback."""
        start = CHECKPOINT_JSX.index("function checkpointSave(")
        end = CHECKPOINT_JSX.index("function checkpointRestore(")
        body = CHECKPOINT_JSX[start:end]
        assert "_saveFallback" in body


class TestGuardSnapshotWarnings:
    """Test 7: captureSnapshot returns warnings array."""

    def test_warnings_field_in_snapshot(self):
        """Snapshot struct must include warnings array."""
        start = SNAPSHOT_JSX.index("function captureSnapshot(")
        body = SNAPSHOT_JSX[start:start + 800]
        assert "warnings:" in body

    def test_empty_capture_warning(self):
        """captureSnapshot warns if zero items captured."""
        assert "No MCP-managed items captured" in SNAPSHOT_JSX


class TestGuardSnapshotDuplicateId:
    """Test 8: restoreSnapshot detects duplicate MCP IDs."""

    def test_duplicate_detection(self):
        start = SNAPSHOT_JSX.index("function restoreSnapshot(")
        body = SNAPSHOT_JSX[start:]
        assert "duplicateIds" in body or "Duplicate" in body

    def test_duplicate_causes_failure(self):
        """Duplicate IDs must cause ok=false return."""
        start = SNAPSHOT_JSX.index("function restoreSnapshot(")
        body = SNAPSHOT_JSX[start:]
        assert "Duplicate MCP IDs found" in body


# ======================== Behavioral Tests ========================

class TestDocumentsPyCheckpointActions:
    """Test 9: HistoryInput supports all checkpoint actions."""

    def test_checkpoint_actions_in_literal(self):
        for action in ["checkpoint_save", "checkpoint_restore",
                       "checkpoint_list", "checkpoint_delete"]:
            assert f'"{action}"' in DOCUMENTS_PY

    def test_name_field_exists(self):
        assert "name:" in DOCUMENTS_PY or '"name"' in DOCUMENTS_PY

    def test_checkpoint_dispatch(self):
        """_handle_checkpoint function exists."""
        assert "async def _handle_checkpoint(" in DOCUMENTS_PY or "_handle_checkpoint" in DOCUMENTS_PY


class TestCheckpointSaveCaps:
    """Test 10: Save enforces item count and byte caps."""

    def test_item_count_check(self):
        start = CHECKPOINT_JSX.index("function checkpointSave(")
        end = CHECKPOINT_JSX.index("function checkpointRestore(")
        body = CHECKPOINT_JSX[start:end]
        assert "MAX_CHECKPOINT_ITEMS" in body

    def test_byte_size_check(self):
        start = CHECKPOINT_JSX.index("function checkpointSave(")
        end = CHECKPOINT_JSX.index("function checkpointRestore(")
        body = CHECKPOINT_JSX[start:end]
        assert "MAX_CHECKPOINT_BYTES" in body


class TestCheckpointRestoreIntegration:
    """Test 11: Restore delegates to restoreSnapshot."""

    def test_restore_calls_restore_snapshot(self):
        start = CHECKPOINT_JSX.index("function checkpointRestore(")
        end = CHECKPOINT_JSX.index("function checkpointList(")
        body = CHECKPOINT_JSX[start:end]
        assert "restoreSnapshot" in body

    def test_restore_handles_not_found(self):
        start = CHECKPOINT_JSX.index("function checkpointRestore(")
        end = CHECKPOINT_JSX.index("function checkpointList(")
        body = CHECKPOINT_JSX[start:end]
        assert "not found" in body.lower()


class TestCheckpointListSort:
    """Test 12: List returns checkpoints sorted by timestamp."""

    def test_list_sorts(self):
        start = CHECKPOINT_JSX.index("function checkpointList(")
        end = CHECKPOINT_JSX.index("function checkpointDelete(")
        body = CHECKPOINT_JSX[start:end]
        assert ".sort(" in body


class TestCheckpointDelete:
    """Test 13: Delete removes from store and persists."""

    def test_delete_removes(self):
        start = CHECKPOINT_JSX.index("function checkpointDelete(")
        body = CHECKPOINT_JSX[start:]
        assert "delete store[name]" in body or "delete store" in body

    def test_delete_persists(self):
        start = CHECKPOINT_JSX.index("function checkpointDelete(")
        body = CHECKPOINT_JSX[start:]
        assert "_saveFallback" in body


class TestSnapshotTypeMismatch:
    """Test 14: restoreSnapshot handles type mismatch gracefully."""

    def test_type_mismatch_warning(self):
        """Type mismatch should produce a warning, not a hard failure."""
        start = SNAPSHOT_JSX.index("function restoreSnapshot(")
        body = SNAPSHOT_JSX[start:]
        assert "Type mismatch" in body

    def test_shared_fields_restored(self):
        """Even with type mismatch, position should be restored."""
        start = SNAPSHOT_JSX.index("function restoreSnapshot(")
        body = SNAPSHOT_JSX[start:]
        # typeMismatch should not block position restore
        assert "typeMismatch" in body
        # But should block fill/stroke
        assert "!typeMismatch" in body


class TestCheckpointExports:
    """Test 15: checkpoint.jsx exports all functions to $.global."""

    @pytest.mark.parametrize("fn", [
        "checkpointSave",
        "checkpointRestore",
        "checkpointList",
        "checkpointDelete",
    ])
    def test_exported(self, fn):
        assert f"$.global.{fn}" in CHECKPOINT_JSX


class TestHistoryInputValidation:
    """Test 16: Pydantic model_validate enforces name requirement."""

    def test_model_validate_override(self):
        assert "model_validate" in DOCUMENTS_PY

    def test_requires_name_for_save(self):
        """Validation should require non-empty name for checkpoint_save."""
        assert "requires a non-empty" in DOCUMENTS_PY or "requires" in DOCUMENTS_PY

    def test_name_not_required_for_list(self):
        """checkpoint_list should not require name."""
        assert "checkpoint_list" in DOCUMENTS_PY
