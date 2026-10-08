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

/**
 * Name a text target in a message.
 *
 * A loop index is meaningless to a caller who passed a set of MCP IDs: a
 * warning reading "Item 1 is not a TextFrame" gave no way to tell *which*
 * requested object was skipped. Report the stable ID when the item has one,
 * then the artwork name, and fall back to the index only when neither exists.
 */
function textTargetLabel(item, index) {
    var id = null;
    if (typeof extractMcpId === "function") {
        try { id = extractMcpId(item.note || ""); } catch (e) { id = null; }
    }
    if (id) return id;
    var nm = null;
    try { nm = item.name; } catch (e2) { nm = null; }
    if (nm) return "'" + nm + "'";
    return "index " + index;
}

// SR05: resolve all font intent before allocation or modification.
function resolveTextFont(params) {
    var requested = params.fontName || params.fontFamily || null;
    var warnings = [], faces = [], font = null, rule = null;
    function fail(message) {
        var suggestions = [];
        if (requested) {
            for (var si = 0; si < app.textFonts.length && suggestions.length < 5; si++) {
                var candidate = app.textFonts[si].name;
                if (candidate.toLowerCase().indexOf(String(requested).toLowerCase()) >= 0) suggestions.push(candidate);
            }
        }
        return {error: makeError(ErrorCodes.V_INVALID_PARAM_VALUE || "V011",
            message + " Nothing was changed." + (suggestions.length ? " Similar available fonts: " + suggestions.join(", ") : ""),
            "validate", null, {requestedFont: requested, suggestions: suggestions, availableFaces: faces.slice(0, 20)})};
    }
    function norm(value) { return String(value || "").replace(/^\s+|\s+$/g, "").toLowerCase(); }
    if (params.fontName !== undefined && params.fontFamily !== undefined)
        return fail("Use fontName or fontFamily, not both.");
    if (params.fontStyle !== undefined && !params.fontFamily)
        return fail("fontStyle requires fontFamily.");
    if (!requested) return {font: null, warnings: warnings, report: null};
    if (params.fontName) {
        try { font = app.textFonts.getByName(params.fontName); } catch (e) { font = null; }
        if (font && font.name !== params.fontName) font = null;
        rule = "exact PostScript name";
    } else {
        var matches = [], i;
        for (i = 0; i < app.textFonts.length; i++) {
            var face = app.textFonts[i];
            if (norm(face.family) === norm(params.fontFamily)) {
                matches.push(face);
                faces.push({name: face.name, style: face.style});
            }
        }
        if (!matches.length && params.fontStyle === undefined) {
            try { font = app.textFonts.getByName(params.fontFamily); } catch (e2) { font = null; }
            if (font && font.name !== params.fontFamily) font = null;
            if (font) warnings.push("Deprecated fontFamily PostScript alias; use fontName: " + font.name);
            rule = "legacy PostScript alias";
        } else if (matches.length) {
            var styles = params.fontStyle !== undefined ? [norm(params.fontStyle)] : ["regular", "roman", "book", "normal"];
            for (var rank = 0; rank < styles.length; rank++) {
                var chosen = [];
                for (i = 0; i < matches.length; i++) if (norm(matches[i].style) === styles[rank]) chosen.push(matches[i]);
                if (chosen.length > 1) return fail("Ambiguous font family/style; specify fontName. Available faces: " + JSON.stringify(faces.slice(0, 20)));
                if (chosen.length === 1) { font = chosen[0]; rule = params.fontStyle !== undefined ? "explicit style" : "Regular, Roman, Book, Normal: " + styles[rank]; break; }
            }
        }
    }
    if (!font) return fail("Font not found or no unambiguous regular-style face: '" + requested + "'. Specify fontStyle/fontName. Available faces: " + JSON.stringify(faces.slice(0, 20)));
    // Resolution identifies an installed face; it does not verify host application.
    return {font: font, warnings: warnings, report: {requested: requested, resolved: font.name, defaultStyleRule: rule, substituted: null, readbackComplete: false}};
}

