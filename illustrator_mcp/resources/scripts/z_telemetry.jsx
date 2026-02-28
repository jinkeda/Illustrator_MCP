/**
 * z_telemetry.jsx — Z-order telemetry collector for OcclusionGuard.
 *
 * Collects layer metadata and items from the topmost visible layers
 * for programmatic occlusion detection. Typename-safe property access.
 *
 * Returns JSON string with:
 *   layers, topLayerItems, artboardRect, totalItemCount
 */

var doc = app.activeDocument;
var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()];
var abr = ab.artboardRect;  // [left, top, right, bottom] Y-up

// ── Collect layer metadata (index 0 = topmost) ──────────────
var layersData = [];
for (var i = 0; i < doc.layers.length; i++) {
    __mcp_check();
    var lyr = doc.layers[i];
    layersData.push({
        name: lyr.name,
        index: i,
        visible: lyr.visible,
        locked: lyr.locked,
        itemCount: lyr.pageItems.length
    });
}

// ── Find topmost M visible unlocked layers ──────────────────
var MAX_LAYERS = 2;
var MAX_ITEMS_PER_LAYER = 15;
var topVisibleLayers = [];
for (var li = 0; li < doc.layers.length; li++) {
    __mcp_check();
    var l = doc.layers[li];
    if (l.visible && !l.locked) {
        topVisibleLayers.push({ layer: l, index: li });
        if (topVisibleLayers.length >= MAX_LAYERS) break;
    }
}

// ── Compute artboard area ───────────────────────────────────
var abWidth = Math.abs(abr[2] - abr[0]);
var abHeight = Math.abs(abr[1] - abr[3]);
var abArea = abWidth * abHeight;

// ── Collect items from topmost visible layers ────────────────
var topItems = [];
for (var tl = 0; tl < topVisibleLayers.length; tl++) {
    __mcp_check();
    var tlInfo = topVisibleLayers[tl];
    var tlLayer = tlInfo.layer;
    var count = Math.min(tlLayer.pageItems.length, MAX_ITEMS_PER_LAYER);

    for (var pi = 0; pi < count; pi++) {
        __mcp_check();
        var item = tlLayer.pageItems[pi];

        // Skip hidden items
        if (item.hidden) continue;

        var tn = item.typename;
        var bounds = null;
        try {
            bounds = item.visibleBounds; // [left, top, right, bottom] Y-up
        } catch (e) {
            continue; // Skip items without accessible bounds
        }

        // Typename-safe property access
        var hasFilled = (tn === 'PathItem' || tn === 'CompoundPathItem');
        var isFilled = hasFilled ? item.filled : false;
        var isRasterLike = (tn === 'RasterItem' || tn === 'PlacedItem');
        if (isRasterLike) isFilled = true;

        var isClippingGroup = false;
        if (tn === 'GroupItem') {
            isClippingGroup = item.clipped || false;
            if (isClippingGroup) isFilled = true;
        }

        // Cover ratio
        var iW = Math.abs(bounds[2] - bounds[0]);
        var iH = Math.abs(bounds[1] - bounds[3]);
        var interLeft = Math.max(bounds[0], abr[0]);
        var interTop = Math.min(bounds[1], abr[1]);
        var interRight = Math.min(bounds[2], abr[2]);
        var interBottom = Math.max(bounds[3], abr[3]);
        var interArea = Math.max(0, interRight - interLeft) * Math.max(0, interTop - interBottom);
        var coverRatio = (abArea > 0) ? interArea / abArea : 0;

        // Fill color (safe access)
        var fillColorHex = null;
        var fillColorRGB = null;
        if (hasFilled && isFilled) {
            try {
                var fc = item.fillColor;
                if (fc.typename === 'RGBColor') {
                    var rr = Math.round(fc.red);
                    var gg = Math.round(fc.green);
                    var bb = Math.round(fc.blue);
                    fillColorHex = '#' +
                        ('0' + rr.toString(16)).slice(-2) +
                        ('0' + gg.toString(16)).slice(-2) +
                        ('0' + bb.toString(16)).slice(-2);
                    fillColorRGB = { r: rr, g: gg, b: bb };
                }
            } catch (e) {
                // Swallow color read errors (e.g., pattern/gradient)
            }
        }

        // Blend mode
        var blendMode = 'Normal';
        try {
            var bm = item.blendingMode;
            // ExtendScript enum → string mapping
            if (bm === BlendModes.MULTIPLY) blendMode = 'Multiply';
            else if (bm === BlendModes.SCREEN) blendMode = 'Screen';
            else if (bm === BlendModes.OVERLAY) blendMode = 'Overlay';
            else if (bm === BlendModes.DARKEN) blendMode = 'Darken';
            else if (bm === BlendModes.LIGHTEN) blendMode = 'Lighten';
            else if (bm === BlendModes.COLORDODGE) blendMode = 'ColorDodge';
            else if (bm === BlendModes.COLORBURN) blendMode = 'ColorBurn';
            else if (bm === BlendModes.HARDLIGHT) blendMode = 'HardLight';
            else if (bm === BlendModes.SOFTLIGHT) blendMode = 'SoftLight';
            else if (bm === BlendModes.DIFFERENCE) blendMode = 'Difference';
            else if (bm === BlendModes.EXCLUSION) blendMode = 'Exclusion';
            else if (bm === BlendModes.NORMAL) blendMode = 'Normal';
            else blendMode = 'Other';
        } catch (e) {
            blendMode = 'Unknown';
        }

        // MCP ID from item.note
        var mcpId = null;
        try {
            var note = item.note || '';
            var match = note.match(/@mcp:id=([^\s;]+)/);
            if (match) mcpId = match[1];
        } catch (e) { }

        topItems.push({
            name: item.name || '<unnamed>',
            typename: tn,
            layerName: tlLayer.name,
            layerIndex: tlInfo.index,
            opacity: item.opacity,
            filled: isFilled,
            stroked: (hasFilled ? item.stroked : false),
            blendingMode: blendMode,
            clipped: isClippingGroup,
            fillColorHex: fillColorHex,
            fillColor: fillColorRGB,
            bounds: [bounds[0], bounds[1], bounds[2], bounds[3]],
            coverRatio: Math.round(coverRatio * 1000) / 1000,
            mcpId: mcpId
        });
    }
}

// ── Count total items ───────────────────────────────────────
var totalCount = 0;
for (var ci = 0; ci < doc.layers.length; ci++) {
    __mcp_check();
    totalCount += doc.layers[ci].pageItems.length;
}

// ── Return ──────────────────────────────────────────────────
JSON.stringify({
    ok: true,
    data: {
        layers: layersData,
        topLayerItems: topItems,
        artboardRect: [abr[0], abr[1], abr[2], abr[3]],
        totalItemCount: totalCount
    }
});
