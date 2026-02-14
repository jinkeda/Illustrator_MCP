/**
 * run_tests.js — Pure JS Test Harness for Illustrator MCP
 *
 * Tests pure JSX modules that have NO Illustrator DOM dependency:
 * - geo_ir.jsx (geometry IR validation, mapping, flattening)
 * - mcp_id.jsx (ID extraction, note manipulation)
 *
 * Run with: node tests_jsx/run_tests.js
 *
 * This provides CI-compatible testing without requiring Illustrator.
 */

// ==================== Polyfills for ExtendScript globals ====================

// ExtendScript's $.global — must be truly global for vm.runInThisContext
globalThis.$ = { global: {} };

// ==================== Minimal Test Framework ====================

var _tests = [];
var _passed = 0;
var _failed = 0;
var _errors = [];

function describe(name, fn) {
    console.log("\n  " + name);
    fn();
}

function it(name, fn) {
    _tests.push({ name: name, fn: fn });
    try {
        fn();
        _passed++;
        console.log("    \x1b[32m✓\x1b[0m " + name);
    } catch (e) {
        _failed++;
        _errors.push({ name: name, error: e.message });
        console.log("    \x1b[31m✗\x1b[0m " + name);
        console.log("      " + e.message);
    }
}

function assert(condition, message) {
    if (!condition) throw new Error(message || "Assertion failed");
}

function assertEqual(actual, expected, message) {
    if (actual !== expected) {
        throw new Error(
            (message || "assertEqual") +
            ": expected " + JSON.stringify(expected) +
            ", got " + JSON.stringify(actual)
        );
    }
}

function assertDeepEqual(actual, expected, message) {
    if (JSON.stringify(actual) !== JSON.stringify(expected)) {
        throw new Error(
            (message || "assertDeepEqual") +
            ":\n      expected " + JSON.stringify(expected) +
            "\n      got      " + JSON.stringify(actual)
        );
    }
}

// ==================== Load Source Files ====================

var fs = require("fs");
var path = require("path");
var vm = require("vm");

var scriptsDir = path.join(__dirname, "..", "illustrator_mcp", "resources", "scripts");

function loadScript(filename) {
    var filePath = path.join(scriptsDir, filename);
    var code = fs.readFileSync(filePath, "utf-8");
    // Execute in a shared sandbox that accumulates exports
    vm.runInThisContext(code, { filename: filename });
}

// Load modules in dependency order
loadScript("mcp_id.jsx");
loadScript("heap.jsx");
loadScript("geo_ir.jsx");

// ==================== geo_ir.jsx Tests ====================

describe("geo_ir — Factories", function () {
    it("irPath creates valid path IR", function () {
        var p = irPath([[0, 0], [10, 20]], true, { seed: 42 });
        assertEqual(p.v, 1, "version");
        assertEqual(p.ir, "path", "type");
        assertEqual(p.kind, "polyline", "kind");
        assertEqual(p.closed, true, "closed");
        assertEqual(p.points.length, 2, "points count");
        assertEqual(p.meta.seed, 42, "meta.seed");
    });

    it("irPath defaults: closed=false, meta={}", function () {
        var p = irPath([[1, 2]]);
        assertEqual(p.closed, false, "closed default");
        assertDeepEqual(p.meta, {}, "meta default");
    });

    it("irMulti creates valid multi IR", function () {
        var p1 = irPath([[0, 0], [1, 1]]);
        var p2 = irPath([[2, 2], [3, 3]], true);
        var m = irMulti([p1, p2], { algo: "test" });
        assertEqual(m.v, 1, "version");
        assertEqual(m.ir, "multi", "type");
        assertEqual(m.paths.length, 2, "paths count");
        assertEqual(m.meta.algo, "test", "meta.algo");
    });

    it("irPoints creates valid points IR", function () {
        var pts = irPoints([[5, 10], [15, 20]]);
        assertEqual(pts.ir, "points", "type");
        assertEqual(pts.points.length, 2, "points count");
    });
});

