"""
Script templates for Adobe Illustrator ExtendScript.

This module centralizes JavaScript/ExtendScript templates used by tool implementations.
Templates use Python's string.Template for variable substitution (${var}).

Benefits:
- Scripts are easier to read and test in isolation
- Clear separation of Python and JavaScript code
- Syntax highlighting works correctly in editors
"""

from string import Template


# ==================== Document Operations ====================

CREATE_DOCUMENT = Template("""
(function() {
    try {
        var preset = new DocumentPreset();
        preset.width = ${width};
        preset.height = ${height};
        preset.colorMode = DocumentColorSpace.${color_space};
        preset.units = RulerUnits.Points;
        ${title_line}

        var doc = app.documents.addDocument(DocumentColorSpace.${color_space}, preset);

        // FIX: Reposition artboard so top is at Y=0 (standard scripting convention)
        // By default, Illustrator places artboard at [0, height, width, 0]
        // We reposition to [0, 0, width, -height] so:
        //   - Artboard top is at Y=0
        //   - Artboard bottom is at Y=-height
        //   - Items placed with position [x, -y] appear correctly
        var ab = doc.artboards[0];
        var w = ${width};
        var h = ${height};
        ab.artboardRect = [0, 0, w, -h];

        return JSON.stringify({
            ok: true,
            data: {
                name: doc.name,
                width: doc.width,
                height: doc.height,
                artboardRect: ab.artboardRect
            },
            operation: "create_document"
        });
    } catch (e) {
        return JSON.stringify({
            ok: false,
            error: { message: e.message || String(e), line: e.line || null, operation: "create_document" }
        });
    }
})()
""")


OPEN_DOCUMENT = Template("""
(function() {
    try {
        var file = new File("${path}");
        if (!file.exists) {
            return JSON.stringify({
                ok: false,
                error: { message: "File not found: ${path}", line: null, operation: "open_document" }
            });
        }
        var doc = app.open(file);
        return JSON.stringify({
            ok: true,
            data: { name: doc.name, path: "${path}" },
            operation: "open_document"
        });
    } catch (e) {
        return JSON.stringify({
            ok: false,
            error: { message: e.message || String(e), line: e.line || null, operation: "open_document" }
        });
    }
})()
""")


SAVE_DOCUMENT = Template("""
(function() {
    try {
        var doc = app.activeDocument;
        var file = new File("${path}");
        doc.saveAs(file);
        return JSON.stringify({ ok: true, data: { path: "${path}" }, operation: "save_document" });
    } catch (e) {
        return JSON.stringify({ ok: false, error: { message: e.message || String(e), line: e.line || null, operation: "save_document" } });
    }
})()
""")


SAVE_DOCUMENT_SIMPLE = """
(function() {
    try {
        var doc = app.activeDocument;
        doc.save();
        return JSON.stringify({ ok: true, data: { message: "Document saved" }, operation: "save_document" });
    } catch (e) {
        return JSON.stringify({ ok: false, error: { message: e.message || String(e), line: e.line || null, operation: "save_document" } });
    }
})()
"""


CLOSE_DOCUMENT = Template("""
(function() {
    var doc = app.activeDocument;
    doc.close(${save_option});
    return JSON.stringify({ ok: true, data: { message: "Document closed" }, operation: "close_document" });
})()
""")


# ==================== Export Templates ====================

EXPORT_FILE = Template("""
(function() {
    var doc = app.activeDocument;
    var file = new File("${path}");
    var opts = new ${options_class}();${scale_opts}
    doc.exportFile(file, ${export_type}, opts);
    return JSON.stringify({ ok: true, data: { path: "${path}", format: "${format_name}" }, operation: "export_file" });
})()
""")


EXPORT_PDF = Template("""
(function() {
    var doc = app.activeDocument;
    var file = new File("${path}");
    var opts = new PDFSaveOptions();
    doc.saveAs(file, opts);
    var abIdx = doc.artboards.getActiveArtboardIndex();
    var abRect = doc.artboards[abIdx].artboardRect;
    return JSON.stringify({
        ok: true,
        data: {
            path: "${path}",
            format: "PDF",
            width_pt: abRect[2] - abRect[0],
            height_pt: Math.abs(abRect[3] - abRect[1])
        },
        operation: "export_pdf"
    });
})()
""")


