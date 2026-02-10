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
from typing import Any, Dict, List, Optional

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
        self._file_cache: Dict[Path, str] = {}
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
                self._manifest_cache = loaded
                self._manifest_stamp = current_stamp
                lib_keys = list(loaded.get("libraries", {}).keys())
                logger.info(f"Manifest loaded from {manifest_path} (mtime_ns={current_stamp[0]}, size={current_stamp[1]}): {len(lib_keys)} libs: {lib_keys}")
                if self._manifest_stamp is not None:
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
        """Read library file with mtime-based cache invalidation."""
        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            raise ValueError(f"Library file not found: {path.name}")

        with self._file_lock:
            if path in self._file_cache:
                cached_content, cached_mtime = self._file_cache[path]
                if cached_mtime == current_mtime:
                    return cached_content

        content = path.read_text(encoding="utf-8")

        with self._file_lock:
            self._file_cache[path] = (content, current_mtime)

        return content

    def resolve(self, includes: List[str]) -> str:
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
            
            # Resolve dependencies first (recursive)
            for dep in lib.get("dependencies", []):
                resolve_one(dep)
            
            # Check for symbol collisions
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
            
            seen.add(lib_name)
        
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

    def get_resolution_metadata(self, includes: List[str]) -> Dict[str, Any]:
        """Get metadata for diagnostics including canonicalized includes and prelude hash.

        Args:
            includes: List of library names to resolve.

        Returns:
            Dict with:
            - includes_canonical: Sorted list of library names
            - prelude_hash: MD5 hash prefix (8 chars) of resolved code
        """
        if not includes:
            return {"includes_canonical": [], "prelude_hash": None}

        canonical = sorted(includes)
        code = self.resolve(includes)
        prelude_hash = hashlib.md5(code.encode('utf-8')).hexdigest()[:8]

        return {
            "includes_canonical": canonical,
            "prelude_hash": prelude_hash
        }


# Default resources directory
_RESOURCES_DIR = Path(__file__).parent / "resources" / "scripts"

# Global resolver instance (lazy initialization)
_resolver: Optional[LibraryResolver] = None
_resolver_lock = threading.Lock()


def get_resolver() -> LibraryResolver:
    """Get the global library resolver instance."""
    global _resolver
    if _resolver is None:
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


def inject_libraries(script: str, includes: List[str]) -> str:
    """Prepend standard library code to a script using manifest-driven resolution.
    
    Features (v2.3):
    - Automatic transitive dependency resolution
    - Deduplication (each library loaded exactly once)
    - Symbol collision detection
    - Library content caching
    
    Args:
        script: The user's ExtendScript code.
        includes: List of library names (e.g., ["geometry", "selection", "layout"]).
    
    Returns:
        Combined script with libraries prepended.
    
    Raises:
        ValueError: If a requested library file is not found or symbol collision detected.
    """
    if not includes:
        return script
    
    library_code = get_resolver().resolve(includes)
    return library_code + "\n\n// === User Script ===\n" + script
