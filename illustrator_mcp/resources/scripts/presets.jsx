/**
 * presets.jsx - Layout Presets Library v1.0
 * Part of Illustrator MCP Standard Library
 * 
 * Pre-defined grid layouts with slot geometry calculation.
 * 
 * @exports PRESETS, getPreset, computeSlotGeometry, fitToSlot, applyPreset
 * @dependencies geometry
 */

/**
 * Pre-defined layout presets
 */
var PRESETS = {
    "2x2": {
        name: "2x2 Grid",
        grid: { rows: 2, cols: 2 },
        margins: { top: 20, right: 20, bottom: 20, left: 20 },
        gutter: 15
    },
    "3x1": {
        name: "3 Horizontal",
        grid: { rows: 1, cols: 3 },
        margins: { top: 20, right: 20, bottom: 20, left: 20 },
        gutter: 15
    },
    "1x3": {
        name: "3 Vertical",
        grid: { rows: 3, cols: 1 },
        margins: { top: 20, right: 20, bottom: 20, left: 20 },
        gutter: 15
    },
    "2x3": {
        name: "2x3 Grid",
        grid: { rows: 2, cols: 3 },
        margins: { top: 20, right: 20, bottom: 20, left: 20 },
        gutter: 15
    },
    "3x2": {
        name: "3x2 Grid",
        grid: { rows: 3, cols: 2 },
        margins: { top: 20, right: 20, bottom: 20, left: 20 },
        gutter: 15
    },
    "1x2": {
        name: "2 Horizontal",
        grid: { rows: 1, cols: 2 },
        margins: { top: 20, right: 20, bottom: 20, left: 20 },
        gutter: 15
    },
    "2x1": {
        name: "2 Vertical",
        grid: { rows: 2, cols: 1 },
        margins: { top: 20, right: 20, bottom: 20, left: 20 },
        gutter: 15
    }
};

/**
 * Get a preset by name
 * @param {string} name - Preset name (e.g., "2x2")
 * @returns {Object} Preset definition
 * @throws {Error} If preset not found
 */
function getPreset(name) {
    if (!PRESETS[name]) {
        var available = [];
        for (var key in PRESETS) {
            if (PRESETS.hasOwnProperty(key)) {
                available.push(key);
            }
        }
        throw new Error("Unknown preset: " + name + ". Available: " + available.join(", "));
    }
    return PRESETS[name];
}

/**
 * Compute slot geometry for a preset on an artboard
 * @param {string} presetName - Name of preset
 * @param {Array} artboardRect - Artboard bounds [left, top, right, bottom]
 * @returns {Object} Geometry with slots array
 */
function computeSlotGeometry(presetName, artboardRect) {
    var preset = getPreset(presetName);
    var m = preset.margins;
    var g = preset.gutter;
    var rows = preset.grid.rows;
    var cols = preset.grid.cols;

    var left = artboardRect[0];
    var top = artboardRect[1];
    var right = artboardRect[2];
    var bottom = artboardRect[3];

    // Calculate available space
    var availW = (right - left) - m.left - m.right;
    var availH = Math.abs(top - bottom) - m.top - m.bottom;

    // Calculate cell size
    var cellW = (availW - (cols - 1) * g) / cols;
    var cellH = (availH - (rows - 1) * g) / rows;

    var slots = [];
    for (var row = 0; row < rows; row++) {
        for (var col = 0; col < cols; col++) {
            var x = left + m.left + col * (cellW + g);
            // Y is positive up in Illustrator, so we subtract from top
            var y = top - m.top - row * (cellH + g);

            slots.push({
                index: row * cols + col,
                row: row,
                col: col,
                x: x,
                y: y,
                width: cellW,
                height: cellH
            });
        }
    }

    return {
        preset: presetName,
        presetName: preset.name,
        grid: { rows: rows, cols: cols },
        cellSize: { width: cellW, height: cellH },
        artboard: {
            left: left,
            top: top,
            right: right,
            bottom: bottom
        },
        slots: slots
    };
}

/**
 * Fit an item to a slot with contain or cover mode.
 * 
 * IDEMPOTENT: Computes final position in absolute artboard coordinates.
 * Running this function multiple times produces the same result.
 * 
 * CLIPPED GROUPS: Uses getVisibleBounds() which returns the mask bounds
 * for clipped groups, ensuring predictable sizing and positioning.
 * 
 * @param {PageItem} item - Item to fit
 * @param {Object} slot - Slot with x, y, width, height (y is top edge)
 * @param {string} mode - "contain" (fit inside) or "cover" (fill completely)
 * @returns {Object} Result with applied scale and position
 */
