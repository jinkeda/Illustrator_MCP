/**
 * ops_journal.jsx - Operation Journal for Recomputability (P6)
 * Part of Illustrator MCP SOC Framework
 *
 * Provides persistent journaling of batch operations for replay.
 * Primary storage: $.global.mcpJournal (session-scoped)
 * Fallback: ~/mcp_journal_<docname>_<WxH>.json (survives engine reset)
 *
 * WARNING: $.global is volatile — Illustrator can reset the engine
 * unpredictably (script errors, memory pressure). The temp-file
 * fallback is critical for meaningful replay.
 *
 * @requires ops_core (for executeOpBatch on replay)
 * @version 1.0.0
 */

// ==================== Journal Storage ====================

/**
 * Get the temp file path for a document's journal.
 * @param {string} docName - Document name
 * @returns {File}
 */
function getJournalFile(docName, doc) {
    var safeName = docName.replace(/[^a-zA-Z0-9_-]/g, "_");
    var fingerprint = "";
    if (doc) {
        try {
            var ab = doc.artboards[0].artboardRect;
            var w = Math.round(ab[2] - ab[0]);
            var h = Math.round(ab[1] - ab[3]);
            fingerprint = "_" + w + "x" + h;
        } catch (e) { }
    }
    return new File(Folder.temp + "/mcp_journal_" + safeName + fingerprint + ".json");
}

/**
 * Append a batch entry to the journal.
 * Writes to both $.global and file fallback.
 *
 * @param {Object} entry - Journal entry
 * @param {string} entry.batchId - UUID of the batch
 * @param {number} entry.timestamp - Execution timestamp
 * @param {Array}  entry.ops - Array of op definitions (task, params, targets)
 * @param {Object} entry.options - Batch options used
 * @param {Object} entry.report - Execution report {ok, stats}
 * @param {string} docName - Document name for file path
 */
function journalAppend(entry, docName, doc) {
    // Primary: $.global
    if (!$.global.mcpJournal) {
        $.global.mcpJournal = {};
    }
    if (!$.global.mcpJournal[docName]) {
        $.global.mcpJournal[docName] = [];
    }
    $.global.mcpJournal[docName].push(entry);

    // Fallback: temp file
    try {
        var f = getJournalFile(docName, doc);
        var existing = [];
        if (f.exists) {
            f.open("r");
            var content = f.read();
            f.close();
            if (content && content.length > 0) {
                existing = eval("(" + content + ")"); // ExtendScript JSON parse
            }
        }
        existing.push(entry);

        f.open("w");
        f.write(jsonStringify(existing));
        f.close();
    } catch (e) {
        // File write failed — journal is in-memory only for this session
    }
}

/**
 * Get the full journal for a document.
 * Tries $.global first, falls back to file.
 *
 * @param {string} docName - Document name
 * @returns {Array} Journal entries
 */
function journalGet(docName, doc) {
    // Try $.global first
    if ($.global.mcpJournal && $.global.mcpJournal[docName]) {
        return $.global.mcpJournal[docName];
    }

    // Fallback: load from file
    try {
        var f = getJournalFile(docName, doc);
        if (f.exists) {
            f.open("r");
            var content = f.read();
            f.close();
            if (content && content.length > 0) {
                var entries = eval("(" + content + ")");
                // Restore to $.global for performance
                if (!$.global.mcpJournal) $.global.mcpJournal = {};
                $.global.mcpJournal[docName] = entries;
                return entries;
            }
        }
    } catch (e) { }

    return [];
}

/**
 * Clear the journal for a document.
 * Removes from both $.global and file.
 *
 * @param {string} docName - Document name
 */
function journalClear(docName, doc) {
    if ($.global.mcpJournal && $.global.mcpJournal[docName]) {
        delete $.global.mcpJournal[docName];
    }

    try {
        var f = getJournalFile(docName, doc);
        if (f.exists) {
            f.remove();
        }
    } catch (e) { }
}

/**
 * Get journal summary without full op data.
 * @param {string} docName
 * @returns {Object} {entries, totalOps, firstTimestamp, lastTimestamp}
 */
function journalSummary(docName) {
    var entries = journalGet(docName);
    if (entries.length === 0) {
        return { entries: 0, totalOps: 0, firstTimestamp: null, lastTimestamp: null };
    }

    var totalOps = 0;
    for (var i = 0; i < entries.length; i++) {
        totalOps += entries[i].ops ? entries[i].ops.length : 0;
    }

    return {
        entries: entries.length,
        totalOps: totalOps,
        firstTimestamp: entries[0].timestamp,
        lastTimestamp: entries[entries.length - 1].timestamp
    };
}

