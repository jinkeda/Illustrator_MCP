"""Worked calls for every tool, in the form a client actually sends.

The examples in tool docstrings used to be written as pseudo-Python calls:
``illustrator_execute_task(payload={task: ...})``. That is not what goes on
the wire. Every tool takes a single ``params`` object, and a caller copying
the old form got a validation error naming a field they had supplied. One
report of exactly that failure is what prompted this module.

This is the single source. Docstring EXAMPLES sections are rendered from the
entries below, and a test in the check gate does two things: it validates
every example against the tool's real argument model, and it compares each
docstring's EXAMPLES body against what :func:`render_examples` produces now.
An example that stops being valid, or a docstring edited away from the data,
fails the build rather than misleading the next caller.

To change an example, edit it here, run ``python -m
illustrator_mcp.tools.examples`` to print the rendered blocks, and paste the
one you changed back into that tool's docstring.
"""

import json
import re
from copy import deepcopy
from typing import Dict, List, Optional, Tuple

#: Compact JSON longer than this is rendered across multiple lines instead.
_INLINE_LIMIT = 96


def operation_example(name: str) -> dict:
    """Render a catalogue example through its supported public entry point."""
    from illustrator_mcp.schemas.contracts import get_op_schema

    schema = get_op_schema(name)
    if schema is None:
        raise ValueError(f"Unknown operation {name!r}; read illustrator://ops for available names.")
    params = deepcopy(schema.documentation.example_params)
    if schema.route == "python_tool":
        return {"tool": schema.public_route, "arguments": {"params": params}}
    op = {"task": name, "params": params}
    if schema.documentation.example_targets is not None:
        op["targets"] = deepcopy(schema.documentation.example_targets)
    if schema.route == "typed_batch":
        request = {"batch": {"operations": [op], "stopOnError": True}}
    else:
        request = {"payload": {"task": "catalogue_example", "params": {"ops": [op]},
                               "options": {"stopOnError": True}}}
    request["return_preview"] = False
    return {"tool": "illustrator_execute_task", "arguments": {"params": request}}

