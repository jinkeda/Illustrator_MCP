/**
 * ops_measure.jsx - Measurement and Assertion Operations
 * Part of Illustrator MCP SOC Framework
 * 
 * Provides handlers for:
 * - assert_count: Assert number of items
 * - assert_bounds: Assert item within bounds
 * - assert_exists: Assert item exists by ID
 * - assert_style: Assert fill/stroke/opacity styles
 * - assert_text: Assert text frame content
 * - assert_alignment: Assert positional alignment with optional spacing
 * - measure_bounds: Get bounds of targets
 * - snapshot_structure: Capture document structure snapshot
 * 
 * @requires ops_core (for registerOpHandler)
 * @version 1.2.0
 */

// ==================== Assert Count ====================

registerOpHandler("assert_count", function (params, targets, ctx) {
    var expected = params.expected;
    var operator = params.operator || "eq"; // eq, gte, lte, gt, lt

    // Per-layer count: if params.layer provided, count items on that layer
    var actual;
    if (params.layer) {
        var doc = ctx.doc;
        var targetLayer = null;
        for (var i = 0; i < doc.layers.length; i++) {
            if (doc.layers[i].name === params.layer) {
                targetLayer = doc.layers[i];
                break;
            }
        }
        if (!targetLayer) {
            return makeError(ErrorCodes.R_APPLY_FAILED, "Layer not found: " + params.layer, "apply");
        }
        actual = targetLayer.pageItems.length;
    } else {
        actual = targets.length;
    }

    var ok = false;
    switch (operator) {
        case "eq": ok = actual === expected; break;
        case "gte": ok = actual >= expected; break;
        case "lte": ok = actual <= expected; break;
        case "gt": ok = actual > expected; break;
        case "lt": ok = actual < expected; break;
    }

    return {
        ok: ok,
        data: {
            expected: expected,
            actual: actual,
            operator: operator,
            layer: params.layer || null
        }
    };
});

// ==================== Assert Z-Order ====================

/**
 * Assert that items are in expected z-order.
 * @param {string} params.above - MCP ID that should be ABOVE (closer to viewer)
 * @param {string} params.below - MCP ID that should be BELOW
 * @param {Array} [params.pairs] - Array of [aboveId, belowId] pairs for batch check
 */
registerOpHandler("assert_z_order", function (params, targets, ctx) {
    var doc = ctx.doc;

    // Collect all pairs to check
    var pairs = params.pairs || [];
    if (params.above && params.below) {
        pairs.push([params.above, params.below]);
    }

    if (pairs.length === 0) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "assert_z_order requires 'above'+'below' or 'pairs' array", "validate");
    }

    // Build a lookup: mcpId -> { layerIndex, itemIndex }
    // In Illustrator, lower pageItems index = higher z-position (topmost = [0])
    var idMap = {};
    for (var li = 0; li < doc.layers.length; li++) {
        var layer = doc.layers[li];
        for (var ii = 0; ii < layer.pageItems.length; ii++) {
            var note = layer.pageItems[ii].note || "";
            var match = note.match(/@mcp:id=([^\s;]+)/);
            if (match) {
                idMap[match[1]] = { layerIndex: li, itemIndex: ii, name: layer.pageItems[ii].name };
            }
        }
    }

    var passed = [];
    var failed = [];

    for (var p = 0; p < pairs.length; p++) {
        var aboveId = pairs[p][0];
        var belowId = pairs[p][1];
        var a = idMap[aboveId];
        var b = idMap[belowId];

        if (!a || !b) {
            failed.push({ above: aboveId, below: belowId, reason: "ID not found: " + (!a ? aboveId : belowId) });
            continue;
        }

        // Compare: higher layer (lower index) = above. Within same layer, lower item index = above.
        var aAbove = false;
        if (a.layerIndex < b.layerIndex) {
            aAbove = true; // a is on a higher layer
        } else if (a.layerIndex === b.layerIndex) {
            aAbove = (a.itemIndex < b.itemIndex); // lower index = higher in stack
        }

        if (aAbove) {
            passed.push({ above: aboveId, below: belowId });
        } else {
            failed.push({ above: aboveId, below: belowId, reason: "z-order reversed" });
        }
    }

    return {
        ok: failed.length === 0,
        data: {
            total: pairs.length,
            passed: passed.length,
            failed: failed.length,
            details: failed.length > 0 ? failed : undefined
        }
    };
});