// Runs use whole strings, not numeric host offsets. Resolve fonts before writes.
function _mcpTextRuns(params) {
    if (params.runs === undefined) return null;
    if (!(params.runs instanceof Array) || !params.runs.length || params.runs.length > 1000)
        throw new Error("runs must be a nonempty array of at most 1000 entries");
    var out = {text: "", runs: [], warnings: []};
    var allowed = {text: true, fontName: true, fontFamily: true, fontStyle: true, fontSize: true, baselineShift: true, fill: true};
    for (var i = 0; i < params.runs.length; i++) {
        var run = params.runs[i];
        if (!run || typeof run.text !== "string" || !run.text.length) throw new Error("Each run requires nonempty text");
        for (var key in run) if (run.hasOwnProperty(key) && !allowed[key]) throw new Error("Unknown run field: " + key);
        for (var ci = 0; ci < run.text.length; ci++) {
            var code = run.text.charCodeAt(ci);
            if (code >= 55296 && code <= 56319) {
                var next = run.text.charCodeAt(++ci);
                if (!(next >= 56320 && next <= 57343)) throw new Error("A run cannot split a UTF-16 surrogate pair");
            } else if (code >= 56320 && code <= 57343) throw new Error("Unpaired UTF-16 surrogate");
        }
        if (run.fontSize !== undefined && (typeof run.fontSize !== "number" || !isFinite(run.fontSize) || run.fontSize <= 0)) throw new Error("Run fontSize must be positive points");
        if (run.baselineShift !== undefined && (typeof run.baselineShift !== "number" || !isFinite(run.baselineShift))) throw new Error("Run baselineShift must be finite points");
        if (run.fill !== undefined) {
            if (!run.fill || typeof run.fill !== "object") throw new Error("Run fill requires r,g,b");
            var channels = ["r", "g", "b"];
            for (var ch = 0; ch < 3; ch++) {
                var value = run.fill[channels[ch]];
                if (typeof value !== "number" || !isFinite(value) || value < 0 || value > 255) throw new Error("Run fill channels must be 0..255");
            }
        }
        var font = resolveTextFont(run);
        if (font.error) throw new Error("Run " + i + " font resolution failed: " + JSON.stringify(font.error));
        out.warnings = out.warnings.concat(font.warnings);
        out.runs.push({start: out.text.length, end: out.text.length + run.text.length, style: run,
            font: font.font, fontReport: font.report});
        out.text += run.text;
    }
    if (params.contents !== undefined && params.contents !== out.text) throw new Error("contents must equal concatenated runs");
    return out;
}

function _mcpTextRunPlan(item, runs) {
    if (item.contents !== runs.text) throw new Error("Run text must exactly match existing contents; use text_set_content to replace it");
    // Read the actual host character strings and reconstruct contents. Neither
    // JS UTF-16 indexing nor Illustrator character indexing is assumed here.
    var chars = item.textRange.characters, offset = 0, ri = 0, plan = [];
    for (var i = 0; i < chars.length; i++) {
        var text = String(chars[i].contents);
        if (!text.length || runs.text.substr(offset, text.length) !== text) throw new Error("Host character indexing cannot be verified");
        while (ri < runs.runs.length && offset >= runs.runs[ri].end) ri++;
        if (ri >= runs.runs.length || offset + text.length > runs.runs[ri].end) throw new Error("Run boundary splits a host character or combining sequence");
        plan.push({character: chars[i], run: runs.runs[ri], runIndex: ri});
        offset += text.length;
    }
    if (offset !== runs.text.length) throw new Error("Host character coverage is incomplete");
    return plan;
}

