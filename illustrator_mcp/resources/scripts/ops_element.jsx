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

/**
 * Close a failed element-creation scope without losing the primary result.
 *
 * Ownership removes DOM objects; the heap is updated only for identified
 * objects whose removal actually succeeded.  A removal failure means the
 * artwork is still present and its heap entry must remain resolvable.
 * Existing cleanup evidence from a delegated handler is preserved and the
 * failures from this scope are appended to it.
 */
function _elementCleanupFailure(scope, result) {
    var cleanup = mcpOwnCleanup(scope);
    var records = cleanup.records || [];
    for (var i = 0; i < records.length; i++) {
        if (records[i].outcome === "removed" && records[i].mcpId &&
                typeof heapTombstone === "function") {
            heapTombstone(records[i].mcpId);
        }
    }
    var failures = mcpCleanupFailures(result).slice(0);
    for (var f = 0; f < cleanup.failed.length; f++) {
        failures.push(cleanup.failed[f]);
    }
    mcpSetCleanupFailures(result, failures);
    return result;
}

/** Roll back element_replace and publish whether its replacement still exists. */
function _elementReplaceRollback(scope, result, newItem) {
    if (typeof mcpOwnReconcileDetach === "function") {
        mcpOwnReconcileDetach(scope, newItem);
    }
    _elementCleanupFailure(scope, result);

    var replacementRemains = false;
    var establishedId = null;
    var entries = scope ? scope.entries : [];
    for (var i = 0; i < entries.length; i++) {
        var entry = entries[i];
        if (entry.item !== newItem) continue;
        establishedId = entry.mcpId || null;
        if (entry.outcome === "owned" || entry.outcome === "removal_failed" ||
                entry.outcome === "committed" || entry.outcome === "released") {
            replacementRemains = true;
        } else if (entry.outcome === "absorbed") {
            // An absorbed child remains exactly when the sandbox that owns its
            // lifetime remains. Read the final container record, not the first
            // removal attempt.
            replacementRemains = true;
            for (var c = 0; c < entries.length; c++) {
                if (entries[c].item === entry.absorbedBy &&
                        (entries[c].outcome === "removed" ||
                         entries[c].outcome === "disposed")) {
                    replacementRemains = false;
                    break;
                }
            }
        }
        break;
    }

    // `newId` is only the requested/planned identity until stampMcpId and
    // mcpOwnIdentify succeed. Publish and tombstone only the identity recorded
    // by ownership, never a name that no surviving object actually carries.
    if (establishedId) {
        if (replacementRemains) {
            result.data = result.data || {};
            result.data.ids = result.data.ids || [];
            if (result.data.ids.indexOf(establishedId) < 0) {
                result.data.ids.push(establishedId);
            }
        } else if (typeof heapTombstone === "function") {
            // When the sandbox removed an absorbed child, that child's record
            // remains "absorbed" by design, so the generic cleanup helper does
            // not see an individual removal to tombstone.
            heapTombstone(establishedId);
        }
    }
    return result;
}

