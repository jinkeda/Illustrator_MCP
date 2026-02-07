/**
 * ops_element.jsx - Element CRUD Operations
 * Part of Illustrator MCP SOC Framework
 * 
 * Provides handlers for:
 * - element_create: Create shapes (rect, ellipse, line, path)
 * - element_modify: Modify existing elements
 * - element_delete: Delete elements
 * 
 * All create ops return the assigned ID for stable referencing.
 * Geometry computation happens here (JSX owns compute).
 * 
 * @requires ops_core (for registerOpHandler, generateUUID)
 * @requires geometry (for shape creation helpers)
 * @version 1.0.0
 */

// ==================== Element Create ====================

registerOpHandler("element_create", function (params, targets, ctx) {
    var doc = ctx.doc;
    var type = params.type || "rect";
    var id = params.id || generateUUID();

    // Geometry params
    var x = params.x || 0;
    var y = params.y || 0;
    var width = params.width || 100;
    var height = params.height || 100;
    var layer = params.layer || null;
    var name = params.name || null;

    // Resolve target layer
    var targetLayer = doc.activeLayer;
    if (layer) {
        for (var i = 0; i < doc.layers.length; i++) {
            if (doc.layers[i].name === layer) {
                targetLayer = doc.layers[i];
                break;
            }
        }
    }

    var item = null;

    // Convert to Illustrator coordinates (Y is negative downward)
    var aiTop = -y;
    var aiLeft = x;

    switch (type) {
        case "rect":
            // rectangle(top, left, width, height)
            item = targetLayer.pathItems.rectangle(aiTop, aiLeft, width, height);
            break;

        case "ellipse":
            // ellipse(top, left, width, height)
            item = targetLayer.pathItems.ellipse(aiTop, aiLeft, width, height);
            break;

        case "line":
            var x2 = params.x2 !== undefined ? params.x2 : x + 100;
            var y2 = params.y2 !== undefined ? params.y2 : y;
            item = targetLayer.pathItems.add();
            item.setEntirePath([[x, -y], [x2, -y2]]);
            break;

        case "roundedRect":
            var cornerRadius = params.cornerRadius || 10;
            item = targetLayer.pathItems.roundedRectangle(
                aiTop, aiLeft, width, height, cornerRadius, cornerRadius
            );
            break;

        case "polygon":
            var sides = params.sides || 6;
            var radius = params.radius || 50;
            item = targetLayer.pathItems.polygon(x, -y, radius, sides);
            break;

        case "star":
            var points = params.points || 5;
            var outerRadius = params.outerRadius || 50;
            var innerRadius = params.innerRadius || 25;
            item = targetLayer.pathItems.star(x, -y, outerRadius, innerRadius, points);
            break;

        case "path":
            // Custom path from point array: [[x1,y1], [x2,y2], ...]
            var pathPoints = params.points || [];
            if (pathPoints.length < 2) {
                return makeError(
                    ErrorCodes.V_MISSING_REQUIRED_PARAM,
                    "Path requires >= 2 points",
                    "apply"
                );
            }
            item = targetLayer.pathItems.add();
            var aiPoints = [];
            for (var pi = 0; pi < pathPoints.length; pi++) {
                aiPoints.push([pathPoints[pi][0], -pathPoints[pi][1]]);
            }
            item.setEntirePath(aiPoints);
            item.closed = params.closed !== false; // Default to closed
            break;

        default:
            return makeError(
                ErrorCodes.V_INVALID_PARAM_TYPE,
                "Unknown element type: " + type,
                "apply"
            );
    }

    // Assign ID via note
    item.note = "@mcp:id=" + id;

    // Set name if provided
    if (name) {
        item.name = name;
    }

    // Apply fill if specified
    if (params.fill) {
        var fillColor = new RGBColor();
        fillColor.red = params.fill.r || 0;
        fillColor.green = params.fill.g || 0;
        fillColor.blue = params.fill.b || 0;
        item.fillColor = fillColor;
    }

    // Apply stroke if specified
    if (params.stroke) {
        var strokeColor = new RGBColor();
        strokeColor.red = params.stroke.r || 0;
        strokeColor.green = params.stroke.g || 0;
        strokeColor.blue = params.stroke.b || 0;
        item.strokeColor = strokeColor;
        item.stroked = true;
        if (params.stroke.width) {
            item.strokeWidth = params.stroke.width;
        }
    }

    // No fill option
    if (params.fill === null || params.fill === false) {
        item.filled = false;
    }

    // No stroke option
    if (params.stroke === null || params.stroke === false) {
        item.stroked = false;
    }

    return {
        ok: true,
        id: id,
        data: {
            typename: item.typename,
            bounds: [item.left, item.top, item.width, item.height]
        }
    };
});

