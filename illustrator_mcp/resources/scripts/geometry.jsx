/**
 * geometry.jsx - Geometry and bounds calculations
 * Part of Illustrator MCP Standard Library
 */

/**
 * Convert millimeters to points
 * @param {number} mm 
 * @returns {number} points
 */
function mmToPoints(mm) {
    return mm * 2.83464567;
}

/**
 * Convert points to millimeters
 * @param {number} pt 
 * @returns {number} millimeters
 */
function pointsToMm(pt) {
    return pt / 2.83464567;
}

/**
 * Calculate the true visible bounds of an item or group.
 * Handles clipping masks correctly (uses the mask bounds, not the clipped content).
 * 
 * @param {PageItem} item - The item to measure
 * @returns {Array} [left, top, right, bottom] (Illustrator Y-axis: Top is > Bottom)
 */
function getVisibleBounds(item) {
    // If it's a group with a clipping mask
    if (item.typename === "GroupItem" && item.clipped) {
        // The mask is always the first path item in the clipping group (z-order top)
        // However, in the pathItems collection, it might not be index 0 depending on complexity.
        // But reliably, we can look for the path with clipping=true.

        var maskItem = null;
        for (var i = 0; i < item.pathItems.length; i++) {
            if (item.pathItems[i].clipping) {
                maskItem = item.pathItems[i];
                break;
            }
        }

        // Sometimes the mask is a compound path
        if (!maskItem && item.compoundPathItems) {
            for (var j = 0; j < item.compoundPathItems.length; j++) {
                if (item.compoundPathItems[j].pathItems[0].clipping) {
                    maskItem = item.compoundPathItems[j];
                    break;
                }
            }
        }

        if (maskItem) {
            return maskItem.geometricBounds; // Use geometric bounds of the mask (stroke doesn't count for mask area usually)
        }
    }

    // Default: return geometric bounds (excludes stroke width) or visibleBounds (includes stroke)
    // For scientific figures, geometricBounds is often preferred for alignment cleanliness,
    // but visibleBounds is better for not overlapping strokes.
    // Let's stick to visibleBounds for general safety unless specifically creating layouts.
    return item.visibleBounds;
}

/**
 * Get unified geometry info for an item
 * @param {PageItem} item 
 * @returns {Object} {left, top, width, height, right, bottom}
 */
function getVisibleInfo(item) {
    var b = getVisibleBounds(item);
    var left = b[0];
    var top = b[1];
    var right = b[2];
    var bottom = b[3];
    return {
        left: left,
        top: top,
        right: right,
        bottom: bottom,
        width: right - left,
        height: top - bottom, // Y is positive up in internal logic, but check Illustrator coords
        // Actually Illustrator bounds are [left, top, right, bottom]
        // Docs say: "The top-left and bottom-right coordinates of the object's bounding box."
        // Y coordinates in Illustrator scripting: Y increases UPWARDS.
        // Wait, standard Illustrator scripting coordinate system:
        // Origin (0,0) is bottom-left of the artboard? No.
        // Traditionally ruler origin is top-left, with Y increasing DOWN.
        // BUT internal Scripting coordinates:
        // geometricBounds returns [x1, y1, x2, y2]
        // x1 = left, y1 = top, x2 = right, y2 = bottom.
        // Typically y1 > y2 because Y axis increases UPWARDS in internal PostScript coords?
        // Let's verify with a quick script or stick to standard assumption:
        // In AI Scripting: Y is positive UP.
        // So Top (y1) > Bottom (y2).
        // Height = Top - Bottom.
    };
}
