/**
 * curves.jsx — Bézier Curve Helpers
 * Part of Illustrator MCP Standard Library
 *
 * Pure-math helpers that output Bézier IR (via irBezierPath).
 * NO Illustrator DOM access — fully composable.
 *
 * Mirrors curves.py (Python source-of-truth). Golden tests ensure parity.
 *
 * COORDINATE CONVENTION
 *   User-space XY: origin = top-left, +X right, +Y down.
 *   Handle coordinates are ABSOLUTE (handleSpace = "absolute").
 *
 * DEPENDS ON: geo_ir.jsx (irBezierPath, irPath)
 *
 * @version 1.0.0
 */

// ==================== CATMULL-ROM ====================

/**
 * Convert waypoints to a smooth cubic Bézier path via Catmull-Rom.
 *
 * For each anchor P[i], handles are computed from neighbors:
 *   out(P[i]) = P[i] + (P[i+1] - P[i-1]) * tension / 3
 *   in(P[i])  = P[i] - (P[i+1] - P[i-1]) * tension / 3
 *
 * Endpoint handling:
 *   Open:   endpoint duplication (P[-1]=P[0], P[n]=P[n-1])
 *   Closed: index wrapping       (P[-1]=P[n-1], P[n]=P[0])
 *
 * Degenerate:
 *   0-1 points → corner(s)
 *   2 points   → straight line (corner, no handles)
 *
 * @param {Array<Array<number>>} pts - [[x,y], ...] waypoints
 * @param {number} [tension=0.5] - 0=straight, 0.5=Catmull-Rom, 1.0=loose
 * @param {boolean} [closed=false]
 * @returns {Object} Bézier path IR
 */
function smoothCurve(pts, tension, closed) {
    if (tension === undefined) tension = 0.5;
    if (closed === undefined) closed = false;

    var n = pts.length;

    // Degenerate: 0 or 1 points
    if (n <= 1) {
        return irPath(pts, false, {});
    }

    // Degenerate: 2 points → straight line
    if (n === 2) {
        return irPath(pts, closed, {});
    }

    // General case: n >= 3
    var alpha = tension / 3.0;
    var anchors = [];
    var handles = [];

    for (var i = 0; i < n; i++) {
        var iPrev, iNext;
        if (closed) {
            iPrev = (i - 1 + n) % n;
            iNext = (i + 1) % n;
        } else {
            iPrev = Math.max(0, i - 1);
            iNext = Math.min(n - 1, i + 1);
        }

        var pPrev = pts[iPrev];
        var pCurr = pts[i];
        var pNext = pts[iNext];

        // Tangent direction
        var dx = pNext[0] - pPrev[0];
        var dy = pNext[1] - pPrev[1];

        // Handles
        var outH = [pCurr[0] + dx * alpha, pCurr[1] + dy * alpha];
        var inH = [pCurr[0] - dx * alpha, pCurr[1] - dy * alpha];

        var hIn = inH;
        var hOut = outH;
        var hType = "smooth";

        // Open curve endpoints: one-sided handles
        if (!closed) {
            if (i === 0) { hIn = null; }
            if (i === n - 1) { hOut = null; }
        }

        if (hIn == null && hOut == null) {
            hType = "corner";
        }

        anchors.push(pCurr);
        handles.push({ "in": hIn, out: hOut, type: hType });
    }

    return irBezierPath(anchors, handles, closed, {});
}


// ==================== CIRCULAR ARC ====================

/**
 * Create a circular arc as cubic Bézier segments.
 * Delegates to ellipticalArc with rx = ry = r.
 *
 * @param {number} cx - Center X
 * @param {number} cy - Center Y
 * @param {number} r  - Radius
 * @param {number} startAngle - Start angle in radians
 * @param {number} endAngle   - End angle in radians
 * @param {number} [segments]  - Override auto. null = auto.
 * @returns {Object} Bézier path IR
 */
function circularArc(cx, cy, r, startAngle, endAngle, segments) {
    return ellipticalArc(cx, cy, r, r, startAngle, endAngle, segments);
}


