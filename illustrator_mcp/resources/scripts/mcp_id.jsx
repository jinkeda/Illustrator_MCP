/**
 * mcp_id.jsx — MCP ID Utilities
 * Part of Illustrator MCP Standard Library
 *
 * Single source of truth for MCP ID operations:
 * - Extracting IDs from item notes
 * - Setting IDs in item notes
 * - Removing IDs from notes
 * - Targeted ID index removal (O(1) per item)
 *
 * CONVENTION
 *   IDs are stored in item.note as: @mcp:id=<id>
 *   Multiple tags may exist in a note, space-separated.
 *
 * @version 1.0.0
 */

// ==================== ID Extraction ====================

/**
 * Extract MCP ID from an item's note string.
 * @param {string} note - The item.note string
 * @returns {string|null} The ID, or null if not found
 */
function extractMcpId(note) {
    if (!note) return null;
    var match = note.match(/@mcp:id=([^\s@]+)/);
    return match ? match[1] : null;
}

/**
 * Set (or replace) the MCP ID in an item's note.
 * If an existing @mcp:id tag is present, it is replaced.
 * Otherwise the tag is appended.
 *
 * @param {PageItem} item - The Illustrator item
 * @param {string} id - The MCP ID to set
 */
function setMcpId(item, id) {
    if (!item || !id) return;
    var note = item.note || "";
    if (note.match(/@mcp:id=[^\s@]+/)) {
        // Replace existing
        item.note = note.replace(/@mcp:id=[^\s@]+/, "@mcp:id=" + id);
    } else {
        // Append
        item.note = (note ? note + " " : "") + "@mcp:id=" + id;
    }
}

/**
 * Remove the @mcp:id tag from a note string.
 * Returns the cleaned note.
 *
 * @param {string} note - The item.note string
 * @returns {string} Note with @mcp:id tag removed
 */
function removeIdFromNote(note) {
    if (!note) return "";
    return note.replace(/@mcp:id=[^\s@]+/, "").replace(/\s{2,}/g, " ").replace(/^\s+|\s+$/g, "");
}

/**
 * Remove a specific ID from the global ID index.
 * O(1) operation — does NOT rebuild the entire index.
 *
 * @param {string} id - The MCP ID to remove
 * @returns {boolean} True if the ID was found and removed
 */
function removeFromIdIndex(id) {
    if (!id) return false;
    if ($.global.mcpIdIndex && $.global.mcpIdIndex.index) {
        if ($.global.mcpIdIndex.index[id]) {
            delete $.global.mcpIdIndex.index[id];
            return true;
        }
    }
    return false;
}
