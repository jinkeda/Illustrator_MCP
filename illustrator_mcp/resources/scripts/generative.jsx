/**
 * generative.jsx — Procedural generation utilities
 * Part of Illustrator MCP standard library
 *
 * ARCHITECTURAL CONTRACT — IR-FIRST
 *   Every function produces data (Intermediate Representation):
 *   arrays of points, segments, polylines, or scalar values.
 *   NO function creates or modifies Illustrator objects.
 *   SOC ops turn IR into PathItems; checks validate properties.
 *
 *   Exception: CANVAS section contains read-only DOM helpers
 *   (artboard bounds, safe text creation) that do not generate
 *   or modify artwork geometry.
 *
 * Sections:
 *   PRNG          — seeded xorshift32
 *   CANVAS        — artboard bounds, safe text creation (DOM read-only)
 *   NOISE         — value noise, fBm, ridged multi-fractal
 *   CONTOUR       — marching squares iso-contour extraction
 *   CHAINING      — segment → polyline merging
 *   SMOOTHING     — Chaikin corner-cutting subdivision (with point budget)
 *   DECIMATION    — uniform point reduction
 *   CLEANUP       — dedup, zero-length removal, snap-close
 *   IR_WRAPPERS   — convenience functions returning Geometry IR
 *   SPATIAL       — spatial hashing, proximity queries, clustering
 *   FIELDS        — vector field precomputation, integration, curl noise grids
 *
 * @requires geo_ir (for IR wrappers only — geometry helpers are standalone)
 * @version 1.5.0
 */

// ==================== PRNG ====================

/**
 * Create a seeded pseudo-random number generator (xorshift32).
 * @param {number} seed - Integer seed
 * @returns {function} Function that returns random floats in [0, 1)
 */
function seededRandom(seed) {
    var s = seed | 0 || 1;
    return function () {
        s ^= s << 13;
        s ^= s >> 17;
        s ^= s << 5;
        return ((s < 0 ? ~s + 1 : s) % 1000000) / 1000000;
    };
}

// ==================== CANVAS ====================
// Read-only DOM helpers — artboard coordinate reference and safe text creation.
// These do NOT generate or modify artwork geometry.

/**
 * Get artboard bounds in Illustrator coordinates.
 *
 * @param {Document} [doc] - Document (default: app.activeDocument)
 * @param {number} [index=0] - Artboard index (clamped to valid range)
 * @returns {{x:number, y:number, w:number, h:number, left:number, top:number, right:number, bottom:number, clamped:boolean}}
 */
function getArtboardBounds(doc, index) {
    doc = doc || app.activeDocument;
    index = index || 0;
    var clamped = false;
    if (index < 0) { index = 0; clamped = true; }
    if (index >= doc.artboards.length) {
        index = doc.artboards.length - 1;
        clamped = true;
    }
    var r = doc.artboards[index].artboardRect; // [left, top, right, bottom]
    var left = r[0], top = r[1], right = r[2], bottom = r[3];
    return {
        x: left,
        y: top,
        w: right - left,
        h: top - bottom,
        left: left,
        top: top,
        right: right,
        bottom: bottom,
        clamped: clamped
    };
}

/**
 * Add a text label safely.
 * Uses pointText + characters[0].characterAttributes to avoid
 * PARM error (1346458189) that occurs with textFrames.add() +
 * textRange.characterAttributes in documents with many pathItems.
 *
 * Canonical style order: create → contents → size → color → font.
 *
 * @param {Layer|GroupItem} container - Target layer or group
 * @param {number} x - X position (artboard coords)
 * @param {number} y - Y position (artboard coords)
 * @param {string} text - Label content
 * @param {Object} [opts] - Options
 * @param {number} [opts.size=12] - Font size in points
 * @param {RGBColor|CMYKColor} [opts.color] - Fill color (default: black)
 * @param {string} [opts.font] - Font name (e.g. "ArialMT")
 * @param {string} [opts.name] - Item name for scripting access
 * @returns {TextFrame} The created text frame
 */
