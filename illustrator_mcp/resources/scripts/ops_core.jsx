/**
 * ops_core.jsx - SOC Operation Batch Executor
 * Part of Illustrator MCP Standard Library
 * 
 * Provides batch operation execution with:
 * - Stable ID-based targeting
 * - Op validation before execution
 * - Fresh target resolution for every operation
 * - Strict/continue error modes
 * - Context injection for pure ops
 * 
 * @requires contracts (for ErrorCodes, makeError, validateOpParams)
 * @requires mcp_id (for extractMcpId)
 * @requires geometry (for shape creation helpers)
 * @version 1.1.0
 */

// ==================== Dependency Guard ====================

if (typeof makeError !== "function" || typeof ErrorCodes === "undefined") {
    throw new Error("ops_core.jsx requires contracts.jsx (makeError=" + typeof makeError + ", ErrorCodes=" + typeof ErrorCodes + ")");
}
if (typeof extractMcpId !== "function") {
    throw new Error("ops_core.jsx requires mcp_id.jsx (extractMcpId=" + typeof extractMcpId + ")");
}

// ==================== Op Schema Version ====================

var OP_SCHEMA_VERSION = "1.0.0";

// ==================== UUID Generation ====================

/**
 * Generate a RFC 4122 v4 UUID for stable item references
 * @returns {string} UUID like "mcp_xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx"
 */
function generateUUID() {
    var s = [];
    var hexDigits = "0123456789abcdef";
    for (var i = 0; i < 36; i++) {
        if (i === 8 || i === 13 || i === 18 || i === 23) {
            s[i] = "-";
        } else if (i === 14) {
            s[i] = "4"; // Version 4
        } else if (i === 19) {
            s[i] = hexDigits[(Math.floor(Math.random() * 4) + 8)]; // 8, 9, a, or b
        } else {
            s[i] = hexDigits[Math.floor(Math.random() * 16)];
        }
    }
    return "mcp_" + s.join("");
}

// ==================== Op Handler Registry ====================

var OP_HANDLERS = {};

/**
 * Register an operation handler
 * @param {string} taskName - Op task name (e.g., "element_create")
 * @param {Function} handler - Handler function: (params, targets, ctx) => result
 */
function registerOpHandler(taskName, handler) {
    OP_HANDLERS[taskName] = handler;
}

// ==================== Op Validation ====================

/**
 * Validate a single operation before execution
 * @param {Object} op - Operation: {task, targets?, params?, comment?}
 * @param {boolean} strict - If true, reject unknown keys
 * @returns {Object} {ok: bool, errors: []}
 */
function validateOp(op, strict) {
    var errors = [];

    // Required: task
    if (!op.task || typeof op.task !== "string") {
        errors.push(makeError(
            ErrorCodes.V_INVALID_PAYLOAD,
            "Op missing 'task' string",
            "validate"
        ));
        return { ok: false, errors: errors };
    }

    // Handler must exist
    if (!OP_HANDLERS[op.task]) {
        errors.push(makeError(
            ErrorCodes.V_INVALID_PAYLOAD,
            "Unknown op task: " + op.task,
            "validate"
        ));
        return { ok: false, errors: errors };
    }

    // Params must be object if present
    if (op.params && typeof op.params !== "object") {
        errors.push(makeError(
            ErrorCodes.V_INVALID_PARAM_TYPE,
            "Op 'params' must be an object",
            "validate"
        ));
    }

    // Schema-based param validation (if op_schemas loaded)
    if (typeof validateOpParams === "function") {
        var paramValidation = validateOpParams(op.task, op.params);
        if (!paramValidation.ok) {
            for (var e = 0; e < paramValidation.errors.length; e++) {
                errors.push(paramValidation.errors[e]);
            }
        }
    }

    // Targets validation
    if (op.targets) {
        var validationTarget = op.targets.target || op.targets;
        var targetType = validationTarget.type;
        var allowedTypes = ["id", "query", "selection", "layer", "all", "spatial", "grid", "compound", "handle"];
        var found = false;
        for (var i = 0; i < allowedTypes.length; i++) {
            if (allowedTypes[i] === targetType) { found = true; break; }
        }
        if (!found) {
            errors.push(makeError(
                ErrorCodes.V_UNKNOWN_TARGET_TYPE,
                "Unknown target type: " + targetType,
                "validate"
            ));
        }
    }

    // Strict mode: reject unknown keys
    if (strict) {
        var allowedKeys = ["task", "targets", "params", "comment", "id", "when", "unless"];
        for (var key in op) {
            if (op.hasOwnProperty(key)) {
                var isAllowed = false;
                for (var j = 0; j < allowedKeys.length; j++) {
                    if (allowedKeys[j] === key) { isAllowed = true; break; }
                }
                if (!isAllowed) {
                    errors.push(makeError(
                        ErrorCodes.V_SCHEMA_MISMATCH,
                        "Unknown op key: " + key,
                        "validate"
                    ));
                }
            }
        }
    }

    return { ok: errors.length === 0, errors: errors };
}

// ==================== ID-Based Target Resolution ====================
// Delegates to heap.jsx for transactional, identity-verified resolution.
// The heap index ($.global.mcpHeap) persists across batches/chunks.
// Transaction lifecycle (begin/commit/rollback) is managed in executeOpBatch.

/**
 * Extended target resolution with ID support
 * @param {Document} doc - Active document
 * @param {Object} targets - Target selector
 * @param {Object} ctx - Batch context
 * @returns {Array<PageItem>} Resolved items
 */
function resolveTargets(doc, targets, ctx) {
    if (!targets) return [];

    // P1: Deprecation warning for selection targeting (removal at v2.0)
    if (targets.type === "selection") {
        if (!ctx.diagnostics.selectionWarnings) ctx.diagnostics.selectionWarnings = 0;
        ctx.diagnostics.selectionWarnings++;
        if (!ctx._selectionWarned) {
            ctx._selectionWarned = true;
            // Warning is surfaced in batch report via diagnostics
        }
    }

    // Never cache PageItem references or selector outcomes. Every operation
    // sees the document produced by all preceding operations in this batch.
    ctx.diagnostics.resolutions++;
    // Carry resolution facts back to the executor so an op can report the
    // targets it was asked for but did not find.
    var report = { unresolvedIds: [] };
    var resolved = collectTargets(doc, targets, {
        startingSelection: ctx.startingSelection,
        report: report
    });
    ctx._lastResolution = report;
    return resolved;
}

// ==================== Handler Result Normalizer ====================

/**
 * Normalize handler return value to a consistent shape.
 * Handlers return varying shapes; this centralizes normalization so
 * counting, slimming, and opSummary all consume stable output.
 *
 * Input shapes handled:
 *   - {ok, data: {modified: N}}           (style ops)
 *   - {ok, data: {ids: [...]}}            (element create)
 *   - {ok, data: {createdIds: [...]}}     (batch create)
 *   - {ok, id: "..."}                     (single create)
 *   - raw object / null / undefined       (legacy)
 *
 * Output shape:
 *   {ok, data: {createdIds?, modified?, ...}, warnings, error, id, recovery?}
 *
 * @param {string} task - Op task name (for diagnostics)
 * @param {*} raw - Handler return value
 * @returns {Object} Normalized result
 */
function normalizeHandlerResult(task, raw) {
    // Null / undefined / non-object → treat as success with no data
    if (!raw || typeof raw !== "object") {
        return { ok: true, data: raw || null, warnings: [], error: null, id: null };
    }

    var norm = {
        ok: raw.ok !== false,
        data: {},
        warnings: raw.warnings || [],
        error: raw.error || null,
        id: raw.id || null,
        // Recovery is an outcome in its own right. Keeping it only inside a
        // handler-specific data object made the canonical boundary report
        // `not_requested` while withTransaction had already disclosed
        // restored/partial/failed/not_needed.
        // Top-level is authoritative. The data location predates the
        // canonical field, but remains supported and must be promoted before
        // response budgeting can omit bulk operation data.
        recovery: raw.recovery ||
            (raw.data && raw.data.recovery ? raw.data.recovery : null) ||
            (raw.error && raw.error.details && raw.error.details.recovery ?
                raw.error.details.recovery : null)
    };

    // Normalize data shape — extract known fields
    var d = raw.data || raw;
    if (typeof d === "object" && d !== null) {
        // Modified count (style, text ops)
        if (typeof d.modified === "number") norm.data.modified = d.modified;
        // Created IDs (element create ops)
        if (d.ids) norm.data.createdIds = d.ids;
        if (d.createdIds) norm.data.createdIds = d.createdIds;
        // Preserve all other data fields as-is
        for (var k in d) {
            if (d.hasOwnProperty(k) && !norm.data.hasOwnProperty(k)
                && k !== "ok" && k !== "warnings" && k !== "error" && k !== "id") {
                norm.data[k] = d[k];
            }
        }
    }

    return norm;
}

// ==================== Rollback Helper (A2) ====================

