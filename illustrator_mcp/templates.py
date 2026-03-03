"""
Script templates for Adobe Illustrator ExtendScript.

This module centralizes JavaScript/ExtendScript templates used by tool implementations.

All templates use wrap_script() from tools.templates to produce the standardized
envelope: { ok: true, data: …, operation: "…" } / { ok: false, error: {…} }.

Parameterized templates expose a .substitute(**kw) API via _CompatTemplate for
backward compatibility with existing consumers.
"""

from string import Template

from illustrator_mcp.tools.templates import wrap_script


# ── Compatibility shim ───────────────────────────────────────────────

class _CompatTemplate:
    """Shim: exposes .substitute(**kw) but delegates to wrap_script() internally.

    Allows consumers to keep using ``templates.XXX.substitute(...)`` without
    changing their call-sites, while the envelope is handled by wrap_script().
    """

    def __init__(self, builder_fn):
        self._build = builder_fn

    def substitute(self, **kw):
        return self._build(**kw)


# ==================== Document Operations ====================


def _build_create_document(width, height, color_space, title_line=""):
    body = f"""
        // Invalidate heap — previous document's DOM references are stale
        if ($.global.mcpHeap) $.global.mcpHeap = {{index: {{}}, docName: null}};

        var preset = new DocumentPreset();
        preset.width = {width};
        preset.height = {height};
        preset.colorMode = DocumentColorSpace.{color_space};
        preset.units = RulerUnits.Points;
        {title_line}

        var doc = app.documents.addDocument(DocumentColorSpace.{color_space}, preset);

        // FIX: Reposition artboard so top is at Y=0 (standard scripting convention)
        // By default, Illustrator places artboard at [0, height, width, 0]
        // We reposition to [0, 0, width, -height] so:
        //   - Artboard top is at Y=0
        //   - Artboard bottom is at Y=-height
        //   - Items placed with position [x, -y] appear correctly
        var ab = doc.artboards[0];
        var w = {width};
        var h = {height};
        ab.artboardRect = [0, 0, w, -h];

        var data = {{
            name: doc.name,
            width: doc.width,
            height: doc.height,
            artboardRect: ab.artboardRect
        }};
    """
    return wrap_script(body, "create_document", require_document=False)


CREATE_DOCUMENT = _CompatTemplate(_build_create_document)
DOC_CREATE = CREATE_DOCUMENT  # Alias used by documents.py


def _build_open_document(path):
    body = f"""
        var file = new File("{path}");
        if (!file.exists) {{
            return JSON.stringify({{
                ok: false,
                error: {{ message: "File not found: {path}", operation: __op }}
            }});
        }}
        var doc = app.open(file);
        var data = {{ name: doc.name, path: "{path}" }};
    """
    return wrap_script(body, "open_document", require_document=False)


OPEN_DOCUMENT = _CompatTemplate(_build_open_document)
DOC_OPEN = OPEN_DOCUMENT  # Alias used by documents.py


def _build_save_document(path):
    body = f"""
        var file = new File("{path}");
        doc.saveAs(file);
        var data = {{ path: "{path}" }};
    """
    return wrap_script(body, "save_document")


SAVE_DOCUMENT = _CompatTemplate(_build_save_document)
DOC_SAVE_AS = SAVE_DOCUMENT  # Alias: save-as (with path → doc.saveAs)


SAVE_DOCUMENT_SIMPLE = wrap_script(
    """
        doc.save();
        var data = { message: "Document saved" };
    """,
    "save_document",
)
DOC_SAVE = SAVE_DOCUMENT_SIMPLE  # Alias: save in-place (no path → doc.save)


def _build_close_document(save_option):
    body = f"""
        doc.close({save_option});
        var data = {{ message: "Document closed" }};
    """
    return wrap_script(body, "close_document")


CLOSE_DOCUMENT = _CompatTemplate(_build_close_document)
DOC_CLOSE = CLOSE_DOCUMENT  # Alias used by documents.py


# ==================== Export Templates ====================


def _build_export_file(path, options_class, export_type, scale_opts="", format_name=""):
    body = f"""
        var file = new File("{path}");
        var opts = new {options_class}();{scale_opts}
        doc.exportFile(file, {export_type}, opts);
        var data = {{ path: "{path}", format: "{format_name}" }};
    """
    return wrap_script(body, "export_file")


EXPORT_FILE = _CompatTemplate(_build_export_file)


