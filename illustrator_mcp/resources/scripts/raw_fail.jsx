/** Explicit raw-script failure; ordinary, catchable Error. No side effects. */
function mcpFail(message, details) {
    var detail = "";
    try { detail = JSON.stringify(details); } catch (e) { detail = "[unserializable details]"; }
    if (typeof detail !== "string") detail = "";
    detail = detail.substring(0, 2048);
    var error = new Error("MCP_FAIL: " + String(message).substring(0, 2048) +
        (detail ? " | details: " + detail : ""));
    error.name = "MCP_FAIL";
    error.mcpDetails = detail;
    throw error;
}