/**
 * Perform batch rollback: delete created items, restore snapshot or undo.
 *
 * UNREACHABLE SINCE T04 — retained only until the recovery model is rebuilt.
 * `executeOpBatch` rejects options.rollback/snapshot/recompute and the
 * compound handler rejects params.atomic, so nothing reaches this function.
 * Do not re-enable it as-is: the snapshot branch cannot restore deleted
 * objects, path geometry, text, grouping or z-order (see snapshot.jsx), and
 * the `undoCount` branch fires one app-level undo per *successful op*, which
 * is wrong whenever a handler performs several DOM mutations or the failing
 * handler already mutated. Slated for removal in T30; a verifiable inverse
 * for an allowlisted subset is T28.
 *
 * @param {Document} doc - Active document
 * @param {Object|null} preSnapshot - Pre-execution snapshot (or null)
 * @param {Array} createdIds - MCP IDs of items created during batch
 * @param {number} undoCount - Number of mutating ops to undo (fallback)
 * @param {boolean} useSnapshot - Whether snapshot-based restore is enabled
 * @param {Array|null} trace - Trace log array (or null)
 * @returns {number} Number of items rolled back
 */
function rollbackBatch(doc, preSnapshot, createdIds, undoCount, useSnapshot, trace) {
    var rolledBack = 0;

    if (useSnapshot && preSnapshot && typeof restoreSnapshot === "function") {
        if (trace) trace.push("[ROLLBACK] Restoring from snapshot");

        // Delete created items first (they weren't in the snapshot)
        var createdDeleted = 0;
        if (createdIds.length > 0) {
            var cidSet = {};
            for (var ci = 0; ci < createdIds.length; ci++) cidSet[createdIds[ci]] = true;
            for (var lx = 0; lx < doc.layers.length; lx++) {
                for (var px = doc.layers[lx].pageItems.length - 1; px >= 0; px--) {
                    var pi = doc.layers[lx].pageItems[px];
                    // T02: canonical exact parser — /[^\s]+/ ran past the tag
                    // boundary when two tags were written without a separator.
                    var pmId = extractMcpId(pi.note || "");
                    if (pmId && cidSet[pmId]) {
                        try { pi.remove(); createdDeleted++; } catch (e) {
                            if (trace) trace.push("[ROLLBACK] Delete failed: " + e.message);
                        }
                    }
                }
            }
            heapRollbackTxn();
        }

        // Restore pre-existing items from snapshot
        try {
            var rr = restoreSnapshot(doc, preSnapshot, { geometry: true, style: true });
            rolledBack = rr.restored + createdDeleted;
            if (trace) trace.push("[ROLLBACK] Restored " + rr.restored + ", deleted " + createdDeleted);
        } catch (e) {
            if (trace) trace.push("[ROLLBACK ERROR] " + e.message);
        }
    } else if (undoCount > 0) {
        // Fallback to undo-based rollback
        if (trace) trace.push("[ROLLBACK] Undoing " + undoCount + " ops");
        for (var u = 0; u < undoCount; u++) {
            try { app.executeMenuCommand("undo"); rolledBack++; } catch (e) { }
        }
    }

    return rolledBack;
}

// ==================== Transaction Helper ====================

/**
 * Run a function, attempting a best-effort property restore on failure.
 *
 * NOT A TRANSACTION (T04).  This previously returned `rolledBack: true` on
 * any exception, without inspecting the restore result — so a caller was told
 * the document had been rolled back when restoreSnapshot had partially or
 * wholly failed.  captureSnapshot records position, size, opacity, visibility,
 * lock and fill/stroke for @mcp:id-tagged items only; it cannot recreate
 * deleted objects or restore path geometry, text, grouping, or z-order.
 *
 * The failure result now reports what recovery actually achieved:
 *   recovery.status  "restored"  — every captured item was restored
 *                    "partial"   — some items could not be restored
 *                    "failed"    — restore threw
 *                    "none"      — nothing was captured to restore
 *   recovery.scope   always "captured properties of MCP-tagged items"
 *
 * `rolledBack` is retained for compatibility and is true ONLY for
 * status === "restored".  It still does not mean the document is back to its
 * prior state — only that the captured subset was reapplied.  Prefer an
 * explicit checkpoint for anything you actually need to undo.
 *
 * @param {Document} doc - Explicit document reference (multi-doc safe)
 * @param {Function} fn - Mutation function: (doc) => result
 * @param {Object} [opts] - Options: {mcpOnly: boolean} — default true (fast)
 * @returns {Object} {ok, result?, error?, rolledBack, recovery}
 */
function withTransaction(doc, fn, opts) {
    opts = opts || {};
    var snap = captureSnapshot(doc, { mcpOnly: opts.mcpOnly !== false });
    try {
        var result = fn(doc);
        return {
            ok: true,
            result: result,
            rolledBack: false,
            recovery: { status: "not_needed", scope: SNAPSHOT_RECOVERY_SCOPE }
        };
    } catch (e) {
        var captured = (snap && snap.items) ? snap.items.length : 0;
        var recovery = {
            status: "none",
            scope: SNAPSHOT_RECOVERY_SCOPE,
            captured: captured,
            restored: 0,
            failed: 0
        };

        if (captured > 0) {
            try {
                var rr = restoreSnapshot(doc, snap, { geometry: true, style: true });
                recovery.restored = rr.restored || 0;
                recovery.failed = rr.failed || 0;
                if (recovery.failed > 0) {
                    recovery.status = "partial";
                } else if (recovery.restored === captured) {
                    recovery.status = "restored";
                } else {
                    recovery.status = "partial";
                }
            } catch (restoreErr) {
                recovery.status = "failed";
                recovery.error = restoreErr.message;
            }
        }

        return {
            ok: false,
            error: makeError(ErrorCodes.R_APPLY_FAILED, e.message, "apply").error,
            rolledBack: recovery.status === "restored",
            recovery: recovery
        };
    }
}

// ==================== Guard Evaluation (C2) ====================

/**
 * Read a property from a PageItem using the bounds-derived allowlist.
 * @param {PageItem} item
 * @param {string} property
 * @returns {Object} Success: {ok: true, value: *}. Failure: {ok: false, error: {code: string, message: string, stage: string}}.
 */
function readGuardProperty(item, property) {
    // Check that item has geometricBounds (PageItem-like)
    if (typeof item.geometricBounds === "undefined") {
        return makeError(ErrorCodes.G_UNKNOWN_PROPERTY,
            "Guard target has no geometricBounds (not a PageItem)", "guard");
    }
    var b = item.geometricBounds; // [left, top, right, bottom]
    switch (property) {
        case "width": return { ok: true, value: b[2] - b[0] };
        case "height": return { ok: true, value: b[1] - b[3] };
        case "left": return { ok: true, value: b[0] };
        case "top": return { ok: true, value: b[1] };
        case "opacity": return { ok: true, value: item.opacity };
        case "name": return { ok: true, value: item.name };
        case "locked": return { ok: true, value: item.locked };
        case "typename": return { ok: true, value: item.typename };
        default:
            return makeError(ErrorCodes.G_UNKNOWN_PROPERTY,
                "Unknown guard property '" + property + "'. Allowed: width, height, left, top, opacity, name, locked, typename",
                "guard");
    }
}

/**
 * Evaluate a single comparator against a value.
 * @param {*} value - The actual property value
 * @param {string} comparator - eq/neq/gt/gte/lt/lte/contains/matches
 * @param {*} expected - The expected value from the guard
 * @returns {{ok: boolean, result: boolean, error: Object}}
 */
function evalComparator(value, comparator, expected) {
    // Numeric comparators require numeric value
    var numericOps = { gt: true, gte: true, lt: true, lte: true };
    if (numericOps[comparator]) {
        if (typeof value !== "number" || typeof expected !== "number") {
            return makeError(ErrorCodes.G_INVALID_COMPARATOR,
                "Comparator '" + comparator + "' requires numeric values, got " + typeof value + " vs " + typeof expected,
                "guard");
        }
    }
    switch (comparator) {
        case "eq": return { ok: true, result: value === expected };
        case "neq": return { ok: true, result: value !== expected };
        case "gt": return { ok: true, result: value > expected };
        case "gte": return { ok: true, result: value >= expected };
        case "lt": return { ok: true, result: value < expected };
        case "lte": return { ok: true, result: value <= expected };
        case "contains":
            if (typeof value !== "string") {
                return makeError(ErrorCodes.G_INVALID_COMPARATOR,
                    "'contains' requires string value, got " + typeof value, "guard");
            }
            return { ok: true, result: value.indexOf(String(expected)) !== -1 };
        case "matches":
            if (typeof value !== "string") {
                return makeError(ErrorCodes.G_INVALID_COMPARATOR,
                    "'matches' requires string value, got " + typeof value, "guard");
            }
            try {
                var rx = new RegExp(String(expected));
                return { ok: true, result: rx.test(value) };
            } catch (e) {
                return makeError(ErrorCodes.G_INVALID_COMPARATOR,
                    "Invalid regex pattern: " + expected, "guard");
            }
        default:
            return makeError(ErrorCodes.G_INVALID_COMPARATOR,
                "Unknown comparator '" + comparator + "'. Allowed: eq, neq, gt, gte, lt, lte, contains, matches",
                "guard");
    }
}

/**
 * Validate guard structure and extract comparator + expected value.
 * @param {Object} guard - The when/unless guard object
 * @returns {{ok: boolean, property: string, comparator: string, expected: *, error: Object}}
 */
