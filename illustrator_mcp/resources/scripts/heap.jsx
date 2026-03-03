/**
 * heap.jsx - Transaction-Scoped ID Index
 * Part of Illustrator MCP SOC Framework
 * @version 1.0.0
 *
 * Replaces ad-hoc ID index in ops_core.jsx with a
 * transaction-aware heap that supports begin/commit/rollback.
 *
 * INVARIANTS:
 * - heapBeginTxn() before any op execution
 * - heapCommitTxn() only on full batch success
 * - heapRollbackTxn() on batch failure
 * - At most one heapRebuildIndex() per batch (guarded by txn.resyncUsed)
 *
 * DEPENDENCIES: mcp_id (extractMcpId)
 */

// ==================== State ====================

// Global index: uuid -> PageItem ref
// Persists across batches within a session via $.global
if (!$.global.mcpHeap) {
    $.global.mcpHeap = {
        index: {},
        docName: null
    };
}

// Current transaction (null when no batch is active)
var _heapTxn = null;

// Module-level warning accumulator (cleared on each heapBeginTxn)
var _heapWarnings = [];

// Rebuild cap: maximum items scanned during heapRebuildIndex
var _HEAP_REBUILD_CAP = 5000;

// Set to false when rebuild is capped (callers should not trust partial index)
var _heapRebuildComplete = true;


// ==================== Transaction Lifecycle ====================

/**
 * Begin a transaction for a new batch.
 * Eagerly rebuilds the heap index from the live DOM so that every batch
 * starts with fresh COM refs (immune to cross-eval proxy staleness).
 *
 * @param {string} batchId - Unique batch identifier
 * @param {Object} [doc] - Optional document ref (avoids redundant app.activeDocument lookup)
 */
function heapBeginTxn(batchId, doc) {
    if (_heapTxn) {
        // Previous txn was not closed (crash recovery)
        // Discard silently - we can't trust the state
        _heapTxn = null;
    }
    // Reset warnings for new batch
    _heapWarnings = [];

    // REBUILD: eagerly refresh all COM refs from the live DOM.
    // $.global persists COM proxy objects across ExtendScript eval boundaries.
    // These proxies support property reads (.note, .typename) but throw PARM
    // on DOM mutations (.move(), .duplicate()). Rebuilding ensures every ref
    // is freshly obtained in the current eval context, safe for both reads
    // and mutations. This replaces the previous clear-and-lazy-resync approach.
    var rebuiltOk = false;
    try {
        var activeDoc = doc || app.activeDocument;
        if (activeDoc) {
            heapRebuildIndex(activeDoc);
            rebuiltOk = true;
        } else {
            $.global.mcpHeap.index = {};
        }
    } catch (e) {
        // No document open — start with empty index
        $.global.mcpHeap.index = {};
    }

    _heapTxn = {
        batchId: batchId || "unknown",
        added: {},       // uuid -> ref (items registered this txn)
        deleted: {},     // uuid -> ref (items tombstoned this txn)
        tomb: {},        // uuid -> true (fast tombstone lookup)
        // Skip redundant mid-batch resync if we already rebuilt at batch start
        resyncUsed: rebuiltOk
    };
}

/**
 * Commit the current transaction.
 * Merges txn.added into the global index, removes txn.deleted.
 * @returns {Object} Stats: {added: number, deleted: number}
 */
function heapCommitTxn() {
    if (!_heapTxn) return { added: 0, deleted: 0 };

    var stats = { added: 0, deleted: 0 };
    var heap = $.global.mcpHeap;

    // Persist additions (they're already in the index from heapRegister)
    for (var uuid in _heapTxn.added) {
        if (_heapTxn.added.hasOwnProperty(uuid)) {
            stats.added++;
        }
    }

    // Finalize deletions
    for (var uuid in _heapTxn.deleted) {
        if (_heapTxn.deleted.hasOwnProperty(uuid)) {
            delete heap.index[uuid];
            stats.deleted++;
        }
    }

    _heapTxn = null;
    return stats;
}

/**
 * Rollback the current transaction.
 * Removes txn.added from the global index, restores txn.deleted.
 * @returns {Object} Stats: {rolledBackAdds: number, rolledBackDeletes: number}
 */
function heapRollbackTxn() {
    if (!_heapTxn) return { rolledBackAdds: 0, rolledBackDeletes: 0 };

    var stats = { rolledBackAdds: 0, rolledBackDeletes: 0 };
    var heap = $.global.mcpHeap;

    // Remove items that were added during this transaction
    for (var uuid in _heapTxn.added) {
        if (_heapTxn.added.hasOwnProperty(uuid)) {
            delete heap.index[uuid];
            stats.rolledBackAdds++;
        }
    }

    // Restore items that were deleted during this transaction
    for (var uuid in _heapTxn.deleted) {
        if (_heapTxn.deleted.hasOwnProperty(uuid)) {
            heap.index[uuid] = _heapTxn.deleted[uuid];
            stats.rolledBackDeletes++;
        }
    }

    _heapTxn = null;
    return stats;
}


