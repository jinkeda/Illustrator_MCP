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
 * - style_snapshot: Read computed style from targets (read-only)
 * - style_clone: Copy style from source to targets (mutating)
 * 
 * @requires ops_core (for registerOpHandler, makeError, ErrorCodes)
 * @requires mcp_id (for extractMcpId)
 * @requires heap (for heapResolve - used by style_clone)
 * @version 1.1.0
 */

// ==================== Shared Color Helpers ====================

/**
 * Clamp an RGB channel value to 0-255 (integer).
 * @param {number} v
 * @returns {number}
 */
function _clampChannel(v) {
    if (v < 0) return 0;
    if (v > 255) return 255;
    return Math.round(v);
}

/**
 * Parse color from canonical nested or compat flat params.
 *
 * Priority:  params[key] → flat r/g/b → null
 * Sentinels: false/null = "disable" (hard off, beats compat fallback)
 * Validation: strict for nested (empty object = error), lenient for flat (default 0)
 *
 * Available to ops_text.jsx via include load order.
 *
 * @param {Object} params - handler params
 * @param {string} key - "fill" or "stroke"
 * @returns {{ color: RGBColor|null, disable: boolean, error: string|null }}
 */
function _parseColorParam(params, key) {
    var src = params[key];

    // ── Sentinel: explicit disable ──
    if (src === false || src === null) {
        return { color: null, disable: true, error: null };
    }

    // ── Canonical nested: strict validation ──
    if (src && typeof src === "object") {
        if (src.r == null && src.g == null && src.b == null) {
            return {
                color: null, disable: false,
                error: key + " object provided but missing r/g/b channels"
            };
        }
        var c = new RGBColor();
        c.red = _clampChannel(src.r != null ? src.r : 0);
        c.green = _clampChannel(src.g != null ? src.g : 0);
        c.blue = _clampChannel(src.b != null ? src.b : 0);
        return { color: c, disable: false, error: null };
    }

    // ── Compat flat: lenient (default 0) ──
    if (params.r != null || params.g != null || params.b != null) {
        var c2 = new RGBColor();
        c2.red = _clampChannel(params.r != null ? params.r : 0);
        c2.green = _clampChannel(params.g != null ? params.g : 0);
        c2.blue = _clampChannel(params.b != null ? params.b : 0);
        return { color: c2, disable: false, error: null };
    }

    return { color: null, disable: false, error: null };
}

// ==================== Style Set Fill ====================

registerOpHandler("style_set_fill", function (params, targets, ctx) {
    if (targets.length === 0) {
        return { ok: true, data: { modified: 0 }, warnings: ["No targets to style"] };
    }

    var parsed = _parseColorParam(params, "fill");

    // Disable sentinel: remove fill
    if (parsed.disable) {
        var removed = 0;
        for (var d = 0; d < targets.length; d++) {
            try { targets[d].filled = false; removed++; } catch (e) { }
        }
        return { ok: true, data: { modified: removed } };
    }

    // Validation error (e.g., empty object)
    if (parsed.error) {
        return makeError(ErrorCodes.V_INVALID_PARAM_VALUE || "V009", parsed.error, "validate");
    }

    // No color provided
    if (!parsed.color) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM,
            "Missing color: use fill:{r,g,b} or flat r,g,b", "validate");
    }

    var modified = 0;
    var warnings = [];

    for (var i = 0; i < targets.length; i++) {
        try {
            targets[i].fillColor = parsed.color;
            targets[i].filled = true;
            modified++;
        } catch (e) {
            warnings.push("Failed to set fill on item " + i + ": " + e.message);
        }
    }

    return { ok: true, data: { modified: modified }, warnings: warnings };
});

// ==================== Style Set Stroke ====================

