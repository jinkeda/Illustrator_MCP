/**
 * ownership.jsx — host-local ownership of artwork a scope is still building.
 *
 * No required executor dependency; scope/allocation identities use a local sequence.
 * Optional recovery journal hooks are feature-detected.
 *
 * OR02. Three defects in a row had the same shape: an object was created, then
 * something that can fail ran, and on failure the object survived. A template
 * clone whose positioning threw, a boolean path whose setEntirePath threw, and
 * a compound container whose children were rolled back while the container
 * itself remained. Each was fixed in place, and each fix was followed by a new
 * instance somewhere else.
 *
 * A scope owns what it has made but not yet finished. If the block throws, the
 * scope removes what it owns. If it commits, ownership passes to the parent,
 * or the objects are released as retained work.
 *
 * Two rules this exists to enforce:
 *
 *   Register before anything can throw. Tracking must not depend on an id that
 *   is stamped later, because the window between creation and stamping is
 *   exactly where the failures happened.
 *
 *   Never swallow a cleanup failure. A removal that itself throws is recorded
 *   and reported. A scope that could not finish cleaning says so, because an
 *   abstraction that hides its own failures reproduces the defect it replaces
 *   one level up.
 *
 * This owns DOM objects. The heap owns the identity index, and rolling that
 * back restores the index while leaving the artwork on the page, which is why
 * the two are separate.
 */

/** Record contract version. Persisted consumers arrive in OR11. */
var MCP_OWNERSHIP_RECORD_VERSION = "1.0";

/** Sequence for allocation identities, unique within a host execution. */
var _mcpOwnSeq = 0;

// Shared host-call chronology. A commit describes disposition, not a new
// allocation: later mutation evidence must still supersede that creation.
var _mcpOwnEventSeq = 0;
function mcpOwnNextEvent() { return ++_mcpOwnEventSeq; }

/** Stack of open scopes, innermost last. */
var _mcpOwnStack = [];
var _mcpOwnAllScopes = [];


/**
 * Open a scope. Objects allocated into it are removed if it is cleaned up.
 *
 * @param {string} label - for diagnostics, e.g. "boolean:region[2]"
 * @returns {Object} the scope
 */
function mcpOwnBegin(label) {
    var scope = {
        id: "scope_" + (++_mcpOwnSeq),
        label: label || "",
        // {allocId, item, kind, mcpId, outcome} — outcome is one of
        // "owned", "committed", "removed", "removal_failed".
        entries: [],
        closed: false,
        parent: _mcpOwnStack.length ? _mcpOwnStack[_mcpOwnStack.length - 1] : null
    };
    _mcpOwnStack.push(scope);
    _mcpOwnAllScopes.push(scope);
    return scope;
}

/**
 * Register an object this scope is responsible for until it commits.
 *
 * Call immediately after the object exists and before anything else touches
 * it. `kind` describes how it was made, for the records only.
 *
 * @returns {Object} the same item, so this can wrap a creation expression
 */
function mcpOwnAllocate(scope, item, kind) {
    if (!scope || scope.closed || !item) return item;
    scope.entries.push({
        allocId: "alloc_" + (++_mcpOwnSeq),
        allocationSequence: mcpOwnNextEvent(),
        item: item,
        kind: kind || "unknown",
        mcpId: null,
        outcome: "owned"
    });
    return item;
}

/**
 * Record the MCP id once it has been stamped. Optional: ownership never
 * depends on it, because the id arrives after the risky window.
 */
function mcpOwnIdentify(scope, item, mcpId) {
    if (!scope) return;
    for (var i = 0; i < scope.entries.length; i++) {
        if (scope.entries[i].item === item) {
            scope.entries[i].mcpId = mcpId;
            return;
        }
    }
}

/**
 * Replace owned objects with the container that consumed them.
 *
 * A menu command such as compoundPath absorbs its inputs, so removing them
 * afterwards strips the container and leaves an empty shell. From that point
 * the container is the thing to remove, and its former children are no longer
 * separately owned.
 *
 * Two entry points, one rule. `mcpOwnReplace` is for a container that appears
 * already holding its children — a menu command that consumed the selection —
 * so allocation and absorption happen together. `mcpOwnAbsorb` is for a
 * container created empty and filled afterwards: it has to be registered
 * beside its own creation, or a throw during the filling leaves it owned by
 * nobody, and cleanup removes the children while the empty container stays.
 *
 * @param {Array} consumed - the objects the container absorbed
 */
function mcpOwnAbsorb(scope, consumed, container) {
    if (!scope || scope.closed) return;
    var absorbed = consumed || [];
    for (var i = 0; i < scope.entries.length; i++) {
        var entry = scope.entries[i];
        if (entry.outcome !== "owned") continue;
        for (var c = 0; c < absorbed.length; c++) {
            if (entry.item === absorbed[c]) {
                entry.outcome = "absorbed";
                entry.absorbedBy = container;
                break;
            }
        }
    }
}

