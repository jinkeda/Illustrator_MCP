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

if (typeof JSON === "undefined") {
    var JSON = {};
    JSON.stringify = function (obj) {
        var t = typeof obj;
        if (t !== "object" || obj === null) {
            if (t === "string") return '"' + obj.replace(/"/g, '\\"').replace(/\n/g, '\\n') + '"';
            return String(obj);
        }
        var n, v, json = [];
        var isArray = (obj && obj.constructor === Array);
        for (n in obj) {
            if (!obj.hasOwnProperty(n)) continue;
            v = obj[n];
            t = typeof v;
            if (t === "string") {
                v = '"' + v.replace(/"/g, '\\"').replace(/\n/g, '\\n') + '"';
            } else if (t === "object" && v !== null) {
                v = JSON.stringify(v);
            }
            json.push((isArray ? "" : '"' + n + '":') + String(v));
        }
        return (isArray ? "[" : "{") + String(json) + (isArray ? "]" : "}");
    };
}
