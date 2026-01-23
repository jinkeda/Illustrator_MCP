# Illustrator MCP v2.4 Implementation Plan

## Overview

Version 2.4 is an **incremental enhancement** that adopts valuable concepts from the v3.0 "Intent Compiler" proposal while preserving the proven "Scripting First" architecture. This plan adds new capabilities without breaking existing functionality.

### Design Principles (Unchanged)

1. **Scripting First** - `execute_script` remains the primary tool
2. **Thick Scripts, Thin Server** - Complex logic lives in ExtendScript
3. **~15 Core Tools** - New features added via libraries, not tool explosion
4. **Additive, Not Replacement** - All existing functionality preserved

### What We're Adopting from v3.0

| v3.0 Concept | v2.4 Implementation |
|--------------|---------------------|
| Asset Pre-Flight | New `analyze_assets` tool + library |
| Layout Presets | New `layout_presets.jsx` library |
| Map-First IR | Optional maps in Task Protocol |
| Semantic Actions | High-level `figure_compose` tool (optional) |
| Deterministic Geometry | Enhanced `geometry.jsx` library |

### What We're NOT Adopting

- Complete architecture rewrite
- "Illustrator as stateless renderer" model
- External geometry computation
- Intent Bridge / Compiler layer
- Strict LLM constraint layer

---

## Phase 1: Asset Pre-Flight System

**Goal:** Enable inspection of placed assets before operations
**Effort:** 3-4 days
**Risk:** Low (additive feature)

### 1.1 New Tool: `illustrator_analyze_assets`

Add a tool that extracts metadata from placed items and linked files.

**File:** `illustrator_mcp/tools/assets.py`

```python
from pydantic import BaseModel, Field
from typing import List, Optional, Literal

class AnalyzeAssetsInput(BaseModel):
    """Input for asset analysis."""
    scope: Literal["selection", "document", "layer"] = Field(
        default="document",
        description="What to analyze: selection, entire document, or specific layer"
    )
    layer: Optional[str] = Field(
        default=None,
        description="Layer name (required if scope='layer')"
    )
    include_embedded: bool = Field(
        default=True,
        description="Include embedded (non-linked) images"
    )

class AssetInfo(BaseModel):
    """Metadata for a single asset."""
    name: str
    item_type: str  # "PlacedItem", "RasterItem", "EmbeddedItem"
    file_path: Optional[str]  # None for embedded
    is_linked: bool
    bounds: dict  # {left, top, right, bottom, width, height}
    aspect_ratio: float
    orientation: Literal["landscape", "portrait", "square"]
    position: dict  # {x, y}
    layer_path: str
    # Detected properties
    has_transparency: Optional[bool]
    color_space: Optional[str]

class AssetManifest(BaseModel):
    """Complete asset analysis result."""
    document_name: str
    total_assets: int
    assets: dict[str, AssetInfo]  # Map by name for stable references
    summary: dict  # {by_type: {...}, by_orientation: {...}}
```

**Registration in `tools/__init__.py`:**
```python
from illustrator_mcp.tools.assets import illustrator_analyze_assets
```

### 1.2 New Library: `assets.jsx`

**File:** `illustrator_mcp/resources/scripts/assets.jsx`

