/**
 * layout.jsx - Grid and layout engine
 * Part of Illustrator MCP Standard Library
 * 
 * @requires geometry.jsx
 * @optional selection.jsx
 */

// Dependency metadata for programmatic checking
var LAYOUT_DEPENDENCIES = {
    required: ['geometry'],
    optional: ['selection']
};

// Check required dependencies
(function checkDependencies() {
    if (typeof getVisibleInfo === 'undefined') {
        throw new Error('layout.jsx requires geometry.jsx to be loaded first. ' +
            'Ensure geometry.jsx is executed before layout.jsx.');
    }
    if (typeof mmToPoints === 'undefined') {
        throw new Error('layout.jsx requires mmToPoints from geometry.jsx.');
    }
})();

/**
 * Arrange items into a grid.
 * 
 * @param {Array<PageItem>} items - Array of items to arrange
 * @param {number} columns - Number of columns
 * @param {number} spacingMm - Spacing between items in mm
 * @returns {void}
 */
function arrangeInGrid(items, columns, spacingMm) {
    if (!items || items.length === 0) return;

    var spacingPt = mmToPoints(spacingMm);
    var startX = null;
    var startY = null;

    // Use the first item's position as the anchor (Top-Left)
    var firstInfo = getVisibleInfo(items[0]);
    startX = firstInfo.left;
    startY = firstInfo.top;

    // We track row heights to know where to place the next row
    // But for a simple grid, we often want uniform row heights or "masonry"?
    // "Grid" usually implies row alignment.
    // Let's assume standard grid: Max height of previous row determines next row Y.

    // However, scientific panels might have varying sizes.
    // Robust approach:
    // 1. Calculate row structure
    // 2. Determine max height for each row
    // 3. Determine max width for each column (optional, or just left-align)

    // Simplest robust implementation:
    // Place items one by one.
    // If col index == 0, new row.
    // X position = (if col==0) startX else (prevItem.right + spacing)
    // Y position = (if row==0) startY else (prevRow.bottom - spacing) -> Problem: varies across row.

    // Better: Row-based processing
    var rows = [];
    var currentRow = [];
    for (var i = 0; i < items.length; i++) {
        currentRow.push(items[i]);
        if (currentRow.length >= columns || i === items.length - 1) {
            rows.push(currentRow);
            currentRow = [];
        }
    }

    var currentY = startY;

    for (var r = 0; r < rows.length; r++) {
        var rowItems = rows[r];
        var rowMaxHeight = 0;
        var currentX = startX;

        // Pass 1: Measure row height and place items horizontally
        for (var c = 0; c < rowItems.length; c++) {
            var item = rowItems[c];
            var info = getVisibleInfo(item); // {left, top, right, bottom, width, height}

            // Move item to new position
            // We want item.visibleBounds.left = currentX
            // We want item.visibleBounds.top = currentY
            // item.position sets [left, top] of GEOMETRIC bounds usually, or is undefined for Groups?
            // PageItem.position is [x, y]. 
            // It applies to geometric bounds or visible? 
            // Documentation: "The position of the top left corner of the item."
            // Usually consistent with geometricBounds.

            // To be robust with clipping masks, executes translation
            // Delta X = targetX - currentVisibleLeft
            // Delta Y = targetY - currentVisibleTop

            var dx = currentX - info.left;
            var dy = currentY - info.top;

            // Illustrator uses translate(deltaX, deltaY)
            // But PageItem.translate(deltaX, deltaY) moves it relative.
            if (dx !== 0 || dy !== 0) {
                item.translate(dx, dy);
            }

            if (info.height > rowMaxHeight) {
                rowMaxHeight = info.height;
            }

            // Prepare X for next item
            // Current item width might be different if we re-measure or trust `info.width`
            // Translation doesn't change dimensions.
            currentX += info.width + spacingPt;
        }

        // Prepare Y for next row
        currentY -= (rowMaxHeight + spacingPt);
    }
}

/**
 * Resize multiple items to have the same width or height.
 *
 * @param {Array<PageItem>} items
 * @param {number|null} targetWidthMm - target width or null to skip
 * @param {number|null} targetHeightMm - target height or null to skip
 */