describe("geo_ir — isIR / irType", function () {
    it("isIR returns true for valid IR", function () {
        assert(isIR(irPath([])), "path");
        assert(isIR(irMulti([])), "multi");
        assert(isIR(irPoints([])), "points");
    });

    it("isIR returns false for non-IR", function () {
        assert(!isIR(null), "null");
        assert(!isIR(42), "number");
        assert(!isIR("path"), "string");
        assert(!isIR({}), "empty obj");
        assert(!isIR({ type: "path" }), "wrong key");
    });

    it("irType returns type string", function () {
        assertEqual(irType(irPath([])), "path");
        assertEqual(irType(irMulti([])), "multi");
        assertEqual(irType(irPoints([])), "points");
        assertEqual(irType({}), null);
        assertEqual(irType(null), null);
    });
});

describe("geo_ir — irValidate", function () {
    it("valid path passes", function () {
        var result = irValidate(irPath([[0, 0], [10, 20]], false));
        assert(result.ok, "should be ok");
        assertEqual(result.errors.length, 0, "no errors");
    });

    it("rejects non-IR objects", function () {
        var result = irValidate({ foo: "bar" });
        assert(!result.ok, "should fail");
        assert(result.errors[0].indexOf("missing") >= 0 || result.errors[0].indexOf("Not an IR") >= 0, "error message");
    });

    it("rejects unknown IR type", function () {
        var result = irValidate({ v: 1, ir: "bezier", points: [] });
        assert(!result.ok, "should fail");
    });

    it("rejects wrong version", function () {
        var result = irValidate({ v: 99, ir: "path", points: [[0, 0]], kind: "polyline" });
        assert(!result.ok, "should fail");
    });

    it("rejects invalid points", function () {
        var result = irValidate({ v: 1, ir: "path", kind: "polyline", points: [[0, "bad"]] });
        assert(!result.ok, "should fail for non-number");
    });

    it("rejects NaN/Infinity in points", function () {
        var result = irValidate({ v: 1, ir: "path", kind: "polyline", points: [[NaN, 0]] });
        assert(!result.ok, "NaN should fail");

        var result2 = irValidate({ v: 1, ir: "path", kind: "polyline", points: [[Infinity, 0]] });
        assert(!result2.ok, "Infinity should fail");
    });

    it("validates multi with nested paths", function () {
        var m = irMulti([irPath([[0, 0]])]);
        var result = irValidate(m);
        assert(result.ok, "valid multi");
    });

    it("rejects empty multi", function () {
        var result = irValidate({ v: 1, ir: "multi", paths: [] });
        assert(!result.ok, "empty paths");
    });

    it("normalizes missing meta to {}", function () {
        var obj = { v: 1, ir: "path", kind: "polyline", points: [[0, 0]] };
        irValidate(obj);
        assertDeepEqual(obj.meta, {}, "meta normalized");
    });
});

describe("geo_ir — irFlatten", function () {
    it("flattens path to [path]", function () {
        var p = irPath([[0, 0]]);
        var flat = irFlatten(p);
        assertEqual(flat.length, 1, "one path");
        assertEqual(flat[0], p, "same object");
    });

    it("flattens multi to its paths", function () {
        var p1 = irPath([[0, 0]]);
        var p2 = irPath([[1, 1]]);
        var m = irMulti([p1, p2]);
        var flat = irFlatten(m);
        assertEqual(flat.length, 2, "two paths");
    });

    it("flattens points to []", function () {
        assertEqual(irFlatten(irPoints([[0, 0]])).length, 0, "empty");
    });

    it("handles non-IR input", function () {
        assertEqual(irFlatten(null).length, 0);
        assertEqual(irFlatten({}).length, 0);
    });
});

