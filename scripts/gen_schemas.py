#!/usr/bin/env python
"""
Generate op_schemas.jsx and op_schemas.json from contracts.py SSOT.

This ensures JSX schemas stay synchronized with Python models.
Run: python -m scripts.gen_schemas

Output:
  - resources/scripts/op_schemas.jsx  (runtime — loaded by ExtendScript)
  - resources/scripts/op_schemas.json (canonical — used by staleness test)
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Import from the Single Source of Truth
from illustrator_mcp.schemas.contracts import OP_SCHEMAS


# Ops that are server-side only (Python handler, no JSX handler)
SERVER_SIDE_OPS = {"path_boolean"}


def build_schema_dict() -> Dict[str, Any]:
    """Build canonical JSON-serializable schema dict from contracts.py."""
    schemas = {}
    for op in OP_SCHEMAS:
        if op.name in SERVER_SIDE_OPS:
            continue
        entry: Dict[str, Any] = {
            "required": op.required_params,
            "optional": op.optional_params,
            "types": op.types_dict,
        }
        enums = op.enum_values_dict
        if enums:
            entry["enumValues"] = enums
        schemas[op.name] = entry
    return schemas


JSX_TEMPLATE = '''/**
 * op_schemas.jsx - Parameter Schemas for SOC Operations
 * Part of Illustrator MCP SOC Framework
 * 
 * AUTO-GENERATED from contracts.py — DO NOT EDIT MANUALLY
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


def generate_jsx(schemas_dict: Dict[str, Any]) -> str:
    """Generate op_schemas.jsx content from schema dict."""
    schemas_json = json.dumps(schemas_dict, indent=4)
    return JSX_TEMPLATE.format(schemas_json=schemas_json)


def generate_json(schemas_dict: Dict[str, Any]) -> str:
    """Generate canonical JSON for staleness testing."""
    return json.dumps(schemas_dict, indent=2, sort_keys=True)


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate op_schemas from contracts.py SSOT")
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=Path(__file__).parent.parent / "illustrator_mcp" / "resources" / "scripts",
        help="Output directory for generated files"
    )
    parser.add_argument(
        "--print", "-p",
        action="store_true",
        dest="print_output",
        help="Print to stdout instead of file"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if generated files are up-to-date (exit 1 if stale)"
    )

    args = parser.parse_args()

    schemas = build_schema_dict()

    if args.print_output:
        print(generate_jsx(schemas))
        return

    jsx_path = args.output_dir / "op_schemas.jsx"
    json_path = args.output_dir / "op_schemas.json"

    if args.check:
        # Check staleness
        stale = False
        expected_json = generate_json(schemas)

        if not json_path.exists():
            print(f"STALE: {json_path} does not exist")
            stale = True
        else:
            current_json = json_path.read_text(encoding="utf-8")
            if current_json.strip() != expected_json.strip():
                print(f"STALE: {json_path} differs from contracts.py")
                stale = True
            else:
                print(f"OK: {json_path} is up to date")

        exit(1 if stale else 0)

    # Generate both files
    jsx_content = generate_jsx(schemas)
    json_content = generate_json(schemas)

    jsx_path.write_text(jsx_content, encoding="utf-8")
    json_path.write_text(json_content, encoding="utf-8")

    print(f"Generated: {jsx_path} ({len(schemas)} ops)")
    print(f"Generated: {json_path} (canonical JSON for staleness test)")
    print(f"  Ops: {', '.join(sorted(schemas.keys()))}")
    print(f"  Excluded (server-side): {', '.join(sorted(SERVER_SIDE_OPS))}")


if __name__ == "__main__":
    main()
