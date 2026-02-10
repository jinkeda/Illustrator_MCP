/**
 * geo_ir.jsx — Geometry Intermediate Representation
 * Part of Illustrator MCP standard library
 *
 * CONTRACT
 *   All geometry data flows through this IR format.
 *   Producers (generative.jsx) create IR; consumers (SOC ops) realize it.
 *   NO function here touches Illustrator objects.
 *
 * COORDINATE CONVENTION
 *   User-space XY: origin = top-left of active artboard,
 *   +X = right, +Y = down. Units are points (1 pt = 1/72 inch).
 *   SOC ops apply the Y-flip to Illustrator doc coords exactly once
 *   via irMapPoints. Generators MUST output in this convention.
 *
 * SCHEMA (v1)
 *   Path:   { v:1, ir:"path",   kind:"polyline", points:[[x,y],...], closed:false, meta:{} }
 *   Multi:  { v:1, ir:"multi",  paths:[pathIR,...], meta:{} }
 *   Points: { v:1, ir:"points", points:[[x,y],...], meta:{} }
 *
 * META RESERVED KEYS (optional, but standardized when present)
 *   seed      {number}  - PRNG seed for reproducibility
 *   threshold {number}  - iso-contour threshold
 *   dx, dy    {number}  - cell size / spacing
 *   algo      {string}  - algorithm name (e.g. "marchingSquares+chainSegments")
 *   ts        {number}  - unix milliseconds timestamp
 *   Callers may add arbitrary keys. Reserved keys may be overwritten
 *   by library wrappers unless explicitly provided by the caller.
 *
 * @version 1.1.0
 */

var GEO_IR_VERSION = 1;
var GEO_IR_TYPES = ["path", "multi", "points"];
var GEO_IR_KINDS = ["polyline"]; // future: "bezier"

// ==================== FACTORIES ====================

/**
 * Create a single path IR.
 * @param {Array<Array<number>>} points - [[x,y], ...]
 * @param {boolean} [closed=false]
 * @param {Object} [meta={}]
 * @returns {Object} Path IR
 */
function irPath(points, closed, meta) {
    return {
        v: GEO_IR_VERSION,
        ir: "path",
        kind: "polyline",
        points: points || [],
        closed: closed === true,
        meta: meta || {}
    };
}

/**
 * Create a multi-path IR from an array of path IRs.
 * @param {Array<Object>} paths - Array of path IRs
 * @param {Object} [meta={}]
 * @returns {Object} Multi IR
 */
function irMulti(paths, meta) {
    return {
        v: GEO_IR_VERSION,
        ir: "multi",
        paths: paths || [],
        meta: meta || {}
    };
}

/**
 * Create a point cloud IR.
 * @param {Array<Array<number>>} points - [[x,y], ...]
 * @param {Object} [meta={}]
 * @returns {Object} Points IR
 */
function irPoints(points, meta) {
    return {
        v: GEO_IR_VERSION,
        ir: "points",
        points: points || [],
        meta: meta || {}
    };
}

// ==================== VALIDATION ====================

/**
 * Check if obj looks like a geometry IR (duck-type check).
 * @param {*} obj
 * @returns {boolean}
 */
function isIR(obj) {
    return obj !== null && typeof obj === "object" && typeof obj.ir === "string";
}

/**
 * Return the ir type string, or null if not IR.
 * @param {*} obj
 * @returns {string|null}
 */
function irType(obj) {
    return isIR(obj) ? obj.ir : null;
}

/**
 * Strict validation of a geometry IR object.
 * @param {*} obj
 * @returns {Object} { ok: boolean, errors: string[] }
 */
