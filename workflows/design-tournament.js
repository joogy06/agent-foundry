// WORKFLOW: design-tournament v1.0.0
// OWNER: forge
// PROVENANCE: hand-authored, reviewed, committed — never agent-emitted (S052)
// FALLBACK: forge SKILL.md "Step 6B design exploration team (portable, canonical)"
// MIN-CLAUDE: 2.1.154
// NESTING: none
// PROHIBITED: shedding the Claude challenger or UX-when-ui_facing; removing entries from unresolved[]; the signing-key string in any prompt (W-KEY)
//
// S055 §5.1 — forge design exploration as parallel fan-out/fan-in. The converge
// script computes the disagreement matrix as a PURE FUNCTION of the verdict
// objects (the synthesis agent can never launder a disagreement away); the
// script may ADD to unresolved[], never remove. The converge DECISION stays
// inline in forge (this workflow returns a DRAFT + matrix; forge presents
// section-by-section). External challengers ride the W-EXT envelope with
// args-supplied command lines (W-EXT command custody). Per the WP-2 live
// experiment, agy is UNREACHABLE from workflow stages — external challenger
// transcripts are PRE-LAUNCHED inline by forge and passed via args; a stage that
// must call an external CLI uses the args-supplied transcript, not a live call.
//
// SCHEMA-TWIN: approach-output.v1 sha256:fa8e5055c201b1bc
// SCHEMA-TWIN: ux-review.v1 sha256:881da62ec03b390c
// SCHEMA-TWIN: challenger-verdict.v1 sha256:8bbd9ef70365d7e7
// SCHEMA-TWIN: external-challenger-verdict.v1 sha256:579521782a412e75
// SCHEMA-TWIN: design-synthesis.v1 sha256:823643ef2d3ee0f1

export const meta = {
  name: "design-tournament",
  version: "1.0.0",
  description:
    "owner:forge — parallel approach/challenge/converge design exploration; script computes the disagreement matrix; converge DECISION stays inline in forge.",
};

const APPROACH_SCHEMA = {
  type: "object",
  required: ["approach_id", "title", "summary", "key_decisions", "tradeoffs"],
  properties: {
    approach_id: { type: "string" },
    title: { type: "string" },
    summary: { type: "string" },
    key_decisions: { type: "array" },
    tradeoffs: { type: "array" },
    risks: { type: "array" },
    estimated_complexity: { enum: ["S", "M", "L", "XL"] },
    ui_facing: { type: "boolean" },
  },
};

const CHALLENGER_SCHEMA = {
  type: "object",
  required: ["verdict", "findings"],
  properties: {
    verdict: { enum: ["ACCEPTABLE", "ACCEPTABLE_WITH_FIXES", "REJECT"] },
    findings: { type: "array" },
    targets_approach: { type: ["string", "null"] },
  },
};

const SYNTHESIS_SCHEMA = {
  type: "object",
  required: ["chosen_direction", "disagreement_matrix", "unresolved", "status"],
  properties: {
    chosen_direction: { type: "string" },
    rationale: { type: "string" },
    incorporated_from: { type: "array" },
    disagreement_matrix: { type: "array" },
    unresolved: { type: "array" },
    status: { enum: ["DRAFT", "INCOMPLETE"] },
  },
};

// PURE function: derive the disagreement matrix from the verdict objects.
// (The synthesis agent never sees a chance to drop a disagreement.)
function computeDisagreementMatrix(challengerVerdicts) {
  const rows = [];
  for (const cv of challengerVerdicts) {
    if (!cv) continue;
    const body = cv.verdict_body || cv; // external wraps in verdict_body
    const source = cv.served_by ? `external:${cv.served_by}` : "claude-challenger";
    for (const f of body.findings || []) {
      if (f.severity === "CRITICAL" || f.severity === "MAJOR" || f.mandatory) {
        rows.push({ source, claim: f.claim, resolved: false });
      }
    }
  }
  return rows;
}

// ── Script body (top-level — current Workflow surface: `args`/`agent`/`parallel`/
// `pipeline`/`budget`/`log`/`phase` are runtime globals. Converted 2026-07-10 from the
// original `export default` wrapper, which the runtime REJECTS at load
// (SyntaxError: Unexpected keyword 'export' — verified live 2026-07-10, zero-agent probe;
// same adaptation as bob-serial-exec.js, 2026-06-11). Body logic unchanged. ──

