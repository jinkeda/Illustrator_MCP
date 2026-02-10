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
    throw new Error("ops_element.jsx requires task_executor.jsx (findLayer=" + typeof findLayer + ")");
}
if (typeof isIR !== "function") {
    throw new Error("ops_element.jsx requires geo_ir.jsx (isIR=" + typeof isIR + ")");
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
    var layer = params.layer || null;
    var name = params.name || null;

    // Resolve target layer
    var targetLayer = doc.activeLayer;
    if (layer) {
        for (var i = 0; i < doc.layers.length; i++) {
            if (doc.layers[i].name === layer) {
                targetLayer = doc.layers[i];
                break;
            }
        }
    }

    var item = null;

    // Convert to Illustrator coordinates (Y is negative downward)
    var aiTop = -y;
    var aiLeft = x;

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
            var x2 = params.x2 !== undefined ? params.x2 : x + 100;
            var y2 = params.y2 !== undefined ? params.y2 : y;
            item = targetLayer.pathItems.add();
            item.setEntirePath([[x, -y], [x2, -y2]]);
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
            item = targetLayer.pathItems.polygon(x, -y, radius, sides);
            break;

        case "star":
            var points = params.points || 5;
            var outerRadius = params.outerRadius || 50;
            var innerRadius = params.innerRadius || 25;
            item = targetLayer.pathItems.star(x, -y, outerRadius, innerRadius, points);
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
            // Y-flip via irMapPoints if IR, otherwise manual
            item = targetLayer.pathItems.add();
            if (isIR(geoInput)) {
                var flipped = irMapPoints(geoInput, function (pt) { return [pt[0], -pt[1]]; });
                item.setEntirePath(flipped.points);
            } else {
                var aiPoints = [];
                for (var pi = 0; pi < pathPoints.length; pi++) {
                    aiPoints.push([pathPoints[pi][0], -pathPoints[pi][1]]);
                }
                item.setEntirePath(aiPoints);
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
    var doc = app.activeDocument;
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

    // Resolve layer ONCE (Hole B optimization)
    var targetLayer = params.layer ? findLayer(doc, params.layer) : doc.activeLayer;
    if (!targetLayer) {
        return makeError(ErrorCodes.V_INVALID_PARAM_TYPE, "Layer not found: " + params.layer, "apply");
    }

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

        // Y-flip via irMapPoints — single source of truth for coord transform
        var flipped = irMapPoints(subPath, function (pt) { return [pt[0], -pt[1]]; });
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
        if (ps.r) style.stroke.r = Math.round(ps.r[0] + (ps.r[1] - ps.r[0]) * t);
        if (ps.g) style.stroke.g = Math.round(ps.g[0] + (ps.g[1] - ps.g[0]) * t);
        if (ps.b) style.stroke.b = Math.round(ps.b[0] + (ps.b[1] - ps.b[0]) * t);
        if (palette.width) {
            style.stroke.width = palette.width[0] + (palette.width[1] - palette.width[0]) * t;
        }
    }
    if (palette.fill) {
        style.fill = {};
        var pf = palette.fill;
        if (pf.r) style.fill.r = Math.round(pf.r[0] + (pf.r[1] - pf.r[0]) * t);
        if (pf.g) style.fill.g = Math.round(pf.g[0] + (pf.g[1] - pf.g[0]) * t);
        if (pf.b) style.fill.b = Math.round(pf.b[0] + (pf.b[1] - pf.b[0]) * t);
    }
    if (palette.opacity) {
        style.opacity = palette.opacity[0] + (palette.opacity[1] - palette.opacity[0]) * t;
    }
    return style;
}


// ==================== Element Create Batch ====================

/**
 * Batch-create mixed shape types with per-item styling.
 * Performance-optimized: style caching, single layer lookup, bounds tracking.
 *
 * params.items: array of {type, style?, ...type-specific fields}
 *   type "line":     {points: [[x1,y1],[x2,y2]], style?}
 *   type "ellipse":  {cx, cy, rx, ry, style?}
 *   type "rect":     {x, y, w, h, style?}
 *   type "polyline":  {points: [[x,y],...], closed?, style?}
 *   type "path":     {points: [[x,y],...], closed?, style?}  (alias)
 *
 * params.defaultStyle: {fill?, stroke?} — applied when item has no style
 * params.layer:        target layer name (default: active layer)
 * params.name:         base name for items (suffixed with _i)
 *
 * Returns: {created, skipped, ids, bounds:[minX, minY, maxW, maxH]}
 */