function batchResize(items, targetWidthMm, targetHeightMm) {
    if (!items) return;

    var targetW = targetWidthMm ? mmToPoints(targetWidthMm) : null;
    var targetH = targetHeightMm ? mmToPoints(targetHeightMm) : null;

    for (var i = 0; i < items.length; i++) {
        var item = items[i];

        // Scale factors
        var scaleX = 100.0;
        var scaleY = 100.0;

        // Need current visible size
        var info = getVisibleInfo(item);

        if (targetW) {
            scaleX = (targetW / info.width) * 100.0;
            // Maintain aspect ratio if height not specified?
            // Usually check if user wants uniform scaling.
            // If both specified, non-uniform.
            // If only one, uniform?
            // Let's assume uniform if only one specified.
            if (!targetH) scaleY = scaleX;
        }

        if (targetH) {
            scaleY = (targetH / info.height) * 100.0;
            if (!targetW) scaleX = scaleY;
        }

        // Apply scaling
        if (scaleX !== 100.0 || scaleY !== 100.0) {
            item.resize(
                scaleX, // scaleX
                scaleY, // scaleY
                true,   // changePositions (relative to center)
                true,   // changeFillPatterns
                true,   // changeFillGradients
                true,   // changeStrokePattern
                scaleX, // changeLineWidths (scale stroke weight? yes typically)
                Transformation.CENTER // transform center
            );
        }
    }
}

// ============================================================================
// GRID CREATION (Phase 2 - Layout Helpers)
// ============================================================================

/**
 * Create a grid of shapes centered on the artboard.
 * Uses intuitive XY coordinates internally.
 *
 * @param {Object} params - Grid parameters
 * @param {number} params.rows - Number of rows
 * @param {number} params.cols - Number of columns
 * @param {number} params.itemWidth - Width of each item in points
 * @param {number} params.itemHeight - Height of each item in points
 * @param {number} [params.gapX=10] - Horizontal gap between items
 * @param {number} [params.gapY=params.gapX] - Vertical gap between items
 * @param {number} [params.cornerRadius=0] - Corner radius for rounded rectangles
 * @param {string} [params.shape='rect'] - Shape type: 'rect', 'ellipse'
 * @param {Array} [params.colors] - Array of {r,g,b} colors for each cell (row-major order)
 * @param {Array} [params.names] - Array of names for each cell
 * @param {number} [params.offsetX=0] - X offset from center
 * @param {number} [params.offsetY=0] - Y offset from center
 * @returns {Array<PathItem>} Array of created items in row-major order
 *
 * @example
 * // Create a 2x2 Microsoft-style logo grid
 * var items = createGrid({
 *     rows: 2, cols: 2,
 *     itemWidth: 100, itemHeight: 100,
 *     gapX: 10, gapY: 10,
 *     cornerRadius: 20,
 *     colors: [
 *         {r: 243, g: 83, b: 37},   // Red-orange
 *         {r: 129, g: 188, b: 6},   // Green
 *         {r: 5, g: 166, b: 240},   // Blue
 *         {r: 255, g: 186, b: 8}    // Yellow
 *     ]
 * });
 */
function createGrid(params) {
    var doc = app.activeDocument;
    var CTX = getContext();

    // Validate required params
    if (!params.rows || !params.cols) {
        throw new Error('createGrid requires rows and cols parameters');
    }
    if (!params.itemWidth || !params.itemHeight) {
        throw new Error('createGrid requires itemWidth and itemHeight parameters');
    }

    var rows = params.rows;
    var cols = params.cols;
    var itemW = params.itemWidth;
    var itemH = params.itemHeight;
    var gapX = (params.gapX !== undefined) ? params.gapX : 10;
    var gapY = (params.gapY !== undefined) ? params.gapY : gapX;
    var cornerRadius = params.cornerRadius || 0;
    var shape = params.shape || 'rect';
    var colors = params.colors || [];
    var names = params.names || [];
    var offsetX = params.offsetX || 0;
    var offsetY = params.offsetY || 0;

    // Calculate total grid dimensions
    var totalW = cols * itemW + (cols - 1) * gapX;
    var totalH = rows * itemH + (rows - 1) * gapY;

    // Calculate starting position (centered on artboard, then apply offset)
    var startX = (CTX.width - totalW) / 2 + offsetX;
    var startY = (CTX.height - totalH) / 2 + offsetY;

    var items = [];
    var idx = 0;

    for (var row = 0; row < rows; row++) {
        for (var col = 0; col < cols; col++) {
            var x = startX + col * (itemW + gapX);
            var y = startY + row * (itemH + gapY);

            var item;
            if (shape === 'ellipse') {
                item = ellipseXY(x, y, itemW, itemH);
            } else {
                // Default to rectangle
                if (cornerRadius > 0) {
                    item = rectXY(x, y, itemW, itemH, {cornerRadius: cornerRadius});
                } else {
                    item = rectXY(x, y, itemW, itemH);
                }
            }

            // Apply color if provided
            if (colors[idx]) {
                var c = colors[idx];
                item.fillColor = makeRGBColor(c.r, c.g, c.b);
            }

            // Apply name if provided
            if (names[idx]) {
                item.name = names[idx];
            } else {
                item.name = 'grid_' + row + '_' + col;
            }

            items.push(item);
            idx++;
        }
    }

    return items;
}

