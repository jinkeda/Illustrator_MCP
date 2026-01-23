"""
Task Protocol Query Tools - Pilot refactor using new Task Protocol.

Demonstrates how to use the task protocol with declarative target selection
for more structured, observable, and debuggable operations.
"""

import json
from typing import Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response
from illustrator_mcp.libraries import inject_libraries


class QueryItemsInput(BaseModel):
    """Input for querying items using declarative target selector.
    
    The targets parameter accepts a Task Protocol target selector dict:
    
    Target types:
    - {"type": "selection"} - Current selection (default)
    - {"type": "layer", "layer": "Layer 1"} - All items on a specific layer
    - {"type": "all"} - All items in document
    - {"type": "query", "itemType": "PathItem", "pattern": "rect_*"} - Filter by type/name
    
    Compound selectors (advanced):
    - {"type": "union", "selectors": [...]} - Union of multiple selectors
    - {"type": "intersection", "selectors": [...]} - Intersection of selectors
    
    Example payloads from living_test.md can be used directly.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    targets: Dict[str, Any] = Field(
        default={"type": "selection"},
        description=(
            "Task Protocol target selector. Examples: "
            "{'type': 'selection'}, "
            "{'type': 'layer', 'layer': 'Layer 1'}, "
            "{'type': 'all'}, "
            "{'type': 'query', 'itemType': 'PathItem', 'pattern': 'rect_*'}"
        )
    )

    include_trace: bool = Field(
        default=False,
        description="Include execution trace in response"
    )

    debug: bool = Field(
        default=False,
        description="Return raw response for debugging"
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
    
    # Use targets directly from input (already matches Task Protocol format)
    targets = params.targets
    
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
// Pre-flight check: verify library functions are available
var _libraryCheck = {{
    executeTask: typeof executeTask,
    validatePayload: typeof validatePayload,
    collectTargets: typeof collectTargets,
    describeItemV2: typeof describeItemV2,
    makeError: typeof makeError
}};

// If any function is undefined, return diagnostic info
if (typeof executeTask !== "function" || typeof validatePayload !== "function") {{
    JSON.stringify({{
        ok: false,
        errors: [{{
            code: "LIB_NOT_LOADED",
            message: "task_executor.jsx library not properly loaded",
            stage: "preflight",
            details: _libraryCheck
        }}],
        stats: {{ itemsProcessed: 0 }},
        timing: {{ total_ms: 0 }}
    }});
}} else {{
    // Compute function - gather item info AND store in artifacts
    // (store here because apply is skipped in dryRun mode)
    function compute(items, params, report) {{
        var actions = [];
        report.artifacts = report.artifacts || {{}};
        report.artifacts.items = [];
        
        for (var i = 0; i < items.length; i++) {{
            var item = items[i];
            var itemRef = describeItemV2(item, {{includeIdentity: true, includeTags: true}});
            var itemData = {{
                itemRef: itemRef,
                name: item.name || "(unnamed)",
                type: item.typename,
                bounds: {{
                    left: item.left,
                    top: item.top,
                    width: item.width,
                    height: item.height
                }}
            }};
            actions.push(itemData);
            report.artifacts.items.push(itemData);
            report.stats.itemsProcessed++;
        }}
        return actions;
    }}

    // Apply function - no-op for query (results already stored in compute)
    function apply(actions, report) {{
        // No-op: items stored in compute stage for dryRun compatibility
    }}

    // Execute task
    var payload = {payload_json};
    var report = executeTask(payload, collectTargets, compute, apply);
    JSON.stringify(report);
}}
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

    # Debug mode: return raw response
    if params.debug:
        import json as json_module
        debug_output = {
            "raw_response": response,
            "script_length": len(final_script),
            "script_preview": final_script[:500] + "..." if len(final_script) > 500 else final_script
        }
        return json_module.dumps(debug_output, indent=2, default=str)

    # Parse and format response
    result_str = format_response(response)
    
    try:
        report = json.loads(result_str)
        
        # Build human-readable output
        status = "✓" if report.get("ok") else "✗"
        timing = report.get("timing", {})
        stats = report.get("stats", {})
        
        output = f"{status} Query: {params.targets.get('type', 'selection')}\n"
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
        
        # Errors
        for e in report.get("errors", []):
            output += f"  ✗ [{e.get('code', '?')}] {e.get('message', 'Unknown error')}\n"
            if e.get("details"):
                details = e.get("details")
                if isinstance(details, dict):
                    output += f"      Details: {json.dumps(details)}\n"
                else:
                    output += f"      Details: {details}\n"
        
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
