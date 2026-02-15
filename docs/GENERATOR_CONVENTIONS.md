# Generator Conventions

> How to write generative scripts that play nice with the SOC ops framework.

## Three-Phase Architecture

Every generator MUST follow this structure:

```
Phase A: IR computation           → no DOM access
Phase B: executeOpBatch(ops, {    → all DOM through SOC ops
           journal: true,
           generatorMeta: { ... }
         })
Phase C: Labels / overlays        → addLabel helper only
```

### Phase A: Pure Computation

- Use `buildCurlField()`, `integrateField()`, `buildFieldGrid()` for field-based generation
- Use `marchingSquares()`, `chainSegments()`, `chaikinSmooth()` for contour-based generation
- Output: arrays of point data + scalar values
- **Zero DOM access in this phase**

### Phase B: SOC Batch

Call `executeOpBatch()` with `{ journal: true }` for all DOM creation:

```javascript
var result = executeOpBatch([
    { task: "layer_create", params: { name: "My Layer" } },
    { task: "element_create_multi", params: {
        geometry: irMultiObj,
        layer: "My Layer",
        fill: false,
        styleScalars: scalars,
        palette: paletteObj
    }}
], { journal: true, summaryOnly: true });
```

This gives you:
- MCP IDs on every item (returned in `createdIds[]`)
- Journal entry for replay/undo
- Structured error reporting
- Target resolution for follow-up ops

### Phase C: Labels

Use `addLabel(layer, x, y, text, opts)` for text overlays. This is outside the batch because text creation uses a different code path to avoid PARM errors.

## Styling Modes

### 1. Shared Style (simple)
```javascript
{ stroke: {r:60, g:60, b:60, width: 0.5}, fill: false }
```

### 2. Explicit Per-Path (`styles[]`)
```javascript
styles: [
  { stroke: {r:20,g:80,b:140}, opacity: 70 },
  null,  // → uses shared default
]
```

### 3. Scalar + Palette (compact, preferred for generators)
```javascript
styleScalars: [0.0, 0.15, 0.42, 0.88, ...],
palette: {
  stroke: { r: [15, 70], g: [70, 210], b: [130, 255] },
  opacity: [40, 95],
  width: [0.3, 0.6]
}
```

The scalar `t ∈ [0,1]` is interpolated against the palette ranges inside the op handler. This keeps payloads small (one float per path vs full RGB+opacity+width).

## Performance Budget

| Metric | Limit | Action |
|--------|-------|--------|
| Paths per `element_create_multi` call | 2000 | Use `offset`/`limit` for chunking |
| Points per path | 8000 | Auto-decimated by handler |
| Total DOM writes per batch | ~10000 | Split into multiple batches |

## Multi-Call Workflow (Session Stash)

For large or interactive generators, split across multiple `execute_script` calls:

```
Call A (compute):  includes: [generative, session, geo_ir]
                   → compute IR, stashPutIR("flow_ir", irGeo, { generator: "flow_field", seed: 42 })
                   → return { key: "flow_ir", pathCount: N }

Call B (create):   includes: [session, ops_core, ops_element]
                   → executeOpBatch([{ task: "element_create_multi_by_ref",
                        params: { irKey: "flow_ir", offset: 0, limit: 500, ... } }])

Call C (chunk 2):  → element_create_multi_by_ref({ irKey: "flow_ir", offset: 500, limit: 500, ... })

Call D (verify):   includes: [session, ops_core, ops_measure]
                   → assert_* checks on created items

Call E (cleanup):  → stashClear("flow_ir")
```

> [!IMPORTANT]
> Stash is session-scoped (lost on Illustrator quit/crash). Keys are namespaced by document name.
> `stashPutIR()` validates IR schema before storing — use it instead of raw `stashPut()`.

## generatorMeta (Journal Replay Fidelity)

Pass generator parameters to the journal for re-derivation:

```javascript
executeOpBatch(ops, {
    journal: true,
    summaryOnly: true,
    generatorMeta: {
        generator: "flow_field",
        version: "1.0.0",
        seed: NOISE_SEED,
        params: { gridRes: GRID_RES, steps: MAX_STEPS, palette: PALETTE_MODE }
    }
});
```

This enables replay systems to either re-execute ops from journal or re-derive the IR from scratch.

## Library Loading

Scripts loaded via `execute_script` with `includes` parameter:
```python
includes=["geo_ir", "generative", "task_executor", "ops_core", "ops_layer", "ops_element", "ops_journal"]
```

**Do NOT use `File.eval()` or `#include`** — use the `includes` mechanism so the framework manages load order and caching.

> [!IMPORTANT]
> `task_executor` must come before `ops_core` (provides `makeError`, `ErrorCodes`, `collectTargets`).
> `ops_layer` must come before any script using `layer_create`.

## Required Dependencies

| Library | Purpose |
|---------|---------|
| `geo_ir` | IR schema, validation, point mapping |
| `generative` | Noise, fields, smoothing, spatial utils |
| `task_executor` | `makeError`, `ErrorCodes`, `collectTargets` (required by `ops_core`) |
| `ops_core` | `executeOpBatch`, validation, handler registry |
| `ops_layer` | `layer_create`, `layer_delete`, `layer_lock`, `layer_visible` |
| `ops_element` | Create/modify/style/delete ops, `element_create_multi_by_ref` |
| `ops_journal` | Journal recording for replay (opt-in via `{ journal: true }`) |
| `session` | Multi-call IR stash (`stashPutIR`, `stashGet`, `stashClear`) |

## Example: Scalar Computation

Compute a meaningful scalar per curve for palette interpolation:

```javascript
// Position-based: normalized Y of midpoint
var midIdx = Math.floor(pts.length / 2);
var t = pts[midIdx][1] / DOMAIN_SIZE;

// Length-based: normalized curve length
var t = pts.length / MAX_STEPS;

// Noise-based: sample noise at seed point
var t = fbm(seedX * 0.01, seedY * 0.01, noiseOpts);
```
