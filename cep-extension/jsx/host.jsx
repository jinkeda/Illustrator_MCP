/**
 * ExtendScript Host for Illustrator MCP
 *
 * This script runs in the Illustrator ExtendScript context and provides
 * the bridge between the CEP panel JavaScript and Illustrator's DOM.
 */

// JSON polyfill for ExtendScript (which lacks native JSON support)
if (typeof JSON === 'undefined') {
    JSON = {
        stringify: function (obj) {
            var t = typeof obj;
            if (t !== 'object' || obj === null) {
                if (t === 'string') return '"' + obj.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t') + '"';
                if (t === 'number' || t === 'boolean') return String(obj);
                if (obj === null) return 'null';
                return undefined;
            }
            var n, v, json = [], arr = (obj instanceof Array);
            for (n in obj) {
                if (!obj.hasOwnProperty(n)) continue;
                v = obj[n];
                t = typeof v;
                if (t === 'undefined' || t === 'function') continue;
                if (t === 'string') v = '"' + v.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t') + '"';
                else if (t === 'object' && v !== null) v = JSON.stringify(v);
                else if (t === 'number' || t === 'boolean') v = String(v);
                else if (v === null) v = 'null';
                json.push((arr ? '' : '"' + n + '":') + v);
            }
            return (arr ? '[' : '{') + json.join(',') + (arr ? ']' : '}');
        },
        parse: function (str) {
            return eval('(' + str + ')');
        }
    };
}

/**
 * Wrap a user script with an iteration safety guard.
 *
 * Injects:
 *   __mcp_ops        – running operation counter
 *   __MCP_MAX_OPS    – hard op limit (default 500 000, overridable by Python)
 *   __mcp_start      – timestamp at script start
 *   __MCP_MAX_MS     – hard wall-clock limit in ms (default 25 000, overridable)
 *   __mcp_check()    – call inside loops; throws when either limit exceeded
 *   __mcp_snapshot(collection) – snapshot a live Illustrator collection to Array
 *   __mcp_forEachSnapshot(collection, fn) – safe iteration with built-in check
 *
 * COVERAGE NOTE:
 *   This is an opt-in guard. Scripts that never call __mcp_check() (e.g. bare
 *   while(true){}) are NOT protected. The only robust fix for non-cooperative
 *   loops is chunked execution via app.scheduleTask() (future P2 work).
 *   The helpers here solve the most common real-world crash class: iterating
 *   a live collection while adding/removing items.
 *
 * @param {string} scriptStr - The raw user script
 * @returns {string} - Script with safety preamble prepended
 */
function wrapWithSafetyGuard(scriptStr) {
    // Do not double-wrap (idempotent)
    if (scriptStr.indexOf('__mcp_ops') >= 0) return scriptStr;

    var preamble =
        '// MCP safety guard \u2013 injected by host.jsx\n' +
        'var __mcp_ops = 0;\n' +
        'var __mcp_start = +new Date();\n' +
        'if (typeof __MCP_MAX_OPS === "undefined") var __MCP_MAX_OPS = 500000;\n' +
        'if (typeof __MCP_MAX_MS  === "undefined") var __MCP_MAX_MS  = 25000;\n' +
        'function __mcp_check() {\n' +
        '  if (++__mcp_ops > __MCP_MAX_OPS)\n' +
        '    throw new Error("MCP_SAFETY: Exceeded " + __MCP_MAX_OPS + " ops. Possible infinite loop.");\n' +
        '  if (__mcp_ops % 1000 === 0 && (+new Date() - __mcp_start) > __MCP_MAX_MS)\n' +
        '    throw new Error("MCP_SAFETY: Exceeded " + __MCP_MAX_MS + "ms wall-clock limit.");\n' +
        '}\n' +
        'function __mcp_snapshot(col) {\n' +
        '  var out = [];\n' +
        '  for (var _i = 0; _i < col.length; _i++) out.push(col[_i]);\n' +
        '  return out;\n' +
        '}\n' +
        'function __mcp_forEachSnapshot(col, fn) {\n' +
        '  var snap = __mcp_snapshot(col);\n' +
        '  for (var _i = 0; _i < snap.length; _i++) { __mcp_check(); fn(snap[_i], _i); }\n' +
        '}\n\n';

    return preamble + scriptStr;
}

