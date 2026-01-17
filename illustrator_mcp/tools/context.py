"""
Context and state inspection tools for Adobe Illustrator.

These tools help agents understand the current document state before writing scripts.
Following the blender-mcp pattern (like get_scene_info).
"""

from pydantic import BaseModel, Field, ConfigDict

from illustrator_mcp.shared import mcp
from illustrator_mcp.proxy_client import execute_script_with_context, format_response


@mcp.tool(
    name="illustrator_get_document_structure",
    annotations={
        "title": "Get Document Structure",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def illustrator_get_document_structure() -> str:
    """
    Get the complete document structure as a JSON tree.
    
    Returns layers, sublayers, and items with their names, types, positions, and properties.
    Essential for understanding canvas state before writing modification scripts.
    
    Returns:
        JSON with:
        - document: name, width, height, artboards
        - layers: array of layer objects with:
            - name, visible, locked
            - items: array of {name, type, position, bounds}
    
    Use this before writing scripts that modify existing objects.
    """
    script = """
    (function() {
        var doc = app.activeDocument;
        
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
            
            // Get fill/stroke for path items
            if (item.typename === "PathItem") {
                info.filled = item.filled;
                info.stroked = item.stroked;
            }
            
            // Get text content for text frames
            if (item.typename === "TextFrame") {
                info.contents = item.contents.substring(0, 50);
            }
            
            return info;
        }
        
        function getLayerInfo(layer, maxItems) {
            var layerInfo = {
                name: layer.name,
                visible: layer.visible,
                locked: layer.locked,
                itemCount: layer.pageItems.length,
                items: []
            };
            
            // Limit items per layer to avoid huge responses
            var itemLimit = Math.min(layer.pageItems.length, maxItems);
            for (var i = 0; i < itemLimit; i++) {
                var itemInfo = getItemInfo(layer.pageItems[i], 2, 0);
                if (itemInfo) layerInfo.items.push(itemInfo);
            }
            
            if (layer.pageItems.length > maxItems) {
                layerInfo.truncated = true;
                layerInfo.totalItems = layer.pageItems.length;
            }
            
            // Get sublayers
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
                artboardCount: doc.artboards.length,
                artboards: []
            },
            layers: []
        };
        
        // Get artboards
        for (var a = 0; a < doc.artboards.length; a++) {
            var ab = doc.artboards[a];
            result.document.artboards.push({
                name: ab.name,
                bounds: ab.artboardRect
            });
        }
        
        // Get layers (limit to 20, 50 items each)
        var layerLimit = Math.min(doc.layers.length, 20);
        for (var i = 0; i < layerLimit; i++) {
            result.layers.push(getLayerInfo(doc.layers[i], 50));
        }
        
        if (doc.layers.length > 20) {
            result.layersTruncated = true;
            result.totalLayers = doc.layers.length;
        }
        
        return JSON.stringify(result);
    })()
    """
    
    response = await execute_script_with_context(
        script=script,
        command_type="get_document_structure",
        tool_name="illustrator_get_document_structure",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_get_selection_info",
    annotations={
        "title": "Get Selection Info",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def illustrator_get_selection_info() -> str:
    """
    Get detailed information about currently selected objects.
    
    Returns:
        JSON with array of selected items, each containing:
        - name, type, position, bounds
        - Fill/stroke info for paths
        - Text contents for text frames
    """
    script = """
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
    
    response = await execute_script_with_context(
        script=script,
        command_type="get_selection_info",
        tool_name="illustrator_get_selection_info",
        params={}
    )
    return format_response(response)


@mcp.tool(
    name="illustrator_get_app_info",
    annotations={
        "title": "Get Application Info",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def illustrator_get_app_info() -> str:
    """
    Get Illustrator application information.
    
    Returns:
        JSON with:
        - version: Illustrator version
        - documentsOpen: number of open documents
        - activeDocumentName: name of active document (if any)
        - scriptingVersion: ExtendScript version
    """
    script = """
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
    
    response = await execute_script_with_context(
        script=script,
        command_type="get_app_info",
        tool_name="illustrator_get_app_info",
        params={}
    )
    return format_response(response)


SCRIPTING_REFERENCE = """
# Illustrator ExtendScript Quick Reference

## Coordinate System
- Origin: Top-left of artboard
- Y-axis: NEGATIVE downward (use -y for visual y position)
- Units: Points (1 pt = 1/72 inch)

## Common Patterns

### Access Document
```javascript
var doc = app.activeDocument;
var layer = doc.activeLayer;
```

### Create Shapes
```javascript
// Rectangle: rectangle(top, left, width, height)
doc.pathItems.rectangle(-100, 50, 200, 100);

// Ellipse: ellipse(top, left, width, height)
doc.pathItems.ellipse(-100, 50, 100, 100);

// Rounded Rectangle: roundedRectangle(top, left, width, height, hRadius, vRadius)
doc.pathItems.roundedRectangle(-100, 50, 200, 100, 10, 10);

// Polygon: polygon(centerX, centerY, radius, sides)
doc.pathItems.polygon(100, -200, 50, 6);

// Star: star(centerX, centerY, outerR, innerR, points)
doc.pathItems.star(100, -200, 50, 25, 5);

// Line (path with 2 points)
var line = doc.pathItems.add();
line.setEntirePath([[x1, -y1], [x2, -y2]]);
```

### Colors
```javascript
// RGB Color
var c = new RGBColor();
c.red = 255; c.green = 0; c.blue = 0;

// CMYK Color
var cmyk = new CMYKColor();
cmyk.cyan = 100; cmyk.magenta = 0; cmyk.yellow = 0; cmyk.black = 0;

// Apply to shape
shape.fillColor = c;
shape.strokeColor = c;
shape.strokeWidth = 2;

// No fill/stroke
shape.filled = false;
shape.stroked = false;
```

### Gradients
```javascript
// Create linear gradient
var gradient = doc.gradients.add();
gradient.name = "MyGradient";
gradient.type = GradientType.LINEAR;

// Set color stops
var stop1 = gradient.gradientStops[0];
var blue = new RGBColor(); blue.red = 0; blue.green = 100; blue.blue = 255;
stop1.color = blue;
stop1.rampPoint = 0;

var stop2 = gradient.gradientStops[1];
var purple = new RGBColor(); purple.red = 128; purple.green = 0; purple.blue = 255;
stop2.color = purple;
stop2.rampPoint = 100;

// Apply to shape
var gradColor = new GradientColor();
gradColor.gradient = gradient;
gradColor.angle = 45;  // degrees
shape.fillColor = gradColor;

// Radial gradient
gradient.type = GradientType.RADIAL;
```

### Text
```javascript
var tf = doc.textFrames.add();
tf.contents = "Hello World";
tf.position = [x, -y];  // Note: -y for visual position

// Style text
tf.textRange.characterAttributes.size = 12;
tf.textRange.characterAttributes.fillColor = c;

// Set font
tf.textRange.characterAttributes.textFont = app.textFonts.getByName("Arial-BoldMT");
```

### Layers
```javascript
// Create layer
var newLayer = doc.layers.add();
newLayer.name = "My Layer";

// Access layer
var layer = doc.layers.getByName("Layer 1");

// Move item to layer
item.move(layer, ElementPlacement.PLACEATBEGINNING);
```

### Selection
```javascript
// Get selection
var sel = doc.selection;
if (sel.length > 0) {
    sel[0].remove();  // Delete first selected
}

// Select by name
var item = doc.pageItems.getByName("MyShape");
item.selected = true;

// Deselect all
doc.selection = null;
```

### Groups
```javascript
// Create group
var group = doc.groupItems.add();
group.name = "My Group";

// Add items to group via move
item.move(group, ElementPlacement.PLACEATBEGINNING);

// Ungroup (move items out)
for (var i = group.pageItems.length - 1; i >= 0; i--) {
    group.pageItems[i].move(doc.activeLayer, ElementPlacement.PLACEATEND);
}
```

### Transform
```javascript
// Move
item.translate(deltaX, -deltaY);

// Scale (percentage)
item.resize(120, 120);  // 120% scale

// Rotate (degrees)
item.rotate(45);

// Reflect
item.reflect(true, false);  // horizontal, vertical
```

### Pathfinder Operations
```javascript
// Unite (merge shapes)
app.executeMenuCommand('Live Pathfinder Add');

// Subtract (cut out)
app.executeMenuCommand('Live Pathfinder Subtract');

// Intersect
app.executeMenuCommand('Live Pathfinder Intersect');

// Exclude (XOR)
app.executeMenuCommand('Live Pathfinder Exclude');

// Expand after pathfinder
app.executeMenuCommand('expandStyle');
```

### Clipping Masks
```javascript
// Create clipping mask (top item clips the rest)
// First, select the items to mask
doc.selection = [clipPath, itemToClip];

// Apply clipping mask
app.executeMenuCommand('makeMask');

// Release clipping mask
app.executeMenuCommand('releaseMask');
```

### Symbols
```javascript
// Create symbol from selection
var sel = doc.selection[0];
var symbol = doc.symbols.add(sel, SymbolRegistrationPoint.SYMBOLCENTERPOINT);
symbol.name = "MySymbol";

// Place symbol instance
var instance = doc.symbolItems.add(symbol);
instance.left = 100;
instance.top = -100;
```

### Compound Paths
```javascript
// Create compound path from selection
app.executeMenuCommand('compoundPath');

// Release compound path
app.executeMenuCommand('noCompoundPath');
```

## Common Mistakes to Avoid
- Using positive Y for downward (should be negative)
- Using ctx.rect() instead of pathItems.rectangle()
- Forgetting to set filled/stroked properties
- Not using -y in position arrays
- Forgetting to expand live effects before export
"""


@mcp.tool(
    name="illustrator_get_scripting_reference",
    annotations={
        "title": "Get Scripting Reference",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False
    }
)
async def illustrator_get_scripting_reference() -> str:
    """
    Get a quick reference guide for Illustrator ExtendScript.
    
    Call this before writing complex scripts to understand:
    - Coordinate system (Y is inverted!)
    - Shape creation syntax
    - Color application
    - Text formatting
    - Common mistakes to avoid
    
    Returns:
        Markdown-formatted scripting reference
    """
    return SCRIPTING_REFERENCE
