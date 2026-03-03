/**
 * ops_core.jsx - SOC Operation Batch Executor
 * Part of Illustrator MCP Standard Library
 * 
 * Provides batch operation execution with:
 * - Stable ID-based targeting
 * - Op validation before execution
 * - Target resolution caching
 * - Strict/continue error modes
 * - Context injection for pure ops
 * 
 * @requires contracts (for ErrorCodes, makeError, validateOpParams)
 * @requires mcp_id (for extractMcpId)
 * @requires geometry (for shape creation helpers)
 * @version 1.1.0
 */

// ==================== Dependency Guard ====================

if (typeof makeError !== "function" || typeof ErrorCodes === "undefined") {
    throw new Error("ops_core.jsx requires contracts.jsx (makeError=" + typeof makeError + ", ErrorCodes=" + typeof ErrorCodes + ")");
}
if (typeof extractMcpId !== "function") {
    throw new Error("ops_core.jsx requires mcp_id.jsx (extractMcpId=" + typeof extractMcpId + ")");
}

// ==================== Op Schema Version ====================

var OP_SCHEMA_VERSION = "1.0.0";

// ==================== UUID Generation ====================

/**
 * Generate a RFC 4122 v4 UUID for stable item references
 * @returns {string} UUID like "mcp_xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx"
 */
function generateUUID() {
    var s = [];
    var hexDigits = "0123456789abcdef";
    for (var i = 0; i < 36; i++) {
        if (i === 8 || i === 13 || i === 18 || i === 23) {
            s[i] = "-";
        } else if (i === 14) {
            s[i] = "4"; // Version 4
        } else if (i === 19) {
            s[i] = hexDigits[(Math.floor(Math.random() * 4) + 8)]; // 8, 9, a, or b
        } else {
            s[i] = hexDigits[Math.floor(Math.random() * 16)];
        }
    }
    return "mcp_" + s.join("");
}

// ==================== Op Handler Registry ====================

var OP_HANDLERS = {};

/**
 * Register an operation handler
 * @param {string} taskName - Op task name (e.g., "element_create")
 * @param {Function} handler - Handler function: (params, targets, ctx) => result
 */
function registerOpHandler(taskName, handler) {
    OP_HANDLERS[taskName] = handler;
}

// ==================== Op Validation ====================

/**
 * Validate a single operation before execution
 * @param {Object} op - Operation: {task, targets?, params?, comment?}
 * @param {boolean} strict - If true, reject unknown keys
 * @returns {Object} {ok: bool, errors: []}
 */
function validateOp(op, strict) {
    var errors = [];

    // Required: task
    if (!op.task || typeof op.task !== "string") {
        errors.push(makeError(
            ErrorCodes.V_INVALID_PAYLOAD,
            "Op missing 'task' string",
            "validate"
        ));
        return { ok: false, errors: errors };
    }

    // Handler must exist
    if (!OP_HANDLERS[op.task]) {
        errors.push(makeError(
            ErrorCodes.V_INVALID_PAYLOAD,
            "Unknown op task: " + op.task,
            "validate"
        ));
        return { ok: false, errors: errors };
    }

    // Params must be object if present
    if (op.params && typeof op.params !== "object") {
        errors.push(makeError(
            ErrorCodes.V_INVALID_PARAM_TYPE,
            "Op 'params' must be an object",
            "validate"
        ));
    }

    // Schema-based param validation (if op_schemas loaded)
    if (typeof validateOpParams === "function") {
        var paramValidation = validateOpParams(op.task, op.params);
        if (!paramValidation.ok) {
            for (var e = 0; e < paramValidation.errors.length; e++) {
                errors.push(paramValidation.errors[e]);
            }
        }
    }

    // Targets validation
    if (op.targets) {
        var targetType = op.targets.type;
        var allowedTypes = ["id", "query", "selection", "layer", "all", "spatial", "compound"];
        var found = false;
        for (var i = 0; i < allowedTypes.length; i++) {
            if (allowedTypes[i] === targetType) { found = true; break; }
        }
        if (!found) {
            errors.push(makeError(
                ErrorCodes.V_UNKNOWN_TARGET_TYPE,
                "Unknown target type: " + targetType,
                "validate"
            ));
        }
    }

    // Strict mode: reject unknown keys
    if (strict) {
        var allowedKeys = ["task", "targets", "params", "comment", "id", "when", "unless"];
        for (var key in op) {
            if (op.hasOwnProperty(key)) {
                var isAllowed = false;
                for (var j = 0; j < allowedKeys.length; j++) {
                    if (allowedKeys[j] === key) { isAllowed = true; break; }
                }
                if (!isAllowed) {
                    errors.push(makeError(
                        ErrorCodes.V_SCHEMA_MISMATCH,
                        "Unknown op key: " + key,
                        "validate"
                    ));
                }
            }
        }
    }

    return { ok: errors.length === 0, errors: errors };
}

/**
 * Generate a cache key for validation deduplication (P3).
 * Two ops with the same task, param keys, param types, and enum values
 * are validation-equivalent — no need to re-run validateOp.
 * @param {Object} op - Operation: {task, params?}
 * @returns {string} Shape key
 */
