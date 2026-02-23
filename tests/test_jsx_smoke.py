"""
JSX smoke tests — static analysis to catch undefined references.

Prevents the class of bug where a JSX library calls a function that
doesn't exist anywhere in its dependency chain (e.g. __mcp_toJSON).

Test classes:
  1. TestExportsAreDefined   — every export in manifest has a function def
  2. TestDepsChainResolution  — cross-library function calls resolve within
                                the transitive dependency chain
  3. TestNoDeadMcpReferences  — __mcp_* calls in JSX & Python templates all
                                reference known runtime-injected symbols
  4. TestManifestDepsExist    — every manifest dependency library actually exists
"""

import json
import re
import pytest
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "illustrator_mcp" / "resources" / "scripts"
MANIFEST_PATH = SCRIPTS_DIR / "manifest.json"
TOOLS_DIR = ROOT / "illustrator_mcp" / "tools"
TEMPLATES_PATH = ROOT / "illustrator_mcp" / "templates.py"

# ── Known runtime-injected symbols ─────────────────────────────────
# These are defined by the Python proxy at runtime (not in JSX files).
# Any __mcp_* call referencing one of these is valid.
RUNTIME_INJECTED = {
    "__mcp_check",
    "__mcp_forEachSnapshot",
    "__mcp_snapshot",
}

# Known __mcp_* globals that are NOT function calls (just object access)
RUNTIME_GLOBALS = {
    "__mcp_stash",
    "__mcp_stash_meta",
    "__mcp_replace_sandbox__",   # string literal, not a call
}


# ── Helpers ────────────────────────────────────────────────────────

def load_manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def get_jsx_source(lib_entry):
    """Read the JSX source for a manifest library entry."""
    path = SCRIPTS_DIR / lib_entry["file"]
    return path.read_text(encoding="utf-8")


def resolve_full_chain(manifest, lib_name, _seen=None):
    """Resolve the full transitive dependency chain for a library."""
    if _seen is None:
        _seen = set()
    if lib_name in _seen:
        return []
    _seen.add(lib_name)

    lib_entry = manifest["libraries"].get(lib_name)
    if not lib_entry:
        return []

    chain = []
    for dep in lib_entry.get("dependencies", []):
        chain.extend(resolve_full_chain(manifest, dep, _seen))
    chain.append(lib_name)
    return chain


def concat_chain_source(manifest, lib_name):
    """Concatenate JSX source for a library and all its transitive deps."""
    chain = resolve_full_chain(manifest, lib_name)
    parts = []
    for name in chain:
        entry = manifest["libraries"].get(name)
        if entry:
            path = SCRIPTS_DIR / entry["file"]
            if path.exists():
                parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


# ── Regex for function definitions and calls ──────────────────────
# Matches: function foo(  |  function foo (  |  var foo = function
RE_FUNC_DEF = re.compile(
    r"""
    (?:function\s+(\w+)\s*\()        # function foo(
    |                                 #   or
    (?:var\s+(\w+)\s*=\s*function\b)  # var foo = function
    """,
    re.VERBOSE,
)

# Matches: __mcp_someFunc(  — i.e. __mcp_* used as a function call
RE_MCP_CALL = re.compile(r"\b(__mcp_\w+)\s*\(")


# ══════════════════════════════════════════════════════════════════
# Test 1: Every exported symbol actually has a function definition
# ══════════════════════════════════════════════════════════════════

