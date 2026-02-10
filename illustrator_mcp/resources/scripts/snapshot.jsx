/**
 * snapshot.jsx - Document State Snapshot/Restore
 * Part of Illustrator MCP SOC Framework
 * 
 * Provides safer rollback than undo-based approach:
 * - Captures serializable state before batch execution
 * - Restores state on failure instead of relying on undo history
 * 
 * @requires ops_core (for MCP ID extraction)
 * @version 1.0.0
 */

// ==================== Color Serialization ====================

/**
 * Serialize color object to JSON-safe format
 */
function serializeColor(color) {
    if (!color) return null;

    try {
        if (color.typename === "RGBColor") {
            return { type: "rgb", r: color.red, g: color.green, b: color.blue };
        }
        if (color.typename === "CMYKColor") {
            return { type: "cmyk", c: color.cyan, m: color.magenta, y: color.yellow, k: color.black };
        }
        if (color.typename === "GrayColor") {
            return { type: "gray", gray: color.gray };
        }
        if (color.typename === "SpotColor") {
            return { type: "spot", name: color.spot.name };
        }
        if (color.typename === "NoColor") {
            return { type: "none" };
        }
    } catch (e) { }

    return null;
}

/**
 * Deserialize color from snapshot format
 */
function deserializeColor(colorData) {
    if (!colorData) return null;

    try {
        if (colorData.type === "rgb") {
            var c = new RGBColor();
            c.red = colorData.r;
            c.green = colorData.g;
            c.blue = colorData.b;
            return c;
        }
        if (colorData.type === "cmyk") {
            var c = new CMYKColor();
            c.cyan = colorData.c;
            c.magenta = colorData.m;
            c.yellow = colorData.y;
            c.black = colorData.k;
            return c;
        }
        if (colorData.type === "gray") {
            var c = new GrayColor();
            c.gray = colorData.gray;
            return c;
        }
        if (colorData.type === "none") {
            return new NoColor();
        }
    } catch (e) { }

    return null;
}

// ==================== ID Extraction ====================

/**
 * Extract MCP ID from item note
 */
function extractMcpId(note) {
    if (!note) return null;
    var match = note.match(/@mcp:id=([^\s@]+)/);
    return match ? match[1] : null;
}

// ==================== Snapshot Capture ====================

/**
 * Capture item state for snapshot
 */
function captureItemState(item) {
    var id = extractMcpId(item.note);
    if (!id) return null;  // Only capture MCP-managed items

    var state = {
        id: id,
        typename: item.typename,
        position: [item.left, item.top],
        size: [item.width, item.height],
        opacity: item.opacity,
        visible: item.hidden !== true,
        locked: item.locked === true
    };

    // Capture fill
    try {
        if (item.filled) {
            state.filled = true;
            state.fillColor = serializeColor(item.fillColor);
        } else {
            state.filled = false;
        }
    } catch (e) { }

    // Capture stroke
    try {
        if (item.stroked) {
            state.stroked = true;
            state.strokeColor = serializeColor(item.strokeColor);
            state.strokeWidth = item.strokeWidth;
        } else {
            state.stroked = false;
        }
    } catch (e) { }

    return state;
}

/**
 * Capture document state snapshot.
 * Only captures items with MCP IDs for targeted restore.
 * 
 * @param {Document} doc - Active document
 * @param {Object} options - Capture options
 * @param {boolean} options.mcpOnly - Only capture MCP-managed items (default: true)
 * @param {Function} options.clock - Injectable clock for P2 compliance (default: new Date().getTime)
 * @returns {Object} Snapshot object
 */
function captureSnapshot(doc, options) {
    options = options || {};
    var mcpOnly = options.mcpOnly !== false;
    var clock = options.clock || function () { return new Date().getTime(); };

    var snapshot = {
        version: "1.0",
        timestamp: clock(),
        docName: doc.name,
        artboardIndex: doc.artboards.getActiveArtboardIndex(),
        items: [],
        layers: []
    };

    // Capture layer state
    for (var i = 0; i < doc.layers.length; i++) {
        var layer = doc.layers[i];
        snapshot.layers.push({
            name: layer.name,
            visible: layer.visible,
            locked: layer.locked,
            color: layer.color ? [layer.color.red, layer.color.green, layer.color.blue] : null
        });
    }

    // Capture items recursively
    function scanContainer(container) {
        if (!container || !container.pageItems) return;

        for (var i = 0; i < container.pageItems.length; i++) {
            var item = container.pageItems[i];

            var state = captureItemState(item);
            if (state) {
                snapshot.items.push(state);
            }

            // Recurse into groups
            if (item.typename === "GroupItem") {
                scanContainer(item);
            }
        }
    }

    for (var i = 0; i < doc.layers.length; i++) {
        scanContainer(doc.layers[i]);
    }

    return snapshot;
}

