"""
Task Protocol Query Tools - Pilot refactor using new Task Protocol.

Demonstrates how to use the task protocol with declarative target selection
for more structured, observable, and debuggable operations.
"""

import json
from typing import Dict, Any, List
from pydantic import Field

import logging
from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_envelope
from illustrator_mcp.libraries import inject_libraries, get_injection_metadata
from illustrator_mcp.tools.base import ToolInputBase

logger = logging.getLogger("illustrator_mcp")


class QueryItemsInput(ToolInputBase):
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

    # Get canonicalized includes metadata
    meta = get_injection_metadata(["task_executor"])
    diagnostics = {
        "targets": params.targets,
        "includes": meta["includes_canonical"],
        "prelude_hash": meta["prelude_hash"]
    }

    # Debug mode: return raw response
    if params.debug:
        debug_output = {
            "raw_response": response,
            "script_length": len(final_script),
            "script_preview": final_script[:500] + "..." if len(final_script) > 500 else final_script
        }
        return json.dumps({
            "ok": True,
            "warnings": [],
            "error": None,
            "diagnostics": diagnostics,
            "result": debug_output
        }, indent=2, default=str)

    # Parse response and return standardized envelope
    try:
        result = response.get("result", "{}")
        if isinstance(result, str):
            report = json.loads(result)
        else:
            report = result

        # Extract warnings from report (if any)
        warnings = []
        for w in report.get("warnings", []):
            if isinstance(w, dict):
                warnings.append(w.get("message", str(w)))
            else:
                warnings.append(str(w))

        # Check for errors in report
        errors = report.get("errors", [])
        if errors:
            error_msg = errors[0].get("message", "Unknown error") if errors else "Query failed"
            error_code = errors[0].get("code", "QUERY_ERROR") if errors else "QUERY_ERROR"
            return json.dumps({
                "ok": False,
                "warnings": warnings,
                "error": {"code": error_code, "message": error_msg},
                "diagnostics": diagnostics,
                "result": report
            })

        # Success case
        return json.dumps({
            "ok": report.get("ok", True),
            "warnings": warnings,
            "error": None,
            "diagnostics": diagnostics,
            "result": report
        })

    except json.JSONDecodeError as e:
        return json.dumps({
            "ok": False,
            "warnings": [],
            "error": {"code": "JSON_PARSE_ERROR", "message": str(e)},
            "diagnostics": diagnostics,
            "result": response.get("result")
        })


# ==================== Preflight Check Tool ====================


class PreflightCheckInput(ToolInputBase):
    """Input for preflight document validation."""

    artboard_index: int = Field(
        default=None,
        description="Artboard index to check (None = active artboard)"
    )

    bounds_type: str = Field(
        default="visible",
        description="Bounds type for validation: 'visible' (includes strokes/effects) or 'geometric' (path only)"
    )

    bounds_source: str = Field(
        default="group_visible",
        description="Bounds source: 'group_visible' (default) or 'clipping_path' (use clipping path bounds for clipped groups)"
    )

    policy: str = Field(
        default="fully-contained",
        description="Containment policy: 'fully-contained' (entire item on artboard) or 'intersects' (any overlap)"
    )

    scope: str = Field(
        default="document",
        description="Item scope: 'document' (all items) or 'artboard' (items on target artboard)"
    )

    check_zero_size: bool = Field(
        default=True,
        description="Check for zero-size items"
    )

    check_empty_text: bool = Field(
        default=True,
        description="Check for empty text frames"
    )

    check_locked: bool = Field(
        default=True,
        description="Report locked layers/items"
    )