```javascript
/**
 * Asset Analysis Library v1.0
 * Extracts metadata from placed items for pre-flight analysis
 *
 * @exports analyzeAssets, getAssetInfo, buildAssetManifest
 * @dependencies geometry
 */

function getAssetInfo(item) {
    var bounds = getVisibleBounds(item);  // from geometry.jsx
    var width = bounds[2] - bounds[0];
    var height = bounds[1] - bounds[3];  // Note: Y is inverted
    var aspectRatio = width / height;

    var orientation = "square";
    if (aspectRatio > 1.05) orientation = "landscape";
    else if (aspectRatio < 0.95) orientation = "portrait";

    var info = {
        name: item.name || "Unnamed",
        itemType: item.typename,
        filePath: null,
        isLinked: false,
        bounds: {
            left: bounds[0],
            top: bounds[1],
            right: bounds[2],
            bottom: bounds[3],
            width: width,
            height: Math.abs(height)
        },
        aspectRatio: aspectRatio,
        orientation: orientation,
        position: {x: item.position[0], y: item.position[1]},
        layerPath: getLayerPath(item)
    };

    // Handle linked files
    if (item.typename === "PlacedItem") {
        info.isLinked = true;
        try {
            info.filePath = item.file.fsName;
        } catch (e) {
            info.filePath = "[linked file unavailable]";
        }
    }

    return info;
}

function analyzeAssets(options) {
    var doc = app.activeDocument;
    var items = [];
    var scope = options.scope || "document";

    if (scope === "selection") {
        items = collectPlacedFromSelection();
    } else if (scope === "layer") {
        items = collectPlacedFromLayer(options.layer);
    } else {
        items = collectAllPlaced(doc, options.includeEmbedded !== false);
    }

    var assets = {};
    var byType = {};
    var byOrientation = {landscape: 0, portrait: 0, square: 0};

    for (var i = 0; i < items.length; i++) {
        var info = getAssetInfo(items[i]);
        var key = info.name || ("asset_" + i);

        // Ensure unique keys (map-first rule)
        if (assets[key]) {
            var suffix = 2;
            while (assets[key + "_" + suffix]) suffix++;
            key = key + "_" + suffix;
        }

        assets[key] = info;
        byType[info.itemType] = (byType[info.itemType] || 0) + 1;
        byOrientation[info.orientation]++;
    }

    return {
        documentName: doc.name,
        totalAssets: items.length,
        assets: assets,
        summary: {
            byType: byType,
            byOrientation: byOrientation
        }
    };
}
```

### 1.3 Update manifest.json

```json
{
  "libraries": {
    "assets": {
      "file": "assets.jsx",
      "dependencies": ["geometry"],
      "exports": ["analyzeAssets", "getAssetInfo", "buildAssetManifest", "collectAllPlaced"]
    }
  }
}
```

### 1.4 Acceptance Criteria

- [ ] `illustrator_analyze_assets` tool registered and functional
- [ ] Returns map-based asset manifest (not array)
- [ ] Correctly identifies linked vs embedded items
- [ ] Calculates aspect ratio and orientation
- [ ] Unit tests with mocked responses
- [ ] Integration test with real Illustrator document

---

## Phase 2: Layout Presets Library

**Goal:** Pre-defined layout configurations for common use cases
**Effort:** 4-5 days
**Risk:** Low (library addition)

### 2.1 New Library: `presets.jsx`

**File:** `illustrator_mcp/resources/scripts/presets.jsx`

