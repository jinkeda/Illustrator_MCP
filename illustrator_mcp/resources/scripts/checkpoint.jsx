/**
 * checkpoint.jsx - Named Checkpoint Management
 * Part of Illustrator MCP SOC Framework
 *
 * Provides save/restore/list/delete for named document snapshots.
 * Uses captureSnapshot/restoreSnapshot from snapshot.jsx as the backend.
 *
 * Storage:
 *   Primary: $.global.mcpCheckpoints[docKey][name]
 *   Fallback: ~/mcp_checkpoints_<sanitized>.json
 *
 * Scope limitation: Only captures MCP-managed items (those with @mcp:id).
 * Manually-created Illustrator items are NOT included.
 *
 * Restore is mutate-in-place: items found by MCP ID get updated,
 * deleted items appear in notFound, newly created items are untouched.
 * Restore may require multiple undo steps to fully revert.
 *
 * @requires snapshot (captureSnapshot, restoreSnapshot)
 * @requires mcp_id (extractMcpId)
 * @version 1.0.0
 */

// ==================== Constants ====================

var MAX_CHECKPOINT_ITEMS = 2000;
var MAX_CHECKPOINT_BYTES = 2097152; // 2 MB
var CHECKPOINT_NAME_RE = /^[A-Za-z0-9._\- ]+$/;

// ==================== DocKey ====================

/**
 * Get a stable document key for checkpoint storage.
 * Saved docs: fullName.fsName (unique path)
 * Unsaved docs: name + artboard count + active artboard rect
 */
function _checkpointDocKey(doc) {
    try {
        if (doc.fullName) {
            return doc.fullName.fsName;
        }
    } catch (e) { /* unsaved doc throws */ }

    // Fallback for unsaved docs
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()];
    var r = ab.artboardRect;
    return doc.name + ":" + doc.artboards.length + ":" +
        Math.round(r[0]) + "," + Math.round(r[1]) + "," +
        Math.round(r[2]) + "," + Math.round(r[3]);
}

/**
 * Sanitize a string for use as a filename component.
 */
function _sanitizeFilename(str) {
    return str.replace(/[^A-Za-z0-9_\-]/g, "_").substring(0, 60);
}

// ==================== Storage ====================

/**
 * Get the checkpoint store for a doc (creates if needed).
 */
function _getStore(docKey) {
    if (!$.global.mcpCheckpoints) $.global.mcpCheckpoints = {};
    if (!$.global.mcpCheckpoints[docKey]) $.global.mcpCheckpoints[docKey] = {};
    return $.global.mcpCheckpoints[docKey];
}

/**
 * Get fallback file path for checkpoint persistence.
 */
function _fallbackPath(docKey) {
    var home = Folder("~").fsName;
    return home + "/mcp_checkpoints_" + _sanitizeFilename(docKey) + ".json";
}

/**
 * Load checkpoints from file fallback (if $.global is empty).
 */
function _loadFallback(docKey) {
    var store = _getStore(docKey);
    // Only load if store is empty
    var hasKeys = false;
    for (var k in store) { if (store.hasOwnProperty(k)) { hasKeys = true; break; } }
    if (hasKeys) return store;

    try {
        var f = new File(_fallbackPath(docKey));
        if (f.exists) {
            f.open("r");
            var raw = f.read();
            f.close();
            var loaded = eval("(" + raw + ")");
            if (loaded && typeof loaded === "object") {
                $.global.mcpCheckpoints[docKey] = loaded;
                return loaded;
            }
        }
    } catch (e) { /* file read failed, ignore */ }

    return store;
}

/**
 * Persist checkpoints to file fallback.
 */
function _saveFallback(docKey) {
    try {
        var store = _getStore(docKey);
        // Build serializable copy (strip items to save size in fallback)
        var serialized = {};
        for (var name in store) {
            if (!store.hasOwnProperty(name)) continue;
            serialized[name] = store[name];
        }
        var json = ""; // Manual JSON serialization for ES3
        json = __mcp_toJSON(serialized);

        var f = new File(_fallbackPath(docKey));
        f.open("w");
        f.write(json);
        f.close();
    } catch (e) { /* file write failed, non-fatal */ }
}

// ==================== Checkpoint Operations ====================

/**
 * Save a named checkpoint.
 *
 * @param {string} name - Checkpoint name
 * @param {Document} doc - Active document
 * @returns {Object} {ok, name, itemCount, byteSize, warnings}
 */
