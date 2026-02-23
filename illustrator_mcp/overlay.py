"""
VLM Debug Overlay — annotated artboard preview for vision-language models.

Pure image compositing module. Draws numbered bounding boxes onto a PNG
so VLM agents can reference items by label (e.g., "Move [3] down 10px").

Features:
  - Adaptive font sizing (12-28px scaled to image diagonal)
  - WCAG contrast-adaptive outline color (6-color palette)
  - Border-ring sampling on precomputed 256px thumbnail
  - Deterministic 8-position pill placement with anti-overlap
  - Text halo stroke for readability on any background
  - Leader lines when pill displaced >10px from box corner
  - Adaptive grid density
  - Coordinate axis rulers (screen-space Y-down, origin top-left)

Gracefully degrades if Pillow is not installed.
"""

from __future__ import annotations

import io
import logging
import math
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

# ── Visual Constants ─────────────────────────────────────────────────

# 6-color palette: black/white guarantee high contrast on any background.
OUTLINE_PALETTE = [
    (0,   0,   0,   200),  # black  — bright backgrounds
    (255, 255, 255, 200),  # white  — dark backgrounds
    (255, 0,   255, 200),  # magenta
    (0,   255, 255, 200),  # cyan
    (0,   255, 0,   200),  # green
    (255, 255, 0,   200),  # yellow
]

FILL_ALPHA = 20               # Very subtle interior tint
MIN_FILL_AREA_PX = 400        # Skip fill for tiny boxes (<20x20 px)
LABEL_BG_COLOR = (0, 0, 0, 200)
LABEL_FG_COLOR = (255, 255, 255, 255)
HALO_COLOR = (0, 0, 0, 220)

# Font fallback chain (platform-adaptive)
_FONT_CANDIDATES = ["consola", "Consolas", "arial", "Arial", "DejaVuSansMono"]

# Pill placement displacement threshold for leader lines
LEADER_LINE_THRESHOLD_PX = 10


# ── Font Loading ─────────────────────────────────────────────────────

def _load_font(size: int) -> "ImageFont.FreeTypeFont | ImageFont.ImageFont":
    """Load a TrueType font at the given size, with fallback chain.

    Tries monospace fonts first (better for consistent label widths),
    then serif/sans, then Pillow's built-in bitmap font.
    """
    if not HAS_PILLOW:
        return None
    for name in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    # Final fallback: built-in bitmap (ignores size)
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _compute_font_size(img_w: int, img_h: int) -> int:
    """Compute adaptive font size: ~1.5% of diagonal, clamped [12, 28]."""
    diag = math.hypot(img_w, img_h)
    return int(max(12, min(28, diag * 0.015)))


def _compute_outline_width(img_w: int, img_h: int) -> int:
    """Compute outline width: 2px at 800px, 3px at 1600px, max 4px."""
    return max(2, min(4, int(round(max(img_w, img_h) / 600))))


# ── WCAG Contrast ────────────────────────────────────────────────────

def _wcag_luminance(r: float, g: float, b: float) -> float:
    """WCAG 2.0 relative luminance (ITU-R BT.709)."""
    def _lin(v: float) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast_ratio(lum1: float, lum2: float) -> float:
    """WCAG contrast ratio (1.0 to 21.0)."""
    lighter = max(lum1, lum2)
    darker = min(lum1, lum2)
    return (lighter + 0.05) / (darker + 0.05)


