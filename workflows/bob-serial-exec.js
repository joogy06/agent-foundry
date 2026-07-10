// WORKFLOW: bob-serial-exec v1.0.0
// OWNER: bob
// PROVENANCE: hand-authored, reviewed, committed — never agent-emitted (S052)
// FALLBACK: bob.md HARD-RULE 1 item 3 (serial bob runs with .bob-checkpoint.md)
// MIN-CLAUDE: 2.1.154
// NESTING: none
// PROHIBITED: parallel() over agentType:'bob' stages (CB4 single-writer); isolation:'worktree' on any stage in this file
//
// S055 §5.3 — the STRICTLY SERIAL bob executor. One bob stage per WP, in
// topological plan order, awaited one-by-one. Bob is the single writer of
// progress/integration-ledger.md, .ledger/**, and .bob-checkpoint.md (CB4), so
// parallel() over bob stages is EXPLICITLY PROHIBITED and bob stages NEVER run
// under worktree isolation (pipeline machinery is canonical-tree only).
//
// Resume bindings (challenger fix #3): plan_hash + ledger_state_version +
// map_sig_sha256 are embedded in EVERY stage's agent() input and recomputed by
// the CALLER at every invocation INCLUDING resumes — moved ledger/map state =>
// changed stage args => surgical cache miss => resume across an amendment is
// structurally impossible.
//
// SCHEMA-TWIN: work-packages.v1 sha256:f685a6911d691f48
// SCHEMA-TWIN: plan-load.v1 sha256:1e7fc64c4b9f9c92
// SCHEMA-TWIN: execution-report.v1 sha256:90dda7579ac3f564

export const meta = {
  name: "bob-serial-exec",
  version: "1.0.0",
  description:
    "owner:bob — STRICTLY SERIAL bob executor; one mode:execute-work-package stage per WP in plan order; parallel()/worktree PROHIBITED (CB4).",
};

// Plan-load stage schema twin (subset — the script reads wp_order + hash_ok).
const PLAN_LOAD_SCHEMA = {
  type: "object",
  required: ["schema_version", "plan_id", "plan_hash", "hash_ok", "wp_order"],
  properties: {
    schema_version: { const: "plan-load.v1" },
    plan_id: { type: "string" },
    plan_hash: { type: "string" },
    hash_ok: { type: "boolean" },
    wp_order: { type: "array", items: { type: "string" } },
    cycles_detected: { type: "array" },
    validation_errors: { type: "array" },
  },
};

// Execution-report stage schema twin (the canonical bob report shape).
const EXECUTION_REPORT_SCHEMA = {
  type: "object",
  required: ["status", "built", "files_changed", "verification"],
  properties: {
    status: { enum: ["COMPLETE", "PARTIAL", "FAILED"] },
    wp_id: { type: ["string", "null"] },
    built: { type: "array" },
    files_changed: { type: "array" },
    verification: { type: "object" },
    needs: { type: ["object", "null"] },
    known_issues: { type: "array" },
    how_to_verify: { type: "array" },
  },
};

// Build the immutable resume-binding block stamped into EVERY bob stage. The
// CALLER passes these in args (recomputed per invocation, incl. resumes).
function resumeBindings(args) {
  return {
    plan_hash: args.plan_hash,
    plan_revision: args.plan_revision,
    ledger_state_version: args.ledger_state_version,
    map_sig_sha256: args.map_sig_sha256, // literal "N/A" for N/A cycles
    run_label: args.run_label,
  };
}

function bobStagePrompt(mode, wpId, args) {
  const b = resumeBindings(args);
  return [
    `BOB_MODE: ${mode}`,
    wpId ? `wp_id: ${wpId}` : null,
    `project_root: ${args.project_root}`,
    `plan_path: ${args.plan_path}`,
    `plan_hash: ${b.plan_hash}`,
    `plan_revision: ${b.plan_revision}`,
    `ledger_state_version: ${b.ledger_state_version}`,
    `map_sig_sha256: ${b.map_sig_sha256}`,
    `run_label: ${b.run_label}`,
    `run_started_at: ${args.run_started_at}`,
    "",
    "You are a TERMINAL bob stage persona (bob.md 'Workflow-stage modes'). " +
      "The named BOB_MODE OVERRIDES Steps 1-3 and HARD-RULE 1 items 1-4. " +
      "Validate the run lease on every mutation. The ledger on disk outranks " +
      "the journal. Emit the schema-mapped execution-report.v1. Do NOT " +
      "orchestrate, decompose, or expand scope beyond this WP.",
  ]
    .filter((x) => x !== null)
    .join("\n");
}

