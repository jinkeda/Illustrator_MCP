# Code Review Report: MCP Improvements (Sessions 1 & 2)

## Overall Assessment: **Solid foundation, some issues to address**

The changes add meaningful infrastructure — request logging, chunking, snapshot/restore, streaming, schema codegen, and `assert_style`. The code is well-structured and follows existing patterns. Below are findings by file/feature.

---

## 1. `ops_core.jsx` — summaryOnly + Global ID Index

**What's good:**
- `summaryOnly` is a smart optimization — skipping per-op detail payloads will significantly reduce token/response size for large batches
- Global ID index at `$.global.mcpIdIndex` with auto-invalidation on document name change is the right approach for O(1) lookups
- `invalidateIdIndex()` and `registerIdInIndex()` are clean helpers for keeping the cache coherent
- Snapshot-based rollback cleanly integrated alongside the existing undo-based fallback

**Issues:**

| Severity | Issue |
|----------|-------|
| **Medium** | **ID index invalidation is too coarse.** It only checks `doc.name` — if you add/delete elements within the same document, the index goes stale. `registerIdInIndex` helps for *creates*, but `element_delete` ops should call `invalidateIdIndex()` or remove the entry. Currently there's no code path that does this in ops_core itself. |
| **Low** | `summaryOnly` still filters and maps the full `results` array for errors (line 550). For truly large batches (500+ ops, all passing), this is fine, but the full `results` array is still built in memory even when unused. |
| **Low** | `maxDepth = 100` in `buildIDIndex` scan (line 193) — fine for safety, but if someone nests 100+ groups, elements past that depth silently become unreachable. A diagnostic warning would help. |

---

## 2. `ops_measure.jsx` — assert_style

**What's good:**
- Tolerance-based comparison is the right call for color matching (floating point imprecision in Illustrator)
- Covers fill, stroke, strokeWidth, opacity — good coverage
- Limits failure details to first 10 (line 340) to prevent response bloat

**Issues:**

| Severity | Issue |
|----------|-------|
| **Medium** | **Only handles RGBColor** (line 284: `item.fillColor.typename === "RGBColor"`). If the document is in CMYK mode, all assertions silently fail with "no fill" even though the item has a fill. At minimum, report the actual color mode in the failure message. |
| **Low** | `assert_exists` (line 92-138) does a full document scan instead of using the global ID index from `ops_core.jsx`. This is O(n) when O(1) is available via `resolveById`. |

---

## 3. `op_schemas.jsx` — Hand-written schemas

**What's good:**
- Clean, readable schema definitions covering all ops
- Validation handles required params, type checking, and enum validation
- `getValueType` correctly uses `Object.prototype.toString` for array detection (ES3 compatible)

**Issues:**

| Severity | Issue |
|----------|-------|
| **Medium** | **Schema drift between `op_schemas.jsx` and `gen_schemas.py`.** The hand-written JSX uses `content`/`font`/`size`/`align` as parameter names, while the codegen Python uses `contents`/`fontName`/`fontSize`/`mode`. These are two separate sources of truth that already disagree — see table below. |

Schema drift details:

| Op | `op_schemas.jsx` (hand-written) | `gen_schemas.py` (codegen) |
|----|------|---------|
| `text_create` | `content`, `font`, `size` | `contents`, `fontName`, `fontSize` |
| `text_set_content` | `content` | `contents` |
| `text_set_style` | `font`, `size` | `fontSize`, `fontName` |
| `align_horizontal` | `align` | `mode` |
| `align_vertical` | `align` | `mode` |
| `style_set_stroke` | required: `[r,g,b]` | required: `[]` (all optional) |
| `element_modify` | has `scale`, `fill`, `stroke`, `opacity` | has `scaleX`, `scaleY`, `rotation` but no `fill`/`stroke`/`opacity` |
| `layer_create` | optional: `position` | optional: `color`, `visible`, `locked` |

This is a significant concern — whichever schema validates at runtime will accept/reject different payloads than the codegen would produce.

---

## 4. `scripts/gen_schemas.py` — Schema Codegen

**What's good:**
- Clean `@dataclass` approach for OpSchema definitions
- CLI with `--output` and `--print` options
- Generated JSX includes validation functions inline — self-contained output

**Issues:**

| Severity | Issue |
|----------|-------|
| **High** | **The codegen output (`op_schemas_generated.jsx`) is never referenced.** The manifest.json points to `op_schemas.jsx` (the hand-written one). Running `python -m scripts.gen_schemas` produces a file that nothing loads. |
| **Medium** | No `__init__.py` in `scripts/` — `python -m scripts.gen_schemas` will fail with `No module named 'scripts'` unless run from the correct working directory and the package is structured right. |
| **Low** | Uses Python f-string double-brace escaping for the entire JSX template (line 212-324). This is fragile — any new `{` in the template will cause a KeyError. Consider using `string.Template` or `$`-based substitution. |

---

## 5. `logging/request_log.py` — Request Logging

**What's good:**
- JSON-lines format is the right choice — easy to parse, grep, and stream
- Script saved separately on error — avoids bloating the log while keeping debug info
- MD5 hash for script deduplication is practical
- Session-based file naming prevents log conflicts
- Clean singleton via `get_request_log()` with lazy init

**Issues:**

