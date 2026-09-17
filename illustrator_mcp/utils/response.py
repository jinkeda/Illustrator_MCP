"""
Shared response parsing utilities.

Pure functions for JSON parsing and envelope unwrapping — used by both
proxy_client and response_classification without creating circular imports.
"""

import json
from collections.abc import Sequence
from typing import Any


class JsxPayloadError(ValueError):
    """A host response carried no usable JSX payload.

    Raised by :func:`require_jsx_payload` so that a caller cannot mistake
    missing evidence for a measured result.
    """


def _ends_inside_string(text: str) -> bool:
    """Whether *text* stops before a string's closing quote.

    Reported as an observation only. It says where the input stops, never why:
    a host that emitted malformed output and a transfer that was cut produce
    the same shape here, and nothing in the bytes distinguishes them.
    """
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
    return in_string


def _unclosed_containers(text: str) -> int:
    """How many objects or arrays are still open. An observation, not a cause."""
    depth = 0
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
    return max(0, depth)


def describe_parse_failure(raw: Any) -> "str | None":
    """Describe a reply that will not parse, without inventing a cause.

    An earlier version of this decoded *why* the payload was bad and reported
    a transport fault, telling the caller their script was not to blame. It
    could not know that. Successive attempts to make the heuristic sound —
    parser position, then structural balance, then a token-prefix check — were
    each defeated by a new input, because JSON syntax simply does not carry
    the information: `{"x":1..2`, `{"x":nope,"y":tru` and `{"x":"bad\\q` all
    look exactly like a cut transfer and none of them is one.

    So this reports what was observed and stops there. Establishing truncation
    needs evidence the host supplies — a declared length and a digest — which
    is OR09. Until then the honest answer is that the reply is not valid JSON
    and the cause is undetermined.

    Returns a ``C005``-coded message, or None when the payload parses.
    """
    if not isinstance(raw, str) or not raw:
        return None
    try:
        json.loads(raw)
        return None
    except json.JSONDecodeError as exc:
        from illustrator_mcp.errors import ErrorCode, format_code

        stripped = raw.rstrip()
        # Kept apart on purpose: the parser's character offset is where it gave
        # up, which is not the same as how much arrived, and conflating them
        # made one number mean two things.
        observations = [
            f"the parser stopped at character {exc.pos}",
            f"{len(raw)} characters were received",
        ]
        if _ends_inside_string(stripped):
            observations.append("the input ends inside an unterminated string")
        open_containers = _unclosed_containers(stripped)
        if open_containers:
            observations.append(
                f"{open_containers} container(s) were never closed"
            )

        return format_code(
            ErrorCode.C_JSON_PARSE,
            "the host reply is not valid JSON and the cause is undetermined: "
            + "; ".join(observations)
            + ". This may be a cut transfer or malformed output; nothing in "
            "the payload distinguishes them",
        )


#: Retained name for callers that predate the rename. It no longer claims
#: truncation, and returns the same undetermined-cause description.
describe_truncation = describe_parse_failure


