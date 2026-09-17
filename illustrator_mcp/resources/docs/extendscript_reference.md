# Illustrator ExtendScript Quick Reference

## Coordinate System
- Geometry helpers (`rectXY`, `ellipseXY`, `lineXY`, `polygonXY`, `pointXY`) use
  artboard-relative coordinates: origin at the active artboard's top-left, with
  Y increasing downward.
- Raw Illustrator DOM positions use document-space coordinates, with Y
  increasing upward. The active artboard's origin may be nonzero.
- Convert an artboard-relative point `(x, y)` before a raw DOM call with
  `[ab[0] + x, ab[1] - y]`, where `ab` is the active `artboardRect`.
- Units: Points (1 pt = 1/72 inch)

## Common Patterns

### Access Document
```javascript
var doc = app.activeDocument;
var layer = doc.activeLayer;
```

### Create Shapes (raw DOM — document-space, Y-up)
```javascript
var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
var x = 50;
var y = 100;
var left = ab[0] + x;
var top = ab[1] - y;

// Rectangle: rectangle(top, left, width, height)
doc.pathItems.rectangle(top, left, 200, 100);

// Ellipse: ellipse(top, left, width, height)
doc.pathItems.ellipse(top, left, 100, 100);

// Rounded Rectangle: roundedRectangle(top, left, width, height, hRadius, vRadius)
doc.pathItems.roundedRectangle(top, left, 200, 100, 10, 10);

// Polygon: polygon(centerX, centerY, radius, sides)
doc.pathItems.polygon(ab[0] + 100, ab[1] - 200, 50, 6);

// Star: star(centerX, centerY, outerR, innerR, points)
doc.pathItems.star(ab[0] + 100, ab[1] - 200, 50, 25, 5);

// Line from two artboard-relative points, converted to raw DOM coordinates
var line = doc.pathItems.add();
line.setEntirePath([
    [ab[0] + x1, ab[1] - y1],
    [ab[0] + x2, ab[1] - y2]
]);
```

On an artboard whose top-left is `(72, 720)`, artboard-relative `(100, 200)`
therefore becomes the raw DOM position `[172, 520]`.

### Create Shapes (geometry helpers — artboard-relative, Y-down)
```javascript
var rect = rectXY(50, 100, 200, 100);
var ellipse = ellipseXY(50, 100, 100, 100);
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

### Text (raw DOM — document-space, Y-up)
```javascript
var tf = doc.textFrames.add();
tf.contents = "Hello World";
var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
tf.position = [ab[0] + x, ab[1] - y];

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

## Z-Order (Stacking Order)

Illustrator uses **index-based z-order**: index 0 = topmost (drawn last), highest index = bottommost (drawn first).

### ElementPlacement Constants
| Constant | Visual Effect | Mnemonic |
|----------|--------------|----------|
| `PLACEBEFORE` | **In front of** reference (lower index) | "before" = closer to viewer |
| `PLACEAFTER` | **Behind** reference (higher index) | "after" = further from viewer |
| `PLACEATBEGINNING` | **Topmost** in container (index 0) | front of stack |
| `PLACEATEND` | **Bottommost** in container (last index) | back of stack |

### Common Patterns
```javascript
// Move item to front of layer (visually on top of everything)
item.move(layer, ElementPlacement.PLACEATBEGINNING);

// Move item to back of layer (visually behind everything)
item.move(layer, ElementPlacement.PLACEATEND);

// Stack A in front of B (A will visually cover B)
itemA.move(itemB, ElementPlacement.PLACEBEFORE);

// Stack A behind B (B will visually cover A)
itemA.move(itemB, ElementPlacement.PLACEAFTER);
```

### Card Recipe (background + content)
When building layered structures (cards with backgrounds), create content **first**, then background **last**, and move the background behind everything:
```javascript
// 1. Create content items first (they get low indices = on top)
var title = layer.textFrames.add();
var dot = layer.pathItems.ellipse(...);

// 2. Create background card LAST
var cardBg = layer.pathItems.rectangle(...);

// 3. cardBg is already at the front (lowest index) — move it behind content
cardBg.move(layer, ElementPlacement.PLACEATEND);

// OR: create bg first, then move each content item in front of it
var cardBg = layer.pathItems.rectangle(...);
title.move(cardBg, ElementPlacement.PLACEBEFORE);  // title in front of bg
```

⚠️ **Common mistake**: Using `PLACEATEND` thinking it means "last created" — it actually means **bottommost z-order** (visually behind everything). Similarly, `PLACEBEFORE` means **visually in front of** the reference item, not "before" in creation order.

## Common Mistakes to Avoid
- Passing artboard-relative Y-down coordinates directly to raw DOM methods
- Negating Y without also adding the active artboard's left/top offsets
- Using ctx.rect() instead of pathItems.rectangle()
- Forgetting to set filled/stroked properties
- Forgetting to expand live effects before export
- **Exceeding ~8000 points in setEntirePath()** — Illustrator crashes with 'Illegal Argument'. Use the `generative` library's `decimatePoints()` to auto-clamp.

## Custom Paths and Polylines (raw DOM — document-space, Y-up)
```javascript
// Convert artboard-relative Y-down points before setEntirePath().
var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect;
var userPts = [[0, 0], [50, 100], [100, 0], [150, 50]];
var pts = [];
for (var i = 0; i < userPts.length; i++) {
    pts.push([ab[0] + userPts[i][0], ab[1] - userPts[i][1]]);
}
var path = doc.pathItems.add();
path.setEntirePath(pts);
path.closed = false;   // Open polyline (default: true for closed)
path.stroked = true;
path.filled = false;
```

## Standard Libraries (use via `includes` parameter)
| Library | Key Functions |
|---------|-------------|
| `geometry` | `rectXY()`, `ellipseXY()`, `lineXY()`, `makeRGBColor()` |
| `layout` | `arrangeInGrid()`, `distributeHorizontal()`, `alignCenter()` |
| `validate` | `countItemsOnArtboard()`, `isItemCenterOnArtboard()` |
| `generative` | `seededRandom()`, `fbm()`, `marchingSquares()`, `chaikinSmooth()` |
| `selection` | `getOrderedSelection()` |
