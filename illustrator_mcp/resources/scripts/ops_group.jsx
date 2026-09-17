/**
 * ops_group.jsx - Group Operations
 * Part of Illustrator MCP SOC Framework
 * 
 * Provides handlers for:
 * - group_create: Create a group from targets
 * - group_ungroup: Ungroup items
 * - zorder_front: Bring to front
 * - zorder_back: Send to back
 * - zorder_forward: Bring forward
 * - zorder_backward: Send backward
 * 
 * @requires ops_core (for registerOpHandler, generateUUID)
 * @version 1.0.0
 */

// ==================== Group Create ====================

registerOpHandler("group_create", function (params, targets, ctx) {
    var doc = ctx.doc;
    var id = params.id || generateUUID();
    var name = params.name || null;

    if (targets.length === 0) {
        return makeError(ErrorCodes.V_NO_SELECTION, "No items to group", "apply");
    }

    // Create group on the layer of the first item.
    //
    // OR05. Nothing cleaned up here. `groupItems.add()` makes an empty group,
    // and both the id stamp and the rename can throw against it, so a failure
    // left an empty unnamed group in the document and the exception escaped
    // the handler. The moves keep their own per-item catch: an item that
    // cannot be moved is an expected outcome, not a failure of the group.
    var groupScope = mcpOwnBegin("group_create");
    var targetLayer = targets[0].layer;
    var group;

    try {
        group = targetLayer.groupItems.add();
        mcpOwnAllocate(groupScope, group, "group");

        // Everything that can fail against the group happens while it is
        // still empty. The first version of this migration moved the targets
        // in first and then stamped, so a rename that threw rolled back a
        // group that by then held the user's artwork — and removing a group
        // removes its children. That deleted originals this operation had
        // only borrowed, which the previous unmigrated code never did.
        stampMcpId(group, id);
        // Recorded as soon as the artwork carries it, and before the rename
        // that can throw. Without this the record held `mcpId: null`, so a
        // group that survived a failed removal was reported as unidentified
        // when it was tagged all along — the round-five defect, in a route
        // migrated after it was supposedly closed.
        mcpOwnIdentify(groupScope, group, id);
        if (name) group.name = name;
    } catch (groupError) {
        var groupCleanup = mcpOwnCleanup(groupScope);
        var groupDetail = {};
        if (!groupCleanup.ok) groupDetail.cleanupFailures = groupCleanup.failed;
        return makeError(ErrorCodes.R_APPLY_FAILED,
            "Failed to create group: " + groupError.message, "apply",
            null, groupDetail);
    }

    // The group is finished as an object, and from here it takes in artwork
    // this operation did not create. A container holding borrowed originals
    // is not ours to remove, so ownership ends before the first move rather
    // than after the last one.
    //
    // Release, not commit: commit hands entries to the parent scope as still
    // owned, so under any enclosing scope an outer rollback would remove this
    // group and take the user's members with it. The standalone case looked
    // right; the nested one was the same deletion one level up.
    mcpOwnRelease(groupScope);

    // Move items into group (in reverse to preserve order). An item that
    // will not move is an expected outcome, not a failure of the group — but
    // it is not a silent one either, because the caller asked for it.
    var declined = 0;
    var moved = 0;
    var movedIds = [];
    var unnamedMoves = 0;
    for (var i = targets.length - 1; i >= 0; i--) {
        // Captured before the move, through the same note-or-handle mechanism
        // the executor's snapshot uses. Reading the note alone lost the
        // identity of untagged artwork, which selection and handle targeting
        // produce routinely — the snapshot issues a handle for it and this
        // handler discarded that, reporting a successful move as no move at
        // all.
        var identity = mcpTargetIdentity(targets[i]);
        try {
            targets[i].move(group, ElementPlacement.PLACEATBEGINNING);
            // Recorded only once the move returned. Deriving this from the
            // requested targets reported members as modified that had refused
            // to move, and reported every member when a failure happened
            // before any move ran. A false identity is worse than a missing
            // one; `complete: false` does not redeem a wrong entry.
            moved++;
            if (identity) {
                movedIds.push(identity);
            } else {
                // It moved, and nothing can name it. Counted, so the account
                // can say it is not exhaustive rather than silently short.
                unnamedMoves++;
            }
        } catch (e) {
            // Item may already be in a group or locked
            declined++;
        }
    }

    return {
        ok: true,
        id: id,
        data: {
            itemCount: group.pageItems.length,
            // Grouping creates one object and reparents others. Reporting
            // only the creation, and calling that account complete, left the
            // change to existing artwork out of the record entirely.
            movedIds: movedIds,
            // Counted independently of recovered identities: a move that
            // succeeded is a move whether or not anything can name what moved.
            moved: moved,
            unnamedMoves: unnamedMoves,
            failed: declined
        }
    };
});