```javascript
/**
 * Layout Presets Library v1.0
 * Pre-defined slot configurations for common layouts
 *
 * @exports PRESETS, getPreset, applyPreset, listPresets
 * @dependencies geometry, layout
 */

var PRESETS = {
    // Scientific figure presets
    "figure_2x2": {
        name: "2x2 Grid",
        description: "Four equal panels in 2x2 grid",
        slots: {
            "SLOT_A": {row: 0, col: 0, rowSpan: 1, colSpan: 1},
            "SLOT_B": {row: 0, col: 1, rowSpan: 1, colSpan: 1},
            "SLOT_C": {row: 1, col: 0, rowSpan: 1, colSpan: 1},
            "SLOT_D": {row: 1, col: 1, rowSpan: 1, colSpan: 1}
        },
        grid: {rows: 2, cols: 2},
        margins: {top: 20, right: 20, bottom: 20, left: 20},
        gutter: {horizontal: 15, vertical: 15},
        labelStyle: {position: "top-left", offset: 5, font: "Arial-BoldMT", size: 14}
    },

    "figure_3_horizontal": {
        name: "3 Panel Horizontal",
        description: "Three panels in horizontal row",
        slots: {
            "SLOT_A": {row: 0, col: 0},
            "SLOT_B": {row: 0, col: 1},
            "SLOT_C": {row: 0, col: 2}
        },
        grid: {rows: 1, cols: 3},
        margins: {top: 20, right: 20, bottom: 20, left: 20},
        gutter: {horizontal: 15, vertical: 15}
    },

    "figure_1_main_2_side": {
        name: "1 Main + 2 Side",
        description: "Large main panel with two smaller side panels",
        slots: {
            "SLOT_MAIN": {row: 0, col: 0, rowSpan: 2, colSpan: 2},
            "SLOT_SIDE_A": {row: 0, col: 2, rowSpan: 1, colSpan: 1},
            "SLOT_SIDE_B": {row: 1, col: 2, rowSpan: 1, colSpan: 1}
        },
        grid: {rows: 2, cols: 3},
        margins: {top: 20, right: 20, bottom: 20, left: 20},
        gutter: {horizontal: 15, vertical: 15}
    },

    // Presentation presets
    "slide_title_content": {
        name: "Title + Content",
        description: "Standard presentation slide layout",
        slots: {
            "SLOT_TITLE": {row: 0, col: 0, colSpan: 2, heightRatio: 0.15},
            "SLOT_CONTENT": {row: 1, col: 0, colSpan: 2, heightRatio: 0.85}
        },
        grid: {rows: 2, cols: 2},
        margins: {top: 40, right: 40, bottom: 40, left: 40}
    },

    // Poster presets
    "poster_a0_scientific": {
        name: "A0 Scientific Poster",
        description: "Standard scientific poster with 3 columns",
        documentSize: {width: 841, height: 1189, units: "mm"},
        slots: {
            "SLOT_HEADER": {row: 0, col: 0, colSpan: 3, heightRatio: 0.1},
            "SLOT_COL1": {row: 1, col: 0, heightRatio: 0.9},
            "SLOT_COL2": {row: 1, col: 1, heightRatio: 0.9},
            "SLOT_COL3": {row: 1, col: 2, heightRatio: 0.9}
        },
        grid: {rows: 2, cols: 3},
        margins: {top: 30, right: 30, bottom: 30, left: 30},
        gutter: {horizontal: 20, vertical: 20}
    }
};

function getPreset(presetName) {
    if (!PRESETS[presetName]) {
        throw new Error("Unknown preset: " + presetName + ". Available: " + listPresets().join(", "));
    }
    return PRESETS[presetName];
}

function listPresets() {
    var names = [];
    for (var key in PRESETS) {
        if (PRESETS.hasOwnProperty(key)) {
            names.push(key);
        }
    }
    return names;
}

function computeSlotGeometry(preset, artboardBounds) {
    // Compute absolute geometry for each slot based on preset and artboard
    var margins = preset.margins;
    var gutter = preset.gutter || {horizontal: 0, vertical: 0};
    var grid = preset.grid;

    var availWidth = (artboardBounds[2] - artboardBounds[0]) - margins.left - margins.right;
    var availHeight = Math.abs(artboardBounds[3] - artboardBounds[1]) - margins.top - margins.bottom;

    var cellWidth = (availWidth - (grid.cols - 1) * gutter.horizontal) / grid.cols;
    var cellHeight = (availHeight - (grid.rows - 1) * gutter.vertical) / grid.rows;

    var geometry = {};

    for (var slotId in preset.slots) {
        var slot = preset.slots[slotId];
        var colSpan = slot.colSpan || 1;
        var rowSpan = slot.rowSpan || 1;

        var x = artboardBounds[0] + margins.left + slot.col * (cellWidth + gutter.horizontal);
        var y = artboardBounds[1] - margins.top - slot.row * (cellHeight + gutter.vertical);
        var w = colSpan * cellWidth + (colSpan - 1) * gutter.horizontal;
        var h = rowSpan * cellHeight + (rowSpan - 1) * gutter.vertical;

        geometry[slotId] = {
            x: x,
            y: y,
            width: w,
            height: h,
            bounds: [x, y, x + w, y - h]
        };
    }

    return geometry;
}

function applyPreset(presetName, assignments, options) {
    // assignments: {"SLOT_A": "asset_name_or_item", ...}
    var preset = getPreset(presetName);
    var doc = app.activeDocument;
    var artboard = doc.artboards[doc.artboards.getActiveArtboardIndex()];
    var artboardBounds = artboard.artboardRect;

    var geometry = computeSlotGeometry(preset, artboardBounds);
    var results = {applied: [], errors: []};

    for (var slotId in assignments) {
        if (!geometry[slotId]) {
            results.errors.push({slot: slotId, error: "Unknown slot in preset"});
            continue;
        }

        var target = assignments[slotId];
        var slotGeo = geometry[slotId];

        try {
            var item = resolveAssetReference(target);
            fitItemToSlot(item, slotGeo, options.fitMode || "contain");
            results.applied.push({slot: slotId, item: item.name});
        } catch (e) {
            results.errors.push({slot: slotId, error: e.message});
        }
    }

    return results;
}
```

