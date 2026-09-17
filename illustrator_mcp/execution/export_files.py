"""Process-local export ownership. Unknown exporters never trigger file cleanup."""
from dataclasses import dataclass, asdict
import hashlib
import os
from pathlib import Path
import uuid


def fingerprint(path):
    try:
        p = Path(path)
        st = p.stat()
        digest = hashlib.sha256()
        with p.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, digest.hexdigest())
    except FileNotFoundError:
        return None


@dataclass
class ExportFiles:
    output: str
    backup: str | None = None
    original: tuple | None = None
    request_token: str | None = None
    state: str = "prepared"
    host_finished: bool = False
    host_ok: bool = False
    detail: str | None = None
    directory_entries: tuple = ()
    completed_output: tuple | None = None
    completion_captured: bool = False
    overwrite: str = "replace"
    # Successful exclusive restoration is separate from backup deletion.
    # Preserve the original completion fingerprint, including an absent output.
    restored_output: tuple | None = None
    verify_raster: bool = False
    raster_size: tuple | None = None
    raster_error: str | None = None

    def snapshot(self):
        return asdict(self)

    @property
    def retained(self):
        return self.backup is not None and self.state not in ("verified", "restored")

    def prepare(self):
        if self.overwrite not in ("replace", "fail", "version"):
            raise ValueError("Unknown overwrite policy: " + self.overwrite)
        if Path(self.output).suffix.lower() == ".svg":
            self.directory_entries = tuple(os.listdir(Path(self.output).parent))
            if len(self.directory_entries) > 4096:
                raise OSError("Use a smaller export directory for bounded SVG asset verification")
        self.original = fingerprint(self.output)
        if self.original is None:
            return
        if self.overwrite != "replace":
            self.state = "conflict"
            self.detail = "Export destination became occupied; overwrite='" + self.overwrite + "' forbids replacement."
            raise FileExistsError(self.detail)
        self.backup = self.output + ".mcp-backup-" + uuid.uuid4().hex
        # Hard-link creation is exclusive and never replaces another backup.
        # Both names remain until identity is checked; a locked file fails safely.
        try:
            os.link(self.output, self.backup)
        except OSError:
            self.backup = None
            raise
        if fingerprint(self.output) != self.original:
            self.state = "conflict"
            raise OSError("Export destination changed during backup; both paths retained")
        os.unlink(self.output)

    def finalize(self):
        if self.state in ("verified", "restored"):
            return self.snapshot()
        if not self.host_finished:
            self.state = "pending_completion"
            return self.snapshot()
        try:
            output = fingerprint(self.output)
            expected_output = self.restored_output if self.restored_output is not None else self.completed_output
            if (self.completion_captured or self.restored_output is not None) and output != expected_output:
                self.state = "conflict"
                phase = "restoration" if self.restored_output is not None else "correlated completion"
                self.detail = "Destination changed after " + phase + "; output and backup retained."
                return self.snapshot()
            if self.restored_output is None and self.host_ok and Path(self.output).suffix.lower() == ".svg":
                from xml.etree import ElementTree
                try:
                    root = ElementTree.parse(self.output).getroot()
                    for element in root.iter():
                        if element.tag.split("}")[-1] == "image":
                            href = element.get("{http://www.w3.org/1999/xlink}href", element.get("href", ""))
                            if not href.startswith("data:"):
                                raise ValueError("SVG contains an external image")
                    allowed = set(self.directory_entries) | {Path(self.output).name}
                    if self.backup:
                        allowed.add(Path(self.backup).name)
                    if set(os.listdir(Path(self.output).parent)) - allowed:
                        raise ValueError("Export directory gained auxiliary files; no cleanup authorized")
                except (ValueError, ElementTree.ParseError) as exc:
                    self.host_ok = False
                    self.detail = str(exc)
            if self.restored_output is None and self.host_ok and self.verify_raster:
                try:
                    from PIL import Image
                    with Image.open(self.output) as raster:
                        raster.load()
                        self.raster_size = raster.size
                except (OSError, ValueError) as exc:
                    self.host_ok = False
                    self.raster_error = "Raster output verification failed: " + str(exc)
                    self.detail = self.raster_error
            if self.backup and fingerprint(self.backup) != self.original:
                self.state = "conflict"
                self.detail = "Backup changed; no files were removed or overwritten."
            elif self.restored_output is not None and self.backup:
                os.unlink(self.backup)
                self.state = "restored"
                self.detail = None
            elif self.host_ok and output is not None and output[2] > 0:
                # Correlated exporter success establishes output ownership.
                if self.backup:
                    os.unlink(self.backup)
                self.state = "verified"
            elif output is None and self.backup:
                # Exclusive link, unlike replace(), cannot overwrite an external file.
                os.link(self.backup, self.output)
                # Record the known original identity immediately after linking,
                # before deletion can fail. Never adopt an external file's hash.
                self.restored_output = self.original
                os.unlink(self.backup)
                self.state = "restored"
                self.detail = None
            elif self.backup and output == self.original:
                os.unlink(self.backup)
                self.state = "restored"
            elif self.backup:
                self.state = "conflict"
                self.detail = "Exporter failed with a destination present; output and backup retained for manual inspection."
            else:
                self.state = "failed"
        except OSError as exc:
            self.state = "pending_cleanup"
            self.detail = str(exc)
        return self.snapshot()


def reserve_export_files(coordinator, job, path, *, overwrite="replace"):
    if sum(bool(r.get("exportFiles", {}).get("backup")) for r in
           coordinator.snapshot().get("records", []) if r.get("exportFiles", {}).get("state")
           not in ("verified", "restored")) >= 32:
        raise OSError("32 retained export backups require finalization/manual recovery before another export")
    owner = ExportFiles(str(Path(path).absolute()), overwrite=overwrite)
    job.export_files = owner  # Attach before the first filesystem mutation.
    return owner
