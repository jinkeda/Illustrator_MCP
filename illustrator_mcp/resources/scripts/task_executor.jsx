/**
 * task_executor.jsx - Task Execution Framework
 * Part of Illustrator MCP Standard Library
 * 
 * Provides standardized task execution with:
 * - Structured payload/report protocol
 * - Stable item references for error localization
 * - Declarative target selection
 * - Safe execution with error handling
 */

// ==================== Error Codes ====================

var ErrorCodes = {
    NO_DOCUMENT: "ERROR_NO_DOCUMENT",
    NO_SELECTION: "ERROR_NO_SELECTION",
    COLLECT_FAILED: "ERROR_COLLECT_FAILED",
    COMPUTE_FAILED: "ERROR_COMPUTE_FAILED",
    APPLY_FAILED: "ERROR_APPLY_FAILED",
    ITEM_FAILED: "ERROR_ITEM_FAILED",
    INVALID_TARGETS: "ERROR_INVALID_TARGETS",
    UNKNOWN_TARGET_TYPE: "ERROR_UNKNOWN_TARGET_TYPE"
};

// ==================== Stable Reference System ====================

/**
 * Get the layer path (including parent layers)
 * @param {Layer} layer
 * @returns {string} Path like "Layer 1/Sublayer A"
 */
function getLayerPath(layer) {
    var parts = [];
    var current = layer;
    while (current && current.typename === "Layer") {
        parts.unshift(current.name);
        current = current.parent;
    }
    return parts.join("/");
}

/**
 * Get the item's index path within its parent containers
 * @param {PageItem} item
 * @returns {Array<number>} Index path like [0, 2, 5]
 */
function getIndexPath(item) {
    var path = [];
    var current = item;

    while (current && current.parent) {
        var parent = current.parent;
        var collection = null;

        // Find the collection that contains the current item
        if (parent.typename === "Document") {
            collection = parent.pageItems;
        } else if (parent.typename === "Layer") {
            collection = parent.pageItems;
        } else if (parent.typename === "GroupItem") {
            collection = parent.pageItems;
        }

        if (collection) {
            for (var i = 0; i < collection.length; i++) {
                if (collection[i] === current) {
                    path.unshift(i);
                    break;
                }
            }
        }

        current = parent;
        if (current.typename === "Document") break;
    }

    return path;
}

/**
 * Generate a stable reference for an item (for error localization)
 * @param {PageItem} item
 * @param {Layer} [layer] - Optional layer override
 * @returns {Object} ItemRef object
 */
function describeItem(item, layer) {
    var itemLayer = layer || null;
    try {
        itemLayer = item.layer;
    } catch (e) { }

    var layerPath = itemLayer ? getLayerPath(itemLayer) : "";
    var indexPath = getIndexPath(item);

    // Try reading an ID from note (if previously written)
    var itemId = null;
    try {
        if (item.note && item.note.indexOf("mcp-id:") >= 0) {
            var match = item.note.match(/mcp-id:([a-zA-Z0-9_-]+)/);
            if (match) itemId = match[1];
        }
    } catch (e) { }

    return {
        layerPath: layerPath,
        indexPath: indexPath,
        itemId: itemId,
        itemName: item.name || "",
        itemType: item.typename
    };
}

/**
 * Assign a unique ID to an item (write into note)
 * Only call when options.assignIds is true
 * @param {PageItem} item
 * @returns {string} The assigned ID
 */
function assignItemId(item) {
    var id = "i" + (new Date().getTime()) + "_" + Math.floor(Math.random() * 10000);

    var existingNote = "";
    try {
        existingNote = item.note || "";
    } catch (e) { }

    // Remove old ID (if any)
    existingNote = existingNote.replace(/mcp-id:[a-zA-Z0-9_-]+\s*/g, "");

    try {
        item.note = "mcp-id:" + id + " " + existingNote;
    } catch (e) { }

    return id;
}

// ==================== Declarative Target Selection ====================

/**
 * Convert selection to array
 * @param {Selection} sel
 * @returns {Array<PageItem>}
 */
function selectionToArray(sel) {
    var arr = [];
    for (var i = 0; i < sel.length; i++) {
        arr.push(sel[i]);
    }
    return arr;
}

