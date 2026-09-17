/**
 * host_runtime.jsx — versioned host runtime bootstrap and handshake (T10)
 *
 * Establishes a single, identifiable runtime namespace on $.global so Python
 * can ask the host what it is running before sending work to it.
 *
 * WHY $.global — measured, not assumed (T08, Illustrator 30.7.0):
 *   Top-level `function` declarations and `var`s do NOT survive between
 *   evalScript calls. Anything reachable from $.global DOES — plain data,
 *   functions, and nested namespaces alike — and it also survives the CEP
 *   panel reconnecting. See docs/HOST_PERSISTENCE_FINDINGS.md.
 *
 * Because $.global outlives a reconnect, the session epoch MUST be generated
 * here, by the host. A reconnected panel is not a fresh runtime, so anything
 * derived from connection count would rotate when the runtime had not — and
 * fail to rotate when it had.
 *
 * This module is deliberately dependency-free: the handshake has to be
 * runnable before any library has been loaded, including this one's own
 * payload.
 *
 * @exports MCP_BOOTSTRAP_VERSION, mcpRuntimeState, mcpRuntimeInit,
 *          mcpRuntimeHandshake, mcpRuntimeBeginWork, mcpRuntimeCompleteWork,
 *          mcpRuntimeJobStatus, mcpRuntimeEndWork, mcpRuntimeReset
 * @version 1.1.0
 */

var MCP_BOOTSTRAP_VERSION = "1.1.0";

/** Key under $.global holding the runtime record. */
var MCP_RUNTIME_KEY = "__mcpRuntime";
var MCP_HOST_RECORD_RETENTION_MS = 15 * 60 * 1000;
var MCP_HOST_MAX_RECORDS = 100;

// ==================== Internals ====================

/**
 * Generate a session epoch: an opaque, host-generated identity for one
 * installed runtime. Rotates on every init/reset and never on reconnect.
 */
function _mcpNewEpoch() {
    var now = new Date().getTime();
    var rand = Math.floor(Math.random() * 0xFFFFFF);
    return "ep_" + now.toString(16) + "_" + rand.toString(16);
}

function _mcpRuntime() {
    return $.global[MCP_RUNTIME_KEY] || null;
}

function _mcpCountKeys(obj) {
    var n = 0, k;
    for (k in obj) { if (obj.hasOwnProperty(k)) n++; }
    return n;
}

function _mcpKeys(obj) {
    var out = [], k;
    for (k in obj) { if (obj.hasOwnProperty(k)) out.push(k); }
    return out;
}

function _mcpOwn(obj, key) {
    return !!obj && Object.prototype.hasOwnProperty.call(obj, key);
}

function _mcpValidJobId(jobId) {
    return typeof jobId === "string" &&
        /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(jobId);
}

function _mcpEmptyEffects() {
    return { created: [], modified: [], deleted: [], complete: false };
}

function _mcpCopyList(value) {
    var out = [];
    if (!(value instanceof Array)) return out;
    for (var i = 0; i < value.length; i++) out.push(value[i]);
    return out;
}

function _mcpCopyEffects(value) {
    value = value || {};
    return {
        created: _mcpCopyList(value.created),
        modified: _mcpCopyList(value.modified),
        deleted: _mcpCopyList(value.deleted),
        complete: value.complete === true
    };
}

/** Drop expired completions and bound the retained terminal ledger. */
function _mcpPruneJobRecords(rt) {
    if (!rt) return;
    if (!rt.jobRecords) rt.jobRecords = {};
    if (!(rt.jobOrder instanceof Array)) rt.jobOrder = [];

    var now = new Date().getTime();
    var kept = [], i, jobId, record;
    for (i = 0; i < rt.jobOrder.length; i++) {
        jobId = rt.jobOrder[i];
        record = _mcpOwn(rt.jobRecords, jobId) ? rt.jobRecords[jobId] : null;
        if (!record) continue;
        var inactive = !_mcpOwn(rt.activeJobs || {}, jobId);
        var expired = inactive && record.completedAt &&
            (now - record.completedAt) > MCP_HOST_RECORD_RETENTION_MS;
        if (expired) delete rt.jobRecords[jobId];
        else kept.push(jobId);
    }

    while (kept.length > MCP_HOST_MAX_RECORDS) {
        var removed = false;
        for (i = 0; i < kept.length; i++) {
            record = _mcpOwn(rt.jobRecords, kept[i]) ? rt.jobRecords[kept[i]] : null;
            if (record && !_mcpOwn(rt.activeJobs || {}, kept[i])) {
                delete rt.jobRecords[kept[i]];
                kept.splice(i, 1);
                removed = true;
                break;
            }
        }
        if (!removed) break; // never discard a job that may still be running
    }
    rt.jobOrder = kept;
}

