/**
 * contracts.jsx - Compiled Operation Contracts
 * Part of Illustrator MCP SOC Framework
 * 
 * AUTO-GENERATED - DO NOT EDIT MANUALLY
 * Generated: 2026-02-20T10:43:58Z
 * Source: illustrator_mcp/schemas/contracts.py
 * 
 * To regenerate: python -m illustrator_mcp.tools.compile_contracts
 */

var CONTRACTS_CHECKSUM = "2512535b676b668d";

// ==================== Error Codes ====================

var ErrorCodes = {
    // === VALIDATION (V) - fail before execution ===
    V_NO_DOCUMENT: "V001",
    V_NO_SELECTION: "V002",
    V_INVALID_PAYLOAD: "V003",
    V_INVALID_TARGETS: "V004",
    V_UNKNOWN_TARGET_TYPE: "V005",
    V_MISSING_REQUIRED_PARAM: "V006",
    V_INVALID_PARAM_TYPE: "V007",
    V_SCHEMA_MISMATCH: "V008",
    V_INVALID_PARAM_VALUE: "V009",
    // === RUNTIME (R) - fail during execution ===
    R_COLLECT_FAILED: "R001",
    R_COMPUTE_FAILED: "R002",
    R_APPLY_FAILED: "R003",
    R_ITEM_OPERATION_FAILED: "R004",
    R_TIMEOUT: "R005",
    R_OUT_OF_BOUNDS: "R006",
    // === EXECUTION (E) - infrastructure/dependency issues ===
    E_EXECUTION: "E001",
    // === SYSTEM (S) - Illustrator/environment issues ===
    S_APP_ERROR: "S001",
    S_SCRIPT_ERROR: "S002",
    S_IO_ERROR: "S003",
    S_MEMORY_ERROR: "S004",
    C_NESTING_NOT_ALLOWED: "C001",
    C_PREV_UNAVAILABLE: "C002",
    C_INVALID_TOKEN_POSITION: "C003",
    C_UNKNOWN_TOKEN: "C004",
    G_UNKNOWN_PROPERTY: "G001",
    G_INVALID_COMPARATOR: "G002",
    G_MALFORMED: "G003",
    SP_MISSING_PREDICATE: "SP01",
    SP_INVALID_RECT: "SP02",
    SP_REF_NOT_FOUND: "SP03"
};

var RETRYABLE_CODES = [ErrorCodes.R_COLLECT_FAILED, ErrorCodes.R_COMPUTE_FAILED];

// ==================== Operation Schemas ====================

