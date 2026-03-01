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

// ============================================================================
// BÉZIER PATH RENDERER (shared with ops_element.jsx)
// ============================================================================

/**
 * Apply point data to a PathItem with optional Bézier control handles.
 *
 * Accepts mixed point formats:
 *   {anchor: [x,y]}                             → anchor-only (corner)
 *   {anchor: [x,y], left: [lx,ly], right: [rx,ry]} → full Bézier
 *   [x, y]                                      → legacy shorthand
 *   [[ax,ay], [inX,inY], [outX,outY]]           → legacy handle tuple
 *
 * @param {PathItem} item - PathItem already added to a layer
 * @param {Array} points - Array of point specs (object or legacy format)
 * @param {number} abLeft - Artboard left X for coordinate transform
 * @param {number} abTop - Artboard top Y for coordinate transform
 * @returns {boolean} true if handles were used
 */
function _createPath(item, points, abLeft, abTop) {
    // Normalise points to internal format: {anchor, left?, right?}
    var normalised = [];
    for (var ni = 0; ni < points.length; ni++) {
        var p = points[ni];
        if (p && typeof p === "object" && !(p instanceof Array) && p.anchor) {
            // Object format: {anchor: [x,y], left?: [lx,ly], right?: [rx,ry]}
            normalised.push(p);
        } else if (p instanceof Array && p.length === 3 && p[0] instanceof Array) {
            // Legacy handle tuple: [[ax,ay], [inX,inY], [outX,outY]]
            normalised.push({
                anchor: p[0],
                left: (p[1] && p[1] instanceof Array) ? p[1] : null,
                right: (p[2] && p[2] instanceof Array) ? p[2] : null
            });
        } else if (p instanceof Array && p.length >= 2) {
            // Legacy shorthand: [x, y]
            normalised.push({ anchor: [p[0], p[1]] });
        } else {
            throw new Error("_createPath: invalid point at index " + ni);
        }
    }

    // Detect if any point has handles
    var hasHandles = false;
    for (var ci = 0; ci < normalised.length; ci++) {
        if (normalised[ci].left || normalised[ci].right) {
            hasHandles = true;
            break;
        }
    }

    if (!hasHandles) {
        // Fast path: all simple anchors → use setEntirePath
        var aiPts = [];
        for (var si = 0; si < normalised.length; si++) {
            var a = normalised[si].anchor;
            aiPts.push([abLeft + a[0], abTop - a[1]]);
        }
        item.setEntirePath(aiPts);
        return false;
    }

    // Bézier path: set dummy anchors first, then apply handles
    var dummyPts = [];
    for (var di = 0; di < normalised.length; di++) {
        var da = normalised[di].anchor;
        dummyPts.push([abLeft + da[0], abTop - da[1]]);
    }
    item.setEntirePath(dummyPts);

    for (var hi = 0; hi < normalised.length; hi++) {
        var src = normalised[hi];
        var pp = item.pathPoints[hi];
        var anchor = [abLeft + src.anchor[0], abTop - src.anchor[1]];
        pp.anchor = anchor;

        if (src.left && src.left instanceof Array) {
            pp.leftDirection = [abLeft + src.left[0], abTop - src.left[1]];
        } else {
            pp.leftDirection = anchor; // coincident = sharp corner
        }

        if (src.right && src.right instanceof Array) {
            pp.rightDirection = [abLeft + src.right[0], abTop - src.right[1]];
        } else {
            pp.rightDirection = anchor; // coincident = sharp corner
        }
    }
    return true;
}

// ============================================================================
// drawPathPoints — Golden Path entry point for generative path drawing
// ============================================================================

/**
 * Draw a path (or compound path) from explicit point data.
 *
 * This is the single entry point for LLM-generated paths via execute_script.
 * Handles UUID stamping, heap registration, layer resolution, and appearance.
 *
 * SPEC FORMAT:
 *   spec.points:     [{anchor, left?, right?}, ...]     — single path
 *     OR
 *   spec.subpaths:   [{ points: [...], closed }, ...]   — multi-path
 *   spec.compound:   true → wrap in CompoundPathItem
 *
 *   spec.closed:     boolean (for single-path mode, default true)
 *   spec.appearance: { fill?: {r,g,b}, stroke?: {r,g,b,width?}, opacity? }
 *   spec.target:     { layer?: string }
 *   spec.meta:       { tag?, source? }
 *
 * @param {Object} spec - Path specification
 * @returns {Object} { ok: true, uuid: string, typename: string, bounds: Array }
 */
