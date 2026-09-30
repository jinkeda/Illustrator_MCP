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
npm test
npm run build
node validate-panel.mjs
cd ..
```

The optional `geometry` extra enables boolean path operations. Use
`python -m pip install -e .` if you do not need it.

On Windows, run `install-cep.bat` from an Administrator terminal.
On macOS, run `bash install-cep.sh`.
The installers link the panel into Adobe's CEP extensions directory and enable
CEP debug mode. Keep the checkout at its installed location.

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
The panel defaults to `ws://127.0.0.1:8081`; no panel configuration is required.

### Changing the WebSocket endpoint without rebuilding

For example, if port 8081 is occupied:

1. Set `WS_PORT` to `8082` in the MCP client's server environment and restart that
   integration. `WS_HOST` / `WS_PORT` (or the Python process's `.env`) configure
   only the Python server; Illustrator does not inherit the client's environment.
2. Copy `cep-extension/connection.example.json` to `cep-extension/connection.json`
   and set the matching endpoint:

   ```json
   {
     "endpoint": "ws://127.0.0.1:8082"
   }
   ```

3. Once Illustrator requests have finished, reload the panel (restart Illustrator
   if closing and reopening only hides/shows it). No source edit, rebuild, or
   reinstall is needed after installing a panel with this feature.

The file lives in the **installed extension root**, beside `CSXS`, `jsx`, and
`dist`, not inside `dist`. With the installers' normal symbolic link, this is the
checkout's `cep-extension/connection.json`. If the installer fell back to copying,
edit the installed copy under
`%APPDATA%\Adobe\CEP\extensions\com.illustrator.mcp.panel` (Windows) or
`~/Library/Application Support/Adobe/CEP/extensions/com.illustrator.mcp.panel`
(macOS). The panel logs the resolved configuration path at startup.

Configuration is read once per panel load. Reconnects continue using that endpoint;
the footer and connection-attempt log show the actual address. Delete
`connection.json` and reload to restore the default. The file is ignored by Git
and remains outside Vite's build output. A missing file uses the default; malformed
JSON, invalid URLs, and read errors stop connection attempts with a configuration
error instead of silently connecting to a different server. Use a JSON object
containing only `endpoint`, an absolute `ws://` or `wss://` URL without credentials
or a fragment. The bundled Python server uses `ws://` (no TLS); use a reachable
host address, not a bind wildcard such as `0.0.0.0`. Browser development previews
without CEP continue using the default and do not read local configuration.

## Distribution and versions

This source release pairs server 3.0.0 with CEP panel 1.0.2. Their version numbers
are independent. The source archive includes panel sources and installers; build
the panel before installing it. A Python wheel contains the server and its runtime
resources only; obtain the matching CEP panel separately from this source release.

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
