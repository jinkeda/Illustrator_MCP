"""Shared bounds configuration and strict evidence parsing; no reservation owner."""
import json
from typing import Literal
from pydantic import BaseModel
from illustrator_mcp.utils.response import require_jsx_payload

BoundsType = Literal["visible", "geometric"]
BoundsSource = Literal["group_visible", "clipping_path"]
BoundsScope = Literal["document", "artboard"]
BoundsPolicy = Literal["fully-contained", "intersects"]


class BoundsOptions(BaseModel):
    artboardIndex: int | None = None
    boundsType: BoundsType = "visible"
    boundsSource: BoundsSource = "group_visible"
    scope: BoundsScope = "document"
    policy: BoundsPolicy = "fully-contained"
    ignoreHidden: bool = True
    ignoreLocked: bool = True

    def jsx(self):
        return json.dumps(self.model_dump())


async def check_bounds(execute, *, options: BoundsOptions, command: str, tool: str):
    """Run inside the caller's reservation; missing evidence raises, never passes."""
    response = await execute(script="countItemsOnArtboard(" + options.jsx() + ");",
        command_type=command, tool_name=tool, includes=["validate"])
    if isinstance(response, dict) and response.get("execution") == "unknown":
        from illustrator_mcp.execution import HostUnresolvedError, get_coordinator
        raise HostUnresolvedError(response.get("jobId") or get_coordinator().active_job_id)
    if isinstance(response, dict) and response.get("error"):
        raise ValueError(str(response["error"]))
    findings = require_jsx_payload(response, context=command,
        required_keys=("on_artboard", "off_artboard"))
    for key in ("on_artboard", "off_artboard", "skipped", "items_total", "items_checked"):
        if key in findings and (type(findings[key]) is not int or findings[key] < 0):
            raise ValueError(f"{command}: {key} must be a nonnegative integer count")
    return findings
