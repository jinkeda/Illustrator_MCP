/**
 * ops_element.jsx - Element CRUD Operations
 * Part of Illustrator MCP SOC Framework
 * 
 * Provides handlers for:
 * - element_create: Create shapes (rect, ellipse, line, path, polyline)
 * - element_create_multi: Create multiple paths from Geometry IR multi
 * - element_modify: Modify existing elements
 * - element_delete: Delete elements
 * 
 * All create ops return the assigned ID for stable referencing.
 * Path/polyline ops accept Geometry IR ({v,ir,kind,points,closed,meta}) or raw point arrays.
 * 
 * @requires ops_core (for registerOpHandler, generateUUID)
 * @requires geo_ir (for isIR, irValidate, irMapPoints)
 * @version 1.1.0
 */

// ==================== Dependency Guard ====================

if (typeof registerOpHandler !== "function") {
    throw new Error("ops_element.jsx requires ops_core.jsx (registerOpHandler=" + typeof registerOpHandler + ")");
}
if (typeof findLayer !== "function") {
    throw new Error("ops_element.jsx requires targets.jsx (findLayer=" + typeof findLayer + ")");
}
if (typeof isIR !== "function") {
    throw new Error("ops_element.jsx requires geo_ir.jsx (isIR=" + typeof isIR + ")");
}
if (typeof _createPath !== "function") {
    throw new Error("ops_element.jsx requires geometry.jsx (_createPath=" + typeof _createPath + ")");
}

// ==================== Artboard Coordinate Helper ====================

/**
 * Get the top Y coordinate of the active artboard in Illustrator's
 * coordinate system.  User-facing params use screen coords where
 * (0,0) is the artboard top-left and Y increases downward.
 * Illustrator's native Y axis increases upward, and a typical
 * artboard rect is [left, top, right, bottom] = [0, 400, 600, 0].
 *
 * Conversion:  aiY = artboardTop - userY
 */
function _artboardTop(doc) {
    try {
        var idx = doc.artboards.getActiveArtboardIndex();
        var rect = doc.artboards[idx].artboardRect;  // [L, T, R, B]
        return rect[1];  // top Y in Illustrator coords
    } catch (e) {
        return 0;  // fallback: pasteboard origin
    }
}

function _artboardLeft(doc) {
    try {
        var idx = doc.artboards.getActiveArtboardIndex();
        var rect = doc.artboards[idx].artboardRect;
        return rect[0];  // left X in Illustrator coords
    } catch (e) {
        return 0;
    }
}

// ==================== Deterministic Layer Resolution ====================

/**
 * Resolve the target layer with deterministic fallback.
 * Priority: params.layer > ctx.defaultLayer > doc.activeLayer (warn).
 *
 * @param {Document} doc
 * @param {Object} params - Must have optional .layer string
 * @param {Object} ctx - Execution context (may have .defaultLayer, .warn)
 * @returns {Object} {ok: true, layer: Layer} or {ok: false, error: ...}
 */
function _resolveTargetLayer(doc, params, ctx) {
    if (params.layer) {
        var found = findLayer(doc, params.layer);
        if (!found) {
            return makeError(ErrorCodes.V_INVALID_PARAM_TYPE, "Layer not found: " + params.layer, "apply");
        }
        return { ok: true, layer: found };
    }
    if (ctx && ctx.defaultLayer) {
        var defLayer = findLayer(doc, ctx.defaultLayer);
        if (defLayer) return { ok: true, layer: defLayer };
    }
    // Final fallback — nondeterministic, warn caller
    var fallback = doc.activeLayer;
    if (ctx && ctx.warn) ctx.warn("No layer specified; using activeLayer '" + fallback.name + "'");
    return { ok: true, layer: fallback };
}

// ==================== Bézier Path Helper ====================

/**
 * Create a path with optional Bézier control point handles.
 *
 * Accepts mixed point formats:
 *   [x, y]                              → anchor-only (straight corner)
 *   [[ax,ay], [inX,inY], [outX,outY]]   → anchor + in-handle + out-handle
 *   [[ax,ay], null, [outX,outY]]         → anchor + smooth start (no in-handle)
 *   [[ax,ay], [inX,inY], null]           → anchor + smooth end (no out-handle)
 *
 * If ALL points are simple [x,y], uses fast setEntirePath().
 * If ANY point has handles, uses pathPoints API for full Bézier control.
 *
 * @param {PathItem} item - PathItem to set points on (already added to layer)
 * @param {Array} points - Mixed array of simple or control-point structures
 * @param {number} abLeft - Artboard left X for coordinate transform
 * @param {number} abTop - Artboard top Y for coordinate transform
 * @returns {boolean} true if handles were used (Bézier path), false if simple
 */
function _createPathWithHandles(item, points, abLeft, abTop) {
    // Detect if any point has handle syntax: [[ax,ay], inH, outH]
    var hasHandles = false;
    for (var ci = 0; ci < points.length; ci++) {
        var pt = points[ci];
        if (pt.length === 3 && pt[0] instanceof Array) {
            hasHandles = true;
            break;
        }
    }

    if (!hasHandles) {
        // Fast path: all simple anchors → use setEntirePath
        var aiPts = [];
        for (var si = 0; si < points.length; si++) {
            aiPts.push([abLeft + points[si][0], abTop - points[si][1]]);
        }
        item.setEntirePath(aiPts);
        return false;
    }

    // Bézier path: use pathPoints API for individual anchor/handle control
    // First set a dummy path so pathPoints can be populated
    var dummyPts = [];
    for (var di = 0; di < points.length; di++) {
        var dp = points[di];
        if (dp.length === 3 && dp[0] instanceof Array) {
            dummyPts.push([abLeft + dp[0][0], abTop - dp[0][1]]);
        } else {
            dummyPts.push([abLeft + dp[0], abTop - dp[1]]);
        }
    }
    item.setEntirePath(dummyPts);

    // Now set handles on each pathPoint
    for (var hi = 0; hi < points.length; hi++) {
        var src = points[hi];
        var pp = item.pathPoints[hi];

        if (src.length === 3 && src[0] instanceof Array) {
            // Control point tuple: [anchor, inHandle, outHandle]
            var anchor = [abLeft + src[0][0], abTop - src[0][1]];
            pp.anchor = anchor;

            // In-handle (leftDirection): where previous segment arrives
            if (src[1] && src[1] instanceof Array) {
                pp.leftDirection = [abLeft + src[1][0], abTop - src[1][1]];
            } else {
                pp.leftDirection = anchor; // coincident = sharp corner
            }

            // Out-handle (rightDirection): where next segment departs
            if (src[2] && src[2] instanceof Array) {
                pp.rightDirection = [abLeft + src[2][0], abTop - src[2][1]];
            } else {
                pp.rightDirection = anchor; // coincident = sharp corner
            }
        } else {
            // Simple anchor: handles coincident (sharp corner)
            var simpleAnchor = [abLeft + src[0], abTop - src[1]];
            pp.anchor = simpleAnchor;
            pp.leftDirection = simpleAnchor;
            pp.rightDirection = simpleAnchor;
        }
    }
    return true;
}

// ==================== Element Create ====================

