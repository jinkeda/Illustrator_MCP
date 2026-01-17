/**
 * selection.jsx - Selection and ordering utilites
 * Part of Illustrator MCP Standard Library
 * Dependencies: geometry.jsx (optional, falls back to geometricBounds)
 */

/**
 * Get selected items sorted by spatial position.
 * Useful for ensuring "Panel A, B, C" labels follow visual order regardless of creation stack.
 * 
 * @param {string} order - "row-major" (Left->Right, Top->Bottom) or "column-major" (Top->Bottom, Left->Right)
 * @param {boolean} reverse - Reverse the sort order
 * @returns {Array} Sorted array of PageItems
 */
function getOrderedSelection(order, reverse) {
    var sel = app.activeDocument.selection;
    if (!sel || sel.length === 0) return [];

    // Convert to native JS array
    var items = [];
    for (var i = 0; i < sel.length; i++) {
        items.push(sel[i]);
    }

    // Sort
    items.sort(function (a, b) {
        // Sort logic depends on coordinate system
        // Y is Positive UP in Illustrator scripting
        // So "Top" has higher Y value than "Bottom"

        var b1_top, b1_left, b2_top, b2_left;

        // Use geometry.jsx if available, else standard bounds
        if (typeof getVisibleBounds !== 'undefined') {
            var vb1 = getVisibleBounds(a);
            var vb2 = getVisibleBounds(b);
            b1_left = vb1[0]; b1_top = vb1[1];
            b2_left = vb2[0]; b2_top = vb2[1];
        } else {
            b1_left = a.geometricBounds[0]; b1_top = a.geometricBounds[1];
            b2_left = b.geometricBounds[0]; b2_top = b.geometricBounds[1];
        }

        // Row major: Sort by Y (Top->Bottom), then X (Left->Right)
        // Since Y is Up, Top->Bottom means Descending Y

        // Threshold for "same row/column" to avoid jitter
        var tolerance = 5; // points

        if (order === "column-major") {
            // Sort by X first (Left->Right), then Y (Top->Bottom)
            if (Math.abs(b1_left - b2_left) > tolerance) {
                return b1_left - b2_left; // Ascending X
            } else {
                return b2_top - b1_top; // Descending Y (Top > Bottom)
            }
        } else {
            // Default: row-major
            // Sort by Y first (Top->Bottom), then X (Left->Right)
            if (Math.abs(b1_top - b2_top) > tolerance) {
                return b2_top - b1_top; // Descending Y
            } else {
                return b1_left - b2_left; // Ascending X
            }
        }
    });

    if (reverse) {
        items.reverse();
    }

    return items;
}
