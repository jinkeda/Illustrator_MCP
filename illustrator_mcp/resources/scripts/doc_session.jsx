/**
 * doc_session.jsx — opaque document session identity + coordinate context (T13)
 *
 * A job must be able to say "operate on THIS document" and have that mean the
 * same thing on every later call, even if the user switches documents, renames
 * one, or closes it.
 *
 * WHY NOT THE DOCUMENT NAME. `session.jsx` keys its stash by
 * `app.activeDocument.name`. A name is a locator, not an identity: two open
 * documents can share one, an unsaved document's name changes the moment it is
 * saved, and a name says nothing about whether the document is still open.
 *
 * WHAT IS USED INSTEAD — measured on Illustrator 30.7.0, see
 * docs/HOST_PERSISTENCE_FINDINGS.md and the T13 probes:
 *
 *   ref === app.activeDocument        works — strict identity comparison
 *   another document becomes active   the stored ref stays readable, and the
 *                                     comparison correctly returns false
 *   doc.saveAs(...) renames the doc   name changes, REFERENCE IDENTITY DOES NOT
 *   the document is closed            reading through the ref throws
 *                                     "Object is invalid" — clean, detectable
 *
 * So a token is bound to a live document reference held on `$.global`. That
 * gives identity that survives renaming and focus changes, and invalidates
 * itself on close — which is exactly the contract T13 asks for.
 *
 * NOT A SANDBOX. A token identifies a document; it does not prevent a script
 * from reaching others. Raw scripts can still touch anything, and this module
 * never claims otherwise — it reports which document a job was bound to and
 * whether that binding still holds.
 *
 * @exports mcpDocBind, mcpDocValidate, mcpDocContext, mcpDocRelease,
 *          mcpDocSessions, MCP_DOC_SESSION_VERSION
 * @version 1.1.0
 */

var MCP_DOC_SESSION_VERSION = "1.1.0";
var MCP_DOC_SESSION_KEY = "__mcpDocSessions";

// ==================== Internals ====================

function _mcpDocStore() {
    if (!$.global[MCP_DOC_SESSION_KEY]) {
        $.global[MCP_DOC_SESSION_KEY] = { entries: [], counter: 0 };
    }
    return $.global[MCP_DOC_SESSION_KEY];
}

function _mcpDocNewToken() {
    var store = _mcpDocStore();
    store.counter++;
    var now = new Date().getTime();
    var rand = Math.floor(Math.random() * 0xFFFFFF);
    return "doc_" + now.toString(16) + "_" + rand.toString(16) + "_" + store.counter;
}

/** The active document, or null when none is open. */
function _mcpActiveDoc() {
    try {
        if (app.documents.length === 0) return null;
        return app.activeDocument;
    } catch (e) {
        return null;
    }
}

/**
 * Is this reference still a live document?
 * A closed document's reference throws on property access.
 */
function _mcpRefAlive(ref) {
    try {
        var probe = ref.name;   // throws "Object is invalid" once closed
        return typeof probe === "string";
    } catch (e) {
        return false;
    }
}

function _mcpFindEntry(token) {
    var entries = _mcpDocStore().entries;
    for (var i = 0; i < entries.length; i++) {
        if (entries[i].token === token) return entries[i];
    }
    return null;
}

function _mcpFindEntryForRef(ref) {
    var entries = _mcpDocStore().entries;
    for (var i = 0; i < entries.length; i++) {
        try {
            if (entries[i].ref === ref) return entries[i];
        } catch (e) { /* dead ref — skip */ }
    }
    return null;
}

/** Drop entries whose documents have been closed. */
function _mcpPruneEntries() {
    var store = _mcpDocStore();
    var kept = [];
    for (var i = 0; i < store.entries.length; i++) {
        if (_mcpRefAlive(store.entries[i].ref)) kept.push(store.entries[i]);
    }
    store.entries = kept;
    return store;
}

// ==================== Coordinate context ====================

/**
 * ER03 visibility prototype. One native candidate read, no traversal or writes.
 * No host version is qualified yet: even a false candidate cannot prove that
 * nested isolation is absent. Do not use this diagnostic for admission.
 */
