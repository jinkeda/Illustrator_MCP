/**
 * DEPRECATED — Schema definitions have moved to contracts.jsx
 * This file exists for backward compatibility only.
 *
 * DO NOT EDIT. All schema changes must go through:
 *   contracts.py -> python -m illustrator_mcp.tools.compile_contracts
 *
 * Source of truth: contracts.jsx exports:
 *   - OP_PARAM_SCHEMAS    (schemas only)
 *   - validateOpParams    (parameter validator)
 *   - getOpSchema         (single schema lookup)
 *   - listSchemaOps       (list known ops)
 *
 * This forwarder will be removed in a future release.
 * If contracts.jsx is loaded first (as it should be via manifest
 * dependencies), all symbols are already defined. This file is
 * a no-op safety net.
 */

// Guard: verify contracts.jsx was loaded
if (typeof OP_PARAM_SCHEMAS === "undefined") {
    // contracts.jsx not loaded — this should not happen in normal operation.
    // Emit a warning but don't crash.
    $.writeln("[WARN] op_schemas.jsx: contracts.jsx not loaded. OP_PARAM_SCHEMAS unavailable.");
}
