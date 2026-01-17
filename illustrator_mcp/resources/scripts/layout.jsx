/**
 * layout.jsx - Grid and layout engine
 * Part of Illustrator MCP Standard Library
 * Dependencies: geometry.jsx
 */

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
    if (typeof getVisibleInfo === 'undefined') {
        throw new Error("Dependency missing: geometry.jsx is required for layout.jsx");
    }

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
