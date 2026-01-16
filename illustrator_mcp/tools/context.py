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

// Apply to shape
shape.fillColor = c;
shape.strokeColor = c;
shape.strokeWidth = 2;

// No fill/stroke
shape.filled = false;
shape.stroked = false;
```

### Text
```javascript
var tf = doc.textFrames.add();
tf.contents = "Hello World";
tf.position = [x, -y];  // Note: -y for visual position

// Style text
tf.textRange.characterAttributes.size = 12;
tf.textRange.characterAttributes.fillColor = c;
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
```

### Groups
```javascript
// Create group
var group = doc.groupItems.add();
group.name = "My Group";

// Add items to group via move
item.move(group, ElementPlacement.PLACEATBEGINNING);
```

### Transform
```javascript
// Move
item.translate(deltaX, -deltaY);

// Scale (percentage)
item.resize(120, 120);  // 120% scale

// Rotate (degrees)
item.rotate(45);
```

## Common Mistakes to Avoid
- Using positive Y for downward (should be negative)
- Using ctx.rect() instead of pathItems.rectangle()
- Forgetting to set filled/stroked properties
- Not using -y in position arrays
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
