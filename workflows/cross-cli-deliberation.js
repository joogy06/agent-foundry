// WORKFLOW: cross-cli-deliberation v1.0.0
// OWNER: cross-cli-deliberation
// PROVENANCE: hand-authored, reviewed, committed — never agent-emitted (S052)
// FALLBACK: cross-cli-deliberation SKILL.md inline two-gate protocol
// MIN-CLAUDE: 2.1.154
// NESTING: none
// PROHIBITED: executing tests in any stage (trusted-runner is bob-only, CB3 — return needs_inline_verification); embedding external-CLI command lines (args-supplied only); the signing-key string in any prompt
//
// S055 §5.6 — the two-gate deliberation as fan-out/fan-in. Gate-1 ballot
// wrapper stages are TRANSCRIPTION WRAPPERS (run the args-supplied command, tee,
// extract literal fields, UNPARSEABLE if not verbatim — never reinterpret).
// Per the WP-2 live experiment, agy is UNREACHABLE from workflow stages and
// codex-from-stage is UNTESTED — so consultant transcripts are PRE-LAUNCHED
// inline by the caller and passed via args.consultant_transcripts; a stage only
// EXTRACTS from the supplied transcript. Command custody is args-supplied
// (consultant_cmds) — no command line is embedded here.
//
// SCHEMA-TWIN: ballot.v1 sha256:b1f6b8432ec897a0
// SCHEMA-TWIN: evidence.v1 sha256:8d0ff408dd198b7e
// SCHEMA-TWIN: deliberation-record.v1 sha256:091bf4bb2d848463

export const meta = {
  name: "cross-cli-deliberation",
  version: "1.0.0",
  description:
    "owner:cross-cli-deliberation — two-gate (null-hypothesis ballot + burden of falsification) deliberation; ballots are transcription-wrapped; tests are NEVER executed in a stage (needs_inline_verification).",
};

const BALLOT_SCHEMA = {
  type: "object",
  required: ["consultant", "ballot_body", "invocation", "raw_transcript", "transcript_sha256", "served_by", "absence"],
  properties: {
    consultant: { type: "string" },
    ballot_body: { type: ["object", "null"] },
    invocation: { type: "object" },
    raw_transcript: { type: "string" },
    transcript_path: { type: ["string", "null"] },
    transcript_sha256: { type: "string" },
    served_by: { type: ["string", "null"] },
    absence: { type: "object" },
  },
};

const EVIDENCE_SCHEMA = {
  type: "object",
  required: ["consultant", "evidence_class", "invocation", "raw_transcript", "transcript_sha256", "absence"],
  properties: {
    consultant: { type: "string" },
    evidence_class: { enum: ["reproduction", "constraint_violation", "efficiency_regression"] },
    reproduction_subform: { enum: ["executable_test", "procedural_trace", "failure_mechanics_trace", null] },
    needs_inline_verification: { type: "boolean" },
    constraint_quote: { type: ["string", "null"] },
    constraint_source_path: { type: ["string", "null"] },
    invocation: { type: "object" },
    raw_transcript: { type: "string" },
    transcript_sha256: { type: "string" },
    served_by: { type: ["string", "null"] },
    absence: { type: "object" },
  },
};

const THRESHOLD = 60; // CHANGE_NEEDED confidence threshold to enter Gate 2.

// ── Script body (top-level — current Workflow surface: `args`/`agent`/`parallel`/
// `pipeline`/`budget`/`log`/`phase` are runtime globals. Converted 2026-07-10 from the
// original `export default` wrapper, which the runtime REJECTS at load
// (SyntaxError: Unexpected keyword 'export' — verified live 2026-07-10, zero-agent probe;
// same adaptation as bob-serial-exec.js, 2026-06-11). Body logic unchanged. ──

