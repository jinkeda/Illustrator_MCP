/**
 * geo_boolean.jsx — ExtendScript geometry extraction and reconstruction helpers.
 *
 * Provides two entry-point functions for the path_boolean pipeline:
 *   1. extractPathGeometry(itemRefs) — reads path data from PathItems
 *   2. reconstructRegions(regions, layerName, style) — creates PathItem/CompoundPathItem
 *
 * Style helpers:
 *   - _extractColorCanonical(colorObj) — canonical color serializer with `model` discriminator
 *   - _extractStyle(item)              — full style snapshot (fill, stroke, opacity)
 *   - _clamp(v, lo, hi)               — numeric clamping utility
 *
 * Coordinate convention:
 *   All coordinates are artboard-relative, Y-down (SOC convention).
 *   Transform: x_soc = anchor[0] - abLeft, y_soc = abTop - anchor[1]
 *   Reverse:   x_ai  = abLeft + x_soc,     y_ai  = abTop - y_soc
 *
 * @requires ops_core (for generateUUID, makeError, ErrorCodes)
 * @requires ownership (scope-based cleanup of unfinished artwork)
 * @version 1.3.0
 */

// ── Dependency guard ───────────────────────────────────────────────
if (typeof generateUUID !== "function") {
    throw new Error("geometry.jsx requires ops_core.jsx (generateUUID)");
}

// ── Coordinate helpers ─────────────────────────────────────────────

function _geoArtboardRect() {
    var doc = app.activeDocument;
    var abIdx = doc.artboards.getActiveArtboardIndex();
    var ab = doc.artboards[abIdx].artboardRect; // [left, top, right, bottom]
    return { left: ab[0], top: ab[1], right: ab[2], bottom: ab[3] };
}

/**
 * Convert Illustrator absolute coords → SOC artboard-relative Y-down.
 * Single transform point — all conversions go through here.
 */
function _toSOC(x, y, ab) {
    return [x - ab.left, ab.top - y];
}

/**
 * Convert SOC artboard-relative Y-down → Illustrator absolute coords.
 * Single transform point — all conversions go through here.
 */
function _fromSOC(x, y, ab) {
    return [ab.left + x, ab.top - y];
}

// ── Style extraction ───────────────────────────────────────────────

/**
 * Clamp a number to [lo, hi].
 */
function _clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

/**
 * Serialize a single Illustrator color object to a canonical descriptor.
 * Every returned object has a `model` discriminator key.
 *
 * @param {Color} colorObj - Illustrator color object
 * @returns {Object|null} Canonical color descriptor, or null only for truly unknown types
 */
function _extractColorCanonical(colorObj) {
    if (!colorObj) return null;
    var tn = "";
    try { tn = colorObj.typename || ""; } catch (e) { return null; }

    switch (tn) {
        case "RGBColor":
            return {
                model: "RGB",
                r: Math.round(colorObj.red),
                g: Math.round(colorObj.green),
                b: Math.round(colorObj.blue)
            };
        case "CMYKColor":
            return {
                model: "CMYK",
                c: _clamp(Math.round(colorObj.cyan * 10) / 10, 0, 100),
                m: _clamp(Math.round(colorObj.magenta * 10) / 10, 0, 100),
                y: _clamp(Math.round(colorObj.yellow * 10) / 10, 0, 100),
                k: _clamp(Math.round(colorObj.black * 10) / 10, 0, 100)
            };
        case "GrayColor":
            return {
                model: "Gray",
                gray: _clamp(Math.round(colorObj.gray * 10) / 10, 0, 100)
            };
        case "SpotColor": {
            var desc = {
                model: "Spot",
                name: colorObj.spot ? colorObj.spot.name : "unknown",
                tint: Math.round(colorObj.tint * 10) / 10
            };
            // Serialize underlying spot color for round-trip capability
            try {
                if (colorObj.spot && colorObj.spot.color) {
                    desc.base = _extractColorCanonical(colorObj.spot.color);
                }
            } catch (e) { /* spot.color may not be readable */ }
            return desc;
        }
        case "GradientColor":
            return { model: "Gradient", supported: false };
        case "PatternColor":
            return { model: "Pattern", supported: false };
        default:
            return null;
    }
}

function _extractStyle(item) {
    var style = {
        filled: item.filled,
        stroked: item.stroked,
        fillColor: null,
        strokeColor: null,
        strokeWidth: item.strokeWidth !== undefined ? item.strokeWidth : 0,
        opacity: item.opacity !== undefined ? item.opacity : 100
    };

    if (item.filled && item.fillColor) {
        try {
            style.fillColor = _extractColorCanonical(item.fillColor);
        } catch (e) { /* ignore read error */ }
    }

    if (item.stroked && item.strokeColor) {
        try {
            style.strokeColor = _extractColorCanonical(item.strokeColor);
        } catch (e) { /* ignore read error */ }
    }

    return style;
}

