/**
 * task_pipeline.jsx - Task Execution Pipeline
 * Part of Illustrator MCP Standard Library
 * @version 1.0.0
 *
 * Provides the core execution framework:
 * - makeError (structured error creation)
 * - safeExecute (per-item error capture)
 * - buildReport, validatePayload
 * - executeTask (collect -> compute -> apply pipeline)
 * - executeTaskWithRetrySafe (stage-aware retry)
 * - Task history (recordTaskHistory, getTaskHistory, clearTaskHistory)
 * - Profiling utilities (profile, formatTiming)
 *
 * DEPENDENCIES: polyfills, contracts (ErrorCodes, RETRYABLE_CODES),
 *               item_ref (describeItemV2, assignItemId/V2),
 *               targets (collectTargets, filterItems, sortItems)
 *
 * Extracted from task_executor.jsx (Phase 5 decomposition).
 */

// ==================== Error Construction ====================

/**
 * Create a structured error object
 * @param {string} code - Error code from ErrorCodes
 * @param {string} message - Human-readable message
 * @param {string} stage - 'validate', 'collect', 'compute', 'apply', 'export'
 * @param {Object} [itemRef] - Optional ItemRef for localization
 * @param {Object} [details] - Optional additional context
 * @returns {Object} TaskError object
 */
function makeError(code, message, stage, itemRef, details) {
    return {
        ok: false,
        error: {
            code: code,
            message: message,
            stage: stage,
            itemRef: itemRef || null,
            details: details || null
        }
    };
}

// ==================== Error Handling ====================

/**
 * Safely execute a function, capture errors, and record them into the report
 * @param {Function} fn - Function to execute, receives (item)
 * @param {PageItem} item - The item to process
 * @param {Object} report - The TaskReport to record errors
 * @param {string} stage - Current stage name
 * @returns {*} Result of fn, or null if error
 */
function safeExecute(fn, item, report, stage) {
    try {
        return fn(item);
    } catch (e) {
        report.errors.push(makeError(
            ErrorCodes.R_ITEM_OPERATION_FAILED,
            e.message,
            stage,
            describeItemV2(item, { includeIdentity: true, includeTags: true }),
            { line: e.line || null }
        ));
        report.stats.itemsSkipped++;
        return null;
    }
}

// ==================== Report Builder ====================

/**
 * Build a TaskReport object
 * @param {boolean} ok
 * @param {Object} stats
 * @param {Object} timing
 * @param {Array} warnings
 * @param {Array} errors
 * @returns {Object} TaskReport
 */
function buildReport(ok, stats, timing, warnings, errors) {
    return {
        ok: ok,
        stats: stats || {
            itemsProcessed: 0,
            itemsModified: 0,
            itemsSkipped: 0
        },
        timing: timing || {
            collect_ms: 0,
            compute_ms: 0,
            apply_ms: 0,
            total_ms: 0
        },
        warnings: warnings || [],
        errors: errors || []
    };
}

// ==================== Payload Validation (v2.3) ====================

/**
 * Validate task payload (v2.3)
 * @param {Object} payload
 * @returns {Array<Object>} Array of error objects (empty if valid)
 */
function validatePayload(payload) {
    var errors = [];

    // Required field: task
    if (!payload.task || typeof payload.task !== "string") {
        errors.push(makeError(
            ErrorCodes.V_INVALID_PAYLOAD,
            "Missing or invalid 'task' field",
            "validate"
        ));
    }

    // Validate version (fail fast on major version mismatch)
    if (payload.version) {
        var majorVersion = payload.version.split(".")[0];
        if (majorVersion !== "2") {
            errors.push(makeError(
                ErrorCodes.V_SCHEMA_MISMATCH,
                "Incompatible protocol version: " + payload.version + " (expected 2.x)",
                "validate",
                null,
                { expected: "2.x", received: payload.version }
            ));
        }
    }

    // Validate targets if present
    if (payload.targets) {
        var t = payload.targets;
        // Handle new TargetSelector format
        var target = t.target || t;

        if (!target.type) {
            errors.push(makeError(
                ErrorCodes.V_INVALID_TARGETS,
                "targets.type is required",
                "validate"
            ));
        } else if (["selection", "layer", "all", "query", "compound", "id"].indexOf(target.type) < 0) {
            errors.push(makeError(
                ErrorCodes.V_UNKNOWN_TARGET_TYPE,
                "Unknown target type: " + target.type,
                "validate",
                null,
                { validTypes: ["selection", "layer", "all", "query", "compound", "id"] }
            ));
        } else if (target.type === "layer" && !target.layer) {
            errors.push(makeError(
                ErrorCodes.V_MISSING_REQUIRED_PARAM,
                "targets.layer is required when type='layer'",
                "validate"
            ));
        } else if (target.type === "compound" && (!target.anyOf || target.anyOf.length === 0)) {
            errors.push(makeError(
                ErrorCodes.V_MISSING_REQUIRED_PARAM,
                "targets.anyOf is required when type='compound'",
                "validate"
            ));
        } else if (target.type === "id" && (!target.ids || target.ids.length === 0)) {
            errors.push(makeError(
                ErrorCodes.V_MISSING_REQUIRED_PARAM,
                "targets.ids is required when type='id'",
                "validate"
            ));
        }
    }

    // Validate options if present
    if (payload.options) {
        var opts = payload.options;
        if (opts.timeout !== undefined && (typeof opts.timeout !== "number" || opts.timeout < 1)) {
            errors.push(makeError(
                ErrorCodes.V_INVALID_PARAM_TYPE,
                "options.timeout must be a positive number",
                "validate"
            ));
        }
    }

    return errors;
}

