/**
 * ops_align.jsx - Alignment and Distribution Operations
 * Part of Illustrator MCP SOC Framework
 *
 * Provides handlers for:
 * - align_horizontal: Align items horizontally (left, center, right)
 * - align_vertical: Align items vertically (top, middle, bottom)
 * - distribute_horizontal: Distribute items horizontally (gap or center mode)
 * - distribute_vertical: Distribute items vertically (gap or center mode)
 *
 * Coordinate semantics:
 *   All coordinates are document space (same as item.left / item.top).
 *   Alignment uses axis-aligned bounds (geometricBounds).
 *   Groups -> group bounds. Clipping masks -> Illustrator geometricBounds.
 *   Vertical: item.top is higher (less negative) = visually higher on page.
 *     mode="top" aligns to highest item.top value.
 *
 * @requires ops_core (for registerOpHandler)
 * @requires heap (for heapResolve - key_id resolution)
 * @version 2.0.0
 */

// ==================== Shared Helper ====================

/**
 * Resolve the reference coordinate for alignment on a given axis.
 * Priority: coordinate > key_id > reference (artboard / targets)
 *
 * @param {Object} params - Op params (mode, reference, key_id, coordinate)
 * @param {Array} targets - Resolved target items
 * @param {Object} ctx - Execution context (ctx.doc)
 * @param {string} axis - "x" or "y"
 * @returns {Object} {value: number, source: string, warning: string|null}
 */
function _resolveReferenceAxis(params, targets, ctx, axis) {
    var warning = null;

    // --- coordinate override (highest priority) ---
    if (params.coordinate !== undefined && params.coordinate !== null) {
        if (params.reference && params.reference !== "targets") {
            warning = "coordinate overrides reference=\"" + params.reference + "\"";
        }
        if (params.key_id) {
            warning = "coordinate overrides key_id=\"" + params.key_id + "\"";
        }
        return { value: params.coordinate, source: "coordinate", warning: warning };
    }

    // --- key_id (second priority) ---
    if (params.key_id) {
        var keyItem = heapResolve(params.key_id, ctx.doc);
        if (!keyItem) {
            return {
                value: null, source: "key_id", warning: null,
                error: "Key item not found: " + params.key_id
            };
        }
        var val;
        if (axis === "x") {
            var mode = params.mode || "center";
            if (mode === "left") val = keyItem.left;
            else if (mode === "right") val = keyItem.left + keyItem.width;
            else val = keyItem.left + keyItem.width / 2; // center
        } else {
            var mode = params.mode || "middle";
            if (mode === "top") val = keyItem.top;
            else if (mode === "bottom") val = keyItem.top - keyItem.height;
            else val = keyItem.top - keyItem.height / 2; // middle
        }
        return { value: val, source: "key_id", warning: warning };
    }

    // --- reference: artboard or targets (lowest priority) ---
    var reference = params.reference || "targets";

    if (reference === "artboard") {
        var ab = ctx.doc.artboards[ctx.doc.artboards.getActiveArtboardIndex()];
        var abBounds = ab.artboardRect; // [left, top, right, bottom]
        var val;
        if (axis === "x") {
            var mode = params.mode || "center";
            if (mode === "left") val = abBounds[0];
            else if (mode === "right") val = abBounds[2];
            else val = (abBounds[0] + abBounds[2]) / 2;
        } else {
            var mode = params.mode || "middle";
            if (mode === "top") val = abBounds[1];
            else if (mode === "bottom") val = abBounds[3];
            else val = (abBounds[1] + abBounds[3]) / 2;
        }
        return { value: val, source: "artboard", warning: warning };
    }

    // --- targets (default) ---
    var val;
    if (axis === "x") {
        var minX = Infinity, maxX = -Infinity;
        for (var i = 0; i < targets.length; i++) {
            minX = Math.min(minX, targets[i].left);
            maxX = Math.max(maxX, targets[i].left + targets[i].width);
        }
        var mode = params.mode || "center";
        if (mode === "left") val = minX;
        else if (mode === "right") val = maxX;
        else val = (minX + maxX) / 2;
    } else {
        var maxY = -Infinity, minY = Infinity;
        for (var i = 0; i < targets.length; i++) {
            maxY = Math.max(maxY, targets[i].top);
            minY = Math.min(minY, targets[i].top - targets[i].height);
        }
        var mode = params.mode || "middle";
        if (mode === "top") val = maxY;
        else if (mode === "bottom") val = minY;
        else val = (minY + maxY) / 2;
    }
    return { value: val, source: "targets", warning: warning };
}


