/**
 * observation.jsx — Coordinated, non-document-mutating evidence capture (T19).
 * @version 1.0.0
 */

var MCP_OBSERVATION_VERSION = "1.0.0";

function _mcpObservationRoot() {
    if (!$.global.__mcpObservationGuards) $.global.__mcpObservationGuards = {};
    return $.global.__mcpObservationGuards;
}

// Called only when a new managed observation owns the coordinator slot.
// Prior records are abandoned; eviction never reconciles a host job.
function _mcpObservationPrune(now) {
    var root = _mcpObservationRoot(), keys = [], key;
    for (key in root) {
        if (!root.hasOwnProperty(key)) continue;
        if (now - root[key].startedAt > 600000) delete root[key];
        else keys.push(key);
    }
    keys.sort(function (a, b) { return root[a].startedAt - root[b].startedAt; });
    while (keys.length >= 32) { key = keys.shift(); delete root[key]; }
}

function _mcpObservationSelection(doc) {
    var out = [];
    try { for (var i = 0; i < doc.selection.length; i++) out.push(doc.selection[i]); } catch (e) { }
    return out;
}

function _mcpObservationBounds(item) {
    try {
        var b = item.visibleBounds;
        return [b[0], b[1], b[2], b[3]];
    } catch (e) { return null; }
}

function _mcpObservationPublicItem(item, documentToken) {
    var note = "";
    try { note = item.note || ""; } catch (e) { }
    var handle = mcpIssueHandle(item, documentToken);
    return {
        name: item.name || item.typename,
        type: item.typename,
        bounds: _mcpObservationBounds(item),
        mcp_id: typeof extractMcpId === "function" ? (extractMcpId(note) || "") : "",
        handle: handle.ok ? handle.record.handle : null,
        handleExpiresAt: handle.ok ? handle.record.expiresAt : null
    };
}

function mcpObservationBegin(observationId, maxItems, clipBox, exactVisibleCount, clipSpace, includeMap) {
    _mcpObservationPrune(new Date().getTime());
    var doc = app.activeDocument;
    var binding = mcpDocBind({ label: "observe" });
    var abIdx = doc.artboards.getActiveArtboardIndex();
    var ab = doc.artboards[abIdx].artboardRect;
    if (clipBox && clipSpace === "illustrator_native_y_up")
        clipBox = [clipBox[0]-ab[0], ab[1]-clipBox[1], clipBox[2]-ab[0], ab[1]-clipBox[3]];
    var limit = maxItems || 200;
    var items = [];
    var guarded = [];
    var totalVisible = 0;
    var cL = ab[0], cT = ab[1], cR = ab[2], cB = ab[3];
    if (clipBox && clipBox.length === 4) {
        cL = Math.max(ab[0], ab[0] + clipBox[0]);
        cT = Math.min(ab[1], ab[1] - clipBox[1]);
        cR = Math.min(ab[2], ab[0] + clipBox[2]);
        cB = Math.max(ab[3], ab[1] - clipBox[3]);
    }
    var scanComplete = true;
    for (var i = 0; i < doc.pageItems.length; i++) {
        if (!exactVisibleCount && (i >= 10000 || totalVisible > limit)) { scanComplete = false; break; }
        var item = doc.pageItems[i];
        try { if (item.hidden || item.guides) continue; } catch (e) { }
        var bounds = _mcpObservationBounds(item);
        if (!bounds || bounds[2] < cL || bounds[0] > cR || bounds[3] > cT || bounds[1] < cB) continue;
        totalVisible++;
        if (guarded.length >= limit) continue;
        var note = "";
        try { note = item.note || ""; } catch (e) { }
        if (includeMap !== false) items.push(_mcpObservationPublicItem(item, _mcpBindingToken(binding)));
        guarded.push({
            item: item,
            type: item.typename,
            name: item.name || "",
            note: note,
            bounds: bounds
        });
    }
    var guard = {
        id: observationId,
        document: doc,
        documentToken: _mcpBindingToken(binding),
        activeLayer: doc.activeLayer,
        activeArtboardIndex: abIdx,
        selection: _mcpObservationSelection(doc),
        saved: doc.saved,
        // Compared against the same source in mcpObservationEnd, so this
        // stays self-consistent even though doc.pageItems can lag a create.
        // It is a change HINT, not a revision number.
        artworkCount: doc.pageItems.length,
        guardedItems: guarded,
        complete: scanComplete && totalVisible <= limit,
        startedAt: new Date().getTime()
    };
    _mcpObservationRoot()[observationId] = guard;
    var runtime = typeof mcpRuntimeState === "function" ? mcpRuntimeState() : null;
    return {
        ok: true,
        observationId: observationId,
        context: {
            documentToken: _mcpBindingToken(binding),
            documentName: doc.name || "",
            activeArtboardIndex: abIdx,
            artboard: [ab[0], ab[1], ab[2], ab[3]],
            activeLayer: doc.activeLayer ? doc.activeLayer.name : null
        },
        items: items,
        totalVisible: totalVisible,
        totalVisibleExact: scanComplete,
        mapComplete: scanComplete && totalVisible <= limit,
        runtime: runtime ? {
            sessionEpoch: runtime.sessionEpoch || null,
            protocolVersion: runtime.protocolVersion || null
        } : null,
        omissions: !scanComplete || totalVisible > limit ? [{
            kind: "annotation_map", reason: "bounded_scan_or_max_items", omitted: scanComplete ? totalVisible - limit : null, omittedLowerBound: Math.max(0, totalVisible - limit)
        }] : []
    };
}