function _mcpEditingScope(doc) {
    var started = new Date().getTime();
    var scope = {
        kind: "unknown", rootIdentity: null,
        qualification: "unqualified", host: {name: null, version: null},
        evidence: {property: "activeLayer.isIsolated", status: "unavailable", value: null},
        limitation: "Active-layer evidence is not qualified to establish document editing scope or an isolation root.",
        observedAt: started, elapsedMs: 0
    };
    try { var hostName = app.name; if (typeof hostName === "string") scope.host.name = hostName; } catch (e) { }
    try { var hostVersion = app.version; if (typeof hostVersion === "string") scope.host.version = hostVersion; } catch (e) { }
    try {
        if (doc !== _mcpActiveDoc()) {
            scope.evidence.status = "inactive_document";
        } else {
            var candidate = doc.activeLayer.isIsolated;
            if (typeof candidate === "boolean") {
                scope.evidence.status = "observed";
                scope.evidence.value = candidate;
            } else {
                scope.evidence.status = "unsupported";
            }
        }
    } catch (e) {
        // Native exceptions must not turn an admitted mutation into a failure.
        scope.evidence.status = "probe_error";
    }
    scope.elapsedMs = new Date().getTime() - started;
    return scope;
}

/**
 * The coordinate frame a job should use, stated explicitly.
 *
 * Two conventions coexist in this codebase and disagree on any artboard whose
 * origin is not (0,0): placement uses raw document coordinates
 * (`left = x, top = -y`) while the element/geometry helpers offset by the
 * active artboard. Same apparent input, different position on a second
 * artboard. Rather than pick a winner here, the context reports BOTH the
 * artboard rect and the offset needed to convert, so every caller can agree
 * on what a coordinate means.
 *
 * `artboardOffset` converts artboard-relative Y-down (the SOC convention) to
 * Illustrator document coordinates:
 *     x_doc = artboardOffset.x + x_soc
 *     y_doc = artboardOffset.y - y_soc
 *
 * @param {Document} doc
 * @returns {Object} coordinate context
 */
function _mcpCoordContext(doc) {
    var context = {
        editingScope: _mcpEditingScope(doc),
        units: "pt",
        yAxis: "down",
        origin: "artboard",
        artboardIndex: null,
        artboardName: null,
        artboardRect: null,
        artboardOffset: null,
        artboardSize: null,
        documentSize: null
    };
    try {
        context.documentSize = { width: doc.width, height: doc.height };
    } catch (e) { }
    try {
        var index = doc.artboards.getActiveArtboardIndex();
        var board = doc.artboards[index];
        var rect = board.artboardRect;   // [left, top, right, bottom], Y-up
        context.artboardIndex = index;
        context.artboardName = board.name;
        context.artboardRect = [rect[0], rect[1], rect[2], rect[3]];
        context.artboardOffset = { x: rect[0], y: rect[1] };
        context.artboardSize = {
            width: rect[2] - rect[0],
            height: rect[1] - rect[3]
        };
    } catch (e) { }
    return context;
}

// ==================== Public API ====================

/**
 * Bind the active document to an opaque session token.
 *
 * Re-binding the same document returns the SAME token, so a job that binds
 * twice does not fragment its own identity.
 *
 * @param {Object} [opts] - {label: string}
 * @returns {Object} {ok, status, token, name, saved, context}
 *   status: "bound" | "no_document"
 */
function mcpDocBind(opts) {
    opts = opts || {};
    _mcpPruneEntries();

    var doc = opts.document || _mcpActiveDoc();
    if (!doc) {
        // An app-level request with no document open is a legitimate state,
        // not an error — it simply cannot be document-bound.
        return {
            ok: true,
            status: "no_document",
            token: null,
            detail: "No document is open; this request cannot be document-bound."
        };
    }

    var existing = _mcpFindEntryForRef(doc);
    if (existing) {
        return {
            ok: true,
            status: "bound",
            token: existing.token,
            name: doc.name,
            reused: true,
            context: _mcpCoordContext(doc)
        };
    }

    var entry = {
        token: _mcpDocNewToken(),
        ref: doc,
        boundAt: new Date().getTime(),
        boundName: doc.name,       // recorded for diagnostics ONLY
        label: opts.label || ""
    };
    _mcpDocStore().entries.push(entry);

    return {
        ok: true,
        status: "bound",
        token: entry.token,
        name: doc.name,
        reused: false,
        context: _mcpCoordContext(doc)
    };
}

/** Enumerate live reference tokens without activating documents. */
function mcpDocList() {
    var documents = [];
    for (var i = 0; i < app.documents.length; i++) {
        documents.push(mcpDocBind({document: app.documents[i]}));
    }
    return {documents: documents, active: mcpDocBind()};
}

