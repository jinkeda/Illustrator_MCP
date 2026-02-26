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
 *      → auto-wrapped to [{task: payload.task, params: payload.params}]
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
        // Single-op mode: wrap the top-level task+params as a single op
        ops = [{ task: payload.task, params: params }];
    }

    if (ops && ops.length > 0) {
        var result = executeOpBatch(ops, { strict: false });

        // Propagate element-level stats (not op-level)
        report.stats.itemsProcessed = result.stats ? result.stats.total : 0;
        report.stats.itemsModified = result.createdIds ? result.createdIds.length : 0;
        report.stats.itemsSkipped = result.stats ? result.stats.failed : 0;

        // Propagate batch failure to pipeline report
        if (!result.ok) {
            report.ok = false;
            // Surface first op error to pipeline level
            for (var i = 0; i < result.ops.length; i++) {
                __mcp_check();
                if (!result.ops[i].ok && result.ops[i].error) {
                    report.errors.push(result.ops[i].error);
                    break;
                }
            }
        }

        report.batchReport = result;
    }
    return [];
}