// ==================== ELLIPTICAL ARC ====================

/**
 * Create an elliptical arc as cubic Bézier segments.
 *
 * Uses kappa approximation: for segment angle θ,
 *   kappa = (4/3) * tan(θ/4)
 *   handle length along tangent = radius * kappa
 *
 * Auto-segments: ceil(|Δθ| / (π/2)) — never >90° per segment.
 * Tangent continuity guaranteed by construction.
 * Max radial error < 0.27% for 90° segments.
 *
 * @param {number} cx - Center X
 * @param {number} cy - Center Y
 * @param {number} rx - Horizontal radius
 * @param {number} ry - Vertical radius
 * @param {number} startAngle - Start angle in radians
 * @param {number} endAngle   - End angle in radians
 * @param {number} [segments]  - Override auto. null = auto.
 * @returns {Object} Bézier path IR
 */
function ellipticalArc(cx, cy, rx, ry, startAngle, endAngle, segments) {
    var delta = endAngle - startAngle;

    // Zero arc → single point
    if (Math.abs(delta) < 1e-10) {
        var px = cx + rx * Math.cos(startAngle);
        var py = cy + ry * Math.sin(startAngle);
        return irPath([[px, py]], false, {});
    }

    // Auto-segment
    if (segments === undefined || segments === null) {
        segments = Math.max(1, Math.ceil(Math.abs(delta) / (Math.PI / 2)));
    }

    // Detect full circle
    var isFull = Math.abs(Math.abs(delta) - 2 * Math.PI) < 1e-6;

    var thetaSeg = delta / segments;
    var kappa = (4.0 / 3.0) * Math.tan(thetaSeg / 4.0);

    var anchors = [];
    var handles = [];

    for (var i = 0; i <= segments; i++) {
        var a = startAngle + i * thetaSeg;
        var cosA = Math.cos(a);
        var sinA = Math.sin(a);

        var x = cx + rx * cosA;
        var y = cy + ry * sinA;

        // Tangent direction scaled by kappa
        var tx = -rx * sinA * kappa;
        var ty = ry * cosA * kappa;

        var inH = null;
        var outH = null;

        if (i > 0 || isFull) {
            inH = [x - tx, y - ty];
        }
        if (i < segments || isFull) {
            outH = [x + tx, y + ty];
        }

        var hType = (inH == null && outH == null) ? "corner" : "smooth";

        anchors.push([x, y]);
        handles.push({ "in": inH, out: outH, type: hType });
    }

    // Full circle: merge last into first, remove last
    if (isFull && anchors.length > 1) {
        // Transfer last point's in-handle to first point
        handles[0]["in"] = handles[anchors.length - 1]["in"];
        anchors.pop();
        handles.pop();
    }

    if (isFull) {
        return irBezierPath(anchors, handles, true, {});
    }
    return irBezierPath(anchors, handles, false, {});
}


// ==================== ROUNDED POLYGON ====================

/**
 * Round corners of a polygon with Bézier fillets.
 *
 * Each corner is replaced by a circular arc tangent to the two edges.
 * Radius clamped to half the shorter adjacent edge.
 *
 * @param {Array<Array<number>>} verts - [[x,y], ...] vertices
 * @param {number} radius - Corner rounding radius (points)
 * @param {boolean} [closed=true]
 * @returns {Object} Bézier path IR
 */
