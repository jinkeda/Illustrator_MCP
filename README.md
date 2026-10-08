# Illustrator MCP

An MCP server that lets AI assistants control Adobe Illustrator through a CEP panel.
Version 3.0.0 supports structured artwork edits, ExtendScript, document management,
visual previews, PNG/JPG export, and SVG path import.

## Requirements

- Python 3.10 or newer.
- Adobe Illustrator on Windows or macOS. The panel manifest permits Illustrator 25.0+;
  this is an installation range, not a verified compatibility guarantee. Compatibility
  across that range and both platforms has not yet been validated.
- Node.js and npm compatible with Vite 6 to build the panel.
- An MCP client supporting stdio.

## Installation

Download or clone this repository, then open a terminal in its root directory.

```sh
python -m venv .venv
```

Activate the environment with `.venv\Scripts\activate` on Windows or
`source .venv/bin/activate` on macOS, then install:

```sh
python -m pip install -e ".[geometry]"
cd cep-extension
npm ci
npm run typecheck
npm run build
python validate_panel.py
cd ..
```

The optional `geometry` extra enables boolean path operations. Use
`python -m pip install -e .` if you do not need it.

With the Python environment activated, run `install-cep.bat` on Windows.
On macOS, run `bash install-cep.sh`.
The installers copy a filtered panel snapshot into Adobe's CEP extensions directory
and enable unsigned-extension loading for CEP 10, 11, and 12. Local `.debug`
remote-debugger configuration is excluded from installation and publication. The build
target is Chromium 74, matching the intended Illustrator 25.0 / CEP 10 baseline;
this does not establish real-host compatibility. Reinstall after rebuilding the panel.
Backups are stored outside Adobe discovery under `Illustrator MCP/cep-backups`
in `%APPDATA%` on Windows or `~/Library/Application Support` on macOS. A failed
activation restores the previous installation. Close Illustrator during upgrades.
An installed `connection.json` is preserved byte-for-byte during upgrades and
rollback, including invalid settings. Unreadable settings abort the upgrade.
Fresh installs exclude live configuration from the development checkout. When
upgrading a legacy or manual directory symlink, its linked `connection.json` is
the installed preference and is carried forward into the new copy. Publication
always excludes live configuration.

Restart Illustrator and open **Window > Extensions > MCP Control**.

## MCP client configuration

Add the following server definition to your client's MCP configuration, replacing
the interpreter path with the absolute path to your installed virtual environment:

```json
{
  "mcpServers": {
    "illustrator": {
      "command": "C:/path/to/Illustrator_MCP/.venv/Scripts/python.exe",
      "args": ["-B", "-m", "illustrator_mcp.server"],
      "env": {
        "WS_HOST": "127.0.0.1",
        "WS_PORT": "8081",
        "TIMEOUT": "30"
      }
    }
  }
}
```

On macOS use `/absolute/path/to/Illustrator_MCP/.venv/bin/python`.
Restart the client's integration and connect the panel. The Python server owns
the WebSocket bridge; only one client should start it at a time.
The default endpoint is `ws://127.0.0.1:8081`. To select another port, set Python's
`WS_PORT` and put `{"endpoint":"ws://127.0.0.1:8082"}` in `connection.json` at the
installed extension root (beside `CSXS` and `dist`), using the same port on both
sides. Use `cep-extension/connection.example.json` as a template. No rebuild is
needed after editing the installed file. Restart the MCP integration and reload
the panel only after running work and unacknowledged completions are resolved.
The panel reads its file once per load; Python environment settings do not change
it. Managed installs use copies. For a manual symlink installation the config
lives in the linked directory; the installer does not create symlinks.

Both sides accept IPv4 loopback only. `localhost` is normalized to `127.0.0.1`
for both Python binding and the panel connection. Panel URLs require `ws://`, an
explicit port from 1024 to 65535, and an empty/root path. Remote hosts, IPv6,
`wss://`, credentials, queries, and fragments are rejected. A missing file uses
the default; invalid/unreadable explicit settings create no socket. An unavailable
configured endpoint is retried without falling back to another port. The panel
footer and connection logs show the chosen endpoint and configuration source.

## Distribution and versions

This release pairs server 3.0.0 with CEP panel 1.0.2; their versions are independent.
The repository source ZIP/tarball (including `Illustrator_MCP.zip`) contains the
server, panel sources, and installers. The installation steps above require that
complete repository archive or a clone.

The Python wheel **and Python sdist** (`illustrator_mcp-*.tar.gz`) contain only
the server and its runtime resources. They do not include `cep-extension` or the
installers. When installing either Python distribution, obtain the matching
panel separately from the complete repository archive.

## Usage

Start with `illustrator_connection_status` using `{"params":{"probe":true}}`.
Open or create a document, then ask your assistant to inspect it before editing.

- `illustrator_document`: create, open, list, activate, save, or close documents.
- `illustrator_observe`: inspect previews and artwork context.
- `illustrator_get_document` and `illustrator_query_items`: inspect structure and targets.
- `illustrator_execute_task`: execute structured batches of artwork operations.
- `illustrator_execute_script`: execute ExtendScript with reusable libraries.
- `illustrator_place_file` and `illustrator_set_reference`: place assets and references.
- `illustrator_path_boolean` and `illustrator_path_import_svg`: work with vector paths.
- `illustrator_preflight_check`: check artwork before delivery.
- `illustrator_export_document`: export PNG or JPG.
- `illustrator_history`: undo, redo, and manage checkpoints.
- `illustrator_job_status`: inspect or reconcile an uncertain job.

The server exposes operation descriptions through `illustrator://ops`, scripting
guidance through `illustrator://reference/extendscript`, and library help through
`illustrator://reference/libraries` and `illustrator://libraries/{name}`.
Files under `illustrator_mcp/resources/docs/` supply these runtime references.

## Limitations and troubleshooting

This is alpha software. Native SVG/PDF export is currently unavailable; PNG/JPG
export and SVG path import are supported. Save your work before automated edits.

A timeout does not mean Illustrator stopped executing. Inspect and reconcile the
job before retrying an uncertain edit. Export supports `overwrite="fail"` and
`overwrite="version"` when replacement is unwanted.

If the panel does not connect, check that the client started the server and that
its WebSocket port matches the panel. Stop the previous client integration before
switching clients. For panel updates, rebuild the extension, reload the panel,
and restart the MCP server. Server diagnostics are written to stderr.

## License

MIT; see [LICENSE](LICENSE). Bundled third-party files retain their own notices.