// ==================== State ====================

/**
 * Report the current runtime state without changing anything.
 *
 * Safe to call when no runtime is installed — that is its main job.
 *
 * @returns {Object} {present, bootstrapVersion, protocolVersion, runtimeHash,
 *                    sessionEpoch, capabilities, installedAt, activeJobs,
 *                    activeJobIds, retainedJobs, retainedJobIds}
 */
function mcpRuntimeState() {
    var rt = _mcpRuntime();
    if (!rt) {
        return {
            present: false,
            bootstrapVersion: MCP_BOOTSTRAP_VERSION,
            protocolVersion: null,
            runtimeHash: null,
            sessionEpoch: null,
            capabilities: {},
            installedAt: null,
            activeJobs: 0,
            activeJobIds: [],
            retainedJobs: 0,
            retainedJobIds: []
        };
    }
    _mcpPruneJobRecords(rt);
    var active = rt.activeJobs || {};
    var records = rt.jobRecords || {};
    return {
        present: true,
        bootstrapVersion: rt.bootstrapVersion || null,
        protocolVersion: rt.protocolVersion || null,
        runtimeHash: rt.runtimeHash || null,
        sessionEpoch: rt.sessionEpoch || null,
        capabilities: rt.capabilities || {},
        installedAt: rt.installedAt || null,
        activeJobs: _mcpCountKeys(active),
        activeJobIds: _mcpKeys(active),
        retainedJobs: _mcpCountKeys(records),
        retainedJobIds: _mcpKeys(records)
    };
}

// ==================== Initialisation ====================

/**
 * Install (or replace) the runtime namespace and rotate the session epoch.
 *
 * REFUSES to replace a runtime that has unfinished work, unless
 * `spec.force` is true. Replacing the namespace changes the runtime identity
 * out from under any job already running in the host; the caller must decide
 * what that means for those jobs rather than have them silently vanish.
 *
 * When it does proceed over unfinished work (force), the displaced job IDs are
 * returned in `displacedJobIds` so the caller can mark them UNKNOWN. They are
 * never reported as "not applied" — the host may well have completed them.
 *
 * @param {Object} spec - {protocolVersion, runtimeHash, capabilities, force}
 * @returns {Object} {ok, status, state, displacedJobIds, previousEpoch}
 */
function mcpRuntimeInit(spec) {
    spec = spec || {};
    var existing = _mcpRuntime();
    var previousEpoch = existing ? (existing.sessionEpoch || null) : null;
    var activeIds = existing ? _mcpKeys(existing.activeJobs || {}) : [];

    if (existing && activeIds.length > 0 && spec.force !== true) {
        return {
            ok: false,
            status: "busy",
            message: "Runtime has " + activeIds.length + " unfinished job(s); " +
                "reinitialising would change the runtime identity underneath " +
                "them. Resolve or reconcile them first, or pass force:true and " +
                "treat them as unknown.",
            state: mcpRuntimeState(),
            displacedJobIds: activeIds,
            previousEpoch: previousEpoch
        };
    }

    if (existing && typeof mcpHandleInvalidateAll === "function") {
        mcpHandleInvalidateAll("host_runtime_reinitialised");
    }

    $.global[MCP_RUNTIME_KEY] = {
        bootstrapVersion: MCP_BOOTSTRAP_VERSION,
        protocolVersion: spec.protocolVersion || null,
        runtimeHash: spec.runtimeHash || null,
        sessionEpoch: _mcpNewEpoch(),
        capabilities: spec.capabilities || {},
        installedAt: new Date().getTime(),
        activeJobs: {},
        jobRecords: {},
        jobOrder: []
    };

    return {
        ok: true,
        status: existing ? "reinitialised" : "initialised",
        state: mcpRuntimeState(),
        displacedJobIds: activeIds,
        previousEpoch: previousEpoch
    };
}