// ==================== Item Registration ====================

/**
 * Register a new item in the heap.
 * @param {string} uuid - Item's MCP ID
 * @param {Object} ref - PageItem reference
 */
function heapRegister(uuid, ref) {
    if (!uuid || !ref) return;
    var heap = $.global.mcpHeap;
    heap.index[uuid] = ref;

    if (_heapTxn) {
        _heapTxn.added[uuid] = ref;
        // If it was previously tombstoned in this txn, un-tombstone it
        delete _heapTxn.tomb[uuid];
        delete _heapTxn.deleted[uuid];
    }
}

/**
 * Stamp MCP ID on item.note and register in heap atomically.
 * All SOC creators MUST use this instead of raw note assignment.
 * Invariant H1: any op that stamps @mcp:id= MUST heapRegister before returning ok.
 * @param {Object} item - PageItem to stamp
 * @param {string} id - MCP ID to assign
 */
function stampMcpId(item, id) {
    item.note = "@mcp:id=" + id;
    heapRegister(id, item);
}

/**
 * Compatibility resolver: heap-first, scan-fallback with self-heal.
 * Tries heap resolution first (O(1)), falls back to linear scan if
 * the item was stamped without heapRegister (e.g. geo_boolean.jsx).
 * On fallback hit, self-heals by registering the item in the heap.
 * @param {string} id - MCP ID to resolve
 * @param {Object} doc - Document reference
 * @returns {Object|null} PageItem or null
 */
function resolveIdCompat(id, doc, opts) {
    opts = opts || {};

    // freshScan: bypass heap entirely — needed for mutation-critical handlers
    // (heap refs from $.global persist across eval contexts and can't be used
    //  for DOM mutations like .move() even though property reads still work)
    if (!opts.freshScan) {
        // 1. Try heap (fast path)
        var item = heapResolve(id, doc);
        if (item) return item;
    }

    // 2. Fallback (or fresh): linear scan + self-heal
    var allItems = doc.pageItems;
    for (var ri = 0; ri < allItems.length; ri++) {
        try {
            if (allItems[ri].note && allItems[ri].note.indexOf("@mcp:id=" + id) >= 0) {
                heapRegister(id, allItems[ri]);
                return allItems[ri];
            }
        } catch (e) { /* some items may not support .note */ }
    }
    return null;
}

/**
 * Mark an item for deletion (tombstone).
 * The item stays in the index until commit finalizes the removal.
 * @param {string} uuid - Item's MCP ID
 */
function heapTombstone(uuid) {
    if (!uuid) return;
    var heap = $.global.mcpHeap;
    var existing = heap.index[uuid];

    if (_heapTxn) {
        _heapTxn.tomb[uuid] = true;
        if (existing) {
            _heapTxn.deleted[uuid] = existing;
        }
    }

    // Remove from main index immediately so resolveById doesn't find it
    delete heap.index[uuid];
}

/**
 * Delete an item directly (bypasses tombstone for compatibility).
 * Records in txn.deleted for potential rollback.
 * @param {string} uuid - Item's MCP ID
 * @param {Object} ref - PageItem reference (for rollback)
 */
function heapDelete(uuid, ref) {
    if (!uuid) return;
    var heap = $.global.mcpHeap;

    if (_heapTxn && ref) {
        _heapTxn.deleted[uuid] = ref;
        _heapTxn.tomb[uuid] = true;
    }

    delete heap.index[uuid];
}


// ==================== Resolution ====================

/**
 * Resolve a UUID to a PageItem with identity verification.
 * Uses suspect-before-evict policy: COM errors mark entries suspect
 * (kept in index), only evict on second failure or identity mismatch.
 *
 * @param {string} uuid - MCP ID to resolve
 * @param {Object} doc - Active Illustrator document
 * @returns {Object|null} PageItem or null if not found
 */
