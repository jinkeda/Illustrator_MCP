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