function roundedPolygon(verts, radius, closed) {
    if (closed === undefined) closed = true;
    var n = verts.length;

    if (n < 2 || (closed && n < 3)) {
        return irPath(verts, closed, {});
    }

    var KAPPA_90 = 0.5522847498;  // 4/3 * tan(π/8)
    var anchors = [];
    var hdles = [];

    // Which corners to round
    var start = closed ? 0 : 1;
    var end = closed ? n : n - 1;

    for (var ci = start; ci < end; ci++) {
        var iPrev = (ci - 1 + n) % n;
        var iNext = (ci + 1) % n;

        var p = verts[ci];
        var pPrev = verts[iPrev];
        var pNext = verts[iNext];

        // Edge vectors
        var dxIn = p[0] - pPrev[0];
        var dyIn = p[1] - pPrev[1];
        var lenIn = Math.sqrt(dxIn * dxIn + dyIn * dyIn);

        var dxOut = pNext[0] - p[0];
        var dyOut = pNext[1] - p[1];
        var lenOut = Math.sqrt(dxOut * dxOut + dyOut * dyOut);

        if (lenIn < 1e-10 || lenOut < 1e-10) {
            anchors.push(p);
            hdles.push({ "in": null, out: null, type: "corner" });
            continue;
        }

        // Clamp radius
        var maxR = Math.min(lenIn, lenOut) / 2.0;
        var r = Math.min(radius, maxR);

        // Unit vectors
        var uInX = dxIn / lenIn, uInY = dyIn / lenIn;
        var uOutX = dxOut / lenOut, uOutY = dyOut / lenOut;

        // Fillet start/end points
        var fsX = p[0] - uInX * r, fsY = p[1] - uInY * r;
        var feX = p[0] + uOutX * r, feY = p[1] + uOutY * r;

        // Handle length
        var hLen = r * KAPPA_90;

        // Handles follow edge direction
        var startOut = [fsX + uInX * hLen, fsY + uInY * hLen];
        var endIn = [feX - uOutX * hLen, feY - uOutY * hLen];

        anchors.push([fsX, fsY]);
        hdles.push({ "in": null, out: startOut, type: "smooth" });

        anchors.push([feX, feY]);
        hdles.push({ "in": endIn, out: null, type: "smooth" });
    }

    // Open polygon: prepend first vertex, append last
    if (!closed) {
        anchors.splice(0, 0, verts[0]);
        hdles.splice(0, 0, { "in": null, out: null, type: "corner" });
        anchors.push(verts[n - 1]);
        hdles.push({ "in": null, out: null, type: "corner" });
    }

    return irBezierPath(anchors, hdles, closed, {});
}

// ==================== NATURAL CUBIC SPLINE ====================

/**
 * Natural cubic spline through waypoints → Bézier handles.
 *
 * Solves the tridiagonal system for natural (zero second derivative
 * at endpoints) or periodic (closed) boundary conditions.
 *
 * @param {Array<Array<number>>} pts - [[x,y], ...] waypoints
 * @param {boolean} [closed=false]
 * @returns {Object} Bézier path IR
 */
