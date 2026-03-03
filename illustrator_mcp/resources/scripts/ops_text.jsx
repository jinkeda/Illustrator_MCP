/**
 * ops_text.jsx - Text Operations
 * Part of Illustrator MCP SOC Framework
 * 
 * Provides handlers for:
 * - text_create: Create a text frame
 * - text_set_content: Set text content
 * - text_set_style: Set text styling (font, size, color)
 * 
 * @requires ops_core (for registerOpHandler, generateUUID)
 * @requires targets (for findLayer)
 * @version 1.1.0
 */

// ==================== Dependency Guard ====================

if (typeof findLayer !== "function") {
    throw new Error("ops_text.jsx requires targets.jsx (findLayer=" + typeof findLayer + ")");
}

// ==================== Text Create ====================

registerOpHandler("text_create", function (params, targets, ctx) {
    var doc = ctx.doc;
    var id = params.id || generateUUID();

    var x = params.x || 0;
    var y = params.y || 0;
    var contents = params.contents || params.text || "";
    var fontSize = params.fontSize || 12;
    var fontFamily = params.fontFamily || null;
    var name = params.name || null;

    // Resolve target layer (deterministic: params.layer > ctx.defaultLayer > activeLayer)
    var targetLayer;
    if (params.layer) {
        targetLayer = findLayer(doc, params.layer);
        if (!targetLayer) {
            return makeError(ErrorCodes.V_INVALID_PARAM_TYPE, "Layer not found: " + params.layer, "apply");
        }
    } else if (ctx && ctx.defaultLayer) {
        targetLayer = findLayer(doc, ctx.defaultLayer);
        if (!targetLayer) targetLayer = doc.activeLayer;
    } else {
        targetLayer = doc.activeLayer;
        if (ctx && ctx.warn) ctx.warn("No layer specified; using activeLayer '" + targetLayer.name + "'");
    }

    // Convert to Illustrator coordinates (artboard-relative, Y-up)
    // _artboardTop/_artboardLeft defined in ops_element.jsx (loaded before this file)
    var abTop = _artboardTop(doc);
    var abLeft = _artboardLeft(doc);

    // Create text frame
    var textFrame = targetLayer.textFrames.add();
    textFrame.position = [abLeft + x, abTop - y];
    textFrame.contents = contents;

    // Assign ID + register in heap (H1 invariant)
    stampMcpId(textFrame, id);
    if (name) textFrame.name = name;

    // Apply styling
    try {
        textFrame.textRange.characterAttributes.size = fontSize;

        if (fontFamily) {
            try {
                textFrame.textRange.characterAttributes.textFont = app.textFonts.getByName(fontFamily);
            } catch (e) {
                // Font not found, use default
            }
        }

        // Color via canonical _parseColorParam (fill:{r,g,b} or flat r,g,b)
        var parsedFill = _parseColorParam(params, "fill");
        if (parsedFill.color) {
            textFrame.textRange.characterAttributes.fillColor = parsedFill.color;
        }
    } catch (e) {
        // Styling may fail on empty text
    }

    return {
        ok: true,
        id: id,
        data: {
            typename: "TextFrame",
            position: [x, y],
            contents: contents
        }
    };
});

// ==================== Text Set Content ====================

registerOpHandler("text_set_content", function (params, targets, ctx) {
    if (targets.length === 0) {
        return makeError(ErrorCodes.V_NO_SELECTION, "No text frames to modify", "apply");
    }

    var contents = params.contents || params.text || "";
    var modified = 0;
    var warnings = [];

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];

        if (item.typename !== "TextFrame") {
            warnings.push("Item " + i + " is not a TextFrame");
            continue;
        }

        try {
            item.contents = contents;
            modified++;
        } catch (e) {
            warnings.push("Failed to set content on item " + i + ": " + e.message);
        }
    }

    return { ok: true, data: { modified: modified }, warnings: warnings };
});

// ==================== Text Set Style ====================

registerOpHandler("text_set_style", function (params, targets, ctx) {
    if (targets.length === 0) {
        return { ok: true, data: { modified: 0 } };
    }

    var modified = 0;
    var warnings = [];

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];

        if (item.typename !== "TextFrame") {
            warnings.push("Item " + i + " is not a TextFrame");
            continue;
        }

        try {
            if (params.fontSize !== undefined) {
                item.textRange.characterAttributes.size = params.fontSize;
            }

            if (params.fontFamily) {
                try {
                    item.textRange.characterAttributes.textFont = app.textFonts.getByName(params.fontFamily);
                } catch (e) { }
            }

            // Color via canonical _parseColorParam (fill:{r,g,b} or flat r,g,b)
            var parsedFill = _parseColorParam(params, "fill");
            if (parsedFill.color) {
                item.textRange.characterAttributes.fillColor = parsedFill.color;
            }

            if (params.tracking !== undefined) {
                item.textRange.characterAttributes.tracking = params.tracking;
            }

            modified++;
        } catch (e) {
            warnings.push("Failed to style text " + i + ": " + e.message);
        }
    }

    return { ok: true, data: { modified: modified }, warnings: warnings };
});
