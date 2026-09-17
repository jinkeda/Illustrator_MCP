/**
 * mcp_id.jsx — MCP ID Utilities
 * Part of Illustrator MCP Standard Library
 *
 * Single source of truth for MCP ID operations:
 * - Extracting IDs from item notes
 * - Setting IDs in item notes
 * - Removing IDs from notes
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
 * Extract every MCP ID tag from a note string.
 * A note may legitimately carry several space-separated tags.
 *
 * @param {string} note - The item.note string
 * @returns {string[]} All IDs in note order (empty array if none)
 */
function extractAllMcpIds(note) {
    var out = [];
    if (!note) return out;
    var re = /@mcp:id=([^\s@]+)/g;
    var m;
    while ((m = re.exec(note)) !== null) {
        out.push(m[1]);
        // ES3 safety: never spin on a zero-length match
        if (m.index === re.lastIndex) re.lastIndex++;
    }
    return out;
}

/**
 * Test whether a note carries an MCP ID tag exactly equal to `id`.
 *
 * This is the ONLY correct way to match an ID against a note.  Callers
 * must never use `note.indexOf("@mcp:id=" + id) >= 0`: that is a prefix
 * test, so the ID "A" matches a note tagged "@mcp:id=AB" and the wrong
 * artwork is read, modified, or deleted.
 *
 * @param {string} note - The item.note string
 * @param {string} id - The complete ID token to match
 * @returns {boolean} True only on an exact whole-token match
 */
function noteHasMcpId(note, id) {
    if (!note || !id) return false;
    var ids = extractAllMcpIds(note);
    for (var i = 0; i < ids.length; i++) {
        if (ids[i] === id) return true;
    }
    return false;
}

// ==================== DOM traversal ====================

/**
 * Visit every page item in a document, in layer order.
 *
 * WHY THIS EXISTS — `document.pageItems` cannot be trusted for this.
 * Measured on Illustrator 30.7.0: immediately after creating a path,
 * `doc.pageItems.length` was 0 while `doc.activeLayer.pageItems.length` was 1;
 * a later evalScript call then saw both. Anything that creates artwork and
 * verifies it in the same call — the guarded boolean commit, a handle resolved
 * right after a create — would conclude the artwork does not exist.
 *
 * Layer collections refresh immediately, but `layer.pageItems` holds only that
 * layer's DIRECT children (a group counts as one item), so groups and
 * sublayers are walked explicitly.
 *
 * @param {Document} doc - Illustrator document
 * @param {Function} visitor - (item) => truthy to stop early
 * @param {Object} [opts] - { limit: number } max items to visit (0 = all)
 * @returns {Object} {visited, truncated, stopped}
 */
function mcpWalkPageItems(doc, visitor, opts) {
    opts = opts || {};
    var limit = (typeof opts.limit === "number" && opts.limit > 0) ? opts.limit : 0;
    var visited = 0;
    var truncated = false;
    var stopped = false;

    function walkContainer(container) {
        if (stopped || truncated || !container) return;
        var items;
        try { items = container.pageItems; } catch (e) { return; }
        if (!items) return;

        for (var i = 0; i < items.length; i++) {
            if (stopped) return;
            if (limit && visited >= limit) { truncated = true; return; }
            visited++;

            var item = items[i];
            try {
                if (visitor(item)) { stopped = true; return; }
            } catch (e) { /* a visitor error must not abort the walk */ }

            var typename = null;
            try { typename = item.typename; } catch (e) { typename = null; }
            if (typename === "GroupItem") walkContainer(item);
        }
    }

    function walkLayer(layer) {
        if (stopped || truncated || !layer) return;
        walkContainer(layer);
        var sublayers;
        try { sublayers = layer.layers; } catch (e) { sublayers = null; }
        if (!sublayers) return;
        for (var i = 0; i < sublayers.length; i++) walkLayer(sublayers[i]);
    }

    var layers = null;
    try { layers = doc.layers; } catch (e) { layers = null; }
    if (layers) {
        for (var li = 0; li < layers.length; li++) walkLayer(layers[li]);
    } else {
        // No layer collection (a stub, or an unusual document) — fall back.
        walkContainer(doc);
    }

    return { visited: visited, truncated: truncated, stopped: stopped };
}

/**
 * Find the live item identical to `ref`, walking layers rather than
 * `document.pageItems`. Returns {item, matches}.
 *
 * Reference identity is the right test here: a different object is never
 * `===`, so identical-looking artwork cannot silently substitute. What it
 * cannot do alone is notice a *zombie* — after `app.undo()` a stashed
 * reference still reports its typename but is no longer in the document — so
 * callers rely on the item being FOUND in the live tree, not merely readable.
 *
 * @param {Document} doc
 * @param {PageItem} ref
 * @param {Object} opts - Optional {limit} traversal budget (0 = unlimited)
 * @returns {Object} {item, matches, scanned, truncated}
 */
function mcpFindItemByRef(doc, ref, opts) {
    var found = null;
    var matches = 0;
    if (!ref) return { item: null, matches: 0 };
    var walk = mcpWalkPageItems(doc, function (item) {
        try {
            if (item === ref) { matches++; if (!found) found = item; }
        } catch (e) { }
        return false;
    }, opts);
    return { item: matches === 1 ? found : null, matches: matches, scanned: walk.visited, truncated: walk.truncated };
}

/**
 * Find every page item whose note carries exactly this MCP ID.
 *
 * Returns all matches rather than the first, so callers can reject an
 * ambiguous ID instead of silently acting on whichever item the scan
 * happened to reach first.  When `opts.limit` truncates the scan the
 * result says so — an incomplete scan is not proof of a no-match.
 *
 * TRAVERSAL — why this walks layers instead of `doc.pageItems`:
 *
 * `document.pageItems` is NOT reliably refreshed within the same script run.
 * Measured on Illustrator 30.7.0: immediately after creating a path,
 * `doc.pageItems.length` was 0 while `doc.activeLayer.pageItems.length` was 1;
 * a later evalScript call then saw both. Anything verifying artwork it just
 * created — the guarded boolean commit checking its own replacements, for
 * instance — would conclude nothing had been created and refuse to proceed.
 *
 * Layer collections do reflect new items immediately, but `layer.pageItems`
 * holds only that layer's DIRECT children (a group counts as one), so groups
 * and sublayers are walked explicitly.
 *
 * @param {Document} doc - Illustrator document
 * @param {string} id - The complete ID token to match
 * @param {Object} [opts] - { limit: number } max items to scan (0 = all)
 * @returns {Object} {items, scanned, truncated, duplicate}
 */
function findItemsByMcpId(doc, id, opts) {
    var found = [];
    var walk = mcpWalkPageItems(doc, function (item) {
        var note = null;
        try { note = item.note; } catch (e) { return false; }
        if (note && noteHasMcpId(note, id)) {
            for (var i = 0; i < found.length; i++) {
                if (found[i] === item) return false;   // already recorded
            }
            found.push(item);
        }
        return false;
    }, opts);

    return {
        items: found,
        scanned: walk.visited,
        truncated: walk.truncated,
        duplicate: found.length > 1
    };
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