class TestExportsAreDefined:
    """For each library in manifest, every export must be defined in its JSX."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.manifest = load_manifest()
        self.libs = self.manifest["libraries"]

    def _get_defined_functions(self, source):
        """Extract all function names defined in source."""
        funcs = set()
        for m in RE_FUNC_DEF.finditer(source):
            name = m.group(1) or m.group(2)
            if name:
                funcs.add(name)
        return funcs

    @pytest.mark.parametrize(
        "lib_name",
        [name for name in load_manifest()["libraries"]],
        ids=lambda x: x,
    )
    def test_exports_have_definitions(self, lib_name):
        """Each exported symbol must have a `function X(` definition in its JSX file."""
        lib_entry = self.libs[lib_name]

        if lib_entry.get("deprecated"):
            pytest.skip(f"{lib_name} is deprecated (stub with no defs)")

        exports = lib_entry.get("exports", [])
        if not exports:
            pytest.skip(f"{lib_name} has no exports")

        jsx_path = SCRIPTS_DIR / lib_entry["file"]
        if not jsx_path.exists():
            pytest.fail(f"JSX file missing: {lib_entry['file']}")

        source = jsx_path.read_text(encoding="utf-8")
        defined = self._get_defined_functions(source)

        # Also accept assignments like: var FOO = { ... }  (for object exports)
        obj_defs = set(re.findall(r"\bvar\s+(\w+)\s*=\s*\{", source))
        # And enums/constants like: var FOO = ...
        var_defs = set(re.findall(r"\bvar\s+(\w+)\s*=", source))

        all_defs = defined | obj_defs | var_defs

        missing = [e for e in exports if e not in all_defs]
        assert not missing, (
            f"Library '{lib_name}' exports symbols not defined in {lib_entry['file']}: "
            f"{missing}"
        )


# ══════════════════════════════════════════════════════════════════
# Test 2: All manifest dependency references are valid
# ══════════════════════════════════════════════════════════════════

class TestManifestDepsExist:
    """Every dependency listed in the manifest must itself be a manifest lib."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.manifest = load_manifest()

    @pytest.mark.parametrize(
        "lib_name",
        [name for name in load_manifest()["libraries"]],
        ids=lambda x: x,
    )
    def test_deps_are_valid_libraries(self, lib_name):
        lib = self.manifest["libraries"][lib_name]
        for dep in lib.get("dependencies", []):
            assert dep in self.manifest["libraries"], (
                f"Library '{lib_name}' depends on '{dep}' which is not in manifest"
            )

    @pytest.mark.parametrize(
        "lib_name",
        [name for name in load_manifest()["libraries"]],
        ids=lambda x: x,
    )
    def test_jsx_file_exists(self, lib_name):
        lib = self.manifest["libraries"][lib_name]
        jsx_path = SCRIPTS_DIR / lib["file"]
        assert jsx_path.exists(), (
            f"Library '{lib_name}' references '{lib['file']}' which doesn't exist"
        )


# ══════════════════════════════════════════════════════════════════
# Test 3: No dead __mcp_* references in JSX or Python templates
# ══════════════════════════════════════════════════════════════════

class TestNoDeadMcpReferences:
    """
    Any __mcp_*() function call in JSX or Python templates must be
    a known runtime-injected symbol. This catches the exact bug where
    checkpoint.jsx called __mcp_toJSON() which never existed.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.manifest = load_manifest()

    def _scan_for_mcp_calls(self, source, exclude_comments=True):
        """Find all __mcp_*( calls in source."""
        calls = set()
        for line in source.splitlines():
            stripped = line.strip()
            # Skip single-line comments and docstrings
            if exclude_comments and (
                stripped.startswith("//")
                or stripped.startswith("*")
                or stripped.startswith("/*")
                or stripped.startswith("#")
                or stripped.startswith('"""')
                or stripped.startswith("'''")
            ):
                continue
            for m in RE_MCP_CALL.finditer(line):
                calls.add(m.group(1))
        return calls

    @pytest.mark.parametrize(
        "lib_name",
        [name for name in load_manifest()["libraries"]],
        ids=lambda x: x,
    )
    def test_jsx_mcp_calls_are_known(self, lib_name):
        """Every __mcp_*() call in a JSX file must be runtime-injected."""
        lib_entry = self.manifest["libraries"][lib_name]
        jsx_path = SCRIPTS_DIR / lib_entry["file"]
        if not jsx_path.exists():
            pytest.skip(f"{lib_entry['file']} not found")

        source = jsx_path.read_text(encoding="utf-8")
        mcp_calls = self._scan_for_mcp_calls(source)

        # Filter out known globals (used as objects, not function calls)
        unknown = mcp_calls - RUNTIME_INJECTED - RUNTIME_GLOBALS
        assert not unknown, (
            f"Library '{lib_name}' calls undefined __mcp_* functions: {unknown}. "
            f"Known runtime-injected: {RUNTIME_INJECTED}"
        )

    def test_python_templates_mcp_calls_are_known(self):
        """Python template ExtendScript must only reference known __mcp_* functions."""
        if not TEMPLATES_PATH.exists():
            pytest.skip("templates.py not found")

        source = TEMPLATES_PATH.read_text(encoding="utf-8")
        mcp_calls = self._scan_for_mcp_calls(source, exclude_comments=True)

        unknown = mcp_calls - RUNTIME_INJECTED - RUNTIME_GLOBALS
        assert not unknown, (
            f"templates.py references undefined __mcp_* functions: {unknown}. "
            f"Known runtime-injected: {RUNTIME_INJECTED}"
        )

    def test_python_tool_files_mcp_calls_are_known(self):
        """Python tool files embedding ExtendScript must only use known __mcp_* calls."""
        if not TOOLS_DIR.exists():
            pytest.skip("tools directory not found")

        all_unknown = {}
        for py_file in TOOLS_DIR.glob("*.py"):
            source = py_file.read_text(encoding="utf-8")
            mcp_calls = self._scan_for_mcp_calls(source, exclude_comments=True)
            unknown = mcp_calls - RUNTIME_INJECTED - RUNTIME_GLOBALS
            if unknown:
                all_unknown[py_file.name] = unknown

        assert not all_unknown, (
            f"Python tool files reference undefined __mcp_* functions: {all_unknown}"
        )


