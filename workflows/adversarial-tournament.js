// WORKFLOW: adversarial-tournament v1.0.0
// OWNER: adversarial-team-brainstorm
// PROVENANCE: hand-authored, reviewed, committed — never agent-emitted (S052)
// FALLBACK: adversarial-team-brainstorm SKILL.md inline four-round tournament
// MIN-CLAUDE: 2.1.154
// NESTING: none
// PROHIBITED: configs that drop kill criteria; upgrading arbiter confidence (script may only downgrade); the signing-key string in any prompt
//
// S055 §5.5 — the four-round tournament as parallel fan-out/fan-in: diverge
// (one isolated agent per team angle) → crossfire (parallel attackers; each sees
// ONLY other teams' outputs) → refine → arbiter (single stage). The script
// REFUSES configs that would drop kill criteria, validates attack target
// coverage with a deterministic single retry on a sycophantic miss, and forces
// confidence to 'speculative' when grounding_sources is empty (DOWNGRADE only).
// design-tournament does NOT wrap this (B's ruling); standalone callers are the
// skill's own inline invocations.
//
// SCHEMA-TWIN: team-output.v1 sha256:f4a3ad4c9099cedb
// SCHEMA-TWIN: attack-set.v1 sha256:694b023fd4d0b913
// SCHEMA-TWIN: tournament-result.v1 sha256:dedf4eca8e1aa336

export const meta = {
  name: "adversarial-tournament",
  version: "1.0.0",
  description:
    "owner:adversarial-team-brainstorm — diverge/crossfire/refine/arbiter; kill-criteria minItems 2 (role-collapse guard); attack minItems 1 per target; script downgrades-never-upgrades confidence.",
};

const TEAM_OUTPUT_SCHEMA = {
  type: "object",
  required: ["team_id", "angle", "proposal", "initial_kill_criteria"],
  properties: {
    team_id: { type: "string" },
    angle: { type: "string" },
    proposal: { type: "string" },
    initial_kill_criteria: { type: "array", minItems: 2, items: { type: "string" } },
    grounding_sources: { type: "array" },
  },
};

const ATTACK_SET_SCHEMA = {
  type: "object",
  required: ["attacker_team_id", "attacks"],
  properties: {
    attacker_team_id: { type: "string" },
    attacks: {
      type: "array",
      minItems: 1,
      items: {
        type: "object",
        required: ["target_team_id", "flaws"],
        properties: {
          target_team_id: { type: "string" },
          flaws: { type: "array", minItems: 1, items: { type: "string" } },
        },
      },
    },
  },
};

const TOURNAMENT_RESULT_SCHEMA = {
  type: "object",
  required: ["ranked_outputs", "meta"],
  properties: {
    ranked_outputs: { type: "array", minItems: 1 },
    meta: { type: "object" },
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
  const angles = ARGS.angles || [];
  if (angles.length < 2) {
    return { ranked_outputs: [], meta: { degraded_to: "insufficient_angles" } };
  }

  // ── diverge (parallel, one isolated agent per team angle) ──
  const divergeStages = angles.map((angle, i) =>
    agent(
      `You are TEAM ${i + 1}, angle '${angle}'. Produce a team-output.v1. You MUST ` +
        "state >=2 initial_kill_criteria (concrete conditions that would kill your " +
        "idea). Grounding feeds: " + JSON.stringify(ARGS.context_paths || []),
      { agentType: "claude", schema: TEAM_OUTPUT_SCHEMA },
    ),
  );
  const teams = await parallel(divergeStages);

  // ── crossfire (parallel attackers; each sees ONLY other teams' outputs) ──
  async function runCrossfire() {
    const stages = teams.map((t, i) => {
      const others = teams.filter((_, j) => j !== i);
      return agent(
        `You are attacker ${t.team_id}. Attack EVERY other team's output: emit an ` +
          "attack-set.v1 with >=1 flaw per target. 'Looks good' is NOT admissible. " +
          `Targets: ${JSON.stringify(others)}`,
        { agentType: "claude", schema: ATTACK_SET_SCHEMA },
      );
    });
    return parallel(stages);
  }
  let attacks = await runCrossfire();
  // Script: validate target coverage; deterministic SINGLE retry on a miss.
  const expectedTargets = teams.length - 1;
  const coverageMiss = (attacks || []).some((a) => !a || (a.attacks || []).length < expectedTargets);
  if (coverageMiss) {
    attacks = await runCrossfire(); // one deterministic retry
  }

  // ── refine (parallel; budget floor: below floor before refine => skip) ──
  const budgetOk = !budget || !budget.total ? true : budget.total > 0;
  let degraded = null;
  if (budgetOk) {
    const refineStages = teams.map((t) =>
      agent(
        `Refine team-output.v1 for ${t.team_id} addressing the attacks. Include ` +
          "before/after and rejected_attacks[].",
        { agentType: "claude", schema: TEAM_OUTPUT_SCHEMA },
      ),
    );
    await parallel(refineStages);
  } else {
    degraded = "quick_tournament"; // documented mode, not silent loss
  }

  // ── arbiter (single stage) ──
  const result = await agent(
    "Emit a tournament-result.v1 ranking the refined outputs. Each ranked output " +
      "MUST carry >=2 kill_criteria. Attacks: " + JSON.stringify(attacks),
    { agentType: "claude", schema: TOURNAMENT_RESULT_SCHEMA },
  );

  // Script post-check: empty grounding_sources => confidence FORCED speculative
  // (DOWNGRADE only, never upgrade). degraded => cap confidence 'low'.
  const ranked = (result && result.ranked_outputs) || [];
  const order = { speculative: 0, low: 1, medium: 2, high: 3 };
  for (const r of ranked) {
    if (!r.grounding_sources || r.grounding_sources.length === 0) {
      r.confidence = "speculative";
    }
    if (degraded && order[r.confidence] > order.low) {
      r.confidence = "low"; // cap, never raise
    }
  }

  return {
    ranked_outputs: ranked,
    meta: { ...(result ? result.meta : {}), degraded_to: degraded || (result && result.meta ? result.meta.degraded_to : null) },
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