def _pick_contrast_color(
    thumb: "Image.Image",
    box_px: List[int],
    img_size: Tuple[int, int],
    thumb_size: Tuple[int, int],
) -> Tuple[int, int, int, int]:
    """Sample border ring on precomputed thumbnail, pick max WCAG contrast color.

    Samples pixel colors along the edges of the bounding box (mapped to
    thumbnail coordinates), averages their luminance, and picks the
    palette color with the highest WCAG contrast ratio.
    """
    sx = thumb_size[0] / img_size[0] if img_size[0] > 0 else 1
    sy = thumb_size[1] / img_size[1] if img_size[1] > 0 else 1

    l = max(0, min(int(box_px[0] * sx), thumb_size[0] - 1))
    t = max(0, min(int(box_px[1] * sy), thumb_size[1] - 1))
    r = max(0, min(int(box_px[2] * sx), thumb_size[0] - 1))
    b = max(0, min(int(box_px[3] * sy), thumb_size[1] - 1))

    # Sample border ring: top/bottom edges + left/right edges
    pixels = []
    for x in range(l, r + 1):
        for y in [t, b]:
            if 0 <= x < thumb_size[0] and 0 <= y < thumb_size[1]:
                pixels.append(thumb.getpixel((x, y))[:3])
    for y in range(t + 1, b):  # skip corners (already sampled)
        for x in [l, r]:
            if 0 <= x < thumb_size[0] and 0 <= y < thumb_size[1]:
                pixels.append(thumb.getpixel((x, y))[:3])

    if not pixels:
        return OUTLINE_PALETTE[0]  # black fallback

    avg_r = sum(p[0] for p in pixels) / len(pixels)
    avg_g = sum(p[1] for p in pixels) / len(pixels)
    avg_b = sum(p[2] for p in pixels) / len(pixels)
    bg_lum = _wcag_luminance(avg_r, avg_g, avg_b)

    return max(
        OUTLINE_PALETTE,
        key=lambda c: _contrast_ratio(_wcag_luminance(c[0], c[1], c[2]), bg_lum),
    )


# ── Pill Placement ───────────────────────────────────────────────────

# 8 deterministic positions, tried in order. First non-colliding wins.
_PILL_POSITIONS = [
    lambda l, t, r, b, pw, ph: (l, t - ph - 2),      # above-left
    lambda l, t, r, b, pw, ph: (r - pw, t - ph - 2),  # above-right
    lambda l, t, r, b, pw, ph: (l, b + 2),             # below-left
    lambda l, t, r, b, pw, ph: (r - pw, b + 2),        # below-right
    lambda l, t, r, b, pw, ph: (l - pw - 4, t),        # outside-left
    lambda l, t, r, b, pw, ph: (r + 4, t),             # outside-right
    lambda l, t, r, b, pw, ph: (l + 2, t + 2),         # inside-top-left
    lambda l, t, r, b, pw, ph: (l + 2, b - ph - 2),   # inside-bottom-left
]


def _in_bounds(rect: Tuple[int, int, int, int], img_w: int, img_h: int) -> bool:
    """Check if rect is fully within image bounds."""
    return rect[0] >= 0 and rect[1] >= 0 and rect[2] <= img_w and rect[3] <= img_h


def _rects_overlap(a: Tuple[int, ...], b: Tuple[int, ...]) -> bool:
    """Check if two (l, t, r, b) rects overlap."""
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _overlap_area(rect: Tuple[int, ...], placed: List[Tuple[int, ...]]) -> int:
    """Total overlap area between rect and all placed rects."""
    total = 0
    for p in placed:
        ox = max(0, min(rect[2], p[2]) - max(rect[0], p[0]))
        oy = max(0, min(rect[3], p[3]) - max(rect[1], p[1]))
        total += ox * oy
    return total


def _place_pill(
    box_l: int, box_t: int, box_r: int, box_b: int,
    pill_w: int, pill_h: int,
    img_w: int, img_h: int,
    placed: List[Tuple[int, int, int, int]],
) -> Tuple[int, int, int, int]:
    """Pick the best pill position using deterministic 8-candidate search.

    Returns (pill_l, pill_t, pill_r, pill_b).
    """
    candidates = []
    for pos_fn in _PILL_POSITIONS:
        px, py = pos_fn(box_l, box_t, box_r, box_b, pill_w, pill_h)
        rect = (px, py, px + pill_w, py + pill_h)
        candidates.append(rect)
        if _in_bounds(rect, img_w, img_h) and not any(_rects_overlap(rect, p) for p in placed):
            return rect

    # All collide or out-of-bounds — pick smallest-overlap candidate
    # (prefer in-bounds candidates)
    in_bounds = [c for c in candidates if _in_bounds(c, img_w, img_h)]
    pool = in_bounds if in_bounds else candidates
    return min(pool, key=lambda c: _overlap_area(c, placed))