function heapResolve(uuid, doc) {
    if (!uuid) return null;
    var heap = $.global.mcpHeap;

    // Check tombstone first
    if (_heapTxn && _heapTxn.tomb[uuid]) return null;

    // Try index lookup
    var ref = heap.index[uuid];
    if (ref) {
        // Identity verification: confirm the ref still has this ID
        try {
            if (ref.note) {
                var foundId = extractMcpId(ref.note);
                if (foundId === uuid) {
                    // Successful access — clear suspect flag if present
                    if (ref.__mcpSuspect) delete ref.__mcpSuspect;
                    return ref;
                }
            }
            // Identity mismatch (note exists but ID differs) — evict immediately
            _heapWarnings.push("heapResolve: evicted " + uuid + " (identity mismatch)");
            delete heap.index[uuid];
        } catch (e) {
            // COM error — could be transient or stale
            if (ref.__mcpSuspect) {
                // Second failure on a suspect entry — confirmed stale, evict
                _heapWarnings.push("heapResolve: evicted " + uuid + " (confirmed stale: " + e.message + ")");
                delete heap.index[uuid];
            } else {
                // First failure — mark suspect, do NOT evict
                ref.__mcpSuspect = true;
                _heapWarnings.push("heapResolve: marked " + uuid + " suspect (COM: " + e.message + ")");
                // Fall through to resync — resync rebuild will either
                // confirm or remove the entry
            }
        }
    }

    // One-time resync per batch
    if (doc && _heapTxn && !_heapTxn.resyncUsed) {
        heapRebuildIndex(doc);
        _heapTxn.resyncUsed = true;

        // Try again after rebuild
        ref = heap.index[uuid];
        if (ref && !(_heapTxn && _heapTxn.tomb[uuid])) {
            return ref;
        }
    }

    return null;
}

/**
 * Resolve multiple UUIDs at once.
 * @param {Object} doc - Active document
 * @param {Array<string>} uuids - Array of IDs to resolve
 * @returns {Array<Object>} Found items (preserves order, skips missing)
 */
function heapResolveMany(doc, uuids) {
    var items = [];
    for (var i = 0; i < uuids.length; i++) {
        var item = heapResolve(uuids[i], doc);
        if (item) items.push(item);
    }
    return items;
}


// ==================== Index Management ====================

/**
 * Full O(N) rebuild of the index from document.
 * Guarded: at most once per batch via txn.resyncUsed.
 * @param {Object} doc - Active document
 * @returns {number} Number of items indexed
 */
function heapRebuildIndex(doc) {
    if (!doc) return 0;

    var heap = $.global.mcpHeap;
    var newIndex = {};
    var count = 0;
    var maxDepth = 100;

    function scan(container, depth) {
        if (depth > maxDepth) return;
        if (!container || !container.pageItems) return;

        for (var i = 0; i < container.pageItems.length; i++) {
            if (count >= _HEAP_REBUILD_CAP) {
                _heapRebuildComplete = false;
                _heapWarnings.push("heapRebuildIndex: capped at " + _HEAP_REBUILD_CAP + " items — index incomplete");
                return;
            }
            var item = container.pageItems[i];
            try {
                if (item.note) {
                    var id = extractMcpId(item.note);
                    if (id) {
                        newIndex[id] = item;
                        count++;
                    }
                }
            } catch (e) { }
            if (item.typename === "GroupItem" || item.typename === "CompoundPathItem") {
                scan(item, depth + 1);
            }
        }
    }

    _heapRebuildComplete = true;  // reset before scan

    for (var i = 0; i < doc.layers.length; i++) {
        if (!_heapRebuildComplete) break;  // cap hit during previous layer scan
        scan(doc.layers[i], 0);
    }

    // Preserve tombstones from current transaction
    if (_heapTxn) {
        for (var uuid in _heapTxn.tomb) {
            if (_heapTxn.tomb.hasOwnProperty(uuid)) {
                delete newIndex[uuid];
            }
        }
    }

    heap.index = newIndex;
    heap.docName = doc.name;
    return count;
}

/**
 * Invalidate the entire index (force rebuild on next access).
 * Use this when you know the document has changed externally.
 */
function heapInvalidate() {
    $.global.mcpHeap = { index: {}, docName: null };
    _heapTxn = null;
}

/**
 * Get heap diagnostics for batch reporting.
 * @returns {Object} Diagnostic data
 */
function heapDiagnostics() {
    var heap = $.global.mcpHeap;
    var indexSize = 0;
    for (var k in heap.index) {
        if (heap.index.hasOwnProperty(k)) indexSize++;
    }

    return {
        indexSize: indexSize,
        docName: heap.docName || null,
        rebuildComplete: _heapRebuildComplete,
        hasTxn: _heapTxn !== null,
        txnBatchId: _heapTxn ? _heapTxn.batchId : null,
        txnAdded: _heapTxn ? _countKeys(_heapTxn.added) : 0,
        txnDeleted: _heapTxn ? _countKeys(_heapTxn.deleted) : 0,
        txnResyncUsed: _heapTxn ? _heapTxn.resyncUsed : false,
        warnings: _heapWarnings.slice()  // copy to prevent mutation
    };
}

/**
 * Count keys in an object (ES3 compatible).
 * @param {Object} obj
 * @returns {number}
 */
function _countKeys(obj) {
    var n = 0;
    for (var k in obj) {
        if (obj.hasOwnProperty(k)) n++;
    }
    return n;
}