function fitToSlot(item, slot, mode) {
    mode = mode || "contain";

    // 1. Get current visible bounds (handles clipped groups correctly)
    var bounds = getVisibleBounds(item);
    var currentLeft = bounds[0];
    var currentTop = bounds[1];
    var currentRight = bounds[2];
    var currentBottom = bounds[3];

    var currentW = currentRight - currentLeft;
    var currentH = currentTop - currentBottom;  // Top > Bottom in Illustrator coords

    if (currentW <= 0 || currentH <= 0) {
        return { error: "Item has zero dimensions", scaled: false };
    }

    // 2. Compute target center in artboard coordinates (absolute, idempotent)
    //    Slot: x=left edge, y=top edge, width, height
    var targetCenterX = slot.x + slot.width / 2;
    var targetCenterY = slot.y - slot.height / 2;  // Y decreases downward

    // 3. Compute scale factor
    var scale;
    if (mode === "cover") {
        // Scale to fill slot completely (may extend beyond slot)
        scale = Math.max(slot.width / currentW, slot.height / currentH);
    } else {
        // Scale to fit inside slot (may have margins)
        scale = Math.min(slot.width / currentW, slot.height / currentH);
    }

    // 4. Compute final dimensions after scaling
    var finalW = currentW * scale;
    var finalH = currentH * scale;

    // 5. Compute where the visible bounds should be after positioning
    //    (centered in slot)
    var targetLeft = targetCenterX - finalW / 2;
    var targetTop = targetCenterY + finalH / 2;

    // 6. Apply scale (percentage-based, relative to current size)
    //    Note: resize() scales relative to current, not absolute
    item.resize(scale * 100, scale * 100);

    // 7. Get new visible bounds after scaling
    var newBounds = getVisibleBounds(item);
    var newLeft = newBounds[0];
    var newTop = newBounds[1];

    // 8. Compute position delta: difference between current anchor and visible bounds
    //    item.position is the anchor point (usually top-left of bounding box)
    //    We need to move anchor such that visible bounds land at target
    var currentAnchor = item.position;  // [x, y]

    // Delta from anchor to visible bounds top-left
    var anchorToVisibleX = newLeft - currentAnchor[0];
    var anchorToVisibleY = newTop - currentAnchor[1];

    // 9. Set new anchor position (idempotent - uses absolute target coords)
    item.position = [
        targetLeft - anchorToVisibleX,
        targetTop - anchorToVisibleY
    ];

    return {
        scaled: true,
        scale: scale,
        finalBounds: {
            left: targetLeft,
            top: targetTop,
            width: finalW,
            height: finalH
        },
        slotCenter: { x: targetCenterX, y: targetCenterY }
    };
}

/**
 * Apply a preset layout to an array of items
 * @param {string} presetName - Name of preset to apply
 * @param {Array} items - Array of PageItems to arrange
 * @param {string} mode - "contain" or "cover"
 * @returns {Object} Result with arranged items and overflow count
 */
function applyPreset(presetName, items, mode) {
    if (!app.documents.length) {
        return { error: "No document open", arranged: [], overflow: 0 };
    }

    var doc = app.activeDocument;
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()];
    var geo = computeSlotGeometry(presetName, ab.artboardRect);

    var results = [];
    var count = Math.min(items.length, geo.slots.length);

    for (var i = 0; i < count; i++) {
        var item = items[i];
        var slot = geo.slots[i];

        fitToSlot(item, slot, mode);

        results.push({
            item: item.name || "Unnamed",
            slotIndex: i,
            row: slot.row,
            col: slot.col,
            position: { x: item.position[0], y: item.position[1] }
        });
    }

    return {
        preset: presetName,
        mode: mode || "contain",
        arranged: results,
        overflow: items.length > geo.slots.length ? items.length - geo.slots.length : 0,
        totalSlots: geo.slots.length
    };
}

/**
 * List all available presets
 * @returns {Array} Array of preset names and descriptions
 */
function listPresets() {
    var list = [];
    for (var key in PRESETS) {
        if (PRESETS.hasOwnProperty(key)) {
            list.push({
                id: key,
                name: PRESETS[key].name,
                grid: PRESETS[key].grid
            });
        }
    }
    return list;
}

