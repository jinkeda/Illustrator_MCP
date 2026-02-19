"""
Library resolution for ExtendScript injection.

This module handles resolution of ExtendScript libraries with:
- Transitive dependency resolution
- Deduplication
- Symbol collision detection
- Thread-safe caching
"""

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class LibraryResolver:
    """
    Handles resolution of ExtendScript libraries with dependency management.
    
    Features:
    - Transitive dependency resolution
    - Deduplication
    - Symbol collision detection
    - Thread-safe caching
    """
    
    def __init__(self, resources_dir: Path):
        self.resources_dir = resources_dir
        self._manifest_cache: Optional[dict] = None
        self._manifest_stamp: Optional[tuple] = None  # (mtime_ns, size)
        self._manifest_lock = threading.Lock()
        self._file_cache: Dict[Path, Tuple[str, float]] = {}
        self._file_lock = threading.Lock()

    def _load_manifest(self) -> dict:
        """Load manifest with mtime+size invalidation, thread-safe.
        
        Uses (st_mtime_ns, st_size) tuple to detect changes, including
        rapid edits within the same second. On stat failure, keeps
        last-known-good cache and logs a warning.
        """
        manifest_path = self.resources_dir / "manifest.json"
        
        with self._manifest_lock:
            # Get current file stamp
            try:
                st = manifest_path.stat()
                current_stamp = (
                    getattr(st, 'st_mtime_ns', int(st.st_mtime * 1e9)),
                    st.st_size
                )
            except OSError:
                if self._manifest_cache is not None:
                    logger.warning("manifest.json stat failed; keeping last-known-good cache")
                    return self._manifest_cache
                logger.error("manifest.json not found and no cached version available")
                return {"libraries": {}}
            
            # Return cached if stamp unchanged
            if self._manifest_cache is not None and self._manifest_stamp == current_stamp:
                logger.debug(f"Manifest cache hit (stamp={current_stamp}, path={manifest_path})")
                return self._manifest_cache
            
            # Load fresh
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    loaded = json.load(f)
                old_stamp = self._manifest_stamp
                self._manifest_cache = loaded
                self._manifest_stamp = current_stamp
                lib_keys = list(loaded.get("libraries", {}).keys())
                logger.info(f"Manifest loaded from {manifest_path} (mtime_ns={current_stamp[0]}, size={current_stamp[1]}): {len(lib_keys)} libs: {lib_keys}")
                if old_stamp is not None:
                    logger.debug("Manifest reloaded (stamp changed)")
            except Exception as e:
                if self._manifest_cache is not None:
                    logger.warning(f"Failed to reload manifest: {e}; keeping last-known-good")
                    return self._manifest_cache
                logger.error(f"Failed to load manifest: {e}")
                self._manifest_cache = {"libraries": {}}
                self._manifest_stamp = current_stamp
                
            return self._manifest_cache

    def _read_library_file(self, path: Path) -> str:
        """Read library file with mtime-based cache invalidation.

        Uses double-stat (before + after read) to detect concurrent
        modifications and ensure stored mtime matches stored content.
        """
        try:
            mtime_before = path.stat().st_mtime
        except OSError:
            raise ValueError(f"Library file not found: {path.name}")

        with self._file_lock:
            cached = self._file_cache.get(path)
            if cached and cached[1] == mtime_before:
                return cached[0]

        content = path.read_text(encoding="utf-8")
        try:
            mtime_after = path.stat().st_mtime
        except OSError:
            raise ValueError(f"Library file disappeared: {path.name}")

        if mtime_after != mtime_before:
            # File changed during read — re-read once
            content = path.read_text(encoding="utf-8")
            mtime_after = path.stat().st_mtime

        with self._file_lock:
            self._file_cache[path] = (content, mtime_after)
        return content

    def resolve(self, includes: List[str], *, skip_collision_check: bool = False) -> str:
        """
        Resolve libraries with transitive dependencies.
        
        Args:
            includes: List of library names to resolve.
            
        Returns:
            Concatenated script content.
            
        Raises:
            ValueError: If library not found or symbol collision detected.
        """
        if not includes:
            return ""

        manifest = self._load_manifest()
        
        if not manifest or not manifest.get("libraries"):
            return self._simple_resolve(includes)
        
        resolved: List[str] = []
        seen: set = set()
        all_exports: Dict[str, str] = {}  # symbol -> library name
        
        def resolve_one(lib_name: str) -> None:
            nonlocal manifest
            if lib_name in seen:
                return
            
            if lib_name not in manifest["libraries"]:
                # Auto-retry: force reload once before failing (stale cache guard)
                logger.warning(f"Library '{lib_name}' not found, forcing manifest reload")
                self._manifest_cache = None
                manifest = self._load_manifest()
                if lib_name not in manifest["libraries"]:
                    available = list(manifest["libraries"].keys())
                    raise ValueError(f"Unknown library: {lib_name}. Available: {available}. Manifest: {self.resources_dir / 'manifest.json'}")
            
            lib = manifest["libraries"][lib_name]
            
            # Warn on deprecated libraries
            if lib.get("deprecated"):
                desc = lib.get("description", "")
                logger.warning(
                    f"Library '{lib_name}' is deprecated. {desc}"
                )
            
            # Mark seen BEFORE recursing to break mutual dependencies
            seen.add(lib_name)
            
            # Resolve dependencies first (recursive)
            for dep in lib.get("dependencies", []):
                resolve_one(dep)
            
            # Check for symbol collisions (unless explicitly skipped)
            if not skip_collision_check:
                for symbol in lib.get("exports", []):
                    if symbol in all_exports:
                        raise ValueError(
                            f"Symbol collision: '{symbol}' defined in both "
                            f"'{all_exports[symbol]}' and '{lib_name}'"
                        )
                    all_exports[symbol] = lib_name
            
            # Load content
            lib_path = self.resources_dir / lib["file"]
            try:
                content = self._read_library_file(lib_path)
                resolved.append(content)
            except ValueError as e:
                raise ValueError(f"Library file not found: {lib['file']}") from e
        
        for lib_name in includes:
            resolve_one(lib_name)
        
        return "\n\n".join(resolved)

    def _simple_resolve(self, includes: List[str]) -> str:
        """Fallback: simple file concatenation without manifest."""
        library_code = []
        
        for lib_name in includes:
            lib_path = self.resources_dir / f"{lib_name}.jsx"
            try:
                content = self._read_library_file(lib_path)
                library_code.append(content)
            except ValueError:
                raise ValueError(
                    f"Library not found: {lib_name}.jsx (looked in {self.resources_dir})"
                )
        
        return "\n".join(library_code)

    def clear_cache(self) -> None:
        """Clear all caches. Useful for testing."""
        with self._manifest_lock:
            self._manifest_cache = None
        with self._file_lock:
            self._file_cache.clear()

    def build_sentinel_script(self, preload_version: str) -> str:
        """Build JS that verifies preloaded libraries match expected version.

        Returns ExtendScript that checks $.global.__mcp.version against
        preload_version. On mismatch, throws an error containing the
        MCP_LIBS_NOT_READY sentinel which response_classification.py catches.
        """
        return (
            'if (typeof $.global.__mcp === "undefined"'
            f' || $.global.__mcp.version !== "{preload_version}") {{\n'
            f'  throw new Error("MCP_LIBS_NOT_READY:{preload_version}");\n'
            '}\n'
        )

    def get_all_library_names(self) -> List[str]:
        """Return all library names from the manifest.

        Used by build_preload_bundle to resolve the full library set.
        """
        manifest = self._load_manifest()
        if not manifest or not manifest.get("libraries"):
            return []
        return list(manifest["libraries"].keys())

    def build_preload_bundle(self) -> Tuple[str, str]:
        """Build a preload script that persists all libraries in global scope.

        Resolves ALL libraries from the manifest in dependency order,
        concatenates them, and appends a version marker to
        ``$.global.__mcp.version``. The resulting script is eval'd once;
        subsequent calls use sentinel-only injection.

        Returns:
            Tuple of (preload_script, version_hash) where version_hash
            is an 8-char MD5 prefix of the concatenated library code.
        """
        all_libs = self.get_all_library_names()
        if not all_libs:
            return ("", "")

        library_code = self.resolve(all_libs, skip_collision_check=True)
        version_hash = hashlib.md5(library_code.encode("utf-8")).hexdigest()[:8]

        # Append version marker so sentinel checks can verify preload state
        preload_script = (
            library_code + "\n\n"
            "// === MCP Preload Version Marker ===\n"
            "$.global.__mcp = $.global.__mcp || {};\n"
            f'$.global.__mcp.version = "{version_hash}";\n'
        )

        return (preload_script, version_hash)


    def _resolve_dependency_order(self, includes: List[str]) -> List[str]:
        """Resolve libraries with transitive dependencies, returning load order.

        Returns the ordered list of library names (deps first, then requested).
        This is the same resolution logic as resolve() but returns names, not code.
        """
        manifest = self._load_manifest()
        if not manifest or not manifest.get("libraries"):
            return list(includes)

        resolved: List[str] = []
        seen: set = set()

        def walk(lib_name: str) -> None:
            nonlocal manifest
            if lib_name in seen:
                return
            if lib_name not in manifest["libraries"]:
                self._manifest_cache = None
                manifest = self._load_manifest()
                if lib_name not in manifest["libraries"]:
                    return  # skip unknown, resolve() will raise
            lib = manifest["libraries"][lib_name]
            # Mark seen BEFORE recursing to break mutual dependencies
            seen.add(lib_name)
            for dep in lib.get("dependencies", []):
                walk(dep)
            resolved.append(lib_name)

        for lib_name in includes:
            walk(lib_name)

        return resolved

    def get_resolution_metadata(self, includes: List[str]) -> Dict[str, Any]:
        """Get metadata for diagnostics including resolution details and versions.

        Args:
            includes: List of requested library names.

        Returns:
            Dict with:
            - includes_requested: Original requested libraries (sorted)
            - includes_resolved: All libraries actually loaded (incl. transitive deps, load order)
            - includes_canonical: Sorted list (backward compat alias for includes_requested)
            - prelude_hash: MD5 hash prefix (8 chars) of resolved code
            - prelude_length: Length of resolved code in bytes
            - library_versions: Dict of library name → version string
            - manifest_version: Manifest version string
        """
        if not includes:
            return {
                "includes_requested": [],
                "includes_resolved": [],
                "includes_canonical": [],
                "prelude_hash": None,
                "prelude_length": 0,
                "library_versions": {},
                "manifest_version": None,
            }

        requested = sorted(includes)
        resolved_order = self._resolve_dependency_order(includes)
        code = self.resolve(includes)
        code_bytes = code.encode('utf-8')
        prelude_hash = hashlib.md5(code_bytes).hexdigest()[:8]

        # Extract versions from manifest
        manifest = self._load_manifest()
        libs = manifest.get("libraries", {})
        library_versions = {
            name: libs[name].get("version", "?")
            for name in resolved_order
            if name in libs
        }

        return {
            "includes_requested": requested,
            "includes_resolved": resolved_order,
            "includes_canonical": requested,  # backward compat
            "prelude_hash": prelude_hash,
            "prelude_length": len(code_bytes),
            "library_versions": library_versions,
            "manifest_version": manifest.get("version"),
        }


