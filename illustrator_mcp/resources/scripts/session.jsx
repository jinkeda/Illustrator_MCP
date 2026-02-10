/**
 * session.jsx - Session-scoped stash for multi-call IR handoff
 * Part of Illustrator MCP SOC Framework
 *
 * Provides key-value storage in $.global that persists across
 * execute_script calls within a single Illustrator session.
 * Lost on app quit/crash — this is a session cache, not a database.
 *
 * Keys are automatically namespaced by document name to prevent
 * cross-document collisions.
 *
 * @version 1.0.0
 */

// ==================== Stash Namespace ====================

// Initialize global stash containers (idempotent)
if (!$.global.__mcp_stash) $.global.__mcp_stash = {};
if (!$.global.__mcp_stash_meta) $.global.__mcp_stash_meta = {};

/**
 * Build namespaced key: "docName::userKey"
 * Falls back to "__no_doc__" if no document is open.
 * @param {string} userKey
 * @returns {string}
 */
function _stashNS(userKey) {
    var docName = "__no_doc__";
    try {
        if (app.documents.length > 0) docName = app.activeDocument.name;
    } catch (e) { /* no doc */ }
    return docName + "::" + userKey;
}

// ==================== Core Stash API ====================

/**
 * Store arbitrary data in the session stash.
 * @param {string} key - User-facing key (auto-namespaced by doc)
 * @param {*} data - Any serializable data
 * @param {Object} [meta] - Optional metadata (e.g., generator name, version)
 */
function stashPut(key, data, meta) {
    var ns = _stashNS(key);
    $.global.__mcp_stash[ns] = data;
    $.global.__mcp_stash_meta[ns] = {
        key: key,
        ns: ns,
        ts: new Date().getTime(),
        size: typeof data === "object" ? JSON.stringify(data).length : String(data).length,
        meta: meta || {}
    };
}

/**
 * Retrieve data from the session stash.
 * Returns a direct reference — do NOT mutate.
 * @param {string} key
 * @returns {*|null}
 */
function stashGet(key) {
    var ns = _stashNS(key);
    var val = $.global.__mcp_stash[ns];
    return val !== undefined ? val : null;
}

/**
 * Store Geometry IR with schema validation.
 * Rejects invalid/corrupt IR before it sits in memory.
 * @param {string} key
 * @param {Object} irData - Must pass irValidate()
 * @param {Object} [meta] - Optional generator metadata
 * @returns {Object} { ok: boolean, errors?: string[] }
 */
function stashPutIR(key, irData, meta) {
    // Dependency check: irValidate must be loaded (from geo_ir.jsx)
    if (typeof irValidate !== "function") {
        return { ok: false, errors: ["stashPutIR requires geo_ir.jsx (irValidate not found)"] };
    }

    var validation = irValidate(irData);
    if (!validation.ok) {
        return { ok: false, errors: validation.errors };
    }

    stashPut(key, irData, meta);
    return { ok: true };
}

/**
 * List all stash keys for the current document.
 * @returns {string[]} - User-facing keys (without namespace prefix)
 */
function stashKeys() {
    var docPrefix = _stashNS("").replace(/::.*/, "::"); // "docName::"
    var keys = [];
    for (var ns in $.global.__mcp_stash) {
        if (ns.indexOf(docPrefix) === 0) {
            keys.push(ns.substring(docPrefix.length));
        }
    }
    return keys;
}

/**
 * Remove a key or clear all keys for the current document.
 * @param {string} [key] - If omitted, clears ALL keys for this document
 */
function stashClear(key) {
    if (key) {
        var ns = _stashNS(key);
        delete $.global.__mcp_stash[ns];
        delete $.global.__mcp_stash_meta[ns];
    } else {
        // Clear all keys for current doc
        var docPrefix = _stashNS("").replace(/::.*/, "::");
        for (var ns in $.global.__mcp_stash) {
            if (ns.indexOf(docPrefix) === 0) {
                delete $.global.__mcp_stash[ns];
                delete $.global.__mcp_stash_meta[ns];
            }
        }
    }
}

/**
 * Get metadata for all stash entries (current document).
 * Useful for debugging and stash inspection.
 * @returns {Object} - Map of userKey → {ts, size, meta}
 */
function stashInfo() {
    var docPrefix = _stashNS("").replace(/::.*/, "::");
    var info = {};
    for (var ns in $.global.__mcp_stash_meta) {
        if (ns.indexOf(docPrefix) === 0) {
            var userKey = ns.substring(docPrefix.length);
            info[userKey] = $.global.__mcp_stash_meta[ns];
        }
    }
    return info;
}