def _build_export_pdf(path):
    body = f"""
        var file = new File("{path}");
        var opts = new PDFSaveOptions();
        doc.saveAs(file, opts);
        var abIdx = doc.artboards.getActiveArtboardIndex();
        var abRect = doc.artboards[abIdx].artboardRect;
        var data = {{
            path: "{path}",
            format: "PDF",
            width_pt: abRect[2] - abRect[0],
            height_pt: Math.abs(abRect[3] - abRect[1])
        }};
    """
    return wrap_script(body, "export_pdf")


EXPORT_PDF = _CompatTemplate(_build_export_pdf)


# ==================== Document Info ====================

GET_DOCUMENT_INFO = wrap_script(
    """
        var data = {
            name: doc.name,
            width: doc.width,
            height: doc.height,
            colorMode: doc.documentColorSpace == DocumentColorSpace.CMYK ? "CMYK" : "RGB",
            layerCount: doc.layers.length,
            saved: doc.saved
        };
    """,
    "get_document_info",
)


GET_APP_INFO = wrap_script(
    """
        var data = {
            name: app.name,
            version: app.version,
            locale: app.locale,
            documentsOpen: app.documents.length,
            activeDocumentName: app.documents.length > 0 ? app.activeDocument.name : null,
            freeMemory: app.freeMemory,
            scriptingVersion: app.scriptingVersion
        };
    """,
    "get_app_info",
    require_document=False,
)


# ==================== Context/Inspection ====================

def _build_get_document_structure(max_items, max_layers, offset, layer_filter):
    body = f"""
    var maxItems = {max_items};
    var maxLayers = {max_layers};
    var itemOffset = {offset};
    var layerFilter = {layer_filter};

    function _q(v){{return(typeof v==="number")?Math.round(v*100)/100:v;}}

    function getItemInfo(item, maxDepth, currentDepth) {{
        if (currentDepth > maxDepth) return null;

        var info = {{
            name: item.name || "(unnamed)",
            type: item.typename,
            position: item.position ? [_q(item.position[0]), _q(item.position[1])] : null,
            bounds: item.geometricBounds ? {{
                left: _q(item.geometricBounds[0]),
                top: _q(item.geometricBounds[1]),
                right: _q(item.geometricBounds[2]),
                bottom: _q(item.geometricBounds[3])
            }} : null
        }};

        if (item.typename === "PathItem") {{
            info.filled = item.filled;
            info.stroked = item.stroked;
        }}

        if (item.typename === "TextFrame") {{
            info.contents = item.contents.substring(0, 50);
        }}

        return info;
    }}

    function getLayerInfo(layer, maxI, off) {{
        var total = layer.pageItems.length;
        var layerInfo = {{
            name: layer.name,
            visible: layer.visible,
            locked: layer.locked,
            itemCount: total,
            items: [],
            offset: off,
            nextOffset: null
        }};

        var end = Math.min(total, off + maxI);
        for (var i = off; i < end; i++) {{
            var itemInfo = getItemInfo(layer.pageItems[i], 2, 0);
            if (itemInfo) layerInfo.items.push(itemInfo);
        }}

        if (end < total) {{
            layerInfo.truncated = true;
            layerInfo.totalItems = total;
            layerInfo.nextOffset = end;
        }}

        layerInfo.sublayers = [];
        for (var j = 0; j < layer.layers.length; j++) {{
            layerInfo.sublayers.push({{
                name: layer.layers[j].name,
                visible: layer.layers[j].visible,
                locked: layer.layers[j].locked
            }});
        }}

        return layerInfo;
    }}

    var result = {{
        document: {{
            name: doc.name,
            width: doc.width,
            height: doc.height,
            colorMode: doc.documentColorSpace.toString(),
            saved: doc.saved,
            layerCount: doc.layers.length,
            artboardCount: doc.artboards.length,
            artboards: []
        }},
        layers: []
    }};

    for (var a = 0; a < doc.artboards.length; a++) {{
        var ab = doc.artboards[a];
        result.document.artboards.push({{
            name: ab.name,
            bounds: ab.artboardRect
        }});
    }}

    // Layer filter: single layer by name or index
    if (layerFilter !== null) {{
        var targetLayer = null;
        if (typeof layerFilter === "number") {{
            if (layerFilter >= 0 && layerFilter < doc.layers.length) {{
                targetLayer = doc.layers[layerFilter];
            }}
        }} else if (typeof layerFilter === "string") {{
            for (var li = 0; li < doc.layers.length; li++) {{
                if (doc.layers[li].name === layerFilter) {{
                    targetLayer = doc.layers[li];
                    break;
                }}
            }}
        }}
        if (targetLayer) {{
            result.layers.push(getLayerInfo(targetLayer, maxItems, itemOffset));
        }}
    }} else {{
        // All layers (no offset applied — offset is per-layer paging only)
        var layerLimit = Math.min(doc.layers.length, maxLayers);
        for (var i = 0; i < layerLimit; i++) {{
            result.layers.push(getLayerInfo(doc.layers[i], maxItems, 0));
        }}
        if (doc.layers.length > maxLayers) {{
            result.layersTruncated = true;
            result.totalLayers = doc.layers.length;
        }}
    }}

    var data = result;
    """
    return wrap_script(body, "get_document_structure")