/**
 * Execute a JavaScript script string in Illustrator context
 * @param {string} scriptStr - The JavaScript code to execute
 * @returns {string} - JSON string of the result
 */
function executeScript(scriptStr, transport) {
    function withFacts(text) {
        if (typeof mcpOwnAllRecords === "function") {
            var envelope = JSON.parse(text);
            envelope.hostFacts = {ownership:mcpOwnAllRecords()};
            return JSON.stringify(envelope);
        }
        return text;
    }
    try {
        if (transport) {
            // Use the existing document identity rule. Its source is supplied
            // by the Python library resolver, never a second name-based rule.
            eval(transport.bindingPrelude);
            transport.documentId = mcpDocBind({ label: "payload" }).token || "none";
            if (transport.expectedDocumentId && transport.expectedDocumentId !== transport.documentId) {
                throw new Error("MCP_PAYLOAD_DOCUMENT_MISMATCH");
            }
        }
        // Wrap with safety guard to prevent infinite-loop crashes
        var safeScript = wrapWithSafetyGuard(scriptStr);

        // Execute the script
        var result = eval(safeScript);

        // Contract-validated passthrough: if the script already returned
        // a JSON string matching the internal envelope contract, pass it
        // through directly. This eliminates double-serialization for
        // wrap_script() results and SOC batch reports.
        if (typeof result === 'string') {
            try {
                var parsed = JSON.parse(result);
                if (typeof parsed === 'object' && parsed !== null) {
                    var isEnvelope =
                        (parsed.ok === true && 'data' in parsed) ||
                        (parsed.ok === false && 'error' in parsed);
                    if (isEnvelope) return withFacts(result);
                }
            } catch (pe) { /* not JSON, fall through */ }
        }

        // Bare return value — wrap in standard envelope.
        // T11: a null/undefined result is a VALID outcome (a script that only
        // performs side effects), not a failure, so it is reported as data:null
        // rather than being conflated with an error.
        if (result === undefined) result = null;

        // Geometry extractors already serialize once to a JSON string. Preserve
        // it exactly on the negotiated bounded-transfer path; legacy limits
        // remain disclosed for legacy peers and DOM-object serialization.
        var serialized = transport && typeof result === "string" ?
            { value: result, truncated: false } : mcpSerializeResult(result);
        var envelope = { ok: true, data: serialized.value };
        // Any limit that was applied is disclosed, never applied silently.
        if (serialized.truncated) {
            envelope.truncation = serialized.truncation;
        }
        return withFacts(JSON.stringify(envelope));

    } catch (e) {
        // Matches required internal fields; name is extra (useful signal)
        return withFacts(JSON.stringify({
            ok: false,
            error: { message: e.message, line: e.line || null, name: e.name || null }
        }));
    }
}

/**
 * Safe dispatcher for MCP commands (No text concatenation)
 * @param {string} command - The command name
 * @param {object} payload - The arguments object
 * @returns {string} - JSON string of the result
 */
function mcp_dispatch(command, payload) {
    try {
        // Dispatch logic here. For now, we only have simple commands,
        // but this extensibility point allows for mapping string commands
        // to specific functions without 'eval'

        switch (command) {
            case 'ping':
                return ping();
            case 'execute_script':
                // For 'execute_script', we sadly still need eval for arbitrary code,
                // but at least the envelope was safely unpacked
                return executeScript(payload.script);
            default:
                return JSON.stringify({ error: "Unknown command: " + command });
        }
    } catch (e) {
        return JSON.stringify({ error: e.message });
    }
}

/**
 * Handle a full MCP request envelope
 * @param {object} request - The full request object {id, script, command...}
 * @returns {string} - JSON result
 */
function mcp_handle_request(request) {
    if (request.transport && request.transport.version === 1) {
        return mcp_payload_execute(request);
    }
    // If it's a raw script request (classic mode)
    if (request.script) {
        return executeScript(request.script);
    }
    // Future: handle structured commands safely
    return JSON.stringify({ error: "No script provided" });
}

/* OR09/OR10: immutable UTF-8 snapshots, never large evalScript scalar results.
 * Host storage contains bytes and plain identities only. Paging cannot evaluate
 * the original script or read a changed document. Limits apply before storing;
 * the CEP releases snapshots after copying their pages, and TTL covers loss.
 */