// ==================== Task Execution Framework ====================

/**
 * Standard task execution flow
 * @param {Object} payload - TaskPayload object: {task, version, targets, params, options}
 * @param {Function} collectFn - Target collection function: (doc, targets) => items[]
 * @param {Function} computeFn - Compute function: (items, params, report) => actions[]
 * @param {Function} applyFn - Apply function: (actions, report) => void
 * @returns {Object} TaskReport
 */
function executeTask(payload, collectFn, computeFn, applyFn) {
    var options = payload.options || {};
    var trace = options.trace ? [] : null;

    var report = {
        ok: true,
        stats: {
            itemsProcessed: 0,
            itemsModified: 0,
            itemsSkipped: 0
        },
        timing: {},
        warnings: [],
        errors: [],
        trace: trace
    };

    // === VALIDATE stage ===
    var validationErrors = validatePayload(payload);
    if (validationErrors.length > 0) {
        report.ok = false;
        report.errors = validationErrors;
        return report;
    }

    // Check for active document
    var doc = null;
    try {
        doc = app.activeDocument;
    } catch (e) { }

    if (!doc) {
        report.ok = false;
        report.errors.push(makeError(
            ErrorCodes.V_NO_DOCUMENT,
            "No active document",
            "collect"
        ));
        report.timing = { collect_ms: 0, compute_ms: 0, apply_ms: 0, total_ms: 0 };
        return report;
    }

    var t0 = new Date().getTime();

    // Resolve skipCollect from kind or explicit flag
    var skipCollect = options.skipCollect || (options.kind === "creation");

    // === COLLECT stage ===
    var items = [];
    if (skipCollect) {
        // Creation-first: skip collect, items stays []
        if (trace) trace.push("[COLLECT] Skipped (kind=" + (options.kind || "n/a") + ", skipCollect=true); items=[]");
        report.timing.collect_ms = 0;
    } else {
        try {
            if (trace) trace.push("[COLLECT] Starting target collection");

            // Handle both v2.3 TargetSelector and legacy formats
            var targets = payload.targets;
            var targetObj = targets;
            var orderBy = "zOrder";
            var globalExclude = null;

            if (targets && targets.target) {
                // V2.3 TargetSelector format
                targetObj = targets.target;
                orderBy = targets.orderBy || "zOrder";
                globalExclude = targets.exclude;
            } else {
                // Legacy format support - some might pass exclude/orderBy directly
                if (targets && targets.exclude) globalExclude = targets.exclude;
                if (targets && targets.orderBy) orderBy = targets.orderBy;
            }

            items = collectFn(doc, targetObj);

            // Phase 4 guard: clear selection after resolution to prevent
            // accidental coupling in downstream ops
            try { if (typeof app !== "undefined") app.selection = null; } catch (selErr) { /* non-critical */ }

            // Apply global exclusion
            if (globalExclude) {
                items = filterItems(items, globalExclude);
            }

            // Apply ordering
            items = sortItems(items, orderBy);

            report.stats.itemsProcessed = items.length;
            if (trace) trace.push("[COLLECT] Found " + items.length + " items");

            if (items.length === 0) {
                report.warnings.push({
                    stage: "collect",
                    message: "No items matched the target selector",
                    suggestion: "Check targets parameter or document content"
                });
            }

            // === ASSIGN IDs (opt-in) ===
            if (options.idPolicy && options.idPolicy !== "none") {
                if (trace) trace.push("[COLLECT] Assigning IDs to " + items.length + " items");
                for (var idx = 0; idx < items.length; idx++) {
                    assignItemIdV2(items[idx], options.idPolicy);
                }
            }
            // Legacy fallback (remove in v3.0)
            else if (options.assignIds && items.length > 0) {
                for (var idx = 0; idx < items.length; idx++) {
                    assignItemId(items[idx]);
                }
            }

        } catch (e) {
            report.ok = false;
            report.errors.push(makeError(
                ErrorCodes.R_COLLECT_FAILED,
                e.message,
                "collect",
                null,
                { line: e.line || null }
            ));
            var t1_err = new Date().getTime();
            report.timing = { collect_ms: t1_err - t0, compute_ms: 0, apply_ms: 0, total_ms: t1_err - t0 };
            return report;
        }
    }
    var t1 = new Date().getTime();
    if (!skipCollect) report.timing.collect_ms = t1 - t0;

    // Early-return on empty items ONLY for selection tasks
    if (items.length === 0 && !skipCollect) {
        report.timing.compute_ms = 0;
        report.timing.apply_ms = 0;
        report.timing.total_ms = t1 - t0;
        return report;
    }

    // === COMPUTE stage ===
    var actions = [];
    try {
        if (trace) trace.push("[COMPUTE] Computing actions");
        actions = computeFn(items, payload.params, report);
        if (trace) trace.push("[COMPUTE] Generated " + actions.length + " actions");
    } catch (e) {
        report.ok = false;
        report.errors.push(makeError(
            ErrorCodes.R_COMPUTE_FAILED,
            e.message,
            "compute",
            null,
            { line: e.line || null }
        ));
        var t2_err = new Date().getTime();
        report.timing.compute_ms = t2_err - t1;
        report.timing.apply_ms = 0;
        report.timing.total_ms = t2_err - t0;
        return report;
    }
    var t2 = new Date().getTime();
    report.timing.compute_ms = t2 - t1;

    // DryRun mode
    if (options.dryRun) {
        if (trace) trace.push("[APPLY] Skipped (dryRun=true)");
        report.timing.apply_ms = 0;
        report.timing.total_ms = t2 - t0;
        report.warnings.push({
            stage: "apply",
            message: "DryRun mode - no changes applied"
        });
        return report;
    }

    // === APPLY stage ===
    try {
        if (trace) trace.push("[APPLY] Applying " + actions.length + " actions");
        applyFn(actions, report);
        if (trace) trace.push("[APPLY] Complete");
    } catch (e) {
        report.ok = false;
        report.errors.push(makeError(
            ErrorCodes.R_APPLY_FAILED,
            e.message,
            "apply",
            null,
            { line: e.line || null }
        ));
    }
    var t3 = new Date().getTime();
    report.timing.apply_ms = t3 - t2;
    report.timing.total_ms = t3 - t0;

    // Creation safety rail: check minCreated
    if (options.minCreated != null && report.stats.itemsModified < options.minCreated) {
        report.warnings.push({
            stage: "apply",
            message: "Created " + report.stats.itemsModified + " items, expected at least " + options.minCreated
        });
    }
    if (trace) trace.push("[APPLY] created=" + report.stats.itemsModified);

    return report;
}

