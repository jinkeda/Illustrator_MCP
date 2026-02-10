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
