// WORKFLOW: evo-apply v1.0.0
// OWNER: evo
// PROVENANCE: hand-authored, reviewed, committed — never agent-emitted (S052)
// FALLBACK: evo.md C2 (direct bob spawn, serial-with-checkpointing)
// MIN-CLAUDE: 2.1.154
// NESTING: none
// PROHIBITED: isolation:'worktree' on the bob stage (bob emits .ledger/requests + heartbeats — canonical tree only); parallel() over bob ever; the signing-key string in any prompt
//
// S055 §5.8 — evo's APPLYING is ONE bob invocation, so this is a single
// agentType:'bob' stage forcing execution-report.v1 (direct, NOT nested through
// bob-serial-exec — nesting would burn the child level for nothing). Args carry
// FULL resume bindings (fix #3 extended): a mutated decision tape
// (consult_log_hash) or moved ledger (ledger_state_version / map_sig_sha256)
// invalidates the cache — a resumed evo-apply with changed decisions re-runs bob
// instead of replaying a stale cached report.
//
// SCHEMA-TWIN: execution-report.v1 sha256:90dda7579ac3f564

export const meta = {
  name: "evo-apply",
  version: "1.0.0",
  description:
    "owner:evo — single bob stage applying the approved evo plan; full resume " +
    "bindings (plan_hash/consult_log_hash/ledger_state_version/map_sig_sha256); " +
    "NO worktree, NO parallel-over-bob.",
};

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

export default async function evoApply({ args, agent }) {
  // Full resume bindings are interpolated into the stage prompt and recomputed
  // by the CALLER at every invocation (incl. resumes): a changed decision tape
  // or moved ledger => changed args => surgical cache miss.
  const prompt = [
    "BOB_MODE: execute-work-package (evo APPLY — single package)",
    `project_root: ${args.project_root}`,
    `plan_path: ${args.plan_path}`,
    `plan_hash: ${args.plan_sha256 || args.plan_hash}`,
    `branch: ${args.branch}`,
    `request_path: ${args.request_path}`,
    `request_sha256: ${args.request_sha256}`,
    `consult_log_path: ${args.consult_log_path}`,
    `consult_log_hash: ${args.consult_log_hash}`,
    `ledger_state_version: ${args.ledger_state_version}`,
    `map_sig_sha256: ${args.map_sig_sha256}`,
    `run_label: ${args.run_label}`,
    `run_started_at: ${args.run_started_at}`,
    "",
    "Apply the approved evo plan as a TERMINAL bob stage. Validate the run lease " +
      "on every mutation. Emit execution-report.v1. The consult-log is the sole " +
      "decision authority (consult_log_hash binds it). Do NOT re-consult, do NOT " +
      "orchestrate.",
  ].join("\n");

  const report = await agent(prompt, { agentType: "bob", schema: EXECUTION_REPORT_SCHEMA });
  return report || { status: "FAILED", built: [], files_changed: [], verification: { evo_apply: "no report" } };
}

/* <!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: claude-code-workflow-surface
    verified_against: "2.1.173 (workflow API; layout frozen WP-2 forge #159)"
    verified_on: "2026-06-11"
    volatility: high
--> */
