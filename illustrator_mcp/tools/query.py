"""
Task Protocol Query Tools - Pilot refactor using new Task Protocol.

Demonstrates how to use the task protocol with declarative target selection
for more structured, observable, and debuggable operations.
"""

import json
from typing import Dict, Any, List, Optional, Literal
from illustrator_mcp.tools.bounds import BoundsType, BoundsSource, BoundsScope, BoundsPolicy, BoundsOptions, check_bounds
from pydantic import BaseModel, ConfigDict, Field, model_validator
from illustrator_mcp.protocol import TargetSelector

import logging
from mcp.types import CallToolResult
from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_envelope, note_host_truncation
from illustrator_mcp.libraries import get_injection_metadata
from illustrator_mcp.errors import ErrorCode, make_envelope
from illustrator_mcp.tools.base import ToolInputBase, TOOL_ANNOTATIONS, canonical_tool
from illustrator_mcp.utils.response import JsxPayloadError, require_jsx_payload

logger = logging.getLogger("illustrator_mcp")


class QueryItemsInput(ToolInputBase):
    """Input for querying items using declarative target selector.
    
    Accepts flat or wrapped selectors of type selection, all, layer, query,
    id, handle, spatial, grid, or compound (anyOf, including nested compounds).
    Ordering, exclusions and maxScan survive normalization. Unknown fields
    are rejected, including nested filters. Prefer targets; the legacy target
    alias is accepted unless it conflicts with targets.
    """

    model_config = {"populate_by_name": True}

    targets: TargetSelector = Field(
        default_factory=lambda: TargetSelector.model_validate({"type": "selection"}),
        description=(
            "Task Protocol target selector. Examples: "
            "{'type': 'selection'}, "
            "{'type': 'layer', 'layer': 'Layer 1'}, "
            "{'type': 'all'}, "
            "{'type': 'query', 'itemType': 'PathItem', 'pattern': 'rect_*'}"
        )
    )

    @model_validator(mode="before")
    @classmethod
    def accept_target_alias(cls, value):
        if isinstance(value, dict) and "target" in value:
            value = dict(value)
            alias = value.pop("target")
            if "targets" in value and TargetSelector.model_validate(value["targets"]) != TargetSelector.model_validate(alias):
                raise ValueError("Conflicting target and targets; use targets")
            value.setdefault("targets", alias)
        return value

    include_trace: bool = Field(
        default=False,
        description="Include execution trace in response"
    )

    debug: bool = Field(
        default=False,
        description="Return raw response for debugging"
    )

    include_handles: bool = Field(
        default=True,
        description=(
            "Return expiring document-scoped handles for exact follow-up edits. "
            "Handles do not write item notes."
        ),
    )


_QUERY_NAME = "illustrator_query_items"


