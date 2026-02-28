# QA Invariants — VLM Occlusion Guard

Version: 1.0
Last updated: 2025-02-27

## Invariants

| ID | Name | Rule | Threshold | Code | Severity |
|----|------|------|-----------|------|----------|
| **B** | No top cover | No topmost-visible opaque normal-blend item covers ≥t of artboard | t=0.90, opacity≥95, blend=Normal | `Q001` | `abort` |
| **C** | BG layer semantics | Background-named layers must not be topmost visible | Names: `Sky`, `Background`, `BG` (case-insensitive) | `Q003` | `abort` |
| **D** | Non-normal blend cover | Full-cover item with non-normal blend mode | Same thresholds as B, blend≠Normal | `Q004` | `warn` |
| **A** | Render diversity | Preview must show ≥k distinct dominant colors when ≥2 components | k=3 | `Q002` | P2 (pixel-based, not yet implemented) |

## Detection Constraints

- **Typename filter**: only `PathItem`, `CompoundPathItem`, `RasterItem`, `PlacedItem` checked for fill/cover. `GroupItem` skipped (bbox misleading) unless `clipped == true`.
- **Single-item bypass**: if `totalItemCount ≤ 1`, no occlusion possible → `ok: True`.
- **Coordinate system**: Illustrator Y-up. `height = top - bottom`.
- **Detection scope**: topmost M=2 visible unlocked layers, not flat `pageItems`.

## Thresholds

```python
COVER_THRESHOLD = 0.90
OPACITY_THRESHOLD = 95
MAX_VISIBLE_LAYERS_TO_SCAN = 2
DEFAULT_BG_LAYER_NAMES = {"sky", "background", "bg"}  # configurable via bg_layer_names param
```