### 2.2 Slot Assignment Logic

**File:** `illustrator_mcp/resources/scripts/slots.jsx`

```javascript
/**
 * Slot Assignment Library v1.0
 * Fit assets into computed slot geometry
 *
 * @exports fitItemToSlot, resolveAssetReference
 * @dependencies geometry
 */

function fitItemToSlot(item, slotGeometry, fitMode) {
    // fitMode: "contain" (fit inside, maintain aspect) or "cover" (fill slot, crop)
    var itemBounds = getVisibleBounds(item);
    var itemWidth = itemBounds[2] - itemBounds[0];
    var itemHeight = Math.abs(itemBounds[3] - itemBounds[1]);
    var itemAspect = itemWidth / itemHeight;

    var slotAspect = slotGeometry.width / slotGeometry.height;
    var scale;

    if (fitMode === "cover") {
        // Scale to fill slot (may crop)
        scale = Math.max(slotGeometry.width / itemWidth, slotGeometry.height / itemHeight);
    } else {
        // Default: contain (fit inside)
        scale = Math.min(slotGeometry.width / itemWidth, slotGeometry.height / itemHeight);
    }

    // Apply scale
    var scalePercent = scale * 100;
    item.resize(scalePercent, scalePercent);

    // Center in slot
    var newBounds = getVisibleBounds(item);
    var newWidth = newBounds[2] - newBounds[0];
    var newHeight = Math.abs(newBounds[3] - newBounds[1]);

    var targetX = slotGeometry.x + (slotGeometry.width - newWidth) / 2;
    var targetY = slotGeometry.y - (slotGeometry.height - newHeight) / 2;

    item.position = [targetX, targetY];

    return {
        scale: scale,
        position: [targetX, targetY],
        finalBounds: getVisibleBounds(item)
    };
}

function resolveAssetReference(reference) {
    // Reference can be: item name, layer path, or PlacedItem index
    var doc = app.activeDocument;

    // Try by name first
    for (var i = 0; i < doc.pageItems.length; i++) {
        if (doc.pageItems[i].name === reference) {
            return doc.pageItems[i];
        }
    }

    // Try as selection index
    if (typeof reference === "number" && doc.selection.length > reference) {
        return doc.selection[reference];
    }

    throw new Error("Could not resolve asset reference: " + reference);
}
```

### 2.3 Update manifest.json

```json
{
  "libraries": {
    "presets": {
      "file": "presets.jsx",
      "dependencies": ["geometry", "layout"],
      "exports": ["PRESETS", "getPreset", "applyPreset", "listPresets", "computeSlotGeometry"]
    },
    "slots": {
      "file": "slots.jsx",
      "dependencies": ["geometry"],
      "exports": ["fitItemToSlot", "resolveAssetReference"]
    }
  }
}
```

### 2.4 Acceptance Criteria

- [ ] `presets.jsx` library with 5+ preset definitions
- [ ] `computeSlotGeometry()` correctly calculates absolute positions
- [ ] `fitItemToSlot()` implements contain/cover modes
- [ ] `applyPreset()` handles partial assignments gracefully
- [ ] Unit tests for geometry calculations
- [ ] Documentation with visual examples

---

## Phase 3: High-Level Figure Composition Tool (Optional)

