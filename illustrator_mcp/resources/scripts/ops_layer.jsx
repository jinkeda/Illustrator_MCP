/**
 * layer_reorder — move an EXISTING layer within the stack.
 *
 * Separate from layer_create deliberately. Creation is idempotent and returns
 * early when the layer is already there, so it is the wrong place to hang a
 * move: an operation named "create" that silently restacks existing artwork
 * is a surprise, and folding the two together is what produced F13's
 * do-nothing repair.
 *
 * @param {Object} params - {name, placement?: "top"|"bottom", above?, below?}
 */
registerOpHandler("layer_reorder", function (params, targets, ctx) {
    var doc = ctx.doc;
    var name = params.name;
    var placement = params.placement || null;
    var above = params.above || null;
    var below = params.below || null;

    if (!name || typeof name !== "string") {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM,
            "Missing 'name' param for layer_reorder", "validate");
    }
    var given = 0;
    if (placement) given++;
    if (above) given++;
    if (below) given++;
    if (given !== 1) {
        return makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
            "layer_reorder requires exactly one of 'placement', 'above', or " +
            "'below' (got " + given + ")", "validate");
    }
    if (placement && placement !== "top" && placement !== "bottom") {
        return makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
            "Unknown placement value: '" + placement + "', expected 'top' or 'bottom'",
            "validate");
    }

    var layer = null, i;
    for (i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === name) { layer = doc.layers[i]; break; }
    }
    if (!layer) {
        return makeError(ErrorCodes.R_LAYER_NOT_FOUND || ErrorCodes.R_APPLY_FAILED,
            "Layer not found: " + name, "apply",
            null, { requested: name, available: _layerNames(doc) });
    }

    var beforeIndex = layer.zOrderPosition;

    if (placement === "top") {
        layer.zOrder(ZOrderMethod.BRINGTOFRONT);
    } else if (placement === "bottom") {
        layer.zOrder(ZOrderMethod.SENDTOBACK);
    } else {
        var refName = above || below;
        var ref = null;
        for (i = 0; i < doc.layers.length; i++) {
            if (doc.layers[i].name === refName) { ref = doc.layers[i]; break; }
        }
        if (!ref) {
            return makeError(ErrorCodes.R_APPLY_FAILED,
                "Reference layer not found for '" + (above ? "above" : "below") +
                "': " + refName, "apply",
                null, { requested: refName, available: _layerNames(doc) });
        }
        if (ref === layer) {
            return makeError(ErrorCodes.V_INVALID_PARAM_VALUE,
                "A layer cannot be positioned relative to itself: " + name,
                "validate");
        }
        layer.move(ref, above ? ElementPlacement.PLACEBEFORE : ElementPlacement.PLACEAFTER);
    }

    // Verify the move actually happened rather than trusting the call.
    var afterIndex = null;
    for (i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === name) { afterIndex = doc.layers[i].zOrderPosition; break; }
    }

    return {
        ok: true,
        data: {
            name: name,
            movedFrom: beforeIndex,
            movedTo: afterIndex,
            moved: beforeIndex !== afterIndex,
            order: _layerNames(doc)
        }
    };
});

/**
 * ops_layer.jsx - Layer Operations
 * Part of Illustrator MCP SOC Framework
 * 
 * Provides handlers for:
 * - layer_create: Create a new layer (idempotent, with placement control)
 * - layer_activate: Make a layer active
 * - layer_lock: Lock/unlock a layer
 * - layer_visible: Show/hide a layer
 * - layer_delete: Delete a layer
 * - layer_list: List all layers (read-only, debugging)
 * 
 * CONTRACT: doc.layers[0] = topmost layer (UI top → DOM index 0)
 * 
 * @requires ops_core (for registerOpHandler)
 * @version 1.2.0
 */

// ==================== Helpers ====================

function _layerNames(doc) {
    var names = [];
    for (var i = 0; i < doc.layers.length; i++) names.push(doc.layers[i].name);
    return names;
}

