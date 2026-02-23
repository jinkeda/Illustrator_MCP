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
 * @returns {Array<{item: PageItem, cx: number, cy: number, L: number, T: number, R: number, B: number}>}
 */
function collectSpatialCandidatesWithBounds(doc, layerFilter) {
    var result = [];
    for (var i = 0; i < doc.layers.length; i++) {
        if (!doc.layers[i].visible) continue;
        if (layerFilter && doc.layers[i].name !== layerFilter) continue;  // P0: early layer filter
        var layerItems = collectLayerItems(doc.layers[i], true);
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
        var candidatesWB = collectSpatialCandidatesWithBounds(doc, target.layer || null);

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
        return collectTargets(doc, {
            type: "spatial", within: cell, coord: "user",
            layer: target.layer  // optional layer filter passthrough
        });
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

