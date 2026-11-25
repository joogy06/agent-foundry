// WORKFLOW: bob-serial-exec v1.0.0
// OWNER: bob
// PROVENANCE: hand-authored, reviewed, committed — never agent-emitted (S052)
// FALLBACK: bob.md HARD-RULE 1 item 3 (serial bob runs with .bob-checkpoint.md)
// MIN-CLAUDE: 2.1.154
// NESTING: none
// PROHIBITED: parallel() over agentType:'bob' stages (CB4 single-writer); isolation:'worktree' on any stage in this file
//
// S055 §5.3 — the STRICTLY SERIAL bob executor. One bob stage at a time, in
// topological plan order, awaited one-by-one. Bob is the single writer of
// progress/integration-ledger.md, .ledger/**, and .bob-checkpoint.md (CB4), so
// parallel() over bob stages is EXPLICITLY PROHIBITED and bob stages NEVER run
// under worktree isolation (pipeline machinery is canonical-tree only).
//
// S081 D3 (revision 4) — THE ESCALATION LADDER. A WP that does not reach COMPLETE
// may be RE-RUN at a later rung: report.escalation.next_rung `opus` re-runs on the
// executor model and `takeover` on the escalation seat's model (#291 renamed the
// rung after the role; its legacy spelling is still read), carrying an append-only
// prior_attempts[] into the next stage prompt. `diagnosis` surfaces
// needs.kind: escalation-diagnosis for the MAIN LOOP to run the escalation seat;
// every other rung keeps the pre-existing break-and-surface behaviour. Retries are
// still SERIAL — the same WP, one stage at a time — so CB4 is unaffected.
//
// #291 — NO BENCHED MODEL IS EVER DISPATCHED. The main loop passes args.benched
// (model_roster.CLAUDE_BENCHED); DEFAULT_BENCHED is always refused as well (the
// effective set is the union, so args.benched: [] unbenches nothing). A stage whose
// model is benched is REFUSED, not dispatched: a benched executor model refuses
// the whole run before any stage, and a retry rung whose model is benched — or a
// takeover with no escalation model at all — surfaces needs.kind
// escalation-diagnosis instead of inheriting or climbing. A report
// whose needs.kind is a never-escalating class (NEVER_ESCALATES below) buys NO
// rung, diagnosis included, whatever its next_rung says: it surfaces unchanged.
//
// Resume bindings (challenger fix #3): plan_hash + ledger_state_version +
// map_sig_sha256 are embedded in EVERY stage's agent() input and recomputed by
// the CALLER at every invocation INCLUDING resumes — moved ledger/map state =>
// changed stage args => surgical cache miss => resume across an amendment is
// structurally impossible.
//
// SCHEMA-TWIN: work-packages.v1 sha256:2d5098f3a50c5c2d
// SCHEMA-TWIN: plan-load.v1 sha256:436e2be9080b81c5
// SCHEMA-TWIN: execution-report.v1 sha256:713410884380b2c6

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
// `escalation` (S081 D3) MUST be declared here, not merely tolerated: the stage
// schema is what tells the agent which fields to emit, and the execute loop below
// reads report.escalation.next_rung. Undeclared, the rung would never arrive and
// the ladder would be silently dead.
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
    escalation: {
      type: ["object", "null"],
      properties: {
        // `fable` is the legacy spelling of `takeover` (read only; #291).
        next_rung: { enum: ["opus", "takeover", "fable", "diagnosis", "user", "none"] },
        task_key: { type: "string" },
        attempt_id: { type: "integer" },
      },
    },
    known_issues: { type: "array" },
    how_to_verify: { type: "array" },
  },
};

// Which ARGS.models key serves each RETRY rung. A rung absent from this map
// (diagnosis, user, none, or anything unrecognised) NEVER re-runs — it falls
// through to the surface-and-stop path, so an unknown rung fails closed.
// `fable` is the pre-#291 spelling of `takeover`, kept so a report written before
// the rename still routes to the same seat (escalation.LEGACY_RUNG_ALIASES).
const RUNG_MODEL_KEY = { opus: "bob", takeover: "escalation", fable: "escalation" };

// The benched families ALWAYS refused; args.benched (model_roster.CLAUDE_BENCHED, which
// the main loop is REQUIRED to pass, bob.md) is added on top, never in place of it. A
// hand-pinned copy of model_roster.CLAUDE_BENCHED: a parity test holds the two equal, and
// the runbook (docs/model-roster-swap.md s3 step 2) edits both in the same change.
const DEFAULT_BENCHED = ["fable"];

// The `bob` agent's own frontmatter model (agents/bob.md), which a stage inherits
// when ARGS.models.bob is undefined. A parity test compares it with the file.
const BOB_FRONTMATTER_MODEL = "opus[1m]";

