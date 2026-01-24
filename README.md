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
- **~15 Core Tools** - Essential operations; everything else via `illustrator_execute_script`
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
├── geometry.jsx    # getVisibleBounds(), mmToPoints()
├── selection.jsx   # getOrderedSelection()
└── layout.jsx      # arrangeImages(), distributeSpacing()
```

Scripts can request libraries via `inject_libraries(script, includes=["geometry"])`.

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

### 6. Context Before Creation

AI should always inspect document state before writing modification scripts:

```
1. get_document_structure  →  Understand what exists
2. get_selection_info      →  Know what's selected
3. execute_script          →  Modify with confidence
```

### 7. Fail Fast with Clear Errors

| Error Type | Handling |
|------------|----------|
| CEP not connected | `ILLUSTRATOR_DISCONNECTED` with connection steps |
| No document open | Clear message before script runs |
| Script syntax error | ExtendScript error message returned in full |
| Library not found | `ValueError: Library not found: {name}.jsx` |

### When to Add New Tools

Add a dedicated MCP tool **only** when:
1. The operation cannot be done via ExtendScript (e.g., file I/O, image import)
2. The operation is used in >80% of workflows (e.g., `create_document`)
3. The script would be >50 lines and identical every time

Otherwise, use `execute_script` with library injection.

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

## Available Tools (~15 total)

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

### Context & State Inspection (4)
| Tool | Description |
|------|-------------|
| `illustrator_get_document_structure` | Get complete document tree (layers, items) |
| `illustrator_get_selection_info` | Get detailed info about selected objects |
| `illustrator_get_app_info` | Get Illustrator application info |
| `illustrator_get_scripting_reference` | Quick ExtendScript syntax reference |

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
│   ├── proxy_client.py        # Script execution client
│   ├── bridge/                # WebSocket bridge components
│   │   ├── server.py          # WebSocket server transport
│   │   └── request_registry.py # Async request management
│   ├── resources/             # Static resources
│   │   └── scripts/           # ExtendScript libraries & Task Executor
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
├── cep-extension/             # Adobe CEP panel
│   ├── CSXS/manifest.xml      # CEP manifest
│   ├── index.html             # Panel UI
│   ├── js/main.js             # WebSocket client
│   ├── jsx/host.jsx           # ExtendScript bridge (with JSON polyfill)
│   └── .debug                 # Debug configuration
├── tests/                     # Unit tests
│   ├── conftest.py            # Shared fixtures
│   ├── test_documents.py
│   ├── test_shapes.py
│   ├── test_objects.py
│   ├── test_effects.py
│   ├── test_pathfinder.py
│   └── test_selection.py      # Selection tool tests
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
