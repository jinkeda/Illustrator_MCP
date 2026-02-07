/**
 * validate.jsx - Bounds validation for Illustrator MCP
 * Part of Illustrator MCP Standard Library
 *
 * Provides centralized bounds validation for artboard checking.
 * Used by: validate_bounds param, preflight_check tool, export pre-check
 */

/**
 * Check if an item's center is on the given artboard.
 *
 * @param {Array} itemBounds - Item bounds [left, top, right, bottom]
 * @param {Array} artboardRect - Artboard rect [left, top, right, bottom]
 * @returns {boolean} True if item center is within artboard
 */
function isItemCenterOnArtboard(itemBounds, artboardRect) {
    var centerX = (itemBounds[0] + itemBounds[2]) / 2;
    var centerY = (itemBounds[1] + itemBounds[3]) / 2;
    // artboardRect: [left, top, right, bottom] where top > bottom
    return (centerX >= artboardRect[0] && centerX <= artboardRect[2] &&
            centerY <= artboardRect[1] && centerY >= artboardRect[3]);
}

/**
 * Check if any ancestor layer of an item is hidden.
 *
 * @param {PageItem} item - The item to check
 * @returns {boolean} True if any ancestor layer is hidden
 */
function isLayerHidden(item) {
    try {
        var l = item.layer;
        while (l) {
            if (!l.visible) return true;
            if (l.parent && l.parent.typename === 'Layer') {
                l = l.parent;
            } else {
                break;
            }
        }
    } catch (e) {}
    return false;
}

/**
 * Count items on/off artboard with configurable policy.
 *
 * @param {Object} opts - Options object
 * @param {number|null} opts.artboardIndex - Artboard index (null = active)
 * @param {string} opts.boundsType - "visible" (default) or "geometric"
 * @param {string} opts.boundsSource - "group_visible" (default) or "clipping_path"
 * @param {string} opts.policy - "fully-contained" (default) or "intersects"
 * @param {string} opts.scope - "document" (default) or "artboard"
 * @param {boolean} opts.ignoreHidden - Skip hidden items (default: true)
 * @param {boolean} opts.ignoreLocked - Skip locked items (default: true)
 *
 * @returns {string} JSON string with counts and metadata
 *
 * boundsSource options:
 *   - "group_visible": Use group's visible/geometric bounds (default)
 *   - "clipping_path": For clipped groups, use clipping path's geometric bounds
 *
 * Policies:
 *   - "fully-contained": item must be entirely within artboard
 *   - "intersects": item must have any overlap with artboard
 *
 * Scope options:
 *   - "document": Check all items in document (default)
 *   - "artboard": Only check items whose center is on target artboard
 *
 * Counts:
 *   - items_total = on_artboard + off_artboard + skipped
 *   - items_checked = on_artboard + off_artboard
 */
function countItemsOnArtboard(opts) {
    opts = opts || {};
    var doc = app.activeDocument;

    // Resolve artboard index
    var abIdx = (opts.artboardIndex !== null && opts.artboardIndex !== undefined)
        ? opts.artboardIndex
        : doc.artboards.getActiveArtboardIndex();

    var ab = doc.artboards[abIdx].artboardRect;
    // artboardRect = [left, top, right, bottom] where top > bottom

    var boundsType = opts.boundsType || "visible";
    var boundsSource = opts.boundsSource || "group_visible";
    var policy = opts.policy || "fully-contained";
    var scope = opts.scope || "document";
    var ignoreHidden = opts.ignoreHidden !== false;  // default true
    var ignoreLocked = opts.ignoreLocked !== false;  // default true

    var on = 0, off = 0, skipped = 0;
    var offItems = [];  // Track names of off-artboard items (first 10)

    for (var i = 0; i < doc.pageItems.length; i++) {
        var item = doc.pageItems[i];

        // Defensive: some exotic PageItem types may not have hidden/locked
        var isHidden = (typeof item.hidden !== 'undefined') ? item.hidden : false;
        var isLocked = (typeof item.locked !== 'undefined') ? item.locked : false;

        // Skip hidden/locked if requested (including items on hidden layers)
        if (ignoreHidden && (isHidden || isLayerHidden(item))) { skipped++; continue; }
        if (ignoreLocked && isLocked) { skipped++; continue; }

        // Get bounds based on type and source
        var b;
        try {
            if (boundsSource === "clipping_path" &&
                item.typename === "GroupItem" &&
                item.clipped) {
                // Find clipping path within the group
                var clipPath = null;
                for (var j = 0; j < item.pathItems.length; j++) {
                    if (item.pathItems[j].clipping) {
                        clipPath = item.pathItems[j];
                        break;
                    }
                }
                if (clipPath) {
                    // Use geometric bounds for clipping path (stroke doesn't define clip area)
                    b = clipPath.geometricBounds;
                } else {
                    // Fallback to standard bounds if no clipping path found
                    b = (boundsType === "visible") ? item.visibleBounds : item.geometricBounds;
                }
            } else {
                b = (boundsType === "visible") ? item.visibleBounds : item.geometricBounds;
            }
        } catch (e) {
            // Some items may not have bounds accessible
            skipped++;
            continue;
        }

        // Scope filter: skip items whose center is not on target artboard
        if (scope === "artboard" && !isItemCenterOnArtboard(b, ab)) {
            skipped++;
            continue;
        }

        // b = [left, top, right, bottom] where top > bottom
        var isOn = false;

        if (policy === "intersects") {
            // Intersects: any overlap with artboard = on
            // No intersection if: item.right < ab.left OR item.left > ab.right
            //                  OR item.bottom > ab.top OR item.top < ab.bottom
            var noIntersection = (b[2] < ab[0] || b[0] > ab[2] || b[3] > ab[1] || b[1] < ab[3]);
            isOn = !noIntersection;
        } else {
            // Fully-contained: entire item within artboard = on
            // item.left >= ab.left AND item.right <= ab.right
            // AND item.top <= ab.top AND item.bottom >= ab.bottom
            isOn = (b[0] >= ab[0] && b[2] <= ab[2] && b[1] <= ab[1] && b[3] >= ab[3]);
        }

        if (isOn) {
            on++;
        } else {
            off++;
            // Track first 10 off-artboard items for debugging
            if (offItems.length < 10) {
                offItems.push(item.name || ("item_" + i));
            }
        }
    }

    return JSON.stringify({
        on_artboard: on,
        off_artboard: off,
        skipped: skipped,
        items_total: on + off + skipped,
        items_checked: on + off,
        artboard_index: abIdx,
        artboard_rect: ab,
        bounds_type: boundsType,
        bounds_source: boundsSource,
        policy: policy,
        scope: scope,
        off_items_sample: offItems
    });
}