function validateGuard(guard) {
    if (!guard || typeof guard !== "object") {
        return makeError(ErrorCodes.G_MALFORMED, "Guard must be an object", "guard");
    }
    if (!guard.property || typeof guard.property !== "string") {
        return makeError(ErrorCodes.G_MALFORMED, "Guard missing 'property' string", "guard");
    }
    // Find the comparator key (the key that isn't 'property')
    var COMPARATORS = { eq: 1, neq: 1, gt: 1, gte: 1, lt: 1, lte: 1, contains: 1, matches: 1 };
    var comparator = null;
    var expected = undefined;
    for (var k in guard) {
        if (guard.hasOwnProperty(k) && k !== "property" && COMPARATORS[k]) {
            comparator = k;
            expected = guard[k];
            break;
        }
    }
    if (!comparator) {
        return makeError(ErrorCodes.G_MALFORMED,
            "Guard missing comparator. Use one of: eq, neq, gt, gte, lt, lte, contains, matches",
            "guard");
    }
    return { ok: true, property: guard.property, comparator: comparator, expected: expected };
}

/**
 * Filter targets by a when/unless guard. Per-target evaluation.
 * @param {Array} targets - Resolved PageItems
 * @param {Object} guard - The guard predicate
 * @param {boolean} isUnless - true for unless (invert), false for when
 * @returns {{ok: boolean, targets: Array, error: Object}}
 */
function filterByGuard(targets, guard, isUnless) {
    var parsed = validateGuard(guard);
    if (!parsed.ok) return parsed;

    var filtered = [];
    for (var i = 0; i < targets.length; i++) {
        var propResult = readGuardProperty(targets[i], parsed.property);
        if (!propResult.ok) return propResult;  // Hard error for non-PageItem or unknown prop

        var cmpResult = evalComparator(propResult.value, parsed.comparator, parsed.expected);
        if (!cmpResult.ok) return cmpResult;  // Hard error for type mismatch

        // when: keep if true; unless: keep if false
        var keep = isUnless ? !cmpResult.result : cmpResult.result;
        if (keep) filtered.push(targets[i]);
    }
    return { ok: true, targets: filtered };
}

// ==================== Sub-Op Execution (C1) ====================

// ==================== Op Classification (3-tier) ====================
// "doc"     = participates in Illustrator undo stack → counted for rollback
// "session" = changes app state (not geometry) → logged, not undo-counted
// default   = "readonly" (assert_*, measure_*, snapshot_*, hash_*)
var OP_CLASS = {
    "element_create": "doc", "element_create_multi": "doc",
    "element_create_multi_by_ref": "doc", "element_create_batch": "doc",
    "element_modify": "doc", "element_delete": "doc", "element_replace": "doc",
    "style_set_fill": "doc", "style_set_stroke": "doc", "style_set_opacity": "doc",
    "style_remove_fill": "doc", "style_remove_stroke": "doc",
    "style_clone": "doc", "style_set_gradient": "doc",
    "group_create": "doc", "group_ungroup": "doc", "clip_create": "doc",
    "zorder_front": "doc", "zorder_back": "doc",
    "zorder_forward": "doc", "zorder_backward": "doc",
    "text_create": "doc", "text_set_content": "doc", "text_set_style": "doc",
    "align_horizontal": "doc", "align_vertical": "doc",
    "distribute_horizontal": "doc", "distribute_vertical": "doc",
    "compound": "doc",
    "layer_create": "doc", "layer_delete": "doc", "layer_reorder": "doc",
    "layer_lock": "doc", "layer_visible": "doc",
    "layer_activate": "session"
};

// Mutations whose meaning requires at least one current target. Creation and
// layer/session operations intentionally stay outside this map.
// Operations whose subjects come from a TARGET SELECTOR. For these, resolving
// nothing means the request cannot be carried out, so an empty match is an
// error rather than a zero-change success.
//
// An operation must only be listed here if its handler actually reads the
// `targets` argument. clip_create does NOT: its schema and handler take
// `mask` and `contents` as params (both MCP IDs) and ignore `targets`
// entirely. Listing it made the executor reject every call with
// V014 "resolved no targets" before the handler ever ran, so clip_create was
// unreachable through execute_task as documented. Its own handler already
// validates and resolves its inputs, and fails loudly when they are missing.
// TARGET_REQUIRED_OP is compiled from contracts.py into contracts.jsx.

function opRequiresTargets(task) {
    return TARGET_REQUIRED_OP[task] === true;
}

/**
 * The stable identity of one item: its MCP id, or a handle issued for it.
 *
 * Untagged artwork is an ordinary production input — selection and handle
 * targeting neither require nor add an `@mcp:id` note — so "has no note" is
 * not the same as "cannot be named". A handler that reads only the note
 * throws away an identity this mechanism would have supplied, which is what
 * `group_create` did: the snapshot issued a handle and the handler lost it.
 *
 * One implementation, so a handler and the snapshot cannot disagree about
 * what an item is called.
 *
 * @returns {string|null}
 */
function mcpTargetIdentity(item) {
    if (!item) return null;
    var id = null;
    try { id = extractMcpId(item.note || ""); } catch (e) { }
    if (!id && typeof mcpIssueHandle === "function") {
        try {
            var issued = mcpIssueHandle(item);
            if (issued.ok) id = issued.record.handle;
        } catch (e) { }
    }
    return id || null;
}

/** Return stable IDs known before a handler mutates or deletes its targets. */
function targetIdentitySnapshot(targets) {
    var ids = [];
    var unidentified = 0;
    for (var i = 0; i < targets.length; i++) {
        var id = mcpTargetIdentity(targets[i]);
        if (id) ids.push(id); else unidentified++;
    }
    return { ids: ids, unidentified: unidentified };
}

// ==================== Recovery outcome stream ====================

// Ownership cleanup happens below handler return values, while transaction
// recovery is returned by the handler itself. Both must reach the same
// operation result or the canonical boundary cannot distinguish "nothing was
// requested" from "cleanup ran and removed an unfinished object".
var _mcpRecoveryEvents = [];
var _mcpRecoverySequence = 0;
var _mcpRecoveryIdentitySequence = 0;

function mcpRecoveryReset() {
    _mcpRecoveryEvents = [];
    _mcpRecoverySequence = 0;
    _mcpRecoveryIdentitySequence = 0;
}

/** Give every recovery record a transport identity and explicit chronology. */
function mcpRecoveryIdentify(recovery) {
    if (!recovery || typeof recovery !== "object") return recovery;
    if (recovery instanceof Array) {
        for (var i = 0; i < recovery.length; i++) {
            mcpRecoveryIdentify(recovery[i]);
        }
        return recovery;
    }
    if (typeof recovery.eventSequence !== "number") {
        recovery.eventSequence = ++_mcpRecoverySequence;
    } else if (recovery.eventSequence > _mcpRecoverySequence) {
        _mcpRecoverySequence = recovery.eventSequence;
    }
    if (!recovery.recoveryId) {
        recovery.recoveryId = "recovery_" + (++_mcpRecoveryIdentitySequence);
    }
    return recovery;
}

/** Record one automatic recovery outcome after identifying the event. */
function mcpRecoveryRecord(recovery) {
    if (!recovery || typeof recovery !== "object") return recovery;
    mcpRecoveryIdentify(recovery);
    _mcpRecoveryEvents.push(recovery);
    return recovery;
}

function mcpRecoveryMark() {
    return _mcpRecoveryEvents.length;
}

function mcpRecoveriesSince(mark) {
    var out = [];
    var start = (typeof mark === "number" && mark >= 0) ? mark : 0;
    for (var i = start; i < _mcpRecoveryEvents.length; i++) {
        out.push(_mcpRecoveryEvents[i]);
    }
    return out;
}

function _mcpRecoveryArray(value) {
    if (!value) return [];
    return value instanceof Array ? value.slice(0) : [value];
}

/** Merge explicit and automatic outcomes without duplicating promoted records. */
function mcpMergeRecovery(first, second) {
    var candidates = _mcpRecoveryArray(first).concat(_mcpRecoveryArray(second));
    var out = [];
    for (var i = 0; i < candidates.length; i++) {
        var candidate = candidates[i];
        if (!candidate || typeof candidate !== "object") continue;
        mcpRecoveryIdentify(candidate);
        var duplicate = false;
        for (var j = 0; j < out.length; j++) {
            if (candidate === out[j] ||
                    (candidate.recoveryId &&
                     candidate.recoveryId === out[j].recoveryId) ||
                    (candidate.scopeKey && out[j].scopeKey &&
                     candidate.scopeKey === out[j].scopeKey &&
                     typeof candidate.eventSequence === "number" &&
                     candidate.eventSequence === out[j].eventSequence)) {
                duplicate = true;
                break;
            }
        }
        if (!duplicate) out.push(candidate);
    }
    if (!out.length) return null;
    return out.length === 1 ? out[0] : out;
}

/**
 * Record what a handler could not remove, on whichever result shape it has.
 *
 * OR15. A success result carries `data`; `makeError` builds `{ok, error}` with
 * no `data` at all. Each shape had its own convention for where the cleanup
 * record went, and the reducer read one of them — so a batch that died
 * leaving an untagged master behind reported no stranded artwork, and the
 * canonical boundary called it a clean failure. Writer and reader now agree
 * because there is one writer and one reader.
 */
function mcpSetCleanupFailures(result, failures) {
    if (!result) return result;
    var list = failures instanceof Array ? failures : [];
    if (result.data) {
        // Always present on a success shape, so a caller can distinguish
        // "nothing was stranded" from "this handler does not report it".
        result.data.cleanupFailures = list;
    } else if (list.length) {
        result.error = result.error || {};
        result.error.details = result.error.details || {};
        result.error.details.cleanupFailures = list;
    }
    return result;
}

