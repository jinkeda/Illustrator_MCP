# Design Note: R-Tree Spatial Cache for Token-Efficient Context

**Status:** Deferred — revisit when documents consistently exceed 200 items  
**Filed:** 2026-02-16  

---

## Problem

A 500-element Illustrator document returned via `get_document` produces ~50KB JSON (~12K tokens). When the agent only cares about items near one region, returning the entire document wastes context window budget.

## Proposal

Implement a Python-side R-Tree spatial index that caches item bounding boxes. When the agent edits a specific region, Python provides only localized context without re-querying Illustrator.

## Existing Solutions (Why This Is Deferred)

We already have server-side spatial filtering that runs **in Illustrator** before JSON crosses the WebSocket:

| Feature | Filtering |
|---|---|
| `grid` target type | A1-style cell partitioning, returns only items in a cell |
| `spatial` targets (`within`, `nearTo`, `outside`) | Bounding-box region filter |
| `get_document` pagination | `max_items`, `offset`, `layer_name` limit output |
| `query_items` with `namePattern` | Pattern-based server-side filter |

An R-Tree in Python would require first fetching **all** bounds to build the index — defeating the purpose unless the index is persistent across turns.

## When to Revisit

The R-Tree becomes valuable when:

1. **Documents consistently >200 items** — current designs rarely exceed this
2. **Conversations >20 turns** on the same document — amortizes the full-scan cost
3. **Measured evidence** that `get_document` / `query_items` latency is a bottleneck
4. **Batch workflows** — multi-figure poster layouts, template batch processing

## Recommended Architecture

Build as a **cache layer** on top of existing spatial queries, not a replacement:

```
Agent requests region context
  → Check R-Tree cache
    ├── Cache HIT + no journal mutations since last sync
    │     → Return cached results (0 Illustrator round-trips)
    └── Cache MISS or stale
          → Spatial query via ExtendScript
          → Update R-Tree with results
          → Return
```

### Key Design Decisions

- **Staleness detection:** Use `ops_journal.jsx` mutation log. If no ops mutated since last index build, cache is valid. If items moved/created/deleted, re-index only affected items.
- **Incremental updates:** SOC ops already return bounding boxes in their reports. Feed these directly into the R-Tree after each `execute_task` call — no extra round-trip needed.
- **Library:** `rtree` (libspatialindex) or `scipy.spatial.cKDTree` for point queries. For pure bounding-box intersection, a simple grid-based spatial hash may suffice and has zero native dependencies.

### Data Flow

```
execute_task(ops)
  → SOC report includes item bounds
  → Python updates R-Tree incrementally
  → Next spatial query hits cache first

get_document(full scan)
  → Builds R-Tree from scratch
  → Subsequent queries use cache until journal detects mutation
```

### Scope

- Python-only (no ExtendScript changes needed)
- ~200 lines: R-Tree wrapper + journal-based invalidation + cache-first query path
- Optional dependency (`rtree` or pure-Python fallback with grid hash)

## Use Cases (When Built)

1. **VLM overlay ROI selection** — find clustered items near a defect region without ExtendScript
2. **Collision detection** — "will this new label overlap anything?" in pure Python
3. **Smart context injection** — auto-show nearby items when agent references an MCP ID
4. **Multi-region edits** — agent modifies legend → Python provides legend-local context only