// ── Appearance check ───────────────────────────────────────────────

function _checkAppearance(item) {
    var warnings = [];
    if (item.stroked && item.strokeWidth > 0) {
        warnings.push("Item has stroke (width=" + item.strokeWidth + "pt). Boolean operates on fill geometry only.");
    }
    // Check for complex appearance (multiple fills/strokes via Appearance panel)
    try {
        if (item.typename === "PathItem" && item.pathEffect) {
            warnings.push("Item has path effects. Boolean result may not match visual appearance.");
        }
    } catch (e) { /* not available */ }
    return warnings;
}

// ── Geometry extraction ────────────────────────────────────────────

function _geoContextSnapshot(doc) {
    var abIdx = doc.artboards.getActiveArtboardIndex();
    var ab = doc.artboards[abIdx].artboardRect;
    var token = null;
    if (typeof mcpDocBind === "function") {
        try { token = mcpDocBind({ label: "path_boolean" }).token; } catch (e) { token = null; }
    }
    return {
        documentToken: token,
        documentName: doc.name || "",
        activeArtboardIndex: abIdx,
        artboardRect: [ab[0], ab[1], ab[2], ab[3]]
    };
}

function _geoContourFromPath(item, ab) {
    var pp = item.pathPoints;
    var pointObjs = [];
    var hasHandles = false;
    for (var pi = 0; pi < pp.length; pi++) {
        var pt = pp[pi];
        var anchor = pt.anchor;
        var left = pt.leftDirection;
        var right = pt.rightDirection;
        var anchorSOC = _toSOC(anchor[0], anchor[1], ab);
        var leftSOC = _toSOC(left[0], left[1], ab);
        var rightSOC = _toSOC(right[0], right[1], ab);
        var ptType = (pt.pointType === PointType.SMOOTH) ? "smooth" : "corner";
        if (Math.abs(left[0] - anchor[0]) > 0.01 ||
                Math.abs(left[1] - anchor[1]) > 0.01 ||
                Math.abs(right[0] - anchor[0]) > 0.01 ||
                Math.abs(right[1] - anchor[1]) > 0.01) {
            hasHandles = true;
        }
        pointObjs.push({
            anchor: anchorSOC,
            left: leftSOC,
            right: rightSOC,
            pointType: ptType
        });
    }
    return { points: pointObjs, hasHandles: hasHandles, closed: item.closed !== false };
}

function _geoSignature(pathRecord) {
    return JSON.stringify({
        schema: pathRecord.schema,
        itemType: pathRecord.itemType,
        contours: pathRecord.contours,
        fillRule: pathRecord.fillRule,
        style: pathRecord.style,
        mcpId: pathRecord.mcpId,
        name: pathRecord.name
    });
}

/**
 * Extract path geometry from exact MCP-ID or selector operands.
 *
 * @param {Array} mcpIds - Ordered IDs/selectors, each resolving one path
 * @returns {string} JSON with paths, context, preconditions and operandHandles
 *   (captured handles for every operand when any selector is supplied).
 */