function addLabel(container, x, y, text, opts) {
    opts = opts || {};
    var tf = container.textFrames.pointText([x, y]);
    tf.contents = text;
    var ca = tf.characters[0].characterAttributes;
    ca.size = opts.size || 12;
    if (opts.color) {
        ca.fillColor = opts.color;
    }
    if (opts.font) {
        ca.textFont = app.textFonts.getByName(opts.font);
    }
    if (opts.name) {
        tf.name = opts.name;
    }
    return tf;
}

// ==================== Noise ====================

/**
 * Build a permutation table for noise from a PRNG.
 * @param {function} rng - PRNG function from seededRandom()
 * @param {number} [size=256] - Table size
 * @returns {Array<number>} Permutation table (doubled for wrapping)
 */
function buildPermTable(rng, size) {
    size = size || 256;
    var p = [];
    for (var i = 0; i < size; i++) p[i] = i;
    // Fisher-Yates shuffle
    for (var i = size - 1; i > 0; i--) {
        var j = Math.floor(rng() * (i + 1));
        var tmp = p[i]; p[i] = p[j]; p[j] = tmp;
    }
    // Double for wrap-around
    var perm = [];
    for (var i = 0; i < size * 2; i++) perm[i] = p[i % size];
    return perm;
}

/**
 * Smoothstep interpolation.
 */
function smoothstep(t) {
    return t * t * (3 - 2 * t);
}

/**
 * Linear interpolation.
 */
function lerp(a, b, t) {
    return a + (b - a) * t;
}

/**
 * 2D value noise.
 * @param {number} x
 * @param {number} y
 * @param {Array<number>} perm - Permutation table from buildPermTable()
 * @returns {number} Noise value in [0, 1]
 */
function valueNoise2D(x, y, perm) {
    var size = perm.length / 2;
    var xi = Math.floor(x) & (size - 1);
    var yi = Math.floor(y) & (size - 1);
    var xf = x - Math.floor(x);
    var yf = y - Math.floor(y);

    var u = smoothstep(xf);
    var v = smoothstep(yf);

    var aa = perm[perm[xi] + yi];
    var ab = perm[perm[xi] + yi + 1];
    var ba = perm[perm[xi + 1] + yi];
    var bb = perm[perm[xi + 1] + yi + 1];

    return lerp(
        lerp(aa, ba, u),
        lerp(ab, bb, u),
        v
    ) / (size - 1);
}

/**
 * Fractal Brownian Motion.
 * @param {number} x
 * @param {number} y
 * @param {Object} opts - {octaves, lacunarity, gain, perm}
 * @returns {number} Value in approximately [0, 1]
 */
function fbm(x, y, opts) {
    var octaves = opts.octaves || 4;
    var lac = opts.lacunarity || 2.0;
    var gain = opts.gain || 0.5;
    var perm = opts.perm;

    var amp = 1.0, freq = 1.0, sum = 0, maxAmp = 0;
    for (var i = 0; i < octaves; i++) {
        sum += amp * valueNoise2D(x * freq, y * freq, perm);
        maxAmp += amp;
        amp *= gain;
        freq *= lac;
    }
    return sum / maxAmp;
}

/**
 * Ridged multi-fractal noise.
 * @param {number} x
 * @param {number} y
 * @param {Object} opts - {octaves, lacunarity, gain, perm}
 * @returns {number} Value in approximately [0, 1]
 */
function ridgedNoise(x, y, opts) {
    var v = fbm(x, y, opts);
    return 1.0 - Math.abs(2.0 * v - 1.0);
}

// ==================== Marching Squares ====================

/**
 * Extract iso-contour segments from a scalar field using marching squares.
 *
 * @param {function} field - field(ix, iy) returns scalar value
 * @param {number} cols - Number of columns in the grid
 * @param {number} rows - Number of rows in the grid
 * @param {number} threshold - Iso-value to extract
 * @param {Object} [cellSize] - {dx, dy} cell dimensions (default 1x1)
 * @returns {Array<Array<Array<number>>>} Array of segments, each [[x1,y1],[x2,y2]]
 */
