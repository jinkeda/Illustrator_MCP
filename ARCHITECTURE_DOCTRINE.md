# Architecture Doctrine v1.1

> Enforceable rules for the Illustrator MCP JSX runtime. Every PR touching `resources/scripts/` must comply.

## 1. ES3-Only JSX

All `.jsx` files under `resources/scripts/` must use **ES3 syntax only**. ExtendScript is ES3-based.

### Forbidden tokens (enforced by `scripts/es3_lint.ps1`):

| Token | Replacement |
|-------|-------------|
| `const` | `var` |
| `let` | `var` |
| `=>` (arrow function) | `function(x) { ... }` |
| `new Map()` | Plain object `{}` |
| `new Set()` | Plain object `{}` with boolean values |
| Template literals `` `${x}` `` | `"" + x` |
| `for...of` | `for (var i = 0; i < arr.length; i++)` |
| Destructuring `{a, b} = obj` | `var a = obj.a; var b = obj.b;` |

### Allowed polyfills (in `polyfills.jsx`):

`Array.prototype.indexOf`, `.forEach`, `.map`, `.filter`, `.every`, `.some`, `.reduce` — guarded by `if (!Array.prototype.X)`.

### JSDoc exception

`=>` in JSDoc `@param` descriptions (e.g., `(params, targets, ctx) => result`) is **allowed** — it's documentation, not code.

---

## 2. Heap Transaction Scoping

All ID index mutations must be **transaction-scoped** and reversible within a batch.

### Invariants

1. `heapBeginTxn(batchId)` before any op execution
2. `heapCommitTxn()` only on full batch success
3. `heapRollbackTxn()` on batch failure — discards all index changes from that batch
4. Created items that survive a failed batch must not persist in the index

### Prohibited patterns

- Direct mutation of `$.global.mcpIdIndex` outside heap APIs
- Setting `item.note` with `@mcp:id=` without calling `heapRegister`

---

## 3. ID Resolution Complexity

| Operation | Complexity | Notes |
|-----------|-----------|-------|
| `heapResolve(uuid)` | O(1) amortized | Index lookup + identity verify |
| `heapRebuildIndex(doc)` | O(N) | Full scan; at most **once per batch** |
| `heapRegister(uuid, ref)` | O(1) | Insert into index + txn record |
| `heapTombstone(uuid)` | O(1) | Mark for deletion |

**Per-op O(N) scans are prohibited.** If `heapResolve` fails after a rebuild, throw `ERR_ID_NOT_FOUND` — do not scan again.

---

## 4. Hybrid Identity

| Store | Role | When Set |
|-------|------|----------|
| `item.note` containing `@mcp:id=UUID` | **Canonical** — always authoritative | On item creation |
| `item.name = "mcp:" + UUID` | **Optional accelerator** — for faster `getByName` resync | On MCP-created items only |

### Rules

- Never trust `item.name` alone — always verify via `extractMcpId(item.note)`
- `item.name` accelerator is opt-in and disabled by default
- Non-MCP items (user-created) must never have their name overwritten

---

## 5. Contract Compilation

Schemas are **compiled artifacts**, not hand-written.

| Source | Output | Mechanism |
|--------|--------|-----------|
| `schemas/contracts.py` (Pydantic) | `contracts.jsx` (ES3) | `tools/compile_contracts.py` |

### Invariants

- `contracts.jsx` includes a SHA-256 checksum header
- Runtime init compares checksums; mismatch → `ERR_VERSION_MISMATCH`
- Editing `contracts.jsx` by hand is prohibited — always re-compile

---

## 6. Go/No-Go PR Checklist

Before merging any PR touching `resources/scripts/`:

- [ ] `scripts/es3_lint.ps1` passes (zero forbidden tokens in executable code)
- [ ] `node tests_jsx/run_tests.js` passes
- [ ] `python -m pytest tests/ -q` passes
- [ ] `contracts.jsx` matches compiled output (if schemas changed)
- [ ] No direct `$.global.mcpIdIndex` mutation outside `heap.jsx`
- [ ] No `app.selection` in `ops_*.jsx` files
