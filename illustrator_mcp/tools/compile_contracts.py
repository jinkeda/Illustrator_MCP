"""
compile_contracts.py - Compile Python SSOT contracts to ES3 JSX.

Reads contracts.py and emits contracts.jsx with:
- OP_PARAM_SCHEMAS object (same structure as current op_schemas.jsx)
- ErrorCodes object
- RETRYABLE_CODES array
- SHA-256 checksum header for runtime handshake
- Validation functions (getValueType, validateOpParams, etc.)

Usage:
    python -m illustrator_mcp.tools.compile_contracts
    python -m illustrator_mcp.tools.compile_contracts --check  # verify only
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from illustrator_mcp.schemas.contracts import (
    ErrorCode,
    OP_SCHEMAS,
    OpSchema,
)

OUTPUT_PATH = (
    Path(__file__).parent.parent
    / "resources"
    / "scripts"
    / "contracts.jsx"
)


def compute_checksum(schemas_json: str, errors_json: str) -> str:
    """Compute SHA-256 checksum of the contract data."""
    payload = schemas_json + "|" + errors_json
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def schema_to_dict(op: OpSchema) -> dict:
    """Convert OpSchema to the legacy OP_PARAM_SCHEMAS dict format."""
    d = {
        "required": op.required_params,
        "optional": op.optional_params,
        "types": op.types_dict,
    }
    enums = op.enum_values_dict
    if enums:
        d["enumValues"] = enums
    return d


def error_codes_to_dict() -> dict:
    """Convert ErrorCode enum to JSX-compatible dict."""
    result = {}
    for code in ErrorCode:
        if code.name == "retryable":
            continue
        result[code.name] = code.value
    return result


def render_jsx(schemas_dict: dict, errors_dict: dict, checksum: str) -> str:
    """Render the complete contracts.jsx file."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = []
    lines.append("/**")
    lines.append(" * contracts.jsx - Compiled Operation Contracts")
    lines.append(" * Part of Illustrator MCP SOC Framework")
    lines.append(" * ")
    lines.append(" * AUTO-GENERATED - DO NOT EDIT MANUALLY")
    lines.append(f" * Generated: {timestamp}")
    lines.append(" * Source: illustrator_mcp/schemas/contracts.py")
    lines.append(" * ")
    lines.append(" * To regenerate: python -m illustrator_mcp.tools.compile_contracts")
    lines.append(" */")
    lines.append("")

    # Checksum
    lines.append(f'var CONTRACTS_CHECKSUM = "{checksum}";')
    lines.append("")

    # Error codes
    lines.append("// ==================== Error Codes ====================")
    lines.append("")
    lines.append("var ErrorCodes = {")
    error_entries = list(errors_dict.items())
    for i, (name, code) in enumerate(error_entries):
        comma = "," if i < len(error_entries) - 1 else ""
        # Add category comments
        if name.startswith("V_") and (i == 0 or not error_entries[i-1][0].startswith("V_")):
            lines.append("    // === VALIDATION (V) - fail before execution ===")
        elif name.startswith("R_") and (i == 0 or not error_entries[i-1][0].startswith("R_")):
            lines.append("    // === RUNTIME (R) - fail during execution ===")
        elif name.startswith("E_") and (i == 0 or not error_entries[i-1][0].startswith("E_")):
            lines.append("    // === EXECUTION (E) - infrastructure/dependency issues ===")
        elif name.startswith("S_") and (i == 0 or not error_entries[i-1][0].startswith("S_")):
            lines.append("    // === SYSTEM (S) - Illustrator/environment issues ===")
        lines.append(f'    {name}: "{code}"{comma}')
    lines.append("};")
    lines.append("")

    # Retryable codes
    retryable = ErrorCode.retryable()
    retryable_refs = ", ".join(f"ErrorCodes.{c.name}" for c in retryable)
    lines.append(f"var RETRYABLE_CODES = [{retryable_refs}];")
    lines.append("")

    # Op schemas
    lines.append("// ==================== Operation Schemas ====================")
    lines.append("")
    lines.append("var OP_PARAM_SCHEMAS = " + _format_obj(schemas_dict, indent=0) + ";")
    lines.append("")

    # Validation functions
    lines.append("// ==================== Validation Functions ====================")
    lines.append("")
    lines.append(_VALIDATION_FUNCTIONS)
    lines.append("")

    return "\n".join(lines)


def _format_obj(obj, indent=0) -> str:
    """Format a Python dict/list as ES3-compatible JS object literal."""
    pad = "    " * indent
    inner = "    " * (indent + 1)

    if isinstance(obj, dict):
        if not obj:
            return "{}"
        parts = []
        for key, val in obj.items():
            formatted_val = _format_obj(val, indent + 1)
            parts.append(f'{inner}"{key}": {formatted_val}')
        return "{\n" + ",\n".join(parts) + "\n" + pad + "}"

    elif isinstance(obj, list):
        if not obj:
            return "[]"
        if all(isinstance(item, str) for item in obj):
            # Short string array: inline if small enough
            items = ", ".join(f'"{item}"' for item in obj)
            if len(items) < 60:
                return f"[{items}]"
        parts = []
        for item in obj:
            formatted = _format_obj(item, indent + 1)
            parts.append(f"{inner}{formatted}")
        return "[\n" + ",\n".join(parts) + "\n" + pad + "]"

    elif isinstance(obj, str):
        return f'"{obj}"'

    elif isinstance(obj, bool):
        return "true" if obj else "false"

    elif isinstance(obj, (int, float)):
        return str(obj)

    else:
        return json.dumps(obj)


# Validation functions (ES3 compatible) - carried over from op_schemas.jsx
_VALIDATION_FUNCTIONS = """/**
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
}"""


def main():
    check_only = "--check" in sys.argv

    # Build data
    schemas_dict = {}
    for op in OP_SCHEMAS:
        schemas_dict[op.name] = schema_to_dict(op)

    errors_dict = error_codes_to_dict()

    # Compute checksum from canonical JSON
    schemas_json = json.dumps(schemas_dict, sort_keys=True)
    errors_json = json.dumps(errors_dict, sort_keys=True)
    checksum = compute_checksum(schemas_json, errors_json)

    if check_only:
        # Verify existing file matches
        if not OUTPUT_PATH.exists():
            print(f"FAIL: {OUTPUT_PATH} does not exist")
            sys.exit(1)

        existing = OUTPUT_PATH.read_text(encoding="utf-8")
        expected_line = f'var CONTRACTS_CHECKSUM = "{checksum}";'
        if expected_line in existing:
            print(f"OK: Checksum {checksum} matches")
            sys.exit(0)
        else:
            print(f"FAIL: Checksum mismatch. Expected {checksum}")
            print("Run: python -m illustrator_mcp.tools.compile_contracts")
            sys.exit(1)
    else:
        # Generate
        jsx = render_jsx(schemas_dict, errors_dict, checksum)
        OUTPUT_PATH.write_text(jsx, encoding="utf-8")
        print(f"Compiled contracts.jsx ({len(OP_SCHEMAS)} ops, checksum={checksum})")
        print(f"  Output: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