function _mcpApplyTextRuns(plan) {
    for (var i = 0; i < plan.length; i++) {
        var attrs = plan[i].character.characterAttributes, run = plan[i].run, style = run.style;
        if (run.font) attrs.textFont = run.font;
        if (style.fontSize !== undefined) attrs.size = style.fontSize;
        if (style.baselineShift !== undefined) attrs.baselineShift = style.baselineShift;
        if (style.fill !== undefined) attrs.fillColor = _parseColorParam(style, "fill").color;
    }
    // Read only after all writes: shaping can substitute earlier characters.
    var report = {status: "passed", checkedCharacters: plan.length, differences: [], fonts: []};
    var fontReports = {};
    for (var ci = 0; ci < plan.length; ci++) {
        var entry = plan[ci], requested = entry.run.style;
        function check(attribute, expected, actual, numeric) {
            if (numeric ? typeof actual !== "number" || !isFinite(actual) || Math.abs(expected - actual) > 0.01 : expected !== actual) {
                report.differences.push({characterIndex: ci, runIndex: entry.runIndex,
                    attribute: attribute, requested: expected, actual: actual === undefined ? null : actual});
            }
        }
        var fontReport = null;
        if (entry.run.font) {
            var fontKey = "run_" + entry.runIndex;
            if (!fontReports[fontKey]) {
                fontReports[fontKey] = {runIndex: entry.runIndex,
                    requested: entry.run.fontReport.requested,
                    resolved: entry.run.fontReport.resolved,
                    defaultStyleRule: entry.run.fontReport.defaultStyleRule,
                    actual: [], substituted: false, readbackComplete: true};
                report.fonts.push(fontReports[fontKey]);
            }
            fontReport = fontReports[fontKey];
        }
        var fontReadComplete = false;
        try {
            var observed = entry.character.characterAttributes;
            if (entry.run.font) {
                var actualFont = observed.textFont.name;
                if (typeof actualFont !== "string" || !actualFont.length) throw new Error("Font readback unavailable");
                var foundFont = false;
                for (var fi = 0; fi < fontReport.actual.length; fi++) if (fontReport.actual[fi] === actualFont) foundFont = true;
                if (!foundFont) fontReport.actual.push(actualFont);
                if (actualFont !== entry.run.font.name) fontReport.substituted = true;
                check("fontName", entry.run.font.name, actualFont, false);
                fontReadComplete = true;
            }
            if (requested.fontSize !== undefined) check("fontSize", requested.fontSize, observed.size, true);
            if (requested.baselineShift !== undefined) check("baselineShift", requested.baselineShift, observed.baselineShift, true);
            if (requested.fill !== undefined) {
                var color = observed.fillColor;
                check("fill.r", requested.fill.r, color.red, true);
                check("fill.g", requested.fill.g, color.green, true);
                check("fill.b", requested.fill.b, color.blue, true);
            }
        } catch (readError) {
            if (fontReport && !fontReadComplete) {
                fontReport.readbackComplete = false;
                if (!fontReport.substituted) fontReport.substituted = null;
            }
            report.differences.push({characterIndex: ci, runIndex: entry.runIndex,
                attribute: "readback", error: String(readError)});
        }
    }
    if (report.differences.length) report.status = "failed";
    return report;
}

function _mcpRecordTextRunReadback(plan, reports, warnings, target) {
    var report = _mcpApplyTextRuns(plan);
    report.target = target;
    reports.push(report);
    if (report.status !== "passed") warnings.push("Requested run attributes were substituted, changed or unreadable on " + target + "; inspect data.runVerification. Application is not verified.");
}