// ==================== Assert Layer Order ====================

/**
 * Assert that layers appear in expected top-to-bottom order.
 * Uses monotonicity check on index map: index[E0] < index[E1] < ...
 *
 * @param {string[]} params.order - Expected layer names, top-to-bottom
 * @param {boolean} [params.strict=false] - false = subset ordering (extra layers ok),
 *                                          true = exact match (no extra layers)
 */
registerOpHandler("assert_layer_order", function (params, targets, ctx) {
    var doc = ctx.doc;
    var expected = params.order;

    if (!expected || expected.length < 2) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM,
            "assert_layer_order requires 'order' array with >= 2 names", "validate");
    }

    // Build actual order + index map (0 = topmost)
    var actual = [];
    var indexMap = {};
    for (var i = 0; i < doc.layers.length; i++) {
        var n = doc.layers[i].name;
        actual.push(n);
        if (indexMap[n] === undefined) indexMap[n] = i; // first occurrence
    }

    var missing = [];
    var violations = [];

    // Check existence + monotonicity: index[E0] < index[E1] < ...
    var prevIdx = -1;
    var prevName = null;
    for (var i = 0; i < expected.length; i++) {
        var name = expected[i];
        if (indexMap[name] === undefined) {
            missing.push(name);
            continue;
        }
        var idx = indexMap[name];
        if (prevIdx >= 0 && idx <= prevIdx) {
            violations.push({
                name: name,
                issue: "expected below '" + prevName + "' (idx " + prevIdx
                    + ") but found at idx " + idx
                    + " (actual neighbor: '" + actual[idx > 0 ? idx - 1 : 0] + "')",
                expectedAfter: prevIdx,
                actualIndex: idx
            });
        }
        prevIdx = idx;
        prevName = name;
    }

    // strict: true = exact set match, no extra layers
    // strict: false (default) = subset relative ordering, extras allowed
    if (params.strict === true && actual.length !== expected.length) {
        var extra = [];
        for (var i = 0; i < actual.length; i++) {
            var found = false;
            for (var j = 0; j < expected.length; j++) {
                if (actual[i] === expected[j]) { found = true; break; }
            }
            if (!found) extra.push(actual[i]);
        }
        violations.push({
            name: "(strict)",
            issue: "extra layers: expected " + expected.length + ", actual " + actual.length,
            extra: extra
        });
    }

    return {
        ok: missing.length === 0 && violations.length === 0,
        data: {
            expectedOrder: expected,
            actualOrder: actual,
            missing: missing.length > 0 ? missing : undefined,
            violations: violations.length > 0 ? violations : undefined
        }
    };
});

// ==================== Assert Bounds ====================

registerOpHandler("assert_bounds", function (params, targets, ctx) {
    var doc = ctx.doc;

    // Get artboard bounds
    var abIndex = params.artboardIndex || doc.artboards.getActiveArtboardIndex();
    var ab = doc.artboards[abIndex];
    var abBounds = ab.artboardRect; // [left, top, right, bottom]

    var inBounds = 0;
    var outOfBounds = [];

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];
        var itemLeft = item.left;
        var itemTop = item.top;
        var itemRight = item.left + item.width;
        var itemBottom = item.top - item.height;

        // Check if item is fully within artboard
        var isIn = itemLeft >= abBounds[0]
            && itemRight <= abBounds[2]
            && itemTop <= abBounds[1]
            && itemBottom >= abBounds[3];

        if (isIn) {
            inBounds++;
        } else {
            outOfBounds.push({
                index: i,
                name: item.name || null,
                bounds: [itemLeft, itemTop, itemRight, itemBottom]
            });
        }
    }

    return {
        ok: outOfBounds.length === 0,
        data: {
            inBounds: inBounds,
            outOfBounds: outOfBounds.length,
            artboardBounds: abBounds,
            details: outOfBounds.slice(0, 5) // Limit to first 5
        }
    };
});

// ==================== Assert Exists ====================

