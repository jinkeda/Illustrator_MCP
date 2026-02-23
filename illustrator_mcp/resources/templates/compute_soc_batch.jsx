/**
 * compute_soc_batch.jsx — Default compute function for SOC batch mode.
 *
 * Used by execute_task when no compute_fn is provided.
 * Runs executeOpBatch(params.ops) and updates the report stats.
 *
 * AUTO-INJECTED — Do not call directly.
 *
 * executeOpBatch return shape (see BATCH_REPORT_SCHEMA in contracts.py):
 *   {ok, stats: {total, passed, failed}, createdIds, ops}
 */
function compute(items, params, report) {
    if (params.ops && params.ops.length > 0) {
        var result = executeOpBatch(params.ops, { strict: false });
        report.stats.itemsModified = result.stats ? result.stats.passed : 0;
        report.batchReport = result;
    }
    return [];
}
