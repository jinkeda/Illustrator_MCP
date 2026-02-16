"""
svgd.py — Pure-Python SVG path data (d attribute) parser.

Parses SVG `d` strings into geometry IR compatible with
irBezierPath (geo_ir.jsx).

Supported commands: M/m, L/l, H/h, V/v, C/c, S/s, Q/q, T/t, Z/z
Deferred (Phase 2): A/a arcs → raises ValueError

Output IR matches geo_ir.jsx irBezierPath contract:
  {v: 1, ir: "path", kind: "bezier", handleSpace: "absolute",
   points: [[x,y],...], handles: [{in, out, type},...], closed: bool}

Multi-subpath returns:
  {ir: "multi", subpaths: [pathIR, ...], all_closed: bool}

No external dependencies — pure Python math.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union


# ── Constants ──────────────────────────────────────────────────────────

GEO_IR_VERSION = 1

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
                # Stray sign or dot with no digits — skip
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
        ValueError: on empty path, arc commands (Phase 2), or parse errors.
    """
    if not d or not d.strip():
        raise ValueError("Empty SVG path data")

    tokens = tokenize_d(d)
    if not tokens:
        raise ValueError("No valid tokens in SVG path data")

    subpaths: List[_SubpathBuilder] = []
    current: Optional[_SubpathBuilder] = None

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
            raise ValueError(
                "Arc commands (A/a) not supported yet. "
                "Decompose arcs to cubic Bézier segments before import, "
                "or wait for Phase 2 arc support."
            )

        # Commands that consume coordinate pairs
        if cmd_upper == "M":
            # MoveTo — starts a new subpath
            x, y = _next_num(), _next_num()
            if is_rel:
                x += cx
                y += cy
            cx, cy = x, y
            sx, sy = x, y
            prev_cp = None

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
                cx, cy = x, y
                current.add_line_to([cx, cy])
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
                cx, cy = x, y
                current.add_line_to([cx, cy])
                prev_cp = None
                if not _has_numbers():
                    break

        elif cmd_upper == "H":
            while True:
                x = _next_num()
                if is_rel:
                    x += cx
                cx = x
                current.add_line_to([cx, cy])
                prev_cp = None
                if not _has_numbers():
                    break

        elif cmd_upper == "V":
            while True:
                y = _next_num()
                if is_rel:
                    y += cy
                cy = y
                current.add_line_to([cx, cy])
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
                current.add_cubic_to([x1, y1], [x2, y2], [x, y])
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
                # Reflect previous control point
                if prev_cp is not None:
                    x1 = 2 * cx - prev_cp[0]
                    y1 = 2 * cy - prev_cp[1]
                else:
                    x1, y1 = cx, cy
                current.add_cubic_to([x1, y1], [x2, y2], [x, y])
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
                # Degree-elevate Q → C
                cp1, cp2 = _elevate_quadratic(
                    [cx, cy], [qx1, qy1], [qx, qy]
                )
                current.add_cubic_to(cp1, cp2, [qx, qy])
                prev_cp = [qx1, qy1]  # Store Q control for T reflection
                cx, cy = qx, qy
                if not _has_numbers():
                    break

        elif cmd_upper == "T":
            while True:
                qx, qy = _next_num(), _next_num()
                if is_rel:
                    qx += cx; qy += cy
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