function _mcpPayloadStore() {
    if (!$.global.__mcpPayloadsV1) {
        $.global.__mcpPayloadsV1 = {
            epoch: "host_" + (+new Date()).toString(16) + "_" + Math.floor(Math.random() * 0x7fffffff).toString(16),
            entries: {}, bytes: 0
        };
    }
    var store = $.global.__mcpPayloadsV1;
    var now = +new Date();
    for (var key in store.entries) {
        if (store.entries.hasOwnProperty(key) && now >= store.entries[key].expires) {
            store.bytes -= store.entries[key].bytes.length;
            delete store.entries[key];
        }
    }
    return store;
}

function _mcpUtf8(text) {
    // JSON serialization precedes this encoding. Surrogate pairs form one
    // code point; unpaired surrogates use U+FFFD, matching standard UTF-8.
    var out = [], code, next;
    for (var i = 0; i < text.length; i++) {
        code = text.charCodeAt(i);
        if (code >= 0xD800 && code <= 0xDBFF) {
            next = text.charCodeAt(i + 1);
            if (next >= 0xDC00 && next <= 0xDFFF) {
                code = 0x10000 + ((code - 0xD800) << 10) + next - 0xDC00; i++;
            } else code = 0xFFFD;
        } else if (code >= 0xDC00 && code <= 0xDFFF) code = 0xFFFD;
        if (code < 128) out.push(String.fromCharCode(code));
        else if (code < 2048) out.push(String.fromCharCode(192 | (code >> 6), 128 | (code & 63)));
        else if (code < 65536) out.push(String.fromCharCode(224 | (code >> 12), 128 | ((code >> 6) & 63), 128 | (code & 63)));
        else out.push(String.fromCharCode(240 | (code >> 18), 128 | ((code >> 12) & 63), 128 | ((code >> 6) & 63), 128 | (code & 63)));
    }
    return out.join("");
}

function _mcpSha256(bytes) {
    var k = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
    var h = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    var n = bytes.length, padded = bytes + String.fromCharCode(128);
    while (padded.length % 64 !== 56) padded += String.fromCharCode(0);
    for (var z = 7; z >= 0; z--) padded += String.fromCharCode(z >= 4 ? 0 : ((n * 8) >>> (z * 8)) & 255);
    function r(x, bits) { return (x >>> bits) | (x << (32 - bits)); }
    var w = [], a,b,c,d,e,f,g,j,s0,s1,t1,t2,i;
    for (var block = 0; block < padded.length; block += 64) {
        for (i = 0; i < 16; i++) {
            var p = block + i * 4;
            w[i] = (padded.charCodeAt(p) << 24) | (padded.charCodeAt(p+1) << 16) | (padded.charCodeAt(p+2) << 8) | padded.charCodeAt(p+3);
        }
        for (i = 16; i < 64; i++) {
            s0 = r(w[i-15],7) ^ r(w[i-15],18) ^ (w[i-15] >>> 3);
            s1 = r(w[i-2],17) ^ r(w[i-2],19) ^ (w[i-2] >>> 10);
            w[i] = (w[i-16] + s0 + w[i-7] + s1) | 0;
        }
        a=h[0]; b=h[1]; c=h[2]; d=h[3]; e=h[4]; f=h[5]; g=h[6]; j=h[7];
        for (i = 0; i < 64; i++) {
            s1 = r(e,6) ^ r(e,11) ^ r(e,25);
            t1 = (j + s1 + ((e & f) ^ (~e & g)) + k[i] + w[i]) | 0;
            s0 = r(a,2) ^ r(a,13) ^ r(a,22);
            t2 = (s0 + ((a & b) ^ (a & c) ^ (b & c))) | 0;
            j=g; g=f; f=e; e=(d+t1)|0; d=c; c=b; b=a; a=(t1+t2)|0;
        }
        h[0]=(h[0]+a)|0; h[1]=(h[1]+b)|0; h[2]=(h[2]+c)|0; h[3]=(h[3]+d)|0;
        h[4]=(h[4]+e)|0; h[5]=(h[5]+f)|0; h[6]=(h[6]+g)|0; h[7]=(h[7]+j)|0;
    }
    var hex = "";
    for (i = 0; i < 8; i++) hex += ("00000000" + (h[i] >>> 0).toString(16)).slice(-8);
    return hex;
}

