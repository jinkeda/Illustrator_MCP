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
 * Fit an item to a slot with contain or cover mode
 * @param {PageItem} item - Item to fit
 * @param {Object} slot - Slot with x, y, width, height
 * @param {string} mode - "contain" (fit inside) or "cover" (fill completely)
 */
function fitToSlot(item, slot, mode) {
    mode = mode || "contain";

    var bounds = getVisibleBounds(item);
    var itemW = bounds[2] - bounds[0];
    var itemH = Math.abs(bounds[1] - bounds[3]);

    if (itemW === 0 || itemH === 0) {
        return; // Can't scale empty item
    }

    var scale;
    if (mode === "cover") {
        // Scale to fill slot completely (may crop)
        scale = Math.max(slot.width / itemW, slot.height / itemH);
    } else {
        // Scale to fit inside slot (may have margins)
        scale = Math.min(slot.width / itemW, slot.height / itemH);
    }

    // Apply scale (percentage)
    item.resize(scale * 100, scale * 100);

    // Get new bounds after scaling
    var newBounds = getVisibleBounds(item);
    var newW = newBounds[2] - newBounds[0];
    var newH = Math.abs(newBounds[1] - newBounds[3]);

    // Center in slot
    // Position is top-left corner in Illustrator
    item.position = [
        slot.x + (slot.width - newW) / 2,
        slot.y - (slot.height - newH) / 2
    ];
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