function checkpointSave(name, doc) {
    // Validate name
    if (!name || typeof name !== "string") {
        return { ok: false, error: "Checkpoint name is required" };
    }
    name = name.replace(/^\s+|\s+$/g, ""); // trim
    if (name.length === 0) {
        return { ok: false, error: "Checkpoint name cannot be empty" };
    }
    if (!CHECKPOINT_NAME_RE.test(name)) {
        return { ok: false, error: "Invalid name. Use: A-Z a-z 0-9 . _ - space" };
    }

    // Capture snapshot
    var snap = captureSnapshot(doc);

    // Hard cap: item count
    if (snap.items.length > MAX_CHECKPOINT_ITEMS) {
        return {
            ok: false,
            error: "Too many items (" + snap.items.length + "). Max: " + MAX_CHECKPOINT_ITEMS +
                ". Reduce MCP items or split into multiple checkpoints."
        };
    }

    // Estimate byte size
    var jsonStr;
    try {
        jsonStr = __mcp_toJSON(snap);
    } catch (e) {
        return { ok: false, error: "Failed to serialize snapshot: " + e.message };
    }

    var byteSize = jsonStr.length; // approximate (1 char ≈ 1 byte for ASCII)
    if (byteSize > MAX_CHECKPOINT_BYTES) {
        return {
            ok: false,
            error: "Snapshot too large (" + Math.round(byteSize / 1024) + "KB). Max: " +
                Math.round(MAX_CHECKPOINT_BYTES / 1024) + "KB."
        };
    }

    // Store
    var docKey = _checkpointDocKey(doc);
    var store = _loadFallback(docKey);
    snap._byteSize = byteSize;
    store[name] = snap;
    _saveFallback(docKey);

    var result = {
        ok: true,
        name: name,
        itemCount: snap.items.length,
        byteSize: byteSize
    };
    if (snap.warnings && snap.warnings.length > 0) {
        result.warnings = snap.warnings;
    }
    return result;
}

/**
 * Restore a named checkpoint.
 *
 * @param {string} name - Checkpoint name
 * @param {Document} doc - Active document
 * @param {Object} opts - Restore options (geometry, style, visibility, restoreSize)
 * @returns {Object} {ok, restored, failed, notFound, warnings}
 */
function checkpointRestore(name, doc, opts) {
    if (!name || typeof name !== "string") {
        return { ok: false, error: "Checkpoint name is required" };
    }
    name = name.replace(/^\s+|\s+$/g, "");

    var docKey = _checkpointDocKey(doc);
    var store = _loadFallback(docKey);
    var snap = store[name];

    if (!snap) {
        return { ok: false, error: "Checkpoint not found: " + name };
    }

    opts = opts || {};
    return restoreSnapshot(doc, snap, opts);
}

/**
 * List all checkpoints for a document.
 *
 * @param {Document} doc - Active document
 * @returns {Object} {ok, checkpoints: [{name, timestamp, itemCount, byteSize}]}
 */
function checkpointList(doc) {
    var docKey = _checkpointDocKey(doc);
    var store = _loadFallback(docKey);
    var list = [];

    for (var name in store) {
        if (!store.hasOwnProperty(name)) continue;
        var snap = store[name];
        list.push({
            name: name,
            timestamp: snap.timestamp || null,
            itemCount: snap.items ? snap.items.length : 0,
            byteSize: snap._byteSize || 0
        });
    }

    // Sort by timestamp descending (newest first)
    list.sort(function (a, b) {
        return (b.timestamp || 0) - (a.timestamp || 0);
    });

    return { ok: true, checkpoints: list };
}

/**
 * Delete a named checkpoint.
 *
 * @param {string} name - Checkpoint name
 * @param {Document} doc - Active document
 * @returns {Object} {ok, deleted}
 */
function checkpointDelete(name, doc) {
    if (!name || typeof name !== "string") {
        return { ok: false, error: "Checkpoint name is required" };
    }
    name = name.replace(/^\s+|\s+$/g, "");

    var docKey = _checkpointDocKey(doc);
    var store = _loadFallback(docKey);

    if (!store[name]) {
        return { ok: false, error: "Checkpoint not found: " + name };
    }

    delete store[name];
    _saveFallback(docKey);

    return { ok: true, deleted: name };
}

// ==================== Exports ====================

if (typeof $.global !== "undefined") {
    $.global.checkpointSave = checkpointSave;
    $.global.checkpointRestore = checkpointRestore;
    $.global.checkpointList = checkpointList;
    $.global.checkpointDelete = checkpointDelete;
}
