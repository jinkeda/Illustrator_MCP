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

        // With artboard-relative coords (artboardTop=400 for 400pt artboard):
        // cx=200, cy=200 → left = cx - w/2 = 200 - 30 = 170, y = cy - h/2 = 170
        // aiLeft = 170, aiTop = 400 - 170 = 230
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
            cxItem && Math.abs(cxItem.left - 170) < 2 && Math.abs(cxItem.top - 230) < 2));

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

    // --------------------------------------------------
    // Group 10: C2 Guard — when.gt partial filtering
    // --------------------------------------------------
    (function () {
        var layerR = executeOpBatch([{ task: 'layer_create', params: { name: 'G10_WhenGt' } }]);
        var setup = executeOpBatch([
            { task: 'element_create', params: { id: 'g10_w80', type: 'rect', x: 10, y: 10, w: 80, h: 40, layer: 'G10_WhenGt' } },
            { task: 'element_create', params: { id: 'g10_w120', type: 'rect', x: 110, y: 10, w: 120, h: 40, layer: 'G10_WhenGt' } },
            { task: 'element_create', params: { id: 'g10_w200', type: 'rect', x: 250, y: 10, w: 200, h: 40, layer: 'G10_WhenGt' } }
        ], { strict: true });
        results.push(_socAssert("G10 setup ok", setup.ok));

        var fill = executeOpBatch([
            {
                task: 'style_set_fill',
                targets: { type: 'id', ids: ['g10_w80', 'g10_w120', 'g10_w200'] },
                params: { r: 255, g: 0, b: 0 },
                when: { property: 'width', gt: 100 }
            }
        ], { strict: true });
        results.push(_socAssert("G10 fill ok", fill.ok));
        results.push(_socAssert("G10 targets_resolved=2",
            fill.ops && fill.ops[0] && fill.ops[0].targets_resolved === 2,
            "targets_resolved=" + (fill.ops && fill.ops[0] ? fill.ops[0].targets_resolved : "?")));
    })();

    // --------------------------------------------------
    // Group 11: C2 Guard — all-filtered → skipped:true
    // --------------------------------------------------
    (function () {
        executeOpBatch([{ task: 'layer_create', params: { name: 'G11_AllFilter' } }]);
        var setup = executeOpBatch([
            { task: 'element_create', params: { id: 'g11_a', type: 'rect', x: 10, y: 60, w: 60, h: 30, layer: 'G11_AllFilter' } },
            { task: 'element_create', params: { id: 'g11_b', type: 'rect', x: 80, y: 60, w: 80, h: 30, layer: 'G11_AllFilter' } }
        ], { strict: true });
        results.push(_socAssert("G11 setup ok", setup.ok));

        var fill = executeOpBatch([
            {
                task: 'style_set_fill',
                targets: { type: 'id', ids: ['g11_a', 'g11_b'] },
                params: { r: 0, g: 255, b: 0 },
                when: { property: 'width', gt: 100 }
            }
        ]);
        results.push(_socAssert("G11 op ok with skipped",
            fill.ok && fill.ops && fill.ops[0] && fill.ops[0].skipped === true,
            fill.ops && fill.ops[0] ? "skipped=" + fill.ops[0].skipped : "no op"));
        results.push(_socAssert("G11 reason=guard_filtered",
            fill.ops && fill.ops[0] && fill.ops[0].data && fill.ops[0].data.reason === "guard_filtered"));
    })();

    // --------------------------------------------------
    // Group 12: C2 Guard — unless inversion
    // --------------------------------------------------
    (function () {
        executeOpBatch([{ task: 'layer_create', params: { name: 'G12_Unless' } }]);
        var setup = executeOpBatch([
            { task: 'element_create', params: { id: 'g12_keep', type: 'rect', x: 10, y: 100, w: 100, h: 30, name: 'KEEP', layer: 'G12_Unless' } },
            { task: 'element_create', params: { id: 'g12_delete', type: 'rect', x: 130, y: 100, w: 100, h: 30, name: 'DELETE', layer: 'G12_Unless' } }
        ], { strict: true });
        results.push(_socAssert("G12 setup ok", setup.ok));

        var fill = executeOpBatch([
            {
                task: 'style_set_fill',
                targets: { type: 'id', ids: ['g12_keep', 'g12_delete'] },
                params: { r: 255, g: 0, b: 0 },
                unless: { property: 'name', contains: 'KEEP' }
            }
        ]);
        results.push(_socAssert("G12 fill ok", fill.ok));
        results.push(_socAssert("G12 targets_resolved=1 (DELETE only)",
            fill.ops && fill.ops[0] && fill.ops[0].targets_resolved === 1,
            "targets_resolved=" + (fill.ops && fill.ops[0] ? fill.ops[0].targets_resolved : "?")));
    })();

    // --------------------------------------------------
    // Group 13: C2 Guard — typename guard
    // --------------------------------------------------
    (function () {
        executeOpBatch([{ task: 'layer_create', params: { name: 'G13_Typename' } }]);
        var setup = executeOpBatch([
            { task: 'element_create', params: { id: 'g13_rect', type: 'rect', x: 10, y: 140, w: 100, h: 30, layer: 'G13_Typename' } },
            { task: 'element_create', params: { id: 'g13_text', type: 'text', x: 130, y: 140, w: 100, h: 30, text: 'hello', layer: 'G13_Typename' } }
        ], { strict: true });
        results.push(_socAssert("G13 setup ok", setup.ok));

        var fill = executeOpBatch([
            {
                task: 'style_set_fill',
                targets: { type: 'id', ids: ['g13_rect', 'g13_text'] },
                params: { r: 0, g: 0, b: 255 },
                when: { property: 'typename', contains: 'PathItem' }
            }
        ]);
        results.push(_socAssert("G13 fill ok", fill.ok));
        results.push(_socAssert("G13 targets_resolved=1 (PathItem only)",
            fill.ops && fill.ops[0] && fill.ops[0].targets_resolved === 1,
            "targets_resolved=" + (fill.ops && fill.ops[0] ? fill.ops[0].targets_resolved : "?")));
    })();

    // --------------------------------------------------
    // Group 14: C2 Guard — unknown property → G001
    // --------------------------------------------------
    (function () {
        executeOpBatch([{ task: 'layer_create', params: { name: 'G14_G001' } }]);
        executeOpBatch([
            { task: 'element_create', params: { id: 'g14_a', type: 'rect', x: 10, y: 180, w: 80, h: 30, layer: 'G14_G001' } }
        ]);
        var r = executeOpBatch([
            {
                task: 'style_set_fill',
                targets: { type: 'id', ids: ['g14_a'] },
                params: { r: 255, g: 0, b: 0 },
                when: { property: 'definitelyNotAProp', eq: 1 }
            }
        ]);
        results.push(_socAssert("G14 op fails", r.ok === false));
        results.push(_socAssert("G14 error code G001",
            r.ops && r.ops[0] && r.ops[0].error && r.ops[0].error.code === "G001",
            r.ops && r.ops[0] && r.ops[0].error ? r.ops[0].error.code : "no error"));
    })();

    // --------------------------------------------------
    // Group 15: C2 Guard — invalid comparator usage → G002
    // 'contains' requires string value but 'width' is numeric → type mismatch
    // --------------------------------------------------
    (function () {
        executeOpBatch([{ task: 'layer_create', params: { name: 'G15_G002' } }]);
        executeOpBatch([
            { task: 'element_create', params: { id: 'g15_a', type: 'rect', x: 10, y: 220, w: 80, h: 30, layer: 'G15_G002' } }
        ]);
        var r = executeOpBatch([
            {
                task: 'style_set_fill',
                targets: { type: 'id', ids: ['g15_a'] },
                params: { r: 255, g: 0, b: 0 },
                when: { property: 'width', contains: 'hello' }
            }
        ]);
        results.push(_socAssert("G15 op fails", r.ok === false));
        results.push(_socAssert("G15 error code G002",
            r.ops && r.ops[0] && r.ops[0].error && r.ops[0].error.code === "G002",
            r.ops && r.ops[0] && r.ops[0].error ? r.ops[0].error.code : "no error"));
    })();

    // --------------------------------------------------
    // Group 16: C2 Guard — malformed guard → G003
    // --------------------------------------------------
    (function () {
        executeOpBatch([{ task: 'layer_create', params: { name: 'G16_G003' } }]);
        executeOpBatch([
            { task: 'element_create', params: { id: 'g16_a', type: 'rect', x: 10, y: 260, w: 80, h: 30, layer: 'G16_G003' } }
        ]);
        var r = executeOpBatch([
            {
                task: 'style_set_fill',
                targets: { type: 'id', ids: ['g16_a'] },
                params: { r: 255, g: 0, b: 0 },
                when: { gt: 100 }
            }
        ]);
        results.push(_socAssert("G16 op fails", r.ok === false));
        results.push(_socAssert("G16 error code G003",
            r.ops && r.ops[0] && r.ops[0].error && r.ops[0].error.code === "G003",
            r.ops && r.ops[0] && r.ops[0].error ? r.ops[0].error.code : "no error"));
    })();

    // --------------------------------------------------
    // Group 17: C3 Spatial — within selects inside region
    // Artboard is 400x400. Place 4 rects: 2 inside region, 2 outside.
    // User coords (y-down from top-left):
    //   sp_in1: (60,60) center=(70,70)   → INSIDE region
    //   sp_in2: (120,120) center=(130,130) → INSIDE region
    //   sp_out1: (200,60) center=(210,70)  → OUTSIDE (x>150)
    //   sp_out2: (10,10) center=(20,20)    → OUTSIDE (x<50)
    // Region in user coords: {x:50, y:50, width:100, height:90}
    // --------------------------------------------------
    (function () {
        executeOpBatch([{ task: 'layer_create', params: { name: 'G17_Within' } }]);
        var setup = executeOpBatch([
            { task: 'element_create', params: { id: 'sp_in1', type: 'rect', x: 60, y: 60, w: 20, h: 20, layer: 'G17_Within' } },
            { task: 'element_create', params: { id: 'sp_in2', type: 'rect', x: 120, y: 120, w: 20, h: 20, layer: 'G17_Within' } },
            { task: 'element_create', params: { id: 'sp_out1', type: 'rect', x: 200, y: 60, w: 20, h: 20, layer: 'G17_Within' } },
            { task: 'element_create', params: { id: 'sp_out2', type: 'rect', x: 10, y: 10, w: 20, h: 20, layer: 'G17_Within' } }
        ], { strict: true });
        results.push(_socAssert("G17 setup ok", setup.ok));

        var fill = executeOpBatch([
            {
                task: 'style_set_fill',
                targets: { type: 'spatial', within: { x: 50, y: 50, width: 100, height: 90 }, layer: 'G17_Within' },
                params: { r: 0, g: 255, b: 0 }
            }
        ]);
        results.push(_socAssert("G17 fill ok", fill.ok));
        results.push(_socAssert("G17 targets_resolved == 2 (inside region)",
            fill.ops && fill.ops[0] && fill.ops[0].targets_resolved === 2,
            "targets_resolved=" + (fill.ops && fill.ops[0] ? fill.ops[0].targets_resolved : "?")));
    })();

    // --------------------------------------------------
    // Group 18: C3 Spatial — outside complement
    // Same region as G17 — outside should select the other 2
    // --------------------------------------------------
    (function () {
        // Reuses items from G17 layer
        var fill = executeOpBatch([
            {
                task: 'style_set_fill',
                targets: { type: 'spatial', outside: { x: 50, y: 50, width: 100, height: 90 }, layer: 'G17_Within' },
                params: { r: 255, g: 0, b: 0 }
            }
        ]);
        results.push(_socAssert("G18 fill ok", fill.ok));
        results.push(_socAssert("G18 targets_resolved == 2 (outside items)",
            fill.ops && fill.ops[0] && fill.ops[0].targets_resolved === 2,
            "targets_resolved=" + (fill.ops && fill.ops[0] ? fill.ops[0].targets_resolved : "?")));
    })();
    // Cleanup G17/G18
    try { doc.layers.getByName('G17_Within').remove(); } catch (e) { }
    doc.selection = null;

    // --------------------------------------------------
    // Group 19: C3 Spatial — nearTo selects by radius
    // --------------------------------------------------
    (function () {
        executeOpBatch([{ task: 'layer_create', params: { name: 'G19_NearTo' } }]);
        // Reference rect at (50, 300), w=20, h=20 → center = (60, -310)
        // Close rect at (80, 300), w=20, h=20 → center = (90, -310), dist = 30
        // Close rect at (50, 270), w=20, h=20 → center = (60, -280), dist = 30
        // Far rect at (200, 300), w=20, h=20 → center = (210, -310), dist = 150
        var setup = executeOpBatch([
            { task: 'element_create', params: { id: 'g19_ref', type: 'rect', x: 50, y: 300, w: 20, h: 20, layer: 'G19_NearTo' } },
            { task: 'element_create', params: { id: 'g19_close1', type: 'rect', x: 80, y: 300, w: 20, h: 20, layer: 'G19_NearTo' } },
            { task: 'element_create', params: { id: 'g19_close2', type: 'rect', x: 50, y: 270, w: 20, h: 20, layer: 'G19_NearTo' } },
            { task: 'element_create', params: { id: 'g19_far', type: 'rect', x: 200, y: 300, w: 20, h: 20, layer: 'G19_NearTo' } }
        ], { strict: true });
        results.push(_socAssert("G19 setup ok", setup.ok));

        var fill = executeOpBatch([
            {
                task: 'style_set_fill',
                targets: { type: 'spatial', nearTo: { id: 'g19_ref', radius: 50 }, layer: 'G19_NearTo' },
                params: { r: 0, g: 0, b: 255 }
            }
        ]);
        results.push(_socAssert("G19 fill ok", fill.ok));
        results.push(_socAssert("G19 targets_resolved == 2 (close items)",
            fill.ops && fill.ops[0] && fill.ops[0].targets_resolved === 2,
            "targets_resolved=" + (fill.ops && fill.ops[0] ? fill.ops[0].targets_resolved : "?")));
    })();
    // Cleanup G19
    try { doc.layers.getByName('G19_NearTo').remove(); } catch (e) { }
    doc.selection = null;

    // --------------------------------------------------
    // Group 20: C3 Spatial — nearTo ref not found → SP03
    // --------------------------------------------------
    (function () {
        try {
            var r = executeOpBatch([
                {
                    task: 'style_set_fill',
                    targets: { type: 'spatial', nearTo: { id: 'nonexistent_xyz', radius: 50 } },
                    params: { r: 255, g: 0, b: 0 }
                }
            ]);
            // If returned (not thrown), check error code in result
            results.push(_socAssert("G20 fails with SP03",
                !r.ok && JSON.stringify(r).indexOf("SP03") >= 0,
                r.ok ? "unexpected ok" : JSON.stringify(r.ops && r.ops[0] && r.ops[0].error).substring(0, 100)));
        } catch (e) {
            results.push(_socAssert("G20 throws SP03",
                e.code === "SP03",
                "code=" + e.code + " msg=" + (e.message || "").substring(0, 60)));
        }
    })();

    // --------------------------------------------------
    // Group 21: C3 Spatial — missing predicate → SP01
    // --------------------------------------------------
    (function () {
        try {
            var r = executeOpBatch([
                {
                    task: 'style_set_fill',
                    targets: { type: 'spatial' },
                    params: { r: 255, g: 0, b: 0 }
                }
            ]);
            results.push(_socAssert("G21 fails with SP01",
                !r.ok && JSON.stringify(r).indexOf("SP01") >= 0,
                r.ok ? "unexpected ok" : JSON.stringify(r.ops && r.ops[0] && r.ops[0].error).substring(0, 100)));
        } catch (e) {
            results.push(_socAssert("G21 throws SP01",
                e.code === "SP01",
                "code=" + e.code + " msg=" + (e.message || "").substring(0, 60)));
        }
    })();

    // --------------------------------------------------
    // Group 22: C3 Spatial — invalid rect → SP02
    // --------------------------------------------------
    (function () {
        try {
            var r = executeOpBatch([
                {
                    task: 'style_set_fill',
                    targets: { type: 'spatial', within: { x: 0, y: 0, width: 200 } },
                    params: { r: 255, g: 0, b: 0 }
                }
            ]);
            results.push(_socAssert("G22 fails with SP02",
                !r.ok && JSON.stringify(r).indexOf("SP02") >= 0,
                r.ok ? "unexpected ok" : JSON.stringify(r.ops && r.ops[0] && r.ops[0].error).substring(0, 100)));
        } catch (e) {
            // normalizeRect returns SP02 code, preserved by throwStructured
            results.push(_socAssert("G22 throws SP02",
                e.code === "SP02",
                "code=" + e.code + " msg=" + (e.message || "").substring(0, 60)));
        }
    })();

    // --------------------------------------------------
    // Group 23: Combined C2+C3 — spatial within + when guard
    // Place 4 rects in region, 2 wide (w=150), 2 narrow (w=50).
    // within selects all 4, then when.gt:100 keeps only the 2 wide ones.
    // --------------------------------------------------
    (function () {
        executeOpBatch([{ task: 'layer_create', params: { name: 'G23_Combined' } }]);
        var setup = executeOpBatch([
            { task: 'element_create', params: { id: 'g23_wide1', type: 'rect', x: 60, y: 60, w: 150, h: 20, layer: 'G23_Combined' } },
            { task: 'element_create', params: { id: 'g23_wide2', type: 'rect', x: 60, y: 90, w: 150, h: 20, layer: 'G23_Combined' } },
            { task: 'element_create', params: { id: 'g23_narrow1', type: 'rect', x: 60, y: 120, w: 50, h: 20, layer: 'G23_Combined' } },
            { task: 'element_create', params: { id: 'g23_narrow2', type: 'rect', x: 60, y: 140, w: 50, h: 20, layer: 'G23_Combined' } }
        ], { strict: true });
        results.push(_socAssert("G23 setup ok", setup.ok));

        // Spatial region covering all 4 items in user coords.
        // Items at user y=60..140, x=60. Centers: (135,70), (135,100), (85,130), (85,150)
        // Region: {x:50, y:50, width:200, height:110}
        var fill = executeOpBatch([
            {
                task: 'style_set_fill',
                targets: { type: 'spatial', within: { x: 50, y: 50, width: 200, height: 110 }, layer: 'G23_Combined' },
                params: { r: 255, g: 128, b: 0 },
                when: { property: 'width', gt: 100 }
            }
        ]);
        results.push(_socAssert("G23 fill ok", fill.ok));
        results.push(_socAssert("G23 targets_resolved=2 (wide only)",
            fill.ops && fill.ops[0] && fill.ops[0].targets_resolved === 2,
            "targets_resolved=" + (fill.ops && fill.ops[0] ? fill.ops[0].targets_resolved : "?")));
    })();
    // Cleanup G23
    try { doc.layers.getByName('G23_Combined').remove(); } catch (e) { }
    doc.selection = null;

    // --------------------------------------------------
    // Group 24: Combined C2+C3 — spatial within + unless guard
    // 3 rects in region, 1 named PROTECT → unless:contains:'PROTECT' keeps 2
    // --------------------------------------------------
    (function () {
        executeOpBatch([{ task: 'layer_create', params: { name: 'G24_SpatialUnless' } }]);
        var setup = executeOpBatch([
            { task: 'element_create', params: { id: 'g24_a', type: 'rect', x: 60, y: 200, w: 80, h: 20, name: 'A', layer: 'G24_SpatialUnless' } },
            { task: 'element_create', params: { id: 'g24_b', type: 'rect', x: 60, y: 230, w: 80, h: 20, name: 'B', layer: 'G24_SpatialUnless' } },
            { task: 'element_create', params: { id: 'g24_protect', type: 'rect', x: 60, y: 260, w: 80, h: 20, name: 'PROTECT', layer: 'G24_SpatialUnless' } }
        ], { strict: true });
        results.push(_socAssert("G24 setup ok", setup.ok));

        // Region covers all 3 in user coords.
        // Items at user y=200..260, x=60. Centers: (100,210), (100,240), (100,270)
        // Region: {x:50, y:195, width:150, height:85}
        var fill = executeOpBatch([
            {
                task: 'style_set_fill',
                targets: { type: 'spatial', within: { x: 50, y: 195, width: 150, height: 85 }, layer: 'G24_SpatialUnless' },
                params: { r: 128, g: 0, b: 255 },
                unless: { property: 'name', contains: 'PROTECT' }
            }
        ]);
        results.push(_socAssert("G24 fill ok", fill.ok));
        results.push(_socAssert("G24 targets_resolved == 2 (A and B, not PROTECT)",
            fill.ops && fill.ops[0] && fill.ops[0].targets_resolved === 2,
            "targets_resolved=" + (fill.ops && fill.ops[0] ? fill.ops[0].targets_resolved : "?")));
    })();
    // Cleanup G24
    try { doc.layers.getByName('G24_SpatialUnless').remove(); } catch (e) { }
    doc.selection = null;

    // --------------------------------------------------
    // Group 25: Soak test — 100 items + repeated guard ops
    // --------------------------------------------------
    (function () {
        executeOpBatch([{ task: 'layer_create', params: { name: 'G25_Soak' } }]);
        // Create 100 rects in a 10x10 grid, widths alternate between 60 and 140
        var createOps = [];
        for (var si = 0; si < 100; si++) {
            var col = si % 10;
            var row = Math.floor(si / 10);
            var w = (si % 2 === 0) ? 60 : 140;
            createOps.push({
                task: 'element_create',
                params: {
                    id: 'soak_' + si,
                    type: 'rect',
                    x: 10 + col * 40,
                    y: 10 + row * 40,
                    w: w,
                    h: 10,
                    layer: 'G25_Soak'
                }
            });
        }
        var setupR = executeOpBatch(createOps, { summaryOnly: true });
        results.push(_socAssert("G25 100-item setup ok",
            setupR.ok && setupR.stats.passed === 100,
            "passed=" + (setupR.stats ? setupR.stats.passed : "?")));

        // Run 10 guard ops targeting all 100 items
        var allIds = [];
        for (var sj = 0; sj < 100; sj++) allIds.push('soak_' + sj);

        var guardOps = [];
        for (var gk = 0; gk < 10; gk++) {
            guardOps.push({
                task: 'style_set_opacity',
                targets: { type: 'id', ids: allIds },
                params: { opacity: 90 + gk },
                when: { property: 'width', gt: 100 }
            });
        }
        var guardR = executeOpBatch(guardOps, { summaryOnly: true });
        results.push(_socAssert("G25 10 guard ops ok",
            guardR.ok && guardR.stats.failed === 0,
            "passed=" + (guardR.stats ? guardR.stats.passed : "?") + ",failed=" + (guardR.stats ? guardR.stats.failed : "?")));
    })();
    // Cleanup G25
    try { doc.layers.getByName('G25_Soak').remove(); } catch (e) { }
    doc.selection = null;

    // --------------------------------------------------
    // Group 26: Spatial within + nearTo — OR union semantics
    // Place 4 rects: 2 inside a within rect, 1 near a reference, 1 outside both.
    // Combined spatial should return the OR-union of both predicates.
    // --------------------------------------------------
    (function () {
        executeOpBatch([{ task: 'layer_create', params: { name: 'G26_Union' } }]);
        var setup = executeOpBatch([
            { task: 'element_create', params: { id: 'g26_inside1', type: 'rect', x: 50, y: 50, w: 10, h: 10, layer: 'G26_Union' } },
            { task: 'element_create', params: { id: 'g26_inside2', type: 'rect', x: 80, y: 50, w: 10, h: 10, layer: 'G26_Union' } },
            { task: 'element_create', params: { id: 'g26_near', type: 'rect', x: 300, y: 300, w: 10, h: 10, layer: 'G26_Union' } },
            { task: 'element_create', params: { id: 'g26_far', type: 'rect', x: 500, y: 500, w: 10, h: 10, layer: 'G26_Union' } }
        ], { strict: true });
        results.push(_socAssert("G26 setup ok", setup.ok));

        // within rect covers (40..110, 40..70) — should match g26_inside1, g26_inside2
        var withinFill = executeOpBatch([
            {
                task: 'style_set_fill',
                targets: { type: 'spatial', within: { x: 40, y: 40, width: 70, height: 30 }, layer: 'G26_Union' },
                params: { r: 0, g: 255, b: 0 }
            }
        ]);
        results.push(_socAssert("G26 within targets 2",
            withinFill.ok && withinFill.ops && withinFill.ops[0] && withinFill.ops[0].targets_resolved === 2,
            "resolved=" + (withinFill.ops && withinFill.ops[0] ? withinFill.ops[0].targets_resolved : "?")));
    })();
    // Cleanup G26
    try { doc.layers.getByName('G26_Union').remove(); } catch (e) { }
    doc.selection = null;

    // --------------------------------------------------
    // Group 27: Bad nearTo ID — confirm .code survives through MCP
    // --------------------------------------------------
    (function () {
        try {
            var r = executeOpBatch([
                {
                    task: 'style_set_fill',
                    targets: { type: 'spatial', nearTo: { id: 'g27_does_not_exist', radius: 100 } },
                    params: { r: 255, g: 0, b: 0 }
                }
            ]);
            // If error was caught internally, check code in result
            var errStr = JSON.stringify(r);
            results.push(_socAssert("G27 bad nearTo returns SP03",
                !r.ok && errStr.indexOf("SP03") >= 0,
                r.ok ? "unexpected ok" : errStr.substring(0, 120)));
        } catch (e) {
            results.push(_socAssert("G27 bad nearTo throws SP03",
                e.code === "SP03",
                "code=" + e.code + " msg=" + (e.message || "").substring(0, 60)));
        }
    })();

    // --------------------------------------------------
    // Group 28: Template instancing — ellipse scatter
    // --------------------------------------------------
    (function () {
        executeOpBatch([{ task: 'layer_create', params: { name: 'G28_Template' } }]);
        var r = executeOpBatch([
            {
                task: 'element_create_batch',
                params: {
                    template: { type: 'ellipse', r: 5, fill: { r: 255, g: 100, b: 0 }, stroke: false },
                    instances: [
                        { x: 50, y: 50 },
                        { x: 100, y: 80, fill: { r: 0, g: 200, b: 100 } },
                        { x: 150, y: 120, scale: 200 },
                        { x: 200, y: 160, opacity: 50 },
                        { x: 250, y: 200 }
                    ],
                    layer: 'G28_Template',
                    name: 'dot'
                }
            }
        ]);
        var data = r.ops && r.ops[0] && r.ops[0].data;
        results.push(_socAssert("G28 template ok", r.ok));
        results.push(_socAssert("G28 created=5",
            data && data.created === 5,
            "created=" + (data ? data.created : "?")));
        results.push(_socAssert("G28 ids.length=5",
            data && data.ids && data.ids.length === 5,
            "ids=" + (data && data.ids ? data.ids.length : "?")));
        results.push(_socAssert("G28 mode=template",
            data && data.mode === "template"));

        // Verify items exist on canvas
        var found = 0;
        for (var i = 0; i < doc.layers.length; i++) {
            if (doc.layers[i].name !== 'G28_Template') continue;
            for (var j = 0; j < doc.layers[i].pageItems.length; j++) {
                if ((doc.layers[i].pageItems[j].name || "").indexOf("dot_") >= 0) found++;
            }
        }
        results.push(_socAssert("G28 5 items on canvas",
            found === 5, "found=" + found));
    })();
    // Cleanup G28
    try { doc.layers.getByName('G28_Template').remove(); } catch (e) { }
    doc.selection = null;

    // --------------------------------------------------
    // Group 29: Template instancing — mutual exclusion guard
    // --------------------------------------------------
    (function () {
        var r = executeOpBatch([
            {
                task: 'element_create_batch',
                params: {
                    template: { type: 'ellipse', r: 5 },
                    items: [{ type: 'rect', x: 0, y: 0, w: 10, h: 10 }],
                    instances: [{ x: 10, y: 10 }]
                }
            }
        ]);
        results.push(_socAssert("G29 template+items → fails",
            r.ok === false));
        var errStr = JSON.stringify(r);
        results.push(_socAssert("G29 error mentions both",
            errStr.indexOf("template") >= 0 && errStr.indexOf("items") >= 0,
            errStr.substring(0, 100)));
    })();

    // --------------------------------------------------
    // Group 30: Template instancing — missing instances → fails
    // --------------------------------------------------
    (function () {
        var r = executeOpBatch([
            {
                task: 'element_create_batch',
                params: {
                    template: { type: 'ellipse', r: 5 }
                }
            }
        ]);
        results.push(_socAssert("G30 template no instances → fails",
            r.ok === false));
        var errStr = JSON.stringify(r);
        results.push(_socAssert("G30 error mentions instances",
            errStr.indexOf("instances") >= 0,
            errStr.substring(0, 100)));
    })();

    // ── G31: Invalid template type → V_INVALID_PARAM_TYPE ──
    (function () {
        var r = executeOpBatch([
            {
                task: 'element_create_batch',
                params: {
                    template: { type: 'banana', r: 5 },
                    instances: [{ x: 0, y: 0 }]
                }
            }
        ]);
        results.push(_socAssert("G31 invalid template type → fails",
            r.ok === false));
        var errStr = JSON.stringify(r);
        results.push(_socAssert("G31 error mentions valid types",
            errStr.indexOf("Valid types") >= 0,
            errStr.substring(0, 120)));
        results.push(_socAssert("G31 error code is V007",
            errStr.indexOf("V007") >= 0));
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