/**
 * Resume direct ownership of an object that has left its owned container.
 *
 * A replacement is first built inside an owned sandbox, where the sandbox is
 * the correct rollback unit. Immediately before the finished child moves out,
 * it becomes the rollback unit again. Keeping that transition here prevents a
 * handler from rewriting ownership records by hand.
 *
 * @returns {Object} the same item
 */
function mcpOwnDetach(scope, item, container) {
    if (!scope || scope.closed || !item) return item;
    for (var i = 0; i < scope.entries.length; i++) {
        var entry = scope.entries[i];
        if (entry.item === item && entry.outcome === "absorbed" &&
                (!container || entry.absorbedBy === container)) {
            // Preserve the former container until the host confirms where the
            // item landed. Illustrator may throw either before or after a move;
            // the catch path must distinguish those final states.
            entry.detachedFrom = entry.absorbedBy;
            entry.outcome = "owned";
            entry.absorbedBy = null;
            break;
        }
    }
    return item;
}

/**
 * Reconcile a detach whose host move threw or was followed by another failure.
 *
 * If the item still belongs to its former container, that container is again
 * the rollback unit. If it landed elsewhere, direct ownership stays in force.
 * An unreadable parent is left directly owned: that is the conservative state.
 */
function mcpOwnReconcileDetach(scope, item) {
    if (!scope || scope.closed || !item) return item;
    for (var i = 0; i < scope.entries.length; i++) {
        var entry = scope.entries[i];
        if (entry.item !== item || entry.outcome !== "owned" ||
                !entry.detachedFrom) continue;
        try {
            if (item.parent === entry.detachedFrom) {
                entry.outcome = "absorbed";
                entry.absorbedBy = entry.detachedFrom;
            }
            entry.detachedFrom = null;
        } catch (e) {
            // Unknown containment must not let a container's removal stand in
            // for removing an item that may already have escaped it.
        }
        break;
    }
    return item;
}

function mcpOwnReplace(scope, consumed, container, kind) {
    if (!scope || scope.closed || !container) return container;
    mcpOwnAbsorb(scope, consumed, container);
    return mcpOwnAllocate(scope, container, kind || "container");
}

/**
 * Finish the scope successfully.
 *
 * A nested scope hands its objects to its parent, so an outer failure still
 * cleans them. A root scope releases them as retained work.
 *
 * @returns {Object} {ok, released: [...], records: [...]}
 */
function mcpOwnCommit(scope) {
    if (!scope || scope.closed) {
        return { ok: true, released: [], records: [] };
    }
    _mcpOwnPop(scope);
    scope.closed = true;

    var released = [];
    for (var i = 0; i < scope.entries.length; i++) {
        var entry = scope.entries[i];
        if (entry.outcome !== "owned") continue;
        entry.outcome = "committed";
        released.push(entry);
        if (scope.parent && !scope.parent.closed) {
            entry.transferredTo = scope.parent.id;
            // The parent inherits it, so a later fatal failure still cleans up.
            scope.parent.entries.push({
                allocId: entry.allocId,
                allocationSequence: entry.allocationSequence,
                item: entry.item,
                kind: entry.kind,
                mcpId: entry.mcpId,
                outcome: "owned"
            });
        }
    }
    return {
        ok: true,
        released: _mcpOwnIds(released),
        records: mcpOwnRecords(scope)
    };
}

/**
 * End ownership permanently: no scope, ancestor or otherwise, may remove these.
 *
 * `mcpOwnCommit` is a transfer, not a release — it hands entries to the parent
 * scope as "owned" so an outer failure still cleans nested work. That is right
 * for ordinary creations, and wrong for a container that has taken in artwork
 * the operation did not create: an ancestor rollback would remove the
 * container and destroy the user's originals with it.
 *
 * Using commit as a hand-off looked correct in isolation and was only wrong
 * under a parent scope, which is exactly the shape of bug this project keeps
 * finding. Release is the operation the hand-off actually needed.
 *
 * @returns {Object} {ok, released: [...], records: [...]}
 */
function mcpOwnRelease(scope) {
    if (!scope || scope.closed) {
        return { ok: true, released: [], records: [] };
    }
    _mcpOwnPop(scope);
    scope.closed = true;

    var released = [];
    for (var i = 0; i < scope.entries.length; i++) {
        var entry = scope.entries[i];
        if (entry.outcome !== "owned") continue;
        // Deliberately not pushed to the parent. That is the whole difference.
        entry.outcome = "released";
        released.push(entry);
    }
    return {
        ok: true,
        released: _mcpOwnIds(released),
        records: mcpOwnRecords(scope)
    };
}

