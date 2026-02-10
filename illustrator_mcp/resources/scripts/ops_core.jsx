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
 * @requires task_executor (for ErrorCodes, makeError, collectTargets, etc.)
 * @requires geometry (for shape creation helpers)
 * @version 1.0.0
 */

// ==================== Dependency Guard ====================

if (typeof makeError !== "function" || typeof ErrorCodes === "undefined") {
    throw new Error("ops_core.jsx requires task_executor.jsx (makeError=" + typeof makeError + ", ErrorCodes=" + typeof ErrorCodes + ")");
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
        var allowedTypes = ["id", "query", "selection", "layer", "all"];
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
        var allowedKeys = ["task", "targets", "params", "comment", "id"];
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

// ==================== ID-Based Target Resolution ====================

// Initialize global ID index cache (persists across batch calls)
if (!$.global.mcpIdIndex) {
    $.global.mcpIdIndex = { docName: null, index: {} };
}

/**
 * Invalidate the global ID index cache.
 * Called automatically at the end of every executeOpBatch.
 *
 * IMPORTANT: You MUST call this manually after any DOM changes
 * made outside executeOpBatch (e.g., direct item.remove(),
 * layer manipulation, or test cleanup). Failure to do so causes
 * target resolution to use a stale index, silently targeting
 * wrong or removed items.
 */
function invalidateIdIndex() {
    $.global.mcpIdIndex = { docName: null, index: {} };
}

/**
 * Register a new ID in the global index (for newly created elements).
 * @param {string} id - Element ID
 * @param {PageItem} item - The element
 */
function registerIdInIndex(id, item) {
    if ($.global.mcpIdIndex && $.global.mcpIdIndex.index) {
        $.global.mcpIdIndex.index[id] = item;
    }
}

/**
 * Build ID index for O(1) lookups.
 * Uses $.global for persistence across batches within the same session.
 * Automatically invalidates if document changes.
 * @param {Document} doc - Active document
 * @param {Object} ctx - Batch context (for diagnostics)
 * @returns {Object} ID index {id: item}
 */
function buildIDIndex(doc, ctx) {
    // Check if we already have a valid global index for this document
    var docName = doc.name;
    if ($.global.mcpIdIndex.docName === docName && $.global.mcpIdIndex.index) {
        ctx.diagnostics.idIndexCacheHit = true;
        // Also store in ctx for backward compatibility
        ctx.idIndex = $.global.mcpIdIndex.index;
        return ctx.idIndex;
    }

    // Need to rebuild index
    var index = {};
    var maxDepth = 100; // Prevent infinite recursion

    function scan(container, depth) {
        if (depth > maxDepth) return;
        if (!container || !container.pageItems) return;

        for (var i = 0; i < container.pageItems.length; i++) {
            var item = container.pageItems[i];
            try {
                if (item.note) {
                    var match = item.note.match(/@mcp:id=([^\s@]+)/);
                    if (match) {
                        index[match[1]] = item;
                    }
                }
            } catch (e) { }
            if (item.typename === "GroupItem") {
                scan(item, depth + 1);
            }
        }
    }

    for (var i = 0; i < doc.layers.length; i++) {
        scan(doc.layers[i], 0);
    }

    // Store in global cache
    $.global.mcpIdIndex = { docName: docName, index: index };
    ctx.idIndex = index;
    ctx.diagnostics.idScans++;
    ctx.diagnostics.idIndexCacheHit = false;
    return index;
}

/**
 * Resolve targets by ID using index (O(1) per ID)
 * @param {Document} doc - Active document
 * @param {Array<string>} ids - Array of item IDs to find
 * @param {Object} ctx - Batch context (for index)
 * @returns {Array<PageItem>} Found items
 */
function resolveById(doc, ids, ctx) {
    var index = buildIDIndex(doc, ctx);
    var items = [];
    for (var i = 0; i < ids.length; i++) {
        if (index[ids[i]]) {
            items.push(index[ids[i]]);
        }
    }
    return items;
}

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

    // ID-based targeting (stable) - uses index
    if (targets.type === "id") {
        var ids = targets.ids || [];
        var cacheKey = "id:" + ids.join(",");
        if (ctx.cache[cacheKey]) {
            ctx.diagnostics.cacheHits++;
            return ctx.cache[cacheKey];
        }
        ctx.diagnostics.cacheMisses++;
        var items = resolveById(doc, ids, ctx); // Pass ctx for index
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
        options: options,
        space: options.space || { units: "pt", origin: "document", yAxis: "down" },
        // Diagnostics counters
        diagnostics: {
            cacheHits: 0,
            cacheMisses: 0,
            idScans: 0,
            selectionWarnings: 0
        }
    };

    // === RECOMPUTE GATE (P6) ===
    // Requires explicit confirmation + takes snapshot before clearing
    if (options.recompute) {
        if (!options.recompute.confirm || options.recompute.snapshotFirst !== true) {
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
            : { ok: false, data: { error: "journalReplay not available" } };

        if (!replayResult.ok && recomputeSnapshot && typeof restoreSnapshot === "function") {
            // Replay failed â€” restore from pre-recompute snapshot
            restoreSnapshot(doc, recomputeSnapshot, { geometry: true, style: true, restoreSize: true });
            replayResult.data.rolledBack = true;
        }

        return replayResult;
    }

    // === VALIDATION PHASE ===
    if (trace) trace.push("[VALIDATE] Checking " + ops.length + " ops");

    var validationErrors = [];
    for (var i = 0; i < ops.length; i++) {
        var validation = validateOp(ops[i], options.strictSchema);
        if (!validation.ok) {
            validationErrors = validationErrors.concat(validation.errors);
            if (strict) break;
        }
    }

    if (validationErrors.length > 0) {
        return {
            ok: false,
            errors: validationErrors,
            ops: [],
            stats: { total: ops.length, passed: 0, failed: validationErrors.length, failedAtIndex: 0 }
        };
    }

    // === EXECUTION PHASE ===
    if (trace) trace.push("[EXECUTE] Running " + ops.length + " ops");

    // Capture snapshot before execution if enabled (for snapshot-based rollback)
    if (useSnapshot && rollback && typeof captureSnapshot === "function") {
        try {
            preSnapshot = captureSnapshot(doc, { mcpOnly: true, clock: ctx.clock });
            if (trace) trace.push("[SNAPSHOT] Captured " + preSnapshot.items.length + " items");
        } catch (snapErr) {
            if (trace) trace.push("[SNAPSHOT ERROR] " + snapErr.message);
        }
    }

    var results = [];
    var passed = 0;
    var failed = 0;

    // Rollback tracking: count mutating ops that complete successfully
    var undoCount = 0;
    var MUTATING_OPS = {
        "element_create": true, "element_modify": true, "element_delete": true,
        "style_set_fill": true, "style_set_stroke": true, "style_set_opacity": true,
        "style_remove_fill": true, "style_remove_stroke": true,
        "layer_create": true, "layer_delete": true, "layer_lock": true, "layer_visible": true,
        "group_create": true, "group_ungroup": true,
        "zorder_front": true, "zorder_back": true, "zorder_forward": true, "zorder_backward": true,
        "text_create": true, "text_set_content": true, "text_set_style": true,
        "align_horizontal": true, "align_vertical": true,
        "distribute_horizontal": true, "distribute_vertical": true
    };

    // Progress tracking
    var chunkIndex = 0;
    var rolledBackCount = 0;

    for (var i = 0; i < ops.length; i++) {
        var op = ops[i];
        var t0 = ctx.clock();

        if (trace) trace.push("[OP " + i + "] " + op.task);

        var handler = OP_HANDLERS[op.task];
        var targets = op.targets ? resolveTargets(doc, op.targets, ctx) : [];

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
                var fanError = null;  // Capture first error for propagation
                for (var t = 0; t < targets.length; t++) {
                    var perTargetParams = resolveFields(resolvedParams, targets[t], t, targets.length, ctx);
                    var singleResult = handler(perTargetParams, [targets[t]], ctx);
                    if (singleResult && typeof singleResult === "object") {
                        if (singleResult.ok === false) {
                            fanOk = false;
                            // Capture nested error from makeError shape
                            if (!fanError && singleResult.error) fanError = singleResult.error;
                        }
                        fanData.push(singleResult.data || singleResult);
                        if (singleResult.warnings) fanWarnings = fanWarnings.concat(singleResult.warnings);
                        if (singleResult.id && !fanId) fanId = singleResult.id;
                    } else {
                        fanData.push(singleResult);
                    }
                }
                handlerResult = { ok: fanOk, data: { perTarget: fanData, count: targets.length }, warnings: fanWarnings, id: fanId, error: fanError };
            } else {
                if (typeof resolveFields === "function") {
                    resolvedParams = resolveFields(resolvedParams, targets[0] || null, 0, targets.length || 1, ctx);
                }
                handlerResult = handler(resolvedParams, targets, ctx);
            }

            // Normalize handler result
            if (handlerResult && typeof handlerResult === "object") {
                opResult.ok = handlerResult.ok !== false;
                if (!opResult.ok) {
                    // Extract nested error (makeError returns {ok:false, error:{...}})
                    opResult.error = handlerResult.error || handlerResult;
                    opResult.data = null;
                } else {
                    opResult.data = handlerResult.data || handlerResult;
                    opResult.warnings = handlerResult.warnings || [];
                    opResult.id = handlerResult.id || opResult.id;
                }
            } else {
                opResult.ok = true;
                opResult.data = handlerResult;
            }

            if (opResult.ok) {
                passed++;
                // Track created element IDs — support all return shapes
                var _batchIds = opResult.data && (opResult.data.ids || opResult.data.createdIds);
                if (_batchIds && typeof _batchIds.length === "number" && _batchIds.length > 0) {
                    // Multi-create ops (element_create_multi) return data.ids[]
                    for (var mi = 0; mi < _batchIds.length; mi++) createdIds.push(_batchIds[mi]);
                } else if (opResult.id) {
                    // Singular create ops (element_create, layer_create)
                    createdIds.push(opResult.id);
                }
                // Track successful mutating ops for rollback
                if (MUTATING_OPS[op.task]) {
                    undoCount++;
                }
            } else {
                failed++;

                // Strict + rollback for non-exception failures (e.g. assert_exists returning ok:false)
                if (strict) {
                    opResult.duration_ms = ctx.clock() - t0;
                    results.push(opResult);

                    if (rollback) {
                        if (useSnapshot && preSnapshot && typeof restoreSnapshot === "function") {
                            if (trace) trace.push("[ROLLBACK] Restoring from snapshot (handler fail)");
                            var createdDeleted2 = 0;
                            if (createdIds.length > 0) {
                                // Build lookup set for created IDs
                                var cidSet = {};
                                for (var ci2 = 0; ci2 < createdIds.length; ci2++) cidSet[createdIds[ci2]] = true;
                                // Iterate layers to find and delete created items by note
                                for (var lx = 0; lx < doc.layers.length; lx++) {
                                    for (var px = doc.layers[lx].pageItems.length - 1; px >= 0; px--) {
                                        var pi = doc.layers[lx].pageItems[px];
                                        var pn = pi.note || '';
                                        var pm = pn.match(/@mcp:id=([^\s]+)/);
                                        if (pm && cidSet[pm[1]]) {
                                            try { pi.remove(); createdDeleted2++; } catch (d2) { }
                                        }
                                    }
                                }
                                if (typeof invalidateIdIndex === "function") invalidateIdIndex();
                            }
                            try {
                                var rr = restoreSnapshot(doc, preSnapshot, { geometry: true, style: true });
                                rolledBackCount = rr.restored + createdDeleted2;
                            } catch (re) { }
                        } else if (undoCount > 0) {
                            if (trace) trace.push("[ROLLBACK] Undoing " + undoCount + " ops (handler fail)");
                            for (var u2 = 0; u2 < undoCount; u2++) {
                                try { app.executeMenuCommand('undo'); rolledBackCount++; } catch (ue) { }
                            }
                        }
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

                // Rollback on failure if enabled
                if (rollback) {
                    // Prefer snapshot-based restore if captured
                    if (useSnapshot && preSnapshot && typeof restoreSnapshot === "function") {
                        if (trace) trace.push("[ROLLBACK] Restoring from snapshot");

                        // First, delete any items created during this batch (they weren't in the snapshot)
                        var createdDeleted = 0;
                        if (createdIds.length > 0) {
                            if (trace) trace.push("[ROLLBACK] Deleting " + createdIds.length + " created items");
                            // Build lookup set for created IDs
                            var cidSet2 = {};
                            for (var ci = 0; ci < createdIds.length; ci++) cidSet2[createdIds[ci]] = true;
                            // Iterate layers to find and delete created items by note
                            for (var lx2 = 0; lx2 < doc.layers.length; lx2++) {
                                for (var px2 = doc.layers[lx2].pageItems.length - 1; px2 >= 0; px2--) {
                                    var pi2 = doc.layers[lx2].pageItems[px2];
                                    var pn2 = pi2.note || '';
                                    var pm2 = pn2.match(/@mcp:id=([^\s]+)/);
                                    if (pm2 && cidSet2[pm2[1]]) {
                                        try { pi2.remove(); createdDeleted++; } catch (delErr) {
                                            if (trace) trace.push("[ROLLBACK] Failed to delete " + pm2[1] + ": " + delErr.message);
                                        }
                                    }
                                }
                            }
                            // Invalidate ID index after deleting created items
                            if (typeof invalidateIdIndex === "function") {
                                invalidateIdIndex();
                            }
                        }

                        // Then restore the snapshot state for pre-existing items
                        try {
                            var restoreResult = restoreSnapshot(doc, preSnapshot, { geometry: true, style: true });
                            rolledBackCount = restoreResult.restored + createdDeleted;
                            if (trace) trace.push("[ROLLBACK] Restored " + restoreResult.restored + " items, deleted " + createdDeleted + " created items");
                        } catch (restoreErr) {
                            if (trace) trace.push("[ROLLBACK ERROR] " + restoreErr.message);
                        }
                    } else if (undoCount > 0) {
                        // Fallback to undo-based rollback
                        if (trace) trace.push("[ROLLBACK] Undoing " + undoCount + " mutating ops (undo fallback)");
                        for (var u = 0; u < undoCount; u++) {
                            try {
                                app.executeMenuCommand('undo');
                                rolledBackCount++;
                            } catch (undoErr) {
                                if (trace) trace.push("[ROLLBACK ERROR] " + undoErr.message);
                            }
                        }
                    }
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

    // Final chunk if not aligned
    if (chunkSize > 0 && onProgress && results.length % chunkSize !== 0) {
        try {
            onProgress({
                chunkIndex: chunkIndex,
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

    // P1: Add deprecation warning to report if selection targeting was used
    var reportWarnings = [];
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

    // Always invalidate ID index at end of batch to prevent stale cache
    // across script executions (items may have been created/deleted)
    if (typeof invalidateIdIndex === "function") {
        invalidateIdIndex();
    }

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
            errors: results.filter(function (r) { return !r.ok; }).map(function (r) {
                return { index: r.index, task: r.task, error: r.error };
            }),
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

