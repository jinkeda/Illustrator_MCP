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

/**
 * Build ID index for O(1) lookups
 * @param {Document} doc - Active document
 * @param {Object} ctx - Batch context (stores index)
 * @returns {Object} ID index {id: item}
 */
function buildIDIndex(doc, ctx) {
    if (ctx.idIndex) return ctx.idIndex;

    var index = {};
    var scanDepth = 0;
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

    ctx.idIndex = index;
    ctx.diagnostics.idScans++;
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
 * @param {boolean} options.trace - Include execution trace
 * @returns {Object} Batch report
 */
function executeOpBatch(ops, options) {
    options = options || {};
    var strict = options.strict || options.stopOnError || false;
    var trace = options.trace ? [] : null;

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

    var results = [];
    var passed = 0;
    var failed = 0;

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

            if (opResult.ok) passed++;
            else failed++;

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
                break;
            }
        }

        opResult.duration_ms = new Date().getTime() - t0;
        results.push(opResult);
    }

    // === BUILD REPORT ===
    var allOk = failed === 0;

    return {
        ok: allOk,
        schemaVersion: OP_SCHEMA_VERSION,
        ops: results,
        stats: {
            total: ops.length,
            executed: results.length,
            passed: passed,
            failed: failed
        },
        timing: {
            total_ms: results.reduce(function (sum, r) { return sum + r.duration_ms; }, 0)
        },
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