GET_DOCUMENT_STRUCTURE = _CompatTemplate(_build_get_document_structure)


GET_SELECTION_INFO = wrap_script(
    """
    var sel = doc.selection;

    if (!sel || sel.length === 0) {
        var data = {
            selected: false,
            count: 0,
            items: []
        };
    } else {
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

        var data = {
            selected: true,
            count: sel.length,
            items: items,
            truncated: sel.length > 50
        };
    }
    """,
    "get_selection_info",
)


# ==================== Import/Place ====================

# Single template for both import_image and place_file (they're 95% identical)
def _build_place_item(path, x, neg_y, y, linked, embed_line="", marker_line="", error_prefix="File"):
    body = f"""
        var file = new File("{path}");
        if (!file.exists) {{
            return JSON.stringify({{
                ok: false,
                error: {{ message: "{error_prefix} not found: {path}", operation: __op }}
            }});
        }}
        var placed = doc.placedItems.add();
        placed.file = file;
        placed.left = {x};
        placed.top = {neg_y};
        {embed_line}
        {marker_line}
        var data = {{
            path: "{path}",
            linked: {linked},
            position: {{x: {x}, y: {y}}},
            width: placed.width,
            height: placed.height
        }};
    """
    return wrap_script(body, "place_item")


PLACE_ITEM = _CompatTemplate(_build_place_item)


# Image Trace: vectorize a placed raster image
# Finds target by UUID marker (not fragile index), retries expandTracing() directly.
def _build_trace_placed_image(marker, preset, expand):
    body = f"""
    var marker = "{marker}";
    var warnings = [];

    // 1. Find target by marker — narrow collections first
    var target = null;
    var collections = [doc.placedItems, doc.rasterItems];
    for (var c = 0; c < collections.length && !target; c++) {{
        for (var i = 0; i < collections[c].length; i++) {{
            __mcp_check();
            if (collections[c][i].note && collections[c][i].note.indexOf(marker) >= 0) {{
                target = collections[c][i];
                break;
            }}
        }}
    }}
    // Fallback: full pageItems scan
    if (!target) {{
        for (var i = 0; i < doc.pageItems.length; i++) {{
            __mcp_check();
            if (doc.pageItems[i].note && doc.pageItems[i].note.indexOf(marker) >= 0) {{
                target = doc.pageItems[i];
                break;
            }}
        }}
    }}
    if (!target) {{
        return JSON.stringify({{
            ok: false, error: {{ message: "Trace target not found (marker: " + marker + ")", operation: __op }}
        }});
    }}

    // 2. Type guard
    var tn = target.typename;
    if (tn !== "PlacedItem" && tn !== "RasterItem") {{
        return JSON.stringify({{
            ok: false, error: {{ message: "Item not traceable: typename=" + tn, operation: __op }}
        }});
    }}

    // 3. Trace
    doc.selection = null;
    target.selected = true;
    var plugin = target.trace();

    // 4. Apply preset (safe fallback on locale/version mismatch)
    var presetName = {preset};
    if (presetName) {{
        try {{
            plugin.tracing.tracingOptions.loadFromPreset(presetName);
        }} catch(pe) {{
            warnings.push("Preset not found: " + presetName + "; using default");
        }}
    }}

    var result = {{
        trace_marker: marker,
        target_typename: tn,
        preset: presetName || "(default)",
        warnings: warnings
    }};

    // 5. Expand with retry-around-expand (direct operation test)
    if ({expand}) {{
        app.redraw();
        var group = null;
        var maxRetries = 20;
        for (var r = 0; r < maxRetries; r++) {{
            __mcp_check();
            try {{
                group = plugin.tracing.expandTracing();
                break;
            }} catch(ex) {{
                $$.sleep(500);
                app.redraw();
            }}
        }}
        if (!group) {{
            return JSON.stringify({{
                ok: false,
                error: {{ message: "expandTracing() failed after " + maxRetries + " retries", operation: __op }},
                warnings: warnings
            }});
        }}

        // Tag with MCP ID (trace: namespace)
        var mcpId = "trace:" + marker.replace("@mcp:trace_target=", "");
        group.note = "@mcp:id=" + mcpId;
        group.name = "traced_group";

        result.type = "traced_expanded";
        result.mcp_id = mcpId;
        result.itemCount = group.pageItems.length;

        var b = group.geometricBounds;
        result.bounds = {{
            left: b[0], top: b[1], right: b[2], bottom: b[3],
            width: b[2] - b[0], height: b[1] - b[3]
        }};

        // Complexity guardrail
        if (group.pageItems.length > 2000) {{
            warnings.push("High complexity: " + group.pageItems.length
                + " items. Consider simpler preset.");
        }}
    }} else {{
        result.type = "traced_live";
    }}

    doc.selection = null;
    var data = result;
    """
    return wrap_script(body, "trace_placed_image")