// ==================== Layer Create (Idempotent) ====================

registerOpHandler("layer_create", function (params, targets, ctx) {
    var doc = ctx.doc;
    var name = params.name;
    var above = params.above || null;
    var below = params.below || null;
    var placement = params.placement || null;

    // Validate name
    if (!name || typeof name !== "string" || name.replace(/\s/g, "").length === 0) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM,
            "Missing or empty 'name' param for layer_create", "validate",
            null, { layerCount: doc.layers.length, docName: doc.name });
    }

    // Schema-level validation: placement vs above/below mutual exclusivity
    if (placement && (above || below)) {
        return makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
            "'placement' cannot be used with 'above'/'below'", "validate",
            null, { placement: placement, above: above, below: below });
    }

    // Schema-level validation: placement whitelist
    if (placement && placement !== "top" && placement !== "bottom") {
        return makeError(ErrorCodes.V_INVALID_PARAM_TYPE,
            "Unknown placement value: '" + placement + "', expected 'top' or 'bottom'", "validate");
    }

    // Check if layer already exists (idempotent)
    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === name) {
            // The layer exists, so nothing is created — and the positioning
            // arguments below are never reached.
            //
            // They used to be dropped in silence: layer_create with
            // {name: "Background", placement: "bottom"} on an existing layer
            // returned a plain success while the layer stayed exactly where it
            // was. That is why the documented "move the background to the
            // back" repair did nothing (F13). An ignored input must be
            // reported, and reordering has its own operation.
            var ignored = [];
            if (placement) ignored.push("placement");
            if (above) ignored.push("above");
            if (below) ignored.push("below");

            var existingWarnings = ["Layer already exists: " + name];
            if (ignored.length > 0) {
                existingWarnings.push(
                    "Positioning argument(s) ignored because no layer was " +
                    "created: " + ignored.join(", ") +
                    ". Use layer_reorder to move an existing layer.");
            }
            return {
                ok: true,
                data: {
                    name: name, existed: true,
                    index: doc.layers[i].zOrderPosition,
                    positioningApplied: false,
                    ignoredParams: ignored
                },
                warnings: existingWarnings
            };
        }
    }

    // OR05. The catch reported the failure and left the layer: `layers.add()`
    // succeeds, then the rename throws, and an unnamed layer stays in the
    // document while the caller is told nothing was created.
    //
    // Placement is resolved first. A reference layer that does not exist is
    // knowable without creating anything, and the first version of this
    // migration committed straight after the rename — so a missing reference
    // returned an error and kept the layer, which is the same retention in a
    // different place.
    var refLayer = null;
    var refPlacement = null;
    if (above || below) {
        var wanted = above || below;
        for (var ri = 0; ri < doc.layers.length; ri++) {
            if (doc.layers[ri].name === wanted) {
                refLayer = doc.layers[ri];
                break;
            }
        }
        if (!refLayer) {
            // Both messages spelled out rather than assembled: the wording a
            // caller sees should not change as a side effect of moving this
            // lookup earlier, and two existing tests pin these exact strings.
            if (above) {
                return makeError(ErrorCodes.R_APPLY_FAILED,
                    "Reference layer not found for 'above': " + wanted, "apply",
                    null, { requested: wanted, available: _layerNames(doc) });
            }
            return makeError(ErrorCodes.R_APPLY_FAILED,
                "Reference layer not found for 'below': " + wanted, "apply",
                null, { requested: wanted, available: _layerNames(doc) });
        }
        refPlacement = above ? ElementPlacement.PLACEBEFORE
                             : ElementPlacement.PLACEAFTER;
    }

    var layerScope = mcpOwnBegin("layer_create");
    var layer;
    try {
        layer = doc.layers.add();
        mcpOwnAllocate(layerScope, layer, "layer");
        layer.name = name;

        // Placement is part of what was asked for, so it is inside the scope:
        // a move that throws leaves a layer in the wrong place, which is not
        // the layer the caller requested.
        if (refLayer) {
            layer.move(refLayer, refPlacement);
        } else if (placement === "bottom") {
            layer.move(doc.layers[doc.layers.length - 1], ElementPlacement.PLACEAFTER);
        } else if (placement === "top" && doc.layers.length > 1) {
            // Safer top move: use PLACEBEFORE on current topmost layer.
            // A single layer is already at the top — no-op.
            layer.move(doc.layers[0], ElementPlacement.PLACEBEFORE);
        }
    } catch (e) {
        var layerCleanup = mcpOwnCleanup(layerScope);
        var layerDetail = { layerCount: doc.layers.length, docName: doc.name };
        if (!layerCleanup.ok) layerDetail.cleanupFailures = layerCleanup.failed;
        return makeError(ErrorCodes.R_APPLY_FAILED,
            "Failed to create layer '" + name + "': " + e.message, "apply",
            null, layerDetail);
    }
    mcpOwnCommit(layerScope);

    return {
        ok: true,
        data: { name: layer.name, existed: false, index: layer.zOrderPosition }
    };
});