// ==================== Ungroup ====================

registerOpHandler("group_ungroup", function (params, targets, ctx) {
    var ungrouped = 0;
    var warnings = [];

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];

        if (item.typename !== "GroupItem") {
            warnings.push("Item " + i + " is not a group");
            continue;
        }

        try {
            // Move all items out of group to parent
            var parent = item.parent;
            while (item.pageItems.length > 0) {
                item.pageItems[0].move(parent, ElementPlacement.PLACEAFTER);
            }
            item.remove();
            ungrouped++;
        } catch (e) {
            warnings.push("Failed to ungroup item " + i + ": " + e.message);
        }
    }

    return {
        ok: ungrouped > 0 || targets.length === 0,
        data: { ungrouped: ungrouped },
        warnings: warnings
    };
});

// ==================== Z-Order Operations ====================

registerOpHandler("zorder_front", function (params, targets, ctx) {
    var moved = 0;
    for (var i = 0; i < targets.length; i++) {
        try {
            targets[i].zOrder(ZOrderMethod.BRINGTOFRONT);
            moved++;
        } catch (e) { }
    }
    return { ok: true, data: { moved: moved } };
});

registerOpHandler("zorder_back", function (params, targets, ctx) {
    var moved = 0;
    for (var i = 0; i < targets.length; i++) {
        try {
            targets[i].zOrder(ZOrderMethod.SENDTOBACK);
            moved++;
        } catch (e) { }
    }
    return { ok: true, data: { moved: moved } };
});

registerOpHandler("zorder_forward", function (params, targets, ctx) {
    var moved = 0;
    for (var i = 0; i < targets.length; i++) {
        try {
            targets[i].zOrder(ZOrderMethod.BRINGFORWARD);
            moved++;
        } catch (e) { }
    }
    return { ok: true, data: { moved: moved } };
});

registerOpHandler("zorder_backward", function (params, targets, ctx) {
    var moved = 0;
    for (var i = 0; i < targets.length; i++) {
        try {
            targets[i].zOrder(ZOrderMethod.SENDBACKWARD);
            moved++;
        } catch (e) { }
    }
    return { ok: true, data: { moved: moved } };
});

// ==================== Clip Create ====================

