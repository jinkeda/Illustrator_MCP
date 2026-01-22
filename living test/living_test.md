Case 1 — “Ping + No Document” (negative)

Setup: Ensure Illustrator has no open document.
Action: Run task_ping or any “get_app_info”.

Expected

Ping returns ok=true and includes app version.

Any doc-dependent task returns ok=false with E_NO_DOC (or equivalent), not a raw exception string.

Case 2 — Collector determinism (basic_paths.ai)

Setup: Open basic_paths.ai. Do not select anything.
Action: collectTargets via payload:

targets: layer L1 or regex ^rect_

Expected

stats.targetCount == 3

Returned ordering is deterministic with your declared rule (recommend: orderBy: "name" or xThenY).

Re-running the same payload twice yields identical itemRefs[] sequence.

Payload sketch

{
  "task": "collect_targets",
  "protocolVersion": "2.3",
  "targets": {
    "type": "layer",
    "name": "L1",
    "orderBy": "name",
    "excludeLocked": true,
    "excludeHidden": true
  },
  "options": { "strict": true }
}

Case 3 — Bounds policy: geometric vs visible (strokes_effects.ai)

Setup: Open strokes_effects.ai.
Action A: compute bounds with use_visible_bounds=false
Action B: compute bounds with use_visible_bounds=true

Expected

Bounds for rect_vis differ between A and B (visible should be larger if stroke/effects are included).

Your report should explicitly state which bounds policy was used.

### ✅ Case 3 Test Results (2026-01-22)

**rect_vis (10pt stroke):**
| Bounds Type | Left | Top | Right | Bottom | Width | Height |
|-------------|------|-----|-------|--------|-------|--------|
| Geometric | 258.94 | 204.79 | 378.94 | 124.79 | 120 | 80 |
| Visible | 253.94 | 209.79 | 383.94 | 119.79 | 130 | 90 |

**Difference**: Visible bounds expand 5pt per side (half of 10pt stroke) ✓

**rect_geo (no stroke):** Geometric = Visible (identical) ✓

**PASS**: Bounds policy correctly distinguishes geometric vs visible bounds.

Case 4 — Clipping group visible bounds (clipping_group.ai)

Setup: Open clipping_group.ai.
Action: getVisibleBounds on clip_group_1.

Expected

The group’s visible bounds must match the clipping mask bounds (within tolerance).

Warnings should be empty; if unsupported, must be explicit (E_UNSUPPORTED_ITEM) and identify the item.

### ⚠️ Case 4 Test Results (2026-01-22)

**clip_group_1** (`clipped: true`, 2 children):

| Item | Size | Notes |
|------|------|-------|
| clip_mask | 150×150 | Clipping path |
| big_shape | 300×300 | Content extends beyond mask |
| Group visibleBounds | 300×300 | Returns content bounds, not clipped |

**Issue**: ExtendScript `visibleBounds` on clipped groups includes all content, not just the clipped visible area.

**PARTIAL PASS**: Clipping detection works, but accurate clipped bounds require custom calculation.

Case 5 — Text bounds stable under rotation (text_point_area.ai)

Setup: Open text_point_area.ai.
Action: compute visible bounds for pt_text_rot, then align it to artboard top-left with a margin.

Expected

After alignment, its visible bounds minX/minY (or top/left depending coordinate system) match the expected margin within tolerance.

No “drift” across repeated apply (idempotency check): running the same align again should move by ~0.

Case 6 — Nested transform bounds (nested_groups_transform.ai)

Setup: Open nested_groups_transform.ai.
Action: compute visible bounds for G_outer.

Expected

Bounds computation completes without recursion errors.

If you return per-node trace, it should show traversal through inner group.

Timing remains reasonable (e.g., < 200ms for small fixture).

Case 7 — Layout grid is stable and non-overlapping (basic_paths.ai)

Setup: Open basic_paths.ai. Select rect_A/B/C (or target by regex).
Action: apply a 1×3 grid layout with fixed gaps.

Expected

X positions increase monotonically (for left-to-right order).

The gaps between adjacent objects’ visible bounds equal the requested gap within tolerance.

No overlaps: right(i) <= left(i+1) - gapTol.

Payload sketch

{
  "task": "layout_grid",
  "protocolVersion": "2.3",
  "targets": { "type": "name_regex", "pattern": "^rect_" , "orderBy": "name" },
  "params": { "rows": 1, "cols": 3, "hGapMm": 3.0, "vGapMm": 0.0, "anchor": "top-left" },
  "options": { "strict": true, "useVisibleBounds": true, "dryRun": false }
}

Case 8 — Retry does not duplicate changes (safety)

Setup: Any fixture, e.g., basic_paths.ai.
Action: Run a task with executeTaskWithRetry(maxRetries=2) while simulating a transient failure in the collect stage (e.g., temporary “CEP busy” error you can trigger via a test hook).

Expected

retryCount > 0

retriedStages includes collect only

Apply stage executes once (your report should count apply invocations = 1)

Final geometry matches a single successful apply (no double move).

If you cannot simulate CEP failures, implement a test-only option: options.testFailStageOnce = "collect".

Case 9 — ID assignment is opt-in and non-destructive (id_conflict_copy.ai)

Setup: Open id_conflict_copy.ai. Ensure objects have meaningful existing notes in at least one item.
Action A: Run any task with assignIds absent/false.
Action B: Run assign_ids with options.assignIds=true for a defined target set.

Expected

A: No document mutation in note fields (report should indicate assignedCount=0)

B: Only targeted items get an @mcp:id=... entry

Existing note content is preserved (append or namespaced JSON merge)

If duplicate IDs exist, conflict is detected and resolved or flagged clearly (depending on policy)

Case 10 — Export pipeline sanity (placed_image.ai)

Setup: Open placed_image.ai.
Action: export PNG at 300 DPI (or scale 2x) with transparent background.

Expected

Export returns a path list with exactly 1 file

File exists on disk (your Python wrapper can verify)

Export timing is recorded

No mutation beyond export-prep (unless explicitly configured)