/**
 * ops_align.jsx - Alignment and Distribution Operations
 * Part of Illustrator MCP SOC Framework
 * 
 * Provides handlers for:
 * - align_horizontal: Align items horizontally (left, center, right)
 * - align_vertical: Align items vertically (top, middle, bottom)
 * - distribute_horizontal: Distribute items horizontally
 * - distribute_vertical: Distribute items vertically
 * 
 * @requires ops_core (for registerOpHandler)
 * @version 1.0.0
 */

// ==================== Align Horizontal ====================

registerOpHandler("align_horizontal", function (params, targets, ctx) {
    if (targets.length < 2) {
        return { ok: true, data: { aligned: 0 }, warnings: ["Need at least 2 items to align"] };
    }

    var mode = params.mode || "center"; // left, center, right
    var reference = params.reference || "targets"; // targets, artboard

    // Calculate reference point
    var refX = 0;
    if (reference === "artboard") {
        var ab = ctx.doc.artboards[ctx.doc.artboards.getActiveArtboardIndex()];
        var abBounds = ab.artboardRect;
        if (mode === "left") refX = abBounds[0];
        else if (mode === "right") refX = abBounds[2];
        else refX = (abBounds[0] + abBounds[2]) / 2;
    } else {
        // Calculate from resolved targets bounds
        var minX = Infinity, maxX = -Infinity;
        for (var i = 0; i < targets.length; i++) {
            minX = Math.min(minX, targets[i].left);
            maxX = Math.max(maxX, targets[i].left + targets[i].width);
        }
        if (mode === "left") refX = minX;
        else if (mode === "right") refX = maxX;
        else refX = (minX + maxX) / 2;
    }

    // Align items
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

    return { ok: true, data: { aligned: aligned } };
});

// ==================== Align Vertical ====================

registerOpHandler("align_vertical", function (params, targets, ctx) {
    if (targets.length < 2) {
        return { ok: true, data: { aligned: 0 }, warnings: ["Need at least 2 items to align"] };
    }

    var mode = params.mode || "middle"; // top, middle, bottom
    var reference = params.reference || "targets";

    var refY = 0;
    if (reference === "artboard") {
        var ab = ctx.doc.artboards[ctx.doc.artboards.getActiveArtboardIndex()];
        var abBounds = ab.artboardRect;
        if (mode === "top") refY = abBounds[1];
        else if (mode === "bottom") refY = abBounds[3];
        else refY = (abBounds[1] + abBounds[3]) / 2;
    } else {
        var minY = Infinity, maxY = -Infinity;
        for (var i = 0; i < targets.length; i++) {
            maxY = Math.max(maxY, targets[i].top);
            minY = Math.min(minY, targets[i].top - targets[i].height);
        }
        if (mode === "top") refY = maxY;
        else if (mode === "bottom") refY = minY;
        else refY = (minY + maxY) / 2;
    }

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

    return { ok: true, data: { aligned: aligned } };
});

// ==================== Distribute Horizontal ====================

registerOpHandler("distribute_horizontal", function (params, targets, ctx) {
    if (targets.length < 3) {
        return { ok: true, data: { distributed: 0 }, warnings: ["Need at least 3 items to distribute"] };
    }

    var spacing = params.spacing; // undefined = auto-distribute

    // Sort by X position
    var sorted = [];
    for (var i = 0; i < targets.length; i++) sorted.push(targets[i]);
    sorted.sort(function (a, b) { return a.left - b.left; });

    if (spacing !== undefined) {
        // Fixed spacing
        var currentX = sorted[0].left;
        for (var i = 0; i < sorted.length; i++) {
            sorted[i].left = currentX;
            currentX += sorted[i].width + spacing;
        }
    } else {
        // Auto-distribute between first and last
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

    return { ok: true, data: { distributed: sorted.length } };
});

// ==================== Distribute Vertical ====================

registerOpHandler("distribute_vertical", function (params, targets, ctx) {
    if (targets.length < 3) {
        return { ok: true, data: { distributed: 0 }, warnings: ["Need at least 3 items to distribute"] };
    }

    var spacing = params.spacing;

    // Sort by Y position (top to bottom, so higher top values first)
    var sorted = [];
    for (var i = 0; i < targets.length; i++) sorted.push(targets[i]);
    sorted.sort(function (a, b) { return b.top - a.top; });

    if (spacing !== undefined) {
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

    return { ok: true, data: { distributed: sorted.length } };
});