function extractPathGeometry(mcpIds) {
    var doc = app.activeDocument;
    var ab = _geoArtboardRect();
    var context = _geoContextSnapshot(doc);
    var paths = [];
    var warnings = [];
    var exact = false, handles = [], seen = [];
    for (var oi = 0; oi < mcpIds.length; oi++) {
        if (typeof mcpIds[oi] !== "string") exact = true;
    }

    for (var mi = 0; mi < mcpIds.length; mi++) {
        var mcpId = mcpIds[mi];

        // Find item by exact MCP ID token (T02).  A prefix match here would
        // silently feed the wrong artwork into the boolean.
        var lookup;
        if (typeof mcpId === "string") {
            lookup = findItemsByMcpId(doc, mcpId);
        } else {
            try {
                var resolved = collectTargets(doc, mcpId);
                if (resolved.length !== 1) throw new Error("Each boolean selector must resolve exactly one operand; got " + resolved.length);
                lookup = {items: resolved, duplicate: false};
            } catch (operandError) {
                return JSON.stringify({error:true,errorCode:"BOOLEAN_OPERAND_INVALID",
                    message:operandError.message || String(operandError)});
            }
        }

        if (lookup.duplicate) {
            return JSON.stringify({
                error: true,
                errorCode: "ITEM_ID_AMBIGUOUS",
                message: "MCP ID '" + mcpId + "' matches " + lookup.items.length +
                    " items. Resolve the duplicate before running a boolean."
            });
        }

        if (lookup.items.length === 0) {
            return JSON.stringify({
                error: true,
                errorCode: "ITEM_NOT_FOUND",
                message: "Could not find item with MCP ID: " + mcpId
            });
        }

        var item = lookup.items[0];
        for (var si = 0; si < seen.length; si++) {
            var ancestor = item, overlaps = false;
            while (ancestor && ancestor !== doc) {
                if (ancestor === seen[si]) { overlaps = true; break; }
                ancestor = ancestor.parent;
            }
            ancestor = seen[si];
            while (!overlaps && ancestor && ancestor !== doc) {
                if (ancestor === item) { overlaps = true; break; }
                ancestor = ancestor.parent;
            }
            if (overlaps) return JSON.stringify({error:true,errorCode:"BOOLEAN_OPERAND_OVERLAP",
                message:"Boolean operands must be distinct, non-overlapping artwork identities"});
        }
        seen.push(item);
        if (exact) {
            var issued = mcpIssueHandle(item, context.documentToken);
            if (!issued.ok) return JSON.stringify({error:true,errorCode:"BOOLEAN_OPERAND_INVALID",message:issued.message});
            mcpId = issued.record.handle;
            handles.push(mcpId);
        }

        // T20: both simple and compound paths are valid filled geometry.
        if (item.typename !== "PathItem" && item.typename !== "CompoundPathItem") {
            return JSON.stringify({
                error: true,
                errorCode: "INVALID_ITEM_TYPE",
                message: "path_boolean requires PathItem or CompoundPathItem, got " + item.typename + " (id: " + mcpId + ")"
            });
        }

        // Ancestor state also prevents a safe replacement/deletion.
        var locked = item.locked, hidden = item.hidden, owner = item.parent;
        while (owner && owner !== doc) {
            if (owner.locked) locked = true;
            if (owner.hidden || (owner.typename === "Layer" && owner.visible === false)) hidden = true;
            owner = owner.parent;
        }
        if (locked) {
            return JSON.stringify({
                error: true,
                errorCode: "ITEM_LOCKED",
                message: "Item is locked (id: " + mcpId + ")"
            });
        }
        if (hidden) {
            return JSON.stringify({
                error: true,
                errorCode: "ITEM_HIDDEN",
                message: "Item is hidden (id: " + mcpId + ")"
            });
        }

        // Check appearance and collect warnings
        var appWarnings = _checkAppearance(item);
        for (var w = 0; w < appWarnings.length; w++) {
            warnings.push(appWarnings[w]);
        }

        var contours = [];
        if (item.typename === "PathItem") {
            contours.push(_geoContourFromPath(item, ab));
        } else {
            for (var cpi = 0; cpi < item.pathItems.length; cpi++) {
                contours.push(_geoContourFromPath(item.pathItems[cpi], ab));
            }
        }
        var record = {
            schema: "mcp.geometry.v1",
            itemType: item.typename,
            contours: contours,
            // Compatibility fields for callers written before compound support.
            points: contours.length ? contours[0].points : [],
            hasHandles: contours.length ? contours[0].hasHandles : false,
            closed: contours.length ? contours[0].closed : true,
            fillRule: (item.typename === "CompoundPathItem" && item.evenodd === true) ? "evenodd" : "nonzero",
            style: _extractStyle(item),
            mcpId: mcpId,
            name: item.name || ""
        };
        record.precondition = { signature: _geoSignature(record) };
        paths.push(record);
    }

    return JSON.stringify({
        paths: paths,
        warnings: warnings,
        context: context,
        operandHandles: exact ? handles : null,
        preconditions: (function () {
            var out = [];
            for (var i = 0; i < paths.length; i++) out.push(paths[i].precondition);
            return out;
        }())
    });
}

// ── Geometry reconstruction ────────────────────────────────────────

/**
 * Reconstruct boolean result as PathItem(s) or CompoundPathItem(s).
 *
 * @param {Object} params - { regions: [...], layer: string, style: {...}, name: string }
 *   regions: [{ outer: [[x,y],...], holes: [[[x,y],...], ...] }, ...]
 *   style: { filled, stroked, fillColor, strokeColor, strokeWidth, opacity }
 * @returns {string} JSON with { ids: [...], bounds: [...], itemTypes: [...] }
 */
/**
 * The holes of a region: always an array, empty when there are none.
 *
 * OR13 audit. Validation asked `region.holes instanceof Array` while
 * reconstruction asked whether it was truthy and then read `.length`, so the
 * two accepted different inputs. An array-like `{0: [...], length: 1}` was
 * skipped by validation and used by reconstruction, and a non-finite
 * coordinate reached `setEntirePath` through the boundary that exists to
 * stop exactly that.
 *
 * Both now go through here. Anything that is not an array yields no holes,
 * and validation rejects a supplied non-array outright, so the two cannot
 * disagree about what a region contains.
 */