function drawPathPoints(spec) {
    // [H4] Dependency guards — check symbols from mcp_id.jsx, heap.jsx, targets.jsx
    if (typeof setMcpId !== "function") {
        throw new Error("drawPathPoints requires mcp_id.jsx (include 'mcp_id' in execute_script includes, or use includes: ['geometry'])");
    }
    if (typeof heapRegister !== "function") {
        throw new Error("drawPathPoints requires heap.jsx (include 'heap' in execute_script includes, or use includes: ['geometry'])");
    }
    if (typeof findLayer !== "function") {
        throw new Error("drawPathPoints requires targets.jsx (include 'targets' in execute_script includes, or use includes: ['geometry'])");
    }

    if (!spec) throw new Error("drawPathPoints: spec is required");

    // [H1] points vs subpaths mutual exclusivity
    if (spec.points && spec.subpaths) {
        throw new Error("drawPathPoints: Provide 'points' (single path) or 'subpaths' (multi), not both");
    }
    if (!spec.points && !spec.subpaths) {
        throw new Error("drawPathPoints: Provide 'points' or 'subpaths'");
    }

    var doc = app.activeDocument;
    var CTX = getContext();
    var abTop = CTX.top;
    var abLeft = CTX.left;

    // Resolve target layer
    var targetLayer;
    if (spec.target && spec.target.layer) {
        targetLayer = findLayer(doc, spec.target.layer);
        if (!targetLayer) {
            throw new Error("drawPathPoints: Layer not found: " + spec.target.layer);
        }
    } else {
        targetLayer = doc.activeLayer;
    }

    // Generate UUID — or use user-supplied spec.id
    var uuid;
    if (spec.id) {
        // User-supplied ID: check for collision before using
        if (typeof heapResolveMany === "function") {
            var existing = heapResolveMany(doc, [spec.id]);
            if (existing.length > 0) {
                throw new Error(
                    "DPP_ID_COLLISION: item with @mcp:id=" + spec.id +
                    " already exists (typename=" + existing[0].typename +
                    "). Use a unique id or remove the existing item first."
                );
            }
        }
        uuid = spec.id;
    } else {
        uuid = _geometryUUID();
    }

    // Determine path mode
    var isSingle = !!spec.points;
    var subpaths;
    if (isSingle) {
        subpaths = [{ points: spec.points, closed: spec.closed !== false }];
    } else {
        subpaths = spec.subpaths;
    }

    // [H2] CompoundPath requires all subpaths closed
    if (spec.compound) {
        for (var vi = 0; vi < subpaths.length; vi++) {
            if (subpaths[vi].closed === false) {
                throw new Error(
                    "drawPathPoints: compound requires all subpaths closed, " +
                    "but subpaths[" + vi + "].closed is false"
                );
            }
        }
    }

    // Validate point counts
    for (var pi = 0; pi < subpaths.length; pi++) {
        var pts = subpaths[pi].points;
        if (!pts || pts.length < 2) {
            throw new Error("drawPathPoints: subpaths[" + pi + "] requires >= 2 points, got " + (pts ? pts.length : 0));
        }
    }

    // Create path items — [H3] failure-atomicity
    var createdItems = [];
    try {
        for (var si = 0; si < subpaths.length; si++) {
            var sub = subpaths[si];
            var item = targetLayer.pathItems.add();
            createdItems.push(item);
            _createPath(item, sub.points, abLeft, abTop);
            item.closed = sub.closed !== false; // default true
        }

        // Wrap in CompoundPathItem if requested
        var resultItem;
        if (spec.compound && createdItems.length > 0) {
            var cpItem = targetLayer.compoundPathItems.add();
            for (var ci = 0; ci < createdItems.length; ci++) {
                createdItems[ci].move(cpItem, ElementPlacement.PLACEATEND);
            }
            resultItem = cpItem;
        } else if (createdItems.length === 1) {
            resultItem = createdItems[0];
        } else {
            // Multiple subpaths, no compound — group them
            var grp = targetLayer.groupItems.add();
            for (var gi = 0; gi < createdItems.length; gi++) {
                createdItems[gi].move(grp, ElementPlacement.PLACEATEND);
            }
            resultItem = grp;
        }

        // Apply appearance
        if (spec.appearance) {
            var app_ = spec.appearance;
            // Apply to all pathItems (works for compound and single)
            var pathItems = [];
            if (resultItem.typename === "CompoundPathItem") {
                for (var ai = 0; ai < resultItem.pathItems.length; ai++) {
                    pathItems.push(resultItem.pathItems[ai]);
                }
            } else if (resultItem.typename === "PathItem") {
                pathItems.push(resultItem);
            } else if (resultItem.typename === "GroupItem") {
                for (var ai2 = 0; ai2 < resultItem.pathItems.length; ai2++) {
                    pathItems.push(resultItem.pathItems[ai2]);
                }
            }
            for (var api = 0; api < pathItems.length; api++) {
                _applyPathAppearance(pathItems[api], app_);
            }
            // Opacity on the top-level item
            if (app_.opacity !== undefined) {
                resultItem.opacity = app_.opacity;
            }
        }

        // Stamp UUID and register — [H3] last steps before success
        setMcpId(resultItem, uuid);
        heapRegister(uuid, resultItem);

        // Apply meta tag
        if (spec.meta && spec.meta.tag) {
            var note = resultItem.note || "";
            if (note) note += " ";
            resultItem.note = note + "@mcp:tag=" + spec.meta.tag;
        }

        return {
            ok: true,
            uuid: uuid,
            typename: resultItem.typename,
            bounds: [resultItem.left, resultItem.top, resultItem.width, resultItem.height],
            subpathCount: subpaths.length,
            compound: !!spec.compound
        };

    } catch (e) {
        // [H3] Failure-atomicity: clean up any items we created
        for (var ri = 0; ri < createdItems.length; ri++) {
            try { createdItems[ri].remove(); } catch (ignored) { }
        }
        throw e; // Re-throw after cleanup
    }
}