/**
 * Compare the installed runtime against what the caller expects.
 *
 * Resolves nothing on its own — it reports, so the caller can decide whether
 * to initialise, proceed, or fail before any work is dispatched.
 *
 * @param {Object} expected - {protocolVersion, runtimeHash, sessionEpoch}
 * @returns {Object} {status, matches, state, mismatches}
 *   status: "absent"   — nothing installed; initialise before working
 *           "ready"    — everything the caller pinned matches
 *           "mismatch" — installed but not what the caller expects
 */
function mcpRuntimeHandshake(expected) {
    expected = expected || {};
    var state = mcpRuntimeState();

    if (!state.present) {
        return {
            status: "absent",
            matches: false,
            state: state,
            mismatches: ["runtime not installed"]
        };
    }

    var mismatches = [];
    if (expected.protocolVersion && expected.protocolVersion !== state.protocolVersion) {
        mismatches.push("protocolVersion: expected " + expected.protocolVersion +
            ", host has " + state.protocolVersion);
    }
    if (expected.runtimeHash && expected.runtimeHash !== state.runtimeHash) {
        mismatches.push("runtimeHash: expected " + expected.runtimeHash +
            ", host has " + state.runtimeHash);
    }
    // An unexpected epoch means the runtime was reinstalled since the caller
    // last looked — anything it believed about in-flight work is now suspect.
    if (expected.sessionEpoch && expected.sessionEpoch !== state.sessionEpoch) {
        mismatches.push("sessionEpoch: expected " + expected.sessionEpoch +
            ", host has " + state.sessionEpoch + " (runtime was reinitialised)");
    }

    return {
        status: mismatches.length === 0 ? "ready" : "mismatch",
        matches: mismatches.length === 0,
        state: state,
        mismatches: mismatches
    };
}

// ==================== Work tracking ====================

/**
 * Mark a job as running in the host.
 *
 * This is what makes "do not reload during active execution" enforceable:
 * mcpRuntimeInit refuses while any job is open.
 *
 * @param {string|Object} spec - job id, or {jobId, digest, context}
 * @returns {Object} {ok, sessionEpoch, activeJobs}
 */
function mcpRuntimeBeginWork(spec) {
    var rt = _mcpRuntime();
    if (!rt) {
        return { ok: false, status: "absent", message: "Runtime not installed" };
    }
    if (typeof spec === "string") spec = { jobId: spec };
    spec = spec || {};
    var jobId = spec.jobId;
    var digest = spec.digest || null;
    if (!_mcpValidJobId(jobId)) {
        return { ok: false, status: "invalid", message: "jobId is required" };
    }
    _mcpPruneJobRecords(rt);

    var existing = _mcpOwn(rt.jobRecords, jobId) ? rt.jobRecords[jobId] : null;
    if (existing) {
        if (existing.digest && digest && existing.digest !== digest) {
            return {
                ok: false, status: "conflict",
                message: "Job id was already used with a different request digest",
                sessionEpoch: rt.sessionEpoch,
                record: existing
            };
        }
        // A continuation must come from the same live Python owner and the
        // exact next phase. A restarted caller cannot replay an old phase.
        if (spec.phase && spec.context && existing.context &&
                spec.context.owner === existing.context.owner &&
                spec.phase === existing.context.nextPhase &&
                existing.completed !== true && !_mcpOwn(rt.activeJobs, jobId)) {
            rt.activeJobs[jobId] = {startedAt: new Date().getTime(), digest: digest};
            existing.status = "running";
            return {ok: true, sessionEpoch: rt.sessionEpoch, record: existing};
        }
        return {
            ok: false,
            status: existing.completed === true ? "duplicate_completed" :
                (_mcpOwn(rt.activeJobs, jobId) ? "duplicate_running" : "duplicate_unknown"),
            message: existing.completed === true ?
                "Job already completed in this runtime: " + jobId :
                (_mcpOwn(rt.activeJobs, jobId) ?
                    "Job is already open in this runtime: " + jobId :
                    "Job has no completed finalizer in this runtime: " + jobId),
            sessionEpoch: rt.sessionEpoch,
            record: existing
        };
    }

    if (spec.phase && spec.phase !== 1) {
        return {ok: false, status: "missing_phase_history", message: "Runtime reset or phase history expired; do not resume automatically"};
    }
    var startedAt = new Date().getTime();
    var record = {
        jobId: jobId,
        digest: digest,
        sessionEpoch: rt.sessionEpoch,
        status: "running",
        completed: false,
        startedAt: startedAt,
        completedAt: null,
        durationMs: null,
        context: spec.context || {},
        effects: _mcpEmptyEffects(),
        errors: [],
        result: null
    };
    rt.jobRecords[jobId] = record;
    rt.jobOrder.push(jobId);
    rt.activeJobs[jobId] = { startedAt: startedAt, digest: digest };
    return {
        ok: true,
        sessionEpoch: rt.sessionEpoch,
        activeJobs: _mcpCountKeys(rt.activeJobs),
        record: record
    };
}