# ==================== Document Info ====================

GET_DOCUMENT_INFO = """
(function() {
    if (app.documents.length === 0) {
        throw new Error("No document is open");
    }
    var doc = app.activeDocument;
    return JSON.stringify({
        name: doc.name,
        width: doc.width,
        height: doc.height,
        colorMode: doc.documentColorSpace == DocumentColorSpace.CMYK ? "CMYK" : "RGB",
        layerCount: doc.layers.length,
        saved: doc.saved
    });
})()
"""


GET_APP_INFO = """
(function() {
    var result = {
        name: app.name,
        version: app.version,
        locale: app.locale,
        documentsOpen: app.documents.length,
        activeDocumentName: app.documents.length > 0 ? app.activeDocument.name : null,
        freeMemory: app.freeMemory,
        scriptingVersion: app.scriptingVersion
    };
    return JSON.stringify(result);
})()
"""


# ==================== Context/Inspection ====================

GET_DOCUMENT_STRUCTURE = Template("""
(function() {
    var doc = app.activeDocument;
    var maxItems = ${max_items};
    var maxLayers = ${max_layers};
    var itemOffset = ${offset};
    var layerFilter = ${layer_filter};
    
    function _q(v){return(typeof v==="number")?Math.round(v*100)/100:v;}
    
    function getItemInfo(item, maxDepth, currentDepth) {
        if (currentDepth > maxDepth) return null;
        
        var info = {
            name: item.name || "(unnamed)",
            type: item.typename,
            position: item.position ? [_q(item.position[0]), _q(item.position[1])] : null,
            bounds: item.geometricBounds ? {
                left: _q(item.geometricBounds[0]),
                top: _q(item.geometricBounds[1]),
                right: _q(item.geometricBounds[2]),
                bottom: _q(item.geometricBounds[3])
            } : null
        };
        
        if (item.typename === "PathItem") {
            info.filled = item.filled;
            info.stroked = item.stroked;
        }
        
        if (item.typename === "TextFrame") {
            info.contents = item.contents.substring(0, 50);
        }
        
        return info;
    }
    
    function getLayerInfo(layer, maxI, off) {
        var total = layer.pageItems.length;
        var layerInfo = {
            name: layer.name,
            visible: layer.visible,
            locked: layer.locked,
            itemCount: total,
            items: [],
            offset: off,
            nextOffset: null
        };
        
        var end = Math.min(total, off + maxI);
        for (var i = off; i < end; i++) {
            var itemInfo = getItemInfo(layer.pageItems[i], 2, 0);
            if (itemInfo) layerInfo.items.push(itemInfo);
        }
        
        if (end < total) {
            layerInfo.truncated = true;
            layerInfo.totalItems = total;
            layerInfo.nextOffset = end;
        }
        
        layerInfo.sublayers = [];
        for (var j = 0; j < layer.layers.length; j++) {
            layerInfo.sublayers.push({
                name: layer.layers[j].name,
                visible: layer.layers[j].visible,
                locked: layer.layers[j].locked
            });
        }
        
        return layerInfo;
    }
    
    var result = {
        document: {
            name: doc.name,
            width: doc.width,
            height: doc.height,
            colorMode: doc.documentColorSpace.toString(),
            saved: doc.saved,
            layerCount: doc.layers.length,
            artboardCount: doc.artboards.length,
            artboards: []
        },
        layers: []
    };
    
    for (var a = 0; a < doc.artboards.length; a++) {
        var ab = doc.artboards[a];
        result.document.artboards.push({
            name: ab.name,
            bounds: ab.artboardRect
        });
    }
    
    // Layer filter: single layer by name or index
    if (layerFilter !== null) {
        var targetLayer = null;
        if (typeof layerFilter === "number") {
            if (layerFilter >= 0 && layerFilter < doc.layers.length) {
                targetLayer = doc.layers[layerFilter];
            }
        } else if (typeof layerFilter === "string") {
            for (var li = 0; li < doc.layers.length; li++) {
                if (doc.layers[li].name === layerFilter) {
                    targetLayer = doc.layers[li];
                    break;
                }
            }
        }
        if (targetLayer) {
            result.layers.push(getLayerInfo(targetLayer, maxItems, itemOffset));
        }
    } else {
        // All layers (no offset applied — offset is per-layer paging only)
        var layerLimit = Math.min(doc.layers.length, maxLayers);
        for (var i = 0; i < layerLimit; i++) {
            result.layers.push(getLayerInfo(doc.layers[i], maxItems, 0));
        }
        if (doc.layers.length > maxLayers) {
            result.layersTruncated = true;
            result.totalLayers = doc.layers.length;
        }
    }
    
    return JSON.stringify(result);
})()
""")