**Goal:** Semantic actions interface for figure composition
**Effort:** 3-4 days
**Risk:** Medium (new tool pattern)

### 3.1 New Tool: `illustrator_figure_compose`

This is an **optional high-level tool** that compiles semantic actions to ExtendScript. It demonstrates how to add domain-specific workflows without changing the architecture.

**File:** `illustrator_mcp/tools/compose.py`

```python
from pydantic import BaseModel, Field
from typing import List, Literal, Optional, Union

class AssignAssetAction(BaseModel):
    """Assign an asset to a slot."""
    action: Literal["assign_asset"] = "assign_asset"
    asset: str = Field(..., description="Asset name or reference")
    slot: str = Field(..., description="Slot ID from preset (e.g., 'SLOT_A')")
    fit_mode: Literal["contain", "cover"] = Field(default="contain")

class SwapSlotsAction(BaseModel):
    """Swap contents of two slots."""
    action: Literal["swap_slots"] = "swap_slots"
    slot1: str
    slot2: str

class AddLabelAction(BaseModel):
    """Add panel label to a slot."""
    action: Literal["add_label"] = "add_label"
    slot: str
    label: str = Field(..., description="Label text (e.g., 'A', 'B', 'Fig. 1')")
    position: Literal["top-left", "top-right", "bottom-left", "bottom-right"] = "top-left"

class SetMarginsAction(BaseModel):
    """Update preset margins."""
    action: Literal["set_margins"] = "set_margins"
    top: Optional[float] = None
    right: Optional[float] = None
    bottom: Optional[float] = None
    left: Optional[float] = None

# Union of all action types
FigureAction = Union[AssignAssetAction, SwapSlotsAction, AddLabelAction, SetMarginsAction]

class FigureComposeInput(BaseModel):
    """Input for figure composition."""
    preset: str = Field(..., description="Layout preset name (e.g., 'figure_2x2')")
    actions: List[FigureAction] = Field(..., description="Semantic actions to execute")
    dry_run: bool = Field(default=False, description="Preview without applying changes")

@mcp.tool(name="illustrator_figure_compose")
async def illustrator_figure_compose(params: FigureComposeInput) -> str:
    """
    Compose a figure using semantic actions and a layout preset.

    This high-level tool compiles semantic intent into ExtendScript.
    Use this for scientific figure composition workflows.

    Example:
        preset: "figure_2x2"
        actions: [
            {"action": "assign_asset", "asset": "graph_1", "slot": "SLOT_A"},
            {"action": "assign_asset", "asset": "graph_2", "slot": "SLOT_B"},
            {"action": "add_label", "slot": "SLOT_A", "label": "A"},
            {"action": "add_label", "slot": "SLOT_B", "label": "B"}
        ]
    """
    # Compile actions to ExtendScript
    script = compile_figure_actions(params.preset, params.actions, params.dry_run)

    # Execute via existing infrastructure
    response = await execute_script_with_context(
        script=script,
        includes=["presets", "slots", "geometry"],
        command=CommandMetadata(
            command_type="figure_compose",
            tool_name="illustrator_figure_compose",
            params=params.model_dump()
        )
    )
    return response
```

### 3.2 Action Compiler

**File:** `illustrator_mcp/tools/compose_compiler.py`

