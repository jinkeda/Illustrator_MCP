/**
 * ops_style.jsx - Style Operations
 * Part of Illustrator MCP SOC Framework
 * 
 * Provides handlers for:
 * - style_set_fill: Set fill color
 * - style_set_stroke: Set stroke color and width
 * - style_set_opacity: Set opacity
 * - style_remove_fill: Remove fill
 * - style_remove_stroke: Remove stroke
 * 
 * @requires ops_core (for registerOpHandler)
 * @version 1.0.0
 */

// ==================== Style Set Fill ====================

registerOpHandler("style_set_fill", function (params, targets, ctx) {
    if (targets.length === 0) {
        return { ok: true, data: { modified: 0 }, warnings: ["No targets to style"] };
    }

    var modified = 0;
    var warnings = [];

    // Parse color
    var color = null;
    if (params.r !== undefined || params.g !== undefined || params.b !== undefined) {
        color = new RGBColor();
        color.red = params.r || 0;
        color.green = params.g || 0;
        color.blue = params.b || 0;
    } else if (params.color) {
        color = new RGBColor();
        color.red = params.color.r || 0;
        color.green = params.color.g || 0;
        color.blue = params.color.b || 0;
    }

    if (!color) {
        return { ok: false, error: makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "Missing color params (r, g, b)", "apply") };
    }

    for (var i = 0; i < targets.length; i++) {
        try {
            targets[i].fillColor = color;
            targets[i].filled = true;
            modified++;
        } catch (e) {
            warnings.push("Failed to set fill on item " + i + ": " + e.message);
        }
    }

    return { ok: modified > 0, data: { modified: modified }, warnings: warnings };
});

// ==================== Style Set Stroke ====================

registerOpHandler("style_set_stroke", function (params, targets, ctx) {
    if (targets.length === 0) {
        return { ok: true, data: { modified: 0 }, warnings: ["No targets to style"] };
    }

    var modified = 0;
    var warnings = [];

    // Parse color
    var color = null;
    if (params.r !== undefined || params.g !== undefined || params.b !== undefined) {
        color = new RGBColor();
        color.red = params.r || 0;
        color.green = params.g || 0;
        color.blue = params.b || 0;
    } else if (params.color) {
        color = new RGBColor();
        color.red = params.color.r || 0;
        color.green = params.color.g || 0;
        color.blue = params.color.b || 0;
    }

    var strokeWidth = params.width || 1;

    for (var i = 0; i < targets.length; i++) {
        try {
            if (color) {
                targets[i].strokeColor = color;
            }
            targets[i].stroked = true;
            targets[i].strokeWidth = strokeWidth;
            modified++;
        } catch (e) {
            warnings.push("Failed to set stroke on item " + i + ": " + e.message);
        }
    }

    return { ok: modified > 0, data: { modified: modified }, warnings: warnings };
});

// ==================== Style Set Opacity ====================

registerOpHandler("style_set_opacity", function (params, targets, ctx) {
    if (targets.length === 0) {
        return { ok: true, data: { modified: 0 } };
    }

    var opacity = params.opacity !== undefined ? params.opacity : 100;
    // Clamp to Illustrator's valid range (0-100)
    if (opacity < 0) opacity = 0;
    if (opacity > 100) opacity = 100;
    var modified = 0;

    for (var i = 0; i < targets.length; i++) {
        try {
            targets[i].opacity = opacity;
            modified++;
        } catch (e) { }
    }

    return { ok: true, data: { modified: modified } };
});

// ==================== Style Remove Fill ====================

registerOpHandler("style_remove_fill", function (params, targets, ctx) {
    var modified = 0;
    for (var i = 0; i < targets.length; i++) {
        try {
            targets[i].filled = false;
            modified++;
        } catch (e) { }
    }
    return { ok: true, data: { modified: modified } };
});

// ==================== Style Remove Stroke ====================

registerOpHandler("style_remove_stroke", function (params, targets, ctx) {
    var modified = 0;
    for (var i = 0; i < targets.length; i++) {
        try {
            targets[i].stroked = false;
            modified++;
        } catch (e) { }
    }
    return { ok: true, data: { modified: modified } };
});