/**
 * Remove everything the scope still owns.
 *
 * Every owned object is attempted even if one removal throws, because giving
 * up on the first failure leaves the rest behind. Failures are recorded, not
 * swallowed: `ok` is false when anything could not be removed, and the caller
 * is expected to report that rather than claim a clean rollback.
 *
 * Calling this again on a scope that already failed retries the objects that
 * would not come away, and reports `ok` false while any of them is still
 * there. It used to return `ok: true` on the second call, having skipped
 * every entry that was not still marked "owned" — so a caller that retried
 * cleanup was told the page was clear while the artwork was on it and the
 * records still said "removal_failed". That is the exact failure this file
 * exists to prevent, committed by the file itself.
 *
 * @returns {Object} {ok, removed, failed: [{allocId, mcpId, error}], records}
 */
/**
 * Attempt one entry's removal, record it, and report the object's final state.
 *
 * OR15. This is the only place a removal happens. `mcpOwnCleanup` and
 * `mcpOwnDispose` each had their own copy of the rules — which states are
 * eligible, when to retry, how to count an attempt, what a failure record
 * looks like — and the copies drifted. The retry rule was written into
 * cleanup and, one round later, a new disposal function shipped without it,
 * so a repeated disposal reported success over artwork that was still there.
 *
 * The eligibility rule is here too: an entry is attempted while it is still
 * owned, or when a previous attempt failed and the obstruction may since have
 * cleared. Anything already removed, disposed, committed or absorbed is done.
 *
 * @returns {Object|null} a failure record, or null when the object came away
 *                        or was never eligible
 */
function _mcpOwnRemoveEntry(entry) {
    if (!entry) return null;
    if (entry.outcome !== "owned" && entry.outcome !== "removal_failed") {
        return null;
    }
    // Counted before the call, so a removal that throws counts once, not twice.
    entry.attempts = (entry.attempts || 0) + 1;
    try {
        entry.item.remove();
        entry.outcome = entry.disposing ? "disposed" : "removed";
        entry.removalSequence = mcpOwnNextEvent();
        entry.error = null;
        return null;
    } catch (e) {
        entry.outcome = "removal_failed";
        entry.error = String(e && e.message ? e.message : e);
        return {
            allocId: entry.allocId,
            kind: entry.kind,
            mcpId: entry.mcpId,
            error: entry.error,
            attempts: entry.attempts
        };
    }
}

/** Whether this entry still has an object on the page. */
function _mcpOwnStillThere(entry) {
    return entry.outcome === "owned" || entry.outcome === "removal_failed";
}

/**
 * Report the current state of every automatic removal attempted in a scope.
 *
 * Cleanup and disposal are events, but recovery status is state. A failed
 * removal may be retried, and a later successful retry must supersede the
 * stale failure for this scope without erasing either event from history.
 * Counting only entries with removal attempts also excludes retained work
 * that the scope will commit normally (for example successful template
 * clones beside a temporary master).
 */
function _mcpOwnRecoverySnapshot(scope, action, targetEntry) {
    var removed = 0;
    var remaining = 0;
    var removalAttempts = 0;
    var kinds = [];
    for (var i = 0; i < scope.entries.length; i++) {
        var entry = scope.entries[i];
        if (!entry.attempts) continue;
        removalAttempts += entry.attempts;
        if (entry.outcome === "removed" || entry.outcome === "disposed") {
            removed++;
        } else if (entry.outcome === "removal_failed") {
            remaining++;
        }
        var seenKind = false;
        for (var k = 0; k < kinds.length; k++) {
            if (kinds[k] === entry.kind) seenKind = true;
        }
        if (!seenKind) kinds.push(entry.kind);
    }

    var status = remaining > 0 ?
        (removed > 0 ? "partial" : "failed") :
        (removed > 0 ? "restored" : "not_needed");
    var recovery = {
        status: status,
        scope: "automatic removals in ownership scope '" +
            (scope.label || scope.id) + "'",
        recoveryKind: action === "dispose" ?
            "ownership_disposal" : "ownership_cleanup",
        // Stable machine identity for final-state reduction. The display
        // label is deliberately not used as an identity: labels can repeat.
        scopeKey: "ownership:" + scope.id,
        scopeId: scope.id,
        scopeLabel: scope.label || "",
        attempted: removed + remaining,
        removalAttempts: removalAttempts,
        removed: removed,
        remaining: remaining,
        kinds: kinds
    };
    if (targetEntry) {
        recovery.targetAllocId = targetEntry.allocId;
        recovery.targetKind = targetEntry.kind;
        recovery.targetMcpId = targetEntry.mcpId;
    }
    if (typeof mcpRecoveryRecord === "function") {
        mcpRecoveryRecord(recovery);
    }
    return recovery;
}