@mcp.tool(name=_QUERY_NAME, annotations=TOOL_ANNOTATIONS[_QUERY_NAME])
@canonical_tool(_QUERY_NAME, reserve=False)
async def illustrator_query_items(params: QueryItemsInput) -> CallToolResult:
    """Query items using the Task Protocol with declarative target selection.

    CONTRACT: readOnly=True, destructive=False, idempotent=True, openWorld=False

    WHEN TO USE:
      - Finding items by type, name pattern, or location before modification
      - Inspecting current selection
      - Listing all items on a layer or in the document

    TARGET SELECTORS:
      {type: "selection"} — current selection (default)
      {type: "layer", layer: "Layer 1"} — all items on layer
      {type: "all", recursive: true} — all items in document
      {type: "query", itemType: "PathItem", pattern: "axis_*"} — filter by type/name

    EXAMPLES:
      Require exactly one matching text label:
        {
          "params": {
            "targets": {
              "type": "query",
              "contents": "alpha-helix",
              "expect": {
                "count": 1
              }
            }
          }
        }
      Every path whose name starts with axis_:
        {"params": {"targets": {"type": "query", "itemType": "PathItem", "pattern": "axis_*"}}}
      Everything on a named layer:
        {"params": {"targets": {"type": "layer", "layer": "Layer 1"}}}

    NOTES:
      - Returns ItemRef plus an expiring handle for exact untagged follow-up edits
      - Handle issuance never writes item.note or item.name
      - Set include_trace=True for debugging
    """
    
    # Use targets directly from input (already matches Task Protocol format)
    targets = params.targets.model_dump(mode="json", exclude_none=True)
    
    # Build payload
    payload = {
        "task": "query_items",
        "targets": targets,
        "params": {},
        "options": {
            # T03: no dryRun here.  This pipeline is read-only because its
            # compute stage only reads item properties and its apply stage is
            # a no-op — not because a flag says so.  dryRun is now rejected
            # during validation, since in batch mode it could not prevent
            # mutation and said otherwise.
            "trace": params.include_trace
        }
    }
    
    payload_json = json.dumps(payload)
    include_handles_js = "true" if params.include_handles else "false"
    
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
            message: "task_pipeline.jsx library not properly loaded",
            stage: "preflight",
            details: _libraryCheck
        }}],
        stats: {{ itemsProcessed: 0 }},
        timing: {{ total_ms: 0 }}
    }});
}} else {{
    // Compute function - gather item info AND store in artifacts
    // (read-only: property reads only, no DOM writes)
    function compute(items, params, report) {{
        var actions = [];
        report.artifacts = report.artifacts || {{}};
        report.artifacts.items = [];
        
        for (var i = 0; i < items.length; i++) {{
            var item = items[i];
            var itemRef = describeItemV2(item, {{includeIdentity: true, includeTags: true}});
            var handleResult = {include_handles_js} && typeof mcpIssueHandle === "function"
                ? mcpIssueHandle(item) : null;
            var itemData = {{
                itemRef: itemRef,
                handle: handleResult && handleResult.ok ? handleResult.record.handle : null,
                handleExpiresAt: handleResult && handleResult.ok ? handleResult.record.expiresAt : null,
                name: item.name || "(unnamed)",
                type: item.typename,
                bounds: {{
                    left: item.left,
                    top: item.top,
                    width: item.width,
                    height: item.height,
                    space: "illustrator_native_y_up",
                    units: "pt"
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
        // No-op: query is read-only; items were stored during compute.
    }}

    // Execute task
    var payload = {payload_json};
    var report = executeTask(payload, collectTargets, compute, apply);
    JSON.stringify(report);
}}
"""
    
    # Get canonicalized includes metadata for diagnostics
    meta = get_injection_metadata(["task_pipeline"])
    diagnostics = {
        "targets": targets,
        "includes": meta["includes_canonical"],
        "prelude_hash": meta["prelude_hash"]
    }

    response = await execute_script_with_context(
        script=script,
        command_type="query_items",
        tool_name="illustrator_query_items",
        params=params.model_dump(),
        includes=["task_pipeline"]
    )

    # Check for pipeline-level errors (connection, library injection, etc.)
    note_host_truncation(diagnostics, response)
    if response.get("error"):
        return format_envelope(response, context="query_items", diagnostics=diagnostics)

    # Debug mode: return raw response
    if params.debug:
        debug_output = {
            "raw_response": response,
            "script_length": len(script),
            "script_preview": script[:500] + "..." if len(script) > 500 else script
        }
        return make_envelope(
            ok=True,
            result=debug_output,
            diagnostics=diagnostics,
        )

    # Parse response and return standardized envelope
    try:
        # The host serializes the task report inside its own data envelope.
        # Decode that layer before interpreting query statistics or errors.
        from illustrator_mcp.utils.response import unwrap_jsx_result
        report = unwrap_jsx_result(response, context="query_items")
        if not report:
            require_jsx_payload(response, context="query_items", required_keys=("ok",))

        # Extract warnings from report (if any)
        warnings = []
        for w in report.get("warnings", []):
            if isinstance(w, dict):
                warnings.append(w.get("message", str(w)))
            else:
                warnings.append(str(w))

        # Check for errors in report
        # makeError() returns {ok:false, error:{code, message, ...}} — unwrap nested shape
        errors = report.get("errors", [])
        if errors:
            err = errors[0]
            # Handle both flat {code, message} and nested {ok, error:{code, message}} shapes
            if isinstance(err, dict) and "error" in err and isinstance(err["error"], dict):
                err = err["error"]
            error_msg = err.get("message", "Unknown error") if err else "Query failed"
            error_code = err.get("code", ErrorCode.R_QUERY_FAILED.value) if err else ErrorCode.R_QUERY_FAILED.value
            return make_envelope(
                ok=False,
                error={**err, "code": error_code, "message": error_msg},
                warnings=warnings,
                diagnostics={**diagnostics, "report": report},
            )

        # ok is authoritative: reflect report status in envelope
        if report.get("ok", True):
            # Diagnostic hint when query returns 0 items
            stats = report.get("stats", {})
            if stats.get("itemsProcessed", -1) == 0:
                warnings.append(
                    "Query returned 0 items. Common causes: "
                    "(1) hidden or locked layers, "
                    "(2) items inside clipping masks, "
                    "(3) items in hidden groups, "
                    "(4) wrong active document, "
                    "(5) all items are guides."
                )
            return make_envelope(
                ok=True,
                result=report,
                warnings=warnings,
                diagnostics=diagnostics,
            )
        else:
            # Option B: extract error from report, key stats in diagnostics
            report_errors = report.get("errors", [])
            first_err = report_errors[0] if report_errors else {}
            if isinstance(first_err, dict) and "error" in first_err and isinstance(first_err["error"], dict):
                first_err = first_err["error"]
            return make_envelope(
                ok=False,
                error={
                    "code": first_err.get("code", ErrorCode.R_QUERY_FAILED.value),
                    "message": first_err.get("message", "Query returned failure"),
                    "suggestions": first_err.get("suggestions", []),
                },
                warnings=warnings,
                diagnostics={**diagnostics, "stats": report.get("stats", {})},
            )

    except (json.JSONDecodeError, JsxPayloadError) as e:
        return make_envelope(
            ok=False,
            error={"code": ErrorCode.C_JSON_PARSE.value, "message": str(e)},
            diagnostics=diagnostics,
        )


# ==================== Preflight Check Tool ====================


class PublicationThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    output_width_mm: Optional[float] = Field(None, gt=0)
    min_font_pt: Optional[float] = Field(None, gt=0)
    min_stroke_pt: Optional[float] = Field(None, gt=0)
    min_image_ppi: Optional[float] = Field(None, gt=0)
    expected_color_mode: Optional[Literal["RGB", "CMYK"]] = None


class PreflightCheckInput(ToolInputBase):
    """Input for preflight document validation."""

    artboard_index: Optional[int] = Field(
        default=None,
        description="Artboard index to check (None = active artboard)"
    )

    bounds_type: BoundsType = Field(
        default="visible",
        description="Bounds type for validation: 'visible' (includes strokes/effects) or 'geometric' (path only)"
    )

    bounds_source: BoundsSource = Field(
        default="group_visible",
        description="Bounds source: 'group_visible' (default) or 'clipping_path' (use clipping path bounds for clipped groups)"
    )

    policy: BoundsPolicy = Field(
        default="fully-contained",
        description="Containment policy: 'fully-contained' (entire item on artboard) or 'intersects' (any overlap)"
    )

    scope: BoundsScope = Field(
        default="document",
        description="Item scope: 'document' (all items) or 'artboard' (items on target artboard)"
    )

    publication: Optional[PublicationThresholds] = Field(
        default=None,
        description=("Run bounded publication measurements instead of legacy preflight checks. "
                     "Omitted legacy options are reported in legacy_preflight; explicitly requested "
                     "omitted checks make verification unavailable. Run without publication for those checks."),
    )
    scan_max_items: int = Field(10000, gt=0, strict=True)
    scan_budget_ms: int = Field(2000, gt=0, strict=True)

    @model_validator(mode="after")
    def publication_scope(self):
        if self.publication is not None:
            if "scope" in self.model_fields_set and self.scope != "artboard":
                raise ValueError("Publication requires artboard scope; nextStep: omit scope or choose artboard")
            self.scope = "artboard"
        return self

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


_PREFLIGHT_NAME = "illustrator_preflight_check"

#: The minimum payload a preflight scan must return to count as having run.
#: A genuinely empty document still reports all three (with an empty ``issues``
#: list), so their absence means evidence was lost, not that nothing was found.
_PREFLIGHT_REQUIRED_KEYS = ("checks", "issues", "summary")


@mcp.tool(name=_PREFLIGHT_NAME, annotations=TOOL_ANNOTATIONS[_PREFLIGHT_NAME])
@canonical_tool(_PREFLIGHT_NAME, reserve=False)
async def illustrator_preflight_check(params: PreflightCheckInput) -> CallToolResult:
    """Perform observational validation on the active document.

    CONTRACT: readOnly=True, destructive=False, idempotent=True, openWorld=False

    WHEN TO USE:
      - Before export to catch common issues
      - Validating document state after a series of modifications

    KEY CONCEPTS:
      Checks for: items outside artboard bounds, zero-size items,
      empty text frames, locked layers/items.
      Does NOT modify the document.

    EXAMPLES:
      Check supplied publication thresholds:
        {
          "params": {
            "publication": {
              "output_width_mm": 89,
              "min_font_pt": 5,
              "min_stroke_pt": 0.25,
              "min_image_ppi": 300
            }
          }
        }
      Check the active artboard before exporting:
        {"params": {}}
      Check one artboard, counting any overlap as on-artboard:
        {"params": {"artboard_index": 0, "policy": "intersects"}}

    NOTES:
      - Returns ok=true only when the scan ran and found no non-info issues
      - Locked layers/items are reported as info and do not fail the check
      - If the scan cannot be read back, the result is an error with
        diagnostics.scan_status='unavailable' — never a passing check
    """
    ab_idx = params.artboard_index if params.artboard_index is not None else 'null'

    # F9: Use json.dumps for user-supplied strings to prevent JSX injection
    scope_js = json.dumps(params.scope)

    # Build the preflight check script
    script = f"""
// Pre-flight check: verify library functions are available
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
    var boundsOptions = {BoundsOptions(artboardIndex=params.artboard_index, boundsType=params.bounds_type, boundsSource=params.bounds_source, policy=params.policy, scope=params.scope, ignoreHidden=True, ignoreLocked=False).jsx()};
    boundsOptions.artboardIndex = abIdx;
    var boundsResult = JSON.parse(countItemsOnArtboard(boundsOptions));

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
    var scope = {scope_js};
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

    if params.publication is not None:
        script = "JSON.stringify(publicationPreflightScan(app.activeDocument, " + json.dumps({
            "artboard_index": params.artboard_index,
            "publication": params.publication.model_dump(exclude_none=True),
            "scan_max_items": params.scan_max_items, "scan_budget_ms": params.scan_budget_ms,
        }) + "))"

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

    logger.info(f"preflight_check: artboard={params.artboard_index}, policy={params.policy}")

    try:
        response = await execute_script_with_context(
            script=script,
            command_type="preflight_check",
            tool_name="illustrator_preflight_check",
            params=params.model_dump(),
            includes=["validate"]
        )

        # The successful preflight path builds its own envelope after parsing
        # the scan. Preserve any host-disclosed response limit before doing so;
        # otherwise a cut scan could leave the registered boundary claiming it
        # was not truncated.
        note_host_truncation(diagnostics, response)

        # Check for pipeline-level errors (connection, library injection, etc.)
        if response.get("error"):
            return format_envelope(response, context="preflight_check", diagnostics=diagnostics)

        # The host wraps a bare script return as ``{ok: true, data: <value>}``
        # (host.jsx ``executeScript``).  This block used to read a nested
        # ``result`` key from the older ``{success, result}`` shape; once the
        # envelope was unified that key stopped existing, the lookup fell back
        # to "{}", and every scan reported zero findings — a validation tool
        # that could not fail.  Parse through the shared unwrapper instead, and
        # require the keys that make a scan readable, so a malformed or
        # truncated payload is reported as *unavailable* rather than as a pass.
        try:
            preflight_data = require_jsx_payload(
                response,
                context="preflight_check",
                required_keys=_PREFLIGHT_REQUIRED_KEYS,
            )
            issues = preflight_data["issues"]
            if not isinstance(issues, list):
                raise JsxPayloadError(
                    f"preflight 'issues' is {type(issues).__name__}, expected a list"
                )
        except JsxPayloadError as exc:
            logger.error("Preflight verification unavailable: %s", exc)
            return make_envelope(
                ok=False,
                error={
                    "code": ErrorCode.R_PREFLIGHT_FAILED.value,
                    "message": (
                        f"Preflight verification unavailable: {exc}. "
                        "The document was not checked — this is not a passing result."
                    ),
                },
                diagnostics={**diagnostics, "scan_status": "unavailable"},
            )

        if params.publication is not None:
            from illustrator_mcp.results import CanonicalResult, ExecutionStatus, Verification, VerificationStatus, build_call_result
            # Aggregate only requested thresholds. Embedding is informational,
            # and missing evidence for a requested check must never become a pass.
            requested = {
                "min_font_pt": "font", "min_stroke_pt": "stroke",
                "min_image_ppi": "image", "expected_color_mode": "color_mode",
            }
            statuses = [
                preflight_data["checks"].get(name, {}).get("status", "unknown")
                for field, name in requested.items()
                if getattr(params.publication, field) is not None
            ]
            # The bounded publication scanner does not execute the legacy scan.
            # Disclose defaults as well as explicit requests, with exact options
            # so callers can run that scan separately without losing intent.
            legacy = {name: getattr(params, name) for name in (
                "bounds_type", "bounds_source", "policy", "check_zero_size",
                "check_empty_text", "check_locked",
            )}
            explicitly_requested = [
                name for name in legacy if name in params.model_fields_set
                and (not name.startswith("check_") or legacy[name])
            ]
            preflight_data["legacy_preflight"] = {
                "status": "not_run", "options": legacy,
                "explicitly_requested": explicitly_requested,
                "nextStep": "Run illustrator_preflight_check with publication omitted to execute these checks.",
            }
            preflight_data.setdefault("omissions", []).append(
                "Publication mode omits legacy bounds, zero-size, empty-text and locked-artwork checks; "
                "see legacy_preflight for the options and follow-up."
            )
            if explicitly_requested or not statuses:
                statuses.append("unknown")
            statuses = [value if value in {"pass", "fail"} else "unknown" for value in statuses]
            status = VerificationStatus.FAILED if "fail" in statuses else VerificationStatus.UNAVAILABLE if "unknown" in statuses else VerificationStatus.PASSED
            return build_call_result(CanonicalResult(
                tool=_PREFLIGHT_NAME, execution=ExecutionStatus.SUCCEEDED, data=preflight_data,
                diagnostics={**diagnostics, "scan_status": "completed"},
                verification=Verification(status=status, scope="publication", detail="See per-check measurements and coverage."),
            ))

        # Findings policy is unchanged: informational findings (locked layers
        # and items) are reported without failing the check.  Separating a
        # completed scan from its findings is a public contract change and is
        # deferred to the declared breaking boundary; until then
        # `diagnostics.scan_status` distinguishes "scanned and found issues"
        # from "could not scan at all".
        non_info_issues = [
            issue for issue in issues
            if isinstance(issue, dict) and issue.get("severity") != "info"
        ]
        warnings = [
            issue.get("message", "Unknown issue") for issue in non_info_issues
        ]

        # ``make_envelope`` drops ``result`` whenever ok is false, and "the
        # check found something" is exactly the failing case whose issue list,
        # counts and summary the caller needs.  So on a failure the scan also
        # rides in diagnostics, where it survives.  On a pass it does not:
        # ``result`` already carries it, and duplicating it there doubled the
        # payload of the most common outcome for nothing.
        passed = not non_info_issues
        scan_diagnostics = {**diagnostics, "scan_status": "completed"}
        if not passed:
            scan_diagnostics["scan"] = preflight_data

        return make_envelope(
            ok=passed,
            result=preflight_data,
            warnings=warnings,
            diagnostics=scan_diagnostics,
        )

    except Exception as e:
        logger.error(f"Preflight check failed: {str(e)}")
        return make_envelope(
            ok=False,
            error={"code": ErrorCode.R_PREFLIGHT_FAILED.value, "message": str(e)},
            diagnostics={**diagnostics, "scan_status": "unavailable"},
        )