// ==================== Layer Activate ====================

registerOpHandler("layer_activate", function (params, targets, ctx) {
    var doc = ctx.doc;
    var name = params.name;

    if (!name) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "Missing 'name' param", "apply");
    }

    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === name) {
            doc.activeLayer = doc.layers[i];
            return { ok: true, data: { activatedLayer: name } };
        }
    }

    return makeError(ErrorCodes.R_APPLY_FAILED, "Layer not found: " + name, "apply");
});

// ==================== Layer Lock ====================

registerOpHandler("layer_lock", function (params, targets, ctx) {
    var doc = ctx.doc;
    var name = params.name;
    var locked = params.locked !== false; // Default to true

    if (!name) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "Missing 'name' param", "apply");
    }

    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === name) {
            doc.layers[i].locked = locked;
            return { ok: true, data: { layer: name, locked: locked } };
        }
    }

    return makeError(ErrorCodes.R_APPLY_FAILED, "Layer not found: " + name, "apply");
});

// ==================== Layer Visible ====================

registerOpHandler("layer_visible", function (params, targets, ctx) {
    var doc = ctx.doc;
    var name = params.name;
    var visible = params.visible !== false; // Default to true

    if (!name) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "Missing 'name' param", "apply");
    }

    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === name) {
            doc.layers[i].visible = visible;
            return { ok: true, data: { layer: name, visible: visible } };
        }
    }

    return makeError(ErrorCodes.R_APPLY_FAILED, "Layer not found: " + name, "apply");
});

// ==================== Layer Delete ====================

registerOpHandler("layer_delete", function (params, targets, ctx) {
    var doc = ctx.doc;
    var name = params.name;

    if (!name) {
        return makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "Missing 'name' param", "apply");
    }

    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === name) {
            try {
                doc.layers[i].remove();
                return { ok: true, data: { deleted: name } };
            } catch (e) {
                return makeError(ErrorCodes.R_APPLY_FAILED, "Cannot delete layer: " + e.message, "apply");
            }
        }
    }

    return makeError(ErrorCodes.R_APPLY_FAILED, "Layer not found: " + name, "apply");
});

// ==================== Layer List (Read-Only) ====================

/**
 * List all layers with metadata. Read-only debugging complement.
 * Returns layers top-to-bottom (index 0 = topmost).
 */
registerOpHandler("layer_list", function (params, targets, ctx) {
    var doc = ctx.doc;
    var layers = [];
    for (var i = 0; i < doc.layers.length; i++) {
        layers.push({
            name: doc.layers[i].name,
            index: i,
            visible: doc.layers[i].visible,
            locked: doc.layers[i].locked,
            itemCount: doc.layers[i].pageItems.length
        });
    }
    return { ok: true, data: { layers: layers, count: layers.length } };
});

