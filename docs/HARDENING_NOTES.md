# Hardening Notes — Generative → SOC Bridge Debug Session

Bugs, gaps, and observations found during verification on 2026-02-10.

---

## 🐛 Bugs Fixed

### 1. `element_create` param names wrong in `flow_field.jsx`
- **Symptom**: `S003 Type error in script`
- **Root cause**: Script used `w`/`h` but the handler reads `params.width`/`params.height` (L29-30 of `ops_element.jsx`)
- **Fix**: Changed to `width`/`height` in both the background rect and border rect ops
- **Risk**: Any other generator using shorthand `w`/`h` will silently get 100×100 default size

### 2. Missing library dependencies
- **Symptom**: `makeError is not a function` (line 80 of `ops_core.jsx`)
- **Root cause**: `ops_core.jsx` declares `@requires task_executor` but nothing enforces load order when using `File.eval()`. The manifest declares deps correctly but the `includes` mechanism failed (see #4).
- **Fix**: Added `task_executor.jsx` and `ops_layer.jsx` to the manual load chain
- **Lesson**: The `@requires` JSDoc comments are the ONLY documentation of dependencies — there's no runtime guard

---

## 🔴 `includes` Mechanism Failure

### 3. `includes: ["geo_ir"]` returns `Unknown library: geo_ir`
- **Symptom**: `ValueError: Unknown library: geo_ir` from `libraries.py:136`
- **Observed**: `geo_ir` IS in `manifest.json` at line 276 under `libraries.geo_ir`
- **Hypothesis A**: Stale `_manifest_cache` — the singleton `LibraryResolver` is created once at import time. If the manifest was loaded before `geo_ir` was added, the cache stamp check (`st_mtime_ns, st_size`) should catch it... but OneDrive file sync can mess with timestamps.
- **Hypothesis B**: JSON parse error silently falls back to empty `{"libraries": {}}` (L81)
- **To investigate**: Add logging in `_load_manifest()` to print actual keys loaded. Check if `_manifest_stamp` comparison uses correct precision on Windows/OneDrive.

---

## ⚡ Performance / Timeout Issues

### 4. 30s CEP bridge timeout is a hard cap
- **Symptom**: Scripts that should take 40-60s always die at exactly 30011ms
- **Root cause**: The `timeout` parameter in `execute_script` doesn't override the CEP panel's internal timeout. The Python-side timeout (`elapsed_ms`) caps at ~30s regardless of what you pass.
- **Impact**: Any generative script producing >~150 curves (with library eval overhead) will fail
- **Solutions**:
  - **Short-term**: Split into two calls — Phase A (libraries + IR computation) stores result in `$.global`, Phase B (SOC batch) reads from `$.global`
  - **Medium-term**: Increase CEP panel timeout in `main.js` or `manifest.xml`
  - **Long-term**: Pre-load libraries persistently via `$.global` so each call doesn't re-eval

### 5. Library eval overhead (~2s for 7 files)
- **Observed**: Loading 7 .jsx files via `File.eval()` takes ~2s of the 30s budget
- **Root cause**: Each `eval()` parses and compiles the entire file. `ops_core.jsx` alone is ~800 lines with complex logic.
- **Mitigation**: Libraries could be loaded once into `$.global` and checked with a version stamp

### 6. Chaikin smoothing + many curves = exponential time
- **Observed**: 2 iterations of `chaikinSmooth` on ~500 curves (each ~50 pts → ~200 pts after smoothing) takes significant time
- **Root cause**: Each Chaikin iteration roughly doubles point count. 50 pts × 2 iters = ~200 pts × 500 curves = 100,000 points to create as path items
- **Recommendation**: Cap `SMOOTH_ITERS` at 1 for >200 curves, or decimate after smoothing

---

## 🏗️ Architectural Observations

### 7. `element_create` doesn't return `createdIds` in summaryOnly mode
- **Observed**: `createdIds` from the batch only contained ONE id (from `element_create` for the rect), not the IDs from `element_create_multi`
- **Root cause**: `element_create_multi` returns IDs in `result.data.ids[]` but `executeOpBatch` only pushes `opResult.id` (singular) to `createdIds[]`, not the array from multi-create
- **Impact**: In `summaryOnly` mode, you lose track of individual curve IDs — only the first/parent ID is captured
- **Fix needed**: `executeOpBatch` should check for `opResult.data.ids` array and concat to `createdIds`

### 8. No runtime dependency guard in JSX
- `ops_core.jsx` calls `makeError()` at line 80 (inside `validateOp`). If `task_executor.jsx` isn't loaded, this throws a generic `TypeError` with no useful message.
- **Suggestion**: Add a guard at top of `ops_core.jsx`:
  ```javascript
  if (typeof makeError !== "function") throw new Error("ops_core requires task_executor.jsx to be loaded first");
  ```

### 9. `addLabel` PARM error with large documents
- **Observed**: PARM error `1346458189` occurred after creating ~500 path items, when trying to create text frames
- **Root cause**: Known Illustrator bug — `textFrames.add()` throws PARM when document has many `pathItems`. The `addLabel` function already works around this by using `pointText()`, but even `pointText()` can fail in very large documents.
- **Mitigation**: Wrap Phase C in try/catch in the generator, make labels optional

### 10. Journal recording skipped in `summaryOnly` mode
- **Observed**: Looking at `executeOpBatch` code — journal recording (P6 section) only runs in the NON-summaryOnly branch (after the `if (summaryOnly) { return ... }` early return at ~line 750)
- **Impact**: When `summaryOnly: true` is used (which generators should use per conventions), journal entries are never written
- **Fix needed**: Move journal recording BEFORE the summaryOnly early return