function marchingSquares(field, cols, rows, threshold, cellSize) {
    // Grid-size safety cap: prevent stalls on dense grids
    var MAX_GRID_CELLS = 250000; // 500×500
    var totalCells = (cols - 1) * (rows - 1);
    if (totalCells > MAX_GRID_CELLS) {
        throw new Error(
            'marchingSquares: grid too large (' + cols + '×' + rows +
            ' = ' + totalCells + ' cells). Max ' + MAX_GRID_CELLS +
            '. Reduce resolution or tile the field.'
        );
    }

    var dx = (cellSize && cellSize.dx) || 1;
    var dy = (cellSize && cellSize.dy) || 1;
    var segments = [];

    for (var iy = 0; iy < rows - 1; iy++) {
        for (var ix = 0; ix < cols - 1; ix++) {
            var v0 = field(ix, iy);
            var v1 = field(ix + 1, iy);
            var v2 = field(ix + 1, iy + 1);
            var v3 = field(ix, iy + 1);

            var idx = 0;
            if (v0 >= threshold) idx |= 1;
            if (v1 >= threshold) idx |= 2;
            if (v2 >= threshold) idx |= 4;
            if (v3 >= threshold) idx |= 8;

            if (idx === 0 || idx === 15) continue;

            // Interpolation helpers
            var t01 = (threshold - v0) / ((v1 - v0) || 1e-10);
            var t12 = (threshold - v1) / ((v2 - v1) || 1e-10);
            var t23 = (threshold - v3) / ((v2 - v3) || 1e-10);
            var t30 = (threshold - v0) / ((v3 - v0) || 1e-10);

            // Edge midpoints with linear interpolation
            var top = [(ix + t01) * dx, iy * dy];
            var right = [(ix + 1) * dx, (iy + t12) * dy];
            var bottom = [(ix + t23) * dx, (iy + 1) * dy];
            var left = [ix * dx, (iy + t30) * dy];

            // Marching squares lookup (16 cases)
            switch (idx) {
                case 1: segments.push([left, top]); break;
                case 2: segments.push([top, right]); break;
                case 3: segments.push([left, right]); break;
                case 4: segments.push([right, bottom]); break;
                case 5:  // Saddle
                    var center = (v0 + v1 + v2 + v3) / 4;
                    if (center >= threshold) {
                        segments.push([left, top]);
                        segments.push([right, bottom]);
                    } else {
                        segments.push([left, bottom]);
                        segments.push([top, right]);
                    }
                    break;
                case 6: segments.push([top, bottom]); break;
                case 7: segments.push([left, bottom]); break;
                case 8: segments.push([bottom, left]); break;
                case 9: segments.push([bottom, top]); break;
                case 10: // Saddle
                    var center = (v0 + v1 + v2 + v3) / 4;
                    if (center >= threshold) {
                        segments.push([top, right]);
                        segments.push([bottom, left]);
                    } else {
                        segments.push([top, left]);
                        segments.push([bottom, right]);
                    }
                    break;
                case 11: segments.push([right, bottom]); break;
                case 12: segments.push([right, left]); break;
                case 13: segments.push([top, right]); break;
                case 14: segments.push([top, left]); break;
            }
        }
    }
    return segments;
}

// ==================== CHAINING ====================

/**
 * Chain disconnected segments into continuous polylines.
 * Segments that share endpoints (within tolerance) are merged.
 *
 * @param {Array} segments - Array of [[x1,y1],[x2,y2]] segments
 * @param {number} [tolerance=0.001] - Distance tolerance for point matching
 * @returns {Array<Array<Array<number>>>} Array of polylines (each is array of [x,y])
 */