/**
 * Sort items deterministically for distribute operations.
 * Horizontal: sort by left (ascending), tie-break by MCP ID ascending.
 * Vertical: sort by top (descending = top-to-bottom), tie-break by MCP ID ascending.
 *
 * @param {Array} items - Target items
 * @param {string} axis - "x" or "y"
 * @returns {Array} Sorted copy
 */
function _sortForDistribute(items, axis) {
    var sorted = [];
    for (var i = 0; i < items.length; i++) sorted.push(items[i]);

    sorted.sort(function (a, b) {
        var diff;
        if (axis === "x") {
            diff = a.left - b.left;
        } else {
            diff = b.top - a.top; // descending: highest top first
        }
        if (diff !== 0) return diff;
        // Tie-break by MCP ID ascending
        var idA = (typeof extractMcpId === "function") ? (extractMcpId(a.note) || "") : "";
        var idB = (typeof extractMcpId === "function") ? (extractMcpId(b.note) || "") : "";
        return idA < idB ? -1 : (idA > idB ? 1 : 0);
    });

    return sorted;
}


// ==================== Align Horizontal ====================

registerOpHandler("align_horizontal", function (params, targets, ctx) {
    if (targets.length < 2) {
        return { ok: true, data: { aligned: 0 }, warnings: ["Need at least 2 items to align"] };
    }

    var ref = _resolveReferenceAxis(params, targets, ctx, "x");
    if (ref.error) return { ok: false, error: ref.error };

    var refX = ref.value;
    var mode = params.mode || "center";
    var warnings = ref.warning ? [ref.warning] : [];

    // Align items (key object stays in place — it gets same refX)
    var aligned = 0;
    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];
        try {
            if (mode === "left") {
                item.left = refX;
            } else if (mode === "right") {
                item.left = refX - item.width;
            } else { // center
                item.left = refX - item.width / 2;
            }
            aligned++;
        } catch (e) { }
    }

    var result = { ok: true, data: { aligned: aligned, source: ref.source } };
    if (warnings.length > 0) result.warnings = warnings;
    return result;
});

// ==================== Align Vertical ====================

registerOpHandler("align_vertical", function (params, targets, ctx) {
    if (targets.length < 2) {
        return { ok: true, data: { aligned: 0 }, warnings: ["Need at least 2 items to align"] };
    }

    var ref = _resolveReferenceAxis(params, targets, ctx, "y");
    if (ref.error) return { ok: false, error: ref.error };

    var refY = ref.value;
    var mode = params.mode || "middle";
    var warnings = ref.warning ? [ref.warning] : [];

    var aligned = 0;
    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];
        try {
            if (mode === "top") {
                item.top = refY;
            } else if (mode === "bottom") {
                item.top = refY + item.height;
            } else { // middle
                item.top = refY + item.height / 2;
            }
            aligned++;
        } catch (e) { }
    }

    var result = { ok: true, data: { aligned: aligned, source: ref.source } };
    if (warnings.length > 0) result.warnings = warnings;
    return result;
});

// ==================== Distribute Horizontal ====================

