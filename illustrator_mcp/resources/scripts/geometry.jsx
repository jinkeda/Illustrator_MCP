/**
 * geometry.jsx - Geometry and bounds calculations
 * Part of Illustrator MCP Standard Library
 *
 * COORDINATE SYSTEM NOTE:
 * Illustrator uses Y-negative-down with (top, left, w, h) parameter order.
 * The XY helper functions provide an intuitive (x, y) mental model where:
 *   - x = distance from LEFT edge (positive = right)
 *   - y = distance from TOP edge (positive = down)
 * This matches typical screen/canvas coordinate conventions.
 */

// ============================================================================
// COORDINATE CONTEXT
// ============================================================================

/**
 * Get coordinate context for the active artboard.
 * Provides artboard-relative positioning values.
 *
 * @returns {Object} CTX object with:
 *   - left: artboard left edge (x origin)
 *   - top: artboard top edge (y origin, in Illustrator coords)
 *   - width: artboard width
 *   - height: artboard height
 *   - right: artboard right edge
 *   - bottom: artboard bottom edge
 *   - centerX: horizontal center
 *   - centerY: vertical center (in Illustrator coords)
 */
function getContext() {
    var doc = app.activeDocument;
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    // artboardRect = [left, top, right, bottom]
    // In Illustrator: top > bottom (Y increases upward)
    return {
        left: ab[0],
        top: ab[1],
        right: ab[2],
        bottom: ab[3],
        width: ab[2] - ab[0],
        height: ab[1] - ab[3],  // top - bottom (positive value)
        centerX: ab[0] + (ab[2] - ab[0]) / 2,
        centerY: ab[1] - (ab[1] - ab[3]) / 2  // halfway down from top
    };
}

// ============================================================================
// INTUITIVE COORDINATE HELPERS (XY Functions)
// ============================================================================

/**
 * Convert intuitive (x, y) coordinates to Illustrator position.
 *
 * @param {number} x - Distance from artboard LEFT edge
 * @param {number} y - Distance from artboard TOP edge (positive = down)
 * @returns {Object} {left, top} in Illustrator coordinates
 */
function pointXY(x, y) {
    var CTX = getContext();
    return {
        left: CTX.left + x,
        top: CTX.top - y  // Invert Y: positive y moves DOWN visually
    };
}

/**
 * Create a rectangle using intuitive (x, y, w, h) coordinates.
 * Handles Illustrator's (top, left, w, h) and Y-inversion internally.
 *
 * @param {number} x - Distance from artboard LEFT edge to rectangle left
 * @param {number} y - Distance from artboard TOP edge to rectangle top (positive = down)
 * @param {number} w - Width
 * @param {number} h - Height
 * @param {Object} [options] - Optional settings
 * @param {number} [options.cornerRadius] - Corner radius for rounded rectangle
 * @returns {PathItem} The created rectangle
 *
 * @example
 * // Create a 200x100 rectangle, 50pt from left, 80pt from top
 * var rect = rectXY(50, 80, 200, 100);
 *
 * // Create a rounded rectangle with 20pt corners
 * var rounded = rectXY(50, 80, 200, 100, {cornerRadius: 20});
 */
function rectXY(x, y, w, h, options) {
    var doc = app.activeDocument;
    var pos = pointXY(x, y);

    if (options && options.cornerRadius) {
        var r = options.cornerRadius;
        return doc.pathItems.roundedRectangle(pos.top, pos.left, w, h, r, r);
    }
    return doc.pathItems.rectangle(pos.top, pos.left, w, h);
}

/**
 * Create an ellipse using intuitive (x, y, w, h) coordinates.
 *
 * @param {number} x - Distance from artboard LEFT edge to ellipse left
 * @param {number} y - Distance from artboard TOP edge to ellipse top (positive = down)
 * @param {number} w - Width
 * @param {number} h - Height
 * @returns {PathItem} The created ellipse
 *
 * @example
 * // Create a 100x100 circle, 50pt from left, 50pt from top
 * var circle = ellipseXY(50, 50, 100, 100);
 */
function ellipseXY(x, y, w, h) {
    var doc = app.activeDocument;
    var pos = pointXY(x, y);
    return doc.pathItems.ellipse(pos.top, pos.left, w, h);
}

/**
 * Create a line using intuitive (x1, y1, x2, y2) coordinates.
 *
 * @param {number} x1 - Start X (distance from artboard LEFT)
 * @param {number} y1 - Start Y (distance from artboard TOP, positive = down)
 * @param {number} x2 - End X
 * @param {number} y2 - End Y
 * @returns {PathItem} The created line
 *
 * @example
 * // Draw a diagonal line from (10,10) to (100,100)
 * var line = lineXY(10, 10, 100, 100);
 */
function lineXY(x1, y1, x2, y2) {
    var doc = app.activeDocument;
    var p1 = pointXY(x1, y1);
    var p2 = pointXY(x2, y2);

    var line = doc.pathItems.add();
    line.setEntirePath([[p1.left, p1.top], [p2.left, p2.top]]);
    line.filled = false;
    return line;
}

/**
 * Create a polygon/polyline using intuitive coordinates.
 *
 * @param {Array} points - Array of [x, y] coordinate pairs
 * @param {boolean} [closed=true] - Whether to close the path
 * @returns {PathItem} The created path
 *
 * @example
 * // Create a triangle
 * var tri = polygonXY([[50, 10], [10, 90], [90, 90]], true);
 */
function polygonXY(points, closed) {
    if (closed === undefined) closed = true;

    var doc = app.activeDocument;
    var path = doc.pathItems.add();

    var ilPoints = [];
    for (var i = 0; i < points.length; i++) {
        var pos = pointXY(points[i][0], points[i][1]);
        ilPoints.push([pos.left, pos.top]);
    }

    path.setEntirePath(ilPoints);
    path.closed = closed;
    return path;
}

/**
 * Create an RGB color object.
 *
 * @param {number} r - Red (0-255)
 * @param {number} g - Green (0-255)
 * @param {number} b - Blue (0-255)
 * @returns {RGBColor} The color object
 *
 * @example
 * var red = makeRGBColor(255, 0, 0);
 * rect.fillColor = red;
 */
function makeRGBColor(r, g, b) {
    var c = new RGBColor();
    c.red = r;
    c.green = g;
    c.blue = b;
    return c;
}

// ============================================================================
// UNIT CONVERSIONS
// ============================================================================

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