| Severity | Issue |
|----------|-------|
| **Low** | **No log rotation or cleanup.** Sessions accumulate indefinitely under `~/.illustrator-mcp/logs/`. For a dev tool this is fine, but a `max_sessions` or `max_age_days` config would prevent disk creep. |
| **Low** | `load_session` (line 153) doesn't handle corrupt lines — a single malformed JSON line throws `json.JSONDecodeError` and aborts the entire load. |

---

## 6. `utils/chunking.py` — Python Chunking

**What's good:**
- Separate limits for create ops vs general ops is smart (creates are heavier in Illustrator)
- `merge_chunk_results` correctly aggregates stats and tracks chunk-indexed errors
- Iterator-based `chunk_ops` is memory efficient
- `estimate_chunk_count` useful for progress UI

**Issues:**

| Severity | Issue |
|----------|-------|
| **Medium** | **No integration point.** `chunk_ops` and `merge_chunk_results` are defined but nothing in `proxy_client.py` or any tool actually calls them. The user would need to manually wire this in. |
| **Low** | `chunk_ops` only checks create ops by prefix string matching (`startswith("element_create")`). If new create ops are added (e.g., `path_create`), they won't be counted. Consider matching against a set. |
| **Low** | `merge_chunk_results` mutates error dicts in-place (line 163: `err["chunk"] = i`). If the same result dict is referenced elsewhere, this is a side effect. |

---

## 7. `snapshot.jsx` — Snapshot/Restore

**What's good:**
- Captures only MCP-managed items (by `@mcp:id` tag) — targeted and efficient
- Color serialization handles RGB, CMYK, Gray, Spot, and NoColor
- Restore is granular: geometry, style, and visibility can be toggled independently
- Error limits (10 notFound, 5 errors) prevent response bloat
- Properly integrated into `executeOpBatch` with snapshot-preferred, undo-fallback strategy

**Issues:**

| Severity | Issue |
|----------|-------|
| **Medium** | **Size restore is commented out** (lines 250-251). Position is restored but width/height are not. This means a snapshot-based rollback after a resize operation won't fully restore state. The comment says "can be complex for certain item types" — this should at least be documented as a known limitation. |
| **Medium** | **Doesn't capture/restore newly created items for deletion on rollback.** If a batch creates 5 elements then fails on element 6, snapshot restore will reset *existing* elements' properties but won't delete the 5 newly created ones. The undo-based fallback handles this better. |
| **Low** | `extractMcpId` is duplicated — it exists in both `snapshot.jsx` (line 82) and is used implicitly in `ops_core.jsx`'s `buildIDIndex`. These should share the implementation. |

---

## 8. `proxy_client.py` — Request Logging Integration

**What's good:**
- Logging call cleanly wraps the existing `execute_script_with_context` flow
- `try/except` around `log_request_to_file` (line 247-256) ensures logging failures never break execution
- Trace ID and elapsed_ms attached to response for downstream consumption

**Issues:**

| Severity | Issue |
|----------|-------|
| **Low** | `includes=None` is always passed (line 251). The comment says "Includes added at higher level" — but there's no code that adds them. The includes field in the log will always be `[]`. |

---

## 9. `bridge/request_registry.py` — WebSocket Streaming

**What's good:**
- Clean separation: `PendingRequest` (future-based) vs `StreamingRequest` (queue-based)
- Thread-safe with `_lock` on all shared state access
- `stream_updates` is a proper async generator with per-update timeout
- Cleanup in `finally` block prevents resource leaks
- `cancel_all` handles both pending and streaming requests

**Issues:**

| Severity | Issue |
|----------|-------|
| **Medium** | **Race condition in `push_update`/`complete_streaming`** (lines 114-158). The lock is released *before* the `queue.put_nowait()` call. Between releasing the lock and the put, another thread could call `complete_streaming`, setting `completed=True`, which would cause `push_update` to silently drop the message. Move the put inside the lock, or use a different synchronization. |
| **Medium** | **Queue size is unbounded** (`asyncio.Queue()` with no maxsize). A long-running streaming operation that produces many updates without consumption will accumulate in memory. |
| **Low** | If `stream_updates` async generator is abandoned (caller breaks early without completing iteration), the `finally` block cleans up, but the streaming request's queue may have unconsumed items that won't be GC'd immediately. |

---

## Summary Table

| # | Feature | Quality | Blocking Issues |
|---|---------|---------|-----------------|
| 1 | summaryOnly | Good | None |
| 2 | Global ID Index | Good | Stale after deletes |
| 3 | assert_style | Good | RGB-only |
| 4 | op_schemas.jsx | Good | Schema drift with codegen |
| 5 | Request Logging | Good | None |
| 6 | Schema Codegen | Needs work | Output unused, drift from hand-written |
| 7 | Python Chunking | Good | Not integrated anywhere |
| 8 | Snapshot/Restore | Good | No size restore, no delete-on-rollback |
| 9 | WebSocket Streaming | Good | Race condition in push/complete |

## Top 3 Recommendations

1. **Resolve the schema dual-source problem.** Either make `gen_schemas.py` the single source of truth and delete the hand-written `op_schemas.jsx`, or delete the codegen. Two diverged schemas will cause hard-to-debug validation failures.

2. **Invalidate ID index on deletes.** Add `invalidateIdIndex()` calls in the `element_delete` handler (and any other destructive ops) to prevent stale index hits.

3. **Fix the streaming race condition.** Move `queue.put_nowait()` inside the lock in `push_update` and `complete_streaming`, or use an `asyncio.Queue` with a sentinel pattern that doesn't depend on the `completed` flag being checked outside the lock.
