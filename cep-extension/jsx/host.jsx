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
                if (t === 'string') return '"' + obj.replace(/"/g, '\\"').replace(/\n/g, '\\n').replace(/\r/g, '\\r') + '"';
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
                if (t === 'string') v = '"' + v.replace(/"/g, '\\"').replace(/\n/g, '\\n').replace(/\r/g, '\\r') + '"';
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
function executeScript(scriptStr) {
    try {
        // Wrap with safety guard to prevent infinite-loop crashes
        var safeScript = wrapWithSafetyGuard(scriptStr);

        // Execute the script
        var result = eval(safeScript);

        // Convert result to JSON-safe format
        if (result === undefined) {
            return JSON.stringify({ success: true, result: null });
        }

        // Handle Illustrator objects by converting to plain objects
        if (typeof result === 'object' && result !== null) {
            result = convertToPlainObject(result);
        }

        return JSON.stringify({ success: true, result: result });

    } catch (e) {
        return JSON.stringify({
            success: false,
            error: e.message,
            line: e.line
        });
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
    // If it's a raw script request (classic mode)
    if (request.script) {
        return executeScript(request.script);
    }
    // Future: handle structured commands safely
    return JSON.stringify({ error: "No script provided" });
}

function ping() {
    return JSON.stringify({
        pong: true,
        app: app.name,
        version: app.version,
        libs: ["host.jsx"]
    });
}

/**
 * Convert Illustrator DOM objects to plain JavaScript objects
 * @param {*} obj - Object to convert
 * @param {number} depth - Current recursion depth
 * @returns {*} - Plain JavaScript object
 */
function convertToPlainObject(obj, depth) {
    if (depth === undefined) depth = 0;
    if (depth > 5) return '[Max depth reached]';

    if (obj === null || obj === undefined) {
        return obj;
    }

    // Handle primitive types
    if (typeof obj !== 'object') {
        return obj;
    }

    // Handle arrays
    if (obj instanceof Array || (obj.length !== undefined && typeof obj.length === 'number')) {
        var arr = [];
        var len = Math.min(obj.length, 100); // Limit array size
        for (var i = 0; i < len; i++) {
            try {
                arr.push(convertToPlainObject(obj[i], depth + 1));
            } catch (e) {
                arr.push('[Error: ' + e.message + ']');
            }
        }
        return arr;
    }

    // Handle Illustrator objects - extract common properties
    var result = {};

    // Common properties to extract
    var props = ['name', 'typename', 'width', 'height', 'left', 'top',
        'bounds', 'visible', 'locked', 'selected', 'opacity',
        'fillColor', 'strokeColor', 'strokeWidth', 'contents',
        'length', 'index', 'parent'];

    for (var i = 0; i < props.length; i++) {
        var prop = props[i];
        try {
            if (obj[prop] !== undefined) {
                var val = obj[prop];
                if (typeof val !== 'function') {
                    result[prop] = convertToPlainObject(val, depth + 1);
                }
            }
        } catch (e) {
            // Property not accessible, skip
        }
    }

    // If no properties were extracted, try to get a string representation
    if (Object.keys(result).length === 0) {
        try {
            result = String(obj);
        } catch (e) {
            result = '[Object]';
        }
    }

    return result;
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
        success: true,
        app: app.name,
        version: app.version,
        documentsOpen: app.documents.length
    });
}
