"""
Script templates for common ExtendScript patterns.

Provides reusable wrappers for error handling, document checks, and JSON response formatting.

Envelope contract (all paths):
    Success: { ok: true,  data: <expr>,  operation: "<name>" }
    Error:   { ok: false, error: { message: "…", line: <n|null>, operation: "<name>" } }

Fragments (e.g. create_selection_check) use ``__op`` — a local variable
injected by wrap_script() — so they stay dumb and composable.
"""

import json
from typing import Optional


def wrap_script(
    script: str,
    operation_name: str = "operation",
    *,
    require_document: bool = True,
    prelude: str = "",
    success_js: str = "",
) -> str:
    """Canonical wrapper for ExtendScript code.

    Wraps *script* inside a try/catch IIFE with a **standardized envelope**:

    Success:  ``{ ok: true,  data: …, operation: "…" }``
    Error:    ``{ ok: false, error: { message: "…", line: …, operation: "…" } }``

    The Python-side classifier can key off ``ok`` reliably without heuristics.

    A local ``var __op`` is injected so that any prelude fragment (e.g.
    ``create_selection_check()``) can emit the same envelope shape without
    needing the operation name passed in separately.

    Args:
        script: The ExtendScript code to execute.
        operation_name: Name surfaced in the JSON response.
        require_document: If True, bail early when no document is open.
        prelude: Extra guard/helper code injected **after** the doc-check
                 but **before** the user script (e.g. selection validation).
        success_js: JS expression for the ``data`` field when the user
                    script does not ``return`` on its own.

                    * ``""`` (default) — uses ``data`` if the user script
                      defined it, otherwise ``"success"``.
                    * Any other string — used verbatim as the expression.

    Returns:
        Complete IIFE string ready for ``execute_script_with_context()``.
    """
    op_json = json.dumps(operation_name)

    doc_guard = ""
    if require_document:
        doc_guard = """
        if (!app.documents.length) {
            return JSON.stringify({
                ok: false,
                error: { message: "NO_DOCUMENT: No document is open. Please create or open a document first.",
                         line: null, operation: __op }
            });
        }
        var doc = app.activeDocument;
"""

    if success_js:
        data_expr = success_js
    else:
        data_expr = '(typeof data !== "undefined") ? data : "success"'

    return f"""
(function() {{
    var __op = {op_json};
    try {{{doc_guard}
        {prelude}
        // User script
        {script}

        return JSON.stringify({{ ok: true, data: {data_expr}, operation: __op }});
    }} catch (e) {{
        return JSON.stringify({{
            ok: false,
            error: {{ message: e.toString(), line: e.line || null, operation: __op }}
        }});
    }}
}})();
"""


# ── Backward-compat aliases ──────────────────────────────────────────


def wrap_script_with_error_handling(script: str, operation_name: str = "operation") -> str:
    """Wrap script with error handling **and** document guard.

    .. deprecated:: Use :func:`wrap_script` directly.
    """
    return wrap_script(script, operation_name, require_document=True)


def wrap_script_no_document_check(script: str, operation_name: str = "operation") -> str:
    """Wrap script with error handling, **no** document guard.

    .. deprecated:: Use ``wrap_script(…, require_document=False)`` directly.
    """
    return wrap_script(script, operation_name, require_document=False)


def create_json_response_script(data_expression: str) -> str:
    """Convenience: evaluate *data_expression*, return it as ``data`` in the envelope.

    The user script sets ``var data = <expr>;`` and the wrapper's default
    success path picks it up via the ``(typeof data !== "undefined")`` check.
    """
    return wrap_script(
        f"var data = {data_expression};",
        require_document=False,
    )


# ── Reusable script fragments ────────────────────────────────────────
#
# Fragments assume ``var __op`` is in scope (injected by wrap_script).


def create_selection_check() -> str:
    """Selection guard fragment — uses ``__op`` for consistent envelope.

    Returns:
        ExtendScript fragment for selection validation.
    """
    return """
        var sel = doc.selection;
        if (!sel || sel.length === 0) {
            return JSON.stringify({
                ok: false,
                error: { message: "NO_SELECTION: No objects are selected. Please select one or more objects.",
                         line: null, operation: __op }
            });
        }
"""