// ==================== Safe Task Retry Mechanism (v2.3) ====================

/**
 * Check if an error is retryable based on code and stage.
 * IMPORTANT: Never retry 'apply' stage unless explicitly allowed.
 *
 * @param {Object} error - TaskError object
 * @param {Array} retryableStages - Allowed stages for retry (default: ["collect"])
 * @returns {boolean}
 */
function isRetryable(error, retryableStages) {
    retryableStages = retryableStages || ["collect"];
    // Unwrap nested makeError shape: {ok:false, error:{code,stage,...}}
    var e = (error && error.error) ? error.error : error;

    // Never retry apply stage unless explicitly in the list
    if (e.stage === "apply" && retryableStages.indexOf("apply") < 0) {
        return false;
    }

    // Check if stage is in allowed list
    if (retryableStages.indexOf(e.stage) < 0) {
        return false;
    }

    // Check if error code is retryable
    return RETRYABLE_CODES.indexOf(e.code) >= 0;
}

/**
 * Execute task with SAFE retry (stage-aware).
 *
 * Key safety rules:
 * - Never auto-retry 'apply' stage (could double-apply changes)
 * - Only retry 'collect' and 'compute' by default
 * - Respect idempotency declaration
 *
 * @param {Object} payload - TaskPayload with optional retry config
 * @param {Function} collectFn
 * @param {Function} computeFn
 * @param {Function} applyFn
 * @returns {Object} TaskReport with retryInfo
 */
