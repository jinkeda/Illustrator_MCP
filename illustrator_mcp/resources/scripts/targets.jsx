/**
 * targets.jsx - Declarative Target Selection & Filtering
 * Part of Illustrator MCP Standard Library
 * @version 1.1.0
 *
 * Provides:
 * - sortItems (deterministic ordering)
 * - filterItems, isInsideClippingMask (exclusion)
 * - collectTargets (declarative target resolution)
 * - Helpers: selectionToArray, pageItemsToArray, findLayer, etc.
 *
 * DEPENDENCIES: polyfills
 * Extracted from task_executor.jsx (Phase 5 decomposition).
 */

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
function collectContainerItems(container, recursive, scan) {
    var items = [];
    if (!container || !container.pageItems) return items;

    for (var i = 0; i < container.pageItems.length; i++) {
        if (scan && scan.limit && ++scan.visited > scan.limit) {
            throwStructured(makeError(ErrorCodes.V_INCOMPLETE_SCAN, "Target scan budget exhausted", "resolve", null,
                {scanned:scan.limit, complete:false, nextStep:"Narrow layer/scope or raise maxScan"}));
        }
        var item = container.pageItems[i];
        items.push(item);

        if (recursive && item.typename === "GroupItem") {
            items = items.concat(collectContainerItems(item, true, scan));
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
function collectLayerItems(layer, recursive, scan) {
    return collectContainerItems(layer, recursive, scan);
}

/**
 * Query items with filters
 * @param {Document} doc
 * @param {Object} query - {layer, itemType, pattern, recursive}
 * @returns {Array<PageItem>}
 */
function queryItems(doc, query, scan) {
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
        var layerItems = collectLayerItems(layers[i], query.recursive || false, scan);

        for (var j = 0; j < layerItems.length; j++) {
            var item = layerItems[j];

            // Type filter
            if (typeFilter && item.typename !== typeFilter) continue;

            // Name filter
            if (regex && !regex.test(item.name || "")) continue;

            if (query.contents !== undefined && query.contents !== null) {
                if (item.typename !== "TextFrame") continue;
                if (String(item.contents).replace(/\r\n|\n/g, "\r") !== query.contents.replace(/\r\n|\n/g, "\r")) continue;
            }
            items.push(item);
        }
    }

    return items;
}

// ==================== Spatial Helpers (C3) ====================

/**
 * Normalize user rect {x, y, width, height} to internal {L, T, R, B}.
 * Illustrator: y positive up, T > B.
 * @param {Object} rect - {x, y, width, height}
 * @returns {{ok: boolean, L: number, T: number, R: number, B: number, error: Object}}
 */
function normalizeRect(rect, doc, coord) {
    if (!rect || typeof rect.x !== "number" || typeof rect.y !== "number" ||
        typeof rect.width !== "number" || typeof rect.height !== "number") {
        return {
            ok: false,
            error: { code: "SP02", message: "Invalid rect: requires x, y, width, height (all numbers)", stage: "spatial" }
        };
    }
    var w = Math.abs(rect.width);
    var h = Math.abs(rect.height);

    if (coord === "ai" || !doc) {
        // Raw Illustrator coords — legacy/power-user mode
        var L = rect.x, T = rect.y;
        var R = L + w, B = T - h;
        // Swap if needed (user passed negative dimensions)
        if (L > R) { var tmpX = L; L = R; R = tmpX; }
        if (B > T) { var tmpY = T; T = B; B = tmpY; }
        return { ok: true, L: L, T: T, R: R, B: B };
    }

    // User coords (default): artboard-relative, origin at top-left, y-down.
    // This is the canonical basis for all user-facing rects (grid cells, spatial queries).
    // Convert to AI-space: aiX = abLeft + x,  aiY = abTop - y  (flip y-down → y-up)
    var abT = 0, abL = 0;
    try {
        var idx = doc.artboards.getActiveArtboardIndex();
        var abr = doc.artboards[idx].artboardRect;  // [L, T, R, B]
        abT = abr[1]; abL = abr[0];
    } catch (e) { }
    var aiX = abL + rect.x;
    var aiY = abT - rect.y;   // top-left in AI space
    return { ok: true, L: aiX, T: aiY, R: aiX + w, B: aiY - h };
}

/**
 * Get center point of a PageItem from geometricBounds.
 * @param {PageItem} item
 * @returns {Array} [cx, cy]
 */
function itemCenter(item) {
    var b = item.geometricBounds; // [left, top, right, bottom]
    return [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
}

/**
 * Check if an item should be included in spatial scan.
 * Skips hidden items, hidden layers, and guides.
 * @param {PageItem} item
 * @returns {boolean}
 */
function spatialScanFilter(item) {
    // Skip hidden items
    try { if (item.hidden) return false; } catch (e) { /* some types may not support .hidden */ }
    // Skip guides
    try { if (item.guides) return false; } catch (e) { }
    // Skip items on hidden layers
    try {
        if (item.layer && !item.layer.visible) return false;
    } catch (e) { }
    return true;
}

/**
 * Collect spatial candidates with pre-snapshotted bounds in one pass.
 *
 * SEMANTIC NOTE: Uses geometricBounds (path geometry only, excludes strokes/effects).
 * Spatial predicates operate on item center points computed from geometricBounds.
 * This is faster and more stable than visibleBounds but may differ from visual extent.
 *
 * Locked layers are NOT skipped (users may query locked reference elements).
 * Locked items may be skipped if bounds access throws.
 *
 * @param {Document} doc
 * @param {string|null} layerFilter - Optional layer name to restrict scan
 * @param {Object} scan - Optional shared {limit, visited} traversal budget
 * @returns {Array<{item: PageItem, cx: number, cy: number, L: number, T: number, R: number, B: number}>}
 */
function collectSpatialCandidatesWithBounds(doc, layerFilter, scan) {
    var result = [];
    for (var i = 0; i < doc.layers.length; i++) {
        if (!doc.layers[i].visible) continue;
        if (layerFilter && doc.layers[i].name !== layerFilter) continue;  // P0: early layer filter
        var layerItems = collectLayerItems(doc.layers[i], true, scan);
        for (var j = 0; j < layerItems.length; j++) {
            if (!spatialScanFilter(layerItems[j])) continue;
            try {
                var b = layerItems[j].geometricBounds;  // single COM call per item
                result.push({
                    item: layerItems[j],
                    cx: (b[0] + b[2]) / 2, cy: (b[1] + b[3]) / 2,
                    L: b[0], T: b[1], R: b[2], B: b[3]
                });
            } catch (e) { /* locked/special items may throw on bounds access */ }
        }
    }
    return result;
}

/**
 * Backward-compatible wrapper preserving old API.
 * Note: inherits new semantics (early layer-visibility filtering, try/catch bounds).
 * @param {Document} doc
 * @returns {Array<PageItem>}
 */
function collectSpatialCandidates(doc) {
    var wb = collectSpatialCandidatesWithBounds(doc, null);
    var items = [];
    for (var i = 0; i < wb.length; i++) items.push(wb[i].item);
    return items;
}

// ==================== Grid Spatial Index (P1) ====================

/**
 * Clamp a value between min and max.
 * @param {number} val
 * @param {number} lo
 * @param {number} hi
 * @returns {number}
 */
function _clamp(val, lo, hi) {
    return val < lo ? lo : (val > hi ? hi : val);
}

/**
 * Build a grid spatial index over pre-snapshotted candidates.
 * Grid resolution adapts to candidate count: cols = rows = clamp(4, 12, round(sqrt(N)/2)).
 * Only used for within/nearTo predicates when candidatesWB.length >= 50.
 *
 * @param {Array} candidatesWB - Output of collectSpatialCandidatesWithBounds
 * @param {Array} abRect - Artboard rect [L, T, R, B]
 * @returns {{grid: Array, cellW: number, cellH: number, cols: number, rows: number}}
 */
function buildSpatialGrid(candidatesWB, abRect) {
    var n = candidatesWB.length;
    var dim = _clamp(Math.round(Math.sqrt(n) / 2), 4, 12);
    var cols = dim, rows = dim;
    var abW = abRect[2] - abRect[0];
    var abH = abRect[1] - abRect[3];  // AI coords: T > B
    if (abW <= 0 || abH <= 0) return null;
    var cellW = abW / cols;
    var cellH = abH / rows;
    var grid = [];
    for (var r = 0; r < rows; r++) {
        grid[r] = [];
        for (var c = 0; c < cols; c++) grid[r][c] = [];
    }
    for (var i = 0; i < n; i++) {
        var col = Math.floor((candidatesWB[i].cx - abRect[0]) / cellW);
        var row = Math.floor((abRect[1] - candidatesWB[i].cy) / cellH);
        col = _clamp(col, 0, cols - 1);
        row = _clamp(row, 0, rows - 1);
        grid[row][col].push(i);
    }
    return { grid: grid, cellW: cellW, cellH: cellH, cols: cols, rows: rows };
}

/**
 * Query a spatial grid for candidate indices whose centers fall in overlapping cells.
 * Returns indices into the candidatesWB array.
 *
 * @param {Object} sg - Spatial grid from buildSpatialGrid
 * @param {{L,T,R,B}} normRect - Normalized query rect
 * @param {Array} abRect - Artboard rect [L, T, R, B]
 * @returns {Array<number>} Candidate indices
 */
function querySpatialGrid(sg, normRect, abRect) {
    var c0 = _clamp(Math.floor((normRect.L - abRect[0]) / sg.cellW), 0, sg.cols - 1);
    var c1 = _clamp(Math.floor((normRect.R - abRect[0]) / sg.cellW), 0, sg.cols - 1);
    var r0 = _clamp(Math.floor((abRect[1] - normRect.T) / sg.cellH), 0, sg.rows - 1);
    var r1 = _clamp(Math.floor((abRect[1] - normRect.B) / sg.cellH), 0, sg.rows - 1);
    var indices = [];
    for (var r = r0; r <= r1; r++) {
        for (var c = c0; c <= c1; c++) {
            var bucket = sg.grid[r][c];
            for (var b = 0; b < bucket.length; b++) indices.push(bucket[b]);
        }
    }
    return indices;
}

/**
 * Throw a structured error from a makeError envelope.
 * Preserves .code and .stage so catch blocks can classify without parsing strings.
 * @param {Object} envelope - makeError return value {ok:false, error:{code,message,stage}}
 */
function throwStructured(envelope) {
    var err = new Error(envelope.error.message);
    err.code = envelope.error.code;
    err.stage = envelope.error.stage;
    err.meta = envelope.error.details || null;
    throw err;
}

/**
 * Normalize both the public TargetSelector wrapper and the legacy unwrapped
 * selector.  Every caller uses this one path for defaults, exclusions,
 * ordering and scan bounds.
 *
 * @param {Object|null} selector
 * @returns {Object} {target, orderBy, exclude, maxScan}
 */
function _selectorKeys(value, keys, label) {
    if (!value || typeof value !== "object" || value instanceof Array) {
        throwStructured(makeError(ErrorCodes.V_INVALID_TARGETS, label + " must be an object", "resolve"));
    }
    for (var key in value) {
        if (Object.prototype.hasOwnProperty.call(value, key) && keys.indexOf(key) < 0) {
            if (key === "expect") throwStructured(makeError(ErrorCodes.V_INVALID_TARGETS,
                "Move expect to the outer TargetSelector", "resolve", null,
                {nextStep:"Move expect outside target and anyOf children"}));
            throwStructured(makeError(ErrorCodes.V_INVALID_TARGETS,
                "Unknown " + label + " field '" + key + "'. Allowed: " + keys.join(", "), "resolve"));
        }
    }
}

function normalizeTargetSelector(selector) {
    var depth = arguments.length > 1 ? arguments[1] : 0;
    if (depth > 16) throwStructured(makeError(ErrorCodes.V_INVALID_TARGETS, "Selector exceeds 16 compound levels", "resolve"));
    selector = selector || { type: "selection" };
    if (typeof selector !== "object" || selector instanceof Array) {
        throwStructured(makeError(ErrorCodes.V_INVALID_TARGETS,
            "Target selector must be an object", "resolve"));
    }

    var wrapped = selector.target !== undefined;
    if (wrapped) _selectorKeys(selector, ["target", "orderBy", "exclude", "maxScan", "expect"], "selector");
    var target = wrapped ? selector.target : selector;
    if (!target || typeof target !== "object" || target instanceof Array) {
        throwStructured(makeError(ErrorCodes.V_INVALID_TARGETS,
            "Target selector.target must be an object", "resolve"));
    }

    var type = target.type || "selection";
    var allowed = {
        selection: true, all: true, layer: true, query: true, id: true,
        spatial: true, grid: true, compound: true, handle: true
    };
    if (!allowed[type]) {
        throwStructured(makeError(ErrorCodes.V_UNKNOWN_TARGET_TYPE,
            "Unknown target type: " + type, "resolve"));
    }
    var fields = {
        selection: [], all: ["recursive"], layer: ["layer", "recursive"],
        query: ["layer", "itemType", "pattern", "contents", "recursive"], id: ["ids"],
        handle: ["handles"], spatial: ["within", "outside", "nearTo", "coord", "layer"],
        grid: ["cell", "cols", "rows", "layer"], compound: ["anyOf", "exclude"]
    };
    _selectorKeys(target, ["type"].concat(fields[type]).concat(wrapped ? [] : ["orderBy", "exclude", "maxScan", "expect"]), "target");
    if (target.recursive !== undefined && typeof target.recursive !== "boolean") {
        throwStructured(makeError(ErrorCodes.V_INVALID_TARGETS, "target.recursive must be boolean", "resolve"));
    }
    var filters = [target.exclude, wrapped ? selector.exclude : null];
    for (var fi = 0; fi < filters.length; fi++) {
        if (filters[fi] != null) {
            _selectorKeys(filters[fi], ["locked", "hidden", "guides", "clipped"], "exclude");
            for (var fk in filters[fi]) {
                if (typeof filters[fi][fk] !== "boolean") {
                    throwStructured(makeError(ErrorCodes.V_INVALID_TARGETS, "exclude." + fk + " must be boolean", "resolve"));
                }
            }
        }
    }
    if (type === "spatial") {
        if (target.within != null) _selectorKeys(target.within, ["x", "y", "width", "height"], "within");
        if (target.outside != null) _selectorKeys(target.outside, ["x", "y", "width", "height"], "outside");
        if (target.nearTo != null) _selectorKeys(target.nearTo, ["id", "radius"], "nearTo");
    }
    target.type = type;

    if (type === "layer" && (typeof target.layer !== "string" || !target.layer)) {
        throwStructured(makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM,
            "Layer target requires a non-empty layer name", "resolve"));
    }
    if (type === "query" && !target.layer && !target.itemType && !target.pattern && target.contents == null) {
        throwStructured(makeError(ErrorCodes.V_INVALID_TARGETS,
            "Query target requires layer, itemType, pattern, or contents", "resolve"));
    }
    if (type === "id" && (!(target.ids instanceof Array) || target.ids.length === 0)) {
        throwStructured(makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM,
            "ID target requires a non-empty ids array", "resolve"));
    }
    if (type === "handle" && (!(target.handles instanceof Array) || target.handles.length === 0)) {
        throwStructured(makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM,
            "Handle target requires a non-empty handles array", "resolve"));
    }
    if (type === "compound" && (!(target.anyOf instanceof Array) || target.anyOf.length === 0)) {
        throwStructured(makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM,
            "Compound target requires a non-empty anyOf array", "resolve"));
    }
    if (type === "compound") {
        for (var ci = 0; ci < target.anyOf.length; ci++) {
            var child = target.anyOf[ci];
            if (!child || child.target !== undefined) {
                throwStructured(makeError(ErrorCodes.V_INVALID_TARGETS, "compound.anyOf requires target objects", "resolve"));
            }
            normalizeTargetSelector(child, depth + 1);
        }
    }

    var expect = wrapped ? selector.expect : target.expect;
    if ((depth > 0 && expect !== undefined) || (wrapped && target.expect !== undefined)) {
        throwStructured(makeError(ErrorCodes.V_INVALID_TARGETS, "Move expect to the outer TargetSelector", "resolve", null,
            {nextStep: "Move expect outside target and anyOf children"}));
    }
    if (expect !== undefined && expect !== null) {
        _selectorKeys(expect, ["count"], "expect");
        if (typeof expect.count !== "number" || !isFinite(expect.count) || expect.count < 0 || expect.count !== Math.floor(expect.count))
            throwStructured(makeError(ErrorCodes.V_INVALID_TARGETS, "expect.count must be a nonnegative integer", "resolve"));
    }
    if (target.contents !== undefined && target.contents !== null && typeof target.contents !== "string")
        throwStructured(makeError(ErrorCodes.V_INVALID_TARGETS, "contents must be a string", "resolve"));
    var orderBy = wrapped ? (selector.orderBy || "zOrder") : (target.orderBy || "zOrder");
    var orders = {
        zOrder: true, zOrderReverse: true, reading: true, column: true,
        name: true, positionX: true, positionY: true, area: true
    };
    if (!orders[orderBy]) {
        throwStructured(makeError(ErrorCodes.V_INVALID_PARAM_VALUE,
            "Unknown target orderBy: " + orderBy, "resolve"));
    }

    var maxScan = wrapped ? selector.maxScan : target.maxScan;
    if (maxScan !== undefined &&
        (typeof maxScan !== "number" || maxScan <= 0 || maxScan !== Math.floor(maxScan))) {
        throwStructured(makeError(ErrorCodes.V_INVALID_PARAM_VALUE,
            "Target maxScan must be a positive integer", "resolve"));
    }

    return {
        target: target,
        orderBy: orderBy,
        exclude: wrapped ? (selector.exclude || null) : (target.exclude || null),
        maxScan: maxScan || 0, expect: expect
    };
}

