"""
Script templates for Adobe Illustrator ExtendScript.

This module centralizes JavaScript/ExtendScript templates used by tool implementations.

All templates use wrap_script() from tools.templates to produce the standardized
envelope: { ok: true, data: …, operation: "…" } / { ok: false, error: {…} }.

Parameterized templates expose a .substitute(**kw) API via _CompatTemplate for
backward compatibility with existing consumers.
"""

import json
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


def _build_create_document(width, height, color_space, title_line="",
                           requested_name="null"):
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

        // Report the name the document actually has, next to the one asked
        // for. Illustrator normalises some titles — a name containing a
        // backslash is treated as a path and only the last segment survives
        // ("a\\b" becomes "b") — and silently returning only `doc.name` gave
        // no way to tell a normalised name from the requested one.
        var requestedName = {requested_name};
        var data = {{
            name: doc.name,
            requestedName: requestedName,
            nameSubstituted: !!(requestedName && requestedName !== doc.name),
            width: doc.width,
            height: doc.height,
            artboardRect: ab.artboardRect
        }};
        if (data.nameSubstituted) {{
            data.warnings = ["Document name normalised by Illustrator: requested '" +
                             requestedName + "', created as '" + doc.name + "'"];
        }}
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
    """PDF saveAs cannot honor the source-preservation contract (SR06)."""
    return wrap_script('throw new Error("Native PDF export disabled; use a separate working copy with Illustrator PDF save.");', "export_pdf")


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
def _build_place_item(path, x, y, linked, embed_line="", marker_line="",
                      error_prefix="File", id_line="", id_json="null",
                      tmp_name="__mcp_placing__", neg_y=None):
    """Place a file, keeping identity and geometry across an embed().

    Two measured Illustrator behaviours drive the shape of this script:

    * ``embed()`` replaces the artwork and leaves the original reference as a
      **silent zombie** — it keeps answering ``typename === "PlacedItem"`` with
      its pre-embed ``width`` and ``note`` and never throws, so anything read
      or written through it afterwards is stale rather than obviously broken.
    * ``embed()`` **discards ``note``** but **preserves ``name``**. The trace
      marker used to be written to ``note`` after the embed, through the zombie
      reference, so it never reached the real artwork and tracing an embedded
      image always failed with "Trace target not found".

    ``neg_y`` is accepted and ignored; placement is now artboard-relative like
    every other operation, so the caller no longer supplies a negated y.
    """
    body = f"""
        var file = new File("{path}");
        if (!file.exists) {{
            return JSON.stringify({{
                ok: false,
                error: {{ message: "{error_prefix} not found: {path}", operation: __op }}
            }});
        }}

        // Artboard-relative, y-down: the convention every executor operation
        // uses (`abLeft + x`, `abTop - y`). Placement used to set
        // document-absolute coordinates (`top = -y`), so place_file(x, y) and
        // element_create(x, y) disagreed, and anything placed at a positive y
        // landed off the artboard entirely.
        var abIdx = doc.artboards.getActiveArtboardIndex();
        var abRect = doc.artboards[abIdx].artboardRect;   // [left, top, right, bottom]
        var abLeft = abRect[0];
        var abTop = abRect[1];

        var placed = doc.placedItems.add();
        placed.file = file;
        placed.left = abLeft + {x};
        placed.top = abTop - {y};

        // Captured BEFORE the embed, while the reference is still real.
        var parent = placed.parent;
        var placedWidth = placed.width;
        var placedHeight = placed.height;
        var placedLeft = placed.left;
        var placedTop = placed.top;

        // `name` survives embed(), `note` does not, so identity travels on the
        // name and is restamped on whatever actually survives.
        var priorName = placed.name;
        var tmpName = "{tmp_name}";
        placed.name = tmpName;

        var item = placed;
        var embedded = false;
        {embed_line}

        if (embedded) {{
            item = null;
            for (var pi = 0; pi < parent.pageItems.length; pi++) {{
                __mcp_check();
                if (parent.pageItems[pi].name === tmpName) {{
                    item = parent.pageItems[pi];
                    break;
                }}
            }}
            if (!item) {{
                return JSON.stringify({{
                    ok: false,
                    error: {{
                        message: "Embedded artwork could not be located after embed(). " +
                                 "It is still in the document; retrying would place a second copy.",
                        operation: __op
                    }}
                }});
            }}
        }}

        item.name = priorName;
        {id_line}
        {marker_line}

        var data = {{
            id: {id_json},
            typename: item.typename,
            embedded: embedded,
            path: "{path}",
            linked: {linked},
            artboard: abIdx,
            position: {{x: {x}, y: {y}}},
            origin: {{left: placedLeft, top: placedTop}},
            width: placedWidth,
            height: placedHeight
        }};
    """
    return wrap_script(body, "place_item")