// ── Script body (top-level — current Workflow surface; `args`/`agent` are
// runtime globals. Adapted 2026-06-11 from the original `export default`
// wrapper, which the current runtime rejects. Body logic unchanged.) ──

{
  // Harness compatibility: the Workflow `args` input may arrive as a JSON
  // string rather than an object — normalize before any binding is read
  // (observed live 2026-06-11, run wf_64b5c70e-75a: every binding rendered
  // "undefined" in the stage prompt).
  const ARGS = typeof args === "string" ? JSON.parse(args) : (args || {});

  // ── Phase plan-load (read-only validation; returns topological wp_order) ──
  const loadReport = await agent(
    [
      "BOB_MODE: execute-work-package (plan-load preflight)",
      `project_root: ${ARGS.project_root}`,
      `plan_path: ${ARGS.plan_path}`,
      `plan_hash: ${ARGS.plan_hash}`,
      "",
      "Read the work-packages.v1 plan at plan_path. Verify " +
        "sha256(plan)==plan_hash. Return a plan-load.v1 object with a " +
        "topologically-sorted wp_order (dependency order). Do NOT execute any WP.",
    ].join("\n"),
    // S059 smart-config (NORMATIVE §7, DORMANT): undefined ARGS.models => model is
    // undefined => byte-identical to today (inherit). Per-WP grade-driven dispatch
    // (ARGS.models populated from WP S/M/L) is v1.1; the in-flight AMY run is NOT
    // resumed from this edited script.
    { agentType: "bob", schema: PLAN_LOAD_SCHEMA, model: ARGS.models && ARGS.models.bob },
  );

  if (!loadReport || loadReport.hash_ok === false) {
    return {
      status: "PARTIAL",
      needs: { kind: "plan-recompile", payload: { reason: "plan hash mismatch at load" } },
      built: [],
      files_changed: [],
      verification: { plan_load: "hash mismatch" },
    };
  }

  const wpOrder = loadReport.wp_order || [];
  const reports = [];

  // ── Phase execute — STRICTLY SERIAL, one WP per stage, awaited one-by-one ──
  // parallel() over these stages is EXPLICITLY PROHIBITED (CB4 single-writer).
  for (const wpId of wpOrder) {
    const report = await agent(bobStagePrompt("execute-work-package", wpId, ARGS), {
      agentType: "bob",
      schema: EXECUTION_REPORT_SCHEMA,
      // S059 (NORMATIVE §7, DORMANT): undefined ARGS.models => inherit, unchanged.
      model: ARGS.models && ARGS.models.bob,
    });
    reports.push({ wp_id: wpId, report });

    // First non-COMPLETE breaks the loop and surfaces the needs block.
    if (!report || report.status !== "COMPLETE") {
      return {
        status: report ? report.status : "FAILED",
        built: reports.flatMap((r) => (r.report && r.report.built) || []),
        files_changed: reports.flatMap((r) => (r.report && r.report.files_changed) || []),
        verification: { executed_wps: reports.map((r) => r.wp_id) },
        needs: (report && report.needs) || { kind: "user-decision", payload: { failed_wp: wpId } },
        known_issues: (report && report.known_issues) || [],
      };
    }
  }

  // ── Phase finalize — one bob stage in mode: finalize ──
  const finalize = await agent(bobStagePrompt("finalize", null, ARGS), {
    agentType: "bob",
    schema: EXECUTION_REPORT_SCHEMA,
    // S059 (NORMATIVE §7, DORMANT): undefined ARGS.models => inherit, unchanged.
    model: ARGS.models && ARGS.models.bob,
  });

  return {
    status: (finalize && finalize.status) || "COMPLETE",
    built: reports.flatMap((r) => r.report.built || []),
    files_changed: reports.flatMap((r) => r.report.files_changed || []),
    verification: (finalize && finalize.verification) || { finalized: true },
    needs: (finalize && finalize.needs) || null,
    how_to_verify: (finalize && finalize.how_to_verify) || [],
  };
}

/* <!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: claude-code-workflow-surface
    verified_against: "2.1.201 (workflow API: bare-body + pure-literal meta enforced at load; live probe)"
    verified_on: "2026-07-10"
    volatility: high
--> */
