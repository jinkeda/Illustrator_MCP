/**
 * compute_soc_batch.jsx — Default compute function for SOC batch mode.
 *
 * Used by execute_task when no compute_fn is provided.
 * Runs executeOpBatch(params.ops) and updates the report stats.
 *
 * AUTO-INJECTED — Do not call directly.
 *
 * Supports two payload shapes:
 *   1. Batch mode:  {task: "batch_name", params: {ops: [{task, params}, ...]}}
 *   2. Single mode: {task: "element_create_batch", params: {template: ..., array: ...}}
 *      → auto-wrapped to [{task: payload.task, params: payload.params, targets: payload.targets}]
 *
 * executeOpBatch return shape (see BATCH_REPORT_SCHEMA in contracts.py):
 *   {ok, stats: {total, passed, failed}, createdIds, ops}
 */
function compute(items, params, report) {
    // Determine ops array: explicit params.ops or auto-wrap single op
    var ops = null;
    if (params.ops && params.ops.length > 0) {
        ops = params.ops;
    } else if (payload && payload.task) {
        // Single-op mode: wrap the top-level task+params as a single op.
        // Forward payload.targets so the op handler receives resolved targets.
        ops = [{ task: payload.task, params: params, targets: payload.targets || null }];
    }

    if (ops && ops.length > 0) {
        var result = executeOpBatch(ops, { strict: false });

        // --- Stats propagation ---
        // itemsProcessed: total ops attempted
        report.stats.itemsProcessed = result.stats ? result.stats.total : 0;

        // itemsCreated: count of newly created items (from createdIds)
        report.stats.itemsCreated = result.createdIds ? result.createdIds.length : 0;

        // itemsModified: sum of handler-reported modifications (style, move, etc.)
        // Uses typeof guard to avoid truthiness bug (modified:0 is falsy)
        var modifiedCount = 0;
        if (result.ops) {
            for (var m = 0; m < result.ops.length; m++) {
                __mcp_check();
                if (result.ops[m].ok && result.ops[m].data) {
                    var n = result.ops[m].data.modified;
                    if (typeof n === "number") modifiedCount += n;
                }
            }
        }
        report.stats.itemsModified = modifiedCount;

        // itemsSkipped: failed ops
        report.stats.itemsSkipped = result.stats ? result.stats.failed : 0;

        // Warn when targets were provided but resolved to zero items
        if (result.ops) {
            for (var w = 0; w < result.ops.length; w++) {
                __mcp_check();
                if (result.ops[w].ok && result.ops[w].targets_resolved === 0
                    && ops[w] && ops[w].targets) {
                    report.warnings.push(
                        "Resolved 0 targets for task '" + ops[w].task +
                        "'; no items modified. Check target IDs/selectors."
                    );
                }
            }
        }

        // Propagate batch failure to pipeline report
        if (!result.ok) {
            report.ok = false;
            // Surface first op error to pipeline level
            if (result.ops) {
                for (var i = 0; i < result.ops.length; i++) {
                    __mcp_check();
                    if (!result.ops[i].ok && result.ops[i].error) {
                        report.errors.push(result.ops[i].error);
                        break;
                    }
                }
            }
        }

        report.batchReport = result;
    }
    return [];
}