registerOpHandler("distribute_horizontal", function (params, targets, ctx) {
    if (targets.length < 3) {
        return { ok: true, data: { distributed: 0 }, warnings: ["Need at least 3 items to distribute"] };
    }

    var spacing = params.spacing;       // undefined = auto
    var mode = params.mode || "gap";    // "gap" or "center"
    var sorted = _sortForDistribute(targets, "x");

    if (mode === "center") {
        // Center-to-center distribution
        var firstCx = sorted[0].left + sorted[0].width / 2;
        var lastCx = sorted[sorted.length - 1].left + sorted[sorted.length - 1].width / 2;

        var step;
        if (spacing !== undefined && spacing !== null) {
            // Fixed center-to-center spacing, anchored to first item
            step = spacing;
        } else {
            // Auto: equalize centers within existing span
            step = (lastCx - firstCx) / (sorted.length - 1);
        }

        for (var i = 0; i < sorted.length; i++) {
            var targetCx = firstCx + step * i;
            sorted[i].left = targetCx - sorted[i].width / 2;
        }
    } else {
        // Gap-based distribution (original behavior)
        if (spacing !== undefined && spacing !== null) {
            // Fixed gap spacing, anchored to first item
            var currentX = sorted[0].left;
            for (var i = 0; i < sorted.length; i++) {
                sorted[i].left = currentX;
                currentX += sorted[i].width + spacing;
            }
        } else {
            // Auto-distribute gaps within existing span
            var first = sorted[0];
            var last = sorted[sorted.length - 1];
            var totalWidth = 0;
            for (var i = 0; i < sorted.length; i++) totalWidth += sorted[i].width;
            var totalSpace = (last.left + last.width) - first.left - totalWidth;
            var gap = totalSpace / (sorted.length - 1);

            var currentX = first.left;
            for (var i = 0; i < sorted.length; i++) {
                sorted[i].left = currentX;
                currentX += sorted[i].width + gap;
            }
        }
    }

    return { ok: true, data: { distributed: sorted.length, mode: mode } };
});

// ==================== Distribute Vertical ====================

registerOpHandler("distribute_vertical", function (params, targets, ctx) {
    if (targets.length < 3) {
        return { ok: true, data: { distributed: 0 }, warnings: ["Need at least 3 items to distribute"] };
    }

    var spacing = params.spacing;
    var mode = params.mode || "gap";
    var sorted = _sortForDistribute(targets, "y");

    if (mode === "center") {
        // Center-to-center distribution
        var firstCy = sorted[0].top - sorted[0].height / 2;
        var lastCy = sorted[sorted.length - 1].top - sorted[sorted.length - 1].height / 2;

        var step;
        if (spacing !== undefined && spacing !== null) {
            // Fixed center-to-center spacing (negative because Y goes down)
            step = -Math.abs(spacing);
        } else {
            // Auto: equalize centers within existing span
            step = (lastCy - firstCy) / (sorted.length - 1);
        }

        for (var i = 0; i < sorted.length; i++) {
            var targetCy = firstCy + step * i;
            sorted[i].top = targetCy + sorted[i].height / 2;
        }
    } else {
        // Gap-based distribution (original behavior)
        if (spacing !== undefined && spacing !== null) {
            var currentY = sorted[0].top;
            for (var i = 0; i < sorted.length; i++) {
                sorted[i].top = currentY;
                currentY -= sorted[i].height + spacing;
            }
        } else {
            var first = sorted[0];
            var last = sorted[sorted.length - 1];
            var totalHeight = 0;
            for (var i = 0; i < sorted.length; i++) totalHeight += sorted[i].height;
            var totalSpace = first.top - (last.top - last.height) - totalHeight;
            var gap = totalSpace / (sorted.length - 1);

            var currentY = first.top;
            for (var i = 0; i < sorted.length; i++) {
                sorted[i].top = currentY;
                currentY -= sorted[i].height + gap;
            }
        }
    }

    return { ok: true, data: { distributed: sorted.length, mode: mode } };
});
