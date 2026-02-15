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

    // Tokens are only valid in type:"id" selectors
    if (op.targets.type !== "id") {
        // Scan for accidental token usage in non-id targets
        var targetsStr = JSON.stringify(op.targets);
        if (targetsStr.indexOf("$prev") !== -1) {
            return makeError(
                ErrorCodes.C_INVALID_TOKEN_POSITION,
                "$prev tokens only valid in targets with type:'id', got type:'" + op.targets.type + "'",
                "compound"
            );
        }
        return { ok: true, op: op };
    }

    // No ids array → pass through
    if (!op.targets.ids || !op.targets.ids.length) {
        return { ok: true, op: op };
    }

    // Deep-clone ids array only
    var resolvedIds = [];
    for (var i = 0; i < op.targets.ids.length; i++) {
        var id = op.targets.ids[i];

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
    return {
        ok: true,
        op: {
            task: op.task,
            params: op.params,
            targets: { type: "id", ids: resolvedIds }
        }
    };
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

    // 3. Enter compound scope (try/finally ensures reset)
    ctx.compoundDepth = 1;
    try {
        var doc = ctx.doc;
        var atomic = !!params.atomic;

        // 4. Capture own preSnapshot for atomic rollback (never reverts outer batch ops)
        var compoundSnapshot = null;
        if (atomic && typeof captureSnapshot === "function") {
            try {
                compoundSnapshot = captureSnapshot(doc, { mcpOnly: true, clock: ctx.clock });
            } catch (snapErr) {
                // Snapshot failure is not fatal — rollback will fall back to undo
            }
        }

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
        var rolledBackCount = 0;

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
                if (atomic) {
                    // Atomic mode: rollback on any failure
                    if (compoundSnapshot || createdIds.length > 0) {
                        rolledBackCount = rollbackBatch(doc, compoundSnapshot, createdIds, undoCount, !!compoundSnapshot, null);
                    }
                    break;
                }
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
                    if (atomic) {
                        // Atomic: rollback all compound sub-ops
                        if (compoundSnapshot || createdIds.length > 0) {
                            rolledBackCount = rollbackBatch(doc, compoundSnapshot, createdIds, undoCount, !!compoundSnapshot, null);
                        }
                        break;
                    }
                    // Non-atomic: reset prev tokens (can't forward from failed op)
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

        return {
            ok: failed === 0,
            id: lastId,
            data: {
                lastId: lastId,
                createdIds: createdIds,
                passed: passed,
                failed: failed,
                results: results
            },
            warnings: rolledBackCount > 0 ? ["Compound rolled back " + rolledBackCount + " ops"] : []
        };

    } finally {
        // Always reset compound depth — prevents stuck state on exception
        ctx.compoundDepth = 0;
    }
});