function irValidate(obj) {
    var errors = [];

    if (!isIR(obj)) {
        errors.push("Not an IR object (missing 'ir' field)");
        return { ok: false, errors: errors };
    }

    // Check type
    var validType = false;
    for (var i = 0; i < GEO_IR_TYPES.length; i++) {
        if (obj.ir === GEO_IR_TYPES[i]) { validType = true; break; }
    }
    if (!validType) {
        errors.push("Unknown ir type: '" + obj.ir + "'. Expected: " + GEO_IR_TYPES.join(", "));
    }

    // Version check
    if (obj.v !== undefined && obj.v !== GEO_IR_VERSION) {
        errors.push("Unsupported IR version: " + obj.v + ". Expected: " + GEO_IR_VERSION);
    }

    if (obj.ir === "path" || obj.ir === "points") {
        // Validate points array
        if (!obj.points || !(obj.points instanceof Array)) {
            errors.push("'" + obj.ir + "' requires 'points' array");
        } else {
            for (var i = 0; i < obj.points.length; i++) {
                var pt = obj.points[i];
                if (!(pt instanceof Array) || pt.length < 2 ||
                    typeof pt[0] !== "number" || typeof pt[1] !== "number" ||
                    !isFinite(pt[0]) || !isFinite(pt[1])) {
                    errors.push("points[" + i + "] is not a valid [finite, finite] pair");
                    break; // Report first bad point only
                }
            }
        }

        // Path-specific checks
        if (obj.ir === "path") {
            if (obj.closed !== undefined && typeof obj.closed !== "boolean") {
                errors.push("'closed' must be boolean, got: " + typeof obj.closed);
            }
            if (obj.kind !== undefined) {
                var validKind = false;
                for (var i = 0; i < GEO_IR_KINDS.length; i++) {
                    if (obj.kind === GEO_IR_KINDS[i]) { validKind = true; break; }
                }
                if (!validKind) {
                    errors.push("Unknown kind: '" + obj.kind + "'. Expected: " + GEO_IR_KINDS.join(", "));
                }
            }
        }
    } else if (obj.ir === "multi") {
        if (!obj.paths || !(obj.paths instanceof Array)) {
            errors.push("'multi' requires 'paths' array");
        } else if (obj.paths.length === 0) {
            errors.push("'multi' has empty 'paths' array");
        } else {
            for (var i = 0; i < obj.paths.length; i++) {
                var sub = irValidate(obj.paths[i]);
                if (!sub.ok) {
                    for (var j = 0; j < sub.errors.length; j++) {
                        errors.push("paths[" + i + "]: " + sub.errors[j]);
                    }
                    break; // Report first bad sub-path only
                }
            }
        }
    }
    // Normalize meta to {} if missing (#10)
    if (obj.meta === undefined || obj.meta === null) {
        obj.meta = {};
    }

    return { ok: errors.length === 0, errors: errors };
}

// ==================== UTILITIES ====================

/**
 * Flatten any IR to an array of path IRs.
 * - path → [path]
 * - multi → paths array
 * - points → [] (not path-like)
 * @param {Object} obj - IR object
 * @returns {Array<Object>} Array of path IRs
 */
function irFlatten(obj) {
    if (!isIR(obj)) return [];
    if (obj.ir === "path") return [obj];
    if (obj.ir === "multi") return obj.paths || [];
    return [];
}

/**
 * Total point count across all paths in an IR.
 * @param {Object} obj - IR object
 * @returns {number}
 */
function irPointCount(obj) {
    if (!isIR(obj)) return 0;
    if (obj.ir === "path" || obj.ir === "points") {
        return (obj.points || []).length;
    }
    if (obj.ir === "multi") {
        var total = 0;
        var paths = obj.paths || [];
        for (var i = 0; i < paths.length; i++) {
            total += irPointCount(paths[i]);
        }
        return total;
    }
    return 0;
}

/**
 * Deep-map all points through a transform function.
 * Use for Y-flip, scaling, translation, etc.
 * Returns a new IR (does not mutate original).
 *
 * @param {Object} obj - IR object
 * @param {function} fn - fn([x,y]) → [x',y']
 * @returns {Object} New IR with transformed points
 */
function irMapPoints(obj, fn) {
    if (!isIR(obj)) return obj;

    function mapPts(pts) {
        var out = [];
        for (var i = 0; i < pts.length; i++) {
            out.push(fn(pts[i]));
        }
        return out;
    }

    if (obj.ir === "path") {
        return {
            v: obj.v || GEO_IR_VERSION,
            ir: "path",
            kind: obj.kind || "polyline",
            points: mapPts(obj.points || []),
            closed: obj.closed === true,
            meta: obj.meta || {}
        };
    }
    if (obj.ir === "points") {
        return {
            v: obj.v || GEO_IR_VERSION,
            ir: "points",
            points: mapPts(obj.points || []),
            meta: obj.meta || {}
        };
    }
    if (obj.ir === "multi") {
        var newPaths = [];
        var paths = obj.paths || [];
        for (var i = 0; i < paths.length; i++) {
            newPaths.push(irMapPoints(paths[i], fn));
        }
        return {
            v: obj.v || GEO_IR_VERSION,
            ir: "multi",
            paths: newPaths,
            meta: obj.meta || {}
        };
    }
    return obj;
}