/** Read that record back, whatever shape the result has. */
function mcpCleanupFailures(result) {
    if (!result) return [];
    if (result.data && result.data.cleanupFailures instanceof Array) {
        return result.data.cleanupFailures;
    }
    if (result.error && result.error.details &&
            result.error.details.cleanupFailures instanceof Array) {
        return result.error.details.cleanupFailures;
    }
    return [];
}

/**
 * Build a bounded, honest effect record from handler output and the identities
 * captured before mutation. `unidentified` counts only confirmed affected
 * objects without identities, never untouched targets in scope. It is a lower
 * bound when evidence is incomplete. The snapshot's unidentified target count
 * is separate and limits completeness; it is not evidence of a change.
 */
function recordOperationEffects(task, before, handlerResult, targetCount) {
    var effects = {
        created: [], modified: [], deleted: [],
        unidentified: 0,
        complete: false
    };
    var data = handlerResult.data || {};
    // Explicit handler guarantee: no mutation was attempted. Error stage alone
    // cannot establish this; validation can also happen after earlier writes.
    if (handlerResult.ok === false && handlerResult.error &&
            handlerResult.error.details &&
            handlerResult.error.details.writesAttempted === false) {
        effects.complete = true;
        return effects;
    }
    var ids = data.ids || data.createdIds || [];
    if (!(ids instanceof Array)) ids = [];

    // A batch keeps positional alignment by pushing null where an instance
    // failed, so `ids` is not a list of identities — it is a list of slots.
    // Copying it straight into effects.created put null into a field the
    // canonical boundary types as a list of strings, which failed validation
    // and took the whole tool call down with it. Worse, `complete` was still
    // true, so the report claimed to be an exhaustive account of a run that
    // had just lost an instance.
    var identified = [];
    var unnamed = 0;
    for (var idIndex = 0; idIndex < ids.length; idIndex++) {
        var candidate = ids[idIndex];
        if (typeof candidate === "string" && candidate.length) {
            identified.push(candidate);
        } else {
            unnamed++;
        }
    }
    // Anything the handler itself counted as skipped or failed also makes the
    // account partial, even when every id that came back was usable.
    var declinedCount = 0;
    if (typeof data.skipped === "number" && data.skipped > 0) {
        declinedCount = data.skipped;
    } else if (typeof data.failed === "number" && data.failed > 0) {
        declinedCount = data.failed;
    }

    // Artwork a rollback could not remove is on the page and carries no id,
    // so the lists below cannot be an exhaustive account of what changed.
    // This was read from nowhere: a batch whose master would not come away
    // reported every clone with complete true, while an untagged shape sat
    // beside them.
    // One accessor, so this cannot fall out of step with whatever shape the
    // handler returned. Reading `data.cleanupFailures` directly is what made
    // a fatal exit's stranded artwork invisible here.
    //
    // A stranded object is split by whether its identity is known. Counting
    // every cleanup record as unidentified was wrong in the case that
    // matters most: a clone is stamped before the step that fails, so it
    // survives on the page WITH an id, and reporting it as unidentified
    // both understates what the caller can act on and leaves its id out of
    // the effect account entirely. `unidentified` means artwork nothing can
    // name; an object whose id is recorded is not that.
    var strandedRecords = mcpCleanupFailures(handlerResult);
    var strandedCount = 0;
    var strandedIds = [];
    for (var sri = 0; sri < strandedRecords.length; sri++) {
        var strandedId = strandedRecords[sri].mcpId;
        if (typeof strandedId === "string" && strandedId.length) {
            strandedIds.push(strandedId);
        } else {
            strandedCount++;
        }
    }

    // Any stranded object makes the account partial, named or not.
    var reportedIncomplete = unnamed > 0 || declinedCount > 0 ||
        strandedRecords.length > 0;
    // `unidentified` means confirmed effects without identities. A null slot is
    // the opposite: a request that never became artwork at all. Counting
    // slots here made an all-failed batch look like it had produced
    // something, so the boundary classified it partial instead of failed —
    // forwarding `unapplied` alone would not have fixed that. Seed the count
    // with stranded artwork; branches below add confirmed unnamed changes.
    effects.unidentified = strandedCount;

    // Execution and completeness are separate questions, and only the second
    // was being answered. An all-failed batch returned ok true with an empty
    // but honest effect list, and the canonical boundary read that as
    // `execution: succeeded` — a request that created nothing, reported as
    // done. `unapplied` is the existing signal for "the handler declined
    // work it was asked to do", and the boundary turns it into partial, or
    // failed when nothing landed at all.
    if (declinedCount > 0) {
        effects.unapplied = [];
        for (var slot = 0; slot < ids.length; slot++) {
            if (typeof ids[slot] !== "string" || !ids[slot]) {
                effects.unapplied.push({ index: slot, reason: "instance_failed" });
            }
        }
        if (!effects.unapplied.length) {
            // The handler counted failures without leaving empty slots.
            effects.unapplied.push({ count: declinedCount, reason: "declined" });
        }
    }

    if (task === "element_replace") {
        effects.created = identified.slice();
        if (handlerResult.id && effects.created.indexOf(handlerResult.id) < 0) {
            effects.created.push(handlerResult.id);
        }
        effects.deleted = data.deletedIds instanceof Array ? data.deletedIds.slice() : [];
        if (data.oldId && effects.deleted.indexOf(data.oldId) < 0) effects.deleted.push(data.oldId);
        if (data.modifiedIds instanceof Array) {
            for (var rmi = 0; rmi < data.modifiedIds.length; rmi++) {
                var replaceModifiedId = data.modifiedIds[rmi];
                if (typeof replaceModifiedId === "string" && replaceModifiedId.length &&
                        effects.modified.indexOf(replaceModifiedId) < 0) {
                    effects.modified.push(replaceModifiedId);
                }
            }
        }
        if (data.unnamedModification === true) {
            effects.unidentified++;
            reportedIncomplete = true;
        }
        effects.complete = handlerResult.ok && !reportedIncomplete &&
            effects.created.length === 1 && effects.deleted.length === 1;
    } else if (task.indexOf("element_create") === 0 || task === "text_create" ||
               task === "layer_create" || task === "group_create" ||
               task === "clip_create") {
        // `group_create` and `clip_create` make a container and were absent
        // from this list, so a clip group retained after a late failure was
        // reported as nothing at all — the caller was told the operation
        // failed and given no way to find what it had left behind.
        effects.created = identified.slice();
        // They also reparent artwork that already existed. Reporting the
        // container alone described half of what changed while `complete`
        // asserted the account was the whole of it.
        //
        // From what the handler actually moved, not from what was requested.
        // `before.ids` named every member asked for, so a member that refused
        // to move was reported as modified, and a failure before any move ran
        // reported all of them. That is a false account, and `complete: false`
        // beside it does not make the identities true.
        // Creation handlers may delegate assembly to another creation handler.
        // `element_create({clipTo: ...})`, for example, creates its own item and
        // then asks `clip_create` to create a group and move the borrowed mask.
        // Restricting move evidence to the top-level task name discarded that
        // delegated modification and allowed the incomplete account to claim
        // `complete: true`.
        var movedIds = [];
        if (data.movedIds instanceof Array) {
            for (var mvi = 0; mvi < data.movedIds.length; mvi++) {
                var movedId = data.movedIds[mvi];
                if (typeof movedId === "string" && movedId.length &&
                        movedIds.indexOf(movedId) < 0) {
                    movedIds.push(movedId);
                }
            }
        }
        effects.modified = movedIds;
        // Only completed unnamed moves count as effects. The target snapshot
        // may also contain anonymous members that refused to move.
        if (typeof data.unnamedMoves === "number" && data.unnamedMoves > 0) {
            effects.unidentified += data.unnamedMoves;
            reportedIncomplete = true;
        } else if (before.unidentified > 0 && typeof data.unnamedMoves !== "number") {
            // An older handler supplied no move inventory for anonymous targets.
            reportedIncomplete = true;
        }
        if (handlerResult.id && effects.created.indexOf(handlerResult.id) < 0) {
            effects.created.push(handlerResult.id);
        }
        effects.complete = handlerResult.ok && !reportedIncomplete &&
            effects.created.length > 0;
    } else if (task === "element_delete") {
        effects.deleted = before.ids.slice();
        if (typeof data.deleted === "number") {
            effects.unidentified += Math.max(0, Math.min(before.unidentified,
                data.deleted - before.ids.length));
        }
        effects.complete = handlerResult.ok && before.unidentified === 0 &&
            typeof data.deleted === "number" && data.deleted === targetCount;
    } else if (task === "layer_visible") {
        // Layers have no page-item identity in this inventory. Hiding one
        // changes the canvas, so an empty list cannot claim exhaustive coverage.
        effects.complete = false;
    } else if (getOpClass(task) === "doc") {
        // Only claim what the handler says it actually changed.
        //
        // Listing every *requested* target reported artwork as modified that
        // the handler had skipped — styling a mixed selection of text frames
        // and a rectangle claimed the rectangle was modified too. When a
        // handler reports `modifiedIds`, narrow the record to the identified
        // targets it names. A count-only result can name the whole selection
        // only when all targets completed; a subset count identifies no item.
        //
        // A FAILED handler does not. The request is not evidence that
        // anything happened: `style_set_gradient` rejecting a gradient it
        // could not configure touches no target at all, and this branch
        // nevertheless named every one of them as modified — which the
        // canonical boundary reads as an effect and reports as `partial`
        // rather than `failed`. This is the same rule already applied to
        // `group_create` above ("from what the handler actually moved, not
        // from what was requested"), which was corrected there and left
        // standing here.
        //
        // Empty is not a claim that nothing changed; `complete` is false on
        // every failure, and that is what says the account is not
        // exhaustive. A handler that fails after modifying some of its
        // targets says so by attaching `modifiedIds` to the error result,
        // the way `clip_create` reports its retained group. An unrecoverable
        // false identity is worse than a recorded unknown.
        effects.modified = handlerResult.ok && declinedCount === 0 &&
            (typeof data.modified !== "number" || data.modified === targetCount)
            ? before.ids.slice() : [];
        var confirmedModifiedCount = typeof data.modified === "number" ? data.modified : 0;
        if (data.modifiedIds instanceof Array) {
            // Older text handlers put display labels in this list when no ID
            // exists. They cannot enter effects.modified, but still establish
            // writes, including writes before a later property failure.
            var writtenLabels = [];
            for (var li = 0; li < data.modifiedIds.length; li++) {
                var label = data.modifiedIds[li];
                if (typeof label === "string" && label.length && writtenLabels.indexOf(label) < 0) {
                    writtenLabels.push(label);
                }
            }
            confirmedModifiedCount = Math.max(confirmedModifiedCount, writtenLabels.length);
            var actuallyModified = [];
            for (var mi = 0; mi < before.ids.length; mi++) {
                for (var mj = 0; mj < data.modifiedIds.length; mj++) {
                    if (before.ids[mi] === data.modifiedIds[mj]) {
                        actuallyModified.push(before.ids[mi]);
                        break;
                    }
                }
            }
            effects.modified = actuallyModified;
        }
        if (typeof data.unnamedModified === "number") {
            effects.unidentified += data.unnamedModified;
        } else if (confirmedModifiedCount > 0) {
            // Subtract the maximum possible named writes to get the minimum
            // guaranteed anonymous writes. This is a worst-case bound, not an
            // execution-order assumption: if an anonymous target changed while
            // a named one did not, this may undercount. Coverage stays partial.
            effects.unidentified += Math.max(0, Math.min(before.unidentified,
                confirmedModifiedCount - before.ids.length));
        }
        effects.complete = handlerResult.ok && before.unidentified === 0 &&
            effects.unidentified === 0 && !reportedIncomplete &&
            (typeof data.failed !== "number" || data.failed === 0) &&
            (typeof data.modified !== "number" || data.modified === targetCount);
    } else {
        effects.complete = handlerResult.ok;
    }

    // An object the rollback could not remove is still on the page and was
    // still created by this operation, whatever task made it. This folding
    // lived inside the element-creation branch, so a stranded group or clip
    // path — the cases most likely to strand anything — was counted as
    // unidentified even when its id was known. It runs here, after every
    // branch has finished assigning `created`, because an earlier placement
    // was simply overwritten.
    for (var si = 0; si < strandedIds.length; si++) {
        if (effects.created.indexOf(strandedIds[si]) < 0) {
            effects.created.push(strandedIds[si]);
        }
    }
    return effects;
}

