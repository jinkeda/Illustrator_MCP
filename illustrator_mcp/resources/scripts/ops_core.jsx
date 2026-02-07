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
 * Call this after deleting elements or when the index is known to be stale.
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
    var ctx = {
        doc: doc,
        app: app,
        cache: {},
        options: options,
        space: options.space || { units: "pt", origin: "document", yAxis: "down" },
        // Diagnostics counters
        diagnostics: {
            cacheHits: 0,
            cacheMisses: 0,
            idScans: 0
        }
    };

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
            stats: { total: ops.length, passed: 0, failed: validationErrors.length }
        };
    }

    // === EXECUTION PHASE ===
    if (trace) trace.push("[EXECUTE] Running " + ops.length + " ops");

    // Capture snapshot before execution if enabled (for snapshot-based rollback)
    if (useSnapshot && rollback && typeof captureSnapshot === "function") {
        try {
            preSnapshot = captureSnapshot(doc, { mcpOnly: true });
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
        var t0 = new Date().getTime();

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
            var handlerResult = handler(op.params || {}, targets, ctx);

            // Normalize handler result
            if (handlerResult && typeof handlerResult === "object") {
                opResult.ok = handlerResult.ok !== false;
                opResult.data = handlerResult.data || handlerResult;
                opResult.warnings = handlerResult.warnings || [];
                opResult.id = handlerResult.id || opResult.id;
            } else {
                opResult.ok = true;
                opResult.data = handlerResult;
            }

            if (opResult.ok) {
                passed++;
                // Track created element IDs for summaryOnly mode
                if (opResult.id) {
                    createdIds.push(opResult.id);
                }
                // Track successful mutating ops for rollback
                if (MUTATING_OPS[op.task]) {
                    undoCount++;
                }
            } else {
                failed++;
            }

        } catch (e) {
            opResult.ok = false;
            opResult.error = makeError(
                ErrorCodes.R_APPLY_FAILED,
                e.message,
                "apply",
                null,
                { line: e.line || null, task: op.task }
            );
            failed++;

            if (strict) {
                opResult.duration_ms = new Date().getTime() - t0;
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
                            var idIndex = typeof $.global.mcpIdIndex === "object" ? $.global.mcpIdIndex.index : {};
                            for (var ci = 0; ci < createdIds.length; ci++) {
                                try {
                                    var createdItem = idIndex[createdIds[ci]];
                                    if (createdItem && createdItem.remove) {
                                        createdItem.remove();
                                        createdDeleted++;
                                    }
                                } catch (delErr) {
                                    if (trace) trace.push("[ROLLBACK] Failed to delete " + createdIds[ci] + ": " + delErr.message);
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

        opResult.duration_ms = new Date().getTime() - t0;
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
                final: true,
                percentComplete: 100
            });
        } catch (cbErr) {
            if (trace) trace.push("[PROGRESS ERROR] " + cbErr.message);
        }
    }

    // === BUILD REPORT ===
    var allOk = failed === 0;
    var totalMs = results.reduce(function (sum, r) { return sum + r.duration_ms; }, 0);

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
                failed: failed
            },
            timing: { total_ms: totalMs },
            diagnostics: ctx.diagnostics,
            // Only include errors, not successful op details
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
            failed: failed
        },
        timing: { total_ms: totalMs },
        diagnostics: ctx.diagnostics,
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
function profileOp(label, fn) {
    var t0 = new Date().getTime();
    var result = fn();
    var t1 = new Date().getTime();
    return { result: result, duration_ms: t1 - t0, label: label };
}
