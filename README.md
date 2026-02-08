# Adobe Illustrator MCP Server

[![MCP](https://img.shields.io/badge/MCP-Compatible-blue)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/Python-3.10+-green)](https://python.org)

An MCP (Model Context Protocol) server that enables AI assistants like Claude to control Adobe Illustrator programmatically using natural language.

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Available Tools](#available-tools-15-total)
- [Usage Examples](#usage-examples)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)
- [Development](#development)

---

## Features

- **Scripting First Architecture** - Minimal toolset
- **~16 Core Tools** - Essential operations; everything else via `illustrator_execute_script`
- **Standardized Response Envelope** - All tools return `{ok, warnings, error, diagnostics, result}`
- **Task Protocol v2.3** - Structured execution with:
  - Standardized error codes (V/R/S categories)
  - Compound target selectors with deterministic ordering
  - Safe retry semantics (never auto-retries `apply`)
  - Stable references with locator/identity/tag separation
- **Manifest-Driven Libraries** - Transitive dependency resolution with collision detection
- **Simplified Architecture** - Single Python server with integrated WebSocket bridge (no Node.js required!)
- **Input Validation** - Pydantic models prevent errors before execution
- **Cross-Platform** - Works on Windows and macOS
- **Tested** - Unit tests with mocked proxy + live testing with Illustrator 30.0

---

## Architecture

This project uses a **simplified single-server architecture**:

```
┌─────────────────┐     ┌─────────────────────────────────┐     ┌─────────────────┐
│  Claude / AI    │────▶│   MCP Server (Python)           │────▶│   CEP Panel     │
│    Client       │     │   + Integrated WebSocket Bridge │     │  (Illustrator)  │
└─────────────────┘     └─────────────────────────────────┘     └─────────────────┘
        │                              │                                │
    MCP Protocol                  WebSocket                       ExtendScript
     (stdio)                    (port 8081)                       (host.jsx)
```

### How It Works

1. **AI calls `illustrator_execute_script`** with ExtendScript code
2. **MCP server sends** the script via WebSocket to the CEP panel
3. **CEP panel executes** the script via ExtendScript and returns result
4. **Context tools** help AI understand document state before writing scripts

### Why Single Server?

Previous versions required a separate Node.js proxy server. The new architecture:
- ✅ **Simpler setup** - Just one server to run
- ✅ **Fewer dependencies** - No Node.js required
- ✅ **More reliable** - No inter-process communication issues
- ✅ **Easier troubleshooting** - Single point of failure

### Thread Architecture

The MCP server uses a dual-thread architecture to handle async MCP calls and WebSocket communication:

```
┌─────────────────────────────────────────────────────────────┐
│ MCP Server Process                                           │
│                                                              │
│  ┌──────────────────┐         ┌───────────────────────┐    │
│  │  Main Thread     │         │  Bridge Thread        │    │
│  │  (MCP Event Loop)│◀────────▶│  (WebSocket Loop)    │    │
│  │                  │  Future │                       │    │
│  │  - Tool calls    │         │  - WebSocket server   │    │
│  │  - run_in_executor()────────▶run_coroutine_threadsafe()│ │
│  └──────────────────┘         └───────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                                        │
                                        │ WebSocket (port 8081)
                                        ▼
                                ┌───────────────┐
                                │  CEP Panel    │
                                │  (Illustrator)│
                                └───────────────┘
```

| Component | Description |
|-----------|-------------|
| **Main Thread** | Runs the MCP event loop, handles tool calls from Claude |
| **Bridge Thread** | Runs WebSocket server, manages CEP panel connection |
| **Coordination** | Uses `run_in_executor()` + `run_coroutine_threadsafe()` for cross-thread communication |

### Extension Support

| Extension | Directory | Status |
|-----------|-----------|--------|
| **CEP Extension** | `cep-extension/` | ✅ Fully supported (primary) |
| **UXP Plugin** | `uxp-plugin/` | 🚧 Reserved for future use |

> **Note:** The UXP plugin directory exists but is not yet functional. CEP remains the primary extension for Illustrator 2021-2024+.

---

## Design Principles & Philosophy
The design is guided by these core principles:

### 1. Minimal Tool Surface

| Principle | Rationale |
|-----------|-----------|
| **~15 core tools, not 100+** | Platforms like Antigravity have ~100 tool limits; fewer tools = faster loading |
| **One powerful script executor** | `execute_script` handles any operation ExtendScript supports |
| **Context tools for understanding** | `get_document_structure`, `get_selection_info` help AI write correct scripts |

### 2. Thick Scripts, Thin Server

Move complexity **into ExtendScript**, not Python:

```
❌ Thin Script (Anti-pattern)        ✅ Thick Script (Preferred)
───────────────────────────────────  ─────────────────────────────────────
Python: calculate bounds             ExtendScript: calculate bounds
Python: loop through items           ExtendScript: loop through items  
Python: call MCP 50 times            ExtendScript: do everything in 1 call
```

**Benefits:**
- Fewer round-trips (network latency)
- Atomic operations (all-or-nothing)
- Illustrator-native calculations (accurate bounds, transforms)

### 3. Library Injection Pattern

For complex operations, use reusable ExtendScript libraries:

```
resources/scripts/
├── geometry.jsx    # XY coords, bounds, colors: rectXY(), ellipseXY(), makeRGBColor()
├── selection.jsx   # getOrderedSelection()
├── layout.jsx      # createGrid(), distributeHorizontal(), alignCenter()
├── presets.jsx     # COLOR_PALETTES, getColor(), applyPreset()
└── task_executor.jsx # Task Protocol execution framework
```

Scripts can request libraries via `includes` parameter:

```javascript
// Single library
illustrator_execute_script({
    script: "var rect = rectXY(50, 100, 200, 150);",
    includes: ["geometry"]
});

// Multiple libraries (dependencies auto-resolved)
illustrator_execute_script({
    script: "var items = createGrid({rows: 2, cols: 2, ...});",
    includes: ["geometry", "layout"]
});
```

| Library | Key Exports | Use Case |
|---------|-------------|----------|
| `geometry` | `rectXY`, `ellipseXY`, `lineXY`, `makeRGBColor`, `getContext` | Shape creation with intuitive coords |
| `layout` | `createGrid`, `distributeHorizontal`, `alignCenter` | Layout and alignment |
| `presets` | `COLOR_PALETTES`, `getColor`, `applyPreset` | Color palettes and grid presets |
| `selection` | `getOrderedSelection` | Spatial sorting of selection |
| `task_executor` | `executeTask`, `collectTargets` | Structured task execution |
| `validate` | `countItemsOnArtboard` | Bounds validation and preflight checks |
| `op_schemas` | `validateOpParams`, `getOpSchema` | Auto-generated parameter schemas for SOC ops |
| `snapshot` | `captureSnapshot`, `restoreSnapshot` | Document state snapshot/restore for rollback |
| `ops_core` | `executeOpBatch`, `registerOpHandler`, `invalidateIdIndex` | SOC batch executor with ID index caching |
| `ops_element` | — | Create, modify, delete shapes |
| `ops_group` | — | Group/ungroup, z-order |
| `ops_layer` | — | Layer CRUD |
| `ops_style` | — | Fill, stroke, opacity |
| `ops_text` | — | Text frame operations |
| `ops_align` | — | Alignment, distribution |
| `ops_measure` | — | Assertions (count, bounds, exists, style), snapshots |

### 5. Task Protocol Architecture (v2.2)

For complex, multi-item operations, use the **Task Protocol** for structured execution:

```javascript
// Task execution with collect → compute → apply stages
var payload = {
    task: 'apply_fill',
    targets: {type: 'selection'},  // Declarative targeting
    params: {color: [255, 0, 0]},
    options: {trace: true}
};

var report = executeTask(payload, collectTargets, compute, apply);
// Returns: {ok: true, stats: {...}, timing: {...}, errors: [], warnings: []}
```

| Feature | Description |
|---------|-------------|
| **Declarative Targets** | `{type: 'selection'}`, `{type: 'layer', layer: 'Layer 1'}`, `{type: 'all'}` |
| **Structured Reports** | Timing breakdown, item stats, error localization |
| **Stable References** | `ItemRef` with layerPath, indexPath, itemId |
| **Trace Mode** | Step-by-step execution logging |
| **Retry Mechanism** | `executeTaskWithRetry()` for fault tolerance |

### 5.1 SOC Framework (State-Ops-Checks)

For high-complexity tasks (≥50 elements, multi-step layouts), use the SOC Framework:

```javascript
var ops = [
    {task: 'element_create', params: {id: 'A1', type: 'rect', x: 100, y: 100, width: 50, height: 50}},
    {task: 'style_set_fill', targets: {type: 'id', ids: ['A1']}, params: {r: 255, g: 0, b: 0}},
    {task: 'assert_exists', params: {ids: ['A1']}}
];
var report = executeOpBatch(ops, {strict: true, trace: true});
// Returns: {ok, schemaVersion, ops: [{index, task, ok, id}], stats, timing, trace}
```

| Feature | Description |
|---------|-------------|
| **Stable ID Targeting** | `@mcp:id=UUID` in item.note for deterministic refs |
| **Batch Validation** | Schema-validated params (auto-generated from `gen_schemas.py`) |
| **Strict/Continue Modes** | Stop on first error or collect all errors |
| **Per-Op Reporting** | Index, task, duration, warnings per operation |
| **summaryOnly Mode** | Omit per-op details for ~80% response size reduction |
| **Global ID Index** | O(1) element lookups cached in `$.global.mcpIdIndex` |
| **Snapshot Rollback** | `{rollback: true, snapshot: true}` for state-based undo |
| **Python Chunking** | `execute_op_batch_chunked()` auto-splits large batches |
| **assert_style** | Verify fill/stroke/opacity with RGB + CMYK support |
| **WebSocket Streaming** | Progress updates via `execute_script_streaming()` |

> See `.agent/skills/state-ops-checks/SKILL.md` for full documentation.

### 6. Context Before Creation

AI should always inspect document state before writing modification scripts:

```
1. get_document_structure  →  Understand what exists
2. get_selection_info      →  Know what's selected
3. execute_script          →  Modify with confidence
```

### 7. Fail Fast with Clear Errors

Errors now include structured codes and actionable suggestions:

| Error Code | Category | Example Message |
|------------|----------|-----------------|
| `C001` | Connection | Illustrator not connected |
| `V001` | Validation | No document open |
| `V002` | Validation | No selection |
| `R005` | Runtime | Layer not found |
| `R006` | Runtime | Element not found |
| `S001` | Script | Syntax error |
| `S002` | Script | Undefined variable |

**Example error response:**
```
Error [R006]: Element not found
Context: execute_script: get layer

Suggestions:
  - The item may have been deleted or renamed
  - Use illustrator_get_document_structure to verify item exists
  - Check item name spelling (case-sensitive)
```

### When to Add New Tools

Add a dedicated MCP tool **only** when:
1. The operation cannot be done via ExtendScript (e.g., file I/O, image import)
2. The operation is used in >80% of workflows (e.g., `create_document`)
3. The script would be >50 lines and identical every time
4. The operation must produce a standardized, canonical output schema that other agents/tools depend on (contract enforcement). Otherwise, use `execute_script` with library injection.

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| **Python** | 3.10+ | For MCP server |
| **Adobe Illustrator** | 25.0+ (2021+) | CC 2021 or later |

> **Note:** Node.js is no longer required! The proxy server functionality is now built into the Python MCP server.

### Installing Prerequisites

**Python:**
```bash
# Windows (via winget)
winget install Python.Python.3.11

# macOS (via Homebrew)
brew install python@3.11
```

**Administrator Access:**
Required for CEP extension installation (creating symbolic links and registry edits).

---

## Installation

### Step 1: Clone the Repository

```bash
git clone https://github.com/yourusername/Illustrator_MCP.git
cd Illustrator_MCP
```

### Step 2: Install Python Package

```bash
# Install in development mode
pip install -e .

# Verify installation
illustrator-mcp --help
```

### Step 3: Install CEP Extension

**Windows (Run as Administrator):**
```bash
install-cep.bat
```

This script will:
1. Create a symbolic link to the CEP extensions folder
2. Enable debug mode in the Windows registry

**Manual Installation (if script fails):**
1. Copy `cep-extension` folder to:
   - Windows: `%APPDATA%\Adobe\CEP\extensions\com.illustrator.mcp.panel`
   - macOS: `~/Library/Application Support/Adobe/CEP/extensions/com.illustrator.mcp.panel`
2. Enable debug mode for **both** CSXS versions (required for Illustrator 2024+):
   ```powershell
   # Windows (run in PowerShell)
   reg add "HKEY_CURRENT_USER\Software\Adobe\CSXS.11" /v PlayerDebugMode /t REG_SZ /d 1 /f
   reg add "HKEY_CURRENT_USER\Software\Adobe\CSXS.12" /v PlayerDebugMode /t REG_SZ /d 1 /f
   ```
   ```bash
   # macOS
   defaults write com.adobe.CSXS.11 PlayerDebugMode 1
   defaults write com.adobe.CSXS.12 PlayerDebugMode 1
   ```
3. Restart Illustrator

The panel will appear in Illustrator under **Window → Extensions → MCP Control**

---

## Configuration

### Claude Desktop Configuration

Add the following to your Claude Desktop configuration file:

**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "illustrator": {
      "command": "illustrator-mcp"
    }
  }
}
```

**Alternative (using Python directly):**
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

### Optional Configuration

Ports are configurable via a **`.env` file** in the project root:

```env
# WebSocket port (CEP panel connects here)
WS_PORT=8081

# Timeout for script execution (seconds)
TIMEOUT=30

# Note: Configuration is validated on startup.
# Ports must be valid integers (1024-65535) and distinct.
```

| Setting | Default | Description |
|---------|---------|-------------|
| `WS_PORT` | 8081 | WebSocket port (MCP server ↔ CEP panel) |
| `TIMEOUT` | 30 | Script execution timeout (seconds) |

---

## Usage

### Starting the System

**Step 1:** Start Claude Desktop (or restart if already running)

The MCP server starts automatically and includes the WebSocket bridge.

**Step 2:** Open Adobe Illustrator

**Step 3:** Open the CEP Panel: Window → Extensions → MCP Control

The panel should automatically connect and show "✅ Connected"

### That's it! No separate proxy server needed.

### Verifying the Connection

1. Open the MCP Control panel in Illustrator (Window → Extensions → MCP Control)
2. Check for "✅ Connected" status
3. In Claude, try: "Create a new 800x600 Illustrator document"

---

## Available Tools (~16 total)

This MCP follows a **Scripting First Architecture**. Most Illustrator operations should be done via the `illustrator_execute_script` tool rather than specialized atomic tools.

### Core Script Execution (1)
| Tool | Description |
|------|-------------|
| `illustrator_execute_script` | **PRIMARY TOOL** - Execute any ExtendScript code in Illustrator |

### Document Operations (10)
| Tool | Description |
|------|-------------|
| `illustrator_create_document` | Create a new document |
| `illustrator_open_document` | Open an existing file |
| `illustrator_save_document` | Save the current document |
| `illustrator_export_document` | Export to PNG, JPG, SVG, PDF |
| `illustrator_get_document_info` | Get document properties |
| `illustrator_close_document` | Close the document |
| `illustrator_import_image` | Import PNG/JPG image into document |
| `illustrator_place_file` | Place linked/embedded file |
| `illustrator_undo` | Undo last action |
| `illustrator_redo` | Redo last undone action |

### Context & State Inspection (5)
| Tool | Description |
|------|-------------|
| `illustrator_get_document_structure` | Get complete document tree (layers, items) |
| `illustrator_get_selection_info` | Get detailed info about selected objects |
| `illustrator_get_app_info` | Get Illustrator application info |
| `illustrator_get_scripting_reference` | Quick ExtendScript syntax reference |
| `illustrator_preflight_check` | Validate document (bounds, zero-size, empty text, locked items) |

### Why Scripting First?

Instead of 100+ specialized tools, this architecture:
- ✅ **Reduces tool count** - Stays under platform limits (e.g., Antigravity's 100-tool max)
- ✅ **More flexible** - Any Illustrator operation is possible via scripting
- ✅ **Better for complex tasks** - Combine multiple operations in one script
- ✅ **Easier maintenance** - Fewer tools to maintain and test

### Using execute_script

```javascript
// Draw a red rectangle
var doc = app.activeDocument;
var rect = doc.pathItems.rectangle(-100, 50, 200, 100);
var c = new RGBColor(); c.red = 255; c.green = 0; c.blue = 0;
rect.fillColor = c;
```

> **Note:** Y coordinates are negative downward. Use `-y` for visual positions.

### Disabled Tool Modules

The following modules exist but are disabled to keep tool count minimal:
- artboards, shapes, paths, pathfinder, text, typography
- layers, objects, selection, styling, effects, arrange
- transform, composite, patterns

These still work via `illustrator_execute_script` - check `get_scripting_reference` for syntax.

---

## Usage Examples

### Basic Document Creation

**Prompt:** "Create a new 1920x1080 document for a YouTube thumbnail"

The AI will call:
```python
illustrator_create_document(width=1920, height=1080, name="YouTube Thumbnail")
```

### Drawing Shapes

**Prompt:** "Draw a red circle with 100pt diameter in the center of the document"

The AI will use `illustrator_execute_script`:
```javascript
var doc = app.activeDocument;
var centerX = doc.width / 2;
var centerY = doc.height / 2;

// Draw circle (ellipse with equal width/height)
var circle = doc.pathItems.ellipse(
    -centerY + 50,  // top (Y is negative downward)
    centerX - 50,   // left
    100,            // width
    100             // height
);

// Set red fill
var red = new RGBColor();
red.red = 255; red.green = 0; red.blue = 0;
circle.fillColor = red;
circle.stroked = false;
```

### Working with Text

**Prompt:** "Add a title 'SALE' in bold 72pt Arial at the top"

The AI will use `illustrator_execute_script`:
```javascript
var doc = app.activeDocument;
var tf = doc.textFrames.add();
tf.contents = "SALE";
tf.position = [100, -100];  // Note: -y for visual position

// Style the text
tf.textRange.characterAttributes.size = 72;
tf.textRange.characterAttributes.textFont = app.textFonts.getByName("Arial-BoldMT");

// Red color
var red = new RGBColor();
red.red = 255; red.green = 0; red.blue = 0;
tf.textRange.characterAttributes.fillColor = red;
```

### Complex Layouts

**Prompt:** "Create 5 rectangles and distribute them evenly horizontally"

The AI will use `illustrator_execute_script`:
```javascript
var doc = app.activeDocument;
var rects = [];
for (var i = 0; i < 5; i++) {
    var rect = doc.pathItems.rectangle(-100, 50 + i * 80, 60, 60);
    rect.selected = true;
    rects.push(rect);
}
// Use Align palette action or calculate positions
```

### Importing Images

**Prompt:** "Import logo.png and place it at position 50, 50"

```python
illustrator_import_image(file_path="C:/images/logo.png", x=50, y=50, link=True)
```

### Exporting

**Prompt:** "Export the document as PNG at 2x resolution"

```python
illustrator_export_document(file_path="C:/output/design.png", format="png", scale=2.0)
```

### Advanced: Complex Scripts

**Prompt:** "Create a gradient-filled rectangle with rounded corners"

The AI will use `illustrator_execute_script`:
```javascript
var doc = app.activeDocument;

// Rounded rectangle
var rect = doc.pathItems.roundedRectangle(
    -100,   // top
    50,     // left
    200,    // width
    100,    // height
    15,     // horizontal radius
    15      // vertical radius
);

// Create gradient
var gradient = doc.gradients.add();
gradient.type = GradientType.LINEAR;

// Add color stops
var stop1 = gradient.gradientStops[0];
var blue = new RGBColor(); blue.red = 0; blue.green = 100; blue.blue = 255;
stop1.color = blue;
stop1.rampPoint = 0;

var stop2 = gradient.gradientStops[1];
var purple = new RGBColor(); purple.red = 128; purple.green = 0; purple.blue = 255;
stop2.color = purple;
stop2.rampPoint = 100;

// Apply gradient
var gradColor = new GradientColor();
gradColor.gradient = gradient;
rect.fillColor = gradColor;
```

---

## Troubleshooting

### "ILLUSTRATOR_DISCONNECTED: CEP panel is not connected"

This is the most common error. Follow these steps:

1. ✅ **Ensure Illustrator is running**
2. ✅ **Open the CEP panel:** Window → Extensions → MCP Control
3. ✅ **Check panel status:** Should show "✅ Connected"
4. ✅ **If "Disconnected":** Click the "Connect" button
5. ✅ **Still not working?** Restart Claude Desktop (this restarts the MCP server)

### "No document is open"

Create or open a document before running commands that operate on documents.

### Script execution errors

- Debug CEP panel at `http://localhost:8088` (Chrome DevTools)
- Use `illustrator_execute_script` to test scripts manually
- Verify file paths use forward slashes or escaped backslashes

### CEP Panel won't appear in Extensions menu

1. Ensure Illustrator version is 25.0+ (2021 or later)
2. Verify debug mode is enabled (see installation steps)
3. Check extension is installed in correct location
4. Restart Illustrator after installation

### Claude doesn't see the tools

1. Restart Claude Desktop after adding the configuration
2. Check configuration file syntax (valid JSON)
3. Verify the `illustrator-mcp` command works in terminal

### WebSocket connection issues

The MCP server includes an integrated WebSocket server on port 8081. If connection fails:

1. Check if port 8081 is in use: `netstat -ano | findstr 8081`
2. If another process is using the port, stop it or change `WS_PORT` in `.env`
3. Restart Claude Desktop to restart the MCP server

---

## Project Structure

```
Illustrator_MCP/
├── illustrator_mcp/           # Python MCP server
│   ├── __init__.py
│   ├── server.py              # Entry point
│   ├── runtime.py             # Runtime dependency injection
│   ├── log_config.py          # Structured logging configuration
│   ├── protocol.py            # Task Protocol Pydantic models
│   ├── config.py              # Configuration (Pydantic Settings)
│   ├── websocket_bridge.py    # Bridge facade
│   ├── shared.py              # Shared context
│   ├── proxy_client.py        # Script execution client + chunked batch execution
│   ├── bridge/                # WebSocket bridge components
│   │   ├── server.py          # WebSocket server transport
│   │   └── request_registry.py # Async request management + streaming support
│   ├── logging/               # Structured request logging
│   │   └── request_log.py     # JSON-lines logger (~/.illustrator-mcp/logs/)
│   ├── utils/                 # Utility modules
│   │   └── chunking.py        # Op batch chunking for large operations
│   ├── resources/             # Static resources
│   │   └── scripts/           # ExtendScript libraries
│   │       ├── manifest.json  # Library metadata & exports
│   │       ├── geometry.jsx   # XY coords, bounds, colors (v2.0)
│   │       ├── layout.jsx     # Grid, distribution, alignment (v2.0)
│   │       ├── presets.jsx    # Layout presets & color palettes (v2.0)
│   │       ├── selection.jsx  # Selection utilities
│   │       ├── task_executor.jsx # Task Protocol framework
│   │       ├── validate.jsx   # Bounds validation & preflight
│   │       ├── op_schemas.jsx # Auto-generated param schemas (from gen_schemas.py)
│   │       ├── snapshot.jsx   # Document state snapshot/restore
│   │       ├── ops_core.jsx   # SOC batch executor + ID index
│   │       ├── ops_element.jsx # Element create/modify/delete
│   │       ├── ops_group.jsx  # Group/ungroup, z-order
│   │       ├── ops_layer.jsx  # Layer CRUD
│   │       ├── ops_style.jsx  # Fill, stroke, opacity
│   │       ├── ops_text.jsx   # Text frame operations
│   │       ├── ops_align.jsx  # Alignment, distribution
│   │       └── ops_measure.jsx # Assertions + measurement
│   ├── schemas/               # Generated JSON schemas
│   └── tools/                 # ~15 tools (Scripting First)
│       ├── __init__.py        # Tool registration
│       ├── execute.py         # Core (execute_script)
│       ├── documents.py       # Document I/O
│       ├── context.py         # Inspection
│       ├── query.py           # Item Query (Task Protocol)
│       └── archive/           # Archived legacy tools
├── proxy-server/              # [DEPRECATED] Node.js proxy (no longer needed)
│   ├── package.json
│   └── index.js
├── cep-extension/             # Adobe CEP panel (React/Vite)
│   ├── CSXS/manifest.xml      # CEP manifest
│   ├── dist/                  # Built output (npm run build)
│   ├── public/                # Static assets (CSInterface.js)
│   ├── src/                   # React source
│   │   ├── components/        # UI components
│   │   │   └── MCPControlPanel.tsx  # Main panel UI
│   │   └── hooks/             # Custom hooks
│   │       └── useMCP.ts      # WebSocket connection hook
│   ├── jsx/host.jsx           # ExtendScript bridge
│   ├── package.json           # Node dependencies
│   ├── vite.config.ts         # Vite build config
│   └── .debug                 # Debug configuration
├── tests/                     # Unit tests
│   ├── conftest.py            # Shared fixtures
│   ├── test_documents.py
│   ├── test_shapes.py
│   ├── test_objects.py
│   ├── test_effects.py
│   ├── test_pathfinder.py
│   └── test_selection.py      # Selection tool tests
├── scripts/                   # Developer tools
│   └── gen_schemas.py         # Schema codegen (python -m scripts.gen_schemas)
├── install-cep.bat            # Windows CEP installer
├── pyproject.toml             # Python package config
└── README.md
```

---

## Development

### Running Tests

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run all unit tests
pytest tests/ -v

# Run specific test file
pytest tests/test_shapes.py -v
```

The test suite uses mocked `execute_script` calls to verify JavaScript generation without requiring Illustrator.

### Live Testing

With Illustrator running and CEP panel connected:

```python
import asyncio
from illustrator_mcp.tools.documents import illustrator_create_document, CreateDocumentInput
from illustrator_mcp.tools.shapes import illustrator_draw_rectangle, DrawRectangleInput

async def test():
    # Create document
    await illustrator_create_document(CreateDocumentInput(width=800, height=600))

    # Draw a rectangle
    await illustrator_draw_rectangle(DrawRectangleInput(x=100, y=100, width=200, height=150))

asyncio.run(test())
```

---

## Migration from Previous Versions

If you were using the old version with a separate Node.js proxy server:

1. **Stop the Node.js proxy server** - It's no longer needed
2. **Update the Python package:** `pip install -e .`
3. **Restart Claude Desktop** - This starts the new integrated server
4. **Open CEP panel in Illustrator** - It will connect to the new server

The Node.js `proxy-server` folder is kept for reference but is no longer used.

---

## Changelog

### v2.12.0 (2026-02-07) - SOC HARDENING & INTEGRATION

Fixes and integrations based on code review of v2.11.0 changes.

**Bug Fixes**
- **ID index invalidation on deletes:** `element_delete` handler now calls `invalidateIdIndex()` after successful deletes, preventing stale index lookups
- **Streaming race condition:** `push_update` and `complete_streaming` in `request_registry.py` now perform lookup + queue put entirely inside the lock, eliminating race between concurrent calls
- **Streaming queue bounded:** `asyncio.Queue(maxsize=1000)` prevents unbounded memory growth on long-running streaming operations
- **Snapshot rollback now deletes created items:** On batch failure, newly created elements are removed before restoring snapshot state (previously they were orphaned)

**Schema Unification**
- Deleted hand-written `op_schemas.jsx` — now auto-generated from `gen_schemas.py` as single source of truth
- All parameter names synchronized: `contents`/`fontSize`/`fontName`/`mode` (codegen wins)
- Generated file includes `AUTO-GENERATED` header with timestamp

**Chunking Integration**
- **New:** `execute_op_batch_chunked()` in `proxy_client.py` — auto-splits large batches with `should_chunk()` check
- Automatically applies `summaryOnly` to each chunk for reduced response size
- Merges chunk results with `merge_chunk_results()` for unified stats

**CMYK Support in assert_style**
- New `cmykMatches()` and unified `checkColor()` helper in `ops_measure.jsx`
- Handles RGBColor, CMYKColor, and reports unsupported color types with clear messages
- Color mode mismatch produces descriptive errors (e.g., "expected CMYK but got RGB")

### v2.11.0 (2026-02-07) - ADVANCED IMPROVEMENTS

Major reliability and developer experience improvements for complex workflows.

**Session 1: Core SOC Improvements**
- **summaryOnly option** (`ops_core.jsx`) — Reduces response size ~80% for large batches by omitting per-op details, returning only stats + createdIds
- **Global ID Index** (`ops_core.jsx`) — O(1) element lookups cached in `$.global.mcpIdIndex` with auto-invalidation on document change. Helpers: `invalidateIdIndex()`, `registerIdInIndex()`
- **assert_style check op** (`ops_measure.jsx`) — Verify fill/stroke/opacity with tolerance-based color matching

**Session 2: Advanced Infrastructure**

**Request Logging** (`logging/request_log.py`)
- JSON-lines structured logging to `~/.illustrator-mcp/logs/`
- Session management with trace ID correlation
- Script files saved on errors for debugging and replay

**Schema Codegen** (`scripts/gen_schemas.py`)
- Generates `op_schemas.jsx` from Python `OpSchema` definitions
- Single source of truth for parameter validation schemas
- Run: `python -m scripts.gen_schemas`

**Python Chunking** (`utils/chunking.py`)
- Automatic splitting of large operation batches
- Separate limits for create ops (heavier) vs general ops
- Iterator-based for memory efficiency

**Snapshot/Restore Rollback** (`snapshot.jsx`)
- Replaces fragile undo-based rollback with explicit state capture
- Captures geometry, fill, stroke, opacity for MCP-managed items
- Color serialization for RGB, CMYK, Gray, Spot, and NoColor
- Usage: `executeOpBatch(ops, {rollback: true, snapshot: true})`

**WebSocket Streaming** (`request_registry.py`, `websocket_bridge.py`, `main.js`)
- New `execute_script_streaming()` async generator for progress updates
- `StreamingRequest` with bounded async queue (`maxsize=1000`)
- CEP panel wrapper for `$.global.__mcpProgress()` callbacks
- Usage:
```python
async for update in bridge.execute_script_streaming(script):
    if update["type"] == "progress":
        print(f"Progress: {update['data']}")
```

**Files Changed:**
| File | Change |
|------|--------|
| `logging/request_log.py` | NEW (~200 lines) |
| `scripts/gen_schemas.py` | NEW (~320 lines) |
| `utils/chunking.py` | NEW (~180 lines) |
| `snapshot.jsx` | NEW (~280 lines) |
| `op_schemas.jsx` | NEW (auto-generated, ~500 lines) |
| `request_registry.py` | MODIFY (+120 lines) |
| `websocket_bridge.py` | MODIFY (+80 lines) |
| `cep-extension/js/main.js` | MODIFY (+75 lines) |
| `proxy_client.py` | MODIFY (+80 lines) |
| `ops_core.jsx` | MODIFY (+40 lines) |
| `ops_measure.jsx` | MODIFY (+80 lines) |
| `manifest.json` | MODIFY (+12 lines) |

### v2.10.0 (2026-02-07) - VISUAL FEEDBACK & ROBUSTNESS

Production-ready patterns integrated from blender-mcp for better debugging and reliability.

**Visual Feedback**
- **New:** `return_image` parameter in `export_document` (PNG/JPG only)
- When `true`, returns MCP `ImageContent` so Claude can see the export inline
- Enables visual verification loops: export → Claude sees → corrects → re-exports

**Connection Robustness**
- **New:** Health-check in `check_connection_or_error()` with auto-reconnect
- Detects stale connections and resets bridge for fresh connection
- Automatic recovery from CEP panel restarts

**3-Tier Error Handling**
- **Tier 1 (Connection):** C001-C003 codes for WebSocket/CEP issues
- **Tier 2 (Timeout):** `[TIMEOUT]` with actionable suggestions
- **Tier 3 (Runtime):** R000, V001 codes for script/protocol errors
- All errors include clear suggestions for recovery

**SOC Workflow Strategy**
- **New:** Decision tree in `state-ops-checks/SKILL.md`
- When to use SOC vs raw script
- Visual verification loop pattern

**Usage:**
```python
# Export with visual feedback
export_document({
    "file_path": "output.png",
    "format": "png",
    "return_image": true  # Claude sees the image
})
```

### v2.9.0 (2026-02-06) - SOC FRAMEWORK

New **State-Ops-Checks Framework** for deterministic batch operations on complex layouts.

**8 New JSX Libraries**
- `ops_core` - Batch executor with validation, ID-based targeting, caching
- `ops_element` - Create/modify/delete shapes (rect, ellipse, line, polygon, star)
- `ops_group` - Group/ungroup, z-order manipulation
- `ops_layer` - Layer CRUD (create, activate, lock, visible, delete)
- `ops_style` - Fill, stroke, opacity operations
- `ops_text` - Text frame creation and styling
- `ops_align` - Horizontal/vertical alignment and distribution
- `ops_measure` - Assertions (count, bounds, exists) and snapshots

**Key Features**
- **Stable ID Targeting**: `@mcp:id=UUID` in item.note for deterministic references
- **Batch Validation**: All ops validated before execution
- **Strict/Continue Modes**: Stop on first error or collect all errors
- **Per-Op Reporting**: Index, task, duration, warnings per operation

**Usage**
```javascript
var ops = [
    {task: 'element_create', params: {id: 'A1', type: 'rect', x: 100, y: 100, width: 50, height: 50}},
    {task: 'style_set_fill', targets: {type: 'id', ids: ['A1']}, params: {r: 255, g: 0, b: 0}},
    {task: 'assert_exists', params: {ids: ['A1']}}
];
executeOpBatch(ops, {strict: true, trace: true});
```

> See `.agent/skills/state-ops-checks/SKILL.md` for full documentation.

### v2.8.0 (2026-01-29) - BOUNDS VALIDATION & PREFLIGHT CHECK

Major improvements to prevent off-artboard placement errors with standardized response envelope.

**Standardized Response Envelope**
- **New:** `format_envelope()` function in `proxy_client.py` - ALL tools now return consistent JSON structure
- **Contract:** `{ok, warnings, error, diagnostics, result}` - stable API for integration
- **Updated:** `base.py`, `execute.py`, `documents.py`, `query.py` all use envelope pattern

**New Validation Library** (`validate.jsx`)
- **New:** `countItemsOnArtboard(opts)` - Count items on/off artboard with configurable policies
- **Policies:**
  - `"fully-contained"` - item must be entirely within artboard (for validation)
  - `"intersects"` - item must have any overlap (for blank export detection)
- **Options:** `artboardIndex`, `boundsType` (visible/geometric), `ignoreHidden`, `ignoreLocked`
- **Returns:** `{on_artboard, off_artboard, skipped, items_total, off_items_sample}`

**New Preflight Check Tool**
- **New:** `illustrator_preflight_check` - READ-ONLY observational validation tool
- **Checks:** Off-artboard items, zero-size items, empty text frames, locked layers/items
- **Returns:** Envelope with `ok: false` when issues detected, warnings populated
- **Usage:** Run before export to catch placement errors early

**Enhanced Execute Script**
- **New:** `validate_bounds` parameter - Optional post-execution bounds check
- **New:** `bounds_type` parameter - "visible" (includes strokes) or "geometric" (path only)
- **New:** `artboard_index` parameter - Target specific artboard for validation
- **Behavior:** Adds warnings to envelope if items are off-artboard after script runs

**Enhanced Export Document**
- **New:** `artboard_only` parameter - Clip export to artboard bounds (PNG artBoardClipping)
- **New:** Pre-export bounds check with "intersects" policy
- **Warning:** "Nothing intersects artboard - export will be blank" when no content visible

**Usage Examples:**
```python
# Preflight check before export
illustrator_preflight_check({})
# Returns: {"ok": false, "warnings": ["2 items outside artboard bounds"], ...}

# Execute with bounds validation
illustrator_execute_script({
    "script": "...",
    "validate_bounds": true
})
# Returns: {"ok": true, "warnings": ["3 items outside artboard..."], ...}

# Export clipped to artboard
illustrator_export_document({
    "file_path": "output.png",
    "artboard_only": true
})
```

### v2.7.0 (2026-01-28) - DEVELOPER EXPERIENCE IMPROVEMENTS

Major improvements to reduce cognitive load and improve error feedback based on practical usage testing.

**Phase 1: Intuitive XY Coordinate System** (`geometry.jsx` v2.0)
- **New:** `getContext()` - Get artboard-relative coordinate context
- **New:** `rectXY(x, y, w, h, options)` - Rectangle with intuitive (x, y) coords (x=right, y=down)
- **New:** `ellipseXY(x, y, w, h)` - Ellipse with intuitive coords
- **New:** `lineXY(x1, y1, x2, y2)` - Line with intuitive coords
- **New:** `polygonXY(points, closed)` - Polygon from [x, y] point array
- **New:** `pointXY(x, y)` - Convert intuitive coords to Illustrator position
- **New:** `makeRGBColor(r, g, b)` - Helper for creating RGB colors
- **Benefit:** Eliminates Y-inversion confusion and (top, left, w, h) parameter order issues

**Phase 2: Layout Helpers** (`layout.jsx` v2.0)
- **New:** `createGrid(params)` - Create centered grid of shapes with colors, corner radius
- **New:** `distributeHorizontal(items, gap)` - Distribute items with even/fixed spacing
- **New:** `distributeVertical(items, gap)` - Vertical distribution
- **New:** `alignCenter(items)` - Center items on artboard
- **New:** `alignHorizontal(items, 'left'|'center'|'right')` - Horizontal alignment
- **New:** `alignVertical(items, 'top'|'center'|'bottom')` - Vertical alignment
- **Benefit:** Microsoft-style logo grid in 5 lines instead of 40

**Phase 3: Structured Error Handling** (`errors.py` expanded)
- **New:** `ErrorCode` enum with 20+ codes (C001-C003, V001-V009, R001-R008, S001-S004)
- **New:** `ERROR_SUGGESTIONS` database mapping codes to recovery suggestions
- **New:** `StructuredError` dataclass for rich error responses
- **New:** `classify_error()` - Auto-detect error type from message
- **New:** `format_error_response()` - Format errors with actionable suggestions
- **Updated:** `proxy_client.py` uses structured error formatting
- **Updated:** `tools/base.py` passes context to format_response
- **Benefit:** "Error: No such element" → "Error [R006]: Element not found" + suggestions

**Phase 4: Color Palettes** (`presets.jsx` v2.0)
- **New:** `COLOR_PALETTES` object with 9 palettes:
  - `okabe_ito` (8 colors) - Colorblind-safe, recommended for publications
  - `nature` (6 colors) - Nature journal style
  - `tol_muted` (7 colors) - Paul Tol's muted palette
  - `science_minimal` (3 colors) - Black/blue/gray
  - `microsoft` (4 colors) - Microsoft brand
  - `google` (4 colors) - Google brand
  - `grayscale` (4 colors) - Black to white
  - `viridis` (6 colors) - Perceptually uniform
  - `category10` (10 colors) - D3.js categorical
- **New:** `getColor(palette, index)` - Get RGBColor from palette
- **New:** `getPalette(name)` - Get all colors as array
- **New:** `applyPaletteToItems(items, palette)` - Apply palette to selection
- **New:** `listPalettes()` - List available palette names

**Usage Examples:**
```javascript
// Intuitive coordinates (includes: ["geometry"])
var rect = rectXY(50, 100, 200, 150);  // 50pt from left, 100pt from top

// Create Microsoft logo (includes: ["geometry", "layout"])
var items = createGrid({
    rows: 2, cols: 2,
    itemWidth: 110, itemHeight: 110,
    gapX: 12, cornerRadius: 8,
    colors: [{r:243,g:83,b:37}, {r:129,g:188,b:6}, {r:5,g:166,b:240}, {r:255,g:186,b:8}]
});

// Color palettes (includes: ["geometry", "presets"])
rect.fillColor = getColor('okabe_ito', 0);  // First colorblind-safe color
```

### v2.6.1 (2026-01-25) - MULTI-CLIENT FIX
- **Security:** Reject duplicate WebSocket connections with error 4001 (fixes multi-client conflict)
- **New:** `illustrator_get_connection_info` tool for debugging connection state
- **New:** `get_connection_info()` method on `WebSocketBridge`
- **Improved:** Standardized error messages for duplicate connections in `shared.py`

### v2.6.0 (2026-01-24) - TEMPLATE CONSOLIDATION
- **Refactor:** Moved 5 more inline scripts to templates:
  - `close_document`, `embed_placed_items`, `update_linked_items` in `documents.py`
  - `get_document_structure`, `get_selection_info` in `context.py`
- **Improved:** Test fixtures now use `ExitStack` for cleaner patch management
- **New:** `is_running()` method on `WebSocketBridge` for better encapsulation
- **Refactor:** `shared.py` now uses `bridge.is_running()` instead of accessing `_thread` directly

### v2.5.0 (2026-01-24) - CODE QUALITY REFACTORING
- **New:** `response_models.py` - Pydantic models for ExtendScript responses (DocumentInfo, OperationResult, ExportResult, PlaceItemResult)
- **Improved:** Error messages now include actionable quick fixes for connection issues
- **Refactor:** Consolidated inline scripts to templates in `documents.py` (export, get_document_info)
- **Cleanup:** Removed dead test files for archived tools (test_shapes, test_pathfinder, test_effects, test_objects, test_selection)
- **Fixed:** `conftest.py` no longer references non-existent shapes module

### v2.4.4 (2026-01-24) - TOOLINPUTBASE MIGRATION
- **Refactor:** All 10 Pydantic input models now inherit from `ToolInputBase`
  - Removes ~30 lines of repeated `model_config = ConfigDict(str_strip_whitespace=True)`
  - Affected: `documents.py` (7 models), `execute.py` (2 models), `query.py` (1 model)

### v2.4.3 (2026-01-24) - EDITABLE PDF IMPORT
- **New:** `embed_editable` parameter in `illustrator_place_file` tool
  - Opens PDF as document, copies content, pastes as editable vectors
  - Slower than linked placement but produces fully editable GroupItems
  - Usage: `place_file(file_path, x, y, embed_editable=True)`

### v2.4.2 (2026-01-23) - TEMPLATE CONSOLIDATION
- **Refactor:** Merged `IMPORT_IMAGE` and `PLACE_FILE` templates into single `PLACE_ITEM` template
- **New:** `_place_item_impl()` helper function for import/place operations (~40 lines reduced)
- **Refactor:** `undo` and `redo` now use `templates.UNDO` and `templates.REDO`
- **New:** `ToolInputBase` class in `base.py` for shared Pydantic configuration

### v2.4.1 (2026-01-23) - CODEBASE REFACTORING
Major refactoring to reduce duplication and improve maintainability:

- **New:** `tools/base.py` with `execute_jsx_tool()` helper - reduces ~10 lines boilerplate per tool
- **Refactor:** `format_response()` now uses `_try_parse_json()` and `_unwrap_result()` helpers
- **New:** Pytest markers `@pytest.mark.live` and `@pytest.mark.unit` in `conftest.py`
- **New:** `format_task_report()` function in `protocol.py` for shared TaskReport formatting
- **Refactor:** Export logic in `documents.py` consolidated with config dict (4 branches → 2)
- **New:** `templates.py` module with 15 ExtendScript templates using `string.Template`
- **New:** `test_websocket_bridge.py` with tests for `RequestRegistry`

**Impact:** ~150 lines of boilerplate eliminated, 15 tools now use single-line `execute_jsx_tool()` pattern.


### v2.4.0 (2026-01-23) - ASSET ANALYSIS & LAYOUT PRESETS

Two new ExtendScript libraries accessible via `execute_script` with `includes`:

**New Libraries:**
- **assets.jsx** - Analyze placed items (bounds, aspect ratio, orientation)
  - `analyzeAssets(scope)` - Collect metadata for selection/document/layer
  - `getAssetInfo(item)` - Get single item metadata
- **presets.jsx** - Pre-defined grid layouts with slot geometry
  - `PRESETS` - 2x2, 3x1, 1x3, 2x3, 3x2, 1x2, 2x1 grid definitions
  - `computeSlotGeometry()` - Calculate slot positions for grid
  - `applyPreset()` - Arrange items in grid with contain/cover modes

**Usage:**
```javascript
// Analyze assets: includes: ["assets", "geometry"]
var manifest = analyzeAssets("document");

// Apply layout: includes: ["presets", "geometry"]
var result = applyPreset("2x2", doc.selection, "contain");
```



### v2.3.7 (2026-01-23) - ES5 POLYFILLS & LIVING TEST
- **Added:** ES5 array polyfills in `task_executor.jsx`:
  - `Array.prototype.forEach()`
  - `Array.prototype.map()`
  - `Array.prototype.filter()`
  - `Array.prototype.every()`
  - `Array.prototype.some()`
  - `Array.prototype.reduce()`
- **Refactor:** `QueryItemsInput` now uses nested `targets` dict matching Task Protocol format
  - Before: `target_type="layer", layer_name="Layer 1"`
  - After: `targets={"type": "layer", "layer": "Layer 1"}`
- **Added:** Living test suite with 10 test cases (8 PASS, 1 PARTIAL, 1 SKIPPED)
- **Fixed:** Removed unused `Optional` import from `query.py`

### v2.3.6 (2026-01-22) - BUG FIXES & STABILITY
- **Fixed:** `query_items` tool now correctly returns items in `dryRun` mode (moved storage to compute stage)
- **Fixed:** Added ES3-compatible `Array.prototype.indexOf` polyfill in `task_executor.jsx` for ExtendScript
- **Fixed:** `proxy_client.py` now correctly handles double-wrapped JSON responses from Illustrator
- **Removed:** Unused `httpx` dependency from `pyproject.toml`
- **Added:** `docs/ARCHITECTURE.md` documenting import patterns and circular import solutions

### v2.3.5 (2026-01-22) - FINAL CLEANUP
- **Refactor:** Consolidated path escaping in `documents.py` using `escape_path_for_jsx()` (5 instances)
- **Refactor:** Updated `conftest.py` to only reference active tool modules (removed 11 archived)
- **Improved:** Added debug logging for non-JSON ExtendScript returns
- **Security:** Added 10MB message size guard in `websocket_bridge.py`
- **Added:** Return type hint for `_handle_message()`

### v2.3.4 (2026-01-22) - ARCHITECTURE CLEANUP
- **Refactor:** Extracted `LibraryResolver` to dedicated `libraries.py` module (~200 lines from execute.py)
- **Refactor:** Propagated `trace_id` through `RequestRegistry.create_request()` for better correlation
- **Removed:** Unused imports (`IllustratorError`, `create_connection_error` in proxy_client, `lru_cache` in execute)
- **Simplified:** `execute.py` now imports `inject_libraries` from `libraries.py`

### v2.3.3 (2026-01-22) - EXTENDED CODE QUALITY
- **Refactor:** Removed unused config fields (`http_port`, `proxy_host`)
- **Added:** Timeout constants (`BRIDGE_STARTUP_TIMEOUT`, `BRIDGE_EXECUTION_BUFFER`, `RECONNECT_INTERVAL_MS`)
- **Added:** `utils.py` with `escape_path_for_jsx()`, `validate_file_path()`, `escape_string_for_jsx()`
- **Improved:** Specific exception handling (`ConnectionError` catch before generic `Exception`)
- **Updated:** `websocket_bridge.py` uses named constants instead of magic numbers

### v2.3.2 (2026-01-22) - CODE QUALITY REFACTORING
- **Refactor:** Consolidated connection handling with `check_connection_or_error()` in `shared.py`
- **Refactor:** Added `CommandMetadata` dataclass and `ExecutionResponse` TypedDict for type safety
- **Refactor:** Unified `trace_id` across proxy_client and websocket_bridge (replaces request_id)
- **Refactor:** Removed `time.sleep(0.1)` from bridge start, added `wait_until_ready()` method
- **Refactor:** Added `ConnectionState` enum for bridge state management
- **Refactor:** Added `log_command()` helper for centralized logging format
- **Added:** `errors.py` with `IllustratorError` enum for standardized error codes
- **Added:** `templates.py` with reusable script wrappers (`wrap_script_with_error_handling()`)
- **Added:** `__version__.py` for single-source version management
- **Added:** JSX dependency metadata in `layout.jsx` with programmatic checks
- **Added:** `LogLevel` enum and `setLogLevel()` in CEP panel for debug filtering
- **Updated:** `pyproject.toml` with correct author, `pytest-cov`, dynamic versioning
- **Updated:** ExtendScript reference moved to `resources/docs/extendscript_reference.md`
- **Updated:** `PendingRequest` dataclass now includes `trace_id` field

### v2.3.0 (2026-01-21) - FORMALIZED PROTOCOL
- **Protocol:** Full Task Protocol v2.3 specification with formal contract
- **Added:** Standardized error codes with categories:
  - Validation (V001-V008): Fail before execution
  - Runtime (R001-R006): Fail during execution (retryable)
  - System (S001-S004): Environment issues
- **Added:** `makeError()` helper for structured error creation
- **Added:** Compound target selectors with `anyOf` and `exclude` filters
- **Added:** Deterministic ordering via `OrderBy` enum (8 modes: reading, column, zOrder, name, etc.)
- **Added:** `sortItems()` and `filterItems()` functions in task_executor.jsx
- **Added:** Stable reference refactoring:
  - Separated `ItemLocator` (volatile) / `ItemIdentity` (stable) / `ItemTags` (user-controlled)
  - `parseMcpTags()` for `@mcp:key=value` syntax
  - `describeItemV2()` with new structure
  - `assignItemIdV2()` with `IdPolicy` (none/opt_in/always/preserve) and conflict detection
- **Added:** Safe retry semantics:
  - `executeTaskWithRetrySafe()` that never auto-retries `apply` stage
  - `isRetryable()` helper for stage-aware retry decisions
  - `Idempotency` enum (safe/unknown/unsafe)
  - `RetryPolicy` and `RetryInfo` models
- **Added:** Payload validation with `validatePayload()` for fail-fast errors
- **Added:** JSON Schema generation from Pydantic models (`schemas/` directory)
- **Added:** Manifest-driven library injection (`manifest.json`):
  - Transitive dependency resolution
  - Symbol collision detection
  - Library content caching
- **Added:** `PROTOCOL.md` comprehensive protocol reference
- **Deprecated:** `executeTaskWithRetry()` (use `executeTaskWithRetrySafe()`)

### v2.3.1 (2026-01-21) - V2.3 IMPLEMENTATION FIXES
- **Fixed:** Compound target selectors now properly implemented in `collectTargets()`
- **Fixed:** `TargetSelector` wrapper handling now correctly unwraps in `executeTask()`
- **Fixed:** Global exclusion and ordering applied after target collection
- **Fixed:** Protocol version string in `protocol.py` updated from 2.3.0 to 2.3.1
- **Added:** `validatePayload()` function for version validation (fails fast on major version mismatch)
- **Added:** Thread architecture diagram to README
- **Added:** Runtime schema validation utilities in `schemas/__init__.py`
- **Updated:** `safeExecute()` now uses `describeItemV2()` for error reporting
- **Updated:** `executeTask()` uses `assignItemIdV2()` with `idPolicy` option
- **Deprecated:** `describeItem()` and `assignItemId()` (use V2 variants, removed in v3.0)
- **Improved:** Added explanatory comments to silent catch blocks for debugging
- **Tests:** Added `test_protocol.py` for V2.3 ItemRef structure
- **Tests:** Added `test_task_protocol_v23.py` for compound selectors, TargetSelector, retry policies
- **Fixed:** Consolidated duplicate `validatePayload` in `task_executor.jsx` (hoisting conflict)
- **Fixed:** `manifest.json` export name typo (`recordTaskExecution` -> `recordTaskHistory`)
- **Fixed:** Recursive `collectLayerItems` for deep nested group support
- **Added:** `exclude.clipped` filter support in `collectTargets`
- **Refactor:** Unified connection error handling (ILLUSTRATOR_DISCONNECTED) in shared/proxy/bridge
- **Refactor:** Centralized logging configuration in `log_config.py` with structured JSON support
- **Refactor:** Thread-safe `LibraryResolver` with locks and `lru_cache`
- **Refactor:** Deterministic `WebSocketBridge` shutdown using `asyncio.Event`
- **Refactor:** Decomposed `WebSocketBridge` into `bridge/server.py` and `bridge/request_registry.py`
- **Refactor:** Configuration via `pydantic-settings` with validation
- **Refactor:** Explicit tool registration in `tools/__init__.py` (removed side-effect imports)
- **Cleanup:** Archived 15 disabled legacy tool modules to `tools/archive/`
- **Improved:** Dynamic tool counting in startup log (replaces hardcoded "94 tools")

### v2.1.0 (2026-01-17) - THICK SCRIPTS
- **Added:** Standard Library Injection support in `illustrator_execute_script`
- **Added:** `resources/scripts/` directory with core libraries:
  - `geometry.jsx`: Robust bounds calculation (handles clipping masks)
  - `selection.jsx`: Spatial sorting (Row-Major/Column-Major)
  - `layout.jsx`: Grid arrangement engine
- **Updated:** `execute.py` now accepts `includes=["geometry", "selection"]` parameter

### v2.0.0 (2026-01-16) - SCRIPTING FIRST ARCHITECTURE
- **BREAKING:** Reduced from 107 tools to ~15 tools
- **Architecture:** Use `illustrator_execute_script` for most operations
- **Added:** `context.py` module with document state inspection tools:
  - `get_document_structure` - Complete document tree
  - `get_selection_info` - Selected object details
  - `get_app_info` - Illustrator version info
  - `get_scripting_reference` - ExtendScript syntax help
- **Disabled:** artboards, shapes, paths, pathfinder, text, typography, layers, objects, selection, styling, effects, arrange, transform, composite, patterns modules
- **Why:** Antigravity and other platforms have ~100 tool limits

### v1.2.0 (2026-01-14)
- **Added:** 13 new tools (94 → 107 total)
  - Pattern Tools (6): `create_pattern`, `apply_pattern`, `transform_pattern`, `set_fill_opacity`, `apply_gradient`, `list_patterns`
  - Selection Tools (3): `select_by_name`, `find_objects`, `select_on_layer`
  - Layer Tools (2): `lock_layer`, `unlock_layer`
  - Text Tools (2): `find_replace_font`, `list_document_fonts`
- **Added:** Wildcard pattern matching for selection by name
- **Added:** Font management tools for document consistency

### v1.1.0 (2026-01-14)
- **Fixed:** WebSocket binding changed from `0.0.0.0` to `localhost` for better Windows compatibility
- **Improved:** Enhanced startup logging with clear success/failure indicators
- **Improved:** CEP panel reconnection reduced from 5s to 3s with better error messages
- **Added:** Port conflict detection with helpful troubleshooting messages
- **Added:** FastMCP lifespan management for proper WebSocket bridge startup/shutdown
- **Added:** Hybrid command protocol with metadata for better logging and debugging

### v1.0.0
- Initial release with integrated WebSocket bridge (no Node.js proxy required)
- 94 tools across 15 categories

---

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- [Model Context Protocol](https://modelcontextprotocol.io) by Anthropic
- Adobe UXP documentation
