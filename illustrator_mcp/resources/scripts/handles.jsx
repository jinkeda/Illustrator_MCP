/**
 * Read the document-session token out of an mcpDocBind() result.
 *
 * doc_session.jsx returns the token as `token`. This module previously read
 * `binding.documentToken`, which is always undefined — so mcpIssueHandle
 * always failed with "A document token is required" and NO handle could ever
 * be issued. Nothing caught it because the JSX harness exercises the two
 * modules separately, never together against a live document.
 *
 * `documentToken` is still accepted so an explicitly-passed token keeps
 * working.
 *
 * @param {Object} binding - result of mcpDocBind()
 * @returns {string|null}
 */
function _mcpBindingToken(binding) {
    if (!binding) return null;
    return binding.token || binding.documentToken || null;
}

/**
 * handles.jsx — Ephemeral identity for untagged Illustrator artwork (T18).
 *
 * Handles live only in the persistent ExtendScript engine. They never write
 * item.note or item.name. Resolution requires the same live document and the
 * exact retained DOM object to appear in a fresh document scan; type, bounds,
 * name, and index are evidence only and are never used as substitute identity.
 *
 * @version 1.0.0
 */

var MCP_HANDLE_VERSION = "1.0.0";
var MCP_HANDLE_RETENTION_MS = 5 * 60 * 1000;
var MCP_HANDLE_MAX_RECORDS = 500;

function _mcpHandleOwn(obj, key) {
    return Object.prototype.hasOwnProperty.call(obj, key);
}

function _mcpHandleStore() {
    var root = $.global;
    if (!root.__mcpHandleStore) {
        root.__mcpHandleStore = {
            version: MCP_HANDLE_VERSION,
            epoch: "he_" + new Date().getTime() + "_" + Math.floor(Math.random() * 1000000000),
            counter: 0,
            records: {},
            order: []
        };
    }
    return root.__mcpHandleStore;
}

function _mcpHandlePublic(record) {
    if (!record) return null;
    return {
        handle: record.handle,
        documentToken: record.documentToken,
        sessionEpoch: record.sessionEpoch,
        issuedAt: record.issuedAt,
        expiresAt: record.expiresAt,
        itemType: record.itemType,
        itemName: record.itemName,
        bounds: record.bounds,
        status: record.status || "live"
    };
}

function _mcpHandlePrune() {
    var store = _mcpHandleStore();
    var now = new Date().getTime();
    var kept = [];
    var i;
    for (i = 0; i < store.order.length; i++) {
        var key = store.order[i];
        var record = store.records[key];
        if (!record || record.expiresAt <= now || record.status === "invalid") {
            delete store.records[key];
        } else {
            kept.push(key);
        }
    }
    while (kept.length > MCP_HANDLE_MAX_RECORDS) {
        delete store.records[kept.shift()];
    }
    store.order = kept;
}

function _mcpHandleBounds(item) {
    try {
        var b = item.visibleBounds;
        return [b[0], b[1], b[2], b[3]];
    } catch (e) { return null; }
}

function mcpIssueHandle(item, documentToken) {
    if (!item) return { ok: false, status: "invalid", message: "Cannot issue a handle for an empty item" };
    _mcpHandlePrune();
    var store = _mcpHandleStore();
    var binding = null;
    if (!documentToken && typeof mcpDocBind === "function") {
        try { binding = mcpDocBind({ label: "handle" }); documentToken = _mcpBindingToken(binding); }
        catch (e) { return { ok: false, status: "no_document", message: e.message || String(e) }; }
    }
    if (!documentToken) {
        return { ok: false, status: "no_document_token", message: "A document token is required" };
    }
    var now = new Date().getTime();
    var i;
    for (i = 0; i < store.order.length; i++) {
        var existing = store.records[store.order[i]];
        if (existing && existing.documentToken === documentToken && existing.item === item) {
            existing.expiresAt = now + MCP_HANDLE_RETENTION_MS;
            existing.bounds = _mcpHandleBounds(item);
            return { ok: true, status: "live", record: _mcpHandlePublic(existing) };
        }
    }
    store.counter++;
    var handle = "mcp_h_" + store.epoch + "_" + store.counter + "_" + Math.floor(Math.random() * 1000000000);
    var runtime = (typeof mcpRuntimeState === "function") ? mcpRuntimeState() : null;
    var record = {
        handle: handle,
        documentToken: documentToken,
        sessionEpoch: runtime && runtime.sessionEpoch ? runtime.sessionEpoch : store.epoch,
        issuedAt: now,
        expiresAt: now + MCP_HANDLE_RETENTION_MS,
        item: item,
        itemType: item.typename || "PageItem",
        itemName: item.name || "",
        bounds: _mcpHandleBounds(item),
        status: "live"
    };
    store.records[handle] = record;
    store.order.push(handle);
    _mcpHandlePrune();
    return { ok: true, status: "live", record: _mcpHandlePublic(record) };
}