describe("geo_ir — irPointCount", function () {
    it("counts path points", function () {
        assertEqual(irPointCount(irPath([[0, 0], [1, 1], [2, 2]])), 3);
    });

    it("counts multi points recursively", function () {
        var m = irMulti([
            irPath([[0, 0], [1, 1]]),
            irPath([[2, 2], [3, 3], [4, 4]])
        ]);
        assertEqual(irPointCount(m), 5);
    });

    it("counts points IR", function () {
        assertEqual(irPointCount(irPoints([[0, 0], [1, 1]])), 2);
    });

    it("returns 0 for non-IR", function () {
        assertEqual(irPointCount(null), 0);
        assertEqual(irPointCount({}), 0);
    });
});

describe("geo_ir — irMapPoints", function () {
    it("maps path points through transform", function () {
        var p = irPath([[10, 20], [30, 40]]);
        var scaled = irMapPoints(p, function (pt) { return [pt[0] * 2, pt[1] * 2]; });
        assertDeepEqual(scaled.points, [[20, 40], [60, 80]], "scaled points");
        assertEqual(scaled.ir, "path", "still a path");
        assertEqual(scaled.closed, false, "preserves closed");
    });

    it("does not mutate original", function () {
        var p = irPath([[10, 20]]);
        irMapPoints(p, function (pt) { return [0, 0]; });
        assertDeepEqual(p.points, [[10, 20]], "original unchanged");
    });

    it("maps multi recursively", function () {
        var m = irMulti([irPath([[1, 2]]), irPath([[3, 4]])]);
        var neg = irMapPoints(m, function (pt) { return [-pt[0], -pt[1]]; });
        assertDeepEqual(neg.paths[0].points, [[-1, -2]], "first path");
        assertDeepEqual(neg.paths[1].points, [[-3, -4]], "second path");
    });

    it("maps points IR", function () {
        var pts = irPoints([[5, 10]]);
        var flipped = irMapPoints(pts, function (pt) { return [pt[0], -pt[1]]; });
        assertDeepEqual(flipped.points, [[5, -10]], "y-flipped");
    });

    it("Y-flip transform (Illustrator convention)", function () {
        var p = irPath([[100, 200], [300, 400]]);
        var flipped = irMapPoints(p, function (pt) { return [pt[0], -pt[1]]; });
        assertDeepEqual(flipped.points, [[100, -200], [300, -400]], "y-flip");
    });

    it("returns non-IR input unchanged", function () {
        var obj = { foo: "bar" };
        assertEqual(irMapPoints(obj, function () { return [0, 0]; }), obj);
        assertEqual(irMapPoints(null, function () { return [0, 0]; }), null);
    });
});

// ==================== mcp_id.jsx Tests ====================

describe("mcp_id — extractMcpId", function () {
    it("extracts ID from simple note", function () {
        assertEqual(extractMcpId("@mcp:id=abc123"), "abc123");
    });

    it("extracts ID from note with other tags", function () {
        assertEqual(extractMcpId("some text @mcp:id=foo_bar more text"), "foo_bar");
    });

    it("extracts UUID-style ID", function () {
        assertEqual(extractMcpId("@mcp:id=mcp_a1b2c3d4-e5f6-4789-abcd-ef0123456789"), "mcp_a1b2c3d4-e5f6-4789-abcd-ef0123456789");
    });

    it("returns null for empty/null note", function () {
        assertEqual(extractMcpId(null), null);
        assertEqual(extractMcpId(""), null);
        assertEqual(extractMcpId(undefined), null);
    });

    it("returns null for note without MCP ID", function () {
        assertEqual(extractMcpId("just some text"), null);
        assertEqual(extractMcpId("@other:tag=value"), null);
    });
});

describe("mcp_id — removeIdFromNote", function () {
    it("removes ID tag from note", function () {
        assertEqual(removeIdFromNote("@mcp:id=abc123"), "");
    });

    it("removes ID tag preserving other content", function () {
        assertEqual(removeIdFromNote("prefix @mcp:id=abc123 suffix"), "prefix suffix");
    });

    it("handles null/empty", function () {
        assertEqual(removeIdFromNote(null), "");
        assertEqual(removeIdFromNote(""), "");
    });
});