/** Restore a temporarily unlocked original and disclose a failed restoration. */
function _elementReplaceRestoreLock(oldItem, restoreNeeded, oldId, result) {
    if (!restoreNeeded || !oldItem) return result;
    try {
        oldItem.locked = true;
    } catch (lockError) {
        result.data = result.data || {};
        if (oldId) result.data.modifiedIds = [oldId];
        else result.data.unnamedModification = true;
        result.warnings = result.warnings || [];
        result.warnings.push(
            "Original item remains unlocked after replacement rollback: " +
            lockError.message
        );
        result.error = result.error || {};
        result.error.details = result.error.details || {};
        result.error.details.lockRestoreFailure = String(lockError.message || lockError);
    }
    return result;
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
    var clipGroupId = null;
    var delegatedClipResult = null;

    // ── Early validation: clipTo target must exist and be valid type ──
    var clipTarget = null;  // declared once, reused in post-creation block
    if (params.clipTo) {
        clipTarget = resolveIdCompat(params.clipTo, doc, { freshScan: true });
        if (!clipTarget) {
            return makeError(ErrorCodes.V_INVALID_PARAM_VALUE || "V009",
                "clipTo target not found: '" + params.clipTo + "'", "validate");
        }
        var ctType = clipTarget.typename;
        // Valid targets: free path, clipping group, or consumed mask (clipping item inside clip group)
        var isPath = (ctType === "PathItem" || ctType === "CompoundPathItem");
        var isClipGroup = (ctType === "GroupItem" && clipTarget.clipped);
        var isConsumedMask = (clipTarget.clipping && clipTarget.parent &&
            clipTarget.parent.typename === "GroupItem" && clipTarget.parent.clipped);
        if (!isPath && !isClipGroup && !isConsumedMask) {
            return makeError(ErrorCodes.V_INVALID_PARAM_TYPE || "V010",
                "clipTo must be PathItem, CompoundPathItem, or clipping GroupItem, got " + ctType,
                "validate");
        }
    }

    // Convert to Illustrator coordinates:
    // User coords: (0,0) = artboard top-left, Y increases downward
    // Illustrator:  Y increases upward, artboard top is a positive number
    var abTop = _artboardTop(doc);
    var abLeft = _artboardLeft(doc);
    var aiTop = abTop - y;          // e.g. y=50 on 400pt artboard → aiY=350
    var aiLeft = abLeft + x;

    // OR05. The item belongs to this operation from the instant it exists
    // until every requested operation against it has succeeded.  In
    // particular, registration is before setEntirePath, areaText conversion,
    // stamping, naming, styling, bounds reads and clip-group moves: each of
    // those can throw after Illustrator has already put artwork on the page.
    var createScope = mcpOwnBegin("element_create");
    try {
      switch (type) {
        case "rect":
            // rectangle(top, left, width, height)
            item = mcpOwnAllocate(createScope,
                targetLayer.pathItems.rectangle(aiTop, aiLeft, width, height), "rect");
            break;

        case "ellipse":
            // ellipse(top, left, width, height)
            item = mcpOwnAllocate(createScope,
                targetLayer.pathItems.ellipse(aiTop, aiLeft, width, height), "ellipse");
            break;

        case "line":
            // Accept x1/y1 as aliases for start point (x/y)
            var lx1 = params.x1 !== undefined ? params.x1 : x;
            var ly1 = params.y1 !== undefined ? params.y1 : y;
            var lx2 = params.x2 !== undefined ? params.x2 : lx1 + 100;
            var ly2 = params.y2 !== undefined ? params.y2 : ly1;
            item = mcpOwnAllocate(createScope, targetLayer.pathItems.add(), "line");
            item.setEntirePath([[abLeft + lx1, abTop - ly1], [abLeft + lx2, abTop - ly2]]);
            item.closed = false;
            item.filled = false;
            break;

        case "roundedRect":
            var cornerRadius = params.cornerRadius || 10;
            item = mcpOwnAllocate(createScope,
                targetLayer.pathItems.roundedRectangle(
                    aiTop, aiLeft, width, height, cornerRadius, cornerRadius
                ), "roundedRect");
            break;

        case "polygon":
            var sides = params.sides || 6;
            var radius = params.radius || 50;
            item = mcpOwnAllocate(createScope,
                targetLayer.pathItems.polygon(abLeft + x, abTop - y, radius, sides), "polygon");
            break;

        case "star":
            var points = params.numPoints || params.points || 5;
            var outerRadius = params.outerRadius || 50;
            var innerRadius = params.innerRadius || 25;
            item = mcpOwnAllocate(createScope,
                targetLayer.pathItems.star(abLeft + x, abTop - y, outerRadius, innerRadius, points), "star");
            break;

        case "text":
            var contents = params.contents || params.text || "";
            var fontSize = params.fontSize || 12;
            if (params.width != null && params.height != null) {
                // Area text: create container rect, then use areaText()
                var container = mcpOwnAllocate(createScope,
                    targetLayer.pathItems.rectangle(aiTop, aiLeft, width, height), "areaTextPath");
                container.filled = false;
                container.stroked = false;
                item = mcpOwnAllocate(createScope,
                    targetLayer.textFrames.areaText(container), "areaText");
                mcpOwnAbsorb(createScope, [container], item);
            } else {
                // Point text
                item = mcpOwnAllocate(createScope, targetLayer.textFrames.add(), "pointText");
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
                return _elementCleanupFailure(createScope,
                    makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "Path requires 'geometry' (IR) or 'points' array", "apply"));
            }
            if (isIR(geoInput)) {
                // Geometry IR object — validate before consuming
                if (geoInput.ir === "multi") {
                    return _elementCleanupFailure(createScope, makeError(
                        ErrorCodes.V_INVALID_PARAM_TYPE,
                        "multi IR not supported in element_create; use element_create_multi",
                        "apply"
                    ));
                }
                var irVal = irValidate(geoInput);
                if (!irVal.ok) {
                    return _elementCleanupFailure(createScope,
                        makeError(ErrorCodes.V_INVALID_PARAM_TYPE, "IR validation failed: " + irVal.errors.join("; "), "apply"));
                }
                if (geoInput.ir !== "path") {
                    return _elementCleanupFailure(createScope,
                        makeError(ErrorCodes.V_INVALID_PARAM_TYPE, "Expected ir:'path', got ir:'" + geoInput.ir + "'", "apply"));
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
                return _elementCleanupFailure(createScope,
                    makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "Path requires >= 2 points", "apply"));
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
            item = mcpOwnAllocate(createScope, targetLayer.pathItems.add(), "path");
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
            return _elementCleanupFailure(createScope, makeError(
                ErrorCodes.V_INVALID_PARAM_TYPE,
                "Unknown element type: " + type,
                "apply"
            ));
      }

    // Assign ID via note + register in heap (H1 invariant)
    stampMcpId(item, id);
    mcpOwnIdentify(createScope, item, id);

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

    // Capture bounds BEFORE clipTo (clip may change item's coordinate context)
    var preBounds = [item.left, item.top, item.width, item.height];

    // clipTo: clip element to target (v2: append to existing, create new, rollback)
    if (params.clipTo) {
        // Reuse early-validated clipTarget (already freshScan'd in this eval context).
        // Only re-resolve if clipTarget was somehow invalidated (e.g., removed by another op).
        if (!clipTarget) {
            clipTarget = resolveIdCompat(params.clipTo, ctx.doc, { freshScan: true });
        }
        if (!clipTarget) {
            return _elementCleanupFailure(createScope,
                makeError(ErrorCodes.V_INVALID_PARAM_VALUE || "V009",
                    "clipTo target not found: '" + params.clipTo + "'", "resolve"));
        }

        // Determine clip mode:
        // (a) Target is already a clipping group → append
        // (b) Target is a consumed mask (clipping:true inside a clipped group) → append to parent group
        // (c) Target is a free PathItem/CompoundPathItem → create new clip group
        var appendGroup = null;
        if (clipTarget.typename === "GroupItem" && clipTarget.clipped) {
            // (a) Direct clip group reference
            appendGroup = clipTarget;
        } else if (clipTarget.clipping && clipTarget.parent &&
            clipTarget.parent.typename === "GroupItem" && clipTarget.parent.clipped) {
            // (b) Consumed mask — append to its parent clip group
            appendGroup = clipTarget.parent;
        }

        if (appendGroup) {
            // Append to existing clip group
            var preMoveParent = item.parent;
            item.move(appendGroup, ElementPlacement.PLACEATEND);
            // Verify move succeeded (parent should now be the clip group)
            if (item.parent === preMoveParent) {
                return _elementCleanupFailure(createScope,
                    makeError(ErrorCodes.E_EXECUTION || "E001",
                        "Failed to move item into clip group (target may be locked)", "apply"));
            }
            // Return the clip group's MCP ID if it has one
            try {
                var gpNote = appendGroup.note || "";
                // T02: canonical exact parser (see mcp_id.jsx)
                clipGroupId = extractMcpId(gpNote) || params.clipTo;
            } catch (e) { clipGroupId = params.clipTo; }
        } else {
            // Delegate to clip_create for PathItem/CompoundPathItem
            // duplicate_mask=false: mask consumed into group (clean for inline clipTo)
            var clipHandler = OP_HANDLERS["clip_create"];
            if (!clipHandler) {
                return _elementCleanupFailure(createScope,
                    makeError(ErrorCodes.E_EXECUTION || "E001",
                        "clip_create handler not registered (required for clipTo)", "apply"));
            }
            var clipResult = clipHandler({
                mask: params.clipTo,
                contents: [id],
                duplicate_mask: false
            }, [], ctx);
            // Normalize to ensure .ok exists
            if (typeof normalizeHandlerResult === "function") {
                clipResult = normalizeHandlerResult("clip_create", clipResult);
            }
            // At this level the content item is a creation, not a modification.
            // Preserve every delegated move except that one so the borrowed
            // mask remains visible in the canonical effect record without
            // double-classifying the new item.
            var clipData = clipResult.data || {};
            var delegatedMoves = [];
            if (clipData.movedIds instanceof Array) {
                for (var dmi = 0; dmi < clipData.movedIds.length; dmi++) {
                    var delegatedMoveId = clipData.movedIds[dmi];
                    if (delegatedMoveId !== id &&
                            typeof delegatedMoveId === "string" &&
                            delegatedMoveId.length &&
                            delegatedMoves.indexOf(delegatedMoveId) < 0) {
                        delegatedMoves.push(delegatedMoveId);
                    }
                }
            }
            clipData.movedIds = delegatedMoves;
            clipResult.data = clipData;
            if (!clipResult.ok) {
                // The delegated handler keeps its primary error and cleanup
                // evidence; this scope adds only the item it created. Its
                // retained group and borrowed-mask move stay in `data`, where
                // the outer task's canonical reducer can still see them.
                return _elementCleanupFailure(createScope, clipResult);
            }
            delegatedClipResult = clipResult;
            clipGroupId = clipResult.id || null;
        }
    }

    mcpOwnCommit(createScope);
    var resultData = {
        typename: item.typename,
        bounds: preBounds,
        clippedTo: params.clipTo || null,
        clipGroupId: clipGroupId
    };
    var resultWarnings = [];
    if (delegatedClipResult) {
        // The outer operation made both objects. `id` remains the primary
        // element identity for compatibility; `ids` is the exhaustive list
        // consumed by the effect reducer.
        resultData.ids = [id];
        if (clipGroupId && clipGroupId !== id) resultData.ids.push(clipGroupId);
        resultData.movedIds = delegatedClipResult.data.movedIds || [];
        if (typeof delegatedClipResult.data.unnamedMoves === "number") {
            resultData.unnamedMoves = delegatedClipResult.data.unnamedMoves;
        }
        if (delegatedClipResult.warnings instanceof Array) {
            resultWarnings = delegatedClipResult.warnings.slice();
        }
    }
    var createResult = {
        ok: true,
        id: id,
        data: resultData
    };
    if (resultWarnings.length) createResult.warnings = resultWarnings;
    return createResult;
    } catch (createError) {
        return _elementCleanupFailure(createScope,
            makeError(ErrorCodes.R_APPLY_FAILED,
                "element_create failed: " + createError.message, "apply"));
    }
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
        // Each finished subpath is independent, matching the handler's prior
        // partial behavior: if a later path fails, earlier completed paths
        // remain. Only the subpath still under construction is rolled back.
        var pathScope = mcpOwnBegin("element_create_multi:path[" + i + "]");
        try {
        var item = mcpOwnAllocate(pathScope, targetLayer.pathItems.add(), "path");
        item.setEntirePath(flipped.points);
        if (flipped.kind === "bezier" && flipped.handles) {
            for (var bhi = 0; bhi < flipped.points.length; bhi++) {
                var bpp = item.pathPoints[bhi];
                var bh = flipped.handles[bhi] || {};
                var bin = bh.left !== undefined ? bh.left : bh["in"];
                var bout = bh.right !== undefined ? bh.right : bh.out;
                bpp.leftDirection = bin || flipped.points[bhi];
                bpp.rightDirection = bout || flipped.points[bhi];
                bpp.pointType = (bh.pointType || bh.type) === "corner" ?
                    PointType.CORNER : PointType.SMOOTH;
            }
        }
        item.closed = subPath.closed === true;

        // Assign MCP ID inline (confirmed: IDs in creation order)
        var subId = generateUUID();
        stampMcpId(item, subId);
        mcpOwnIdentify(pathScope, item, subId);
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
        mcpOwnCommit(pathScope);
        } catch (pathError) {
            var pathFailure = {
                ok: false,
                data: {
                    created: created,
                    skipped: skipped,
                    failed: skipped + 1,
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
                warnings: warnings,
                error: makeError(ErrorCodes.R_APPLY_FAILED,
                    "element_create_multi failed at path[" + i + "]: " + pathError.message,
                    "apply").error
            };
            return _elementCleanupFailure(pathScope, pathFailure);
        }
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
    // OR03: the batch scope inherits each committed instance, so a fatal
    // failure still cleans clones that individually succeeded. Replaces a
    // hand-rolled list whose per-instance rollback popped the shared array
    // and deleted the previous instance's clone.
    var batchScope = mcpOwnBegin("template:batch");
    // Per-instance identity and measured bounds, for the caller.
    var instanceRecords = [];
    // Removals that failed during rollback, reported rather than swallowed.
    var cleanupFailures = [];
    var ids = [];
    var created = 0;
    var skipped = 0;
    var warnings = [];

    /**
     * The one way out of this function.
     *
     * Every exit has to dispose of the master, close the batch scope, and
     * carry the cleanup record — and the previous shape did none of that
     * uniformly. The master was removed in a `finally`, which runs after a
     * `return` has already evaluated its object, so the disclosure reached
     * the caller on the success path only because that object happened to
     * hold the same arrays. `makeError` builds a different shape entirely,
     * so on a fatal exit the warning and the cleanup failure were written
     * into arrays nothing referenced and then dropped. The three validation
     * returns skipped the scope disposition altogether, leaving an open
     * `template:batch` on the stack for the next scope to inherit.
     *
     * Routing every exit through here is what makes those three cases the
     * same case.
     *
     * @param {Object} result   the handler result being returned
     * @param {boolean} succeeded whether the batch's work stands
     */
    function _closeOut(result, succeeded) {
        if (master) {
            // Disposed through the scope that owns it, so a removal that
            // fails is recorded the same way any other is. Removing it by
            // hand is what let a stranded master hide behind a swallowed
            // catch, and it is why this site needed an audit exception in
            // the allocation gate. There is no exception now.
            mcpOwnDispose(batchScope, master);
            master = null;
        }

        if (succeeded) {
            mcpOwnCommit(batchScope);
        } else {
            mcpOwnCleanup(batchScope);
        }

        // What is still on the page, read from the scope's final records
        // rather than accumulated one push per attempt.
        //
        // Recording each failure as it happened produced two wrong reports.
        // A disposal that failed and was then retried successfully by the
        // scope's cleanup still claimed the artwork remained, because the
        // first push was never revisited. And when both attempts failed, the
        // disposal and the cleanup each pushed an entry, so one stuck master
        // was reported as two stranded items. Events are not state; the
        // records hold the outcome, so the report is derived from them.
        var finalRecords = mcpOwnRecords(batchScope);
        for (var fr = 0; fr < finalRecords.length; fr++) {
            var record = finalRecords[fr];
            if (record.outcome !== "removal_failed") continue;
            cleanupFailures.push({
                stage: record.kind === "master" ? "master" : "batch",
                allocId: record.allocId,
                kind: record.kind,
                mcpId: record.mcpId,
                error: record.cleanupError || null,
                attempts: record.removalAttempts || 1
            });
        }
        if (cleanupFailures.length) {
            // Name what is left. "1 object(s) could not be removed" sends a
            // reader hunting; "the template master" tells them what to look
            // for on the page.
            var kinds = [];
            var tagged = [];
            for (var ci = 0; ci < cleanupFailures.length; ci++) {
                var kind = cleanupFailures[ci].kind || "object";
                var seen = false;
                for (var ki = 0; ki < kinds.length; ki++) {
                    if (kinds[ki] === kind) seen = true;
                }
                if (!seen) kinds.push(kind);
                if (cleanupFailures[ci].mcpId) tagged.push(cleanupFailures[ci].mcpId);
            }
            var note = cleanupFailures.length + " object(s) could not be removed " +
                "and remain on the page (" + kinds.join(", ") + ").";
            // Whether an id-based tool can find it is a fact about the object,
            // not a fixed sentence. Saying "carries no MCP id" over a stamped
            // clone sends the reader hunting by hand for something they could
            // have selected by id.
            if (tagged.length === cleanupFailures.length) {
                note += " They are tagged: " + tagged.join(", ") + ".";
            } else if (tagged.length) {
                note += " " + tagged.length + " are tagged (" + tagged.join(", ") +
                    "); the rest carry no MCP id and must be found by hand.";
            } else {
                note += " They carry no MCP id, so no id-based tool can find them.";
            }
            warnings.push(note);
        }

        // One writer, matching the one reader in the effects reducer. Doing
        // this by hand here is how the two shapes came to disagree about
        // where the record lived.
        mcpSetCleanupFailures(result, cleanupFailures);
        if (warnings.length) {
            result.warnings = (result.warnings || []).concat(warnings);
        }
        return result;
    }

    try {
        // --- Create master item ---
        var type = tmpl.type;
        switch (type) {
            case "ellipse":
                var rx = tmpl.rx || tmpl.r || 5, ry = tmpl.ry || tmpl.r || 5;
                master = targetLayer.pathItems.ellipse(abTop + ry, abLeft - rx, rx * 2, ry * 2);
                mcpOwnAllocate(batchScope, master, "master");
                break;
            case "rect":
                var bw = tmpl.w || 50, bh = tmpl.h || 50;
                master = targetLayer.pathItems.rectangle(abTop, abLeft, bw, bh);
                mcpOwnAllocate(batchScope, master, "master");
                break;
            case "line":
                var lp = tmpl.points;
                if (!lp || lp.length < 2) {
                    return _closeOut(makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
                        "template line needs 2 points", "validate"), false);
                }
                master = targetLayer.pathItems.add();
                mcpOwnAllocate(batchScope, master, "master");
                master.setEntirePath([[abLeft + lp[0][0], abTop - lp[0][1]], [abLeft + lp[1][0], abTop - lp[1][1]]]);
                master.closed = false;
                master.filled = false;
                break;
            case "polyline":
            case "path":
                var pp = tmpl.points;
                if (!pp || pp.length < 2) {
                    return _closeOut(makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
                        "template path needs >=2 points", "validate"), false);
                }
                master = targetLayer.pathItems.add();
                mcpOwnAllocate(batchScope, master, "master");
                _createPathWithHandles(master, pp, abLeft, abTop);
                master.closed = tmpl.closed === true;
                if (!tmpl.closed) master.filled = false;
                break;
            case "polygon":
                var bSides = tmpl.sides || 6;
                var bRadius = tmpl.radius || 50;
                master = targetLayer.pathItems.polygon(abLeft, abTop, bRadius, bSides);
                mcpOwnAllocate(batchScope, master, "master");
                break;
            case "star":
                var bNumPoints = tmpl.numPoints || tmpl.points || 5;
                var bOuterR = tmpl.outerRadius || 50;
                var bInnerR = tmpl.innerRadius || 25;
                master = targetLayer.pathItems.star(abLeft, abTop, bOuterR, bInnerR, bNumPoints);
                mcpOwnAllocate(batchScope, master, "master");
                break;
            default:
                return _closeOut(makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
                    "unknown template type: " + type, "validate"), false);
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
                // A scope per instance: it owns only this clone, so a
                // failure here cannot reach a sibling. duplicate() throwing
                // leaves an empty scope, which cleans up to nothing.
                var instScope = mcpOwnBegin("template:instance[" + i + "]");
                var clone = master.duplicate();
                // Registered the moment it exists, before anything that can
                // throw touches it.
                mcpOwnAllocate(instScope, clone, "clone");

                // Position: absolute artboard-relative coordinates
                if (inst.x !== undefined && inst.y !== undefined) {
                    clone.position = [abLeft + inst.x, abTop - inst.y];
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

                // Assign MCP ID + register in heap (H1 invariant)
                var id = generateUUID();
                stampMcpId(clone, id);
                // Tell the scope which object this is, now that it has an
                // identity. Ownership never depended on the id — that is the
                // point of registering before the stamp — but the records
                // did carry `mcpId: null` for every object ever allocated,
                // because nothing called this. A clone that survived a failed
                // cleanup was then reported as untagged, with advice that no
                // id-based tool could find it, when it was tagged all along.
                mcpOwnIdentify(instScope, clone, id);

                // Name
                if (params.name) {
                    clone.name = params.name + "_" + i;
                }

                // Record what was actually made, per instance, so a caller
                // can see that one landed at a default rather than only an
                // aggregate bound for the whole run.
                var instBounds = null;
                try {
                    var ivb = clone.visibleBounds;
                    instBounds = [ivb[0], ivb[1], ivb[2] - ivb[0],
                                  Math.abs(ivb[3] - ivb[1])];
                } catch (be) {}
                instanceRecords.push({
                    index: i,
                    id: id,
                    typename: clone.typename,
                    bounds: instBounds
                });
                if (instBounds) {
                    // trackBounds works in artboard-relative screen space
                    // (Y-down), while visibleBounds is absolute and Y-up, so
                    // convert before feeding it. Both corners are tracked so
                    // the aggregate spans the artwork rather than the anchor
                    // points: one instance used to collapse it to zero size.
                    var sx = instBounds[0] - abLeft;
                    var sy = abTop - instBounds[1];
                    trackBounds(sx, sy);
                    trackBounds(sx + instBounds[2], sy + instBounds[3]);
                }

                ids.push(id);
                created++;
                // Success: the batch scope inherits it, so a later fatal
                // failure still cleans it.
                mcpOwnCommit(instScope);
            } catch (e) {
                // Non-fatal per-instance error: null placeholder for index
                // alignment, and cleanup scoped to this instance alone.
                // An instance scope is cleaned once and never revisited by
                // the batch, so this record is already final for its objects.
                var instCleanup = mcpOwnCleanup(instScope);
                if (!instCleanup.ok) {
                    for (var fi = 0; fi < instCleanup.failed.length; fi++) {
                        var failure = instCleanup.failed[fi];
                        cleanupFailures.push({
                            stage: "instance",
                            index: i,
                            allocId: failure.allocId,
                            kind: failure.kind,
                            mcpId: failure.mcpId,
                            error: failure.error
                        });
                    }
                }
                ids.push(null);
                skipped++;
                warnings.push("instances[" + i + "] error: " + e.message);
            }
        }
    } catch (e) {
        // Fatal error. The primary failure is preserved as the error; what
        // cleanup could not undo rides alongside it in details, rather than
        // being written into arrays this return does not carry.
        var failure = _closeOut(
            makeError(ErrorCodes.R_APPLY_FAILED,
                      "template instancing failed: " + e.message, "apply"),
            false);
        if (cleanupFailures.length) {
            failure.error.message += " (cleanup incomplete: " +
                cleanupFailures.length + " item(s) remain on the page)";
        }
        return failure;
    }

    var boundsResult = null;
    if (bMinX !== Infinity) {
        boundsResult = [bMinX, bMinY, bMaxX - bMinX, bMaxY - bMinY];
    }

    return _closeOut({
        ok: true,
        data: {
            created: created,
            skipped: skipped,
            failed: skipped,
            ids: ids,
            bounds: boundsResult,
            // Per-instance identity and measured bounds, in request order,
            // matching what the heterogeneous items path returns.
            items: instanceRecords,
            mode: "template"
        }
    }, true);
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

    // ── Mode validation ──────────────────────────────────────────────
    // Allowed modes (mutually exclusive):
    //   1. items[]              — heterogeneous batch
    //   2. template + instances — explicit positions
    //   3. template + array    — generated positions
    // Disallowed:
    //   - array without template
    //   - template without instances AND without array
    //   - items combined with template/instances/array

    var hasTemplate = !!params.template;
    var hasInstances = params.instances && params.instances.length;
    var hasItems = params.items && params.items.length;
    var hasArray = !!params.array;

    // Guard: items combined with template-family params
    if (hasItems && (hasTemplate || hasInstances || hasArray)) {
        return makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
            "cannot combine 'items' with 'template'/'instances'/'array'", "validate");
    }

    // Guard: array without template
    if (hasArray && !hasTemplate) {
        return makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
            "'array' requires 'template'", "validate");
    }

    // Guard: template without instances and without array
    if (hasTemplate && !hasInstances && !hasArray) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM,
            "'instances' or 'array' required with 'template'", "validate");
    }

    // ── Array expansion: generate instances[] from array params ──────
    if (hasTemplate && hasArray && !hasInstances) {
        var arr = params.array;
        var count = arr.count;

        // Validate count is a finite integer >= 0
        if (typeof count !== "number" || !isFinite(count) || Math.floor(count) !== count) {
            return makeError(ErrorCodes.V_INVALID_PARAM_VALUE,
                "array.count must be a finite integer", "validate");
        }
        if (count < 0) {
            return makeError(ErrorCodes.V_INVALID_PARAM_VALUE,
                "array.count must be >= 0", "validate");
        }
        if (count > 10000) {
            return makeError(ErrorCodes.V_INVALID_PARAM_VALUE,
                "array.count exceeds maximum (10000)", "validate");
        }

        // Early return: count=0 → empty result, skip template creation
        if (count === 0) {
            return {
                ok: true,
                data: { created: 0, skipped: 0, failed: 0, ids: [], bounds: null, mode: "array" },
                warnings: []
            };
        }

        var cols = (arr.cols != null) ? arr.cols : count;

        // Validate cols is a finite integer >= 1
        if (typeof cols !== "number" || !isFinite(cols) || Math.floor(cols) !== cols) {
            return makeError(ErrorCodes.V_INVALID_PARAM_VALUE,
                "array.cols must be a finite integer", "validate");
        }
        if (cols < 1) {
            return makeError(ErrorCodes.V_INVALID_PARAM_VALUE,
                "array.cols must be >= 1", "validate");
        }

        var sx = arr.startX || 0;
        var sy = arr.startY || 0;
        var dx = arr.spacingX || 0;
        var dy = arr.spacingY || 0;

        var generated = [];
        for (var ai = 0; ai < count; ai++) {
            __mcp_check();
            var col = ai % cols;
            var row = Math.floor(ai / cols);
            generated.push({ x: sx + col * dx, y: sy + row * dy });
        }
        params.instances = generated;
    }

    // === Template mode: duplicate() instancing ===
    if (hasTemplate) {
        // Validate template type upfront (contract-level check)
        var _VALID_TEMPLATE_TYPES = { ellipse: 1, rect: 1, line: 1, polyline: 1, path: 1, polygon: 1, star: 1 };
        if (!params.template.type || !_VALID_TEMPLATE_TYPES[params.template.type]) {
            return makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
                "invalid template.type: '" + (params.template.type || "(missing)") +
                "'. Valid: ellipse, rect, line, polyline, path, polygon, star", "validate");
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
    var createdItems = [];
    var created = 0;
    var skipped = 0;
    var warnings = [];
    var cleanupFailures = [];

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
        var itemScope = null;
        // Bounds are provisional until every post-creation step succeeds.
        // Publishing them straight into the aggregate here made rolled-back
        // geometry survive in the report after its artwork was removed.
        var pendingBounds = [];
        try {
            switch (type) {
                case "line":
                    var lp = spec.points;
                    if (!lp || lp.length < 2) { skipped++; warnings.push("items[" + i + "] skipped: line needs 2 points"); continue; }
                    itemScope = mcpOwnBegin("element_create_batch:item[" + i + "]");
                    item = mcpOwnAllocate(itemScope, targetLayer.pathItems.add(), "line");
                    item.setEntirePath([[abLeft + lp[0][0], abTop - lp[0][1]], [abLeft + lp[1][0], abTop - lp[1][1]]]);
                    item.closed = false;
                    item.filled = false;
                    pendingBounds.push([lp[0][0], lp[0][1]]);
                    pendingBounds.push([lp[1][0], lp[1][1]]);
                    break;

                case "ellipse":
                    var cx = spec.cx || 0, cy = spec.cy || 0;
                    var rx = spec.rx || spec.r || 5, ry = spec.ry || spec.r || 5;
                    itemScope = mcpOwnBegin("element_create_batch:item[" + i + "]");
                    item = mcpOwnAllocate(itemScope,
                        targetLayer.pathItems.ellipse(abTop - cy + ry, abLeft + cx - rx, rx * 2, ry * 2), "ellipse");
                    pendingBounds.push([cx - rx, cy - ry]);
                    pendingBounds.push([cx + rx, cy + ry]);
                    break;

                case "rect":
                    var bx = spec.x || 0, by = spec.y || 0;
                    var bw = spec.w || 50, bh = spec.h || 50;
                    itemScope = mcpOwnBegin("element_create_batch:item[" + i + "]");
                    item = mcpOwnAllocate(itemScope,
                        targetLayer.pathItems.rectangle(abTop - by, abLeft + bx, bw, bh), "rect");
                    pendingBounds.push([bx, by]);
                    pendingBounds.push([bx + bw, by + bh]);
                    break;

                case "polyline":
                case "path":
                    var pp = spec.points;
                    if (!pp || pp.length < 2) { skipped++; warnings.push("items[" + i + "] skipped: path needs >=2 points"); continue; }
                    if (pp.length > 8000) { skipped++; warnings.push("items[" + i + "] skipped: >8000 points"); continue; }
                    itemScope = mcpOwnBegin("element_create_batch:item[" + i + "]");
                    item = mcpOwnAllocate(itemScope, targetLayer.pathItems.add(), "path");
                    _createPathWithHandles(item, pp, abLeft, abTop);
                    // Track bounds using anchor coordinates
                    for (var pi = 0; pi < pp.length; pi++) {
                        var bpt = (pp[pi].length === 3 && pp[pi][0] instanceof Array) ? pp[pi][0] : pp[pi];
                        pendingBounds.push([bpt[0], bpt[1]]);
                    }
                    item.closed = spec.closed === true;
                    if (!spec.closed) item.filled = false;
                    break;

                default:
                    skipped++;
                    warnings.push("items[" + i + "] skipped: unknown type '" + type + "'");
                    continue;
            }

            // Assign ID + register in heap (H1 invariant)
            var id = generateUUID();
            stampMcpId(item, id);
            mcpOwnIdentify(itemScope, item, id);

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

            // Record what was actually made, per item. The aggregate bounds
            // below cannot show that one shape landed at a default size, so a
            // caller who mis-spelled a geometry field had nothing to compare
            // against their intent.
            var actual = null;
            try {
                var vb = item.visibleBounds;
                actual = [vb[0], vb[1], vb[2] - vb[0], Math.abs(vb[3] - vb[1])];
            } catch (be) {}
            mcpOwnCommit(itemScope);
            // Publish identity, per-item data and aggregate geometry together,
            // only after the item is no longer eligible for rollback.
            for (var pbi = 0; pbi < pendingBounds.length; pbi++) {
                trackBounds(pendingBounds[pbi][0], pendingBounds[pbi][1]);
            }
            createdItems.push({
                index: i,
                id: id,
                typename: item.typename,
                bounds: actual
            });
            ids.push(id);
            created++;
        } catch (e) {
            skipped++;
            warnings.push("items[" + i + "] error: " + e.message);
            if (itemScope) {
                var itemFailure = makeError(ErrorCodes.R_APPLY_FAILED,
                    "element_create_batch item[" + i + "] failed: " + e.message,
                    "apply");
                _elementCleanupFailure(itemScope, itemFailure);
                var itemCleanupFailures = mcpCleanupFailures(itemFailure);
                for (var cfi = 0; cfi < itemCleanupFailures.length; cfi++) {
                    cleanupFailures.push(itemCleanupFailures[cfi]);
                }
            }
        }
    }

    // Compute bounds result
    var boundsResult = null;
    if (bMinX !== Infinity) {
        boundsResult = [bMinX, bMinY, bMaxX - bMinX, bMaxY - bMinY];
    }

    var batchResult = {
        ok: true,
        data: {
            created: created,
            skipped: skipped,
            failed: skipped,
            ids: ids,
            bounds: boundsResult,
            // Per-item identity and measured bounds, in request order.
            items: createdItems
        },
        warnings: warnings
    };
    mcpSetCleanupFailures(batchResult, cleanupFailures);
    return batchResult;
});

