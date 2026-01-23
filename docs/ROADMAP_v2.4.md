# Illustrator MCP v2.4 Implementation Plan

## Overview

Version 2.4 adds **two new ExtendScript libraries** for asset analysis and layout presets. No new tools. No architecture changes. Pure script-based enhancements.

### Design Principles

1. **Scripting First** - No new tools, just libraries for `execute_script`
2. **Illustrator is Truth** - No external state files
3. **Keep It Simple** - Libraries only, minimal Python changes

---

## What's New in v2.4

| Addition | Type | Purpose |
|----------|------|---------|
| `assets.jsx` | Library | Analyze placed items (bounds, aspect ratio, orientation) |
| `presets.jsx` | Library | Pre-defined layouts with slot geometry |

**That's it.** Two libraries. Users access them via the existing `execute_script` tool with `includes: ["assets"]` or `includes: ["presets"]`.

---

## Phase 1: Asset Analysis Library

**Effort:** 2-3 days

### New File: `illustrator_mcp/resources/scripts/assets.jsx`

```javascript
/**
 * Asset Analysis Library v1.0
 * @exports analyzeAssets, getAssetInfo
 * @dependencies geometry
 */

function getAssetInfo(item) {
    var bounds = getVisibleBounds(item);
    var width = bounds[2] - bounds[0];
    var height = Math.abs(bounds[1] - bounds[3]);
    var aspectRatio = width / height;

    var orientation = "square";
    if (aspectRatio > 1.05) orientation = "landscape";
    else if (aspectRatio < 0.95) orientation = "portrait";

    return {
        name: item.name || "Unnamed",
        type: item.typename,
        bounds: {left: bounds[0], top: bounds[1], right: bounds[2], bottom: bounds[3]},
        width: width,
        height: height,
        aspectRatio: aspectRatio,
        orientation: orientation,
        position: {x: item.position[0], y: item.position[1]},
        isLinked: item.typename === "PlacedItem"
    };
}

function analyzeAssets(scope) {
    // scope: "selection" | "document" | layer name
    var doc = app.activeDocument;
    var items = [];

    if (scope === "selection") {
        for (var i = 0; i < doc.selection.length; i++) {
            if (isPlacedOrRaster(doc.selection[i])) {
                items.push(doc.selection[i]);
            }
        }
    } else if (scope === "document") {
        items = collectAllPlaced(doc);
    } else {
        // Assume layer name
        try {
            var layer = doc.layers.getByName(scope);
            items = collectPlacedFromLayer(layer);
        } catch (e) {
            return {error: "Layer not found: " + scope};
        }
    }

    var results = [];
    for (var i = 0; i < items.length; i++) {
        results.push(getAssetInfo(items[i]));
    }

    return {
        count: results.length,
        assets: results
    };
}

function collectAllPlaced(doc) {
    var items = [];
    for (var i = 0; i < doc.placedItems.length; i++) {
        items.push(doc.placedItems[i]);
    }
    for (var i = 0; i < doc.rasterItems.length; i++) {
        items.push(doc.rasterItems[i]);
    }
    return items;
}

function isPlacedOrRaster(item) {
    return item.typename === "PlacedItem" || item.typename === "RasterItem";
}
```

### Usage Example

```javascript
// Via execute_script with includes: ["assets", "geometry"]
var manifest = analyzeAssets("document");
return JSON.stringify(manifest);

// Returns:
// {
//   "count": 3,
//   "assets": [
//     {"name": "panel_a", "aspectRatio": 1.5, "orientation": "landscape", ...},
//     {"name": "panel_b", "aspectRatio": 0.8, "orientation": "portrait", ...}
//   ]
// }
```

### Acceptance Criteria

- [ ] `analyzeAssets()` works with selection, document, and layer scopes
- [ ] Returns aspect ratio and orientation for each asset
- [ ] Added to `manifest.json` with `geometry` dependency

---

## Phase 2: Layout Presets Library

**Effort:** 3-4 days

### New File: `illustrator_mcp/resources/scripts/presets.jsx`

