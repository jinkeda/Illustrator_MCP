# SOC Design Principles — Living Test Plan

**Fixture:** `basic_paths.ai` (existing) unless noted otherwise.
**Prerequisite:** Illustrator connected, document open, MCP panel active.

---

## Case 11 — Selection Deprecation Warning (P1)

**Setup:** Open `basic_paths.ai`.
**Action:** Run SOC batch targeting `type: "selection"` with rect_A selected:
```javascript
var ops = [{task: "assert_exists", targets: {type: "selection"}, params: {}}];
executeOpBatch(ops, {strict: true});
```

**Expected:**
- Batch completes (ok: true or returns assertion data)
- `diagnostics.selectionWarnings` >= 1
- Warning text includes "deprecated"

---

## Case 12 — Injectable Clock (P2)

**Setup:** Open `basic_paths.ai`.
**Action:** Run batch with custom clock:
```javascript
var ops = [{task: "element_create", params: {id: "CLK1", type: "rect", x: 10, y: 10, width: 50, height: 50}}];
var report = executeOpBatch(ops, {clock: function() { return 1234567890; }});
```

**Expected:**
- `report.timing.total_ms` is computed from the injected clock (value should be 0 since start and end return the same value)
- No `new Date()` calls in timing path

---

## Case 13 — Repair Mode: assert_alignment (P5)

**Setup:** Open `basic_paths.ai`. Create 3 rects at deliberately misaligned x positions:
```javascript
var ops = [
    {task: "element_create", params: {id: "RA1", type: "rect", x: 100, y: 100, width: 50, height: 50}},
    {task: "element_create", params: {id: "RA2", type: "rect", x: 107, y: 200, width: 50, height: 50}},
    {task: "element_create", params: {id: "RA3", type: "rect", x: 95,  y: 300, width: 50, height: 50}},
    {task: "assert_alignment", targets: {type: "id", ids: ["RA1","RA2","RA3"]},
     params: {axis: "left", tolerance: 2, repair: true}}
];
executeOpBatch(ops, {strict: false});
```

