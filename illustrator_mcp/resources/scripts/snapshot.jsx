/**
 * snapshot.jsx - Partial property snapshot / restore
 * Part of Illustrator MCP SOC Framework
 *
 * SCOPE — read this before relying on it for recovery (T04).
 *
 * This is a shallow PROPERTY snapshot of @mcp:id-tagged page items. It is
 * NOT a document transaction and cannot make an arbitrary batch reversible.
 *
 * What it captures, per tagged item:
 *   position (left/top), size (width/height), opacity, visibility, locked,
 *   filled + fill colour, stroked + stroke colour + stroke width.
 * Plus, for layers: name, visible, locked, colour — captured but NOT restored.
 *
 * What it CANNOT restore, and therefore what rollback cannot undo:
 *   - deleted objects (nothing here can recreate one)
 *   - path anchors and Bézier handles; any geometry change beyond the
 *     bounding box
 *   - text content, character/paragraph runs, or applied fonts
 *   - parent/child structure: grouping, ungrouping, clipping masks
 *   - z-order and layer membership or ordering
 *   - appearance beyond a single flat fill/stroke (effects, multiple fills,
 *     gradients, patterns, transparency modes)
 *   - anything on an UNTAGGED item: captureItemState returns null when there
 *     is no @mcp:id, so `options.mcpOnly: false` does NOT widen capture.
 *
 * Restore is also best effort per item: it can partially apply and then fail,
 * leaving an item in a mixed state. Always inspect the returned
 * {restored, failed, notFound, errors} — a call that throws nothing has still
 * not necessarily restored anything.
 *
 * Use it for what it is: reverting simple property edits on tagged items.
 * For real recovery, take an explicit document checkpoint (T29).
 *
 * @requires mcp_id (for extractMcpId)
 * @version 1.1.0
 */

/**
 * One-line description of what a snapshot-based recovery actually covers.
 * Included in recovery results so callers do not over-read a "restored".
 */
var SNAPSHOT_RECOVERY_SCOPE =
    "captured properties (position, size, opacity, visibility, lock, flat " +
    "fill/stroke) of @mcp:id-tagged items only; does not cover deletions, " +
    "path geometry, text, grouping, or z-order";

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
// extractMcpId is provided by mcp_id.jsx (shared utility)
if (typeof extractMcpId !== "function") {
    throw new Error("snapshot.jsx requires mcp_id.jsx (extractMcpId not found)");
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
 * Capture a partial property snapshot. See the module header for the full
 * list of what is and is not covered.
 *
 * @param {Document} doc - Active document
 * @param {Object} options - Capture options
 * @param {boolean} options.mcpOnly - NO EFFECT. Retained for call-site
 *   compatibility only. captureItemState returns null for any item without an
 *   @mcp:id, so passing false does NOT capture untagged artwork (T04).
 * @param {Function} options.clock - Injectable clock for P2 compliance (default: new Date().getTime)
 * @returns {Object} Snapshot object — {version, timestamp, docName,
 *   artboardIndex, items, layers, warnings}. `layers` is captured but never
 *   restored by restoreSnapshot.
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
        layers: [],
        warnings: []
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

    if (snapshot.items.length === 0) {
        snapshot.warnings.push("No MCP-managed items captured");
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

    // Build ID index for O(1) lookups — detect duplicates
    var idIndex = {};
    var duplicateIds = [];
    function buildIndex(container) {
        if (!container || !container.pageItems) return;
        for (var i = 0; i < container.pageItems.length; i++) {
            var item = container.pageItems[i];
            var id = extractMcpId(item.note);
            if (id) {
                if (idIndex[id]) {
                    duplicateIds.push(id);
                } else {
                    idIndex[id] = item;
                }
            }
            if (item.typename === "GroupItem") {
                buildIndex(item);
            }
        }
    }
    for (var i = 0; i < doc.layers.length; i++) {
        buildIndex(doc.layers[i]);
    }

    // Fail on duplicate MCP IDs
    if (duplicateIds.length > 0) {
        return {
            ok: false,
            error: "Duplicate MCP IDs found: " + duplicateIds.slice(0, 5).join(", "),
            restored: 0,
            failed: 0,
            captured: snapshot.items.length,
            complete: false,
            scope: SNAPSHOT_RECOVERY_SCOPE,
            notFound: [],
            errors: []
        };
    }

    // Restore each item
    var warnings = [];
    for (var i = 0; i < snapshot.items.length; i++) {
        var saved = snapshot.items[i];
        var item = idIndex[saved.id];

        if (!item) {
            notFound.push(saved.id);
            failed++;
            continue;
        }

        // Type mismatch: warn and restore shared fields only
        var typeMismatch = saved.typename && item.typename !== saved.typename;
        if (typeMismatch) {
            warnings.push("Type mismatch for " + saved.id + ": expected " + saved.typename + ", found " + item.typename);
        }

        try {
            // Restore geometry (shared across all types)
            if (restoreGeometry) {
                item.left = saved.position[0];
                item.top = saved.position[1];
                if (restoreSize && saved.size && !typeMismatch) {
                    try {
                        item.width = saved.size[0];
                        item.height = saved.size[1];
                    } catch (sizeErr) { }
                }
            }

            // Restore opacity (shared across all types)
            if (restoreStyle && saved.opacity !== undefined) {
                item.opacity = saved.opacity;
            }

            // Restore fill/stroke only if types match
            if (restoreStyle && !typeMismatch) {
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

    // T04: report completeness explicitly.  `ok: true` means every captured
    // property was reapplied — NOT that the document is back to its prior
    // state.  `scope` says what was in range at all.
    var result = {
        ok: failed === 0,
        restored: restored,
        failed: failed,
        captured: snapshot.items.length,
        complete: failed === 0 && restored === snapshot.items.length,
        scope: SNAPSHOT_RECOVERY_SCOPE,
        notFound: notFound.slice(0, 10),
        errors: errors.slice(0, 5)
    };
    if (warnings.length > 0) result.warnings = warnings;
    return result;
}

// ==================== Exports ====================

// Register with global if available (for manifest system)
if (typeof $.global !== "undefined") {
    $.global.captureSnapshot = captureSnapshot;
    $.global.restoreSnapshot = restoreSnapshot;
    $.global.serializeColor = serializeColor;
    $.global.deserializeColor = deserializeColor;
    $.global.SNAPSHOT_RECOVERY_SCOPE = SNAPSHOT_RECOVERY_SCOPE;
}
