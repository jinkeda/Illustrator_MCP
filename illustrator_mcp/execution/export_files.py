"""Process-local export ownership. Unknown exporters never trigger file cleanup."""
from dataclasses import dataclass, asdict
import hashlib
import errno
import os
import shutil
from pathlib import Path
import uuid


def _unsupported_link(exc):
    """Only link-operation capability errors authorize exclusive copying."""
    winerror = getattr(exc, "winerror", None)
    if winerror is not None:
        return winerror in (1, 50)
    return os.name != "nt" and exc.errno in {
        getattr(errno, name, None) for name in ("ENOSYS", "ENOTSUP", "EOPNOTSUPP")
    } - {None}


def _sync_directory(path):
    """Windows directory persistence is explicitly unqualified."""
    if os.name == "nt":
        return "unsupported_windows"
    fd = os.open(str(Path(path).parent), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return "synced"


def _same_content(left, right):
    return left is not None and right is not None and left[2] == right[2] and left[4] == right[4]


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
    backup_fingerprint: tuple | None = None
    preparation_complete: bool = False
    original_removed: bool = False
    backup_removed: bool = False
    restoration_incomplete: bool = False
    backup_method: str | None = None
    restoration_method: str | None = None
    copy_phase: str | None = None
    copy_identity: tuple | None = None
    directory_sync: str = "not_attempted"
    cleanup_outcome: str | None = None
    backup_link_error: dict | None = None
    restoration_link_error: dict | None = None

    def snapshot(self):
        return asdict(self)

    @property
    def retained(self):
        return self.backup is not None and self.state not in ("verified", "restored")

    def _sync(self, path):
        self.directory_sync = "pending"
        self.directory_sync = _sync_directory(path)

    def _create_recovery_file(self, source, destination, expected, phase):
        """Create once, synchronize copies, then verify both names independently.

        An incomplete owned copy remains for inspection. Retrying finalization
        must never adopt it as verified or bypass a failed flush/close/sync.
        """
        try:
            os.link(source, destination)
        except OSError as exc:
            setattr(self, phase + "_link_error", {
                "errno": exc.errno, "winerror": getattr(exc, "winerror", None)})
            if not _unsupported_link(exc):
                raise
            setattr(self, phase + "_method", "copy")
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            self.copy_phase = phase + ":created"
            try:
                st = os.fstat(fd)
                self.copy_identity = (st.st_dev, st.st_ino)
                stream = os.fdopen(fd, "wb")
            except BaseException:
                os.close(fd)
                raise
            with stream:
                with open(source, "rb") as incoming:
                    shutil.copyfileobj(incoming, stream)
                self.copy_phase = phase + ":written"
                stream.flush()
                self.copy_phase = phase + ":flushed"
                os.fsync(stream.fileno())
                self.copy_phase = phase + ":file_synced"
            self.copy_phase = phase + ":closed"
        else:
            setattr(self, phase + "_method", "link")
        result = fingerprint(destination)
        if (not _same_content(result, expected) or
                (getattr(self, phase + "_method") == "link" and result != expected) or
                (getattr(self, phase + "_method") == "copy" and result[:2] != self.copy_identity)):
            raise OSError("Recovery file identity/content verification failed; both paths retained")
        self._sync(destination)
        if fingerprint(source) != expected or fingerprint(destination) != result:
            raise OSError("Recovery source/destination changed; both paths retained")
        self.copy_phase = phase + ":verified"
        return result

    def _remove_backup(self, outcome):
        if not self.backup_removed:
            if outcome == "verified" and not self.completion_captured:
                self.completed_output = fingerprint(self.output)
                self.completion_captured = True
            os.unlink(self.backup)
            self.backup_removed = True
            self.cleanup_outcome = outcome
        self._sync(self.backup)
        self.state = outcome
        self.detail = None

    def prepare(self):
        if self.preparation_complete:
            return
        if self.backup is not None:
            raise OSError("Incomplete preparation already owns a backup; inspect retained files before retrying")
        if self.overwrite not in ("replace", "fail", "version"):
            raise ValueError("Unknown overwrite policy: " + self.overwrite)
        if Path(self.output).suffix.lower() == ".svg":
            self.directory_entries = tuple(os.listdir(Path(self.output).parent))
            if len(self.directory_entries) > 4096:
                raise OSError("Use a smaller export directory for bounded SVG asset verification")
        self.original = fingerprint(self.output)
        if self.original is None:
            self.preparation_complete = True
            return
        if self.overwrite != "replace":
            self.state = "conflict"
            self.detail = "Export destination became occupied; overwrite='" + self.overwrite + "' forbids replacement."
            raise FileExistsError(self.detail)
        self.backup = self.output + ".mcp-backup-" + uuid.uuid4().hex
        try:
            self.backup_fingerprint = self._create_recovery_file(
                self.output, self.backup, self.original, "backup")
            os.unlink(self.output)
            self.original_removed = True
            self._sync(self.output)
            self.preparation_complete = True
        except OSError as exc:
            if self.backup_method is None or (self.copy_phase is None and self.backup_method == "copy"):
                self.backup = None
            self.state = "pending_cleanup"
            self.detail = "Preparation incomplete; export not dispatched: " + str(exc)
            raise

    def finalize(self):
        if self.state in ("verified", "restored"):
            return self.snapshot()
        if not self.host_finished:
            self.state = "pending_completion"
            return self.snapshot()
        if not self.preparation_complete or self.restoration_incomplete:
            self.state = "pending_cleanup"
            self.detail = self.detail or "Incomplete recovery creation retained for manual inspection; no files removed."
            return self.snapshot()
        try:
            output = fingerprint(self.output)
            expected_output = self.restored_output if self.restored_output is not None else self.completed_output
            if (self.completion_captured or self.restored_output is not None) and output != expected_output:
                self.state = "conflict"
                phase = "restoration" if self.restored_output is not None else "correlated completion"
                self.detail = "Destination changed after " + phase + "; output and backup retained."
                return self.snapshot()
            if self.backup_removed:
                self._remove_backup(self.cleanup_outcome)
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
            if self.backup and fingerprint(self.backup) != self.backup_fingerprint:
                self.state = "conflict"
                self.detail = "Backup changed; no files were removed or overwritten."
            elif self.restored_output is not None and self.backup:
                self._remove_backup("restored")
            elif self.host_ok and output is not None and output[2] > 0:
                # Correlated exporter success establishes output ownership.
                if self.backup:
                    self._remove_backup("verified")
                else:
                    self.state = "verified"
            elif output is None and self.backup:
                self.restoration_incomplete = True
                self.restored_output = self._create_recovery_file(
                    self.backup, self.output, self.backup_fingerprint, "restoration")
                self.restoration_incomplete = False
                self._remove_backup("restored")
            elif self.backup and output == self.original:
                self.restored_output = output
                self._remove_backup("restored")
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
