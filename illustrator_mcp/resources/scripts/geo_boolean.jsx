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
 * @version 1.1.0
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
        strokeWidth: item.strokeWidth || 0,
        opacity: item.opacity || 100
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

/**
 * Extract path geometry from items identified by MCP IDs.
 *
 * @param {string[]} mcpIds - Array of MCP item IDs
 * @returns {string} JSON with { paths: [...], warnings: [...] }
 */
function extractPathGeometry(mcpIds) {
    var doc = app.activeDocument;
    var ab = _geoArtboardRect();
    var paths = [];
    var warnings = [];

    for (var mi = 0; mi < mcpIds.length; mi++) {
        var mcpId = mcpIds[mi];

        // Find item by MCP ID — scan all page items
        var item = null;
        var allItems = doc.pageItems;
        for (var ai = 0; ai < allItems.length; ai++) {
            var it = allItems[ai];
            if (it.note && it.note.indexOf("@mcp:id=" + mcpId) >= 0) {
                item = it;
                break;
            }
        }

        if (!item) {
            return JSON.stringify({
                error: true,
                errorCode: "ITEM_NOT_FOUND",
                message: "Could not find item with MCP ID: " + mcpId
            });
        }

        // Validate: must be PathItem
        if (item.typename !== "PathItem") {
            return JSON.stringify({
                error: true,
                errorCode: "INVALID_ITEM_TYPE",
                message: "path_boolean requires PathItem, got " + item.typename + " (id: " + mcpId + ")"
            });
        }

        // Check locked/hidden
        if (item.locked) {
            return JSON.stringify({
                error: true,
                errorCode: "ITEM_LOCKED",
                message: "Item is locked (id: " + mcpId + ")"
            });
        }
        if (item.hidden) {
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

        // Extract geometry — canonical per-point format (8C)
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

            // pointType: explicit comparison, never toString()
            var ptType = (pt.pointType === PointType.SMOOTH) ? "smooth" : "corner";

            // Check if handles differ from anchor (i.e., it's a curve)
            var dx1 = Math.abs(left[0] - anchor[0]);
            var dy1 = Math.abs(left[1] - anchor[1]);
            var dx2 = Math.abs(right[0] - anchor[0]);
            var dy2 = Math.abs(right[1] - anchor[1]);
            if (dx1 > 0.01 || dy1 > 0.01 || dx2 > 0.01 || dy2 > 0.01) {
                hasHandles = true;
            }

            pointObjs.push({
                anchor: anchorSOC,
                left: leftSOC,
                right: rightSOC,
                pointType: ptType
            });
        }

        // Extract style for transfer
        var style = _extractStyle(item);

        paths.push({
            schema: "mcp.geometry.v1",
            points: pointObjs,
            hasHandles: hasHandles,
            closed: item.closed,
            style: style,
            mcpId: mcpId,
            name: item.name || ""
        });
    }

    return JSON.stringify({
        error: false,
        paths: paths,
        warnings: warnings
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

    var createdIds = [];
    var createdTypes = [];
    var globalBounds = [Infinity, Infinity, -Infinity, -Infinity]; // [l, t, r, b] in SOC

    /**
     * Create a single PathItem from SOC-coordinate points.
     */
    function _createPath(socPoints, closed, parentLayer) {
        var aiPoints = [];
        for (var i = 0; i < socPoints.length; i++) {
            var ai = _fromSOC(socPoints[i][0], socPoints[i][1], ab);
            aiPoints.push(ai);
        }

        var path = parentLayer.pathItems.add();
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
        var id = generateUUID();

        _trackBounds(region.outer);

        if (!region.holes || region.holes.length === 0) {
            // Simple region: just a PathItem
            var simplePath = _createPath(region.outer, true, targetLayer);
            simplePath.note = "@mcp:id=" + id;
            if (itemName) simplePath.name = itemName + (regions.length > 1 ? "_" + ri : "");
            _applyStyle(simplePath, styleDef);
            createdIds.push(id);
            createdTypes.push("PathItem");
        } else {
            // Region with holes: create CompoundPathItem
            // Create outer path first
            var outerPath = _createPath(region.outer, true, targetLayer);
            outerPath.selected = true;

            // Create hole paths
            var holePaths = [];
            for (var hi = 0; hi < region.holes.length; hi++) {
                _trackBounds(region.holes[hi]);
                var holePath = _createPath(region.holes[hi], true, targetLayer);
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
                compound.note = "@mcp:id=" + id;
                if (itemName) compound.name = itemName + (regions.length > 1 ? "_" + ri : "");
                _applyStyle(compound, styleDef);
                createdIds.push(id);
                createdTypes.push("CompoundPathItem");
            } else {
                // Fallback: compound path creation failed, keep individual paths
                outerPath.note = "@mcp:id=" + id;
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
    }

    return JSON.stringify({
        error: false,
        ids: createdIds,
        itemTypes: createdTypes,
        bounds: globalBounds,
        regionCount: regions.length
    });
}

/**
 * Delete items by MCP IDs. Called only after successful reconstruction.
 *
 * @param {string[]} mcpIds - Array of MCP IDs to delete
 * @returns {string} JSON with { deleted: number, warnings: [...] }
 */
function deleteByMcpIds(mcpIds) {
    var doc = app.activeDocument;
    var deleted = 0;
    var warnings = [];

    for (var di = 0; di < mcpIds.length; di++) {
        var mcpId = mcpIds[di];
        var found = false;

        // Scan page items (reverse to avoid index shifting)
        var allItems = doc.pageItems;
        for (var ai = allItems.length - 1; ai >= 0; ai--) {
            var it = allItems[ai];
            if (it.note && it.note.indexOf("@mcp:id=" + mcpId) >= 0) {
                try {
                    it.remove();
                    deleted++;
                    found = true;
                } catch (e) {
                    warnings.push("Failed to delete item " + mcpId + ": " + e.message);
                }
                break;
            }
        }

        if (!found) {
            warnings.push("Item not found for deletion: " + mcpId);
        }
    }

    return JSON.stringify({
        error: false,
        deleted: deleted,
        warnings: warnings
    });
}