registerOpHandler("element_create", function (params, targets, ctx) {
    var doc = ctx.doc;
    var type = params.type || "rect";
    var id = params.id || generateUUID();

    // Geometry params
    var width = params.width || params.w || 100;
    var height = params.height || params.h || 100;

    // Support center-based positioning (cx/cy → x/y)
    var x, y;
    if (params.cx !== undefined || params.cy !== undefined) {
        x = (params.cx !== undefined ? params.cx : 0) - width / 2;
        y = (params.cy !== undefined ? params.cy : 0) - height / 2;
    } else {
        x = params.x || 0;
        y = params.y || 0;
    }
    var name = params.name || null;

    // Resolve target layer (deterministic: params.layer > ctx.defaultLayer > activeLayer)
    var layerResult = _resolveTargetLayer(doc, params, ctx);
    if (!layerResult.ok) return layerResult;
    var targetLayer = layerResult.layer;

    var item = null;

    // Convert to Illustrator coordinates:
    // User coords: (0,0) = artboard top-left, Y increases downward
    // Illustrator:  Y increases upward, artboard top is a positive number
    var abTop = _artboardTop(doc);
    var abLeft = _artboardLeft(doc);
    var aiTop = abTop - y;          // e.g. y=50 on 400pt artboard → aiY=350
    var aiLeft = abLeft + x;

    switch (type) {
        case "rect":
            // rectangle(top, left, width, height)
            item = targetLayer.pathItems.rectangle(aiTop, aiLeft, width, height);
            break;

        case "ellipse":
            // ellipse(top, left, width, height)
            item = targetLayer.pathItems.ellipse(aiTop, aiLeft, width, height);
            break;

        case "line":
            // Accept x1/y1 as aliases for start point (x/y)
            var lx1 = params.x1 !== undefined ? params.x1 : x;
            var ly1 = params.y1 !== undefined ? params.y1 : y;
            var lx2 = params.x2 !== undefined ? params.x2 : lx1 + 100;
            var ly2 = params.y2 !== undefined ? params.y2 : ly1;
            item = targetLayer.pathItems.add();
            item.setEntirePath([[abLeft + lx1, abTop - ly1], [abLeft + lx2, abTop - ly2]]);
            item.closed = false;
            item.filled = false;
            break;

        case "roundedRect":
            var cornerRadius = params.cornerRadius || 10;
            item = targetLayer.pathItems.roundedRectangle(
                aiTop, aiLeft, width, height, cornerRadius, cornerRadius
            );
            break;

        case "polygon":
            var sides = params.sides || 6;
            var radius = params.radius || 50;
            item = targetLayer.pathItems.polygon(abLeft + x, abTop - y, radius, sides);
            break;

        case "star":
            var points = params.numPoints || params.points || 5;
            var outerRadius = params.outerRadius || 50;
            var innerRadius = params.innerRadius || 25;
            item = targetLayer.pathItems.star(abLeft + x, abTop - y, outerRadius, innerRadius, points);
            break;

        case "text":
            var contents = params.contents || params.text || "";
            var fontSize = params.fontSize || 12;
            if (params.width != null && params.height != null) {
                // Area text: create container rect, then use areaText()
                var container = targetLayer.pathItems.rectangle(aiTop, aiLeft, width, height);
                container.filled = false;
                container.stroked = false;
                item = targetLayer.textFrames.areaText(container);
            } else {
                // Point text
                item = targetLayer.textFrames.add();
                item.position = [aiLeft, aiTop];
            }
            item.contents = contents;
            item.textRange.characterAttributes.size = fontSize;
            if (params.fontName) {
                try {
                    item.textRange.characterAttributes.textFont =
                        app.textFonts.getByName(params.fontName);
                } catch (e) { /* font not found, keep default */ }
            }
            break;

        case "polyline":
            // Alias for open path — falls through to "path" with closed=false default
            if (params.closed === undefined) params.closed = false;
        // fall through
        case "path":
            // [HB] Soft warning: prefer geometry.drawPathPoints for new paths
            if (ctx && ctx.warn) ctx.warn("Prefer geometry.drawPathPoints for new paths");
            // Resolve points: geometry IR > points (raw or legacy IR) > error
            var pathPoints;
            var pathWarnings = [];
            var geoInput = params.geometry || params.points;
            if (!geoInput) {
                return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "Path requires 'geometry' (IR) or 'points' array", "apply");
            }
            if (isIR(geoInput)) {
                // Geometry IR object — validate before consuming
                if (geoInput.ir === "multi") {
                    return makeError(
                        ErrorCodes.V_INVALID_PARAM_TYPE,
                        "multi IR not supported in element_create; use element_create_multi",
                        "apply"
                    );
                }
                var irVal = irValidate(geoInput);
                if (!irVal.ok) {
                    return makeError(ErrorCodes.V_INVALID_PARAM_TYPE, "IR validation failed: " + irVal.errors.join("; "), "apply");
                }
                if (geoInput.ir !== "path") {
                    return makeError(ErrorCodes.V_INVALID_PARAM_TYPE, "Expected ir:'path', got ir:'" + geoInput.ir + "'", "apply");
                }
                pathPoints = geoInput.points || [];
                if (params.closed === undefined) params.closed = geoInput.closed;
                // Warn if IR was passed via 'points' instead of 'geometry'
                if (params.points && isIR(params.points) && !params.geometry) {
                    pathWarnings.push("IR in 'points' is deprecated; use 'geometry' param");
                }
            } else {
                // Raw point array: [[x,y], ...]
                pathPoints = geoInput;

                // Auto-smooth: Catmull-Rom → Bézier IR
                if (params.smooth && pathPoints.length >= 3) {
                    var isClosed = params.closed !== false;
                    var tension = (params.tension !== undefined && params.tension !== null)
                        ? params.tension : 0.5;
                    geoInput = smoothCurve(pathPoints, tension, isClosed);
                    pathPoints = geoInput.points || [];
                    if (params.closed === undefined) params.closed = geoInput.closed;
                    pathWarnings.push("smooth: Catmull-Rom applied (" + pathPoints.length + " pts, tension=" + tension + ")");
                } else if (params.smooth) {
                    pathWarnings.push("smooth: ignored (< 3 points, need >= 3 for smoothing)");
                }
            }

            if (pathPoints.length < 2) {
                return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "Path requires >= 2 points", "apply");
            }
            // Guard: Illustrator crashes with 'Illegal Argument' above ~8000 points.
            // Monotonic decimation: enforce strictly increasing indices to avoid duplicates.
            var MAX_PATH_POINTS = 8000;
            if (pathPoints.length > MAX_PATH_POINTS) {
                var origLen = pathPoints.length;
                var decimated = [];
                var lastIdx = -1;
                for (var di = 0; di < MAX_PATH_POINTS; di++) {
                    var idx = Math.round(di * (origLen - 1) / (MAX_PATH_POINTS - 1));
                    if (idx <= lastIdx) idx = lastIdx + 1;
                    if (idx >= origLen) break;
                    decimated.push(pathPoints[idx]);
                    lastIdx = idx;
                }
                pathPoints = decimated;
                pathWarnings.push("Path decimated from " + origLen + " to " + pathPoints.length + " points");
            }
            // Y-flip via irMapPoints if IR, otherwise use Bézier-aware helper
            item = targetLayer.pathItems.add();
            if (isIR(geoInput)) {
                var abT = abTop, abL = abLeft;
                var flipped = irMapPoints(geoInput, function (pt) { return [abL + pt[0], abT - pt[1]]; });

                if (flipped.kind === "bezier" && flipped.handles) {
                    // Bézier IR: use pathPoints API with handles
                    // irMapPoints already transformed both anchors and handles
                    var bPts = flipped.points;
                    var bH = flipped.handles;

                    // Set anchors first via setEntirePath (creates pathPoints)
                    item.setEntirePath(bPts);

                    // Apply handles and pointType — single transform (already flipped)
                    // Accept both IR format (in/out/type) and canonical (left/right/pointType)
                    for (var bi = 0; bi < bPts.length; bi++) {
                        var pp = item.pathPoints[bi];
                        var hEntry = bH[bi];

                        // In-handle (leftDirection): IR key "in", canonical key "left"
                        var hIn = (hEntry.left != null) ? hEntry.left
                            : (hEntry["in"] != null) ? hEntry["in"] : null;
                        if (hIn != null) {
                            pp.leftDirection = hIn;
                        } else {
                            pp.leftDirection = bPts[bi]; // coincident = sharp
                        }

                        // Out-handle (rightDirection): IR key "out", canonical key "right"
                        var hOut = (hEntry.right != null) ? hEntry.right
                            : (hEntry.out != null) ? hEntry.out : null;
                        if (hOut != null) {
                            pp.rightDirection = hOut;
                        } else {
                            pp.rightDirection = bPts[bi]; // coincident = sharp
                        }

                        // PointType: canonical "pointType", IR "type"
                        var pType = hEntry.pointType || hEntry.type || "smooth";
                        if (pType === "corner") {
                            pp.pointType = PointType.CORNER;
                        } else {
                            pp.pointType = PointType.SMOOTH;
                        }
                    }
                } else {
                    // Polyline IR: fast path — corner-only anchors
                    item.setEntirePath(flipped.points);
                }
            } else {
                _createPathWithHandles(item, pathPoints, abLeft, abTop);
            }
            item.closed = params.closed !== false; // Default to closed
            // Emit collected warnings
            if (ctx && ctx.warn) {
                for (var wi = 0; wi < pathWarnings.length; wi++) ctx.warn(pathWarnings[wi]);
            }
            break;

        default:
            return makeError(
                ErrorCodes.V_INVALID_PARAM_TYPE,
                "Unknown element type: " + type,
                "apply"
            );
    }

    // Assign ID via note
    item.note = "@mcp:id=" + id;

    // Set name if provided
    if (name) {
        item.name = name;
    }

    // Apply fill if specified
    if (params.fill) {
        var fillColor = new RGBColor();
        fillColor.red = params.fill.r || 0;
        fillColor.green = params.fill.g || 0;
        fillColor.blue = params.fill.b || 0;
        item.fillColor = fillColor;
    }

    // Apply stroke if specified
    if (params.stroke) {
        var strokeColor = new RGBColor();
        strokeColor.red = params.stroke.r || 0;
        strokeColor.green = params.stroke.g || 0;
        strokeColor.blue = params.stroke.b || 0;
        item.strokeColor = strokeColor;
        item.stroked = true;
        if (params.stroke.width) {
            item.strokeWidth = params.stroke.width;
        }
    }

    // No fill option (params.noFill:true OR fill:false/null)
    if (params.noFill || params.fill === null || params.fill === false) {
        item.filled = false;
    }

    // No stroke option (params.noStroke:true OR stroke:false/null)
    if (params.noStroke || params.stroke === null || params.stroke === false) {
        item.stroked = false;
    }

    // Top-level strokeWidth shorthand
    if (params.strokeWidth !== undefined) {
        item.strokeWidth = params.strokeWidth;
        if (!params.stroke && !params.noStroke && params.stroke !== false) {
            item.stroked = true;
        }
    }

    // Opacity
    if (params.opacity !== undefined) {
        item.opacity = params.opacity;
    }

    return {
        ok: true,
        id: id,
        data: {
            typename: item.typename,
            bounds: [item.left, item.top, item.width, item.height]
        }
    };
});