registerOpHandler("assert_exists", function (params, targets, ctx) {
    var ids = params.ids || [];
    var doc = ctx.doc;

    // Find items by ID
    var found = [];
    var missing = [];

    function searchContainer(container) {
        if (!container || !container.pageItems) return;
        for (var i = 0; i < container.pageItems.length; i++) {
            var item = container.pageItems[i];
            try {
                if (item.note) {
                    var match = item.note.match(/@mcp:id=([^\s@]+)/);
                    if (match) {
                        var itemId = match[1];
                        for (var j = 0; j < ids.length; j++) {
                            if (ids[j] === itemId && found.indexOf(itemId) === -1) {
                                found.push(itemId);
                            }
                        }
                    }
                }
            } catch (e) { }
            if (item.typename === "GroupItem") searchContainer(item);
        }
    }

    for (var i = 0; i < doc.layers.length; i++) {
        searchContainer(doc.layers[i]);
    }

    for (var i = 0; i < ids.length; i++) {
        if (found.indexOf(ids[i]) === -1) {
            missing.push(ids[i]);
        }
    }

    return {
        ok: missing.length === 0,
        data: {
            found: found.length,
            missing: missing
        }
    };
});

// ==================== Measure Bounds ====================

registerOpHandler("measure_bounds", function (params, targets, ctx) {
    if (targets.length === 0) {
        return { ok: true, data: { bounds: null } };
    }

    var minX = Infinity, minY = Infinity;
    var maxX = -Infinity, maxY = -Infinity;

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];
        minX = Math.min(minX, item.left);
        maxX = Math.max(maxX, item.left + item.width);
        maxY = Math.max(maxY, item.top);
        minY = Math.min(minY, item.top - item.height);
    }

    function _q(v) { return (typeof v === "number") ? Math.round(v * 100) / 100 : v; }
    return {
        ok: true,
        data: {
            bounds: {
                left: _q(minX),
                top: _q(maxY),
                right: _q(maxX),
                bottom: _q(minY),
                width: _q(maxX - minX),
                height: _q(maxY - minY)
            },
            itemCount: targets.length
        }
    };
});

// ==================== Snapshot Structure ====================

registerOpHandler("snapshot_structure", function (params, targets, ctx) {
    var doc = ctx.doc;
    var includeItems = params.includeItems || false;

    var snapshot = {
        documentName: doc.name,
        artboards: doc.artboards.length,
        layers: [],
        selection: doc.selection ? doc.selection.length : 0,
        timestamp: ctx.clock()
    };

    for (var i = 0; i < doc.layers.length; i++) {
        var layer = doc.layers[i];
        var layerInfo = {
            name: layer.name,
            visible: layer.visible,
            locked: layer.locked,
            itemCount: layer.pageItems.length
        };

        if (includeItems) {
            layerInfo.items = [];
            for (var j = 0; j < layer.pageItems.length; j++) {
                var item = layer.pageItems[j];
                var _qm = function (v) { return (typeof v === "number") ? Math.round(v * 100) / 100 : v; };
                layerInfo.items.push({
                    name: item.name || null,
                    typename: item.typename,
                    bounds: [_qm(item.left), _qm(item.top), _qm(item.width), _qm(item.height)]
                });
            }
        }

        snapshot.layers.push(layerInfo);
    }

    return {
        ok: true,
        data: snapshot
    };
});

// ==================== Hash Structure (lightweight digest) ====================

registerOpHandler("hash_structure", function (params, targets, ctx) {
    var doc = ctx.doc;

    // Create a simple hash of document structure
    var parts = [
        doc.name,
        String(doc.layers.length),
        String(doc.artboards.length)
    ];

    for (var i = 0; i < doc.layers.length; i++) {
        var layer = doc.layers[i];
        parts.push(layer.name + ":" + layer.pageItems.length);
    }

    // Simple string hash
    var str = parts.join("|");
    var hash = 0;
    for (var i = 0; i < str.length; i++) {
        var charCode = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + charCode;
        hash = hash & hash;
    }

    return {
        ok: true,
        data: {
            hash: String(hash),
            components: parts.length
        }
    };
});

/**
 * Assert that targets have expected fill/stroke styles.
 * Supports RGB and CMYK color modes.
 * 
 * @param {Object} params.fill - Expected fill color {r, g, b} or {c, m, y, k} (optional)
 * @param {Object} params.stroke - Expected stroke color {r, g, b} or {c, m, y, k} (optional)
 * @param {number} params.strokeWidth - Expected stroke width (optional)
 * @param {number} params.opacity - Expected opacity 0-100 (optional)
 * @param {number} params.tolerance - Color tolerance per channel (default: 1).
 *   NOTE: Tolerance is applied per-channel independently (|actual.R - expected.R| <= tol),
 *   NOT as perceptual ΔE. Two colors may be perceptually different but pass, or
 *   perceptually identical but fail. For academic figures, per-channel is typically sufficient.
 */