{
  // Harness compatibility: `args` may arrive as a JSON string — normalize before
  // any binding is read (bob-serial-exec.js precedent, run wf_64b5c70e-75a).
  const ARGS = typeof args === "string" ? JSON.parse(args) : (args || {});
  // ── gate1_ballots (parallel transcription wrappers, one per consultant) ──
  const consultants = ARGS.consultants || [];
  const transcripts = ARGS.consultant_transcripts || {}; // pre-launched inline
  const ballotStages = consultants.map((c) =>
    agent(
      "You are a TRANSCRIPTION WRAPPER, not a reviewer. From this PRE-LAUNCHED " +
        `transcript, extract the literal ballot fields and emit a ballot.v1. If ` +
        `the verdict line is not locatable verbatim, set ballot_body.verdict = ` +
        `'UNPARSEABLE'. NEVER reinterpret. Consultant=${c}. ` +
        `Transcript: <<<${(transcripts[c] || {}).raw_transcript || ""}>>> ` +
        `command=${(transcripts[c] || {}).command || ""} ` +
        `served_by=${(transcripts[c] || {}).served_by || ""}`,
      { agentType: "claude", schema: BALLOT_SCHEMA },
    ),
  );
  const ballots = await parallel(ballotStages);

  // ── gate2_falsification (skip unless a CHANGE_NEEDED ballot >= threshold) ──
  const dissenters = (ballots || []).filter(
    (b) => b && b.ballot_body && b.ballot_body.verdict === "CHANGE_NEEDED" &&
      (b.ballot_body.confidence || 0) >= THRESHOLD,
  );

  const budgetOk = !budget || !budget.total ? true : budget.total > 0;
  const gate2 = { entered: false, reason: null, evidence: [], verification_results: [] };

  if (dissenters.length > 0 && budgetOk) {
    gate2.entered = true;
    const evidenceStages = dissenters.map((b) =>
      agent(
        "Provide ONE admissible evidence package (evidence.v1) for your " +
          "CHANGE_NEEDED ballot. For an executable_test reproduction, set " +
          "needs_inline_verification=true — this workflow NEVER executes tests " +
          "(trusted-runner is bob-only, CB3). From your pre-launched transcript: " +
          `<<<${(transcripts[b.consultant] || {}).raw_transcript || ""}>>>`,
        { agentType: "claude", schema: EVIDENCE_SCHEMA },
      ),
    );
    gate2.evidence = await parallel(evidenceStages);

    // Mechanical verification: constraint_violation => deterministic grep is a
    // job for the INLINE caller (the workflow only flags it); executable tests
    // => needs_inline_verification. The script classifies, never executes.
    gate2.verification_results = gate2.evidence.map((e) => {
      if (!e) return { consultant: "?", verdict: "NULL_VERDICT" };
      if (e.evidence_class === "reproduction" && e.reproduction_subform === "executable_test") {
        return { consultant: e.consultant, verdict: "NEEDS_INLINE_VERIFICATION" };
      }
      // constraint_violation / procedural traces are handed to the inline caller
      // to grep/check; the workflow marks them pending-inline as well.
      return { consultant: e.consultant, verdict: "NEEDS_INLINE_VERIFICATION" };
    });
  } else if (dissenters.length > 0) {
    gate2.reason = "budget";
  }

  // ── assemble (deterministic bundle) ──
  let outcome = "ACCEPT_AS_IS";
  if (dissenters.length > 0) {
    outcome = gate2.entered ? "ESCALATE" : "ESCALATE"; // inline caller adjudicates
  }

  return {
    schema_version: "deliberation-record.v1",
    ballots: ballots || [],
    gate2,
    outcome,
    nullified_consultants: [],
  };
}

/* <!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: claude-code-workflow-surface
    verified_against: "2.1.201 (workflow API: bare-body + pure-literal meta enforced at load; live probe)"
    verified_on: "2026-07-10"
    volatility: high
  - kind: tool_version
    subject: codex-cli
    verified_against: "0.144.1 (ballots pre-launched inline; codex-from-stage UNTESTED, WP-2)"
    verified_on: "2026-07-10"
    volatility: high
  - kind: tool_version
    subject: antigravity-cli
    verified_against: "1.1.0 (stage reachability UNVERIFIED under corrected flag order — the WP-2 probe used the buggy `agy -p --sandbox` order; pre-launch inline until re-probed)"
    verified_on: "2026-07-10"
    volatility: high
--> */