#: tool name -> [(caption, complete tool arguments as sent on the wire)]
TOOL_EXAMPLES: Dict[str, List[Tuple[str, dict]]] = {

    # Scripts here are single-line on purpose. Docstrings are ordinary Python
    # strings, so a backslash in an example is interpreted before the text
    # reaches a reader: an escaped newline arrives as a real line break, and
    # the example stops being the JSON it claims to be. A test forbids
    # backslashes in rendered examples for exactly that reason.
    "illustrator_execute_script": [
        ("Read with a native-coordinate crop", {"params": {"script": "app.activeDocument.name;", "return_preview": True, "clip_box": [0, 125, 125, 0], "clip_space": "illustrator_native_y_up"}}),
        ("Draw in artboard-relative Y-down coordinates with geometry helpers", {"params": {
            "script": "var r = rectXY(50, 80, 200, 100); r.fillColor = makeRGBColor(255, 0, 0); r.name;",
            "includes": ["geometry"],
            "description": "red banner",
        }}),
        ("Position text from an offset artboard using raw DOM coordinates", {"params": {
            "script": "var doc = app.activeDocument; var ab = doc.artboards[doc.artboards.getActiveArtboardIndex()].artboardRect; var x = 100; var y = 200; var tf = doc.textFrames.add(); tf.contents = 'Offset'; tf.position = [ab[0] + x, ab[1] - y]; tf.position;",
            "description": "raw DOM offset-artboard placement",
        }}),
        ("Read state back; the last expression is the result", {"params": {
            "script": "JSON.stringify({items: app.activeDocument.pageItems.length});",
        }}),
        ("Return early, which needs a function wrapper", {"params": {
            "script": "(function () { var d = app.activeDocument; if (d.pageItems.length === 0) return 'empty'; return d.pageItems[0].name; })()",
        }}),
        ("A readback, declared so it is not treated as an edit", {"params": {
            "script": "JSON.stringify({name: app.activeDocument.name});",
            "read_only": True,
        }}),
    ],

    "illustrator_execute_task": [
        ("One structured operation (the preferred form)", {"params": {
            "batch": {"operations": [
                {"task": "element_create", "params": {
                    "type": "rect", "x": 40, "y": 40, "width": 200, "height": 120,
                    "fill": {"r": 0, "g": 150, "b": 136}}},
            ]},
        }}),
        ("Several operations, stopping at the first failure", {"params": {
            "batch": {
                "operations": [
                    {"task": "element_create", "params": {
                        "type": "ellipse", "x": 0, "y": 0, "width": 60, "height": 60,
                        "id": "dot"}},
                    {"task": "element_modify",
                     "targets": {"type": "id", "ids": ["dot"]},
                     "params": {"x": 120}},
                ],
                "stopOnError": True,
            },
        }}),
        ("Validate a batch without applying it", {"params": {
            "batch": {
                "operations": [
                    {"task": "element_create", "params": {
                        "type": "star", "x": 100, "y": 100,
                        "numPoints": 5, "outerRadius": 40, "innerRadius": 18}},
                ],
                "mode": "validate",
            },
        }}),
        ("Create a layer through the compatibility route", {"params": {
            "payload": {
                "task": "layer_create",
                "params": {"name": "Background"},
            },
        }}),
        ("Create a layer, then a rectangle on it, in one batch", {"params": {
            "batch": {
                "operations": [
                    {"task": "layer_create", "params": {"name": "Background"}},
                    {"task": "element_create", "params": {
                        "type": "rect", "x": 0, "y": 0,
                        "width": 800, "height": 600, "layer": "Background",
                    }},
                ],
                "stopOnError": True,
            },
        }}),
    ],

    "illustrator_job_status": [
        ("Reconcile a job whose reply was lost", {"params": {
            "jobId": "job_7f3a91c2",
        }}),
    ],

    "illustrator_observe": [
        ("Compact annotated evidence and handles", {"params": {"mode": "annotated", "detail": "summary", "map_detail": "compact"}}),
        ("Look at the page and get handles for what is on it", {"params": {
            "mode": "both",
        }}),
        ("Crop to a region, in artboard-relative points", {"params": {
            "mode": "raw", "clip_box": [0, 0, 200, 120],
        }}),
        ("Compare every artboard on one contact sheet", {"params": {
            "artboards": "all",
        }}),
        ("Three specific boards, on a checkerboard", {"params": {
            "artboards": [0, 2, 5], "background": "checkerboard",
        }}),
    ],

    "illustrator_query_items": [
        ("Require exactly one matching text label", {"params": {"targets": {"type": "query", "contents": "alpha-helix", "expect": {"count": 1}}}}),
        ("Every path whose name starts with axis_", {"params": {
            "targets": {"type": "query", "itemType": "PathItem", "pattern": "axis_*"},
        }}),
        ("Everything on a named layer", {"params": {
            "targets": {"type": "layer", "layer": "Layer 1"},
        }}),
    ],

    "illustrator_preflight_check": [
        ("Check supplied publication thresholds", {"params": {"publication": {"output_width_mm": 89, "min_font_pt": 5, "min_stroke_pt": 0.25, "min_image_ppi": 300}}}),
        ("Check the active artboard before exporting", {"params": {}}),
        ("Check one artboard, counting any overlap as on-artboard", {"params": {
            "artboard_index": 0, "policy": "intersects",
        }}),
    ],

    "illustrator_get_document": [
        ("Document structure", {"params": {}}),
        ("Application info, with no document open", {"params": {"scope": "app"}}),
        ("One layer, paginated", {"params": {
            "layer_name": "Layer 1", "offset": 200, "max_items": 200,
        }}),
        ("Symbol definitions and instances, without placing anything", {"params": {
            "scope": "symbols",
        }}),
        ("One symbol, names and counts only", {"params": {
            "scope": "symbols", "symbol_name": "icon-star", "symbol_contents": False,
        }}),
    ],

    "illustrator_document": [
        ("Create", {"params": {
            "action": "create", "width": 800, "height": 600, "color_mode": "RGB",
        }}),
        ("Open", {"params": {"action": "open", "file_path": "C:/art/figure.ai"}}),
        ("Save under a new name", {"params": {
            "action": "save", "file_path": "C:/art/figure_v2.ai",
        }}),
        ("Close, saving first", {"params": {
            "action": "close", "save_before_close": True,
        }}),
    ],

    "illustrator_export_document": [
        ("PNG at twice the size", {"params": {
            "file_path": "C:/out/fig.png", "format": "png", "scale": 2.0,
        }}),
        ("PDF refusal; use a separate working copy with Illustrator PDF save", {"params": {"file_path": "C:/out/fig.pdf", "format": "pdf"}}),
        ("SVG refusal after source-association failure; use a separate working copy", {"params": {"file_path": "C:/out/fig.svg", "format": "svg"}}),
        ("PNG of the artboard, returned inline as well", {"params": {
            "file_path": "C:/out/fig.png", "return_image": True,
            "artboard_only": True,
        }}),
        ("Refuse rather than overwrite an existing file", {"params": {
            "file_path": "C:/out/fig.png", "format": "png", "overwrite": "fail",
        }}),
        ("Keep the old file and write beside it", {"params": {
            "file_path": "C:/out/fig.png", "overwrite": "version",
        }}),
    ],

    "illustrator_history": [
        ("Undo three steps", {"params": {"action": "undo", "count": 3}}),
        ("Save a checkpoint before risky work", {"params": {
            "action": "checkpoint_save", "name": "before_boolean",
        }}),
        ("Restore it", {"params": {
            "action": "checkpoint_restore", "name": "before_boolean",
        }}),
        ("List checkpoints", {"params": {"action": "checkpoint_list"}}),
    ],

    "illustrator_place_file": [
        ("Place a linked image", {"params": {
            "file_path": "C:/img/photo.png", "x": 100, "y": 50, "linked": True,
        }}),
        ("Place and auto-trace", {"params": {
            "file_path": "C:/img/photo.png", "trace": True,
            "trace_preset": "6 Colors",
        }}),
    ],

    "illustrator_set_reference": [
        ("Set a dimmed tracing reference", {"params": {
            "action": "set", "file_path": "C:/ref/sketch.png", "opacity": 50,
        }}),
        ("Legacy set (still accepted)", {"params": {
            "file_path": "C:/ref/sketch.png",
        }}),
        ("Clear the reference layer", {"params": {"action": "clear"}}),
    ],

    "illustrator_path_boolean": [
        ("Unite", {"params": {
            "operation": "unite", "subject": "body_id", "clip": ["wing_id"],
        }}),
        ("Subtract a hole", {"params": {
            "operation": "subtract", "subject": "plate_id", "clip": ["hole_id"],
        }}),
    ],

    "illustrator_path_import_svg": [
        ("A curve", {"params": {"d": "M 10 50 C 20 20, 80 20, 90 50 Z"}}),
        ("Filled red", {"params": {
            "d": "M 0 0 L 100 0 L 100 100 Z", "fill": {"r": 255, "g": 0, "b": 0},
        }}),
        ("Stroked with no fill", {"params": {
            "d": "M 0 0 L 50 50 L 100 0",
            "stroke": {"r": 0, "g": 0, "b": 0, "width": 2},
            "fill": False,
        }}),
        ("With an explicit id for later targeting", {"params": {
            "d": "M 0 0 L 100 0 L 100 100 Z", "id": "triangle",
        }}),
    ],

    "illustrator_connection_status": [
        ("Instant report, no host call", {"params": {}}),
        ("Also confirm Illustrator itself answers", {"params": {"probe": True}}),
    ],
}