// The one normaliser's JavaScript twin: skills/_meta/model_ids.py (which
// seat_model.is_benched delegates to) states the rule and a parity test runs both
// over the same spellings. Remove EVERY "[..]" / "(..)" group, anywhere (#291 fix
// round 2 N4), lowercase ASCII A-Z only, split on any run of characters outside
// ASCII [a-z0-9] (N5: an explicit set, never \s / trim(), which disagree with
// Python on BOM, U+0085, U+001C). A family is benched in an id when its tokens
// occur as a contiguous run of the id's tokens, the last one allowed a version
// glued on as ASCII digits: "fable", "fable[1m][1m]", "claude-fable[1m]-5-1",
// "Fable 5.1", "claude_fable" and "claude-fable5-1" all match "fable"; "fablex",
// "fables", "fable5x" and "5fable" do not.
function idTokens(id) {
  if (typeof id !== "string") return [];
  const text = id
    .replace(/\[[^\]]*\]|\([^)]*\)/g, " ")
    .replace(/[A-Z]/g, (c) => c.toLowerCase());
  return text.split(/[^a-z0-9]+/).filter((t) => t !== "");
}

function isBenchedModel(model, benched) {
  const have = idTokens(model);
  if (!have.length) return false;
  const tokenMatches = (h, w, last) =>
    h === w || (last && h.startsWith(w) && /^[0-9]+$/.test(h.slice(w.length)));
  for (const family of benched) {
    const want = idTokens(family);
    if (!want.length) continue;
    for (let i = 0; i + want.length <= have.length; i++) {
      if (want.every((t, j) => tokenMatches(have[i + j], t, j === want.length - 1))) return true;
    }
  }
  return false;
}

// "Same model" as the executor, compared on the normalised id (suffix stripped,
// lowercased). RECORDED LIMIT: an alias and a full id that serve the same model
// ("opus" / "claude-opus-5-5") do not compare equal here.
function sameModel(a, b) {
  const x = idTokens(a).join("-");
  return x !== "" && x === idTokens(b).join("-");
}

// The needs kinds that NEVER buy a stronger model, consulted BEFORE the rung
// (S081 revision 4 fix round 1, F3). next_rung and needs.kind are two fields one
// producer writes and nothing forces them to agree: a `user-decision` carrying
// next_rung `fable` (today `takeover`) used to buy the escalation seat on a question only the user can
// answer. Member for member escalation.NEVER_ESCALATES (all twelve, spelled as
// escalation.py spells them, the gate verdicts included — this file's schema twin
// does not close needs.kind); a parity test extracts this array from these bytes
// and compares it with the Python set, so the two cannot drift silently.
const NEVER_ESCALATES = [
  "user-decision",
  "forge-amendment-mode",
  "plan-recompile",
  "budget-floor",
  "RED",
  "REJECTED",
  "AUDIT_UNAVAILABLE",
  "INDETERMINATE",
  "reviewer-disagreement",
  "quota-exhausted",
  "auth-or-missing-tool",
  "clarification", // #313: compatibility-only parity edit (this workflow is abandoned)
];

function neverEscalates(report) {
  const kind = report && report.needs && report.needs.kind;
  return NEVER_ESCALATES.includes(kind);
}

// THE LOOP'S OWN BOUND, and it is a different bound from the ladder's.
// escalation.py holds the authoritative cap (MAX_FAILED_ATTEMPTS_PER_PLAN = 6,
// summed over every WP and rung); that bounds the LADDER. This bounds the LOOP:
// the workflow must not spin even when handed a malformed or stuck report that
// keeps asking for the same rung, because the workflow cannot assume its producer
// is well-behaved. escalation.LADDER is (opus, opus, takeover, diagnosis) — at most
// three EXECUTIONS before diagnosis, which surfaces rather than runs — so 4 covers
// every legal path with one spare.
const MAX_ATTEMPTS_PER_WP = 4;

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

