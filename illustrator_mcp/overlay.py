"""
VLM Debug Overlay — annotated artboard preview for vision-language models.

Pure image compositing module. Draws numbered bounding boxes onto a PNG
so VLM agents can reference items by label (e.g., "Move [3] down 10px").

Gracefully degrades if Pillow is not installed.
"""

from __future__ import annotations

import io
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

# Visual constants
OUTLINE_COLOR = (255, 0, 255, 160)    # Magenta, semi-transparent
FILL_HINT     = (255, 0, 255, 20)     # Very subtle interior tint (~8% alpha)
MIN_FILL_AREA_PX = 400                # Skip fill for tiny boxes (<20×20px)
LABEL_BG_COLOR = (0, 0, 0, 180)       # Semi-transparent black for label pill
LABEL_FG_COLOR = (255, 255, 255, 255) # White text


def composite_overlay(
    img_bytes: bytes,
    annotations: List[dict],
) -> bytes:
    """Draw numbered labels and bounding boxes onto a PNG image.

    Args:
        img_bytes: Raw PNG bytes (the base artboard export).
        annotations: List of dicts, each with:
            - label: str — display text (e.g., "1", "2")
            - bounds_px: [left, top, right, bottom] in pixel coords (ints, clamped)

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

        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

        for ann in annotations:
            l, t, r, b = ann["bounds_px"]
            label_text = f"[{ann['label']}]"

            # 1. Draw bounding box outline (semi-transparent, thin)
            box_area = max(0, r - l) * max(0, b - t)
            fill = FILL_HINT if box_area >= MIN_FILL_AREA_PX else None
            draw.rectangle([l, t, r, b], outline=OUTLINE_COLOR, fill=fill, width=1)

            # 2. Measure label text
            if font and hasattr(font, "getbbox"):
                bbox = font.getbbox(label_text)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
            else:
                text_w, text_h = len(label_text) * 7, 12

            # 3. Place label outside the box — try positions in priority order
            pad = 2
            pill_w = text_w + pad * 2
            pill_h = text_h + pad * 2

            # Priority: above-left, above-right, below-left, inside-top-left
            candidates = [
                (l, t - pill_h),            # above-left
                (r - pill_w, t - pill_h),    # above-right
                (l, b),                      # below-left
                (l, t),                      # inside top-left (fallback)
            ]

            pill_x, pill_y = l, t  # default fallback
            for cx, cy in candidates:
                if 0 <= cy and cy + pill_h <= img_h and 0 <= cx and cx + pill_w <= img_w:
                    pill_x, pill_y = cx, cy
                    break

            pill_bounds = [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h]

            # 4. Draw label pill (semi-transparent black bg) + white text
            draw.rectangle(pill_bounds, fill=LABEL_BG_COLOR)
            draw.text(
                (pill_x + pad, pill_y + pad),
                label_text,
                fill=LABEL_FG_COLOR,
                font=font,
            )

        # Composite and return
        final_img = Image.alpha_composite(base_img, overlay)
        out_buf = io.BytesIO()
        final_img.save(out_buf, format="PNG")
        return out_buf.getvalue()

    except Exception as e:
        logger.error(f"Overlay compositing failed: {e}")
        return img_bytes


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
    l = int(round(px_left))
    r = int(round(px_right))
    t = int(round(px_top))
    b = int(round(px_bottom))

    # Normalize if swapped
    l, r = sorted((l, r))
    t, b = sorted((t, b))

    # Clamp to image bounds
    l = max(0, min(l, px_w - 1))
    r = max(0, min(r, px_w - 1))
    t = max(0, min(t, px_h - 1))
    b = max(0, min(b, px_h - 1))

    return [l, t, r, b]


def draw_grid_overlay(
    img_bytes: bytes,
    artboard_rect_pt: List[float],
    png_size_px: Tuple[int, int],
    cols: int = 4,
    rows: int = 4,
) -> bytes:
    """Draw an evenly-spaced grid with A1-style cell labels onto a PNG.

    Args:
        img_bytes: Raw PNG bytes (the base artboard export).
        artboard_rect_pt: [left, top, right, bottom] artboard rect in points.
        png_size_px: (width, height) of the exported PNG.
        cols: Number of grid columns (default 4).
        rows: Number of grid rows (default 4).

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

    px_w, px_h = png_size_px

    try:
        base_img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        overlay = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        grid_color = (100, 100, 255, 120)  # Semi-transparent blue
        label_bg = (0, 0, 0, 160)
        label_fg = (255, 255, 255, 255)

        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

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

                if font and hasattr(font, "getbbox"):
                    bbox = font.getbbox(label)
                    tw = bbox[2] - bbox[0]
                    th = bbox[3] - bbox[1]
                else:
                    tw, th = len(label) * 7, 12

                pad = 2
                pill = [cx - tw // 2 - pad, cy - th // 2 - pad,
                        cx + tw // 2 + pad, cy + th // 2 + pad]
                draw.rectangle(pill, fill=label_bg)
                draw.text((pill[0] + pad, pill[1] + pad), label,
                          fill=label_fg, font=font)

        final_img = Image.alpha_composite(base_img, overlay)
        out_buf = io.BytesIO()
        final_img.save(out_buf, format="PNG")
        return out_buf.getvalue()

    except Exception as e:
        logger.error(f"Grid overlay failed: {e}")
        return img_bytes