**Expected:**
- `violations_before` > 0 (RA2 and RA3 are misaligned)
- `repaired` > 0
- `violations_after` == 0 (all snapped to first item's left edge)
- `repairs[]` array contains entries with `{id, before, after}` values
- After repair, all items share the same left x ±tolerance

**Idempotency check:** Run the assert_alignment again with `repair: true`. `violations_before` should be 0.

---

## Case 14 — Repair Mode: assert_style (P5)

**Setup:** Create elements with inconsistent fills:
```javascript
var ops = [
    {task: "element_create", params: {id: "RS1", type: "rect", x: 10, y: 10, width: 50, height: 50}},
    {task: "style_set_fill", targets: {type: "id", ids: ["RS1"]}, params: {r: 255, g: 0, b: 0}},
    {task: "element_create", params: {id: "RS2", type: "rect", x: 80, y: 10, width: 50, height: 50}},
    {task: "style_set_fill", targets: {type: "id", ids: ["RS2"]}, params: {r: 200, g: 50, b: 50}},
    {task: "assert_style", targets: {type: "id", ids: ["RS1","RS2"]},
     params: {fill: {r: 255, g: 0, b: 0}, tolerance: 5, repair: true}}
];
executeOpBatch(ops, {strict: false});
```

**Expected:**
- RS2 detected as violation (fill deviates beyond tolerance)
- `repaired` >= 1
- `repairs[]` has entry for RS2 with `before: {r:200,...}` and `after: {r:255,...}`
- `violations_after` == 0

---

## Case 15 — Field Evaluator: index_ratio Gradient (P3)

**Setup:** Create 5 rects with gradient fill using field evaluator:
```javascript
var ops = [];
for (var i = 0; i < 5; i++) {
    ops.push({task: "element_create", params: {id: "FG" + i, type: "rect", x: 10 + i*60, y: 10, width: 50, height: 50}});
}
ops.push({task: "style_set_fill", targets: {type: "id", ids: ["FG0","FG1","FG2","FG3","FG4"]},
    params: {r: {$field: "index_ratio", min: 50, max: 255}, g: 0, b: 0}});
executeOpBatch(ops, {strict: true});
```

**Expected:**
- All 5 rects created (ok: true)
- Fill red channel increases across items: FG0=50, FG4=255
- `index_ratio` semantics: `i/(n-1)` → values at 0, 0.25, 0.5, 0.75, 1.0
- Mapped to [50, 255]: 50, 101, 152, 204, 255 (±1 for rounding)

**Verify:** Read back fill colors with `assert_style` or manual inspection.

---

## Case 16 — Field Evaluator: noise Determinism (P3)

**Setup:** Create 3 rects. Apply noise-driven opacity:
```javascript
var ops = [
    {task: "element_create", params: {id: "FN1", type: "rect", x: 10, y: 10, width: 50, height: 50}},
    {task: "element_create", params: {id: "FN2", type: "rect", x: 80, y: 10, width: 50, height: 50}},
    {task: "element_create", params: {id: "FN3", type: "rect", x: 150, y: 10, width: 50, height: 50}},
    {task: "style_set_opacity", targets: {type: "id", ids: ["FN1","FN2","FN3"]},
     params: {opacity: {$field: "noise", seed: 42, min: 30, max: 100}}}
];
var r1 = executeOpBatch(ops, {strict: true});
```

**Expected:**
- All items have opacity in [30, 100]
- Run the same batch again (with same seed) → identical opacity values per item
- Zero `Math.random()` calls (deterministic hash)

---

## Case 17 — Field Evaluator: lookup (P3)

**Setup:** Create named elements, apply lookup-driven style:
```javascript
var ops = [
    {task: "element_create", params: {id: "FL_A", type: "rect", x: 10, y: 10, width: 50, height: 50, name: "carbon"}},
    {task: "element_create", params: {id: "FL_B", type: "rect", x: 80, y: 10, width: 50, height: 50, name: "oxygen"}},
    {task: "style_set_fill", targets: {type: "id", ids: ["FL_A","FL_B"]},
     params: {r: {$field: "lookup", key: "name", map: {"carbon": 50, "oxygen": 255}, default: 128}, g: 0, b: 0}}
];
executeOpBatch(ops, {strict: true});
```

**Expected:**
- carbon → r=50, oxygen → r=255
- An item with unmatched name → r=128 (default)

---

## Case 18 — Journal Record + Replay (P6)

**Setup:** Open empty document. Run a journaled batch:
```javascript
var ops = [
    {task: "element_create", params: {id: "JR1", type: "rect", x: 50, y: 50, width: 80, height: 60}},
    {task: "style_set_fill", targets: {type: "id", ids: ["JR1"]}, params: {r: 0, g: 128, b: 255}},
    {task: "element_create", params: {id: "JR2", type: "ellipse", x: 200, y: 50, width: 60, height: 60}},
    {task: "assert_exists", params: {ids: ["JR1", "JR2"]}}
];
executeOpBatch(ops, {journal: true, strict: true});
```

**Action A:** Verify journal was recorded:
```javascript
journalSummary(doc.name);
// Expected: {entries: 1, totalOps: 4, ...}
```

**Action B:** Recompute (clear + replay):
```javascript
executeOpBatch([], {recompute: {confirm: true, snapshotFirst: true}});
```

**Expected:**
- Document is cleared, then rebuilt from journal
- JR1 and JR2 exist after replay with correct positions and fill
- Recompute report: `{ok: true, replayedBatches: 1}`

---

## Case 19 — Journal Replay Error Policies (P6)

**Setup:** Populate journal with 2 batches, second batch has a deliberately invalid op:
```javascript
// Batch 1: valid
executeOpBatch([
    {task: "element_create", params: {id: "EP1", type: "rect", x: 10, y: 10, width: 50, height: 50}}
], {journal: true, strict: true});

// Batch 2: will fail on replay (targets nonexistent ID)
executeOpBatch([
    {task: "style_set_fill", targets: {type: "id", ids: ["NONEXISTENT"]}, params: {r: 255, g: 0, b: 0}}
], {journal: true, strict: false});
```

**Test A — strict:** Replay stops at batch 2, `failedAt.batchIndex == 1`.
**Test B — skip:** Replay continues, `replayedBatches == 2`, `failed > 0`.
**Test C — rollback:** Replay stops at batch 2, snapshot restored, `failedAt.rolledBack == true`.

---

## Case 20 — Journal Filename Collision Safety (P6)

**Setup:** Create two documents with the **same name** but different artboard sizes.
**Action:** Run `getJournalFile(docName, doc)` for each.

**Expected:**
- File paths differ (fingerprint suffix: `_800x600` vs `_1920x1080`)
- No cross-contamination of journal data between documents

---

## Case 21 — Replay Determinism with ID Targeting (P6)

**Setup:** Open empty document. Run a multi-step journaled batch:
```javascript
var ops = [
    {task: "element_create", params: {id: "RD1", type: "rect", x: 50, y: 50, width: 80, height: 60}},
    {task: "element_create", params: {id: "RD2", type: "rect", x: 200, y: 50, width: 80, height: 60}},
    {task: "style_set_fill", targets: {type: "id", ids: ["RD1"]}, params: {r: 255, g: 0, b: 0}},
    {task: "style_set_fill", targets: {type: "id", ids: ["RD2"]}, params: {r: 0, g: 0, b: 255}},
    {task: "assert_exists", params: {ids: ["RD1", "RD2"]}}
];
executeOpBatch(ops, {journal: true, strict: true});
```

**Action:** Run recompute twice:
```javascript
// Recompute #1
executeOpBatch([], {recompute: {confirm: true, snapshotFirst: true}});
// Recompute #2
executeOpBatch([], {recompute: {confirm: true, snapshotFirst: true}});
```

**Expected:**
- Both recomputes succeed (ok: true)
- RD1 position, fill identical after both recomputes
- RD2 position, fill identical after both recomputes
- Positions and styles match the original batch exactly

**Stretch goal:** Compute structure hash after original, after recompute #1, after recompute #2 — all three must match.

---

## Summary Table

| Case | Feature | Phase | Priority |
|------|---------|-------|----------|
| 11 | Selection deprecation warning | P1 | Medium |
| 12 | Injectable clock | P2 | Low |
| 13 | Repair assert_alignment | P5 | **High** |
| 14 | Repair assert_style | P5 | **High** |
| 15 | Field eval: index_ratio | P3 | **High** |
| 16 | Field eval: noise determinism | P3 | **High** |
| 17 | Field eval: lookup | P3 | Medium |
| 18 | Journal record + replay | P6 | **High** |
| 19 | Replay error policies | P6 | **High** |
| 20 | Journal filename collision | P6 | Medium |
| 21 | Replay determinism (2× recompute) | P6 | **Critical** |

**Run order:** 11 → 12 → 13 → 14 → 15 → 16 → 17 → 18 → 19 → 20 → 21
**Estimated time:** ~30 min with Illustrator connected