function _geoHolesOf(region) {
    return (region && region.holes instanceof Array) ? region.holes : [];
}

/**
 * Reject a contour the host would accept without complaint.
 *
 * OR13. Illustrator rejects some bad geometry loudly and absorbs the rest in
 * silence, and the silent kind is what reaches a document. Measured: an empty
 * contour raises "You cannot delete all path-points of a path" and a
 * 20,000-point contour raises "Illegal Argument", but a contour containing
 * `NaN` raises nothing at all. `_fromSOC` manufactures exactly that from a
 * short point — `[10]` has no `[1]`, the arithmetic yields `NaN` — so a path
 * with `NaN` coordinates is created, stamped with an id, and reported as a
 * successful region. Ownership scopes cannot help: nothing threw, so there is
 * nothing to roll back.
 *
 * This is the only place the rule lives. `reconstructRegions` is the boundary
 * every caller crosses — `illustrator_path_boolean` reaches it through Python,
 * and a raw script reaches it directly — so validating here covers both
 * without the rule being written twice.
 *
 * Deliberately narrow. The claim is only that a coordinate which is not a
 * finite number never reaches the host; this is not general geometry
 * validation, and it says nothing about whether a shape is sensible.
 *
 * @returns {string|null} what is wrong, or null when the contour is buildable
 */
function _geoValidateContour(points, label) {
    if (!(points instanceof Array)) {
        return label + " is not an array of points";
    }
    if (points.length === 0) {
        return label + " has no points";
    }
    for (var i = 0; i < points.length; i++) {
        var point = points[i];
        // Exactly two. `length < 2` also accepted `[10, 5, 123]` and silently
        // dropped the third component, which is not the pair the contract
        // promises — and a caller sending three numbers has misunderstood
        // something worth telling them about.
        if (!(point instanceof Array) || point.length !== 2) {
            return label + " point " + i + " is not an [x, y] pair";
        }
        for (var axis = 0; axis < 2; axis++) {
            var value = point[axis];
            if (typeof value !== "number" || !isFinite(value)) {
                return label + " point " + i + (axis === 0 ? " x" : " y") +
                    " is not a finite number (" + String(value) + ")";
            }
        }
    }
    return null;
}

/**
 * Check every contour of every region before anything is created.
 *
 * Up front rather than per region: a request carrying one malformed contour
 * should leave the document untouched, not half-built. A contour that is
 * merely too dense still fails the way it always did, from the host, part
 * way through — that is a different thing from geometry we can see is wrong
 * before we start.
 *
 * @returns {string|null}
 */
function _geoValidateRegions(regions) {
    if (!(regions instanceof Array)) return "regions is not an array";
    for (var ri = 0; ri < regions.length; ri++) {
        var region = regions[ri] || {};
        var problem = _geoValidateContour(region.outer, "regions[" + ri + "].outer");
        if (problem) return problem;
        // Absent or null means "no holes". Anything else supplied must be a
        // real array: an array-like object used to pass validation untouched
        // and then be built from.
        if (region.holes !== undefined && region.holes !== null) {
            if (!(region.holes instanceof Array)) {
                return "regions[" + ri + "].holes is not an array of contours";
            }
            for (var hi = 0; hi < region.holes.length; hi++) {
                problem = _geoValidateContour(
                    region.holes[hi], "regions[" + ri + "].holes[" + hi + "]");
                if (problem) return problem;
            }
        }
    }
    return null;
}

