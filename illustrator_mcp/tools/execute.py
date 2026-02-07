"""
Core execute_script tool for Adobe Illustrator.

This is the PRIMARY tool for interacting with Illustrator.
Following the "Scripting First" pattern (like blender-mcp), most operations
should be done via this tool rather than specialized atomic tools.
"""

import json
import logging
from typing import List, Optional
from pydantic import Field
from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_envelope
from illustrator_mcp.protocol import TaskPayload, TaskReport, format_task_report
from illustrator_mcp.libraries import inject_libraries, get_injection_metadata
from illustrator_mcp.tools.base import ToolInputBase

# Set up logging for telemetry
logger = logging.getLogger("illustrator_mcp")





class ExecuteScriptInput(ToolInputBase):
    """Input for executing raw JavaScript in Illustrator."""

    script: str = Field(
        ...,
        description="JavaScript/ExtendScript code to execute in Illustrator",
        min_length=1
    )

    description: str = Field(
        default="",
        description="Brief description of what the script does (e.g., 'Draw graphene lattice', 'Add axis labels'). Shown in CEP panel log for debugging."
    )

    includes: Optional[List[str]] = Field(
        default=None,
        description="List of standard libraries to inject (e.g., ['geometry', 'selection', 'layout', 'validate'])"
    )

    # Validation parameters
    validate_bounds: bool = Field(
        default=False,
        description="Check if items are on artboard after execution"
    )

    bounds_type: str = Field(
        default="visible",
        description="Bounds type for validation: 'visible' (includes strokes/effects) or 'geometric' (path only)"
    )

    artboard_index: Optional[int] = Field(
        default=None,
        description="Artboard index for validation (None = active artboard)"
    )

    ignore_hidden: bool = Field(
        default=True,
        description="Skip hidden items in validation"
    )

    ignore_locked: bool = Field(
        default=True,
        description="Skip locked items in validation"
    )

    bounds_scope: str = Field(
        default="document",
        description="Scope: 'document' (all items) or 'artboard' (items on target artboard)"
    )

    bounds_source: str = Field(
        default="group_visible",
        description="Bounds source: 'group_visible' (default) or 'clipping_path' (use clipping path bounds for clipped groups)"
    )