GET_SELECTION_INFO = """
(function() {
    var doc = app.activeDocument;
    var sel = doc.selection;
    
    if (!sel || sel.length === 0) {
        return JSON.stringify({
            selected: false,
            count: 0,
            items: []
        });
    }
    
    var items = [];
    var limit = Math.min(sel.length, 50);
    
    function _q(v){return(typeof v==="number")?Math.round(v*100)/100:v;}
    
    for (var i = 0; i < limit; i++) {
        var item = sel[i];
        var info = {
            name: item.name || "(unnamed)",
            type: item.typename,
            position: item.position ? [_q(item.position[0]), _q(item.position[1])] : null,
            bounds: item.geometricBounds ? {
                left: _q(item.geometricBounds[0]),
                top: _q(item.geometricBounds[1]),
                right: _q(item.geometricBounds[2]),
                bottom: _q(item.geometricBounds[3])
            } : null
        };
        
        if (item.typename === "PathItem") {
            info.filled = item.filled;
            info.stroked = item.stroked;
            if (item.filled && item.fillColor) {
                info.fillType = item.fillColor.typename;
            }
        }
        
        if (item.typename === "TextFrame") {
            info.contents = item.contents.substring(0, 100);
        }
        
        items.push(info);
    }
    
    return JSON.stringify({
        selected: true,
        count: sel.length,
        items: items,
        truncated: sel.length > 50
    });
})()
"""


# ==================== Import/Place ====================

# Single template for both import_image and place_file (they're 95% identical)
PLACE_ITEM = Template("""
(function() {
    var doc = app.activeDocument;
    var file = new File("${path}");
    if (!file.exists) {
        throw new Error("${error_prefix} not found: ${path}");
    }
    var placed = doc.placedItems.add();
    placed.file = file;
    placed.left = ${x};
    placed.top = ${neg_y};
    ${embed_line}
    ${marker_line}
    return JSON.stringify({
        ok: true,
        data: {
            path: "${path}",
            linked: ${linked},
            position: {x: ${x}, y: ${y}},
            width: placed.width,
            height: placed.height
        },
        operation: "place_item"
    });
})()
""")  


