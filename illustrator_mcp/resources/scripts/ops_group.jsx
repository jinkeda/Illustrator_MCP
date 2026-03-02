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

    // Create group on the layer of the first item
    var targetLayer = targets[0].layer;
    var group = targetLayer.groupItems.add();

    // Move items into group (in reverse to preserve order)
    for (var i = targets.length - 1; i >= 0; i--) {
        try {
            targets[i].move(group, ElementPlacement.PLACEATBEGINNING);
        } catch (e) {
            // Item may already be in a group or locked
        }
    }

    // Assign ID and name (H1 invariant: stamp + register)
    stampMcpId(group, id);
    if (name) group.name = name;

    return {
        ok: true,
        id: id,
        data: { itemCount: group.pageItems.length }
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

    // ── Resolve mask by MCP ID (H2: use heap) ────────────────────
    var maskItem = heapResolve(maskId, doc);

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

    // ── Resolve content items (H2: use heap) ──────────────────────
    var contents = [];
    var missingIds = [];
    for (var cj = 0; cj < contentIds.length; cj++) {
        var found = heapResolve(contentIds[cj], doc);
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
                    ? "group at mask z-position; original above group"
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
    try {
        var group = parent.groupItems.add();
        var groupId = params.id || generateUUID();

        if (duplicateMask) {
            // ── duplicate_mask=true path ───────────────────────────
            // 1. Place group at mask's z-position
            group.move(maskItem, ElementPlacement.PLACEBEFORE);

            // 2. Duplicate mask → invisible clip path
            var dupMask = maskItem.duplicate();
            stripAppearance(dupMask);
            // No MCP ID on duplicate — anonymous clip path
            try { dupMask.note = ""; } catch (e) { }

            // 3. Move duplicate into group as topmost (clip path)
            dupMask.move(group, ElementPlacement.PLACEATBEGINNING);

            // 4. Move content items into group below dupMask
            for (var k = contents.length - 1; k >= 0; k--) {
                contents[k].move(group, ElementPlacement.PLACEATEND);
            }

            // 5. Set clipping properties on duplicate
            group.clipped = true;
            dupMask.clipping = true;

            // 6. Move original mask immediately above the clip group
            maskItem.move(group, ElementPlacement.PLACEBEFORE);

        } else {
            // ── duplicate_mask=false path (original behavior) ─────
            // Position group at mask's z-location (before mask)
            group.move(maskItem, ElementPlacement.PLACEBEFORE);

            // Move mask into group first (topmost = clipping path)
            maskItem.move(group, ElementPlacement.PLACEATBEGINNING);

            // Move content items into group (reverse order preserves stacking)
            for (var k2 = contents.length - 1; k2 >= 0; k2--) {
                contents[k2].move(group, ElementPlacement.PLACEATEND);
            }

            // Set clipping properties
            group.clipped = true;
            maskItem.clipping = true;
        }

        // Assign ID and name (H1 invariant: stamp + register)
        stampMcpId(group, groupId);
        if (params.name) group.name = params.name;

        return {
            ok: true,
            id: groupId,
            data: {
                itemCount: group.pageItems.length,
                maskType: maskType,
                parentType: parentType,
                duplicate_mask_applied: duplicateMask
            }
        };
    } catch (e) {
        return makeError(
            "CLIP_CREATE_FAILED",
            "Failed to create clipping group: " + e.message,
            "apply"
        );
    }
});
