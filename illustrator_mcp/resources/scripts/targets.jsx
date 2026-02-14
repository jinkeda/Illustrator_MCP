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
        }
        // Fallback to resolveById if available (legacy ops_core path)
        else if (typeof resolveById === "function") {
            items = resolveById(doc, ids, {});
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