registerOpHandler("element_create_batch", function (params, targets, ctx) {
    var doc = ctx.doc;
    var items = params.items;

    if (!items || !items.length) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "items array is required", "apply");
    }

    // Resolve target layer
    var targetLayer = doc.activeLayer;
    if (params.layer) {
        var found = false;
        for (var li = 0; li < doc.layers.length; li++) {
            if (doc.layers[li].name === params.layer) {
                targetLayer = doc.layers[li];
                found = true;
                break;
            }
        }
        if (!found) {
            return makeError(ErrorCodes.V_INVALID_PARAM_TYPE, "Layer not found: " + params.layer, "apply");
        }
    }

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
                    item.setEntirePath([[lp[0][0], -lp[0][1]], [lp[1][0], -lp[1][1]]]);
                    item.closed = false;
                    item.filled = false;
                    trackBounds(lp[0][0], lp[0][1]);
                    trackBounds(lp[1][0], lp[1][1]);
                    break;

                case "ellipse":
                    var cx = spec.cx || 0, cy = spec.cy || 0;
                    var rx = spec.rx || spec.r || 5, ry = spec.ry || spec.r || 5;
                    item = targetLayer.pathItems.ellipse(-cy + ry, cx - rx, rx * 2, ry * 2);
                    trackBounds(cx - rx, cy - ry);
                    trackBounds(cx + rx, cy + ry);
                    break;

                case "rect":
                    var bx = spec.x || 0, by = spec.y || 0;
                    var bw = spec.w || 50, bh = spec.h || 50;
                    item = targetLayer.pathItems.rectangle(-by, bx, bw, bh);
                    trackBounds(bx, by);
                    trackBounds(bx + bw, by + bh);
                    break;

                case "polyline":
                case "path":
                    var pp = spec.points;
                    if (!pp || pp.length < 2) { skipped++; warnings.push("items[" + i + "] skipped: path needs >=2 points"); continue; }
                    if (pp.length > 8000) { skipped++; warnings.push("items[" + i + "] skipped: >8000 points"); continue; }
                    item = targetLayer.pathItems.add();
                    var aiPts = [];
                    for (var pi = 0; pi < pp.length; pi++) {
                        aiPts.push([pp[pi][0], -pp[pi][1]]);
                        trackBounds(pp[pi][0], pp[pi][1]);
                    }
                    item.setEntirePath(aiPts);
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
        ok: created > 0,
        data: {
            created: created,
            skipped: skipped,
            ids: ids,
            bounds: boundsResult
        },
        warnings: warnings
    };
});

// ==================== Element Modify ====================

registerOpHandler("element_modify", function (params, targets, ctx) {
    if (targets.length === 0) {
        return {
            ok: false,
            error: makeError(ErrorCodes.V_NO_SELECTION, "No targets to modify", "apply")
        };
    }

    var modified = 0;
    var warnings = [];

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];

        try {
            // Position
            if (params.x !== undefined) item.left = params.x;
            if (params.y !== undefined) item.top = -params.y;

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
        } catch (e) {
            warnings.push("Failed to modify item " + i + ": " + e.message);
        }
    }

    return {
        ok: modified > 0,
        data: { modified: modified, total: targets.length, failed: targets.length - modified },
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
            targets[i].remove();
            deleted++;
        } catch (e) {
            warnings.push("Failed to delete item " + i + ": " + e.message);
        }
    }

    // Invalidate ID index after deletes (deleted items would cause stale references)
    if (deleted > 0 && typeof invalidateIdIndex === "function") {
        invalidateIdIndex();
    }

    return {
        ok: deleted > 0 || targets.length === 0,
        data: { deleted: deleted, total: targets.length, failed: targets.length - deleted },
        warnings: warnings
    };
});