describe("mcp_id — removeFromIdIndex", function () {
    it("removes ID from global index", function () {
        $.global.mcpIdIndex = { docName: "test", index: { "a": "itemA", "b": "itemB" } };
        assert(removeFromIdIndex("a"), "should return true");
        assertEqual($.global.mcpIdIndex.index["a"], undefined, "removed");
        assertEqual($.global.mcpIdIndex.index["b"], "itemB", "other preserved");
    });

    it("returns false for missing ID", function () {
        $.global.mcpIdIndex = { docName: "test", index: {} };
        assert(!removeFromIdIndex("nonexistent"), "should return false");
    });

    it("returns false when no index exists", function () {
        $.global.mcpIdIndex = null;
        assert(!removeFromIdIndex("any"), "null index");
    });

    it("returns false for null ID", function () {
        assert(!removeFromIdIndex(null));
        assert(!removeFromIdIndex(""));
    });
});

// ==================== heap.jsx Tests ====================

// Helper: reset heap state before each test group
function resetHeap() {
    $.global.mcpHeap = { index: {}, docName: null };
    // Reset _heapTxn by calling heapInvalidate
    heapInvalidate();
}

describe("heap — Transaction Lifecycle", function () {
    it("heapBeginTxn creates a transaction", function () {
        resetHeap();
        heapBeginTxn("batch-1");
        var diag = heapDiagnostics();
        assert(diag.hasTxn, "should have active txn");
        assertEqual(diag.txnBatchId, "batch-1");
    });

    it("heapCommitTxn clears the transaction", function () {
        resetHeap();
        heapBeginTxn("batch-2");
        var stats = heapCommitTxn();
        var diag = heapDiagnostics();
        assert(!diag.hasTxn, "txn should be cleared");
        assertEqual(stats.added, 0);
        assertEqual(stats.deleted, 0);
    });

    it("heapRollbackTxn clears the transaction", function () {
        resetHeap();
        heapBeginTxn("batch-3");
        var stats = heapRollbackTxn();
        assert(!heapDiagnostics().hasTxn, "txn should be cleared");
        assertEqual(stats.rolledBackAdds, 0);
    });
});

describe("heap — Registration", function () {
    it("heapRegister adds to index and txn.added", function () {
        resetHeap();
        heapBeginTxn("batch-4");
        var fakeItem = { note: "@mcp:id=abc123" };
        heapRegister("abc123", fakeItem);
        var diag = heapDiagnostics();
        assertEqual(diag.indexSize, 1);
        assertEqual(diag.txnAdded, 1);
    });

    it("heapRegister with null uuid is a no-op", function () {
        resetHeap();
        heapBeginTxn("batch-5");
        heapRegister(null, {});
        heapRegister("", {});
        assertEqual(heapDiagnostics().indexSize, 0);
    });

    it("commit preserves registered items", function () {
        resetHeap();
        heapBeginTxn("batch-6");
        heapRegister("id1", { note: "@mcp:id=id1" });
        heapRegister("id2", { note: "@mcp:id=id2" });
        var stats = heapCommitTxn();
        assertEqual(stats.added, 2);
        assertEqual(heapDiagnostics().indexSize, 2);
    });
});

describe("heap — Tombstoning", function () {
    it("heapTombstone removes from index", function () {
        resetHeap();
        $.global.mcpHeap.index["item1"] = { note: "@mcp:id=item1" };
        heapBeginTxn("batch-7");
        heapTombstone("item1");
        assertEqual(heapDiagnostics().indexSize, 0);
        assertEqual(heapDiagnostics().txnDeleted, 1);
    });

    it("commit finalizes tombstoned items", function () {
        resetHeap();
        $.global.mcpHeap.index["item2"] = { note: "@mcp:id=item2" };
        heapBeginTxn("batch-8");
        heapTombstone("item2");
        heapCommitTxn();
        assertEqual(heapDiagnostics().indexSize, 0);
    });
});