function chainSegments(segments, tolerance) {
    tolerance = tolerance || 0.001;
    var tol2 = tolerance * tolerance;

    function dist2(a, b) {
        var dx = a[0] - b[0], dy = a[1] - b[1];
        return dx * dx + dy * dy;
    }

    // Convert segments to chains
    var chains = [];
    for (var i = 0; i < segments.length; i++) {
        chains.push([segments[i][0], segments[i][1]]);
    }

    // Merge chains iteratively
    var changed = true;
    while (changed) {
        changed = false;
        for (var i = 0; i < chains.length; i++) {
            if (!chains[i]) continue;
            var ci = chains[i];
            var ciHead = ci[0];
            var ciTail = ci[ci.length - 1];

            for (var j = i + 1; j < chains.length; j++) {
                if (!chains[j]) continue;
                var cj = chains[j];
                var cjHead = cj[0];
                var cjTail = cj[cj.length - 1];

                if (dist2(ciTail, cjHead) < tol2) {
                    // Append cj to ci (skip duplicate point)
                    for (var k = 1; k < cj.length; k++) ci.push(cj[k]);
                    chains[j] = null;
                    changed = true;
                } else if (dist2(ciTail, cjTail) < tol2) {
                    // Reverse cj and append
                    for (var k = cj.length - 2; k >= 0; k--) ci.push(cj[k]);
                    chains[j] = null;
                    changed = true;
                } else if (dist2(ciHead, cjTail) < tol2) {
                    // Prepend cj to ci
                    for (var k = cj.length - 2; k >= 0; k--) ci.unshift(cj[k]);
                    chains[j] = null;
                    changed = true;
                } else if (dist2(ciHead, cjHead) < tol2) {
                    // Reverse cj and prepend
                    for (var k = 1; k < cj.length; k++) ci.unshift(cj[k]);
                    chains[j] = null;
                    changed = true;
                }

                // Update head/tail after merge
                if (changed) {
                    ciHead = ci[0];
                    ciTail = ci[ci.length - 1];
                }
            }
        }
    }

    // Compact
    var result = [];
    for (var i = 0; i < chains.length; i++) {
        if (chains[i] && chains[i].length >= 2) result.push(chains[i]);
    }
    return result;
}

// ==================== SMOOTHING ====================

/**
 * Chaikin's corner-cutting subdivision.
 * Each iteration doubles point count and smooths corners.
 *
 * @param {Array<Array<number>>} points - Array of [x, y]
 * @param {number} [iterations=2] - Number of subdivision passes
 * @param {boolean} [closed=false] - Whether the curve is closed
 * @returns {Array<Array<number>>} Smoothed points
 */
function chaikinSmooth(points, iterations, closed, maxPoints) {
    iterations = iterations || 2;
    maxPoints = maxPoints || 0; // 0 = no limit
    var pts = points;

    for (var iter = 0; iter < iterations; iter++) {
        var newPts = [];
        var len = closed ? pts.length : pts.length - 1;

        for (var i = 0; i < len; i++) {
            var p0 = pts[i];
            var p1 = pts[(i + 1) % pts.length];

            newPts.push([
                0.75 * p0[0] + 0.25 * p1[0],
                0.75 * p0[1] + 0.25 * p1[1]
            ]);
            newPts.push([
                0.25 * p0[0] + 0.75 * p1[0],
                0.25 * p0[1] + 0.75 * p1[1]
            ]);
        }

        // For open curves, preserve first and last points
        if (!closed && pts.length >= 2) {
            newPts[0] = pts[0];
            newPts[newPts.length - 1] = pts[pts.length - 1];
        }

        pts = newPts;

        // Per-iteration point budget enforcement
        // Uses "keep endpoints + evenly spaced interior" strategy.
        // For closed paths, treat as ring (no duplicated endpoint).
        if (maxPoints > 0 && pts.length > maxPoints) {
            if (closed) {
                // Evenly sample around the ring
                var step = pts.length / maxPoints;
                var sampled = [];
                for (var si = 0; si < maxPoints; si++) {
                    sampled.push(pts[Math.round(si * step) % pts.length]);
                }
                pts = sampled;
            } else {
                // Keep first + last, evenly sample interior
                var interiorMax = maxPoints - 2;
                if (interiorMax <= 0) {
                    pts = [pts[0], pts[pts.length - 1]];
                } else {
                    var stp = (pts.length - 2) / (interiorMax + 1);
                    var result = [pts[0]];
                    for (var si = 1; si <= interiorMax; si++) {
                        result.push(pts[Math.round(si * stp)]);
                    }
                    result.push(pts[pts.length - 1]);
                    pts = result;
                }
            }
        }
    }
    return pts;
}