/**
 * Convert pageItems collection to array
 * @param {PageItems} items
 * @returns {Array<PageItem>}
 */
function pageItemsToArray(items) {
    var arr = [];
    for (var i = 0; i < items.length; i++) {
        arr.push(items[i]);
    }
    return arr;
}

/**
 * Find a layer by name
 * @param {Document} doc
 * @param {string} layerName
 * @returns {Layer|null}
 */
function findLayer(doc, layerName) {
    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === layerName) {
            return doc.layers[i];
        }
    }
    return null;
}

/**
 * Collect all items from a layer
 * @param {Layer} layer
 * @param {boolean} [recursive] - Include nested group items
 * @returns {Array<PageItem>}
 */
function collectLayerItems(layer, recursive) {
    var items = [];
    for (var i = 0; i < layer.pageItems.length; i++) {
        items.push(layer.pageItems[i]);

        if (recursive && layer.pageItems[i].typename === "GroupItem") {
            var groupItems = pageItemsToArray(layer.pageItems[i].pageItems);
            items = items.concat(groupItems);
        }
    }
    return items;
}

/**
 * Query items with filters
 * @param {Document} doc
 * @param {Object} query - {layer, itemType, pattern, recursive}
 * @returns {Array<PageItem>}
 */
function queryItems(doc, query) {
    var items = [];
    var layerFilter = query.layer;
    var typeFilter = query.itemType;
    var namePattern = query.pattern;

    // Convert wildcard to regex
    var regex = null;
    if (namePattern) {
        var regexStr = namePattern.replace(/\*/g, ".*").replace(/\?/g, ".");
        regex = new RegExp("^" + regexStr + "$");
    }

    // Traverse all items (or a specific layer)
    var layers = [];
    if (layerFilter) {
        var foundLayer = findLayer(doc, layerFilter);
        if (foundLayer) layers.push(foundLayer);
    } else {
        for (var k = 0; k < doc.layers.length; k++) {
            layers.push(doc.layers[k]);
        }
    }

    for (var i = 0; i < layers.length; i++) {
        if (!layers[i]) continue;
        var layerItems = collectLayerItems(layers[i], query.recursive || false);

        for (var j = 0; j < layerItems.length; j++) {
            var item = layerItems[j];

            // Type filter
            if (typeFilter && item.typename !== typeFilter) continue;

            // Name filter
            if (regex && !regex.test(item.name || "")) continue;

            items.push(item);
        }
    }

    return items;
}

/**
 * Declarative target selection - replaces manual selection micro-ops
 * @param {Document} doc
 * @param {Object} targets - {type: "selection"} | {type: "layer", layer: "Layer 1"} | etc.
 * @returns {Array<PageItem>}
 */
function collectTargets(doc, targets) {
    if (!targets || targets.type === "selection") {
        // Default: current selection
        return selectionToArray(doc.selection);
    }

    if (targets.type === "all") {
        // All items (optionally recursive)
        var allItems = [];
        for (var i = 0; i < doc.layers.length; i++) {
            var layerItems = collectLayerItems(doc.layers[i], targets.recursive || false);
            allItems = allItems.concat(layerItems);
        }
        return allItems;
    }

    if (targets.type === "layer") {
        // All items in a given layer
        var layer = findLayer(doc, targets.layer);
        if (!layer) {
            throw new Error("Layer not found: " + targets.layer);
        }
        return collectLayerItems(layer, targets.recursive || false);
    }

    if (targets.type === "query") {
        // Advanced query: {type: "query", itemType: "PathItem", layer: "Layer 1", pattern: "axis_*"}
        return queryItems(doc, targets);
    }

    throw new Error("Unknown target type: " + targets.type);
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
        report.errors.push({
            stage: stage,
            code: ErrorCodes.ITEM_FAILED,
            message: e.message,
            itemRef: describeItem(item),
            line: e.line || null
        });
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

    // Check for active document
    var doc = null;
    try {
        doc = app.activeDocument;
    } catch (e) { }

    if (!doc) {
        report.ok = false;
        report.errors.push({
            stage: "collect",
            code: ErrorCodes.NO_DOCUMENT,
            message: "No active document"
        });
        report.timing = { collect_ms: 0, compute_ms: 0, apply_ms: 0, total_ms: 0 };
        return report;
    }

    var t0 = new Date().getTime();

    // === COLLECT stage ===
    var items = [];
    try {
        if (trace) trace.push("[COLLECT] Starting target collection");
        items = collectFn(doc, payload.targets);
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
        if (options.assignIds && items.length > 0) {
            if (trace) trace.push("[COLLECT] Assigning IDs to " + items.length + " items");
            for (var idx = 0; idx < items.length; idx++) {
                assignItemId(items[idx]);
            }
        }

    } catch (e) {
        report.ok = false;
        report.errors.push({
            stage: "collect",
            code: ErrorCodes.COLLECT_FAILED,
            message: e.message,
            line: e.line || null
        });
        var t1_err = new Date().getTime();
        report.timing = { collect_ms: t1_err - t0, compute_ms: 0, apply_ms: 0, total_ms: t1_err - t0 };
        return report;
    }
    var t1 = new Date().getTime();
    report.timing.collect_ms = t1 - t0;

    if (items.length === 0) {
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
        report.errors.push({
            stage: "compute",
            code: ErrorCodes.COMPUTE_FAILED,
            message: e.message,
            line: e.line || null
        });
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
        report.errors.push({
            stage: "apply",
            code: ErrorCodes.APPLY_FAILED,
            message: e.message,
            line: e.line || null
        });
    }
    var t3 = new Date().getTime();
    report.timing.apply_ms = t3 - t2;
    report.timing.total_ms = t3 - t0;

    return report;
}