registerOpHandler("style_set_stroke", function (params, targets, ctx) {
    if (targets.length === 0) {
        return { ok: true, data: { modified: 0 }, warnings: ["No targets to style"] };
    }

    var parsed = _parseColorParam(params, "stroke");

    // Disable sentinel: remove stroke
    if (parsed.disable) {
        var removed = 0;
        for (var d = 0; d < targets.length; d++) {
            try { targets[d].stroked = false; removed++; } catch (e) { }
        }
        return { ok: true, data: { modified: removed } };
    }

    // Validation error
    if (parsed.error) {
        return makeError(ErrorCodes.V_INVALID_PARAM_VALUE || "V009", parsed.error, "validate");
    }

    // Stroke width: nested > flat > default  (use != null so 0 is valid)
    var strokeWidth = 1; // default
    if (params.stroke && typeof params.stroke === "object" && params.stroke.width != null) {
        strokeWidth = params.stroke.width;
    } else if (params.width != null) {
        strokeWidth = params.width;
    }

    var modified = 0;
    var warnings = [];

    for (var i = 0; i < targets.length; i++) {
        try {
            if (parsed.color) {
                targets[i].strokeColor = parsed.color;
            }
            targets[i].stroked = true;
            targets[i].strokeWidth = strokeWidth;
            modified++;
        } catch (e) {
            warnings.push("Failed to set stroke on item " + i + ": " + e.message);
        }
    }

    return { ok: true, data: { modified: modified }, warnings: warnings };
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

// ==================== Style Helpers ====================

/**
 * Serialize an Illustrator color object to a portable JSON descriptor.
 * Handles RGB, CMYK, Spot, Gradient, Pattern, and NoColor.
 *
 * @param {Color} colorObj - Illustrator color object
 * @param {boolean} isFilled - Whether the item has fill/stroke enabled
 * @returns {Object} {type: "rgb"|"cmyk"|"spot"|"gradient"|"pattern"|"none", ...}
 */
function _serializeColor(colorObj, isFilled) {
    if (!isFilled || !colorObj) return { type: "none" };

    var tn = "";
    try { tn = colorObj.typename || ""; } catch (e) { return { type: "unknown" }; }

    switch (tn) {
        case "RGBColor":
            return {
                type: "rgb",
                r: Math.round(colorObj.red),
                g: Math.round(colorObj.green),
                b: Math.round(colorObj.blue)
            };
        case "CMYKColor":
            return {
                type: "cmyk",
                c: Math.round(colorObj.cyan * 10) / 10,
                m: Math.round(colorObj.magenta * 10) / 10,
                y: Math.round(colorObj.yellow * 10) / 10,
                k: Math.round(colorObj.black * 10) / 10
            };
        case "SpotColor":
            return {
                type: "spot",
                name: colorObj.spot ? colorObj.spot.name : "unknown",
                tint: Math.round(colorObj.tint * 10) / 10
            };
        case "GradientColor":
            return { type: "gradient" };
        case "PatternColor":
            return { type: "pattern" };
        case "NoColor":
            return { type: "none" };
        default:
            return { type: "unknown" };
    }
}

/**
 * Check if a TextFrame has uniform character attributes.
 * Compares first and last character's font name, font size, and fill color.
 *
 * @param {TextFrame} tf - TextFrame to check
 * @returns {boolean} true if all characters share the same style
 */
function _isTextUniform(tf) {
    try {
        var chars = tf.characters;
        if (chars.length <= 1) return true;

        var first = chars[0].characterAttributes;
        var last = chars[chars.length - 1].characterAttributes;

        // Compare font name
        if (first.textFont.name !== last.textFont.name) return false;
        // Compare font size
        if (Math.abs(first.size - last.size) > 0.01) return false;
        // Compare fill color (RGB only for simplicity)
        try {
            var fc1 = first.fillColor;
            var fc2 = last.fillColor;
            if (fc1.typename !== fc2.typename) return false;
            if (fc1.typename === "RGBColor") {
                if (Math.abs(fc1.red - fc2.red) > 1 ||
                    Math.abs(fc1.green - fc2.green) > 1 ||
                    Math.abs(fc1.blue - fc2.blue) > 1) return false;
            }
        } catch (e) { /* color comparison failed, assume uniform */ }

        return true;
    } catch (e) {
        return true; // default to uniform if inspection fails
    }
}

/**
 * Serialize text style from a TextFrame.
 * Returns full attributes if uniform, or {uniform: false} if mixed formatting.
 *
 * @param {TextFrame} tf - TextFrame to extract style from
 * @returns {Object} {uniform, fontName?, fontSize?, fill?, tracking?, leading?, justification?}
 */
function _serializeTextStyle(tf) {
    if (!_isTextUniform(tf)) {
        return { uniform: false };
    }

    var result = { uniform: true };
    try {
        var ca = tf.characters[0].characterAttributes;
        result.fontName = ca.textFont.name;
        result.fontSize = ca.size;
        result.fill = _serializeColor(ca.fillColor, true);
        try { result.tracking = ca.tracking; } catch (e) { }
        try { result.leading = ca.leading; } catch (e) { }
    } catch (e) {
        return { uniform: true, error: e.message };
    }

    // Paragraph justification (from first paragraph)
    try {
        var pj = tf.paragraphs[0].justification;
        if (pj === Justification.LEFT) result.justification = "left";
        else if (pj === Justification.CENTER) result.justification = "center";
        else if (pj === Justification.RIGHT) result.justification = "right";
        else if (pj === Justification.FULLJUSTIFYLASTLINELEFT) result.justification = "justify";
        else result.justification = "left";
    } catch (e) { }

    return result;
}

// ==================== Style Snapshot (Read-Only) ====================

/**
 * Extract computed style from targeted items.
 * Returns structured JSON with fill, stroke, opacity, and text attributes.
 *
 * v1 scope: single fill + single stroke only. Gradient/pattern fills
 * are reported but not fully serialized. Appearance stacks (multiple
 * fills/strokes) cannot be detected via scripting — we serialize what
 * .fillColor/.strokeColor return.
 */
registerOpHandler("style_snapshot", function (params, targets, ctx) {
    if (targets.length === 0) {
        return { ok: true, data: { items: [] }, warnings: ["No targets to snapshot"] };
    }

    var items = [];
    var warnings = [];

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];
        var entry = {
            type: item.typename
        };

        // Extract MCP ID
        try {
            if (typeof extractMcpId === "function" && item.note) {
                entry.id = extractMcpId(item.note);
            }
        } catch (e) { }

        // Fill
        try {
            entry.fill = _serializeColor(item.fillColor, item.filled);
            if (entry.fill.type === "gradient") {
                warnings.push("Item " + (entry.id || i) + ": gradient fill — summary only");
            }
        } catch (e) {
            entry.fill = { type: "unknown", error: e.message };
        }

        // Stroke
        try {
            entry.stroke = _serializeColor(item.strokeColor, item.stroked);
            if (item.stroked) {
                entry.strokeWidth = Math.round(item.strokeWidth * 100) / 100;
            }
            if (entry.stroke.type === "gradient") {
                warnings.push("Item " + (entry.id || i) + ": gradient stroke — summary only");
            }
        } catch (e) {
            entry.stroke = { type: "unknown", error: e.message };
        }

        // Opacity
        try { entry.opacity = Math.round(item.opacity * 100) / 100; } catch (e) { }

        // Text attributes (TextFrame only)
        if (item.typename === "TextFrame") {
            entry.text = _serializeTextStyle(item);
            if (!entry.text.uniform) {
                warnings.push("Item " + (entry.id || i) + ": mixed text formatting — text attrs omitted");
            }
        }

        items.push(entry);
    }

    return { ok: true, data: { items: items }, warnings: warnings };
});