// ============================================================================
// COLOR PALETTES
// ============================================================================

/**
 * Color palettes for scientific figures and design.
 *
 * Usage:
 *   var color = getColor('okabe_ito', 0);  // First Okabe-Ito color
 *   shape.fillColor = color;
 *
 * Palettes:
 *   - okabe_ito: Colorblind-safe palette (8 colors) - RECOMMENDED for publications
 *   - nature: Nature journal style (6 colors)
 *   - tol_muted: Paul Tol's muted palette (7 colors)
 *   - science_minimal: Minimal black/blue/gray (3 colors)
 *   - microsoft: Microsoft logo colors (4 colors)
 *   - google: Google brand colors (4 colors)
 *   - grayscale: Black to white gradient (4 colors)
 *   - viridis: Perceptually uniform colormap (6 colors)
 */
var COLOR_PALETTES = {
    // Okabe-Ito colorblind-safe palette
    // Reference: https://jfly.uni-koeln.de/color/
    okabe_ito: [
        { r: 0,   g: 114, b: 178, name: "blue" },
        { r: 230, g: 159, b: 0,   name: "orange" },
        { r: 0,   g: 158, b: 115, name: "bluish_green" },
        { r: 240, g: 228, b: 66,  name: "yellow" },
        { r: 86,  g: 180, b: 233, name: "sky_blue" },
        { r: 213, g: 94,  b: 0,   name: "vermillion" },
        { r: 204, g: 121, b: 167, name: "reddish_purple" },
        { r: 0,   g: 0,   b: 0,   name: "black" }
    ],

    // Nature journal style
    nature: [
        { r: 31,  g: 119, b: 180, name: "blue" },
        { r: 255, g: 127, b: 14,  name: "orange" },
        { r: 44,  g: 160, b: 44,  name: "green" },
        { r: 214, g: 39,  b: 40,  name: "red" },
        { r: 148, g: 103, b: 189, name: "purple" },
        { r: 127, g: 127, b: 127, name: "gray" }
    ],

    // Paul Tol's muted palette
    // Reference: https://personal.sron.nl/~pault/
    tol_muted: [
        { r: 68,  g: 119, b: 170, name: "blue" },
        { r: 221, g: 204, b: 119, name: "sand" },
        { r: 34,  g: 136, b: 51,  name: "green" },
        { r: 204, g: 102, b: 119, name: "rose" },
        { r: 136, g: 34,  b: 85,  name: "purple" },
        { r: 170, g: 68,  b: 153, name: "violet" },
        { r: 68,  g: 170, b: 153, name: "teal" }
    ],

    // Minimal scientific palette
    science_minimal: [
        { r: 0,   g: 0,   b: 0,   name: "black" },
        { r: 0,   g: 90,  b: 160, name: "dark_blue" },
        { r: 150, g: 150, b: 150, name: "gray" }
    ],

    // Microsoft brand colors
    microsoft: [
        { r: 243, g: 83,  b: 37,  name: "red" },
        { r: 129, g: 188, b: 6,   name: "green" },
        { r: 5,   g: 166, b: 240, name: "blue" },
        { r: 255, g: 186, b: 8,   name: "yellow" }
    ],

    // Google brand colors
    google: [
        { r: 66,  g: 133, b: 244, name: "blue" },
        { r: 234, g: 67,  b: 53,  name: "red" },
        { r: 251, g: 188, b: 5,   name: "yellow" },
        { r: 52,  g: 168, b: 83,  name: "green" }
    ],

    // Grayscale
    grayscale: [
        { r: 0,   g: 0,   b: 0,   name: "black" },
        { r: 85,  g: 85,  b: 85,  name: "dark_gray" },
        { r: 170, g: 170, b: 170, name: "light_gray" },
        { r: 255, g: 255, b: 255, name: "white" }
    ],

    // Viridis colormap (perceptually uniform)
    viridis: [
        { r: 68,  g: 1,   b: 84,  name: "dark_purple" },
        { r: 59,  g: 82,  b: 139, name: "blue_purple" },
        { r: 33,  g: 145, b: 140, name: "teal" },
        { r: 94,  g: 201, b: 98,  name: "green" },
        { r: 189, g: 223, b: 38,  name: "yellow_green" },
        { r: 253, g: 231, b: 37,  name: "yellow" }
    ],

    // Categorical palette for many categories
    category10: [
        { r: 31,  g: 119, b: 180, name: "blue" },
        { r: 255, g: 127, b: 14,  name: "orange" },
        { r: 44,  g: 160, b: 44,  name: "green" },
        { r: 214, g: 39,  b: 40,  name: "red" },
        { r: 148, g: 103, b: 189, name: "purple" },
        { r: 140, g: 86,  b: 75,  name: "brown" },
        { r: 227, g: 119, b: 194, name: "pink" },
        { r: 127, g: 127, b: 127, name: "gray" },
        { r: 188, g: 189, b: 34,  name: "olive" },
        { r: 23,  g: 190, b: 207, name: "cyan" }
    ]
};

