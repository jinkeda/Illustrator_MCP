# Adobe Illustrator MCP Server

[![MCP](https://img.shields.io/badge/MCP-Compatible-blue)](https://modelcontextprotocol.io)
[![Python](https://img.shields.io/badge/Python-3.10+-green)](https://python.org)
[![Node.js](https://img.shields.io/badge/Node.js-18+-green)](https://nodejs.org)

An MCP (Model Context Protocol) server that enables AI assistants like Claude to control Adobe Illustrator programmatically using natural language.

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Available Tools](#available-tools-94-total)
- [Usage Examples](#usage-examples)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)
- [Development](#development)

---

## Features

- **94 AI-Friendly Tools** - Comprehensive coverage of Illustrator operations across 15 categories
- **Hybrid Architecture** - High-level tools + raw JavaScript execution for flexibility
- **Input Validation** - Pydantic models prevent errors before execution
- **Natural Language** - Tools designed for AI discoverability and ease of use
- **Cross-Platform** - Works on Windows and macOS
- **Tested** - Unit tests with mocked proxy + live testing with Illustrator 30.0

---

## Architecture

This project uses an **execute_script-based architecture**:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Claude / AI    │────▶│   MCP Server    │────▶│  Proxy Server   │────▶│   CEP Panel     │
│    Client       │     │    (Python)     │     │   (Node.js)     │     │  (Illustrator)  │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │                       │
    MCP Protocol         HTTP POST /execute       WebSocket           ExtendScript
     (stdio)             { "script": "..." }     (port 8081)          (host.jsx)
```

### How It Works

1. **AI calls a tool** (e.g., `illustrator_draw_rectangle`)
2. **Tool generates JavaScript** code internally
3. **MCP server sends** the script to the proxy via HTTP
4. **Proxy forwards** to Illustrator via WebSocket
5. **CEP panel executes** the script via ExtendScript and returns result

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| **Python** | 3.10+ | For MCP server |
| **Node.js** | 18+ | For proxy server |
| **Adobe Illustrator** | 25.0+ (2021+) | CC 2021 or later |

### Installing Prerequisites

**Python:**
```bash
# Windows (via winget)
winget install Python.Python.3.11

# macOS (via Homebrew)
brew install python@3.11
```

**Node.js:**
```bash
# Windows (via winget)
winget install OpenJS.NodeJS.LTS

# macOS (via Homebrew)
brew install node@18
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

### Step 3: Install Proxy Server Dependencies

```bash
cd proxy-server
npm install
cd ..
```

### Step 4: Install CEP Extension

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

### Proxy Server Configuration

Ports are configurable via a **`.env` file** in the project root:

**Step 1:** Copy the example file:
```bash
cp .env.example .env
```

**Step 2:** Edit `.env` as needed:
```env
# Proxy Server Ports
HTTP_PORT=8080
WS_PORT=8081

# Proxy Server Host (for MCP server to connect to)
PROXY_HOST=localhost

# Timeout for script execution (seconds)
TIMEOUT=30
```

| Setting | Default | Description |
|---------|---------|-------------|
| `HTTP_PORT` | 8080 | HTTP API port (MCP → Proxy) |
| `WS_PORT` | 8081 | WebSocket port (Proxy → Illustrator) |
| `PROXY_HOST` | localhost | Proxy server hostname |
| `TIMEOUT` | 30 | Script execution timeout (seconds) |

Both the Python MCP server and Node.js proxy server read from the same `.env` file.

---

## Usage

### Starting the System

**Terminal 1 - Start the Proxy Server:**
```bash
cd Illustrator_MCP/proxy-server
npm start
```

You should see:
```
[Proxy] WebSocket server listening on port 8081
[Proxy] HTTP server listening on port 8080
Waiting for Illustrator connection...
```

**Terminal 2 - Ensure Illustrator is running with the plugin loaded**

The plugin panel will show "✅ Connected" when successfully connected to the proxy.

**Terminal 3 - Start Claude Desktop** (or restart if already running)

### Verifying the Connection

1. Open the MCP Control panel in Illustrator (Window → Extensions → MCP Control)
2. Check for "✅ Connected" status
3. In Claude, try: "Create a new 800x600 Illustrator document"

---

## Available Tools (94 total)

### Core Tool (1)
| Tool | Description |
|------|-------------|
| `illustrator_execute_script` | Execute raw JavaScript in Illustrator |

### Document Operations (7)
| Tool | Description |
|------|-------------|
| `illustrator_create_document` | Create a new document |
| `illustrator_open_document` | Open an existing file |
| `illustrator_save_document` | Save the current document |
| `illustrator_export_document` | Export to PNG, JPG, SVG, PDF |
| `illustrator_get_document_info` | Get document properties |
| `illustrator_close_document` | Close the document |
| `illustrator_import_image` | Import PNG/JPG image into document |

### Artboard Management (5)
| Tool | Description |
|------|-------------|
| `illustrator_list_artboards` | Get all artboards with properties |
| `illustrator_create_artboard` | Add a new artboard |
| `illustrator_delete_artboard` | Remove artboard by index |
| `illustrator_set_active_artboard` | Switch to specified artboard |
| `illustrator_resize_artboard` | Change artboard dimensions |

### Shape Tools (6)
| Tool | Description |
|------|-------------|
| `illustrator_draw_rectangle` | Draw a rectangle |
| `illustrator_draw_ellipse` | Draw an ellipse/circle |
| `illustrator_draw_polygon` | Draw a regular polygon |
| `illustrator_draw_line` | Draw a line |
| `illustrator_draw_path` | Draw a custom path |
| `illustrator_draw_star` | Draw a star |

### Path Operations (10)
| Tool | Description |
|------|-------------|
| `illustrator_join_paths` | Join selected open paths |
| `illustrator_outline_stroke` | Convert stroke to filled path |
| `illustrator_offset_path` | Create parallel path at offset |
| `illustrator_simplify_path` | Reduce anchor points |
| `illustrator_smooth_path` | Smooth path curves |
| `illustrator_reverse_path` | Reverse path direction |
| `illustrator_make_compound_path` | Combine paths into compound |
| `illustrator_release_compound_path` | Split compound path |
| `illustrator_expand_appearance` | Expand effects/strokes to paths |
| `illustrator_flatten_transparency` | Flatten transparent objects |

### Pathfinder Operations (8)
| Tool | Description |
|------|-------------|
| `illustrator_pathfinder_unite` | Merge/combine shapes |
| `illustrator_pathfinder_minus_front` | Subtract front from back |
| `illustrator_pathfinder_minus_back` | Subtract back from front |
| `illustrator_pathfinder_intersect` | Keep only overlap |
| `illustrator_pathfinder_exclude` | Remove overlap |
| `illustrator_pathfinder_divide` | Divide at intersections |
| `illustrator_pathfinder_trim` | Trim overlapping areas |
| `illustrator_pathfinder_merge` | Merge same-color shapes |

### Text Tools (4)
| Tool | Description |
|------|-------------|
| `illustrator_add_text` | Add a text frame |
| `illustrator_set_text_font` | Change font properties |
| `illustrator_set_text_color` | Change text color |
| `illustrator_get_text_content` | Get text content |

### Typography (6)
| Tool | Description |
|------|-------------|
| `illustrator_create_text_on_path` | Text following a path |
| `illustrator_create_area_text` | Text inside a shape |
| `illustrator_convert_text_to_outlines` | Convert text to paths |
| `illustrator_set_paragraph_alignment` | Set text alignment |
| `illustrator_set_character_spacing` | Set tracking/kerning |
| `illustrator_set_line_height` | Set line spacing |

### Layer Tools (6)
| Tool | Description |
|------|-------------|
| `illustrator_list_layers` | List all layers |
| `illustrator_create_layer` | Create a new layer |
| `illustrator_delete_layer` | Delete a layer |
| `illustrator_set_active_layer` | Set active layer |
| `illustrator_rename_layer` | Rename a layer |
| `illustrator_toggle_layer_visibility` | Show/hide layer |

### Object Operations (10)
| Tool | Description |
|------|-------------|
| `illustrator_duplicate_selection` | Duplicate with offset |
| `illustrator_copy_to_layer` | Copy selection to layer |
| `illustrator_lock_selection` | Lock selected objects |
| `illustrator_unlock_all` | Unlock all objects |
| `illustrator_hide_selection` | Hide selected objects |
| `illustrator_show_all` | Show all hidden objects |
| `illustrator_get_object_bounds` | Get bounding box |
| `illustrator_rename_object` | Rename selected object |
| `illustrator_set_opacity` | Set transparency |
| `illustrator_set_blend_mode` | Set blend mode |

### Selection Tools (7)
| Tool | Description |
|------|-------------|
| `illustrator_select_all` | Select all objects |
| `illustrator_deselect_all` | Clear selection |
| `illustrator_get_selection` | Get selection info |
| `illustrator_delete_selection` | Delete selected objects |
| `illustrator_move_selection` | Move selection |
| `illustrator_scale_selection` | Scale selection |
| `illustrator_rotate_selection` | Rotate selection |

### Styling Tools (5)
| Tool | Description |
|------|-------------|
| `illustrator_set_fill_color` | Set fill color (RGB) |
| `illustrator_set_stroke_color` | Set stroke color (RGB) |
| `illustrator_set_stroke_width` | Set stroke width |
| `illustrator_remove_fill` | Remove fill |
| `illustrator_remove_stroke` | Remove stroke |

### Effects & Gradients (7)
| Tool | Description |
|------|-------------|
| `illustrator_apply_drop_shadow` | Add drop shadow |
| `illustrator_apply_blur` | Apply Gaussian blur |
| `illustrator_apply_inner_glow` | Add inner glow |
| `illustrator_apply_outer_glow` | Add outer glow |
| `illustrator_clear_effects` | Remove all effects |
| `illustrator_apply_linear_gradient` | Linear gradient fill |
| `illustrator_apply_radial_gradient` | Radial gradient fill |

### Arrange Tools (8)
| Tool | Description |
|------|-------------|
| `illustrator_align_objects` | Align objects |
| `illustrator_distribute_objects` | Distribute objects |
| `illustrator_group_selection` | Group objects |
| `illustrator_ungroup_selection` | Ungroup objects |
| `illustrator_make_clipping_mask` | Create clipping mask |
| `illustrator_release_clipping_mask` | Release clipping mask |
| `illustrator_bring_to_front` | Bring to front |
| `illustrator_send_to_back` | Send to back |

### Transform Tools (4)
| Tool | Description |
|------|-------------|
| `illustrator_reflect_selection` | Mirror horizontally/vertically |
| `illustrator_shear_selection` | Skew/shear objects |
| `illustrator_transform_each` | Transform each individually |
| `illustrator_reset_bounding_box` | Reset bounding box |

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

The AI will:
1. Get document info to find center
2. Draw an ellipse at the center
3. Set fill color to red

### Working with Text

**Prompt:** "Add a title 'SALE' in bold 72pt Arial at the top"

```python
illustrator_add_text(content="SALE", x=100, y=100, font_family="Arial", font_size=72)
illustrator_set_text_font(font_style="Bold")
illustrator_set_text_color(red=255, green=0, blue=0)
```

### Complex Layouts

**Prompt:** "Create 5 rectangles and distribute them evenly horizontally"

The AI will:
1. Create 5 rectangles
2. Select all
3. Call `illustrator_distribute_objects(distribution="horizontal")`

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

### Advanced: Raw JavaScript

**Prompt:** "Apply 50% opacity to the selected object"

```python
illustrator_execute_script(script="app.activeDocument.selection[0].opacity = 50;")
```

---

## Troubleshooting

### "Illustrator is not connected"

1. ✅ Ensure Illustrator is running
2. ✅ Check panel is visible: Window → Extensions → MCP Control
3. ✅ Check proxy is running: `cd proxy-server && npm start`
4. ✅ Check panel shows "Connected" status
5. ✅ Try clicking "Connect" in the panel

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

---

## Project Structure

```
Illustrator_MCP/
├── illustrator_mcp/           # Python MCP server
│   ├── __init__.py
│   ├── server.py              # Entry point
│   ├── shared.py              # Shared MCP instance
│   ├── proxy_client.py        # HTTP client for proxy
│   └── tools/                 # 94 tools across 15 modules
│       ├── __init__.py
│       ├── execute.py         # Raw script execution (1)
│       ├── documents.py       # Document operations (7)
│       ├── artboards.py       # Artboard management (5)
│       ├── shapes.py          # Shape drawing (6)
│       ├── paths.py           # Path operations (10)
│       ├── pathfinder.py      # Boolean operations (8)
│       ├── text.py            # Text tools (4)
│       ├── typography.py      # Advanced typography (6)
│       ├── layers.py          # Layer management (6)
│       ├── objects.py         # Object operations (10)
│       ├── selection.py       # Selection tools (7)
│       ├── styling.py         # Fill/stroke styling (5)
│       ├── effects.py         # Effects & gradients (7)
│       ├── arrange.py         # Alignment & grouping (8)
│       └── transform.py       # Transformations (4)
├── proxy-server/              # Node.js WebSocket bridge
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
│   └── test_pathfinder.py
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

With Illustrator and proxy server running:

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

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- [Model Context Protocol](https://modelcontextprotocol.io) by Anthropic
- [adobe-mcp](https://github.com/david-t-martel/adobe-mcp) for architectural inspiration
- Adobe UXP documentation