function reconstructRegions(params) {
    var doc = app.activeDocument;
    var ab = _geoArtboardRect();
    var regions = params.regions;
    var styleDef = params.style || {};
    var layerName = params.layer || null;
    var itemName = params.name || null;

    // Resolve target layer
    var targetLayer = doc.activeLayer;
    if (layerName) {
        try {
            targetLayer = doc.layers.getByName(layerName);
        } catch (e) {
            return JSON.stringify({
                error: true,
                errorCode: "LAYER_NOT_FOUND",
                message: "Layer not found: " + layerName
            });
        }
    }

    // Before any creation, so a malformed request leaves the page untouched.
    var geometryProblem = _geoValidateRegions(regions);
    if (geometryProblem) {
        return JSON.stringify({
            error: true,
            errorCode: "INVALID_GEOMETRY",
            message: "Refusing to build geometry Illustrator would accept " +
                "without complaint: " + geometryProblem
        });
    }

    var createdIds = [];
    var createdTypes = [];
    var globalBounds = [Infinity, Infinity, -Infinity, -Infinity]; // [l, t, r, b] in SOC
    // Removals that failed during rollback, reported rather than swallowed.
    var cleanupFailures = [];

    /**
     * Create a single PathItem from SOC-coordinate points.
     */
    function _createPath(socPoints, closed, parentLayer, scope) {
        var aiPoints = [];
        for (var i = 0; i < socPoints.length; i++) {
            var ai = _fromSOC(socPoints[i][0], socPoints[i][1], ab);
            aiPoints.push(ai);
        }

        // pathItems.add() returns an EMPTY path, so it exists in the document
        // before the call that can fail. A dense region makes setEntirePath
        // throw, and the empty path was left behind — untagged, because the
        // id is stamped afterwards, so nothing could find it.
        //
        // This used to remove the path itself, in a catch that swallowed a
        // removal failure: `try { path.remove(); } catch (ex) { }`. When both
        // calls threw, the path stayed on the page and nothing recorded it,
        // because it belonged to no scope until this function had already
        // returned. Registering here closes the window the comment above
        // describes, and hands a failed removal to the region scope, which
        // reports it instead of dropping it.
        var path = parentLayer.pathItems.add();
        mcpOwnAllocate(scope, path, "path");
        path.setEntirePath(aiPoints);
        path.closed = closed !== false;
        return path;
    }

    /**
     * Apply style definition to a path item.
     */
    function _applyStyle(item, sDef) {
        if (sDef.filled !== undefined) item.filled = sDef.filled;
        if (sDef.stroked !== undefined) item.stroked = sDef.stroked;

        if (sDef.fillColor) {
            var fc;
            if (sDef.fillColor.model === "CMYK") {
                fc = new CMYKColor();
                fc.cyan = sDef.fillColor.c || 0;
                fc.magenta = sDef.fillColor.m || 0;
                fc.yellow = sDef.fillColor.y || 0;
                fc.black = sDef.fillColor.k || 0;
            } else {
                fc = new RGBColor();
                fc.red = sDef.fillColor.r || 0;
                fc.green = sDef.fillColor.g || 0;
                fc.blue = sDef.fillColor.b || 0;
            }
            item.fillColor = fc;
        }

        if (sDef.strokeColor) {
            var sc;
            if (sDef.strokeColor.model === "CMYK") {
                sc = new CMYKColor();
                sc.cyan = sDef.strokeColor.c || 0;
                sc.magenta = sDef.strokeColor.m || 0;
                sc.yellow = sDef.strokeColor.y || 0;
                sc.black = sDef.strokeColor.k || 0;
            } else {
                sc = new RGBColor();
                sc.red = sDef.strokeColor.r || 0;
                sc.green = sDef.strokeColor.g || 0;
                sc.blue = sDef.strokeColor.b || 0;
            }
            item.strokeColor = sc;
        }

        if (sDef.strokeWidth !== undefined) item.strokeWidth = sDef.strokeWidth;
        if (sDef.opacity !== undefined) item.opacity = sDef.opacity;
    }

    /**
     * Track bounds in SOC coordinates.
     */
    function _trackBounds(socPoints) {
        for (var b = 0; b < socPoints.length; b++) {
            var px = socPoints[b][0], py = socPoints[b][1];
            if (px < globalBounds[0]) globalBounds[0] = px;
            if (py < globalBounds[1]) globalBounds[1] = py;
            if (px > globalBounds[2]) globalBounds[2] = px;
            if (py > globalBounds[3]) globalBounds[3] = py;
        }
    }

    // Process each region
    for (var ri = 0; ri < regions.length; ri++) {
        var region = regions[ri];
        // The guarded commit supplies IDs up front so effects remain knowable
        // even if Illustrator throws part-way through reconstruction.
        var id = region.id || generateUUID();

        _trackBounds(region.outer);

        // OR03: one scope per region, so a failure part-way through a
        // compound does not leave the earlier paths behind, and committed
        // regions keep their artwork. The scope replaces a hand-rolled list
        // that could not report a removal that itself failed.
        var regionScope = mcpOwnBegin("boolean:region[" + ri + "]");

        try {
        // The same predicate validation used, so the two cannot accept
        // different inputs.
        var regionHoles = _geoHolesOf(region);
        if (regionHoles.length === 0) {
            // Simple region: just a PathItem
            var simplePath = _createPath(region.outer, true, targetLayer,
                                         regionScope);
            simplePath.note = "@mcp:id=" + id;
            mcpOwnIdentify(regionScope, simplePath, id);
            if (itemName) simplePath.name = itemName + (regions.length > 1 ? "_" + ri : "");
            _applyStyle(simplePath, styleDef);
            createdIds.push(id);
            createdTypes.push("PathItem");
        } else {
            // Region with holes: create CompoundPathItem
            // Create outer path first
            var outerPath = _createPath(region.outer, true, targetLayer,
                                        regionScope);
            outerPath.selected = true;

            // Create hole paths
            var holePaths = [];
            for (var hi = 0; hi < regionHoles.length; hi++) {
                _trackBounds(regionHoles[hi]);
                var holePath = _createPath(regionHoles[hi], true, targetLayer,
                                           regionScope);
                holePath.selected = true;
                holePaths.push(holePath);
            }

            // Select all paths and make compound path
            doc.selection = null;
            outerPath.selected = true;
            for (var si = 0; si < holePaths.length; si++) {
                holePaths[si].selected = true;
            }

            // Execute compound path creation via menu command
            app.executeMenuCommand("compoundPath");

            // The compound path should now be selected
            var compound = doc.selection[0];
            if (compound) {
                // The menu command consumed the outer path and the holes into
                // this container, so rolling those back would strip its
                // children and leave a zero-child CompoundPathItem: invisible
                // on the canvas, present in the layer tree, and therefore
                // surviving exactly the check a person would make. From here
                // the container is the thing to remove.
                // The menu command absorbed the paths; from here the
                // container is the thing to remove.
                mcpOwnReplace(regionScope, holePaths.concat([outerPath]),
                              compound, "compound");
                try { compound.evenodd = params.fillRule === "evenodd"; } catch (e) { }
                compound.note = "@mcp:id=" + id;
                mcpOwnIdentify(regionScope, compound, id);
                if (itemName) compound.name = itemName + (regions.length > 1 ? "_" + ri : "");
                _applyStyle(compound, styleDef);
                createdIds.push(id);
                createdTypes.push("CompoundPathItem");
            } else {
                // Fallback: compound path creation failed, keep individual paths
                outerPath.note = "@mcp:id=" + id;
                mcpOwnIdentify(regionScope, outerPath, id);
                if (itemName) outerPath.name = itemName;
                _applyStyle(outerPath, styleDef);
                createdIds.push(id);
                createdTypes.push("PathItem (compound failed)");
                for (var fhi = 0; fhi < holePaths.length; fhi++) {
                    _applyStyle(holePaths[fhi], styleDef);
                }
            }

            // Clear selection
            doc.selection = null;
        }
        } catch (regionError) {
            // Roll this region back. Earlier regions are committed and keep
            // their ids, which is what the caller was told about them.
            var regionCleanup = mcpOwnCleanup(regionScope);
            try { doc.selection = null; } catch (ex) { }
            if (!regionCleanup.ok) {
                // A removal that itself failed is disclosed rather than
                // absorbed: artwork is still on the page and saying the
                // rollback was clean would be the same lie one level up.
                cleanupFailures.push({
                    region: ri,
                    failed: regionCleanup.failed
                });
                // The disclosure has to travel with the error. Cleanup runs
                // only when a region throws, and the returned JSON below is
                // reached only when none did, so a cleanup failure recorded
                // solely in that return can never be read by anyone. Riding
                // on the error is the only route out of here.
                try {
                    regionError.mcpCleanupFailures = cleanupFailures;
                } catch (attachError) { }
            }
            throw regionError;
        }
        mcpOwnCommit(regionScope);
    }

    return JSON.stringify({
        cleanupFailures: cleanupFailures,
        ids: createdIds,
        itemTypes: createdTypes,
        bounds: globalBounds,
        regionCount: regions.length
    });
}