function executeTaskWithRetrySafe(payload, collectFn, computeFn, applyFn) {
    var options = payload.options || {};
    var retryPolicy = options.retry || { maxAttempts: 1, retryableStages: [] };
    var maxAttempts = retryPolicy.maxAttempts || 1;
    var retryableStages = retryPolicy.retryableStages || ["collect"];

    var attempts = 0;
    var retriedStages = [];
    var lastReport = null;

    while (attempts < maxAttempts) {
        attempts++;
        lastReport = executeTask(payload, collectFn, computeFn, applyFn);

        if (lastReport.ok) {
            break; // Success, no retry needed
        }

        // Check if any error is retryable
        var canRetry = false;
        for (var i = 0; i < lastReport.errors.length; i++) {
            var err = lastReport.errors[i];
            if (isRetryable(err, retryableStages)) {
                canRetry = true;
                var eInner = (err && err.error) ? err.error : err;
                if (retriedStages.indexOf(eInner.stage) < 0) {
                    retriedStages.push(eInner.stage);
                }
            }
        }

        if (!canRetry) {
            break; // Non-retryable error, stop
        }

        // Log retry attempt
        if (lastReport.trace) {
            lastReport.trace.push("[RETRY] Attempt " + attempts + " failed, retrying stages: " + retriedStages.join(", "));
        }
    }

    // Add retry info to report
    lastReport.retryInfo = {
        attempts: attempts,
        succeeded: lastReport.ok,
        retriedStages: retriedStages,
        idempotency: options.idempotency || "unknown"
    };

    return lastReport;
}

/**
 * @deprecated Use executeTaskWithRetrySafe instead.
 * This function is kept for backward compatibility but will be removed in v3.0.
 */
function executeTaskWithRetry(payload, collectFn, computeFn, applyFn, maxRetries) {
    // Wrap old API to new safe API
    payload = JSON.parse(JSON.stringify(payload)); // Clone
    payload.options = payload.options || {};
    payload.options.retry = {
        maxAttempts: maxRetries || 3,
        retryableStages: ["collect", "compute"]
    };
    return executeTaskWithRetrySafe(payload, collectFn, computeFn, applyFn);
}

// ==================== Task History ====================

/**
 * Global task history for backtracking (in-session only)
 */
var _taskHistory = [];
var _taskHistoryLimit = 50;

/**
 * Record a task execution in history
 * @param {Object} payload
 * @param {Object} report
 */
function recordTaskHistory(payload, report) {
    _taskHistory.push({
        timestamp: new Date().getTime(),
        task: payload.task,
        targets: payload.targets,
        paramsSnapshot: JSON.stringify(payload.params),
        ok: report.ok,
        itemsModified: report.stats.itemsModified,
        timing_ms: report.timing.total_ms
    });

    // Trim history
    while (_taskHistory.length > _taskHistoryLimit) {
        _taskHistory.shift();
    }
}

/**
 * Get task history
 * @param {number} [limit] - Max items to return
 * @returns {Array}
 */
function getTaskHistory(limit) {
    limit = limit || 10;
    var start = Math.max(0, _taskHistory.length - limit);
    return _taskHistory.slice(start);
}

/**
 * Clear task history
 */
function clearTaskHistory() {
    _taskHistory = [];
}

// ==================== Performance Profiler ====================

/**
 * Profile a function's execution time
 * @param {string} name - Profile name
 * @param {Function} fn - Function to profile
 * @returns {Object} {result, elapsed_ms}
 */
function profile(name, fn) {
    var start = new Date().getTime();
    var result = fn();
    var end = new Date().getTime();
    return {
        name: name,
        result: result,
        elapsed_ms: end - start
    };
}

/**
 * Get timing breakdown as formatted string
 * @param {Object} timing - Timing object from report
 * @returns {string}
 */
function formatTiming(timing) {
    return "collect=" + timing.collect_ms + "ms, " +
        "compute=" + timing.compute_ms + "ms, " +
        "apply=" + timing.apply_ms + "ms, " +
        "total=" + timing.total_ms + "ms";
}
