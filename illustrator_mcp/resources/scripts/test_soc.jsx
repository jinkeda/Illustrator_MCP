/**
 * SOC Integration Test Harness
 * @version 1.0.0
 * 
 * Pure DOM property assertions — no pixel exports, no UI state.
 * Run via: includes: ["test_soc"] then call runSOCTests()
 * 
 * Dependencies: task_executor, ops_core, ops_layer, ops_element,
 *               ops_journal, session, geo_ir, generative
 */

// ==================== Test Framework ====================

function _socAssert(name, condition, detail) {
    return {
        name: name,
        pass: !!condition,
        detail: detail || (condition ? "ok" : "FAIL")
    };
}

// ==================== Test Suite ====================

function runSOCTests() {
    var doc = app.documents.add(DocumentColorSpace.RGB, 400, 400);
    var results = [];

    // --------------------------------------------------
    // Group 1: makeError contract
    // --------------------------------------------------
    (function () {
        var err = makeError("V007", "test message", "validate", null, { foo: 1 });
        results.push(_socAssert("makeError has ok:false",
            err.ok === false));
        results.push(_socAssert("makeError has nested error.code",
            err.error && err.error.code === "V007"));
        results.push(_socAssert("makeError has nested error.message",
            err.error && err.error.message === "test message"));
        results.push(_socAssert("makeError has nested error.stage",
            err.error && err.error.stage === "validate"));
        results.push(_socAssert("makeError has nested error.details",
            err.error && err.error.details && err.error.details.foo === 1));
    })();

    // --------------------------------------------------
    // Group 2: Handler error paths (batch executor)
    // --------------------------------------------------
    (function () {
        // Missing geometry → fail
        var r1 = executeOpBatch([
            { task: "element_create_multi", params: {} }
        ], { summaryOnly: true });
        results.push(_socAssert("missing param → batch fails",
            r1.ok === false && r1.stats.failed === 1));
        results.push(_socAssert("error has code field",
            r1.errors && r1.errors.length > 0 && r1.errors[0].error && r1.errors[0].error.code,
            r1.errors && r1.errors[0] ? JSON.stringify(r1.errors[0].error).substring(0, 80) : "no errors"));

        // Bad element type → fail
        var r2 = executeOpBatch([
            { task: "element_create", params: { type: "banana" } }
        ], { summaryOnly: true });
        results.push(_socAssert("bad element type → batch fails",
            r2.ok === false && r2.stats.failed === 1));

        // Stash miss → fail
        var r3 = executeOpBatch([
            { task: "element_create_multi_by_ref", params: { irKey: "nonexistent_key" } }
        ], { summaryOnly: true });
        results.push(_socAssert("stash miss → batch fails",
            r3.ok === false && r3.stats.failed === 1));
    })();

    // --------------------------------------------------
    // Group 3: Handler success paths
    // --------------------------------------------------
    (function () {
        var r4 = executeOpBatch([
            { task: "layer_create", params: { name: "TestLayerSOC" } }
        ], { summaryOnly: true });
        results.push(_socAssert("layer_create → ok:true",
            r4.ok === true && r4.stats.passed === 1));

        var r5 = executeOpBatch([
            { task: "element_create", params: { type: "rect", w: 100, h: 50, layer: "TestLayerSOC" } }
        ], { summaryOnly: true });
        results.push(_socAssert("element_create rect → ok + id",
            r5.ok === true && r5.createdIds && r5.createdIds.length >= 1));

        // Multi-create
        var ir = {
            ir: "multi",
            v: 1,
            paths: [
                { ir: "path", points: [[10, 10], [50, 10], [50, 50]], closed: false },
                { ir: "path", points: [[60, 10], [100, 10], [100, 50]], closed: false }
            ]
        };
        var r6 = executeOpBatch([
            { task: "element_create_multi", params: { geometry: ir, layer: "TestLayerSOC", stroke: { r: 0, g: 0, b: 0 } } }
        ], { summaryOnly: true });
        results.push(_socAssert("element_create_multi → ok + ids",
            r6.ok === true && r6.createdIds && r6.createdIds.length >= 2,
            "ids: " + (r6.createdIds ? r6.createdIds.length : 0)));
    })();

    // --------------------------------------------------
    // Group 4: Mixed batch (partial failure)
    // --------------------------------------------------
    (function () {
        var r7 = executeOpBatch([
            { task: "layer_create", params: { name: "MixedLayer" } },
            { task: "element_create_multi", params: {} }  // bad
        ], { summaryOnly: true });
        results.push(_socAssert("mixed batch → partial failure",
            r7.ok === false && r7.stats.passed === 1 && r7.stats.failed === 1));
    })();

    // --------------------------------------------------
    // Group 5: Multi-call / session stash
    // --------------------------------------------------
    (function () {
        var ir = {
            ir: "multi",
            v: 1,
            paths: [
                { ir: "path", points: [[0, 0], [10, 0], [10, 10]], closed: false },
                { ir: "path", points: [[20, 0], [30, 0], [30, 10]], closed: false },
                { ir: "path", points: [[40, 0], [50, 0], [50, 10]], closed: false }
            ]
        };

        // stashPutIR validates
        var putResult = stashPutIR("test_ir", ir);
        results.push(_socAssert("stashPutIR → ok",
            putResult && putResult.ok === true));

        // stashGet round-trip
        var got = stashGet("test_ir");
        results.push(_socAssert("stashGet round-trip → paths intact",
            got && got.paths && got.paths.length === 3));

        // stashInfo
        var info = stashInfo();
        var hasKey = false;
        for (var k in info) { if (k.indexOf("test_ir") >= 0) hasKey = true; }
        results.push(_socAssert("stashInfo → key present",
            hasKey));

        // by_ref: resolve from stash and create
        var r8 = executeOpBatch([
            { task: "layer_create", params: { name: "ByRefLayer" } },
            { task: "element_create_multi_by_ref", params: { irKey: "test_ir", layer: "ByRefLayer", stroke: { r: 0, g: 0, b: 0 } } }
        ], { summaryOnly: true });
        results.push(_socAssert("by_ref → creates from stash",
            r8.ok === true && r8.createdIds && r8.createdIds.length >= 3,
            "ids: " + (r8.createdIds ? r8.createdIds.length : 0)));

        // Cleanup
        stashClear("test_ir");
        results.push(_socAssert("stashClear → key removed",
            stashGet("test_ir") === null));
    })();

    // --------------------------------------------------
    // Group 6: Chunked creation (offset/limit)
    // --------------------------------------------------
    (function () {
        var ir = {
            ir: "multi",
            v: 1,
            paths: []
        };
        for (var i = 0; i < 10; i++) {
            ir.paths.push({ ir: "path", points: [[i * 15, 0], [i * 15 + 10, 0], [i * 15 + 10, 10]], closed: false });
        }

        // Chunk 1: offset=0, limit=4
        var r9 = executeOpBatch([
            { task: "layer_create", params: { name: "ChunkLayer" } },
            {
                task: "element_create_multi", params: {
                    geometry: ir, layer: "ChunkLayer", offset: 0, limit: 4,
                    stroke: { r: 100, g: 100, b: 100 }
                }
            }
        ], { summaryOnly: true });
        results.push(_socAssert("chunk 1 (0-3) → 4 created",
            r9.ok === true && r9.createdIds && r9.createdIds.length >= 4,
            "ids: " + (r9.createdIds ? r9.createdIds.length : 0)));

        // Chunk 2: offset=4, limit=4
        var r10 = executeOpBatch([
            {
                task: "element_create_multi", params: {
                    geometry: ir, layer: "ChunkLayer", offset: 4, limit: 4,
                    stroke: { r: 100, g: 100, b: 100 }
                }
            }
        ], { summaryOnly: true });
        results.push(_socAssert("chunk 2 (4-7) → 4 created",
            r10.ok === true && r10.createdIds && r10.createdIds.length >= 4,
            "ids: " + (r10.createdIds ? r10.createdIds.length : 0)));

        // Chunk 3: offset=8, limit=4 (only 2 remain)
        var r11 = executeOpBatch([
            {
                task: "element_create_multi", params: {
                    geometry: ir, layer: "ChunkLayer", offset: 8, limit: 4,
                    stroke: { r: 100, g: 100, b: 100 }
                }
            }
        ], { summaryOnly: true });
        results.push(_socAssert("chunk 3 (8-9) → 2 created (clamped)",
            r11.ok === true && r11.createdIds && r11.createdIds.length >= 2,
            "ids: " + (r11.createdIds ? r11.createdIds.length : 0)));
    })();

    // --------------------------------------------------
    // Group 7: Journal
    // --------------------------------------------------
    (function () {
        // Enable journal and run an op with generatorMeta
        if (typeof journalClear === "function") journalClear();

        var r12 = executeOpBatch([
            { task: "layer_create", params: { name: "JournalLayer" } }
        ], {
            journal: true,
            generatorMeta: {
                generator: "test_suite",
                version: "1.0.0",
                seed: 42,
                params: { testMode: true }
            }
        });

        // Read journal
        var entries = (typeof journalGet === "function") ? journalGet(doc.name) : [];
        var lastEntry = entries.length > 0 ? entries[entries.length - 1] : null;

        results.push(_socAssert("journal records entry",
            lastEntry !== null && lastEntry.batchId));
        results.push(_socAssert("journal has generatorMeta",
            lastEntry && lastEntry.generatorMeta && lastEntry.generatorMeta.generator === "test_suite",
            lastEntry ? JSON.stringify(lastEntry.generatorMeta).substring(0, 60) : "null"));
        results.push(_socAssert("journal has createdIds",
            lastEntry && lastEntry.createdIds && lastEntry.createdIds.length >= 0));
    })();

    // --------------------------------------------------
    // Group 8: stashPutIR validation rejects bad IR
    // --------------------------------------------------
    (function () {
        var badIR = { ir: "multi", v: 1, paths: "not_an_array" };
        var putBad = stashPutIR("bad_ir", badIR);
        results.push(_socAssert("stashPutIR rejects bad IR",
            putBad && putBad.ok === false));

        // Ensure it wasn't stashed
        results.push(_socAssert("bad IR not in stash",
            stashGet("bad_ir") === null));
    })();

    // ========== Group 9: New Features (cx/cy, assert_z_order, query selectors) ==========
    (function () {
        // 9a: Center positioning (cx/cy)
        var r1 = executeOpBatch([
            {
                task: 'element_create', params: {
                    id: 'cx_test', type: 'ellipse', cx: 200, cy: 200, w: 60, h: 60,
                    layer: 'TestLayerSOC', fill: { r: 100, g: 200, b: 100 }
                }
            }
        ]);
        results.push(_socAssert("cx/cy create ok", r1.ok));

        // Verify position: cx=200 means left = 200-30 = 170, cy=200 means top = -(200-30) = -170
        var cxItem = null;
        for (var i = 0; i < doc.layers.length; i++) {
            for (var j = 0; j < doc.layers[i].pageItems.length; j++) {
                if ((doc.layers[i].pageItems[j].note || "").indexOf("cx_test") >= 0) {
                    cxItem = doc.layers[i].pageItems[j];
                    break;
                }
            }
            if (cxItem) break;
        }
        results.push(_socAssert("cx/cy position correct",
            cxItem && Math.abs(cxItem.left - 170) < 2 && Math.abs(cxItem.top - (-170)) < 2));

        // 9b: noFill / noStroke booleans
        var r2 = executeOpBatch([
            {
                task: 'element_create', params: {
                    id: 'nofill_test', type: 'rect', x: 300, y: 300, w: 50, h: 50,
                    layer: 'TestLayerSOC', noFill: true, stroke: { r: 255, g: 0, b: 0 }, strokeWidth: 2
                }
            }
        ]);
        var nfItem = null;
        for (var i = 0; i < doc.layers.length; i++) {
            for (var j = 0; j < doc.layers[i].pageItems.length; j++) {
                if ((doc.layers[i].pageItems[j].note || "").indexOf("nofill_test") >= 0) {
                    nfItem = doc.layers[i].pageItems[j];
                    break;
                }
            }
            if (nfItem) break;
        }
        results.push(_socAssert("noFill boolean works",
            nfItem && nfItem.filled === false && nfItem.stroked === true));

        // 9c: assert_z_order
        var r3 = executeOpBatch([
            { task: 'element_create', params: { id: 'z_bottom', type: 'rect', x: 0, y: 0, w: 10, h: 10, layer: 'TestLayerSOC' } },
            { task: 'element_create', params: { id: 'z_top', type: 'rect', x: 0, y: 0, w: 10, h: 10, layer: 'TestLayerSOC' } },
            { task: 'assert_z_order', params: { above: 'z_top', below: 'z_bottom' } }
        ]);
        results.push(_socAssert("assert_z_order passes", r3.ok));

        // 9d: assert_z_order fails correctly on reversed order
        var r4 = executeOpBatch([
            { task: 'assert_z_order', params: { above: 'z_bottom', below: 'z_top' } }
        ]);
        results.push(_socAssert("assert_z_order detects reversal", !r4.ok));

        // 9e: Per-layer assert_count
        var r5 = executeOpBatch([
            { task: 'assert_count', params: { layer: 'TestLayerSOC', expected: 0, operator: 'gt' } }
        ]);
        results.push(_socAssert("per-layer assert_count works", r5.ok));

        // 9f: Query selector restyle
        var r6 = executeOpBatch([
            { task: 'element_create', params: { id: 'qsel_a', name: 'qtest_circle_a', type: 'ellipse', cx: 100, cy: 100, w: 20, h: 20, layer: 'TestLayerSOC', opacity: 50 } },
            { task: 'element_create', params: { id: 'qsel_b', name: 'qtest_circle_b', type: 'ellipse', cx: 140, cy: 100, w: 20, h: 20, layer: 'TestLayerSOC', opacity: 50 } }
        ]);
        // Now restyle via ID selector (query by namePattern not available in style ops, use id selector)
        var r7 = executeOpBatch([
            { task: 'style_set_opacity', targets: { type: 'id', ids: ['qsel_a', 'qsel_b'] }, params: { opacity: 85 } }
        ]);
        // Verify
        var qItem = null;
        for (var i = 0; i < doc.layers.length; i++) {
            for (var j = 0; j < doc.layers[i].pageItems.length; j++) {
                if ((doc.layers[i].pageItems[j].note || "").indexOf("qsel_a") >= 0) {
                    qItem = doc.layers[i].pageItems[j];
                    break;
                }
            }
            if (qItem) break;
        }
        results.push(_socAssert("target selector restyle works",
            qItem && Math.abs(qItem.opacity - 85) < 1));
    })();

    // === Summary ===
    doc.close(SaveOptions.DONOTSAVECHANGES);

    var passed = 0, failed = 0, failNames = [];
    for (var r = 0; r < results.length; r++) {
        if (results[r].pass) { passed++; } else { failed++; failNames.push(results[r].name); }
    }

    return {
        total: results.length,
        passed: passed,
        failed: failed,
        failedTests: failNames,
        allPass: failed === 0,
        results: results
    };
}