/**
 * Apply appearance (fill, stroke) to a single PathItem.
 * @private
 */
function _applyPathAppearance(item, app_) {
    if (app_.fill) {
        if (app_.fill === false || app_.fill === null) {
            item.filled = false;
        } else {
            var fc = new RGBColor();
            fc.red = app_.fill.r || 0;
            fc.green = app_.fill.g || 0;
            fc.blue = app_.fill.b || 0;
            item.fillColor = fc;
        }
    }
    if (app_.stroke) {
        if (app_.stroke === false || app_.stroke === null) {
            item.stroked = false;
        } else {
            var sc = new RGBColor();
            sc.red = app_.stroke.r || 0;
            sc.green = app_.stroke.g || 0;
            sc.blue = app_.stroke.b || 0;
            item.strokeColor = sc;
            item.stroked = true;
            if (app_.stroke.width !== undefined) {
                item.strokeWidth = app_.stroke.width;
            }
        }
    }
    if (app_.noFill) item.filled = false;
    if (app_.noStroke) item.stroked = false;
}

/**
 * Generate a UUID without depending on ops_core.
 * Uses same format as generateUUID() for consistency.
 * @private
 * @returns {string} UUID string
 */
function _geometryUUID() {
    // Simple but unique: timestamp_hex + random_hex
    var t = new Date().getTime();
    var hex = "";
    var chars = "0123456789abcdef";
    // 8 hex digits from timestamp
    for (var i = 28; i >= 0; i -= 4) {
        hex += chars.charAt((t >>> i) & 0xF);
    }
    hex += "-";
    // 4 random hex segments
    for (var s = 0; s < 4; s++) {
        for (var r = 0; r < 4; r++) {
            hex += chars.charAt(Math.floor(Math.random() * 16));
        }
        if (s < 3) hex += "-";
    }
    return "dpp-" + hex;
}