// ============================================================================
// DISTRIBUTION HELPERS
// ============================================================================

/**
 * Distribute items horizontally with equal spacing.
 * Items are distributed between the leftmost and rightmost item positions.
 *
 * @param {Array<PageItem>} items - Items to distribute (minimum 3 for visible effect)
 * @param {number} [gap] - If provided, use fixed gap; otherwise distribute evenly
 * @returns {void}
 *
 * @example
 * // Distribute selected items with 20pt gap
 * distributeHorizontal(doc.selection, 20);
 */
function distributeHorizontal(items, gap) {
    if (!items || items.length < 2) return;

    // Get bounds info for all items
    var infos = [];
    for (var i = 0; i < items.length; i++) {
        infos.push({
            item: items[i],
            info: getVisibleInfo(items[i])
        });
    }

    // Sort by left position
    infos.sort(function(a, b) {
        return a.info.left - b.info.left;
    });

    if (gap !== undefined) {
        // Fixed gap: position each item after previous + gap
        var currentX = infos[0].info.left;
        for (var j = 0; j < infos.length; j++) {
            var data = infos[j];
            var dx = currentX - data.info.left;
            if (dx !== 0) {
                data.item.translate(dx, 0);
            }
            currentX += data.info.width + gap;
        }
    } else {
        // Even distribution: calculate total span and distribute
        var leftMost = infos[0].info.left;
        var rightMost = infos[infos.length - 1].info.right;
        var totalSpan = rightMost - leftMost;

        // Calculate total width of all items
        var totalItemWidth = 0;
        for (var k = 0; k < infos.length; k++) {
            totalItemWidth += infos[k].info.width;
        }

        // Calculate even gap
        var evenGap = (totalSpan - totalItemWidth) / (infos.length - 1);

        var posX = leftMost;
        for (var m = 0; m < infos.length; m++) {
            var d = infos[m];
            var deltaX = posX - d.info.left;
            if (deltaX !== 0) {
                d.item.translate(deltaX, 0);
            }
            posX += d.info.width + evenGap;
        }
    }
}

/**
 * Distribute items vertically with equal spacing.
 * Items are distributed between the topmost and bottommost item positions.
 *
 * @param {Array<PageItem>} items - Items to distribute (minimum 3 for visible effect)
 * @param {number} [gap] - If provided, use fixed gap; otherwise distribute evenly
 * @returns {void}
 *
 * @example
 * // Distribute selected items with 15pt gap
 * distributeVertical(doc.selection, 15);
 */
function distributeVertical(items, gap) {
    if (!items || items.length < 2) return;

    // Get bounds info for all items
    var infos = [];
    for (var i = 0; i < items.length; i++) {
        infos.push({
            item: items[i],
            info: getVisibleInfo(items[i])
        });
    }

    // Sort by top position (highest Y value first in Illustrator coords)
    infos.sort(function(a, b) {
        return b.info.top - a.info.top;  // Descending: top-most first
    });

    if (gap !== undefined) {
        // Fixed gap: position each item below previous + gap
        var currentY = infos[0].info.top;
        for (var j = 0; j < infos.length; j++) {
            var data = infos[j];
            var dy = currentY - data.info.top;
            if (dy !== 0) {
                data.item.translate(0, dy);
            }
            currentY -= (data.info.height + gap);  // Move down (negative Y)
        }
    } else {
        // Even distribution
        var topMost = infos[0].info.top;
        var bottomMost = infos[infos.length - 1].info.bottom;
        var totalSpan = topMost - bottomMost;

        var totalItemHeight = 0;
        for (var k = 0; k < infos.length; k++) {
            totalItemHeight += infos[k].info.height;
        }

        var evenGap = (totalSpan - totalItemHeight) / (infos.length - 1);

        var posY = topMost;
        for (var m = 0; m < infos.length; m++) {
            var d = infos[m];
            var deltaY = posY - d.info.top;
            if (deltaY !== 0) {
                d.item.translate(0, deltaY);
            }
            posY -= (d.info.height + evenGap);
        }
    }
}

// ============================================================================
// ALIGNMENT HELPERS
// ============================================================================

/**
 * Center-align items on the artboard (as a group).
 * Moves all items together so their collective center matches artboard center.
 *
 * @param {Array<PageItem>} items - Items to center
 * @returns {void}
 *
 * @example
 * alignCenter(doc.selection);
 */