/**
 * Delete items by MCP IDs. Called only after verified reconstruction.
 *
 * Reports per-ID outcomes so the caller can distinguish complete deletion
 * from a partial one (T01) — a bare count cannot say which artwork survived.
 *
 * @param {string[]} mcpIds - Array of MCP IDs to delete
 * @returns {string} JSON with { deleted, deletedIds, failedIds, notFoundIds, warnings }
 */
function deleteByMcpIds(mcpIds) {
    var doc = app.activeDocument;
    var deletedIds = [];
    var failedIds = [];
    var notFoundIds = [];
    var warnings = [];

    var ambiguousIds = [];

    for (var di = 0; di < mcpIds.length; di++) {
        var mcpId = mcpIds[di];

        // Exact whole-token match (T02).  The previous prefix test meant a
        // request to delete "A" could remove an item tagged "AB".
        var lookup = findItemsByMcpId(doc, mcpId);

        if (lookup.duplicate) {
            // Refuse to guess which duplicate the caller meant.
            ambiguousIds.push(mcpId);
            warnings.push(
                "Refused to delete '" + mcpId + "': matches " +
                lookup.items.length + " items."
            );
            continue;
        }

        if (lookup.items.length === 0) {
            notFoundIds.push(mcpId);
            warnings.push("Item not found for deletion: " + mcpId);
            continue;
        }

        try {
            lookup.items[0].remove();
            deletedIds.push(mcpId);
        } catch (e) {
            failedIds.push(mcpId);
            warnings.push("Failed to delete item " + mcpId + ": " + e.message);
        }
    }

    return JSON.stringify({
        deleted: deletedIds.length,
        deletedIds: deletedIds,
        failedIds: failedIds,
        notFoundIds: notFoundIds,
        ambiguousIds: ambiguousIds,
        warnings: warnings
    });
}