# Default resources directory
_RESOURCES_DIR = Path(__file__).parent / "resources" / "scripts"

# Global resolver instance (lazy initialization)
_resolver: Optional[LibraryResolver] = None
_resolver_lock = threading.Lock()


def get_resolver() -> LibraryResolver:
    """Get the global library resolver instance.

    B6: Always acquires lock (no double-checked locking) so this is safe
    under free-threaded Python (PEP 703 / --disable-gil).
    """
    global _resolver
    with _resolver_lock:
        if _resolver is None:
            _resolver = LibraryResolver(_RESOURCES_DIR)
        return _resolver


def get_injection_metadata(includes: List[str]) -> Dict[str, Any]:
    """Get metadata for library injection diagnostics.

    Args:
        includes: List of library names.

    Returns:
        Dict with includes_canonical (sorted) and prelude_hash.
    """
    return get_resolver().get_resolution_metadata(includes)


# Sentinel marker to detect already-injected scripts
INJECTION_SENTINEL = "/* @ILLUSTRATOR_MCP_INJECTED */"


def inject_libraries(
    script: str,
    includes: List[str],
    preload_version: Optional[str] = None,
) -> str:
    """Prepend standard library code to a script using manifest-driven resolution.
    
    Features (v2.4):
    - Automatic transitive dependency resolution
    - Deduplication (each library loaded exactly once)
    - Symbol collision detection
    - Library content caching
    - Sentinel marker for double-injection prevention
    - Preload-aware: sentinel-only injection when libraries are preloaded (C1)
    
    Args:
        script: The user's ExtendScript code.
        includes: List of library names (e.g., ["geometry", "selection", "layout"]).
        preload_version: If set, libraries are preloaded; inject sentinel check only.
    
    Returns:
        Combined script with libraries prepended and sentinel marker.
    
    Raises:
        ValueError: If a requested library file is not found or symbol collision detected.
    """
    if not includes:
        return script
    
    resolver = get_resolver()
    
    if preload_version:
        # C1: Sentinel-only injection — libraries already in $.global.__mcp
        sentinel_script = resolver.build_sentinel_script(preload_version)
        return (
            INJECTION_SENTINEL + "\n"
            + sentinel_script + "\n\n"
            + "// === MCP user script ===\n"
            + script
        )
    
    # Full injection — resolve and prepend all library code
    library_code = resolver.resolve(includes)
    return (
        INJECTION_SENTINEL + "\n"
        + library_code + "\n\n"
        + "// === MCP user script ===\n"
        + script
    )