// ==================== Element Create Multi ====================

/**
 * Create multiple paths from a Geometry IR multi object.
 * Each sub-path gets its own PathItem and MCP ID (assigned inline).
 *
 * Styling modes (evaluated in priority order):
 *   1. styles[i]       — explicit per-path {fill?, stroke?, opacity?}
 *   2. styleScalars[i] — compact: t∈[0,1] + palette with lerp ranges
 *   3. fill/stroke     — shared default style for all paths
 *
 * Performance: color cache avoids duplicate RGBColor allocations.
 * Recommended limit: 2000 paths per call; chunk above that.
 *
 * @param {Object} params.geometry - IR multi object
 * @param {string} [params.layer] - Target layer name
 * @param {string} [params.name] - Base name for items (suffixed _i)
 * @param {Object} [params.fill] - Shared fill {r,g,b} or false/null
 * @param {Object} [params.stroke] - Shared stroke {r,g,b,width?} or false/null
 * @param {Array<Object>} [params.styles] - Per-path overrides, parallel to paths[]
 * @param {Array<number>} [params.styleScalars] - t∈[0,1] per path for palette lerp
 * @param {Object} [params.palette] - Lerp ranges for scalar mode:
 *   { stroke: {r:[lo,hi], g:[lo,hi], b:[lo,hi]},
 *     opacity: [lo,hi], width: [lo,hi] }
 */
