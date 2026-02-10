#!/usr/bin/env python3
"""
Manifest Dependency Validator

Scans all .jsx library files referenced in manifest.json,
checks which exported symbols from other libraries they use,
and reports any undeclared dependencies.

Usage:
    python scripts/validate_manifest_deps.py

Exit code 0 = all deps declared, 1 = missing deps found.
"""

import json
import os
import re
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "illustrator_mcp" / "resources" / "scripts"
MANIFEST_PATH = SCRIPTS_DIR / "manifest.json"


def load_manifest():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_export_map(manifest):
    """Map each exported symbol to its source library."""
    export_to_lib = {}
    for lib_name, lib_info in manifest["libraries"].items():
        for exp in lib_info.get("exports", []):
            export_to_lib[exp] = lib_name
    return export_to_lib


def resolve_transitive_deps(manifest, lib_name):
    """Resolve all transitive dependencies for a library."""
    lib_info = manifest["libraries"].get(lib_name, {})
    declared = set(lib_info.get("dependencies", []))
    all_deps = set()
    queue = list(declared)
    while queue:
        dep = queue.pop(0)
        if dep not in all_deps:
            all_deps.add(dep)
            sub_deps = manifest["libraries"].get(dep, {}).get("dependencies", [])
            queue.extend(sub_deps)
    return declared, all_deps


def scan_file_for_symbols(filepath, export_to_lib, lib_name, all_deps):
    """Find exported symbols used in a file that aren't from declared deps."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
        lines = content.split("\n")

    missing = {}
    for symbol, source_lib in export_to_lib.items():
        if source_lib == lib_name:
            continue  # Skip own exports
        if source_lib in all_deps:
            continue  # Already a transitive dependency

        # Word-boundary match, skip comments and strings (basic heuristic)
        pattern = re.compile(r"\b" + re.escape(symbol) + r"\b")
        match_lines = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Skip single-line comments and @requires annotations
            if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/**"):
                continue
            if pattern.search(line):
                match_lines.append(i)

        if match_lines:
            if source_lib not in missing:
                missing[source_lib] = []
            missing[source_lib].append((symbol, match_lines))

    return missing


def main():
    manifest = load_manifest()
    export_to_lib = build_export_map(manifest)

    total_issues = 0
    results = {}

    for lib_name, lib_info in sorted(manifest["libraries"].items()):
        filepath = SCRIPTS_DIR / lib_info["file"]
        if not filepath.exists():
            print(f"WARNING: {lib_info['file']} referenced in manifest but not found on disk!")
            total_issues += 1
            continue

        declared_deps, all_deps = resolve_transitive_deps(manifest, lib_name)
        missing = scan_file_for_symbols(filepath, export_to_lib, lib_name, all_deps)

        if missing:
            results[lib_name] = {
                "file": lib_info["file"],
                "declared_deps": sorted(declared_deps),
                "missing": {
                    src_lib: [(sym, lines) for sym, lines in syms]
                    for src_lib, syms in sorted(missing.items())
                },
            }
            total_issues += len(missing)

    # Print report
    if not results:
        print("✅ All manifest dependencies are correctly declared.")
        return 0

    print(f"❌ Found {total_issues} undeclared dependencies:\n")
    for lib_name, info in results.items():
        print(f"=== {info['file']} (deps: {info['declared_deps']}) ===")
        for src_lib, syms in info["missing"].items():
            for sym, lines in syms:
                line_str = ", ".join(str(l) for l in lines[:5])
                if len(lines) > 5:
                    line_str += f", ... ({len(lines)} total)"
                print(f"  MISSING: {src_lib}.{sym} used at L{line_str}")
        print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