PLACE_ITEM = _CompatTemplate(_build_place_item)


# Image Trace: vectorize a placed raster image
# Finds target by UUID marker (not fragile index), retries expandTracing() directly.
def _build_trace_placed_image(marker, preset, expand, placed_id=None):
    placed_id_js = json.dumps(placed_id) if placed_id else "null"
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
        // The placement already happened. Name what is in the document so a
        // caller retries the trace against existing artwork instead of
        // placing a second copy of the image.
        return JSON.stringify({{
            ok: false,
            error: {{
                message: "Trace target not found (marker: " + marker + "). " +
                         "The image was placed and is still in the document" +
                         ({placed_id_js} ? " as " + {placed_id_js} : "") +
                         "; trace it directly rather than placing it again.",
                operation: __op
            }},
            data: {{ placedId: {placed_id_js}, placementRetained: true }}
        }});
    }}

    // 2. Type guard
    var tn = target.typename;
    if (tn !== "PlacedItem" && tn !== "RasterItem") {{
        return JSON.stringify({{
            ok: false, error: {{ message: "Item not traceable: typename=" + tn, operation: __op }}
        }});
    }}

    // 3. Validate the preset BEFORE tracing.
    //
    // `loadFromPreset` does not throw on an unknown name — it silently leaves
    // the previous options in place. The old code relied on a catch that never
    // fired, so an unavailable or misspelled preset produced a confident
    // "preset: <requested>" in the result while the trace used something else
    // entirely. Checking the name first also means a bad preset costs nothing:
    // the image is not traced at all, so no artwork is half-converted.
    var presetName = {preset};
    var available = [];
    try {{ available = app.tracingPresetsList; }} catch (le) {{ available = []; }}
    if (presetName) {{
        var known = false;
        for (var ai = 0; ai < available.length; ai++) {{
            if (available[ai] === presetName) {{ known = true; break; }}
        }}
        if (!known) {{
            return JSON.stringify({{
                ok: false,
                error: {{
                    message: "Trace preset not found: '" + presetName + "'. Nothing was traced. " +
                             "Available presets: " + available.join(", "),
                    operation: __op
                }},
                data: {{ placedId: {placed_id_js}, placementRetained: true,
                        availablePresets: available }}
            }});
        }}
    }}

    // 4. Trace
    doc.selection = null;
    target.selected = true;
    var plugin = target.trace();

    var appliedPreset = null;
    if (presetName) {{
        try {{ plugin.tracing.tracingOptions.loadFromPreset(presetName); }}
        catch (pe) {{ warnings.push("Preset could not be loaded: " + presetName); }}
    }}
    // Read back what the tracing engine actually holds rather than repeating
    // the request back to the caller.
    try {{ appliedPreset = String(plugin.tracing.tracingOptions.preset); }}
    catch (re) {{ appliedPreset = null; }}
    if (presetName && appliedPreset && appliedPreset !== presetName) {{
        warnings.push("Trace preset substituted: requested '" + presetName +
                      "', applied '" + appliedPreset + "'");
    }}

    var result = {{
        trace_marker: marker,
        target_typename: tn,
        preset: {{ requested: presetName || null,
                  applied: appliedPreset,
                  substituted: !!(presetName && appliedPreset && appliedPreset !== presetName) }},
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

        // Tag with the caller's requested identity when there is one.
        //
        // Tracing consumes the placed raster, so the traced group IS the
        // imported artwork. Stamping only a generated "trace:" ID meant the
        // ID the caller asked for named nothing in the document afterwards,
        // and the reported identity could not be used to target the result.
        var mcpId = {placed_id_js} ? {placed_id_js}
                                   : ("trace:" + marker.replace("@mcp:trace_target=", ""));
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

# Undo/redo report UNKNOWN effects, not a successful transaction.
#
# These used to return {message: "Undo successful"} — a job-sized claim for an
# operation whose scope this server cannot know. Worse, undo leaves **silent
# zombies**: a deleted-then-restored item's old reference still answers with
# typename "PathItem" and never throws, so handles issued before an undo can
# resolve to artwork that is no longer what they described. Every handle is
# therefore invalidated here; MCP IDs, which live in the artwork's own note,
# survive because they are stored in the document itself.
_HISTORY_NOTE = (
    "Illustrator's undo stack is not aligned with MCP jobs: one app.undo() "
    "reverts one Illustrator history step, which may be part of an operation, "
    "a whole operation, or something a person did in the UI. The reverted "
    "scope is not knowable from this server."
)

_HISTORY_EPILOGUE = """
        var invalidated = null;
        if (typeof mcpHandleInvalidateAll === "function") {
            invalidated = mcpHandleInvalidateAll(action + "_history_step");
        }
        var data = {
            action: action,
            applied: applied,
            requested: requested,
            scope: "unknown",
            effects: "unknown",
            note: __NOTE__,
            handlesInvalidated: invalidated ? invalidated.invalidated : 0,
            handleEpoch: invalidated ? invalidated.epoch : null
        };
""".replace("__NOTE__", json.dumps(_HISTORY_NOTE))


UNDO = wrap_script(
    """
        var action = "undo";
        var requested = 1;
        var applied = 0;
        app.undo();
        applied = 1;
    """ + _HISTORY_EPILOGUE,
    "undo",
    require_document=False,
)


REDO = wrap_script(
    """
        var action = "redo";
        var requested = 1;
        var applied = 0;
        app.redo();
        applied = 1;
    """ + _HISTORY_EPILOGUE,
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

        var requested = count;
        var applied = succeeded;
    """ + _HISTORY_EPILOGUE + """
        data.failed = failed;
        data.succeeded = succeeded;
        data.message = action + " " + succeeded + "/" + count + " actions";
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
def _build_embed_editable(path, x, y, id_line="", id_json="null", neg_y=None):
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

        // Position: artboard-relative and y-down, matching every other
        // operation. This used to be document-absolute ([x, -y]), so editable
        // imports landed somewhere different from identically-addressed
        // element_create calls, and off the artboard for any positive y.
        var abIdx = targetDoc.artboards.getActiveArtboardIndex();
        var abRect = targetDoc.artboards[abIdx].artboardRect;   // [L, T, R, B]
        group.position = [abRect[0] + {x}, abRect[1] - {y}];

        var bounds = group.geometricBounds;
        targetDoc.selection = null;

        {id_line}

        var data = {{
            type: "editable",
            id: {id_json},
            typename: group.typename,
            artboard: abIdx,
            position: [{x}, {y}],
            width: bounds[2] - bounds[0],
            height: bounds[1] - bounds[3]
        }};
    """
    return wrap_script(body, "embed_editable")


EMBED_EDITABLE = _CompatTemplate(_build_embed_editable)


# ==================== Export (Standard formats: PNG/JPG/SVG) ====================

def _build_export_standard(ab_index_js, options_class, scale_opts, clip_opt,
                           path, export_type, scale, fmt_name, artboard_clip,
                           clip_supported="false"):
    """Export to PNG/JPEG/SVG.

    Two things this has to get right that it previously did not:

    * **The active artboard is temporary context.** Selecting the artboard to
      export changed the document's active artboard and never put it back, so
      an export silently repositioned the user's document (and every later
      operation that reads the active artboard). It is now restored in a
      ``finally``.
    * **Report the clipping that was applied, not the clipping requested.**
      ``artboard_clipping`` echoed the request for every format, but only PNG
      ever set the option. A JPEG export with ``artboard_only=True`` reported
      the artboard's dimensions while writing the whole artwork bounds:
      reported 300x200, actual 1292x402.
    """
    body = f"""
        var abIdx = {ab_index_js};
        if (abIdx < 0 || abIdx >= doc.artboards.length) {{
            return JSON.stringify({{
                ok: false,
                error: {{ message: "Artboard index " + abIdx + " is out of range; " +
                                   "the document has " + doc.artboards.length + " artboard(s).",
                         operation: __op }}
            }});
        }}

        var prevAbIdx = doc.artboards.getActiveArtboardIndex();
        var exportError = null;
        var data = null;
        try {{
            doc.artboards.setActiveArtboardIndex(abIdx);

            var opts = new {options_class}();{scale_opts}
            {clip_opt}

            var file = new File("{path}");
            doc.exportFile(file, {export_type}, opts);

            var abRect = doc.artboards[abIdx].artboardRect;
            var exportWidth = Math.round((abRect[2] - abRect[0]) * {scale} / 100);
            var exportHeight = Math.round(Math.abs(abRect[3] - abRect[1]) * {scale} / 100);

            data = {{
                path: file.fsName,
                format: "{fmt_name}",
                artboard_index: abIdx,
                artboard_clipping_requested: {artboard_clip},
                artboard_clipping: {clip_supported} ? {artboard_clip} : false,
                artboard_clipping_supported: {clip_supported},
                artboardWidthPoints: abRect[2] - abRect[0],
                artboardHeightPoints: Math.abs(abRect[3] - abRect[1]),
                artboardFrame: "document",
                artboardUnits: "pt",
                width: exportWidth,
                height: exportHeight,
                dimensions_describe: {clip_supported} && {artboard_clip}
                    ? "the exported file" : "the artboard, not necessarily the file"
            }};
        }} catch (ee) {{
            exportError = ee;
        }} finally {{
            // Restore the caller's artboard whether or not the export worked.
            try {{ doc.artboards.setActiveArtboardIndex(prevAbIdx); }} catch (re) {{
                throw new Error("Export artboard restoration failed: " + String(re) + (exportError ? "; export error: " + String(exportError) : ""));
            }}
        }}

        if (exportError) throw exportError;
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

# One producer, retaining both historical template entry points.
def _build_set_reference(payload_json):
    return SET_REFERENCE % payload_json


SET_REFERENCE = """
(function(payload) {
    var __op = "set_reference";
    var existing = null, refLayer = null, drawLayer = null;
    var existingLocked = false, existingVisible = true;
    var referenceRemoved = false, committed = false;
    var originalActiveName = null;
    var cleanupErrors = [];
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
        originalActiveName = doc.activeLayer.name;

        // Validate the action before any document changes, even for direct use.
        if (payload.action !== "set" && payload.action !== "clear") {
            throw new Error("Use action='set' with a file or action='clear' alone.");
        }
        if (payload.action === "set" &&
            (typeof payload.file_path !== "string" || !/\\S/.test(payload.file_path))) {
            throw new Error("action='set' requires a nonempty file_path.");
        }
        if (payload.action === "clear" &&
            (payload.hasOwnProperty("file_path") || payload.hasOwnProperty("opacity") ||
             payload.hasOwnProperty("fit"))) {
            throw new Error("action='clear' accepts no placement arguments.");
        }

        // File preflight does not touch the existing reference.
        var imgFile = null;
        if (payload.action === "set") {
            imgFile = new File(payload.file_path);
            if (!imgFile.exists) throw new Error("File not found: " + payload.file_path);
        }
        // Enumeration distinguishes absence from failures accessing/removing a layer.
        for (var n = 0; n < doc.layers.length; n++) {
            if (doc.layers[n].name === layerName) {
                existing = doc.layers[n];
                existingLocked = existing.locked;
                existingVisible = existing.visible;
                break;
            }
        }

        if (payload.action === "clear") {
            if (existing) {
                if (doc.layers.length === 1) {
                    drawLayer = doc.layers.add();
                    drawLayer.name = "Drawing Layer";
                }
                existing.locked = false;
                existing.visible = true;
                existing.remove();
                referenceRemoved = true;
            }
            return JSON.stringify({
                ok: true, data: { status: "cleared", layer_name: layerName,
                                 reference_removed: referenceRemoved }, operation: __op
            });
        }

        // 4. Create layer, send to bottom
        refLayer = doc.layers.add();
        refLayer.name = layerName + " (pending)";
        if (doc.layers.length > 1) {
            // Illustrator refuses layer.move relative to a locked reference.
            // Keep its artwork intact and restore its flags after ordering;
            // the outer failure path restores them if move itself throws.
            if (existing) { existing.locked = false; existing.visible = true; }
            refLayer.move(doc.layers[doc.layers.length - 1], ElementPlacement.PLACEAFTER);
            if (existing) { existing.locked = existingLocked; existing.visible = existingVisible; }
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
            if (L.name === originalActiveName && L !== existing && L !== refLayer
                && !L.locked && L.visible) {
                doc.activeLayer = L;
                safeLayerFound = true;
                break;
            }
        }
        if (!safeLayerFound) {
            for (var i = 0; i < doc.layers.length; i++) {
                var L = doc.layers[i];
                if (L !== existing && L !== refLayer && !L.locked && L.visible) {
                    doc.activeLayer = L;
                    safeLayerFound = true;
                    break;
                }
            }
        }
        if (!safeLayerFound) {
            drawLayer = doc.layers.add();
            drawLayer.name = "Drawing Layer";
            doc.activeLayer = drawLayer;
        }

        // Materialize result fields before committing the replacement.
        var resultData = {
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
        };
        refLayer.name = layerName;
        if (existing) {
            existing.locked = false;
            existing.visible = true;
            existing.remove();
            referenceRemoved = true;
        }
        committed = true;
        return JSON.stringify({ok: true, data: resultData, operation: __op});
    } catch (e) {
        // Remove only this call's staged layer. Never delete the old reference
        // as compensation; failed cleanup must remain visible in the result.
        if (refLayer && !committed) {
            try {
                refLayer.locked = false;
                refLayer.remove();
                refLayer = null;
            } catch (cleanupError) {
                cleanupErrors.push("Replacement cleanup: " + cleanupError.toString());
                try { refLayer.name = layerName + " (pending)"; }
                catch (nameError) { cleanupErrors.push("Replacement rename: " + nameError.toString()); }
            }
        }
        if (existing && !referenceRemoved) {
            try {
                existing.locked = existingLocked;
                existing.visible = existingVisible;
            } catch (restoreError) {
                cleanupErrors.push("Reference state restore: " + restoreError.toString());
            }
        }
        if (drawLayer && !referenceRemoved) {
            try { drawLayer.remove(); drawLayer = null; }
            catch (drawError) { cleanupErrors.push("Drawing layer cleanup: " + drawError.toString()); }
        }
        if (originalActiveName !== null) {
            try { doc.activeLayer = doc.layers.getByName(originalActiveName); }
            catch (activeError) { cleanupErrors.push("Active layer restore: " + activeError.toString()); }
        }
        return JSON.stringify({
            ok: false,
            data: { status: "failed", reference_removed: referenceRemoved,
                    replacement_retained: refLayer !== null,
                    drawing_layer_retained: drawLayer !== null,
                    cleanup_errors: cleanupErrors },
            error: { message: e.toString(), line: e.line || null, operation: __op }
        });
    }
})(%s);
"""


def with_user_interaction(script: str) -> str:
    """Scope alert suppression to one host evaluation; never implies cancellation.

    Restore in host-side finally, preserving the primary failure if restoration
    also fails. An unknown evaluation must be reconciled before any further call.
    """
    import json
    return """(function(){
var previous=app.userInteractionLevel, value, primary=null, cleanup=null;
try { app.userInteractionLevel=UserInteractionLevel.DONTDISPLAYALERTS; value=eval(SCRIPT); }
catch(e) { primary=e; }
finally { try { app.userInteractionLevel=previous; } catch(restoreError) { cleanup=restoreError; } }
if(primary) { if(cleanup) primary.message += "; interaction restoration failed: " + String(cleanup); throw primary; }
if(cleanup) throw cleanup;
return value;
})()""".replace("SCRIPT", json.dumps(script))