/**
 * Finalise a managed job and retain its truthful outcome for reconciliation.
 * Whole-job outcomes use completed:true; internal phase outcomes remain
 * completed:false because the logical job includes later Python/host work.
 */
function mcpRuntimeCompleteWork(jobId, outcome) {
    var rt = _mcpRuntime();
    if (!rt) return { ok: false, status: "absent", message: "Runtime not installed" };
    if (!_mcpValidJobId(jobId)) {
        return { ok: false, status: "invalid", message: "A valid jobId is required" };
    }
    _mcpPruneJobRecords(rt);
    var active = _mcpOwn(rt.activeJobs, jobId) ? rt.activeJobs[jobId] : null;
    var record = _mcpOwn(rt.jobRecords, jobId) ? rt.jobRecords[jobId] : null;
    if (!active || !record) {
        if (record && record.completed === true) {
            return { ok: true, status: "already_completed", record: record };
        }
        return {
            ok: false, status: "unknown_job",
            message: "Job has no active host record: " + jobId,
            sessionEpoch: rt.sessionEpoch
        };
    }

    outcome = outcome || {};
    var status = outcome.status;
    if (status !== "succeeded" && status !== "failed" && status !== "partial") {
        status = "unknown";
    }
    var completedAt = new Date().getTime();
    record.status = status;
    record.completed = !outcome.phase;
    record.completedAt = completedAt;
    record.durationMs = completedAt - record.startedAt;
    record.effects = _mcpCopyEffects(outcome.effects);
    record.errors = _mcpCopyList(outcome.errors);
    record.result = typeof outcome.result === "undefined" ? null : outcome.result;
    if (outcome.context) record.context = outcome.context;
    if (outcome.phase) {
        // The finalizer proves this host phase only. Python postprocessing and
        // subsequent host phases have not completed merely because it ran.
        record.status = "unknown";
        record.effects.complete = false;
        record.context.nextPhase = outcome.phase + 1;
        record.context.lastPhase = {index: outcome.phase, name: outcome.phaseName,
            status: status, finalized: true};
    }
    delete rt.activeJobs[jobId];
    _mcpPruneJobRecords(rt);
    return {
        ok: true, status: "completed", sessionEpoch: rt.sessionEpoch,
        activeJobs: _mcpCountKeys(rt.activeJobs), record: record
    };
}