# Image Trace: vectorize a placed raster image
# Finds target by UUID marker (not fragile index), retries expandTracing() directly.
TRACE_PLACED_IMAGE = Template("""
(function() {
    var doc = app.activeDocument;
    var marker = "${marker}";
    var warnings = [];

    // 1. Find target by marker — narrow collections first
    var target = null;
    var collections = [doc.placedItems, doc.rasterItems];
    for (var c = 0; c < collections.length && !target; c++) {
        for (var i = 0; i < collections[c].length; i++) {
            __mcp_check();
            if (collections[c][i].note && collections[c][i].note.indexOf(marker) >= 0) {
                target = collections[c][i];
                break;
            }
        }
    }
    // Fallback: full pageItems scan
    if (!target) {
        for (var i = 0; i < doc.pageItems.length; i++) {
            __mcp_check();
            if (doc.pageItems[i].note && doc.pageItems[i].note.indexOf(marker) >= 0) {
                target = doc.pageItems[i];
                break;
            }
        }
    }
    if (!target) {
        return JSON.stringify({
            ok: false, error: "Trace target not found (marker: " + marker + ")"
        });
    }

    // 2. Type guard
    var tn = target.typename;
    if (tn !== "PlacedItem" && tn !== "RasterItem") {
        return JSON.stringify({
            ok: false, error: "Item not traceable: typename=" + tn
        });
    }

    // 3. Trace
    doc.selection = null;
    target.selected = true;
    var plugin = target.trace();

    // 4. Apply preset (safe fallback on locale/version mismatch)
    var presetName = ${preset};
    if (presetName) {
        try {
            plugin.tracing.tracingOptions.loadFromPreset(presetName);
        } catch(pe) {
            warnings.push("Preset not found: " + presetName + "; using default");
        }
    }

    var result = {
        trace_marker: marker,
        target_typename: tn,
        preset: presetName || "(default)",
        warnings: warnings
    };

    // 5. Expand with retry-around-expand (direct operation test)
    if (${expand}) {
        app.redraw();
        var group = null;
        var maxRetries = 20;
        for (var r = 0; r < maxRetries; r++) {
            __mcp_check();
            try {
                group = plugin.tracing.expandTracing();
                break;
            } catch(ex) {
                $$.sleep(500);
                app.redraw();
            }
        }
        if (!group) {
            return JSON.stringify({
                ok: false,
                error: "expandTracing() failed after " + maxRetries + " retries",
                warnings: warnings
            });
        }

        // Tag with MCP ID (trace: namespace)
        var mcpId = "trace:" + marker.replace("@mcp:trace_target=", "");
        group.note = "@mcp:id=" + mcpId;
        group.name = "traced_group";

        result.type = "traced_expanded";
        result.mcp_id = mcpId;
        result.itemCount = group.pageItems.length;

        var b = group.geometricBounds;
        result.bounds = {
            left: b[0], top: b[1], right: b[2], bottom: b[3],
            width: b[2] - b[0], height: b[1] - b[3]
        };

        // Complexity guardrail
        if (group.pageItems.length > 2000) {
            warnings.push("High complexity: " + group.pageItems.length
                + " items. Consider simpler preset.");
        }
    } else {
        result.type = "traced_live";
    }

    doc.selection = null;
    return JSON.stringify({ ok: true, data: result, operation: "trace_placed_image" });
})()
""")


# ==================== Undo/Redo ====================

UNDO = """
(function() {
    try {
        app.undo();
        return JSON.stringify({ ok: true, data: { message: "Undo successful" }, operation: "undo" });
    } catch (e) {
        return JSON.stringify({ ok: false, error: { message: "Nothing to undo", line: null, operation: "undo" } });
    }
})()
"""


REDO = """
(function() {
    try {
        app.redo();
        return JSON.stringify({ ok: true, data: { message: "Redo successful" }, operation: "redo" });
    } catch (e) {
        return JSON.stringify({ ok: false, error: { message: "Nothing to redo", line: null, operation: "redo" } });
    }
})()
"""


HISTORY_MULTI = Template("""
(function() {
    var count = ${count};
    var action = "${action_name}";
    var succeeded = 0;
    var failed = 0;
    
    for (var i = 0; i < count; i++) {
        try {
            app.${action_method}();
            succeeded++;
        } catch (e) {
            failed++;
            break;  // Stop if nothing more to undo/redo
        }
    }
    
    return JSON.stringify({
        ok: succeeded > 0,
        data: {
            message: action + " " + succeeded + "/" + count + " actions",
            succeeded: succeeded,
            failed: failed
        },
        operation: "history_multi"
    });
})()
""")


# ==================== Linked Items ====================

