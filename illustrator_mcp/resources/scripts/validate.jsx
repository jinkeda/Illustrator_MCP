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


/** Bounded publication measurements. Missing host evidence stays unknown. */
function publicationPreflightScan(doc, options) {
    var p = options.publication, index = options.artboard_index;
    if (index === null || index === undefined) index = doc.artboards.getActiveArtboardIndex();
    if (index < 0 || index >= doc.artboards.length) throw new Error("Artboard index is out of range");
    var ab = doc.artboards[index].artboardRect;
    var widthMm = (ab[2]-ab[0])*25.4/72;
    var scale = p.output_width_mm === undefined ? 1 : p.output_width_mm/widthMm;
    var result = {artboard_index:index, scope:"artboard", artboard:{bounds:ab, space:"illustrator_native_y_up", units:"pt", width_mm:widthMm, height_mm:(ab[1]-ab[3])*25.4/72},
        output_scale:scale, checks:{}, issues:[], omissions:[], summary:{total_items:0, issues_found:0},
        coverage:{complete:true, scanned:0, nested_work:0, nested_cap:Math.min(options.scan_max_items*4,40000)}};
    function check(name, threshold) {
        result.checks[name] = {status:threshold === undefined ? "not_requested" : "pass", minimum:null, threshold:threshold === undefined ? null : threshold, samples:[]};
    }
    check("font",p.min_font_pt); check("stroke",p.min_stroke_pt); check("image",p.min_image_ppi);
    check("color_mode",p.expected_color_mode); check("font_embedding",0);
    result.checks.font_embedding.status = "unknown";
    result.checks.font_embedding.informational = true;
    result.omissions.push("Font embedding eligibility and font-file glyph coverage are not exposed by this scan.");
    function unknown(name, reason) {
        if (result.checks[name].status === "pass") result.checks[name].status = "unknown";
        if (result.omissions.length < 20) result.omissions.push(reason);
    }
    function measured(name, value, itemIndex, extra) {
        var c = result.checks[name];
        if (!isFinite(value) || value < 0) { unknown(name,"Invalid " + name + " measurement"); return; }
        if (c.minimum === null || value < c.minimum) c.minimum = value;
        if (c.samples.length < 20) c.samples.push({item_index:itemIndex, value:value, detail:extra || null});
        if (value < c.threshold) c.status = "fail";
    }
    var started = new Date().getTime(), exhausted = false;
    function budget(nested) {
        if (nested) result.coverage.nested_work++;
        if (new Date().getTime()-started >= options.scan_budget_ms || result.coverage.nested_work > result.coverage.nested_cap) {
            exhausted = true; return false;
        }
        return true;
    }
    // Check inherited visibility without an unbounded parent walk. The layer
    // chain is checked separately because some host collections expose layer
    // membership even when their parent chain is unavailable.
    function inheritedHidden(item) {
        try {
            var ancestor = item.parent;
            while (ancestor && ancestor.typename !== "Document") {
                if (!budget(true)) return null;
                if (ancestor.typename === "Layer") {
                    if (!ancestor.visible) return true;
                } else if (ancestor.hidden) return true;
                ancestor = ancestor.parent;
            }
            ancestor = item.layer;
            while (ancestor && ancestor.typename !== "Document") {
                if (!budget(true)) return null;
                if (!ancestor.visible) return true;
                ancestor = ancestor.parent;
            }
            return false;
        } catch (visibilityError) { return null; }
    }
    if (p.expected_color_mode !== undefined) {
        try {
            var mode = String(doc.documentColorSpace);
            mode = mode.indexOf("CMYK") >= 0 ? "CMYK" : mode.indexOf("RGB") >= 0 ? "RGB" : null;
            result.checks.color_mode.measured = mode;
            result.checks.color_mode.status = mode === null ? "unknown" : mode === p.expected_color_mode ? "pass" : "fail";
        } catch (colorError) { unknown("color_mode","Document colour mode unavailable"); }
    }
    for (var i = 0; i < doc.pageItems.length; i++) {
        if (i >= options.scan_max_items || !budget(false)) { exhausted = true; break; }
        result.coverage.scanned++;
        var item = doc.pageItems[i], b;
        try {
            if (item.hidden || item.guides) continue;
            var hidden = inheritedHidden(item);
            if (hidden === true) continue;
            if (hidden === null) {
                result.coverage.complete = false;
                unknown("font", "Ancestor visibility could not be established");
                unknown("stroke", "Ancestor visibility could not be established");
                unknown("image", "Ancestor visibility could not be established");
                continue;
            }
            b = item.visibleBounds;
            if (b[2] < ab[0] || b[0] > ab[2] || b[3] > ab[1] || b[1] < ab[3]) continue;
            result.summary.total_items++;
            // These containers/foreign appearances are not recursively inspected.
            // A readable sibling cannot establish coverage of their contents.
            if (item.typename !== "TextFrame" && item.typename !== "PathItem" && item.typename !== "RasterItem") {
                unknown("font", "Uninspected " + item.typename + " contents may contain text");
                unknown("image", "Uninspected " + item.typename + " contents may contain images");
            }
            if (item.typename === "TextFrame" && p.min_font_pt !== undefined) {
                for (var ci = 0; ci < item.characters.length; ci++) {
                    if (!budget(true)) break;
                    var attrs = item.characters[ci].characterAttributes;
                    var normal = false;
                    try { normal = attrs.baselinePosition === FontBaselineOption.NORMALBASELINE && attrs.openTypePosition === FontOpenTypePositionOption.OPENTYPEDEFAULT; } catch (nativeError) { }
                    if (!normal) { unknown("font","Native/OpenType script positioning has unknown rendered size"); continue; }
                    var vertical = attrs.verticalScale;
                    var matrix = item.matrix;
                    if (typeof vertical !== "number" || !isFinite(vertical) || vertical <= 0 || !matrix ||
                        !isFinite(matrix.mValueA) || !isFinite(matrix.mValueB) || !isFinite(matrix.mValueC) || !isFinite(matrix.mValueD) ||
                        Math.abs(matrix.mValueA*matrix.mValueA+matrix.mValueB*matrix.mValueB-1) > 0.000001 ||
                        Math.abs(matrix.mValueC*matrix.mValueC+matrix.mValueD*matrix.mValueD-1) > 0.000001 ||
                        Math.abs(matrix.mValueA*matrix.mValueC+matrix.mValueB*matrix.mValueD) > 0.000001) {
                        unknown("font","Missing metrics or nonuniform/transformed text requires rendered review"); continue;
                    }
                    measured("font",attrs.size*vertical/100*scale,i,{nominal_pt:attrs.size,vertical_scale_pct:vertical,baseline_shift_pt:attrs.baselineShift});
                }
            }
            if (item.typename !== "PathItem" && p.min_stroke_pt !== undefined)
                unknown("stroke","Non-path stroke appearances are not inspectable by the nominal path-width check");
            if (item.typename === "PathItem" && p.min_stroke_pt !== undefined) {
                if (!budget(true)) break;
                if (item.stroked) {
                    measured("stroke",item.strokeWidth*scale,i,{nominal:true});
                    unknown("stroke","Brush, appearance and nonuniform-transform widths are not certified by nominal strokeWidth");
                }
            }
            if ((item.typename === "RasterItem" || item.typename === "PlacedItem") && p.min_image_ppi !== undefined)
                unknown("image","Intrinsic raster pixel dimensions and linked-file metadata unavailable; PPI cannot be established");
        } catch (itemError) {
            unknown("font","Item properties unavailable"); unknown("stroke","Item properties unavailable"); unknown("image","Item properties unavailable");
        }
        if (exhausted) break;
    }
    if (exhausted) {
        result.coverage.complete = false;
        unknown("font","Scan budget exhausted"); unknown("stroke","Scan budget exhausted"); unknown("image","Scan budget exhausted");
        result.nextStep = "Narrow scope or raise scan_max_items/scan_budget_ms";
    }
    if (p.min_font_pt !== undefined && result.checks.font.minimum === null)
        unknown("font","No live text size established; outlined text has no inspectable font size");
    result.coverage.elapsed_ms = new Date().getTime()-started;
    for (var key in result.checks) {
        if (result.checks[key].status === "fail") result.issues.push({type:key,message:key+" fails the supplied publication threshold"});
    }
    result.summary.issues_found = result.issues.length;
    return result;
}