function alignCenter(items) {
    if (!items || items.length === 0) return;

    var CTX = getContext();

    // Calculate bounding box of all items
    var groupLeft = Infinity;
    var groupTop = -Infinity;
    var groupRight = -Infinity;
    var groupBottom = Infinity;

    for (var i = 0; i < items.length; i++) {
        var info = getVisibleInfo(items[i]);
        if (info.left < groupLeft) groupLeft = info.left;
        if (info.top > groupTop) groupTop = info.top;
        if (info.right > groupRight) groupRight = info.right;
        if (info.bottom < groupBottom) groupBottom = info.bottom;
    }

    var groupCenterX = (groupLeft + groupRight) / 2;
    var groupCenterY = (groupTop + groupBottom) / 2;

    var artboardCenterX = CTX.left + CTX.width / 2;
    var artboardCenterY = CTX.top - CTX.height / 2;

    var dx = artboardCenterX - groupCenterX;
    var dy = artboardCenterY - groupCenterY;

    if (dx !== 0 || dy !== 0) {
        for (var j = 0; j < items.length; j++) {
            items[j].translate(dx, dy);
        }
    }
}

/**
 * Align items horizontally (left, center, or right).
 *
 * @param {Array<PageItem>} items - Items to align
 * @param {string} alignment - 'left', 'center', or 'right'
 * @returns {void}
 */
function alignHorizontal(items, alignment) {
    if (!items || items.length < 2) return;

    var infos = [];
    for (var i = 0; i < items.length; i++) {
        infos.push({
            item: items[i],
            info: getVisibleInfo(items[i])
        });
    }

    var targetX;
    if (alignment === 'left') {
        targetX = Infinity;
        for (var j = 0; j < infos.length; j++) {
            if (infos[j].info.left < targetX) targetX = infos[j].info.left;
        }
        for (var k = 0; k < infos.length; k++) {
            var dx = targetX - infos[k].info.left;
            if (dx !== 0) infos[k].item.translate(dx, 0);
        }
    } else if (alignment === 'right') {
        targetX = -Infinity;
        for (var m = 0; m < infos.length; m++) {
            if (infos[m].info.right > targetX) targetX = infos[m].info.right;
        }
        for (var n = 0; n < infos.length; n++) {
            var dxR = targetX - infos[n].info.right;
            if (dxR !== 0) infos[n].item.translate(dxR, 0);
        }
    } else {
        // center
        var sumCenterX = 0;
        for (var p = 0; p < infos.length; p++) {
            sumCenterX += (infos[p].info.left + infos[p].info.right) / 2;
        }
        var avgCenterX = sumCenterX / infos.length;
        for (var q = 0; q < infos.length; q++) {
            var itemCenterX = (infos[q].info.left + infos[q].info.right) / 2;
            var dxC = avgCenterX - itemCenterX;
            if (dxC !== 0) infos[q].item.translate(dxC, 0);
        }
    }
}

/**
 * Align items vertically (top, center, or bottom).
 *
 * @param {Array<PageItem>} items - Items to align
 * @param {string} alignment - 'top', 'center', or 'bottom'
 * @returns {void}
 */
function alignVertical(items, alignment) {
    if (!items || items.length < 2) return;

    var infos = [];
    for (var i = 0; i < items.length; i++) {
        infos.push({
            item: items[i],
            info: getVisibleInfo(items[i])
        });
    }

    var targetY;
    if (alignment === 'top') {
        targetY = -Infinity;
        for (var j = 0; j < infos.length; j++) {
            if (infos[j].info.top > targetY) targetY = infos[j].info.top;
        }
        for (var k = 0; k < infos.length; k++) {
            var dy = targetY - infos[k].info.top;
            if (dy !== 0) infos[k].item.translate(0, dy);
        }
    } else if (alignment === 'bottom') {
        targetY = Infinity;
        for (var m = 0; m < infos.length; m++) {
            if (infos[m].info.bottom < targetY) targetY = infos[m].info.bottom;
        }
        for (var n = 0; n < infos.length; n++) {
            var dyB = targetY - infos[n].info.bottom;
            if (dyB !== 0) infos[n].item.translate(0, dyB);
        }
    } else {
        // center
        var sumCenterY = 0;
        for (var p = 0; p < infos.length; p++) {
            sumCenterY += (infos[p].info.top + infos[p].info.bottom) / 2;
        }
        var avgCenterY = sumCenterY / infos.length;
        for (var q = 0; q < infos.length; q++) {
            var itemCenterY = (infos[q].info.top + infos[q].info.bottom) / 2;
            var dyC = avgCenterY - itemCenterY;
            if (dyC !== 0) infos[q].item.translate(0, dyC);
        }
    }
}