function validationShapeKey(op) {
    var key = op.task;
    if (!op.params) return key + "::";
    var keys = [];
    for (var k in op.params) {
        if (op.params.hasOwnProperty(k)) keys.push(k);
    }
    keys.sort();
    for (var i = 0; i < keys.length; i++) {
        key += "|" + keys[i] + ":" + getValueType(op.params[keys[i]]);
    }
    // Include enum field values (these affect validation outcome)
    var schema = (typeof getOpSchema === "function") ? getOpSchema(op.task) : null;
    if (schema && schema.enumValues) {
        for (var ek in schema.enumValues) {
            if (schema.enumValues.hasOwnProperty(ek) && op.params[ek] !== undefined) {
                key += "=" + ek + ":" + op.params[ek];
            }
        }
    }
    return key;
}

// ==================== ID-Based Target Resolution ====================
// Delegates to heap.jsx for transactional, identity-verified resolution.
// The heap index ($.global.mcpHeap) persists across batches/chunks.
// Transaction lifecycle (begin/commit/rollback) is managed in executeOpBatch.

/**
 * Extended target resolution with ID support
 * @param {Document} doc - Active document
 * @param {Object} targets - Target selector
 * @param {Object} ctx - Batch context (for caching)
 * @returns {Array<PageItem>} Resolved items
 */
function resolveTargets(doc, targets, ctx) {
    if (!targets) return [];

    // P1: Deprecation warning for selection targeting (removal at v2.0)
    if (targets.type === "selection") {
        if (!ctx.diagnostics.selectionWarnings) ctx.diagnostics.selectionWarnings = 0;
        ctx.diagnostics.selectionWarnings++;
        if (!ctx._selectionWarned) {
            ctx._selectionWarned = true;
            // Warning is surfaced in batch report via diagnostics
        }
    }

    // ID-based targeting (stable) - uses heap for identity-verified O(1) resolution
    if (targets.type === "id") {
        var ids = targets.ids || [];
        var cacheKey = "id:" + ids.join(",");
        if (ctx.cache[cacheKey]) {
            ctx.diagnostics.cacheHits++;
            return ctx.cache[cacheKey];
        }
        ctx.diagnostics.cacheMisses++;
        var items = heapResolveMany(doc, ids);
        ctx.cache[cacheKey] = items;
        return items;
    }

    // Use existing collectTargets for other types
    var cacheKey = JSON.stringify(targets);
    if (ctx.cache[cacheKey]) {
        ctx.diagnostics.cacheHits++;
        return ctx.cache[cacheKey];
    }
    ctx.diagnostics.cacheMisses++;

    var items = collectTargets(doc, targets);
    ctx.cache[cacheKey] = items;
    return items;
}

// ==================== Handler Result Normalizer ====================

/**
 * Normalize handler return value to a consistent shape.
 * Handlers return varying shapes; this centralizes normalization so
 * counting, slimming, and opSummary all consume stable output.
 *
 * Input shapes handled:
 *   - {ok, data: {modified: N}}           (style ops)
 *   - {ok, data: {ids: [...]}}            (element create)
 *   - {ok, data: {createdIds: [...]}}     (batch create)
 *   - {ok, id: "..."}                     (single create)
 *   - raw object / null / undefined       (legacy)
 *
 * Output shape:
 *   {ok, data: {createdIds?, modified?, ...}, warnings, error, id}
 *
 * @param {string} task - Op task name (for diagnostics)
 * @param {*} raw - Handler return value
 * @returns {Object} Normalized result
 */
function normalizeHandlerResult(task, raw) {
    // Null / undefined / non-object → treat as success with no data
    if (!raw || typeof raw !== "object") {
        return { ok: true, data: raw || null, warnings: [], error: null, id: null };
    }

    var norm = {
        ok: raw.ok !== false,
        data: {},
        warnings: raw.warnings || [],
        error: raw.error || null,
        id: raw.id || null
    };

    // Normalize data shape — extract known fields
    var d = raw.data || raw;
    if (typeof d === "object" && d !== null) {
        // Modified count (style, text ops)
        if (typeof d.modified === "number") norm.data.modified = d.modified;
        // Created IDs (element create ops)
        if (d.ids) norm.data.createdIds = d.ids;
        if (d.createdIds) norm.data.createdIds = d.createdIds;
        // Preserve all other data fields as-is
        for (var k in d) {
            if (d.hasOwnProperty(k) && !norm.data.hasOwnProperty(k)
                && k !== "ok" && k !== "warnings" && k !== "error" && k !== "id") {
                norm.data[k] = d[k];
            }
        }
    }

    return norm;
}

// ==================== Rollback Helper (A2) ====================

/**
 * Perform batch rollback: delete created items, restore snapshot or undo.
 * Extracted from executeOpBatch to eliminate duplicated rollback blocks.
 *
 * @param {Document} doc - Active document
 * @param {Object|null} preSnapshot - Pre-execution snapshot (or null)
 * @param {Array} createdIds - MCP IDs of items created during batch
 * @param {number} undoCount - Number of mutating ops to undo (fallback)
 * @param {boolean} useSnapshot - Whether snapshot-based restore is enabled
 * @param {Array|null} trace - Trace log array (or null)
 * @returns {number} Number of items rolled back
 */