```javascript
/**
 * Layout Presets Library v1.0
 * @exports PRESETS, getPreset, applyPreset, computeSlotGeometry
 * @dependencies geometry
 */

var PRESETS = {
    "2x2": {
        name: "2x2 Grid",
        grid: {rows: 2, cols: 2},
        margins: {top: 20, right: 20, bottom: 20, left: 20},
        gutter: 15
    },
    "3x1": {
        name: "3 Horizontal",
        grid: {rows: 1, cols: 3},
        margins: {top: 20, right: 20, bottom: 20, left: 20},
        gutter: 15
    },
    "1x3": {
        name: "3 Vertical",
        grid: {rows: 3, cols: 1},
        margins: {top: 20, right: 20, bottom: 20, left: 20},
        gutter: 15
    },
    "2x3": {
        name: "2x3 Grid",
        grid: {rows: 2, cols: 3},
        margins: {top: 20, right: 20, bottom: 20, left: 20},
        gutter: 15
    }
};

function getPreset(name) {
    if (!PRESETS[name]) {
        throw new Error("Unknown preset: " + name);
    }
    return PRESETS[name];
}

function computeSlotGeometry(presetName, artboardRect) {
    var preset = getPreset(presetName);
    var m = preset.margins;
    var g = preset.gutter;
    var rows = preset.grid.rows;
    var cols = preset.grid.cols;

    var left = artboardRect[0];
    var top = artboardRect[1];
    var right = artboardRect[2];
    var bottom = artboardRect[3];

    var availW = (right - left) - m.left - m.right;
    var availH = Math.abs(bottom - top) - m.top - m.bottom;

    var cellW = (availW - (cols - 1) * g) / cols;
    var cellH = (availH - (rows - 1) * g) / rows;

    var slots = [];
    for (var row = 0; row < rows; row++) {
        for (var col = 0; col < cols; col++) {
            var x = left + m.left + col * (cellW + g);
            var y = top - m.top - row * (cellH + g);
            slots.push({
                row: row,
                col: col,
                x: x,
                y: y,
                width: cellW,
                height: cellH
            });
        }
    }

    return {
        preset: presetName,
        slots: slots,
        cellSize: {width: cellW, height: cellH}
    };
}

function fitToSlot(item, slot, mode) {
    // mode: "contain" (default) or "cover"
    mode = mode || "contain";

    var bounds = getVisibleBounds(item);
    var itemW = bounds[2] - bounds[0];
    var itemH = Math.abs(bounds[1] - bounds[3]);

    var scale;
    if (mode === "cover") {
        scale = Math.max(slot.width / itemW, slot.height / itemH);
    } else {
        scale = Math.min(slot.width / itemW, slot.height / itemH);
    }

    item.resize(scale * 100, scale * 100);

    // Center in slot
    var newBounds = getVisibleBounds(item);
    var newW = newBounds[2] - newBounds[0];
    var newH = Math.abs(newBounds[1] - newBounds[3]);

    item.position = [
        slot.x + (slot.width - newW) / 2,
        slot.y - (slot.height - newH) / 2
    ];
}

function applyPreset(presetName, items, mode) {
    // items: array of PageItems to arrange
    var doc = app.activeDocument;
    var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()];
    var geo = computeSlotGeometry(presetName, ab.artboardRect);

    var results = [];
    var count = Math.min(items.length, geo.slots.length);

    for (var i = 0; i < count; i++) {
        fitToSlot(items[i], geo.slots[i], mode);
        results.push({
            item: items[i].name,
            slot: i,
            position: items[i].position
        });
    }

    return {
        preset: presetName,
        arranged: results,
        overflow: items.length > geo.slots.length ? items.length - geo.slots.length : 0
    };
}
```

### Usage Example

```javascript
// Via execute_script with includes: ["presets", "geometry"]

// 1. Preview slot geometry
var geo = computeSlotGeometry("2x2", app.activeDocument.artboards[0].artboardRect);
return JSON.stringify(geo);

// 2. Arrange selected items in 2x2 grid
var items = [];
for (var i = 0; i < app.activeDocument.selection.length; i++) {
    items.push(app.activeDocument.selection[i]);
}
var result = applyPreset("2x2", items, "contain");
return JSON.stringify(result);
```

### Acceptance Criteria

- [ ] 4 basic presets defined (2x2, 3x1, 1x3, 2x3)
- [ ] `computeSlotGeometry()` returns correct positions
- [ ] `fitToSlot()` supports contain/cover modes
- [ ] `applyPreset()` arranges items in grid
- [ ] Added to `manifest.json` with `geometry` dependency

---

## Phase 3: Update Manifest & Test

**Effort:** 1 day

### Update `manifest.json`

```json
{
  "libraries": {
    "geometry": { ... },
    "selection": { ... },
    "layout": { ... },
    "task_executor": { ... },
    "assets": {
      "file": "assets.jsx",
      "dependencies": ["geometry"],
      "exports": ["analyzeAssets", "getAssetInfo", "collectAllPlaced"]
    },
    "presets": {
      "file": "presets.jsx",
      "dependencies": ["geometry"],
      "exports": ["PRESETS", "getPreset", "computeSlotGeometry", "fitToSlot", "applyPreset"]
    }
  }
}
```

### Update README Changelog

```markdown
## v2.4.0

### New Libraries
- **assets.jsx** - Analyze placed items (bounds, aspect ratio, orientation)
- **presets.jsx** - Pre-defined grid layouts with slot geometry

### Usage
```javascript
// Analyze assets
var manifest = analyzeAssets("document");

// Apply 2x2 layout to selection
var result = applyPreset("2x2", doc.selection, "contain");
```
```

---

## Summary

| Phase | What | Effort |
|-------|------|--------|
| 1 | `assets.jsx` library | 2-3 days |
| 2 | `presets.jsx` library | 3-4 days |
| 3 | Manifest + docs | 1 day |

**Total: 6-8 days**

### What We're NOT Doing

- ❌ New tools (stays at ~15)
- ❌ External state files
- ❌ Task Protocol changes
- ❌ Python-side compilers
- ❌ Complex action systems

### What We Get

- ✅ Asset metadata before operations
- ✅ Quick grid layouts
- ✅ Reusable via `includes`
- ✅ Script-based, no drift problems
- ✅ Simple, focused, shippable