// ==================== DECIMATION ====================

/**
 * Uniformly decimate a point array to maxN points.
 * Preserves first and last points.
 *
 * @param {Array<Array<number>>} points
 * @param {number} maxN - Maximum number of output points
 * @returns {Array<Array<number>>} Decimated points
 */
function decimatePoints(points, maxN) {
    if (points.length <= maxN) return points;
    var step = (points.length - 1) / (maxN - 1);
    var result = [];
    for (var i = 0; i < maxN; i++) {
        result.push(points[Math.round(i * step)]);
    }
    return result;
}

// ==================== CLEANUP ====================

/**
 * Clean a polyline: remove duplicate/coincident points, remove zero-length
 * segments, optionally snap endpoints to close the path.
 *
 * @param {Array<Array<number>>} points - Array of [x, y]
 * @param {Object} [opts] - Options
 * @param {number} [opts.epsilon=0.001] - Distance below which points are coincident
 * @param {number} [opts.minSegLen=0] - Minimum segment length (0 = keep all)
 * @param {boolean} [opts.snapClose=false] - If true and head≈tail within epsilon, close exactly
 * @returns {Array<Array<number>>} Cleaned points
 */
function cleanPolyline(points, opts) {
    if (!points || points.length < 2) return points || [];
    opts = opts || {};
    var eps = opts.epsilon !== undefined ? opts.epsilon : 0.001;
    var eps2 = eps * eps;
    var minSeg = opts.minSegLen || 0;
    var minSeg2 = minSeg * minSeg;
    var snapClose = opts.snapClose || false;

    function d2(a, b) {
        var dx = a[0] - b[0], dy = a[1] - b[1];
        return dx * dx + dy * dy;
    }

    // Pass 1: deduplicate coincident consecutive points
    var deduped = [points[0]];
    for (var i = 1; i < points.length; i++) {
        if (d2(points[i], deduped[deduped.length - 1]) > eps2) {
            deduped.push(points[i]);
        }
    }

    // Pass 2: remove segments shorter than minSegLen (if set)
    var result;
    if (minSeg > 0 && deduped.length > 2) {
        result = [deduped[0]];
        for (var i = 1; i < deduped.length; i++) {
            if (d2(deduped[i], result[result.length - 1]) >= minSeg2) {
                result.push(deduped[i]);
            }
        }
        // Always keep last point
        var last = deduped[deduped.length - 1];
        if (d2(last, result[result.length - 1]) > eps2) {
            result.push(last);
        }
    } else {
        result = deduped;
    }

    // Pass 3: snap-close if head ≈ tail
    if (snapClose && result.length >= 3) {
        if (d2(result[0], result[result.length - 1]) < eps2) {
            result[result.length - 1] = [result[0][0], result[0][1]];
        }
    }

    return result;
}

// ==================== IR_WRAPPERS ====================

/**
 * Wrap chainSegments output as a Geometry IR multi-path.
 * Meta is merged: caller meta + standard wrapper keys.
 *
 * @param {Array<Array<Array<number>>>} segments - Segments from marchingSquares etc.
 * @param {number} [tolerance=0.5] - Chaining tolerance
 * @param {Object} [meta={}] - Optional caller metadata (seed, threshold, etc.)
 * @returns {Object} Geometry IR multi-path
 */
function chainSegmentsIR(segments, tolerance, meta) {
    var polylines = chainSegments(segments, tolerance);
    var paths = [];
    for (var i = 0; i < polylines.length; i++) {
        paths.push(irPath(polylines[i], false));
    }
    // Merge caller meta with standard wrapper keys
    var merged = {};
    if (meta) {
        for (var k in meta) {
            if (meta.hasOwnProperty(k)) merged[k] = meta[k];
        }
    }
    merged.algo = "chainSegments";
    merged.ts = +new Date();
    return irMulti(paths, merged);
}

