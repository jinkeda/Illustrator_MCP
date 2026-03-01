---
name: vlm-checkpoint
description: Checklist and heuristics for VLM QA checkpoints during Illustrator illustration tasks
---

# VLM Checkpoint — Visual QA Skill

Use this skill when a VLM QA checkpoint fires during illustration work. The system auto-injects an annotated preview every N mutations. Your job is to **verify the visual state before proceeding**.

> [!NOTE]
> The checkpoint instruction injected into responses is compact (3 lines). This skill contains the **full reference checklist** — consult it whenever a checkpoint fires.

## When This Fires

The system provides you with:
1. **Raw image** — unmodified artboard export (ground truth)
2. **Annotated image** — numbered bounding boxes over items
3. **Annotation map** — JSON with label→item mapping
4. **Z-order telemetry** — compact layer/item state

## Mandatory Checklist

At every VLM checkpoint, verify ALL of the following:

- [ ] **Color diversity**: ≥3 distinct colors visible (if ≥2 components should exist)
- [ ] **No full-canvas cover**: No single object covering entire artboard in Raw image
- [ ] **Background position**: Layers named Sky/Background/BG are NOT topmost in telemetry
- [ ] **Expected components visible**: Check that elements you've drawn are present
- [ ] **Annotation count**: Labels match expected element count
- [ ] **Ghost elements**: If a layer reports `items=N` but those items have **no annotations** and are invisible in the Raw image, their bounds are likely outside the artboard → verify with `geometricBounds` or `get_document()`
- [ ] **Peer occlusion**: If an expected element is missing from Raw but exists in telemetry with cover < 0.90, check if another element on its or an adjacent layer overlaps it (z-order issue)

## Reading Z-Order Telemetry

```
Layers (3 total, 0=top):
  0 Windows vis=1 lock=0 items=5       ← index 0 = topmost
  1 Body vis=1 lock=0 items=8
  2 Sky vis=1 lock=0 items=1            ← background at bottom ✓

Top items (5, topmost visible layers):
  #1 "window_1" PathItem L=Windows op=100 blend=Normal fill=#C8E6FF cover=0.02
  #2 "sky_bg" PathItem L=Sky op=100 blend=Normal fill=#87CEEB cover=0.99  ← 🚨
```

Key signals:
- `cover=0.99` on any item → **occlusion risk** (especially if topmost)
- `blend=Multiply` + high cover → likely intentional overlay, not bug
- `🚨` marker (cover ≥ 0.90) → abort-class, system guard flagged this item
- `⚡` marker (cover ≥ 0.70) → high suspicion, review manually
- Layer index `0` = topmost; background should have highest index

## Decision Tree

| Raw Image | Telemetry | Action |
|-----------|-----------|--------|
| Solid color | High cover item at top | **FIX**: move item to bottom layer |
| Looks correct | Clean | **PROCEED** |
| Missing elements | Clean telemetry | Check visibility/opacity |
| Partial occlusion | No 🚨 flags | Review layer order manually |
| Blank / no background | Layer has `items≥1` but 0 annotations | **Q005**: element bounds outside artboard |

## Dual-Image Comparison

**CRITICAL**: Compare the Raw Image to the Annotated Image.
- If the Raw Image is a solid block of color → **occlusion bug**, not an annotation artifact
- If the Raw Image shows artwork but annotations cover it → annotations are working correctly

## Abort Behavior

When the guard aborts (`🛑 PREVIEW ABORTED`), the response contains:
1. **Envelope** — with `guard_status: "aborted"` in diagnostics
2. **Evidence preview** — raw image showing the occluded state (solid color proof)
3. **Z-order telemetry** — layer/item data with 🚨/⚡ markers
4. **Checkpoint instruction** — this text

### Mutation Counter Rule
- Abort **increments** the mutation counter (same as pass)
- Next mutation triggers another checkpoint (even if "soon")
- This is **intended**: forces post-fix verification immediately

## Red Flags (Must Investigate)

- `🛑 PREVIEW ABORTED BY SYSTEM GUARD` — hard occlusion detected, must fix before proceeding
- `🚨` prefix in telemetry — flagged by OcclusionGuard (cover ≥ 0.90)
- `⚡` prefix in telemetry — high suspicion (cover ≥ 0.70)
- All annotation labels clustered in one small region
- `itemCount: 0` on layers that should have content
- Layer has `items≥1` but **zero annotations** for those items — ghost element, bounds outside artboard
- Raw image is blank/white but telemetry shows items exist — bounds are in wrong coordinate space
- `⚠️ Q004` — non-normal blend mode full cover (review if intentional)

## Fix Patterns

### Q003 — Background Layer On Top
```
# Move Sky to bottom
illustrator_execute_task → layer_create: {name: "Sky", placement: "bottom"}
```

### Q001 — Opaque Item Covers Canvas
```
# Move item to bottom layer
illustrator_execute_script → item.move(doc.layers[doc.layers.length-1], ElementPlacement.PLACEATEND)
```

### Q004 — Non-Normal Blend Cover (Warning)
Review the Raw Image:
- If it shows expected tint/shadow effect → proceed (intentional overlay)
- If it shows solid color → change blend mode to Normal or delete the overlay

### Q005 — Ghost Element (Bounds Outside Artboard)
A layer has `items≥1` in telemetry but those items produce **zero** annotation labels
and are invisible in the Raw image. The item's `geometricBounds` are entirely outside
the artboard rect.

**Root cause**: Y-coordinate sign error. Common with `pathItems.rectangle(top, left, width, height)` — the `height` parameter must be **positive** (draws downward from `top`). A negative height pushes the shape above the artboard into positive-Y space.

```
# Bug: height=-600 places rect at y=0..+600 (ABOVE artboard)
rectangle(0, 0, 1000, -600)  # ❌ bounds [0, +600, 1000, 0]

# Fix: height=600 places rect at y=0..-600 (ON artboard)
rectangle(0, 0, 1000, 600)   # ✓ bounds [0, 0, 1000, -600]
```

**Diagnosis**: Query the item's bounds and compare to artboard:
```
illustrator_execute_script → JSON.stringify({
    itemBounds: item.geometricBounds,
    artboard: doc.artboards[0].artboardRect
})
```
If itemBounds Y-values are positive while artboard Y-values are negative → coordinate flip.

**Fix**: Delete and recreate the item with correct height sign.
