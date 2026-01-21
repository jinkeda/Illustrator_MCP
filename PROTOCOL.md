# Task Protocol Reference v2.3

Complete reference documentation for the Illustrator MCP Task Protocol.

## Table of Contents

- [Protocol Overview](#protocol-overview)
- [Error Codes](#error-codes)
- [Target Selectors](#target-selectors)
- [Stable References](#stable-references)
- [Retry Semantics](#retry-semantics)
- [Payload Structure](#payload-structure)
- [Report Structure](#report-structure)
- [Migration Guide](#migration-guide)
- [Future Outlook](#future-outlook)

---

## Protocol Overview

The Task Protocol provides a structured approach to executing Illustrator operations with:

| Feature | Description |
|---------|-------------|
| **Standardized Error Codes** | Categorized codes (V/R/S) for validation, runtime, and system errors |
| **Compound Target Selectors** | `anyOf` unions, exclusion filters, deterministic ordering |
| **Stable References** | Separated locator/identity/tag concerns |
| **Safe Retry** | Stage-aware retry that never auto-retries `apply` |
| **JSON Schemas** | Auto-generated schemas for validation |

### Execution Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  VALIDATE   │────▶│   COLLECT   │────▶│   COMPUTE   │────▶│    APPLY    │
│  (fail-fast)│     │  (targets)  │     │  (actions)  │     │  (execute)  │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
      │                   │                   │                   │
      ▼                   ▼                   ▼                   ▼
   V001-V008          R001 on fail        R002 on fail       R003 on fail
   (validation)       (retryable)         (retryable)        (NOT retryable)
```

---

## Error Codes

### Categories

| Category | Prefix | Description | Retryable |
|----------|--------|-------------|-----------|
| **Validation** | `V` | Fail before execution (invalid input) | ❌ No |
| **Runtime** | `R` | Fail during execution | ✅ Usually |
| **System** | `S` | Illustrator/environment issues | ❌ Usually no |

### Complete Reference

#### Validation Errors (V001-V008)

| Code | Name | Description |
|------|------|-------------|
| `V001` | V_NO_DOCUMENT | No active Illustrator document |
| `V002` | V_NO_SELECTION | No items selected when selection required |
| `V003` | V_INVALID_PAYLOAD | Missing or malformed payload structure |
| `V004` | V_INVALID_TARGETS | Invalid targets object |
| `V005` | V_UNKNOWN_TARGET_TYPE | Unknown target type (not selection/layer/all/query/compound) |
| `V006` | V_MISSING_REQUIRED_PARAM | Required parameter missing |
| `V007` | V_INVALID_PARAM_TYPE | Parameter has wrong type |
| `V008` | V_SCHEMA_MISMATCH | Payload doesn't match expected schema |

#### Runtime Errors (R001-R006)

| Code | Name | Description | Retryable |
|------|------|-------------|-----------|
| `R001` | R_COLLECT_FAILED | Failed to collect target items | ✅ Yes |
| `R002` | R_COMPUTE_FAILED | Failed during computation | ✅ Yes |
| `R003` | R_APPLY_FAILED | Failed to apply changes | ❌ No |
| `R004` | R_ITEM_OPERATION_FAILED | Single item operation failed | ❌ No |
| `R005` | R_TIMEOUT | Operation timed out | ✅ Yes |
| `R006` | R_OUT_OF_BOUNDS | Value out of valid range | ❌ No |

#### System Errors (S001-S004)

| Code | Name | Description |
|------|------|-------------|
| `S001` | S_APP_ERROR | Illustrator application error |
| `S002` | S_SCRIPT_ERROR | ExtendScript execution error |
| `S003` | S_IO_ERROR | File I/O error |
| `S004` | S_MEMORY_ERROR | Memory allocation error |

---

## Target Selectors

### Simple Targets

```javascript
// Current selection
{type: "selection"}

// All items on a layer
{type: "layer", layer: "Layer 1", recursive: false}

// All items in document
{type: "all", recursive: true}

// Query with filters
{type: "query", itemType: "PathItem", pattern: "panel_*", layer: "Panels"}
```

### Compound Targets

```javascript
// Union of multiple sources
{
  type: "compound",
  anyOf: [
    {type: "layer", layer: "Panels"},
    {type: "selection"}
  ],
  exclude: {locked: true, hidden: true}
}
```

### Target Selector with Ordering

```javascript
// Full target selector (v2.3 format)
{
  target: {type: "selection"},
  orderBy: "reading",  // Deterministic ordering
  exclude: {locked: true, hidden: true}
}
```

### Ordering Modes

| Mode | Description |
|------|-------------|
| `zOrder` | Illustrator stacking order (back to front) - **default** |
| `zOrderReverse` | Front to back |
| `reading` | Left-to-right, top-to-bottom (row-major) |
| `column` | Top-to-bottom, left-to-right (column-major) |
| `name` | Alphabetical by item.name |
| `positionX` | Left edge ascending |
| `positionY` | Top edge ascending |
| `area` | Smallest to largest |

### Exclusion Filters

```javascript
{
  locked: true,   // Exclude locked items
  hidden: true,   // Exclude hidden items
  guides: true,   // Exclude guides
  clipped: true   // Exclude items inside clipping masks
}
```

---

## Stable References

### Concept Separation

| Concept | Volatility | Use Case |
|---------|------------|----------|
| **Locator** | Volatile | One-shot operations, error localization |
| **Identity** | Stable | Cross-session item tracking |
| **Tag** | User-controlled | Semantic selection without UUIDs |

### ItemRef Structure (v2.3)

```javascript
{
  locator: {
    layerPath: "Layer 1/Group A",
    indexPath: [0, 2, 5]
  },
  identity: {
    itemId: "mcp_1705834200_42",
    idSource: "note"  // "none", "note", "name"
  },
  tags: {
    tags: {role: "header", order: "1"}
  },
  itemType: "PathItem",
  itemName: "Panel A @mcp:role=header"
}
```

### Tag Syntax

Items can be tagged using `@mcp:key=value` in name or note:

```
Panel A @mcp:role=header @mcp:order=1
```

Parsed as: `{role: "header", order: "1"}`

### ID Policies

| Policy | Behavior |
|--------|----------|
| `none` | Never assign IDs (default) |
| `opt_in` | Only assign when explicitly requested |
| `always` | Always assign (with conflict detection) |
| `preserve` | Keep existing IDs, don't assign new ones |

---

## Retry Semantics

### Stage Safety

| Stage | Auto-Retry | Reason |
|-------|------------|--------|
| `collect` | ✅ Safe | Read-only, no side effects |
| `compute` | ✅ Safe | No document changes |
| `apply` | ❌ **Never** | Could double-apply changes |

### Retry Exceptions

`apply` can only be retried if:
1. `options.dryRun = true` (no actual changes)
2. `options.idempotency = "safe"` (caller guarantees)
3. Undo state available (rollback before retry)

### Retry Configuration

```javascript
{
  options: {
    retry: {
      maxAttempts: 3,
      retryableStages: ["collect", "compute"],
      retryOnCodes: ["R001", "R002"],
      requireIdempotent: true
    },
    idempotency: "unknown"  // "safe", "unknown", "unsafe"
  }
}
```

### Retry Info in Report

```javascript
{
  retryInfo: {
    attempts: 2,
    succeeded: true,
    retriedStages: ["collect"],
    idempotency: "unknown"
  }
}
```

---

## Payload Structure

### TaskPayload

```javascript
{
  task: "query_items",           // Required: operation type
  version: "2.3.0",              // Protocol version
  targets: {                     // Target selector
    target: {type: "selection"},
    orderBy: "reading"
  },
  params: {                      // Operation-specific parameters
    includeHidden: false
  },
  options: {                     // Execution options
    dryRun: false,
    trace: true,
    idPolicy: "none",
    timeout: 30,
    retry: null,
    idempotency: "unknown"
  }
}
```

---

## Report Structure

### TaskReport

```javascript
{
  ok: true,
  stats: {
    itemsProcessed: 10,
    itemsModified: 8,
    itemsSkipped: 2
  },
  timing: {
    collect_ms: 15,
    compute_ms: 5,
    apply_ms: 120,
    total_ms: 140
  },
  warnings: [...],
  errors: [...],
  artifacts: {
    exportedPath: "/path/to/file.svg"
  },
  trace: [
    "[COLLECT] Starting target collection",
    "[COLLECT] Found 10 items",
    "[COMPUTE] Computing actions",
    "[APPLY] Applying 8 actions"
  ],
  retryInfo: {
    attempts: 1,
    succeeded: true,
    retriedStages: [],
    idempotency: "unknown"
  }
}
```

---

## Migration Guide

### From v2.2 to v2.3

#### Error Codes

```diff
- ErrorCodes.NO_DOCUMENT
+ ErrorCodes.V_NO_DOCUMENT

- ErrorCodes.COLLECT_FAILED
+ ErrorCodes.R_COLLECT_FAILED
```

#### Target Selectors

```diff
// Old format (still supported)
targets: {type: "selection"}

// New format (recommended)
targets: {
  target: {type: "selection"},
  orderBy: "reading"
}
```

#### ID Assignment

```diff
// Old
options: {assignIds: true}

// New
options: {idPolicy: "opt_in"}
```

#### Retry

```diff
// Old (deprecated)
executeTaskWithRetry(payload, collect, compute, apply, 3)

// New
payload.options.retry = {maxAttempts: 3, retryableStages: ["collect"]}
executeTaskWithRetrySafe(payload, collect, compute, apply)
```

---

## Future Outlook

### Protocol Versioning (Planned)

When breaking changes are needed:

```javascript
// Version validation (future)
{
  version: "3.0.0",  // Pattern: major.minor.patch
  // ...
}
```

**Compatibility Policy:**
- `2.x.y` → `2.x.z`: Backward compatible
- `2.x` → `3.x`: Breaking change (requires migration)

### Potential v3.0 Changes

1. Remove deprecated `executeTaskWithRetry`
2. Require structured `TargetSelector` (no legacy dict)
3. Add transaction/undo support for safe apply retry
4. Add `nonce` for duplicate detection

---

## JSON Schemas

Generated schemas are available in `illustrator_mcp/schemas/`:

| Schema | Description |
|--------|-------------|
| `task_payload.schema.json` | TaskPayload validation |
| `task_report.schema.json` | TaskReport validation |
| `target_selector.schema.json` | TargetSelector validation |
| `task_options.schema.json` | TaskOptions validation |
| `item_ref.schema.json` | ItemRef validation |
| `error_codes.schema.json` | Error code enum |

Generate schemas:
```bash
python -m illustrator_mcp.schemas.schema_generator
```
