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
4. Context tools (`get_document_structure`, `get_selection_info`) let the AI understand document state before writing scripts

### Architecture

```
MCP Server Process
├── Main Thread  (MCP event loop, tool dispatch)
└── Bridge Thread (WebSocket server on port 8081)
    └── RequestRegistry (async request/response lifecycle)
```

Both threads coordinate via `run_in_executor()` / `run_coroutine_threadsafe()`. No separate proxy or Node.js process is required.

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

### Script Execution (2)

| Tool | Description |
|---|---|
| `illustrator_execute_script` | **Primary tool.** Execute any ExtendScript code in Illustrator. Supports library injection, params, bounds validation, and preview export. |
| `illustrator_execute_task` | Execute a structured task using the Task Protocol (collect > compute > apply). |

### Document Operations (8)

| Tool | Description |
|---|---|
| `illustrator_create_document` | Create a new document with specified dimensions and color mode |
| `illustrator_open_document` | Open an existing `.ai` / `.eps` / `.pdf` file |
| `illustrator_save_document` | Save the current document (or Save As to a new path) |
| `illustrator_export_document` | Export to PNG, JPG, SVG, or PDF with optional visual feedback |
| `illustrator_close_document` | Close the active document |
| `illustrator_import_image` | Place a raster image (PNG, JPG) as linked or embedded |
| `illustrator_place_file` | Place an external file (EPS, AI, PDF, image) with optional editable embed |
| `illustrator_update_linked_items` | Refresh all linked items from their source files |

### Undo / Redo (2)

| Tool | Description |
|---|---|
| `illustrator_undo` | Undo the last action |
| `illustrator_redo` | Redo the last undone action |

### Context & Inspection (5)

| Tool | Description |
|---|---|
| `illustrator_get_document_info` | Active document metadata (name, dimensions, saved status) |
| `illustrator_get_document_structure` | Full document tree: layers, sublayers, items with types, positions, bounds |
| `illustrator_get_selection_info` | Detailed info about selected objects (fill, stroke, text contents) |
| `illustrator_get_app_info` | Illustrator version, open document count, scripting version |
| `illustrator_get_scripting_reference` | ExtendScript syntax cheat sheet (coordinate system, shapes, colors, text) |

### Query & Validation (3)

| Tool | Description |
|---|---|
| `illustrator_query_items` | Declarative item query via the Task Protocol (target selectors, stable refs) |
| `illustrator_preflight_check` | Read-only validation: off-artboard items, zero-size items, empty text, locked layers |
| `illustrator_get_connection_info` | WebSocket connection status (useful for debugging multi-client issues) |

**Total: 20 tools.**

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
| `geometry` | `rectXY`, `ellipseXY`, `lineXY`, `makeRGBColor`, `getContext` | Intuitive XY coordinate helpers (x=right, y=down) |
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
| `ops_group` | Group / ungroup, z-order |
| `ops_layer` | Layer CRUD |
| `ops_style` | Fill, stroke, opacity |
| `ops_text` | Text frame creation and styling |
| `ops_align` | Alignment and distribution |
| `ops_measure` | Assertions (count, bounds, exists, style, alignment), snapshots, repair mode |
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

See [`PROTOCOL.md`](PROTOCOL.md) and [`SOC_CONTRACTS.md`](SOC_CONTRACTS.md) for full specifications.

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

### Raw ExtendScript

```javascript
var doc = app.activeDocument;
var rect = doc.pathItems.rectangle(-100, 50, 200, 100);
var c = new RGBColor(); c.red = 255; c.green = 0; c.blue = 0;
rect.fillColor = c;
```

> **Coordinate system:** Origin is top-left. Y is **negative downward**. Use `-y` for visual positions. Units are points (1 pt = 1/72 in).

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
- Use `illustrator_get_scripting_reference` for ExtendScript syntax
- File paths: use forward slashes or escaped backslashes

### Structured Error Codes

| Code | Category | Meaning |
|---|---|---|
| `C001` | Connection | Illustrator not connected |
| `V001` | Validation | No document open |
| `V002` | Validation | No selection |
| `R005` | Runtime | Layer not found |
| `R006` | Runtime | Element not found |
| `S001` | Script | Syntax error |
| `S002` | Script | Undefined variable |

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
│   ├── proxy_client.py           # Script execution client + response envelope
│   ├── websocket_bridge.py       # WebSocket bridge facade
│   ├── libraries.py              # Library resolver + manifest-driven injection
│   ├── protocol.py               # Task Protocol v2.3 Pydantic models
│   ├── errors.py                 # Structured error codes + suggestions
│   ├── templates.py              # Reusable ExtendScript templates
│   ├── response_models.py        # Pydantic models for responses
│   ├── utils.py                  # Path escaping, validation helpers
│   ├── log_config.py             # Structured logging config
│   ├── bridge/
│   │   ├── server.py             # WebSocket server transport
│   │   └── request_registry.py   # Async request lifecycle + streaming
│   ├── logging/
│   │   └── request_log.py        # JSON-lines logger
│   ├── utils/
│   │   └── chunking.py           # Auto-split large op batches
│   ├── schemas/                  # Generated JSON schemas
│   ├── tools/
│   │   ├── __init__.py           # Tool registration
│   │   ├── base.py               # Shared execute_jsx_tool helper
│   │   ├── execute.py            # execute_script + execute_task
│   │   ├── documents.py          # Document I/O tools
│   │   ├── context.py            # State inspection tools
│   │   ├── query.py              # query_items + preflight_check
│   │   └── archive/              # Disabled legacy tools (reference only)
│   └── resources/
│       ├── docs/
│       │   └── extendscript_reference.md
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
├── tests/                        # Unit tests (pytest)
│   ├── conftest.py               # Shared fixtures
│   ├── test_execute.py
│   ├── test_documents.py
│   ├── test_context.py
│   ├── test_protocol.py
│   ├── test_task_protocol_v23.py
│   ├── test_library_resolver.py
│   ├── test_injection.py
│   ├── test_templates.py
│   ├── test_proxy_client.py
│   ├── test_websocket_bridge.py
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
pip install -e ".[dev]"
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
4. **Context Before Creation** -- AI inspects document state (`get_document_structure`, `get_selection_info`) before writing modification scripts.
5. **Standardized Envelope** -- All tools return `{ok, warnings, error, diagnostics, result}` for consistent downstream handling.
6. **Fail Fast with Structured Errors** -- Typed error codes (V/R/S/C categories) with actionable recovery suggestions.

---

## License

MIT -- see [LICENSE](LICENSE) for details.

## Acknowledgments

- [Model Context Protocol](https://modelcontextprotocol.io) by Anthropic
- Adobe CEP / ExtendScript documentation