registerOpHandler("assert_style", function (params, targets, ctx) {
    var tolerance = params.tolerance || 1;
    var passed = [];
    var failed = [];

    function rgbMatches(actual, expected, tol) {
        if (!actual || !expected) return false;
        return Math.abs(actual.red - expected.r) <= tol &&
            Math.abs(actual.green - expected.g) <= tol &&
            Math.abs(actual.blue - expected.b) <= tol;
    }

    function cmykMatches(actual, expected, tol) {
        if (!actual || !expected) return false;
        return Math.abs(actual.cyan - expected.c) <= tol &&
            Math.abs(actual.magenta - expected.m) <= tol &&
            Math.abs(actual.yellow - expected.y) <= tol &&
            Math.abs(actual.black - expected.k) <= tol;
    }

    function checkColor(actualColor, expected, tol) {
        if (!actualColor) return { ok: false, message: "no color" };

        var typename = actualColor.typename;

        // RGB color check
        if (typename === "RGBColor") {
            if (expected.r !== undefined) {
                if (rgbMatches(actualColor, expected, tol)) {
                    return { ok: true };
                } else {
                    return {
                        ok: false,
                        message: "mismatch: expected rgb(" + expected.r + "," + expected.g + "," + expected.b +
                            ") got rgb(" + actualColor.red + "," + actualColor.green + "," + actualColor.blue + ")"
                    };
                }
            } else {
                return { ok: false, message: "expected CMYK but got RGB" };
            }
        }

        // CMYK color check  
        if (typename === "CMYKColor") {
            if (expected.c !== undefined) {
                if (cmykMatches(actualColor, expected, tol)) {
                    return { ok: true };
                } else {
                    return {
                        ok: false,
                        message: "mismatch: expected cmyk(" + expected.c + "," + expected.m + "," + expected.y + "," + expected.k +
                            ") got cmyk(" + actualColor.cyan + "," + actualColor.magenta + "," + actualColor.yellow + "," + actualColor.black + ")"
                    };
                }
            } else {
                return { ok: false, message: "expected RGB but got CMYK" };
            }
        }

        // Unsupported color type
        return { ok: false, message: "unsupported color type: " + typename };
    }

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];
        var issues = [];

        try {
            // Check fill color
            if (params.fill) {
                if (item.filled && item.fillColor) {
                    var fillResult = checkColor(item.fillColor, params.fill, tolerance);
                    if (!fillResult.ok) {
                        issues.push("fill " + fillResult.message);
                    }
                } else if (!item.filled) {
                    issues.push("no fill");
                }
            }

            // Check stroke color
            if (params.stroke) {
                if (item.stroked && item.strokeColor) {
                    var strokeResult = checkColor(item.strokeColor, params.stroke, tolerance);
                    if (!strokeResult.ok) {
                        issues.push("stroke " + strokeResult.message);
                    }
                } else if (!item.stroked) {
                    issues.push("no stroke");
                }
            }

            // Check stroke width
            if (params.strokeWidth !== undefined) {
                if (item.stroked) {
                    if (Math.abs(item.strokeWidth - params.strokeWidth) > tolerance) {
                        issues.push("strokeWidth mismatch: expected " + params.strokeWidth + " got " + item.strokeWidth);
                    }
                } else {
                    issues.push("no stroke");
                }
            }

            // Check opacity
            if (params.opacity !== undefined) {
                if (Math.abs(item.opacity - params.opacity) > tolerance) {
                    issues.push("opacity mismatch: expected " + params.opacity + " got " + item.opacity);
                }
            }

            if (issues.length === 0) {
                passed.push(i);
            } else {
                failed.push({ index: i, name: item.name || null, issues: issues });
            }

        } catch (e) {
            failed.push({ index: i, name: item.name || null, issues: ["error: " + e.message] });
        }
    }

    // P5: Repair mode — apply expected styles to items with violations
    var repairs = [];
    var violationsBefore = failed.length;

    if (params.repair === true && failed.length > 0) {

        for (var i = 0; i < failed.length; i++) {
            var idx = failed[i].index;
            var item = targets[idx];
            var repair = {
                index: idx,
                name: failed[i].name,
                id: (typeof extractMcpId === "function" && item.note) ? extractMcpId(item.note) : null,
                before: {},
                after: {}
            };
            var didRepair = false;

            try {
                // Repair fill (RGB)
                if (params.fill && params.fill.r !== undefined) {
                    if (item.filled && item.fillColor && item.fillColor.typename === "RGBColor") {
                        repair.before.fill = { r: item.fillColor.red, g: item.fillColor.green, b: item.fillColor.blue };
                    } else {
                        repair.before.fill = item.filled ? "non-rgb" : "none";
                    }
                    var fc = new RGBColor();
                    fc.red = params.fill.r;
                    fc.green = params.fill.g;
                    fc.blue = params.fill.b;
                    item.filled = true;
                    item.fillColor = fc;
                    repair.after.fill = { r: params.fill.r, g: params.fill.g, b: params.fill.b };
                    didRepair = true;
                }

                // Repair fill (CMYK)
                if (params.fill && params.fill.c !== undefined) {
                    if (item.filled && item.fillColor && item.fillColor.typename === "CMYKColor") {
                        repair.before.fill = { c: item.fillColor.cyan, m: item.fillColor.magenta, y: item.fillColor.yellow, k: item.fillColor.black };
                    } else {
                        repair.before.fill = item.filled ? "non-cmyk" : "none";
                    }
                    var fcc = new CMYKColor();
                    fcc.cyan = params.fill.c;
                    fcc.magenta = params.fill.m;
                    fcc.yellow = params.fill.y;
                    fcc.black = params.fill.k;
                    item.filled = true;
                    item.fillColor = fcc;
                    repair.after.fill = { c: params.fill.c, m: params.fill.m, y: params.fill.y, k: params.fill.k };
                    didRepair = true;
                }

                // Repair stroke (RGB)
                if (params.stroke && params.stroke.r !== undefined) {
                    if (item.stroked && item.strokeColor && item.strokeColor.typename === "RGBColor") {
                        repair.before.stroke = { r: item.strokeColor.red, g: item.strokeColor.green, b: item.strokeColor.blue };
                    } else {
                        repair.before.stroke = item.stroked ? "non-rgb" : "none";
                    }
                    var sc = new RGBColor();
                    sc.red = params.stroke.r;
                    sc.green = params.stroke.g;
                    sc.blue = params.stroke.b;
                    item.stroked = true;
                    item.strokeColor = sc;
                    repair.after.stroke = { r: params.stroke.r, g: params.stroke.g, b: params.stroke.b };
                    didRepair = true;
                }

                // Repair stroke (CMYK)
                if (params.stroke && params.stroke.c !== undefined) {
                    if (item.stroked && item.strokeColor && item.strokeColor.typename === "CMYKColor") {
                        repair.before.stroke = { c: item.strokeColor.cyan, m: item.strokeColor.magenta, y: item.strokeColor.yellow, k: item.strokeColor.black };
                    } else {
                        repair.before.stroke = item.stroked ? "non-cmyk" : "none";
                    }
                    var scc = new CMYKColor();
                    scc.cyan = params.stroke.c;
                    scc.magenta = params.stroke.m;
                    scc.yellow = params.stroke.y;
                    scc.black = params.stroke.k;
                    item.stroked = true;
                    item.strokeColor = scc;
                    repair.after.stroke = { c: params.stroke.c, m: params.stroke.m, y: params.stroke.y, k: params.stroke.k };
                    didRepair = true;
                }

                // Repair stroke width
                if (params.strokeWidth !== undefined) {
                    repair.before.strokeWidth = item.stroked ? item.strokeWidth : null;
                    item.strokeWidth = params.strokeWidth;
                    repair.after.strokeWidth = params.strokeWidth;
                    didRepair = true;
                }

                // Repair opacity
                if (params.opacity !== undefined) {
                    repair.before.opacity = item.opacity;
                    item.opacity = params.opacity;
                    repair.after.opacity = params.opacity;
                    didRepair = true;
                }

                if (didRepair) {
                    repairs.push(repair);
                }
            } catch (e) {
                // Item couldn't be repaired (e.g. locked)
            }
        }
    }

    var violationsAfter = violationsBefore - repairs.length;

    var result = {
        ok: failed.length === 0 || repairs.length === failed.length,
        data: {
            passed: passed.length,
            failed: failed.length,
            details: failed.slice(0, 10)
        }
    };

    if (params.repair === true) {
        result.data.violations_before = violationsBefore;
        result.data.repaired = repairs.length;
        result.data.violations_after = violationsAfter;
        result.data.repairs = repairs;
    }

    return result;
});

