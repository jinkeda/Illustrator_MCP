"""
svgd.py — Pure-Python SVG path data (d attribute) parser.

Parses SVG `d` strings into geometry IR compatible with
irBezierPath (geo_ir.jsx).

Supported commands: M/m, L/l, H/h, V/v, C/c, S/s, Q/q, T/t, A/a, Z/z

Output IR matches geo_ir.jsx irBezierPath contract:
  {v: 1, ir: "path", kind: "bezier", handleSpace: "absolute",
   points: [[x,y],...], handles: [{in, out, type},...], closed: bool}

Multi-subpath returns:
  {ir: "multi", subpaths: [pathIR, ...], all_closed: bool}

No external dependencies — pure Python math.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple, Union


# ── Constants ──────────────────────────────────────────────────────────

GEO_IR_VERSION = 1

# [H7] Safety limits — hardcoded, no user override
MAX_D_LENGTH = 50_000       # max chars in d attribute
MAX_SEGMENTS = 5_000        # max total segments (points) across all subpaths
MAX_SUBPATHS = 100          # max number of M commands
MAX_COORD_ABS = 100_000.0   # max absolute coordinate value
MAX_TOKENS = 50_000         # max tokenizer output length

# [H6] Arc numeric epsilon
_ARC_EPSILON = 1e-10

_COMMANDS = set("MmLlHhVvCcSsQqTtAaZz")


# ── Tokenizer ──────────────────────────────────────────────────────────

def tokenize_d(d: str) -> List[Union[str, float]]:
    """Tokenize an SVG d attribute string into commands and numbers.

    Handles:
    - Comma/space separators
    - Sign-separated numbers (M10-20 → M, 10, -20)
    - Scientific notation (1.5e-3)
    - Decimal shorthand (.5.3 → 0.5, 0.3)
    - Omitted repeated command letters
    """
    tokens: List[Union[str, float]] = []
    i = 0
    n = len(d)

    while i < n:
        c = d[i]

        # Skip whitespace and commas
        if c in " \t\r\n,":
            i += 1
            continue

        # Command letter
        if c in _COMMANDS:
            tokens.append(c)
            i += 1
            continue

        # Number: optional sign, digits, optional decimal, optional exponent
        if c in "0123456789.+-":
            start = i
            # Sign
            if c in "+-":
                i += 1
                if i >= n:
                    break

            # Integer part
            has_digit = False
            while i < n and d[i].isdigit():
                has_digit = True
                i += 1

            # Decimal point
            has_dot = False
            if i < n and d[i] == ".":
                has_dot = True
                i += 1
                while i < n and d[i].isdigit():
                    has_digit = True
                    i += 1

            if not has_digit:
                # B8: Stray sign or dot with no trailing digits — advance past
                # the character (start+1) so we don't re-visit it.  This is
                # safe even at end-of-input because the outer `while i < n`
                # will terminate.
                i = start + 1
                continue

            # Exponent
            if i < n and d[i] in "eE":
                i += 1
                if i < n and d[i] in "+-":
                    i += 1
                while i < n and d[i].isdigit():
                    i += 1

            num_str = d[start:i]
            tokens.append(float(num_str))

            # Peek ahead for decimal shorthand: if next char is '.'
            # followed by a digit, it starts a new number (e.g., ".5.3")
            # This is handled by the loop naturally since '.' triggers
            # a new number parse.
            continue

        # Unknown character — skip
        i += 1

    return tokens


# ── Parser ─────────────────────────────────────────────────────────────

def _elevate_quadratic(
    p0: List[float], p1: List[float], p2: List[float]
) -> Tuple[List[float], List[float]]:
    """Degree-elevate a quadratic Bézier (Q) to cubic (C).

    Q(p0, p1, p2) → C(p0, cp1, cp2, p2) where:
      cp1 = p0 + 2/3 * (p1 - p0)
      cp2 = p2 + 2/3 * (p1 - p2)
    """
    cp1 = [
        p0[0] + 2.0 / 3.0 * (p1[0] - p0[0]),
        p0[1] + 2.0 / 3.0 * (p1[1] - p0[1]),
    ]
    cp2 = [
        p2[0] + 2.0 / 3.0 * (p1[0] - p2[0]),
        p2[1] + 2.0 / 3.0 * (p1[1] - p2[1]),
    ]
    return cp1, cp2


# ── Arc-to-cubic conversion (W3C SVG 1.1 §F.6) ───────────────────────


def _clamp(val: float, lo: float, hi: float) -> float:
    """Clamp val to [lo, hi]. [H6] prevents math.acos domain errors."""
    return max(lo, min(hi, val))


def _arc_to_center(
    x1: float, y1: float,
    rx: float, ry: float,
    phi_deg: float,
    fa: int, fs: int,
    x2: float, y2: float,
) -> Tuple[float, float, float, float, float, float]:
    """W3C SVG 1.1 §F.6.5 — endpoint → center parameterization.

    Returns (cx, cy, theta1, dtheta, rx_scaled, ry_scaled).
    rx/ry may be scaled up per §F.6.6.3 if too small.
    """
    phi = math.radians(phi_deg)
    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)

    # Step 1: Compute (x1', y1')
    dx2 = (x1 - x2) / 2.0
    dy2 = (y1 - y2) / 2.0
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2

    # Step 2: Scale radii if too small (§F.6.6.3)
    x1p_sq = x1p * x1p
    y1p_sq = y1p * y1p
    rx_sq = rx * rx
    ry_sq = ry * ry

    lam = x1p_sq / rx_sq + y1p_sq / ry_sq
    if lam > 1.0:
        lam_sqrt = math.sqrt(lam)
        rx *= lam_sqrt
        ry *= lam_sqrt
        rx_sq = rx * rx
        ry_sq = ry * ry

    # Step 3: Compute center' (cx', cy')
    num = max(0.0, rx_sq * ry_sq - rx_sq * y1p_sq - ry_sq * x1p_sq)
    den = rx_sq * y1p_sq + ry_sq * x1p_sq
    if den < _ARC_EPSILON:
        # Degenerate — points coincide or nearly so
        sq = 0.0
    else:
        sq = math.sqrt(num / den)
    if fa == fs:
        sq = -sq

    cxp = sq * rx * y1p / ry
    cyp = -sq * ry * x1p / rx

    # Step 4: Compute center (cx, cy) from center'
    cx = cos_phi * cxp - sin_phi * cyp + (x1 + x2) / 2.0
    cy = sin_phi * cxp + cos_phi * cyp + (y1 + y2) / 2.0

    # Step 5: Compute theta1 and dtheta
    def _angle(ux: float, uy: float, vx: float, vy: float) -> float:
        dot = ux * vx + uy * vy
        cross = ux * vy - uy * vx
        mag = math.sqrt((ux * ux + uy * uy) * (vx * vx + vy * vy))
        if mag < _ARC_EPSILON:
            return 0.0
        cos_a = _clamp(dot / mag, -1.0, 1.0)
        a = math.acos(cos_a)
        return -a if cross < 0 else a

    theta1 = _angle(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dtheta = _angle(
        (x1p - cxp) / rx, (y1p - cyp) / ry,
        (-x1p - cxp) / rx, (-y1p - cyp) / ry,
    )

    # Constrain dtheta per sweep flag
    if fs == 0 and dtheta > 0:
        dtheta -= 2.0 * math.pi
    elif fs == 1 and dtheta < 0:
        dtheta += 2.0 * math.pi

    return cx, cy, theta1, dtheta, rx, ry


def _arc_segment_to_cubic(
    cx: float, cy: float,
    rx: float, ry: float,
    phi_deg: float,
    theta1: float, dtheta: float,
) -> List[Tuple[List[float], List[float], List[float]]]:
    """Approximate an arc segment as one or more cubic Béziers.

    Splits into ≤90° sub-arcs and uses the standard kappa approximation.
    Returns list of (cp1, cp2, end) tuples in document space.
    """
    phi = math.radians(phi_deg)
    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)

    # Split into ≤90° arcs
    n_segs = max(1, int(math.ceil(abs(dtheta) / (math.pi / 2.0))))
    seg_angle = dtheta / n_segs

    # Kappa for unit-arc approximation:
    # alpha = sin(seg_angle) * (sqrt(4 + 3*tan(seg_angle/2)^2) - 1) / 3
    half = seg_angle / 2.0
    cos_half = math.cos(half)
    if abs(cos_half) < _ARC_EPSILON:
        alpha = 0.0
    else:
        tan_half = math.sin(half) / cos_half
        alpha = math.sin(seg_angle) * (math.sqrt(4.0 + 3.0 * tan_half * tan_half) - 1.0) / 3.0

    def _point_on_ellipse(theta: float) -> Tuple[float, float]:
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        x = cos_phi * rx * cos_t - sin_phi * ry * sin_t + cx
        y = sin_phi * rx * cos_t + cos_phi * ry * sin_t + cy
        return x, y

    def _derivative(theta: float) -> Tuple[float, float]:
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        dx = -cos_phi * rx * sin_t - sin_phi * ry * cos_t
        dy = -sin_phi * rx * sin_t + cos_phi * ry * cos_t
        return dx, dy

    cubics: List[Tuple[List[float], List[float], List[float]]] = []
    t1 = theta1

    for _ in range(n_segs):
        t2 = t1 + seg_angle
        p1x, p1y = _point_on_ellipse(t1)
        p2x, p2y = _point_on_ellipse(t2)
        d1x, d1y = _derivative(t1)
        d2x, d2y = _derivative(t2)

        cp1 = [p1x + alpha * d1x, p1y + alpha * d1y]
        cp2 = [p2x - alpha * d2x, p2y - alpha * d2y]
        end = [p2x, p2y]

        cubics.append((cp1, cp2, end))
        t1 = t2

    return cubics


def arc_to_cubics(
    x1: float, y1: float,
    rx: float, ry: float,
    x_rot: float,
    large_arc: int, sweep: int,
    x2: float, y2: float,
) -> List[Tuple[List[float], List[float], List[float]]]:
    """Convert an SVG arc command to cubic Bézier segments.

    [H6] Handles all degenerate cases:
    - Zero radii → empty list (caller should emit lineTo)
    - Coincident endpoints → empty list
    - Too-small radii → scaled up per W3C spec

    Returns list of (cp1, cp2, end) tuples.
    """
    # [H6] Degenerate: zero radius → lineTo
    if abs(rx) < _ARC_EPSILON or abs(ry) < _ARC_EPSILON:
        return []

    # [H6] Degenerate: coincident endpoints → nothing
    if abs(x1 - x2) < _ARC_EPSILON and abs(y1 - y2) < _ARC_EPSILON:
        return []

    rx = abs(rx)
    ry = abs(ry)

    cx, cy, theta1, dtheta, rx, ry = _arc_to_center(
        x1, y1, rx, ry, x_rot, large_arc, sweep, x2, y2
    )

    return _arc_segment_to_cubic(cx, cy, rx, ry, x_rot, theta1, dtheta)


def _make_handle(
    h_in: Optional[List[float]], h_out: Optional[List[float]]
) -> Dict[str, Any]:
    """Create a handle entry matching irBezierPath contract."""
    if h_in is None and h_out is None:
        kind = "corner"
    else:
        kind = "smooth"
    return {"in": h_in, "out": h_out, "type": kind}


class _SubpathBuilder:
    """Accumulates points and handles for a single subpath."""

    def __init__(self) -> None:
        self.points: List[List[float]] = []
        self.handles: List[Dict[str, Any]] = []
        self.closed: bool = False

    def add_line_to(self, pt: List[float]) -> None:
        """Add a line segment to pt (corner point, no handles)."""
        # Set out-handle of previous point to None (corner)
        self.points.append(list(pt))
        self.handles.append(_make_handle(None, None))

    def add_cubic_to(
        self,
        cp1: List[float],
        cp2: List[float],
        end: List[float],
    ) -> None:
        """Add a cubic Bézier segment.

        cp1 is the out-handle of the PREVIOUS point.
        cp2 is the in-handle of the NEW point.
        """
        # Set out-handle of previous point
        if self.handles:
            prev = self.handles[-1]
            prev["out"] = list(cp1)
            # If it now has either handle, upgrade to smooth
            if prev["in"] is not None or prev["out"] is not None:
                prev["type"] = "smooth"

        self.points.append(list(end))
        self.handles.append(_make_handle(list(cp2), None))

    def move_to(self, pt: List[float]) -> None:
        """Start the subpath at pt."""
        self.points.append(list(pt))
        self.handles.append(_make_handle(None, None))

    def to_ir(self) -> Dict[str, Any]:
        """Convert to geometry IR dict."""
        return {
            "v": GEO_IR_VERSION,
            "ir": "path",
            "kind": "bezier",
            "handleSpace": "absolute",
            "points": self.points,
            "handles": self.handles,
            "closed": self.closed,
            "meta": {},
        }


def parse_svg_d(d: str) -> Dict[str, Any]:
    """Parse an SVG path `d` attribute string into geometry IR.

    Returns:
        Single subpath: {ir: "path", kind: "bezier", ...}
        Multi-subpath:  {ir: "multi", subpaths: [...], all_closed: bool}

    Raises:
        ValueError: on empty path, safety limit violations, or parse errors.
    """
    if not d or not d.strip():
        raise ValueError("Empty SVG path data")

    # [H7] Safety limits
    if len(d) > MAX_D_LENGTH:
        raise ValueError(
            f"E_D_TOO_LONG: SVG path data exceeds {MAX_D_LENGTH} chars "
            f"(got {len(d)})"
        )

    tokens = tokenize_d(d)
    if not tokens:
        raise ValueError("No valid tokens in SVG path data")

    if len(tokens) > MAX_TOKENS:
        raise ValueError(
            f"E_TOO_MANY_TOKENS: Tokenized path exceeds {MAX_TOKENS} tokens "
            f"(got {len(tokens)})"
        )

    subpaths: List[_SubpathBuilder] = []
    current: Optional[_SubpathBuilder] = None
    total_segments = 0  # [H7] running segment counter

    # Current position
    cx, cy = 0.0, 0.0
    # Start of current subpath (for Z)
    sx, sy = 0.0, 0.0
    # Previous control point (for S, T shorthand)
    prev_cp: Optional[List[float]] = None
    # Previous command (for repeated command detection)
    prev_cmd: Optional[str] = None

    i = 0
    n_tok = len(tokens)

    def _check_coord(val: float) -> None:
        """[H7] Assert coordinate is within safe range."""
        if abs(val) > MAX_COORD_ABS:
            raise ValueError(
                f"E_COORD_OVERFLOW: Coordinate {val:.1f} exceeds "
                f"±{MAX_COORD_ABS}"
            )

    def _add_segment() -> None:
        """[H7] Increment segment counter and check limit."""
        nonlocal total_segments
        total_segments += 1
        if total_segments > MAX_SEGMENTS:
            raise ValueError(
                f"E_TOO_MANY_SEGMENTS: Path exceeds {MAX_SEGMENTS} segments"
            )

    def _next_num() -> float:
        nonlocal i
        if i >= n_tok:
            raise ValueError(f"Expected number at token {i}, got end of path")
        val = tokens[i]
        if not isinstance(val, (int, float)):
            raise ValueError(f"Expected number at token {i}, got '{val}'")
        i += 1
        return float(val)

    def _has_numbers() -> bool:
        """Check if next token is a number (for repeated params)."""
        return i < n_tok and isinstance(tokens[i], (int, float))

    while i < n_tok:
        tok = tokens[i]

        # Determine command
        if isinstance(tok, str) and tok in _COMMANDS:
            cmd = tok
            i += 1
        elif isinstance(tok, (int, float)) and prev_cmd is not None:
            # Implicit command repetition
            # After M, implicit repeats become L; after m, implicit repeats become l
            if prev_cmd == "M":
                cmd = "L"
            elif prev_cmd == "m":
                cmd = "l"
            else:
                cmd = prev_cmd
        else:
            raise ValueError(f"Unexpected token at position {i}: {tok}")

        is_rel = cmd.islower()
        cmd_upper = cmd.upper()

        if cmd_upper == "Z":
            # Close current subpath
            if current is not None:
                current.closed = True
            cx, cy = sx, sy
            prev_cp = None
            prev_cmd = cmd
            continue

        if cmd_upper == "A":
            while True:
                arc_rx = abs(_next_num())
                arc_ry = abs(_next_num())
                arc_rot = _next_num()
                arc_fa = int(_next_num())
                arc_fs = int(_next_num())
                ax, ay = _next_num(), _next_num()
                if is_rel:
                    ax += cx; ay += cy
                _check_coord(ax); _check_coord(ay)

                if current is None:
                    raise ValueError("Arc command before MoveTo")

                cubics = arc_to_cubics(
                    cx, cy, arc_rx, arc_ry, arc_rot,
                    arc_fa, arc_fs, ax, ay,
                )
                if not cubics:
                    # [H6] Degenerate arc → lineTo
                    current.add_line_to([ax, ay])
                    _add_segment()
                else:
                    for cp1, cp2, end in cubics:
                        current.add_cubic_to(cp1, cp2, end)
                        _add_segment()

                cx, cy = ax, ay
                prev_cp = None
                if not _has_numbers():
                    break
            prev_cmd = cmd
            continue

        # Commands that consume coordinate pairs
        if cmd_upper == "M":
            # MoveTo — starts a new subpath
            x, y = _next_num(), _next_num()
            if is_rel:
                x += cx
                y += cy
            _check_coord(x); _check_coord(y)
            cx, cy = x, y
            sx, sy = x, y
            prev_cp = None

            # [H7] Subpath count limit
            if len(subpaths) >= MAX_SUBPATHS:
                raise ValueError(
                    f"E_TOO_MANY_SUBPATHS: Path exceeds {MAX_SUBPATHS} subpaths"
                )

            current = _SubpathBuilder()
            current.move_to([cx, cy])
            subpaths.append(current)
            prev_cmd = cmd

            # Implicit LineTo for additional coordinate pairs
            while _has_numbers():
                x, y = _next_num(), _next_num()
                if is_rel:
                    x += cx
                    y += cy
                _check_coord(x); _check_coord(y)
                cx, cy = x, y
                current.add_line_to([cx, cy])
                _add_segment()
            continue

        # All remaining commands require an active subpath
        if current is None:
            raise ValueError(f"Command '{cmd}' before MoveTo")

        if cmd_upper == "L":
            while True:
                x, y = _next_num(), _next_num()
                if is_rel:
                    x += cx
                    y += cy
                _check_coord(x); _check_coord(y)
                cx, cy = x, y
                current.add_line_to([cx, cy])
                _add_segment()
                prev_cp = None
                if not _has_numbers():
                    break

        elif cmd_upper == "H":
            while True:
                x = _next_num()
                if is_rel:
                    x += cx
                _check_coord(x)
                cx = x
                current.add_line_to([cx, cy])
                _add_segment()
                prev_cp = None
                if not _has_numbers():
                    break

        elif cmd_upper == "V":
            while True:
                y = _next_num()
                if is_rel:
                    y += cy
                _check_coord(y)
                cy = y
                current.add_line_to([cx, cy])
                _add_segment()
                prev_cp = None
                if not _has_numbers():
                    break

        elif cmd_upper == "C":
            while True:
                x1, y1 = _next_num(), _next_num()
                x2, y2 = _next_num(), _next_num()
                x, y = _next_num(), _next_num()
                if is_rel:
                    x1 += cx; y1 += cy
                    x2 += cx; y2 += cy
                    x += cx; y += cy
                _check_coord(x); _check_coord(y)
                current.add_cubic_to([x1, y1], [x2, y2], [x, y])
                _add_segment()
                prev_cp = [x2, y2]
                cx, cy = x, y
                if not _has_numbers():
                    break

        elif cmd_upper == "S":
            while True:
                x2, y2 = _next_num(), _next_num()
                x, y = _next_num(), _next_num()
                if is_rel:
                    x2 += cx; y2 += cy
                    x += cx; y += cy
                _check_coord(x); _check_coord(y)
                # Reflect previous control point
                if prev_cp is not None:
                    x1 = 2 * cx - prev_cp[0]
                    y1 = 2 * cy - prev_cp[1]
                else:
                    x1, y1 = cx, cy
                current.add_cubic_to([x1, y1], [x2, y2], [x, y])
                _add_segment()
                prev_cp = [x2, y2]
                cx, cy = x, y
                if not _has_numbers():
                    break

        elif cmd_upper == "Q":
            while True:
                qx1, qy1 = _next_num(), _next_num()
                qx, qy = _next_num(), _next_num()
                if is_rel:
                    qx1 += cx; qy1 += cy
                    qx += cx; qy += cy
                _check_coord(qx); _check_coord(qy)
                # Degree-elevate Q → C
                cp1, cp2 = _elevate_quadratic(
                    [cx, cy], [qx1, qy1], [qx, qy]
                )
                current.add_cubic_to(cp1, cp2, [qx, qy])
                _add_segment()
                prev_cp = [qx1, qy1]  # Store Q control for T reflection
                cx, cy = qx, qy
                if not _has_numbers():
                    break

        elif cmd_upper == "T":
            while True:
                qx, qy = _next_num(), _next_num()
                if is_rel:
                    qx += cx; qy += cy
                _check_coord(qx); _check_coord(qy)
                # Reflect previous Q control point
                if prev_cp is not None:
                    qx1 = 2 * cx - prev_cp[0]
                    qy1 = 2 * cy - prev_cp[1]
                else:
                    qx1, qy1 = cx, cy
                cp1, cp2 = _elevate_quadratic(
                    [cx, cy], [qx1, qy1], [qx, qy]
                )
                current.add_cubic_to(cp1, cp2, [qx, qy])
                _add_segment()
                prev_cp = [qx1, qy1]
                cx, cy = qx, qy
                if not _has_numbers():
                    break

        else:
            raise ValueError(f"Unknown SVG path command: {cmd}")

        prev_cmd = cmd

    # ── Build output ──────────────────────────────────────────────────

    if not subpaths:
        raise ValueError("No subpaths found in SVG path data")

    # Filter out empty subpaths (M with no following commands)
    valid_subpaths = [sp for sp in subpaths if len(sp.points) >= 2]
    if not valid_subpaths:
        raise ValueError(
            "SVG path has no subpaths with >= 2 points"
        )

    # Single subpath → return path IR directly
    if len(valid_subpaths) == 1:
        return valid_subpaths[0].to_ir()

    # Multi-subpath → return multi IR
    all_closed = all(sp.closed for sp in valid_subpaths)
    return {
        "ir": "multi",
        "subpaths": [sp.to_ir() for sp in valid_subpaths],
        "all_closed": all_closed,
    }