/** Verify the pilot operations from direct readback/handler evidence. */
function verifyOperationPostcondition(task, params, targets, handlerResult, effects) {
    var data = handlerResult.data || {};
    if (!handlerResult.ok) {
        return { status: "not_run", complete: false };
    }
    if (task.indexOf("element_create") === 0) {
        return {
            status: effects.created.length > 0 ? "passed" : "unavailable",
            complete: effects.created.length > 0,
            created: effects.created.slice()
        };
    }
    if (task === "style_set_opacity") {
        var expected = params.opacity !== undefined ? params.opacity : 100;
        if (expected < 0) expected = 0;
        if (expected > 100) expected = 100;
        for (var i = 0; i < targets.length; i++) {
            try {
                if (targets[i].opacity !== expected) {
                    return { status: "failed", complete: true, expected: expected, failedAt: i };
                }
            } catch (e) {
                return { status: "unavailable", complete: false, message: e.message };
            }
        }
        return { status: "passed", complete: true, expected: expected, checked: targets.length };
    }
    if (task === "measure_bounds") {
        return {
            status: (targets.length === 0 || data.bounds) ? "passed" : "failed",
            complete: true,
            checked: targets.length
        };
    }
    if (task === "element_delete") {
        return {
            status: (typeof data.deleted === "number" && data.deleted === targets.length)
                ? "passed" : "failed",
            complete: true,
            checked: targets.length
        };
    }
    return { status: "not_requested", complete: false };
}

/** Contract/preflight pass that invokes no operation handler. */
function validateOpBatch(ops, options) {
    var results = [];
    var failed = 0;
    var priorMutation = false;
    var strict = options.strict === true;
    for (var i = 0; i < ops.length; i++) {
        var op = ops[i];
        var validation = validateOp(op, options.strictSchema);
        var selectorError = null;
        if (validation.ok && op.targets) {
            try { normalizeTargetSelector(op.targets); }
            catch (e) {
                selectorError = {
                    code: e.code || ErrorCodes.V_INVALID_TARGETS,
                    message: e.message,
                    stage: e.stage || "validate",
                    details: e.meta || null
                };
            }
        }
        var ok = validation.ok && !selectorError;
        var error = selectorError || (validation.ok ? null : validation.errors[0]);
        if (error && error.error) error = error.error;
        results.push({
            index: i,
            task: op.task,
            ok: ok,
            status: ok ? "validated" : "invalid",
            targets_resolved: 0,
            targetResolution: op.targets
                ? (priorMutation ? "deferred" : "not_performed")
                : "not_required",
            effects: { created: [], modified: [], deleted: [], unidentified: 0, complete: true },
            postcondition: { status: "not_run", complete: false },
            error: error
        });
        if (!ok) {
            failed++;
            if (strict) break;
        }
        if (getOpClass(op.task) === "doc") priorMutation = true;
    }
    return {
        ok: failed === 0,
        mode: "validate",
        schemaVersion: OP_SCHEMA_VERSION,
        ops: results,
        createdIds: [],
        effects: { created: [], modified: [], deleted: [], unidentified: 0, complete: true },
        stats: { total: ops.length, executed: 0, validated: results.length, passed: results.length - failed, failed: failed },
        warnings: priorMutation ? ["Target resolution after a planned mutation is deferred until apply mode."] : []
    };
}

// Dedupe cache: warn once per unknown task name
var _OP_CLASS_WARNED = {};

/**
 * Get classification for an op task.
 * @param {string} task - Op task name
 * @param {Object} [ctx] - Batch context (for warnings)
 * @returns {string} "doc", "session", or "readonly"
 */
function getOpClass(task, ctx) {
    var cls = OP_CLASS[task];
    if (!cls && OP_HANDLERS[task] && !_OP_CLASS_WARNED[task]) {
        _OP_CLASS_WARNED[task] = true;
        if (ctx && ctx.warn) {
            ctx.warn("OP_CLASS: '" + task + "' has handler but no classification → readonly");
        }
    }
    return cls || "readonly";
}

/**
 * How many targets an operation asked for.
 *
 * For an `id` or `handle` selector this is the length of the requested list,
 * which is what makes "asked for 2, found 1" visible. For selectors whose
 * size is only known after resolution (query/all/layer/spatial) the resolved
 * count is the honest answer — there was no fixed request size.
 */
function _opTargetsRequested(selector, resolvedCount) {
    if (!selector) return 0;
    var target = selector.target || selector;
    if (target.ids instanceof Array) return target.ids.length;
    if (target.handles instanceof Array) return target.handles.length;
    return resolvedCount;
}

/**
 * Execute sub-ops within an existing context. Does NOT start/commit heap txn.
 * Used by executeOpBatch for the main loop AND by compound handler for sub-ops.
 *
 * @param {Array} ops - Operations to execute
 * @param {Object} ctx - Existing execution context (inherited)
 * @param {Object} mode - Execution mode:
 *   mode.strict    — stop on first error
 *   mode.rollback  — undo completed ops on failure (requires strict)
 *   mode.snapshot  — use snapshot-based rollback (preferred over undo)
 *   mode.doc       — active document
 *   mode.preSnapshot — pre-captured snapshot (if any)
 *   mode.trace     — trace array (or null)
 *   mode.chunkSize — progress chunk size (0 = disabled)
 *   mode.onProgress — progress callback
 * @returns {Object} {ok, results[], createdIds[], passed, failed, undoCount, rolledBackCount}
 */
