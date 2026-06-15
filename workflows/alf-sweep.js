// WORKFLOW: alf-sweep v1.0.0
// OWNER: alf
// PROVENANCE: hand-authored, reviewed, committed — never agent-emitted (S052)
// FALLBACK: alf_sweep_launcher.sh --inline mode (direct sweep, no workflow)
// MIN-CLAUDE: 2.1.154
// NESTING: none
// PROHIBITED: any write under .alf/ from a stage (main loop is the single .alf/ writer); an apply stage (D1 — no apply exists in this workflow ever); the signing-key string in any prompt
//
// S055 §5.4 — ONE parameterized sweep workflow for all tiers
// (version/freshness/flow-pulse/full/flow-review). Feed refresh stays OUTSIDE
// (launcher-side feed freeze): the launcher writes the args file with per-target
// feed excerpts + feed sha256 hashes that ride inside every finder prompt
// (changed feed => changed prompt => cache miss). Finder stages emit
// alf-finding-batch.v1 (ZERO .alf/ writes); the verify arm is a cold-context
// cite-check; synthesize is a PURE JS reduce (NOT an LLM stage).
//
// SCHEMA-TWIN: alf-finding-batch.v1 sha256:0c3129d1242a6493
// SCHEMA-TWIN: alf-verify.v1 sha256:1675f00e2fc94159
// SCHEMA-TWIN: alf-sweep-summary.v1 sha256:25222ffd8a2806c7

export const meta = {
  name: "alf-sweep",
  version: "1.0.0",
  description:
    "owner:alf — one parameterized read-only sweep (version/freshness/" +
    "flow-pulse/full/flow-review); finders emit batches, ZERO .alf/ writes; " +
    "synthesize is a pure JS reduce; the main loop is the single .alf/ writer.",
};

const FINDING_BATCH_SCHEMA = {
  type: "object",
  required: ["target", "lens", "findings", "skipped", "limits"],
  properties: {
    target: { type: "object" },
    lens: { type: "string" },
    findings: { type: "array" },
    handoff_requests: { type: "array" },
    skipped: { type: "array" },
    limits: { type: "object" },
  },
};

const VERIFY_SCHEMA = {
  type: "object",
  required: ["finding_ref", "verdict"],
  properties: {
    finding_ref: { type: "string" },
    verdict: { enum: ["VERIFIED", "FALSE_POSITIVE", "NEEDS_FOLLOWUP"] },
    false_positive_reason: { type: ["string", "null"] },
    cited_evidence_verbatim: { type: ["string", "null"] },
  },
};

// Pure priority recompute (mirror of _meta/sweep_scope.priority_score).
function priorityScore(i, e, c, u, eff) {
  const d = eff && eff > 0 ? eff : 1;
  return Math.round(((i * e * c * u) / d) * 10000) / 10000;
}