def try_parse_json(value: Any) -> Any:
    """Attempt JSON parse, return original on failure."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def unwrap_result(result: Any, _depth: int = 0) -> Any:
    """
    Recursively unwrap nested success/result envelopes.

    Handles double-wrapped results like:
    {success: true, result: "{\"success\": true, \"result\": ...}"}

    Has a depth guard (max 10) to prevent infinite recursion on
    malformed responses with circular nesting.
    """
    if _depth > 10:
        return result

    if not isinstance(result, dict):
        return result

    # Error takes priority: key presence, not truthiness (catches "" and {})
    if "error" in result:
        return result
    # Handle {success: false} without 'error' key (edge case, rare)
    if result.get("success") is False:
        return result
    # Handle {ok: false} without 'error' key
    if result.get("ok") is False:
        return result

    # Unwrap legacy success envelope {success: true, result: …}
    if result.get("success") and "result" in result:
        inner = result["result"]
        # Parse if string, then recurse
        parsed = try_parse_json(inner) if isinstance(inner, str) else inner
        return unwrap_result(parsed, _depth + 1)

    # Unwrap standard {ok: true, data: …} envelope (wrap_script / SOC)
    if result.get("ok") is True and "data" in result:
        inner = result["data"]
        parsed = try_parse_json(inner) if isinstance(inner, str) else inner
        return unwrap_result(parsed, _depth + 1)

    # Alias: {ok: true, value: …} (SOC resolveProperty)
    if result.get("ok") is True and "value" in result and "data" not in result:
        return result["value"]

    return result


def unwrap_jsx_result(raw: Any, *, context: str = "") -> dict:
    """Unwrap an execute_script_with_context envelope to its payload dict.

    Handles:
    - Outer envelope ``{result: "<json>"}`` or ``{result: {...}}``
    - Inner ``{ok: true, data: ...}`` / ``{success: true, result: ...}``
    - Double-serialized strings (1-2 layers)
    - Non-JSON or missing results

    Returns:
        Parsed dict payload.  Returns ``{}`` on failure and logs a warning
        with *context* for diagnostics.
    """
    import logging as _log
    _logger = _log.getLogger(__name__)

    try:
        # Extract inner result from response envelope
        if isinstance(raw, dict):
            raw = raw.get("result", raw)

        parsed = try_parse_json(raw)
        result = unwrap_result(parsed)

        # Final pass: if still a string, try one more parse
        if isinstance(result, str):
            result = try_parse_json(result)

        if isinstance(result, dict):
            return result

        _logger.warning(
            "unwrap_jsx_result: non-dict result (type=%s)%s",
            type(result).__name__,
            f" context={context}" if context else "",
        )
        return {}
    except Exception as exc:
        _logger.warning(
            "unwrap_jsx_result: parse failed: %s%s",
            exc,
            f" context={context}" if context else "",
        )
        return {}


def require_jsx_payload(
    raw: Any,
    *,
    context: str = "",
    required_keys: Sequence[str] = (),
    allow_domain_failure: bool = False,
) -> dict:
    """Unwrap a host response to its payload dict, or raise.

    Strict counterpart to :func:`unwrap_jsx_result`.  That function returns
    ``{}`` when it cannot find a payload, and a caller reading the result
    with ``.get(key, default)`` then turns missing evidence into a
    measured-looking value — a validation scan with no findings, an item
    count of zero.  Those are different outcomes and this variant refuses to
    collapse them: either the payload is there, or the call fails.

    Use this wherever the payload *is* the evidence.  Keep
    :func:`unwrap_jsx_result` for callers that already treat an empty dict as
    "unknown, skip the optional step".

    Args:
        raw: The ``execute_script_with_context`` response.
        context: Label included in the raised message, for diagnostics.
        allow_domain_failure: Accept a decoded ok:false domain payload (e.g.
            observation preservation differences). Explicit error envelopes still
            raise, preserving transport/host errors.
        required_keys: Keys the payload must carry to be usable.  State the
            minimum evidence the caller needs, so a truncated payload fails
            here rather than reading as a clean result downstream.

    Returns:
        The payload dict.

    Raises:
        JsxPayloadError: The response could not be parsed, carried a non-dict
            payload, reported an in-band host error, or omitted a required key.
    """
    where = f" (context={context})" if context else ""

    try:
        candidate = raw.get("result", raw) if isinstance(raw, dict) and raw.get("error") is None else raw
        payload = unwrap_result(try_parse_json(candidate))
        # A doubly-serialized payload survives one more parse.
        if isinstance(payload, str):
            payload = try_parse_json(payload)
    except Exception as exc:  # pragma: no cover - defensive
        raise JsxPayloadError(
            f"could not parse the host response{where}: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        # A payload still in string form after unwrapping usually means the
        # parse failed, and the most common reason for that on a large result
        # is a transfer that stopped partway.
        cut = describe_truncation(payload if isinstance(payload, str) else candidate)
        if cut:
            raise JsxPayloadError(f"{cut}{where}")
        raise JsxPayloadError(
            f"the host response carried no object payload{where} "
            f"(got {type(payload).__name__})"
        )

    # An in-band failure is evidence of failure, not a payload to read.
    if (
        "error" in payload
        or (payload.get("ok") is False and not allow_domain_failure)
        or payload.get("success") is False
    ):
        error = JsxPayloadError(
            f"the host reported an error{where}: {payload.get('error', payload)!r}"
        )
        error.host_error = payload.get("error", payload)
        raise error

    missing = [key for key in required_keys if key not in payload]
    if missing:
        raise JsxPayloadError(
            f"the host payload is missing required key(s) "
            f"{', '.join(repr(k) for k in missing)}{where}"
        )

    return payload


def normalize_raw_script_response(response: dict) -> dict:
    """Remove the known bridge/host envelope once; never unwrap user objects.

    This is only for the raw evaluator. SOC reports keep their domain semantics.
    The private marker is produced server-side, never interpreted from user data.
    """
    if response.get("error"):
        return response
    value = try_parse_json(response.get("result"))
    if isinstance(value, dict) and "ok" in value and "data" in value:
        if value["ok"] is not True:
            return response
        value = value["data"]
    return {**response, "_rawScriptValue": try_parse_json(value)}
