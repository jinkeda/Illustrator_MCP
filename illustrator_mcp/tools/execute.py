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
from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Literal, Optional, Union
from illustrator_mcp.tools.base import MutationInputBase
from illustrator_mcp.tools.bounds import BoundsType, BoundsSource, BoundsScope, BoundsPolicy, BoundsOptions, check_bounds
from pydantic import Field, model_validator
from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_envelope
from illustrator_mcp.execution.coordinator import HostUnresolvedError
from illustrator_mcp.results import finalize_tool_result
from mcp.types import CallToolResult
from illustrator_mcp.libraries import get_injection_metadata
from illustrator_mcp.tools.base import (
    ToolInputBase, TOOL_ANNOTATIONS, ABSTRACTION_LADDER, COORDINATE_SYSTEM_BLOCK,
)
from illustrator_mcp.tools import evidence
from illustrator_mcp.utils.load_script import load_script
from illustrator_mcp.utils.response import (
    JsxPayloadError, require_jsx_payload, unwrap_jsx_result,
)
from mcp.types import ImageContent, TextContent

# Import from sibling modules
from illustrator_mcp.tools.cadence import (
    _MutationCounter, _counter, VLM_QA_CADENCE,
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
# Fix 3: fresh pathPoints patterns.
#
# The gap before ``pathItems.add`` excludes semicolons so it cannot reach
# across a statement boundary. It used to be ``.*?``, which on a single-line
# script matched from the first declaration on the line all the way to a later
# ``add()`` call, capturing the wrong variable: given
# ``var doc = app.activeDocument; var z = doc.pathItems.add(); z.pathPoints[0]``
# it captured ``doc``, looked for ``doc.pathPoints[``, found none, and stayed
# silent about a script that does throw. Newlines hid this, since ``.`` does
# not cross them.
_ADD_PATH_VAR_RE = re.compile(
    r'(?:var|let|const)\s+(\w+)\s*=\s*[^;]*?pathItems\.add\s*\(\s*\)',
)
_ADD_PATH_ASSIGN_RE = re.compile(
    r'(\w+)\s*=\s*[^;]*?pathItems\.add\s*\(\s*\)',
)
_ADD_PATH_CHAINED_RE = re.compile(
    r'pathItems\.add\s*\(\s*\)\s*\.\s*pathPoints\s*\[',
)
# Fix 5: rectangle/ellipse call detection
_RECT_ELLIPSE_CALL_RE = re.compile(
    r'(?:rectangle|ellipse)\s*\(',
)
_MAX_ADVISORY_HINTS = 3

#: What counts as giving a fresh path its points. Indexing ``pathPoints`` is
#: only a mistake while the path is still empty, and these are the two ways it
#: stops being empty.
_POPULATES_PATH_RE_TMPL = r'\b{var}\.(?:setEntirePath\s*\(|pathPoints\.add\s*\()'


def _loop_bodies(script: str) -> "list[str]":
    """The source inside each ``for`` loop body.

    The batch-creation advisory used to test for a loop anywhere and two shape
    calls anywhere, with nothing tying the two together. A script whose loop
    converted coordinates and which separately created two paths matched both
    halves and was told to use batch creation, which was no help at all.

    Extracting the bodies lets the advisory ask the question it meant to ask:
    is anything being created *in* the loop.

    ``while`` is deliberately not covered, matching the rule this replaces.
    Widening what fires is a separate decision from making it accurate.
    """
    bodies: "list[str]" = []
    for match in _LOOP_RE.finditer(script):
        # Step over the loop header, which contains its own parentheses.
        depth, i = 0, match.end() - 1
        while i < len(script):
            if script[i] == '(':
                depth += 1
            elif script[i] == ')':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if i >= len(script):
            continue  # unbalanced header; nothing reliable to read

        i += 1
        while i < len(script) and script[i].isspace():
            i += 1
        if i >= len(script):
            continue

        if script[i] == '{':
            depth, start = 0, i + 1
            while i < len(script):
                if script[i] == '{':
                    depth += 1
                elif script[i] == '}':
                    depth -= 1
                    if depth == 0:
                        bodies.append(script[start:i])
                        break
                i += 1
        else:
            end = script.find(';', i)
            bodies.append(script[i:end if end != -1 else len(script)])
    return bodies


def _points_are_populated(script: str, var_name: str, start: int, end: int) -> bool:
    """Whether *var_name* is given points between two positions in the script.

    ``pathItems.add()`` returns a path with no points, so indexing them throws.
    But the documented way to build a path is to add it, call setEntirePath,
    and only then adjust the handles. Warning about that sequence contradicts
    this tool's own notes, so the span between creation and use is checked
    before the warning is raised.
    """
    if start >= end:
        return False
    pattern = _POPULATES_PATH_RE_TMPL.format(var=re.escape(var_name))
    return re.search(pattern, script[start:end]) is not None


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

    # Batch creation: shapes created *inside* a loop body. Counting calls
    # anywhere in the script matched coordinate-processing loops that happened
    # to sit near unrelated creation calls.
    if sum(len(_SHAPE_API_RE.findall(body)) for body in _loop_bodies(script)) >= 2:
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
        # Patterns 2 and 3 bind creation and use through a variable name, so
        # they can also see what happened in between. Indexing pathPoints is
        # only a mistake while the path is still empty; the documented way to
        # build one is add, setEntirePath, then adjust handles, and warning
        # about that sequence contradicts this tool's own notes.
        for pattern in (_ADD_PATH_VAR_RE, _ADD_PATH_ASSIGN_RE):
            if _fresh_path_warned:
                break
            for m in pattern.finditer(script):
                var_name = m.group(1)
                if var_name in ('var', 'let', 'const'):
                    continue  # already handled by the declared-variable pass
                use = re.search(
                    rf'\b{re.escape(var_name)}\.pathPoints\s*\[', script[m.end():]
                )
                if not use:
                    continue
                use_at = m.end() + use.start()
                if _points_are_populated(script, var_name, m.end(), use_at):
                    continue
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

    try:
        jsx_with_params = load_script("auto_tag", params={
            "mode": mode,
            "scope": scope,
            "cap": cap,
            "preCount": pre_count,
            "cushion": cushion,
        })
    except Exception as e:
        logger.warning("auto_tag script loading failed: %s", e)
        return None

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

    parsed = unwrap_jsx_result(resp, context="auto_tag")
    if not parsed:
        return None

    # Say plainly that this is not a complete account of what the script did.
    #
    # A raw script is opaque to this server: it can create, delete, restack and
    # restyle anything, and auto-tagging infers "what was created" from a count
    # delta plus a cushion, preferring the selection. That is a useful guess and
    # nothing more. The structured executor knows its own effects and reports
    # `effects.complete`; a raw script must never be read the same way, so the
    # diagnostics carry the distinction rather than leaving a reader to assume
    # the tagged set is the change set.
    parsed["complete"] = False
    parsed["basis"] = (
        "heuristic: selection first, then a count delta with a cushion"
        if mode == "delta" else f"scan of untagged items in scope '{scope}'"
    )
    parsed["covers"] = "items this scan could identify, not the script's full effect"
    return parsed


class ExecuteScriptInput(MutationInputBase):
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
        from illustrator_mcp.tools.preview import CaptureOptions
        self.clip_box = CaptureOptions(clip_box=self.clip_box, clip_space=self.clip_space).clip_box
        if not self.script and not self.file_path:
            raise ValueError("Provide either 'script' or 'file_path'")
        if self.script and self.file_path:
            raise ValueError("Provide 'script' or 'file_path', not both")
        if self.file_path:
            from pathlib import Path
            from illustrator_mcp.execution import get_coordinator
            path = str(Path(self.file_path).resolve())
            retained = get_coordinator().get(self.job_id) if self.job_id else None
            snapshot = retained.source_snapshot if retained and retained.label == "illustrator_execute_script" else None
            if snapshot and snapshot.get("path") == path and "scriptSource" in snapshot:
                self.script = snapshot["scriptSource"]
            else:
                if not os.path.isfile(path):
                    raise ValueError(f"Script file not found: {path}")
                with open(path, 'r', encoding='utf-8') as f:
                    self.script = f.read()
            self._script_source = self.script
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

    bounds_type: BoundsType = Field(
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

    bounds_scope: BoundsScope = Field(
        default="document",
        description="Scope: 'document' (all items) or 'artboard' (items on target artboard)"
    )

    bounds_source: BoundsSource = Field(
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

    clip_space: Literal["artboard_relative_y_down", "illustrator_native_y_up"] = "artboard_relative_y_down"

    clip_box: Optional[List[float]] = Field(
        default=None,
        description=(
            "Optional high-resolution crop region: [xmin, ymin, xmax, ymax] in "
            "artboard-relative Y-down points by default; clip_space can select native "
            "[left,top,right,bottom] Y-up coordinates. The preview captures a bounded "
            "region at the disclosed actual resolution. Annotations are culled and mapped "
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

    read_only: bool = Field(
        default=False,
        description=(
            "Declare that this script only reads. The server cannot tell a "
            "readback from an edit on its own, so without this every raw call "
            "counts as a mutation and can be asked to produce visual evidence "
            "for a script that changed nothing. Setting it skips the mutation "
            "counter, the occlusion guard and the evidence requirement. It is "
            "a claim about your script, not a sandbox: the script can still "
            "mutate. Server auto-tagging is forced off; item counts are only a limited mutation hint."
        ),
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
                    '"off": no tag scanning or tagging; read-only count hints remain. '
                    'Auto-tagging mutates item.note by writing @mcp:id= tags. '
                    'Read-only calls force off. Delta retains a zero-count cushion and may tag existing selected items; it is not a creation record. '
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


# TOOL_ANNOTATIONS, ABSTRACTION_LADDER, COORDINATE_SYSTEM_BLOCK imported at top of file

_NAME = "illustrator_execute_script"


# ── Phase decomposition types ─────────────────────────────────────

# dataclass, dc_field imported at top of file


@dataclass
class _ExecContext:
    """Shared state flowing through pre → post → present phases."""

    warnings: list = dc_field(default_factory=list)
    diagnostics: dict = dc_field(default_factory=dict)
    effective_auto_tag: str = "off"
    read_count_before: Optional[dict] = None
    auto_tag_pre_count: Optional[int] = None
    evidence: object = None  # evidence.EvidenceDecision for this call
    is_vlm_checkpoint: bool = False
    checkpoint_skipped: bool = False
    command_type: str = ""
    context: str = ""  # for format_envelope
    guard_result: Optional[GuardCheckpointResult] = None


def _mark_evidence(ctx, *, supplied: bool) -> None:
    """Record whether the required evidence was actually attached.

    Kept as one call so the several return paths cannot disagree about it,
    which is how the previous checkpoint text drifted across seven sites.
    """
    block = ctx.diagnostics.get("evidence")
    if isinstance(block, dict):
        block["evidenceSupplied"] = supplied


# ── Phase 1: Pre-execution ────────────────────────────────────────

def _pre_execute(params: ExecuteScriptInput, count: int) -> tuple:
    """Setup: safety overrides, precount, advisories, VLM cadence, diagnostics.

    Returns (script, ctx) where script is the potentially modified JS code.
    """
    script = params.script  # Already resolved by model_validator

    # Safety guard: inject max_ops / max_ms overrides if non-default
    safety_overrides = []
    if params.max_ops != 500000:
        safety_overrides.append(f"var __MCP_MAX_OPS = {params.max_ops};")
    if params.max_ms != 25000:
        safety_overrides.append(f"var __MCP_MAX_MS = {params.max_ms};")
    if safety_overrides:
        script = "\n".join(safety_overrides) + "\n" + script

    ctx = _ExecContext()

    # Abstraction advisory: non-blocking hints
    advisory_hints = _abstraction_advisory(script)
    if advisory_hints:
        ctx.warnings.extend(advisory_hints)

    # ── What verification does this edit require? ──
    #
    # A raw script is opaque: the server cannot classify what it did, so it
    # cannot reason about layout, clipping or boolean changes the way it can
    # for a structured batch. This path therefore keeps the backlog rule as
    # its trigger and says so in the reason, rather than guessing.
    decision = evidence.NO_EVIDENCE if params.read_only else (
        evidence.limit_to_available(
            evidence.decide(
                opaque_script=True,
                mutation_count=count,
                final_step=params.final_step,
            ),
            ("annotated", "raw"),
        )
    )
    ctx.evidence = decision

    if decision.required:
        declined = evidence.capture_declined(params.return_preview, final_step=params.final_step)
        if declined:
            # The requirement stands and is reported unmet; only capture is
            # suppressed. A skipped check that leaves no trace is how an
            # unverified document comes to look verified.
            ctx.checkpoint_skipped = True
        else:
            params.return_preview = True
            params.preview_mode = (
                "annotated" if decision.mode == "annotated" else "artboard"
            )
            ctx.is_vlm_checkpoint = True
            logger.info(
                "evidence required at mutation #%s: %s",
                count, ", ".join(decision.reason_values),
            )

    # Deterministic ES3 method support; resolver deduplicates explicit includes.
    params.includes = list(dict.fromkeys(["polyfills", *(params.includes or [])]))

    # Canonicalized includes metadata
    if params.includes:
        meta = get_injection_metadata(params.includes)
        includes_canonical = meta["includes_canonical"]
        prelude_hash = meta["prelude_hash"]
    else:
        includes_canonical = []
        prelude_hash = None

    ctx.diagnostics = {
        "includes": includes_canonical,
        "prelude_hash": prelude_hash,
        "validate_bounds": params.validate_bounds,
        "bounds_type": params.bounds_type,
        "bounds_source": params.bounds_source,
        "bounds_scope": params.bounds_scope,
        "artboard_index": params.artboard_index,
        "is_vlm_checkpoint": ctx.is_vlm_checkpoint,
        "evidence": evidence.diagnostics(decision, evidence_supplied=False),
    }

    ctx.effective_auto_tag = "off" if params.read_only else params.auto_assign_ids
    ctx.diagnostics["autoTagMode"] = ctx.effective_auto_tag
    if params.read_only and "auto_assign_ids" in params.model_fields_set and params.auto_assign_ids != "off":
        ctx.warnings.append("read_only forces auto_assign_ids off; explicit " + params.auto_assign_ids + " was ignored.")

    # Command type for CEP panel
    desc = params.description.strip() if params.description else None
    if desc:
        ctx.command_type = desc[:50]
    else:
        lines = [l.strip() for l in script.split('\n') if l.strip() and not l.strip().startswith('//')]
        preview = lines[0][:40] if lines else "script"
        ctx.command_type = f"script: {preview}..."

    ctx.context = f"execute_script: {desc}" if desc else "execute_script"

    # Keep the helper out of trusted connectivity probes and shared wrappers.
    from illustrator_mcp.utils.load_script import load_inline_script
    script = load_inline_script("raw_fail.jsx") + "\n" + script
    return script, ctx


# ── Phase 2: Pre-execution async (precount) ───────────────────────

async def _pre_execute_async(params: ExecuteScriptInput, ctx: _ExecContext) -> _ExecContext:
    """Async pre-execution: auto-tag precount (requires bridge call)."""
    if params.read_only:
        ctx.read_count_before = await _read_count_hint()
    if not params.read_only and params.auto_assign_ids != "off":
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
            # A lost payload must not read as a baseline of zero: auto-tagging
            # infers "what was created" from the delta against this number, so
            # zero makes every pre-existing item look newly created.  The
            # strict unwrapper raises instead of returning an empty dict, which
            # lands in the handler below and skips auto-tagging — the same
            # degradation this block already applies to an execution failure.
            _count_data = require_jsx_payload(
                _count_resp,
                context="auto_tag_precount",
                required_keys=("count",),
            )
            _pre_count = _count_data["count"]
            if isinstance(_pre_count, bool) or not isinstance(_pre_count, int):
                raise JsxPayloadError(
                    f"auto-tag pre-count is {type(_pre_count).__name__}, "
                    "expected an int"
                )
            ctx.auto_tag_pre_count = _pre_count
        except Exception as e:
            logger.debug("Auto-tag pre-count failed: %s", e)
            ctx.auto_tag_pre_count = None  # Graceful degradation: skip auto-tag
    return ctx


async def _read_count_hint():
    """Compare document-wide populations, never two different active layers."""
    from illustrator_mcp.execution import get_coordinator
    try:
        get_coordinator().assert_host_available()
        response = await execute_script_with_context(
            script="(function(){var d=app.activeDocument;return JSON.stringify({count:d.pageItems.length,token:mcpDocBind().token});})()",
            command_type="read_only_count", tool_name=_NAME, timeout=5.0,
            includes=["doc_session"],
        )
        data = require_jsx_payload(response, context="read_only_count", required_keys=("count", "token"))
        if type(data["count"]) is not int or not data["token"]:
            return None
        return data
    except Exception:
        return None


# ── Phase 3: Post-execution ───────────────────────────────────────

async def _post_execute(
    response: dict,
    params: ExecuteScriptInput,
    ctx: _ExecContext,
) -> tuple:
    """Post-execution hooks. Runs exactly once after successful execution.

    Order: bounds validation → preview_state → guard → auto-tag.
    Guard computes result but does NOT return early — _present handles abort.
    Auto-tag always runs (if mode != off) regardless of guard outcome.

    Returns (response, ctx) with updated diagnostics/warnings.
    """
    if params.read_only:
        after = None if response.get("error") or response.get("execution") == "unknown" else await _read_count_hint()
        before = ctx.read_count_before
        comparable = before is not None and after is not None and before["token"] == after["token"]
        ctx.diagnostics["readOnlyCountHint"] = {
            "before": before, "after": after, "scope": "document",
            "status": "comparable" if comparable else "unavailable",
            "completeMutationDetection": False,
        }
        if comparable and before["count"] != after["count"]:
            ctx.warnings.append("Declared read-only script changed the observed document item count; counts do not detect all mutations.")
        elif comparable:
            ctx.diagnostics["readOnlyCountHint"]["detail"] = "Unchanged counts do not prove preservation (styles, notes and equal-count replacement are unobserved)."

    # ── Bounds validation ──
    if params.validate_bounds:
        try:
            bounds = await check_bounds(execute_script_with_context,
                options=BoundsOptions(artboardIndex=params.artboard_index,
                    boundsType=params.bounds_type, boundsSource=params.bounds_source,
                    scope=params.bounds_scope, ignoreHidden=params.ignore_hidden,
                    ignoreLocked=params.ignore_locked),
                command="bounds_validation", tool="illustrator_execute_script")
            ctx.diagnostics["validation_result"] = bounds
            ctx.diagnostics["boundsVerification"] = {
                "status": "failed" if bounds["off_artboard"] else "passed", "findings": bounds}
            if bounds["off_artboard"]:
                ctx.warnings.append(f"{bounds['off_artboard']} items outside artboard bounds (policy: fully-contained, {params.bounds_type}Bounds)")
        except Exception as exc:
            ctx.diagnostics["boundsVerification"] = {"status": "unavailable", "detail": str(exc)}
            ctx.warnings.append(f"Bounds validation failed: {exc}")

    # ── Preview state injection ──
    has_error = response.get("error") is not None
    ctx.diagnostics["preview_state"] = "pre_execution" if has_error else "post_execution"

    # ── Occlusion guard ──
    if ctx.is_vlm_checkpoint and not ctx.checkpoint_skipped:
        gcp = await _guard_checkpoint(
            timeout=params.timeout or 15.0,
            checkpoint_label="execute_script",
        )
        ctx.guard_result = gcp
        ctx.diagnostics["guard_status"] = gcp.guard_status

        # Geometry the guard finds suspicious raises the requirement, using the
        # guard's own tiers rather than a second set of numbers.
        if ctx.evidence is not None:
            ctx.evidence = evidence.escalate_for_geometry(
                ctx.evidence, gcp.guard_telemetry
            )
            ctx.diagnostics["evidence"] = evidence.diagnostics(
                ctx.evidence,
                evidence_supplied=ctx.diagnostics.get(
                    "evidence", {}).get("evidenceSupplied", False),
            )

        if gcp.should_abort:
            # Mark for abort in _present, but do NOT return early
            params.return_preview = False
            ctx.diagnostics.update(gcp.diag_extras)
            ctx.warnings.append(gcp.abort_message)
        else:
            # Guard passed (possibly with Q004 warnings)
            ctx.warnings.extend(gcp.warn_messages)
    else:
        ctx.diagnostics["guard_status"] = "skipped"

    # ── Auto-tag (always runs if mode != off, regardless of guard outcome) ──
    if (
        not params.read_only
        and params.auto_assign_ids != "off"
        and ctx.auto_tag_pre_count is not None
        and not response.get("error")
    ):
        try:
            _auto_tag_result = await _run_auto_tag(
                mode=params.auto_assign_ids,
                scope=params.auto_tag_scope,
                cap=params.max_auto_tag,
                pre_count=ctx.auto_tag_pre_count,
                timeout=params.timeout,
            )
            if _auto_tag_result:
                ctx.diagnostics["auto_assign_ids"] = _auto_tag_result
                if _auto_tag_result.get("tagged"):
                    ctx.warnings.append(
                        f"Auto-tagged {_auto_tag_result['tagged']} item(s) after a raw "
                        "script. This is an inferred set, not a complete record of "
                        "what the script changed — use illustrator_execute_task for "
                        "operations whose effects must be known."
                    )
                if _auto_tag_result.get("cap_hit"):
                    ctx.warnings.append(
                        f"Auto-tag cap hit: tagged {_auto_tag_result['tagged']}/{params.max_auto_tag} items. "
                        "Increase max_auto_tag or use auto_assign_ids='off' if unneeded."
                    )
        except Exception as e:
            logger.debug("Auto-tag post-scan failed: %s", e)
            ctx.diagnostics["auto_assign_ids"] = {"error": str(e)}

    return response, ctx


# ── Phase 4: Presentation ─────────────────────────────────────────

async def _present(
    response: dict,
    params: ExecuteScriptInput,
    ctx: _ExecContext,
) -> Union[str, list]:
    """Build final response. No mutations — only formatting, preview, VLM packaging.

    Preview export (PNG generation) is the only side-effect: read-only export.
    """
    # Compute envelope once
    envelope = format_envelope(
        response=response,
        context=ctx.context,
        warnings=ctx.warnings,
        diagnostics=ctx.diagnostics,
    )

    # ── Guard abort path ──
    gcp = ctx.guard_result
    if gcp and gcp.should_abort:
        abort_parts = [TextContent(type="text", text=envelope)]

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
        if ctx.evidence is not None and ctx.evidence.required:
            abort_parts.append(TextContent(
                type="text",
                text=evidence.requirement_text(
                    ctx.evidence,
                    evidence_supplied=any(
                        isinstance(b, ImageContent) for b in abort_parts
                    ),
                ),
            ))
        return abort_parts

    # ── Preview generation (read-only export) ──
    if params.return_preview:
        try:
            preview_result = await _generate_preview(
                params=params,
                timeout=params.timeout
            )
            if preview_result:
                from illustrator_mcp.tools.preview import capture_metadata
                ctx.diagnostics["capture"] = capture_metadata.get()
                envelope = format_envelope(response=response, context=ctx.context, warnings=ctx.warnings, diagnostics=ctx.diagnostics)
                if params.preview_mode == "annotated":
                    import base64 as _b64
                    raw_bytes = _b64.b64decode(preview_result.data)
                    annotated_bytes, annotation_result = await _annotate_preview(
                        img_bytes=raw_bytes,
                        max_items=params.preview_max_items,
                        timeout=params.timeout,
                        probe_points=params.probe_points,
                        clip_box=params.clip_box, clip_space=params.clip_space,
                    )
                    ann_b64 = _b64.b64encode(annotated_bytes).decode('utf-8')
                    result_parts = [
                        TextContent(type="text", text=envelope),
                    ]

                    # Dual-image at VLM checkpoints: raw + annotated
                    if ctx.is_vlm_checkpoint:
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
                    if ctx.is_vlm_checkpoint and gcp and gcp.telemetry_text:
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

                    # VLM checkpoint instruction — last for maximum recency weight
                    # Skip checkpoint on empty canvas (0 annotations = nothing to review)
                    if ctx.is_vlm_checkpoint:
                        ann_count = annotation_result.get("meta", {}).get("annotated_count", 0)
                        if ann_count == 0:
                            # Nothing on the page to review. The requirement is
                            # not silently dropped: it is reported unmet, which
                            # is what "unavailable" means everywhere else in
                            # this codebase — wanted, but not obtainable.
                            ctx.diagnostics["checkpoint_skipped_empty_canvas"] = True
                            _mark_evidence(ctx, supplied=False)
                            result_parts.append(TextContent(
                                type="text",
                                text=(
                                    "Verification unavailable: checkpoint skipped "
                                    "on an empty canvas (0 annotations)."
                                ),
                            ))
                        elif ctx.evidence is not None:
                            _mark_evidence(ctx, supplied=True)
                            # The envelope was serialised before this capture,
                            # so the dict update above cannot reach the client;
                            # stamp the built string too.
                            result_parts[0] = TextContent(
                                type="text",
                                text=evidence.stamp_supplied(
                                    result_parts[0].text, ctx.evidence,
                                    supplied=True,
                                ),
                            )
                            result_parts.append(TextContent(
                                type="text",
                                text=evidence.requirement_text(
                                    ctx.evidence, evidence_supplied=True
                                ),
                            ))
                    return result_parts
                else:
                    return [
                        TextContent(type="text", text=envelope),
                        preview_result
                    ]
            else:
                # Preview returned empty — rebuild envelope with warning
                ctx.warnings.append("Preview generation returned empty")
                envelope = format_envelope(
                    response=response,
                    context=ctx.context,
                    warnings=ctx.warnings,
                    diagnostics=ctx.diagnostics,
                )
                if ctx.is_vlm_checkpoint and ctx.evidence is not None:
                    return [
                        TextContent(type="text", text=envelope),
                        TextContent(type="text", text=evidence.requirement_text(
                            ctx.evidence, evidence_supplied=False)),
                    ]
                return envelope
        except Exception as e:
            # Preview failed — rebuild envelope with warning
            ctx.warnings.append(f"Preview failed: {e}")
            envelope = format_envelope(
                response=response,
                context=ctx.context,
                warnings=ctx.warnings,
                diagnostics=ctx.diagnostics,
            )
            if ctx.is_vlm_checkpoint and ctx.evidence is not None:
                return [
                    TextContent(type="text", text=envelope),
                    TextContent(type="text", text=evidence.requirement_text(
                        ctx.evidence, evidence_supplied=False)),
                ]
            return envelope

    # ── No preview: return envelope only ──
    return envelope


# ── Main tool function ─────────────────────────────────────────────

@mcp.tool(name=_NAME, annotations=TOOL_ANNOTATIONS[_NAME])
async def illustrator_execute_script(params: ExecuteScriptInput) -> CallToolResult:
    """Execute raw JavaScript/ExtendScript code in Adobe Illustrator.

    CONTRACT: readOnly=False, destructive=True, idempotent=False, openWorld=True

    WHEN TO USE:
      - Single one-off items, quick prototypes, or operations not covered by higher-level tools
      - Full DOM access when structured tools are insufficient
      - Reading document state with custom logic
      - To SEE the artwork, use illustrator_observe instead: it returns the
        image inline with a numbered map of items, their handles and bounds,
        so there is no file to export, locate and open

    EXECUTION CONTRACT:
      Your script is evaluated at the top level, not inside a function.
        - The value of the LAST EXPRESSION is the result. End with the value
          you want back, usually a JSON.stringify(...) call.
        - A bare `return` is a syntax error: "Illegal return outside of a
          function body". Wrap the code in a function and call it immediately
          when you need an early exit.
        - Returning an object is fine; it is serialised for you. Returning
          nothing is a valid outcome and is reported as data: null.
      Injected helper libraries are declared at the same top level, so they
      are in scope either way. See EXAMPLES for both forms.
      Top-level {ok:false}, {success:false}, or a string error field produces
      a warning, not an execution failure. Nested values remain opaque.
      Use throw or mcpFail(message, details) for an explicit failure:
        try { doWork(); } catch (e) { mcpFail("Label failed", {cause:String(e)}); }
      mcpFail throws an ordinary catchable Error; details are bounded to 2048
      characters. Neither throwing nor returning an error rolls back edits.
      Host line numbers, when available, refer to injected host code, not
      necessarily to the caller's source lines. Verification is separate.

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
      - Geometry helpers use artboard-relative coordinates: origin at the active
        artboard's top-left, with y increasing downward (screen space)
      - Raw Illustrator DOM positions use document-space coordinates, with y
        increasing upward; do not assume that the active artboard starts at (0, 0)
      - Units: points (1 pt = 1/72 inch)

    HELPERS — ARTBOARD-RELATIVE, Y-DOWN (includes: ['geometry']):
      Use these to avoid manual conversion to raw document coordinates:
        rectXY(x, y, w, h)          — rectangle at screen-space (x,y)
        ellipseXY(x, y, w, h)       — ellipse at screen-space (x,y)
        lineXY(x1, y1, x2, y2)      — line between screen-space points
        polygonXY([[x,y],...], closed)— polygon from screen-space points
        pointXY(x, y)               — returns {left, top} for position assignments
        drawPathPoints(spec)         — full path with handles, UUID, heap registration
      Example: var rect = rectXY(100, 200, 50, 30);  // no -y needed

    RAW DOM — DOCUMENT-SPACE, Y-UP (only when helpers are insufficient):
      These are API snippets to put inside a script, not tool calls. Convert
      an artboard-relative point before passing it to the DOM:
        var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
        var position = [ab[0] + x, ab[1] - y];
        // Nonzero-origin example: ab top-left (72, 720), (x, y) = (100, 200)
        // gives the raw DOM position [172, 520].
        Rectangle: doc.pathItems.rectangle(position[1], position[0], width, height)
          ⚠ width & height must be POSITIVE. Negative height → shape above artboard (invisible).
        Ellipse: doc.pathItems.ellipse(position[1], position[0], width, height)
        Line: convert each artboard-relative point with the same ab-offset formula
        Color: var c = new RGBColor(); c.red=255; c.green=0; c.blue=0; shape.fillColor = c;
        Text: var tf = doc.textFrames.add(); tf.contents = "text"; tf.position = position;
        Grid helpers: artboardGrid(cols, rows), itemsInCell(cell, mode)

    EXAMPLES:
      Read with a native-coordinate crop:
        {
          "params": {
            "script": "app.activeDocument.name;",
            "return_preview": true,
            "clip_box": [
              0,
              125,
              125,
              0
            ],
            "clip_space": "illustrator_native_y_up"
          }
        }
      Draw in artboard-relative Y-down coordinates with geometry helpers:
        {
          "params": {
            "script": "var r = rectXY(50, 80, 200, 100); r.fillColor = makeRGBColor(255, 0, 0); r.name;",
            "includes": [
              "geometry"
            ],
            "description": "red banner"
          }
        }
      Position text from an offset artboard using raw DOM coordinates:
        {
          "params": {
            "script": "var doc = app.activeDocument; var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect; var x = 100; var y = 200; var tf = doc.textFrames.add(); tf.contents = 'Offset'; tf.position = [ab[0] + x, ab[1] - y]; tf.position;",
            "description": "raw DOM offset-artboard placement"
          }
        }
      Read state back; the last expression is the result:
        {"params": {"script": "JSON.stringify({items: app.activeDocument.pageItems.length});"}}
      Return early, which needs a function wrapper:
        {
          "params": {
            "script": "(function () { var d = app.activeDocument; if (d.pageItems.length === 0) return 'empty'; return d.pageItems[0].name; })()"
          }
        }
      A readback, declared so it is not treated as an edit:
        {
          "params": {
            "script": "JSON.stringify({name: app.activeDocument.name});",
            "read_only": true
          }
        }

    ELEMENT DISCOVERY:
      - Use artboardGrid(cols, rows) to partition the artboard into a labeled grid
      - Use itemsInCell(cell, mode) to find items in a specific grid cell
      - Modes: 'containsCenter' (default) or 'intersects'
      - Cell labels follow A1 scheme (letter row + number col, e.g. A1, B3)

    MUTATION SAFETY:
      - Each call increments a per-document mutation counter
      - Failed executions decrement it again, so failures do not accumulate
      - A raw script is opaque to this server, so it cannot tell which kind of
        change you made. Evidence is therefore requested on a backlog rule
        rather than on the operations performed, unlike illustrator_execute_task
      - Use final_step=true on the last mutation to require final evidence

    NOTES:
      - When evidence is required the result carries a VERIFICATION REQUIRED
        block naming what to confirm, and diagnostics.evidence says whether an
        image was actually supplied
      - return_preview=false suppresses capture but not the requirement, which
        is then reported unmet rather than dropped
      - setEntirePath() creates corner points only; set handles after creation
      - ExtendScript can access File/Folder and OS — treat as open-world

    SAFETY:
      - __mcp_check() watchdog: call as FIRST line inside every for/while body
      - Never iterate live Illustrator collections if adding/removing items
      - Use __mcp_forEachSnapshot(collection, fn) or __mcp_snapshot(collection) instead
    """
    # A declared read does not advance the cadence. Counting reads is what
    # let a script that only returned document properties be asked to verify
    # itself visually, citing an opaque script and geometry it never touched.
    from illustrator_mcp.execution.logical_job import run_logical_job
    async def body(job):
        count = _counter.value if params.read_only else _counter.increment()
        script, ctx = _pre_execute(params, count)
        ctx = await _pre_execute_async(params, ctx)
        response = await execute_script_with_context(
            script=script, command_type=ctx.command_type,
            tool_name=_NAME,
            params={"description": params.description or "raw script", "length": len(script)},
            timeout=params.timeout, includes=params.includes,
        )
        from illustrator_mcp.utils.response import normalize_raw_script_response
        response = normalize_raw_script_response(response)
        value = response.get("_rawScriptValue")
        if isinstance(value, dict) and (
            value.get("ok") is False or value.get("success") is False
            or isinstance(value.get("error"), str)
        ):
            ctx.warnings.append(
                "The top-level return value looks like a failure, but raw values "
                "are opaque and do not change execution status. Use throw or "
                "mcpFail(message, details) to fail the call. Prior edits are not rolled back."
            )
        response, ctx = await _post_execute(response, params, ctx)
        return await _present(response, params, ctx)
    try:
        return await run_logical_job(_NAME, params, body)
    except Exception:
        if not params.read_only:
            _counter.decrement()
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
    "_MutationCounter", "_counter", "VLM_QA_CADENCE",
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