registerOpHandler("text_create", function (params, targets, ctx) {
    var doc = ctx.doc;
    var id = params.id || generateUUID();

    var x = params.x || 0;
    var y = params.y || 0;
    var runs;
    try { runs = _mcpTextRuns(params); } catch (runError) { return makeError(ErrorCodes.V_INVALID_PARAM_VALUE || "V011", runError.message, "validate"); }
    if (!runs && params.contents === undefined && params.text === undefined) return makeError(ErrorCodes.V_INVALID_PARAM_VALUE || "V011", "contents or runs is required", "validate");
    var contents = runs ? runs.text : (params.contents || params.text || "");
    var fontSize = params.fontSize || 12;
    var resolved = resolveTextFont(params);
    if (resolved.error) return resolved.error;
    var styled = params.fontName !== undefined || params.fontFamily !== undefined ||
        params.fontStyle !== undefined || params.fontSize !== undefined || params.fill !== undefined ||
        params.r !== undefined || params.g !== undefined || params.b !== undefined;
    if (!contents && styled) return makeError(ErrorCodes.V_INVALID_PARAM_VALUE || "V011",
        "Styled empty text is not supported until host persistence is verified.", "validate");
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
    // ops_text can be loaded independently of ops_element.
    var abRect = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
    var abTop = abRect[1];
    var abLeft = abRect[0];

    // Create text frame.
    //
    // OR05. Nothing cleaned up here: `textFrames.add()` returns an empty
    // frame, and both the position and the contents can throw against it —
    // measured, a non-numeric coordinate raises "Numeric value expected".
    // An exception left the empty frame on the page and escaped the handler.
    // The scope covers the allocation itself and every fallible step against
    // the frame, not just the two in the middle. The first version of this
    // migration left `textFrames.add()` and the naming outside the try, so a
    // rename that threw escaped the handler with the frame on the page and
    // the scope still open on the ownership stack — where the next scope
    // would have inherited it.
    var textScope = mcpOwnBegin("text_create");
    var textFrame, runVerification = [], runWarnings = [];
    try {
        textFrame = targetLayer.textFrames.add();
        mcpOwnAllocate(textScope, textFrame, "textFrame");
        textFrame.position = [abLeft + x, abTop - y];
        textFrame.contents = contents;

        // Assign ID + register in heap (H1 invariant)
        stampMcpId(textFrame, id);
        mcpOwnIdentify(textScope, textFrame, id);
        if (name) textFrame.name = name;
        if (contents) {
            textFrame.textRange.characterAttributes.size = fontSize;
            if (resolved.font) textFrame.textRange.characterAttributes.textFont = resolved.font;
            var parsedFill = _parseColorParam(params, "fill");
            if (parsedFill.color) textFrame.textRange.characterAttributes.fillColor = parsedFill.color;
            if (runs) _mcpRecordTextRunReadback(_mcpTextRunPlan(textFrame, runs), runVerification, runWarnings, id);
        }
    } catch (textError) {
        var textCleanup = mcpOwnCleanup(textScope);
        var textDetail = {};
        if (!textCleanup.ok) textDetail.cleanupFailures = textCleanup.failed;
        return makeError(ErrorCodes.R_APPLY_FAILED,
            "Failed to create/style text: " + textError.message, "apply", null, textDetail);
    }

    mcpOwnCommit(textScope);
    return {
        ok: true,
        id: id,
        warnings: resolved.warnings.concat(runs ? runs.warnings : [], runWarnings),
        data: {
            typename: "TextFrame",
            position: [x, y],
            contents: contents,
            runVerification: runVerification,
            font: resolved.report
        }
    };
});

// ==================== Text Set Content ====================

registerOpHandler("text_set_content", function (params, targets, ctx) {
    if (targets.length === 0) {
        return makeError(ErrorCodes.V_NO_SELECTION, "No text frames to modify", "apply");
    }

    var runs;
    try { runs = _mcpTextRuns(params); } catch (runError) { return makeError(ErrorCodes.V_INVALID_PARAM_VALUE || "V011", runError.message, "validate"); }
    if (!runs && params.contents === undefined && params.text === undefined) return makeError(ErrorCodes.V_INVALID_PARAM_VALUE || "V011", "contents or runs is required", "validate");
    var contents = runs ? runs.text : (params.contents || params.text || "");
    var modified = 0;
    var warnings = runs ? runs.warnings.slice(0) : [];
    warnings.push("Replacing contents uses Illustrator native formatting inheritance; prior mixed formatting is not guaranteed. Runs explicitly apply only their supplied attributes.");
    var failed = [], runVerification = [];
    var modifiedIds = [];
    var skippedIds = [];

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];
        var label = textTargetLabel(item, i);

        if (item.typename !== "TextFrame") {
            warnings.push("Target " + label + " is a " + item.typename +
                ", not a TextFrame; its content was not changed");
            skippedIds.push(label);
            continue;
        }

        try {
            item.contents = contents;
            modifiedIds.push(label);
            if (runs) _mcpRecordTextRunReadback(_mcpTextRunPlan(item, runs), runVerification, warnings, label);
            modified++;
        } catch (e) {
            warnings.push("Failed to set content on " + label + ": " + e.message);
            skippedIds.push(label);
            failed.push(label);
        }
    }

    var contentData = { modified: modified, modifiedIds: modifiedIds, runVerification: runVerification };
    if (skippedIds.length) contentData.skippedIds = skippedIds;
    if (failed.length) {
        var failure = makeError(ErrorCodes.R_APPLY_FAILED, "Content replacement or run application failed", "apply");
        failure.data = contentData;
        failure.effects = {created: [], modified: modifiedIds, deleted: [], complete: false};
        failure.warnings = warnings;
        return failure;
    }
    return { ok: true, data: contentData, warnings: warnings };
});

