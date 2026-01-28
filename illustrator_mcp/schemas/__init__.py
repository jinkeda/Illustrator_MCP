# Schema package for Illustrator MCP
"""
JSON Schema utilities for Task Protocol validation.

Provides runtime validation against generated JSON schemas.
"""
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

# Schema directory
SCHEMA_DIR = Path(__file__).parent

# Cached schemas
_schema_cache: Dict[str, dict] = {}


def load_schema(name: str) -> dict:
    """
    Load a JSON schema by name.
    
    Args:
        name: Schema name without extension (e.g., 'task_payload')
        
    Returns:
        Parsed JSON schema dict
        
    Raises:
        FileNotFoundError: If schema file doesn't exist
    """
    if name in _schema_cache:
        return _schema_cache[name]
    
    schema_path = SCHEMA_DIR / f"{name}.schema.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema not found: {schema_path}")
    
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema = json.load(f)
    
    _schema_cache[name] = schema
    return schema


def validate_payload(payload: Dict[str, Any]) -> List[str]:
    """
    Validate a task payload against the JSON schema.
    
    Args:
        payload: Task payload dict to validate
        
    Returns:
        List of validation error messages (empty if valid)
    """
    try:
        import jsonschema
    except ImportError:
        # jsonschema is optional - return empty if not installed
        return []
    
    try:
        schema = load_schema("task_payload")
        jsonschema.validate(payload, schema)
        return []
    except jsonschema.ValidationError as e:
        return [str(e.message)]
    except Exception as e:
        return [f"Schema validation error: {e}"]


def validate_report(report: Dict[str, Any]) -> List[str]:
    """
    Validate a task report against the JSON schema.
    
    Args:
        report: Task report dict to validate
        
    Returns:
        List of validation error messages (empty if valid)
    """
    try:
        import jsonschema
    except ImportError:
        return []
    
    try:
        schema = load_schema("task_report")
        jsonschema.validate(report, schema)
        return []
    except jsonschema.ValidationError as e:
        return [str(e.message)]
    except Exception as e:
        return [f"Schema validation error: {e}"]


# Available schemas
AVAILABLE_SCHEMAS = [
    "error_codes",
    "item_ref", 
    "target_selector",
    "task_options",
    "task_payload",
    "task_report",
]
