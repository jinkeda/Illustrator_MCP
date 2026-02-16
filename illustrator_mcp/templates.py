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
            success: true,
            name: doc.name,
            width: doc.width,
            height: doc.height,
            artboardRect: ab.artboardRect
        });
    } catch (e) {
        return JSON.stringify({
            success: false,
            error: e.message || String(e)
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
                success: false,
                error: "File not found: ${path}"
            });
        }
        var doc = app.open(file);
        return JSON.stringify({success: true, name: doc.name, path: "${path}"});
    } catch (e) {
        return JSON.stringify({
            success: false,
            error: e.message || String(e)
        });
    }
})()
""")


SAVE_DOCUMENT = Template("""
(function() {
    var doc = app.activeDocument;
    var file = new File("${path}");
    doc.saveAs(file);
    return JSON.stringify({success: true, path: "${path}"});
})()
""")


SAVE_DOCUMENT_SIMPLE = """
(function() {
    var doc = app.activeDocument;
    doc.save();
    return JSON.stringify({success: true, message: "Document saved"});
})()
"""


CLOSE_DOCUMENT = Template("""
(function() {
    var doc = app.activeDocument;
    doc.close(${save_option});
    return JSON.stringify({success: true, message: "Document closed"});
})()
""")


# ==================== Export Templates ====================

EXPORT_FILE = Template("""
(function() {
    var doc = app.activeDocument;
    var file = new File("${path}");
    var opts = new ${options_class}();${scale_opts}
    doc.exportFile(file, ${export_type}, opts);
    return JSON.stringify({success: true, path: "${path}", format: "${format_name}"});
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
        success: true,
        path: "${path}",
        format: "PDF",
        width_pt: abRect[2] - abRect[0],
        height_pt: Math.abs(abRect[3] - abRect[1])
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
    
    function getItemInfo(item, maxDepth, currentDepth) {
        if (currentDepth > maxDepth) return null;
        
        var info = {
            name: item.name || "(unnamed)",
            type: item.typename,
            position: item.position ? [item.position[0], item.position[1]] : null,
            bounds: item.geometricBounds ? {
                left: item.geometricBounds[0],
                top: item.geometricBounds[1],
                right: item.geometricBounds[2],
                bottom: item.geometricBounds[3]
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
    
    for (var i = 0; i < limit; i++) {
        var item = sel[i];
        var info = {
            name: item.name || "(unnamed)",
            type: item.typename,
            position: item.position ? [item.position[0], item.position[1]] : null,
            bounds: item.geometricBounds ? {
                left: item.geometricBounds[0],
                top: item.geometricBounds[1],
                right: item.geometricBounds[2],
                bottom: item.geometricBounds[3]
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
    return JSON.stringify({
        success: true,
        path: "${path}",
        linked: ${linked},
        position: {x: ${x}, y: ${y}},
        width: placed.width,
        height: placed.height
    });
})()
""")


# ==================== Undo/Redo ====================

UNDO = """
(function() {
    try {
        app.undo();
        return JSON.stringify({success: true, message: "Undo successful"});
    } catch (e) {
        return JSON.stringify({success: false, message: "Nothing to undo"});
    }
})()
"""


REDO = """
(function() {
    try {
        app.redo();
        return JSON.stringify({success: true, message: "Redo successful"});
    } catch (e) {
        return JSON.stringify({success: false, message: "Nothing to redo"});
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
        success: succeeded > 0,
        message: action + " " + succeeded + "/" + count + " actions",
        succeeded: succeeded,
        failed: failed
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
    return JSON.stringify({success: true, embeddedCount: embedded});
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
    return JSON.stringify({success: true, updatedCount: updated});
})()
"""