function _mcpBase64(bytes) {
    var alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/", out = [];
    for (var i = 0; i < bytes.length; i += 3) {
        var a = bytes.charCodeAt(i), b = i+1 < bytes.length ? bytes.charCodeAt(i+1) : 0;
        var c = i+2 < bytes.length ? bytes.charCodeAt(i+2) : 0;
        out.push(alphabet.charAt(a >> 2), alphabet.charAt(((a & 3) << 4) | (b >> 4)),
            i+1 < bytes.length ? alphabet.charAt(((b & 15) << 2) | (c >> 6)) : "=",
            i+2 < bytes.length ? alphabet.charAt(c & 63) : "=");
    }
    return out.join("");
}

function mcp_payload_execute(request) {
    var options = request.transport, store = _mcpPayloadStore();
    try {
        var identities = [request.jobId, request.requestToken, options.sessionId];
        for (var identityIndex = 0; identityIndex < identities.length; identityIndex++) {
            if (typeof identities[identityIndex] !== "string" || !identities[identityIndex] || identities[identityIndex].length > 256) throw new Error("invalid_payload_identity");
        }
        if (options.hostSession && options.hostSession !== store.epoch) throw new Error("stale_host_session");
        var key = options.payloadId;
        if (!/^[a-f0-9]{32}$/.test(key)) throw new Error("invalid_payload_id");
        if (store.entries[key]) {
            _mcpPayloadEntry({payloadId:key, sessionId:options.sessionId, jobId:request.jobId, requestToken:request.requestToken});
            return JSON.stringify({ payloadDescriptor: store.entries[key].descriptor });
        }
        var count = 0;
        for (var existing in store.entries) if (store.entries.hasOwnProperty(existing)) count++;
        if (count >= 128 || store.bytes >= 64 * 1024 * 1024) throw new Error("payload_storage_limit");
        var text = executeScript(request.script, options);
        var bytes = _mcpUtf8(text);
        if (bytes.length > 32 * 1024 * 1024 || store.bytes + bytes.length > 64 * 1024 * 1024) throw new Error("payload_size_limit");
        var descriptor = {version:1, jobId:request.jobId, requestId:request.id, requestToken:request.requestToken,
            sessionId:options.sessionId, hostSession:store.epoch, documentId:options.documentId || "none",
            payloadId:key, encoding:"utf-8", byteLength:bytes.length, digestAlgorithm:"sha256",
            digest:_mcpSha256(bytes), transferMode:"pages", pageBytes:12288};
        if (_mcpUtf8(JSON.stringify(descriptor)).length > 4096) throw new Error("payload_descriptor_limit");
        store.entries[key] = {bytes:bytes, descriptor:descriptor, expires:(+new Date())+120000};
        store.bytes += bytes.length;
        return JSON.stringify({payloadDescriptor:descriptor});
    } catch (e) {
        return JSON.stringify({payloadError:String(e.message || e)});
    }
}

function _mcpPayloadEntry(spec) {
    var store = _mcpPayloadStore(), entry = store.entries[spec.payloadId];
    if (!entry) throw new Error("payload_expired_or_released");
    var descriptor = entry.descriptor;
    if (descriptor.sessionId !== spec.sessionId || descriptor.jobId !== spec.jobId || descriptor.requestToken !== spec.requestToken) {
        throw new Error("payload_owner_mismatch");
    }
    return entry;
}

function mcp_payload_read(spec) {
    try {
        var entry = _mcpPayloadEntry(spec), offset = spec.offset;
        if (typeof offset !== "number" || offset < 0 || offset % 12288 !== 0 || offset >= entry.bytes.length) throw new Error("invalid_page_offset");
        return JSON.stringify({payloadId:spec.payloadId, offset:offset, data:_mcpBase64(entry.bytes.substring(offset, offset+12288))});
    } catch (e) { return JSON.stringify({payloadError:String(e.message || e)}); }
}

function mcp_payload_release(spec) {
    try {
        var entry = _mcpPayloadEntry(spec), store = _mcpPayloadStore();
        store.bytes -= entry.bytes.length;
        delete store.entries[spec.payloadId];
        return JSON.stringify({released:true});
    } catch (e) { return JSON.stringify({released:false, payloadError:String(e.message || e)}); }
}

