# SOC Result Contracts

> Single source of truth for all data shapes flowing through the SOC framework.

## 1. Handler Result

Every op handler (`registerOpHandler`) MUST return one of these two shapes:

### Success
```javascript
{
    ok: true,
    data: { ... },           // Op-specific payload
    id: "uuid",              // Optional: singular created item ID
    warnings: ["..."]        // Optional: non-fatal issues
}
```

`data` contents vary by op:
| Op | `data` fields |
|----|---------------|
| `element_create` | `{ type, id, bounds }` |
| `element_create_multi` | `{ created, skipped, ids[], totalPoints, stylingMode, pagination }` |
| `layer_create` | `{ name, existed }` |
| `element_modify` | `{ modified }` |
| `element_delete` | `{ deleted, failed }` |

### Failure
```javascript
{
    ok: false,
    error: {
        code: "V007",            // ErrorCodes constant
        message: "Human text",   // Descriptive message
        stage: "apply",          // "validate" | "collect" | "compute" | "apply"
        itemRef: null,           // Optional: ItemRef for localization
        details: null            // Optional: additional context
    }
}
```

Produced by `makeError(code, message, stage, itemRef?, details?)`.

---

## 2. Batch Report (`executeOpBatch` return)

### `summaryOnly: true` (recommended for generators)
```javascript
{
    ok: true|false,              // false if any op failed
    schemaVersion: "1.0.0",
    summaryOnly: true,
    rolledBack: 0,
    createdIds: ["uuid1", ...],  // All IDs from all ops
    stats: {
        total: 3,
        executed: 3,
        passed: 3,
        failed: 0,
        failedAtIndex: null      // Index of first failure
    },
    timing: { total_ms: 42 },
    diagnostics: { cacheHits, cacheMisses, idScans, selectionWarnings },
    warnings: ["..."],           // Only if present
    errors: [                    // Only failed ops
        { index: 1, task: "op_name", error: { code, message, stage } }
    ],
    trace: ["..."]               // Only if trace:true
}
```

### `summaryOnly: false` (full)
Same as above, plus:
```javascript
{
    ops: [                       // Per-op results
        { index: 0, task: "...", ok: true, data: {...}, duration_ms: 5 },
        { index: 1, task: "...", ok: false, error: {...}, duration_ms: 2 }
    ]
}
```

---

## 3. Journal Entry (`journalAppend`)

```javascript
{
    batchId: "uuid",
    timestamp: 1700000000000,
    ops: [                       // Stripped ops (no resolved items)
        { task: "...", params: {...}, targets: {...} }
    ],
    createdIds: ["uuid1", ...],
    generatorMeta: {             // Optional: for replay fidelity
        generator: "flow_field",
        version: "1.0.0",
        seed: 42,
        params: { gridRes: 20, steps: 100 }
    },
    options: { strict, rollback, snapshot },
    report: { ok: true, stats: { total, passed, failed } }
}
```

---

## 4. Session Stash

```javascript
// Store
stashPut(key, data, meta?)     // Raw store
stashPutIR(key, irData, meta?) // Validates IR schema first → {ok, errors?}

// Retrieve
stashGet(key)      // Returns reference or null (do NOT mutate)
stashKeys()        // User-facing keys for current document
stashInfo()        // Metadata: {key: {ts, size, meta}}
stashClear(key?)   // Remove one or all keys
```

Keys are namespaced as `docName::userKey`. Session-scoped (lost on quit/crash).

---

## Size Limits

| Resource | Limit |
|----------|-------|
| Journal entry | 500 KB |
| Stash IR value | 5 MB |
| Paths per `element_create_multi` | 2000 (use offset/limit) |
| Points per path | 8000 (auto-decimated) |