def _nearest_corner(
    box_l: int, box_t: int, box_r: int, box_b: int,
    pill_cx: int, pill_cy: int,
) -> Tuple[int, int]:
    """Return the box corner nearest to the pill center."""
    corners = [(box_l, box_t), (box_r, box_t), (box_l, box_b), (box_r, box_b)]
    return min(corners, key=lambda c: math.hypot(c[0] - pill_cx, c[1] - pill_cy))


# ── Text Drawing ─────────────────────────────────────────────────────

def _measure_text(font, text: str) -> Tuple[int, int]:
    """Measure text dimensions using available font API."""
    if font and hasattr(font, "getbbox"):
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    return len(text) * 7, 12


def _draw_text_with_halo(
    draw: "ImageDraw.ImageDraw",
    pos: Tuple[int, int],
    text: str,
    font,
    fg: Tuple[int, ...] = LABEL_FG_COLOR,
    halo: Tuple[int, ...] = HALO_COLOR,
) -> None:
    """Draw text with a 1px dark halo for readability on any background."""
    x, y = pos
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        draw.text((x + dx, y + dy), text, fill=halo, font=font)
    draw.text((x, y), text, fill=fg, font=font)


# ── Main Compositing ─────────────────────────────────────────────────

def composite_overlay(
    img_bytes: bytes,
    annotations: List[dict],
) -> bytes:
    """Draw numbered labels and bounding boxes onto a PNG image.

    Features:
      - WCAG contrast-adaptive outline color (6-color palette)
      - Adaptive font sizing (12-28px)
      - Deterministic 8-position pill placement with anti-overlap
      - Text halo stroke for readability
      - Leader lines when pill displaced >10px

    Args:
        img_bytes: Raw PNG bytes (the base artboard export).
        annotations: List of dicts, each with:
            - label: str — display text (e.g., "1", "2")
            - bounds_px: [left, top, right, bottom] in pixel coords

    Returns:
        Annotated PNG bytes. If Pillow is missing or an error occurs,
        returns the original bytes unchanged.
    """
    if not HAS_PILLOW:
        logger.warning("Pillow not installed. Returning plain image.")
        return img_bytes

    if not annotations:
        return img_bytes

    try:
        base_img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        overlay = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        img_w, img_h = base_img.size

        # Pre-render: adaptive font, outline width, contrast thumbnail
        font_size = _compute_font_size(img_w, img_h)
        font = _load_font(font_size)
        outline_width = _compute_outline_width(img_w, img_h)

        # Precompute 256px-wide thumbnail for O(1) contrast sampling
        thumb_w = min(256, img_w)
        thumb_h = max(1, int(thumb_w * img_h / max(1, img_w)))
        thumb = base_img.resize((thumb_w, thumb_h), Image.NEAREST)
        thumb_size = (thumb_w, thumb_h)

        placed_pills: List[Tuple[int, int, int, int]] = []

        for ann in annotations:
            l, t, r, b = ann["bounds_px"]
            label_text = f"[{ann['label']}]"

            # 1. Pick contrast-adaptive outline color
            outline_color = _pick_contrast_color(thumb, [l, t, r, b], (img_w, img_h), thumb_size)
            fill_color = (*outline_color[:3], FILL_ALPHA)

            # 2. Draw bounding box outline
            box_area = max(0, r - l) * max(0, b - t)
            fill = fill_color if box_area >= MIN_FILL_AREA_PX else None
            draw.rectangle([l, t, r, b], outline=outline_color, fill=fill, width=outline_width)

            # 3. Measure label text
            text_w, text_h = _measure_text(font, label_text)

            # 4. Place pill (deterministic, anti-overlap)
            pad = 4
            pill_w = text_w + pad * 2
            pill_h = text_h + pad * 2
            pill_rect = _place_pill(l, t, r, b, pill_w, pill_h, img_w, img_h, placed_pills)
            placed_pills.append(pill_rect)

            # 5. Leader line if displaced >10px from box corner
            pill_cx = (pill_rect[0] + pill_rect[2]) // 2
            pill_cy = (pill_rect[1] + pill_rect[3]) // 2
            # Distance from pill center to nearest box corner
            displacement = min(
                math.hypot(pill_cx - cx, pill_cy - cy)
                for cx, cy in [(l, t), (r, t), (l, b), (r, b)]
            )
            if displacement > LEADER_LINE_THRESHOLD_PX:
                corner = _nearest_corner(l, t, r, b, pill_cx, pill_cy)
                draw.line([corner, (pill_cx, pill_cy)], fill=outline_color, width=1)

            # 6. Draw pill background + text with halo
            # Use rounded rectangle if available (Pillow 8.2+)
            if hasattr(draw, "rounded_rectangle"):
                draw.rounded_rectangle(list(pill_rect), radius=3, fill=LABEL_BG_COLOR)
            else:
                draw.rectangle(list(pill_rect), fill=LABEL_BG_COLOR)

            _draw_text_with_halo(
                draw,
                (pill_rect[0] + pad, pill_rect[1] + pad),
                label_text,
                font,
            )

        # Composite and return
        final_img = Image.alpha_composite(base_img, overlay)
        out_buf = io.BytesIO()
        final_img.save(out_buf, format="PNG")
        return out_buf.getvalue()

    except Exception as e:
        logger.error(f"Overlay compositing failed: {e}")
        return img_bytes