// ==================== Text Set Style ====================

registerOpHandler("text_set_style", function (params, targets, ctx) {
    if (targets.length === 0) {
        return { ok: true, data: { modified: 0 } };
    }

    var modified = 0;
    var warnings = [];
    var modifiedIds = [];
    var skippedIds = [];
    var applicationErrors = [];
    var partialTargets = [];

    var resolved = resolveTextFont(params);
    if (resolved.error) return resolved.error;
    var resolvedFont = resolved.font;
    warnings = warnings.concat(resolved.warnings);

    var runs, runPlans = [], runVerification = [];
    try {
        runs = _mcpTextRuns(params);
        if (runs) {
            warnings = warnings.concat(runs.warnings);
            for (var pi = 0; pi < targets.length; pi++) runPlans.push(targets[pi].typename === "TextFrame" ? _mcpTextRunPlan(targets[pi], runs) : null);
        }
    } catch (runError) { return makeError(ErrorCodes.V_INVALID_PARAM_VALUE || "V011", runError.message, "validate"); }

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];

        if (item.typename !== "TextFrame") {
            warnings.push("Target " + textTargetLabel(item, i) + " is a " +
                item.typename + ", not a TextFrame; it was not styled");
            skippedIds.push(textTargetLabel(item, i));
            continue;
        }

        var touched = false;
        try {
            if (params.fontSize !== undefined) {
                item.textRange.characterAttributes.size = params.fontSize;
                touched = true;
            }

            if (resolvedFont) {
                item.textRange.characterAttributes.textFont = resolvedFont;
                touched = true;
            }

            // Color via canonical _parseColorParam (fill:{r,g,b} or flat r,g,b)
            var parsedFill = _parseColorParam(params, "fill");
            if (parsedFill.color) {
                item.textRange.characterAttributes.fillColor = parsedFill.color;
                touched = true;
            }

            if (params.tracking !== undefined) {
                item.textRange.characterAttributes.tracking = params.tracking;
                touched = true;
            }

            if (runs) { touched = true; _mcpRecordTextRunReadback(runPlans[i], runVerification, warnings, textTargetLabel(item, i)); }
            modified++;
            modifiedIds.push(textTargetLabel(item, i));
        } catch (e) {
            warnings.push("Failed to style " + textTargetLabel(item, i) + ": " + e.message);
            if (touched) modifiedIds.push(textTargetLabel(item, i));
            partialTargets.push(textTargetLabel(item, i));
            applicationErrors.push(String(e));
        }
    }

    var styleData = { modified: modified, modifiedIds: modifiedIds, runVerification: runVerification };
    if (skippedIds.length) styleData.skippedIds = skippedIds;
    if (resolved.report) styleData.font = resolved.report;
    if (applicationErrors.length) {
        var failure = makeError(ErrorCodes.R_APPLY_FAILED, applicationErrors.join("; "), "apply");
        failure.data = styleData;
        failure.data.partiallyStyledTargets = partialTargets;
        failure.effects = {created: [], modified: modifiedIds, deleted: [], complete: false};
        failure.warnings = warnings;
        return failure;
    }
    return { ok: true, data: styleData, warnings: warnings };
});