// ==================== SPATIAL ====================

/**
 * Build a spatial hash grid for O(1)-amortized point lookup.
 *
 * @param {Array<Array<number>>} points - Array of [x, y] (or [x, y, ...])
 * @param {number} cellSize - Grid cell size; should be >= expected query radius
 * @returns {{cellSize: number, buckets: Object}} buckets["ix:iy"] = [indices]
 */
function spatialHashBuild(points, cellSize) {
    if (!cellSize || cellSize <= 0) cellSize = 1;
    var buckets = {};
    for (var i = 0; i < points.length; i++) {
        var ix = Math.floor(points[i][0] / cellSize);
        var iy = Math.floor(points[i][1] / cellSize);
        var key = ix + ":" + iy;
        if (!buckets[key]) buckets[key] = [];
        buckets[key].push(i);
    }
    return { cellSize: cellSize, buckets: buckets };
}

/**
 * Query a spatial hash for all point indices within radius of (x, y).
 *
 * @param {{cellSize, buckets}} hash - From spatialHashBuild
 * @param {number} x
 * @param {number} y
 * @param {number} radius
 * @returns {Array<number>} Indices of points within radius
 */
function spatialHashQuery(hash, x, y, radius) {
    var cs = hash.cellSize;
    var r2 = radius * radius;
    var rCells = Math.ceil(radius / cs);
    var cx = Math.floor(x / cs);
    var cy = Math.floor(y / cs);
    var result = [];
    for (var dx = -rCells; dx <= rCells; dx++) {
        for (var dy = -rCells; dy <= rCells; dy++) {
            var key = (cx + dx) + ":" + (cy + dy);
            var bucket = hash.buckets[key];
            if (!bucket) continue;
            for (var bi = 0; bi < bucket.length; bi++) {
                result.push(bucket[bi]);
            }
        }
    }
    return result;
}

/**
 * Find all point pairs within radius. Deduped: returns [i,j] where i < j.
 * Complexity: O(N·k) where k = average neighbors per point.
 *
 * @param {Array<Array<number>>} points
 * @param {{cellSize, buckets}} hash - From spatialHashBuild (cellSize should be >= radius)
 * @param {number} radius
 * @returns {Array<Array<number>>} Array of [i, j] pairs, i < j
 */
function pairsWithinRadius(points, hash, radius) {
    var r2 = radius * radius;
    var cs = hash.cellSize;
    var rCells = Math.ceil(radius / cs);
    var pairs = [];
    // Visit each point, check its neighborhood, emit pair if j > i
    for (var i = 0; i < points.length; i++) {
        var px = points[i][0], py = points[i][1];
        var cx = Math.floor(px / cs);
        var cy = Math.floor(py / cs);
        for (var dx = -rCells; dx <= rCells; dx++) {
            for (var dy = -rCells; dy <= rCells; dy++) {
                var key = (cx + dx) + ":" + (cy + dy);
                var bucket = hash.buckets[key];
                if (!bucket) continue;
                for (var bi = 0; bi < bucket.length; bi++) {
                    var j = bucket[bi];
                    if (j <= i) continue; // dedupe: only emit i < j
                    var ddx = points[j][0] - px;
                    var ddy = points[j][1] - py;
                    if (ddx * ddx + ddy * ddy <= r2) {
                        pairs.push([i, j]);
                    }
                }
            }
        }
    }
    return pairs;
}

/**
 * Cluster nearby points by radius. Default reducer: centroid (average x, y).
 * Deterministic tie-breaker: first point encountered (input order) determines
 * initial cluster, and additional data fields are taken from the first point.
 *
 * @param {Array<Object>} points - Array of {x, y, ...extra fields}
 * @param {{cellSize, buckets}} hash - From spatialHashBuild (on [[x,y],...])
 * @param {number} radius - Merge radius
 * @param {function} [reducer] - (cluster) => merged point; default = centroid
 * @returns {Array<Object>} Merged points with same structure as input
 */