function executeSubOps(ops, ctx, mode) {
    var doc = mode.doc;
    var strict = mode.strict || false;
    var rollback = mode.rollback || false;
    var useSnapshot = mode.snapshot || false;
    var trace = mode.trace || null;
    var chunkSize = mode.chunkSize || 0;
    var onProgress = mode.onProgress || null;
    var preSnapshot = mode.preSnapshot || null;

    var results = [];
    var passed = 0;
    var failed = 0;
    var undoCount = 0;
    var createdIds = [];
    var rolledBackCount = 0;


    var chunkIndex = 0;

    for (var i = 0; i < ops.length; i++) {
        var op = ops[i];
        var t0 = ctx.clock();

        if (trace) trace.push("[OP " + i + "] " + op.task);

        // Validate the actual operation immediately before it runs. Values and
        // selectors can depend on earlier operations, so outcomes are not cached.
        var validation = validateOp(op, mode.strictSchema);
        ctx.diagnostics.validationsRun++;
        if (!validation.ok) {
            results.push({
                index: i,
                task: op.task,
                ok: false,
                duration_ms: ctx.clock() - t0,
                targets_resolved: 0,
                id: op.params ? op.params.id : null,
                data: null,
                warnings: [],
                error: validation.errors[0]
            });
            failed++;
            if (strict) break;
            continue;
        }

        var handler = OP_HANDLERS[op.task];
        var targets = [];
        var unresolvedIds = [];
        try {
            ctx._lastResolution = null;
            targets = op.targets ? resolveTargets(doc, op.targets, ctx) : [];
            if (ctx._lastResolution && ctx._lastResolution.unresolvedIds) {
                unresolvedIds = ctx._lastResolution.unresolvedIds;
            }
        } catch (resolveErr) {
            results.push({
                index: i,
                task: op.task,
                ok: false,
                duration_ms: ctx.clock() - t0,
                targets_resolved: 0,
                id: op.params ? op.params.id : null,
                data: null,
                warnings: [],
                error: {
                    code: resolveErr.code || ErrorCodes.R_COLLECT_FAILED,
                    message: resolveErr.message,
                    stage: resolveErr.stage || "resolve",
                    details: resolveErr.meta || null
                }
            });
            failed++;
            if (strict) break;
            continue;
        }

        if (opRequiresTargets(op.task) && targets.length === 0) {
            results.push({
                index: i,
                task: op.task,
                ok: false,
                duration_ms: ctx.clock() - t0,
                targets_resolved: 0,
                id: op.params ? op.params.id : null,
                data: null,
                warnings: [],
                error: makeError(
                    ErrorCodes.V_EMPTY_TARGETS || "V014",
                    "Mutating operation resolved no targets: " + op.task,
                    "resolve"
                ).error
            });
            failed++;
            if (strict) break;
            continue;
        }

        // C2: Guard evaluation — filter targets by when/unless predicates
        var guardSkipped = false;
        if (op.when || op.unless) {
            if (op.when && op.unless) {
                // B15: opResult not yet initialized here (var hoisted as undefined).
                // Route warning through ctx so it appears in batch report.warnings.
                ctx.warn("Op has both 'when' and 'unless'; 'when' takes precedence. (op " + i + ")");
            }
            var guard = op.when || op.unless;
            var isUnless = !!op.unless;
            var guardResult = filterByGuard(targets, guard, isUnless);
            if (!guardResult.ok) {
                // Guard error (G001/G002/G003) — treat as op failure
                results.push({
                    index: i,
                    task: op.task,
                    ok: false,
                    duration_ms: ctx.clock() - t0,
                    targets_resolved: targets.length,
                    id: op.params ? op.params.id : null,
                    data: null,
                    warnings: [],
                    error: guardResult.error
                });
                failed++;
                if (strict) break;
                continue;
            }
            targets = guardResult.targets;
            if (targets.length === 0) {
                // All targets filtered out — skip op
                results.push({
                    index: i,
                    task: op.task,
                    ok: true,
                    skipped: true,
                    duration_ms: ctx.clock() - t0,
                    targets_resolved: 0,
                    id: op.params ? op.params.id : null,
                    data: { reason: "guard_filtered" },
                    warnings: [],
                    error: null
                });
                passed++;
                continue;
            }
        }

        var opResult = {
            index: i,
            task: op.task,
            ok: false,
            duration_ms: 0,
            // What the caller ASKED for, alongside what was found. Reporting
            // only the resolved count made a partially-satisfied request look
            // identical to a fully satisfied one.
            targets_requested: _opTargetsRequested(op.targets, targets.length),
            targets_resolved: targets.length,
            unresolvedIds: unresolvedIds,
            id: op.params ? op.params.id : null,
            data: null,
            warnings: [],
            error: null,
            recovery: null,
            effects: { created: [], modified: [], deleted: [], unidentified: 0, complete: false },
            postcondition: { status: "not_run", complete: false }
        };

        var recoveryMark = mcpRecoveryMark();
        try {
            // P3: Resolve field descriptors in params before handler sees them
            var resolvedParams = op.params || {};
            var handlerResult;
            var handlerEffects = null;
            var targetSnapshot = targetIdentitySnapshot(targets);
            opResult.targets_unidentified = targetSnapshot.unidentified;
            var hasFieldDescs = typeof resolveFields === "function" &&
                typeof containsFields === "function" && containsFields(resolvedParams);

            if (hasFieldDescs && targets.length > 0) {
                // Fan-out: call handler once per target with per-target resolved params
                var fanOk = true;
                var fanData = [];
                var fanWarnings = [];
                var fanRecovery = [];
                var fanId = null;
                var fanError = null;
                var fanEffects = {
                    created: [], modified: [], deleted: [], unidentified: 0, complete: true
                };
                for (var t = 0; t < targets.length; t++) {
                    var perTargetParams = resolveFields(resolvedParams, targets[t], t, targets.length, ctx);
                    var singleSnapshot = targetIdentitySnapshot([targets[t]]);
                    var singleResult = handler(perTargetParams, [targets[t]], ctx);
                    // Normalize unconditionally — guaranteed shape: {ok, data, warnings, error, id}
                    singleResult = normalizeHandlerResult(op.task, singleResult);
                    // Preserve per-target write evidence through field fan-out.
                    // Reducing only {perTarget, count} would infer all requested
                    // identities again, including targets whose writes failed.
                    var singleEffects = recordOperationEffects(op.task, singleSnapshot, singleResult, 1);
                    fanEffects.created = fanEffects.created.concat(singleEffects.created);
                    fanEffects.modified = fanEffects.modified.concat(singleEffects.modified);
                    fanEffects.deleted = fanEffects.deleted.concat(singleEffects.deleted);
                    fanEffects.unidentified += singleEffects.unidentified;
                    if (!singleEffects.complete) fanEffects.complete = false;
                    var singleUnapplied = (singleEffects.unapplied || [])
                        .concat((singleResult.data && singleResult.data.skippedIds) || []);
                    if (singleUnapplied.length) {
                        fanEffects.unapplied = (fanEffects.unapplied || []).concat(singleUnapplied);
                    }
                    if (singleResult.ok === false) {
                        fanOk = false;
                        if (!fanError) fanError = singleResult.error;
                    }
                    fanData.push(singleResult.data);
                    fanWarnings = fanWarnings.concat(singleResult.warnings);
                    if (singleResult.recovery) fanRecovery.push(singleResult.recovery);
                    if (singleResult.id && !fanId) fanId = singleResult.id;
                }
                handlerResult = {
                    ok: fanOk,
                    data: { perTarget: fanData, count: targets.length },
                    warnings: fanWarnings,
                    id: fanId,
                    error: fanError,
                    recovery: fanRecovery.length ? fanRecovery : null
                };
                handlerEffects = fanEffects;
            } else {
                if (typeof resolveFields === "function") {
                    resolvedParams = resolveFields(resolvedParams, targets[0] || null, 0, targets.length || 1, ctx);
                }
                handlerResult = handler(resolvedParams, targets, ctx);
            }

            // Normalize handler result via centralised normalizer
            handlerResult = normalizeHandlerResult(op.task, handlerResult);
            handlerResult.recovery = mcpMergeRecovery(
                handlerResult.recovery, mcpRecoveriesSince(recoveryMark)
            );
            opResult.ok = handlerResult.ok;
            opResult.data = handlerResult.data;
            opResult.warnings = handlerResult.warnings;
            opResult.id = handlerResult.id || opResult.id;
            opResult.recovery = handlerResult.recovery;
            opResult.effects = handlerEffects || recordOperationEffects(
                op.task, targetSnapshot, handlerResult, targets.length
            );
            if (typeof mcpOwnNextEvent === "function") {
                opResult.effects.eventSequence = mcpOwnNextEvent();
            }
            // `opResult.id` starts as the caller's requested id, but the batch
            // contract exposes it as a created id. A failed replacement that
            // never established or retained that identity must not echo the
            // request as if it named surviving artwork.
            if (op.task === "element_replace" && !handlerResult.id &&
                    opResult.effects.created.length === 0) {
                opResult.id = null;
            }
            opResult.postcondition = verifyOperationPostcondition(
                op.task, resolvedParams, targets, handlerResult, opResult.effects
            );

            // A requested target that matched nothing is reported here, AFTER
            // the handler's own warnings are assigned (they replace the array).
            // The effect account is also no longer presented as complete: the
            // operation did everything it could, but not everything it was
            // asked to do, and "complete" must mean the latter.
            if (unresolvedIds.length > 0) {
                opResult.warnings = (opResult.warnings || []).concat([
                    "Targets not found and therefore not modified: " +
                    unresolvedIds.join(", ")
                ]);
                opResult.effects.complete = false;
            }

            // Record targets the operation was asked to act on but did not.
            //
            // This is deliberately NARROWER than `effects.complete`, which is
            // also false when affected artwork simply had no stable identity —
            // there the work happened, it just could not be named. `unapplied`
            // means the requested work did NOT happen to those targets, and it
            // is what degrades the batch's execution status below "succeeded".
            // Without it, `text_set_content` aimed at a rectangle reported
            // "succeeded" while changing nothing (the F19 failure mode).
            var unapplied = unresolvedIds.slice();
            var skipped = opResult.data && opResult.data.skippedIds;
            if (skipped instanceof Array) unapplied = unapplied.concat(skipped);
            if (unapplied.length > 0) opResult.unapplied = unapplied;
            if (!opResult.ok) {
                opResult.error = handlerResult.error;
                if (!opResult.error && handlerResult.data && handlerResult.data.message) {
                    opResult.error = { code: "R_UNSTRUCTURED", message: handlerResult.data.message, stage: "apply" };
                }
            }

            if (opResult.ok) {
                passed++;
                var _batchIds = opResult.data && (opResult.data.ids || opResult.data.createdIds);
                if (_batchIds && typeof _batchIds.length === "number" && _batchIds.length > 0) {
                    for (var mi = 0; mi < _batchIds.length; mi++) createdIds.push(_batchIds[mi]);
                } else if (opResult.id) {
                    createdIds.push(opResult.id);
                }
                if (getOpClass(op.task, ctx) === "doc") {
                    undoCount++;
                }
            } else {
                failed++;
                if (strict) {
                    opResult.duration_ms = ctx.clock() - t0;
                    results.push(opResult);
                    if (rollback) {
                        rolledBackCount = rollbackBatch(doc, preSnapshot, createdIds, undoCount, useSnapshot, trace);
                    }
                    break;
                }
            }

        } catch (e) {
            opResult.ok = false;
            opResult.recovery = mcpMergeRecovery(
                opResult.recovery, mcpRecoveriesSince(recoveryMark)
            );
            opResult.error = makeError(
                ErrorCodes.R_APPLY_FAILED,
                e.message,
                "apply",
                null,
                { line: e.line || null, task: op.task, opIndex: i }
            ).error;
            failed++;

            if (strict) {
                opResult.duration_ms = ctx.clock() - t0;
                results.push(opResult);
                if (rollback) {
                    rolledBackCount = rollbackBatch(doc, preSnapshot, createdIds, undoCount, useSnapshot, trace);
                }
                break;
            }
        }

        opResult.duration_ms = ctx.clock() - t0;
        results.push(opResult);

        // Progress callback
        if (chunkSize > 0 && onProgress && results.length % chunkSize === 0) {
            var chunkReport = {
                chunkIndex: chunkIndex++,
                opsCompleted: results.length,
                opsTotal: ops.length,
                passed: passed,
                failed: failed,
                lastOp: op.task,
                percentComplete: Math.round((results.length / ops.length) * 100)
            };
            try {
                onProgress(chunkReport);
            } catch (cbErr) {
                if (trace) trace.push("[PROGRESS ERROR] " + cbErr.message);
            }
            if (trace) trace.push("[CHUNK " + (chunkIndex - 1) + "] " + results.length + "/" + ops.length);
        }
    }

    return {
        ok: failed === 0,
        results: results,
        createdIds: createdIds,
        passed: passed,
        failed: failed,
        undoCount: undoCount,
        rolledBackCount: rolledBackCount
    };
}