function ping() {
    return JSON.stringify({
        pong: true,
        app: app.name,
        version: app.version,
        libs: ["host.jsx"]
    });
}

/* ==================== Result serialisation (T11) ====================
 *
 * Ordinary JavaScript values returned by a script must survive intact.
 *
 * The previous implementation routed EVERY object through an Illustrator DOM
 * property whitelist, so a plain result was destroyed on the way out:
 *   ({answer: 42, items: [1,2,3]})  ->  "[object Object]"
 * because none of the whitelisted DOM properties existed and the fallback was
 * String(obj). Arrays were silently cut to 100 elements with no indication,
 * and depth > 5 became the literal string '[Max depth reached]'. That is why
 * so many scripts hand-roll JSON.stringify — and why measurement results
 * arrived empty.
 *
 * The fix is to tell the two kinds of value apart. Measured in Illustrator
 * 30.7.0:
 *
 *   plain object  reflect.name === "Object",   typeof typename === "undefined"
 *   plain array   reflect.name === "Array",    obj instanceof Array
 *   DOM item      reflect.name === "PathItem", typename === "PathItem"
 *
 * Plain values are preserved losslessly; host objects keep the whitelist
 * extraction, which is genuinely useful for them. Limits still exist, but
 * every one of them is now REPORTED rather than applied silently.
 */

var MCP_SER_MAX_DEPTH = 12;      /* plain JSON legitimately nests */
var MCP_SER_MAX_NODES = 20000;   /* total values across the whole result */
var MCP_SER_MAX_ARRAY = 5000;    /* elements per array */
var MCP_SER_MAX_KEYS = 1000;     /* keys per object */
var MCP_SER_MAX_STRING = 100000; /* characters per string */

/** Collected truncation notes for the serialisation currently in progress. */
var _mcpSerNotes = [];
var _mcpSerNodes = 0;

function _mcpSerNote(path, reason, kept, total) {
    if (_mcpSerNotes.length >= 50) return;
    var note = { path: path || '$', reason: reason };
    if (kept !== undefined) note.kept = kept;
    if (total !== undefined) note.total = total;
    _mcpSerNotes.push(note);
}

/**
 * Is this a plain JSON-ish value rather than an Illustrator host object?
 */
function _mcpIsPlainObject(obj) {
    try {
        if (obj.reflect && obj.reflect.name === 'Object') return true;
    } catch (e) { /* reflect may be unavailable */ }
    try {
        if (typeof obj.typename === 'string') return false;
    } catch (e) { /* host objects can throw on property access */ }
    try {
        if (obj.constructor === Object) return true;
    } catch (e) { }
    return false;
}

function _mcpIsPlainArray(obj) {
    if (obj instanceof Array) return true;
    try {
        if (obj.reflect && obj.reflect.name === 'Array') return true;
    } catch (e) { }
    return false;
}

/* Properties worth extracting from an Illustrator DOM object. */
var MCP_DOM_PROPS = ['name', 'typename', 'width', 'height', 'left', 'top',
    'bounds', 'geometricBounds', 'visibleBounds', 'visible', 'hidden', 'locked',
    'selected', 'opacity', 'fillColor', 'strokeColor', 'strokeWidth',
    'contents', 'note', 'length', 'index'];

/**
 * Convert a value for transport.
 *
 * @param {*} obj - value to convert
 * @param {number} depth - current recursion depth
 * @param {string} path - JSON-path-ish location, used in truncation notes
 * @returns {*} - a JSON-serialisable value
 */