TRACE_PLACED_IMAGE = _CompatTemplate(_build_trace_placed_image)


# ==================== Undo/Redo ====================

UNDO = wrap_script(
    """
        app.undo();
        var data = { message: "Undo successful" };
    """,
    "undo",
    require_document=False,
)


REDO = wrap_script(
    """
        app.redo();
        var data = { message: "Redo successful" };
    """,
    "redo",
    require_document=False,
)


def _build_history_multi(count, action_name, action_method):
    body = f"""
        var count = {count};
        var action = "{action_name}";
        var succeeded = 0;
        var failed = 0;

        for (var i = 0; i < count; i++) {{
            try {{
                app.{action_method}();
                succeeded++;
            }} catch (e) {{
                failed++;
                break;  // Stop if nothing more to undo/redo
            }}
        }}

        if (succeeded === 0) throw new Error("No history step executed");

        var data = {{
            message: action + " " + succeeded + "/" + count + " actions",
            succeeded: succeeded,
            failed: failed
        }};
    """
    return wrap_script(body, "history_multi", require_document=False)


HISTORY_MULTI = _CompatTemplate(_build_history_multi)


# ==================== Linked Items ====================

EMBED_PLACED_ITEMS = wrap_script(
    """
        var embedded = 0;
        for (var i = doc.placedItems.length - 1; i >= 0; i--) {
            try {
                doc.placedItems[i].embed();
                embedded++;
            } catch(e) {}
        }
        var data = { embeddedCount: embedded };
    """,
    "embed_placed_items",
)


UPDATE_LINKED_ITEMS = wrap_script(
    """
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
        var data = { updatedCount: updated };
    """,
    "update_linked_items",
)


# ==================== Place/Embed (Editable) ====================

# Open/copy/paste workflow for embedding editable content (PDFs)
def _build_embed_editable(path, x, neg_y, y):
    body = f"""
        var targetDoc = doc;
        var targetDocName = targetDoc.name;

        // Open PDF as new document
        var pdfFile = new File("{path}");
        var pdfDoc = app.open(pdfFile);

        // Select all and copy
        pdfDoc.selectObjectsOnActiveArtboard();
        app.executeMenuCommand('copy');

        // Close PDF without saving
        pdfDoc.close(SaveOptions.DONOTSAVECHANGES);

        // Find and activate target document
        for (var d = 0; d < app.documents.length; d++) {{
            if (app.documents[d].name === targetDocName) {{
                app.activeDocument = app.documents[d];
                targetDoc = app.documents[d];
                break;
            }}
        }}

        // Paste
        app.executeMenuCommand('paste');

        // Get pasted selection and group
        var sel = targetDoc.selection;
        if (!sel || sel.length === 0) {{
            throw new Error("No content pasted");
        }}

        var group;
        if (sel.length > 1) {{
            app.executeMenuCommand('group');
            group = targetDoc.selection[0];
        }} else {{
            group = sel[0];
        }}

        // Position
        group.position = [{x}, {neg_y}];

        var bounds = group.geometricBounds;
        targetDoc.selection = null;

        var data = {{
            type: "editable",
            position: [{x}, {y}],
            width: bounds[2] - bounds[0],
            height: bounds[1] - bounds[3]
        }};
    """
    return wrap_script(body, "embed_editable")