// ==================== Journal Compaction (Issue #4) ====================

/**
 * Compact the journal by keeping only the last N entries or limiting file size.
 * Call periodically or when file size exceeds threshold.
 *
 * @param {string} docName - Document name
 * @param {Document} doc - Document reference (for file path)
 * @param {Object} opts
 * @param {number} opts.maxEntries - Keep only last N entries (default 50)
 * @param {number} opts.maxBytes - Trim if file exceeds this size (default 102400 = 100KB)
 * @returns {Object} {before, after, pruned, fileBytes}
 */
function journalCompact(docName, doc, opts) {
    opts = opts || {};
    var maxEntries = opts.maxEntries !== undefined ? opts.maxEntries : 50;
    var maxBytes = opts.maxBytes !== undefined ? opts.maxBytes : 102400;

    var entries = journalGet(docName, doc);
    var before = entries.length;

    if (before === 0) {
        return { before: 0, after: 0, pruned: 0, fileBytes: 0 };
    }

    // Compact: keep last maxEntries
    var compacted = entries;
    if (maxEntries > 0 && compacted.length > maxEntries) {
        compacted = compacted.slice(compacted.length - maxEntries);
    }

    // Write back compacted journal
    if ($.global.mcpJournal) {
        $.global.mcpJournal[docName] = compacted;
    }

    var fileBytes = 0;
    try {
        var f = getJournalFile(docName, doc);
        var serialized = jsonStringify(compacted);

        // Further trim if exceeds maxBytes
        while (serialized.length > maxBytes && compacted.length > 1) {
            compacted = compacted.slice(1);
            serialized = jsonStringify(compacted);
        }

        if ($.global.mcpJournal) {
            $.global.mcpJournal[docName] = compacted;
        }

        f.open("w");
        f.write(serialized);
        f.close();
        fileBytes = serialized.length;
    } catch (e) { }

    return {
        before: before,
        after: compacted.length,
        pruned: before - compacted.length,
        fileBytes: fileBytes
    };
}

// ==================== Replay Engine ====================

/**
 * Replay journal entries onto a document.
 *
 * @param {Document} doc - Target document
 * @param {Array} entries - Journal entries to replay
 * @param {Object} replayOptions
 * @param {string} replayOptions.onError - "strict" (default) | "skip" | "rollback"
 * @param {Function} replayOptions.clock - Injectable clock for ctx
 * @param {string} replayOptions.fromBatchId - Skip entries up to and including this batchId (incremental replay)
 * @returns {Object} Replay report
 *
 * @limitation rollback mode restores snapshot properties and deletes items
 *   created during replay, but CANNOT recreate items that were deleted
 *   during replay, nor undo layer moves. For true transactional rollback,
 *   use app.undo() externally.
 */
