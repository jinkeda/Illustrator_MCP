/**
 * field_eval.jsx - Field Evaluator Preprocessing Layer (P3)
 * Part of Illustrator MCP SOC Framework
 *
 * Resolves dynamic parameter values before handlers see them.
 * Fields are declared as {$field: "evaluator_name", ...params} in op params.
 * Evaluated per-target, so handlers remain pure.
 *
 * EXACTLY 4 BUILT-IN EVALUATORS (ceiling — no expansion without review):
 *   index_ratio  - Element index / total → 0–1 float
 *   position     - Target bounds → {x, y}
 *   noise        - Deterministic pseudo-random based on (x, y, seed) → 0–1
 *   lookup       - Map element name/tag to a value
 *
 * @requires ops_core (called from executeOpBatch)
 * @version 1.0.0
 */

// ==================== Evaluator Registry ====================

var FIELD_EVALUATORS = {};

/**
 * Register a field evaluator.
 * @param {string} name - Evaluator name
 * @param {Function} fn - function(fieldParams, context) → resolved value
 */
function registerFieldEvaluator(name, fn) {
    FIELD_EVALUATORS[name] = fn;
}

// ==================== Built-in Evaluators ====================

/**
 * index_ratio: Returns a 0–1 float based on element index within the batch.
 * Usage: {$field: "index_ratio"}
 * Optional: {$field: "index_ratio", min: 0.2, max: 0.8}
 */
registerFieldEvaluator("index_ratio", function (fieldParams, ctx) {
    var ratio = ctx.total > 1 ? ctx.index / (ctx.total - 1) : 0;
    var min = fieldParams.min !== undefined ? fieldParams.min : 0;
    var max = fieldParams.max !== undefined ? fieldParams.max : 1;
    return min + ratio * (max - min);
});

/**
 * position: Returns the target's position as {x, y}.
 * Usage: {$field: "position"}
 * Optional: {$field: "position", component: "x"} → returns just x
 *           {$field: "position", normalize: true} → 0-1 relative to artboard
 */
registerFieldEvaluator("position", function (fieldParams, ctx) {
    var item = ctx.target;
    if (!item) return { x: 0, y: 0 };

    var x = item.left + item.width / 2;
    var y = -(item.top - item.height / 2); // Convert to positive-Y-down

    if (fieldParams.normalize === true && ctx.doc) {
        var ab = ctx.doc.artboards[ctx.doc.artboards.getActiveArtboardIndex()];
        var abRect = ab.artboardRect;
        var abW = abRect[2] - abRect[0];
        var abH = abRect[1] - abRect[3];
        x = (x - abRect[0]) / abW;
        y = (abRect[1] - (item.top - item.height / 2)) / abH;
    }

    if (fieldParams.component === "x") return x;
    if (fieldParams.component === "y") return y;
    return { x: x, y: y };
});

/**
 * noise: Deterministic pseudo-random value based on position and seed.
 * Uses a simple hash function — not cryptographic, but reproducible.
 * Usage: {$field: "noise", seed: 42}
 * Optional: {$field: "noise", seed: 42, min: 0.5, max: 1.0}
 */
registerFieldEvaluator("noise", function (fieldParams, ctx) {
    var item = ctx.target;
    var seed = fieldParams.seed || 0;
    var x = item ? Math.round(item.left) : ctx.index;
    var y = item ? Math.round(item.top) : 0;

    // Simple hash: combine seed, x, y
    var h = seed * 374761393 + x * 668265263 + y * 2654435761;
    h = ((h ^ (h >>> 13)) * 1274126177) >>> 0;
    h = ((h ^ (h >>> 16))) >>> 0;
    var ratio = (h & 0xFFFF) / 0xFFFF; // 0–1

    var min = fieldParams.min !== undefined ? fieldParams.min : 0;
    var max = fieldParams.max !== undefined ? fieldParams.max : 1;
    return min + ratio * (max - min);
});

/**
 * lookup: Map element name or tag to a value from a provided table.
 * Usage: {$field: "lookup", key: "name", map: {"axis_x": 255, "axis_y": 128}}
 * Optional: key can be "name", "tag", or "index"
 *           default: value if key not found in map
 */
registerFieldEvaluator("lookup", function (fieldParams, ctx) {
    var map = fieldParams.map || {};
    var keyType = fieldParams.key || "name";
    var defaultVal = fieldParams["default"]; // "default" is reserved in some engines

    var lookupKey;
    if (keyType === "name") {
        lookupKey = ctx.target ? (ctx.target.name || "") : "";
    } else if (keyType === "tag") {
        lookupKey = ctx.target && ctx.target.note ? ctx.target.note : "";
    } else if (keyType === "index") {
        lookupKey = String(ctx.index);
    } else {
        lookupKey = "";
    }

    if (map.hasOwnProperty(lookupKey)) {
        return map[lookupKey];
    }
    return defaultVal !== undefined ? defaultVal : null;
});

// ==================== Field Resolution ====================

/**
 * Check if a value is a field descriptor.
 * @param {*} val
 * @returns {boolean}
 */
function isField(val) {
    return val !== null && typeof val === "object" &&
        !(val instanceof Array) && val.hasOwnProperty("$field");
}

/**
 * Recursively check if a params object contains any field descriptors.
 * Used by ops_core to decide whether per-target fan-out is needed.
 * @param {*} val
 * @returns {boolean}
 */
function containsFields(val) {
    if (val === null || val === undefined || typeof val !== "object") return false;
    if (isField(val)) return true;
    if (val instanceof Array) {
        for (var i = 0; i < val.length; i++) {
            if (containsFields(val[i])) return true;
        }
        return false;
    }
    for (var key in val) {
        if (val.hasOwnProperty(key) && containsFields(val[key])) return true;
    }
    return false;
}

/**
 * Evaluate a single field descriptor.
 * @param {Object} field - {$field: "name", ...params}
 * @param {Object} evalCtx - {target, index, total, doc}
 * @returns {*} Resolved value
 */
function evaluateField(field, evalCtx) {
    var evaluator = FIELD_EVALUATORS[field.$field];
    if (!evaluator) {
        return field; // Unknown evaluator — pass through unchanged
    }
    return evaluator(field, evalCtx);
}

/**
 * Recursively resolve all field descriptors in a params object.
 * Called per-target so each element gets its own evaluated values.
 *
 * @param {Object} params - Op params (may contain $field descriptors)
 * @param {Object} target - Current Illustrator item
 * @param {number} index - Index of this target in the batch
 * @param {number} total - Total number of targets
 * @param {Object} ctx - Execution context (has doc, clock, etc.)
 * @returns {Object} New params object with fields resolved
 */
function resolveFields(params, target, index, total, ctx) {
    if (params === null || params === undefined) return params;

    // Primitive types pass through
    if (typeof params !== "object") return params;

    // Array: resolve each element
    if (params instanceof Array) {
        var arr = [];
        for (var i = 0; i < params.length; i++) {
            arr.push(resolveFields(params[i], target, index, total, ctx));
        }
        return arr;
    }

    // Field descriptor: evaluate it
    if (isField(params)) {
        var evalCtx = {
            target: target,
            index: index,
            total: total,
            doc: ctx.doc
        };
        return evaluateField(params, evalCtx);
    }

    // Plain object: recurse into each key
    var resolved = {};
    for (var key in params) {
        if (params.hasOwnProperty(key)) {
            resolved[key] = resolveFields(params[key], target, index, total, ctx);
        }
    }
    return resolved;
}