// ── Field naming glossary ──────────────────────────────────────────
// Internal (executeSubOps return): "results"  — per-op result objects
// External (batch report):         "ops"      — same data, renamed for API consumers
// Reason: "results" is an implementation name; "ops" matches the input array name
//         and is the documented API surface (see Batch Report Contract above).

// ==================== Batch Execution ====================

/**
 * Execute a batch of operations
 *
 * Batch Report Contract:
 *   report.ok            — true if all ops passed
 *   report.createdIds    — flat list of ALL created MCP IDs
 *                          (from opResult.id + opResult.data.ids + opResult.data.createdIds)
 *   report.ops[i].id     — singular ID (element_create, layer_create)
 *   report.ops[i].data   — handler-specific data
 *                          (element_create_multi → {ids[], created, skipped, stylingMode})
 *   report.stats         — {total, executed, passed, failed, failedAtIndex}
 *
 * Journal Entry Schema (written when options.journal === true):
 *   entry.ops            — serialized op list (task/params/targets only)
 *   entry.createdIds     — full ID list (for replay cleanup)
 *   entry.report         — {ok, stats} summary
 *
 * @param {Array<Object>} ops - Array of operations
 * @param {Object} options - Execution options
 * @param {string} options.space.units - Coordinate units ("pt", "mm")
 * @param {string} options.space.origin - Origin ("document", "artboard")
 * @param {string} options.space.yAxis - Y-axis direction ("down", "up")
 * @param {boolean} options.strict - Stop on first error
 * @param {boolean} options.stopOnError - Alias for strict
 * @param {boolean} options.rollback - Undo all completed ops on failure (requires strict)
 * @param {boolean} options.snapshot - Capture state before execution for snapshot-based rollback (preferred over undo)
 * @param {number} options.chunkSize - Emit progress every N ops (0 = disabled)
 * @param {Function} options.onProgress - Progress callback (receives chunk report)
 * @param {boolean} options.trace - Include execution trace
 * @param {boolean} options.summaryOnly - Omit per-op details, return only stats+createdIds (reduces token usage)
 * @param {boolean} options.journal - Record ops to journal for replay (P6)
 * @param {Object} options.recompute - Replay journal from scratch: {confirm: true, snapshotFirst: true}
 * @returns {Object} Batch report
 */