function clusterByRadius(points, hash, radius, reducer) {
    var r2 = radius * radius;
    var cs = hash.cellSize;
    var rCells = Math.ceil(radius / cs);
    var visited = {};
    var clusters = [];

    for (var i = 0; i < points.length; i++) {
        if (visited[i]) continue;
        visited[i] = true;

        // BFS: find all points reachable within radius
        var cluster = [i];
        var queue = [i];
        while (queue.length > 0) {
            var cur = queue.shift();
            var px = points[cur].x !== undefined ? points[cur].x : points[cur][0];
            var py = points[cur].y !== undefined ? points[cur].y : points[cur][1];
            var cx = Math.floor(px / cs);
            var cy = Math.floor(py / cs);
            for (var dx = -rCells; dx <= rCells; dx++) {
                for (var dy = -rCells; dy <= rCells; dy++) {
                    var key = (cx + dx) + ":" + (cy + dy);
                    var bucket = hash.buckets[key];
                    if (!bucket) continue;
                    for (var bi = 0; bi < bucket.length; bi++) {
                        var j = bucket[bi];
                        if (visited[j]) continue;
                        var jx = points[j].x !== undefined ? points[j].x : points[j][0];
                        var jy = points[j].y !== undefined ? points[j].y : points[j][1];
                        var ddx = jx - px;
                        var ddy = jy - py;
                        if (ddx * ddx + ddy * ddy <= r2) {
                            visited[j] = true;
                            cluster.push(j);
                            queue.push(j);
                        }
                    }
                }
            }
        }
        clusters.push(cluster);
    }

    // Reduce each cluster
    var results = [];
    for (var ci = 0; ci < clusters.length; ci++) {
        var cl = clusters[ci];
        if (reducer) {
            var clPoints = [];
            for (var k = 0; k < cl.length; k++) clPoints.push(points[cl[k]]);
            results.push(reducer(clPoints));
        } else {
            // Default reducer: centroid of x,y; extra fields from first point
            var sumX = 0, sumY = 0;
            for (var k = 0; k < cl.length; k++) {
                var p = points[cl[k]];
                sumX += (p.x !== undefined ? p.x : p[0]);
                sumY += (p.y !== undefined ? p.y : p[1]);
            }
            var first = points[cl[0]];
            var merged = {};
            // Copy extra fields from first point
            for (var fk in first) {
                if (first.hasOwnProperty(fk)) merged[fk] = first[fk];
            }
            merged.x = sumX / cl.length;
            merged.y = sumY / cl.length;
            if (first[0] !== undefined) {
                // Array-style points: return array too
                merged[0] = merged.x;
                merged[1] = merged.y;
            }
            results.push(merged);
        }
    }
    return results;
}

// ==================== Fields ====================

/**
 * Precompute a 2D vector field on a regular grid.
 * Returns an object with a `lookup(x, y)` method that does
 * bilinear interpolation between grid nodes.
 *
 * @param {function} fn - Field function: fn(x, y) → [vx, vy]
 * @param {number} cols - Grid columns
 * @param {number} rows - Grid rows
 * @param {Object} bounds - {x, y, w, h} domain bounds
 * @returns {Object} { cols, rows, vx[][], vy[][], lookup(x,y)→[vx,vy] }
 */