function rollbackBatch(doc, preSnapshot, createdIds, undoCount, useSnapshot, trace) {
    var rolledBack = 0;

    if (useSnapshot && preSnapshot && typeof restoreSnapshot === "function") {
        if (trace) trace.push("[ROLLBACK] Restoring from snapshot");

        // Delete created items first (they weren't in the snapshot)
        var createdDeleted = 0;
        if (createdIds.length > 0) {
            var cidSet = {};
            for (var ci = 0; ci < createdIds.length; ci++) cidSet[createdIds[ci]] = true;
            for (var lx = 0; lx < doc.layers.length; lx++) {
                for (var px = doc.layers[lx].pageItems.length - 1; px >= 0; px--) {
                    var pi = doc.layers[lx].pageItems[px];
                    var pm = (pi.note || "").match(/@mcp:id=([^\s]+)/);
                    if (pm && cidSet[pm[1]]) {
                        try { pi.remove(); createdDeleted++; } catch (e) {
                            if (trace) trace.push("[ROLLBACK] Delete failed: " + e.message);
                        }
                    }
                }
            }
            heapRollbackTxn();
        }

        // Restore pre-existing items from snapshot
        try {
            var rr = restoreSnapshot(doc, preSnapshot, { geometry: true, style: true });
            rolledBack = rr.restored + createdDeleted;
            if (trace) trace.push("[ROLLBACK] Restored " + rr.restored + ", deleted " + createdDeleted);
        } catch (e) {
            if (trace) trace.push("[ROLLBACK ERROR] " + e.message);
        }
    } else if (undoCount > 0) {
        // Fallback to undo-based rollback
        if (trace) trace.push("[ROLLBACK] Undoing " + undoCount + " ops");
        for (var u = 0; u < undoCount; u++) {
            try { app.executeMenuCommand("undo"); rolledBack++; } catch (e) { }
        }
    }

    return rolledBack;
}

// ==================== Transaction Helper ====================

/**
 * Execute a function within a snapshot-based transaction.
 * On success: returns {ok: true, result: fn(doc), rolledBack: false}.
 * On failure: restores snapshot, returns {ok: false, error: ..., rolledBack: true}.
 *
 * Usage from execute_script:
 *   var txResult = withTransaction(doc, function(doc) {
 *       // ... multi-step mutations ...
 *       return someValue;
 *   });
 *
 * @param {Document} doc - Explicit document reference (multi-doc safe)
 * @param {Function} fn - Mutation function: (doc) => result
 * @param {Object} [opts] - Options: {mcpOnly: boolean} — default true (fast)
 * @returns {Object} {ok, result?, error?, rolledBack}
 */
function withTransaction(doc, fn, opts) {
    opts = opts || {};
    var snap = captureSnapshot(doc, { mcpOnly: opts.mcpOnly !== false });
    try {
        var result = fn(doc);
        return { ok: true, result: result, rolledBack: false };
    } catch (e) {
        restoreSnapshot(doc, snap, { geometry: true, style: true });
        return {
            ok: false,
            error: makeError(ErrorCodes.R_APPLY_FAILED, e.message, "apply").error,
            rolledBack: true
        };
    }
}

// ==================== Guard Evaluation (C2) ====================

/**
 * Read a property from a PageItem using the bounds-derived allowlist.
 * @param {PageItem} item
 * @param {string} property
 * @returns {Object} Success: {ok: true, value: *}. Failure: {ok: false, error: {code: string, message: string, stage: string}}.
 */
function readGuardProperty(item, property) {
    // Check that item has geometricBounds (PageItem-like)
    if (typeof item.geometricBounds === "undefined") {
        return makeError(ErrorCodes.G_UNKNOWN_PROPERTY,
            "Guard target has no geometricBounds (not a PageItem)", "guard");
    }
    var b = item.geometricBounds; // [left, top, right, bottom]
    switch (property) {
        case "width": return { ok: true, value: b[2] - b[0] };
        case "height": return { ok: true, value: b[1] - b[3] };
        case "left": return { ok: true, value: b[0] };
        case "top": return { ok: true, value: b[1] };
        case "opacity": return { ok: true, value: item.opacity };
        case "name": return { ok: true, value: item.name };
        case "locked": return { ok: true, value: item.locked };
        case "typename": return { ok: true, value: item.typename };
        default:
            return makeError(ErrorCodes.G_UNKNOWN_PROPERTY,
                "Unknown guard property '" + property + "'. Allowed: width, height, left, top, opacity, name, locked, typename",
                "guard");
    }
}

/**
 * Evaluate a single comparator against a value.
 * @param {*} value - The actual property value
 * @param {string} comparator - eq/neq/gt/gte/lt/lte/contains/matches
 * @param {*} expected - The expected value from the guard
 * @returns {{ok: boolean, result: boolean, error: Object}}
 */
function evalComparator(value, comparator, expected) {
    // Numeric comparators require numeric value
    var numericOps = { gt: true, gte: true, lt: true, lte: true };
    if (numericOps[comparator]) {
        if (typeof value !== "number" || typeof expected !== "number") {
            return makeError(ErrorCodes.G_INVALID_COMPARATOR,
                "Comparator '" + comparator + "' requires numeric values, got " + typeof value + " vs " + typeof expected,
                "guard");
        }
    }
    switch (comparator) {
        case "eq": return { ok: true, result: value === expected };
        case "neq": return { ok: true, result: value !== expected };
        case "gt": return { ok: true, result: value > expected };
        case "gte": return { ok: true, result: value >= expected };
        case "lt": return { ok: true, result: value < expected };
        case "lte": return { ok: true, result: value <= expected };
        case "contains":
            if (typeof value !== "string") {
                return makeError(ErrorCodes.G_INVALID_COMPARATOR,
                    "'contains' requires string value, got " + typeof value, "guard");
            }
            return { ok: true, result: value.indexOf(String(expected)) !== -1 };
        case "matches":
            if (typeof value !== "string") {
                return makeError(ErrorCodes.G_INVALID_COMPARATOR,
                    "'matches' requires string value, got " + typeof value, "guard");
            }
            try {
                var rx = new RegExp(String(expected));
                return { ok: true, result: rx.test(value) };
            } catch (e) {
                return makeError(ErrorCodes.G_INVALID_COMPARATOR,
                    "Invalid regex pattern: " + expected, "guard");
            }
        default:
            return makeError(ErrorCodes.G_INVALID_COMPARATOR,
                "Unknown comparator '" + comparator + "'. Allowed: eq, neq, gt, gte, lt, lte, contains, matches",
                "guard");
    }
}

