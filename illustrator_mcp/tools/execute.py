"""
Core execute_script tool for Adobe Illustrator.

This is the PRIMARY tool for interacting with Illustrator.
Following the "Scripting First" pattern (like blender-mcp), most operations
should be done via this tool rather than specialized atomic tools.
"""

import json
import logging
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict
from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response
from illustrator_mcp.protocol import TaskPayload, TaskReport

# Set up logging for telemetry
logger = logging.getLogger("illustrator_mcp")


def inject_libraries(script: str, includes: List[str]) -> str:
    """Prepend standard library code to a script using manifest-driven resolution.
    
    Features (v2.3):
    - Automatic transitive dependency resolution
    - Deduplication (each library loaded exactly once)
    - Symbol collision detection
    - Library content caching
    
    Args:
        script: The user's ExtendScript code
        includes: List of library names ["geometry", "selection", "layout", "task_executor"]
    
    Returns:
        Combined script with libraries prepended
    
    Raises:
        ValueError: If a requested library file is not found or symbol collision detected
    """
    if not includes:
        return script
    
    resolver = LibraryResolver()
    library_code = resolver.resolve(includes)
    
    return library_code + "\n\n// === User Script ===\n" + script


class LibraryResolver:
    """Manifest-driven library injection with dependency resolution (v2.3)."""
    
    _instance = None
    _cache: dict = {}
    
    def __new__(cls):
        """Singleton pattern for caching."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        resources_dir = Path(__file__).parent.parent / "resources" / "scripts"
        manifest_path = resources_dir / "manifest.json"
        
        if not manifest_path.exists():
            # Fallback to simple mode if no manifest
            self.manifest = None
            self.resources_dir = resources_dir
        else:
            import json
            with open(manifest_path, encoding="utf-8") as f:
                self.manifest = json.load(f)
            self.resources_dir = resources_dir
        
        self._initialized = True
    
    def resolve(self, includes: List[str]) -> str:
        """
        Resolve libraries with transitive dependencies.
        
        Returns concatenated script content with:
        - Automatic dependency resolution
        - Deduplication  
        - Symbol collision detection
        """
        if not self.manifest:
            # Fallback: simple concatenation without resolution
            return self._simple_resolve(includes)
        
        resolved: List[str] = []
        seen: set = set()
        all_exports: dict = {}  # symbol -> library name
        
        def resolve_one(lib_name: str):
            if lib_name in seen:
                return
            
            if lib_name not in self.manifest["libraries"]:
                raise ValueError(f"Unknown library: {lib_name}")
            
            lib = self.manifest["libraries"][lib_name]
            
            # Resolve dependencies first (recursive)
            for dep in lib.get("dependencies", []):
                resolve_one(dep)
            
            # Check for symbol collisions
            for symbol in lib.get("exports", []):
                if symbol in all_exports:
                    raise ValueError(
                        f"Symbol collision: '{symbol}' defined in both "
                        f"'{all_exports[symbol]}' and '{lib_name}'"
                    )
                all_exports[symbol] = lib_name
            
            # Load and cache library content
            if lib_name not in LibraryResolver._cache:
                lib_path = self.resources_dir / lib["file"]
                if not lib_path.exists():
                    raise ValueError(f"Library file not found: {lib['file']}")
                LibraryResolver._cache[lib_name] = lib_path.read_text(encoding="utf-8")
            
            resolved.append(LibraryResolver._cache[lib_name])
            seen.add(lib_name)
        
        for lib_name in includes:
            resolve_one(lib_name)
        
        return "\n\n".join(resolved)
    
    def _simple_resolve(self, includes: List[str]) -> str:
        """Fallback: simple file concatenation without manifest."""
        library_code = []
        
        for lib_name in includes:
            if lib_name not in LibraryResolver._cache:
                lib_path = self.resources_dir / f"{lib_name}.jsx"
                if not lib_path.exists():
                    raise ValueError(f"Library not found: {lib_name}.jsx (looked in {self.resources_dir})")
                LibraryResolver._cache[lib_name] = lib_path.read_text(encoding="utf-8")
            library_code.append(LibraryResolver._cache[lib_name])
        
        return "\n".join(library_code)



class ExecuteScriptInput(BaseModel):
    """Input for executing raw JavaScript in Illustrator."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
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
        description="List of standard libraries to inject (e.g., ['geometry', 'selection', 'layout', 'task_executor'])"
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
    
    # Inject standard libraries if requested
    final_script = params.script
    if params.includes:
        try:
            final_script = inject_libraries(params.script, params.includes)
            logger.info(f"Injected libraries: {params.includes}")
        except ValueError as e:
            return f"Error importing libraries: {str(e)}"
    
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
        
        # Log errors for debugging
        result = format_response(response)
        if "error" in result.lower() or "eval error" in result.lower():
            logger.warning(f"Script error: {result[:200]}")
        
        return result
        
    except Exception as e:
        logger.error(f"Script execution failed: {str(e)}")
        raise


# ==================== Task Protocol Tool ====================


class ExecuteTaskInput(BaseModel):
    """Input for executing a structured task (Task Protocol v2.1)."""
    model_config = ConfigDict(str_strip_whitespace=True)
    
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
    
    # Inject task_executor library
    try:
        final_script = inject_libraries(script, ["task_executor"])
    except ValueError as e:
        return f"Error loading task_executor library: {str(e)}"
    
    logger.info(f"execute_task: {params.payload.task}")
    
    try:
        response = await execute_script_with_context(
            script=final_script,
            command_type=f"task:{params.payload.task}",
            tool_name="illustrator_execute_task",
            params=params.payload.model_dump()
        )
        
        result_str = format_response(response)
        
        # Try to parse and format the TaskReport
        try:
            report_data = json.loads(result_str)
            report = TaskReport.model_validate(report_data)
            
            # Build human-readable output
            status = "✓" if report.ok else "✗"
            output = f"{status} Task: {params.payload.task}\n"
            output += f"  Timing: collect={report.timing.collect_ms:.0f}ms, "
            output += f"compute={report.timing.compute_ms:.0f}ms, "
            output += f"apply={report.timing.apply_ms:.0f}ms\n"
            output += f"  Stats: {report.stats.itemsProcessed} processed, "
            output += f"{report.stats.itemsModified} modified, "
            output += f"{report.stats.itemsSkipped} skipped\n"
            
            if report.warnings:
                output += f"  ⚠ Warnings ({len(report.warnings)}):\n"
                for w in report.warnings:
                    output += f"    [{w.stage}] {w.message}\n"
            
            if report.errors:
                output += f"  ✗ Errors ({len(report.errors)}):\n"
                for e in report.errors:
                    loc = ""
                    if e.itemRef:
                        loc = f" at {e.itemRef.layerPath}[{e.itemRef.indexPath}]"
                    output += f"    [{e.stage}] {e.code}: {e.message}{loc}\n"
            
            if report.trace:
                output += f"  Trace:\n"
                for t in report.trace:
                    output += f"    {t}\n"
            
            return output
            
        except (json.JSONDecodeError, Exception) as parse_error:
            # Fallback: return raw result if parsing fails
            logger.warning(f"Failed to parse TaskReport: {parse_error}")
            return result_str
        
    except Exception as e:
        logger.error(f"Task execution failed: {str(e)}")
        raise

