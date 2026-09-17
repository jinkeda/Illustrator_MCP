"""
Export tool for Adobe Illustrator.

Extracted from documents.py for readability.
"""

import base64
import json
import logging
import os
from typing import Union

from mcp.types import ImageContent
from mcp.types import CallToolResult
from illustrator_mcp.tools.bounds import BoundsOptions, check_bounds
from illustrator_mcp.shared import mcp
from illustrator_mcp import templates
from illustrator_mcp.tools.base import (
    ToolInputBase, TOOL_ANNOTATIONS, canonical_tool, declare_effects,
)
from illustrator_mcp.utils import escape_path_for_jsx
from illustrator_mcp.proxy_client import execute_script_with_context, format_envelope
from illustrator_mcp.libraries import get_injection_metadata
from illustrator_mcp.execution import HostUnresolvedError, get_coordinator

from illustrator_mcp.tools._models import ExportFormat, ExportDocumentInput

logger = logging.getLogger(__name__)


def _versioned_path(file_path: str, limit: int = 999) -> str:
    """The first free ``name-N.ext`` beside *file_path*.

    Raises FileExistsError if the whole run is taken, rather than looping or
    silently reusing one: a caller asking not to replace anything is better
    served by a refusal than by a surprise.
    """
    stem, ext = os.path.splitext(file_path)
    for n in range(2, limit + 1):
        candidate = f"{stem}-{n}{ext}"
        if not os.path.exists(candidate):
            return candidate
    raise FileExistsError(
        f"{stem}-2{ext} through {stem}-{limit}{ext} all exist; "
        "choose another file_path"
    )


def resolve_export_target(file_path: str, policy: str) -> tuple:
    """Settle the output path before Illustrator is asked to write anything.

    Illustrator's "Replace Files" prompt is modal and runs on the host
    thread, so a call that trips it hangs until a person clicks: the MCP
    times out, Illustrator keeps waiting, and no later call can clear it.
    Deciding here means the host is only ever handed a path it can write
    without asking.

    Returns ``(path, note)`` where *note* is a warning to surface, or raises
    FileExistsError when the policy is to refuse.
    """
    if not os.path.exists(file_path):
        return file_path, None

    if policy == "fail":
        raise FileExistsError(
            f"{file_path} already exists and overwrite='fail'. "
            "Pass overwrite='replace' to overwrite it, or 'version' to write "
            "alongside it."
        )

    if policy == "version":
        target = _versioned_path(file_path)
        return target, (
            f"{file_path} exists; wrote {target} instead (overwrite='version')."
        )

    if policy != "replace":
        raise ValueError("Unknown overwrite policy: " + policy)
    # Replacement is prepared by the retained logical-job owner, after validation.
    return file_path, None


_EXPORT_NAME = "illustrator_export_document"


