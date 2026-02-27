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
from illustrator_mcp.proxy_client import execute_script_with_context, format_envelope
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


from illustrator_mcp.tools.base import TOOL_ANNOTATIONS

_SVG_NAME = "illustrator_path_import_svg"


@mcp.tool(name=_SVG_NAME, annotations=TOOL_ANNOTATIONS[_SVG_NAME])
async def illustrator_path_import_svg(params: PathImportSvgInput) -> str:
    """Import an SVG path d attribute into the active document.

    CONTRACT: readOnly=False, destructive=False, idempotent=False, openWorld=False

    WHEN TO USE:
      - Importing existing SVG path data (d strings) into Illustrator
      - Complex outlines, organic shapes, arcs described in SVG syntax

    EXAMPLES:
      illustrator_path_import_svg(d="M 10 50 C 20 20, 80 20, 90 50 Z")
      illustrator_path_import_svg(d="M 0 0 L 100 0 L 100 100 Z", fill={r: 255, g: 0, b: 0})

    NOTES:
      - Parses SVG d string server-side, converts arcs to cubic Beziers
      - Safety limits: 50,000 chars, 5,000 segments, 100 subpaths, +/-100,000 coords
      - For new shapes prefer illustrator_execute_task + element_create with smooth:true
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
        # Let format_envelope → classify_error handle E_D_TOO_LONG → SVG001 etc.
        return format_envelope(
            {"error": str(e)},
            context="path_import_svg",
            warnings=warnings,
            diagnostics=diagnostics,
        )

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
        return format_envelope(
            {"error": "Import execution failed: " + str(e)},
            context="path_import_svg",
            warnings=warnings,
            diagnostics=diagnostics,
        )

    # Let format_envelope handle result parsing, error classification,
    # and success/failure determination (replaces manual json.loads +
    # draw_result.get("ok") check).
    return format_envelope(
        response,
        context="path_import_svg",
        warnings=warnings,
        diagnostics=diagnostics,
    )


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