function journalReplay(doc, entries, replayOptions) {
    replayOptions = replayOptions || {};
    var onError = replayOptions.onError || "strict";
    var clock = replayOptions.clock || function () { return new Date().getTime(); };

    var totalOps = 0;
    var totalPassed = 0;
    var totalFailed = 0;
    var replayedBatches = 0;
    var failedAt = null;
    var preReplaySnapshot = null;
    var preReplayIds = {};  // Track existing MCP IDs for rollback cleanup
    var skippedBatches = 0;

    // Issue #5: Incremental replay — skip entries up to fromBatchId
    var fromBatchId = replayOptions.fromBatchId || null;
    var skipMode = fromBatchId !== null;

    // If rollback mode, take snapshot before replay and record existing IDs
    if (onError === "rollback" && typeof captureSnapshot === "function") {
        preReplaySnapshot = captureSnapshot(doc, { geometry: true, style: true });
        // Record all MCP IDs that exist before replay
        for (var pi = 0; pi < preReplaySnapshot.items.length; pi++) {
            preReplayIds[preReplaySnapshot.items[pi].id] = true;
        }
    }

    for (var b = 0; b < entries.length; b++) {
        var entry = entries[b];

        // Skip entries until we pass fromBatchId
        if (skipMode) {
            if (entry.batchId === fromBatchId) {
                skipMode = false;  // Found the watermark, start replaying AFTER this
            }
            skippedBatches++;
            continue;
        }
        var ops = entry.ops || [];
        totalOps += ops.length;

        // Strip journal flag to prevent recursive journaling during replay
        var batchOptions = {};
        if (entry.options) {
            for (var key in entry.options) {
                if (key !== "journal" && key !== "recompute") {
                    batchOptions[key] = entry.options[key];
                }
            }
        }
        batchOptions.clock = clock;

        try {
            var result = executeOpBatch(ops, batchOptions);

            if (result.ok) {
                totalPassed += result.stats.passed;
                replayedBatches++;
            } else {
                totalFailed += result.stats.failed;
                totalPassed += result.stats.passed;

                if (onError === "strict") {
                    failedAt = {
                        batchIndex: b,
                        batchId: entry.batchId || null,
                        opsInBatch: ops.length,
                        batchFailed: result.stats.failed
                    };
                    break;
                } else if (onError === "rollback") {
                    // Restore pre-replay state
                    if (preReplaySnapshot && typeof restoreSnapshot === "function") {
                        restoreSnapshot(doc, preReplaySnapshot, { geometry: true, style: true });
                    }
                    // Delete items created during replay (not in pre-replay snapshot)
                    for (var rl = 0; rl < doc.layers.length; rl++) {
                        for (var ri = doc.layers[rl].pageItems.length - 1; ri >= 0; ri--) {
                            var rNote = doc.layers[rl].pageItems[ri].note || '';
                            var rMatch = rNote.match(/@mcp:id=([^\s@]+)/);
                            if (rMatch && !preReplayIds[rMatch[1]]) {
                                try { doc.layers[rl].pageItems[ri].remove(); } catch (re) { }
                            }
                        }
                    }
                    failedAt = {
                        batchIndex: b,
                        batchId: entry.batchId || null,
                        rolledBack: true
                    };
                    break;
                }
                // "skip" mode: continue to next batch
                replayedBatches++;
            }
        } catch (e) {
            totalFailed++;
            if (onError === "strict") {
                failedAt = {
                    batchIndex: b,
                    batchId: entry.batchId || null,
                    error: e.message
                };
                break;
            } else if (onError === "rollback") {
                if (preReplaySnapshot && typeof restoreSnapshot === "function") {
                    restoreSnapshot(doc, preReplaySnapshot, { geometry: true, style: true });
                }
                // Delete items created during replay (not in pre-replay snapshot)
                for (var rl2 = 0; rl2 < doc.layers.length; rl2++) {
                    for (var ri2 = doc.layers[rl2].pageItems.length - 1; ri2 >= 0; ri2--) {
                        var rNote2 = doc.layers[rl2].pageItems[ri2].note || '';
                        var rMatch2 = rNote2.match(/@mcp:id=([^\s@]+)/);
                        if (rMatch2 && !preReplayIds[rMatch2[1]]) {
                            try { doc.layers[rl2].pageItems[ri2].remove(); } catch (re2) { }
                        }
                    }
                }
                failedAt = {
                    batchIndex: b,
                    batchId: entry.batchId || null,
                    error: e.message,
                    rolledBack: true
                };
                break;
            }
            // "skip": continue
            replayedBatches++;
        }
    }

    return {
        ok: failedAt === null,
        data: {
            totalBatches: entries.length,
            replayedBatches: replayedBatches,
            skippedBatches: skippedBatches,
            totalOps: totalOps,
            passed: totalPassed,
            failed: totalFailed,
            onError: onError,
            failedAt: failedAt
        }
    };
}

// ==================== JSON Stringify (ExtendScript) ====================

/**
 * Minimal JSON.stringify for ExtendScript (no native JSON).
 * Handles strings, numbers, booleans, null, arrays, and plain objects.
 */
function jsonStringify(val) {
    if (val === null || val === undefined) return "null";
    if (typeof val === "boolean") return val ? "true" : "false";
    if (typeof val === "number") return isFinite(val) ? String(val) : "null";
    if (typeof val === "string") {
        return '"' + val.replace(/\\/g, "\\\\").replace(/"/g, '\\"')
            .replace(/\n/g, "\\n").replace(/\r/g, "\\r")
            .replace(/\t/g, "\\t") + '"';
    }
    if (val instanceof Array) {
        var parts = [];
        for (var i = 0; i < val.length; i++) {
            parts.push(jsonStringify(val[i]));
        }
        return "[" + parts.join(",") + "]";
    }
    if (typeof val === "object") {
        var parts = [];
        for (var k in val) {
            if (val.hasOwnProperty(k)) {
                parts.push(jsonStringify(k) + ":" + jsonStringify(val[k]));
            }
        }
        return "{" + parts.join(",") + "}";
    }
    return "null";
}