/**
 * Validate guard structure and extract comparator + expected value.
 * @param {Object} guard - The when/unless guard object
 * @returns {{ok: boolean, property: string, comparator: string, expected: *, error: Object}}
 */
function validateGuard(guard) {
    if (!guard || typeof guard !== "object") {
        return makeError(ErrorCodes.G_MALFORMED, "Guard must be an object", "guard");
    }
    if (!guard.property || typeof guard.property !== "string") {
        return makeError(ErrorCodes.G_MALFORMED, "Guard missing 'property' string", "guard");
    }
    // Find the comparator key (the key that isn't 'property')
    var COMPARATORS = { eq: 1, neq: 1, gt: 1, gte: 1, lt: 1, lte: 1, contains: 1, matches: 1 };
    var comparator = null;
    var expected = undefined;
    for (var k in guard) {
        if (guard.hasOwnProperty(k) && k !== "property" && COMPARATORS[k]) {
            comparator = k;
            expected = guard[k];
            break;
        }
    }
    if (!comparator) {
        return makeError(ErrorCodes.G_MALFORMED,
            "Guard missing comparator. Use one of: eq, neq, gt, gte, lt, lte, contains, matches",
            "guard");
    }
    return { ok: true, property: guard.property, comparator: comparator, expected: expected };
}

/**
 * Filter targets by a when/unless guard. Per-target evaluation.
 * @param {Array} targets - Resolved PageItems
 * @param {Object} guard - The guard predicate
 * @param {boolean} isUnless - true for unless (invert), false for when
 * @returns {{ok: boolean, targets: Array, error: Object}}
 */
function filterByGuard(targets, guard, isUnless) {
    var parsed = validateGuard(guard);
    if (!parsed.ok) return parsed;

    var filtered = [];
    for (var i = 0; i < targets.length; i++) {
        var propResult = readGuardProperty(targets[i], parsed.property);
        if (!propResult.ok) return propResult;  // Hard error for non-PageItem or unknown prop

        var cmpResult = evalComparator(propResult.value, parsed.comparator, parsed.expected);
        if (!cmpResult.ok) return cmpResult;  // Hard error for type mismatch

        // when: keep if true; unless: keep if false
        var keep = isUnless ? !cmpResult.result : cmpResult.result;
        if (keep) filtered.push(targets[i]);
    }
    return { ok: true, targets: filtered };
}

// ==================== Sub-Op Execution (C1) ====================

// ==================== Op Classification (3-tier) ====================
// "doc"     = participates in Illustrator undo stack → counted for rollback
// "session" = changes app state (not geometry) → logged, not undo-counted
// default   = "readonly" (assert_*, measure_*, snapshot_*, hash_*)
var OP_CLASS = {
    "element_create": "doc", "element_create_multi": "doc",
    "element_create_multi_by_ref": "doc", "element_create_batch": "doc",
    "element_modify": "doc", "element_delete": "doc", "element_replace": "doc",
    "style_set_fill": "doc", "style_set_stroke": "doc", "style_set_opacity": "doc",
    "style_remove_fill": "doc", "style_remove_stroke": "doc",
    "style_clone": "doc", "style_set_gradient": "doc",
    "group_create": "doc", "group_ungroup": "doc", "clip_create": "doc",
    "zorder_front": "doc", "zorder_back": "doc",
    "zorder_forward": "doc", "zorder_backward": "doc",
    "text_create": "doc", "text_set_content": "doc", "text_set_style": "doc",
    "align_horizontal": "doc", "align_vertical": "doc",
    "distribute_horizontal": "doc", "distribute_vertical": "doc",
    "compound": "doc",
    "layer_create": "doc", "layer_delete": "doc",
    "layer_lock": "doc", "layer_visible": "doc",
    "layer_activate": "session"
};

// Dedupe cache: warn once per unknown task name
var _OP_CLASS_WARNED = {};

/**
 * Get classification for an op task.
 * @param {string} task - Op task name
 * @param {Object} [ctx] - Batch context (for warnings)
 * @returns {string} "doc", "session", or "readonly"
 */
function getOpClass(task, ctx) {
    var cls = OP_CLASS[task];
    if (!cls && OP_HANDLERS[task] && !_OP_CLASS_WARNED[task]) {
        _OP_CLASS_WARNED[task] = true;
        if (ctx && ctx.warn) {
            ctx.warn("OP_CLASS: '" + task + "' has handler but no classification → readonly");
        }
    }
    return cls || "readonly";
}

