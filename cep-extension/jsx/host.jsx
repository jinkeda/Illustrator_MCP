/**
 * ExtendScript Host for Illustrator MCP
 *
 * This script runs in the Illustrator ExtendScript context and provides
 * the bridge between the CEP panel JavaScript and Illustrator's DOM.
 */

// JSON polyfill for ExtendScript (which lacks native JSON support)
if (typeof JSON === 'undefined') {
    JSON = {
        stringify: function(obj) {
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
        parse: function(str) {
            return eval('(' + str + ')');
        }
    };
}

/**
 * Execute a JavaScript script string in Illustrator context
 * @param {string} scriptStr - The JavaScript code to execute
 * @returns {string} - JSON string of the result
 */
function executeScript(scriptStr) {
    try {
        // Execute the script
        var result = eval(scriptStr);

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