// ==================== Task Retry Mechanism ====================

/**
 * Execute task with automatic retry on failure
 * @param {Object} payload - TaskPayload with optional retry settings
 * @param {Function} collectFn
 * @param {Function} computeFn
 * @param {Function} applyFn
 * @param {number} [maxRetries] - Maximum retry attempts (default: 3)
 * @returns {Object} TaskReport with retry info
 */
function executeTaskWithRetry(payload, collectFn, computeFn, applyFn, maxRetries) {
    maxRetries = maxRetries || 3;
    var attempts = 0;
    var lastReport = null;

    while (attempts < maxRetries) {
        attempts++;
        lastReport = executeTask(payload, collectFn, computeFn, applyFn);

        if (lastReport.ok) {
            lastReport.retryInfo = {
                attempts: attempts,
                succeeded: true
            };
            return lastReport;
        }

        // Check if error is retryable
        var hasNonRetryable = false;
        for (var i = 0; i < lastReport.errors.length; i++) {
            var err = lastReport.errors[i];
            // Non-retryable errors
            if (err.code === ErrorCodes.NO_DOCUMENT ||
                err.code === ErrorCodes.INVALID_TARGETS) {
                hasNonRetryable = true;
                break;
            }
        }

        if (hasNonRetryable) {
            break; // Don't retry
        }

        // Brief pause before retry (ExtendScript has no setTimeout, but we track)
        if (lastReport.trace) {
            lastReport.trace.push("[RETRY] Attempt " + attempts + " failed, retrying...");
        }
    }

    lastReport.retryInfo = {
        attempts: attempts,
        succeeded: false,
        maxRetries: maxRetries
    };

    return lastReport;
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

// ==================== Utility: JSON Stringify for ExtendScript ====================

/**
 * Simple JSON stringify for ExtendScript (which lacks native JSON)
 * Note: If your environment has JSON, use JSON.stringify instead
 */
if (typeof JSON === "undefined") {
    var JSON = {};
    JSON.stringify = function (obj) {
        var t = typeof obj;
        if (t !== "object" || obj === null) {
            if (t === "string") return '"' + obj.replace(/"/g, '\\"').replace(/\n/g, '\\n') + '"';
            return String(obj);
        }
        var n, v, json = [];
        var isArray = (obj && obj.constructor === Array);
        for (n in obj) {
            if (!obj.hasOwnProperty(n)) continue;
            v = obj[n];
            t = typeof v;
            if (t === "string") {
                v = '"' + v.replace(/"/g, '\\"').replace(/\n/g, '\\n') + '"';
            } else if (t === "object" && v !== null) {
                v = JSON.stringify(v);
            }
            json.push((isArray ? "" : '"' + n + '":') + String(v));
        }
        return (isArray ? "[" : "{") + String(json) + (isArray ? "]" : "}");
    };
}