describe("heap — Rollback Semantics", function () {
    it("rollback removes items added during txn", function () {
        resetHeap();
        heapBeginTxn("batch-9");
        heapRegister("new1", { note: "@mcp:id=new1" });
        heapRegister("new2", { note: "@mcp:id=new2" });
        assertEqual(heapDiagnostics().indexSize, 2);
        var stats = heapRollbackTxn();
        assertEqual(stats.rolledBackAdds, 2);
        assertEqual(heapDiagnostics().indexSize, 0);
    });

    it("rollback restores items deleted during txn", function () {
        resetHeap();
        var orig = { note: "@mcp:id=existing" };
        $.global.mcpHeap.index["existing"] = orig;
        heapBeginTxn("batch-10");
        heapTombstone("existing");
        assertEqual(heapDiagnostics().indexSize, 0);
        var stats = heapRollbackTxn();
        assertEqual(stats.rolledBackDeletes, 1);
        assertEqual(heapDiagnostics().indexSize, 1);
    });

    it("rollback handles mixed adds and deletes", function () {
        resetHeap();
        $.global.mcpHeap.index["old1"] = { note: "@mcp:id=old1" };
        heapBeginTxn("batch-11");
        heapRegister("new3", { note: "@mcp:id=new3" });
        heapTombstone("old1");
        var stats = heapRollbackTxn();
        assertEqual(stats.rolledBackAdds, 1);
        assertEqual(stats.rolledBackDeletes, 1);
        // old1 restored, new3 removed
        assertEqual(heapDiagnostics().indexSize, 1);
    });
});

describe("heap — Resolution", function () {
    it("heapResolve returns item with matching identity", function () {
        resetHeap();
        var item = { note: "@mcp:id=res1" };
        $.global.mcpHeap.index["res1"] = item;
        heapBeginTxn("batch-12");
        var result = heapResolve("res1", null);
        assertEqual(result, item);
    });

    it("heapResolve returns null for tombstoned items", function () {
        resetHeap();
        $.global.mcpHeap.index["res2"] = { note: "@mcp:id=res2" };
        heapBeginTxn("batch-13");
        heapTombstone("res2");
        var result = heapResolve("res2", null);
        assertEqual(result, null);
    });

    it("heapResolve detects stale ref (identity mismatch)", function () {
        resetHeap();
        // Index says res3 but the item's note says something else
        $.global.mcpHeap.index["res3"] = { note: "@mcp:id=WRONG" };
        heapBeginTxn("batch-14");
        var result = heapResolve("res3", null);
        assertEqual(result, null, "stale ref should return null");
    });

    it("heapResolveMany returns items in order", function () {
        resetHeap();
        var a = { note: "@mcp:id=a" };
        var b = { note: "@mcp:id=b" };
        $.global.mcpHeap.index["a"] = a;
        $.global.mcpHeap.index["b"] = b;
        heapBeginTxn("batch-15");
        var results = heapResolveMany(null, ["a", "missing", "b"]);
        assertEqual(results.length, 2);
        assertEqual(results[0], a);
        assertEqual(results[1], b);
    });
});

describe("heap — Resync Guard", function () {
    it("resyncUsed starts false", function () {
        resetHeap();
        heapBeginTxn("batch-16");
        assertEqual(heapDiagnostics().txnResyncUsed, false);
    });
});

describe("heap — Invalidation", function () {
    it("heapInvalidate clears everything", function () {
        $.global.mcpHeap.index["x"] = {};
        heapBeginTxn("batch-17");
        heapInvalidate();
        assertEqual(heapDiagnostics().indexSize, 0);
        assertEqual(heapDiagnostics().hasTxn, false);
    });
});

// ==================== Summary ====================

console.log("\n" + "=".repeat(50));
if (_failed === 0) {
    console.log("\x1b[32m  All " + _passed + " tests passed\x1b[0m");
} else {
    console.log("\x1b[31m  " + _failed + " of " + (_passed + _failed) + " tests failed\x1b[0m");
    _errors.forEach(function (e) {
        console.log("    \x1b[31m✗\x1b[0m " + e.name + ": " + e.error);
    });
}
console.log("=".repeat(50) + "\n");

process.exit(_failed > 0 ? 1 : 0);
