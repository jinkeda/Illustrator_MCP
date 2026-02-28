"""
VLM Occlusion Guard — programmatic pre-flight check for VLM checkpoints.

Detects occlusion bugs (background covering all artwork) BEFORE generating
a preview image, saving export latency and preventing VLM misinterpretation.

Detection is layer-based (topmost visible layers), NOT flat pageItems.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Thresholds (from docs/qa_invariants.md) ──────────────────────────
COVER_THRESHOLD: float = 0.90
OPACITY_THRESHOLD: float = 95.0
MAX_VISIBLE_LAYERS_TO_SCAN: int = 2
DEFAULT_BG_LAYER_NAMES: set = {"sky", "background", "bg"}

# Typenames that support `.filled` in ExtendScript
_FILLABLE_TYPES = {"PathItem", "CompoundPathItem"}
_RASTER_TYPES = {"RasterItem", "PlacedItem"}
_CHECKABLE_TYPES = _FILLABLE_TYPES | _RASTER_TYPES


# ── Data Classes ─────────────────────────────────────────────────────

@dataclass
class OcclusionFinding:
    """A single occlusion finding."""
    code: str          # Q001 | Q003 | Q004
    severity: str      # "abort" | "warn"
    offender: dict     # {name, typename, layer, layerIndex, opacity, ...}
    message: str


@dataclass
class OcclusionResult:
    """Result of the occlusion guard check."""
    ok: bool  # False if any severity=abort
    findings: List[OcclusionFinding] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    suggested_fix: List[dict] = field(default_factory=list)


# ── Geometry ─────────────────────────────────────────────────────────

def _intersection_area(bounds: list, artboard: list) -> float:
    """Compute intersection area between item bounds and artboard.

    Illustrator Y-up: bounds = [left, top, right, bottom]
    where top > bottom (e.g., top=0, bottom=-400 for a 400pt artboard).

    Returns area in square points.
    """
    # Item bounds
    i_left, i_top, i_right, i_bottom = bounds
    # Artboard bounds
    a_left, a_top, a_right, a_bottom = artboard

    # Intersection rectangle
    x_overlap = max(0, min(i_right, a_right) - max(i_left, a_left))
    y_overlap = max(0, min(i_top, a_top) - max(i_bottom, a_bottom))

    return x_overlap * y_overlap


def _artboard_area(artboard: list) -> float:
    """Compute artboard area. Y-up: height = top - bottom."""
    a_left, a_top, a_right, a_bottom = artboard
    return abs(a_right - a_left) * abs(a_top - a_bottom)


# ── Main Detection ───────────────────────────────────────────────────

def check_occlusion(
    layers: List[dict],
    top_layer_items: List[dict],
    artboard_rect: list,
    total_item_count: int,
    bg_layer_names: Optional[set] = None,
) -> OcclusionResult:
    """Run occlusion guard checks.

    Args:
        layers: Layer metadata, ordered by index (0=topmost).
            Each: {name, index, visible, locked, itemCount}
        top_layer_items: Items from topmost M visible layers.
            Each: {name, typename, layerName, layerIndex, opacity,
                   filled, stroked, blendingMode, clipped,
                   bounds: [l,t,r,b], coverRatio, mcpId}
        artboard_rect: [left, top, right, bottom] (Y-up)
        total_item_count: Total items in document.
        bg_layer_names: Optional override for background layer names.
            If None, falls back to DEFAULT_BG_LAYER_NAMES.
            Names are normalized to lowercase with whitespace stripped.

    Returns:
        OcclusionResult with findings and suggested fixes.
    """
    # Normalize bg_layer_names once: case-insensitive, strip whitespace
    effective_names = (
        {n.strip().lower() for n in bg_layer_names}
        if bg_layer_names
        else DEFAULT_BG_LAYER_NAMES
    )
    findings: List[OcclusionFinding] = []
    diag: Dict[str, Any] = {
        "layers_checked": 0,
        "items_scanned": 0,
        "total_items": total_item_count,
    }

    # ── Check 0: Single-item bypass ──────────────────────────────
    if total_item_count <= 1:
        diag["bypass"] = "single_item"
        return OcclusionResult(ok=True, diagnostics=diag)

    ab_area = _artboard_area(artboard_rect)
    if ab_area <= 0:
        diag["bypass"] = "zero_artboard_area"
        return OcclusionResult(ok=True, diagnostics=diag)
    diag["artboard_area"] = ab_area

    # ── Check 1: Layer name semantics (Q003) ─────────────────────
    visible_layers = 0
    for layer in layers:
        if not layer.get("visible", False) or layer.get("locked", False):
            continue
        visible_layers += 1
        diag["layers_checked"] = visible_layers

        # Only flag if it's the FIRST (topmost) visible layer
        if visible_layers == 1:
            name_lower = layer.get("name", "").lower().strip()
            if name_lower in effective_names:
                findings.append(OcclusionFinding(
                    code="Q003",
                    severity="abort",
                    offender={
                        "name": layer["name"],
                        "layerIndex": layer.get("index", 0),
                        "type": "layer",
                    },
                    message=(
                        f"Background layer '{layer['name']}' is topmost visible "
                        f"(index {layer.get('index', 0)}). "
                        "Background layers should be at the bottom of the stack."
                    ),
                ))

        if visible_layers >= MAX_VISIBLE_LAYERS_TO_SCAN:
            break

    # ── Check 2: Top-cover scan (Q001 / Q004) ────────────────────
    for item in top_layer_items:
        diag["items_scanned"] = diag.get("items_scanned", 0) + 1
        typename = item.get("typename", "")

        # Typename gate: GroupItem handling
        if typename == "GroupItem":
            # Only check clipping groups
            if not item.get("clipped", False):
                continue
            # For clipping groups, check the group bounds as proxy
            # (the clipping path defines the visible area)
        elif typename not in _CHECKABLE_TYPES:
            continue

        # Fill gate: rasters/placed are always "filled"; paths need .filled
        is_filled = item.get("filled", False)
        if typename in _RASTER_TYPES:
            is_filled = True
        elif typename == "GroupItem" and item.get("clipped", False):
            is_filled = True  # Clipping group acts as filled region

        if not is_filled:
            continue

        # Opacity gate
        opacity = item.get("opacity", 100)
        if opacity < OPACITY_THRESHOLD:
            continue

        # Cover ratio computation
        bounds = item.get("bounds")
        if not bounds or len(bounds) < 4:
            continue

        cover_ratio = item.get("coverRatio")
        if cover_ratio is None:
            inter = _intersection_area(bounds, artboard_rect)
            cover_ratio = inter / ab_area if ab_area > 0 else 0

        if cover_ratio < COVER_THRESHOLD:
            continue

        # Blend mode check
        blend = item.get("blendingMode", "Normal")
        offender_info = {
            "name": item.get("name", "<unnamed>"),
            "typename": typename,
            "layer": item.get("layerName", ""),
            "layerIndex": item.get("layerIndex", -1),
            "opacity": opacity,
            "blendingMode": blend,
            "coverRatio": round(cover_ratio, 3),
            "bounds": bounds,
            "mcpId": item.get("mcpId"),
        }

        if blend == "Normal":
            findings.append(OcclusionFinding(
                code="Q001",
                severity="abort",
                offender=offender_info,
                message=(
                    f"'{offender_info['name']}' ({typename}) covers "
                    f"{cover_ratio:.0%} of artboard with Normal blend, "
                    f"opacity={opacity}%. Likely occluding all content below."
                ),
            ))
        else:
            findings.append(OcclusionFinding(
                code="Q004",
                severity="warn",
                offender=offender_info,
                message=(
                    f"'{offender_info['name']}' ({typename}) covers "
                    f"{cover_ratio:.0%} of artboard with {blend} blend, "
                    f"opacity={opacity}%. Intentional overlay?"
                ),
            ))

    # ── Build result ─────────────────────────────────────────────
    has_abort = any(f.severity == "abort" for f in findings)
    suggested_fix: List[dict] = []

    if has_abort:
        suggested_fix = _build_suggested_fix(findings)

    return OcclusionResult(
        ok=not has_abort,
        findings=findings,
        diagnostics=diag,
        suggested_fix=suggested_fix,
    )


# ── Remediation ──────────────────────────────────────────────────────

def _build_suggested_fix(findings: List[OcclusionFinding]) -> List[dict]:
    """Generate SOC ops to fix abort-level occlusion findings.

    - Q003 (bg layer on top): layer_move to bottom
    - Q001 (item covers artboard): cross-layer move to bottom
    """
    ops: List[dict] = []

    for f in findings:
        if f.severity != "abort":
            continue

        if f.code == "Q003":
            # Move the bg layer to the bottom of the stack
            ops.append({
                "task": "layer_create",
                "params": {
                    "name": f.offender.get("name", "Sky"),
                    "placement": "bottom",
                },
                "_note": (
                    "layer_create with existing name will find the layer; "
                    "placement='bottom' moves it. If a layer_move op is "
                    "available, prefer that instead."
                ),
            })
        elif f.code == "Q001":
            mcp_id = f.offender.get("mcpId")
            if mcp_id:
                ops.append({
                    "task": "zorder_back",
                    "targets": {"type": "id", "ids": [mcp_id]},
                    "params": {},
                    "_note": (
                        "Sends item to back of its layer. For cross-layer "
                        "fix, manually move to the bottom layer."
                    ),
                })

    return ops


# ── Abort Message Formatting ─────────────────────────────────────────

def format_abort_message(result: OcclusionResult) -> str:
    """Format a loud abort message for VLM checkpoint failure.

    Only call when result.ok is False.
    """
    lines = [
        "[🛑 PREVIEW ABORTED BY SYSTEM GUARD]",
        "",
    ]

    for f in result.findings:
        if f.severity == "abort":
            lines.append(f"CRITICAL ERROR {f.code}: {f.message}")
    for f in result.findings:
        if f.severity == "warn":
            lines.append(f"⚠️ WARNING {f.code}: {f.message}")

    lines.append("")
    lines.append(
        "The preview image was NOT generated because the top-most item "
        "occludes the canvas. If rendered, you would see a solid color."
    )
    lines.append("")
    lines.append(
        "ACTION REQUIRED: Execute the suggested_fix ops in "
        "diagnostics.suggested_fix to correct the Z-order, then retry."
    )

    return "\n".join(lines)
