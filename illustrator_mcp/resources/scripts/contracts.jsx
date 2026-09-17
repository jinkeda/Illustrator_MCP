/**
 * contracts.jsx - Compiled Operation Contracts
 * Part of Illustrator MCP SOC Framework
 * 
 * AUTO-GENERATED - DO NOT EDIT MANUALLY
 * Generated: 2026-09-13T09:51:57Z
 * Source: illustrator_mcp/schemas/contracts.py
 * 
 * To regenerate: python -m illustrator_mcp.tools.compile_contracts
 */

var CONTRACTS_CHECKSUM = "996eab5b7f534054";

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
    C_RESPONSE_TRUNCATED: "C010",
    C_RESPONSE_OVERLONG: "C011",
    C_RESPONSE_DIGEST: "C012",
    C_RESPONSE_IDENTITY: "C013",
    C_RESPONSE_DESCRIPTOR: "C014",
    C_PAYLOAD_EXPIRED: "C015",
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
    V_AMBIGUOUS_ID: "V012",
    V_INCOMPLETE_SCAN: "V013",
    V_EMPTY_TARGETS: "V014",
    V_TARGET_COUNT_MISMATCH: "V015",
    V_INVALID_COORDINATE_SPACE: "V016",
    V_CAPTURE_EMPTY_REGION: "V017",
    V_CAPTURE_MINIMUM_BUDGET_EXCEEDED: "V018",
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
    E_UNSUPPORTED_RECOVERY: "E002",
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
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
            "opacity",
            "strokeWidth",
            "noFill",
            "noStroke",
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
            "opacity": "number",
            "strokeWidth": "number",
            "noFill": "boolean",
            "noStroke": "boolean",
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
        "required": [],
        "optional": [
            "x",
            "y",
            "width",
            "height",
            "rotation",
            "scaleX",
            "scaleY",
            "scale",
            "name",
            "fill",
            "stroke",
            "opacity",
            "layer"
        ],
        "types": {
            "x": "number",
            "y": "number",
            "width": "number",
            "height": "number",
            "rotation": "number",
            "scaleX": "number",
            "scaleY": "number",
            "scale": "number",
            "name": "string",
            "fill": "object",
            "stroke": "object",
            "opacity": "number",
            "layer": "string"
        }
    },
    "element_delete": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
        "required": [],
        "optional": [],
        "types": {}
    },
    "element_create_multi": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
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
    "layer_reorder": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": ["name"],
        "optional": ["placement", "above", "below"],
        "types": {
            "name": "string",
            "placement": "string",
            "above": "string",
            "below": "string"
        },
        "enumValues": {
            "placement": ["top", "bottom"]
        }
    },
    "layer_activate": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": ["name"],
        "optional": [],
        "types": {
            "name": "string"
        }
    },
    "layer_lock": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": ["name", "locked"],
        "optional": [],
        "types": {
            "name": "string",
            "locked": "boolean"
        }
    },
    "layer_visible": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": ["name", "visible"],
        "optional": [],
        "types": {
            "name": "string",
            "visible": "boolean"
        }
    },
    "layer_delete": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": ["name"],
        "optional": [],
        "types": {
            "name": "string"
        }
    },
    "layer_list": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": [],
        "optional": [],
        "types": {}
    },
    "style_set_fill": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
        "required": ["opacity"],
        "optional": [],
        "types": {
            "opacity": "number"
        }
    },
    "style_remove_fill": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
        "required": [],
        "optional": [],
        "types": {}
    },
    "style_remove_stroke": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
        "required": [],
        "optional": [],
        "types": {}
    },
    "style_snapshot": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": [],
        "optional": [],
        "types": {}
    },
    "style_clone": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
        "required": ["from"],
        "optional": ["properties"],
        "types": {
            "from": "string",
            "properties": "array"
        }
    },
    "style_set_gradient": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
        "required": [],
        "optional": ["name"],
        "types": {
            "name": "string"
        }
    },
    "group_ungroup": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
        "required": [],
        "optional": [],
        "types": {}
    },
    "clip_create": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
        "required": [],
        "optional": [],
        "types": {}
    },
    "zorder_back": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
        "required": [],
        "optional": [],
        "types": {}
    },
    "zorder_forward": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
        "required": [],
        "optional": [],
        "types": {}
    },
    "zorder_backward": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
        "required": [],
        "optional": [],
        "types": {}
    },
    "text_create": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": [],
        "optional": [
            "contents",
            "runs",
            "id",
            "x",
            "y",
            "layer",
            "name",
            "fontSize",
            "fontName",
            "fontFamily",
            "fontStyle",
            "fill",
            "r",
            "g",
            "b"
        ],
        "types": {
            "contents": "string",
            "runs": "array",
            "id": "string",
            "x": "number",
            "y": "number",
            "layer": "string",
            "name": "string",
            "fontSize": "number",
            "fontName": "string",
            "fontFamily": "string",
            "fontStyle": "string",
            "fill": "object",
            "r": "number",
            "g": "number",
            "b": "number"
        }
    },
    "text_set_content": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
        "required": [],
        "optional": ["contents", "runs"],
        "types": {
            "contents": "string",
            "runs": "array"
        }
    },
    "text_set_style": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
        "required": [],
        "optional": [
            "fontSize",
            "fontName",
            "fontFamily",
            "fontStyle",
            "runs",
            "tracking",
            "fill",
            "r",
            "g",
            "b"
        ],
        "types": {
            "fontSize": "number",
            "fontName": "string",
            "fontFamily": "string",
            "fontStyle": "string",
            "runs": "array",
            "tracking": "number",
            "fill": "object",
            "r": "number",
            "g": "number",
            "b": "number"
        }
    },
    "align_horizontal": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": true,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": [],
        "optional": ["artboardIndex"],
        "types": {
            "artboardIndex": "number"
        }
    },
    "assert_exists": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": ["ids"],
        "optional": [],
        "types": {
            "ids": "array"
        }
    },
    "assert_style": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
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
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": [],
        "optional": ["above", "below", "pairs"],
        "types": {
            "above": "string",
            "below": "string",
            "pairs": "array"
        }
    },
    "assert_layer_order": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": ["order"],
        "optional": ["strict"],
        "types": {
            "order": "array",
            "strict": "boolean"
        }
    },
    "measure_bounds": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": [],
        "optional": [],
        "types": {}
    },
    "snapshot_structure": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": [],
        "optional": ["includeItems"],
        "types": {
            "includeItems": "boolean"
        }
    },
    "hash_structure": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": [],
        "optional": [],
        "types": {}
    },
    "compound": {
        "route": "typed_batch",
        "backend": "jsx",
        "requiresTargets": false,
        "required": ["ops"],
        "optional": ["atomic"],
        "types": {
            "ops": "array",
            "atomic": "boolean"
        }
    },
    "path_boolean": {
        "route": "python_tool",
        "backend": "python",
        "requiresTargets": false,
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

var TARGET_REQUIRED_OP = {
    "element_modify": true,
    "element_delete": true,
    "element_replace": true,
    "style_set_fill": true,
    "style_set_stroke": true,
    "style_set_opacity": true,
    "style_remove_fill": true,
    "style_remove_stroke": true,
    "style_clone": true,
    "style_set_gradient": true,
    "group_create": true,
    "group_ungroup": true,
    "zorder_front": true,
    "zorder_back": true,
    "zorder_forward": true,
    "zorder_backward": true,
    "text_set_content": true,
    "text_set_style": true,
    "align_horizontal": true,
    "align_vertical": true,
    "distribute_horizontal": true,
    "distribute_vertical": true
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
    var errors = [];
    function fail(code, field, message) {
        errors.push({code:code, operation:task, field:field,
            message:task + "." + field + ": " + message, stage:"validate"});
    }
    var schema = Object.prototype.hasOwnProperty.call(OP_PARAM_SCHEMAS, task) ? OP_PARAM_SCHEMAS[task] : null;
    if (!schema || schema.backend !== "jsx") {
        fail("V008", "task", "Expected a supported JSX operation; read illustrator://ops");
        return {ok:false, errors:errors};
    }
    if (params != null && (typeof params !== "object" || params instanceof Array)) {
        fail("V007", "params", "Expected object");
        return {ok:false, errors:errors};
    }
    params = params || {};
    var i, key;
    for (i = 0; i < schema.required.length; i++) {
        key = schema.required[i];
        if (params[key] == null) fail("V006", key, "Missing required parameter");
    }
    var known = [];
    for (key in schema.types) {
        if (Object.prototype.hasOwnProperty.call(schema.types, key)) known.push(key);
    }
    for (key in params) {
        if (!Object.prototype.hasOwnProperty.call(params, key)) continue;
        if (!Object.prototype.hasOwnProperty.call(schema.types, key)) {
            fail("V008", key, "Unknown parameter '" + key + "'. Allowed: " + known.join(", "));
            continue;
        }
        var value = params[key];
        if (value == null || (typeof value === "object" && typeof value.$field === "string")) continue;
        var expected = schema.types[key], actual = getValueType(value);
        if (expected === "object" && value === false) continue;
        if (actual !== expected || (actual === "number" && !isFinite(value))) {
            fail("V007", key, "Expected finite " + expected + ", got " + actual);
        } else if (schema.enumValues && schema.enumValues[key]) {
            var allowed = schema.enumValues[key], found = false;
            for (i = 0; i < allowed.length; i++) if (allowed[i] === value) found = true;
            if (!found) fail("V008", key, "Expected one of: " + allowed.join(", "));
        }
    }
    return {ok:errors.length === 0, errors:errors};
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