function normTitle(t) {
  return (t || "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
}

export default async function alfSweep({ args, agent, pipeline, parallel, budget }) {
  // The launcher resolved tier->scope and wrote targets + feed excerpts + feed
  // sha256 hashes into the args file (via _meta/sweep_scope.py). The workflow
  // consumes them; it NEVER refreshes feeds or resolves scope itself.
  const tier = args.tier;
  const targets = args.targets || [];
  const finderModel = args.finder_model || "sonnet";
  const verifyArm = args.verify_arm || "external-only";

  // ── plan (pure JS validate) ──
  if (targets.length === 0) {
    return { sweep_id: args.sweep_id, tier, findings: [], skipped: ["no targets in scope"] };
  }

  // ── find+verify (pipeline: finder -> verifier for critical/external) ──
  const budgetOk = !budget || !budget.total ? true : budget.total > 0;

  async function finder(target) {
    if (!budgetOk) {
      // budget shed = synthetic empty batch with skipped[]
      return { target, lens: "all", findings: [], skipped: ["budget shed"], limits: { budget: "exhausted" } };
    }
    return agent(
      `ALF_FORMAT: 5\ntier: ${tier}\ntarget: ${JSON.stringify(target)}\n` +
        `feed_excerpts: ${JSON.stringify(args.feed_excerpts ? args.feed_excerpts[target.path] || {} : {})}\n` +
        `feed_sha256: ${JSON.stringify(args.feed_sha256 ? args.feed_sha256[target.path] || {} : {})}\n` +
        "Apply the 7 lenses. Output is alf-finding-batch.v1 ONLY. Write NOTHING " +
        "under .alf/. Out-of-scope HIGH findings => handoff_requests[] data. " +
        "Cite feed_record or local evidence per finding (HR6). Budget honesty: " +
        "skipped[] + limits.",
      { agentType: "alf", schema: FINDING_BATCH_SCHEMA, model: finderModel },
    );
  }

  async function verifier(batch) {
    // Cold-context cite-check for critical / external-evidence findings,
    // mechanizing the Stage-1.5 firewall. The arm is tier-controlled.
    if (verifyArm === "on-breach") return [];
    const toVerify = (batch.findings || []).filter((f) =>
      f.severity === "CRITICAL" ||
      (f.evidence && f.evidence.feed_record) ||
      verifyArm === "all-critical",
    );
    // S059 smart-config (NORMATIVE §7): the verify arm gains an optional model. The
    // launcher resolves verifier_model caller-side (alf_sweep_launcher.sh) and writes
    // it into args; undefined => model is undefined => inherit (byte-identical to today).
    const stages = toVerify.map((f) =>
      agent(
        "Cold-context cite-check: confirm this finding's cited evidence is real. " +
          `finding=${JSON.stringify({ target: batch.target.path, lens: batch.lens, title: f.title })} ` +
          `evidence=${JSON.stringify(f.evidence)}`,
        { agentType: "alf", schema: VERIFY_SCHEMA, model: args.verifier_model },
      ),
    );
    return parallel(stages);
  }

  const batches = await pipeline(targets, finder, verifier);

  // ── synthesize (PURE JS reduce — NOT an LLM stage) ──
  // apply verdicts, recompute every priority_score, dedupe keep-max, stable sort.
  const flat = [];
  const skipped = [];
  for (const entry of batches) {
    const batch = entry.output || entry; // pipeline shape: {output, verifications}
    const verifications = entry.verifications || [];
    const verdictByRef = {};
    for (const v of verifications) {
      if (v) verdictByRef[v.finding_ref] = v.verdict;
    }
    for (const s of batch.skipped || []) skipped.push(s);
    for (const f of batch.findings || []) {
      const ref = `${batch.target.path}|${batch.lens}|${normTitle(f.title)}`;
      // Recompute priority from numeric inputs when present (never trust finder score).
      const inp = f.priority_inputs || {};
      const score =
        inp.impact != null
          ? priorityScore(inp.impact, inp.exposure || 1, inp.confidence || 0.75, inp.urgency || 1, inp.effort || 1)
          : f.priority_score || 0;
      flat.push({
        target_path: batch.target.path,
        lens: batch.lens,
        title: f.title,
        severity: f.severity,
        priority_score: score,
        verdict: verdictByRef[ref] || "UNVERIFIED",
      });
    }
  }

  // dedupe (target.path, lens, normalized-title) keep-max + stable sort.
  const best = new Map();
  for (const f of flat) {
    const key = `${f.target_path}|${f.lens}|${normTitle(f.title)}`;
    const cur = best.get(key);
    if (!cur || f.priority_score > cur.priority_score) best.set(key, f);
  }
  const findings = Array.from(best.values()).sort(
    (a, b) =>
      b.priority_score - a.priority_score ||
      String(a.target_path).localeCompare(String(b.target_path)) ||
      String(a.lens).localeCompare(String(b.lens)) ||
      normTitle(a.title).localeCompare(normTitle(b.title)),
  );

  return {
    sweep_id: args.sweep_id,
    tier,
    trigger_event: args.trigger_event || null,
    detection_feeds: args.detection_feeds || [],
    findings,
    skipped,
    tokens_spent: null,
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
