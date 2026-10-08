"""Shared transactional CEP installer. Called by the platform launchers.

Backups and staging live outside Adobe's discovery roots. No recursive deletion
is performed: failed candidates are retained for diagnosis, and upgrades roll back.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'cep-extension'))
from validate_panel import validate_panel

EXTENSION_ID = 'com.illustrator.mcp.panel'


def exists(path):
    return path.exists() or path.is_symlink()


def configure_debug():
    for version in (10, 11, 12):
        if sys.platform == 'win32':
            command = ['reg', 'add', f'HKCU\\Software\\Adobe\\CSXS.{version}',
                       '/v', 'PlayerDebugMode', '/t', 'REG_SZ', '/d', '1', '/f']
        else:
            command = ['defaults', 'write', f'com.adobe.CSXS.{version}', 'PlayerDebugMode', '1']
        subprocess.run(command, check=True)


def stage_panel(source, candidate):
    # A symlink would expose local debugger configuration, including files
    # added after installation. Stage an independent, filtered snapshot.
    shutil.copytree(source, candidate,
                    ignore=shutil.ignore_patterns('node_modules', '__pycache__', '.debug', 'connection.json'))


def install(source, target, backup_root, *, validate=validate_panel, configure=configure_debug,
            stage=stage_panel):
    source = source.resolve()
    target = target.absolute()  # Do not resolve a managed symlink to its source.
    backup_root = backup_root.resolve()
    if backup_root.is_relative_to(target.parent.resolve()):
        raise ValueError('Backup directory must be outside CEP extension discovery')
    validate(source)
    backup_root.mkdir(parents=True, exist_ok=True)
    transaction = Path(tempfile.mkdtemp(prefix='upgrade-', dir=backup_root))
    candidate = transaction / 'candidate'
    previous = transaction / 'previous'
    stage(source, candidate)
    # Preserve the active panel's preferences, including a legacy installation
    # symlink's linked configuration. Fresh source settings remain excluded.
    # Preserve exact bytes (even invalid JSON) before moving the active
    # installation; a read/copy failure aborts the upgrade safely.
    installed_config = target / 'connection.json'
    if exists(installed_config):
        if installed_config.is_symlink() or not installed_config.is_file():
            raise ValueError('Installed connection.json must be a regular file')
        shutil.copy2(installed_config, candidate / 'connection.json')
    validate(candidate)
    configure()  # Do this before taking the old panel out of service.
    target.parent.mkdir(parents=True, exist_ok=True)
    legacy = target.with_name(target.name + '.previous')
    if exists(legacy):
        legacy.rename(transaction / 'legacy-previous')
        print(f'Moved legacy backup outside CEP discovery: {transaction / "legacy-previous"}')
    moved_previous = False
    activated = False
    try:
        if exists(target):
            target.rename(previous)
            moved_previous = True
        candidate.rename(target)
        activated = True
        validate(target)
    except BaseException:
        try:
            if activated and exists(target):
                target.rename(transaction / 'failed-candidate')
            if moved_previous:
                previous.rename(target)
                print(f'Restored previous installation: {target}', file=sys.stderr)
        except OSError as recovery_error:
            print(f'Automatic restoration failed: {recovery_error}. Restore {previous} to {target}.', file=sys.stderr)
        raise
    print(f'Installation Complete! Backup/staging directory: {transaction}')
    print('Open Illustrator > Window > Extensions > MCP Control, then Connect.')
    return transaction


def main():
    if sys.platform == 'win32':
        appdata = Path(os.environ['APPDATA'])
        target = appdata / 'Adobe/CEP/extensions' / EXTENSION_ID
        backups = appdata / 'Illustrator MCP/cep-backups'
    elif sys.platform == 'darwin':
        support = Path.home() / 'Library/Application Support'
        target = support / 'Adobe/CEP/extensions' / EXTENSION_ID
        backups = support / 'Illustrator MCP/cep-backups'
    else:
        raise RuntimeError('The CEP installer supports Windows and macOS only')
    install(ROOT / 'cep-extension', target, backups)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'ERROR: Installation failed: {error}', file=sys.stderr)
        sys.exit(1)
