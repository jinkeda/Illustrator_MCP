/**
 * ops_measure.jsx - Measurement and Assertion Operations
 * Part of Illustrator MCP SOC Framework
 * 
 * Provides handlers for:
 * - assert_count: Assert number of items
 * - assert_bounds: Assert item within bounds
 * - assert_exists: Assert item exists by ID
 * - measure_bounds: Get bounds of targets
 * - snapshot_structure: Capture document structure snapshot
 * 
 * @requires ops_core (for registerOpHandler)
 * @version 1.0.0
 */

// ==================== Assert Count ====================

registerOpHandler("assert_count", function (params, targets, ctx) {
    var expected = params.expected;
    var actual = targets.length;
    var operator = params.operator || "eq"; // eq, gte, lte, gt, lt

    var ok = false;
    switch (operator) {
        case "eq": ok = actual === expected; break;
        case "gte": ok = actual >= expected; break;
        case "lte": ok = actual <= expected; break;
        case "gt": ok = actual > expected; break;
        case "lt": ok = actual < expected; break;
    }

    return {
        ok: ok,
        data: {
            expected: expected,
            actual: actual,
            operator: operator
        }
    };
});

// ==================== Assert Bounds ====================

registerOpHandler("assert_bounds", function (params, targets, ctx) {
    var doc = ctx.doc;

    // Get artboard bounds
    var abIndex = params.artboardIndex || doc.artboards.getActiveArtboardIndex();
    var ab = doc.artboards[abIndex];
    var abBounds = ab.artboardRect; // [left, top, right, bottom]

    var inBounds = 0;
    var outOfBounds = [];

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];
        var itemLeft = item.left;
        var itemTop = item.top;
        var itemRight = item.left + item.width;
        var itemBottom = item.top - item.height;

        // Check if item is fully within artboard
        var isIn = itemLeft >= abBounds[0]
            && itemRight <= abBounds[2]
            && itemTop <= abBounds[1]
            && itemBottom >= abBounds[3];

        if (isIn) {
            inBounds++;
        } else {
            outOfBounds.push({
                index: i,
                name: item.name || null,
                bounds: [itemLeft, itemTop, itemRight, itemBottom]
            });
        }
    }

    return {
        ok: outOfBounds.length === 0,
        data: {
            inBounds: inBounds,
            outOfBounds: outOfBounds.length,
            artboardBounds: abBounds,
            details: outOfBounds.slice(0, 5) // Limit to first 5
        }
    };
});

// ==================== Assert Exists ====================

registerOpHandler("assert_exists", function (params, targets, ctx) {
    var ids = params.ids || [];
    var doc = ctx.doc;

    // Find items by ID
    var found = [];
    var missing = [];

    function searchContainer(container) {
        if (!container || !container.pageItems) return;
        for (var i = 0; i < container.pageItems.length; i++) {
            var item = container.pageItems[i];
            try {
                if (item.note) {
                    var match = item.note.match(/@mcp:id=([^\s@]+)/);
                    if (match) {
                        var itemId = match[1];
                        for (var j = 0; j < ids.length; j++) {
                            if (ids[j] === itemId && found.indexOf(itemId) === -1) {
                                found.push(itemId);
                            }
                        }
                    }
                }
            } catch (e) { }
            if (item.typename === "GroupItem") searchContainer(item);
        }
    }

    for (var i = 0; i < doc.layers.length; i++) {
        searchContainer(doc.layers[i]);
    }

    for (var i = 0; i < ids.length; i++) {
        if (found.indexOf(ids[i]) === -1) {
            missing.push(ids[i]);
        }
    }

    return {
        ok: missing.length === 0,
        data: {
            found: found.length,
            missing: missing
        }
    };
});

// ==================== Measure Bounds ====================

registerOpHandler("measure_bounds", function (params, targets, ctx) {
    if (targets.length === 0) {
        return { ok: true, data: { bounds: null } };
    }

    var minX = Infinity, minY = Infinity;
    var maxX = -Infinity, maxY = -Infinity;

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];
        minX = Math.min(minX, item.left);
        maxX = Math.max(maxX, item.left + item.width);
        maxY = Math.max(maxY, item.top);
        minY = Math.min(minY, item.top - item.height);
    }

    return {
        ok: true,
        data: {
            bounds: {
                left: minX,
                top: maxY,
                right: maxX,
                bottom: minY,
                width: maxX - minX,
                height: maxY - minY
            },
            itemCount: targets.length
        }
    };
});

// ==================== Snapshot Structure ====================

registerOpHandler("snapshot_structure", function (params, targets, ctx) {
    var doc = ctx.doc;
    var includeItems = params.includeItems || false;

    var snapshot = {
        documentName: doc.name,
        artboards: doc.artboards.length,
        layers: [],
        selection: doc.selection ? doc.selection.length : 0,
        timestamp: new Date().getTime()
    };

    for (var i = 0; i < doc.layers.length; i++) {
        var layer = doc.layers[i];
        var layerInfo = {
            name: layer.name,
            visible: layer.visible,
            locked: layer.locked,
            itemCount: layer.pageItems.length
        };

        if (includeItems) {
            layerInfo.items = [];
            for (var j = 0; j < layer.pageItems.length; j++) {
                var item = layer.pageItems[j];
                layerInfo.items.push({
                    name: item.name || null,
                    typename: item.typename,
                    bounds: [item.left, item.top, item.width, item.height]
                });
            }
        }

        snapshot.layers.push(layerInfo);
    }

    return {
        ok: true,
        data: snapshot
    };
});

// ==================== Hash Structure (lightweight digest) ====================

registerOpHandler("hash_structure", function (params, targets, ctx) {
    var doc = ctx.doc;

    // Create a simple hash of document structure
    var parts = [
        doc.name,
        String(doc.layers.length),
        String(doc.artboards.length)
    ];

    for (var i = 0; i < doc.layers.length; i++) {
        var layer = doc.layers[i];
        parts.push(layer.name + ":" + layer.pageItems.length);
    }

    // Simple string hash
    var str = parts.join("|");
    var hash = 0;
    for (var i = 0; i < str.length; i++) {
        var charCode = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + charCode;
        hash = hash & hash;
    }

    return {
        ok: true,
        data: {
            hash: String(hash),
            components: parts.length
        }
    };
});