@mcp.tool(
    name="illustrator_preflight_check",
    annotations={
        "title": "Preflight Document Check",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def illustrator_preflight_check(params: PreflightCheckInput) -> str:
    """
    Perform observational validation on the active document.

    This is a READ-ONLY tool that checks for common issues:
    - Items outside artboard bounds (configurable policy)
    - Zero-size items (width or height = 0)
    - Empty text frames
    - Locked layers and items

    Use this before export or to validate document state.
    Does NOT modify the document.

    Returns standardized envelope with:
    - ok: true if all checks pass
    - warnings: list of issues found
    - result: detailed validation data
    """
    ab_idx = params.artboard_index if params.artboard_index is not None else 'null'

    # Build the preflight check script
    script = f"""
(function() {{
    var doc = app.activeDocument;
    var result = {{
        document: doc.name,
        artboard_index: null,
        checks: {{}},
        issues: [],
        summary: {{
            total_items: 0,
            issues_found: 0
        }}
    }};

    // Get artboard
    var abIdx = {ab_idx};
    if (abIdx === null) {{
        abIdx = doc.artboards.getActiveArtboardIndex();
    }}
    result.artboard_index = abIdx;
    var ab = doc.artboards[abIdx].artboardRect;

    // 1. Bounds check using validate library
    var boundsResult = JSON.parse(countItemsOnArtboard({{
        artboardIndex: abIdx,
        boundsType: "{params.bounds_type}",
        boundsSource: "{params.bounds_source}",
        policy: "{params.policy}",
        scope: "{params.scope}",
        ignoreHidden: true,
        ignoreLocked: false
    }}));

    result.checks.bounds = boundsResult;
    result.summary.total_items = boundsResult.items_checked;

    if (boundsResult.off_artboard > 0) {{
        result.issues.push({{
            type: "off_artboard",
            count: boundsResult.off_artboard,
            message: boundsResult.off_artboard + " items outside artboard bounds",
            samples: boundsResult.off_items_sample
        }});
        result.summary.issues_found += boundsResult.off_artboard;
    }}

    // Helper for scope filtering
    var scope = "{params.scope}";
    function isItemCenterOnArtboard(itemBounds, artboardRect) {{
        var centerX = (itemBounds[0] + itemBounds[2]) / 2;
        var centerY = (itemBounds[1] + itemBounds[3]) / 2;
        return (centerX >= artboardRect[0] && centerX <= artboardRect[2] &&
                centerY <= artboardRect[1] && centerY >= artboardRect[3]);
    }}

    // Helper for layer-visibility filtering
    function isLayerHidden(item) {{
        try {{
            var l = item.layer;
            while (l) {{
                if (!l.visible) return true;
                if (l.parent && l.parent.typename === 'Layer') {{
                    l = l.parent;
                }} else {{
                    break;
                }}
            }}
        }} catch (e) {{}}
        return false;
    }}

    // 2. Zero-size check (scope-aware)
    if ({str(params.check_zero_size).lower()}) {{
        var zeroSize = [];
        for (var i = 0; i < doc.pageItems.length; i++) {{
            var item = doc.pageItems[i];
            if (item.hidden || isLayerHidden(item)) continue;
            if (item.guides) continue;  // guide lines are inherently zero-size
            try {{
                var b = item.geometricBounds;
                // Apply scope filter
                if (scope === "artboard" && !isItemCenterOnArtboard(b, ab)) continue;

                if (item.width === 0 || item.height === 0) {{
                    zeroSize.push(item.name || ("item_" + i));
                }}
            }} catch (e) {{
                // Some items may not have width/height
            }}
        }}
        result.checks.zero_size = {{ count: zeroSize.length, items: zeroSize.slice(0, 10) }};
        if (zeroSize.length > 0) {{
            result.issues.push({{
                type: "zero_size",
                count: zeroSize.length,
                message: zeroSize.length + " items have zero width or height",
                samples: zeroSize.slice(0, 10)
            }});
            result.summary.issues_found += zeroSize.length;
        }}
    }}

    // 3. Empty text frames check (scope-aware)
    if ({str(params.check_empty_text).lower()}) {{
        var emptyText = [];
        for (var i = 0; i < doc.textFrames.length; i++) {{
            var tf = doc.textFrames[i];
            if (tf.hidden || isLayerHidden(tf)) continue;
            try {{
                var b = tf.geometricBounds;
                // Apply scope filter
                if (scope === "artboard" && !isItemCenterOnArtboard(b, ab)) continue;

                var content = tf.contents.replace(/\\s/g, "");
                if (content.length === 0) {{
                    emptyText.push(tf.name || ("textFrame_" + i));
                }}
            }} catch (e) {{
                // Some items may not have bounds accessible
            }}
        }}
        result.checks.empty_text = {{ count: emptyText.length, items: emptyText.slice(0, 10) }};
        if (emptyText.length > 0) {{
            result.issues.push({{
                type: "empty_text",
                count: emptyText.length,
                message: emptyText.length + " empty text frames",
                samples: emptyText.slice(0, 10)
            }});
            result.summary.issues_found += emptyText.length;
        }}
    }}

    // 4. Locked layers/items check
    if ({str(params.check_locked).lower()}) {{
        var lockedLayers = [];
        var lockedItems = 0;

        for (var i = 0; i < doc.layers.length; i++) {{
            var layer = doc.layers[i];
            if (layer.locked) {{
                lockedLayers.push(layer.name);
            }}
        }}

        for (var i = 0; i < doc.pageItems.length; i++) {{
            var item = doc.pageItems[i];
            if (item.locked) lockedItems++;
        }}

        result.checks.locked = {{
            locked_layers: lockedLayers,
            locked_items: lockedItems
        }};

        // Locked items are informational, not issues
        if (lockedLayers.length > 0 || lockedItems > 0) {{
            result.issues.push({{
                type: "locked",
                count: lockedLayers.length + lockedItems,
                message: lockedLayers.length + " locked layers, " + lockedItems + " locked items",
                severity: "info"
            }});
        }}
    }}

    return JSON.stringify(result);
}})();
"""

    # Get canonicalized includes metadata
    preflight_meta = get_injection_metadata(["validate"])
    diagnostics = {
        "artboard_index": params.artboard_index,
        "bounds_type": params.bounds_type,
        "bounds_source": params.bounds_source,
        "policy": params.policy,
        "scope": params.scope,
        "includes": preflight_meta["includes_canonical"],
        "prelude_hash": preflight_meta["prelude_hash"]
    }

    try:
        # Inject validate library
        final_script = inject_libraries(script, ["validate"])
    except ValueError as e:
        return json.dumps({
            "ok": False,
            "warnings": [],
            "error": {"code": "V_LIBRARY_NOT_FOUND", "message": str(e)},
            "diagnostics": diagnostics,
            "result": None
        })

    logger.info(f"preflight_check: artboard={params.artboard_index}, policy={params.policy}")

    try:
        response = await execute_script_with_context(
            script=final_script,
            command_type="preflight_check",
            tool_name="illustrator_preflight_check",
            params=params.model_dump()
        )

        # Parse result - CEP returns {"success": bool, "result": "JSON string"}
        cep_result = response.get("result", {})
        if isinstance(cep_result, str):
            cep_result = json.loads(cep_result)

        # Extract the inner result (preflight data as JSON string)
        inner_result = cep_result.get("result", "{}")
        if isinstance(inner_result, str):
            preflight_data = json.loads(inner_result)
        else:
            preflight_data = inner_result

        # Build warnings from issues
        warnings = []
        for issue in preflight_data.get("issues", []):
            if issue.get("severity") != "info":
                warnings.append(issue.get("message", "Unknown issue"))

        # Determine ok status: ok if no non-info issues
        non_info_issues = [i for i in preflight_data.get("issues", []) if i.get("severity") != "info"]
        is_ok = len(non_info_issues) == 0

        return json.dumps({
            "ok": is_ok,
            "warnings": warnings,
            "error": None,
            "diagnostics": diagnostics,
            "result": preflight_data
        })

    except Exception as e:
        logger.error(f"Preflight check failed: {str(e)}")
        return json.dumps({
            "ok": False,
            "warnings": [],
            "error": {"code": "PREFLIGHT_ERROR", "message": str(e)},
            "diagnostics": diagnostics,
            "result": None
        })