// ==================== Snapshot Restore ====================

/**
 * Restore document state from snapshot.
 * 
 * @param {Document} doc - Active document
 * @param {Object} snapshot - Snapshot to restore
 * @param {Object} options - Restore options
 * @param {boolean} options.geometry - Restore position/size (default: true)
 * @param {boolean} options.restoreSize - Restore width/height within geometry (default: false)
 * @param {boolean} options.style - Restore fill/stroke (default: true)
 * @param {boolean} options.visibility - Restore visibility/lock state (default: false)
 * @returns {Object} Result with restored/failed counts
 */
function restoreSnapshot(doc, snapshot, options) {
    options = options || {};
    var restoreGeometry = options.geometry !== false;
    var restoreSize = options.restoreSize === true;
    var restoreStyle = options.style !== false;
    var restoreVisibility = options.visibility === true;

    var restored = 0;
    var failed = 0;
    var notFound = [];
    var errors = [];

    // Build ID index for O(1) lookups
    var idIndex = {};
    function buildIndex(container) {
        if (!container || !container.pageItems) return;
        for (var i = 0; i < container.pageItems.length; i++) {
            var item = container.pageItems[i];
            var id = extractMcpId(item.note);
            if (id) {
                idIndex[id] = item;
            }
            if (item.typename === "GroupItem") {
                buildIndex(item);
            }
        }
    }
    for (var i = 0; i < doc.layers.length; i++) {
        buildIndex(doc.layers[i]);
    }

    // Restore each item
    for (var i = 0; i < snapshot.items.length; i++) {
        var saved = snapshot.items[i];
        var item = idIndex[saved.id];

        if (!item) {
            notFound.push(saved.id);
            failed++;
            continue;
        }

        try {
            // Restore geometry
            if (restoreGeometry) {
                item.left = saved.position[0];
                item.top = saved.position[1];
                // Size restore is opt-in (can be complex for certain item types)
                if (restoreSize && saved.size) {
                    try {
                        item.width = saved.size[0];
                        item.height = saved.size[1];
                    } catch (sizeErr) {
                        // Some item types (e.g. linked images) may not support size assignment
                    }
                }
            }

            // Restore style
            if (restoreStyle) {
                if (saved.filled === true && saved.fillColor) {
                    var fc = deserializeColor(saved.fillColor);
                    if (fc) {
                        item.filled = true;
                        item.fillColor = fc;
                    }
                } else if (saved.filled === false) {
                    item.filled = false;
                }

                if (saved.stroked === true && saved.strokeColor) {
                    var sc = deserializeColor(saved.strokeColor);
                    if (sc) {
                        item.stroked = true;
                        item.strokeColor = sc;
                        if (saved.strokeWidth !== undefined) {
                            item.strokeWidth = saved.strokeWidth;
                        }
                    }
                } else if (saved.stroked === false) {
                    item.stroked = false;
                }

                if (saved.opacity !== undefined) {
                    item.opacity = saved.opacity;
                }
            }

            // Restore visibility
            if (restoreVisibility) {
                if (saved.visible !== undefined) {
                    item.hidden = !saved.visible;
                }
                if (saved.locked !== undefined) {
                    item.locked = saved.locked;
                }
            }

            restored++;

        } catch (e) {
            errors.push({ id: saved.id, error: e.message });
            failed++;
        }
    }

    return {
        ok: failed === 0,
        restored: restored,
        failed: failed,
        notFound: notFound.slice(0, 10),  // Limit to first 10
        errors: errors.slice(0, 5)
    };
}

// ==================== Exports ====================

// Register with global if available (for manifest system)
if (typeof $.global !== "undefined") {
    $.global.captureSnapshot = captureSnapshot;
    $.global.restoreSnapshot = restoreSnapshot;
    $.global.serializeColor = serializeColor;
    $.global.deserializeColor = deserializeColor;
}
