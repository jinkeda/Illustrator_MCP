"""
Schema Generator for Illustrator MCP Task Protocol v2.3.

Generates JSON Schema files from Pydantic models for:
- External validation (e.g., in skill files)
- Documentation
- IDE autocompletion

Usage:
    python -m illustrator_mcp.schemas.schema_generator
"""

import json
from pathlib import Path

# Import models from protocol
from illustrator_mcp.protocol import (
    TaskPayload,
    TaskReport,
    TargetSelector,
    TaskOptions,
    ItemRef,
    ErrorCode,
)

SCHEMA_DIR = Path(__file__).parent


def generate_schemas():
    """Generate and save JSON schemas from Pydantic models."""
    
    schemas = {
        "task_payload": TaskPayload.model_json_schema(),
        "task_report": TaskReport.model_json_schema(),
        "target_selector": TargetSelector.model_json_schema(),
        "task_options": TaskOptions.model_json_schema(),
        "item_ref": ItemRef.model_json_schema(),
    }
    
    # Add metadata
    for name, schema in schemas.items():
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://illustrator-mcp.local/schemas/{name}.json"
    
    # Write schemas
    for name, schema in schemas.items():
        path = SCHEMA_DIR / f"{name}.schema.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2, ensure_ascii=False)
        print(f"Generated: {path}")
    
    # Generate error codes reference
    error_codes = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://illustrator-mcp.local/schemas/error_codes.json",
        "title": "Error Codes Reference",
        "description": "Standardized error codes for Task Protocol v2.3",
        "type": "string",
        "enum": [e.value for e in ErrorCode],
        "x-categories": {
            "validation": [e.value for e in ErrorCode if e.value.startswith("V")],
            "runtime": [e.value for e in ErrorCode if e.value.startswith("R")],
            "system": [e.value for e in ErrorCode if e.value.startswith("S")],
        }
    }
    
    error_path = SCHEMA_DIR / "error_codes.schema.json"
    with open(error_path, "w", encoding="utf-8") as f:
        json.dump(error_codes, f, indent=2, ensure_ascii=False)
    print(f"Generated: {error_path}")
    
    print(f"\nTotal: {len(schemas) + 1} schemas generated in {SCHEMA_DIR}")


if __name__ == "__main__":
    generate_schemas()
