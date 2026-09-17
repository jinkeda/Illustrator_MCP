/**
 * error_envelope.jsx — the structured error envelope, and nothing else.
 *
 * OR14. `makeError` lived in `task_pipeline.jsx`, which depends on
 * `targets.jsx`. `targets.jsx` calls `makeError` twenty-five times and could
 * not declare where it comes from without creating a cycle, so it declared
 * nothing and worked by the accident that something else always loaded
 * `task_pipeline` first. That accident held only because every caller
 * happened to pull in the whole cluster; a narrower include set would have
 * produced a ReferenceError at the first validation failure — the same shape
 * as the `ownership.jsx` defect, where a library was adopted and never
 * injected.
 *
 * A leaf with no dependencies of its own can be declared by anything, which
 * is the point. `contracts.jsx` would have been the natural home, but it is
 * generated from `illustrator_mcp/schemas/contracts.py` and must not be
 * hand-edited.
 *
 * Nothing else belongs here. This is not a general error module; it is the
 * one function two libraries both need and neither can own.
 */

/**
 * Build a structured failure envelope.
 *
 * @param {string} code    an ErrorCodes value
 * @param {string} message human-readable detail
 * @param {string} stage   where it happened: validate, apply, verify, ...
 * @param {Object} [itemRef] the item concerned, when there is one
 * @param {Object} [details] anything a caller needs to act on
 * @returns {Object} {ok: false, error: {code, message, stage, itemRef, details}}
 */
function makeError(code, message, stage, itemRef, details) {
    return {
        ok: false,
        error: {
            code: code,
            message: message,
            stage: stage,
            itemRef: itemRef || null,
            details: details || null
        }
    };
}
