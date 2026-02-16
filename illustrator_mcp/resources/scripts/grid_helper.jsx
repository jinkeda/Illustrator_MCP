/**
 * grid_helper.jsx — Grid-based element discovery
 *
 * Divides the active artboard into labeled cells (A1, B2, C3…)
 * for human-readable element targeting. Cells are in USER COORDS:
 * artboard-relative, y-down from top-left. This matches
 * normalizeRect(rect, doc, "user") in targets.jsx.
 *
 * @requires polyfills
 * @version 1.0.0
 */

// ==================== Grid Construction ====================

/**
 * Divide active artboard into a labeled grid.
 *
 * Labels: row = letter (A=top), col = number (1=left).
 * A 4×4 grid yields: A1 A2 A3 A4 / B1 B2 B3 B4 / C1…C4 / D1…D4.
 *
 * @param {number} [cols=4] - Grid columns (1–99)
 * @param {number} [rows=4] - Grid rows (1–26, A–Z)
 * @returns {Object} { cells: {A1: {x,y,width,height}, ...}, cols, rows, cellWidth, cellHeight }
 */
function artboardGrid(cols, rows) {
    cols = cols || 4;
    rows = rows || 4;
    if (rows < 1 || rows > 26) throw new Error("rows must be 1\u201326, got " + rows);
    if (cols < 1 || cols > 99) throw new Error("cols must be 1\u201399, got " + cols);

    var doc = app.activeDocument;
    var idx = doc.artboards.getActiveArtboardIndex();
    var ab = doc.artboards[idx].artboardRect; // [left, top, right, bottom]
    var abW = ab[2] - ab[0];  // right - left
    var abH = ab[1] - ab[3];  // top - bottom (positive because top > bottom in AI)
    if (abW <= 0 || abH <= 0) throw new Error("Invalid artboardRect: zero or negative size");

    var cw = abW / cols;
    var ch = abH / rows;

    // Cells in USER COORDS: artboard-relative, origin at top-left, y-down.
    // normalizeRect(cell, doc, "user") converts these to AI-space via:
    //   aiX = abLeft + x,  aiY = abTop - y
    var cells = {};
    for (var r = 0; r < rows; r++) {
        for (var c = 0; c < cols; c++) {
            var label = String.fromCharCode(65 + r) + (c + 1);
            cells[label] = { x: c * cw, y: r * ch, width: cw, height: ch };
        }
    }
    return { cells: cells, cols: cols, rows: rows, cellWidth: cw, cellHeight: ch };
}


// ==================== Element Discovery ====================

/**
 * Find all items whose geometry overlaps or falls within a grid cell.
 *
 * Returns compact discovery records (not raw PageItems) with a
 * deterministic sort: ascending y (top→bottom), then ascending x (left→right)
 * in user coords.
 *
 * @param {string} cellLabel - Grid cell label (e.g. "B2", case-insensitive)
 * @param {number} [cols=4]  - Grid columns
 * @param {number} [rows=4]  - Grid rows
 * @param {Object} [opts]    - Options: {mode: "containsCenter"|"intersects"}
 * @returns {Object} {cell, mode, items:[], summary:{}, total}
 */
function itemsInCell(cellLabel, cols, rows, opts) {
    cellLabel = (cellLabel || "").toUpperCase();
    opts = opts || {};
    var mode = opts.mode || "containsCenter";

    var grid = artboardGrid(cols || 4, rows || 4);
    var cell = grid.cells[cellLabel];
    if (!cell) throw new Error("Unknown grid cell: " + cellLabel);

    var doc = app.activeDocument;
    var abIdx = doc.artboards.getActiveArtboardIndex();
    var ab = doc.artboards[abIdx].artboardRect;
    var abLeft = ab[0], abTop = ab[1];

    // Convert cell from user coords to AI coords for comparison
    var cellL = abLeft + cell.x;
    var cellT = abTop - cell.y;              // AI top (highest y)
    var cellR = abLeft + cell.x + cell.width;
    var cellB = abTop - (cell.y + cell.height); // AI bottom (lowest y)

    // Collect all visible items across all visible layers
    var candidates = [];
    for (var li = 0; li < doc.layers.length; li++) {
        if (!doc.layers[li].visible) continue;
        _collectFromContainer(doc.layers[li], candidates);
    }

    // Filter by mode
    var matched = [];
    for (var i = 0; i < candidates.length; i++) {
        var item = candidates[i];
        var gb;
        try { gb = item.geometricBounds; } catch (e) { continue; } // [L, T, R, B]
        if (!gb || gb.length < 4) continue;

        var itemL = gb[0], itemT = gb[1], itemR = gb[2], itemB = gb[3];

        if (mode === "intersects") {
            // Axis-aligned overlap: any intersection with cell rect
            // AI coords: T > B (y-up), so overlap = itemR > cellL && itemL < cellR && itemT > cellB && itemB < cellT
            if (itemR > cellL && itemL < cellR && itemT > cellB && itemB < cellT) {
                matched.push(item);
            }
        } else {
            // containsCenter: item center inside cell rect
            var cx = (itemL + itemR) / 2;
            var cy = (itemT + itemB) / 2;
            if (cx >= cellL && cx <= cellR && cy <= cellT && cy >= cellB) {
                matched.push(item);
            }
        }
    }

    // Sort in user coords: ascending y (top→bottom) then ascending x (left→right)
    // In AI coords: descending top (higher top = more "up" = earlier), then ascending left
    matched.sort(function (a, b) {
        var aB = a.geometricBounds, bB = b.geometricBounds;
        var rowThreshold = 5;
        if (Math.abs(aB[1] - bB[1]) < rowThreshold) {
            return aB[0] - bB[0]; // Same row: sort by x (ascending left)
        }
        return bB[1] - aB[1]; // Different rows: higher top first (top→bottom in user coords)
    });

    // Build compact records
    var items = [];
    var summary = {};
    for (var mi = 0; mi < matched.length; mi++) {
        var m = matched[mi];
        var mgb = m.geometricBounds;
        var tn = m.typename || "Unknown";

        // Count by typename
        summary[tn] = (summary[tn] || 0) + 1;

        // Extract MCP ID from note if present
        var note = "";
        try { note = m.note || ""; } catch (e) { }

        var layerName = "";
        try { layerName = m.layer.name; } catch (e) { }

        items.push({
            typename: tn,
            name: m.name || "",
            note: note,
            bounds: [mgb[0], mgb[1], mgb[2], mgb[3]], // AI coords [L,T,R,B]
            center: [(mgb[0] + mgb[2]) / 2, (mgb[1] + mgb[3]) / 2],
            layer: layerName,
            index: mi
        });
    }

    return {
        cell: cellLabel,
        mode: mode,
        items: items,
        summary: summary,
        total: items.length
    };
}


// ==================== Internal Helpers ====================

/**
 * Recursively collect visible, non-guide items from a container.
 * @param {Layer|GroupItem} container
 * @param {Array} out - accumulator
 */
function _collectFromContainer(container, out) {
    if (!container || !container.pageItems) return;
    for (var i = 0; i < container.pageItems.length; i++) {
        var item = container.pageItems[i];
        // Skip hidden items
        try { if (item.hidden) continue; } catch (e) { }
        // Skip guides
        try { if (item.guides) continue; } catch (e) { }

        out.push(item);

        // Recurse into groups
        if (item.typename === "GroupItem") {
            _collectFromContainer(item, out);
        }
    }
}