var OP_PARAM_SCHEMAS = {
    "element_create": {
        "required": ["type"],
        "optional": [
            "id",
            "x",
            "y",
            "width",
            "height",
            "layer",
            "name",
            "fill",
            "stroke",
            "points",
            "geometry",
            "sides",
            "radius",
            "outerRadius",
            "innerRadius",
            "cornerRadius",
            "closed",
            "x2",
            "y2",
            "contents",
            "text",
            "fontSize",
            "fontName"
        ],
        "types": {
            "type": "string",
            "id": "string",
            "x": "number",
            "y": "number",
            "width": "number",
            "height": "number",
            "layer": "string",
            "name": "string",
            "fill": "object",
            "stroke": "object",
            "points": "array",
            "geometry": "object",
            "sides": "number",
            "radius": "number",
            "outerRadius": "number",
            "innerRadius": "number",
            "cornerRadius": "number",
            "closed": "boolean",
            "x2": "number",
            "y2": "number",
            "contents": "string",
            "text": "string",
            "fontSize": "number",
            "fontName": "string"
        },
        "enumValues": {
            "type": [
                "rect",
                "ellipse",
                "line",
                "path",
                "polyline",
                "polygon",
                "star",
                "roundedRect",
                "text"
            ]
        }
    },
    "element_modify": {
        "required": [],
        "optional": [
            "x",
            "y",
            "width",
            "height",
            "rotation",
            "scaleX",
            "scaleY",
            "name"
        ],
        "types": {
            "x": "number",
            "y": "number",
            "width": "number",
            "height": "number",
            "rotation": "number",
            "scaleX": "number",
            "scaleY": "number",
            "name": "string"
        }
    },
    "element_delete": {
        "required": [],
        "optional": [],
        "types": {}
    },
    "element_create_multi": {
        "required": ["geometry"],
        "optional": [
            "layer",
            "name",
            "fill",
            "stroke",
            "styles",
            "styleScalars",
            "palette",
            "offset",
            "limit"
        ],
        "types": {
            "geometry": "object",
            "layer": "string",
            "name": "string",
            "fill": "object",
            "stroke": "object",
            "styles": "array",
            "styleScalars": "array",
            "palette": "object",
            "offset": "number",
            "limit": "number"
        }
    },
    "element_replace": {
        "required": ["type"],
        "optional": [
            "id",
            "x",
            "y",
            "width",
            "height",
            "name",
            "fill",
            "stroke",
            "points",
            "sides",
            "radius",
            "outerRadius",
            "innerRadius",
            "cornerRadius",
            "closed",
            "x2",
            "y2",
            "contents",
            "text",
            "fontSize",
            "fontName",
            "opacity",
            "inheritPosition"
        ],
        "types": {
            "type": "string",
            "id": "string",
            "x": "number",
            "y": "number",
            "width": "number",
            "height": "number",
            "name": "string",
            "fill": "object",
            "stroke": "object",
            "points": "array",
            "sides": "number",
            "radius": "number",
            "outerRadius": "number",
            "innerRadius": "number",
            "cornerRadius": "number",
            "closed": "boolean",
            "x2": "number",
            "y2": "number",
            "contents": "string",
            "text": "string",
            "fontSize": "number",
            "fontName": "string",
            "opacity": "number",
            "inheritPosition": "boolean"
        },
        "enumValues": {
            "type": [
                "rect",
                "ellipse",
                "line",
                "path",
                "polyline",
                "polygon",
                "star",
                "roundedRect",
                "text"
            ]
        }
    },
    "element_create_multi_by_ref": {
        "required": ["irKey"],
        "optional": [
            "offset",
            "limit",
            "layer",
            "name",
            "fill",
            "stroke",
            "styles",
            "styleScalars",
            "palette"
        ],
        "types": {
            "irKey": "string",
            "offset": "number",
            "limit": "number",
            "layer": "string",
            "name": "string",
            "fill": "object",
            "stroke": "object",
            "styles": "array",
            "styleScalars": "array",
            "palette": "object"
        }
    },
    "element_create_batch": {
        "required": [],
        "optional": [
            "template",
            "instances",
            "items",
            "defaultStyle",
            "layer",
            "name"
        ],
        "types": {
            "template": "object",
            "instances": "array",
            "items": "array",
            "defaultStyle": "object",
            "layer": "string",
            "name": "string"
        }
    },
    "layer_create": {
        "required": ["name"],
        "optional": ["color", "visible", "locked"],
        "types": {
            "name": "string",
            "color": "object",
            "visible": "boolean",
            "locked": "boolean"
        }
    },
    "layer_activate": {
        "required": ["name"],
        "optional": [],
        "types": {
            "name": "string"
        }
    },
    "layer_lock": {
        "required": ["name", "locked"],
        "optional": [],
        "types": {
            "name": "string",
            "locked": "boolean"
        }
    },
    "layer_visible": {
        "required": ["name", "visible"],
        "optional": [],
        "types": {
            "name": "string",
            "visible": "boolean"
        }
    },
    "layer_delete": {
        "required": ["name"],
        "optional": [],
        "types": {
            "name": "string"
        }
    },
    "style_set_fill": {
        "required": ["r", "g", "b"],
        "optional": [],
        "types": {
            "r": "number",
            "g": "number",
            "b": "number"
        }
    },
    "style_set_stroke": {
        "required": [],
        "optional": ["r", "g", "b", "width"],
        "types": {
            "r": "number",
            "g": "number",
            "b": "number",
            "width": "number"
        }
    },
    "style_set_opacity": {
        "required": ["opacity"],
        "optional": [],
        "types": {
            "opacity": "number"
        }
    },
    "style_remove_fill": {
        "required": [],
        "optional": [],
        "types": {}
    },
    "style_remove_stroke": {
        "required": [],
        "optional": [],
        "types": {}
    },
    "style_snapshot": {
        "required": [],
        "optional": [],
        "types": {}
    },
    "style_clone": {
        "required": ["from"],
        "optional": ["properties"],
        "types": {
            "from": "string",
            "properties": "array"
        }
    },
    "style_set_gradient": {
        "required": ["type", "stops"],
        "optional": ["angle", "origin", "length", "name"],
        "types": {
            "type": "string",
            "stops": "array",
            "angle": "number",
            "origin": "object",
            "length": "number",
            "name": "string"
        }
    },
    "group_create": {
        "required": [],
        "optional": ["name"],
        "types": {
            "name": "string"
        }
    },
    "group_ungroup": {
        "required": [],
        "optional": [],
        "types": {}
    },
    "clip_create": {
        "required": ["mask", "contents"],
        "optional": ["id", "name", "dryRun"],
        "types": {
            "mask": "string",
            "contents": "array",
            "id": "string",
            "name": "string",
            "dryRun": "boolean"
        }
    },
    "zorder_front": {
        "required": [],
        "optional": [],
        "types": {}
    },
    "zorder_back": {
        "required": [],
        "optional": [],
        "types": {}
    },
    "zorder_forward": {
        "required": [],
        "optional": [],
        "types": {}
    },
    "zorder_backward": {
        "required": [],
        "optional": [],
        "types": {}
    },
    "text_create": {
        "required": ["contents"],
        "optional": [
            "id",
            "x",
            "y",
            "layer",
            "name",
            "fontSize",
            "fontName",
            "r",
            "g",
            "b"
        ],
        "types": {
            "contents": "string",
            "id": "string",
            "x": "number",
            "y": "number",
            "layer": "string",
            "name": "string",
            "fontSize": "number",
            "fontName": "string",
            "r": "number",
            "g": "number",
            "b": "number"
        }
    },
    "text_set_content": {
        "required": ["contents"],
        "optional": [],
        "types": {
            "contents": "string"
        }
    },
    "text_set_style": {
        "required": [],
        "optional": ["fontSize", "fontName", "r", "g", "b"],
        "types": {
            "fontSize": "number",
            "fontName": "string",
            "r": "number",
            "g": "number",
            "b": "number"
        }
    },
    "align_horizontal": {
        "required": ["mode"],
        "optional": [],
        "types": {
            "mode": "string"
        },
        "enumValues": {
            "mode": ["left", "center", "right"]
        }
    },
    "align_vertical": {
        "required": ["mode"],
        "optional": [],
        "types": {
            "mode": "string"
        },
        "enumValues": {
            "mode": ["top", "middle", "bottom"]
        }
    },
    "distribute_horizontal": {
        "required": [],
        "optional": [],
        "types": {}
    },
    "distribute_vertical": {
        "required": [],
        "optional": [],
        "types": {}
    },
    "assert_count": {
        "required": ["expected"],
        "optional": ["operator"],
        "types": {
            "expected": "number",
            "operator": "string"
        },
        "enumValues": {
            "operator": ["eq", "gte", "lte", "gt", "lt"]
        }
    },
    "assert_bounds": {
        "required": [],
        "optional": ["artboardIndex"],
        "types": {
            "artboardIndex": "number"
        }
    },
    "assert_exists": {
        "required": ["ids"],
        "optional": [],
        "types": {
            "ids": "array"
        }
    },
    "assert_style": {
        "required": [],
        "optional": [
            "fill",
            "stroke",
            "strokeWidth",
            "opacity",
            "tolerance",
            "repair"
        ],
        "types": {
            "fill": "object",
            "stroke": "object",
            "strokeWidth": "number",
            "opacity": "number",
            "tolerance": "number",
            "repair": "boolean"
        }
    },
    "assert_text": {
        "required": ["contents"],
        "optional": ["matchMode", "caseSensitive"],
        "types": {
            "contents": "string",
            "matchMode": "string",
            "caseSensitive": "boolean"
        },
        "enumValues": {
            "matchMode": ["exact", "contains", "regex"]
        }
    },
    "assert_alignment": {
        "required": ["mode"],
        "optional": ["tolerance", "spacing", "repair"],
        "types": {
            "mode": "string",
            "tolerance": "number",
            "spacing": "number",
            "repair": "boolean"
        },
        "enumValues": {
            "mode": ["left", "centerX", "right", "top", "centerY", "bottom"]
        }
    },
    "assert_z_order": {
        "required": [],
        "optional": ["above", "below", "pairs"],
        "types": {
            "above": "string",
            "below": "string",
            "pairs": "array"
        }
    },
    "measure_bounds": {
        "required": [],
        "optional": [],
        "types": {}
    },
    "snapshot_structure": {
        "required": [],
        "optional": ["includeItems"],
        "types": {
            "includeItems": "boolean"
        }
    },
    "hash_structure": {
        "required": [],
        "optional": [],
        "types": {}
    },
    "compound": {
        "required": ["ops"],
        "optional": ["atomic"],
        "types": {
            "ops": "array",
            "atomic": "boolean"
        }
    },
    "path_boolean": {
        "required": ["operation", "subject", "clip"],
        "optional": [
            "flatten_tolerance",
            "max_segments",
            "delete_originals",
            "style",
            "layer",
            "name"
        ],
        "types": {
            "operation": "string",
            "subject": "string",
            "clip": "array",
            "flatten_tolerance": "number",
            "max_segments": "number",
            "delete_originals": "boolean",
            "style": "string",
            "layer": "string",
            "name": "string"
        },
        "enumValues": {
            "operation": ["subtract", "unite", "intersect", "xor"]
        }
    }
};