@mcp.tool(
    name="illustrator_execute_script",
    annotations={
        "title": "Execute JavaScript in Illustrator",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False
    }
)
async def illustrator_execute_script(params: ExecuteScriptInput) -> str:
    """
    Execute raw JavaScript/ExtendScript code in Adobe Illustrator.
    
    This is the PRIMARY tool for all Illustrator operations. Use get_scripting_reference
    for syntax help if needed.
    
    COORDINATE SYSTEM:
    - Origin: Top-left of artboard
    - Y-axis: NEGATIVE downward. Use -y for visual y positions.
    - Units: Points (1 pt = 1/72 inch)
    
    COMMON OPERATIONS:
    
    Shapes:
    - Rectangle: doc.pathItems.rectangle(top, left, width, height)
    - Ellipse: doc.pathItems.ellipse(top, left, width, height)
    - Line: var p = doc.pathItems.add(); p.setEntirePath([[x1,-y1], [x2,-y2]])
    
    Colors:
    - var c = new RGBColor(); c.red=255; c.green=0; c.blue=0;
    - shape.fillColor = c; shape.strokeColor = c;
    
    Text:
    - var tf = doc.textFrames.add(); tf.contents = "text"; tf.position = [x, -y];
    
    Selection:
    - var sel = doc.selection; // Array of selected items
    - item.selected = true; // Select an item
    
    Args:
        params.script: Valid ExtendScript code to execute
    
    Returns:
        JSON result from script execution, or error details if failed
    
    Example:
        // Draw a red rectangle
        var doc = app.activeDocument;
        var rect = doc.pathItems.rectangle(-100, 50, 200, 100);
        var c = new RGBColor(); c.red = 255; c.green = 0; c.blue = 0;
        rect.fillColor = c;
    
    IMPORTANT: Always use -y for Y coordinates when positioning objects.
    Call get_scripting_reference for more detailed syntax examples.
    """
    # Log script execution for telemetry
    script_len = len(params.script)
    desc = params.description.strip() if params.description else None

    warnings = []

    # Get canonicalized includes metadata
    if params.includes:
        meta = get_injection_metadata(params.includes)
        includes_canonical = meta["includes_canonical"]
        prelude_hash = meta["prelude_hash"]
    else:
        includes_canonical = []
        prelude_hash = None

    diagnostics = {
        "includes": includes_canonical,
        "prelude_hash": prelude_hash,
        "validate_bounds": params.validate_bounds,
        "bounds_type": params.bounds_type,
        "bounds_source": params.bounds_source,
        "bounds_scope": params.bounds_scope,
        "artboard_index": params.artboard_index
    }

    # Inject standard libraries if requested
    final_script = params.script
    if params.includes:
        try:
            final_script = inject_libraries(params.script, params.includes)
            logger.info(f"Injected libraries: {params.includes}")
        except ValueError as e:
            return json.dumps({
                "ok": False,
                "warnings": [],
                "error": {"code": "V_LIBRARY_NOT_FOUND", "message": str(e)},
                "diagnostics": diagnostics,
                "result": None
            })

    # Create a descriptive command_type for CEP panel
    # Priority: description > script snippet
    if desc:
        command_type = desc[:50]  # Limit length for display
    else:
        # Extract first meaningful line from script as fallback
        lines = [l.strip() for l in params.script.split('\n') if l.strip() and not l.strip().startswith('//')]
        preview = lines[0][:40] if lines else "script"
        command_type = f"script: {preview}..."

    logger.info(f"execute_script: {command_type} ({script_len} chars)")

    try:
        response = await execute_script_with_context(
            script=final_script,
            command_type=command_type,
            tool_name="illustrator_execute_script",
            params={"description": desc or "raw script", "length": script_len}
        )

        # Optional bounds validation after execution
        if params.validate_bounds:
            ab_idx = params.artboard_index if params.artboard_index is not None else 'null'
            check_script = f"""
            countItemsOnArtboard({{
                artboardIndex: {ab_idx},
                boundsType: "{params.bounds_type}",
                boundsSource: "{params.bounds_source}",
                ignoreHidden: {str(params.ignore_hidden).lower()},
                ignoreLocked: {str(params.ignore_locked).lower()},
                policy: "fully-contained",
                scope: "{params.bounds_scope}"
            }});
            """
            try:
                check_with_lib = inject_libraries(check_script, ["validate"])
                check_response = await execute_script_with_context(
                    script=check_with_lib,
                    command_type="bounds_validation",
                    tool_name="illustrator_execute_script"
                )
                # CEP returns {"success": bool, "result": "JSON string"}
                cep_result = check_response.get("result", {})
                if isinstance(cep_result, str):
                    cep_result = json.loads(cep_result)

                # Check for validation errors (e.g., invalid artboard index)
                if cep_result.get("ok") is False or cep_result.get("error"):
                    error_info = cep_result.get("error", {})
                    error_msg = error_info.get("message", "unknown error") if isinstance(error_info, dict) else str(error_info)
                    warnings.append(f"Bounds validation failed: {error_msg}")
                else:
                    # Extract inner result (the actual validation data)
                    inner_result = cep_result.get("result", "{}")
                    if isinstance(inner_result, str):
                        bounds = json.loads(inner_result)
                    else:
                        bounds = inner_result

                    # Always include validation result in diagnostics when validation runs
                    if bounds:
                        diagnostics["validation_result"] = bounds

                        # Add warning if items are off-artboard
                        if bounds.get('off_artboard', 0) > 0:
                            warnings.append(
                                f"{bounds['off_artboard']} items outside artboard bounds "
                                f"(policy: fully-contained, {params.bounds_type}Bounds)"
                            )
            except Exception as e:
                warnings.append(f"Bounds validation failed: {e}")

        # Log errors for debugging
        context = f"execute_script: {desc}" if desc else "execute_script"

        # Return standardized envelope
        return format_envelope(
            response=response,
            context=context,
            warnings=warnings,
            diagnostics=diagnostics
        )

    except Exception as e:
        logger.error(f"Script execution failed: {str(e)}")
        raise


