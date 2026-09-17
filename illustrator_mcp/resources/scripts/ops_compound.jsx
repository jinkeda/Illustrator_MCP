/**
 * ops_compound.jsx — Compound meta-op (C1)
 * Sequences sub-ops with $prev/$prevAll ID forwarding.
 *
 * @requires ops_core (registerOpHandler, executeSubOps, makeError, ErrorCodes)
 * @requires contracts (validateOp)
 * @version 1.0.0
 */

// Dependency guard
if (typeof registerOpHandler === "undefined" || typeof executeSubOps === "undefined") {
    throw new Error("ops_compound.jsx requires ops_core.jsx (registerOpHandler, executeSubOps)");
}

// ==================== Token Resolution ====================

/**
 * Resolve $prev / $prevAll tokens in a single op's targets.ids.
 * Pure function — never mutates the input op.
 *
 * @param {Object} op - The sub-operation to resolve
 * @param {string|null} prevId - ID from previous op (null if none)
 * @param {Array} prevAllIds - All IDs from previous op (may be empty)
 * @returns {Object} {ok: true, op: resolvedOp} or {ok: false, error: {...}}
 */
function resolvePrevTokens(op, prevId, prevAllIds) {
    // No targets → pass through unchanged
    if (!op.targets) {
        return { ok: true, op: op };
    }

    // The Python boundary normalizes selectors to the wrapped shape. Keep
    // both public spellings and all operation metadata during substitution.
    var selector = op.targets.target || op.targets;
    if (selector.type !== "id") {
        // Scan for accidental token usage in non-id targets
        var targetsStr = JSON.stringify(op.targets);
        if (targetsStr.indexOf("$prev") !== -1) {
            return makeError(
                ErrorCodes.C_INVALID_TOKEN_POSITION,
                "$prev tokens only valid in targets with type:'id', got type:'" + selector.type + "'",
                "compound"
            );
        }
        return { ok: true, op: op };
    }

    // No ids array → pass through
    if (!selector.ids || !selector.ids.length) {
        return { ok: true, op: op };
    }

    // Deep-clone ids array only
    var resolvedIds = [];
    for (var i = 0; i < selector.ids.length; i++) {
        var id = selector.ids[i];

        if (id === "$prev") {
            // Exact match only — no trim, case-sensitive
            if (prevId === null || prevId === undefined) {
                return makeError(
                    ErrorCodes.C_PREV_UNAVAILABLE,
                    "$prev token at index " + i + " but previous op produced no ID",
                    "compound"
                );
            }
            resolvedIds.push(prevId);

        } else if (id === "$prevAll") {
            // Exact match only
            if (!prevAllIds || prevAllIds.length === 0) {
                return makeError(
                    ErrorCodes.C_PREV_UNAVAILABLE,
                    "$prevAll token at index " + i + " but previous op produced no IDs",
                    "compound"
                );
            }
            // Splice in all IDs (preserves ordering)
            for (var j = 0; j < prevAllIds.length; j++) {
                resolvedIds.push(prevAllIds[j]);
            }

        } else if (typeof id === "string" && id.charAt(0) === "$") {
            // Unknown $ token — hard error
            return makeError(
                ErrorCodes.C_UNKNOWN_TOKEN,
                "Unknown token '" + id + "' at index " + i + ". Only $prev and $prevAll are supported.",
                "compound"
            );

        } else {
            // Regular ID — pass through
            resolvedIds.push(id);
        }
    }

    // Return shallow-cloned op with resolved targets
    var resolvedOp = {}, resolvedSelector = {}, key;
    for (key in op) if (Object.prototype.hasOwnProperty.call(op, key)) resolvedOp[key] = op[key];
    for (key in selector) if (Object.prototype.hasOwnProperty.call(selector, key)) resolvedSelector[key] = selector[key];
    resolvedSelector.ids = resolvedIds;
    if (op.targets.target) {
        resolvedOp.targets = {};
        for (key in op.targets) if (Object.prototype.hasOwnProperty.call(op.targets, key)) resolvedOp.targets[key] = op.targets[key];
        resolvedOp.targets.target = resolvedSelector;
    } else resolvedOp.targets = resolvedSelector;
    return { ok: true, op: resolvedOp };
}

// ==================== Compound Handler ====================

