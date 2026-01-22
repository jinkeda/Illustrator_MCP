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

// ==================== ES3 Polyfills ====================
// ExtendScript is based on ES3 and lacks many modern array methods

if (!Array.prototype.indexOf) {
    Array.prototype.indexOf = function (searchElement, fromIndex) {
        var k;
        if (this == null) {
            throw new TypeError('"this" is null or not defined');
        }
        var o = Object(this);
        var len = o.length >>> 0;
        if (len === 0) {
            return -1;
        }
        var n = fromIndex | 0;
        if (n >= len) {
            return -1;
        }
        k = Math.max(n >= 0 ? n : len - Math.abs(n), 0);
        while (k < len) {
            if (k in o && o[k] === searchElement) {
                return k;
            }
            k++;
        }
        return -1;
    };
}

// ==================== Error Codes (v2.3) ====================
// Categories: V=Validation (fail before execution), R=Runtime, S=System

var ErrorCodes = {
    // === VALIDATION (V) - fail before execution ===
    V_NO_DOCUMENT: "V001",
    V_NO_SELECTION: "V002",
    V_INVALID_PAYLOAD: "V003",
    V_INVALID_TARGETS: "V004",
    V_UNKNOWN_TARGET_TYPE: "V005",
    V_MISSING_REQUIRED_PARAM: "V006",
    V_INVALID_PARAM_TYPE: "V007",
    V_SCHEMA_MISMATCH: "V008",

    // === RUNTIME (R) - fail during execution ===
    R_COLLECT_FAILED: "R001",
    R_COMPUTE_FAILED: "R002",
    R_APPLY_FAILED: "R003",
    R_ITEM_OPERATION_FAILED: "R004",
    R_TIMEOUT: "R005",
    R_OUT_OF_BOUNDS: "R006",

    // === SYSTEM (S) - Illustrator/environment issues ===
    S_APP_ERROR: "S001",
    S_SCRIPT_ERROR: "S002",
    S_IO_ERROR: "S003",
    S_MEMORY_ERROR: "S004"
};

// Error codes that are safe to retry (collect/compute only, NOT apply)
var RETRYABLE_CODES = [
    ErrorCodes.R_COLLECT_FAILED,
    ErrorCodes.R_COMPUTE_FAILED
];

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
        code: code,
        message: message,
        stage: stage,
        itemRef: itemRef || null,
        details: details || null
    };
}

/**
 * Validate task payload (v2.3)
 * @param {Object} payload
 * @returns {Array<Object>} Array of error objects (empty if valid)
 */



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
 * @deprecated Since v2.3. Use describeItemV2() instead. Will be removed in v3.0.
 * @param {PageItem} item
 * @param {Layer} [layer] - Optional layer override
 * @returns {Object} ItemRef object (legacy format)
 */