/** Remove duplicate object references while retaining first-seen order. */
function dedupeTargetItems(items) {
    var out = [];
    for (var i = 0; i < items.length; i++) {
        var duplicate = false;
        for (var j = 0; j < out.length; j++) {
            if (out[j] === items[i]) { duplicate = true; break; }
        }
        if (!duplicate) out.push(items[i]);
    }
    return out;
}

/**
 * Declarative target selection (v2.3)
 * Recursively collects items from targets.
 * NOTE: Global filtering and ordering are handled in executeTask.
 * Compound targets handle their own internal exclusion.
 * @param {Document} doc
 * @param {Object} target - Target definition (unwrapped)
 * @returns {Array<PageItem>}
 */
function collectTargets(doc, target, opts) {
    // `opts.report` collects facts the caller must be told about but that do
    // not justify aborting — currently the requested IDs that matched nothing.
    if (opts && opts.report && !(opts.report.unresolvedIds instanceof Array)) {
        opts.report.unresolvedIds = [];
    }
    var normalized = normalizeTargetSelector(target);
    opts = opts || {};
    if (normalized.expect) opts.requireIdentities = true;
    var scan = opts.scan || {limit:normalized.maxScan, visited:0};
    opts.scan = scan;
    target = normalized.target;
    var type = target.type;
    var items = [];

    // Collection
    if (type === "selection") {
        // A managed batch captures selection once. Later operations use that
        // same object set even if Illustrator changes its live selection.
        items = (opts && opts.startingSelection)
            ? opts.startingSelection.slice()
            : selectionToArray(doc.selection);
        scan.visited += items.length;
        if (scan.limit && scan.visited > scan.limit) {
            throwStructured(makeError(ErrorCodes.V_INCOMPLETE_SCAN, "Target scan budget exhausted", "resolve", null,
                {scanned:scan.limit, complete:false, nextStep:"Narrow scope or raise maxScan"}));
        }
    }
    else if (type === "all") {
        for (var i = 0; i < doc.layers.length; i++) {
            items = items.concat(collectLayerItems(doc.layers[i], target.recursive, scan));
        }
    }
    else if (type === "layer") {
        var layerName = target.layer;
        var layer = findLayer(doc, layerName);
        if (!layer) throw new Error("Layer not found: " + layerName);
        items = collectLayerItems(layer, target.recursive, scan);
    }
    else if (type === "query") {
        items = queryItems(doc, target, scan);
    }
    else if (type === "id") {
        // Exact, duplicate-aware lookup. A heap hit alone cannot prove that a
        // second item with the same stamped ID does not exist.
        var ids = target.ids || [];
        for (var idi = 0; idi < ids.length; idi++) {
            if (typeof ids[idi] !== "string" || !ids[idi]) {
                throwStructured(makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
                    "Target IDs must be non-empty strings", "resolve"));
            }
            if (scan.limit && scan.visited >= scan.limit) {
                throwStructured(makeError(ErrorCodes.V_INCOMPLETE_SCAN, "Target scan budget exhausted", "resolve", null,
                    {scanned:scan.visited, complete:false, nextStep:"Narrow scope or raise maxScan"}));
            }
            var found = findItemsByMcpId(doc, ids[idi], { limit: scan.limit ? scan.limit - scan.visited : 0 });
            scan.visited += found.scanned;
            if (found.truncated) {
                throwStructured(makeError(ErrorCodes.V_INCOMPLETE_SCAN || "V013",
                    "ID scan was capped before identity could be proven: " + ids[idi],
                    "resolve", null,
                    { id: ids[idi], scanned: scan.visited, complete: false, nextStep: "Narrow scope or raise maxScan" }));
            }
            if (found.duplicate) {
                throwStructured(makeError(ErrorCodes.V_AMBIGUOUS_ID || "V012",
                    "Ambiguous MCP ID matched " + found.items.length + " items: " + ids[idi],
                    "resolve", null, { id: ids[idi], matches: found.items.length }));
            }
            if (found.items.length === 1) {
                items.push(found.items[0]);
            } else {
                // A requested ID that matched nothing. Duplicates and capped
                // scans throw above; a MISSING id used to be dropped in
                // silence, so styling ["S0","GHOST"] reported ok/complete with
                // no mention of GHOST anywhere — the caller could not tell
                // that one of its targets never existed.
                //
                // It is not thrown, because asking to act on whichever of a
                // set still exists is legitimate. It is REPORTED instead, and
                // the caller decides.
                if (opts.requireIdentities) throwStructured(makeError(ErrorCodes.R_ELEMENT_NOT_FOUND,
                    "Requested ID does not exist: " + ids[idi], "resolve", null,
                    {nextStep: "Query again for a current identity"}));
                if (opts && opts.report) opts.report.unresolvedIds.push(ids[idi]);
            }
        }
    }
    else if (type === "handle") {
        if (typeof mcpResolveHandle !== "function") {
            throwStructured(makeError(ErrorCodes.R_COLLECT_FAILED,
                "Artwork handle resolver is unavailable", "resolve"));
        }
        var handles = target.handles || [];
        for (var hdi = 0; hdi < handles.length; hdi++) {
            var handleResult = mcpResolveHandle(handles[hdi], doc, {scan:scan});
            if (handleResult.status === "incomplete") {
                throwStructured(makeError(ErrorCodes.V_INCOMPLETE_SCAN, "Handle scan budget exhausted", "resolve", null,
                    {scanned:scan.visited, complete:false, nextStep:"Narrow scope or raise maxScan"}));
            }
            if (!handleResult.ok) {
                throwStructured(makeError(ErrorCodes.V_INVALID_TARGETS,
                    "Artwork handle could not be resolved: " + handles[hdi] +
                    " (" + handleResult.status + ")", "resolve", null,
                    { handle: handles[hdi], status: handleResult.status }));
            }
            items.push(handleResult.item);
        }
    }
    else if (type === "spatial") {
        // C3: Spatial query targets
        // Spatial predicates operate on item center points computed from geometricBounds.
        var hasWithin = target.within;
        var hasNearTo = target.nearTo;
        var hasOutside = target.outside;
        if (!hasWithin && !hasNearTo && !hasOutside) {
            throwStructured(makeError(ErrorCodes.SP_MISSING_PREDICATE,
                "Spatial target requires within, nearTo, or outside predicate", "collect"));
        }

        // Validate coord flag: type guard first, then enum
        if (target.coord !== undefined) {
            if (typeof target.coord !== "string") {
                throwStructured(makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
                    "target.coord must be a string, got " + typeof target.coord, "collect"));
            } else if (target.coord !== "user" && target.coord !== "ai") {
                throwStructured(makeError(ErrorCodes.V_INVALID_PARAM_VALUE,
                    "target.coord must be 'user' or 'ai', got '" + target.coord + "'", "collect"));
            }
        }
        // Validate layer: string only (v1)
        if (target.layer !== undefined && typeof target.layer !== "string") {
            throwStructured(makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
                "target.layer must be a string, got " + typeof target.layer, "collect"));
        }

        // One-pass scan with snapshotted bounds + early layer filter
        var candidatesWB = collectSpatialCandidatesWithBounds(doc, target.layer || null, scan);

        // Spatial predicates are combined as OR (union):
        // - within + nearTo → items inside rect OR near reference
        // - within + outside on same rect degenerates to all candidates
        // Runtime guard intentionally duplicates validatePayload checks for safety.

        // Helper: get artboard rect for grid index (lazily resolved)
        var _abRect = null;
        function _getAbRect() {
            if (!_abRect) {
                try {
                    var idx = doc.artboards.getActiveArtboardIndex();
                    _abRect = doc.artboards[idx].artboardRect;
                } catch (e) { _abRect = [0, 0, 0, 0]; }
            }
            return _abRect;
        }

        if (hasWithin) {
            var normW = normalizeRect(hasWithin, doc, target.coord || "user");
            if (!normW.ok) throwStructured(normW);

            // P1: Use grid index for large candidate sets
            if (candidatesWB.length >= 50) {
                var sgW = buildSpatialGrid(candidatesWB, _getAbRect());
                if (sgW) {
                    var cellIdxs = querySpatialGrid(sgW, normW, _getAbRect());
                    for (var gi = 0; gi < cellIdxs.length; gi++) {
                        var cw = candidatesWB[cellIdxs[gi]];
                        if (cw.cx >= normW.L && cw.cx <= normW.R && cw.cy <= normW.T && cw.cy >= normW.B) {
                            items.push(cw.item);
                        }
                    }
                } else {
                    // Grid build failed (zero-size artboard), fall through to linear
                    for (var si = 0; si < candidatesWB.length; si++) {
                        if (candidatesWB[si].cx >= normW.L && candidatesWB[si].cx <= normW.R &&
                            candidatesWB[si].cy <= normW.T && candidatesWB[si].cy >= normW.B) {
                            items.push(candidatesWB[si].item);
                        }
                    }
                }
            } else {
                // Small candidate set → linear scan (no grid overhead)
                for (var si = 0; si < candidatesWB.length; si++) {
                    if (candidatesWB[si].cx >= normW.L && candidatesWB[si].cx <= normW.R &&
                        candidatesWB[si].cy <= normW.T && candidatesWB[si].cy >= normW.B) {
                        items.push(candidatesWB[si].item);
                    }
                }
            }
        }

        if (hasOutside) {
            // Outside stays linear — complement set doesn't benefit from grid index
            var normO = normalizeRect(hasOutside, doc, target.coord || "user");
            if (!normO.ok) throwStructured(normO);

            for (var oi = 0; oi < candidatesWB.length; oi++) {
                var inside = candidatesWB[oi].cx >= normO.L && candidatesWB[oi].cx <= normO.R &&
                    candidatesWB[oi].cy <= normO.T && candidatesWB[oi].cy >= normO.B;
                if (!inside) items.push(candidatesWB[oi].item);
            }
        }

        if (hasNearTo) {
            if (!hasNearTo.id || typeof hasNearTo.radius !== "number") {
                throwStructured(makeError(ErrorCodes.SP_INVALID_RECT,
                    "nearTo requires id (string) and radius (number)", "collect"));
            }
            // Resolve reference item
            var refItems;
            if (!scan.limit && typeof heapResolveMany === "function") {
                refItems = heapResolveMany(doc, [hasNearTo.id]);
            } else {
                refItems = collectTargets(doc, { type: "id", ids: [hasNearTo.id], maxScan: normalized.maxScan }, opts);
            }
            if (!refItems || refItems.length === 0) {
                throwStructured(makeError(ErrorCodes.SP_REF_NOT_FOUND,
                    "nearTo reference item not found: " + hasNearTo.id, "collect"));
            }
            if (refItems.length > 1) {
                throwStructured(makeError(ErrorCodes.SP_REF_NOT_FOUND,
                    "nearTo requires exactly one reference item, found " + refItems.length, "collect"));
            }
            var refCenter = itemCenter(refItems[0]);
            var rad = hasNearTo.radius;
            var r2 = rad * rad;

            // P1: Grid prefilter for nearTo — expand ref center by radius to bounding rect
            if (candidatesWB.length >= 50) {
                var nearNorm = {
                    L: refCenter[0] - rad, R: refCenter[0] + rad,
                    T: refCenter[1] + rad, B: refCenter[1] - rad
                };
                var sgN = buildSpatialGrid(candidatesWB, _getAbRect());
                if (sgN) {
                    var nearIdxs = querySpatialGrid(sgN, nearNorm, _getAbRect());
                    for (var ngi = 0; ngi < nearIdxs.length; ngi++) {
                        var cn = candidatesWB[nearIdxs[ngi]];
                        if (cn.item === refItems[0]) continue;  // Skip ref item
                        var dx = cn.cx - refCenter[0];
                        var dy = cn.cy - refCenter[1];
                        if (dx * dx + dy * dy <= r2) items.push(cn.item);
                    }
                } else {
                    // Grid failed, linear fallback
                    for (var ni = 0; ni < candidatesWB.length; ni++) {
                        if (candidatesWB[ni].item === refItems[0]) continue;
                        var dx = candidatesWB[ni].cx - refCenter[0];
                        var dy = candidatesWB[ni].cy - refCenter[1];
                        if (dx * dx + dy * dy <= r2) items.push(candidatesWB[ni].item);
                    }
                }
            } else {
                for (var ni = 0; ni < candidatesWB.length; ni++) {
                    if (candidatesWB[ni].item === refItems[0]) continue;
                    var dx = candidatesWB[ni].cx - refCenter[0];
                    var dy = candidatesWB[ni].cy - refCenter[1];
                    if (dx * dx + dy * dy <= r2) items.push(candidatesWB[ni].item);
                }
            }
        }
    }
    else if (type === "grid") {
        // Grid target: maps cell label (A1, B2) to spatial within rect.
        // Delegates to spatial — no recursion back to grid.
        var cellLabel = (target.cell || "").toUpperCase();
        if (!cellLabel) {
            throwStructured(makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM,
                "grid target requires 'cell' param", "collect"));
        }
        var grid = artboardGrid(target.cols || 4, target.rows || 4);
        var cell = grid.cells[cellLabel];
        if (!cell) {
            throwStructured(makeError(ErrorCodes.V_INVALID_PARAM_VALUE,
                "Unknown grid cell: " + cellLabel + ". Valid: A1.." +
                String.fromCharCode(64 + (target.rows || 4)) + (target.cols || 4),
                "collect"));
        }
        items = collectTargets(doc, {
            type: "spatial", within: cell, coord: "user",
            layer: target.layer  // optional layer filter passthrough
        }, opts);
    }
    else if (type === "compound") {
        if (target.anyOf) {
            for (var j = 0; j < target.anyOf.length; j++) {
                // Recursively collect sub-targets and concatenate
                items = items.concat(collectTargets(doc, target.anyOf[j], opts));
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

    items = dedupeTargetItems(items);
    if (normalized.exclude) items = filterItems(items, normalized.exclude);
    items = sortItems(items, normalized.orderBy);

    if (normalized.expect && items.length !== normalized.expect.count) {
        var candidates = [];
        for (var ei = 0; ei < items.length && ei < 20; ei++) {
            var candidate = {type: items[ei].typename, name: String(items[ei].name || "").substr(0, 200)};
            try {
                if (typeof mcpIssueHandle === "function" && typeof mcpDocBind === "function") {
                    var binding = mcpDocBind({label:"target_candidates"});
                    var issued = mcpIssueHandle(items[ei], _mcpBindingToken(binding));
                    if (issued.ok) candidate.handle = issued.record.handle;
                }
            } catch (handleError) { }
            if (items[ei].typename === "TextFrame") candidate.contents = String(items[ei].contents).substr(0, 500);
            candidates.push(candidate);
        }
        throwStructured(makeError(ErrorCodes.V_TARGET_COUNT_MISMATCH, "Target count mismatch", "resolve", null,
            {expected: normalized.expect.count, actual: items.length, candidates: candidates,
             nextStep: "Inspect candidates and refine the selector"}));
    }
    return items;
}