EMBED_EDITABLE = _CompatTemplate(_build_embed_editable)


# ==================== Export (Standard formats: PNG/JPG/SVG) ====================

def _build_export_standard(ab_index_js, options_class, scale_opts, clip_opt,
                           path, export_type, scale, fmt_name, artboard_clip):
    body = f"""
        var abIdx = {ab_index_js};
        doc.artboards.setActiveArtboardIndex(abIdx);

        var opts = new {options_class}();{scale_opts}
        {clip_opt}

        var file = new File("{path}");
        doc.exportFile(file, {export_type}, opts);

        var abRect = doc.artboards[abIdx].artboardRect;
        var exportWidth = Math.round((abRect[2] - abRect[0]) * {scale} / 100);
        var exportHeight = Math.round(Math.abs(abRect[3] - abRect[1]) * {scale} / 100);

        var data = {{
            path: file.fsName,
            format: "{fmt_name}",
            artboard_index: abIdx,
            artboard_clipping: {artboard_clip},
            width: exportWidth,
            height: exportHeight
        }};
    """
    return wrap_script(body, "export_standard")


EXPORT_STANDARD = _CompatTemplate(_build_export_standard)


# ==================== Checkpoint Actions ====================

# Generic template for checkpoint save/restore/list/delete.
# name_arg is empty for 'list', otherwise: '"escapedName", '
def _build_checkpoint_action(jsx_fn, name_arg):
    body = f"""
        var data = {jsx_fn}({name_arg}doc);
    """
    return wrap_script(body, "checkpoint_action")


CHECKPOINT_ACTION = _CompatTemplate(_build_checkpoint_action)


# ==================== Reference Overlay ====================

# Uses %s format for JSON payload injection.
# SET_REFERENCE is special: it takes a JSON payload argument to the IIFE.
# We keep it as a raw string with %s but wrap the body in wrap_script style.
def _build_set_reference(payload_json):
    # This template uses an IIFE argument pattern: (function(payload){...})(%s)
    # We cannot use wrap_script directly because of the IIFE argument.
    # Instead, we build a similar envelope manually but with the canonical shape.
    return """
(function(payload) {
    var __op = "set_reference";
    try {
        if (!app.documents.length) {
            return JSON.stringify({
                ok: false,
                error: { message: "NO_DOCUMENT: No document is open. Please create or open a document first.",
                         line: null, operation: __op }
            });
        }
        var doc = app.activeDocument;
        var layerName = payload.layer_name;
        var originalActiveName = doc.activeLayer.name;

        // 1. Pre-flight file check
        var imgFile = null;
        if (payload.file_path) {
            imgFile = new File(payload.file_path);
            if (!imgFile.exists) {
                return JSON.stringify({
                    ok: false,
                    error: { message: "File not found: " + payload.file_path, operation: __op }
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
                ok: true, data: { status: "cleared", layer_name: layerName }, operation: __op
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
            operation: __op
        });
    } catch (e) {
        return JSON.stringify({
            ok: false,
            error: { message: e.toString(), line: e.line || null, operation: __op }
        });
    }
})(""" + payload_json + """);
"""


# The legacy constant — uses %s formatting from the consumer side
SET_REFERENCE = """
(function(payload) {
    var __op = "set_reference";
    try {
        if (!app.documents.length) {
            return JSON.stringify({
                ok: false,
                error: { message: "NO_DOCUMENT: No document is open. Please create or open a document first.",
                         line: null, operation: __op }
            });
        }
        var doc = app.activeDocument;
        var layerName = payload.layer_name;
        var originalActiveName = doc.activeLayer.name;

        // 1. Pre-flight file check
        var imgFile = null;
        if (payload.file_path) {
            imgFile = new File(payload.file_path);
            if (!imgFile.exists) {
                return JSON.stringify({
                    ok: false,
                    error: { message: "File not found: " + payload.file_path, operation: __op }
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
                ok: true, data: { status: "cleared", layer_name: layerName }, operation: __op
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
            operation: __op
        });
    } catch (e) {
        return JSON.stringify({
            ok: false,
            error: { message: e.toString(), line: e.line || null, operation: __op }
        });
    }
})(%s);
"""
