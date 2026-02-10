#!/usr/bin/env python
"""
Generate op_schemas.jsx from Python OpSchema definitions.

This ensures JSX schemas stay synchronized with Python models.
Run: python -m scripts.gen_schemas

Output: resources/scripts/op_schemas_generated.jsx
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

# Schema definitions matching current op_schemas.jsx
# These would ideally be defined in protocol.py as Pydantic models

@dataclass
class OpSchema:
    required: List[str]
    optional: List[str]
    types: Dict[str, str]
    enum_values: Optional[Dict[str, List[str]]] = None


# ==================== Schema Definitions ====================
# These match the current op_schemas.jsx structure

OP_SCHEMAS: Dict[str, OpSchema] = {
    # Element Operations
    "element_create": OpSchema(
        required=["type"],
        optional=["id", "x", "y", "width", "height", "layer", "name", "fill", "stroke",
                  "points", "geometry", "sides", "radius", "outerRadius", "innerRadius",
                  "cornerRadius", "closed", "x2", "y2", "contents", "text", "fontSize", "fontName"],
        types={
            "type": "string", "id": "string", "x": "number", "y": "number",
            "x2": "number", "y2": "number", "width": "number", "height": "number",
            "layer": "string", "name": "string", "fill": "object", "stroke": "object",
            "points": "array", "geometry": "object", "sides": "number", "radius": "number",
            "outerRadius": "number", "innerRadius": "number", "cornerRadius": "number",
            "closed": "boolean", "contents": "string", "text": "string",
            "fontSize": "number", "fontName": "string"
        },
        enum_values={"type": ["rect", "ellipse", "line", "path", "polyline", "polygon", "star", "roundedRect", "text"]}
    ),

    "element_create_multi": OpSchema(
        required=["geometry"],
        optional=["layer", "name", "fill", "stroke"],
        types={
            "geometry": "object", "layer": "string", "name": "string",
            "fill": "object", "stroke": "object"
        }
    ),
    
    "element_modify": OpSchema(
        required=[],
        optional=["x", "y", "width", "height", "rotation", "scaleX", "scaleY", "name"],
        types={
            "x": "number", "y": "number", "width": "number", "height": "number",
            "rotation": "number", "scaleX": "number", "scaleY": "number", "name": "string"
        }
    ),
    
    "element_delete": OpSchema(required=[], optional=[], types={}),
    
    # Layer Operations
    "layer_create": OpSchema(
        required=["name"],
        optional=["color", "visible", "locked"],
        types={"name": "string", "color": "object", "visible": "boolean", "locked": "boolean"}
    ),
    
    "layer_activate": OpSchema(
        required=["name"],
        optional=[],
        types={"name": "string"}
    ),
    
    "layer_lock": OpSchema(
        required=["name", "locked"],
        optional=[],
        types={"name": "string", "locked": "boolean"}
    ),
    
    "layer_visible": OpSchema(
        required=["name", "visible"],
        optional=[],
        types={"name": "string", "visible": "boolean"}
    ),
    
    "layer_delete": OpSchema(
        required=["name"],
        optional=[],
        types={"name": "string"}
    ),
    
    # Style Operations
    "style_set_fill": OpSchema(
        required=["r", "g", "b"],
        optional=[],
        types={"r": "number", "g": "number", "b": "number"}
    ),
    
    "style_set_stroke": OpSchema(
        required=[],
        optional=["r", "g", "b", "width"],
        types={"r": "number", "g": "number", "b": "number", "width": "number"}
    ),
    
    "style_set_opacity": OpSchema(
        required=["opacity"],
        optional=[],
        types={"opacity": "number"}
    ),
    
    "style_remove_fill": OpSchema(required=[], optional=[], types={}),
    "style_remove_stroke": OpSchema(required=[], optional=[], types={}),
    
    # Group Operations
    "group_create": OpSchema(
        required=[],
        optional=["name"],
        types={"name": "string"}
    ),
    
    "group_ungroup": OpSchema(required=[], optional=[], types={}),
    
    # Z-Order Operations
    "zorder_front": OpSchema(required=[], optional=[], types={}),
    "zorder_back": OpSchema(required=[], optional=[], types={}),
    "zorder_forward": OpSchema(required=[], optional=[], types={}),
    "zorder_backward": OpSchema(required=[], optional=[], types={}),
    
    # Text Operations
    "text_create": OpSchema(
        required=["contents"],
        optional=["id", "x", "y", "fontSize", "fontName", "r", "g", "b"],
        types={
            "contents": "string", "id": "string", "x": "number", "y": "number",
            "fontSize": "number", "fontName": "string",
            "r": "number", "g": "number", "b": "number"
        }
    ),
    
    "text_set_content": OpSchema(
        required=["contents"],
        optional=[],
        types={"contents": "string"}
    ),
    
    "text_set_style": OpSchema(
        required=[],
        optional=["fontSize", "fontName", "r", "g", "b"],
        types={
            "fontSize": "number", "fontName": "string",
            "r": "number", "g": "number", "b": "number"
        }
    ),
    
    # Align Operations
    "align_horizontal": OpSchema(
        required=["mode"],
        optional=[],
        types={"mode": "string"},
        enum_values={"mode": ["left", "center", "right"]}
    ),
    
    "align_vertical": OpSchema(
        required=["mode"],
        optional=[],
        types={"mode": "string"},
        enum_values={"mode": ["top", "middle", "bottom"]}
    ),
    
    "distribute_horizontal": OpSchema(required=[], optional=[], types={}),
    "distribute_vertical": OpSchema(required=[], optional=[], types={}),
    
    # Measure/Assert Operations
    "assert_count": OpSchema(
        required=["expected"],
        optional=["operator"],
        types={"expected": "number", "operator": "string"},
        enum_values={"operator": ["eq", "gte", "lte", "gt", "lt"]}
    ),
    
    "assert_bounds": OpSchema(
        required=[],
        optional=["artboardIndex"],
        types={"artboardIndex": "number"}
    ),
    
    "assert_exists": OpSchema(
        required=["ids"],
        optional=[],
        types={"ids": "array"}
    ),
    
    "assert_style": OpSchema(
        required=[],
        optional=["fill", "stroke", "strokeWidth", "opacity", "tolerance", "repair"],
        types={
            "fill": "object", "stroke": "object",
            "strokeWidth": "number", "opacity": "number", "tolerance": "number",
            "repair": "boolean"
        }
    ),
    
    "measure_bounds": OpSchema(required=[], optional=[], types={}),
    
    "snapshot_structure": OpSchema(
        required=[],
        optional=["includeItems"],
        types={"includeItems": "boolean"}
    ),
    
    "hash_structure": OpSchema(required=[], optional=[], types={}),

    "assert_text": OpSchema(
        required=["contents"],
        optional=["matchMode", "caseSensitive"],
        types={"contents": "string", "matchMode": "string", "caseSensitive": "boolean"},
        enum_values={"matchMode": ["exact", "contains", "regex"]}
    ),

    "assert_alignment": OpSchema(
        required=["mode"],
        optional=["tolerance", "spacing", "repair"],
        types={"mode": "string", "tolerance": "number", "spacing": "number", "repair": "boolean"},
        enum_values={"mode": ["left", "centerX", "right", "top", "centerY", "bottom"]}
    ),
}


JSX_TEMPLATE = '''/**
 * op_schemas.jsx - Parameter Schemas for SOC Operations
 * Part of Illustrator MCP SOC Framework
 * 
 * AUTO-GENERATED - DO NOT EDIT MANUALLY
 * Generated: {timestamp}
 * Source: scripts/gen_schemas.py
 * 
 * To regenerate: python -m scripts.gen_schemas
 */

var OP_PARAM_SCHEMAS = {schemas_json};

// ==================== Validation Functions ====================

/**
 * Get the type of a value
 */
function getValueType(val) {{
    if (val === null || val === undefined) return "null";
    if (val instanceof Array) return "array";
    return typeof val;
}}

/**
 * Validate operation parameters against schema
 * @param {{string}} task - Operation name
 * @param {{Object}} params - Parameters to validate
 * @returns {{{{ok: boolean, errors: Array}}}}
 */
function validateOpParams(task, params) {{
    var schema = OP_PARAM_SCHEMAS[task];
    if (!schema) {{
        return {{ ok: true, errors: [] }}; // Unknown task - skip validation
    }}

    var errors = [];
    params = params || {{}};

    // Check required parameters
    if (schema.required) {{
        for (var i = 0; i < schema.required.length; i++) {{
            var key = schema.required[i];
            if (params[key] === undefined || params[key] === null) {{
                errors.push({{
                    code: "V003",
                    message: "Missing required parameter: " + key,
                    stage: "validate"
                }});
            }}
        }}
    }}

    // Check parameter types
    if (schema.types) {{
        for (var key in params) {{
            if (params.hasOwnProperty(key) && schema.types[key]) {{
                var expected = schema.types[key];
                var actual = getValueType(params[key]);
                if (actual !== "null" && actual !== expected) {{
                    errors.push({{
                        code: "V004",
                        message: "Parameter '" + key + "' expected " + expected + ", got " + actual,
                        stage: "validate"
                    }});
                }}
            }}
        }}
    }}

    // Check enum values
    if (schema.enumValues) {{
        for (var key in schema.enumValues) {{
            if (params[key] !== undefined) {{
                var allowed = schema.enumValues[key];
                var found = false;
                for (var i = 0; i < allowed.length; i++) {{
                    if (allowed[i] === params[key]) {{ found = true; break; }}
                }}
                if (!found) {{
                    errors.push({{
                        code: "V005",
                        message: "Parameter '" + key + "' must be one of: " + allowed.join(", "),
                        stage: "validate"
                    }});
                }}
            }}
        }}
    }}

    return {{ ok: errors.length === 0, errors: errors }};
}}

/**
 * Get schema for an operation
 */
function getOpSchema(task) {{
    return OP_PARAM_SCHEMAS[task] || null;
}}

/**
 * List all operations with schemas
 */
function listSchemaOps() {{
    var ops = [];
    for (var task in OP_PARAM_SCHEMAS) {{
        if (OP_PARAM_SCHEMAS.hasOwnProperty(task)) {{
            ops.push(task);
        }}
    }}
    return ops;
}}
'''


def schema_to_dict(schema: OpSchema) -> Dict[str, Any]:
    """Convert OpSchema to dictionary for JSON serialization."""
    result = {
        "required": schema.required,
        "optional": schema.optional,
        "types": schema.types
    }
    if schema.enum_values:
        result["enumValues"] = schema.enum_values
    return result


def generate_jsx(output_path: Path = None) -> str:
    """Generate op_schemas.jsx content."""
    
    # Convert schemas to JSON-serializable format
    schemas_dict = {name: schema_to_dict(schema) for name, schema in OP_SCHEMAS.items()}
    
    # Format JSON with proper indentation
    schemas_json = json.dumps(schemas_dict, indent=4)
    
    # Generate JSX content
    jsx_content = JSX_TEMPLATE.format(
        timestamp=datetime.now().isoformat(),
        schemas_json=schemas_json
    )
    
    # Write to file if path provided
    if output_path:
        output_path.write_text(jsx_content, encoding="utf-8")
        print(f"Generated: {output_path}")
    
    return jsx_content


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate op_schemas.jsx from Python definitions")
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path(__file__).parent.parent / "illustrator_mcp" / "resources" / "scripts" / "op_schemas.jsx",
        help="Output file path"
    )
    parser.add_argument(
        "--print", "-p",
        action="store_true",
        dest="print_output",
        help="Print to stdout instead of file"
    )
    
    args = parser.parse_args()
    
    if args.print_output:
        print(generate_jsx())
    else:
        generate_jsx(args.output)
        print(f"Schema generation complete: {args.output}")


if __name__ == "__main__":
    main()
