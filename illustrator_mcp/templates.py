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

        return JSON.stringify({
            success: true,
            name: doc.name,
            width: doc.width,
            height: doc.height
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
    var file = new File("${path}");
    if (!file.exists) {
        throw new Error("File not found: ${path}");
    }
    var doc = app.open(file);
    return JSON.stringify({success: true, name: doc.name, path: "${path}"});
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
    return JSON.stringify({success: true, path: "${path}", format: "PDF"});
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


# ==================== Import/Place ====================

IMPORT_IMAGE = Template("""
(function() {
    var doc = app.activeDocument;
    var file = new File("${path}");
    if (!file.exists) {
        throw new Error("Image file not found: ${path}");
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


PLACE_FILE = Template("""
(function() {
    var doc = app.activeDocument;
    var file = new File("${path}");
    if (!file.exists) {
        throw new Error("File not found: ${path}");
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


# ==================== Helper Functions ====================

def render_template(template: Template, **kwargs) -> str:
    """
    Render a template with the given variables.
    
    Args:
        template: A string.Template object
        **kwargs: Variables to substitute
        
    Returns:
        Rendered script string
    """
    return template.substitute(**kwargs)