@mcp.tool(name=_EXPORT_NAME, annotations=TOOL_ANNOTATIONS[_EXPORT_NAME])
@canonical_tool(_EXPORT_NAME, reserve=True)
async def illustrator_export_document(params: ExportDocumentInput) -> CallToolResult:
    """Export the active document to PNG or JPG. Native SVG and PDF are refused.

    CONTRACT: readOnly=False, destructive=True, idempotent=False, openWorld=True

    WHEN TO USE:
      - Generating raster output (PNG, JPG) with optional scale factor
      - Native SVG is disabled: live export changed the source file association
      - Getting visual feedback by setting return_image=True (PNG/JPG only)
      - NOT for looking at your work in progress. Exporting writes a file to
        disk and overwrites whatever was there. To see the artwork, call
        illustrator_observe: it returns the image inline together with a
        numbered map of items, their handles and their bounds, with no file
        to create, locate and open. Export when you want a deliverable

    EXAMPLES:
      PNG at twice the size:
        {"params": {"file_path": "C:/out/fig.png", "format": "png", "scale": 2.0}}
      PDF refusal; use a separate working copy with Illustrator PDF save:
        {"params": {"file_path": "C:/out/fig.pdf", "format": "pdf"}}
      SVG refusal after source-association failure; use a separate working copy:
        {"params": {"file_path": "C:/out/fig.svg", "format": "svg"}}
      PNG of the artboard, returned inline as well:
        {"params": {"file_path": "C:/out/fig.png", "return_image": true, "artboard_only": true}}
      Refuse rather than overwrite an existing file:
        {"params": {"file_path": "C:/out/fig.png", "format": "png", "overwrite": "fail"}}
      Keep the old file and write beside it:
        {"params": {"file_path": "C:/out/fig.png", "overwrite": "version"}}

    NOTES:
      - artboard_only=True clips export to artboard; a pre-check warns if nothing is on it
      - Native PDF is temporarily disabled because saveAs changes source state
      - Native SVG is temporarily disabled after a measured source-association failure
      - return_image returns base64 image bytes as ImageContent for visual verification
      - An existing file is resolved before dispatch per `overwrite`, so
        Illustrator is never asked to confirm a replacement. Its Replace Files
        prompt is modal and would hang the host until a person clicked it
      - overwrite='replace' retains a unique sibling backup until completion
      - Unknown completion retains the backup; use illustrator_job_status with
        finalize_export=true on the returned jobId after completion is established
      - Backup ownership is in-memory; after server restart use manual recovery
    """
    scale = params.scale * 100
    fmt_name = params.format.value.upper()

    warnings = []

    # Pure input checks precede host calls and every filesystem side effect.
    if params.format == ExportFormat.PDF:
        return format_envelope({"error": "Native PDF export is temporarily disabled: saveAs cannot preserve source state. Save a separate working copy and use Illustrator's PDF save workflow on that copy, keeping the source document separate. The copy's identity/history may change."}, diagnostics={"dispatched": False, "effects": declare_effects(complete=True)})
    if params.format == ExportFormat.SVG:
        return format_envelope({"error": "Native SVG export is temporarily disabled: live Illustrator export changed the source document's file association to the SVG path. Export PNG/JPG, or use a separate working copy for a manual SVG export. No automatic save-back or reopen is performed."}, diagnostics={"dispatched": False, "effects": declare_effects(complete=True)})
    from pathlib import Path
    suffixes = {ExportFormat.PNG: (".png",), ExportFormat.JPG: (".jpg", ".jpeg"), ExportFormat.SVG: (".svg",)}
    if Path(params.file_path).suffix.lower() not in suffixes[params.format]:
        return format_envelope({"error": "Output extension must match export format."}, diagnostics={"dispatched": False, "effects": declare_effects(complete=True)})
    target_path = os.path.abspath(params.file_path)
    if os.path.islink(target_path) or os.path.isdir(target_path):
        return format_envelope({"error": "Export destination must be a regular file path, not a directory or symbolic link."}, diagnostics={"dispatched": False, "effects": declare_effects(complete=True)})
    path = escape_path_for_jsx(target_path)

    # Get canonicalized includes metadata (for precheck)
    export_meta = get_injection_metadata(["validate"])
    diagnostics = {
        # An export writes a file and changes no page items. Empty lists with
        # complete=true is a real answer, and different from the empty lists
        # with complete=false this used to emit.
        "effects": declare_effects(complete=True),
        "file_path": target_path,
        "requested_file_path": params.file_path,
        "overwrite": params.overwrite,
        "format": params.format.value,
        "scale": params.scale,
        "artboard_only": params.artboard_only,
        "artboard_index": params.artboard_index,
        "precheck_includes": export_meta["includes_canonical"],
        "precheck_prelude_hash": export_meta["prelude_hash"]
    }

    from illustrator_mcp.utils.response import require_jsx_payload, JsxPayloadError
    ab_check = params.artboard_index if params.artboard_index is not None else "app.activeDocument.artboards.getActiveArtboardIndex()"
    validation = await execute_script_with_context(
        script="(function(){if(!app.documents.length) throw new Error('No document open'); var index=" + str(ab_check) + "; if(index<0 || index>=app.activeDocument.artboards.length) throw new Error('Artboard index out of range'); var source=null; try {source=app.activeDocument.fullName.fsName;} catch(e) {} if(source && String(source).toLowerCase()===String(new File(\"" + path + "\").fsName).toLowerCase()) throw new Error('Export destination is the source document; use a separate output path'); return JSON.stringify({validated:true});})()",
        command_type="export_validate", tool_name=_EXPORT_NAME)
    try:
        checked = require_jsx_payload(validation, required_keys=("validated",))
        if checked["validated"] is not True:
            raise JsxPayloadError("Export validation did not succeed")
    except JsxPayloadError as exc:
        return format_envelope({"error": str(exc)}, diagnostics={**diagnostics, "dispatched": False})
    try:
        target_path, overwrite_note = resolve_export_target(target_path, params.overwrite)
    except (OSError, ValueError) as exc:
        return format_envelope({"error": str(exc)}, diagnostics={**diagnostics, "dispatched": False})
    if overwrite_note:
        warnings.append(overwrite_note)
    path = escape_path_for_jsx(target_path)
    diagnostics["file_path"] = target_path

    # Pre-export bounds check if artboard_only
    if params.artboard_only:
        try:
            count = await check_bounds(execute_script_with_context,
                options=BoundsOptions(artboardIndex=params.artboard_index,
                    policy="intersects", scope="artboard"),
                command="export_precheck", tool="illustrator_export_document")
            diagnostics["precheck_findings"] = count
            if count.get('on_artboard', 0) == 0:
                bt = count.get('bounds_type', 'visible')
                warnings.append(
                    f"Pre-check found 0 intersecting items using "
                    f"{bt}Bounds; SVG/gradient/pattern items may be "
                    f"undercounted. See diagnostics."
                )
            # Structured pre-check diagnostics
            diagnostics["precheck_item_count"] = count.get('on_artboard', 0)
            diagnostics["precheck_method"] = f"{count.get('bounds_type', 'visible')}Bounds"
            diagnostics["precheck_artboard"] = {
                "rect": count.get('artboard_rect'),
                "space": "illustrator_native_y_up",
            }
            diagnostics["precheck_skipped_count"] = count.get('skipped', 0)
            diagnostics["precheck_off_artboard"] = count.get('off_artboard', 0)
            diagnostics["precheck_sample_misses"] = count.get('off_items_sample', [])
        except HostUnresolvedError as exc:
            return format_envelope(
                {"error": str(exc), "execution": "unknown"},
                warnings=warnings,
                diagnostics={**diagnostics, "precheck_status": "unresolved",
                    "dispatched": False, "output_verified": False,
                    "output_state": "untouched", "blockingJob": exc.job_id,
                    "nextStep": {"tool": "illustrator_job_status", "params": {"jobId": exc.job_id}}},
            )
        except Exception as e:
            diagnostics["precheck_status"] = "unavailable"
            warnings.append(f"Pre-export check failed: {e}")

    # Config-driven export
    export_configs = {
        # `clips`: whether the options class actually exposes artBoardClipping.
        ExportFormat.PNG: {"options": "ExportOptionsPNG24", "type": "ExportType.PNG24", "scales": True, "clips": True},
        ExportFormat.JPG: {"options": "ExportOptionsJPEG", "type": "ExportType.JPEG", "scales": True, "clips": True},
        ExportFormat.SVG: {"options": "ExportOptionsSVG", "type": "ExportType.SVG", "scales": False, "clips": False},
        ExportFormat.PDF: {"options": "PDFSaveOptions", "type": None, "scales": False, "clips": False},
    }

    fmt_config = export_configs[params.format]

    # Reject artboard options a format cannot honour, rather than reporting
    # them as applied. ExportOptionsPNG24 and ExportOptionsJPEG both expose
    # artBoardClipping; ExportOptionsSVG does not (measured), and PDF export
    # goes through saveAs, which has no per-artboard clipping at all. The old
    # code set the option for PNG only but echoed `artboard_clipping: true`
    # for every format: a JPEG export reported the artboard's 300x200 while
    # writing a 1292x402 file.
    if params.artboard_only and not fmt_config["clips"]:
        return format_envelope(
            {"error": (
                f"{fmt_name} export cannot clip to an artboard. "
                f"artboard_only is supported for PNG and JPG only. "
                f"Export PNG/JPG for a clipped raster, or remove artboard_only."
            )},
            context="export_document",
            warnings=warnings,
            diagnostics=diagnostics,
        )
    if params.artboard_index is not None and params.format == ExportFormat.PDF:
        return format_envelope(
            {"error": (
                "PDF export writes the whole document through saveAs and cannot "
                "select a single artboard. Remove artboard_index, or export "
                "PNG/JPG/SVG for a single artboard."
            )},
            context="export_document",
            warnings=warnings,
            diagnostics=diagnostics,
        )

    # Build export script with artboard clipping support
    if fmt_config["type"]:  # Standard exportFile (PNG, JPG, SVG)
        ab_index_js = params.artboard_index if params.artboard_index is not None else 'doc.artboards.getActiveArtboardIndex()'
        artboard_clip = "true" if params.artboard_only else "false"

        scale_opts = ""
        if fmt_config["scales"]:
            scale_opts = f"""
            opts.horizontalScale = {scale};
            opts.verticalScale = {scale};"""

        # Every format whose options class supports clipping gets it. This was
        # PNG-only while the result claimed clipping for all of them.
        clip_opt = "opts.embedRasterImages = true;" if params.format == ExportFormat.SVG else ""
        if fmt_config["clips"]:
            clip_opt = f"opts.artBoardClipping = {artboard_clip};"

        script = templates.EXPORT_STANDARD.substitute(
            ab_index_js=ab_index_js,
            options_class=fmt_config["options"],
            scale_opts=scale_opts,
            clip_opt=clip_opt,
            path=path,
            export_type=fmt_config["type"],
            scale=scale,
            fmt_name=fmt_name,
            artboard_clip=artboard_clip,
            clip_supported="true" if fmt_config["clips"] else "false",
        )
    else:  # PDF uses saveAs
        script = templates.EXPORT_PDF.substitute(path=path)

    from illustrator_mcp.execution.export_files import reserve_export_files
    coordinator = get_coordinator()
    # File preparation is also a side effect: do not move the destination or
    # create directories while any managed host outcome remains unresolved.
    coordinator.assert_host_available()
    job = coordinator.get(coordinator.active_job_id)
    try:
        owner = reserve_export_files(coordinator, job, target_path, overwrite=params.overwrite)
        if not os.path.exists(os.path.dirname(target_path)):
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            warnings.append("Created directory: " + os.path.dirname(target_path))
        owner.verify_raster = params.format in (ExportFormat.PNG, ExportFormat.JPG)
        owner.prepare()
    except OSError as exc:
        if job.export_files:
            job.export_files.host_finished = True
        return format_envelope({"error": str(exc)}, diagnostics={**diagnostics, "exportFiles": job.export_files.snapshot() if job.export_files else None, "dispatched": False})

    # Fingerprint the destination BEFORE exporting, so a file that was already
    # there cannot be mistaken for this export's output.
    before = _file_fingerprint(target_path)

    # Execute export (PDF gets longer timeout due to complexity)
    response = await execute_script_with_context(
        script=script,
        command_type="export_document",
        tool_name="illustrator_export_document",
        params={"file_path": target_path, "format": params.format.value, "scale": params.scale},
        timeout=60.0 if params.format == ExportFormat.PDF else None
    )

    owner.request_token = response.get("requestToken") or owner.request_token
    owner.host_finished = not job.awaiting_host and response.get("execution") != "unknown"
    owner.host_ok = _response_ok(response)
    diagnostics["exportFiles"] = owner.finalize()
    if owner.retained:
        diagnostics["nextStep"] = {"tool": "illustrator_job_status", "params": {"jobId": job.job_id, "finalize_export": True}}
        warnings.append("Export backup retained: " + str(owner.backup))

    # Did a file actually appear or change?
    #
    # Illustrator's exportFile does not always raise when it cannot write —
    # measured: exporting over a read-only file returned ok:true, wrote
    # nothing, and the tool then handed back the OLD image as if it were the
    # new one. Freshness is decided here, from the filesystem, not from the
    # host's word.
    after = _file_fingerprint(target_path)
    fresh = owner.state == "verified" and after is not None and after != before
    diagnostics["output_verified"] = fresh
    if after is None:
        diagnostics["output_state"] = "missing"
    elif not fresh:
        diagnostics["output_state"] = "unchanged"
    else:
        diagnostics["output_state"] = "written"

    host_ok = _response_ok(response)
    if owner.raster_error:
        diagnostics.update(output_verified=False, output_state="unreadable")
        return format_envelope({"error": owner.raster_error}, context="export_document",
                               warnings=warnings, diagnostics=diagnostics)
    if host_ok and not fresh:
        detail = (
            "no file was written" if after is None
            else "the file at that path was not modified, so it is left over "
                 "from an earlier export"
        )
        return format_envelope(
            {"error": (
                f"Export reported success but {detail}: {target_path}. "
                f"Check that the path is writable and not open elsewhere."
            )},
            context="export_document",
            warnings=warnings,
            diagnostics=diagnostics,
        )

    if fresh and host_ok and params.format in (ExportFormat.PNG, ExportFormat.JPG):
        try:
            from illustrator_mcp.utils.response import require_jsx_payload
            width, height = owner.raster_size
            payload = require_jsx_payload(response, context="export raster")
            payload.update(pixelWidth=width, pixelHeight=height, width=width, height=height,
                           dimensions_describe="measured raster pixels",
                           artworkPixelRegion="unknown" if not params.artboard_only else "artboard")
            response = {**response, "result": {"ok": True, "data": payload}}
        except Exception as exc:
            diagnostics.update(output_verified=False, output_state="unreadable")
            return format_envelope({"error": "Raster output verification failed: " + str(exc)},
                                   context="export_document", warnings=warnings, diagnostics=diagnostics)

    envelope = format_envelope(
        response=response,
        context="export_document",
        warnings=warnings,
        diagnostics=diagnostics
    )

    # Return image bytes for visual feedback if requested — only for output
    # this export is known to have produced.
    if params.return_image and params.format in [ExportFormat.PNG, ExportFormat.JPG]:
        if not fresh:
            logger.warning(
                "Not returning an image for %s: the export did not produce fresh output",
                target_path,
            )
            return envelope
        try:
            with open(target_path, 'rb') as f:
                img_bytes = f.read()
            mime_type = "image/png" if params.format == ExportFormat.PNG else "image/jpeg"
            # Return both envelope JSON and image content
            return [
                {"type": "text", "text": envelope},
                ImageContent(
                    type="image",
                    data=base64.b64encode(img_bytes).decode('utf-8'),
                    mimeType=mime_type
                )
            ]
        except Exception as e:
            # Image read is best-effort; return the original text envelope
            logger.warning(f"Failed to read exported image for return: {e}")
            return envelope

    return envelope


def _file_fingerprint(path: str):
    """(mtime, size) of a file, or None when it is not there."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _response_ok(response) -> bool:
    """Whether the host reported a successful export."""
    if not isinstance(response, dict) or response.get("error"):
        return False
    from illustrator_mcp.response_classification import classify_response
    if not classify_response(response).ok:
        return False
    raw = response.get("result")
    for _ in range(4):
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError):
                return False
        if not isinstance(raw, dict) or raw.get("ok") is not True:
            return False
        if "data" not in raw:
            return True
        nested = raw["data"]
        if isinstance(nested, str):
            try:
                nested = json.loads(nested)
            except ValueError:
                return False
        if isinstance(nested, dict) and "ok" not in nested:
            return True
        raw = nested
    return False