/**
 * Execute sub-ops within an existing context. Does NOT start/commit heap txn.
 * Used by executeOpBatch for the main loop AND by compound handler for sub-ops.
 *
 * @param {Array} ops - Operations to execute
 * @param {Object} ctx - Existing execution context (inherited)
 * @param {Object} mode - Execution mode:
 *   mode.strict    — stop on first error
 *   mode.rollback  — undo completed ops on failure (requires strict)
 *   mode.snapshot  — use snapshot-based rollback (preferred over undo)
 *   mode.doc       — active document
 *   mode.preSnapshot — pre-captured snapshot (if any)
 *   mode.trace     — trace array (or null)
 *   mode.chunkSize — progress chunk size (0 = disabled)
 *   mode.onProgress — progress callback
 * @returns {Object} {ok, results[], createdIds[], passed, failed, undoCount, rolledBackCount}
 */
function executeSubOps(ops, ctx, mode) {
    var doc = mode.doc;
    var strict = mode.strict || false;
    var rollback = mode.rollback || false;
    var useSnapshot = mode.snapshot || false;
    var trace = mode.trace || null;
    var chunkSize = mode.chunkSize || 0;
    var onProgress = mode.onProgress || null;
    var preSnapshot = mode.preSnapshot || null;

    var results = [];
    var passed = 0;
    var failed = 0;
    var undoCount = 0;
    var createdIds = [];
    var rolledBackCount = 0;


    var chunkIndex = 0;

    for (var i = 0; i < ops.length; i++) {
        var op = ops[i];
        var t0 = ctx.clock();

        if (trace) trace.push("[OP " + i + "] " + op.task);

        // JIT validation (P3): validate just before execution, with shape dedup
        var shapeKey = validationShapeKey(op);
        if (!ctx.validationCache[shapeKey]) {
            ctx.validationCache[shapeKey] = validateOp(op, mode.strictSchema);
            ctx.diagnostics.validationsRun++;
        } else {
            ctx.diagnostics.validationsSkipped++;
        }
        var cachedValidation = ctx.validationCache[shapeKey];
        if (!cachedValidation.ok) {
            results.push({
                index: i,
                task: op.task,
                ok: false,
                duration_ms: ctx.clock() - t0,
                targets_resolved: 0,
                id: op.params ? op.params.id : null,
                data: null,
                warnings: [],
                error: cachedValidation.errors[0]
            });
            failed++;
            if (strict) break;
            continue;
        }

        var handler = OP_HANDLERS[op.task];
        var targets = op.targets ? resolveTargets(doc, op.targets, ctx) : [];

        // C2: Guard evaluation — filter targets by when/unless predicates
        var guardSkipped = false;
        if (op.when || op.unless) {
            if (op.when && op.unless) {
                // B15: opResult not yet initialized here (var hoisted as undefined).
                // Route warning through ctx so it appears in batch report.warnings.
                ctx.warn("Op has both 'when' and 'unless'; 'when' takes precedence. (op " + i + ")");
            }
            var guard = op.when || op.unless;
            var isUnless = !!op.unless;
            var guardResult = filterByGuard(targets, guard, isUnless);
            if (!guardResult.ok) {
                // Guard error (G001/G002/G003) — treat as op failure
                results.push({
                    index: i,
                    task: op.task,
                    ok: false,
                    duration_ms: ctx.clock() - t0,
                    targets_resolved: targets.length,
                    id: op.params ? op.params.id : null,
                    data: null,
                    warnings: [],
                    error: guardResult.error
                });
                failed++;
                if (strict) break;
                continue;
            }
            targets = guardResult.targets;
            if (targets.length === 0) {
                // All targets filtered out — skip op
                results.push({
                    index: i,
                    task: op.task,
                    ok: true,
                    skipped: true,
                    duration_ms: ctx.clock() - t0,
                    targets_resolved: 0,
                    id: op.params ? op.params.id : null,
                    data: { reason: "guard_filtered" },
                    warnings: [],
                    error: null
                });
                passed++;
                continue;
            }
        }

        var opResult = {
            index: i,
            task: op.task,
            ok: false,
            duration_ms: 0,
            targets_resolved: targets.length,
            id: op.params ? op.params.id : null,
            data: null,
            warnings: [],
            error: null
        };

        try {
            // P3: Resolve field descriptors in params before handler sees them
            var resolvedParams = op.params || {};
            var handlerResult;
            var hasFieldDescs = typeof resolveFields === "function" &&
                typeof containsFields === "function" && containsFields(resolvedParams);

            if (hasFieldDescs && targets.length > 0) {
                // Fan-out: call handler once per target with per-target resolved params
                var fanOk = true;
                var fanData = [];
                var fanWarnings = [];
                var fanId = null;
                var fanError = null;
                for (var t = 0; t < targets.length; t++) {
                    var perTargetParams = resolveFields(resolvedParams, targets[t], t, targets.length, ctx);
                    var singleResult = handler(perTargetParams, [targets[t]], ctx);
                    // Normalize unconditionally — guaranteed shape: {ok, data, warnings, error, id}
                    singleResult = normalizeHandlerResult(op.task, singleResult);
                    if (singleResult.ok === false) {
                        fanOk = false;
                        if (!fanError) fanError = singleResult.error;
                    }
                    fanData.push(singleResult.data);
                    fanWarnings = fanWarnings.concat(singleResult.warnings);
                    if (singleResult.id && !fanId) fanId = singleResult.id;
                }
                handlerResult = { ok: fanOk, data: { perTarget: fanData, count: targets.length }, warnings: fanWarnings, id: fanId, error: fanError };
            } else {
                if (typeof resolveFields === "function") {
                    resolvedParams = resolveFields(resolvedParams, targets[0] || null, 0, targets.length || 1, ctx);
                }
                handlerResult = handler(resolvedParams, targets, ctx);
            }

            // Normalize handler result via centralised normalizer
            handlerResult = normalizeHandlerResult(op.task, handlerResult);
            opResult.ok = handlerResult.ok;
            if (!opResult.ok) {
                opResult.error = handlerResult.error;
                if (!opResult.error && handlerResult.data && handlerResult.data.message) {
                    opResult.error = { code: "R_UNSTRUCTURED", message: handlerResult.data.message, stage: "apply" };
                }
                opResult.data = null;
            } else {
                opResult.data = handlerResult.data;
                opResult.warnings = handlerResult.warnings;
                opResult.id = handlerResult.id || opResult.id;
            }

            if (opResult.ok) {
                passed++;
                var _batchIds = opResult.data && (opResult.data.ids || opResult.data.createdIds);
                if (_batchIds && typeof _batchIds.length === "number" && _batchIds.length > 0) {
                    for (var mi = 0; mi < _batchIds.length; mi++) createdIds.push(_batchIds[mi]);
                } else if (opResult.id) {
                    createdIds.push(opResult.id);
                }
                if (getOpClass(op.task, ctx) === "doc") {
                    undoCount++;
                }
            } else {
                failed++;
                if (strict) {
                    opResult.duration_ms = ctx.clock() - t0;
                    results.push(opResult);
                    if (rollback) {
                        rolledBackCount = rollbackBatch(doc, preSnapshot, createdIds, undoCount, useSnapshot, trace);
                    }
                    break;
                }
            }

        } catch (e) {
            opResult.ok = false;
            opResult.error = makeError(
                ErrorCodes.R_APPLY_FAILED,
                e.message,
                "apply",
                null,
                { line: e.line || null, task: op.task, opIndex: i }
            ).error;
            failed++;

            if (strict) {
                opResult.duration_ms = ctx.clock() - t0;
                results.push(opResult);
                if (rollback) {
                    rolledBackCount = rollbackBatch(doc, preSnapshot, createdIds, undoCount, useSnapshot, trace);
                }
                break;
            }
        }

        opResult.duration_ms = ctx.clock() - t0;
        results.push(opResult);

        // Progress callback
        if (chunkSize > 0 && onProgress && results.length % chunkSize === 0) {
            var chunkReport = {
                chunkIndex: chunkIndex++,
                opsCompleted: results.length,
                opsTotal: ops.length,
                passed: passed,
                failed: failed,
                lastOp: op.task,
                percentComplete: Math.round((results.length / ops.length) * 100)
            };
            try {
                onProgress(chunkReport);
            } catch (cbErr) {
                if (trace) trace.push("[PROGRESS ERROR] " + cbErr.message);
            }
            if (trace) trace.push("[CHUNK " + (chunkIndex - 1) + "] " + results.length + "/" + ops.length);
        }
    }

    return {
        ok: failed === 0,
        results: results,
        createdIds: createdIds,
        passed: passed,
        failed: failed,
        undoCount: undoCount,
        rolledBackCount: rolledBackCount
    };
}