function _geoSameArray(a, b) {
    return JSON.stringify(a) === JSON.stringify(b);
}

function _geoKnownCreated(doc, ids) {
    var known = [];
    for (var i = 0; i < ids.length; i++) {
        var lookup = findItemsByMcpId(doc, ids[i]);
        if (!lookup.duplicate && lookup.items.length === 1) known.push(ids[i]);
    }
    return known;
}

function _geoVerifyReplacement(doc, id, region) {
    var lookup = findItemsByMcpId(doc, id);
    if (lookup.duplicate || lookup.items.length !== 1) {
        return { ok: false, message: "Replacement identity is missing or ambiguous: " + id };
    }
    var item = lookup.items[0];
    // The third reader of a region's holes, through the same predicate as the
    // other two. Verification deciding "this needed a compound" differently
    // from the code that built it is the same divergence one level on.
    var verifyHoles = _geoHolesOf(region);
    var needsCompound = verifyHoles.length > 0;
    if (needsCompound && item.typename !== "CompoundPathItem") {
        return { ok: false, message: "Replacement " + id + " lost its compound holes" };
    }
    if (!needsCompound && item.typename !== "PathItem") {
        return { ok: false, message: "Replacement " + id + " has unexpected type " + item.typename };
    }
    if (needsCompound && item.pathItems.length !== verifyHoles.length + 1) {
        return { ok: false, message: "Replacement " + id + " has an unexpected contour count" };
    }
    if (!needsCompound && item.pathPoints.length !== region.outer.length) {
        return { ok: false, message: "Replacement " + id + " has an unexpected point count" };
    }
    return { ok: true, itemType: item.typename };
}

/**
 * Guarded boolean commit (T17).
 *
 * Revalidates every extracted input and the exact document/artboard context
 * before the first write. Replacements are then built, freshly resolved and
 * verified before originals are removed. One eval prevents another managed
 * request from entering between those steps; the explicit effects remain the
 * source of truth because an eval is not an Illustrator transaction.
 */