function convertToPlainObject(obj, depth, path) {
    if (depth === undefined) depth = 0;
    if (path === undefined) path = '$';

    if (obj === null || obj === undefined) return null;

    var t = typeof obj;
    if (t === 'function') return undefined;

    if (t === 'string') {
        if (obj.length > MCP_SER_MAX_STRING) {
            _mcpSerNote(path, 'string_truncated', MCP_SER_MAX_STRING, obj.length);
            return obj.substring(0, MCP_SER_MAX_STRING);
        }
        return obj;
    }

    if (t === 'number' || t === 'boolean') {
        /* NaN/Infinity are not representable in JSON — say so rather than
         * emitting a token that parses as null on the other side. */
        if (t === 'number' && !isFinite(obj)) {
            _mcpSerNote(path, 'non_finite_number');
            return null;
        }
        return obj;
    }

    if (t !== 'object') return String(obj);

    if (++_mcpSerNodes > MCP_SER_MAX_NODES) {
        _mcpSerNote(path, 'node_budget_exhausted', MCP_SER_MAX_NODES);
        return null;
    }

    if (depth > MCP_SER_MAX_DEPTH) {
        _mcpSerNote(path, 'max_depth', MCP_SER_MAX_DEPTH);
        return null;
    }

    /* --- Dates serialise as ISO-ish strings --- */
    try {
        if (obj instanceof Date) return obj.toString();
    } catch (e) { }

    /* --- Arrays (plain, or an Illustrator collection) --- */
    if (_mcpIsPlainArray(obj) ||
        (obj.length !== undefined && typeof obj.length === 'number' &&
         !_mcpIsPlainObject(obj))) {
        var out = [];
        var total = obj.length;
        var len = total < MCP_SER_MAX_ARRAY ? total : MCP_SER_MAX_ARRAY;
        for (var i = 0; i < len; i++) {
            try {
                out.push(convertToPlainObject(obj[i], depth + 1, path + '[' + i + ']'));
            } catch (e) {
                out.push(null);
                _mcpSerNote(path + '[' + i + ']', 'read_error: ' + e.message);
            }
        }
        if (total > len) {
            _mcpSerNote(path, 'array_truncated', len, total);
        }
        return out;
    }

    /* --- Plain object: preserve every own property --- */
    if (_mcpIsPlainObject(obj)) {
        var plain = {};
        var keys = 0;
        for (var k in obj) {
            if (!obj.hasOwnProperty(k)) continue;
            if (keys >= MCP_SER_MAX_KEYS) {
                _mcpSerNote(path, 'object_truncated', MCP_SER_MAX_KEYS);
                break;
            }
            try {
                var v = convertToPlainObject(obj[k], depth + 1, path + '.' + k);
                if (v !== undefined) { plain[k] = v; keys++; }
            } catch (e) {
                _mcpSerNote(path + '.' + k, 'read_error: ' + e.message);
            }
        }
        return plain;
    }

    /* --- Illustrator host object: whitelist extraction --- */
    var result = {};
    var extracted = 0;
    for (var p = 0; p < MCP_DOM_PROPS.length; p++) {
        var prop = MCP_DOM_PROPS[p];
        try {
            var val = obj[prop];
            if (val === undefined || typeof val === 'function') continue;
            result[prop] = convertToPlainObject(val, depth + 1, path + '.' + prop);
            extracted++;
        } catch (e) {
            /* Property not readable on this object type — expected, skip. */
        }
    }

    if (extracted === 0) {
        _mcpSerNote(path, 'unrecognised_object');
        try { return String(obj); } catch (e) { return '[Object]'; }
    }
    return result;
}

/**
 * Serialise a script result, reporting any truncation explicitly.
 *
 * @param {*} value
 * @returns {Object} {value, truncated, truncation}
 */
function mcpSerializeResult(value) {
    _mcpSerNotes = [];
    _mcpSerNodes = 0;
    var converted;
    try {
        converted = convertToPlainObject(value, 0, '$');
    } catch (e) {
        _mcpSerNote('$', 'serialisation_failed: ' + e.message);
        converted = null;
    }
    return {
        value: converted === undefined ? null : converted,
        truncated: _mcpSerNotes.length > 0,
        truncation: _mcpSerNotes
    };
}

/**
 * Helper function to get document info
 * @returns {string} - JSON string with document information
 */
function getDocumentInfo() {
    try {
        if (app.documents.length === 0) {
            return JSON.stringify({ error: 'No documents open' });
        }

        var doc = app.activeDocument;
        return JSON.stringify({
            name: doc.name,
            path: doc.path ? doc.path.fsName : '',
            width: doc.width,
            height: doc.height,
            artboards: doc.artboards.length,
            layers: doc.layers.length
        });
    } catch (e) {
        return JSON.stringify({ error: e.message });
    }
}

/**
 * Test function to verify ExtendScript is working
 * @returns {string} - Test result
 */
function testConnection() {
    return JSON.stringify({
        ok: true,
        data: {
            app: app.name,
            version: app.version,
            documentsOpen: app.documents.length
        },
        operation: "test_connection"
    });
}
