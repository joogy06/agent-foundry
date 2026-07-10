// WORKFLOW: evo-analyze v1.0.0
// OWNER: evo
// PROVENANCE: hand-authored, reviewed, committed — never agent-emitted (S052)
// FALLBACK: evo.md C2/C3 (direct spawn / INIT→PLANNED→STOP)
// MIN-CLAUDE: 2.1.154
// NESTING: none
// PROHIBITED: attempting consultations from a stage (consult-log.jsonl is main-loop-only); writing .ledger/scope-deltas or the integration ledger (bob-only, CB4); the signing-key string in any prompt
//
// S055 §5.7 — evo modes b/c ANALYSIS as fan-out/fan-in: clone → extract
// (parallel wiring+deps; mode-c HR3 pre-check HALTs NOW on any direct-dep
// gap_kind:'unknown', zero intent spend) → intent (pipeline; intent-extract runs
// UNCHANGED incl. its two_arm_verify.py canonical HR7 arm; the cold-audit stage
// is the FIRST budget shed — shedding forfeits the audit, never HR7 grounding;
// every shed in skipped[] per HR8) → drift (drift-report + intent-map-render
// ≤3 diagrams per HR5). CONSULTED runs in the MAIN LOOP between evo-analyze and
// evo-apply (consult-log.jsonl is never written from a stage).
//
// SCHEMA-TWIN: evo-phase-result.v1 sha256:492bbf14536a361c
// SCHEMA-TWIN: intent-stage.v1 sha256:dabfd48367f6c912
// SCHEMA-TWIN: cold-audit.v1 sha256:203e2a21c9a4156d
// SCHEMA-TWIN: drift-stage.v1 sha256:0d241115a4b710c3

export const meta = {
  name: "evo-analyze",
  version: "1.0.0",
  description:
    "owner:evo — clone/extract/intent/drift analysis for modes b/c; mode-c HR3 pre-check HALTs on unknown dep data; cold-audit is the first budget shed; consultations NEVER run in a stage.",
};

const PHASE_SCHEMA = {
  type: "object",
  required: ["phase", "status"],
  properties: {
    phase: { enum: ["CLONING", "ANALYZED", "INTENT_MAPPED", "DRIFT_SURFACED", "HALTED"] },
    status: { enum: ["OK", "PARTIAL", "HALTED"] },
    status_reason: { type: ["string", "null"] },
    artifacts: { type: "array" },
    skipped: { type: "array" },
    run_id: { type: ["string", "null"] },
  },
};

const INTENT_SCHEMA = {
  type: "object",
  required: ["component_id", "confidence_level"],
  properties: {
    component_id: { type: "string" },
    confidence_level: { enum: ["grounded", "interpretive"] },
    intent_path: { type: ["string", "null"] },
    evidence_edges_resolved: { type: "boolean" },
    skipped: { type: "array" },
  },
};

const COLD_AUDIT_SCHEMA = {
  type: "object",
  required: ["component_id", "audit_status"],
  properties: {
    component_id: { type: "string" },
    audit_status: { enum: ["AUDITED", "SHED", "DISAGREEMENT"] },
    disagreements: { type: "array" },
    skipped: { type: "array" },
  },
};

const DRIFT_SCHEMA = {
  type: "object",
  required: ["drift_report_path", "diagrams"],
  properties: {
    drift_report_path: { type: "string" },
    diagrams: { type: "array", maxItems: 3 },
    skipped: { type: "array" },
  },
};

// ── Script body (top-level — current Workflow surface: `args`/`agent`/`parallel`/
// `pipeline`/`budget`/`log`/`phase` are runtime globals. Converted 2026-07-10 from the
// original `export default` wrapper, which the runtime REJECTS at load
// (SyntaxError: Unexpected keyword 'export' — verified live 2026-07-10, zero-agent probe;
// same adaptation as bob-serial-exec.js, 2026-06-11). Body logic unchanged. ──

{
  // Harness compatibility: `args` may arrive as a JSON string — normalize before
  // any binding is read (bob-serial-exec.js precedent, run wf_64b5c70e-75a).
  const ARGS = typeof args === "string" ? JSON.parse(args) : (args || {});
  const skipped = [];

  // ── clone (evo stage: claim, manifest, HR6 sandbox clone) ──
  const clone = await agent(
    `evo INIT/CLONING for ${ARGS.project_root} mode=${ARGS.mode} run_id=${ARGS.run_id}. ` +
      "Issue a claim, write manifest.yaml phase=CLONING, HR6 sandbox clone " +
      "(0700 under $HOME/.cache/evo/sessions/<run_id>/clone/).",
    { agentType: "claude", schema: PHASE_SCHEMA },
  );
  if (clone && clone.status === "HALTED") return { status: "HALTED", phase: "CLONING", skipped };

  // ── extract (parallel wiring + deps; mode-c HR3 pre-check) ──
  const [wiring, deps] = await parallel([
    agent("Extract static wiring (wiring-extract-static --standalone).", { agentType: "claude", schema: PHASE_SCHEMA }),
    agent("Run dep-currency-check; report any direct-dep gap_kind.", { agentType: "claude", schema: PHASE_SCHEMA }),
  ]);
  // mode-c HR3: any direct-dep gap_kind:'unknown' => HALTED verdict NOW, zero intent spend.
  if (ARGS.mode === "cve-fix" && deps && deps.status_reason && deps.status_reason.includes("gap_kind:unknown")) {
    return {
      status: "HALTED",
      phase: "HALTED",
      status_reason: "EVO_HALT_DEGRADED_DATA (HR3 — direct-dep gap_kind:unknown)",
      skipped,
    };
  }

  // ── intent (pipeline: intent-extract stage -> cold-audit; audit is first shed) ──
  const components = ARGS.components_hint || [];
  const budgetOk = !budget || !budget.total ? true : budget.total > 0;

  async function intentStage(component) {
    return agent(
      `intent-extract (UNCHANGED, incl. two_arm_verify.py canonical HR7 arm) for ${component}.`,
      { agentType: "claude", schema: INTENT_SCHEMA },
    );
  }
  async function coldAudit(intentResult) {
    if (!budgetOk) {
      skipped.push(`cold-audit shed for ${intentResult ? intentResult.component_id : "?"} (HR8 budget)`);
      return { component_id: intentResult ? intentResult.component_id : "?", audit_status: "SHED", disagreements: [], skipped: ["budget"] };
    }
    return agent(
      `Cold-context audit of the intent for ${intentResult ? intentResult.component_id : "?"}. ` +
        "Shedding forfeits the AUDIT, never the HR7 grounding (which already ran in intent-extract).",
      { agentType: "claude", schema: COLD_AUDIT_SCHEMA },
    );
  }
  const intentResults = await pipeline(components, intentStage, coldAudit);

  // ── drift (drift-report + intent-map-render <=3 diagrams per HR5) ──
  const drift = await agent(
    "Produce drift-report + intent-map-render diagrams (<=3 per HR5; function-level rejected).",
    { agentType: "claude", schema: DRIFT_SCHEMA },
  );

  return {
    status: "OK",
    phase: "DRIFT_SURFACED",
    run_id: ARGS.run_id,
    intent: intentResults,
    drift,
    skipped,
  };
}

/* <!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: claude-code-workflow-surface
    verified_against: "2.1.173 (workflow API; layout frozen WP-2 forge #159)"
    verified_on: "2026-06-11"
    volatility: high
--> */