registerOpHandler("element_create_multi", function (params, targets, ctx) {
    var doc = ctx.doc;
    var abTop = _artboardTop(doc);
    var abLeft = _artboardLeft(doc);
    var geo = params.geometry;

    if (!geo || !isIR(geo)) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "element_create_multi requires 'geometry' IR object", "apply");
    }
    if (geo.ir !== "multi") {
        return makeError(ErrorCodes.V_INVALID_PARAM_TYPE, "Expected ir:'multi', got ir:'" + geo.ir + "'", "apply");
    }

    var validation = irValidate(geo);
    if (!validation.ok) {
        return makeError(ErrorCodes.V_INVALID_PARAM_TYPE, "IR validation failed: " + validation.errors.join("; "), "apply");
    }

    var fullPaths = geo.paths || [];
    var totalPaths = fullPaths.length;

    // Chunked creation: process a slice of paths
    var offset = params.offset || 0;
    var limit = params.limit || totalPaths;
    var end = Math.min(offset + limit, totalPaths);
    var pathsArr = (offset > 0 || end < totalPaths) ? fullPaths.slice(offset, end) : fullPaths;

    // Resolve layer ONCE (Hole B optimization + deterministic fallback)
    var layerResult = _resolveTargetLayer(doc, params, ctx);
    if (!layerResult.ok) return layerResult;
    var targetLayer = layerResult.layer;

    // Styling modes — slice in sync with pathsArr when chunked
    var styles = params.styles || null;       // Mode 1: explicit per-path
    var scalars = params.styleScalars || null; // Mode 2: compact lerp
    var palette = params.palette || null;
    if (offset > 0 || end < totalPaths) {
        if (styles) styles = styles.slice(offset, end);
        if (scalars) scalars = scalars.slice(offset, end);
    }

    // Color cache: avoids creating duplicate RGBColor objects (Hole B)
    var colorCache = {};
    function getCachedColor(r, g, b) {
        var key = r + "|" + g + "|" + b;
        if (!colorCache[key]) {
            var c = new RGBColor();
            c.red = r; c.green = g; c.blue = b;
            colorCache[key] = c;
        }
        return colorCache[key];
    }

    // Precompute shared default colors (avoid per-item allocation)
    var defaultFillColor = null;
    var defaultFillOff = false;
    if (params.fill && params.fill !== false && params.fill !== null) {
        defaultFillColor = getCachedColor(params.fill.r || 0, params.fill.g || 0, params.fill.b || 0);
    } else if (params.fill === false || params.fill === null) {
        defaultFillOff = true;
    }

    var defaultStrokeColor = null;
    var defaultStrokeWidth = null;
    var defaultStrokeOff = false;
    if (params.stroke && params.stroke !== false && params.stroke !== null) {
        defaultStrokeColor = getCachedColor(params.stroke.r || 0, params.stroke.g || 0, params.stroke.b || 0);
        defaultStrokeWidth = params.stroke.width || null;
    } else if (params.stroke === false || params.stroke === null) {
        defaultStrokeOff = true;
    }

    var MAX_PATH_POINTS = 8000;
    var ids = [];
    var created = 0;
    var skipped = 0;
    var warnings = [];

    for (var i = 0; i < pathsArr.length; i++) {
        var subPath = pathsArr[i];
        var pts = subPath.points || [];

        if (pts.length < 2) {
            skipped++;
            warnings.push("paths[" + i + "] skipped: < 2 points");
            continue;
        }

        // Monotonic decimation guard per path
        if (pts.length > MAX_PATH_POINTS) {
            var origLen = pts.length;
            var dec = [];
            var lastIdx = -1;
            for (var di = 0; di < MAX_PATH_POINTS; di++) {
                var idx = Math.round(di * (origLen - 1) / (MAX_PATH_POINTS - 1));
                if (idx <= lastIdx) idx = lastIdx + 1;
                if (idx >= origLen) break;
                dec.push(pts[idx]);
                lastIdx = idx;
            }
            pts = dec;
            warnings.push("paths[" + i + "] decimated from " + origLen + " to " + pts.length);
        }

        // Y-flip via irMapPoints — artboard-relative coord transform
        var _abT = abTop, _abL = abLeft;
        var flipped = irMapPoints(subPath, function (pt) { return [_abL + pt[0], _abT - pt[1]]; });
        var item = targetLayer.pathItems.add();
        item.setEntirePath(flipped.points);
        item.closed = subPath.closed === true;

        // Assign MCP ID inline (confirmed: IDs in creation order)
        var subId = generateUUID();
        item.note = "@mcp:id=" + subId;
        if (params.name) {
            item.name = params.name + "_" + i;
        }

        // === STYLING (priority: styles[i] > styleScalars[i]+palette > shared defaults) ===

        var itemStyle = null;
        if (styles && styles[i]) {
            // Mode 1: explicit per-path style
            itemStyle = styles[i];
        } else if (scalars && palette && scalars[i] !== undefined) {
            // Mode 2: interpolate from palette using scalar t
            itemStyle = _interpolatePalette(scalars[i], palette);
        }

        if (itemStyle) {
            // Per-item styling
            if (itemStyle.fill && itemStyle.fill !== false) {
                item.fillColor = getCachedColor(itemStyle.fill.r || 0, itemStyle.fill.g || 0, itemStyle.fill.b || 0);
            } else if (itemStyle.fill === false || itemStyle.fill === null) {
                item.filled = false;
            } else if (defaultFillColor) {
                item.fillColor = defaultFillColor;
            } else if (defaultFillOff) {
                item.filled = false;
            }

            if (itemStyle.stroke && itemStyle.stroke !== false) {
                var sr = itemStyle.stroke.r !== undefined ? itemStyle.stroke.r : 0;
                var sg = itemStyle.stroke.g !== undefined ? itemStyle.stroke.g : 0;
                var sb = itemStyle.stroke.b !== undefined ? itemStyle.stroke.b : 0;
                item.strokeColor = getCachedColor(sr, sg, sb);
                item.stroked = true;
                if (itemStyle.stroke.width !== undefined) item.strokeWidth = itemStyle.stroke.width;
                else if (defaultStrokeWidth) item.strokeWidth = defaultStrokeWidth;
            } else if (itemStyle.stroke === false || itemStyle.stroke === null) {
                item.stroked = false;
            } else if (defaultStrokeColor) {
                item.strokeColor = defaultStrokeColor;
                item.stroked = true;
                if (defaultStrokeWidth) item.strokeWidth = defaultStrokeWidth;
            } else if (defaultStrokeOff) {
                item.stroked = false;
            }

            // Opacity (only set if provided — skip=no DOM write)
            if (itemStyle.opacity !== undefined) {
                item.opacity = itemStyle.opacity;
            }
        } else {
            // Shared defaults only (original behavior)
            if (defaultFillColor) {
                item.fillColor = defaultFillColor;
            } else if (defaultFillOff) {
                item.filled = false;
            }
            if (defaultStrokeColor) {
                item.strokeColor = defaultStrokeColor;
                item.stroked = true;
                if (defaultStrokeWidth) item.strokeWidth = defaultStrokeWidth;
            } else if (defaultStrokeOff) {
                item.stroked = false;
            }
        }

        ids.push(subId);
        created++;
    }

    // Emit warnings
    if (ctx && ctx.warn) {
        for (var w = 0; w < warnings.length; w++) {
            ctx.warn(warnings[w]);
        }
    }

    return {
        ok: true,
        data: {
            created: created,
            skipped: skipped,
            ids: ids,
            totalPoints: irPointCount(geo),
            stylingMode: scalars ? "scalars" : (styles ? "explicit" : "shared"),
            pagination: {
                offset: offset,
                limit: limit,
                total: totalPaths,
                hasMore: end < totalPaths
            }
        },
        warnings: warnings
    };
});

// ==================== Element Create Multi By Ref ====================

/**
 * Create multiple paths from IR stored in the session stash.
 * Resolves irKey via stashGet() and delegates to element_create_multi.
 * This reduces generator boilerplate and standardizes stash-miss errors.
 *
 * @param {Object} params
 * @param {string} params.irKey - Session stash key (set via stashPutIR)
 * @param {number} [params.offset] - Start index for chunked creation
 * @param {number} [params.limit] - Max paths to create in this chunk
 * @param {string} [params.layer] - Target layer name
 * @param {string} [params.name] - Name prefix for created items
 * @param {Object|false} [params.fill] - Fill color or false
 * @param {Object|false} [params.stroke] - Stroke color or false
 * @param {Array} [params.styleScalars] - Per-path scalar values for palette lerp
 * @param {Object} [params.palette] - Palette for scalar-based styling
 * @param {Array} [params.styles] - Per-path explicit style objects
 */
registerOpHandler("element_create_multi_by_ref", function (params, targets, ctx) {
    var irKey = params.irKey;
    if (!irKey) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "element_create_multi_by_ref requires 'irKey' param", "apply");
    }

    // Resolve from session stash
    if (typeof stashGet !== "function") {
        return makeError(ErrorCodes.E_EXECUTION, "element_create_multi_by_ref requires session.jsx (stashGet not found)", "apply");
    }

    var ir = stashGet(irKey);
    if (ir === null) {
        var available = (typeof stashKeys === "function") ? stashKeys().join(", ") : "unknown";
        return makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
            "Stash key '" + irKey + "' not found. Available keys: [" + available + "]", "apply");
    }

    // Delegate to element_create_multi with the resolved geometry
    var delegateParams = {};
    for (var k in params) {
        if (k !== "irKey") delegateParams[k] = params[k];
    }
    delegateParams.geometry = ir;

    // Look up the handler directly
    var multiHandler = OP_HANDLERS["element_create_multi"];
    if (!multiHandler) {
        return makeError(ErrorCodes.E_EXECUTION, "element_create_multi handler not registered", "apply");
    }

    return multiHandler(delegateParams, targets, ctx);
});

