# Illustrator MCP

[![MCP](https://img.shields.io/badge/MCP-Compatible-blue)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/Python-3.10+-green)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An [MCP](https://modelcontextprotocol.io) server that lets AI assistants like Claude control Adobe Illustrator through natural language. Write ExtendScript via a single powerful tool, or use purpose-built tools for document I/O, state inspection, and structured queries.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Available Tools](#available-tools)
- [Standard Libraries](#standard-libraries)
- [Task Protocol & SOC Framework](#task-protocol--soc-framework)
- [Abstraction Ladder](#abstraction-ladder)
- [VLM Debug Overlay & Auto-Grounding](#vlm-debug-overlay--auto-grounding)
- [Examples](#examples)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)
- [Development](#development)

---

## How It Works

A single Python process serves both the MCP protocol (stdio) and a WebSocket bridge. A CEP panel inside Illustrator connects over WebSocket and executes ExtendScript on demand.

```
Claude / AI Client           MCP Server (Python)            Illustrator
 ──── MCP (stdio) ────>  ──── WebSocket :8081 ────>  CEP Panel + ExtendScript
```

1. AI calls a tool (e.g. `illustrator_execute_script`) with ExtendScript code
2. The MCP server sends the script over WebSocket to the CEP panel
3. The CEP panel executes it in Illustrator's ExtendScript runtime and returns the result
4. Context tools (`get_document`) let the AI understand document state before writing scripts

### Architecture

```
MCP Server Process
├── Main Thread  (MCP event loop, tool dispatch)
└── Bridge Thread (WebSocket server on port 8081)
    └── RequestRegistry (async request/response lifecycle)
```

Both threads coordinate via `run_in_executor()` / `run_coroutine_threadsafe()`. No separate proxy or Node.js process is required.

### Two-Contract Data Model

All data between layers follows two strict envelope contracts:

| Contract | Direction | Success Shape | Error Shape |
|---|---|---|---|
| **Internal** | JSX → Python | `{ok: true, data: {...}, operation: "..."}` | `{ok: false, error: {message, line, operation}}` |
| **External** | Python → Client | `{ok: true, result: {...}, diagnostics: {...}}` | `{ok: false, error: {code, message, suggestions}}` |

- **Internal:** Every ExtendScript template and `wrap_script()` emits the internal envelope. `host.jsx` validates and passes through compliant JSON; bare values are auto-wrapped.
- **External:** `format_envelope()` strips the internal wrapper and surfaces pure domain data in `result`. Structured error codes, line numbers, and recovery suggestions are always present.

---

## Prerequisites

| Requirement | Version |
|---|---|
| **Python** | 3.10+ |
| **Adobe Illustrator** | 25.0+ (CC 2021 or later) |

---

## Installation

### 1. Clone & Install

```bash
git clone https://github.com/jinkeda/Illustrator_MCP.git
cd Illustrator_MCP
pip install -e .
```

This installs core dependencies including [Pillow](https://python-pillow.org/) for VLM preview overlays.

**Optional — boolean path operations:**

```bash
pip install -e ".[geometry]"
```

This adds [pyclipper](https://github.com/fonttools/pyclipper) for `path_boolean` (unite, subtract, intersect, xor). If using `uv`:

```bash
uv sync --extra geometry
```

### 2. Build & Install the CEP Extension

```bash
cd cep-extension
npm install
npm run build
cd ..
```

**macOS:**

```bash
chmod +x install-cep.sh
./install-cep.sh
```

**Windows (Run as Administrator):**

```bat
install-cep.bat
```

The installer creates a symlink into Adobe's CEP extensions folder and enables debug mode. If it fails, see [Manual CEP Installation](#manual-cep-installation) below.

### 3. Restart Illustrator

The panel appears under **Window > Extensions > MCP Control**.

---

## Configuration

### Claude Desktop

Add to your config file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "illustrator": {
      "command": "illustrator-mcp"
    }
  }
}
```

<details>
<summary>Alternative: run via Python module</summary>

```json
{
  "mcpServers": {
    "illustrator": {
      "command": "python",
      "args": ["-m", "illustrator_mcp.server"]
    }
  }
}
```

</details>

### Environment Variables (Optional)

Create a `.env` file in the project root:

```env
WS_PORT=8081     # WebSocket port (default: 8081)
TIMEOUT=30       # Script execution timeout in seconds (default: 30)
```

| Setting | Default | Range | Description |
|---|---|---|---|
| `WS_PORT` | `8081` | 1024 - 65535 | WebSocket port for CEP panel connection |
| `TIMEOUT` | `30` | 1 - 300 | Script execution timeout (seconds) |

---

## Usage

1. **Start Claude Desktop** (or restart it) -- the MCP server launches automatically
2. **Open Illustrator**
3. **Open the CEP panel:** Window > Extensions > MCP Control
4. Verify the panel shows **Connected**
5. In Claude, try: _"Create a new 800x600 document"_

No additional servers or processes needed.

---

## Available Tools

This server follows a **Scripting First** architecture: one powerful script executor handles most operations, complemented by purpose-built tools for document I/O, state inspection, and structured queries.

Every tool carries a `CONTRACT:` line in its docstring and machine-checkable annotation hints (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) sourced from a canonical `TOOL_ANNOTATIONS` registry in `base.py`. Hints follow the **worst-case capability rule**: if *any* action of a multi-action tool is destructive, the tool is annotated as destructive.

### Script Execution (2)

| Tool | Description |
|---|---|
| `illustrator_execute_script` | **Primary tool.** Execute any ExtendScript code in Illustrator. Supports library injection, params, bounds validation, and preview export. |
| `illustrator_execute_task` | Execute a structured task using the Task Protocol (collect > compute > apply). |

### Document Operations (4)

| Tool | Description |
|---|---|
| `illustrator_document` | Unified document I/O: `action="create"` / `"open"` / `"save"` / `"close"` |
| `illustrator_export_document` | Export to PNG, JPG, SVG, or PDF with optional visual feedback |
| `illustrator_place_file` | Place an external file (PNG, JPG, EPS, AI, PDF) with optional editable embed or Image Trace vectorization (`trace=True`) |
| `illustrator_set_reference` | Place or clear a locked reference image on a background layer. Returns dominant colors for palette matching. |

### Undo / Redo / Checkpoints (1)

| Tool | Description |
|---|---|
| `illustrator_history` | Undo/redo actions (multi-step count), plus named checkpoint management: `checkpoint_save`, `checkpoint_restore`, `checkpoint_list`, `checkpoint_delete` |

### Context & Inspection (1)

| Tool | Description |
|---|---|
| `illustrator_get_document` | Full document tree + optional app info via `scope` param (`"document"`, `"app"`, `"both"`) |

### Path Operations (2)

| Tool | Description |
|---|---|
| `illustrator_path_import_svg` | Import an SVG path `d` attribute. Parses server-side, converts arcs to cubic Béziers. Hardcoded safety limits. |
| `illustrator_path_boolean` | Boolean operations (unite, subtract, intersect, xor) on paths. Uses [pyclipper](https://github.com/fonttools/pyclipper) for polygon clipping. Bézier curves are auto-flattened. Requires `geometry` extras. |

### Query & Validation (2)

| Tool | Description |
|---|---|
| `illustrator_query_items` | Declarative item query via the Task Protocol (target selectors, stable refs). Defaults to selection info when no targets given. |
| `illustrator_preflight_check` | Read-only validation: off-artboard items, zero-size items, empty text, locked layers |

**Total: 12 tools.** Scripting reference and linked-item refresh are available as MCP resources.

---

## Standard Libraries

Complex scripts can pull in reusable ExtendScript libraries via the `includes` parameter. Dependencies are resolved automatically from `manifest.json`.

```python
illustrator_execute_script(
    script='var rect = rectXY(50, 100, 200, 150);',
    includes=["geometry"]
)
```

### Core Libraries

| Library | Key Exports | Purpose |
|---|---|---|
| `geometry` | `rectXY`, `ellipseXY`, `lineXY`, `makeRGBColor`, `drawPathPoints` | Intuitive XY coordinate helpers, **Golden Path** for Bézier/compound path creation |
| `selection` | `getOrderedSelection` | Spatial sorting (row-major / column-major) |
| `layout` | `createGrid`, `distributeHorizontal`, `alignCenter` | Grid creation, alignment, distribution |
| `presets` | `COLOR_PALETTES`, `getColor`, `applyPreset` | 9 color palettes (Okabe-Ito, Viridis, etc.) and layout presets |
| `validate` | `countItemsOnArtboard` | Bounds validation and preflight checks |
| `snapshot` | `captureSnapshot`, `restoreSnapshot` | Document state snapshot / restore for rollback |

### Task Protocol Libraries

| Library | Purpose |
|---|---|
| `task_executor` | Task Protocol framework: `executeTask`, `collectTargets`, `makeError`, retry semantics |
| `field_eval` | Dynamic param preprocessing (4 built-in evaluators: `index_ratio`, `position`, `noise`, `lookup`) |

### SOC (State-Ops-Checks) Libraries

| Library | Purpose |
|---|---|
| `ops_core` | Batch executor, global ID index, journal integration |
| `ops_element` | Create / modify / delete shapes (rect, ellipse, line, polygon, star, text) |
| `ops_group` | Group / ungroup, z-order, clipping masks |
| `ops_layer` | Layer CRUD, fail-loud reference checks, `placement` pinning, `layer_list` |
| `ops_style` | Fill, stroke, opacity |
| `ops_text` | Text frame creation and styling |
| `ops_align` | Alignment and distribution |
| `ops_measure` | Assertions (count, bounds, exists, style, alignment, layer order), snapshots, repair mode |
| `op_schemas` | Auto-generated parameter validation schemas |

### Advanced Libraries

| Library | Purpose |
|---|---|
| `geo_ir` | Geometry IR schema, validation, and construction |
| `generative` | Procedural generation: seeded PRNG, noise, fBm, marching squares, Chaikin smoothing |
| `session` | Multi-call IR handoff via `$.global` session stash |
| `ops_journal` | Op journal for batch replay and recomputability |
| `assets` | Asset analysis (bounds, aspect ratio, orientation) |

---

## Task Protocol & SOC Framework

### Task Protocol (v2.3)

For multi-item operations, the Task Protocol provides structured **collect > compute > apply** execution with standardized error codes, retry semantics, and stable references.

```javascript
var payload = {
    task: 'apply_fill',
    targets: {type: 'selection'},
    params: {color: [255, 0, 0]},
    options: {trace: true}
};
var report = executeTask(payload, collectTargets, compute, apply);
```

Target selectors: `selection`, `layer`, `query`, `all`, and compound (`union`, `intersection`).

### SOC Framework

For high-complexity layouts (50+ elements, multi-step operations), the SOC framework provides batch operations with ID-based targeting, schema validation, snapshot rollback, and per-op reporting.

```javascript
var ops = [
    {task: 'element_create', params: {id: 'A1', type: 'rect', x: 100, y: 100, width: 50, height: 50}},
    {task: 'style_set_fill', targets: {type: 'id', ids: ['A1']}, params: {r: 255, g: 0, b: 0}},
    {task: 'assert_exists', params: {ids: ['A1']}}
];
var report = executeOpBatch(ops, {strict: true, trace: true});
```

Key capabilities: stable ID targeting (`@mcp:id=` in item.note), strict/continue error modes, `summaryOnly` for large batches, snapshot rollback, Python-side chunking for WebSocket limits, field evaluators for dynamic params, and op journaling for replay.

### Abstraction Ladder

`element_create` supports multiple abstraction levels for path creation, from fully declarative down to raw handles:

| Level | Feature | Use Case |
|---|---|---|
| **smooth** | Catmull-Rom spline from waypoints | Organic curves, wave shapes |
| **handles** | Polar `{angle, length}` or relative `{dx, dy}` Bézier handles | Sharp tips, engineering profiles |
| **mirror** | Bilateral symmetry: define half-profile, auto-mirror | Fuselage cross-sections, symmetric wings |

Handles and mirror are resolved Python-side before reaching JSX — the AI provides intuitive specs, and trigonometry + mirroring are handled automatically.

**SVG path import:** Use the dedicated `path_import_svg` tool to import SVG `d` attributes. The path string is parsed Python-side into geometry IR (supports M/L/H/V/C/S/Q/T/A/Z commands including arc-to-cubic conversion), then drawn via `geometry.drawPathPoints`. Hardcoded safety limits prevent abuse (50k chars, 5k segments, 100 subpaths, ±100k coordinates).

**Path boolean:** Use `path_boolean` to unite, subtract, intersect, or xor shapes by MCP ID. The pipeline extracts geometry from Illustrator (ExtendScript), flattens any Bézier curves (Python), runs the boolean via pyclipper (Python), and reconstructs the result as a `PathItem` or `CompoundPathItem` (ExtendScript). Shapes with holes produce `CompoundPathItem` automatically. Requires `geometry` extras (`pip install -e ".[geometry]"`).

**Clipping masks:** `clip_create` creates a clipping mask group from a mask path and content items referenced by MCP ID. Supports `dryRun` mode for validation without mutation, parent-aware placement, and mask type validation.

**Conditional operations:** `when` / `unless` guards filter targets by property predicates before execution (e.g., `when: {property: 'width', gt: 100}`).

**Spatial query targets:** `within`, `nearTo`, and `outside` predicates select items by geometric region. Predicates combine as OR (union). Structured error codes (`SP01`–`SP03`) provide precise diagnostics.

See [`PROTOCOL.md`](PROTOCOL.md) and [`SOC_CONTRACTS.md`](SOC_CONTRACTS.md) for full specifications.

---

## VLM Debug Overlay & Auto-Grounding

### Annotated Preview

When calling `execute_script` with `preview_mode: "annotated"`, the server returns an annotated PNG with numbered bounding boxes overlaid on the artboard, plus a JSON annotation map linking visual labels to item IDs.

```python
execute_script(
    script="var r = doc.pathItems.rectangle(-50, 50, 200, 100);",
    return_preview=True,
    preview_mode="annotated",
    preview_max_items=50
)
# Returns:
# [0] TextContent  — execution envelope
# [1] ImageContent — annotated PNG with [1], [2], ... bounding boxes
# [2] TextContent  — annotation map JSON
```

The annotation map bridges visual labels to stable `@mcp:id` tags:

```json
{
  "meta": {"bounds_kind": "visibleBounds", "item_count": 3},
  "annotations": [
    {"label": "1", "mcp_id": "a1b2c3d4", "has_mcp_id": true, "name": "chart_area", "type": "PathItem"},
    {"label": "2", "mcp_id": null, "has_mcp_id": false, "name": "title_text", "type": "TextFrame"}
  ],
  "warnings": []
}
```

### Auto-Grounding

Every `execute_task` (SOC pipeline) call **automatically** includes the annotated overlay in its return. The agent doesn't opt in — it is forcibly handed a visual map of the canvas grounded with `[1]` → `@mcp:id` tags alongside the SOC task report.

```
execute_task return shape:
  [TextContent(SOC report), ImageContent(annotated PNG), TextContent(annotation map)]
```

This closes the visual loop: the agent sees overlapping elements, abandoned text frames, or off-artboard items before deciding its next action. If the overlay fails (export error), the response degrades gracefully to the text-only SOC report.

> **Note:** Pillow is a core dependency (installed automatically). The VLM overlay is always available.

### Coordinate Rulers

All VLM auto-previews include coordinate axis rulers along the top and left edges, giving the VLM exact point-coordinate reference. Ruler labels use **screen-space**: origin at top-left of artboard, X rightward, Y downward — matching `spatial_context` (returned by `set_reference`) and `bounds_screen` (used in `vlm_grounding`). Tick intervals are adaptive (≤12 labels per axis), and labels use anti-overlap logic to stay readable on any artboard size.

### Coordinate Prober

Pass `probe_points` to `execute_script` to render labeled coordinate markers on the annotated preview. Each probe is a colored circle with crosshair lines and a coordinate readout, useful for verifying exact positions.

```python
execute_script(
    script="...",
    return_preview=True,
    preview_mode="annotated",
    probe_points=[
        {"label": "center", "x": 250, "y": 300},
        {"label": "top_left", "x": 50, "y": 50}
    ]
)
```

Probe coordinates use the same screen-space Y-down convention as rulers. Colors cycle through a 6-color palette. Rendering is non-fatal — probes are skipped gracefully if Pillow is unavailable.

### Regional Zoom (`clip_box`)

Pass `clip_box` to `execute_script` or `execute_task` to generate a high-resolution crop of a specific region. This solves the VLM patch resolution limit — fine details like 3pt vector elements are invisible at full-artboard zoom but become clearly visible in a regional crop.

```python
execute_script(
    script="...",
    return_preview=True,
    preview_mode="annotated",
    clip_box=[580, 420, 680, 510]  # [xmin, ymin, xmax, ymax] screen-space Y-down
)
```

| Feature | Behavior |
|---|---|
| **Coordinate input** | Screen-space Y-down points (matches rulers, `bounds_screen`) |
| **Export** | Creates a temporary artboard for the crop, exports at up to 776% scale (Illustrator engine limit), then cleans up |
| **Item culling** | ExtendScript-side AABB intersection check — only items in the clip region count against `max_items` |
| **Annotation coordinates** | Always **global** document coordinates — use them directly for follow-up edits |
| **Ruler overlay** | Shows **absolute** tick labels (e.g., 580, 600, 620... not 0, 20, 40...) |
| **Probe points** | Automatically remapped to clip-relative coordinates |
| **Beyond-bounds** | Clip rect is clamped to artboard edges — no crash if the region extends past the document |
| **System note** | `⚠️ CLIP BOX ACTIVE: ...` injected into the response when clip_box is set |

### VLM QA Cadence

The server automatically injects an annotated preview every **5th** `execute_script` call, even if the caller didn't request one. This forces the AI to periodically *see* the canvas and catch visual defects (broken glyphs, overlaps, misaligned items) before they accumulate.

| Trigger | Behavior |
|---|---|
| Every 5th call | Auto-inject `return_preview=True, preview_mode="annotated"` |
| `final_step=True` | Force annotated preview on the last mutation |
| AI sets `return_preview=False` | Respected, but a skip warning is added to the envelope |

```python
# Final mutation — forces VLM QA regardless of cadence count
execute_script(
    script="...",
    final_step=True  # → annotated preview returned automatically
)
```

The cadence counter is module-level and resets on server restart. Configurable via `VLM_QA_CADENCE` in `execute.py`.

### VLM Grounding Pipeline

The `vlm_grounding` module provides three features that transform VLM checkpoints from "look at this screenshot" into a math-verifiable QA loop:

| Feature | Functions | What It Does |
|---|---|---|
| **Hybrid Grounding** | `build_dom_map`, `build_relationship_map` | Pairs each overlay label `[1]`, `[2]`, ... with DOM metadata (screen-space bounds, fill, font, text). Computes pairwise spatial relationships via spatial binning. |
| **Proposer / Verifier** | `VLMHypothesis`, `verify_hypothesis` | VLM proposes structured hypotheses (misalignment, overlap, spacing, off-artboard, style mismatch). Pure-Python verifier confirms or discards each claim using bounds math. |
| **Before / After Diffing** | `capture_dom_snapshot`, `diff_dom_snapshots` | Captures DOM state before mutations, diffs after. Two-pass matching: stable `mcp_id` first, then IoU + center proximity scoring for destructive operations. |

### Occlusion Guard

A **shift-left** safety net that catches full-canvas occlusion *before* the VLM preview. Runs deterministically in Python/ExtendScript — no LLM cost.

| Check | Code | Severity | Fires when |
|---|---|---|---|
| Opaque full cover | `Q001` | abort | Item covers ≥90% of artboard, normal blend, opacity ≥95% |
| Background layer on top | `Q003` | abort | Layer named Sky/Background/BG is topmost visible |
| Non-normal blend cover | `Q004` | warn | Full cover but Multiply/Screen/etc. blend |

Guard results are reported via `diagnostics.guard_status`:

| Status | Meaning |
|---|---|
| `"skipped"` | Not a VLM checkpoint, guard did not run |
| `"passed"` | Guard ran, no abort-level findings |
| `"aborted"` | Guard blocked the annotated preview |

On abort, the response includes: envelope with `guard_status: "aborted"`, a **raw evidence image** (proof of occlusion), Z-order telemetry with `🚨` (≥0.90) / `⚡` (≥0.70) cover markers, and the VLM checkpoint instruction.

Key design decisions:
- **`mcp_id` is the primary key** — overlay IDs are a view layer for VLM communication only
- **Screen-space Y-down coordinates** — all bounds normalized to `[x, y, width, height]` matching the exported image
- **Tolerance-aware verification** — `abs_tol=1.0pt` default, per-hypothesis override via `align_tol`
- **Spatial binning** — O(n) relationship generation with 2,000-pair hard cap

---

## Examples

### Create a Document

```
Prompt: "Create a new 1920x1080 document for a YouTube thumbnail"
```

### Draw Shapes with Library Helpers

```javascript
// includes: ["geometry"]
var rect = rectXY(50, 100, 200, 150);  // x=50, y=100, 200x150pt
rect.fillColor = makeRGBColor(255, 0, 0);
```

### Create a Grid Layout

```javascript
// includes: ["geometry", "layout"]
var items = createGrid({
    rows: 2, cols: 2,
    itemWidth: 110, itemHeight: 110,
    gapX: 12, cornerRadius: 8,
    colors: [
        {r:243, g:83, b:37},
        {r:129, g:188, b:6},
        {r:5, g:166, b:240},
        {r:255, g:186, b:8}
    ]
});
```

### Smooth Curve from Waypoints

```json
{"task": "element_create", "params": {
    "type": "path",
    "points": [[0,50],[50,0],[100,50],[150,0],[200,50]],
    "smooth": true, "tension": 0.5,
    "fill": {"r": 0, "g": 150, "b": 136}
}}
```

### Polar Handles — Precise Bézier Control

Define handles by angle + length instead of absolute coordinates. Python resolves the trigonometry.

```json
{"task": "element_create", "params": {
    "type": "path",
    "points": [[0,50],[100,0],[200,50]],
    "handles": [null, {"angle": 0, "length": 30, "symmetric": true}, null],
    "stroke": {"r": 0, "g": 100, "b": 200, "width": 3}
}}
```

- `null` → corner point (no curvature)
- `{angle, length, symmetric}` → out-handle at polar coords; `symmetric: true` auto-mirrors the in-handle
- `{in: {...}, out: {...}}` → independent in/out handles
- `{dx, dy}` → relative offsets instead of polar

### Symmetry Modifier — Define Half, Mirror Automatically

```json
{"task": "element_create", "params": {
    "type": "path",
    "points": [[0,100],[30,85],[80,85],[120,100]],
    "smooth": true,
    "mirror": "mirror_y_bottom",
    "fill": {"r": 200, "g": 200, "b": 200}
}}
```

Modes: `mirror_y_bottom`, `mirror_y_top`, `mirror_x_right`, `mirror_x_left`. First/last points on the axis are auto-deduplicated to prevent kinks. Handles are mirrored and swapped for path continuity.

### Raw ExtendScript

```javascript
var doc = app.activeDocument;
var rect = doc.pathItems.rectangle(-100, 50, 200, 100);
var c = new RGBColor(); c.red = 255; c.green = 0; c.blue = 0;
rect.fillColor = c;
```

> **Coordinate system:** Origin is top-left. Y is **negative downward**. Use `-y` for visual positions. Units are points (1 pt = 1/72 in).

### Boolean Operations

```python
# Unite two overlapping shapes into one
path_boolean(
    operation="unite",
    subject="mcp_id_of_shape_1",
    clip=["mcp_id_of_shape_2"],
    delete_originals=True,
    style="subject"  # inherit fill/stroke from subject
)

# Subtract a cutout from a circle
path_boolean(
    operation="subtract",
    subject="circle_id",
    clip=["cutout_id"],
    delete_originals=True
)
# → CompoundPathItem (circle with rectangular hole)
```

> Requires `geometry` extras. Bézier curves are auto-flattened to polylines for the Clipper engine.

### Export with Visual Feedback

```python
illustrator_export_document(
    file_path="output.png",
    format="png",
    scale=2.0,
    return_image=True   # Claude sees the exported image inline
)
```

---

## Troubleshooting

### "ILLUSTRATOR_DISCONNECTED: CEP panel is not connected"

1. Ensure Illustrator is running
2. Open the panel: **Window > Extensions > MCP Control**
3. Check for "Connected" status; click **Connect** if disconnected
4. Restart Claude Desktop if the issue persists (this restarts the MCP server)

### CEP Panel Not Appearing

1. Verify Illustrator is version 25.0+ (CC 2021 or later)
2. Ensure debug mode is enabled:
   - **macOS:** `defaults read com.adobe.CSXS.11 PlayerDebugMode` should return `1`
   - **Windows:** Check `HKCU\Software\Adobe\CSXS.11\PlayerDebugMode` is `1`
3. Confirm the extension is installed at the correct path (see installation steps)
4. Restart Illustrator after installing

### WebSocket Port Conflict

```bash
# Check if port 8081 is in use
lsof -i :8081        # macOS/Linux
netstat -ano | findstr 8081  # Windows
```

If occupied, change `WS_PORT` in `.env` and restart.

### Script Errors

- Debug the CEP panel at `http://localhost:8088` (Chrome DevTools)
- The scripting reference is available as an MCP resource (`illustrator://reference/extendscript`)
- File paths: use forward slashes or escaped backslashes

### Structured Error Codes

| Code | Category | Meaning |
|---|---|---|
| `C001` | Connection | Illustrator not connected |
| `V001` | Validation | No document open |
| `V002` | Validation | No selection |
| `V006` | Validation | Missing required parameter |
| `V007` | Validation | Invalid parameter type |
| `R005` | Runtime | Layer not found |
| `R006` | Runtime | Element not found |
| `S001` | Script | Syntax error |
| `S002` | Script | Undefined variable |
| `G001` | Guard | Unknown guard property |
| `G002` | Guard | Invalid comparator |
| `G003` | Guard | Malformed guard clause |
| `SP01` | Spatial | Missing spatial predicate |
| `SP02` | Spatial | Invalid rect specification |
| `SP03` | Spatial | Reference item not found |
| `SVG001` | SVG Import | Path data too long (>50k chars) |
| `SVG002` | SVG Import | Too many segments (>5k) |
| `SVG003` | SVG Import | Too many subpaths (>100) |
| `SVG004` | SVG Import | Coordinate overflow (>±100k) |
| `SVG005` | SVG Import | Too many tokens (>50k) |
| `R010` | Runtime | Could not parse TaskReport |
| `Q001` | Occlusion | Opaque item covers ≥90% of artboard |
| `Q003` | Occlusion | Background layer is topmost visible |
| `Q004` | Occlusion | Non-normal blend full cover (warning) |

All errors include actionable recovery suggestions.

### Manual CEP Installation

If the install script fails:

1. Build: `cd cep-extension && npm install && npm run build && cd ..`
2. Copy the `cep-extension` folder to:
   - **macOS:** `~/Library/Application Support/Adobe/CEP/extensions/com.illustrator.mcp.panel`
   - **Windows:** `%APPDATA%\Adobe\CEP\extensions\com.illustrator.mcp.panel`
3. Enable debug mode for **both** CSXS 11 and 12:

   ```bash
   # macOS
   defaults write com.adobe.CSXS.11 PlayerDebugMode 1
   defaults write com.adobe.CSXS.12 PlayerDebugMode 1
   ```

   ```powershell
   # Windows (Admin PowerShell)
   reg add "HKCU\Software\Adobe\CSXS.11" /v PlayerDebugMode /t REG_SZ /d 1 /f
   reg add "HKCU\Software\Adobe\CSXS.12" /v PlayerDebugMode /t REG_SZ /d 1 /f
   ```

4. Restart Illustrator

---

## Project Structure

```
Illustrator_MCP/
├── illustrator_mcp/              # Python MCP server
│   ├── server.py                 # Entry point
│   ├── shared.py                 # FastMCP instance + lifespan management
│   ├── config.py                 # Pydantic Settings (ws_port, timeout)
│   ├── runtime.py                # Dependency injection for bridge
│   ├── proxy_client.py           # Script execution + response envelope (format_envelope)
│   ├── websocket_bridge.py       # WebSocket bridge facade
│   ├── libraries.py              # Library resolver + manifest-driven injection
│   ├── protocol.py               # Task Protocol v2.3 Pydantic models
│   ├── errors.py                 # Structured error codes + suggestions
│   ├── templates.py              # Reusable ExtendScript templates ({ok, data} envelope)
│   ├── response_classification.py # Response classifier (error metadata extraction)
│   ├── response_models.py        # Pydantic models for responses
│   ├── vlm_grounding.py          # VLM QA pipeline: hybrid grounding, hypothesis verifier, DOM diffing
│   ├── geometry.py               # Python-side boolean geometry engine (pyclipper, Bézier flattening)
│   ├── svgd.py                   # SVG path data parser (d attribute → geometry IR, arc→cubic)
│   ├── curves.py                 # Bézier helpers (rounded polygon, arcs, polar handles, mirror)
│   ├── log_config.py             # Structured logging config
│   ├── bridge/
│   │   ├── server.py             # WebSocket server transport
│   │   └── request_registry.py   # Async request lifecycle + streaming
│   ├── logging/
│   │   └── request_log.py        # JSON-lines logger
│   ├── utils/
│   │   ├── chunking.py           # Auto-split large op batches
│   │   ├── path.py               # Path escaping helper
│   │   └── response.py           # JSON parsing + envelope unwrapping
│   ├── schemas/                  # Generated JSON schemas
│   ├── tools/
│   │   ├── __init__.py           # Tool registration
│   │   ├── base.py               # Shared base + TOOL_ANNOTATIONS registry (SSOT)
│   │   ├── execute.py            # execute_script + auto-grounding
│   │   ├── task_execution.py     # execute_task + path boolean operations
│   │   ├── cadence.py            # VLM QA cadence counter + constants
│   │   ├── preview.py            # Preview capture + annotation pipeline
│   │   ├── documents.py          # Document I/O + checkpoint tools
│   │   ├── context.py            # State inspection tools
│   │   ├── query.py              # query_items + preflight_check
│   │   ├── import_svg.py         # SVG path import tool (d → drawPathPoints)
│   │   └── archive/              # Disabled legacy tools (reference only)
│   ├── overlay.py                # VLM overlay (bounding boxes + ruler + probe markers + coordinate mapping)
│   └── resources/
│       ├── docs/
│       │   └── extendscript_reference.md
│       ├── templates/            # JSX templates loaded by Python (IDE-checkable)
│       │   └── compute_soc_batch.jsx
│       └── scripts/              # 18+ ExtendScript libraries
│           ├── manifest.json     # Library metadata + dependency graph
│           ├── geometry.jsx      # XY coordinates, bounds, colors
│           ├── layout.jsx        # Grid, distribution, alignment
│           ├── task_executor.jsx  # Task Protocol framework
│           ├── ops_core.jsx      # SOC batch executor
│           └── ...               # (see Standard Libraries section)
├── cep-extension/                # Adobe CEP panel (React + Vite + TypeScript)
│   ├── CSXS/manifest.xml
│   ├── jsx/host.jsx              # ExtendScript bridge
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/MCPControlPanel.tsx
│   │   └── hooks/useMCP.ts       # WebSocket connection hook
│   └── vite.config.ts
├── tests/                        # Unit tests (pytest, 1350+ tests)
│   ├── conftest.py               # Shared fixtures + collection-error guard
│   ├── test_execute.py
│   ├── test_documents.py
│   ├── test_context.py
│   ├── test_protocol.py
│   ├── test_task_protocol_v23.py
│   ├── test_execute_task_envelope.py  # Canonical envelope wrapping tests (19 tests)
│   ├── test_library_resolver.py
│   ├── test_injection.py
│   ├── test_templates.py
│   ├── test_proxy_client.py
│   ├── test_websocket_bridge.py
│   ├── test_overlay.py
│   ├── test_svgd.py              # SVG path parser tests (35 tests)
│   ├── test_import_svg.py        # SVG import tool tests (14 tests)
│   ├── test_clip_box.py          # Regional zoom / clip_box tests (28 tests)
│   ├── test_clip_ops.py          # Clipping mask schema + handler guard tests
│   ├── test_grid_helper.py       # Grid discovery tests
│   ├── test_vlm_grounding.py     # VLM grounding pipeline tests (42 tests)
│   ├── test_layer_targeting.py   # Layer targeting resolution tests
│   ├── test_layer_order.py       # Layer ordering fixes: fail-loud refs, placement, assert_layer_order (10 tests)
│   ├── test_soc_contracts.py     # Contract sync tests across 4 registry layers (6 tests)
│   ├── test_registry_snapshot.py  # Registry + canonical policy tests (11 tests)
│   └── test_brand_social_kit_fixes.py
├── scripts/
│   └── gen_schemas.py            # Schema codegen (Python -> JSX)
├── docs/
│   ├── ARCHITECTURE.md
│   └── ROADMAP_v2.4.md
├── pyproject.toml
├── PROTOCOL.md                   # Task Protocol v2.3 specification
├── SOC_CONTRACTS.md              # Result contract schemas
├── install-cep.sh                # macOS CEP installer
├── install-cep.bat               # Windows CEP installer
└── .env.example
```

---

## Development

### Running Tests

```bash
pip install -e ".[dev,geometry]"
pytest tests/ -v
```

Tests use mocked bridge connections -- Illustrator is not required for unit tests.

### Live Testing

With Illustrator running and the CEP panel connected, use `pytest -m integration` or run `tests/live_test_phase1_3.py` directly.

### Schema Codegen

Regenerate the ExtendScript parameter schemas from Python definitions:

```bash
python -m scripts.gen_schemas
```

### Design Principles

1. **Scripting First** -- One powerful script executor instead of 100+ atomic tools. Stays under platform tool limits, enables any ExtendScript operation, and reduces maintenance surface.
2. **Thick Scripts, Thin Server** -- Move complexity into ExtendScript, not Python. Fewer round-trips, atomic operations, and Illustrator-native calculations.
3. **Library Injection** -- Reusable `.jsx` libraries with manifest-driven transitive dependency resolution and symbol collision detection.
4. **Context Before Creation** -- AI inspects document state (`get_document`, `query_items`) before writing modification scripts.
5. **Two-Contract Envelope** -- Internal contract (`{ok, data, operation}`) flows from ExtendScript to Python. External contract (`{ok, result, error, diagnostics, warnings}`) flows from Python to the MCP client. `build_envelope_dict()` is the shared core that unwraps internal envelopes and classifies errors. `format_envelope()` wraps it for standard tools; `execute_task` uses it as Phase 1 of a three-phase pipeline (canonical unwrap → TaskReport parse → `make_envelope` construction).
6. **Fail Fast with Structured Errors** -- Typed error codes (V/R/S/C/SVG categories) with actionable recovery suggestions.
7. **Auto-Grounding** -- SOC task results always include an annotated artboard preview, forcing the AI to see the visual state before its next action. No opt-in required.
8. **VLM QA Cadence** -- Every 5th `execute_script` call auto-injects an annotated preview. Combined with `final_step=True`, the AI is periodically forced to visually verify and catch defects.
9. **Canonical Tool Annotations** -- A single `TOOL_ANNOTATIONS` registry in `base.py` defines `readOnly`, `destructive`, `idempotent`, and `openWorld` hints for all 12 tools. Each docstring contains a `CONTRACT:` line that is verified against the registry by automated tests, preventing annotation drift.

---

## License

MIT -- see [LICENSE](LICENSE) for details.

## Acknowledgments

- [Model Context Protocol](https://modelcontextprotocol.io) by Anthropic
- Adobe CEP / ExtendScript documentation