// ==================== Element Modify ====================

registerOpHandler("element_modify", function (params, targets, ctx) {
    if (targets.length === 0) {
        return makeError(ErrorCodes.V_NO_SELECTION, "No targets to modify", "apply");
    }

    // Validate the complete destination before any property assignment.
    // Keep the existing top-level-only lookup contract; never choose the first
    // of duplicate names or silently accept a sublayer.
    var targetLayer = null;
    if (params.layer !== undefined) {
        var matches = 0;
        for (var li = 0; li < ctx.doc.layers.length; li++) {
            if (ctx.doc.layers[li].name === params.layer) {
                targetLayer = ctx.doc.layers[li];
                matches++;
            }
        }
        if (matches !== 1 || targetLayer.locked || targetLayer.visible === false) {
            var invalidLayer = makeError(ErrorCodes.V_INVALID_PARAM_VALUE,
                "Destination must be one editable, visible top-level layer: " + params.layer +
                ". Use a unique top-level name; sublayers are unsupported.", "validate",
                null, {writesAttempted: false});
            return invalidLayer;
        }
    }

    var modifiedIds = [];
    var unnamedModified = 0;
    var failures = [];
    var modified = 0;
    var warnings = [];
    var firstModifiedItem = null;
    var partial = 0;

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];
        var itemId = mcpTargetIdentity(item);
        var touched = false;
        var property = null;

        try {
            // Position (artboard-relative)
            if (params.x !== undefined) { property = "x"; item.left = _artboardLeft(ctx.doc) + params.x; touched = true; }
            if (params.y !== undefined) { property = "y"; item.top = _artboardTop(ctx.doc) - params.y; touched = true; }

            // Size
            if (params.width !== undefined) { property = "width"; item.width = params.width; touched = true; }
            if (params.height !== undefined) { property = "height"; item.height = params.height; touched = true; }

            // Rotation
            if (params.rotation !== undefined) {
                property = "rotation";
                item.rotate(params.rotation);
                touched = true;
            }

            // Scale
            if (params.scale !== undefined) {
                var s = params.scale * 100;
                property = "scale";
                item.resize(s, s);
                touched = true;
            }

            // Fill
            if (params.fill) {
                var fillColor = new RGBColor();
                fillColor.red = params.fill.r || 0;
                fillColor.green = params.fill.g || 0;
                fillColor.blue = params.fill.b || 0;
                property = "fillColor";
                item.fillColor = fillColor;
                touched = true;
                property = "filled";
                item.filled = true;
                touched = true;
            } else if (params.fill === null || params.fill === false) {
                property = "filled";
                item.filled = false;
                touched = true;
            }

            // Stroke
            if (params.stroke) {
                var strokeColor = new RGBColor();
                strokeColor.red = params.stroke.r || 0;
                strokeColor.green = params.stroke.g || 0;
                strokeColor.blue = params.stroke.b || 0;
                property = "strokeColor";
                item.strokeColor = strokeColor;
                touched = true;
                property = "stroked";
                item.stroked = true;
                touched = true;
                if (params.stroke.width) {
                    property = "strokeWidth";
                    item.strokeWidth = params.stroke.width;
                    touched = true;
                }
            } else if (params.stroke === null || params.stroke === false) {
                property = "stroked";
                item.stroked = false;
                touched = true;
            }

            // Opacity
            if (params.opacity !== undefined) {
                var opVal = params.opacity;
                if (opVal < 0) opVal = 0;
                if (opVal > 100) opVal = 100;
                property = "opacity";
                item.opacity = opVal;
                touched = true;
            }

            // Name
            if (params.name !== undefined) {
                property = "name";
                item.name = params.name;
                touched = true;
            }

            // Layer move
            if (params.layer !== undefined) {
                property = "layer";
                item.move(targetLayer, ElementPlacement.PLACEATEND);
                touched = true;
            }

            modified++;
            if (!firstModifiedItem) firstModifiedItem = item;
        } catch (e) {
            warnings.push("Failed to modify item " + i + ": " + e.message);
            if (touched) partial++;
            failures.push({index: i, id: itemId, property: property,
                message: String(e.message || e), effectsUnknown: true});
        }
        if (touched) {
            if (itemId) modifiedIds.push(itemId);
            else unnamedModified++;
        }
    }

    // Position echo: bounds-based position in user coords (artboard-relative, y-down)
    // Note: width/height are axis-aligned bounding box dimensions, not original geometry
    var posEcho = null;
    if (firstModifiedItem) {
        try {
            var abT = _artboardTop(ctx.doc), abL = _artboardLeft(ctx.doc);
            posEcho = {
                x: Math.round((firstModifiedItem.left - abL) * 100) / 100,
                y: Math.round((abT - firstModifiedItem.top) * 100) / 100,
                width: Math.round(firstModifiedItem.width * 100) / 100,
                height: Math.round(firstModifiedItem.height * 100) / 100
            };
        } catch (echoError) {
            warnings.push("Position readback unavailable: " + echoError.message);
        }
    }
    var modifyOk = modified === targets.length;
    return {
        ok: modifyOk,
        data: { modified: modified, total: targets.length, failed: targets.length - modified, partial: partial, position: posEcho,
            modifiedIds: modifiedIds, unnamedModified: unnamedModified, failures: failures },
        warnings: warnings,
        error: modifyOk ? null : makeError(
            ErrorCodes.R_APPLY_FAILED,
            "Completed " + modified + " of " + targets.length + " targets; earlier writes may remain",
            "apply"
        ).error
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

    var deleteOk = deleted === targets.length;
    return {
        ok: deleteOk,
        data: { deleted: deleted, total: targets.length, failed: targets.length - deleted },
        warnings: warnings,
        error: deleteOk ? null : makeError(
            ErrorCodes.R_APPLY_FAILED,
            "Deleted " + deleted + " of " + targets.length + " targets",
            "apply"
        ).error
    };
});