/**
 * Interpolate a style from a palette using scalar t ∈ [0,1].
 * @private
 * @param {number} t - Scalar value [0,1]
 * @param {Object} palette - { stroke:{r,g,b}, opacity, width } with [lo,hi] ranges
 * @returns {Object} { stroke:{r,g,b,width?}, opacity? }
 */
function _interpolatePalette(t, palette) {
    if (t < 0) t = 0;
    if (t > 1) t = 1;
    var style = {};

    if (palette.stroke) {
        style.stroke = {};
        var ps = palette.stroke;
        if (ps.r instanceof Array) style.stroke.r = Math.round(ps.r[0] + (ps.r[1] - ps.r[0]) * t);
        if (ps.g instanceof Array) style.stroke.g = Math.round(ps.g[0] + (ps.g[1] - ps.g[0]) * t);
        if (ps.b instanceof Array) style.stroke.b = Math.round(ps.b[0] + (ps.b[1] - ps.b[0]) * t);
        if (palette.width instanceof Array) {
            style.stroke.width = palette.width[0] + (palette.width[1] - palette.width[0]) * t;
        }
    }
    if (palette.fill) {
        style.fill = {};
        var pf = palette.fill;
        if (pf.r instanceof Array) style.fill.r = Math.round(pf.r[0] + (pf.r[1] - pf.r[0]) * t);
        if (pf.g instanceof Array) style.fill.g = Math.round(pf.g[0] + (pf.g[1] - pf.g[0]) * t);
        if (pf.b instanceof Array) style.fill.b = Math.round(pf.b[0] + (pf.b[1] - pf.b[0]) * t);
    }
    if (palette.opacity instanceof Array) {
        style.opacity = palette.opacity[0] + (palette.opacity[1] - palette.opacity[0]) * t;
    }
    return style;
}


// ==================== Template Instancing Helper ====================

/**
 * Create homogeneous items via duplicate() instancing.
 * Master template is created once, duplicated N times, then removed.
 *
 * @param {Object} params - must have .template and .instances[]
 * @param {Document} doc
 * @param {number} abTop - artboard top (pt)
 * @param {number} abLeft - artboard left (pt)
 * @param {Object} ctx - execution context
 * @returns {Object} SOC result {ok, data: {created, skipped, ids, bounds}, warnings}
 */
function _createFromTemplate(params, doc, abTop, abLeft, ctx) {
    var tmpl = params.template;
    var instances = params.instances;

    // Resolve target layer (deterministic: params.layer > ctx.defaultLayer > activeLayer)
    var layerResult = _resolveTargetLayer(doc, params, ctx);
    if (!layerResult.ok) return layerResult;
    var targetLayer = layerResult.layer;

    // Color cache
    var colorCache = {};
    function getCachedColor(colorDef) {
        if (!colorDef || colorDef === false || colorDef === null) return null;
        var key = (colorDef.r || 0) + "|" + (colorDef.g || 0) + "|" + (colorDef.b || 0);
        if (!colorCache[key]) {
            var c = new RGBColor();
            c.red = colorDef.r || 0;
            c.green = colorDef.g || 0;
            c.blue = colorDef.b || 0;
            colorCache[key] = c;
        }
        return colorCache[key];
    }

    // Bounds tracking
    var bMinX = Infinity, bMinY = Infinity, bMaxX = -Infinity, bMaxY = -Infinity;
    function trackBounds(x, y) {
        if (x < bMinX) bMinX = x;
        if (x > bMaxX) bMaxX = x;
        if (y < bMinY) bMinY = y;
        if (y > bMaxY) bMaxY = y;
    }

    var master = null;
    var createdItems = [];
    var ids = [];
    var created = 0;
    var skipped = 0;
    var warnings = [];

    try {
        // --- Create master item ---
        var type = tmpl.type;
        switch (type) {
            case "ellipse":
                var rx = tmpl.rx || tmpl.r || 5, ry = tmpl.ry || tmpl.r || 5;
                master = targetLayer.pathItems.ellipse(abTop + ry, abLeft - rx, rx * 2, ry * 2);
                break;
            case "rect":
                var bw = tmpl.w || 50, bh = tmpl.h || 50;
                master = targetLayer.pathItems.rectangle(abTop, abLeft, bw, bh);
                break;
            case "line":
                var lp = tmpl.points;
                if (!lp || lp.length < 2) {
                    return makeError(ErrorCodes.V_INVALID_PARAM_TYPE, "template line needs 2 points", "validate");
                }
                master = targetLayer.pathItems.add();
                master.setEntirePath([[abLeft + lp[0][0], abTop - lp[0][1]], [abLeft + lp[1][0], abTop - lp[1][1]]]);
                master.closed = false;
                master.filled = false;
                break;
            case "polyline":
            case "path":
                var pp = tmpl.points;
                if (!pp || pp.length < 2) {
                    return makeError(ErrorCodes.V_INVALID_PARAM_TYPE, "template path needs >=2 points", "validate");
                }
                master = targetLayer.pathItems.add();
                _createPathWithHandles(master, pp, abLeft, abTop);
                master.closed = tmpl.closed === true;
                if (!tmpl.closed) master.filled = false;
                break;
            case "polygon":
                var bSides = tmpl.sides || 6;
                var bRadius = tmpl.radius || 50;
                master = targetLayer.pathItems.polygon(abLeft, abTop, bRadius, bSides);
                break;
            case "star":
                var bNumPoints = tmpl.numPoints || tmpl.points || 5;
                var bOuterR = tmpl.outerRadius || 50;
                var bInnerR = tmpl.innerRadius || 25;
                master = targetLayer.pathItems.star(abLeft, abTop, bOuterR, bInnerR, bNumPoints);
                break;
            default:
                return makeError(ErrorCodes.V_INVALID_PARAM_TYPE, "unknown template type: " + type, "validate");
        }

        // Apply template styling
        if (tmpl.fill === false || tmpl.fill === null || tmpl.noFill) {
            master.filled = false;
        } else if (tmpl.fill) {
            var fc = getCachedColor(tmpl.fill);
            if (fc) { master.fillColor = fc; master.filled = true; }
        }
        if (tmpl.stroke === false || tmpl.stroke === null || tmpl.noStroke) {
            master.stroked = false;
        } else if (tmpl.stroke) {
            var sc = getCachedColor(tmpl.stroke);
            if (sc) {
                master.strokeColor = sc;
                master.stroked = true;
                if (tmpl.stroke.width !== undefined) master.strokeWidth = tmpl.stroke.width;
            }
        }
        if (tmpl.opacity !== undefined) {
            master.opacity = Math.max(0, Math.min(100, tmpl.opacity));
        }

        // --- Duplicate for each instance ---
        for (var i = 0; i < instances.length; i++) {
            var inst = instances[i];
            try {
                var clone = master.duplicate();

                // Position: absolute artboard-relative coordinates
                if (inst.x !== undefined && inst.y !== undefined) {
                    clone.position = [abLeft + inst.x, abTop - inst.y];
                    trackBounds(inst.x, inst.y);
                }

                // Per-instance scale (percentage, about center)
                if (inst.scale !== undefined && inst.scale !== 100) {
                    clone.resize(inst.scale, inst.scale, true, true, true, true, inst.scale, Transformation.CENTER);
                }

                // Per-instance fill override
                if (inst.fill === false || inst.fill === null) {
                    clone.filled = false;
                } else if (inst.fill) {
                    var ifc = getCachedColor(inst.fill);
                    if (ifc) { clone.fillColor = ifc; clone.filled = true; }
                }

                // Per-instance stroke override
                if (inst.stroke === false || inst.stroke === null) {
                    clone.stroked = false;
                } else if (inst.stroke) {
                    var isc = getCachedColor(inst.stroke);
                    if (isc) {
                        clone.strokeColor = isc;
                        clone.stroked = true;
                        if (inst.stroke.width !== undefined) clone.strokeWidth = inst.stroke.width;
                    }
                }

                // Per-instance opacity
                if (inst.opacity !== undefined) {
                    clone.opacity = Math.max(0, Math.min(100, inst.opacity));
                }

                // Assign MCP ID
                var id = generateUUID();
                clone.note = "@mcp:id=" + id;

                // Name
                if (params.name) {
                    clone.name = params.name + "_" + i;
                }

                createdItems.push(clone);
                ids.push(id);
                created++;
            } catch (e) {
                // Non-fatal per-instance error: null placeholder for index alignment
                ids.push(null);
                skipped++;
                warnings.push("instances[" + i + "] error: " + e.message);
            }
        }
    } catch (e) {
        // Fatal error: cleanup all created clones
        for (var k = createdItems.length - 1; k >= 0; k--) {
            try { createdItems[k].remove(); } catch (ex) { }
        }
        return makeError(ErrorCodes.R_APPLY_FAILED, "template instancing failed: " + e.message, "apply");
    } finally {
        // Always remove the master template
        if (master) {
            try { master.remove(); } catch (ex) { }
        }
    }

    var boundsResult = null;
    if (bMinX !== Infinity) {
        boundsResult = [bMinX, bMinY, bMaxX - bMinX, bMaxY - bMinY];
    }

    return {
        ok: true,
        data: {
            created: created,
            skipped: skipped,
            failed: skipped,
            ids: ids,
            bounds: boundsResult,
            mode: "template"
        },
        warnings: warnings
    };
}