// ==================== Style Clone (Mutating) ====================

/**
 * Copy computed style from a single source item to all targets.
 * Eyedropper tool equivalent.
 *
 * @param {Object} params.from - MCP ID of source item (required)
 * @param {Array} [params.properties] - Optional subset: ["fill","stroke","opacity","text"]
 *   Default: all compatible properties
 */
registerOpHandler("style_clone", function (params, targets, ctx) {
    // Validate: 'from' is required
    if (!params.from) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM,
            "style_clone requires 'from' param (source MCP ID)", "validate");
    }

    if (targets.length === 0) {
        return { ok: true, data: { modified: 0 }, warnings: ["No targets to clone to"] };
    }

    var doc = ctx.doc;
    var warnings = [];

    // --- Resolve source item ---
    var source = null;
    if (typeof heapResolve === "function") {
        source = heapResolve(params.from, doc);
    }
    if (!source) {
        return makeError(ErrorCodes.V_INVALID_TARGETS,
            "Source item not found: " + params.from, "validate");
    }

    // --- Determine which properties to clone ---
    var VALID_PROPS = { fill: true, stroke: true, opacity: true, text: true };
    var propsToClone = {};
    if (params.properties && params.properties.length > 0) {
        for (var p = 0; p < params.properties.length; p++) {
            var pName = params.properties[p];
            if (VALID_PROPS[pName]) {
                propsToClone[pName] = true;
            } else {
                warnings.push("Unknown property: " + pName + " — skipped");
            }
        }
    } else {
        // Default: all properties
        propsToClone = { fill: true, stroke: true, opacity: true, text: true };
    }

    // --- Snapshot source style ---
    var srcFilled = false;
    var srcFillColor = null;
    var srcStroked = false;
    var srcStrokeColor = null;
    var srcStrokeWidth = 1;
    var srcOpacity = 100;
    var srcIsText = (source.typename === "TextFrame");
    var srcTextUniform = false;
    var srcTextAttrs = null;

    try { srcFilled = source.filled; } catch (e) { }
    try { srcFillColor = source.fillColor; } catch (e) { }
    try { srcStroked = source.stroked; } catch (e) { }
    try { srcStrokeColor = source.strokeColor; } catch (e) { }
    try { srcStrokeWidth = source.strokeWidth; } catch (e) { }
    try { srcOpacity = source.opacity; } catch (e) { }

    // Check for gradient/pattern fills — warn but still clone the color object
    try {
        if (srcFillColor && srcFillColor.typename === "GradientColor") {
            warnings.push("Source has gradient fill — clone may not reproduce exactly");
        }
        if (srcStrokeColor && srcStrokeColor.typename === "GradientColor") {
            warnings.push("Source has gradient stroke — clone may not reproduce exactly");
        }
    } catch (e) { }

    // Text style from source
    if (srcIsText && propsToClone.text) {
        srcTextUniform = _isTextUniform(source);
        if (!srcTextUniform) {
            warnings.push("Source text has mixed formatting — text attrs skipped");
        } else {
            try {
                srcTextAttrs = {};
                var ca = source.characters[0].characterAttributes;
                srcTextAttrs.textFont = ca.textFont;
                srcTextAttrs.size = ca.size;
                srcTextAttrs.fillColor = ca.fillColor;
                try { srcTextAttrs.tracking = ca.tracking; } catch (e) { }
            } catch (e) {
                warnings.push("Failed to read source text attrs: " + e.message);
                srcTextAttrs = null;
            }
        }
    }

    // --- Apply to targets ---
    var modified = 0;

    for (var i = 0; i < targets.length; i++) {
        var target = targets[i];
        var applied = false;

        try {
            // Fill
            if (propsToClone.fill) {
                target.filled = srcFilled;
                if (srcFilled && srcFillColor) {
                    target.fillColor = srcFillColor;
                }
                applied = true;
            }

            // Stroke
            if (propsToClone.stroke) {
                target.stroked = srcStroked;
                if (srcStroked && srcStrokeColor) {
                    target.strokeColor = srcStrokeColor;
                }
                target.strokeWidth = srcStrokeWidth;
                applied = true;
            }

            // Opacity
            if (propsToClone.opacity) {
                target.opacity = srcOpacity;
                applied = true;
            }

            // Text (TextFrame → TextFrame only)
            if (propsToClone.text && srcTextAttrs) {
                if (target.typename === "TextFrame") {
                    var tr = target.textRange;
                    if (srcTextAttrs.textFont) {
                        tr.characterAttributes.textFont = srcTextAttrs.textFont;
                    }
                    if (srcTextAttrs.size) {
                        tr.characterAttributes.size = srcTextAttrs.size;
                    }
                    if (srcTextAttrs.fillColor) {
                        tr.characterAttributes.fillColor = srcTextAttrs.fillColor;
                    }
                    if (srcTextAttrs.tracking !== undefined) {
                        tr.characterAttributes.tracking = srcTextAttrs.tracking;
                    }
                    applied = true;
                } else {
                    warnings.push("Target " + i + " is " + target.typename + " — text attrs skipped");
                }
            }

            if (applied) modified++;
        } catch (e) {
            warnings.push("Failed on target " + i + ": " + e.message);
        }
    }

    return {
        ok: modified > 0 || targets.length === 0,
        data: { modified: modified, total: targets.length },
        warnings: warnings
    };
});