# ── PNG Utilities ────────────────────────────────────────────────────

def get_png_dimensions(img_bytes: bytes) -> Optional[Tuple[int, int]]:
    """Decode PNG header to get (width, height) in pixels.

    Returns None if Pillow is missing or bytes are invalid.
    """
    if not HAS_PILLOW:
        return None
    try:
        img = Image.open(io.BytesIO(img_bytes))
        return img.size  # (width, height)
    except Exception:
        return None


def map_bounds_to_pixels(
    item_bounds_pt: List[float],
    artboard_rect_pt: List[float],
    png_size_px: Tuple[int, int],
) -> List[int]:
    """Convert Illustrator point-space bounds to PNG pixel-space.

    Returns integer pixel coordinates, clamped to image dimensions,
    with left<=right and top<=bottom guaranteed.

    Args:
        item_bounds_pt: [left, top, right, bottom] in Illustrator points.
        artboard_rect_pt: [left, top, right, bottom] artboard rect.
        png_size_px: (width, height) of the exported PNG.

    Returns:
        [left, top, right, bottom] as clamped integers in pixel coordinates.
    """
    ab_l, ab_t, ab_r, ab_b = artboard_rect_pt
    px_w, px_h = png_size_px

    ab_w_pt = ab_r - ab_l
    ab_h_pt = ab_t - ab_b  # top > bottom in Illustrator

    if ab_w_pt <= 0 or ab_h_pt <= 0:
        return [0, 0, 0, 0]

    scale_x = px_w / ab_w_pt
    scale_y = px_h / ab_h_pt

    i_l, i_t, i_r, i_b = item_bounds_pt

    # X: straightforward offset + scale
    px_left = (i_l - ab_l) * scale_x
    px_right = (i_r - ab_l) * scale_x

    # Y: inverted — Illustrator top maps to pixel 0
    px_top = (ab_t - i_t) * scale_y
    px_bottom = (ab_t - i_b) * scale_y

    # Round to int
    l_px = int(round(px_left))
    r_px = int(round(px_right))
    t_px = int(round(px_top))
    b_px = int(round(px_bottom))

    # Normalize if swapped
    l_px, r_px = sorted((l_px, r_px))
    t_px, b_px = sorted((t_px, b_px))

    # Clamp to image bounds
    l_px = max(0, min(l_px, px_w - 1))
    r_px = max(0, min(r_px, px_w - 1))
    t_px = max(0, min(t_px, px_h - 1))
    b_px = max(0, min(b_px, px_h - 1))

    return [l_px, t_px, r_px, b_px]


