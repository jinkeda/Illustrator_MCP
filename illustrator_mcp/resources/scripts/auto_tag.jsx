/**
 * auto_tag.jsx — Auto-assign MCP IDs to untagged items
 * Part of Illustrator MCP Standard Library
 * @version 1.1.0
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
 * DEPENDENCIES: item_ref (assignItemIdV2)
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

    // Reference-identity dedup: track seen items via array + === comparison
    // O(n²) but fine for cap <= 200
    var seen = [];

    function alreadySeen(item) {
        for (var i = 0; i < seen.length; i++) {
            if (seen[i] === item) return true;
        }
        seen.push(item);
        return false;
    }

    /**
     * Try to tag a single item. Returns true if tagged.
     * Delegates ID assignment to assignItemIdV2(item, "opt_in"):
     *   - has existing ID → returns {assigned: false, id: existingId}
     *   - no existing ID → generates + writes new ID {assigned: true, id: newId}
     */
    function tryTag(item) {
        if (tagged >= need) return false;

        // Skip already-processed items (dedup across selection + scan phases)
        if (alreadySeen(item)) return false;

        // Delegate to assignItemIdV2 — handles check + assign in one call
        var result;
        try {
            result = assignItemIdV2(item, "opt_in");
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

        if (!result.assigned) return false; // Already had an ID

        if (result.error) {
            skippedError++;
            if (errors.length < MAX_ERRORS) {
                errors.push(result.error);
            }
            return false;
        }

        // Get layer name safely
        var layerName = "";
        try { layerName = item.layer.name; } catch (e2) { }

        assigned.push({
            id: result.id,
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