function mcpObservationEnd(observationId) {
    var root = _mcpObservationRoot();
    var guard = root[observationId];
    if (!guard) return { ok: false, status: "unavailable", message: "Observation guard is missing" };
    delete root[observationId];
    var differences = [];
    var doc = null;
    try { doc = app.activeDocument; } catch (e) { }
    if (!doc || doc !== guard.document) {
        return { ok: false, status: "failed", differences: ["active_document_changed"], complete: guard.complete };
    }
    if (doc.artboards.getActiveArtboardIndex() !== guard.activeArtboardIndex) differences.push("active_artboard_changed");
    if (doc.activeLayer !== guard.activeLayer) differences.push("active_layer_changed");
    if (doc.saved !== guard.saved) differences.push("document_saved_state_changed");
    if (doc.pageItems.length !== guard.artworkCount) differences.push("artwork_count_changed");
    var selection = _mcpObservationSelection(doc);
    if (selection.length !== guard.selection.length) differences.push("selection_changed");
    else {
        for (var si = 0; si < selection.length; si++) {
            if (selection[si] !== guard.selection[si]) { differences.push("selection_changed"); break; }
        }
    }
    // One live DOM traversal, retaining reference identity and ambiguity checks.
    var foundItems = [], matchCounts = [];
    for (var mi = 0; mi < guard.guardedItems.length; mi++) { foundItems.push(null); matchCounts.push(0); }
    mcpWalkPageItems(doc, function (candidate) {
        for (var ri = 0; ri < guard.guardedItems.length; ri++) {
            if (candidate === guard.guardedItems[ri].item) {
                foundItems[ri] = candidate;
                matchCounts[ri]++;
            }
        }
        return false;
    });
    for (var gi = 0; gi < guard.guardedItems.length; gi++) {
        var prior = guard.guardedItems[gi];
        // Walk layers, not doc.pageItems: the document-level collection is not
        // refreshed within a script run (HOST_PERSISTENCE_FINDINGS §4), so a
        // stale read here would report every guarded item as
        // "artwork_identity_changed" and turn a clean observation into a
        // spurious preservation failure.
        var found = matchCounts[gi] === 1 ? foundItems[gi] : null;
        if (!found) { differences.push("artwork_identity_changed:" + gi); continue; }
        var note = "";
        try { note = found.note || ""; } catch (e) { }
        if (note !== prior.note) differences.push("note_changed:" + gi);
        if ((found.name || "") !== prior.name) differences.push("name_changed:" + gi);
        if (found.typename !== prior.type) differences.push("type_changed:" + gi);
        if (JSON.stringify(_mcpObservationBounds(found)) !== JSON.stringify(prior.bounds)) {
            differences.push("bounds_changed:" + gi);
        }
    }
    return {
        ok: differences.length === 0,
        status: differences.length === 0 ? "passed" : "failed",
        complete: guard.complete,
        differences: differences,
        durationMs: new Date().getTime() - guard.startedAt
    };
}
