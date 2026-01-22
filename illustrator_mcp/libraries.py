"""
Library resolution for ExtendScript injection.

This module handles resolution of ExtendScript libraries with:
- Transitive dependency resolution
- Deduplication
- Symbol collision detection
- Thread-safe caching
"""

import json
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional

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
        self._manifest_lock = threading.Lock()
        self._file_cache: Dict[Path, str] = {}
        self._file_lock = threading.Lock()

    def _load_manifest(self) -> dict:
        """Load manifest lazily with thread safety."""
        if self._manifest_cache is not None:
            return self._manifest_cache
            
        with self._manifest_lock:
            if self._manifest_cache is not None:
                return self._manifest_cache
                
            manifest_path = self.resources_dir / "manifest.json"
            if manifest_path.exists():
                try:
                    with open(manifest_path, encoding="utf-8") as f:
                        self._manifest_cache = json.load(f)
                except Exception as e:
                    logger.error(f"Failed to load manifest: {e}")
                    self._manifest_cache = {"libraries": {}}
            else:
                self._manifest_cache = {"libraries": {}}
                
            return self._manifest_cache

    def _read_library_file(self, path: Path) -> str:
        """Read library file with caching."""
        with self._file_lock:
            if path in self._file_cache:
                return self._file_cache[path]
        
        if not path.exists():
            raise ValueError(f"Library file not found: {path.name}")
            
        content = path.read_text(encoding="utf-8")
        
        with self._file_lock:
            self._file_cache[path] = content
            
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
            if lib_name in seen:
                return
            
            if lib_name not in manifest["libraries"]:
                raise ValueError(f"Unknown library: {lib_name}")
            
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