registerOpHandler("compound", function (params, targets, ctx) {
    // 1. Guard: no nesting allowed (depth=1 max)
    if (ctx.compoundDepth > 0) {
        return makeError(
            ErrorCodes.C_NESTING_NOT_ALLOWED,
            "Compound ops cannot be nested (current depth: " + ctx.compoundDepth + ")",
            "compound"
        );
    }

    // 2. Validate params.ops is a non-empty array
    if (!params.ops || typeof params.ops.length !== "number" || params.ops.length === 0) {
        return makeError(
            ErrorCodes.V_INVALID_PARAMS,
            "compound requires params.ops as a non-empty array",
            "validate"
        );
    }

    // 2b. T04: `atomic` promised all-or-nothing but was backed by the same
    // property snapshot as batch rollback — it could not undo a deletion, a
    // path edit, a regroup, or a z-order change, and fell back to blind
    // app.executeMenuCommand("undo") calls counted one-per-op when a single
    // handler may perform several DOM mutations.  Rejected before the first
    // sub-op runs, so no partial compound is left behind.
    if (params.atomic) {
        var atomicUnsupported = makeError(
            ErrorCodes.E_UNSUPPORTED_RECOVERY || "E002",
            "compound params.atomic is not supported: the available snapshot " +
            "cannot restore deleted objects, path geometry, text, grouping, " +
            "or z-order, so all-or-nothing cannot be honoured. Rejected " +
            "before execution — no sub-ops ran. Re-run without atomic and " +
            "inspect the per-op results, or take an explicit checkpoint first.",
            "validate",
            null,
            { option: "atomic" }
        );
        atomicUnsupported.recovery = {
            requested: "atomic",
            status: "unsupported",
            scope: "compound sub-operations"
        };
        return atomicUnsupported;
    }

    // 3. Enter compound scope (try/finally ensures reset)
    ctx.compoundDepth = 1;
    try {
        var doc = ctx.doc;
        // T04: atomic is rejected above; sub-ops always run non-atomically and
        // partial effects are reported rather than silently "rolled back".

        // 5. Execute sub-ops sequentially with inline $prev resolution
        //    Token resolution happens DURING execution because $prev depends on
        //    the actual ID returned by the preceding op at runtime.
        var subOps = params.ops;
        var results = [];
        var createdIds = [];
        var passed = 0;
        var failed = 0;
        var undoCount = 0;
        var prevId = null;
        var prevAllIds = [];

        for (var i = 0; i < subOps.length; i++) {
            // Resolve tokens for this op
            var resolved = resolvePrevTokens(subOps[i], prevId, prevAllIds);
            if (!resolved.ok) {
                // Token resolution failed — treat as op failure
                results.push({
                    index: i,
                    task: subOps[i].task || "unknown",
                    ok: false,
                    duration_ms: 0,
                    targets_resolved: 0,
                    id: null,
                    data: null,
                    warnings: [],
                    error: resolved.error
                });
                failed++;
                continue;
            }

            // Execute this single sub-op via executeSubOps
            var singleResult = executeSubOps([resolved.op], ctx, {
                strict: true,  // Always strict within compound (one op at a time)
                rollback: false,  // We handle rollback at compound level
                snapshot: false,
                doc: doc,
                preSnapshot: null,
                trace: null
            });

            var opResult = singleResult.results[0];
            if (opResult) {
                opResult.index = i;  // Re-index relative to compound
                results.push(opResult);

                if (opResult.ok) {
                    passed++;
                    // Track IDs for compound-level createdIds
                    var _ids = opResult.data && (opResult.data.ids || opResult.data.createdIds);
                    if (_ids && typeof _ids.length === "number" && _ids.length > 0) {
                        for (var mi = 0; mi < _ids.length; mi++) createdIds.push(_ids[mi]);
                    } else if (opResult.id) {
                        createdIds.push(opResult.id);
                    }
                    undoCount += singleResult.undoCount;

                    // Update prevId / prevAllIds for next iteration (type-safe)
                    prevId = opResult.id || null;
                    var rawIds = opResult.data && (opResult.data.ids || opResult.data.createdIds);
                    if (typeof rawIds === "string") rawIds = [rawIds];
                    if (rawIds && typeof rawIds.length !== "number") rawIds = null;
                    prevAllIds = rawIds || (prevId ? [prevId] : []);

                } else {
                    failed++;
                    // Reset prev tokens (can't forward an ID from a failed op).
                    // T04: no rollback — completed sub-ops stay applied and are
                    // reported in data.createdIds / data.results so the caller
                    // can see exactly what happened.
                    prevId = null;
                    prevAllIds = [];
                }
            }
        }

        // 6. Build compound result
        var lastId = null;
        for (var li = results.length - 1; li >= 0; li--) {
            if (results[li].ok && results[li].id) {
                lastId = results[li].id;
                break;
            }
        }

        // T04: on partial failure the completed sub-ops remain applied.  Say so
        // instead of implying the compound was undone. This policy record is
        // separate from narrow recovery a child may have attempted itself.
        var compoundRecovery = {
            status: "not_requested",
            scope: "compound sub-operations",
            policy: "non_atomic"
        };
        // Promote child recovery before data.results can be omitted by the
        // response budget. Operation provenance survives the promotion.
        for (var cri = 0; cri < results.length; cri++) {
            var childRecords = results[cri].recovery;
            if (!childRecords) continue;
            if (!(childRecords instanceof Array)) childRecords = [childRecords];
            for (var crj = 0; crj < childRecords.length; crj++) {
                var child = childRecords[crj];
                if (!child || typeof child !== "object") continue;
                var promoted = {};
                for (var crk in child) {
                    if (child.hasOwnProperty(crk)) promoted[crk] = child[crk];
                }
                promoted.operationIndex = results[cri].index;
                promoted.operationTask = results[cri].task;
                compoundRecovery = mcpMergeRecovery(compoundRecovery, promoted);
            }
        }
        return {
            ok: failed === 0,
            id: lastId,
            recovery: compoundRecovery,
            data: {
                lastId: lastId,
                createdIds: createdIds,
                passed: passed,
                failed: failed,
                results: results,
                recovery: { status: "not_requested", scope: null }
            },
            warnings: failed > 0
                ? ["Compound partially applied: " + passed + " sub-op(s) " +
                   "succeeded and remain in the document, " + failed +
                   " failed. No rollback was performed."]
                : []
        };

    } finally {
        // Always reset compound depth — prevents stuck state on exception
        ctx.compoundDepth = 0;
    }
});
