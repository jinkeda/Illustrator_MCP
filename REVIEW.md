# Code Review: Illustrator_MCP

## Architecture Summary

This is a Model Context Protocol (MCP) server that bridges AI assistants with Adobe Illustrator via a "Scripting First" architecture. A single Python process integrates the MCP server (stdio transport) and a WebSocket bridge (port 8081) connecting to a CEP panel running inside Illustrator.

**Data flow:** Claude → MCP (stdio) → Python tools → WebSocket bridge → CEP panel (JS) → ExtendScript eval() → Illustrator DOM → response back up the chain.

The architecture is well-designed: dual-thread model (MCP + WebSocket), facade pattern for the bridge, library injection with dependency resolution, and clean tool abstractions.

---

## BUGS & ERRORS

### 1. `started_event` type mismatch
**Files:** `websocket_bridge.py:88`, `bridge/server.py:28`

`WebSocketBridge._thread_main()` passes `self._started` (a `threading.Event`) to `server.run(started_event)`, but `server.run()` type-hints the parameter as `Optional[asyncio.Event]`. Works at runtime because both have `.set()`, but the type annotation is wrong and misleading.

### 2. `ConnectionState` set to `CONNECTED` before CEP panel connects
**File:** `websocket_bridge.py:116`

After `start()`, state is set to `CONNECTED` when the WebSocket *server* starts listening — not when the CEP panel actually connects. `is_connected()` delegates to `server.is_connected()` which checks the actual client, so it's partially masked, but `self.state` is semantically incorrect.

### 3. Race condition in double-check locking
**File:** `runtime.py:27-28`

The first check `if self.bridge:` is done without the lock. Safe on CPython due to GIL, but technically a data race in the general Python memory model. Could break with alternative implementations.

### 4. `_unwrap_result` infinite recursion potential
**File:** `proxy_client.py:228-251`

Malformed response with deeply nested `{success: true, result: {success: true, result: ...}}` will recurse until stack overflow. No depth guard.

### 5. Server error misreported as success
**Files:** `bridge/server.py:61-73`, `websocket_bridge.py:111-116`

When server encounters `OSError` (port in use), `started_event.set()` is called before re-raising. `WebSocketBridge.start()` sees event set → sets state to `CONNECTED`. The bridge reports as running even though the server thread is dying.

### 6. `request_id` type mismatch risk
**Files:** `request_registry.py:30`, `websocket_bridge.py:67`

Registry uses `int` IDs. JSON round-trip could return string (`"1"`) vs int (`1`) depending on client implementation. Lookup would fail silently.

### 7. `OPEN_DOCUMENT` template lacks try/catch
**File:** `templates.py:46-55`

Unlike `CREATE_DOCUMENT`, `OPEN_DOCUMENT` doesn't wrap `app.open()` in try/catch. Errors from corrupted files propagate as unstructured ExtendScript errors.

---

## REDUNDANCIES & DEAD CODE

### 8. `errors.py` is entirely unused
`IllustratorError` enum is never imported. Error codes are hardcoded as strings elsewhere.

### 9. `response_models.py` is entirely unused
`OperationResult`, `DocumentInfo`, `ExportResult`, `PlaceItemResult` etc. are never imported by any tool.

### 10. `render_template()` in `templates.py:391` is unused
Defined but never called. Templates use `.substitute()` directly.

### 11. `validate_file_path()` and `escape_string_for_jsx()` in `utils.py` are unused
Only `escape_path_for_jsx()` is imported anywhere.

### 12. `assets.jsx` and `presets.jsx` missing from `manifest.json`
Files exist on disk but aren't declared in the manifest. Can only be resolved via fallback `_simple_resolve()`.

### 13. `ItemRefLegacy` in `protocol.py:216` is unused
Defined with deprecation note but never referenced.

### 14. `illustrator_embed_placed_items` — decorator commented out, body remains
**File:** `documents.py:393-409`

Dead function with commented-out decorator. Should be removed or clearly disabled.

### 15. Duplicate `get_bridge()` accessor functions
- `websocket_bridge.py:213` → `get_bridge()`
- `proxy_client.py:44` → `_get_bridge()`
- `runtime.py:56` → `get_runtime().get_bridge()`

All do the same thing.

### 16. Test mocks target wrong function
**File:** `conftest.py`

Fixtures mock `execute_script` but tools call `execute_script_with_context` (via `execute_jsx_tool`). Mocks may not intercept correctly.

---

## SECURITY CONCERNS

### 17. Potential ExtendScript injection
**Files:** `host.jsx:47`, `cep-extension/js/main.js:207`

Script escaping in `main.js` handles `\`, `'`, `\n`, `\r` but may miss edge cases (`\0`, template literals). The `description` field reaches CEP panel unvalidated.

### 18. `validate_file_path()` exists but is never called
Designed to prevent directory traversal but unused. File paths go directly to `escape_path_for_jsx()` without validation.

---

## DESIGN ISSUES

### 19. `config` variable shadow
**File:** `documents.py:236`

Local `config = export_configs[params.format]` shadows module-level `config` import.

### 20. Version string inconsistencies
- `__version__.py`: `"2.3.6"`
- `protocol.py` TaskPayload default: `"2.3.1"`
- `manifest.json` task_executor: `"2.3.1"`
- README claims v2.6.0

### 21. Stale comments
`tools/__init__.py` references "Task Protocol v2.1" but actual is v2.3.

### 22. No pending request cleanup on disconnect
When CEP panel disconnects mid-request, pending futures hang until timeout. `_handle_client` sets `self.client = None` but doesn't notify registry.

### 23. Single-client assumption
`bridge/server.py` replaces previous client on new connection. Multiple Illustrator instances can't connect simultaneously.

### 24. Library cache never invalidates
`LibraryResolver._file_cache` caches forever. JSX file changes require server restart.

---

## Suggested Priority Fixes

| Priority | Issue | Effort |
|----------|-------|--------|
| **P0** | #5 Server error misreported as success | Small |
| **P0** | #4 Add depth limit to `_unwrap_result` | Small |
| **P1** | #8-14 Remove dead code (errors.py, response_models.py, etc.) | Medium |
| **P1** | #12 Add assets/presets to manifest.json | Small |
| **P1** | #2 Fix ConnectionState semantics | Small |
| **P1** | #18 Use or remove validate_file_path() | Small |
| **P2** | #22 Fail pending requests on disconnect | Medium |
| **P2** | #20 Synchronize version strings | Small |
| **P2** | #16 Fix test mocks to match call path | Medium |
| **P3** | #15 Consolidate get_bridge() accessors | Small |
| **P3** | #24 Add library cache invalidation for dev | Medium |