EMBED_PLACED_ITEMS = """
(function() {
    var doc = app.activeDocument;
    var embedded = 0;
    for (var i = doc.placedItems.length - 1; i >= 0; i--) {
        try {
            doc.placedItems[i].embed();
            embedded++;
        } catch(e) {}
    }
    return JSON.stringify({ ok: true, data: { embeddedCount: embedded }, operation: "embed_placed_items" });
})()
"""


UPDATE_LINKED_ITEMS = """
(function() {
    var doc = app.activeDocument;
    var updated = 0;
    for (var i = 0; i < doc.placedItems.length; i++) {
        try {
            var file = doc.placedItems[i].file;
            if (file && file.exists) {
                doc.placedItems[i].relink(file);
                updated++;
            }
        } catch(e) {}
    }
    return JSON.stringify({ ok: true, data: { updatedCount: updated }, operation: "update_linked_items" });
})()
"""


# ==================== Place/Embed (Editable) ====================

# Open/copy/paste workflow for embedding editable content (PDFs)
EMBED_EDITABLE = Template("""
(function() {
    var targetDoc = app.activeDocument;
    var targetDocName = targetDoc.name;

    try {
        // Open PDF as new document
        var pdfFile = new File("${path}");
        var pdfDoc = app.open(pdfFile);

        // Select all and copy
        pdfDoc.selectObjectsOnActiveArtboard();
        app.executeMenuCommand('copy');

        // Close PDF without saving
        pdfDoc.close(SaveOptions.DONOTSAVECHANGES);

        // Find and activate target document
        for (var d = 0; d < app.documents.length; d++) {
            if (app.documents[d].name === targetDocName) {
                app.activeDocument = app.documents[d];
                targetDoc = app.documents[d];
                break;
            }
        }

        // Paste
        app.executeMenuCommand('paste');

        // Get pasted selection and group
        var sel = targetDoc.selection;
        if (sel && sel.length > 0) {
            var group;
            if (sel.length > 1) {
                app.executeMenuCommand('group');
                group = targetDoc.selection[0];
            } else {
                group = sel[0];
            }

            // Position
            group.position = [${x}, ${neg_y}];

            var bounds = group.geometricBounds;
            targetDoc.selection = null;

            return JSON.stringify({
                ok: true,
                data: {
                    type: "editable",
                    position: [${x}, ${y}],
                    width: bounds[2] - bounds[0],
                    height: bounds[1] - bounds[3]
                },
                operation: "embed_editable"
            });
        }
        throw new Error("No content pasted");
    } catch(e) {
        return JSON.stringify({ ok: false, error: { message: e.message, line: e.line || null, operation: "embed_editable" } });
    }
})();
""")


# ==================== Export (Standard formats: PNG/JPG/SVG) ====================

EXPORT_STANDARD = Template("""
(function() {
    var doc = app.activeDocument;
    var abIdx = ${ab_index_js};
    doc.artboards.setActiveArtboardIndex(abIdx);

    var opts = new ${options_class}();${scale_opts}
    ${clip_opt}

    var file = new File("${path}");
    doc.exportFile(file, ${export_type}, opts);

    var abRect = doc.artboards[abIdx].artboardRect;
    var exportWidth = Math.round((abRect[2] - abRect[0]) * ${scale} / 100);
    var exportHeight = Math.round(Math.abs(abRect[3] - abRect[1]) * ${scale} / 100);

    return JSON.stringify({
        ok: true,
        data: {
            path: file.fsName,
            format: "${fmt_name}",
            artboard_index: abIdx,
            artboard_clipping: ${artboard_clip},
            width: exportWidth,
            height: exportHeight
        },
        operation: "export_standard"
    });
})();
""")


# ==================== Checkpoint Actions ====================

# Generic template for checkpoint save/restore/list/delete.
# name_arg is empty for 'list', otherwise: '"escapedName", '
CHECKPOINT_ACTION = Template("""
(function() {
    var doc = app.activeDocument;
    return JSON.stringify(${jsx_fn}(${name_arg}doc));
})();
""")


# ==================== Reference Overlay ====================

