/**
 * contracts.jsx - Compiled Operation Contracts
 * Part of Illustrator MCP SOC Framework
 * 
 * AUTO-GENERATED - DO NOT EDIT MANUALLY
 * Generated: 2026-03-03T16:07:50Z
 * Source: illustrator_mcp/schemas/contracts.py
 * 
 * To regenerate: python -m illustrator_mcp.tools.compile_contracts
 */

var CONTRACTS_CHECKSUM = "97bedb603b18094e";

// ==================== Protocol Version ====================
var TASK_PROTOCOL_VERSION = "3.0.0";
var TASK_PROTOCOL_MAJOR_VERSIONS = ["2", "3"];

// ==================== Error Codes ====================

var ErrorCodes = {
    C_DISCONNECTED: "C001",
    C_TIMEOUT: "C002",
    C_BRIDGE_ERROR: "C003",
    C_PROTOCOL: "C004",
    C_JSON_PARSE: "C005",
    C_NESTING_NOT_ALLOWED: "C006",
    C_PREV_UNAVAILABLE: "C007",
    C_INVALID_TOKEN_POSITION: "C008",
    C_UNKNOWN_TOKEN: "C009",
    // === VALIDATION (V) - fail before execution ===
    V_NO_DOCUMENT: "V001",
    V_NO_SELECTION: "V002",
    V_INVALID_PAYLOAD: "V003",
    V_INVALID_TARGETS: "V004",
    V_UNKNOWN_TARGET_TYPE: "V005",
    V_MISSING_REQUIRED_PARAM: "V006",
    V_INVALID_PARAM_TYPE: "V007",
    V_SCHEMA_MISMATCH: "V008",
    V_LIBRARY_NOT_FOUND: "V009",
    V_LIBRARY_CONFLICT: "V010",
    V_INVALID_PARAM_VALUE: "V011",
    // === RUNTIME (R) - fail during execution ===
    R_COLLECT_FAILED: "R001",
    R_COMPUTE_FAILED: "R002",
    R_APPLY_FAILED: "R003",
    R_ITEM_OPERATION_FAILED: "R004",
    R_TIMEOUT: "R005",
    R_OUT_OF_BOUNDS: "R006",
    R_LAYER_NOT_FOUND: "R007",
    R_ELEMENT_NOT_FOUND: "R008",
    R_UNKNOWN: "R009",
    R_INJECTION_FAILED: "R010",
    R_BUSY: "R011",
    R_QUERY_FAILED: "R012",
    R_PREFLIGHT_FAILED: "R013",
    // === EXECUTION (E) - infrastructure/dependency issues ===
    E_EXECUTION: "E001",
    // === SYSTEM (S) - Illustrator/environment issues ===
    S_APP_ERROR: "S001",
    S_SCRIPT_ERROR: "S002",
    S_IO_ERROR: "S003",
    S_MEMORY_ERROR: "S004",
    S_SYNTAX_ERROR: "S005",
    S_REFERENCE_ERROR: "S006",
    S_TYPE_ERROR: "S007",
    S_RANGE_ERROR: "S008",
    S_PERMISSION_DENIED: "S009",
    S_LIBRARY_IO: "S010",
    S_MANIFEST_ERROR: "S011",
    G_UNKNOWN_PROPERTY: "G001",
    G_INVALID_COMPARATOR: "G002",
    G_MALFORMED: "G003",
    SP_MISSING_PREDICATE: "SP001",
    SP_INVALID_RECT: "SP002",
    SP_REF_NOT_FOUND: "SP003",
    SVG_D_TOO_LONG: "SVG001",
    SVG_TOO_MANY_SEGMENTS: "SVG002",
    SVG_TOO_MANY_SUBPATHS: "SVG003",
    SVG_COORD_OVERFLOW: "SVG004",
    SVG_TOO_MANY_TOKENS: "SVG005",
    Q_OCCLUSION_LIKELY: "Q001",
    Q_RENDER_UNIFORM: "Q002",
    Q_BG_LAYER_ON_TOP: "Q003",
    Q_NONNORMAL_BLEND_COVER: "Q004"
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
            "numPoints",
            "cornerRadius",
            "closed",
            "smooth",
            "tension",
            "handles",
            "mirror",
            "mirrorOrigin",
            "x2",
            "y2",
            "contents",
            "text",
            "fontSize",
            "fontName",
            "clipTo"
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
            "numPoints": "number",
            "cornerRadius": "number",
            "closed": "boolean",
            "smooth": "boolean",
            "tension": "number",
            "handles": "array",
            "mirror": "string",
            "mirrorOrigin": "number",
            "x2": "number",
            "y2": "number",
            "contents": "string",
            "text": "string",
            "fontSize": "number",
            "fontName": "string",
            "clipTo": "string"
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
            ],
            "mirror": [
                "mirror_y_bottom",
                "mirror_y_top",
                "mirror_x_right",
                "mirror_x_left"
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
            "numPoints",
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
            "numPoints": "number",
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
            "array",
            "defaultStyle",
            "layer",
            "name"
        ],
        "types": {
            "template": "object",
            "instances": "array",
            "items": "array",
            "array": "object",
            "defaultStyle": "object",
            "layer": "string",
            "name": "string"
        }
    },
    "layer_create": {
        "required": ["name"],
        "optional": ["color", "visible", "locked", "above", "below", "placement"],
        "types": {
            "name": "string",
            "color": "object",
            "visible": "boolean",
            "locked": "boolean",
            "above": "string",
            "below": "string",
            "placement": "string"
        },
        "enumValues": {
            "placement": ["top", "bottom"]
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
    "layer_list": {
        "required": [],
        "optional": [],
        "types": {}
    },
    "style_set_fill": {
        "required": [],
        "optional": ["fill", "r", "g", "b"],
        "types": {
            "fill": "object",
            "r": "number",
            "g": "number",
            "b": "number"
        }
    },
    "style_set_stroke": {
        "required": [],
        "optional": ["stroke", "r", "g", "b", "width"],
        "types": {
            "stroke": "object",
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
        "required": ["stops"],
        "optional": ["type", "angle", "origin", "length", "name"],
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
        "optional": ["id", "name", "dryRun", "duplicate_mask"],
        "types": {
            "mask": "string",
            "contents": "array",
            "id": "string",
            "name": "string",
            "dryRun": "boolean",
            "duplicate_mask": "boolean"
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
            "fill",
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
            "fill": "object",
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
        "optional": ["fontSize", "fontName", "fill", "r", "g", "b"],
        "types": {
            "fontSize": "number",
            "fontName": "string",
            "fill": "object",
            "r": "number",
            "g": "number",
            "b": "number"
        }
    },
    "align_horizontal": {
        "required": [],
        "optional": ["mode", "reference", "key_id", "coordinate"],
        "types": {
            "mode": "string",
            "reference": "string",
            "key_id": "string",
            "coordinate": "number"
        },
        "enumValues": {
            "mode": ["left", "center", "right"],
            "reference": ["targets", "artboard"]
        }
    },
    "align_vertical": {
        "required": [],
        "optional": ["mode", "reference", "key_id", "coordinate"],
        "types": {
            "mode": "string",
            "reference": "string",
            "key_id": "string",
            "coordinate": "number"
        },
        "enumValues": {
            "mode": ["top", "middle", "bottom"],
            "reference": ["targets", "artboard"]
        }
    },
    "distribute_horizontal": {
        "required": [],
        "optional": ["mode", "spacing"],
        "types": {
            "mode": "string",
            "spacing": "number"
        },
        "enumValues": {
            "mode": ["gap", "center"]
        }
    },
    "distribute_vertical": {
        "required": [],
        "optional": ["mode", "spacing"],
        "types": {
            "mode": "string",
            "spacing": "number"
        },
        "enumValues": {
            "mode": ["gap", "center"]
        }
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
    "assert_layer_order": {
        "required": ["order"],
        "optional": ["strict"],
        "types": {
            "order": "array",
            "strict": "boolean"
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
                    // Allow false sentinel for object-typed params (disable pattern)
                    if (expected === "object" && params[key] === false) continue;
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