// ==================== Style Set Gradient ====================

/**
 * Apply a gradient fill to targeted items.
 *
 * @param {Object} params
 * @param {string} params.type - "linear" or "radial"
 * @param {Array} params.stops - [{r,g,b,pos}, ...] — at least 2 stops required
 * @param {number} [params.angle] - Gradient angle in degrees (default 0)
 * @param {Object} [params.origin] - {x, y} gradient origin
 * @param {number} [params.length] - Gradient length
 * @param {string} [params.name] - Gradient name for reuse (same name = reuse existing)
 */
registerOpHandler("style_set_gradient", function (params, targets, ctx) {
    var doc = ctx.doc;

    // Validate: at least 2 stops required (prevents div-by-zero in rampPoint calc)
    if (!params.stops || params.stops.length < 2) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM,
            "Gradient requires at least 2 stops", "apply");
    }

    if (targets.length === 0) {
        return { ok: true, data: { modified: 0 }, warnings: ["No targets for gradient"] };
    }

    var gradType = params.type === "radial" ? GradientType.RADIAL : GradientType.LINEAR;
    var gradName = params.name || ("MCP_grad_" + generateUUID().substr(0, 8));

    // Reuse existing gradient by name (prevents document resource leak)
    var gradient = null;
    try { gradient = doc.gradients.getByName(gradName); } catch (e) { /* not found */ }
    if (!gradient) {
        gradient = doc.gradients.add();
        gradient.name = gradName;
    }
    gradient.type = gradType;

    // Configure stops — add extras if needed, remove extras
    while (gradient.gradientStops.length < params.stops.length) {
        gradient.gradientStops.add();
    }
    // Remove excess stops (iterate in reverse)
    while (gradient.gradientStops.length > params.stops.length) {
        gradient.gradientStops[gradient.gradientStops.length - 1].remove();
    }

    for (var s = 0; s < params.stops.length; s++) {
        var c = new RGBColor();
        c.red = params.stops[s].r || 0;
        c.green = params.stops[s].g || 0;
        c.blue = params.stops[s].b || 0;
        gradient.gradientStops[s].color = c;
        gradient.gradientStops[s].rampPoint = params.stops[s].pos !== undefined
            ? params.stops[s].pos
            : Math.round(s * 100 / (params.stops.length - 1));
    }

    var modified = 0;
    var warnings = [];
    for (var i = 0; i < targets.length; i++) {
        try {
            var gc = new GradientColor();
            gc.gradient = gradient;
            gc.angle = params.angle || 0;
            if (params.origin) gc.origin = [params.origin.x || 0, params.origin.y || 0];
            if (params.length) gc.length = params.length;
            targets[i].fillColor = gc;
            targets[i].filled = true;
            modified++;
        } catch (e) {
            warnings.push("Failed to apply gradient to item " + i + ": " + e.message);
        }
    }

    return {
        ok: true,
        data: { modified: modified, gradientName: gradName },
        warnings: warnings
    };
});