/** Read a retained host outcome without replaying the job. */
function mcpRuntimeJobStatus(jobId) {
    var rt = _mcpRuntime();
    if (!rt) {
        return {
            ok: false, status: "unknown", reason: "runtime_absent",
            message: "The host runtime was reset or has not been initialised."
        };
    }
    if (!_mcpValidJobId(jobId)) {
        return { ok: false, status: "invalid", message: "A valid jobId is required" };
    }
    _mcpPruneJobRecords(rt);
    var record = _mcpOwn(rt.jobRecords, jobId) ? rt.jobRecords[jobId] : null;
    if (!record) {
        return {
            ok: false, status: "unknown", reason: "expired_or_never_submitted",
            message: "No retained host record exists. It may have expired or the job may never have reached this runtime.",
            sessionEpoch: rt.sessionEpoch
        };
    }
    return {
        ok: true,
        status: record.completed === true ? "completed" :
            (_mcpOwn(rt.activeJobs, jobId) ? "running" : "unknown"),
        sessionEpoch: rt.sessionEpoch,
        record: record
    };
}

/**
 * Mark a job as finished.
 *
 * Returns ok:false with status "unknown_job" when the job was not open —
 * which is itself information (the runtime may have been reinitialised under
 * it). It is never treated as success.
 *
 * @param {string} jobId
 * @returns {Object} {ok, status, durationMs, sessionEpoch, activeJobs}
 */
function mcpRuntimeEndWork(jobId) {
    var rt = _mcpRuntime();
    if (!rt) {
        return { ok: false, status: "absent", message: "Runtime not installed" };
    }
    var entry = _mcpOwn(rt.activeJobs, jobId) ? rt.activeJobs[jobId] : null;
    if (!entry) {
        return {
            ok: false, status: "unknown_job",
            message: "Job was not open in this runtime: " + jobId,
            sessionEpoch: rt.sessionEpoch
        };
    }
    delete rt.activeJobs[jobId];
    // Closing without mcpRuntimeCompleteWork is deliberately UNKNOWN. This
    // compatibility path must never manufacture a successful completion.
    var record = _mcpOwn(rt.jobRecords, jobId) ? rt.jobRecords[jobId] : null;
    if (record && record.completed !== true) {
        record.status = "unknown";
        record.completedAt = new Date().getTime();
        record.durationMs = record.completedAt - record.startedAt;
        record.errors = [{ message: "Host work marker closed without a completion outcome" }];
    }
    return {
        ok: true,
        status: "closed",
        durationMs: new Date().getTime() - entry.startedAt,
        sessionEpoch: rt.sessionEpoch,
        activeJobs: _mcpCountKeys(rt.activeJobs)
    };
}

/**
 * Tear the runtime down. Rotates identity by removing it entirely, so the next
 * handshake reports "absent" rather than a stale-but-plausible runtime.
 *
 * Returns the job IDs that were still open. They are UNKNOWN, not unapplied.
 *
 * @returns {Object} {ok, previousEpoch, displacedJobIds}
 */
function mcpRuntimeReset() {
    var rt = _mcpRuntime();
    var previousEpoch = rt ? (rt.sessionEpoch || null) : null;
    var displaced = rt ? _mcpKeys(rt.activeJobs || {}) : [];
    if (typeof mcpHandleInvalidateAll === "function") {
        mcpHandleInvalidateAll("host_runtime_reset");
    }
    $.global[MCP_RUNTIME_KEY] = null;
    return {
        ok: true,
        previousEpoch: previousEpoch,
        displacedJobIds: displaced
    };
}

// ==================== Exports ====================

if (typeof $.global !== "undefined") {
    $.global.mcpRuntimeState = mcpRuntimeState;
    $.global.mcpRuntimeInit = mcpRuntimeInit;
    $.global.mcpRuntimeHandshake = mcpRuntimeHandshake;
    $.global.mcpRuntimeBeginWork = mcpRuntimeBeginWork;
    $.global.mcpRuntimeCompleteWork = mcpRuntimeCompleteWork;
    $.global.mcpRuntimeJobStatus = mcpRuntimeJobStatus;
    $.global.mcpRuntimeEndWork = mcpRuntimeEndWork;
    $.global.mcpRuntimeReset = mcpRuntimeReset;
    $.global.MCP_BOOTSTRAP_VERSION = MCP_BOOTSTRAP_VERSION;
}