// `priorAttempts` is the APPEND-ONLY failure history for THIS WP within this run
// (design §3.1 — the property mirrors escalation.py's store). The loop below can
// ADD a failure but never erases or rewrites one, so a later attempt always sees
// every earlier one. Omitted from the prompt entirely on a first attempt, so the
// common case is byte-identical to before this change.
//
// `dispatch` is set on a RETRY only (the rung being run, and for the takeover
// whether it runs on the executor's own model — the honest record of #291: while
// the Claude main tier equals the execution tier the takeover is a fresh-context
// attempt with the history, not a model step-up). Absent on a first attempt.
function bobStagePrompt(mode, wpId, args, priorAttempts, dispatch) {
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
    priorAttempts && priorAttempts.length
      ? `prior_attempts: ${JSON.stringify(priorAttempts)}`
      : null,
    dispatch && dispatch.rung ? `rung: ${dispatch.rung}` : null,
    dispatch && dispatch.same_model_as_executor !== undefined
      ? `same_model_as_executor: ${dispatch.same_model_as_executor}`
      : null,
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
  const MODELS = ARGS.models || {};
  // #291 fix round 1 (J): args.benched ADDS to DEFAULT_BENCHED, never replaces it, so a
  // caller passing [] cannot unbench the default. Safe for reversibility because
  // DEFAULT_BENCHED is held equal to model_roster.CLAUDE_BENCHED by a parity test and the
  // runbook edits both together (docs/model-roster-swap.md s3 step 2, s7).
  //
  // #291 fix round 2 (N7b): a malformed args.benched is never ignored SILENTLY. A string
  // is treated as a one-element list (safe: it can only ADD a refusal); any other
  // non-array value is ignored; non-string / empty entries are dropped. Each case is
  // recorded in verification.benched_warnings on every result the run returns.
  const BENCHED_WARNINGS = [];
  let callerBenched = [];
  if (typeof ARGS.benched === "string") {
    callerBenched = [ARGS.benched];
    BENCHED_WARNINGS.push(
      `args.benched was a string (${JSON.stringify(ARGS.benched)}), not a list: treated as a one-element list`);
  } else if (Array.isArray(ARGS.benched)) {
    callerBenched = ARGS.benched.filter((f) => typeof f === "string" && f.trim() !== "");
    const dropped = ARGS.benched.length - callerBenched.length;
    if (dropped) {
      BENCHED_WARNINGS.push(`args.benched: ${dropped} non-string or empty entr${dropped === 1 ? "y" : "ies"} dropped`);
    }
  } else if (ARGS.benched !== undefined) {
    BENCHED_WARNINGS.push(
      `args.benched ${JSON.stringify(ARGS.benched)} is not a list of families: ignored ` +
        `(DEFAULT_BENCHED ${JSON.stringify(DEFAULT_BENCHED)} still applies)`);
  }
  const BENCHED = [...new Set([...DEFAULT_BENCHED, ...callerBenched])];
  const withBenchedWarnings = (verification) =>
    BENCHED_WARNINGS.length
      ? Object.assign({}, verification, { benched_warnings: BENCHED_WARNINGS })
      : verification;

  // #291: a benched EXECUTOR model refuses the whole run before any stage — every
  // stage (plan-load, each WP, finalize) would otherwise dispatch it.
  if (isBenchedModel(MODELS.bob, BENCHED)) {
    return {
      status: "PARTIAL",
      needs: {
        kind: "user-decision",
        payload: {
          reason: "benched-executor-model",
          refused_model: MODELS.bob,
          benched: BENCHED,
        },
      },
      built: [],
      files_changed: [],
      verification: withBenchedWarnings({ dispatched: 0, refused: "args.models.bob is a benched family" }),
    };
  }

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
      verification: withBenchedWarnings({ plan_load: "hash mismatch" }),
    };
  }

  const wpOrder = loadReport.wp_order || [];
  const reports = [];

  // ── Phase execute — STRICTLY SERIAL, one WP per stage, awaited one-by-one ──
  // parallel() over these stages is EXPLICITLY PROHIBITED (CB4 single-writer).
  for (const wpId of wpOrder) {
    // The rung ladder (S081 D3). STILL STRICTLY SERIAL: this is a retry of the
    // SAME WP, one stage at a time, awaited — parallel() is still prohibited and
    // no stage is worktree-isolated, so CB4 single-writer is untouched.
    const priorAttempts = [];
    // Every dispatch of this WP: its rung, the model it ran on and, for the
    // escalation seat, whether that is the executor's own model (#291).
    const rungDispatches = [];
    let modelKey = "bob";
    let dispatch = null; // null on the first attempt; the retry's rung after
    let refusal = null;
    let report = null;
    for (let attempt = 1; attempt <= MAX_ATTEMPTS_PER_WP; attempt++) {
      const model = MODELS[modelKey];
      rungDispatches.push(Object.assign(
        { attempt: attempt, rung: dispatch ? dispatch.rung : null, model: model === undefined ? null : model },
        dispatch && dispatch.same_model_as_executor !== undefined
          ? { same_model_as_executor: dispatch.same_model_as_executor }
          : {},
      ));
      report = await agent(bobStagePrompt("execute-work-package", wpId, ARGS, priorAttempts, dispatch), {
        agentType: "bob",
        schema: EXECUTION_REPORT_SCHEMA,
        // S059 (NORMATIVE §7, DORMANT): undefined ARGS.models => inherit, unchanged.
        model: model,
      });
      if (report && report.status === "COMPLETE") break;

      const rung = report && report.escalation && report.escalation.next_rung;
      // APPEND-ONLY: record the failure before deciding anything about it.
      priorAttempts.push({
        attempt_id: (report && report.escalation && report.escalation.attempt_id) || attempt,
        status: report ? report.status : "FAILED",
        next_rung: rung || null,
        needs_kind: (report && report.needs && report.needs.kind) || null,
        source: "workflow",
      });

      // F3: the needs kind decides BEFORE the rung does.
      if (neverEscalates(report)) break;
      const nextKey = RUNG_MODEL_KEY[rung];
      if (!nextKey) break; // diagnosis / user / none / absent -> surface below

      // #291: the rung is REFUSED, never dispatched, when its model is benched,
      // and the takeover is refused when there is no escalation model at all
      // (undefined would silently inherit the executor's model and call it an
      // escalation). Either way the ladder moves to the diagnosis half.
      const nextModel = MODELS[nextKey];
      if (nextKey === "escalation" && (typeof nextModel !== "string" || !nextModel.trim())) {
        refusal = { rung: rung, model_key: nextKey, reason: "missing-escalation-model" };
        break;
      }
      if (isBenchedModel(nextModel, BENCHED)) {
        refusal = { rung: rung, model_key: nextKey, reason: "benched-model", model: nextModel, benched: BENCHED };
        break;
      }
      dispatch = { rung: rung };
      if (nextKey === "escalation") {
        dispatch.same_model_as_executor = sameModel(
          nextModel, MODELS.bob === undefined ? BOB_FRONTMATTER_MODEL : MODELS.bob);
      }
      modelKey = nextKey;
    }
    reports.push({ wp_id: wpId, report, rung_dispatches: rungDispatches });

    // First WP that does not reach COMPLETE (after any rung re-runs) breaks the
    // loop and surfaces the needs block.
    if (!report || report.status !== "COMPLETE") {
      const rung = report && report.escalation && report.escalation.next_rung;
      // The diagnosis rung is the MAIN LOOP's half of the ladder (bob.md): it
      // runs the escalation seat under codex_watch — a stronger model too, so a
      // never-escalating needs kind never reaches it. Every other rung keeps
      // today's break-and-surface behaviour unchanged.
      // A REFUSED retry rung (#291) surfaces the same way: the diagnosis half
      // of the ladder, with the refusal named — never a silent inherit.
      const needs =
        refusal
          ? {
              kind: "escalation-diagnosis",
              payload: {
                failed_wp: wpId,
                escalation: report.escalation,
                prior_attempts: priorAttempts,
                refused_rung: refusal,
              },
            }
          : rung === "diagnosis" && !neverEscalates(report)
          ? {
              kind: "escalation-diagnosis",
              payload: {
                failed_wp: wpId,
                escalation: report.escalation,
                prior_attempts: priorAttempts,
              },
            }
          : (report && report.needs) || { kind: "user-decision", payload: { failed_wp: wpId } };
      return {
        status: report ? report.status : "FAILED",
        built: reports.flatMap((r) => (r.report && r.report.built) || []),
        files_changed: reports.flatMap((r) => (r.report && r.report.files_changed) || []),
        verification: withBenchedWarnings({
          executed_wps: reports.map((r) => r.wp_id),
          // Every execution of this WP, the last included, is already on the
          // history here, so its length IS the count (f13: it was `+ 1`).
          attempts: priorAttempts.length,
          rung_dispatches: rungDispatches,
        }),
        needs,
        known_issues: (report && report.known_issues) || [],
      };
    }
  }

  // ── Phase finalize — one bob stage in mode: finalize ──
  const finalize = await agent(bobStagePrompt("finalize", null, ARGS), {
    agentType: "bob",
    schema: EXECUTION_REPORT_SCHEMA,
    // S059 (NORMATIVE §7, DORMANT): undefined ARGS.models => inherit, unchanged.
    model: MODELS.bob,
  });

  // Retries are recorded only when one happened, so a run without any keeps the
  // exact verification object finalize returned.
  const retried = reports.filter((r) => r.rung_dispatches.length > 1);
  const finalVerification = (finalize && finalize.verification) || { finalized: true };

  return {
    status: (finalize && finalize.status) || "COMPLETE",
    built: reports.flatMap((r) => r.report.built || []),
    files_changed: reports.flatMap((r) => r.report.files_changed || []),
    verification: withBenchedWarnings(retried.length
      ? Object.assign({}, finalVerification, {
          rung_dispatches: retried.map((r) => ({ wp_id: r.wp_id, dispatches: r.rung_dispatches })),
        })
      : finalVerification),
    needs: (finalize && finalize.needs) || null,
    how_to_verify: (finalize && finalize.how_to_verify) || [],
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