// ── Field naming glossary ──────────────────────────────────────────
// Internal (executeSubOps return): "results"  — per-op result objects
// External (batch report):         "ops"      — same data, renamed for API consumers
// Reason: "results" is an implementation name; "ops" matches the input array name
//         and is the documented API surface (see Batch Report Contract above).

// ==================== Batch Execution ====================

/**
 * Execute a batch of operations
 *
 * Batch Report Contract:
 *   report.ok            — true if all ops passed
 *   report.createdIds    — flat list of ALL created MCP IDs
 *                          (from opResult.id + opResult.data.ids + opResult.data.createdIds)
 *   report.ops[i].id     — singular ID (element_create, layer_create)
 *   report.ops[i].data   — handler-specific data
 *                          (element_create_multi → {ids[], created, skipped, stylingMode})
 *   report.stats         — {total, executed, passed, failed, failedAtIndex}
 *
 * Journal Entry Schema (written when options.journal === true):
 *   entry.ops            — serialized op list (task/params/targets only)
 *   entry.createdIds     — full ID list (for replay cleanup)
 *   entry.report         — {ok, stats} summary
 *
 * @param {Array<Object>} ops - Array of operations
 * @param {Object} options - Execution options
 * @param {string} options.space.units - Coordinate units ("pt", "mm")
 * @param {string} options.space.origin - Origin ("document", "artboard")
 * @param {string} options.space.yAxis - Y-axis direction ("down", "up")
 * @param {boolean} options.strict - Stop on first error
 * @param {boolean} options.stopOnError - Alias for strict
 * @param {boolean} options.rollback - Undo all completed ops on failure (requires strict)
 * @param {boolean} options.snapshot - Capture state before execution for snapshot-based rollback (preferred over undo)
 * @param {number} options.chunkSize - Emit progress every N ops (0 = disabled)
 * @param {Function} options.onProgress - Progress callback (receives chunk report)
 * @param {boolean} options.trace - Include execution trace
 * @param {boolean} options.summaryOnly - Omit per-op details, return only stats+createdIds (reduces token usage)
 * @param {boolean} options.journal - Record ops to journal for replay (P6)
 * @param {Object} options.recompute - Replay journal from scratch: {confirm: true, snapshotFirst: true}
 * @returns {Object} Batch report
 */