// ==================== Element Create Batch ====================

/**
 * Batch-create items. Two modes (mutually exclusive):
 *
 *   1. template + instances: duplicate() instancing for homogeneous shapes
 *      params.template: {type, fill?, stroke?, opacity?, ...geometry}
 *      params.instances: [{x, y, fill?, stroke?, opacity?, scale?}, ...]
 *
 *   2. items[]: heterogeneous batch with per-item type/geometry
 *      type "line":     {points: [[x1,y1],[x2,y2]], style?}
 *      type "ellipse":  {cx, cy, rx, ry, style?}
 *      type "rect":     {x, y, w, h, style?}
 *      type "polyline":  {points: [[x,y],...], closed?, style?}
 *      type "path":     {points: [[x,y],...], closed?, style?}  (alias)
 *
 * params.defaultStyle: {fill?, stroke?} — applied when item has no style
 * params.layer:        target layer name (default: active layer)
 * params.name:         base name for items (suffixed with _i)
 *
 * Returns: {created, skipped, ids, bounds:[minX, minY, maxW, maxH]}
 */
registerOpHandler("element_create_batch", function (params, targets, ctx) {
    var doc = ctx.doc;
    var abTop = _artboardTop(doc);
    var abLeft = _artboardLeft(doc);

    // Mutual exclusion: template XOR items
    if (params.template && params.items) {
        return makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
            "cannot specify both 'template' and 'items'", "validate");
    }
    if (params.template && (!params.instances || !params.instances.length)) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM,
            "'instances' array required with 'template'", "validate");
    }

    // === Template mode: duplicate() instancing ===
    if (params.template) {
        // Validate template type upfront (contract-level check)
        var _VALID_TEMPLATE_TYPES = { ellipse: 1, rect: 1, line: 1, polyline: 1, path: 1 };
        if (!params.template.type || !_VALID_TEMPLATE_TYPES[params.template.type]) {
            return makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
                "invalid template.type: '" + (params.template.type || "(missing)") +
                "'. Valid types: ellipse, rect, line, polyline, path", "validate");
        }
        return _createFromTemplate(params, doc, abTop, abLeft, ctx);
    }

    // === Items mode: existing heterogeneous batch ===
    var items = params.items;

    if (!items || !items.length) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "items array is required", "apply");
    }

    // Resolve target layer (deterministic: params.layer > ctx.defaultLayer > activeLayer)
    var layerResult = _resolveTargetLayer(doc, params, ctx);
    if (!layerResult.ok) return layerResult;
    var targetLayer = layerResult.layer;

    var defaultStyle = params.defaultStyle || {};

    // Style cache: avoids creating duplicate RGBColor objects
    // Key format: "fill:r|g|b" or "stroke:r|g|b|w:1.5"
    var colorCache = {};
    function getCachedColor(colorDef) {
        if (!colorDef || colorDef === false || colorDef === null) return null;
        var key = (colorDef.r || 0) + "|" + (colorDef.g || 0) + "|" + (colorDef.b || 0);
        if (!colorCache[key]) {
            var c = new RGBColor();
            c.red = colorDef.r || 0;
            c.green = colorDef.g || 0;
            c.blue = colorDef.b || 0;
            colorCache[key] = c;
        }
        return colorCache[key];
    }

    var ids = [];
    var created = 0;
    var skipped = 0;
    var warnings = [];

    // Bounds tracking (input-geometry based, no DOM reads)
    var bMinX = Infinity, bMinY = Infinity, bMaxX = -Infinity, bMaxY = -Infinity;
    function trackBounds(x, y) {
        if (x < bMinX) bMinX = x;
        if (x > bMaxX) bMaxX = x;
        if (y < bMinY) bMinY = y;
        if (y > bMaxY) bMaxY = y;
    }

    for (var i = 0; i < items.length; i++) {
        var spec = items[i];
        var type = spec.type;
        if (!type) {
            skipped++;
            warnings.push("items[" + i + "] skipped: no type");
            continue;
        }

        var item = null;
        try {
            switch (type) {
                case "line":
                    var lp = spec.points;
                    if (!lp || lp.length < 2) { skipped++; warnings.push("items[" + i + "] skipped: line needs 2 points"); continue; }
                    item = targetLayer.pathItems.add();
                    item.setEntirePath([[abLeft + lp[0][0], abTop - lp[0][1]], [abLeft + lp[1][0], abTop - lp[1][1]]]);
                    item.closed = false;
                    item.filled = false;
                    trackBounds(lp[0][0], lp[0][1]);
                    trackBounds(lp[1][0], lp[1][1]);
                    break;

                case "ellipse":
                    var cx = spec.cx || 0, cy = spec.cy || 0;
                    var rx = spec.rx || spec.r || 5, ry = spec.ry || spec.r || 5;
                    item = targetLayer.pathItems.ellipse(abTop - cy + ry, abLeft + cx - rx, rx * 2, ry * 2);
                    trackBounds(cx - rx, cy - ry);
                    trackBounds(cx + rx, cy + ry);
                    break;

                case "rect":
                    var bx = spec.x || 0, by = spec.y || 0;
                    var bw = spec.w || 50, bh = spec.h || 50;
                    item = targetLayer.pathItems.rectangle(abTop - by, abLeft + bx, bw, bh);
                    trackBounds(bx, by);
                    trackBounds(bx + bw, by + bh);
                    break;

                case "polyline":
                case "path":
                    var pp = spec.points;
                    if (!pp || pp.length < 2) { skipped++; warnings.push("items[" + i + "] skipped: path needs >=2 points"); continue; }
                    if (pp.length > 8000) { skipped++; warnings.push("items[" + i + "] skipped: >8000 points"); continue; }
                    item = targetLayer.pathItems.add();
                    _createPathWithHandles(item, pp, abLeft, abTop);
                    // Track bounds using anchor coordinates
                    for (var pi = 0; pi < pp.length; pi++) {
                        var bpt = (pp[pi].length === 3 && pp[pi][0] instanceof Array) ? pp[pi][0] : pp[pi];
                        trackBounds(bpt[0], bpt[1]);
                    }
                    item.closed = spec.closed === true;
                    if (!spec.closed) item.filled = false;
                    break;

                default:
                    skipped++;
                    warnings.push("items[" + i + "] skipped: unknown type '" + type + "'");
                    continue;
            }

            // Assign ID
            var id = generateUUID();
            item.note = "@mcp:id=" + id;
            ids.push(id);

            // Name
            if (params.name) {
                item.name = params.name + "_" + i;
            }

            // Apply style: per-item overrides defaultStyle
            var style = spec.style || defaultStyle;

            // Fill
            var fillDef = style.fill !== undefined ? style.fill : defaultStyle.fill;
            if (fillDef === null || fillDef === false) {
                item.filled = false;
            } else if (fillDef) {
                var fc = getCachedColor(fillDef);
                if (fc) {
                    item.fillColor = fc;
                    item.filled = true;
                }
            }

            // Stroke
            var strokeDef = style.stroke !== undefined ? style.stroke : defaultStyle.stroke;
            if (strokeDef === null || strokeDef === false) {
                item.stroked = false;
            } else if (strokeDef) {
                var sc = getCachedColor(strokeDef);
                if (sc) {
                    item.strokeColor = sc;
                    item.stroked = true;
                    if (strokeDef.width !== undefined) item.strokeWidth = strokeDef.width;
                }
            }

            // Opacity
            var opacityDef = style.opacity !== undefined ? style.opacity : defaultStyle.opacity;
            if (opacityDef !== undefined) {
                item.opacity = Math.max(0, Math.min(100, opacityDef));
            }

            created++;
        } catch (e) {
            skipped++;
            warnings.push("items[" + i + "] error: " + e.message);
        }
    }

    // Compute bounds result
    var boundsResult = null;
    if (bMinX !== Infinity) {
        boundsResult = [bMinX, bMinY, bMaxX - bMinX, bMaxY - bMinY];
    }

    return {
        ok: true,
        data: {
            created: created,
            skipped: skipped,
            failed: skipped,
            ids: ids,
            bounds: boundsResult
        },
        warnings: warnings
    };
});

