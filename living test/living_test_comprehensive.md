# SOC Framework — Comprehensive Living Tests

**Prerequisite:** All Cases 11–21 from `living_test_soc_design.md` must PASS first.
**Fixture:** Active document with mixed existing items.

---

## Case 22 — Field Eval + Assert + Repair Pipeline

**Goal:** Verify that field-eval-driven fills can be detected and repaired by `assert_style`.

```javascript
var ops = [], ids = [];
for (var i = 0; i < 5; i++) {
    ids.push('C22_' + i);
    ops.push({task: 'element_create', params: {id: 'C22_' + i, type: 'rect', x: 10 + i*60, y: 900, width: 50, height: 50}});
}
// Apply gradient fills via index_ratio
ops.push({task: 'style_set_fill', targets: {type: 'id', ids: ids},
    params: {r: {$field: 'index_ratio', min: 0, max: 255}, g: 0, b: {$field: 'index_ratio', min: 255, max: 0}}});
executeOpBatch(ops, {strict: true});
// Now assert all should be green — triggers repair
executeOpBatch([{task: 'assert_style', targets: {type: 'id', ids: ids},
    params: {fill: {r: 0, g: 200, b: 0}, tolerance: 5, repair: true}}], {strict: false});
```

**Expected:**
- `violations_before: 5`, `repaired: 5`, `violations_after: 0`
- All items green after repair

---

## Case 23 — Journal + Field Eval Determinism

**Goal:** Verify journal replay with `$field` params produces identical results.

```javascript
journalClear(doc.name, doc);
var ids = [], ops = [];
for (var i = 0; i < 4; i++) {
    ids.push('C23_' + i);
    ops.push({task: 'element_create', params: {id: 'C23_' + i, type: 'rect', x: 10 + i*70, y: 950, width: 50, height: 50, name: 'C23_' + i}});
}
ops.push({task: 'style_set_fill', targets: {type: 'id', ids: ids},
    params: {
        r: {$field: 'noise', seed: 77, min: 0, max: 255},
        g: {$field: 'index_ratio', min: 50, max: 200},
        b: {$field: 'lookup', key: 'name', map: {'C23_0': 255, 'C23_1': 128, 'C23_2': 64, 'C23_3': 0}, 'default': 100}
    }});
executeOpBatch(ops, {journal: true, strict: true});
// Recompute twice — fills must be identical
executeOpBatch([], {recompute: {confirm: true, snapshotFirst: true}});
executeOpBatch([], {recompute: {confirm: true, snapshotFirst: true}});
```

**Expected:** Original fills === after recompute #1 === after recompute #2

---

## Case 24 — Multi-Op Chaining (8 ops)

**Goal:** Single batch with create → fill → assert → move → fill → assert → opacity → assert.

```javascript
executeOpBatch([
    {task: 'element_create', params: {id: 'C24', type: 'rect', x: 100, y: 100, width: 80, height: 60}},
    {task: 'style_set_fill', targets: {type: 'id', ids: ['C24']}, params: {r: 255, g: 0, b: 0}},
    {task: 'assert_style', targets: {type: 'id', ids: ['C24']}, params: {fill: {r: 255, g: 0, b: 0}, tolerance: 2}},
    {task: 'element_modify', targets: {type: 'id', ids: ['C24']}, params: {x: 300, y: 200}},
    {task: 'style_set_fill', targets: {type: 'id', ids: ['C24']}, params: {r: 0, g: 0, b: 255}},
    {task: 'assert_style', targets: {type: 'id', ids: ['C24']}, params: {fill: {r: 0, g: 0, b: 255}, tolerance: 2}},
    {task: 'style_set_opacity', targets: {type: 'id', ids: ['C24']}, params: {opacity: 50}},
    {task: 'assert_style', targets: {type: 'id', ids: ['C24']}, params: {opacity: 50, tolerance: 1}}
], {strict: true});
```

**Expected:** All 8 ops pass. Final state: blue fill, 50% opacity, position (300, 200).

---

## Case 25 — Schema Validation Edge Cases

**Goal:** Verify schema validation catches errors correctly.

| Sub-test | Input | Expected |
|----------|-------|----------|
| A | `element_create` without `type` | `ok: false` (missing required) |
| B | `nonexistent_op` | `ok: false` + V003 |
| C | `x: 'not_a_number'` | `ok: false` (wrong type) |
| D | Extra `unknownParam: 999` | `ok: true` (tolerant) |
| E | Empty `[]` ops array | `ok: true, total: 0` |

---

## Case 26 — Rollback Under Mid-Batch Failure

**Goal:** Verify both undo and snapshot rollback clean up created items.

```javascript
executeOpBatch([
    {task: 'element_create', params: {id: 'C26_A', type: 'rect', x: 500, y: 500, width: 30, height: 30}},
    {task: 'element_create', params: {id: 'C26_B', type: 'rect', x: 550, y: 500, width: 30, height: 30}},
    {task: 'assert_exists', params: {ids: ['DOES_NOT_EXIST_EVER']}}
], {strict: true, rollback: true, snapshot: true});
```

**Expected:** `countAfter === countBefore` — created items rolled back.

---

## Case 27 — Delete + Re-Create Same IDs

**Goal:** Full lifecycle with same ID.

1. Create `C27_X` as red rect
2. Delete `C27_X`
3. Verify `assert_exists` returns false
4. Re-create `C27_X` as green ellipse
5. Verify it's green ellipse (not red rect)

---

## Case 28 — Large Batch Stress (50 items)

**Goal:** Performance and correctness at scale.

```javascript
// 50 element_create + 1 field_eval style + 1 assert_exists = 52 ops
```

**Expected:** `ok: true`, all 52 ops pass, gradient fills verified, <500ms total.

---

## Case 29 — Multi-Layer Targeting

**Goal:** Verify items can be created on specific layers and targeted cross-layer.

1. Create `C29_Layer_A` and `C29_Layer_B`
2. Place 2 items on each
3. Style differently per layer
4. Assert fills per-layer

**Expected:** All items on correct layers, cross-layer assertions pass.

---

## Summary

| Case | Feature | Priority |
|------|---------|----------|
| 22 | Field eval → assert → repair | **High** |
| 23 | Journal + field eval determinism | **High** |
| 24 | Multi-op chaining | **High** |
| 25 | Schema validation edge cases | Medium |
| 26 | Rollback under failure | **Critical** |
| 27 | Delete + re-create same ID | **High** |
| 28 | Large batch stress | Medium |
| 29 | Multi-layer targeting | Medium |

**Run order:** 22 → 23 → 24 → 25 → 26 → 27 → 28 → 29