{
  // Harness compatibility: `args` may arrive as a JSON string — normalize before
  // any binding is read (bob-serial-exec.js precedent, run wf_64b5c70e-75a).
  const ARGS = typeof args === "string" ? JSON.parse(args) : (args || {});
  // ── prepare (pure JS) ──
  const approaches = Array.isArray(ARGS.approaches) ? ARGS.approaches : [];
  if (approaches.length < 2 || approaches.length > 5) {
    return { status: "INCOMPLETE", reason: "approaches must be 2..5", unresolved: [] };
  }

  // Budget floor: must cover >=2 approaches + 1 challenger + synthesis.
  const haveBudget = !budget || !budget.total ? true : budget.total > 0;

  // ── diverge (ONE parallel() barrier) ──
  const approachStages = approaches.map((a) =>
    agent(
      `Produce an approach-output.v1 for approach '${a.id || a}'. Brief at ${ARGS.brief_path} ` +
        `(sha256 ${ARGS.brief_sha256}). Shared context at ${ARGS.shared_context_path} ` +
        `(sha256 ${ARGS.shared_context_sha256}).`,
      { agentType: "claude", schema: APPROACH_SCHEMA },
    ),
  );
  if (ARGS.ui_facing) {
    approachStages.push(
      agent(
        `Produce a ux-review.v1 for the UI-facing aspects of the brief at ${ARGS.brief_path}.`,
        { agentType: "multi-platform-apps:ui-ux-designer" },
      ),
    );
  }
  const divergeResults = await parallel(approachStages);

  // ── challenge (parallel: Claude challenger + external W-EXT wrappers) ──
  const challengeStages = [
    agent(
      `Challenge the approaches. Emit a challenger-verdict.v1. Brief sha256 ${ARGS.brief_sha256}.`,
      { agentType: "claude", schema: CHALLENGER_SCHEMA },
    ),
  ];
  // External challengers: forge PRE-LAUNCHED these (agy unreachable from stages,
  // WP-2 finding 6). The transcripts arrive via ARGS.external_transcripts; the
  // stage only EXTRACTS the verdict from the supplied transcript and wraps it in
  // the W-EXT envelope — it never makes a live external call.
  for (const ext of ARGS.external_transcripts || []) {
    challengeStages.push(
      agent(
        "You are a TRANSCRIPTION WRAPPER, not a reviewer. Extract the verdict from " +
          `this pre-launched transcript and emit an external-challenger-verdict.v1 ` +
          `with invocation, raw_transcript, transcript_sha256, served_by, absence. ` +
          `Transcript: <<<${ext.raw_transcript}>>> served_by=${ext.served_by} ` +
          `command=${ext.command} exit_code=${ext.exit_code}`,
        { agentType: "claude" },
      ),
    );
  }
  const challengeResults = await parallel(challengeStages);

  // ── converge (script computes the matrix; synthesis stage is judgment-limited) ──
  const matrix = computeDisagreementMatrix(challengeResults);
  const synthesis = await agent(
    "Emit a design-synthesis.v1 DRAFT. You MAY choose a direction and rationale, " +
      "but you receive the disagreement_matrix as FIXED input — copy it through " +
      "unchanged and you may only ADD to unresolved[], never remove. " +
      `Approaches: ${JSON.stringify(divergeResults)}. ` +
      `Disagreement matrix (FIXED): ${JSON.stringify(matrix)}.`,
    { agentType: "claude", schema: SYNTHESIS_SCHEMA },
  );

  // Script guard: matrix is authoritative; unresolved CRITICAL disagreements
  // the synthesis tried to drop are re-added (never removed).
  const unresolved = new Set(synthesis ? synthesis.unresolved || [] : []);
  for (const row of matrix) {
    if (!row.resolved) unresolved.add(row.claim);
  }

  // Budget floor: if we could not cover >=2 approaches + 1 challenger + synthesis,
  // the tournament looks UNFINISHED, not polished.
  const status = haveBudget && divergeResults.length >= 2 ? (synthesis ? synthesis.status : "DRAFT") : "INCOMPLETE";

  return {
    status: status === "INCOMPLETE" ? "INCOMPLETE" : "DRAFT",
    chosen_direction: synthesis ? synthesis.chosen_direction : null,
    rationale: synthesis ? synthesis.rationale : null,
    disagreement_matrix: matrix, // script-authoritative
    unresolved: Array.from(unresolved),
    approaches: divergeResults,
  };
}

/* <!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: claude-code-workflow-surface
    verified_against: "2.1.173 (workflow API; layout frozen WP-2 forge #159)"
    verified_on: "2026-06-11"
    volatility: high
  - kind: tool_version
    subject: codex-cli
    verified_against: "0.139.0 (external-challenger transcripts pre-launched by forge)"
    verified_on: "2026-06-11"
    volatility: high
  - kind: tool_version
    subject: antigravity-cli
    verified_against: "1.0.7 (UNREACHABLE from workflow stages — pre-launched inline, WP-2 finding 6)"
    verified_on: "2026-06-11"
    volatility: high
--> */