// ==================== Element Modify ====================

registerOpHandler("element_modify", function (params, targets, ctx) {
    if (targets.length === 0) {
        return {
            ok: false,
            error: makeError(ErrorCodes.V_NO_SELECTION, "No targets to modify", "apply")
        };
    }

    var modified = 0;
    var warnings = [];

    for (var i = 0; i < targets.length; i++) {
        var item = targets[i];

        try {
            // Position
            if (params.x !== undefined) item.left = params.x;
            if (params.y !== undefined) item.top = -params.y;

            // Size
            if (params.width !== undefined) item.width = params.width;
            if (params.height !== undefined) item.height = params.height;

            // Rotation
            if (params.rotation !== undefined) {
                item.rotate(params.rotation);
            }

            // Scale
            if (params.scale !== undefined) {
                var s = params.scale * 100;
                item.resize(s, s);
            }

            // Fill
            if (params.fill) {
                var fillColor = new RGBColor();
                fillColor.red = params.fill.r || 0;
                fillColor.green = params.fill.g || 0;
                fillColor.blue = params.fill.b || 0;
                item.fillColor = fillColor;
                item.filled = true;
            } else if (params.fill === null || params.fill === false) {
                item.filled = false;
            }

            // Stroke
            if (params.stroke) {
                var strokeColor = new RGBColor();
                strokeColor.red = params.stroke.r || 0;
                strokeColor.green = params.stroke.g || 0;
                strokeColor.blue = params.stroke.b || 0;
                item.strokeColor = strokeColor;
                item.stroked = true;
                if (params.stroke.width) {
                    item.strokeWidth = params.stroke.width;
                }
            } else if (params.stroke === null || params.stroke === false) {
                item.stroked = false;
            }

            // Opacity
            if (params.opacity !== undefined) {
                item.opacity = params.opacity * 100;
            }

            // Name
            if (params.name !== undefined) {
                item.name = params.name;
            }

            modified++;
        } catch (e) {
            warnings.push("Failed to modify item " + i + ": " + e.message);
        }
    }

    return {
        ok: modified > 0,
        data: { modified: modified, total: targets.length, failed: targets.length - modified },
        warnings: warnings
    };
});

// ==================== Element Delete ====================

registerOpHandler("element_delete", function (params, targets, ctx) {
    if (targets.length === 0) {
        return {
            ok: true,
            data: { deleted: 0 }
        };
    }

    var deleted = 0;
    var warnings = [];

    // Delete in reverse order to avoid index shifting issues
    for (var i = targets.length - 1; i >= 0; i--) {
        try {
            targets[i].remove();
            deleted++;
        } catch (e) {
            warnings.push("Failed to delete item " + i + ": " + e.message);
        }
    }

    // Invalidate ID index after deletes (deleted items would cause stale references)
    if (deleted > 0 && typeof invalidateIdIndex === "function") {
        invalidateIdIndex();
    }

    return {
        ok: deleted > 0 || targets.length === 0,
        data: { deleted: deleted, total: targets.length, failed: targets.length - deleted },
        warnings: warnings
    };
});