// ==================== Element Modify ====================

registerOpHandler("element_modify", function (params, targets, ctx) {
    if (targets.length === 0) {
        return makeError(ErrorCodes.V_NO_SELECTION, "No targets to modify", "apply");
    }

    var modified = 0;
    var warnings = [];
    var firstModifiedItem = null;

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];

        try {
            // Position (artboard-relative)
            if (params.x !== undefined) item.left = _artboardLeft(ctx.doc) + params.x;
            if (params.y !== undefined) item.top = _artboardTop(ctx.doc) - params.y;

            // Size
            if (params.width !== undefined) item.width = params.width;
            if (params.height !== undefined) item.height = params.height;

            // Rotation
            if (params.rotation !== undefined) {
                item.rotate(params.rotation);
            }

            // Scale
            if (params.scale !== undefined) {
                var s = params.scale * 100;
                item.resize(s, s);
            }

            // Fill
            if (params.fill) {
                var fillColor = new RGBColor();
                fillColor.red = params.fill.r || 0;
                fillColor.green = params.fill.g || 0;
                fillColor.blue = params.fill.b || 0;
                item.fillColor = fillColor;
                item.filled = true;
            } else if (params.fill === null || params.fill === false) {
                item.filled = false;
            }

            // Stroke
            if (params.stroke) {
                var strokeColor = new RGBColor();
                strokeColor.red = params.stroke.r || 0;
                strokeColor.green = params.stroke.g || 0;
                strokeColor.blue = params.stroke.b || 0;
                item.strokeColor = strokeColor;
                item.stroked = true;
                if (params.stroke.width) {
                    item.strokeWidth = params.stroke.width;
                }
            } else if (params.stroke === null || params.stroke === false) {
                item.stroked = false;
            }

            // Opacity
            if (params.opacity !== undefined) {
                var opVal = params.opacity;
                if (opVal < 0) opVal = 0;
                if (opVal > 100) opVal = 100;
                item.opacity = opVal;
            }

            // Name
            if (params.name !== undefined) {
                item.name = params.name;
            }

            // Layer move
            if (params.layer !== undefined) {
                var targetLayer = null;
                for (var li = 0; li < ctx.doc.layers.length; li++) {
                    if (ctx.doc.layers[li].name === params.layer) {
                        targetLayer = ctx.doc.layers[li];
                        break;
                    }
                }
                if (targetLayer) {
                    item.move(targetLayer, ElementPlacement.PLACEATEND);
                } else {
                    warnings.push("Layer not found for move: " + params.layer);
                }
            }

            modified++;
            if (!firstModifiedItem) firstModifiedItem = item;
        } catch (e) {
            warnings.push("Failed to modify item " + i + ": " + e.message);
        }
    }

    // Position echo: bounds-based position in user coords (artboard-relative, y-down)
    // Note: width/height are axis-aligned bounding box dimensions, not original geometry
    var posEcho = null;
    if (firstModifiedItem) {
        var abT = _artboardTop(ctx.doc), abL = _artboardLeft(ctx.doc);
        posEcho = {
            x: Math.round((firstModifiedItem.left - abL) * 100) / 100,
            y: Math.round((abT - firstModifiedItem.top) * 100) / 100,
            width: Math.round(firstModifiedItem.width * 100) / 100,
            height: Math.round(firstModifiedItem.height * 100) / 100
        };
    }
    return {
        ok: true,
        data: { modified: modified, total: targets.length, failed: targets.length - modified, position: posEcho },
        warnings: warnings
    };
});

// ==================== Element Delete ====================

registerOpHandler("element_delete", function (params, targets, ctx) {
    if (targets.length === 0) {
        return {
            ok: true,
            data: { deleted: 0 }
        };
    }

    var deleted = 0;
    var warnings = [];

    // Delete in reverse order to avoid index shifting issues
    for (var i = targets.length - 1; i >= 0; i--) {
        try {
            // Tombstone in heap before DOM removal (tracked by active txn)
            if (typeof extractMcpId === "function" && typeof heapTombstone === "function") {
                var id = extractMcpId(targets[i].note);
                if (id) heapTombstone(id);
            }
            targets[i].remove();
            deleted++;
        } catch (e) {
            warnings.push("Failed to delete item " + i + ": " + e.message);
        }
    }

    return {
        ok: deleted > 0 || targets.length === 0,
        data: { deleted: deleted, total: targets.length, failed: targets.length - deleted },
        warnings: warnings
    };
});

// ==================== Element Replace (Atomic Swap) ====================