/**
 * Get a color from a palette as an RGBColor object.
 *
 * @param {string} paletteName - Name of the palette (e.g., 'okabe_ito')
 * @param {number} index - Color index (wraps around if > palette length)
 * @returns {RGBColor} Illustrator RGBColor object
 *
 * @example
 * var color = getColor('okabe_ito', 0);
 * rect.fillColor = color;
 */
function getColor(paletteName, index) {
    var palette = COLOR_PALETTES[paletteName];
    if (!palette) {
        throw new Error("Unknown palette: " + paletteName +
            ". Available: " + listPalettes().join(", "));
    }

    // Wrap index if out of bounds
    var idx = index % palette.length;
    var c = palette[idx];

    var color = new RGBColor();
    color.red = c.r;
    color.green = c.g;
    color.blue = c.b;
    return color;
}

/**
 * Get color definition (r, g, b, name) from a palette.
 *
 * @param {string} paletteName - Name of the palette
 * @param {number} index - Color index
 * @returns {Object} Color definition {r, g, b, name}
 */
function getColorDef(paletteName, index) {
    var palette = COLOR_PALETTES[paletteName];
    if (!palette) {
        throw new Error("Unknown palette: " + paletteName);
    }
    return palette[index % palette.length];
}

/**
 * Get all colors from a palette as RGBColor objects.
 *
 * @param {string} paletteName - Name of the palette
 * @returns {Array<RGBColor>} Array of RGBColor objects
 */
function getPalette(paletteName) {
    var palette = COLOR_PALETTES[paletteName];
    if (!palette) {
        throw new Error("Unknown palette: " + paletteName);
    }

    var colors = [];
    for (var i = 0; i < palette.length; i++) {
        colors.push(getColor(paletteName, i));
    }
    return colors;
}

/**
 * List all available palette names.
 *
 * @returns {Array<string>} Array of palette names
 */
function listPalettes() {
    var names = [];
    for (var key in COLOR_PALETTES) {
        if (COLOR_PALETTES.hasOwnProperty(key)) {
            names.push(key);
        }
    }
    return names;
}

/**
 * Get palette info including all colors.
 *
 * @param {string} paletteName - Name of the palette
 * @returns {Object} Palette info with colors array
 */
function getPaletteInfo(paletteName) {
    var palette = COLOR_PALETTES[paletteName];
    if (!palette) {
        throw new Error("Unknown palette: " + paletteName);
    }

    return {
        name: paletteName,
        count: palette.length,
        colors: palette
    };
}

/**
 * Apply colors from a palette to an array of items.
 *
 * @param {Array<PageItem>} items - Items to color
 * @param {string} paletteName - Name of the palette
 * @param {Object} [options] - Options
 * @param {boolean} [options.fill=true] - Apply to fill
 * @param {boolean} [options.stroke=false] - Apply to stroke
 * @returns {number} Number of items colored
 *
 * @example
 * applyPaletteToItems(doc.selection, 'okabe_ito');
 */
function applyPaletteToItems(items, paletteName, options) {
    options = options || {};
    var applyFill = options.fill !== false;  // default true
    var applyStroke = options.stroke === true;  // default false

    var palette = COLOR_PALETTES[paletteName];
    if (!palette) {
        throw new Error("Unknown palette: " + paletteName);
    }

    var count = 0;
    for (var i = 0; i < items.length; i++) {
        var item = items[i];
        var color = getColor(paletteName, i);

        if (applyFill && item.fillColor !== undefined) {
            item.fillColor = color;
        }
        if (applyStroke && item.strokeColor !== undefined) {
            item.strokeColor = color;
        }
        count++;
    }
    return count;
}
