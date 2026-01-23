/**
 * assets.jsx - Asset Analysis Library v1.0
 * Part of Illustrator MCP Standard Library
 * 
 * Analyzes placed items (PlacedItem, RasterItem) for metadata:
 * bounds, aspect ratio, orientation.
 * 
 * @exports analyzeAssets, getAssetInfo, collectAllPlaced, collectPlacedFromLayer, isPlacedOrRaster
 * @dependencies geometry
 */

/**
 * Check if item is a placed or raster item
 * @param {PageItem} item
 * @returns {boolean}
 */
function isPlacedOrRaster(item) {
    return item.typename === "PlacedItem" || item.typename === "RasterItem";
}

/**
 * Get detailed info for a single asset item
 * @param {PageItem} item - PlacedItem or RasterItem
 * @returns {Object} Asset metadata
 */
function getAssetInfo(item) {
    var bounds = getVisibleBounds(item);
    var width = bounds[2] - bounds[0];
    var height = Math.abs(bounds[1] - bounds[3]);
    var aspectRatio = height > 0 ? width / height : 0;

    var orientation = "square";
    if (aspectRatio > 1.05) orientation = "landscape";
    else if (aspectRatio < 0.95) orientation = "portrait";

    var info = {
        name: item.name || "Unnamed",
        type: item.typename,
        bounds: {
            left: bounds[0],
            top: bounds[1],
            right: bounds[2],
            bottom: bounds[3]
        },
        width: width,
        height: height,
        aspectRatio: Math.round(aspectRatio * 1000) / 1000,  // Round to 3 decimals
        orientation: orientation,
        position: {
            x: item.position[0],
            y: item.position[1]
        }
    };

    // Add linked file info for PlacedItems
    if (item.typename === "PlacedItem") {
        info.isLinked = true;
        try {
            info.filePath = item.file ? item.file.fsName : null;
        } catch (e) {
            info.filePath = null;
        }
    } else {
        info.isLinked = false;
        info.filePath = null;
    }

    return info;
}

/**
 * Collect all placed and raster items from a document
 * @param {Document} doc
 * @returns {Array} Array of PageItems
 */
function collectAllPlaced(doc) {
    var items = [];

    // Collect PlacedItems
    for (var i = 0; i < doc.placedItems.length; i++) {
        items.push(doc.placedItems[i]);
    }

    // Collect RasterItems
    for (var j = 0; j < doc.rasterItems.length; j++) {
        items.push(doc.rasterItems[j]);
    }

    return items;
}

/**
 * Collect placed and raster items from a specific layer
 * @param {Layer} layer
 * @returns {Array} Array of PageItems
 */
function collectPlacedFromLayer(layer) {
    var items = [];

    // Check layer's placedItems
    for (var i = 0; i < layer.placedItems.length; i++) {
        items.push(layer.placedItems[i]);
    }

    // Check layer's rasterItems
    for (var j = 0; j < layer.rasterItems.length; j++) {
        items.push(layer.rasterItems[j]);
    }

    // Recursively check sublayers
    for (var k = 0; k < layer.layers.length; k++) {
        var subItems = collectPlacedFromLayer(layer.layers[k]);
        for (var m = 0; m < subItems.length; m++) {
            items.push(subItems[m]);
        }
    }

    return items;
}

/**
 * Analyze assets in a given scope
 * @param {string} scope - "selection" | "document" | layer name
 * @returns {Object} Analysis result with count and assets array
 */
function analyzeAssets(scope) {
    if (!app.documents.length) {
        return { error: "No document open", count: 0, assets: [] };
    }

    var doc = app.activeDocument;
    var items = [];

    if (scope === "selection") {
        // Filter selection to only placed/raster items
        for (var i = 0; i < doc.selection.length; i++) {
            if (isPlacedOrRaster(doc.selection[i])) {
                items.push(doc.selection[i]);
            }
        }
    } else if (scope === "document") {
        items = collectAllPlaced(doc);
    } else {
        // Assume layer name
        try {
            var layer = doc.layers.getByName(scope);
            items = collectPlacedFromLayer(layer);
        } catch (e) {
            return { error: "Layer not found: " + scope, count: 0, assets: [] };
        }
    }

    var results = [];
    for (var j = 0; j < items.length; j++) {
        results.push(getAssetInfo(items[j]));
    }

    // Sort by name for consistent ordering
    results.sort(function (a, b) {
        return a.name.localeCompare(b.name);
    });

    return {
        count: results.length,
        scope: scope,
        assets: results
    };
}