```python
"""
Compiles semantic figure actions to ExtendScript.
This keeps all compilation logic in Python, not JSX.
"""

def compile_figure_actions(preset: str, actions: list, dry_run: bool) -> str:
    """Compile semantic actions to executable ExtendScript."""

    lines = [
        "(function() {",
        "    var preset = getPreset('%s');" % preset,
        "    var doc = app.activeDocument;",
        "    var artboard = doc.artboards[doc.artboards.getActiveArtboardIndex()];",
        "    var geometry = computeSlotGeometry(preset, artboard.artboardRect);",
        "    var results = {ok: true, actions: [], errors: []};",
        ""
    ]

    for i, action in enumerate(actions):
        action_script = compile_single_action(action, i, dry_run)
        lines.append(action_script)

    lines.extend([
        "",
        "    return JSON.stringify(results);",
        "})();"
    ])

    return "\n".join(lines)

def compile_single_action(action: dict, index: int, dry_run: bool) -> str:
    """Compile a single action to ExtendScript."""
    action_type = action.get("action")

    if action_type == "assign_asset":
        return compile_assign_asset(action, index, dry_run)
    elif action_type == "swap_slots":
        return compile_swap_slots(action, index, dry_run)
    elif action_type == "add_label":
        return compile_add_label(action, index, dry_run)
    elif action_type == "set_margins":
        return compile_set_margins(action, index, dry_run)
    else:
        return "    results.errors.push({index: %d, error: 'Unknown action: %s'});" % (index, action_type)

def compile_assign_asset(action: dict, index: int, dry_run: bool) -> str:
    asset = action["asset"]
    slot = action["slot"]
    fit_mode = action.get("fit_mode", "contain")

    if dry_run:
        return """    results.actions.push({
        index: %d,
        action: 'assign_asset',
        asset: '%s',
        slot: '%s',
        geometry: geometry['%s'],
        dryRun: true
    });""" % (index, asset, slot, slot)

    return """    try {
        var item_%d = resolveAssetReference('%s');
        var slotGeo_%d = geometry['%s'];
        if (!slotGeo_%d) throw new Error('Unknown slot: %s');
        var fitResult_%d = fitItemToSlot(item_%d, slotGeo_%d, '%s');
        results.actions.push({
            index: %d,
            action: 'assign_asset',
            asset: '%s',
            slot: '%s',
            result: fitResult_%d
        });
    } catch (e) {
        results.errors.push({index: %d, action: 'assign_asset', error: e.message});
    }""" % (index, asset, index, slot, index, slot, index, index, index, fit_mode,
            index, asset, slot, index, index)
```

### 3.3 Acceptance Criteria

- [ ] `illustrator_figure_compose` tool registered
- [ ] Supports 4 action types (assign, swap, label, margins)
- [ ] `dry_run` mode returns plan without executing
- [ ] Compilation is deterministic (same input → same script)
- [ ] Clear error messages for invalid actions
- [ ] Integration test with real figure composition

---

## Phase 4: Task Protocol Enhancements

**Goal:** Adopt map-first IR patterns where beneficial
**Effort:** 2-3 days
**Risk:** Low (backward compatible)

### 4.1 Map-Based Item Collections

Update `task_executor.jsx` to optionally return items as maps instead of arrays.

```javascript
// New option in TaskPayload
options: {
    outputFormat: "map"  // "array" (default) or "map"
}

// When outputFormat === "map", artifacts.items becomes:
{
    "Panel_A": {itemRef: {...}, result: {...}},
    "Panel_B": {itemRef: {...}, result: {...}}
}
// Instead of:
[
    {itemRef: {...}, result: {...}},
    {itemRef: {...}, result: {...}}
]
```

### 4.2 Stable Key Generation

```javascript
function generateStableKey(item, index) {
    // Priority: explicit name > MCP tag > generated
    if (item.name && item.name.indexOf("@mcp:") === -1) {
        return sanitizeKey(item.name);
    }

    var tags = parseMcpTags(item);
    if (tags.id) {
        return tags.id;
    }

    // Fallback: type + index
    return item.typename + "_" + index;
}

function sanitizeKey(name) {
    // Make safe for JSON object keys
    return name.replace(/[^a-zA-Z0-9_]/g, "_");
}
```

### 4.3 Acceptance Criteria

- [ ] `outputFormat: "map"` option implemented
- [ ] Backward compatible (array remains default)
- [ ] Stable key generation logic documented
- [ ] Protocol version bumped to 2.4.0
- [ ] Updated PROTOCOL.md documentation

---

## Phase 5: Enhanced Context Tools

**Goal:** Better document analysis for AI decision-making
**Effort:** 2 days
**Risk:** Low (additive)

### 5.1 Enhanced `get_document_structure`

Add layout analysis to the existing structure response:

