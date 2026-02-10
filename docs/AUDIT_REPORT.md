# Illustrator MCP -- Full Audit Report

**Date:** 2026-02-10
**Scope:** Complete codebase review -- Python server, ExtendScript libraries, CEP extension, tests, configuration
**Version audited:** 2.3.6 (`__version__.py`)

---

## Executive Summary

The project is architecturally sound but has accumulated significant technical debt across rapid feature development. The audit found **6 critical bugs**, **14 high-severity issues**, and **20+ medium/low concerns** spanning code correctness, test quality, dead code, and documentation drift.

The most impactful finding is a **dual ID-format bug** where `task_executor.jsx` writes IDs in one format (`mcp-id:xxx`) while the entire SOC framework reads them in another (`@mcp:id=xxx`). This silently breaks all ID-based targeting between the two systems.

---

## Table of Contents

1. [Critical Bugs](#1-critical-bugs)
2. [High-Severity Issues](#2-high-severity-issues)
3. [Medium Issues](#3-medium-issues)
4. [Low / Cleanup Items](#4-low--cleanup-items)
5. [Test Suite Quality](#5-test-suite-quality)
6. [Dead Code & Redundancy](#6-dead-code--redundancy)
7. [Documentation Drift](#7-documentation-drift-fixed)
8. [Recommendations for Next Version](#8-recommendations-for-next-version)

---

## 1. Critical Bugs

### BUG-001: Dual ID Format -- Task Protocol vs SOC Framework

**Severity:** CRITICAL
**Impact:** All ID-based cross-system targeting silently fails
**Files:** `task_executor.jsx`, `ops_core.jsx`, `ops_element.jsx`, `ops_group.jsx`, `ops_text.jsx`, `snapshot.jsx`

Two incompatible ID formats are used:

| System | Format | Write | Read |
|---|---|---|---|
| Task Protocol (`task_executor.jsx`) | `mcp-id:xxx` | `assignItemId()`, `assignItemIdV2()` | `describeItem()`, `describeItemV2()` |
| SOC Framework (`ops_core.jsx` et al.) | `@mcp:id=xxx` | `ops_element`, `ops_group`, `ops_text` | `buildIDIndex()`, `resolveById()`, `snapshot` |

**Consequence:** Items created or tagged via the Task Protocol (`executeTask`) will not be found by SOC batch operations (`executeOpBatch`), and vice versa. Any workflow that crosses the boundary (e.g., query items with Task Protocol, then modify with SOC) will silently miss all items.

**Fix:** Standardize on `@mcp:id=xxx` everywhere. Update `task_executor.jsx` lines 270, 305, 308, 366-367, 413-414, 437, 440.

---

### BUG-002: Three ExtendScript Libraries Referenced but Missing

**Severity:** CRITICAL
**Impact:** Runtime crashes for generative, geometry-IR, and multi-call workflows
**Files:** `ops_element.jsx`, manifest.json, README

The following libraries are referenced in code but do not exist on disk:

| Library | Referenced by | Functions called |
|---|---|---|
| `geo_ir.jsx` | `ops_element.jsx` (lines 139, 148, 189, 495) | `isIR()`, `irValidate()`, `irMapPoints()`, `irPointCount()` |
| `generative.jsx` | README, old changelog | `seededRandom()`, `fBm()`, `marching()` |
| `session.jsx` | `ops_element.jsx` (line 534) | `stashGet()`, `stashKeys()`, `stashPutIR()` |

None of these are in the `manifest.json` either.

**Consequence:** Any call to `element_create` with Geometry IR, `element_create_multi_by_ref` (stash), or generative library includes will crash with "function is not defined".

**Fix:** Either create these libraries or remove/guard the references. The `element_create` path handler should have a check like `if (typeof isIR === "function")` before calling.

---

### BUG-003: Request Registry Race Condition on Completion

**Severity:** CRITICAL
**Impact:** Potential double-completion or exception on futures
**File:** `bridge/request_registry.py`, lines 203-216

```python
def complete_request(self, request_id: int, result: Any) -> bool:
    with self._lock:
        pending = self._pending.pop(request_id, None)  # Remove under lock
    # ---- lock released ----
    if pending and not pending.future.done():
        pending.future.set_result(result)  # Set OUTSIDE lock
```

Between releasing the lock and calling `set_result()`, another thread could call `fail_request()` with the same request ID. Since the request was already popped, `fail_request` would return False, but if it somehow held a stale reference, both threads could race on `future.set_result()` / `future.set_exception()`.

The same pattern exists in `fail_request()` (lines 218-231).

**Fix:** Move `set_result()` inside the lock, or use `loop.call_soon_threadsafe()`.

---

### BUG-004: `execute_op_batch_chunked` Variable Shadowing

**Severity:** CRITICAL
**Impact:** Chunking uses wrong timeout, may hang
**File:** `proxy_client.py`, line 295

```python
async def execute_op_batch_chunked(
    ops: List[Dict[str, Any]],
    options: Optional[Dict[str, Any]] = None,
    config: Optional[ChunkConfig] = None,  # param named "config"
    timeout: Optional[float] = None
) -> ExecutionResponse:
    config = config or ChunkConfig()  # Now shadows the module-level config import
    timeout = timeout or config.timeout if hasattr(config, 'timeout') else 60.0
```

The parameter `config` shadows the module-level `from illustrator_mcp.config import config`. After `config = config or ChunkConfig()`, the rest of the function sees `ChunkConfig` where it might expect the global `Config`. The expression `config.timeout` is ambiguous -- `ChunkConfig` doesn't have a `timeout` attribute, so `hasattr` returns False, and it falls back to 60.0 regardless of the user's configured timeout.

**Fix:** Rename the parameter to `chunk_config`.

---

### BUG-005: `ConnectionState.CONNECTED` Set Prematurely

**Severity:** HIGH (borderline CRITICAL)
**Impact:** Tools may attempt execution before WebSocket is actually listening
**File:** `websocket_bridge.py`, lines 123-129

```python
if not self._started.wait(timeout=BRIDGE_STARTUP_TIMEOUT):
    self.state = ConnectionState.ERROR
else:
    self.state = ConnectionState.CONNECTED  # Set to CONNECTED...
```

The `_started` event is set when the server `run()` coroutine begins (line 46-47 of `server.py`), not when a CEP client actually connects. So `ConnectionState.CONNECTED` is set even though no Illustrator instance has connected yet.

**Fix:** Use a more accurate name like `ConnectionState.LISTENING`, or only set `CONNECTED` on first client connection.

---

### BUG-006: `eval()` for JSON Parsing in host.jsx

**Severity:** HIGH
**Impact:** Any malformed WebSocket message triggers arbitrary code execution in ExtendScript
**File:** `cep-extension/jsx/host.jsx`

The JSON polyfill uses `eval('(' + str + ')')` for parsing. Since all scripts from the MCP server are already executed via `eval()`, the practical security impact is limited (the attacker already has code execution). However, malformed JSON in error messages or unexpected inputs could cause confusing eval failures instead of parse errors.

**Fix:** Replace with a safer JSON parser (e.g., Crockford's json2.js) or add input sanitization.

---

## 2. High-Severity Issues

### ISSUE-001: `findLayer()` Cross-Module Dependency Without Load Guard

**File:** `ops_element.jsx`, line 327
`findLayer()` is defined in `task_executor.jsx` but called from `ops_element.jsx`. If `ops_element` is loaded without `task_executor`, it crashes.

**Fix:** Add `if (typeof findLayer !== "function")` guard, or inline the function.

### ISSUE-002: Falsy Check Bug in Text Frame Creation

**File:** `ops_element.jsx`, line 106
`if (width && height && ...)` evaluates to false when `width=0` or `height=0`, which are valid dimensions for some layouts. This causes incorrect text frame type selection (point text instead of area text).

**Fix:** Use `!== undefined` checks instead of truthiness.

### ISSUE-003: WebSocket `send()` Has No Connection State Check

**File:** `bridge/server.py`, line 112-116
`send()` checks `if not self.client` but not `self.is_connected()`. If the client reference exists but the socket is closed, `await self.client.send(message)` raises `ConnectionClosed`.

**Fix:** Check `self.is_connected()` before sending.

### ISSUE-004: `is_connected()` Fallback Returns True

**File:** `bridge/server.py`, line 133
If the websocket object has neither `open` nor `closed` attributes, the function returns `True` (assumes connected). This is dangerous for unknown websocket library versions.

**Fix:** Return `False` as the safe default.

### ISSUE-005: `.env.example` Has Deprecated Fields

**File:** `.env.example`
Still contains `HTTP_PORT=8080` and `PROXY_HOST=localhost`, which are unused since the Node.js proxy was removed. Users copying this will have dead config.

**Fix:** Remove deprecated fields, add comments explaining current settings.

### ISSUE-006: `tools/__init__.py` Docstring Says "v2.1"

**File:** `illustrator_mcp/tools/__init__.py`, line 14
Docstring says "Task Protocol tools (v2.1)" but the actual protocol version is v2.3.

**Fix:** Update to "v2.3".

### ISSUE-007: Silent Error Suppression in SOC Handlers

**Files:** `ops_text.jsx` (line 68), `ops_group.jsx` (line 39), `ops_style.jsx` (line 113)
Multiple try/catch blocks silently swallow errors (e.g., font not found, item locked). These failures produce no warnings in the batch report.

**Fix:** Collect warnings via `ctx.warn()` instead of empty catch blocks.

### ISSUE-008: `cep-extension-legacy/` Is Dead Code in the Repo

**File:** `cep-extension-legacy/`
The CSXS manifest is in `CSXS_DISABLED/`, the code is superseded by the React extension, and nothing references it. It shares the same bundle ID (`com.illustrator.mcp`) with the current extension, which could cause conflicts if both are installed.

**Fix:** Delete entirely or move to a separate branch.

### ISSUE-009: Hardcoded WebSocket URL in CEP Extension

**File:** `cep-extension/src/hooks/useMCP.ts`, `MCPControlPanel.tsx`
The URL `ws://127.0.0.1:8081` is hardcoded. Port cannot be changed without modifying source.

**Fix:** Read port from CEP environment or a config file.

### ISSUE-010: `health_check` in `check_connection_or_error` Calls Synchronous `bridge.execute`

**File:** `shared.py`, lines 129-145
`check_connection_or_error` calls `bridge.execute()` which doesn't exist on `WebSocketBridge` (the method is `execute_script_async`). This code path with `health_check=True` would raise `AttributeError`.

Currently masked because `proxy_client.py` always passes `health_check=False`.

**Fix:** Either implement `bridge.execute()` or remove the health-check code path.

### ISSUE-011: Stale Connection Cleanup Race in WebSocket Server

**File:** `bridge/server.py`, lines 75-96
Between checking `self.client is not None and self.is_connected()` (line 78) and the cleanup at line 90-96, another connection could arrive. The cleanup then closes the new connection instead of the stale one.

**Fix:** Use a lock or make the entire acceptance atomic.

### ISSUE-012: Inconsistent Error Return Formats in SOC Handlers

**Files:** Various `ops_*.jsx`
Some handlers return `{ ok: false, error: makeError(...) }` while others return `makeError(...)` directly. This inconsistency makes error aggregation in `ops_core.jsx` fragile.

**Fix:** Standardize all handlers to return `{ ok: false, error: {...} }`.

### ISSUE-013: `__version__` vs README Version

**File:** `__version__.py` says `2.3.6`, but the old README title was "v3.0" and the changelog had a v3.0.0 entry. The pyproject.toml reads version dynamically from `__version__.py`, so the published package version is 2.3.6.

**Fix:** Either bump `__version__` to match the changelog entries, or retroactively note the version discrepancy.

### ISSUE-014: `proxy-server/` Referenced in Old README but Directory Doesn't Exist

**File:** Old README project structure (now fixed in rewrite)
The old README listed `proxy-server/` but the directory was already deleted.

**Status:** Fixed in README rewrite.

---

## 3. Medium Issues

### MED-001: `classify_error` Regex Creates Unused Variable
`errors.py`, line 280: `error_lower = error_message.lower()` is computed but never used; the regex uses `re.IGNORECASE` instead.

### MED-002: Y-Axis Documentation Contradictions in `geometry.jsx`
Lines 5-10 say "Y positive down" (screen coords) while lines 271-287 say "Y is positive UP" (PostScript). The code is correct but comments are contradictory.

### MED-003: `format_response()` Uses Emoji
`proxy_client.py`, line 416: Connection errors are prefixed with the emoji. May render poorly in non-Unicode terminals.

### MED-004: `convertToPlainObject` Silently Truncates Arrays
`cep-extension/jsx/host.jsx`: Arrays over 100 items are truncated without any indication to the caller.

### MED-005: Inefficient Regex Loop in Tag Parsing
`task_executor.jsx`, lines 331-334: Uses string replacement inside a while loop instead of `regex.exec()` with global flag.

### MED-006: JSON.stringify as Cache Key
`ops_core.jsx`, line 270: `JSON.stringify(targets)` for caching is non-deterministic (property order) and can crash on circular references.

### MED-007: Library Resolver File Cache Holds Content in Memory
`libraries.py`: All library file contents are cached forever in `_file_cache`. With 18+ libraries, this is a few hundred KB -- acceptable but unbounded.

### MED-008: Snapshot Restore Does Not Restore Size
`snapshot.jsx`, lines 247-251: Size restoration is commented out with no explanation. Position and style are restored but dimensions are not.

### MED-009: `useEffect` Dependency Loop in CEP Extension
`useMCP.ts`: `connect` and `disconnect` are in the `useEffect` dependency array but are recreated on each render, potentially causing reconnection loops.

### MED-010: Request Log Opens/Closes File Per Request
`logging/request_log.py`: Each log call opens and closes the file handle. High-frequency logging will thrash the filesystem.

---

## 4. Low / Cleanup Items

- **LOW-001:** Empty `exports` arrays in manifest.json for all `ops_*` modules (correct but confusing).
- **LOW-002:** `demo_server.py` in project root -- purpose unclear, may be orphaned.
- **LOW-003:** `living test/` directory has a space in the name, which is unusual and may cause scripting issues.
- **LOW-004:** `REVIEW_SOC_IMPROVEMENTS.md` exists both at root and in `docs/` -- redundant.
- **LOW-005:** `proxy-server/` is gone but `pyproject.toml` still has `hatch` build target alongside `setuptools`.
- **LOW-006:** `uxp-plugin/` directory contains only `icons/README.md` -- could be a `.gitkeep` instead.

---

## 5. Test Suite Quality

### Overall Assessment: **Moderate -- gives false confidence**

| Metric | Value |
|---|---|
| Test files | 11 |
| Approximate test count | ~60 |
| Tests that validate output | ~30% |
| Tests that only check mocks | ~50% |
| Tests that skip silently | ~20% |

### Key Problems

1. **False-positive tests:** ~15 tests verify mocks were called but never check the actual return value. Example: `test_context.py::test_returns_document_info` calls the function but only asserts the mock was called, not the result.

2. **Silent skips masking failures:** `test_library_resolver.py` has 5+ tests that `pytest.skip("No manifest.json found")` when the manifest isn't in the expected path. In CI, these show as "skipped" (green), not "failed".

3. **No error-path tests for documents:** `test_documents.py` tests happy paths only. No tests for export failures, permission errors, or missing files.

4. **No concurrency tests:** The `RequestRegistry` has a threading lock, but no tests exercise concurrent completion/failure.

5. **Archived module references:** `conftest.py` is clean, but old test files for archived modules (`test_shapes.py`, etc.) were previously deleted -- good.

6. **No integration tests runnable without Illustrator:** All live tests require a running Illustrator instance. No mock-based integration tests exist.

### Missing Coverage

- `execute_op_batch_chunked()` -- zero tests
- `execute_script_streaming()` -- zero tests
- Error envelope formatting with actual CEP error structures
- `check_connection_or_error()` with `health_check=True`
- `WebSocketBridge.stop()` cleanup verification
- Concurrent `create_request` / `complete_request` calls

---

## 6. Dead Code & Redundancy

| Item | Location | Status |
|---|---|---|
| `cep-extension-legacy/` | Root | Dead code. CSXS manifest disabled. Same bundle ID as current extension. |
| `tools/archive/` | 15+ archived Python files | Dead code. Kept for reference. OK. |
| `tools/templates.py` | `tools/` | Contains helper functions. Separate from `illustrator_mcp/templates.py` which has the actual templates. Naming is confusing. |
| `proxy-server/` reference | Old README | Directory already deleted. Reference removed in README rewrite. |
| `IllustratorProxy` class | `proxy_client.py` | Thin wrapper around `_execute_via_bridge`. Only used via `get_proxy()` in `execute_script()`. Could be inlined. |
| `format_response()` | `proxy_client.py` | Older response formatter. Superseded by `format_envelope()` but still imported by `base.py`. |
| `mcp_dispatch()` | `cep-extension/jsx/host.jsx` | Called via `useMCP.ts::mcpDispatch()` (L77-84) which is exported for UI actions. Not dead code -- it's a separate dispatch channel from the main `mcp_handle_request()` message path. Only handles `ping` and `execute_script` commands currently. |
| `create_selection_check()` | `tools/templates.py` | Only used if archived tools were re-enabled. |
| `wrap_script_no_document_check()` | `tools/templates.py` | Not called anywhere in active code. |
| `REVIEW_SOC_IMPROVEMENTS.md` | Root + `docs/` | Duplicate file. |

---

## 7. Documentation Drift (Fixed)

The README was rewritten in this session. Issues that were fixed:

- Version: "v3.0" -> removed (actual version is 2.3.6)
- Tool count: "~14" -> 20 (actual count from source)
- Tool names: `illustrator_history` -> `illustrator_undo` / `illustrator_redo`
- Broken links: `example/`, `proxy-server/`, `.agent/skills/` -> removed
- Project structure: Updated to match actual files on disk
- Development section: Removed references to archived modules
- Changelog: 600+ lines moved out of README

---

## 8. Recommendations for Next Version

### Priority 1 -- Must Fix (blocks correctness)

1. **Unify ID format** to `@mcp:id=xxx` across task_executor.jsx and all SOC modules. This is the single highest-impact fix.

2. **Create or stub missing libraries** (`geo_ir.jsx`, `generative.jsx`, `session.jsx`). Either implement them or add runtime guards (`typeof isIR === "function"`) in `ops_element.jsx`.

3. **Fix `execute_op_batch_chunked` variable shadowing** -- rename the `config` parameter to `chunk_config`.

4. **Move `set_result()` inside the lock** in `request_registry.py::complete_request()` and `fail_request()`.

### Priority 2 -- Should Fix (improves reliability)

5. **Clean up `.env.example`** -- remove `HTTP_PORT` and `PROXY_HOST`.

6. **Delete `cep-extension-legacy/`** -- it's dead code with a conflicting bundle ID.

7. **Add `is_connected()` check to `server.py::send()`** -- prevent sending on closed sockets.

8. **Fix `is_connected()` fallback** -- return `False` instead of `True` when socket attributes are unknown.

9. **Remove or fix `check_connection_or_error` health check** -- the `bridge.execute()` call doesn't exist.

10. **Make WebSocket URL configurable** in the CEP extension.

### Priority 3 -- Should Improve (developer experience)

11. **Improve test quality:**
    - Add assertions on return values, not just mock calls
    - Replace `pytest.skip()` with proper fixtures that ensure manifest.json exists
    - Add error-path tests for document tools
    - Add at least one concurrency test for `RequestRegistry`

12. **Standardize SOC handler error returns** -- all handlers should return `{ ok: false, error: {...} }`.

13. **Add warnings to silent catch blocks** in `ops_text.jsx`, `ops_group.jsx`, `ops_style.jsx`.

14. **Bump `__version__`** to match the actual feature set (the changelog has entries through v3.0 but version is 2.3.6).

15. **Create CHANGELOG.md** -- the 600 lines of changelog removed from README should live somewhere.

### Priority 4 -- Nice to Have (future quality)

16. **Consolidate `templates.py` naming** -- `tools/templates.py` and `illustrator_mcp/templates.py` are confusingly named. Consider renaming `tools/templates.py` to `tools/script_helpers.py`.

17. **Add a JSON parsing guard to `host.jsx`** -- replace `eval()` with Crockford's json2.js.

18. **Implement log rotation** in `request_log.py`.

19. **Add pre-commit hooks** for linting and type checking.

20. **Document the Y-axis convention** in a single authoritative location that geometry.jsx references.

---

*End of audit report.*
