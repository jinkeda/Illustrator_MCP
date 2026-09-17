/**
 * polyfills.jsx - ES3 Array & JSON Polyfills
 * Part of Illustrator MCP Standard Library
 * @version 1.0.0
 *
 * Provides missing Array.prototype methods and JSON for ExtendScript.
 * MUST be loaded first in the dependency chain.
 *
 * Extracted from task_executor.jsx (Phase 5 decomposition).
 */

// ==================== ES3 Array Polyfills ====================
// ExtendScript is based on ES3 and lacks many modern array methods

if (!Array.prototype.indexOf) {
    Array.prototype.indexOf = function (searchElement, fromIndex) {
        var k;
        if (this == null) {
            throw new TypeError('"this" is null or not defined');
        }
        var o = Object(this);
        var len = o.length >>> 0;
        if (len === 0) {
            return -1;
        }
        var n = fromIndex | 0;
        if (n >= len) {
            return -1;
        }
        k = Math.max(n >= 0 ? n : len - Math.abs(n), 0);
        while (k < len) {
            if (k in o && o[k] === searchElement) {
                return k;
            }
            k++;
        }
        return -1;
    };
}

if (!Array.prototype.forEach) {
    Array.prototype.forEach = function (callback, thisArg) {
        if (this == null) throw new TypeError('"this" is null or not defined');
        var o = Object(this);
        var len = o.length >>> 0;
        if (typeof callback !== 'function') throw new TypeError(callback + ' is not a function');
        for (var k = 0; k < len; k++) {
            if (k in o) callback.call(thisArg, o[k], k, o);
        }
    };
}

if (!Array.prototype.map) {
    Array.prototype.map = function (callback, thisArg) {
        if (this == null) throw new TypeError('"this" is null or not defined');
        var o = Object(this);
        var len = o.length >>> 0;
        if (typeof callback !== 'function') throw new TypeError(callback + ' is not a function');
        var result = new Array(len);
        for (var k = 0; k < len; k++) {
            if (k in o) result[k] = callback.call(thisArg, o[k], k, o);
        }
        return result;
    };
}

if (!Array.prototype.filter) {
    Array.prototype.filter = function (callback, thisArg) {
        if (this == null) throw new TypeError('"this" is null or not defined');
        var o = Object(this);
        var len = o.length >>> 0;
        if (typeof callback !== 'function') throw new TypeError(callback + ' is not a function');
        var result = [];
        for (var k = 0; k < len; k++) {
            if (k in o && callback.call(thisArg, o[k], k, o)) result.push(o[k]);
        }
        return result;
    };
}

if (!Array.prototype.every) {
    Array.prototype.every = function (callback, thisArg) {
        if (this == null) throw new TypeError('"this" is null or not defined');
        var o = Object(this);
        var len = o.length >>> 0;
        if (typeof callback !== 'function') throw new TypeError(callback + ' is not a function');
        for (var k = 0; k < len; k++) {
            if (k in o && !callback.call(thisArg, o[k], k, o)) return false;
        }
        return true;
    };
}

if (!Array.prototype.some) {
    Array.prototype.some = function (callback, thisArg) {
        if (this == null) throw new TypeError('"this" is null or not defined');
        var o = Object(this);
        var len = o.length >>> 0;
        if (typeof callback !== 'function') throw new TypeError(callback + ' is not a function');
        for (var k = 0; k < len; k++) {
            if (k in o && callback.call(thisArg, o[k], k, o)) return true;
        }
        return false;
    };
}

if (!Array.prototype.reduce) {
    Array.prototype.reduce = function (callback, initialValue) {
        if (this == null) throw new TypeError('"this" is null or not defined');
        var o = Object(this);
        var len = o.length >>> 0;
        if (typeof callback !== 'function') throw new TypeError(callback + ' is not a function');
        var k = 0;
        var value;
        if (arguments.length >= 2) {
            value = initialValue;
        } else {
            while (k < len && !(k in o)) k++;
            if (k >= len) throw new TypeError('Reduce of empty array with no initial value');
            value = o[k++];
        }
        for (; k < len; k++) {
            if (k in o) value = callback(value, o[k], k, o);
        }
        return value;
    };
}

// ==================== JSON Polyfill ====================
//
// DO NOT reintroduce `var JSON` here. The previous version was:
//
//     if (typeof JSON === "undefined") { var JSON = {}; JSON.stringify = ... }
//
// `var` is function-scoped and hoisted, so declaring it *inside* the guard
// still created a local `JSON` shadowing the host's for the whole injected
// script. `typeof JSON === "undefined"` was therefore ALWAYS true, and every
// script that injected any library (polyfills is a dependency of nearly all
// of them) silently lost host.jsx's JSON implementation and got this one —
// which had no `parse` at all, and a `stringify` that escaped only `"` and
// `\n`.
//
// Not escaping backslashes is the damaging part: stringifying a value that
// already contains JSON (e.g. wrapping extractPathGeometry's output, which is
// full of \" sequences) emitted unescaped backslashes and produced INVALID
// JSON. Python then failed to parse the response, which surfaced as
// "could not parse host result" rather than anything pointing here.
//
// So: never shadow, and only fill in members that are genuinely missing.

if (typeof JSON === "undefined") {
    $.global.JSON = {};
}

if (typeof JSON.stringify !== "function") {
    JSON.stringify = (function () {
        var ESCAPES = {
            "\\": "\\\\",
            '"': '\\"',
            "\b": "\\b",
            "\f": "\\f",
            "\n": "\\n",
            "\r": "\\r",
            "\t": "\\t"
        };

        function quote(s) {
            var out = '"', i, c, code;
            for (i = 0; i < s.length; i++) {
                c = s.charAt(i);
                if (ESCAPES[c]) {
                    out += ESCAPES[c];
                    continue;
                }
                code = s.charCodeAt(i);
                if (code < 0x20) {
                    // Control characters must be \u-escaped or the result is
                    // not valid JSON.
                    var hex = code.toString(16);
                    while (hex.length < 4) hex = "0" + hex;
                    out += "\\u" + hex;
                } else {
                    out += c;
                }
            }
            return out + '"';
        }

        function serialize(value) {
            var t = typeof value;
            if (value === null) return "null";
            if (t === "string") return quote(value);
            if (t === "number") return isFinite(value) ? String(value) : "null";
            if (t === "boolean") return String(value);
            if (t === "undefined" || t === "function") return undefined;
            if (t !== "object") return quote(String(value));

            var parts = [], i, n, encoded;
            if (value instanceof Array) {
                for (i = 0; i < value.length; i++) {
                    encoded = serialize(value[i]);
                    parts.push(encoded === undefined ? "null" : encoded);
                }
                return "[" + parts.join(",") + "]";
            }
            for (n in value) {
                if (!value.hasOwnProperty(n)) continue;
                encoded = serialize(value[n]);
                if (encoded === undefined) continue;
                parts.push(quote(String(n)) + ":" + encoded);
            }
            return "{" + parts.join(",") + "}";
        }

        return function (obj) { return serialize(obj); };
    })();
}

if (typeof JSON.parse !== "function") {
    JSON.parse = function (str) {
        return eval("(" + str + ")");
    };
}