// ==================== Assert Text ====================

/**
 * Assert that target text frames contain expected content.
 * 
 * @param {string} params.contents - Expected text content
 * @param {string} [params.matchMode="exact"] - "exact", "contains", or "regex"
 * @param {boolean} [params.caseSensitive=true] - Case sensitivity flag
 */
registerOpHandler("assert_text", function (params, targets, ctx) {
    var expected = params.contents;

    // Guard against missing required param
    if (expected === undefined || expected === null) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "missing required param: contents", "apply");
    }

    var matchMode = params.matchMode || "exact";
    var caseSensitive = params.caseSensitive !== false; // default true

    var passed = [];
    var failed = [];

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];

        // Must be a TextFrame
        if (item.typename !== "TextFrame") {
            failed.push({
                index: i,
                name: item.name || null,
                issue: "not a TextFrame (got " + item.typename + ")"
            });
            continue;
        }

        var actual = item.contents;
        var exp = expected;

        // Apply case sensitivity
        if (!caseSensitive) {
            actual = actual.toLowerCase();
            exp = exp.toLowerCase();
        }

        var ok = false;
        switch (matchMode) {
            case "exact":
                ok = actual === exp;
                break;
            case "contains":
                ok = actual.indexOf(exp) !== -1;
                break;
            case "regex":
                try {
                    var flags = caseSensitive ? "" : "i";
                    var re = new RegExp(expected, flags);
                    ok = re.test(item.contents);
                } catch (e) {
                    failed.push({
                        index: i,
                        name: item.name || null,
                        issue: "invalid regex: " + e.message
                    });
                    continue;
                }
                break;
            default:
                failed.push({
                    index: i,
                    name: item.name || null,
                    issue: "unknown matchMode: " + matchMode
                });
                continue;
        }

        if (ok) {
            passed.push(i);
        } else {
            failed.push({
                index: i,
                name: item.name || null,
                issue: matchMode + " mismatch: expected " + JSON.stringify(expected) + " got " + JSON.stringify(item.contents)
            });
        }
    }

    return {
        ok: failed.length === 0,
        data: {
            passed: passed.length,
            failed: failed.length,
            details: failed.slice(0, 10)
        }
    };
});