function buildFieldGrid(fn, cols, rows, bounds) {
    var dx = bounds.w / (cols - 1);
    var dy = bounds.h / (rows - 1);
    var vx = [];
    var vy = [];

    for (var r = 0; r < rows; r++) {
        vx[r] = [];
        vy[r] = [];
        for (var c = 0; c < cols; c++) {
            var px = bounds.x + c * dx;
            var py = bounds.y + r * dy;
            var v = fn(px, py);
            vx[r][c] = v[0];
            vy[r][c] = v[1];
        }
    }

    return {
        cols: cols,
        rows: rows,
        vx: vx,
        vy: vy,
        /** Bilinear lookup. Returns [0,0] for out-of-bounds. */
        lookup: function (x, y) {
            // Map world coords → grid coords
            var gx = (x - bounds.x) / dx;
            var gy = (y - bounds.y) / dy;

            // Clamp to valid grid range
            if (gx < 0) gx = 0;
            if (gy < 0) gy = 0;
            if (gx > cols - 1) gx = cols - 1;
            if (gy > rows - 1) gy = rows - 1;

            var c0 = Math.floor(gx);
            var r0 = Math.floor(gy);
            var c1 = (c0 < cols - 1) ? c0 + 1 : c0;
            var r1 = (r0 < rows - 1) ? r0 + 1 : r0;
            var fx = gx - c0;
            var fy = gy - r0;

            // Bilinear interpolation
            var rx = lerp(
                lerp(vx[r0][c0], vx[r0][c1], fx),
                lerp(vx[r1][c0], vx[r1][c1], fx),
                fy
            );
            var ry = lerp(
                lerp(vy[r0][c0], vy[r0][c1], fx),
                lerp(vy[r1][c0], vy[r1][c1], fx),
                fy
            );
            return [rx, ry];
        }
    };
}

/**
 * Euler-integrate a path through a vector field.
 *
 * @param {Object|function} field - Either a fieldGrid (with .lookup) or fn(x,y)→[vx,vy]
 * @param {Array<number>} start - [x, y] starting point
 * @param {number} stepLen - Step length in domain units
 * @param {number} maxSteps - Maximum integration steps
 * @param {Object} bounds - {x, y, w, h} — stop if path leaves bounds
 * @returns {Array<Array<number>>} Array of [x,y] points
 */
function integrateField(field, start, stepLen, maxSteps, bounds) {
    var lookupFn = (typeof field.lookup === "function") ? field.lookup : field;
    var pts = [start.slice()];
    var cx = start[0], cy = start[1];

    // Compute effective bounds
    var bx0 = bounds.x || 0;
    var by0 = bounds.y || 0;
    var bx1 = bx0 + (bounds.w || Infinity);
    var by1 = by0 + (bounds.h || Infinity);

    for (var step = 0; step < maxSteps; step++) {
        var v = lookupFn(cx, cy);
        var mag = Math.sqrt(v[0] * v[0] + v[1] * v[1]);
        if (mag < 0.0001) break; // stagnation

        // Normalize and step
        var nx = cx + (v[0] / mag) * stepLen;
        var ny = cy + (v[1] / mag) * stepLen;

        // Bounds check
        if (nx < bx0 || nx > bx1 || ny < by0 || ny > by1) break;

        pts.push([nx, ny]);
        cx = nx;
        cy = ny;
    }
    return pts;
}

/**
 * Precompute a curl-noise vector field on a grid.
 * Curl of scalar fBm = divergence-free flow (natural vortices).
 *
 * @param {Object} noiseOpts - { perm, octaves, lacunarity, gain }
 * @param {Object} bounds - { x, y, w, h } domain bounds
 * @param {number} fieldScale - Noise frequency multiplier
 * @param {Object} [gridOpts] - { cols, rows, eps }
 * @returns {Object} fieldGrid with .lookup(x, y) → [vx, vy]
 */
function buildCurlField(noiseOpts, bounds, fieldScale, gridOpts) {
    gridOpts = gridOpts || {};
    var cols = gridOpts.cols || 80;
    var rows = gridOpts.rows || 80;
    var eps = gridOpts.eps || 0.01;

    return buildFieldGrid(function (x, y) {
        // Map world coords to noise space
        var nx = x / bounds.w * fieldScale;
        var ny = y / bounds.h * fieldScale;

        var f00 = fbm(nx, ny, noiseOpts);
        var fdx = fbm(nx + eps, ny, noiseOpts);
        var fdy = fbm(nx, ny + eps, noiseOpts);

        var dfdx = (fdx - f00) / eps;
        var dfdy = (fdy - f00) / eps;

        // Curl = rot90(gradient) = (-df/dy, df/dx)
        return [-dfdy, dfdx];
    }, cols, rows, bounds);
}