def batch_operation_names(schema: Optional[dict] = None) -> List[str]:
    """Return the typed operation tags from the batch discriminator mapping.

    The Pydantic union is the authority.  This helper is intentionally a
    development-time documentation renderer, not a second runtime registry.
    Passing the registered argument model's JSON Schema lets checks use the
    exact contract published over MCP; omitting it renders from the input model
    while editing the source documentation.
    """
    if schema is None:
        from illustrator_mcp.tools.task_execution import ExecuteTaskInput

        schema = ExecuteTaskInput.model_json_schema()

    mapping = schema["$defs"]["StructuredPilotBatch"]["properties"][
        "operations"
    ]["items"]["discriminator"]["mapping"]
    names = sorted(mapping)
    token = re.compile(r"^[a-z][a-z0-9_]*$")
    invalid = [name for name in names if not token.fullmatch(name)]
    if invalid:
        raise ValueError(f"Invalid typed batch operation tag(s): {invalid}")
    if len(names) != len(set(names)):
        raise ValueError("Duplicate typed batch operation tags")
    return names


def render_supported_batch_operations(schema: Optional[dict] = None) -> str:
    """Render the checked operation-list line used in the tool description."""
    return "SUPPORTED_BATCH_OPERATIONS: [" + ", ".join(
        batch_operation_names(schema)
    ) + "]"


def render_examples(tool_name: str, indent: str = "      ") -> str:
    """The EXAMPLES body for one tool, exactly as its docstring must carry it."""
    lines: List[str] = []
    for caption, args in TOOL_EXAMPLES[tool_name]:
        compact = json.dumps(args, separators=(", ", ": "))
        lines.append(f"{indent}{caption}:")
        if len(compact) + len(indent) + 2 <= _INLINE_LIMIT:
            lines.append(f"{indent}  {compact}")
        else:
            pretty = json.dumps(args, indent=2)
            lines.extend(f"{indent}  {line}" for line in pretty.splitlines())
    return "\n".join(lines)


def examples_section(description: str) -> Optional[str]:
    """The EXAMPLES body of a tool description, or None if it has none.

    The section ends at the next *known* docstring header. Matching any
    capitalised word followed by a colon would end it at a caption like
    ``PDF:``, silently truncating the section and making a comparison against
    it pass for the wrong reason.
    """
    from illustrator_mcp.tools.base import ALLOWED_DOCSTRING_SECTIONS

    headers = "|".join(
        re.escape(h.rstrip(":")) for h in sorted(ALLOWED_DOCSTRING_SECTIONS)
    )
    match = re.search(
        rf"^[ \t]*EXAMPLES:[ \t]*$(.*?)(?=^[ \t]*(?:{headers}):[ \t]*$|\Z)",
        description or "", re.M | re.S,
    )
    if not match:
        return None
    return "\n".join(
        line.rstrip() for line in match.group(1).strip("\n").splitlines()
    ).strip("\n")


def main() -> None:  # pragma: no cover - developer convenience
    """Print every rendered block, for pasting into docstrings."""
    print(render_supported_batch_operations())
    for name in TOOL_EXAMPLES:
        print(f"\n## {name}\n    EXAMPLES:")
        print(render_examples(name))


if __name__ == "__main__":  # pragma: no cover
    main()
