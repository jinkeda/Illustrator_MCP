"""
Script templates for common ExtendScript patterns.

Provides reusable wrappers for error handling, document checks, and JSON response formatting.
"""

from typing import Optional


def wrap_script_with_error_handling(script: str, operation_name: str = "operation") -> str:
    """Wrap script with standard error handling and document checks.
    
    Args:
        script: The ExtendScript code to wrap.
        operation_name: Name of the operation for error reporting.
        
    Returns:
        Wrapped script with try/catch and document validation.
    """
    return f"""
(function() {{
    try {{
        if (!app.documents.length) {{
            return JSON.stringify({{
                error: "NO_DOCUMENT: No document is open. Please create or open a document first."
            }});
        }}
        
        var doc = app.activeDocument;
        
        // User script
        {script}
        
        return JSON.stringify({{ result: "success", operation: "{operation_name}" }});
    }} catch (e) {{
        return JSON.stringify({{ 
            error: e.toString(), 
            line: e.line || null,
            operation: "{operation_name}"
        }});
    }}
}})();
"""


def wrap_script_no_document_check(script: str, operation_name: str = "operation") -> str:
    """Wrap script with error handling but without document requirement.
    
    Use for operations that don't require an open document (e.g., create_document).
    
    Args:
        script: The ExtendScript code to wrap.
        operation_name: Name of the operation for error reporting.
        
    Returns:
        Wrapped script with try/catch.
    """
    return f"""
(function() {{
    try {{
        // User script
        {script}
        
        return JSON.stringify({{ result: "success", operation: "{operation_name}" }});
    }} catch (e) {{
        return JSON.stringify({{ 
            error: e.toString(), 
            line: e.line || null,
            operation: "{operation_name}"
        }});
    }}
}})();
"""


def create_json_response_script(data_expression: str) -> str:
    """Create a script that returns a JSON response with data.
    
    Args:
        data_expression: ExtendScript expression that evaluates to the data object.
        
    Returns:
        Script that returns JSON-stringified data.
    """
    return f"""
(function() {{
    try {{
        var data = {data_expression};
        return JSON.stringify(data);
    }} catch (e) {{
        return JSON.stringify({{ error: e.toString() }});
    }}
}})();
"""


def create_selection_check() -> str:
    """Create script fragment that checks for selection.
    
    Returns:
        ExtendScript fragment for selection validation.
    """
    return """
        var sel = doc.selection;
        if (!sel || sel.length === 0) {
            return JSON.stringify({
                error: "NO_SELECTION: No objects are selected. Please select one or more objects."
            });
        }
"""
