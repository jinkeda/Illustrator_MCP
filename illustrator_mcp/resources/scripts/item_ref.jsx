/**
 * item_ref.jsx - Stable Item Reference System
 * Part of Illustrator MCP Standard Library
 * @version 1.0.0
 *
 * Provides stable references for error localization and identity management:
 * - getLayerPath, getIndexPath (locators)
 * - describeItem, describeItemV2 (ItemRef generation)
 * - parseMcpTags (tag parsing)
 * - assignItemId, assignItemIdV2 (ID assignment)
 *
 * DEPENDENCIES: contracts (ErrorCodes)
 * Extracted from task_executor.jsx (Phase 5 decomposition).
 */

// ==================== Stable Reference System ====================

/**
 * Get the layer path (including parent layers)
 * @param {Layer} layer
 * @returns {string} Path like "Layer 1/Sublayer A"
 */
function getLayerPath(layer) {
    var parts = [];
    var current = layer;
    while (current && current.typename === "Layer") {
        parts.unshift(current.name);
        current = current.parent;
    }
    return parts.join("/");
}

/**
 * Get the item's index path within its parent containers
 * @param {PageItem} item
 * @returns {Array<number>} Index path like [0, 2, 5]
 */
function getIndexPath(item) {
    var path = [];
    var current = item;

    while (current && current.parent) {
        var parent = current.parent;
        var collection = null;

        // Find the collection that contains the current item
        if (parent.typename === "Document") {
            collection = parent.pageItems;
        } else if (parent.typename === "Layer") {
            collection = parent.pageItems;
        } else if (parent.typename === "GroupItem") {
            collection = parent.pageItems;
        }

        if (collection) {
            for (var i = 0; i < collection.length; i++) {
                if (collection[i] === current) {
                    path.unshift(i);
                    break;
                }
            }
        }

        current = parent;
        if (current.typename === "Document") break;
    }

    return path;
}

/**
 * Generate a stable reference for an item (for error localization)
 * @deprecated Since v2.3. Use describeItemV2() instead. Will be removed in v3.0.
 * @param {PageItem} item
 * @param {Layer} [layer] - Optional layer override
 * @returns {Object} ItemRef object (legacy format)
 */
function describeItem(item, layer) {
    var itemLayer = layer || null;
    try {
        itemLayer = item.layer;
    } catch (e) {
        // item.layer may fail on some item types (e.g., SymbolItems)
    }

    var layerPath = itemLayer ? getLayerPath(itemLayer) : "";
    var indexPath = getIndexPath(item);

    // Try reading an ID from note (if previously written)
    var itemId = null;
    try {
        if (item.note && item.note.indexOf("@mcp:id=") >= 0) {
            var match = item.note.match(/@mcp:id=([^\s@]+)/);
            if (match) itemId = match[1];
        }
    } catch (e) {
        // item.note may not be accessible on all item types
    }

    return {
        layerPath: layerPath,
        indexPath: indexPath,
        itemId: itemId,
        itemName: item.name || "",
        itemType: item.typename
    };
}

// ==================== Tag Parsing (v2.3) ====================

/**
 * Parse @mcp:key=value tags from a string.
 * @param {string} str - String to parse (item.name or item.note)
 * @returns {Object} Parsed tags {key: value}
 */
function parseMcpTags(str) {
    var tags = {};
    if (!str) return tags;

    // Match @mcp:key=value patterns
    var regex = /@mcp:([a-zA-Z0-9_]+)=([^\s@]+)/g;
    var match;
    // ExtendScript regex.exec loop
    while ((match = str.match(/@mcp:([a-zA-Z0-9_]+)=([^\s@]+)/)) !== null) {
        tags[match[1]] = match[2];
        str = str.replace(match[0], ""); // Remove matched part to find next
    }
    return tags;
}

// ==================== Refactored Item Reference (v2.3) ====================

/**
 * Generate a complete ItemRef with separated concerns (locator/identity/tags).
 * @param {PageItem} item
 * @param {Object} [options] - {includeIdentity: bool, includeTags: bool}
 * @returns {Object} ItemRef with locator, identity, tags, metadata
 */