# ── Grid Overlay ─────────────────────────────────────────────────────

def draw_grid_overlay(
    img_bytes: bytes,
    artboard_rect_pt: List[float],
    png_size_px: Tuple[int, int],
    cols: int = 0,
    rows: int = 0,
) -> bytes:
    """Draw an evenly-spaced grid with A1-style cell labels onto a PNG.

    Args:
        img_bytes: Raw PNG bytes (the base artboard export).
        artboard_rect_pt: [left, top, right, bottom] artboard rect in points.
        png_size_px: (width, height) of the exported PNG.
        cols: Number of grid columns (0 = adaptive, ~150pt cells).
        rows: Number of grid rows (0 = adaptive, ~150pt cells).

    Returns:
        Annotated PNG bytes with grid lines and labels. If Pillow is missing
        or artboard is zero-size, returns original bytes unchanged.
    """
    if not HAS_PILLOW:
        return img_bytes

    ab_l, ab_t, ab_r, ab_b = artboard_rect_pt
    ab_w = ab_r - ab_l
    ab_h = ab_t - ab_b  # Illustrator: top > bottom

    if ab_w <= 0 or ab_h <= 0:
        return img_bytes

    # Adaptive grid density: ~150pt cells, clamped [2, 8]
    if cols <= 0:
        cols = max(2, min(8, int(round(ab_w / 150))))
    if rows <= 0:
        rows = max(2, min(8, int(round(ab_h / 150))))

    px_w, px_h = png_size_px

    try:
        base_img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        overlay = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        grid_color = (100, 100, 255, 120)  # Semi-transparent blue
        label_bg = (0, 0, 0, 160)
        label_fg = (255, 255, 255, 255)

        font_size = max(10, _compute_font_size(px_w, px_h) - 4)
        font = _load_font(font_size)

        cell_w = px_w / cols
        cell_h = px_h / rows

        # Draw vertical lines
        for c in range(1, cols):
            x = int(round(c * cell_w))
            draw.line([(x, 0), (x, px_h)], fill=grid_color, width=1)

        # Draw horizontal lines
        for r in range(1, rows):
            y = int(round(r * cell_h))
            draw.line([(0, y), (px_w, y)], fill=grid_color, width=1)

        # Draw cell labels (A1 scheme)
        for r in range(rows):
            for c in range(cols):
                label = chr(65 + r) + str(c + 1)
                cx = int(round(c * cell_w + cell_w / 2))
                cy = int(round(r * cell_h + cell_h / 2))

                tw, th = _measure_text(font, label)

                pad = 3
                pill = [cx - tw // 2 - pad, cy - th // 2 - pad,
                        cx + tw // 2 + pad, cy + th // 2 + pad]

                if hasattr(draw, "rounded_rectangle"):
                    draw.rounded_rectangle(pill, radius=2, fill=label_bg)
                else:
                    draw.rectangle(pill, fill=label_bg)

                _draw_text_with_halo(
                    draw,
                    (pill[0] + pad, pill[1] + pad),
                    label,
                    font,
                    fg=label_fg,
                )

        final_img = Image.alpha_composite(base_img, overlay)
        out_buf = io.BytesIO()
        final_img.save(out_buf, format="PNG")
        return out_buf.getvalue()

    except Exception as e:
        logger.error(f"Grid overlay failed: {e}")
        return img_bytes


# ── Ruler Overlay ────────────────────────────────────────────────────

# Candidate intervals (pt) — pick smallest with ≤ MAX_LABELS_PER_AXIS labels
_CANDIDATE_INTERVALS = [25, 50, 100, 200, 500, 1000, 2000, 5000, 10000]
_MAX_LABELS_PER_AXIS = 12
_RULER_BAND_PX = 20
_RULER_BG = (30, 30, 30, 180)       # semi-transparent dark strip
_RULER_TICK_COLOR = (255, 255, 255, 200)
_RULER_MINOR_TICK_COLOR = (200, 200, 200, 140)


def _pick_interval(artboard_dim: float) -> float:
    """Pick the smallest candidate interval giving ≤ MAX_LABELS_PER_AXIS ticks."""
    for iv in _CANDIDATE_INTERVALS:
        if artboard_dim / iv <= _MAX_LABELS_PER_AXIS:
            return float(iv)
    return float(_CANDIDATE_INTERVALS[-1])


def draw_ruler_overlay(
    img_bytes: bytes,
    artboard_width_pt: float,
    artboard_height_pt: float,
    tick_interval_pt: float = 0,
) -> bytes:
    """Draw coordinate axis rulers along top and left edges of a PNG.

    Ruler labels use screen-space: origin at top-left of artboard,
    X rightward, Y downward.  This matches the coordinates in
    ``spatial_context`` (returned by ``set_reference``) and
    ``bounds_screen`` (used in ``vlm_grounding``).

    Args:
        img_bytes: Raw PNG bytes.
        artboard_width_pt: Artboard width in points.
        artboard_height_pt: Artboard height in points.
        tick_interval_pt: Major tick interval in points (0 = auto).

    Returns:
        Annotated PNG bytes (same dimensions, no resize).  Falls back
        to original bytes if Pillow is missing or artboard is zero-size.
    """
    if not HAS_PILLOW:
        return img_bytes
    if artboard_width_pt <= 0 or artboard_height_pt <= 0:
        return img_bytes

    # ── Interval selection ──
    iv_x = tick_interval_pt if tick_interval_pt > 0 else _pick_interval(artboard_width_pt)
    iv_y = tick_interval_pt if tick_interval_pt > 0 else _pick_interval(artboard_height_pt)

    try:
        base_img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        img_w, img_h = base_img.size
        overlay = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # Font size heuristic: 10px normally, 8px for small previews
        font_sz = 10 if min(img_w, img_h) >= 400 else 8
        font = _load_font(font_sz)

        band = _RULER_BAND_PX
        pad = 2  # label padding from edge

        # pt → px scale factors
        sx = img_w / artboard_width_pt
        sy = img_h / artboard_height_pt

        # ── Draw ruler bands ──
        draw.rectangle([0, 0, img_w, band], fill=_RULER_BG)       # top band
        draw.rectangle([0, 0, band, img_h], fill=_RULER_BG)       # left band
        draw.rectangle([0, 0, band, band], fill=_RULER_BG)        # corner overlap

        # ── Origin marker ──
        origin_font = _load_font(font_sz + 2)  # slightly bolder
        _draw_text_with_halo(draw, (pad, pad), "0", origin_font,
                            fg=(255, 255, 255, 255))
        # crosshair lines from corner
        draw.line([(band, 0), (band, band)], fill=_RULER_TICK_COLOR, width=1)
        draw.line([(0, band), (band, band)], fill=_RULER_TICK_COLOR, width=1)

        # ── Minor tick size ──
        minor_h = 5
        major_h = 10

        # ── Helper: draw ticks along one axis ──
        def _draw_axis_ticks(
            axis: str,
            artboard_dim: float,
            interval: float,
            scale: float,
        ) -> None:
            # Minor ticks (half-interval) — only if not too dense
            half_iv = interval / 2
            draw_minors = artboard_dim / half_iv <= 24

            # Major ticks: 0, iv, 2*iv, ... up to last tick ≤ artboard_dim
            max_tick = int(artboard_dim // interval) * int(interval)
            major_ticks = list(range(0, max_tick + 1, int(interval)))

            # Minor tick positions (excluding major positions)
            minor_ticks: List[int] = []
            if draw_minors:
                max_minor = int(artboard_dim // half_iv) * int(half_iv)
                minor_ticks = [
                    t for t in range(0, max_minor + 1, int(half_iv))
                    if t not in set(major_ticks)
                ]

            # Draw minor ticks (no labels)
            for tick_pt in minor_ticks:
                px = int(round(tick_pt * scale))
                if axis == "x":
                    if px < band:
                        continue
                    draw.line([(px, band - minor_h), (px, band)],
                              fill=_RULER_MINOR_TICK_COLOR, width=1)
                else:
                    if px < band:
                        continue
                    draw.line([(band - minor_h, px), (band, px)],
                              fill=_RULER_MINOR_TICK_COLOR, width=1)

            # Draw major ticks with labels (anti-overlap)
            last_label_end = -1  # px position of last label's trailing edge
            for tick_pt in major_ticks:
                px = int(round(tick_pt * scale))
                label = str(tick_pt)

                if axis == "x":
                    # Tick line
                    draw.line([(px, band - major_h), (px, band)],
                              fill=_RULER_TICK_COLOR, width=1)
                    # Label (skip if it would overlap or clip)
                    tw, th = _measure_text(font, label)
                    lx = px + pad
                    if lx < band:
                        lx = band + pad  # avoid corner
                    if lx <= last_label_end + 2:
                        continue  # anti-overlap
                    if lx + tw > img_w:
                        continue  # off-edge
                    ly = pad
                    _draw_text_with_halo(draw, (lx, ly), label, font,
                                        fg=_RULER_TICK_COLOR)
                    last_label_end = lx + tw
                else:
                    # Tick line
                    draw.line([(band - major_h, px), (band, px)],
                              fill=_RULER_TICK_COLOR, width=1)
                    # Label
                    tw, th = _measure_text(font, label)
                    ly = px + pad
                    if ly < band:
                        ly = band + pad
                    if ly <= last_label_end + 2:
                        continue
                    if ly + th > img_h:
                        continue
                    lx = pad
                    _draw_text_with_halo(draw, (lx, ly), label, font,
                                        fg=_RULER_TICK_COLOR)
                    last_label_end = ly + th

        _draw_axis_ticks("x", artboard_width_pt, iv_x, sx)
        _draw_axis_ticks("y", artboard_height_pt, iv_y, sy)

        # ── Terminal extent markers ──
        dim_color = (200, 200, 200, 160)
        # X-axis: show artboard width at the right end
        w_label = str(int(artboard_width_pt))
        w_tw, w_th = _measure_text(font, w_label)
        w_px = int(round(artboard_width_pt * sx))
        if w_px - w_tw - pad > band:  # only if it fits
            _draw_text_with_halo(draw, (w_px - w_tw - pad, pad), w_label,
                                font, fg=dim_color)
            draw.line([(w_px - 1, 0), (w_px - 1, band)],
                      fill=dim_color, width=1)
        # Y-axis: show artboard height at the bottom end
        h_label = str(int(artboard_height_pt))
        h_tw, h_th = _measure_text(font, h_label)
        h_px = int(round(artboard_height_pt * sy))
        if h_px - h_th - pad > band:
            _draw_text_with_halo(draw, (pad, h_px - h_th - pad), h_label,
                                font, fg=dim_color)
            draw.line([(0, h_px - 1), (band, h_px - 1)],
                      fill=dim_color, width=1)

        final_img = Image.alpha_composite(base_img, overlay)
        out_buf = io.BytesIO()
        final_img.save(out_buf, format="PNG")
        return out_buf.getvalue()

    except Exception as e:
        logger.error(f"Ruler overlay failed: {e}")
        return img_bytes


# ── Probe-Point Overlay ──────────────────────────────────────────────

# Visual constants for probe markers
_PROBE_RADIUS = 6           # circle radius in pixels
_PROBE_CROSSHAIR = 10       # crosshair half-length in pixels
_PROBE_FONT_SIZE = 12

# 6-color probe palette (distinct from annotation outline colors)
_PROBE_PALETTE = [
    (255, 60,  60,  220),   # red
    (60,  180, 255, 220),   # blue
    (60,  220, 60,  220),   # green
    (255, 200, 40,  220),   # yellow
    (200, 80,  255, 220),   # purple
    (255, 140, 40,  220),   # orange
]


def draw_probe_overlay(
    img_bytes: bytes,
    probe_points: List[dict],
    artboard_width_pt: float,
    artboard_height_pt: float,
) -> bytes:
    """Draw coordinate probe markers onto a PNG image.

    Each probe point is rendered as a colored circle with crosshair lines
    and a label showing the name and coordinates.

    Probe points use screen-space coordinates: origin at top-left of artboard,
    X rightward, Y downward. This matches the ruler overlay convention.

    Args:
        img_bytes: Raw PNG bytes (base image).
        probe_points: List of dicts with keys:
            - x (float): X coordinate in artboard points (screen-space).
            - y (float): Y coordinate in artboard points (screen-space, Y-down).
            - label (str, optional): Display label for the probe point.
        artboard_width_pt: Artboard width in points.
        artboard_height_pt: Artboard height in points.

    Returns:
        PNG bytes with probe markers composited. Returns original bytes
        if Pillow is missing, no points provided, or an error occurs.
    """
    if not HAS_PILLOW:
        return img_bytes
    if not probe_points:
        return img_bytes
    if artboard_width_pt <= 0 or artboard_height_pt <= 0:
        return img_bytes

    try:
        from PIL import Image, ImageDraw

        base_img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        img_w, img_h = base_img.size
        overlay = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        scale_x = img_w / artboard_width_pt
        scale_y = img_h / artboard_height_pt

        font = _load_font(_PROBE_FONT_SIZE)
        radius = _PROBE_RADIUS
        cross = _PROBE_CROSSHAIR

        for i, pt in enumerate(probe_points):
            px_x = pt.get("x", 0) * scale_x
            px_y = pt.get("y", 0) * scale_y
            cx = int(round(px_x))
            cy = int(round(px_y))

            color = _PROBE_PALETTE[i % len(_PROBE_PALETTE)]
            label = pt.get("label", "")

            # Crosshair lines
            draw.line(
                [(cx - cross, cy), (cx + cross, cy)],
                fill=color, width=2,
            )
            draw.line(
                [(cx, cy - cross), (cx, cy + cross)],
                fill=color, width=2,
            )

            # Filled circle
            draw.ellipse(
                [cx - radius, cy - radius, cx + radius, cy + radius],
                fill=color,
                outline=(255, 255, 255, 240),
                width=1,
            )

            # Label pill: "label (x, y)"
            coord_text = f"({pt.get('x', 0):.0f}, {pt.get('y', 0):.0f})"
            display = f"{label} {coord_text}" if label else coord_text
            tw, th = _measure_text(font, display)

            # Position label: to the right of the marker, offset slightly
            lx = cx + radius + 4
            ly = cy - th // 2
            # Clamp to image
            if lx + tw + 4 > img_w:
                lx = cx - radius - tw - 4  # flip to left
            if ly < 2:
                ly = 2
            if ly + th + 2 > img_h:
                ly = img_h - th - 2

            # Draw background pill
            pill_pad = 3
            draw.rounded_rectangle(
                [lx - pill_pad, ly - pill_pad, lx + tw + pill_pad, ly + th + pill_pad],
                radius=4,
                fill=(0, 0, 0, 160),
            )
            _draw_text_with_halo(draw, (lx, ly), display, font, fg=(255, 255, 255, 255))

        final_img = Image.alpha_composite(base_img, overlay)
        out_buf = io.BytesIO()
        final_img.save(out_buf, format="PNG")
        return out_buf.getvalue()

    except Exception as e:
        logger.error(f"Probe overlay failed: {e}")
        return img_bytes