/** Explicit lifecycle transition; never used by ordinary guards. */
function mcpDocActivate(token) {
    var check = mcpDocValidate(token, {requireActive: false});
    if (!check.ok) return check;
    _mcpFindEntry(token).ref.activate();
    return {ok: true, data: mcpDocBind()};
}

/**
 * Check that a token still refers to a usable document.
 *
 * @param {string} token
 * @param {Object} [opts] - {requireActive: boolean} default true
 * @returns {Object} {ok, status, ...}
 *   status: "valid"         — bound document is open AND active
 *           "not_active"    — open, but a different document is active
 *           "closed"        — the bound document has been closed
 *           "unknown_token" — never minted here, or the runtime was reset
 *           "no_document"   — nothing is open at all
 */
function mcpDocValidate(token, opts) {
    opts = opts || {};
    var requireActive = opts.requireActive !== false;

    if (!token) {
        return {
            ok: false, status: "unknown_token",
            message: "No document session token supplied."
        };
    }

    var entry = _mcpFindEntry(token);
    if (!entry) {
        return {
            ok: false, status: "unknown_token",
            message: "Unknown document session token " + token + ". It was " +
                "never issued by this runtime, or the runtime was reset. " +
                "Re-bind before mutating."
        };
    }

    if (!_mcpRefAlive(entry.ref)) {
        return {
            ok: false, status: "closed",
            message: "The bound document has been closed. Its token is void; " +
                "a reopened document is a different document.",
            boundName: entry.boundName
        };
    }

    var active = _mcpActiveDoc();
    if (!active) {
        return {
            ok: false, status: "no_document",
            message: "No document is active."
        };
    }

    var isActive = false;
    try { isActive = (entry.ref === active); } catch (e) { isActive = false; }

    if (!isActive && requireActive) {
        var activeName = "";
        try { activeName = active.name; } catch (e) { }
        return {
            ok: false, status: "not_active",
            message: "The bound document is open but is not the active " +
                "document (active: " + activeName + "). Refusing to act on " +
                "the wrong document.",
            boundName: entry.boundName,
            currentName: entry.ref.name,
            activeName: activeName
        };
    }

    return {
        ok: true,
        status: isActive ? "valid" : "valid_inactive",
        token: token,
        // Reported so a rename is visible without being treated as a change
        // of identity — the reference, not the name, is the identity.
        boundName: entry.boundName,
        currentName: entry.ref.name,
        renamed: entry.ref.name !== entry.boundName,
        isActive: isActive,
        context: _mcpCoordContext(entry.ref)
    };
}

/**
 * Coordinate context for a token, or for the active document if omitted.
 *
 * @param {string} [token]
 * @returns {Object} {ok, status, context}
 */
function mcpDocContext(token) {
    if (token) {
        var validation = mcpDocValidate(token, { requireActive: false });
        if (!validation.ok) return validation;
        return { ok: true, status: validation.status, context: validation.context };
    }
    var doc = _mcpActiveDoc();
    if (!doc) {
        return { ok: false, status: "no_document", message: "No document is open." };
    }
    return { ok: true, status: "unbound", context: _mcpCoordContext(doc) };
}

/**
 * Release a token. Idempotent.
 * @param {string} token
 * @returns {Object} {ok, released}
 */
function mcpDocRelease(token) {
    var store = _mcpDocStore();
    var kept = [];
    var released = false;
    for (var i = 0; i < store.entries.length; i++) {
        if (store.entries[i].token === token) { released = true; }
        else { kept.push(store.entries[i]); }
    }
    store.entries = kept;
    return { ok: true, released: released };
}

/**
 * Diagnostics: every live session.
 * @returns {Object} {count, sessions}
 */
function mcpDocSessions() {
    _mcpPruneEntries();
    var entries = _mcpDocStore().entries;
    var out = [];
    for (var i = 0; i < entries.length; i++) {
        var name = null;
        try { name = entries[i].ref.name; } catch (e) { }
        out.push({
            token: entries[i].token,
            boundName: entries[i].boundName,
            currentName: name,
            label: entries[i].label,
            boundAt: entries[i].boundAt
        });
    }
    return { count: out.length, sessions: out };
}

// ==================== Exports ====================

if (typeof $.global !== "undefined") {
    $.global.mcpDocBind = mcpDocBind;
    $.global.mcpDocValidate = mcpDocValidate;
    $.global.mcpDocContext = mcpDocContext;
    $.global.mcpDocRelease = mcpDocRelease;
    $.global.mcpDocSessions = mcpDocSessions;
    $.global.MCP_DOC_SESSION_VERSION = MCP_DOC_SESSION_VERSION;
}