function describeItemV2(item, options) {
    options = options || {};

    // === LOCATOR (always computed) ===
    var itemLayer = null;
    try { itemLayer = item.layer; } catch (e) { }

    var locator = {
        layerPath: itemLayer ? getLayerPath(itemLayer) : "",
        indexPath: getIndexPath(item)
    };

    // === IDENTITY (opt-in) ===
    var identity = {
        itemId: null,
        idSource: "none"
    };

    if (options.includeIdentity !== false) {
        try {
            if (item.note && item.note.indexOf("@mcp:id=") >= 0) {
                var match = item.note.match(/@mcp:id=([^\s@]+)/);
                if (match) {
                    identity.itemId = match[1];
                    identity.idSource = "note";
                }
            }
        } catch (e) { }
    }

    // === TAGS (parsed from name and note) ===
    var tags = {};
    if (options.includeTags !== false) {
        var nameTags = parseMcpTags(item.name || "");
        var noteTags = parseMcpTags(item.note || "");
        // Merge (note takes precedence)
        for (var k in nameTags) tags[k] = nameTags[k];
        for (var k in noteTags) tags[k] = noteTags[k];
    }

    return {
        locator: locator,
        identity: identity,
        tags: { tags: tags },
        itemType: item.typename,
        itemName: item.name || null
    };
}

// ==================== ID Assignment with Conflict Detection (v2.3) ====================

/**
 * Assign a unique ID to an item (write into note)
 * @deprecated Since v2.3. Use assignItemIdV2() instead. Will be removed in v3.0.
 * Only call when options.assignIds is true
 * @param {PageItem} item
 * @returns {string} The assigned ID
 */
function assignItemId(item) {
    var id = "i" + (new Date().getTime()) + "_" + Math.floor(Math.random() * 10000);

    var existingNote = "";
    try {
        existingNote = item.note || "";
    } catch (e) {
        // item.note may not be readable on some item types
    }

    // Remove old ID (if any)
    existingNote = existingNote.replace(/@mcp:id=[^\s@]+\s*/g, "");

    try {
        item.note = "@mcp:id=" + id + " " + existingNote;
    } catch (e) {
        // item.note may not be writable on some item types (e.g., locked items)
    }

    return id;
}

/**
 * Assign an ID to an item with conflict detection and policy support.
 * @param {PageItem} item
 * @param {string} policy - "none", "opt_in", "always", "preserve"
 * @returns {Object} {assigned: bool, id: string|null, conflict: bool, previousId: string|null}
 */
function assignItemIdV2(item, policy) {
    policy = policy || "none";

    if (policy === "none") {
        return { assigned: false, id: null, conflict: false, previousId: null };
    }

    // Check for existing ID
    var existingId = null;
    try {
        if (item.note && item.note.indexOf("@mcp:id=") >= 0) {
            var match = item.note.match(/@mcp:id=([^\s@]+)/);
            if (match) existingId = match[1];
        }
    } catch (e) { }

    if (policy === "preserve") {
        return { assigned: false, id: existingId, conflict: false, previousId: existingId };
    }

    if (existingId && policy === "opt_in") {
        // Don't overwrite existing ID
        return { assigned: false, id: existingId, conflict: false, previousId: existingId };
    }

    // Generate new ID with timestamp and random suffix
    var newId = "mcp_" + (new Date().getTime()) + "_" + Math.floor(Math.random() * 10000);

    // Conflict detection for "always" policy
    var conflict = (existingId !== null && policy === "always");

    // Write ID to note
    var existingNote = "";
    try { existingNote = item.note || ""; } catch (e) { }
    existingNote = existingNote.replace(/@mcp:id=[^\s@]+\s*/g, "");

    try {
        item.note = "@mcp:id=" + newId + " " + existingNote;
    } catch (e) {
        return { assigned: false, id: null, conflict: false, error: e.message };
    }

    return { assigned: true, id: newId, conflict: conflict, previousId: existingId };
}
