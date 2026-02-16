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

    // Assign ID and name
    group.note = "@mcp:id=" + id;
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

    // ── Resolve mask by MCP ID ────────────────────────────────────
    var maskItem = null;
    var allItems = doc.pageItems;
    for (var mi = 0; mi < allItems.length; mi++) {
        try {
            if (allItems[mi].note && allItems[mi].note.indexOf("@mcp:id=" + maskId) >= 0) {
                maskItem = allItems[mi];
                break;
            }
        } catch (e) { /* some items may not support .note */ }
    }

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

    // ── Resolve content items ─────────────────────────────────────
    var contents = [];
    var missingIds = [];
    for (var cj = 0; cj < contentIds.length; cj++) {
        var found = null;
        for (var pj = 0; pj < allItems.length; pj++) {
            try {
                if (allItems[pj].note && allItems[pj].note.indexOf("@mcp:id=" + contentIds[cj]) >= 0) {
                    found = allItems[pj];
                    break;
                }
            } catch (e) { }
        }
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
                maskType: maskType,
                maskId: maskId,
                contentCount: contents.length,
                contentIds: contentIds,
                contentTypes: contentTypes,
                parentType: parentType,
                parentName: parentName,
                wouldPlaceAt: "before mask (z-preserving)"
            }
        };
    }

    // ── Create clipping group ─────────────────────────────────────
    try {
        // Create group in mask's parent (preserves context)
        var group = parent.groupItems.add();

        // Position group at mask's z-location (before mask)
        group.move(maskItem, ElementPlacement.PLACEBEFORE);

        // Move mask into group first (topmost = clipping path)
        maskItem.move(group, ElementPlacement.PLACEATBEGINNING);

        // Move content items into group (reverse order preserves stacking)
        for (var k = contents.length - 1; k >= 0; k--) {
            contents[k].move(group, ElementPlacement.PLACEATEND);
        }

        // Set clipping properties
        group.clipped = true;
        maskItem.clipping = true;

        // Assign ID and name
        var groupId = params.id || generateUUID();
        group.note = "@mcp:id=" + groupId;
        if (params.name) group.name = params.name;

        return {
            ok: true,
            id: groupId,
            data: {
                itemCount: group.pageItems.length,
                maskType: maskType,
                parentType: parentType
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
