"""
Task Protocol Query Tools - Pilot refactor using new Task Protocol.

Demonstrates how to use the task protocol with declarative target selection
for more structured, observable, and debuggable operations.
"""

import json
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response
from illustrator_mcp.tools.execute import inject_libraries


class QueryItemsInput(BaseModel):
    """Input for querying items using declarative target selector."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    target_type: str = Field(
        default="selection",
        description="Target type: 'selection', 'layer', 'all', or 'query'"
    )
    
    layer_name: Optional[str] = Field(
        default=None,
        description="Layer name (required when target_type is 'layer')"
    )
    
    item_type: Optional[str] = Field(
        default=None,
        description="Filter by item type: 'PathItem', 'TextFrame', 'GroupItem', etc."
    )
    
    name_pattern: Optional[str] = Field(
        default=None,
        description="Name pattern to match (supports * wildcard)"
    )
    
    include_trace: bool = Field(
        default=False,
        description="Include execution trace in response"
    )


@mcp.tool(
    name="illustrator_query_items",
    annotations={
        "title": "Query Items (Task Protocol)",
        "readOnlyHint": True,
        "destructiveHint": False
    }
)
async def illustrator_query_items(params: QueryItemsInput) -> str:
    """
    Query items using the Task Protocol with declarative target selection.
    
    This is a pilot tool demonstrating the new Task Protocol architecture:
    - Uses collectTargets() for declarative selection
    - Returns structured TaskReport with timing and stats
    - Supports trace mode for debugging
    
    Target types:
    - 'selection': Current selection (default)
    - 'layer': All items on a specific layer
    - 'all': All items in document
    - 'query': Filter by itemType and/or namePattern
    
    Returns ItemRef for each matched item, enabling stable references.
    """
    
    # Build targets object based on input
    targets: Dict[str, Any] = {"type": params.target_type}
    
    if params.target_type == "layer" and params.layer_name:
        targets["layer"] = params.layer_name
    elif params.target_type == "query":
        if params.item_type:
            targets["itemType"] = params.item_type
        if params.name_pattern:
            targets["pattern"] = params.name_pattern
    
    # Build payload
    payload = {
        "task": "query_items",
        "targets": targets,
        "params": {},
        "options": {
            "dryRun": True,  # Read-only query
            "trace": params.include_trace
        }
    }
    
    payload_json = json.dumps(payload)
    
    script = f"""
// Compute function - gather item info
function compute(items, params, report) {{
    var actions = [];
    for (var i = 0; i < items.length; i++) {{
        var item = items[i];
        var itemRef = describeItemV2(item, {{includeIdentity: true, includeTags: true}});
        actions.push({{
            itemRef: itemRef,
            name: item.name || "(unnamed)",
            type: item.typename,
            bounds: {{
                left: item.left,
                top: item.top,
                width: item.width,
                height: item.height
            }}
        }});
        report.stats.itemsProcessed++;
    }}
    return actions;
}}

// Apply function - no modifications (query only)
function apply(actions, report) {{
    // Store results in artifacts
    report.artifacts = report.artifacts || {{}};
    report.artifacts.items = actions;
}}

// Execute task
var payload = {payload_json};
var report = executeTask(payload, collectTargets, compute, apply);
JSON.stringify(report);
"""
    
    # Inject task_executor library
    try:
        final_script = inject_libraries(script, ["task_executor"])
    except ValueError as e:
        return f"Error loading task_executor library: {str(e)}"
    
    response = await execute_script_with_context(
        script=final_script,
        command_type="query_items",
        tool_name="illustrator_query_items",
        params=params.model_dump()
    )
    
    # Parse and format response
    result_str = format_response(response)
    
    try:
        report = json.loads(result_str)
        
        # Build human-readable output
        status = "✓" if report.get("ok") else "✗"
        timing = report.get("timing", {})
        stats = report.get("stats", {})
        
        output = f"{status} Query: {params.target_type}\n"
        output += f"  Timing: {timing.get('total_ms', 0):.0f}ms\n"
        output += f"  Found: {stats.get('itemsProcessed', 0)} items\n"
        
        # List items
        items = report.get("artifacts", {}).get("items", [])
        if items:
            output += "\n  Items:\n"
            for item in items[:20]:  # Limit to 20
                ref = item.get("itemRef", {})
                output += f"    - {item.get('name')} ({item.get('type')}) @ {ref.get('layerPath', '?')}\n"
            if len(items) > 20:
                output += f"    ... and {len(items) - 20} more\n"
        
        # Warnings
        for w in report.get("warnings", []):
            output += f"  ⚠ {w.get('message')}\n"
        
        # Trace
        if params.include_trace and report.get("trace"):
            output += "\n  Trace:\n"
            for t in report["trace"]:
                output += f"    {t}\n"
        
        return output
        
    except json.JSONDecodeError:
        return result_str
