/**
 * auto_tag.jsx — Auto-assign MCP IDs to untagged items
 * Part of Illustrator MCP Standard Library
 * @version 1.0.0
 *
 * Called by execute_script post-execution to tag newly created items.
 *
 * PARAMS (__PARAMS__):
 *   mode     {string}  "delta" | "converge"
 *   scope    {string}  "activeLayer" | "document"
 *   cap      {number}  Hard limit on items to tag (default 200)
 *   preCount {number}  Item count before script execution (same scope)
 *   cushion  {number}  Extra tags beyond delta (default 2)
 *
 * ALGORITHM (delta mode):
 *   1. Compute expectedDelta = postCount - preCount
 *   2. need = min(cap, expectedDelta + cushion)
 *   3. Selection-first: scan doc.selection for untagged items, tag up to "need"
 *   4. Scope fallback: scan scope pageItems for remaining untagged, up to "need"
 *   5. Stop as soon as tagged == need or scanned all items
 *
 * ALGORITHM (converge mode):
 *   1. need = cap
 *   2. Scan scope pageItems, tag all untagged up to cap
 *   (No selection priority — this is a bulk migration tool)
 *
 * DEPENDENCIES: mcp_id (extractMcpId, setMcpId)
 *
 * RETURNS: {tagged, cap_hit, need, skipped, assigned, errors}
 */
(function () {
    var P = (typeof __PARAMS__ !== "undefined") ? __PARAMS__ : {};
    var mode = P.mode || "delta";
    var scope = P.scope || "activeLayer";
    var cap = P.cap || 200;
    var preCount = P.preCount || 0;
    var cushion = P.cushion || 2;

    var doc;
    try { doc = app.activeDocument; } catch (e) {
        return JSON.stringify({
            tagged: 0, cap_hit: false, need: 0,
            skipped: { locked: 0, error: 0 },
            assigned: [], errors: ["No active document"]
        });
    }

    // Resolve scope collection
    var collection;
    if (scope === "activeLayer") {
        collection = doc.activeLayer.pageItems;
    } else {
        collection = doc.pageItems;
    }

    var postCount = collection.length;

    // Compute need
    var need;
    if (mode === "delta") {
        var expectedDelta = Math.max(0, postCount - preCount);
        need = Math.min(cap, expectedDelta + cushion);
    } else {
        // converge mode
        need = cap;
    }

    // Early exit if nothing to do
    if (need <= 0) {
        return JSON.stringify({
            tagged: 0, cap_hit: false, need: 0,
            skipped: { locked: 0, error: 0 },
            assigned: [], errors: []
        });
    }

    var tagged = 0;
    var skippedLocked = 0;
    var skippedError = 0;
    var assigned = [];
    var errors = [];
    var MAX_ERRORS = 10;
    // Track already-processed items to avoid double-tagging
    var seen = {};
    var seenCount = 0;

    /**
     * Try to tag a single item. Returns true if tagged.
     */
    function tryTag(item) {
        if (tagged >= need) return false;

        // Check if already has MCP ID
        var note = "";
        try { note = item.note || ""; } catch (e) { return false; }
        var existingId = extractMcpId(note);
        if (existingId) return false; // Already tagged

        // Generate dedup key from typename + index
        // (We can't reliably hash PageItems in ES3, so use name+type+bounds)
        var key = "";
        try {
            var b = item.visibleBounds;
            key = item.typename + "_" + b[0] + "_" + b[1] + "_" + b[2] + "_" + b[3];
        } catch (e) {
            key = item.typename + "_" + seenCount;
        }
        if (seen[key]) return false;
        seen[key] = true;
        seenCount++;

        // Try to write ID
        var newId = "mcp_" + (new Date().getTime()) + "_" + Math.floor(Math.random() * 10000);
        try {
            setMcpId(item, newId);
        } catch (e) {
            // Likely locked item
            if (e.message && e.message.indexOf("locked") >= 0) {
                skippedLocked++;
            } else {
                skippedError++;
                if (errors.length < MAX_ERRORS) {
                    errors.push(e.message || String(e));
                }
            }
            return false;
        }

        // Get layer name safely
        var layerName = "";
        try { layerName = item.layer.name; } catch (e2) { }

        assigned.push({
            id: newId,
            typename: item.typename,
            name: item.name || "",
            layerName: layerName
        });
        tagged++;
        return true;
    }

    // === Phase 1: Selection-first (delta mode only) ===
    if (mode === "delta") {
        try {
            var sel = doc.selection;
            if (sel && sel.length > 0) {
                for (var s = 0; s < sel.length && tagged < need; s++) {
                    __mcp_check();
                    tryTag(sel[s]);
                }
            }
        } catch (e) {
            // doc.selection may fail in some states
        }
    }

    // === Phase 2: Scope scan (both modes) ===
    if (tagged < need) {
        for (var i = 0; i < collection.length && tagged < need; i++) {
            __mcp_check();
            var it = collection[i];
            // Skip hidden items in scan (but still tag if selected in Phase 1)
            if (it.hidden) continue;
            tryTag(it);
        }
    }

    var cap_hit = (tagged >= cap);

    return JSON.stringify({
        tagged: tagged,
        cap_hit: cap_hit,
        need: need,
        skipped: { locked: skippedLocked, error: skippedError },
        assigned: assigned,
        errors: errors
    });
})();
