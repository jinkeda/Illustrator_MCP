"""
import_svg.py — MCP tool for importing SVG `d` path data into Illustrator.

For new shapes, prefer geometry.drawPathPoints() via execute_script.
This tool is for importing existing SVG path data only.
"""

import hashlib
import json
import logging
from typing import Any, Dict, Optional

from pydantic import Field

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context
from illustrator_mcp.tools.base import ToolInputBase

logger = logging.getLogger(__name__)


class PathImportSvgInput(ToolInputBase):
    """Input for path_import_svg tool."""

    d: str = Field(
        ...,
        description="SVG path `d` attribute string to import."
    )
    layer: Optional[str] = Field(
        default=None,
        description="Target layer name. Falls back to active layer."
    )
    tag: Optional[str] = Field(
        default=None,
        description="Optional @mcp:tag metadata for the imported path."
    )
    name: Optional[str] = Field(
        default=None,
        description="Optional name for the imported path item."
    )


@mcp.tool(
    name="illustrator_path_import_svg",
    annotations={
        "title": "Import SVG Path",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def illustrator_path_import_svg(params: PathImportSvgInput) -> str:
    """Import an SVG path `d` attribute into the active document.

    Parses the SVG `d` string server-side, converts arc commands to
    cubic Beziers, and draws the result via geometry.drawPathPoints.

    For new shapes, prefer geometry.drawPathPoints() via execute_script.
    This tool is for importing existing SVG path data only.

    Safety limits (hardcoded, no override):
    - MAX_D_LENGTH: 50,000 chars
    - MAX_SEGMENTS: 5,000 total segments
    - MAX_SUBPATHS: 100 subpaths
    - MAX_COORD_ABS: +/-100,000
    """
    # F5: Track mutation cadence — lazy import avoids import-order risk
    from illustrator_mcp.tools.execute import _counter
    _counter.increment()
    try:
        return await _path_import_svg_impl(params)
    except Exception:
        _counter.decrement()
        raise


async def _path_import_svg_impl(params: PathImportSvgInput) -> str:
    """Inner implementation of path_import_svg, extracted for counter safety."""
    from illustrator_mcp.svgd import parse_svg_d

    d_str = params.d
    warnings = [
        "Prefer geometry.drawPathPoints for new shapes"
    ]
    diagnostics: Dict[str, Any] = {"tool": "path_import_svg"}

    # Compute d hash for metadata stamping
    d_hash = hashlib.sha256(d_str.encode("utf-8")).hexdigest()[:16]
    diagnostics["d_sha256"] = d_hash

    # ── Parse SVG d ────────────────────────────────────────────
    try:
        ir = parse_svg_d(d_str)
    except ValueError as e:
        err_str = str(e)
        # [H7] Extract structured error code if present
        error_code = None
        for code in (
            "E_D_TOO_LONG", "E_TOO_MANY_SEGMENTS",
            "E_TOO_MANY_SUBPATHS", "E_COORD_OVERFLOW", "E_TOO_MANY_TOKENS",
        ):
            if err_str.startswith(code):
                error_code = code
                break
        return json.dumps({
            "ok": False,
            "error": err_str,
            "errorCode": error_code,
            "diagnostics": diagnostics,
        })

    # ── Build drawPathPoints spec from IR ──────────────────────
    is_multi = ir.get("ir") == "multi"

    if is_multi:
        subpaths_ir = ir.get("subpaths", [])
        segment_count = sum(len(sp.get("points", [])) for sp in subpaths_ir)
        all_closed = ir.get("all_closed", False)

        # Build subpath specs for drawPathPoints
        subpath_specs = []
        for sp in subpaths_ir:
            points_spec = _ir_points_to_draw_spec(sp)
            subpath_specs.append({
                "points": points_spec,
                "closed": sp.get("closed", False),
            })

        spec = {
            "subpaths": subpath_specs,
            "compound": all_closed,  # compound only when all closed
        }
    else:
        segment_count = len(ir.get("points", []))
        spec = {
            "points": _ir_points_to_draw_spec(ir),
            "closed": ir.get("closed", False),
        }

    # Add target/meta
    if params.layer:
        spec["target"] = {"layer": params.layer}
    meta = {"source": "svg_import", "d_sha256": d_hash}
    if params.tag:
        meta["tag"] = params.tag
    spec["meta"] = meta

    if params.name:
        spec["name"] = params.name

    diagnostics["segments"] = segment_count
    diagnostics["is_multi"] = is_multi
    if is_multi:
        diagnostics["subpath_count"] = len(ir.get("subpaths", []))

    # ── Execute drawPathPoints via ExtendScript ────────────────
    spec_json = json.dumps(spec)
    script = (
        "(function() {"
        "    var spec = " + spec_json + ";"
        "    var result = drawPathPoints(spec);"
        "    return JSON.stringify(result);"
        "})()"
    )

    try:
        response = await execute_script_with_context(
            script=script,
            command_type="path_import_svg",
            tool_name="illustrator_path_import_svg",
            includes=["geometry"],
        )
    except Exception as e:
        return json.dumps({
            "ok": False,
            "error": "Import execution failed: " + str(e),
            "diagnostics": diagnostics,
        })

    # Parse the response
    result_str = response.get("result", "{}")
    if isinstance(result_str, str):
        try:
            draw_result = json.loads(result_str)
        except json.JSONDecodeError:
            draw_result = {"raw": result_str}
    else:
        draw_result = result_str

    if not draw_result.get("ok", False):
        return json.dumps({
            "ok": False,
            "error": draw_result.get("error", "Unknown draw error"),
            "diagnostics": diagnostics,
        })

    # [H5] Stronger nudge in response payload
    return json.dumps({
        "ok": True,
        "imported": True,
        "hint": "For new shapes, use geometry.drawPathPoints via execute_script",
        "uuid": draw_result.get("uuid"),
        "segments": segment_count,
        "source": "svg_import",
        "d_sha256": d_hash,
        "subpathCount": draw_result.get("subpathCount", 1),
        "bounds": draw_result.get("bounds"),
        "warnings": warnings,
        "diagnostics": diagnostics,
    })


def _ir_points_to_draw_spec(ir: Dict[str, Any]) -> list:
    """Convert IR points+handles to drawPathPoints point spec format."""
    points = ir.get("points", [])
    handles = ir.get("handles", [])

    result = []
    for idx, pt in enumerate(points):
        entry: Dict[str, Any] = {"anchor": pt}
        if idx < len(handles):
            h = handles[idx]
            if h.get("in") is not None:
                entry["left"] = h["in"]
            if h.get("out") is not None:
                entry["right"] = h["out"]
        result.append(entry)
    return result