/**
 * Atomically replace a single element with new content.
 * Uses a sandbox group pattern:
 *   1. Capture old item metadata (bounds, layer, z-order, visibility, locked)
 *   2. Create new content inside a temporary sandbox group
 *   3. Move sandbox next to old item, unpack children, remove old item + sandbox
 *   4. On failure: sandbox.remove() in catch — old item untouched
 *
 * @param {Object} params - element_create params + inheritPosition
 * @param {Array} targets - Must resolve to exactly 1 item
 * @param {Object} ctx - Execution context
 */
registerOpHandler("element_replace", function (params, targets, ctx) {
    // --- Validate: exactly 1 target ---
    if (!targets || targets.length !== 1) {
        return makeError(ErrorCodes.V_INVALID_TARGETS,
            "element_replace requires exactly 1 target, got " + (targets ? targets.length : 0),
            "validate");
    }

    var doc = ctx.doc;
    var oldItem = targets[0];

    // --- Capture metadata from old item ---
    var oldBounds = oldItem.geometricBounds; // [left, top, right, bottom]
    var oldLayer = oldItem.layer;
    var oldVisible = oldItem.hidden === false;
    var oldLocked = oldItem.locked;
    var abTop = _artboardTop(doc);
    var abLeft = _artboardLeft(doc);

    // Extract old MCP ID for tombstoning
    var oldId = null;
    if (typeof extractMcpId === "function") {
        oldId = extractMcpId(oldItem.note);
    }

    // Unlock old item if locked (required for removal)
    if (oldLocked) {
        oldItem.locked = false;
    }

    // --- Create sandbox group on same layer ---
    var sandbox = null;
    var newItem = null;

    try {
        sandbox = oldLayer.groupItems.add();
        sandbox.name = "__mcp_replace_sandbox__";

        // --- Build replacement inside sandbox using element_create params ---
        var type = params.type || "rect";
        var newId = params.id || generateUUID();
        var width = params.width || params.w || 100;
        var height = params.height || params.h || 100;

        // Position: inherit from old item unless overridden
        var inheritPosition = params.inheritPosition !== false; // default true
        var x, y;
        if (inheritPosition && params.x === undefined && params.y === undefined) {
            // Convert old item position to user coords (artboard-relative)
            x = oldBounds[0] - abLeft;
            y = abTop - oldBounds[1];
        } else {
            x = params.x || 0;
            y = params.y || 0;
        }

        var aiTop = abTop - y;
        var aiLeft = abLeft + x;

        // Create element inside sandbox
        switch (type) {
            case "rect":
                newItem = sandbox.pathItems.rectangle(aiTop, aiLeft, width, height);
                break;
            case "ellipse":
                newItem = sandbox.pathItems.ellipse(aiTop, aiLeft, width, height);
                break;
            case "line":
                // Accept x1/y1 as aliases for start point (x/y)
                var rlx1 = params.x1 !== undefined ? params.x1 : x;
                var rly1 = params.y1 !== undefined ? params.y1 : y;
                var rlx2 = params.x2 !== undefined ? params.x2 : rlx1 + width;
                var rly2 = params.y2 !== undefined ? params.y2 : rly1;
                newItem = sandbox.pathItems.add();
                newItem.setEntirePath([[abLeft + rlx1, abTop - rly1], [abLeft + rlx2, abTop - rly2]]);
                newItem.closed = false;
                newItem.filled = false;
                break;
            case "polygon":
                var sides = params.sides || 6;
                var radius = params.radius || 50;
                newItem = sandbox.pathItems.polygon(aiLeft, aiTop, radius, sides);
                break;
            case "star":
                var points = params.numPoints || params.points || 5;
                var outerRadius = params.outerRadius || 50;
                var innerRadius = params.innerRadius || 25;
                newItem = sandbox.pathItems.star(aiLeft, aiTop, outerRadius, innerRadius, points);
                break;
            case "roundedRect":
                var cornerRadius = params.cornerRadius || 10;
                newItem = sandbox.pathItems.roundedRectangle(aiTop, aiLeft, width, height, cornerRadius, cornerRadius);
                break;
            case "text":
                var tf = sandbox.textFrames.add();
                tf.contents = params.contents || params.text || "";
                tf.position = [aiLeft, aiTop];
                if (params.fontSize) tf.textRange.characterAttributes.size = params.fontSize;
                if (params.fontName) {
                    try {
                        tf.textRange.characterAttributes.textFont =
                            app.textFonts.getByName(params.fontName);
                    } catch (e) { /* font not found, keep default */ }
                }
                newItem = tf;
                break;
            case "path":
            case "polyline":
                var pathPoints = params.points;
                if (!pathPoints || pathPoints.length < 2) {
                    sandbox.remove();
                    return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "Path requires >= 2 points", "apply");
                }
                newItem = sandbox.pathItems.add();
                _createPathWithHandles(newItem, pathPoints, abLeft, abTop);
                newItem.closed = (type === "path") ? (params.closed !== false) : (params.closed === true);
                break;
            default:
                sandbox.remove();
                return makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
                    "Unknown element type for replace: " + type, "apply");
        }

        // Assign MCP ID
        newItem.note = "@mcp:id=" + newId;

        // Set name if provided
        if (params.name) {
            newItem.name = params.name;
        }

        // Apply fill
        if (params.fill) {
            var fillColor = new RGBColor();
            fillColor.red = params.fill.r || 0;
            fillColor.green = params.fill.g || 0;
            fillColor.blue = params.fill.b || 0;
            newItem.fillColor = fillColor;
        }

        // Apply stroke
        if (params.stroke) {
            var strokeColor = new RGBColor();
            strokeColor.red = params.stroke.r || 0;
            strokeColor.green = params.stroke.g || 0;
            strokeColor.blue = params.stroke.b || 0;
            newItem.strokeColor = strokeColor;
            newItem.stroked = true;
            if (params.stroke.width !== undefined) {
                newItem.strokeWidth = params.stroke.width;
            }
        }

        // No stroke option
        if (params.noStroke || params.stroke === null || params.stroke === false) {
            newItem.stroked = false;
        }

        // Opacity
        if (params.opacity !== undefined) {
            newItem.opacity = params.opacity;
        }

        // --- Commit sequence (z-order safe) ---

        // 1. Move sandbox next to oldItem via PLACEAFTER (z-order anchor preserved)
        sandbox.move(oldItem, ElementPlacement.PLACEAFTER);

        // 2. Move new item out of sandbox to the layer
        newItem.move(oldLayer, ElementPlacement.PLACEBEFORE);

        // 3. Inherit visibility from old item
        newItem.hidden = !oldVisible;

        // 4. Tombstone old MCP ID, then remove old item
        if (oldId && typeof heapTombstone === "function") {
            heapTombstone(oldId);
        }
        oldItem.remove();

        // 5. Remove the now-empty sandbox
        sandbox.remove();
        sandbox = null;

        // 6. Apply locked state from old item
        if (oldLocked) {
            newItem.locked = true;
        }

        return {
            ok: true,
            id: newId,
            data: {
                typename: newItem.typename,
                bounds: [newItem.left, newItem.top, newItem.width, newItem.height],
                oldId: oldId
            }
        };

    } catch (e) {
        // --- Failure path: clean up sandbox, old item untouched ---
        if (sandbox) {
            try { sandbox.remove(); } catch (ex) { }
        }
        // Restore locked state if we unlocked it
        if (oldLocked) {
            try { oldItem.locked = true; } catch (ex) { }
        }
        return makeError(ErrorCodes.R_APPLY_FAILED,
            "element_replace failed: " + e.message, "apply");
    }
});