# ══════════════════════════════════════════════════════════════════
# Test 4: Cross-library exports consumed by dependents are defined
# ══════════════════════════════════════════════════════════════════

class TestCrossLibraryExportConsumption:
    """
    For each library, if it calls a function exported by a dependency,
    that function must actually be defined in the dependency's JSX.

    This is the deeper version of TestExportsAreDefined — it checks
    that the *consumer* side can actually resolve the call.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        self.manifest = load_manifest()
        self.libs = self.manifest["libraries"]

    def _collect_all_exports_in_chain(self, lib_name):
        """Collect all exported symbols from the full dep chain."""
        chain = resolve_full_chain(self.manifest, lib_name)
        exports = set()
        for name in chain:
            entry = self.libs.get(name)
            if entry:
                exports.update(entry.get("exports", []))
        return exports

    @pytest.mark.parametrize(
        "lib_name",
        [name for name in load_manifest()["libraries"]],
        ids=lambda x: x,
    )
    def test_consumed_exports_exist_in_dep_chain(self, lib_name):
        """
        Cross-reference: for each export consumed by this library
        (by checking if the function name appears as a call in the source),
        verify it's actually defined in a dependency's JSX.
        """
        lib_entry = self.libs[lib_name]
        jsx_path = SCRIPTS_DIR / lib_entry["file"]
        if not jsx_path.exists():
            pytest.skip(f"{lib_entry['file']} not found")

        source = jsx_path.read_text(encoding="utf-8")

        # Collect all exports from dependencies (not self)
        dep_exports = set()
        for dep in lib_entry.get("dependencies", []):
            chain = resolve_full_chain(self.manifest, dep)
            for name in chain:
                entry = self.libs.get(name)
                if entry:
                    dep_exports.update(entry.get("exports", []))

        if not dep_exports:
            pytest.skip(f"{lib_name} has no dependencies with exports")

        # For each dep export, if it's called in this library's source,
        # verify it's actually defined in the dep chain's concatenated source
        called_dep_exports = [
            exp for exp in dep_exports
            if re.search(rf"\b{re.escape(exp)}\b", source)
        ]

        if not called_dep_exports:
            pytest.skip(f"{lib_name} doesn't reference any dep exports")

        # Concat all dep source
        dep_chain = set()
        for dep in lib_entry.get("dependencies", []):
            for name in resolve_full_chain(self.manifest, dep):
                dep_chain.add(name)

        dep_source = ""
        for name in dep_chain:
            entry = self.libs.get(name)
            if entry:
                p = SCRIPTS_DIR / entry["file"]
                if p.exists():
                    dep_source += "\n" + p.read_text(encoding="utf-8")

        # Check each called export is actually defined
        missing = []
        for exp in called_dep_exports:
            # Check for function definition or var assignment
            if not (
                re.search(rf"\bfunction\s+{re.escape(exp)}\b", dep_source)
                or re.search(rf"\bvar\s+{re.escape(exp)}\s*=", dep_source)
            ):
                missing.append(exp)

        assert not missing, (
            f"Library '{lib_name}' calls exports from deps that aren't actually "
            f"defined in the dep chain: {missing}"
        )