```python
class DocumentStructureOutput(BaseModel):
    # Existing fields...
    layers: List[LayerInfo]
    artboards: List[ArtboardInfo]

    # New fields for v2.4
    layout_analysis: Optional[LayoutAnalysis] = None

class LayoutAnalysis(BaseModel):
    """Automatic layout detection."""
    detected_grid: Optional[GridInfo]  # Detected rows/cols
    item_clusters: List[ClusterInfo]   # Spatially grouped items
    suggested_preset: Optional[str]     # Best matching preset
    alignment_issues: List[str]         # Misaligned items
```

### 5.2 New: `illustrator_suggest_layout`

```python
@mcp.tool(name="illustrator_suggest_layout")
async def illustrator_suggest_layout(params: SuggestLayoutInput) -> str:
    """
    Analyze current document and suggest appropriate layout presets.

    Returns:
        - Detected grid structure
        - Best matching presets
        - Recommendations for improvement
    """
```

### 5.3 Acceptance Criteria

- [ ] Layout analysis added to document structure
- [ ] Grid detection algorithm implemented
- [ ] Preset matching logic functional
- [ ] Clear suggestions for common issues

---

## Phase 6: Documentation & Polish

**Goal:** Complete documentation and examples
**Effort:** 2 days
**Risk:** None

### 6.1 Update PROTOCOL.md

- Add v2.4 features section
- Document map-based output format
- Add asset pre-flight examples

### 6.2 Update README.md

- Add v2.4 changelog entry
- Document new tools
- Add figure composition examples

### 6.3 Create PRESETS.md

Document all available presets with visual diagrams.

### 6.4 Example Scripts

Create example scripts in `examples/`:
- `scientific_figure_2x2.py`
- `poster_layout.py`
- `asset_analysis_workflow.py`

---

## Timeline Summary

| Phase | Description | Effort | Dependencies |
|-------|-------------|--------|--------------|
| **1** | Asset Pre-Flight System | 3-4 days | None |
| **2** | Layout Presets Library | 4-5 days | Phase 1 (geometry) |
| **3** | Figure Composition Tool | 3-4 days | Phase 1, 2 |
| **4** | Task Protocol Enhancements | 2-3 days | None |
| **5** | Enhanced Context Tools | 2 days | Phase 2 |
| **6** | Documentation & Polish | 2 days | All |

**Total Estimated Effort:** 16-20 days

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Geometry calculation edge cases | Medium | Medium | Extensive unit tests |
| ExtendScript compatibility | Low | Medium | Test on Illustrator 2021-2024 |
| Breaking existing workflows | Low | High | All features additive |
| Scope creep | Medium | Medium | Strict phase boundaries |

---

## Success Metrics

1. **Backward Compatibility:** All existing tests pass
2. **New Tool Coverage:** >80% test coverage for new tools
3. **Performance:** Asset analysis <2s for 50 items
4. **Adoption:** Figure compose tool reduces script complexity by 50%+ for target use cases

---

## Future Considerations (v2.5+)

- Sidecar metadata protocol for matplotlib integration
- Visual layout editor (web UI)
- Undo/redo stack for figure actions
- Template library sharing

---

## Appendix: File Changes Summary

### New Files
- `illustrator_mcp/tools/assets.py`
- `illustrator_mcp/tools/compose.py`
- `illustrator_mcp/tools/compose_compiler.py`
- `illustrator_mcp/resources/scripts/assets.jsx`
- `illustrator_mcp/resources/scripts/presets.jsx`
- `illustrator_mcp/resources/scripts/slots.jsx`
- `docs/PRESETS.md`
- `examples/scientific_figure_2x2.py`

### Modified Files
- `illustrator_mcp/tools/__init__.py` (register new tools)
- `illustrator_mcp/resources/scripts/manifest.json` (add libraries)
- `illustrator_mcp/resources/scripts/task_executor.jsx` (map output)
- `illustrator_mcp/tools/context.py` (layout analysis)
- `PROTOCOL.md` (v2.4 additions)
- `README.md` (changelog, examples)

### Test Files
- `tests/test_assets.py`
- `tests/test_presets.py`
- `tests/test_compose.py`
- `tests/test_layout_analysis.py`