// ==================== Validation Functions ====================

/**
 * Get the type of a value
 */
function getValueType(val) {
    if (val === null || val === undefined) return "null";
    if (val instanceof Array) return "array";
    return typeof val;
}

/**
 * Validate operation parameters against schema
 * @param {string} task - Operation name
 * @param {Object} params - Parameters to validate
 * @returns {{ok: boolean, errors: Array}}
 */
function validateOpParams(task, params) {
    var schema = OP_PARAM_SCHEMAS[task];
    if (!schema) {
        return { ok: true, errors: [] }; // Unknown task - skip validation
    }

    var errors = [];
    params = params || {};

    // Check required parameters
    if (schema.required) {
        for (var i = 0; i < schema.required.length; i++) {
            var key = schema.required[i];
            if (params[key] === undefined || params[key] === null) {
                errors.push({
                    code: ErrorCodes.V_MISSING_REQUIRED_PARAM || "V006",
                    message: "Missing required parameter: " + key,
                    stage: "validate"
                });
            }
        }
    }

    // Check parameter types
    if (schema.types) {
        for (var key in params) {
            if (params.hasOwnProperty(key) && schema.types[key]) {
                // Skip type check for $field descriptors
                if (typeof isField === "function" && isField(params[key])) continue;
                var expected = schema.types[key];
                var actual = getValueType(params[key]);
                if (actual !== "null" && actual !== expected) {
                    errors.push({
                        code: ErrorCodes.V_INVALID_PARAM_TYPE || "V007",
                        message: "Parameter '" + key + "' expected " + expected + ", got " + actual,
                        stage: "validate"
                    });
                }
            }
        }
    }

    // Check enum values
    if (schema.enumValues) {
        for (var key in schema.enumValues) {
            if (params[key] !== undefined) {
                var allowed = schema.enumValues[key];
                var found = false;
                for (var i = 0; i < allowed.length; i++) {
                    if (allowed[i] === params[key]) { found = true; break; }
                }
                if (!found) {
                    errors.push({
                        code: ErrorCodes.V_SCHEMA_MISMATCH || "V008",
                        message: "Parameter '" + key + "' must be one of: " + allowed.join(", "),
                        stage: "validate"
                    });
                }
            }
        }
    }

    return { ok: errors.length === 0, errors: errors };
}

/**
 * Get schema for an operation
 */
function getOpSchema(task) {
    return OP_PARAM_SCHEMAS[task] || null;
}

/**
 * List all operations with schemas
 */
function listSchemaOps() {
    var ops = [];
    for (var task in OP_PARAM_SCHEMAS) {
        if (OP_PARAM_SCHEMAS.hasOwnProperty(task)) {
            ops.push(task);
        }
    }
    return ops;
}