registerOpHandler("clip_create", function (params, targets, ctx) {
    var doc = ctx.doc;
    var maskId = params.mask;
    var contentIds = params.contents;
    var dryRun = params.dryRun === true;
    var duplicateMask = params.duplicate_mask !== false;  // default true
    var warnings = [];

    if (!maskId) {
        return makeError(
            ErrorCodes.V_MISSING_REQUIRED_PARAM,
            "clip_create requires 'mask' parameter (MCP ID of clipping path)",
            "validate"
        );
    }
    if (!contentIds || !contentIds.length) {
        return makeError(
            ErrorCodes.V_MISSING_REQUIRED_PARAM,
            "clip_create requires 'contents' parameter (array of MCP IDs)",
            "validate"
        );
    }

    // Guard: mask must not appear in contents
    for (var ci = 0; ci < contentIds.length; ci++) {
        if (contentIds[ci] === maskId) {
            return makeError(
                ErrorCodes.V_INVALID_PARAM_VALUE || "V009",
                "mask ID '" + maskId + "' cannot also appear in contents (would cause self-move)",
                "validate"
            );
        }
    }

    // ── Resolve mask by MCP ID (compat: heap-first + scan-fallback) ──
    var maskItem = resolveIdCompat(maskId, doc);

    if (!maskItem) {
        return makeError(
            ErrorCodes.V_INVALID_PARAM_VALUE || "V009",
            "Mask item not found: '" + maskId + "'",
            "resolve"
        );
    }

    // ── Mask type validation ──────────────────────────────────────
    var maskType = maskItem.typename;
    if (maskType !== "PathItem" && maskType !== "CompoundPathItem") {
        return makeError(
            ErrorCodes.V_INVALID_PARAM_TYPE || "V010",
            "clip_create mask must be PathItem or CompoundPathItem, got " + maskType,
            "validate"
        );
    }

    // ── Resolve content items (compat: heap-first + scan-fallback) ─
    var contents = [];
    var missingIds = [];
    for (var cj = 0; cj < contentIds.length; cj++) {
        var found = resolveIdCompat(contentIds[cj], doc);
        if (found) {
            contents.push(found);
        } else {
            missingIds.push(contentIds[cj]);
        }
    }

    if (missingIds.length > 0) {
        return makeError(
            ErrorCodes.V_INVALID_PARAM_VALUE || "V009",
            "Content items not found: " + missingIds.join(", "),
            "resolve"
        );
    }

    // ── Determine parent (parent-aware placement) ─────────────────
    var parent = maskItem.parent;
    var parentType = parent.typename || "unknown";
    var parentName = parent.name || "";

    // ── Validate: warn if content items are on different parents ──
    for (var pi = 0; pi < contents.length; pi++) {
        try {
            var cParent = contents[pi].parent;
            if (cParent !== parent) {
                warnings.push(
                    "Content item '" + contentIds[pi] + "' is on " +
                    (cParent.typename || "unknown") + " '" +
                    (cParent.name || "<unnamed>") +
                    "' but mask is on " + parentType + " '" +
                    (parentName || "<unnamed>") +
                    "'. Cross-parent clipping may produce unexpected results."
                );
            }
        } catch (pe) { /* parent access may fail for some item types */ }
    }

    // ── dryRun: return plan without mutation ───────────────────────
    if (dryRun) {
        var contentTypes = [];
        for (var dt = 0; dt < contents.length; dt++) {
            contentTypes.push(contents[dt].typename);
        }
        return {
            ok: true,
            dryRun: true,
            data: {
                action: duplicateMask ? "duplicate_mask" : "move_mask",
                maskType: maskType,
                maskId: maskId,
                contentCount: contents.length,
                contentIds: contentIds,
                contentTypes: contentTypes,
                parentType: parentType,
                parentName: parentName,
                duplicate_mask_applied: duplicateMask,
                wouldPlaceAt: duplicateMask
                    ? "group at mask z-position; original below group"
                    : "before mask (z-preserving)"
            }
        };
    }

    // ── Helper: strip fill/stroke from a path (handles CompoundPathItem) ──
    function stripAppearance(item) {
        if (item.typename === "CompoundPathItem") {
            for (var si = 0; si < item.pathItems.length; si++) {
                item.pathItems[si].filled = false;
                item.pathItems[si].stroked = false;
            }
        } else {
            item.filled = false;
            item.stroked = false;
        }
    }

    // ── Create clipping group ─────────────────────────────────────
    // OR05. The catch below reported the failure and removed nothing, so a
    // clip that failed part way left the group — and on the duplicate_mask
    // path a stray copy of the mask — on the page.
    var clipScope = mcpOwnBegin("clip_create");
    //: whether borrowed artwork has entered the group. Past that point a
    //: failure retains a partially assembled clip group, which is a result
    //: the caller has to be told about — not a silent nothing.
    var handedOff = false;
    //: ids of borrowed artwork actually moved into the group, recorded after
    //: each move returns. Derived from the request instead, it would name
    //: originals that never moved — a false account, which `complete: false`
    //: alongside it would not redeem.
    var clipMovedIds = [];
    try {
        var group = parent.groupItems.add();
        mcpOwnAllocate(clipScope, group, "group");
        var groupId = params.id || generateUUID();

        if (duplicateMask) {
            // ── duplicate_mask=true path ───────────────────────────
            // 1. Place group at mask's z-position
            group.move(maskItem, ElementPlacement.PLACEBEFORE);

            // 2. Duplicate mask → invisible clip path
            var dupMask = maskItem.duplicate();
            mcpOwnAllocate(clipScope, dupMask, "clipPath");
            stripAppearance(dupMask);
            // No MCP ID on duplicate — anonymous clip path
            try { dupMask.note = ""; } catch (e) { }

            // 3. Move duplicate into group as topmost (clip path)
            dupMask.move(group, ElementPlacement.PLACEATBEGINNING);

            // 4. Move content items into group below dupMask.
            //
            // Ownership ends here. From this point the group holds the user's
            // own content, and removing it would take that content with it —
            // deleting originals this operation only borrowed. A failure past
            // this line reports a partially assembled clip group instead of
            // rolling one back.
            //
            // Stamped before the record claims the id: `mcpOwnIdentify` was
            // called here while `stampMcpId` ran much later, so a failure on
            // the first borrowed move left a retained group whose record
            // named an id the artwork did not carry.
            stampMcpId(group, groupId);
            mcpOwnIdentify(clipScope, group, groupId);
            mcpOwnRelease(clipScope);
            handedOff = true;
            for (var k = contents.length - 1; k >= 0; k--) {
                contents[k].move(group, ElementPlacement.PLACEATEND);
                clipMovedIds.push(contentIds[k]);
            }

            // 5. Set clipping properties on duplicate
            group.clipped = true;
            dupMask.clipping = true;

            // 6. Move original mask immediately below the clip group
            //    (so clipped content is visible on top of the fill)
            maskItem.move(group, ElementPlacement.PLACEAFTER);
            clipMovedIds.push(maskId);

        } else {
            // ── duplicate_mask=false path (original behavior) ─────
            // Warn if mask has visible styling that will be lost
            var hasFill = false;
            var hasStroke = false;
            try { hasFill = maskItem.filled; } catch (e2) { }
            try { hasStroke = maskItem.stroked; } catch (e3) { }
            if (hasFill || hasStroke) {
                warnings.push(
                    "duplicate_mask=false: mask '" + maskId +
                    "' has visible " +
                    (hasFill && hasStroke ? "fill and stroke" :
                        hasFill ? "fill" : "stroke") +
                    " that will become invisible as clip path. " +
                    "Use duplicate_mask=true to preserve visible boundary."
                );
            }

            // Position group at mask's z-location (before mask)
            group.move(maskItem, ElementPlacement.PLACEBEFORE);

            // Move mask into group first (topmost = clipping path).
            //
            // Ownership ends here on this path too: the mask itself is the
            // user's, so from this line the group holds borrowed artwork and
            // removing it would destroy the original.
            stampMcpId(group, groupId);
            mcpOwnIdentify(clipScope, group, groupId);
            mcpOwnRelease(clipScope);
            handedOff = true;
            maskItem.move(group, ElementPlacement.PLACEATBEGINNING);
            clipMovedIds.push(maskId);

            // Strip @mcp:id from consumed mask — it's now a structural
            // clip path, not a user-visible element. Prevents phantom
            // references in query_items and VLM annotations.
            // NOTE: the mask's original MCP ID is no longer valid after
            // this point. Callers should reference the clip group ID instead.
            try {
                maskItem.note = "";
                heapTombstone(maskId);  // Remove stale heap reference
                warnings.push(
                    "Mask '" + maskId + "' consumed into clip group (ID no longer valid). " +
                    "Use clip group ID '" + groupId + "' to reference this clip."
                );
            } catch (e4) { }

            // Move content items into group (reverse order preserves stacking)
            for (var k2 = contents.length - 1; k2 >= 0; k2--) {
                contents[k2].move(group, ElementPlacement.PLACEATEND);
                clipMovedIds.push(contentIds[k2]);
            }

            // Set clipping properties
            group.clipped = true;
            maskItem.clipping = true;
        }

        // Already stamped at the hand-off above, so that a retained group
        // carries the id its ownership record names.
        if (params.name) group.name = params.name;

        // Ownership already ended at the hand-off above, on both branches.
        // Committing a closed scope is a no-op, and calling it here would
        // read as though the assembly were still ours until the very end.
        return {
            ok: true,
            id: groupId,
            warnings: warnings,
            data: {
                itemCount: group.pageItems.length,
                maskType: maskType,
                parentType: parentType,
                duplicate_mask_applied: duplicateMask,
                movedIds: clipMovedIds
            }
        };
    } catch (e) {
        // A released scope removes nothing, so this is a rollback only while
        // the group is still empty of borrowed artwork. Past the hand-off it
        // reports what was assembled and leaves it alone.
        var clipCleanup = mcpOwnCleanup(clipScope);
        var clipFailure = makeError(
            "CLIP_CREATE_FAILED",
            "Failed to create clipping group: " + e.message,
            "apply"
        );

        if (handedOff) {
            // Nothing was removed, and that is correct — but a caller told
            // only "failed" would not know a clip group is sitting on the
            // page. The reducer reads `data.ids`, so the retained creation is
            // reported there and the account is partial rather than empty.
            clipFailure.data = {
                ids: [groupId],
                movedIds: clipMovedIds,
                retained: true,
                retainedTypename: "GroupItem",
                partialAssembly: true
            };
        }

        // Flat per-object records, which is what the shared reader expects: it
        // reads `mcpId` off each entry. Wrapping them in `{stage, failed}`
        // made two stranded objects count as one unidentified item.
        if (!clipCleanup.ok) {
            mcpSetCleanupFailures(clipFailure, clipCleanup.failed);
        }
        return clipFailure;
    }
});