function executeOpBatch(ops, options) {
    options = options || {};
    var strict = options.strict || options.stopOnError || false;
    var rollback = options.rollback === true;
    var useSnapshot = options.snapshot === true;
    var chunkSize = options.chunkSize || 0;
    var onProgress = options.onProgress || null;
    var trace = options.trace ? [] : null;
    var summaryOnly = options.summaryOnly === true;
    var journalEnabled = options.journal === true;
    var createdIds = [];  // Track created element IDs for summaryOnly mode
    var preSnapshot = null;  // Pre-execution snapshot for rollback

    // Check for active document
    var doc = null;
    try { doc = app.activeDocument; } catch (e) { }
    if (!doc) {
        return {
            ok: false,
            errors: [makeError(ErrorCodes.V_NO_DOCUMENT, "No active document", "validate")],
            ops: [],
            stats: { total: ops.length, passed: 0, failed: ops.length }
        };
    }

    // Build execution context (injected into handlers)
    // P2: clock is injectable for testability; isolates Date impurity
    var ctx = {
        doc: doc,
        app: app,
        clock: options.clock || function () { return new Date().getTime(); },
        cache: {},
        validationCache: {},
        options: options,
        space: options.space || { units: "pt", origin: "document", yAxis: "down" },
        defaultLayer: options.defaultLayer || null,
        warnings: [],
        // Diagnostics counters
        diagnostics: {
            cacheHits: 0,
            cacheMisses: 0,
            validationsRun: 0,
            validationsSkipped: 0,
            selectionWarnings: 0
        },
        compoundDepth: 0
    };
    ctx.warn = function (msg) { ctx.warnings.push(msg); };

    // Begin heap transaction for this batch (pass doc to avoid redundant lookup)
    var heapBatchId = generateUUID();
    heapBeginTxn(heapBatchId, doc);

    // === RECOMPUTE GATE (P6) ===
    // Requires explicit confirmation + takes snapshot before clearing
    if (options.recompute) {
        if (!options.recompute.confirm || options.recompute.snapshotFirst !== true) {
            heapRollbackTxn();  // F1: close txn opened at L853
            return {
                ok: false,
                errors: [makeError(ErrorCodes.V_INVALID_PARAMS,
                    "recompute requires {confirm: true, snapshotFirst: true}", "validate")],
                ops: [],
                stats: { total: 0, passed: 0, failed: 0 }
            };
        }

        var docName = doc.name;
        var journal = (typeof journalGet === "function") ? journalGet(docName, doc) : [];
        if (journal.length === 0) {
            heapRollbackTxn();  // F1: close txn opened at L853
            return {
                ok: false,
                errors: [makeError(ErrorCodes.V_INVALID_PARAMS,
                    "recompute: no journal entries for '" + docName + "'", "validate")],
                ops: [],
                stats: { total: 0, passed: 0, failed: 0 }
            };
        }

        // Snapshot before clearing
        var recomputeSnapshot = null;
        if (typeof captureSnapshot === "function") {
            recomputeSnapshot = captureSnapshot(doc, { mcpOnly: true, clock: ctx.clock });
        }

        // Clear all MCP-created items
        try {
            for (var li = 0; li < doc.layers.length; li++) {
                var layer = doc.layers[li];
                for (var pi = layer.pageItems.length - 1; pi >= 0; pi--) {
                    var item = layer.pageItems[pi];
                    if (item.note && item.note.indexOf("@mcp:id=") >= 0) {
                        item.remove();
                    }
                }
            }
        } catch (clearErr) {
            // Restore on clear failure
            if (recomputeSnapshot && typeof restoreSnapshot === "function") {
                restoreSnapshot(doc, recomputeSnapshot, { geometry: true, style: true, restoreSize: true });
            }
            return {
                ok: false,
                errors: [makeError(ErrorCodes.E_EXECUTION, "recompute: clear failed: " + clearErr.message, "execute")],
                ops: [],
                stats: { total: 0, passed: 0, failed: 0, failedAtIndex: null }
            };
        }

        // Replay journal
        var replayResult = (typeof journalReplay === "function")
            ? journalReplay(doc, journal, { onError: "strict", clock: (options.clock || function () { return new Date().getTime(); }) })
            : makeError(ErrorCodes.E_EXECUTION, "journalReplay not available", "apply");

        if (!replayResult.ok && recomputeSnapshot && typeof restoreSnapshot === "function") {
            // Replay failed â€” restore from pre-recompute snapshot
            restoreSnapshot(doc, recomputeSnapshot, { geometry: true, style: true, restoreSize: true });
            replayResult.data.rolledBack = true;
        }

        return replayResult;
    }

    // === EXECUTION PHASE (with JIT validation, P3) ===
    if (trace) trace.push("[EXECUTE] Running " + ops.length + " ops (JIT validation)");

    // Capture snapshot before execution if enabled (for snapshot-based rollback)
    if (useSnapshot && rollback && typeof captureSnapshot === "function") {
        try {
            preSnapshot = captureSnapshot(doc, { mcpOnly: true, clock: ctx.clock });
            if (trace) trace.push("[SNAPSHOT] Captured " + preSnapshot.items.length + " items");
        } catch (snapErr) {
            if (trace) trace.push("[SNAPSHOT ERROR] " + snapErr.message);
        }
    }

    // C1: Delegate to executeSubOps — single source of truth for per-op execution
    var subResult = executeSubOps(ops, ctx, {
        strict: strict,
        rollback: rollback,
        snapshot: useSnapshot,
        strictSchema: options.strictSchema,
        doc: doc,
        preSnapshot: preSnapshot,
        trace: trace,
        chunkSize: chunkSize,
        onProgress: onProgress
    });

    var results = subResult.results;
    var passed = subResult.passed;
    var failed = subResult.failed;
    var createdIds = subResult.createdIds;
    var rolledBackCount = subResult.rolledBackCount;

    // Final chunk if not aligned
    if (chunkSize > 0 && onProgress && results.length % chunkSize !== 0) {
        try {
            onProgress({
                chunkIndex: Math.floor(results.length / chunkSize),
                opsCompleted: results.length,
                opsTotal: ops.length,
                passed: passed,
                failed: failed,
                isFinal: true,
                percentComplete: 100
            });
        } catch (cbErr) {
            if (trace) trace.push("[PROGRESS ERROR] " + cbErr.message);
        }
    }

    // === BUILD REPORT ===
    var allOk = failed === 0;
    var totalMs = results.reduce(function (sum, r) { return sum + r.duration_ms; }, 0);

    // P1: Surface handler warnings + deprecation warnings in report
    var reportWarnings = ctx.warnings ? ctx.warnings.slice() : [];
    // Aggregate per-op handler warnings into report-level warnings
    for (var rwi = 0; rwi < results.length; rwi++) {
        if (results[rwi].warnings && results[rwi].warnings.length > 0) {
            for (var rwj = 0; rwj < results[rwi].warnings.length; rwj++) {
                reportWarnings.push(results[rwi].warnings[rwj]);
            }
        }
    }
    if (ctx.diagnostics.selectionWarnings > 0) {
        reportWarnings.push("DEPRECATED: 'selection' targeting used " + ctx.diagnostics.selectionWarnings + "x. Use 'id' targeting. Removal at v2.0.");
    }

    // Find first failed op index for quick debugging
    var failedAtIndex = null;
    for (var fi = 0; fi < results.length; fi++) {
        if (!results[fi].ok) { failedAtIndex = results[fi].index; break; }
    }

    // === JOURNAL RECORDING (P6) — runs for BOTH summary and full reports ===
    // Uses internal results[] array, not the returned report, so journal
    // always has full detail even when summaryOnly omits per-op data.
    if (journalEnabled && typeof journalAppend === "function") {
        var batchId = (typeof generateUUID === "function") ? generateUUID() : ("batch_" + ctx.clock());
        // Strip ops to just task/params/targets (no resolved items)
        var journalOps = [];
        for (var j = 0; j < ops.length; j++) {
            journalOps.push({
                task: ops[j].task,
                params: ops[j].params,
                targets: ops[j].targets
            });
        }
        journalAppend({
            batchId: batchId,
            timestamp: ctx.clock(),
            ops: journalOps,
            createdIds: createdIds,
            generatorMeta: options.generatorMeta || undefined,
            options: { strict: strict, rollback: rollback, snapshot: useSnapshot },
            report: { ok: allOk, stats: { total: ops.length, passed: passed, failed: failed } }
        }, doc.name, doc);
    }

    // Commit heap transaction: persist index mutations from this batch
    var heapStats = heapCommitTxn();
    ctx.diagnostics.heapStats = heapDiagnostics();
    ctx.diagnostics.heapCommit = heapStats;

    // Gate redraw on actual DOM mutations (redraw is expensive)
    if (passed > 0) {
        app.redraw();
    }

    // summaryOnly mode: omit per-op details to reduce token usage
    if (summaryOnly) {
        return {
            ok: allOk,
            schemaVersion: OP_SCHEMA_VERSION,
            summaryOnly: true,
            rolledBack: rolledBackCount,
            createdIds: createdIds,
            stats: {
                total: ops.length,
                executed: results.length,
                passed: passed,
                failed: failed,
                failedAtIndex: failedAtIndex
            },
            timing: { total_ms: totalMs },
            diagnostics: ctx.diagnostics,
            warnings: reportWarnings.length > 0 ? reportWarnings : undefined,
            errors: (function () {
                var errs = [];
                for (var ei = 0; ei < results.length; ei++) {
                    if (!results[ei].ok) errs.push({ index: results[ei].index, task: results[ei].task, error: results[ei].error });
                }
                return errs.length > 0 ? errs : undefined;
            })(),
            trace: trace
        };
    }

    return {
        ok: allOk,
        schemaVersion: OP_SCHEMA_VERSION,
        rolledBack: rolledBackCount,
        createdIds: createdIds,
        ops: results,
        stats: {
            total: ops.length,
            executed: results.length,
            passed: passed,
            failed: failed,
            failedAtIndex: failedAtIndex
        },
        timing: { total_ms: totalMs },
        diagnostics: ctx.diagnostics,
        warnings: reportWarnings.length > 0 ? reportWarnings : undefined,
        trace: trace
    };
}

// ==================== Profiling Utility ====================

/**
 * Profile a function execution
 * @param {string} label
 * @param {Function} fn
 * @returns {Object} {result, duration_ms}
 */
function profileOp(label, fn, clock) {
    var now = clock || function () { return new Date().getTime(); };
    var t0 = now();
    var result = fn();
    var t1 = now();
    return { result: result, duration_ms: t1 - t0, label: label };
}