# Uses %s format (not Template) for JSON payload injection.
SET_REFERENCE = """
(function(payload) {
    var doc = app.activeDocument;
    var layerName = payload.layer_name;
    var originalActiveName = doc.activeLayer.name;

    // 1. Pre-flight file check
    var imgFile = null;
    if (payload.file_path) {
        imgFile = new File(payload.file_path);
        if (!imgFile.exists) {
            return JSON.stringify({
                ok: false, status: "error",
                message: "File not found: " + payload.file_path
            });
        }
    }

    // 2. Idempotent cleanup (unlock before delete, 0-layer guard)
    try {
        var existing = doc.layers.getByName(layerName);
        existing.locked = false;
        existing.visible = true;
        if (doc.layers.length === 1) {
            doc.layers.add().name = "Drawing Layer";
        }
        existing.remove();
    } catch(e) {}

    // 3. Clear-only mode
    if (!payload.file_path) {
        if (doc.layers.length > 0) doc.activeLayer = doc.layers[0];
        return JSON.stringify({
            ok: true, data: { status: "cleared", layer_name: layerName }, operation: "set_reference"
        });
    }

    // 4. Create layer, send to bottom
    var refLayer = doc.layers.add();
    refLayer.name = layerName;
    if (doc.layers.length > 1) {
        refLayer.move(doc.layers[doc.layers.length - 1], ElementPlacement.PLACEAFTER);
    }
    refLayer.printable = false;

    // 5. Place image, opacity on ITEM (not layer)
    var pItem = refLayer.placedItems.add();
    pItem.file = imgFile;

    // 6. Redraw to materialize bounds
    app.redraw();

    pItem.opacity = payload.opacity;

    // 7. Proportional fit + center on active artboard
    var abRect = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    var abW = Math.abs(abRect[2] - abRect[0]);
    var abH = Math.abs(abRect[3] - abRect[1]);

    if (payload.fit && pItem.width > 0 && pItem.height > 0) {
        var scale = Math.min(abW / pItem.width, abH / pItem.height) * 100;
        pItem.resize(scale, scale);
    }
    pItem.position = [
        abRect[0] + (abW - pItem.width) / 2,
        abRect[1] - (abH - pItem.height) / 2
    ];

    // 8. Lock layer
    refLayer.locked = true;

    // 9. Restore active layer by NAME (avoids stale object refs)
    var safeLayerFound = false;
    for (var i = 0; i < doc.layers.length; i++) {
        var L = doc.layers[i];
        if (L.name === originalActiveName && L.name !== layerName
            && !L.locked && L.visible) {
            doc.activeLayer = L;
            safeLayerFound = true;
            break;
        }
    }
    if (!safeLayerFound) {
        for (var i = 0; i < doc.layers.length; i++) {
            var L = doc.layers[i];
            if (L.name !== layerName && !L.locked && L.visible) {
                doc.activeLayer = L;
                safeLayerFound = true;
                break;
            }
        }
    }
    if (!safeLayerFound) {
        var drawLayer = doc.layers.add();
        drawLayer.name = "Drawing Layer";
        doc.activeLayer = drawLayer;
    }

    return JSON.stringify({
        ok: true, data: {
            status: "set", layer_name: layerName,
            opacity: payload.opacity,
            artboard: { width: abW, height: abH },
            image_bounds: {
                left: pItem.left, top: pItem.top,
                width: pItem.width, height: pItem.height,
                center_x: pItem.left + pItem.width / 2,
                center_y: pItem.top - pItem.height / 2
            },
            spatial_context: {
                artboard: "X: 0 to " + Math.round(abW) + ", Y: 0 to " + Math.round(abH),
                reference_bounds: "X: " + Math.round(pItem.left - abRect[0]) + ", Y: " + Math.round(abRect[1] - pItem.top) + ", Width: " + Math.round(pItem.width) + ", Height: " + Math.round(pItem.height),
                instruction: "Use Y-down user coordinates (origin at artboard top-left). Keep all generated path coordinates within the artboard bounds."
            }
        },
        operation: "set_reference"
    });
})(%s);
"""
