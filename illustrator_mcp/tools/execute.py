"""
Core execute_script tool for Adobe Illustrator.

This is the PRIMARY tool for interacting with Illustrator.
Following the "Scripting First" pattern (like blender-mcp), most operations
should be done via this tool rather than specialized atomic tools.

Auto-assign MCP IDs: after script execution, newly created items can be
automatically tagged with @mcp:id= so they're targetable by SOC ops.
Controlled by auto_assign_ids parameter ("delta"|"converge"|"off").
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import Field, model_validator
from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_envelope
from illustrator_mcp.libraries import get_injection_metadata
from illustrator_mcp.tools.base import ToolInputBase
from mcp.types import ImageContent, TextContent

# Import from sibling modules
from illustrator_mcp.tools.cadence import (
    _MutationCounter, _counter, VLM_QA_CADENCE, VLM_CHECKPOINT_INSTRUCTION,
    get_mutation_count, reset_mutation_count,
    format_z_telemetry,
)
from illustrator_mcp.tools.preview import (
    _build_export_script, _capture_artboard, _capture_artboard_png,
    _generate_preview, _COLLECT_ITEMS_JSX, _filter_items, _annotate_preview,
    _run_occlusion_guard, _guard_checkpoint, GuardCheckpointResult,
)

# Set up logging for telemetry
logger = logging.getLogger("illustrator_mcp")


# ── Abstraction advisory: non-blocking hints for raw scripts ───────
_SHAPE_API_RE = re.compile(
    r'pathItems\.(?:add|rectangle|ellipse)\s*\(',
)
_LOOP_RE = re.compile(r'for\s*\(')
_SET_ENTIRE_PATH_RE = re.compile(
    r'setEntirePath\s*\(\s*\[',
)
_PATHFINDER_CMD_RE = re.compile(
    r'executeMenuCommand\s*\(\s*["\'](?:Live Pathfinder|pathfinder)',
    re.IGNORECASE,
)
# Fix 3: fresh pathPoints patterns
_ADD_PATH_VAR_RE = re.compile(
    r'(?:var|let|const)\s+(\w+)\s*=\s*.*?pathItems\.add\s*\(\s*\)',
)
_ADD_PATH_ASSIGN_RE = re.compile(
    r'(\w+)\s*=\s*.*?pathItems\.add\s*\(\s*\)',
)
_ADD_PATH_CHAINED_RE = re.compile(
    r'pathItems\.add\s*\(\s*\)\s*\.\s*pathPoints\s*\[',
)
# Fix 5: rectangle/ellipse call detection
_RECT_ELLIPSE_CALL_RE = re.compile(
    r'(?:rectangle|ellipse)\s*\(',
)
_MAX_ADVISORY_HINTS = 3


def _split_call_args(text: str, start: int) -> "list[str] | None":
    """Split function args by top-level commas (respects nesting).
    `start` points to the opening '('. Returns None if unbalanced."""
    depth = 0
    args: list[str] = []
    current: list[str] = []
    for ch in text[start:]:
        if ch == '(':
            depth += 1
            if depth == 1:
                continue  # skip the opening paren itself
        elif ch == ')':
            depth -= 1
            if depth == 0:
                args.append(''.join(current).strip())
                return args
        elif ch == ',' and depth == 1:
            args.append(''.join(current).strip())
            current = []
            continue
        if depth >= 1:
            current.append(ch)
    return None  # unbalanced


def _abstraction_advisory(script: str) -> list:
    """Emit non-blocking hints when raw script could use a higher-level tool.

    Returns at most _MAX_ADVISORY_HINTS short advisory strings.
    """
    hints = []

    # Batch creation: for-loop + multiple shape API calls
    if _LOOP_RE.search(script) and len(_SHAPE_API_RE.findall(script)) >= 2:
        hints.append(
            "\U0001f4a1 This script creates shapes in a loop. "
            "Consider element_create_batch (array or template+instances)."
        )

    # Large manual path: setEntirePath with many coordinate pairs
    if len(hints) < _MAX_ADVISORY_HINTS:
        m = _SET_ENTIRE_PATH_RE.search(script)
        if m:
            # Count coordinate pairs after setEntirePath([...
            rest = script[m.end():]
            bracket_depth = 1
            pairs = 0
            for ch in rest:
                if ch == '[':
                    bracket_depth += 1
                elif ch == ']':
                    bracket_depth -= 1
                    if bracket_depth == 0:
                        break
                    pairs += 1  # each inner ] closes a [x,y] pair
            if pairs > 12:
                hints.append(
                    "\U0001f4a1 Large setEntirePath detected (~%d points). "
                    "Consider element_create with smooth:true or path_import_svg." % pairs
                )

    # Boolean workarounds via menu commands
    if len(hints) < _MAX_ADVISORY_HINTS and _PATHFINDER_CMD_RE.search(script):
        hints.append(
            "\U0001f4a1 Use the path_boolean tool for reliable boolean ops."
        )

    # Fix 3: pathPoints on fresh pathItems.add() — three patterns
    if len(hints) < _MAX_ADVISORY_HINTS:
        _fresh_path_warned = False
        # Pattern 1: chained form — pathItems.add().pathPoints[
        if _ADD_PATH_CHAINED_RE.search(script):
            _fresh_path_warned = True
        # Pattern 2: var-declared + same var .pathPoints[
        if not _fresh_path_warned:
            for m in _ADD_PATH_VAR_RE.finditer(script):
                var_name = m.group(1)
                if re.search(rf'\b{re.escape(var_name)}\.pathPoints\s*\[', script):
                    _fresh_path_warned = True
                    break
        # Pattern 3: assignment without var + same var .pathPoints[
        if not _fresh_path_warned:
            for m in _ADD_PATH_ASSIGN_RE.finditer(script):
                var_name = m.group(1)
                if var_name in ('var', 'let', 'const'):
                    continue  # already handled by pattern 2
                if re.search(rf'\b{re.escape(var_name)}\.pathPoints\s*\[', script):
                    _fresh_path_warned = True
                    break
        if _fresh_path_warned:
            hints.append(
                "\u26a0\ufe0f pathItems.add() creates a path with zero points. "
                ".pathPoints[N] will throw 'Index out of bounds'. "
                "Use setEntirePath() or element_create instead."
            )

    # Fix 5: rectangle/ellipse with negative width/height (args 2 or 3)
    if len(hints) < _MAX_ADVISORY_HINTS:
        for m in _RECT_ELLIPSE_CALL_RE.finditer(script):
            # Find the opening paren
            paren_pos = m.end() - 1  # position of '('
            args = _split_call_args(script, paren_pos)
            if args and len(args) >= 4:
                neg_params = []
                # args[2] = width, args[3] = height
                for idx, label in ((2, "width"), (3, "height")):
                    val = args[idx].lstrip()
                    if val.startswith('-'):
                        neg_params.append(label)
                if neg_params:
                    hints.append(
                        f"\u26a0\ufe0f rectangle/ellipse called with negative "
                        f"{'/'.join(neg_params)}. "
                        "Negative width/height creates an invisible shape "
                        "above the artboard. Use positive values."
                    )
                    break  # one warning is enough

    return hints[:_MAX_ADVISORY_HINTS]


# ── Auto-tag helper ────────────────────────────────────────────────

_AUTO_TAG_SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "resources", "scripts", "auto_tag.jsx",
)


async def _run_auto_tag(
    *,
    mode: str,
    scope: str,
    cap: int,
    pre_count: int,
    cushion: int = 2,
    timeout: Optional[float] = None,
) -> Optional[dict]:
    """Execute auto_tag.jsx to assign MCP IDs to untagged items.

    Returns parsed result dict or None on failure.  The JSX script
    handles selection-first priority (delta mode) and scope scanning.

    Delta mode tags only items likely created by the preceding script:
    items created AND deleted within the script are intentionally not tagged.
    """
    if not os.path.isfile(_AUTO_TAG_SCRIPT_PATH):
        logger.warning("auto_tag.jsx not found at %s", _AUTO_TAG_SCRIPT_PATH)
        return None

    # Use the library resolver to get auto_tag.jsx WITH its dependencies
    # (mcp_id.jsx provides extractMcpId/setMcpId used by auto_tag.jsx)
    from illustrator_mcp.libraries import get_resolver
    try:
        resolved_code = get_resolver().resolve(
            ["auto_tag"], skip_collision_check=True
        )
    except Exception as e:
        logger.warning("auto_tag library resolution failed: %s", e)
        return None

    # Inject params as preamble
    params_obj = json.dumps({
        "mode": mode,
        "scope": scope,
        "cap": cap,
        "preCount": pre_count,
        "cushion": cushion,
    })
    jsx_with_params = f"var __PARAMS__ = {params_obj};\n{resolved_code}"

    try:
        resp = await execute_script_with_context(
            script=jsx_with_params,
            command_type="auto_tag",
            tool_name="illustrator_execute_script",
            timeout=timeout or 10.0,
        )
    except Exception as e:
        logger.debug("auto_tag.jsx execution failed: %s", e)
        return None

    raw = resp.get("result")
    if not raw:
        return None

    try:
        if isinstance(raw, str):
            parsed = json.loads(raw)
        else:
            parsed = raw
        # Unwrap host.jsx envelope if present
        if isinstance(parsed, dict) and "data" in parsed:
            parsed = parsed["data"]
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
    except (json.JSONDecodeError, TypeError):
        return None

    return parsed


class ExecuteScriptInput(ToolInputBase):
    """Input for executing raw JavaScript in Illustrator."""

    script: Optional[str] = Field(
        default=None,
        description="JavaScript/ExtendScript code to execute in Illustrator"
    )

    file_path: Optional[str] = Field(
        default=None,
        description="Path to a .jsx file to execute (alternative to inline script). Mutually exclusive with 'script'."
    )

    params: Optional[Dict[str, Any]] = Field(
        default=None,
        description="JSON-serializable variables to inject before script execution. "
                    "Values must be JSON-compatible (string, number, bool, array, plain object)."
    )

    params_mode: Literal["__PARAMS_ONLY__", "EXPOSE_VARS"] = Field(
        default="__PARAMS_ONLY__",
        description="__PARAMS_ONLY__: inject single __PARAMS__ object. "
                    "EXPOSE_VARS: also declare top-level vars for each key."
    )

    # Reserved param keys that would collide with injection mechanism
    _RESERVED_PARAM_KEYS = {"__PARAMS__"}

    @model_validator(mode='after')
    def resolve_script_source(self):
        """Ensure either script or file_path is provided, resolve file_path, and inject params."""
        if not self.script and not self.file_path:
            raise ValueError("Provide either 'script' or 'file_path'")
        if self.script and self.file_path:
            raise ValueError("Provide 'script' or 'file_path', not both")
        if self.file_path:
            path = self.file_path
            if not os.path.isfile(path):
                raise ValueError(f"Script file not found: {path}")
            with open(path, 'r', encoding='utf-8') as f:
                self.script = f.read()
            if not self.script.strip():
                raise ValueError(f"Script file is empty: {path}")

        # Inject params as JS object literal preamble
        if self.params:
            bad_keys = set(self.params.keys()) & self._RESERVED_PARAM_KEYS
            if bad_keys:
                raise ValueError(f"Reserved param key(s): {bad_keys}")
            # JSON is valid JS for JSON-serializable values (no undefined, no functions)
            params_literal = json.dumps(self.params, ensure_ascii=False)
            lines = [f"var __PARAMS__ = {params_literal};"]
            if self.params_mode == "EXPOSE_VARS":
                for key in self.params:
                    if not key.isidentifier():
                        raise ValueError(f"Param key is not a valid JS identifier: {key!r}")
                    lines.append(f"var {key} = __PARAMS__[{json.dumps(key)}];")
            preamble = "// Injected by MCP params:\n" + "\n".join(lines) + "\n\n"
            self.script = preamble + self.script

        return self

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

    timeout: Optional[float] = Field(
        default=None, le=300.0,
        description="Execution timeout in seconds. Default 30s, max 300s. Set higher for generative scripts."
    )

    # Preview fields (P4)
    # None = not specified (VLM cadence will auto-inject at checkpoints)
    # True = explicitly requested
    # False = explicitly declined (cadence will skip with warning)
    return_preview: Optional[bool] = Field(
        default=None,
        description="After execution, auto-export a thumbnail and return as ImageContent. "
                    "Leave unset to allow VLM QA cadence to auto-inject at checkpoints."
    )

    preview_mode: Literal["artboard", "bounds", "annotated"] = Field(
        default="artboard",
        description="'artboard': preview active artboard. 'bounds': preview specified bounds. "
                    "'annotated': artboard with numbered bounding boxes and annotation map for VLM grounding."
    )

    preview_max_items: int = Field(
        default=200,
        description="Max items to annotate in 'annotated' preview mode.",
        ge=1,
        le=500
    )

    clip_box: Optional[List[float]] = Field(
        default=None,
        description=(
            "Optional high-resolution crop region: [xmin, ymin, xmax, ymax] in "
            "screen-space Y-down points.  When set, the preview exports a zoomed, "
            "upscaled crop of just this region.  Annotations are culled and mapped "
            "to the crop.  All coordinates in the annotation map remain in global "
            "document space.  Use this when fine details are too small to see or "
            "when annotation tags overlap in dense areas."
        ),
    )

    preview_max_dim: int = Field(
        default=1024,
        description="Max dimension (width or height) of preview thumbnail in pixels.",
        ge=64,
        le=4096
    )

    preview_format: Literal["png", "jpg"] = Field(
        default="png",
        description="Preview image format."
    )

    final_step: bool = Field(
        default=False,
        description="Set to True on the last mutation to force an annotated VLM QA preview, "
                    "regardless of the cadence counter."
    )

    max_ops: int = Field(
        default=500000,
        ge=1000,
        le=5000000,
        description="Maximum iteration guard count. A watchdog counter (__mcp_check()) is "
                    "injected into scripts; when called more than max_ops times it throws "
                    "to prevent infinite-loop crashes. Raise for legitimately large batch scripts."
    )

    max_ms: int = Field(
        default=25000,
        ge=1000,
        le=120000,
        description="Maximum wall-clock time in milliseconds. __mcp_check() also monitors "
                    "elapsed time (checked every 1000 ops) and throws if exceeded."
    )

    probe_points: Optional[List[dict]] = Field(
        default=None,
        description="Coordinate probe markers to render on the annotated preview. "
                    "Each dict has: x (float, pts screen-space), y (float, pts Y-down), "
                    "label (str, optional). Only drawn when preview_mode='annotated'."
    )

    # Auto-assign MCP IDs to items created by this script
    auto_assign_ids: Literal["delta", "converge", "off"] = Field(
        default="delta",
        description='Auto-tag mode for items created by this script. '
                    '"delta": tag items likely created by this script (selection-first, '
                    'bounded by count delta + cushion). '
                    '"converge": tag ALL untagged items in scope (up to cap, explicit migration). '
                    '"off": no scanning, no tagging. '
                    'Auto-tagging mutates item.note by writing @mcp:id= tags. '
                    'Delta mode is cheap (skips entirely when no items created). '
                    'Converge mode can be expensive on large legacy documents.'
    )

    max_auto_tag: int = Field(
        default=200,
        ge=1,
        le=1000,
        description="Maximum number of items to auto-tag per call. "
                    "A warning is emitted when the cap is hit."
    )

    auto_tag_scope: Literal["activeLayer", "document"] = Field(
        default="activeLayer",
        description='Scope for auto-tagging scan. "activeLayer" narrows to the active layer '
                    '(recommended). "document" scans all pageItems.'
    )


from illustrator_mcp.tools.base import (
    TOOL_ANNOTATIONS, ABSTRACTION_LADDER, COORDINATE_SYSTEM_BLOCK,
)

_NAME = "illustrator_execute_script"


@mcp.tool(name=_NAME, annotations=TOOL_ANNOTATIONS[_NAME])
async def illustrator_execute_script(params: ExecuteScriptInput) -> Union[str, list]:
    """Execute raw JavaScript/ExtendScript code in Adobe Illustrator.

    CONTRACT: readOnly=False, destructive=True, idempotent=False, openWorld=True

    WHEN TO USE:
      - Single one-off items, quick prototypes, or operations not covered by higher-level tools
      - Full DOM access when structured tools are insufficient
      - Reading document state with custom logic

    ABSTRACTION LADDER — prefer higher levels before using raw script:
      Level 5 — illustrator_path_boolean: boolean sculpt (unite/subtract/intersect/xor)
      Level 4 — illustrator_execute_task + element_create_batch: batch-create identical shapes
      Level 3 — illustrator_path_import_svg: import SVG d-string paths
      Level 2 — illustrator_execute_task + element_create: smooth curves, handles, mirror
      Level 1 — illustrator_execute_script (THIS tool): raw ExtendScript

    DECISION RULES:
      - Subtract/unite shapes — MUST use illustrator_path_boolean
      - Creating >=3 identical shapes — MUST use illustrator_execute_task + element_create_batch
      - setEntirePath with >12 coord pairs — STOP and use smooth:true or illustrator_path_import_svg

    COORDINATE SYSTEM:
      - API coordinates use top-left origin with y increasing downward (screen space)
      - ExtendScript expects Y-up internally; use -y when calling Illustrator DOM methods
      - Units: points (1 pt = 1/72 inch)
      - Example: to place at visual position (100, 200), use position = [100, -200]

    EXAMPLES:
      Rectangle: doc.pathItems.rectangle(top, left, width, height)
        ⚠ width & height must be POSITIVE. Negative height → shape above artboard (invisible).
      Ellipse: doc.pathItems.ellipse(top, left, width, height)
      Line: var p = doc.pathItems.add(); p.setEntirePath([[x1,-y1], [x2,-y2]])
      Color: var c = new RGBColor(); c.red=255; c.green=0; c.blue=0; shape.fillColor = c;
      Text: var tf = doc.textFrames.add(); tf.contents = "text"; tf.position = [x, -y];
      Grid helpers: artboardGrid(cols, rows), itemsInCell(cell, mode)

    ELEMENT DISCOVERY:
      - Use artboardGrid(cols, rows) to partition the artboard into a labeled grid
      - Use itemsInCell(cell, mode) to find items in a specific grid cell
      - Modes: 'containsCenter' (default) or 'intersects'
      - Cell labels follow A1 scheme (letter row + number col, e.g. A1, B3)

    MUTATION SAFETY:
      - Each call increments a mutation counter for VLM QA cadence tracking
      - Failed executions auto-decrement the counter to avoid cadence drift
      - Use final_step=true on the last mutation to force a visual checkpoint

    NOTES:
      - Every call increments a mutation counter; annotated preview auto-injected at VLM cadence
      - Set final_step=true on the last mutation to force a VLM checkpoint
      - setEntirePath() creates corner points only; set handles after creation
      - ExtendScript can access File/Folder and OS — treat as open-world

    SAFETY:
      - __mcp_check() watchdog: call as FIRST line inside every for/while body
      - Never iterate live Illustrator collections if adding/removing items
      - Use __mcp_forEachSnapshot(collection, fn) or __mcp_snapshot(collection) instead
    """
    # Log script execution for telemetry
    script = params.script  # Already resolved by model_validator

    # ── Safety guard: inject max_ops / max_ms overrides if non-default ──
    safety_overrides = []
    if params.max_ops != 500000:
        safety_overrides.append(f"var __MCP_MAX_OPS = {params.max_ops};")
    if params.max_ms != 25000:
        safety_overrides.append(f"var __MCP_MAX_MS = {params.max_ms};")
    if safety_overrides:
        script = "\n".join(safety_overrides) + "\n" + script

    script_len = len(script)

    # ── Auto-tag: pre-exec count capture ──────────────────────────────
    auto_tag_pre_count = None
    if params.auto_assign_ids != "off":
        _scope_expr = (
            "doc.activeLayer.pageItems.length"
            if params.auto_tag_scope == "activeLayer"
            else "doc.pageItems.length"
        )
        _count_script = (
            f"(function(){{ var doc = app.activeDocument; "
            f"return JSON.stringify({{count: {_scope_expr}}}); }})()"
        )
        try:
            _count_resp = await execute_script_with_context(
                script=_count_script,
                command_type="auto_tag_precount",
                tool_name="illustrator_execute_script",
                timeout=5.0,
            )
            _count_raw = _count_resp.get("result", "{}")
            if isinstance(_count_raw, str):
                _count_data = json.loads(_count_raw)
            else:
                _count_data = _count_raw
            # Unwrap host.jsx envelope if present
            if isinstance(_count_data, dict) and "data" in _count_data:
                _count_data = _count_data["data"]
            if isinstance(_count_data, str):
                _count_data = json.loads(_count_data)
            auto_tag_pre_count = _count_data.get("count", 0)
        except Exception as e:
            logger.debug("Auto-tag pre-count failed: %s", e)
            auto_tag_pre_count = None  # Graceful degradation: skip auto-tag

    desc = params.description.strip() if params.description else None

    warnings = []

    # ── Abstraction advisory: non-blocking hints for raw scripts ──
    advisory_hints = _abstraction_advisory(script)
    if advisory_hints:
        warnings.extend(advisory_hints)

    # ── VLM QA Cadence: auto-inject annotated preview ──────────
    # B3: Increment counter here; decremented in outer except if execution fails
    count = _counter.increment()
    is_checkpoint = (count % VLM_QA_CADENCE == 0) or params.final_step
    is_vlm_checkpoint = False  # True only when cadence auto-injects

    # Record checkpoint skip before execution (preview gating decided here,
    # but guard runs AFTER execution to check post-mutation state)
    checkpoint_skipped = False
    if is_checkpoint:
        if params.return_preview is False and not params.final_step:
            # AI explicitly disabled preview — soft override: warn but respect
            warnings.append(
                f"VLM QA checkpoint skipped (mutation #{count}). "
                "Consider using return_preview=True, preview_mode='annotated' "
                "to visually verify the document state."
            )
            checkpoint_skipped = True
        else:
            # Mark for post-execution guard + preview
            params.return_preview = True
            params.preview_mode = "annotated"
            is_vlm_checkpoint = True
            logger.info(
                f"VLM QA cadence: checkpoint at mutation #{count} "
                f"(final_step={params.final_step})"
            )

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
        "artboard_index": params.artboard_index,
        "is_vlm_checkpoint": is_vlm_checkpoint,
    }

    # Create a descriptive command_type for CEP panel
    # Priority: description > script snippet
    if desc:
        command_type = desc[:50]  # Limit length for display
    else:
        # Extract first meaningful line from script as fallback
        lines = [l.strip() for l in script.split('\n') if l.strip() and not l.strip().startswith('//')]
        preview = lines[0][:40] if lines else "script"
        command_type = f"script: {preview}..."

    logger.info(f"execute_script: {command_type} ({script_len} chars)")

    try:
        response = await execute_script_with_context(
            script=script,
            command_type=command_type,
            tool_name="illustrator_execute_script",
            params={"description": desc or "raw script", "length": script_len},
            timeout=params.timeout,
            includes=params.includes
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
                check_response = await execute_script_with_context(
                    script=check_script,
                    command_type="bounds_validation",
                    tool_name="illustrator_execute_script",
                    includes=["validate"]
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

        # B1: Inject preview_state into diagnostics BEFORE serialization
        # (eliminates the old json.loads→mutate→json.dumps roundtrip)
        has_error = response.get("error") is not None
        diagnostics["preview_state"] = "pre_execution" if has_error else "post_execution"

        # ── Occlusion guard: run AFTER script execution, BEFORE preview ──
        # Checks the POST-MUTATION document state (what the VLM would see).
        guard_telemetry = {}

        if is_vlm_checkpoint and not checkpoint_skipped:
            gcp = await _guard_checkpoint(
                timeout=params.timeout or 15.0,
                checkpoint_label="execute_script",
            )
            guard_telemetry = gcp.guard_telemetry
            diagnostics["guard_status"] = gcp.guard_status

            if gcp.should_abort:
                # ABORT: occlusion detected — skip annotated preview
                params.return_preview = False
                diagnostics.update(gcp.diag_extras)
                warnings.append(gcp.abort_message)

                # Build abort response: envelope + evidence + telemetry + checkpoint
                env_text = format_envelope(
                    response=response,
                    context=context,
                    warnings=warnings,
                    diagnostics=diagnostics,
                )
                abort_parts = [TextContent(type="text", text=env_text)]

                # Evidence preview (raw) — cheap proof of occlusion
                try:
                    from types import SimpleNamespace
                    evidence_params = SimpleNamespace(
                        preview_format="png",
                        preview_max_dim=800,
                        clip_box=None,
                    )
                    evidence_img = await _generate_preview(
                        params=evidence_params,
                        timeout=params.timeout or 15.0,
                    )
                    if evidence_img:
                        abort_parts.append(TextContent(
                            type="text",
                            text="Evidence preview (raw) — guard aborted before annotation.",
                        ))
                        abort_parts.append(evidence_img)
                except Exception as e:
                    logger.debug("Evidence preview skipped: %s", e)

                if gcp.telemetry_text:
                    abort_parts.append(TextContent(
                        type="text",
                        text=gcp.telemetry_text,
                    ))
                abort_parts.append(TextContent(
                    type="text",
                    text=VLM_CHECKPOINT_INSTRUCTION.format(
                        count=_counter.value
                    ),
                ))
                return abort_parts
            else:
                # Guard passed (possibly with Q004 warnings)
                warnings.extend(gcp.warn_messages)
        else:
            diagnostics["guard_status"] = "skipped"

        # Return standardized envelope
        # ── Auto-tag: post-exec scan (before envelope so diagnostics are included) ──
        if (
            params.auto_assign_ids != "off"
            and auto_tag_pre_count is not None
            and not response.get("error")
        ):
            try:
                _auto_tag_result = await _run_auto_tag(
                    mode=params.auto_assign_ids,
                    scope=params.auto_tag_scope,
                    cap=params.max_auto_tag,
                    pre_count=auto_tag_pre_count,
                    timeout=params.timeout,
                )
                if _auto_tag_result:
                    diagnostics["auto_assign_ids"] = _auto_tag_result
                    if _auto_tag_result.get("cap_hit"):
                        warnings.append(
                            f"Auto-tag cap hit: tagged {_auto_tag_result['tagged']}/{params.max_auto_tag} items. "
                            "Increase max_auto_tag or use auto_assign_ids='off' if unneeded."
                        )
            except Exception as e:
                logger.debug("Auto-tag post-scan failed: %s", e)
                diagnostics["auto_assign_ids"] = {"error": str(e)}

        envelope = format_envelope(
            response=response,
            context=context,
            warnings=warnings,
            diagnostics=diagnostics
        )

        # Auto-preview: export thumbnail and return as ImageContent
        if params.return_preview:
            try:
                preview_result = await _generate_preview(
                    params=params,
                    timeout=params.timeout
                )
                if preview_result:
                    # Annotated mode: overlay numbered boxes + return annotation map
                    if params.preview_mode == "annotated":
                        import base64 as _b64
                        raw_bytes = _b64.b64decode(preview_result.data)
                        annotated_bytes, annotation_result = await _annotate_preview(
                            img_bytes=raw_bytes,
                            max_items=params.preview_max_items,
                            timeout=params.timeout,
                            probe_points=params.probe_points,
                            clip_box=params.clip_box,
                        )
                        ann_b64 = _b64.b64encode(annotated_bytes).decode('utf-8')
                        result_parts = [
                            TextContent(type="text", text=envelope),
                        ]

                        # Dual-image at VLM checkpoints: raw + annotated
                        if is_vlm_checkpoint:
                            raw_b64 = preview_result.data  # already b64
                            result_parts.append(ImageContent(
                                type="image",
                                data=raw_b64,
                                mimeType=preview_result.mimeType,
                            ))

                        result_parts.append(ImageContent(
                            type="image",
                            data=ann_b64,
                            mimeType=preview_result.mimeType,
                        ))
                        result_parts.append(TextContent(
                            type="text",
                            text=json.dumps(annotation_result, indent=2),
                        ))

                        # Z-order telemetry (VLM checkpoints only)
                        if is_vlm_checkpoint and guard_telemetry and gcp.telemetry_text:
                            result_parts.append(TextContent(
                                type="text",
                                text=gcp.telemetry_text,
                            ))

                        # Clip box system note
                        if params.clip_box:
                            result_parts.append(TextContent(
                                type="text",
                                text=(
                                    f"\u26a0\ufe0f CLIP BOX ACTIVE: This preview shows a "
                                    f"high-resolution crop of region "
                                    f"{params.clip_box} (screen-space Y-down, points). "
                                    f"All element IDs and coordinates in the annotation "
                                    f"map are in GLOBAL document coordinates. "
                                    f"Use global coordinates for all subsequent edits."
                                ),
                            ))
                        # Cognitive Forcing Function: append checkpoint
                        # instruction as absolute LAST element so it has
                        # maximum recency weight in the LLM's attention.
                        if is_vlm_checkpoint:
                            result_parts.append(TextContent(
                                type="text",
                                text=VLM_CHECKPOINT_INSTRUCTION.format(
                                    count=_counter.value
                                ),
                            ))
                        return result_parts
                    else:
                        return [
                            TextContent(type="text", text=envelope),
                            preview_result
                        ]
                else:
                    # B2: Rebuild envelope with added warning (reuse diagnostics,
                    # don't call format_envelope a second time with stale state)
                    warnings.append("Preview generation returned empty")
                    env_text = format_envelope(
                        response=response,
                        context=context,
                        warnings=warnings,
                        diagnostics=diagnostics
                    )
                    if is_vlm_checkpoint:
                        return [
                            TextContent(type="text", text=env_text),
                            TextContent(type="text", text=VLM_CHECKPOINT_INSTRUCTION.format(count=_counter.value)),
                        ]
                    return env_text
            except Exception as e:
                # B2: Single rebuild with the preview failure warning
                warnings.append(f"Preview failed: {e}")
                env_text = format_envelope(
                    response=response,
                    context=context,
                    warnings=warnings,
                    diagnostics=diagnostics
                )
                if is_vlm_checkpoint:
                    return [
                        TextContent(type="text", text=env_text),
                        TextContent(type="text", text=VLM_CHECKPOINT_INSTRUCTION.format(count=_counter.value)),
                    ]
                return env_text
        return envelope

    except Exception as e:
        # B3: Decrement counter so failed executions don't pollute cadence
        _counter.decrement()
        logger.error(f"Script execution failed: {str(e)}")
        raise


# ── Backward-compatible re-exports ──────────────────────────────────
# These ensure existing imports like `from illustrator_mcp.tools.execute import X`
# continue to work from tests and import_svg.py.
from illustrator_mcp.tools.task_execution import (  # noqa: E402, F401
    ExecuteTaskInput,
    PathBooleanInput,
    illustrator_execute_task,
    illustrator_path_boolean,
)

__all__ = [
    # Cadence
    "_MutationCounter", "_counter", "VLM_QA_CADENCE", "VLM_CHECKPOINT_INSTRUCTION",
    "get_mutation_count", "reset_mutation_count",
    # Preview
    "_build_export_script", "_capture_artboard", "_capture_artboard_png",
    "_generate_preview", "_COLLECT_ITEMS_JSX", "_filter_items", "_annotate_preview",
    # Execute script
    "ExecuteScriptInput", "illustrator_execute_script",
    # Re-exports from task_execution
    "ExecuteTaskInput", "PathBooleanInput",
    "illustrator_execute_task", "illustrator_path_boolean",
]
