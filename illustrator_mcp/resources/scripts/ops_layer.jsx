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
            return {
                ok: true,
                data: { name: name, existed: true, index: doc.layers[i].zOrderPosition },
                warnings: ["Layer already exists: " + name]
            };
        }
    }

    var layer;
    try {
        layer = doc.layers.add();
        layer.name = name;
    } catch (e) {
        return makeError(ErrorCodes.R_APPLY_FAILED,
            "Failed to create layer '" + name + "': " + e.message, "apply",
            null, { layerCount: doc.layers.length, docName: doc.name });
    }

    // Position relative to another layer (fail loudly if ref not found)
    if (above) {
        var foundAbove = false;
        for (var i = 0; i < doc.layers.length; i++) {
            if (doc.layers[i].name === above) {
                layer.move(doc.layers[i], ElementPlacement.PLACEBEFORE);
                foundAbove = true;
                break;
            }
        }
        if (!foundAbove) {
            return makeError(ErrorCodes.R_APPLY_FAILED,
                "Reference layer not found for 'above': " + above, "apply",
                null, { requested: above, available: _layerNames(doc) });
        }
    } else if (below) {
        var foundBelow = false;
        for (var i = 0; i < doc.layers.length; i++) {
            if (doc.layers[i].name === below) {
                layer.move(doc.layers[i], ElementPlacement.PLACEAFTER);
                foundBelow = true;
                break;
            }
        }
        if (!foundBelow) {
            return makeError(ErrorCodes.R_APPLY_FAILED,
                "Reference layer not found for 'below': " + below, "apply",
                null, { requested: below, available: _layerNames(doc) });
        }
    } else if (placement === "bottom") {
        layer.move(doc.layers[doc.layers.length - 1], ElementPlacement.PLACEAFTER);
    } else if (placement === "top") {
        // Safer top move: use PLACEBEFORE on current topmost layer
        if (doc.layers.length > 1) {
            layer.move(doc.layers[0], ElementPlacement.PLACEBEFORE);
        }
        // else: only layer, already at top — no-op
    }

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

