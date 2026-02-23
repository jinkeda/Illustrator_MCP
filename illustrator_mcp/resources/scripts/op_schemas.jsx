/**
 * op_schemas.jsx - Parameter Schemas for SOC Operations
 * Part of Illustrator MCP SOC Framework
 * 
 * AUTO-GENERATED from contracts.py — DO NOT EDIT MANUALLY
 * To regenerate: python -m scripts.gen_schemas
 */

var OP_PARAM_SCHEMAS = {
    "element_create": {
        "required": [
            "type"
        ],
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
        "required": [
            "geometry"
        ],
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
        "required": [
            "type"
        ],
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
        "required": [
            "irKey"
        ],
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
        "required": [
            "name"
        ],
        "optional": [
            "color",
            "visible",
            "locked"
        ],
        "types": {
            "name": "string",
            "color": "object",
            "visible": "boolean",
            "locked": "boolean"
        }
    },
    "layer_activate": {
        "required": [
            "name"
        ],
        "optional": [],
        "types": {
            "name": "string"
        }
    },
    "layer_lock": {
        "required": [
            "name",
            "locked"
        ],
        "optional": [],
        "types": {
            "name": "string",
            "locked": "boolean"
        }
    },
    "layer_visible": {
        "required": [
            "name",
            "visible"
        ],
        "optional": [],
        "types": {
            "name": "string",
            "visible": "boolean"
        }
    },
    "layer_delete": {
        "required": [
            "name"
        ],
        "optional": [],
        "types": {
            "name": "string"
        }
    },
    "style_set_fill": {
        "required": [
            "r",
            "g",
            "b"
        ],
        "optional": [],
        "types": {
            "r": "number",
            "g": "number",
            "b": "number"
        }
    },
    "style_set_stroke": {
        "required": [],
        "optional": [
            "r",
            "g",
            "b",
            "width"
        ],
        "types": {
            "r": "number",
            "g": "number",
            "b": "number",
            "width": "number"
        }
    },
    "style_set_opacity": {
        "required": [
            "opacity"
        ],
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
        "required": [
            "from"
        ],
        "optional": [
            "properties"
        ],
        "types": {
            "from": "string",
            "properties": "array"
        }
    },
    "style_set_gradient": {
        "required": [
            "type",
            "stops"
        ],
        "optional": [
            "angle",
            "origin",
            "length",
            "name"
        ],
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
        "optional": [
            "name"
        ],
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
        "required": [
            "mask",
            "contents"
        ],
        "optional": [
            "id",
            "name",
            "dryRun"
        ],
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
        "required": [
            "contents"
        ],
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
        "required": [
            "contents"
        ],
        "optional": [],
        "types": {
            "contents": "string"
        }
    },
    "text_set_style": {
        "required": [],
        "optional": [
            "fontSize",
            "fontName",
            "r",
            "g",
            "b"
        ],
        "types": {
            "fontSize": "number",
            "fontName": "string",
            "r": "number",
            "g": "number",
            "b": "number"
        }
    },
    "align_horizontal": {
        "required": [],
        "optional": [
            "mode",
            "reference",
            "key_id",
            "coordinate"
        ],
        "types": {
            "mode": "string",
            "reference": "string",
            "key_id": "string",
            "coordinate": "number"
        },
        "enumValues": {
            "mode": [
                "left",
                "center",
                "right"
            ],
            "reference": [
                "targets",
                "artboard"
            ]
        }
    },
    "align_vertical": {
        "required": [],
        "optional": [
            "mode",
            "reference",
            "key_id",
            "coordinate"
        ],
        "types": {
            "mode": "string",
            "reference": "string",
            "key_id": "string",
            "coordinate": "number"
        },
        "enumValues": {
            "mode": [
                "top",
                "middle",
                "bottom"
            ],
            "reference": [
                "targets",
                "artboard"
            ]
        }
    },
    "distribute_horizontal": {
        "required": [],
        "optional": [
            "mode",
            "spacing"
        ],
        "types": {
            "mode": "string",
            "spacing": "number"
        },
        "enumValues": {
            "mode": [
                "gap",
                "center"
            ]
        }
    },
    "distribute_vertical": {
        "required": [],
        "optional": [
            "mode",
            "spacing"
        ],
        "types": {
            "mode": "string",
            "spacing": "number"
        },
        "enumValues": {
            "mode": [
                "gap",
                "center"
            ]
        }
    },
    "assert_count": {
        "required": [
            "expected"
        ],
        "optional": [
            "operator"
        ],
        "types": {
            "expected": "number",
            "operator": "string"
        },
        "enumValues": {
            "operator": [
                "eq",
                "gte",
                "lte",
                "gt",
                "lt"
            ]
        }
    },
    "assert_bounds": {
        "required": [],
        "optional": [
            "artboardIndex"
        ],
        "types": {
            "artboardIndex": "number"
        }
    },
    "assert_exists": {
        "required": [
            "ids"
        ],
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
        "required": [
            "contents"
        ],
        "optional": [
            "matchMode",
            "caseSensitive"
        ],
        "types": {
            "contents": "string",
            "matchMode": "string",
            "caseSensitive": "boolean"
        },
        "enumValues": {
            "matchMode": [
                "exact",
                "contains",
                "regex"
            ]
        }
    },
    "assert_alignment": {
        "required": [
            "mode"
        ],
        "optional": [
            "tolerance",
            "spacing",
            "repair"
        ],
        "types": {
            "mode": "string",
            "tolerance": "number",
            "spacing": "number",
            "repair": "boolean"
        },
        "enumValues": {
            "mode": [
                "left",
                "centerX",
                "right",
                "top",
                "centerY",
                "bottom"
            ]
        }
    },
    "assert_z_order": {
        "required": [],
        "optional": [
            "above",
            "below",
            "pairs"
        ],
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
        "optional": [
            "includeItems"
        ],
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
        "required": [
            "ops"
        ],
        "optional": [
            "atomic"
        ],
        "types": {
            "ops": "array",
            "atomic": "boolean"
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
                    code: "V003",
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
                var expected = schema.types[key];
                var actual = getValueType(params[key]);
                if (actual !== "null" && actual !== expected) {
                    errors.push({
                        code: "V004",
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
                        code: "V005",
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
