/**
 * ops_layer.jsx - Layer Operations
 * Part of Illustrator MCP SOC Framework
 * 
 * Provides handlers for:
 * - layer_create: Create a new layer (idempotent)
 * - layer_activate: Make a layer active
 * - layer_lock: Lock/unlock a layer
 * - layer_visible: Show/hide a layer
 * - layer_delete: Delete a layer
 * 
 * @requires ops_core (for registerOpHandler)
 * @version 1.1.0
 */

// ==================== Layer Create (Idempotent) ====================

registerOpHandler("layer_create", function (params, targets, ctx) {
    var doc = ctx.doc;
    var name = params.name;
    var above = params.above || null;
    var below = params.below || null;

    // Validate name
    if (!name || typeof name !== "string" || name.replace(/\s/g, "").length === 0) {
        return {
            ok: false,
            error: makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM,
                "Missing or empty 'name' param for layer_create", "validate",
                null, { layerCount: doc.layers.length, docName: doc.name })
        };
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
        return {
            ok: false,
            error: makeError(ErrorCodes.R_APPLY_FAILED,
                "Failed to create layer '" + name + "': " + e.message, "apply",
                null, { layerCount: doc.layers.length, docName: doc.name })
        };
    }

    // Position relative to another layer
    if (above) {
        for (var i = 0; i < doc.layers.length; i++) {
            if (doc.layers[i].name === above) {
                layer.move(doc.layers[i], ElementPlacement.PLACEBEFORE);
                break;
            }
        }
    } else if (below) {
        for (var i = 0; i < doc.layers.length; i++) {
            if (doc.layers[i].name === below) {
                layer.move(doc.layers[i], ElementPlacement.PLACEAFTER);
                break;
            }
        }
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
        return { ok: false, error: makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "Missing 'name' param", "apply") };
    }

    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === name) {
            doc.activeLayer = doc.layers[i];
            return { ok: true, data: { activatedLayer: name } };
        }
    }

    return { ok: false, error: makeError(ErrorCodes.R_APPLY_FAILED, "Layer not found: " + name, "apply") };
});

// ==================== Layer Lock ====================

registerOpHandler("layer_lock", function (params, targets, ctx) {
    var doc = ctx.doc;
    var name = params.name;
    var locked = params.locked !== false; // Default to true

    if (!name) {
        return { ok: false, error: makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "Missing 'name' param", "apply") };
    }

    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === name) {
            doc.layers[i].locked = locked;
            return { ok: true, data: { layer: name, locked: locked } };
        }
    }

    return { ok: false, error: makeError(ErrorCodes.R_APPLY_FAILED, "Layer not found: " + name, "apply") };
});

// ==================== Layer Visible ====================

registerOpHandler("layer_visible", function (params, targets, ctx) {
    var doc = ctx.doc;
    var name = params.name;
    var visible = params.visible !== false; // Default to true

    if (!name) {
        return { ok: false, error: makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "Missing 'name' param", "apply") };
    }

    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === name) {
            doc.layers[i].visible = visible;
            return { ok: true, data: { layer: name, visible: visible } };
        }
    }

    return { ok: false, error: makeError(ErrorCodes.R_APPLY_FAILED, "Layer not found: " + name, "apply") };
});

// ==================== Layer Delete ====================

registerOpHandler("layer_delete", function (params, targets, ctx) {
    var doc = ctx.doc;
    var name = params.name;

    if (!name) {
        return { ok: false, error: makeError(ErrorCodes.V_MISSING_REQUIRED_PARAM, "Missing 'name' param", "apply") };
    }

    for (var i = 0; i < doc.layers.length; i++) {
        if (doc.layers[i].name === name) {
            try {
                doc.layers[i].remove();
                return { ok: true, data: { deleted: name } };
            } catch (e) {
                return { ok: false, error: makeError(ErrorCodes.R_APPLY_FAILED, "Cannot delete layer: " + e.message, "apply") };
            }
        }
    }

    return { ok: false, error: makeError(ErrorCodes.R_APPLY_FAILED, "Layer not found: " + name, "apply") };
});