function executeOpBatch(ops, options) {
    options = options || {};
    // Recovery events are host-call-local facts. Never let a prior batch's
    // cleanup become evidence for this one, and bound the in-memory stream.
    mcpRecoveryReset();
    var strict = options.strict || options.stopOnError || false;
    var rollback = options.rollback === true;
    var useSnapshot = options.snapshot === true;
    var chunkSize = options.chunkSize || 0;
    var onProgress = options.onProgress || null;
    var trace = options.trace ? [] : null;
    var summaryOnly = options.summaryOnly === true;
    var journalEnabled = options.journal === true;
    var createdIds = [];  // Track created element IDs for summaryOnly mode
    var preSnapshot = null;  // Pre-execution snapshot for rollback

    // Check for active document
    var doc = null;
    try { doc = app.activeDocument; } catch (e) { }
    if (!doc) {
        return {
            ok: false,
            errors: [makeError(ErrorCodes.V_NO_DOCUMENT, "No active document", "validate")],
            ops: [],
            stats: { total: ops.length, passed: 0, failed: ops.length }
        };
    }

    // Build execution context (injected into handlers)
    // P2: clock is injectable for testability; isolates Date impurity
    var ctx = {
        doc: doc,
        app: app,
        clock: options.clock || function () { return new Date().getTime(); },
        startingSelection: selectionToArray(doc.selection || []),
        options: options,
        space: options.space || { units: "pt", origin: "document", yAxis: "down" },
        defaultLayer: options.defaultLayer || null,
        warnings: [],
        // Diagnostics counters
        diagnostics: {
            resolutions: 0,
            validationsRun: 0,
            selectionWarnings: 0
        },
        compoundDepth: 0
    };
    ctx.warn = function (msg) { ctx.warnings.push(msg); };

    // === T04: UNSUPPORTED RECOVERY GATE ===
    // Rejected here — before heapBeginTxn, before any snapshot, and before a
    // single op runs — so an unsupported request performs no edits at all.
    //
    // Why these are refused rather than "best effort":
    //
    //   recompute  Deleted every @mcp:id-tagged item in the document and then
    //              replayed the journal.  Its safety net was a property
    //              snapshot that cannot recreate a deleted object: it stores
    //              position, size, opacity, visibility, lock and fill/stroke
    //              for tagged items only.  If the replay failed, the artwork
    //              was gone and restoreSnapshot had nothing to restore it
    //              onto.  This is destructive replay without recovery.
    //
    //   rollback / snapshot
    //              captureSnapshot records the same shallow property set, and
    //              only for tagged items.  It cannot restore path anchors and
    //              handles, text content or runs, parents/groups, z-order, or
    //              layer topology, and it cannot recreate deleted objects.  A
    //              batch that failed mid-way therefore reported rolledBack
    //              while leaving created artwork in place and unrelated edits
    //              unreverted.
    //
    // A verifiable inverse for a documented subset of operations is T28; an
    // explicit, live-tested document checkpoint is T29.  Until one of those
    // lands, refusing is the only truthful answer.
    var unsupportedRecovery = null;
    if (options.recompute) {
        unsupportedRecovery = "recompute";
    } else if (options.rollback === true) {
        unsupportedRecovery = "rollback";
    } else if (options.snapshot === true) {
        unsupportedRecovery = "snapshot";
    }

    if (unsupportedRecovery) {
        return {
            ok: false,
            errors: [makeError(
                ErrorCodes.E_UNSUPPORTED_RECOVERY || "E002",
                "options." + unsupportedRecovery + " is not supported: the " +
                "property snapshot cannot restore the state it would need to " +
                "(deleted objects, path geometry, text, grouping, z-order). " +
                "Rejected before execution — no operations ran and nothing " +
                "was changed. Re-run without it, or take an explicit " +
                "checkpoint first.",
                "validate",
                null,
                { option: unsupportedRecovery }
            )],
            ops: [],
            stats: { total: ops.length, executed: 0, passed: 0, failed: 0 },
            recovery: {
                requested: unsupportedRecovery,
                status: "unsupported",
                scope: "entire structured batch"
            }
        };
    }

    if (options.mode !== undefined && options.mode !== "apply" && options.mode !== "validate") {
        return {
            ok: false,
            errors: [makeError(
                ErrorCodes.V_INVALID_PARAM_VALUE,
                "options.mode must be 'apply' or 'validate'",
                "validate"
            )],
            ops: [],
            stats: { total: ops.length, executed: 0, passed: 0, failed: 0 }
        };
    }

    // Validation mode ends before heap transaction, handler dispatch and
    // redraw. It is therefore read-only by construction.
    if (options.mode === "validate") {
        return validateOpBatch(ops, options);
    }

    // Begin heap transaction for this batch (pass doc to avoid redundant lookup)
    var heapBatchId = generateUUID();
    heapBeginTxn(heapBatchId, doc);

    // === EXECUTION PHASE (fresh validation and target resolution) ===
    if (trace) trace.push("[EXECUTE] Running " + ops.length + " ops (fresh resolution)");

    // T04: no pre-execution snapshot is taken.  `rollback` and `snapshot` are
    // rejected by the gate above, so this batch has no recovery path — which
    // is now stated rather than implied by a snapshot that could not deliver
    // it.  preSnapshot stays null and executeSubOps runs with rollback off.

    // C1: Delegate to executeSubOps — single source of truth for per-op execution
    var subResult = executeSubOps(ops, ctx, {
        strict: strict,
        rollback: false,
        snapshot: false,
        strictSchema: options.strictSchema,
        doc: doc,
        preSnapshot: null,
        trace: trace,
        chunkSize: chunkSize,
        onProgress: onProgress
    });

    var results = subResult.results;
    var passed = subResult.passed;
    var failed = subResult.failed;
    var createdIds = subResult.createdIds;
    var rolledBackCount = subResult.rolledBackCount;

    // Final chunk if not aligned
    if (chunkSize > 0 && onProgress && results.length % chunkSize !== 0) {
        try {
            onProgress({
                chunkIndex: Math.floor(results.length / chunkSize),
                opsCompleted: results.length,
                opsTotal: ops.length,
                passed: passed,
                failed: failed,
                isFinal: true,
                percentComplete: 100
            });
        } catch (cbErr) {
            if (trace) trace.push("[PROGRESS ERROR] " + cbErr.message);
        }
    }

    // === BUILD REPORT ===
    var allOk = failed === 0;
    var totalMs = results.reduce(function (sum, r) { return sum + r.duration_ms; }, 0);

    // P1: Surface handler warnings + deprecation warnings in report
    var reportWarnings = ctx.warnings ? ctx.warnings.slice() : [];
    // Aggregate per-op handler warnings into report-level warnings
    for (var rwi = 0; rwi < results.length; rwi++) {
        if (results[rwi].warnings && results[rwi].warnings.length > 0) {
            for (var rwj = 0; rwj < results[rwi].warnings.length; rwj++) {
                reportWarnings.push(results[rwi].warnings[rwj]);
            }
        }
    }
    if (ctx.diagnostics.selectionWarnings > 0) {
        reportWarnings.push("DEPRECATED: 'selection' targeting used " + ctx.diagnostics.selectionWarnings + "x. Use 'id' targeting. Removal at v2.0.");
    }

    // Find first failed op index for quick debugging
    var failedAtIndex = null;
    for (var fi = 0; fi < results.length; fi++) {
        if (!results[fi].ok) { failedAtIndex = results[fi].index; break; }
    }

    var batchEffects = {
        created: [], modified: [], deleted: [], unidentified: 0, complete: true
    };
    // Outcome chronology must survive summaryOnly, which omits operation
    // details. Aggregate ID arrays cannot distinguish delete/recreate order.
    var effectSteps = [];
    for (var efi = 0; efi < results.length; efi++) {
        var oef = results[efi].effects;
        if (!oef) { batchEffects.complete = false; continue; }
        effectSteps.push(oef);
        batchEffects.created = batchEffects.created.concat(oef.created || []);
        batchEffects.modified = batchEffects.modified.concat(oef.modified || []);
        batchEffects.deleted = batchEffects.deleted.concat(oef.deleted || []);
        batchEffects.unidentified += oef.unidentified || 0;
        if (!oef.complete) batchEffects.complete = false;
        if (results[efi].unapplied instanceof Array && results[efi].unapplied.length) {
            batchEffects.unapplied = (batchEffects.unapplied || [])
                .concat(results[efi].unapplied);
        }
        // The reducer also records declined work on the effects object
        // itself. This loop copied five fields from `oef` and read
        // `unapplied` from the op result beside it, so a batch whose
        // instances were declined arrived at the boundary with nothing
        // saying so, and an operation that created nothing was reported as
        // succeeded.
        if (oef.unapplied instanceof Array && oef.unapplied.length) {
            batchEffects.unapplied = (batchEffects.unapplied || [])
                .concat(oef.unapplied);
        }
    }

    // Recovery is bounded outcome metadata, not optional operation detail.
    // Promote every record to the batch before summaryOnly can omit ops and
    // before the Python wire budget can omit op.data. Keep the operation
    // coordinates alongside nested compound provenance rather than
    // overwriting it.
    var batchRecovery = null;
    for (var bri = 0; bri < results.length; bri++) {
        var operationRecovery = _mcpRecoveryArray(results[bri].recovery);
        for (var brj = 0; brj < operationRecovery.length; brj++) {
            var sourceRecovery = operationRecovery[brj];
            if (!sourceRecovery || typeof sourceRecovery !== "object") continue;
            var batchRecord = {};
            for (var brk in sourceRecovery) {
                if (sourceRecovery.hasOwnProperty(brk)) {
                    batchRecord[brk] = sourceRecovery[brk];
                }
            }
            batchRecord.batchOperationIndex = results[bri].index;
            batchRecord.batchOperationTask = results[bri].task;
            batchRecovery = mcpMergeRecovery(batchRecovery, batchRecord);
        }
    }

    // === JOURNAL RECORDING (P6) — runs for BOTH summary and full reports ===
    // Uses internal results[] array, not the returned report, so journal
    // always has full detail even when summaryOnly omits per-op data.
    if (journalEnabled && typeof journalAppend === "function") {
        var batchId = (typeof generateUUID === "function") ? generateUUID() : ("batch_" + ctx.clock());
        // Strip ops to just task/params/targets (no resolved items)
        var journalOps = [];
        for (var j = 0; j < ops.length; j++) {
            journalOps.push({
                task: ops[j].task,
                params: ops[j].params,
                targets: ops[j].targets
            });
        }
        journalAppend({
            batchId: batchId,
            timestamp: ctx.clock(),
            ops: journalOps,
            createdIds: createdIds,
            effects: batchEffects,
            generatorMeta: options.generatorMeta || undefined,
            options: { strict: strict, rollback: rollback, snapshot: useSnapshot },
            report: { ok: allOk, stats: { total: ops.length, passed: passed, failed: failed } }
        }, doc.name, doc);
    }

    // Commit heap transaction: persist index mutations from this batch
    var heapStats = heapCommitTxn();
    ctx.diagnostics.heapStats = heapDiagnostics();
    ctx.diagnostics.heapCommit = heapStats;

    // Gate redraw on actual DOM mutations (redraw is expensive)
    if (passed > 0) {
        app.redraw();
    }

    // summaryOnly mode: omit per-op details to reduce token usage
    if (summaryOnly) {
        return {
            ok: allOk,
            schemaVersion: OP_SCHEMA_VERSION,
            summaryOnly: true,
            rolledBack: rolledBackCount,
            createdIds: createdIds,
            effects: batchEffects,
            recovery: batchRecovery,
            effectSteps: effectSteps,
            stats: {
                total: ops.length,
                executed: results.length,
                passed: passed,
                failed: failed,
                failedAtIndex: failedAtIndex
            },
            timing: { total_ms: totalMs },
            diagnostics: ctx.diagnostics,
            warnings: reportWarnings.length > 0 ? reportWarnings : undefined,
            errors: (function () {
                var errs = [];
                for (var ei = 0; ei < results.length; ei++) {
                    if (!results[ei].ok) errs.push({ index: results[ei].index, task: results[ei].task, error: results[ei].error });
                }
                return errs.length > 0 ? errs : undefined;
            })(),
            trace: trace
        };
    }

    return {
        ok: allOk,
        schemaVersion: OP_SCHEMA_VERSION,
        rolledBack: rolledBackCount,
        createdIds: createdIds,
        effects: batchEffects,
        recovery: batchRecovery,
        effectSteps: effectSteps,
        ops: results,
        stats: {
            total: ops.length,
            executed: results.length,
            passed: passed,
            failed: failed,
            failedAtIndex: failedAtIndex
        },
        timing: { total_ms: totalMs },
        diagnostics: ctx.diagnostics,
        warnings: reportWarnings.length > 0 ? reportWarnings : undefined,
        trace: trace
    };
}

// ==================== Profiling Utility ====================

/**
 * Profile a function execution
 * @param {string} label
 * @param {Function} fn
 * @returns {Object} {result, duration_ms}
 */
function profileOp(label, fn, clock) {
    var now = clock || function () { return new Date().getTime(); };
    var t0 = now();
    var result = fn();
    var t1 = now();
    return { result: result, duration_ms: t1 - t0, label: label };
}