# ==================== Task Protocol Tool ====================


class ExecuteTaskInput(ToolInputBase):
    """Input for executing a structured task (Task Protocol v2.1)."""
    
    payload: TaskPayload = Field(..., description="Task payload with targets, params, and options")
    
    collect_fn: str = Field(
        default="collectTargets",
        description="Collector function name (use standard 'collectTargets' or provide custom)"
    )
    
    compute_fn: str = Field(
        ...,
        description="JSX code for compute logic. Receives (items, params, report), must return actions array."
    )
    
    apply_fn: str = Field(
        ...,
        description="JSX code for apply logic. Receives (actions, report), modifies items."
    )


@mcp.tool(
    name="illustrator_execute_task",
    annotations={
        "title": "Execute Structured Task",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False
    }
)
async def illustrator_execute_task(params: ExecuteTaskInput) -> str:
    """
    Execute a structured task using the Task Protocol v2.1.
    
    Benefits over raw execute_script:
    - Standardized payload/report format
    - Automatic timing and error context
    - Declarative target selection (no manual selection micro-ops)
    - Supports dryRun and trace modes
    - Per-item error localization via itemRef
    
    TARGET SELECTORS:
    - {type: "selection"} - Current selection (default)
    - {type: "layer", layer: "Layer 1"} - All items in layer
    - {type: "query", itemType: "PathItem", pattern: "axis_*"} - Pattern match
    - {type: "all", recursive: true} - All items in document
    
    OPTIONS:
    - dryRun: true - Compute actions but don't apply
    - trace: true - Include execution trace in report
    - assignIds: true - Write unique IDs to item.note (opt-in)
    
    Example payload:
        {
            "task": "apply_fill_color",
            "targets": {"type": "selection"},
            "params": {"color": {"r": 255, "g": 0, "b": 0}},
            "options": {"trace": true}
        }
    """
    # Build the execution script
    payload_json = json.dumps(params.payload.model_dump())
    
    script = f"""
// Compute function
function compute(items, params, report) {{
{params.compute_fn}
}}

// Apply function  
function apply(actions, report) {{
{params.apply_fn}
}}

// Execute task
var payload = {payload_json};
var report = executeTask(
    payload,
    {params.collect_fn},
    compute,
    apply
);

JSON.stringify(report);
"""
    
    diagnostics = {
        "task": params.payload.task,
        "includes": ["task_executor"]
    }

    # Inject task_executor library
    try:
        final_script = inject_libraries(script, ["task_executor"])
    except ValueError as e:
        return json.dumps({
            "ok": False,
            "warnings": [],
            "error": {"code": "V_LIBRARY_NOT_FOUND", "message": str(e)},
            "diagnostics": diagnostics,
            "result": None
        })

    logger.info(f"execute_task: {params.payload.task}")

    try:
        response = await execute_script_with_context(
            script=final_script,
            command_type=f"task:{params.payload.task}",
            tool_name="illustrator_execute_task",
            params=params.payload.model_dump()
        )

        context = f"execute_task: {params.payload.task}"

        # Try to parse TaskReport for formatted output
        try:
            result = response.get("result", "{}")
            if isinstance(result, str):
                report_data = json.loads(result)
            else:
                report_data = result

            report = TaskReport.model_validate(report_data)
            formatted = format_task_report(report, params.payload.task)

            # Return envelope with formatted report as result
            return json.dumps({
                "ok": True,
                "warnings": [],
                "error": None,
                "diagnostics": diagnostics,
                "result": {"formatted": formatted, "report": report_data}
            })

        except (json.JSONDecodeError, Exception) as parse_error:
            # Fallback: return raw result in envelope
            logger.warning(f"Failed to parse TaskReport: {parse_error}")
            return format_envelope(
                response=response,
                context=context,
                diagnostics=diagnostics
            )

    except Exception as e:
        logger.error(f"Task execution failed: {str(e)}")
        raise