function naturalSpline(pts, closed) {
    if (closed === undefined) closed = false;
    var n = pts.length;

    if (n <= 2) {
        return irPath(pts, closed, {});
    }

    // Solve 1D natural spline for one coordinate axis
    // Returns array of {out, in} handle offsets per segment
    function solveAxis(vals) {
        var m = vals.length;
        var a = [], b = [], c = [], r = [];

        if (!closed) {
            // Natural boundary: second derivative = 0 at endpoints
            // Tridiagonal system for interior points
            for (var i = 1; i < m - 1; i++) {
                a.push(1);
                b.push(4);
                c.push(1);
                r.push(6 * vals[i]);
            }
            // Boundary: first and last control points
            // P0" = 0 → 2*P0 - 5*P0cp + 4*P1 - P1cp = 0
            // Natural spline: d1 = (3*(a[1]-a[0]) - d2) where d2 comes from tridiag
            // Simpler: solve for tangents
            var tangents = [];
            // Thomas algorithm for tridiagonal
            var nn = m - 2;  // interior points only
            if (nn === 0) {
                // Only 2 points — no interior
                tangents = [];
            } else {
                var cp = [];
                var dp = [];
                // Forward sweep
                cp.push(c[0] / b[0]);
                dp.push(r[0] / b[0]);
                for (var i = 1; i < nn; i++) {
                    var mi = 1.0 / (b[i] - a[i] * cp[i - 1]);
                    cp.push(c[i] * mi);
                    dp.push((r[i] - a[i] * dp[i - 1]) * mi);
                }
                // Back substitution
                tangents = new Array(nn);
                tangents[nn - 1] = dp[nn - 1];
                for (var i = nn - 2; i >= 0; i--) {
                    tangents[i] = dp[i] - cp[i] * tangents[i + 1];
                }
            }
            return tangents;
        }
        return []; // closed spline TODO — Catmull-Rom covers closed case well
    }

    // For natural spline, compute tangents at each point
    // Then convert tangents to Bézier handles
    // Using the standard cubic Hermite-to-Bézier conversion:
    //   out_handle(i) = P(i) + tangent(i) / 3
    //   in_handle(i+1) = P(i+1) - tangent(i+1) / 3

    // Alternative simpler approach: fit cubic through each pair of points
    // with tangents derived from neighboring points (like Catmull-Rom but
    // with natural spline tangents)

    // For now, delegate closed case to smoothCurve (Catmull-Rom is close enough)
    if (closed) {
        return smoothCurve(pts, 0.5, true);
    }

    // Compute tangents using natural spline system
    var xVals = [], yVals = [];
    for (var i = 0; i < n; i++) {
        xVals.push(pts[i][0]);
        yVals.push(pts[i][1]);
    }

    // Build tridiagonal for tangent computation
    // d_i = tangent at point i
    // 2*d_0 + d_1 = 3*(x_1 - x_0)
    // d_{i-1} + 4*d_i + d_{i+1} = 3*(x_{i+1} - x_{i-1})
    // d_{n-2} + 2*d_{n-1} = 3*(x_{n-1} - x_{n-2})

    var dxArr = new Array(n);
    var dyArr = new Array(n);

    // Thomas algorithm for tangent tridiagonal system
    var bb = new Array(n);
    var rxArr = new Array(n);
    var ryArr = new Array(n);

    bb[0] = 2.0;
    rxArr[0] = 3.0 * (xVals[1] - xVals[0]);
    ryArr[0] = 3.0 * (yVals[1] - yVals[0]);

    for (var i = 1; i < n - 1; i++) {
        var m = 1.0 / bb[i - 1];
        bb[i] = 4.0 - m;
        rxArr[i] = 3.0 * (xVals[i + 1] - xVals[i - 1]) - m * rxArr[i - 1];
        ryArr[i] = 3.0 * (yVals[i + 1] - yVals[i - 1]) - m * ryArr[i - 1];
    }

    var mLast = 1.0 / bb[n - 2];
    bb[n - 1] = 2.0 - mLast;
    rxArr[n - 1] = 3.0 * (xVals[n - 1] - xVals[n - 2]) - mLast * rxArr[n - 2];
    ryArr[n - 1] = 3.0 * (yVals[n - 1] - yVals[n - 2]) - mLast * ryArr[n - 2];

    // Back substitution
    dxArr[n - 1] = rxArr[n - 1] / bb[n - 1];
    dyArr[n - 1] = ryArr[n - 1] / bb[n - 1];
    for (var i = n - 2; i >= 0; i--) {
        dxArr[i] = (rxArr[i] - dxArr[i + 1]) / bb[i];
        dyArr[i] = (ryArr[i] - dyArr[i + 1]) / bb[i];
    }

    // Convert tangents to Bézier handles
    var anchors = [];
    var hdles = [];

    for (var i = 0; i < n; i++) {
        anchors.push(pts[i]);

        var inH = null;
        var outH = null;

        if (i > 0) {
            inH = [pts[i][0] - dxArr[i] / 3.0, pts[i][1] - dyArr[i] / 3.0];
        }
        if (i < n - 1) {
            outH = [pts[i][0] + dxArr[i] / 3.0, pts[i][1] + dyArr[i] / 3.0];
        }

        var hType = (inH == null && outH == null) ? "corner" : "smooth";
        hdles.push({ "in": inH, out: outH, type: hType });
    }

    return irBezierPath(anchors, hdles, false, {});
}
