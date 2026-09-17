/**
 * symbols.jsx — read-only inspection of symbol definitions and instances.
 *
 * @requires polyfills (JSON)
 *
 * Checking what a symbol contains used to mean placing an instance and
 * expanding a temporary copy. That is a mutation performed only to enable a
 * read, it puts expanded artwork wherever Illustrator decides to put it, and
 * the audit copy then has to be found and removed again. Everything here
 * reads: nothing is placed, expanded, selected or deleted.
 *
 * A symbol definition is reachable through `symbol.symbolArt`, which is a
 * live group whose contents can be walked without instantiating anything.
 */

/**
 * Summarise one page item without recursing into a group's children.
 * @param {PageItem} item
 * @returns {Object}
 */
function mcpSymbolDescribeItem(item) {
    var out = {
        typename: item.typename,
        name: null,
        hidden: false,
        locked: false,
        opacity: null,
        bounds: null
    };
    try { out.name = item.name || null; } catch (e) {}
    try { out.hidden = item.hidden === true; } catch (e) {}
    try { out.locked = item.locked === true; } catch (e) {}
    try { out.opacity = item.opacity; } catch (e) {}
    try {
        var b = item.visibleBounds;
        // Illustrator native, Y-up: [left, top, right, bottom].
        out.bounds = [b[0], b[1], b[2], b[3]];
    } catch (e) {}
    try {
        if (item.typename === "TextFrame") { out.contents = item.contents; }
    } catch (e) {}
    return out;
}

/**
 * Walk a symbol definition's artwork.
 * @param {Object} art - symbol.symbolArt
 * @param {number} maxItems - cap on items reported
 * @returns {Object} {items: [], truncated: bool, total: number}
 */
function mcpSymbolContents(art, maxItems) {
    var items = [];
    var total = 0;
    var truncated = false;

    function walk(container, depth) {
        var children;
        try { children = container.pageItems; } catch (e) { return; }
        for (var i = 0; i < children.length; i++) {
            var child = children[i];
            total++;
            if (items.length < maxItems) {
                var described = mcpSymbolDescribeItem(child);
                described.depth = depth;
                items.push(described);
            } else {
                truncated = true;
            }
            if (child.typename === "GroupItem" && depth < 8) {
                walk(child, depth + 1);
            }
        }
    }

    walk(art, 0);
    return { items: items, truncated: truncated, total: total };
}

/**
 * List symbol definitions in the active document.
 * @param {Object} options - {includeContents: bool, maxItems: number, name: string|null}
 * @returns {string} JSON
 */
function mcpSymbolDefinitions(options) {
    options = options || {};
    var maxItems = options.maxItems || 50;
    var wanted = options.name || null;
    var doc = app.activeDocument;
    var out = [];

    for (var i = 0; i < doc.symbols.length; i++) {
        var sym = doc.symbols[i];
        var name = null;
        try { name = sym.name; } catch (e) {}
        if (wanted !== null && name !== wanted) continue;

        var entry = { index: i, name: name, registrationPoint: null };
        try { entry.registrationPoint = String(sym.registrationPoint); } catch (e) {}

        if (options.includeContents) {
            try {
                var summary = mcpSymbolContents(sym.symbolArt, maxItems);
                entry.contents = summary.items;
                entry.itemCount = summary.total;
                entry.truncated = summary.truncated;
            } catch (e) {
                entry.contents = null;
                entry.contentsError = String(e);
            }
        }
        out.push(entry);
    }

    return JSON.stringify({
        ok: true,
        definitions: out,
        definitionCount: doc.symbols.length
    });
}

/**
 * List placed symbol instances and the transform each one carries.
 *
 * The transform is derived from the instance's bounds against its
 * definition's bounds, because Illustrator does not expose an instance
 * matrix directly. Scale is therefore reported as a ratio and is null when
 * the definition has no measurable size.
 *
 * @param {Object} options - {name: string|null, maxInstances: number}
 * @returns {string} JSON
 */
function mcpSymbolInstances(options) {
    options = options || {};
    var wanted = options.name || null;
    var cap = options.maxInstances || 200;
    var doc = app.activeDocument;

    // Definition sizes, so instance scale can be expressed against them.
    var defSize = {};
    for (var d = 0; d < doc.symbols.length; d++) {
        try {
            var dn = doc.symbols[d].name;
            var db = doc.symbols[d].symbolArt.visibleBounds;
            defSize[dn] = [db[2] - db[0], Math.abs(db[3] - db[1])];
        } catch (e) {}
    }

    var out = [];
    var total = 0;
    var truncated = false;
    var items = doc.symbolItems;
    for (var i = 0; i < items.length; i++) {
        var inst = items[i];
        var symName = null;
        try { symName = inst.symbol.name; } catch (e) {}
        if (wanted !== null && symName !== wanted) continue;
        total++;
        if (out.length >= cap) { truncated = true; continue; }

        var entry = {
            symbol: symName,
            name: null,
            position: null,
            width: null,
            height: null,
            scale: null,
            rotationKnown: false,
            layer: null,
            hidden: false,
            locked: false
        };
        try { entry.name = inst.name || null; } catch (e) {}
        try { entry.position = [inst.left, inst.top]; } catch (e) {}
        try { entry.width = inst.width; } catch (e) {}
        try { entry.height = inst.height; } catch (e) {}
        try { entry.layer = inst.layer.name; } catch (e) {}
        try { entry.hidden = inst.hidden === true; } catch (e) {}
        try { entry.locked = inst.locked === true; } catch (e) {}
        try {
            var base = defSize[symName];
            if (base && base[0] > 0 && base[1] > 0) {
                entry.scale = [
                    (inst.width / base[0]) * 100,
                    (inst.height / base[1]) * 100
                ];
            }
        } catch (e) {}
        out.push(entry);
    }

    return JSON.stringify({
        ok: true,
        instances: out,
        instanceCount: total,
        truncated: truncated,
        // Illustrator exposes no instance matrix, so a rotated instance
        // reports its bounding box, not its angle. Said plainly rather than
        // left for the caller to infer from surprising numbers.
        note: "scale is derived from bounds; rotation is not recoverable"
    });
}