function mcpOwnCleanup(scope) {
    if (!scope) return { ok: true, removed: 0, failed: [], records: [] };
    _mcpOwnPop(scope);
    scope.closed = true;

    var removed = 0;
    var failed = [];
    // Reverse order: later allocations may depend on earlier ones.
    for (var i = scope.entries.length - 1; i >= 0; i--) {
        var eligible = _mcpOwnStillThere(scope.entries[i]);
        var failure = _mcpOwnRemoveEntry(scope.entries[i]);
        if (failure) {
            failed.push(failure);
        } else if (eligible) {
            removed++;
        }
    }
    var recovery = _mcpOwnRecoverySnapshot(scope, "cleanup", null);
    return {
        ok: failed.length === 0,
        removed: removed,
        failed: failed,
        records: mcpOwnRecords(scope),
        recovery: recovery
    };
}

/**
 * End one owned object's life now, inside the scope that owns it.
 *
 * For an object whose whole purpose was temporary — a template master that
 * exists only to be duplicated. Removing it by hand and leaving the entry
 * "owned" would make the records claim it was released as retained work,
 * and removing it by hand outside any scope is how a swallowed
 * `catch (ex) { }` came to hide a stranded master in the first place.
 *
 * Failure is reported the same way cleanup reports it, never swallowed, and
 * calling it again on an object that would not come away retries rather than
 * reporting success. That second rule was already established for
 * `mcpOwnCleanup`, and this function shipped without it: a repeated disposal
 * returned `ok: true` while the artwork was still there and its own record
 * still said "removal_failed". Same defect, one function over.
 *
 * @returns {Object} {ok, removed, failed: [{allocId, mcpId, error}]}
 */
function mcpOwnDispose(scope, item) {
    if (!scope || !item) return { ok: true, removed: 0, failed: [] };
    for (var i = 0; i < scope.entries.length; i++) {
        var entry = scope.entries[i];
        if (entry.item !== item) continue;
        // Marks the outcome as "disposed" rather than "removed", so a record
        // still distinguishes an object whose life was meant to end here from
        // one rolled back by a failure.
        entry.disposing = true;
        var eligible = _mcpOwnStillThere(entry);
        if (!eligible) return { ok: true, removed: 0, failed: [] };
        var failure = _mcpOwnRemoveEntry(entry);
        var recovery = _mcpOwnRecoverySnapshot(scope, "dispose", entry);
        if (failure) {
            return {
                ok: false, removed: 0, failed: [failure], recovery: recovery
            };
        }
        return {
            ok: true, removed: eligible ? 1 : 0, failed: [], recovery: recovery
        };
    }
    return { ok: true, removed: 0, failed: [] };
}

/**
 * The scope's records, serialisable and free of native references.
 *
 * DOM objects are deliberately not included: they are valid only inside the
 * host execution that made them, and a durable record carrying one would be a
 * handle that silently stops meaning anything.
 */
function mcpOwnRecords(scope) {
    var out = [];
    if (!scope) return out;
    for (var i = 0; i < scope.entries.length; i++) {
        var entry = scope.entries[i];
        var record = {
            version: MCP_OWNERSHIP_RECORD_VERSION,
            scope: scope.id,
            label: scope.label,
            sequence: i,
            allocId: entry.allocId,
            allocationSequence: entry.allocationSequence,
            kind: entry.kind,
            mcpId: entry.mcpId,
            outcome: entry.outcome
        };
        if (entry.error) record.cleanupError = entry.error;
        if (entry.transferredTo) record.transferredTo = entry.transferredTo;
        if (entry.attempts) record.removalAttempts = entry.attempts;
        if (entry.removalSequence) record.removalSequence = entry.removalSequence;
        out.push(record);
    }
    return out;
}

/** Final host-call snapshot. Native references stay in this execution only. */
function mcpOwnAllRecords() {
    var out = [];
    for (var i = 0; i < _mcpOwnAllScopes.length; i++) {
        var records = mcpOwnRecords(_mcpOwnAllScopes[i]);
        for (var j = 0; j < records.length; j++) out.push(records[j]);
    }
    return out;
}

/** Remove a scope from the open stack, wherever it sits. */
function _mcpOwnPop(scope) {
    for (var i = _mcpOwnStack.length - 1; i >= 0; i--) {
        if (_mcpOwnStack[i] === scope) {
            _mcpOwnStack.splice(i, 1);
            return;
        }
    }
}

function _mcpOwnIds(entries) {
    var ids = [];
    for (var i = 0; i < entries.length; i++) {
        ids.push(entries[i].mcpId || entries[i].allocId);
    }
    return ids;
}

/** Test seam: forget all open scopes. Never called by production paths. */
function mcpOwnReset() {
    _mcpOwnStack = [];
    _mcpOwnAllScopes = [];
    _mcpOwnSeq = 0;
    _mcpOwnEventSeq = 0;
    if (typeof mcpRecoveryReset === "function") mcpRecoveryReset();
}