function describeItem(item, layer) {
    var itemLayer = layer || null;
    try {
        itemLayer = item.layer;
    } catch (e) {
        // item.layer may fail on some item types (e.g., SymbolItems)
    }

    var layerPath = itemLayer ? getLayerPath(itemLayer) : "";
    var indexPath = getIndexPath(item);

    // Try reading an ID from note (if previously written)
    var itemId = null;
    try {
        if (item.note && item.note.indexOf("mcp-id:") >= 0) {
            var match = item.note.match(/mcp-id:([a-zA-Z0-9_-]+)/);
            if (match) itemId = match[1];
        }
    } catch (e) {
        // item.note may not be accessible on all item types
    }

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
 * @deprecated Since v2.3. Use assignItemIdV2() instead. Will be removed in v3.0.
 * Only call when options.assignIds is true
 * @param {PageItem} item
 * @returns {string} The assigned ID
 */
function assignItemId(item) {
    var id = "i" + (new Date().getTime()) + "_" + Math.floor(Math.random() * 10000);

    var existingNote = "";
    try {
        existingNote = item.note || "";
    } catch (e) {
        // item.note may not be readable on some item types
    }

    // Remove old ID (if any)
    existingNote = existingNote.replace(/mcp-id:[a-zA-Z0-9_-]+\s*/g, "");

    try {
        item.note = "mcp-id:" + id + " " + existingNote;
    } catch (e) {
        // item.note may not be writable on some item types (e.g., locked items)
    }

    return id;
}

// ==================== Tag Parsing (v2.3) ====================

/**
 * Parse @mcp:key=value tags from a string.
 * @param {string} str - String to parse (item.name or item.note)
 * @returns {Object} Parsed tags {key: value}
 */
function parseMcpTags(str) {
    var tags = {};
    if (!str) return tags;

    // Match @mcp:key=value patterns
    var regex = /@mcp:([a-zA-Z0-9_]+)=([^\s@]+)/g;
    var match;
    // ExtendScript regex.exec loop
    while ((match = str.match(/@mcp:([a-zA-Z0-9_]+)=([^\s@]+)/)) !== null) {
        tags[match[1]] = match[2];
        str = str.replace(match[0], ""); // Remove matched part to find next
    }
    return tags;
}

// ==================== Refactored Item Reference (v2.3) ====================

/**
 * Generate a complete ItemRef with separated concerns (locator/identity/tags).
 * @param {PageItem} item
 * @param {Object} [options] - {includeIdentity: bool, includeTags: bool}
 * @returns {Object} ItemRef with locator, identity, tags, metadata
 */
function describeItemV2(item, options) {
    options = options || {};

    // === LOCATOR (always computed) ===
    var itemLayer = null;
    try { itemLayer = item.layer; } catch (e) { }

    var locator = {
        layerPath: itemLayer ? getLayerPath(itemLayer) : "",
        indexPath: getIndexPath(item)
    };

    // === IDENTITY (opt-in) ===
    var identity = {
        itemId: null,
        idSource: "none"
    };

    if (options.includeIdentity !== false) {
        try {
            if (item.note && item.note.indexOf("mcp-id:") >= 0) {
                var match = item.note.match(/mcp-id:([a-zA-Z0-9_-]+)/);
                if (match) {
                    identity.itemId = match[1];
                    identity.idSource = "note";
                }
            }
        } catch (e) { }
    }

    // === TAGS (parsed from name and note) ===
    var tags = {};
    if (options.includeTags !== false) {
        var nameTags = parseMcpTags(item.name || "");
        var noteTags = parseMcpTags(item.note || "");
        // Merge (note takes precedence)
        for (var k in nameTags) tags[k] = nameTags[k];
        for (var k in noteTags) tags[k] = noteTags[k];
    }

    return {
        locator: locator,
        identity: identity,
        tags: { tags: tags },
        itemType: item.typename,
        itemName: item.name || null
    };
}

// ==================== ID Assignment with Conflict Detection (v2.3) ====================

/**
 * Assign an ID to an item with conflict detection and policy support.
 * @param {PageItem} item
 * @param {string} policy - "none", "opt_in", "always", "preserve"
 * @returns {Object} {assigned: bool, id: string|null, conflict: bool, previousId: string|null}
 */
function assignItemIdV2(item, policy) {
    policy = policy || "none";

    if (policy === "none") {
        return { assigned: false, id: null, conflict: false, previousId: null };
    }

    // Check for existing ID
    var existingId = null;
    try {
        if (item.note && item.note.indexOf("mcp-id:") >= 0) {
            var match = item.note.match(/mcp-id:([a-zA-Z0-9_-]+)/);
            if (match) existingId = match[1];
        }
    } catch (e) { }

    if (policy === "preserve") {
        return { assigned: false, id: existingId, conflict: false, previousId: existingId };
    }

    if (existingId && policy === "opt_in") {
        // Don't overwrite existing ID
        return { assigned: false, id: existingId, conflict: false, previousId: existingId };
    }

    // Generate new ID with timestamp and random suffix
    var newId = "mcp_" + (new Date().getTime()) + "_" + Math.floor(Math.random() * 10000);

    // Conflict detection for "always" policy
    var conflict = (existingId !== null && policy === "always");

    // Write ID to note
    var existingNote = "";
    try { existingNote = item.note || ""; } catch (e) { }
    existingNote = existingNote.replace(/mcp-id:[a-zA-Z0-9_-]+\s*/g, "");

    try {
        item.note = "mcp-id:" + newId + " " + existingNote;
    } catch (e) {
        return { assigned: false, id: null, conflict: false, error: e.message };
    }

    return { assigned: true, id: newId, conflict: conflict, previousId: existingId };
}

// ==================== Item Sorting (v2.3) ====================

/**
 * Sort items by specified order mode for deterministic results.
 * @param {Array<PageItem>} items
 * @param {string} orderBy - "zOrder", "zOrderReverse", "reading", "column", "name", "positionX", "positionY", "area"
 * @returns {Array<PageItem>} Sorted items (new array)
 */
function sortItems(items, orderBy) {
    if (!items || items.length === 0) return items;

    var sorted = [];
    for (var i = 0; i < items.length; i++) {
        sorted.push(items[i]);
    }

    switch (orderBy) {
        case "zOrder":
            // Already in z-order (back to front) from Illustrator
            break;

        case "zOrderReverse":
            sorted.reverse();
            break;

        case "reading":  // Row-major: top-to-bottom, then left-to-right
            sorted.sort(function (a, b) {
                var rowThreshold = 10; // Tolerance for "same row"
                if (Math.abs(a.top - b.top) < rowThreshold) {
                    return a.left - b.left; // Same row: sort by X
                }
                return b.top - a.top; // Different rows: sort by Y (higher top = earlier)
            });
            break;

        case "column":  // Column-major: left-to-right, then top-to-bottom
            sorted.sort(function (a, b) {
                var colThreshold = 10;
                if (Math.abs(a.left - b.left) < colThreshold) {
                    return b.top - a.top; // Same column: sort by Y
                }
                return a.left - b.left; // Different columns: sort by X
            });
            break;

        case "name":
            sorted.sort(function (a, b) {
                var nameA = a.name || "";
                var nameB = b.name || "";
                if (nameA < nameB) return -1;
                if (nameA > nameB) return 1;
                return 0;
            });
            break;

        case "positionX":
            sorted.sort(function (a, b) { return a.left - b.left; });
            break;

        case "positionY":
            sorted.sort(function (a, b) { return b.top - a.top; }); // Higher top = earlier
            break;

        case "area":
            sorted.sort(function (a, b) {
                return (a.width * a.height) - (b.width * b.height);
            });
            break;
    }

    return sorted;
}

// ==================== Item Filtering (v2.3) ====================

/**
 * Check if an item is inside a clipping mask (is part of a clipped group content).
 * @param {PageItem} item
 * @returns {boolean}
 */
function isInsideClippingMask(item) {
    var current = item.parent;
    while (current) {
        if (current.typename === "GroupItem" && current.clipped) {
            return true;
        }
        if (current.typename === "Layer" || current.typename === "Document") {
            break;
        }
        try {
            current = current.parent;
        } catch (e) {
            break;
        }
    }
    return false;
}

/**
 * Filter items based on exclusion criteria.
 * @param {Array<PageItem>} items
 * @param {Object} exclude - {locked: bool, hidden: bool, guides: bool, clipped: bool}
 * @returns {Array<PageItem>} Filtered items (new array)
 */
function filterItems(items, exclude) {
    if (!exclude) return items;

    var filtered = [];
    for (var i = 0; i < items.length; i++) {
        var item = items[i];

        if (exclude.locked && item.locked) continue;
        if (exclude.hidden && !item.visible) continue;
        if (exclude.guides && item.guides) continue;
        if (exclude.clipped && isInsideClippingMask(item)) continue;

        filtered.push(item);
    }
    return filtered;
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
 * Recursively collect items from a container (Layer or GroupItem)
 * @param {Object} container - Object with pageItems (Layer, GroupItem)
 * @param {boolean} recursive
 * @returns {Array<PageItem>}
 */
function collectContainerItems(container, recursive) {
    var items = [];
    if (!container || !container.pageItems) return items;

    for (var i = 0; i < container.pageItems.length; i++) {
        var item = container.pageItems[i];
        items.push(item);

        if (recursive && item.typename === "GroupItem") {
            items = items.concat(collectContainerItems(item, true));
        }
    }
    return items;
}

/**
 * Collect all items from a layer
 * @param {Layer} layer
 * @param {boolean} [recursive] - Include nested group items
 * @returns {Array<PageItem>}
 */
function collectLayerItems(layer, recursive) {
    return collectContainerItems(layer, recursive);
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
/**
 * Declarative target selection (v2.3)
 * Supports simple targets, compound targets, filtering, and ordering.
 * @param {Document} doc
 * @param {Object} targets - TargetSelector or Target definition
 * @returns {Array<PageItem>}
 */
/**
 * Declarative target selection (v2.3)
 * Recursively collects items from targets.
 * NOTE: Global filtering and ordering are handled in executeTask.
 * Compound targets handle their own internal exclusion.
 * @param {Document} doc
 * @param {Object} target - Target definition (unwrapped)
 * @returns {Array<PageItem>}
 */
function collectTargets(doc, target) {
    if (!target) target = { type: "selection" };
    var type = target.type || "selection";
    var items = [];

    // Collection
    if (type === "selection") {
        items = selectionToArray(doc.selection);
    }
    else if (type === "all") {
        for (var i = 0; i < doc.layers.length; i++) {
            items = items.concat(collectLayerItems(doc.layers[i], target.recursive));
        }
    }
    else if (type === "layer") {
        var layerName = target.layer;
        var layer = findLayer(doc, layerName);
        if (!layer) throw new Error("Layer not found: " + layerName);
        items = collectLayerItems(layer, target.recursive);
    }
    else if (type === "query") {
        items = queryItems(doc, target);
    }
    else if (type === "compound") {
        if (target.anyOf) {
            for (var j = 0; j < target.anyOf.length; j++) {
                // Recursively collect sub-targets and concatenate
                items = items.concat(collectTargets(doc, target.anyOf[j]));
            }
        }
        // Apply exclusion filter specific to this compound target
        if (target.exclude) {
            items = filterItems(items, target.exclude);
        }
    }
    else {
        throw new Error("Unknown target type: " + type);
    }

    return items;
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

    // === COLLECT stage ===
    var items = [];
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

    return report;
}

// ==================== Payload Validation (v2.3) ====================

/**
 * Validate payload structure (lightweight, no full JSON Schema).
 * Use this before executeTask() for fail-fast validation.
 * 
 * @param {Object} payload
 * @returns {Object} {valid: boolean, errors: Array}
 */
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
        } else if (["selection", "layer", "all", "query", "compound"].indexOf(target.type) < 0) {
            errors.push(makeError(
                ErrorCodes.V_UNKNOWN_TARGET_TYPE,
                "Unknown target type: " + target.type,
                "validate",
                null,
                { validTypes: ["selection", "layer", "all", "query", "compound"] }
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

    // Never retry apply stage unless explicitly in the list
    if (error.stage === "apply" && retryableStages.indexOf("apply") < 0) {
        return false;
    }

    // Check if stage is in allowed list
    if (retryableStages.indexOf(error.stage) < 0) {
        return false;
    }

    // Check if error code is retryable
    return RETRYABLE_CODES.indexOf(error.code) >= 0;
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
                if (retriedStages.indexOf(err.stage) < 0) {
                    retriedStages.push(err.stage);
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