function mcpIssueHandles(items, documentToken) {
    var out = [];
    for (var i = 0; i < items.length; i++) out.push(mcpIssueHandle(items[i], documentToken));
    return out;
}

function mcpResolveHandle(handle, doc, opts) {
    _mcpHandlePrune();
    var store = _mcpHandleStore();
    if (typeof handle !== "string" || handle.indexOf("mcp_h_") !== 0 || !_mcpHandleOwn(store.records, handle)) {
        return { ok: false, status: "unknown", message: "Unknown or expired artwork handle" };
    }
    var record = store.records[handle];
    if (typeof mcpDocValidate !== "function") {
        return { ok: false, status: "unavailable", message: "Document-session validation is unavailable" };
    }
    var validated = mcpDocValidate(record.documentToken, { requireActive: true });
    if (!validated.ok) {
        record.status = "invalid";
        return { ok: false, status: "stale", message: "Handle document is no longer current: " + validated.status };
    }
    doc = doc || validated.document;

    // Walk LAYERS, not doc.pageItems: the document-level collection is not
    // refreshed within a script run (Illustrator 30.7.0 — see
    // docs/HOST_PERSISTENCE_FINDINGS.md), so a handle to artwork created
    // earlier in the same call would resolve as stale.
    //
    // Requiring the item to be FOUND in the live tree is also what catches a
    // zombie: after app.undo() a stashed reference still reports its typename
    // and reads without throwing, but it is no longer in the document. A
    // check that only read properties off the reference would happily hand
    // back deleted artwork.
    var scan = opts && opts.scan;
    if (scan && scan.limit && scan.visited >= scan.limit) return {ok:false, status:"incomplete"};
    var located = mcpFindItemByRef(doc, record.item, {limit:scan && scan.limit ? scan.limit-scan.visited : 0});
    if (scan) scan.visited += located.scanned;
    if (located.truncated) return {ok:false, status:"incomplete"};
    if (!located.item) {
        record.status = "invalid";
        return {
            ok: false,
            status: located.matches > 1 ? "ambiguous" : "stale",
            message: "The exact artwork object can no longer be resolved",
            matches: located.matches
        };
    }
    var current = located.item;
    if ((current.typename || "PageItem") !== record.itemType) {
        record.status = "invalid";
        return { ok: false, status: "stale", message: "Artwork type changed for handle" };
    }
    record.expiresAt = new Date().getTime() + MCP_HANDLE_RETENTION_MS;
    record.bounds = _mcpHandleBounds(current);
    return { ok: true, status: "live", item: current, record: _mcpHandlePublic(record) };
}

function mcpHandleStatus(handle) {
    var resolved = mcpResolveHandle(handle, null);
    return {
        ok: resolved.ok,
        status: resolved.status,
        message: resolved.message || null,
        record: resolved.record || null
    };
}

function mcpHandleInvalidateAll(reason) {
    var store = _mcpHandleStore();
    var count = store.order.length;
    store.records = {};
    store.order = [];
    store.epoch = "he_" + new Date().getTime() + "_" + Math.floor(Math.random() * 1000000000);
    store.counter = 0;
    return { ok: true, invalidated: count, reason: reason || "reset", epoch: store.epoch };
}

function mcpHandleState() {
    _mcpHandlePrune();
    var store = _mcpHandleStore();
    return { version: store.version, epoch: store.epoch, retained: store.order.length, maxRecords: MCP_HANDLE_MAX_RECORDS };
}