// ==================== Element Replace (Verified Swap) ====================

/**
 * Replace a single element with new content while preserving known effects.
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
    if (!oldId && typeof mcpIssueHandle === "function") {
        try {
            var oldHandle = mcpIssueHandle(oldItem);
            if (oldHandle.ok) oldId = oldHandle.record.handle;
        } catch (e) { }
    }

    // Validate before creating the sandbox. These were formerly early returns
    // from inside the ownership window, each with its own hand-written remove.
    var type = params.type || "rect";
    var validTypes = {
        rect: 1, ellipse: 1, line: 1, polygon: 1, star: 1,
        roundedRect: 1, text: 1, path: 1, polyline: 1
    };
    if (!validTypes[type]) {
        return makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
            "Unknown element type for replace: " + type, "apply");
    }
    var pathPoints = params.points;
    if ((type === "path" || type === "polyline") &&
            (!pathPoints || pathPoints.length < 2)) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM,
            "Path requires >= 2 points", "apply");
    }

    // The sandbox owns its children while they are being constructed. Once the
    // replacement leaves it, direct ownership resumes until the original is
    // successfully removed. That deletion is the irreversible hand-off.
    var replaceScope = mcpOwnBegin("element_replace");
    var sandbox = null;
    var newItem = null;
    var newId = null;
    var oldRemoved = false;
    var oldUnlocked = false;

    try {
        sandbox = mcpOwnAllocate(replaceScope,
            oldLayer.groupItems.add(), "replaceSandbox");
        sandbox.name = "__mcp_replace_sandbox__";

        // --- Build replacement inside sandbox using element_create params ---
        newId = params.id || generateUUID();
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
                newItem = mcpOwnAllocate(replaceScope,
                    sandbox.pathItems.rectangle(aiTop, aiLeft, width, height), "rect");
                mcpOwnAbsorb(replaceScope, [newItem], sandbox);
                break;
            case "ellipse":
                newItem = mcpOwnAllocate(replaceScope,
                    sandbox.pathItems.ellipse(aiTop, aiLeft, width, height), "ellipse");
                mcpOwnAbsorb(replaceScope, [newItem], sandbox);
                break;
            case "line":
                // Accept x1/y1 as aliases for start point (x/y)
                var rlx1 = params.x1 !== undefined ? params.x1 : x;
                var rly1 = params.y1 !== undefined ? params.y1 : y;
                var rlx2 = params.x2 !== undefined ? params.x2 : rlx1 + width;
                var rly2 = params.y2 !== undefined ? params.y2 : rly1;
                newItem = mcpOwnAllocate(replaceScope,
                    sandbox.pathItems.add(), "line");
                mcpOwnAbsorb(replaceScope, [newItem], sandbox);
                newItem.setEntirePath([[abLeft + rlx1, abTop - rly1], [abLeft + rlx2, abTop - rly2]]);
                newItem.closed = false;
                newItem.filled = false;
                break;
            case "polygon":
                var sides = params.sides || 6;
                var radius = params.radius || 50;
                newItem = mcpOwnAllocate(replaceScope,
                    sandbox.pathItems.polygon(aiLeft, aiTop, radius, sides), "polygon");
                mcpOwnAbsorb(replaceScope, [newItem], sandbox);
                break;
            case "star":
                var points = params.numPoints || params.points || 5;
                var outerRadius = params.outerRadius || 50;
                var innerRadius = params.innerRadius || 25;
                newItem = mcpOwnAllocate(replaceScope,
                    sandbox.pathItems.star(aiLeft, aiTop, outerRadius, innerRadius, points), "star");
                mcpOwnAbsorb(replaceScope, [newItem], sandbox);
                break;
            case "roundedRect":
                var cornerRadius = params.cornerRadius || 10;
                newItem = mcpOwnAllocate(replaceScope,
                    sandbox.pathItems.roundedRectangle(
                        aiTop, aiLeft, width, height, cornerRadius, cornerRadius
                    ), "roundedRect");
                mcpOwnAbsorb(replaceScope, [newItem], sandbox);
                break;
            case "text":
                newItem = mcpOwnAllocate(replaceScope,
                    sandbox.textFrames.add(), "text");
                mcpOwnAbsorb(replaceScope, [newItem], sandbox);
                newItem.contents = params.contents || params.text || "";
                newItem.position = [aiLeft, aiTop];
                if (params.fontSize) newItem.textRange.characterAttributes.size = params.fontSize;
                if (params.fontName) {
                    try {
                        newItem.textRange.characterAttributes.textFont =
                            app.textFonts.getByName(params.fontName);
                    } catch (e) { /* font not found, keep default */ }
                }
                break;
            case "path":
            case "polyline":
                newItem = mcpOwnAllocate(replaceScope,
                    sandbox.pathItems.add(), "path");
                mcpOwnAbsorb(replaceScope, [newItem], sandbox);
                _createPathWithHandles(newItem, pathPoints, abLeft, abTop);
                newItem.closed = (type === "path") ? (params.closed !== false) : (params.closed === true);
                break;
        }

        // Assign MCP ID + register in heap (H1 invariant)
        stampMcpId(newItem, newId);
        mcpOwnIdentify(replaceScope, newItem, newId);

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
        // Ownership changes before the move so either a thrown-before-move or
        // a thrown-after-move host behavior still leaves the child removable.
        mcpOwnDetach(replaceScope, newItem, sandbox);
        // PLACEBEFORE/PLACEAFTER require an artwork anchor in Illustrator;
        // a Layer is a container and rejects that placement form. Anchor the
        // replacement to the original, whose removal then leaves it in the
        // original's z-order slot.
        newItem.move(oldItem, ElementPlacement.PLACEAFTER);
        mcpOwnReconcileDetach(replaceScope, newItem);

        // 3. Inherit visibility from old item
        newItem.hidden = !oldVisible;

        // 4. Dispose the empty sandbox before crossing the irreversible point.
        var sandboxDisposal = mcpOwnDispose(replaceScope, sandbox);
        if (!sandboxDisposal.ok) {
            throw new Error("Could not remove replacement sandbox: " +
                sandboxDisposal.failed[0].error);
        }
        sandbox = null;

        // 5. Unlock only for the removal itself, then remove. Tombstoning is
        // after DOM success: a failed removal must remain resolvable.
        if (oldLocked) {
            oldItem.locked = false;
            oldUnlocked = true;
        }
        oldItem.remove();
        oldRemoved = true;
        mcpOwnRelease(replaceScope);
        if (oldId && typeof heapTombstone === "function") {
            heapTombstone(oldId);
        }

        // 6. Apply locked state from old item. The replacement has been
        // released already, so a late failure cannot delete it after the
        // original is gone.
        if (oldLocked) {
            newItem.locked = true;
        }

        return {
            ok: true,
            id: newId,
            data: {
                typename: newItem.typename,
                bounds: [newItem.left, newItem.top, newItem.width, newItem.height],
                oldId: oldId,
                ids: [newId],
                deletedIds: oldId ? [oldId] : []
            }
        };

    } catch (e) {
        // If removal already happened, the verified replacement is useful
        // artwork and must survive. Report the exact partial effects.
        if (oldRemoved) {
            return {
                ok: false,
                id: newId,
                data: {
                    ids: newId ? [newId] : [],
                    oldId: oldId,
                    deletedIds: oldId ? [oldId] : [],
                    partial: true
                },
                warnings: ["Replacement exists after a later cleanup failure"],
                error: makeError(ErrorCodes.R_APPLY_FAILED,
                    "element_replace partially completed: " + e.message, "apply").error
            };
        }
        // Failure before the irreversible hand-off: final-state cleanup owns
        // the report, and the original remains. If it had been unlocked for a
        // failed removal, restoring that borrowed state is reported too.
        var replaceFailure = makeError(ErrorCodes.R_APPLY_FAILED,
            "element_replace failed: " + e.message, "apply");
        _elementReplaceRollback(replaceScope, replaceFailure, newItem);
        _elementReplaceRestoreLock(oldItem, oldUnlocked, oldId, replaceFailure);
        return replaceFailure;
    }
});
