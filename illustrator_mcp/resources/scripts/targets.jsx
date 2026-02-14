/**
 * targets.jsx - Declarative Target Selection & Filtering
 * Part of Illustrator MCP Standard Library
 * @version 1.0.0
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

    // User coords (default): artboard-relative, y-down from top-left
    // Convert: aiX = abLeft + x,  aiY = abTop - y  (flip y-down → y-up)
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
 * Collect all scannable PageItems from the document for spatial queries.
 * Recurses into groups, skips hidden/guides.
 * @param {Document} doc
 * @returns {Array<PageItem>}
 */
function collectSpatialCandidates(doc) {
    var candidates = [];
    for (var i = 0; i < doc.layers.length; i++) {
        if (!doc.layers[i].visible) continue;  // Skip hidden layers
        var layerItems = collectLayerItems(doc.layers[i], true);
        for (var j = 0; j < layerItems.length; j++) {
            if (spatialScanFilter(layerItems[j])) {
                candidates.push(layerItems[j]);
            }
        }
    }
    return candidates;
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
    else if (type === "id") {
        // ID-based targeting: stable O(1) resolution
        var ids = target.ids || [];
        if (ids.length === 0) return items;

        // Prefer heap (Phase 2+) for identity-verified resolution
        if (typeof heapResolveMany === "function") {
            items = heapResolveMany(doc, ids);
            // If no txn active and nothing found, try one explicit rebuild
            if (items.length === 0 && ids.length > 0 && typeof heapRebuildIndex === "function") {
                heapRebuildIndex(doc);
                items = heapResolveMany(doc, ids);
            }
        }
        // Last resort: full document scan
        else {
            var allItems = [];
            for (var k = 0; k < doc.layers.length; k++) {
                allItems = allItems.concat(collectLayerItems(doc.layers[k], true));
            }
            for (var m = 0; m < allItems.length; m++) {
                try {
                    if (allItems[m].note) {
                        var match = allItems[m].note.match(/@mcp:id=([^\s@]+)/);
                        if (match && ids.indexOf(match[1]) >= 0) {
                            items.push(allItems[m]);
                        }
                    }
                } catch (e) { /* some items may not support .note */ }
            }
        }
    }
    else if (type === "spatial") {
        // C3: Spatial query targets
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

        var candidates = collectSpatialCandidates(doc);

        // P1: Optional layer filter for spatial targets
        var spatialLayer = target.layer || null;
        if (spatialLayer) {
            var filtered = [];
            for (var fi = 0; fi < candidates.length; fi++) {
                try { if (candidates[fi].layer.name === spatialLayer) filtered.push(candidates[fi]); } catch (e) { }
            }
            candidates = filtered;
        }

        // Spatial predicates are combined as OR (union):
        // - within + nearTo → items inside rect OR near reference
        // - within + outside on same rect degenerates to all candidates
        // Runtime guard intentionally duplicates validatePayload checks for safety.
        if (hasWithin || hasOutside) {
            var rectSpec = hasWithin || hasOutside;
            var norm = normalizeRect(rectSpec, doc, target.coord || "user");
            if (!norm.ok) throwStructured(norm);

            for (var si = 0; si < candidates.length; si++) {
                var c = itemCenter(candidates[si]);
                var inside = c[0] >= norm.L && c[0] <= norm.R && c[1] <= norm.T && c[1] >= norm.B;
                if (hasWithin && inside) items.push(candidates[si]);
                if (hasOutside && !inside) items.push(candidates[si]);
            }
        }

        if (hasNearTo) {
            if (!hasNearTo.id || typeof hasNearTo.radius !== "number") {
                throwStructured(makeError(ErrorCodes.SP_INVALID_RECT,
                    "nearTo requires id (string) and radius (number)", "collect"));
            }
            // Resolve reference item
            var refItems;
            if (typeof heapResolveMany === "function") {
                refItems = heapResolveMany(doc, [hasNearTo.id]);
            } else {
                refItems = collectTargets(doc, { type: "id", ids: [hasNearTo.id] });
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
            var r = hasNearTo.radius;
            var r2 = r * r;

            for (var ni = 0; ni < candidates.length; ni++) {
                // Skip the reference item itself
                if (candidates[ni] === refItems[0]) continue;
                var nc = itemCenter(candidates[ni]);
                var dx = nc[0] - refCenter[0];
                var dy = nc[1] - refCenter[1];
                if (dx * dx + dy * dy <= r2) items.push(candidates[ni]);
            }
        }
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

