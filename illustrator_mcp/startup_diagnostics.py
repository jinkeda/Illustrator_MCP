"""Advisory, read-only startup evidence. Never participates in ownership."""

import errno
import json
import logging
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version

from illustrator_mcp.config import config

logger = logging.getLogger(__name__)
INSTANCE_ID = uuid.uuid4().hex
OWNER_LOOKUP_TIMEOUT = 3.0


def _version(package: str) -> str:
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"


def log_startup_identity() -> None:
    logger.info("MCP startup identity %s", json.dumps({
        "instance": INSTANCE_ID, "pid": os.getpid(), "parent_pid": os.getppid(),
        "cwd": os.getcwd(), "host": config.ws_host, "port": config.ws_port,
        "executable": sys.executable, "prefix": sys.prefix,
        "base_prefix": sys.base_prefix, "project_version": _version("illustrator-mcp"),
        "sdk_version": _version("mcp"),
    }))


def lookup_owners(port: int) -> list[dict]:
    """Snapshot all families/wildcards on this port; candidates aren't proven conflicts.

    subprocess.run kills and reaps its direct child on timeout. The PowerShell
    script starts no children and requires neither elevation nor extra packages.
    """
    if sys.platform != "win32":
        raise OSError("automatic owner lookup is available only on Windows")
    script = r"""
$ErrorActionPreference = 'Stop'
$listeners = @(Get-NetTCPConnection -State Listen -LocalPort PORT)
$processes = @(Get-CimInstance Win32_Process)
$result = @(foreach ($listener in $listeners) {
    $owner = $processes | Where-Object ProcessId -eq $listener.OwningProcess | Select-Object -First 1
    $chain = @()
    $current = $owner
    for ($depth = 0; $current -and $depth -lt 8; $depth++) {
        $chain += $current | Select-Object ProcessId, ParentProcessId, CreationDate, ExecutablePath, CommandLine
        $parentId = $current.ParentProcessId
        $current = $processes | Where-Object ProcessId -eq $parentId | Select-Object -First 1
    }
    [pscustomobject]@{address=$listener.LocalAddress; port=$listener.LocalPort;
        pid=$listener.OwningProcess; ancestry=$chain}
})
ConvertTo-Json -InputObject $result -Depth 5 -Compress
""".replace("PORT", str(int(port)))
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=OWNER_LOOKUP_TIMEOUT,
        creationflags=subprocess.CREATE_NO_WINDOW, check=True,
    )
    return json.loads(result.stdout)


def log_bind_failure(error: OSError, host: str, port: int) -> None:
    """Never replace the original error with an inspection failure."""
    logger.error("MCP instance=%s bind %s:%s failed: %r", INSTANCE_ID, host, port, error)
    if (error.errno not in {errno.EADDRINUSE, 10048}
            and getattr(error, "winerror", None) != 10048):
        return
    observed = datetime.now(timezone.utc).isoformat()
    try:
        owners = lookup_owners(port)
        if not owners or not any(owner.get("ancestry") for owner in owners):
            raise OSError("no owner identity obtained; listener may have disappeared")
        logger.error("Listener candidates observed=%s (compare failing address/family): %s",
                     observed, json.dumps(owners))
    except Exception as exc:
        if isinstance(exc, subprocess.TimeoutExpired):
            reason = f"lookup exceeded {OWNER_LOOKUP_TIMEOUT} seconds"
        elif isinstance(exc, subprocess.CalledProcessError):
            reason = f"lookup exited {exc.returncode} (access denied or inspection unavailable)"
        else:
            reason = str(exc)
        logger.error("owner unknown observed=%s: %s. Read-only fallback: "
                     "Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq %s; "
                     "Get-CimInstance Win32_Process", observed, reason, port)
    logger.error("Release the integration through its owning MCP client, then reconnect "
                 "the destination client. Do not terminate an unverified endpoint owner.")