function commitBooleanRegions(params) {
    var doc = app.activeDocument;
    var exactHandles = params.operandHandles || null;
    var ids = exactHandles || params.originalIds || [];
    var expected = params.preconditions || [];
    var regions = params.regions || [];
    var expectedCreated = [];
    var effects = { created: [], modified: [], deleted: [], unidentified: 0, complete: true };
    var originals = {
        requested: ids.slice(), deleteRequested: params.deleteOriginals === true,
        status: "retained", deletedIds: []
    };

    // All guards run before reconstruction or deletion.
    var currentContext = _geoContextSnapshot(doc);
    var wantedContext = params.context || {};
    if ((wantedContext.documentToken && currentContext.documentToken !== wantedContext.documentToken) ||
            currentContext.activeArtboardIndex !== wantedContext.activeArtboardIndex ||
            !_geoSameArray(currentContext.artboardRect, wantedContext.artboardRect)) {
        return JSON.stringify({
            error: true, errorCode: "BOOLEAN_CONTEXT_CHANGED", phase: "precondition",
            message: "Document or artboard context changed after boolean extraction",
            originals: originals, effects: effects, atomic: false
        });
    }

    var operands = ids;
    if (exactHandles) {
        operands = [];
        for (var hi = 0; hi < ids.length; hi++) operands.push({type:"handle",handles:[ids[hi]]});
    }
    var freshRaw = extractPathGeometry(operands);
    var fresh = JSON.parse(freshRaw);
    if (fresh.error) {
        fresh.phase = "precondition";
        fresh.originals = originals;
        fresh.effects = effects;
        fresh.atomic = false;
        return JSON.stringify(fresh);
    }
    if (fresh.paths.length !== expected.length) {
        return JSON.stringify({
            error: true, errorCode: "BOOLEAN_INPUT_CHANGED", phase: "precondition",
            message: "Boolean input count changed after extraction",
            originals: originals, effects: effects, atomic: false
        });
    }
    for (var pi = 0; pi < fresh.paths.length; pi++) {
        if (!expected[pi] || fresh.paths[pi].precondition.signature !== expected[pi].signature) {
            return JSON.stringify({
                error: true, errorCode: "BOOLEAN_INPUT_CHANGED", phase: "precondition",
                message: "Boolean input geometry, style, or identity changed: " + ids[pi],
                changedId: ids[pi], originals: originals, effects: effects, atomic: false
            });
        }
    }

    for (var ri = 0; ri < regions.length; ri++) {
        expectedCreated.push(regions[ri].id);
    }

    var reconstruction = { ids: [], itemTypes: [], regionCount: 0 };
    if (regions.length > 0) {
        try {
            reconstruction = JSON.parse(reconstructRegions({
                regions: regions,
                style: params.style || {},
                layer: params.layer || null,
                name: params.name || null,
                fillRule: params.fillRule || "nonzero"
            }));
        } catch (reconstructError) {
            effects.created = _geoKnownCreated(doc, expectedCreated);
            effects.complete = false;
            var rollbackFailures = reconstructError.mcpCleanupFailures || [];
            var failureNote = reconstructError.message || String(reconstructError);
            if (rollbackFailures.length) {
                // Artwork the rollback could not remove is still on the page.
                // Reporting only the original error would describe a clean
                // failure that did not happen.
                failureNote += " (rollback incomplete: " + rollbackFailures.length +
                    " region(s) left artwork behind)";
            }
            return JSON.stringify({
                error: true, errorCode: "BOOLEAN_RECONSTRUCT_FAILED", phase: "reconstruct",
                message: failureNote, cleanupFailures: rollbackFailures,
                ids: effects.created, originals: originals, effects: effects, atomic: false
            });
        }
        effects.created = _geoKnownCreated(doc, expectedCreated);
        if (reconstruction.error || effects.created.length !== regions.length) {
            effects.complete = reconstruction.error ? false : effects.complete;
            return JSON.stringify({
                error: true, errorCode: reconstruction.errorCode || "BOOLEAN_RECONSTRUCT_FAILED",
                phase: "reconstruct",
                message: reconstruction.message || "Not every replacement was created",
                ids: effects.created, originals: originals, effects: effects, atomic: false
            });
        }
        for (var vi = 0; vi < regions.length; vi++) {
            var verified = _geoVerifyReplacement(doc, expectedCreated[vi], regions[vi]);
            if (!verified.ok) {
                return JSON.stringify({
                    error: true, errorCode: "BOOLEAN_REPLACEMENT_UNVERIFIED", phase: "verify",
                    message: verified.message, ids: effects.created,
                    originals: originals, effects: effects, atomic: false
                });
            }
        }
    }

    if (params.deleteOriginals === true) {
        var deletion;
        if (exactHandles) {
            deletion = {deletedIds:[],failedIds:[],notFoundIds:[],ambiguousIds:[],survivingIds:[],warnings:[]};
            for (var di = 0; di < ids.length; di++) {
                var resolvedOriginal = mcpResolveHandle(ids[di], doc);
                if (!resolvedOriginal.ok) {
                    deletion.notFoundIds.push(ids[di]);
                    deletion.warnings.push("Original handle unavailable for deletion: " + ids[di]);
                    continue;
                }
                try {
                    resolvedOriginal.item.remove();
                    deletion.deletedIds.push(ids[di]);
                } catch (deleteError) {
                    deletion.failedIds.push(ids[di]);
                    if (mcpResolveHandle(ids[di], doc).ok) deletion.survivingIds.push(ids[di]);
                    deletion.warnings.push("Failed to delete original handle " + ids[di] + ": " + deleteError.message);
                }
            }
        } else deletion = JSON.parse(deleteByMcpIds(ids));
        originals.deletedIds = deletion.deletedIds || [];
        originals.failedIds = deletion.failedIds || [];
        originals.notFoundIds = deletion.notFoundIds || [];
        originals.ambiguousIds = deletion.ambiguousIds || [];
        originals.status = originals.deletedIds.length === ids.length ? "deleted" :
            (originals.deletedIds.length ? "partial" : "retained");
        originals.warnings = deletion.warnings || [];
        if (exactHandles) originals.survivingIds = deletion.survivingIds;
        effects.deleted = originals.deletedIds.slice();
        effects.complete = originals.status === "deleted";
    }

    var deletionIncomplete = params.deleteOriginals === true && originals.status !== "deleted";
    var commitStatus = deletionIncomplete ?
        (effects.created.length || effects.deleted.length ? "partial" : "failed") : "succeeded";
    return JSON.stringify({
        error: deletionIncomplete,
        errorCode: deletionIncomplete ? "BOOLEAN_DELETE_INCOMPLETE" : null,
        phase: deletionIncomplete ? "delete" : "complete",
        ids: effects.created,
        itemTypes: reconstruction.itemTypes || [],
        regionCount: regions.length,
        originals: originals,
        effects: effects,
        status: commitStatus,
        atomic: false,
        message: deletionIncomplete ?
            "Required original deletion was incomplete; verified replacements were retained" : "Boolean commit completed"
    });
}