// ==================== Assert Alignment ====================

/**
 * Assert that targets are aligned on a specified axis, with optional spacing check.
 * 
 * @param {string} params.mode - "left", "centerX", "right", "top", "centerY", "bottom"
 * @param {number} [params.tolerance=1] - Tolerance in points
 * @param {number} [params.spacing] - Expected uniform gap between items (optional)
 */
registerOpHandler("assert_alignment", function (params, targets, ctx) {
    var mode = params.mode;
    var tolerance = (params.tolerance !== undefined) ? params.tolerance : 1;

    if (targets.length < 2) {
        return {
            ok: true,
            data: {
                mode: mode,
                message: "need >=2 targets to check alignment",
                aligned: targets.length,
                misaligned: 0,
                details: []
            }
        };
    }

    // Validate mode
    var validModes = ["left", "centerX", "right", "top", "centerY", "bottom"];
    var modeValid = false;
    for (var m = 0; m < validModes.length; m++) {
        if (validModes[m] === mode) { modeValid = true; break; }
    }
    if (!modeValid) {
        return makeError(ErrorCodes.V_INVALID_PARAM_TYPE, "unknown mode: " + mode + ", expected one of: " + validModes.join(", "), "apply");
    }

    function getValue(item) {
        switch (mode) {
            case "left": return item.left;
            case "right": return item.left + item.width;
            case "centerX": return item.left + item.width / 2;
            case "top": return item.top;
            case "bottom": return item.top - item.height;
            case "centerY": return item.top - item.height / 2;
            // No default needed as mode is validated above
        }
    }

    var values = [];
    for (var i = 0; i < targets.length; i++) {
        values.push({
            index: i,
            name: targets[i].name || null,
            value: getValue(targets[i])
        });
    }

    // Use the first item's value as reference
    var refValue = values[0].value;
    var aligned = [];
    var misaligned = [];

    for (var i = 0; i < values.length; i++) {
        if (Math.abs(values[i].value - refValue) <= tolerance) {
            aligned.push(values[i].index);
        } else {
            misaligned.push({
                index: values[i].index,
                name: values[i].name,
                value: values[i].value,
                delta: Math.round((values[i].value - refValue) * 100) / 100
            });
        }
    }

    // P5: Repair mode — snap misaligned items to reference value
    var repairs = [];
    var violationsBefore = misaligned.length;

    if (params.repair === true && misaligned.length > 0) {
        for (var i = 0; i < misaligned.length; i++) {
            var idx = misaligned[i].index;
            var item = targets[idx];
            var beforeVal = misaligned[i].value;

            try {
                // Apply correction based on mode
                switch (mode) {
                    case "left":
                        item.left = refValue;
                        break;
                    case "right":
                        item.left = refValue - item.width;
                        break;
                    case "centerX":
                        item.left = refValue - item.width / 2;
                        break;
                    case "top":
                        item.top = refValue;
                        break;
                    case "bottom":
                        item.top = refValue + item.height;
                        break;
                    case "centerY":
                        item.top = refValue + item.height / 2;
                        break;
                }

                var afterVal = getValue(item);
                repairs.push({
                    index: idx,
                    name: misaligned[i].name,
                    id: (typeof extractMcpId === "function" && item.note) ? extractMcpId(item.note) : null,
                    before: beforeVal,
                    after: Math.round(afterVal * 100) / 100
                });
            } catch (e) {
                // Item couldn't be repaired (e.g. locked)
            }
        }
    }

    var violationsAfter = violationsBefore - repairs.length;

    var result = {
        ok: misaligned.length === 0 || repairs.length === misaligned.length,
        data: {
            mode: mode,
            referenceValue: Math.round(refValue * 100) / 100,
            aligned: aligned.length,
            misaligned: misaligned.length,
            details: misaligned.slice(0, 10)
        }
    };

    // Include repair report if repair was requested
    if (params.repair === true) {
        result.data.violations_before = violationsBefore;
        result.data.repaired = repairs.length;
        result.data.violations_after = violationsAfter;
        result.data.repairs = repairs;
    }

    // Optional spacing check (measured PERPENDICULAR to alignment axis)
    if (params.spacing !== undefined && targets.length >= 2) {
        var expectedSpacing = params.spacing;

        // Spacing is measured PERPENDICULAR to the alignment axis:
        // - Items aligned horizontally (left/centerX/right) are in a column → measure vertical spacing
        // - Items aligned vertically (top/centerY/bottom) are in a row → measure horizontal spacing
        var spacingIsHorizontal = (mode === "top" || mode === "centerY" || mode === "bottom");

        // Build sortable array with position on the spacing axis
        var sortable = [];
        for (var i = 0; i < targets.length; i++) {
            sortable.push({
                index: i,
                name: targets[i].name || null,
                pos: spacingIsHorizontal
                    ? targets[i].left
                    : targets[i].top
            });
        }

        // Sort ascending for horizontal (left to right), descending for vertical (top to bottom, since top is higher Y)
        sortable.sort(function (a, b) {
            return spacingIsHorizontal ? a.pos - b.pos : b.pos - a.pos;
        });

        var spacingErrors = [];
        for (var i = 1; i < sortable.length; i++) {
            var gap;
            if (spacingIsHorizontal) {
                // gap = left of next - right of current
                var currRight = targets[sortable[i - 1].index].left + targets[sortable[i - 1].index].width;
                gap = targets[sortable[i].index].left - currRight;
            } else {
                // gap = bottom of prev - top of next (vertical)
                var prevBottom = targets[sortable[i - 1].index].top - targets[sortable[i - 1].index].height;
                gap = prevBottom - targets[sortable[i].index].top;
            }

            if (Math.abs(gap - expectedSpacing) > tolerance) {
                spacingErrors.push({
                    between: [sortable[i - 1].index, sortable[i].index],
                    names: [sortable[i - 1].name, sortable[i].name],
                    expected: expectedSpacing,
                    actual: Math.round(gap * 100) / 100
                });
            }
        }

        result.data.spacingCheck = {
            expected: expectedSpacing,
            ok: spacingErrors.length === 0,
            errors: spacingErrors.slice(0, 10)
        };

        if (spacingErrors.length > 0) {
            result.ok = false;
        }
    }

    return result;
});
