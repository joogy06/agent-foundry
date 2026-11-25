// WORKFLOW: bob-stage v1.3.0
// OWNER: bob
// PROVENANCE: hand-authored, reviewed, committed — never agent-emitted (S052)
// FALLBACK: bob.md "Workflow-stage modes" (one serial BOB_MODE stage, dispatched directly)
// MIN-CLAUDE: 2.1.154
// NESTING: none
// PROHIBITED: parallel() over agentType:'bob' stages (CB4 single-writer); isolation:'worktree' on any stage in this file; an agent() call without an explicit effort
//
// #311 phase 1 (design docs/plans/2026-09-24-adaptive-effort-design.md s3.4, U5) — ONE bob
// work-package stage, dispatched by the main loop as a one-stage workflow so the stage runs
// at a PER-WP reasoning effort. Exactly one agent() call: agentType 'bob', the execution-report
// schema, and an EXPLICIT effort (never omitted: bob.md carries a static `effort:` frontmatter
// default, and an explicit per-call effort is what beats it — design s3.6). This replaces
// nothing: the multi-stage bob-serial-exec stays as it is and is still not how bob runs.
//
// THE MAIN LOOP OWNS EVERYTHING AROUND THE CALL (a workflow has no filesystem):
//   1. `effort_policy.py wp --plan <plan> --wp <id>` -> effort, effort_source, grade,
//      policy_hash, task_key and a fresh dispatch_id;
//   2. `effort_policy.py record-dispatch ...` (the dispatch row) BEFORE starting this workflow;
//   3. this workflow, with those values in args;
//   4. `effort_policy.py record-outcome ...` from result.dispatch AFTER it returns.
// The script validates that the dispatcher chose an effort and REFUSES to dispatch without
// one, rather than silently inheriting the session's level.
//
// Retries are NOT built here (phase 2 is gated, design s4). A caller that re-dispatches a WP
// passes the history it holds as args.prior_attempts; the script forwards it to the stage and
// returns it extended by this attempt when the stage does not reach COMPLETE — append-only,
// never rewritten. The attempt number is len(prior_attempts) + 1 (#311 fix round 1 m1); the
// dispatcher passes the same number to record-dispatch and record-outcome.
//
// #313 (design docs/plans/2026-09-25-apply-the-contract-design.md s3-s5) — the stage prompt is the
// one RUNTIME producer of the spawn-brief block: Goal, Non-goals, Open questions, Done when and
// Stop when come from args.goal / args.non_goals / args.done_when (the WP's acceptance_criteria and
// the DWs it covers), and the stage may return ONE needs.kind `clarification` in preflight. The
// allowance is DERIVED, not held: the dispatcher passes `clarification_admission` from
// `effort_policy.py admit-clarification --plan-id <plan>` (the persisted outcome rows), and a resume
// passes `answers`, the asking dispatch's id and a FRESH dispatch_id. A clean clarification is never
// appended to prior_attempts and never escalates. A second request, a fix-round dispatch or a retry
// that asks becomes `user-decision`; so do a malformed payload and a clarification that changed
// files (that one is also a failed attempt). A D21 fix round is `dispatch_kind: "fix-round"` with
// the `fix_admission` JSON `effort_policy.py admit-fix-round` printed (it CONSUMED the round); a
// fix round outside 1..MAX_FIX_ROUNDS (or "user") refuses the dispatch. HONEST LIMIT: the workflow
// validates what the dispatcher passes; it cannot see the store, so the guarantee holds for a
// dispatcher that runs the two admits — which is what bob.md tells the main loop to do.
//
// SCHEMA-TWIN: execution-report.v1 sha256:713410884380b2c6

export const meta = {
  name: "bob-stage",
  version: "1.3.0",
  description:
    "owner:bob — ONE bob execute-work-package stage at an explicit per-WP reasoning effort (#311); the main loop records the dispatch and outcome rows.",
};

// Execution-report stage schema twin (the canonical bob report shape) — byte-for-byte the
// literal bob-serial-exec.js carries, held to the same canonical hash.
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

// effort_policy.LEVELS and effort_policy.SOURCES (skills/_meta/effort_policy.py); a parity test
// extracts both arrays from these bytes and compares them with the Python tuples.
const EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"];
const EFFORT_SOURCES = ["grade", "promotion", "protected", "default-ungraded", "inherit", "override", "policy"];

// #311 fix round 1 M2 — the grade table's twin (effort_policy.GRADE_EFFORT / PROMOTED_EFFORT /
// UNGRADED_EFFORT / RESERVED_*), held equal by a parity test. The dispatcher's effort must be the
// one the policy gives for its grade and source, or the stage is not dispatched.
const GRADE_EFFORT = { S: "low", M: "medium", L: "high" };
const PROMOTED_EFFORT = { S: "medium", M: "high" };
const UNGRADED_EFFORT = "high";
const RESERVED_LEVELS = ["xhigh", "max"];
const RESERVED_SOURCES = ["protected", "override"];

// #311 fix round 1 F2 — the CLOSED set of needs kinds (effort_policy.NEEDS_KINDS: the
// execution-report needs.kind enum plus escalation.NEVER_ESCALATES). A report's needs.kind is
// producer text; anything outside this set is recorded as "invalid" and never copied into the
// history a later stage prompt interpolates.
const NEEDS_KINDS = ["AUDIT_UNAVAILABLE", "INDETERMINATE", "RED", "REJECTED", "auth-or-missing-tool", "budget-floor", "capability-failure", "clarification", "escalation-diagnosis", "forge-amendment-mode", "needs_inline_verification", "plan-execution", "plan-recompile", "quota-exhausted", "reviewer-disagreement", "user-decision"];
// The execution-report schema's rung enum (the escalation block above).
const RUNGS = ["opus", "takeover", "fable", "diagnosis", "user", "none"];

// The args the dispatcher MUST supply. Missing any one refuses the dispatch. #313: `goal` and
// `done_when` are the brief — a stage never starts without a written done-when.
const REQUIRED_ARGS = [
  "project_root", "plan_path", "plan_hash", "wp_id", "run_label", "run_started_at",
  "effort", "effort_source", "dispatch_id", "task_key", "goal", "done_when", "dispatch_kind",
];
// #313 fix round 1 B: what the dispatch IS. A fix-round dispatch carries the admission
// `effort_policy.py admit-fix-round` printed (which consumed the round); a work-package dispatch
// carries none. There is no default, so a fix dispatch cannot pass as a first attempt by omission.
const DISPATCH_KINDS = ["work-package", "fix-round"];
const USER_ROUND = "user";
const ID32 = /^[0-9a-f]{32}$/;
const REVIEW_ID = /^[a-z0-9][a-z0-9._:\/@\[\]+-]{0,199}$/;

// #313 s4 — effort_policy.MAX_FIX_ROUNDS, held equal by a parity test. An initial review, then at
// most this many D21 fix rounds, then the user decides.
// <!-- contract:loop id=bob-stage.fix-round bound=2 on_exhaust=user -->
const MAX_FIX_ROUNDS = 2;
const DEFAULT_NON_GOALS = "anything outside this WP's files and acceptance criteria; other WPs; the design's DWs themselves";

function closed(value, allowed) {
  if (value === undefined || value === null) return null;
  return allowed.includes(value) ? value : "invalid";
}

// The same verdicts as effort_policy.check_consistency(effort, source, grade) with no role —
// a parity test runs one case matrix through both (fix round 2 item 5). A bob stage never
// carries a protected role, so `protected` is refused outright here, and `max` under any source
// (fix round 2 item 2): until phase 2 verifies an escalation retry, nothing dispatches at max.
function consistencyProblem(effort, source, grade) {
  const isGrade = (g) => Object.prototype.hasOwnProperty.call(GRADE_EFFORT, g);
  if (grade !== undefined && grade !== null && !isGrade(grade)) {
    return `grade must be S/M/L or absent, got ${JSON.stringify(grade)}`;
  }
  if (source === "protected") {
    return "effort_source protected is refused: a bob stage is never a protected seat";
  }
  if (effort === "max") {
    return "effort max is refused for every source but a verified protected escalation";
  }
  if (RESERVED_LEVELS.includes(effort) && !RESERVED_SOURCES.includes(source)) {
    return `effort ${JSON.stringify(effort)} is reserved for ${JSON.stringify(RESERVED_SOURCES)}, not ${JSON.stringify(source)}`;
  }
  if (source === "grade" || source === "promotion") {
    const table = source === "grade" ? GRADE_EFFORT : PROMOTED_EFFORT;
    if (!isGrade(grade)) return `effort_source ${source} needs a grade in S/M/L, got ${JSON.stringify(grade)}`;
    if (!Object.prototype.hasOwnProperty.call(table, grade)) return `grade ${grade} is never promoted`;
    if (table[grade] !== effort) return `${source} for grade ${grade} is ${table[grade]}, not ${JSON.stringify(effort)}`;
  } else if (source === "default-ungraded") {
    if (grade !== undefined && grade !== null) return "a default-ungraded dispatch carries no grade";
    if (effort !== UNGRADED_EFFORT) return `default-ungraded is ${UNGRADED_EFFORT}, not ${JSON.stringify(effort)}`;
  }
  return null;
}

// The plan's allowance, from `effort_policy.py admit-clarification` (derived from the persisted
// outcome rows, keyed on plan_id so later WPs inherit it) — never from a bare dispatcher flag.
function allowanceUsed(args) {
  const a = args.clarification_admission;
  return !!(a && a.clarification_used === true);
}

// Why this dispatch may not ask a question, or null when it may (#313 s5).
function noClarificationReason(args, priorAttempts) {
  if (allowanceUsed(args)) return "second-clarification";
  if (args.dispatch_kind === "fix-round") return "fix-round";
  if (priorAttempts.length) return "retry";
  return null;
}

// Fix round 1 D and B: the validated shape of the two admissions. Returns problems.
function admissionProblems(args) {
  const out = [];
  const planId = typeof args.task_key === "string" ? args.task_key.split(":")[0] : null;
  const ca = args.clarification_admission;
  if (!ca || typeof ca !== "object" || Array.isArray(ca)) {
    out.push("missing args.clarification_admission (run effort_policy.py admit-clarification --plan-id <plan>)");
  } else {
    if (ca.plan_id !== planId) out.push(`clarification_admission.plan_id ${JSON.stringify(ca.plan_id)} is not this task's plan_id ${JSON.stringify(planId)}`);
    if (typeof ca.clarification_used !== "boolean") out.push("clarification_admission.clarification_used must be a boolean");
    // fix round 2 item 6: the admission's state must agree with its flag. `unknown` (an open
    // dispatch of the plan) FAILS CLOSED: the stage may run but may not ask. This is the extent of
    // what bob-stage can check -- the admission is caller-supplied; record time enforces it.
    const states = { clear: false, used: true, unknown: true };
    if (!Object.prototype.hasOwnProperty.call(states, ca.state)) out.push(`clarification_admission.state ${JSON.stringify(ca.state)} is not clear|used|unknown`);
    else if (states[ca.state] !== ca.clarification_used) out.push(`clarification_admission.state ${ca.state} contradicts clarification_used`);
    if (ca.state === "used" && !(typeof ca.prior_dispatch_id === "string" && ID32.test(ca.prior_dispatch_id))) {
      out.push("clarification_admission.prior_dispatch_id must name the asking dispatch when the allowance is used");
    }
    // fix round 2 item 8: the task key is effort_policy.task_key_for(plan_id, wp_id), or a
    // clarification recorded under it would be invisible to admit-clarification.
    if (typeof ca.plan_id === "string" && args.task_key !== `${ca.plan_id}:${args.wp_id}`) {
      out.push(`task_key ${JSON.stringify(args.task_key)} is not plan_id:wp_id (${ca.plan_id}:${args.wp_id})`);
    }
  }
  if (args.clarification_used !== undefined) {
    if (typeof args.clarification_used !== "boolean") out.push("args.clarification_used must be a boolean");
    else if (ca && typeof ca === "object" && args.clarification_used !== ca.clarification_used) {
      out.push("args.clarification_used contradicts clarification_admission");
    }
  }
  const answered = typeof args.answers === "string" && args.answers.trim() !== "";
  if (answered) {
    if (!allowanceUsed(args)) out.push("args.answers but the admission shows no clarification was asked");
    if (typeof args.clarification_dispatch_id !== "string") {
      out.push("args.answers needs clarification_dispatch_id (the dispatch that asked)");
    } else {
      if (args.clarification_dispatch_id === args.dispatch_id) out.push("a resume after a clarification needs a fresh dispatch_id");
      if (ca && args.clarification_dispatch_id !== ca.prior_dispatch_id) out.push("clarification_dispatch_id is not the asking dispatch the admission recorded");
    }
  }
  if (args.fix_round !== undefined) out.push("args.fix_round is not accepted: pass fix_admission from effort_policy.py admit-fix-round");
  const fa = args.fix_admission;
  if (args.dispatch_kind === "fix-round") {
    if (!fa || typeof fa !== "object" || Array.isArray(fa)) {
      out.push("a fix-round dispatch needs args.fix_admission (effort_policy.py admit-fix-round)");
    } else {
      if (!(typeof fa.review_id === "string" && REVIEW_ID.test(fa.review_id))) out.push("fix_admission.review_id is not a review identity");
      // fix round 2 item 4: the admission must be for THIS plan's design doc (review_id is its
      // toplevel-relative path, lowercased). Replay and forgery are refused at record-dispatch.
      // round 3 item 8: design_doc is the dispatcher-supplied `effort_policy.py review-id` output,
      // compared EXACTLY -- no normalisation here that could disagree with the Python resolver.
      const doc = typeof args.design_doc === "string" && args.design_doc !== "" ? args.design_doc : null;
      if (!doc) out.push("a fix-round dispatch needs args.design_doc (the plan's design_doc) to check the admission against");
      else if (doc !== fa.review_id) out.push(`fix_admission.review_id ${JSON.stringify(fa.review_id)} is not this plan's design_doc ${JSON.stringify(doc)}`);
      if (!(typeof fa.admission_id === "string" && ID32.test(fa.admission_id))) out.push("fix_admission.admission_id is not an admission id");
      if (!(fa.fix_round === USER_ROUND || (Number.isInteger(fa.fix_round) && fa.fix_round >= 1 && fa.fix_round <= MAX_FIX_ROUNDS))) {
        out.push(`fix_admission.fix_round ${JSON.stringify(fa.fix_round)} is outside 1..${MAX_FIX_ROUNDS} and not "user": a further automatic fix round is refused; the user decides`);
      }
    }
  } else if (fa !== undefined) {
    out.push("fix_admission on a work-package dispatch: a fix round is dispatched as dispatch_kind fix-round");
  }
  return out;
}

// Fix round 1 m4: a clarification payload must be what the schema says — or it is not a question.
function payloadValid(p) {
  if (!p || typeof p !== "object" || Array.isArray(p)) return false;
  const nonEmpty = (s) => typeof s === "string" && s.trim() !== "";
  if (!Array.isArray(p.questions) || p.questions.length < 1 || p.questions.length > 3) return false;
  if (!p.questions.every((q) => q && typeof q === "object" && nonEmpty(q.question) && nonEmpty(q.work_changes_if))) return false;
  return nonEmpty(p.default_if_unanswered);
}

// <!-- spawn-brief.v1 id=bob-stage.stage -->
function stagePrompt(args, priorAttempts) {
  const noAsk = noClarificationReason(args, priorAttempts);
  const nonGoals = typeof args.non_goals === "string" && args.non_goals.trim() ? args.non_goals : DEFAULT_NON_GOALS;
  const covers = Array.isArray(args.covers) && args.covers.length ? ` (covers ${args.covers.join(", ")})` : "";
  return [
    "BOB_MODE: execute-work-package",
    `wp_id: ${args.wp_id}`,
    `project_root: ${args.project_root}`,
    `plan_path: ${args.plan_path}`,
    `plan_hash: ${args.plan_hash}`,
    `plan_revision: ${args.plan_revision}`,
    `ledger_state_version: ${args.ledger_state_version}`,
    `map_sig_sha256: ${args.map_sig_sha256}`,
    `run_label: ${args.run_label}`,
    `run_started_at: ${args.run_started_at}`,
    `dispatch_id: ${args.dispatch_id}`,
    priorAttempts.length ? `prior_attempts: ${JSON.stringify(priorAttempts)}` : null,
    args.dispatch_kind === "fix-round" && args.fix_admission
      ? `fix_round: ${args.fix_admission.fix_round} of ${MAX_FIX_ROUNDS} (review ${args.fix_admission.review_id})` : null,
    "",
    `Goal: ${args.goal}`,
    `Non-goals: ${nonGoals}`,
    noAsk === null
      ? "Open questions: material ones only (answers would change the work) — return ONCE, in preflight, BEFORE any mutation, as status PARTIAL, files_changed [], needs.kind clarification with payload {questions (≤3, each with work_changes_if), default_if_unanswered}; otherwise decide, note the assumption, proceed."
      : `Open questions: none may be returned (${noAsk}) — decide, note the assumption, proceed; a blocker keeps its existing needs.kind.`,
    typeof args.answers === "string" && args.answers.trim() ? `Answers: ${args.answers}` : null,
    `Done when: ${args.done_when}${covers}`,
    "Stop when: done-when holds, or you are blocked (state the blocker). This stage runs ONE WP once; it never starts another round.",
    "Brief block: skills/_meta/spawn-brief.md",
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
// <!-- /spawn-brief.v1 -->

// ── Script body (top-level; `args`/`agent` are runtime globals) ──
{
  const ARGS = typeof args === "string" ? JSON.parse(args) : (args || {});
  const priorAttempts = Array.isArray(ARGS.prior_attempts) ? ARGS.prior_attempts.slice() : [];
  // #311 fix round 1 m1: the attempt is DERIVED from the history the dispatcher holds; an
  // args.attempt that contradicts it refuses the dispatch rather than mislabel a retry.
  const attempt = priorAttempts.length + 1;

  const missing = REQUIRED_ARGS.filter(
    (k) => typeof ARGS[k] !== "string" || ARGS[k].trim() === "");
  const problems = missing.map((k) => `missing args.${k}`);
  if (!missing.includes("effort") && !EFFORT_LEVELS.includes(ARGS.effort)) {
    problems.push(`args.effort ${JSON.stringify(ARGS.effort)} is not one of ${JSON.stringify(EFFORT_LEVELS)}`);
  }
  if (!missing.includes("effort_source") && !EFFORT_SOURCES.includes(ARGS.effort_source)) {
    problems.push(`args.effort_source ${JSON.stringify(ARGS.effort_source)} is not one of ${JSON.stringify(EFFORT_SOURCES)}`);
  }
  if (ARGS.effort_source === "inherit") {
    problems.push("effort_source inherit is refused: this workflow always dispatches an explicit effort");
  }
  if (!problems.length) {
    const why = consistencyProblem(ARGS.effort, ARGS.effort_source, ARGS.grade);
    if (why) problems.push(why);
  }
  if (!missing.includes("dispatch_kind") && !DISPATCH_KINDS.includes(ARGS.dispatch_kind)) {
    problems.push(`args.dispatch_kind ${JSON.stringify(ARGS.dispatch_kind)} is not one of ${JSON.stringify(DISPATCH_KINDS)}`);
  }
  problems.push(...admissionProblems(ARGS));
  if (ARGS.attempt !== undefined && ARGS.attempt !== attempt) {
    problems.push(`args.attempt ${JSON.stringify(ARGS.attempt)} contradicts prior_attempts (this is attempt ${attempt})`);
  }

  const idsValid = !missing.includes("dispatch_id") && !missing.includes("task_key");
  const dispatchBlock = (status, needsKind) => ({
    dispatch_id: ARGS.dispatch_id,
    task_key: ARGS.task_key,
    wp_id: typeof ARGS.wp_id === "string" ? ARGS.wp_id : null,
    attempt: attempt,
    grade: Object.prototype.hasOwnProperty.call(GRADE_EFFORT, ARGS.grade) ? ARGS.grade : null,
    effort_requested: EFFORT_LEVELS.includes(ARGS.effort) ? ARGS.effort : null,
    effort_applied: "unknown",
    effort_source: closed(ARGS.effort_source, EFFORT_SOURCES),
    policy_hash: typeof ARGS.policy_hash === "string" ? ARGS.policy_hash : null,
    surface: "workflow",
    agent_type: "bob",
    status: status,
    needs_kind: needsKind,
    // fix round 2 item 4: the binding the dispatch and outcome rows carry (record-dispatch
    // --dispatch-kind --fix-admission-id --review-id refuses an unknown or reused admission).
    dispatch_kind: DISPATCH_KINDS.includes(ARGS.dispatch_kind) ? ARGS.dispatch_kind : null,
    fix_admission_id: ARGS.dispatch_kind === "fix-round" && ARGS.fix_admission && ID32.test(ARGS.fix_admission.admission_id)
      ? ARGS.fix_admission.admission_id : null,
    review_id: ARGS.dispatch_kind === "fix-round" && ARGS.fix_admission && typeof ARGS.fix_admission.review_id === "string"
      ? ARGS.fix_admission.review_id : null,
  });

  if (problems.length) {
    // Refused BEFORE any stage: a dispatch without a consistent, chosen effort would be wrong
    // or would silently inherit. m2: still joinable to its dispatch row when the ids are valid.
    return {
      status: "PARTIAL",
      wp_id: typeof ARGS.wp_id === "string" ? ARGS.wp_id : null,
      built: [],
      files_changed: [],
      verification: { dispatched: 0, refused: problems },
      needs: { kind: "user-decision", payload: { reason: "bob-stage-args-invalid", problems: problems } },
      dispatch: idsValid ? dispatchBlock("REFUSED", null) : null,
      prior_attempts: priorAttempts,
      clarification_used: allowanceUsed(ARGS),
    };
  }

  const report = await agent(stagePrompt(ARGS, priorAttempts), {
    agentType: "bob",
    schema: EXECUTION_REPORT_SCHEMA,
    effort: ARGS.effort, // ALWAYS explicit (design s3.6 build rule)
    label: `bob ${ARGS.wp_id} @ ${ARGS.effort}`,
  });

  let status = report ? report.status : "NO_REPORT";
  let needsKind = closed(report && report.needs && report.needs.kind, NEEDS_KINDS);
  let clarificationUsed = allowanceUsed(ARGS);

  // #313 s5 — a clarification is a question, not an attempt. Allowed once per plan, in preflight,
  // with no file changed and a well-formed payload; anything else that asks becomes a user-decision.
  // ANY ask spends the allowance (fix round 1 m1: the dispatcher records clarification_asked on the
  // outcome row, which admit-clarification reads). Only a clean question stays out of
  // prior_attempts; one asked after changing files is also a failed attempt.
  let clarification = null;
  let asked = false;
  let countsAsAttempt = false;
  if (needsKind === "clarification") {
    asked = true;
    clarificationUsed = true;
    const noAsk = noClarificationReason(ARGS, priorAttempts);
    const mutated = Array.isArray(report.files_changed) && report.files_changed.length > 0;
    const why = noAsk || (mutated ? "clarification-after-mutation"
      : (!payloadValid(report.needs.payload) ? "clarification-payload-invalid" : null));
    if (why) {
      clarification = {
        status: "PARTIAL",
        needs: { kind: "user-decision", payload: { reason: "clarification-not-allowed", why: why, questions: report.needs.payload || null } },
      };
      needsKind = "user-decision";
      countsAsAttempt = why === "clarification-after-mutation";
    } else {
      clarification = { status: "PARTIAL", needs: report.needs };
    }
    status = "PARTIAL";
  }
  // The joined record the main loop writes as the outcome row. effort_applied stays
  // `unknown`: the host does not confirm the level a stage actually ran at.
  const dispatch = dispatchBlock(status, needsKind);
  dispatch.clarification_asked = asked;
  if (clarification && needsKind === "clarification") dispatch.waiting = "clarification";

  // APPEND-ONLY: a failed attempt joins the history the caller passed; nothing is rewritten.
  // m3: every top-level field is the DISPATCHER's fact; what the stage said about itself is
  // kept apart under `reported`, closed-enum or null, so phase 2 cannot read it as fact.
  if (status !== "COMPLETE" && (!clarification || countsAsAttempt)) {
    const esc = (report && report.escalation) || {};
    priorAttempts.push({
      attempt_id: attempt,
      status: status === "NO_REPORT" ? "FAILED" : closed(status, ["PARTIAL", "FAILED"]),
      source: "workflow",
      dispatch_id: dispatch.dispatch_id,
      effort_requested: dispatch.effort_requested,
      effort_source: dispatch.effort_source,
      grade: dispatch.grade,
      reported: {
        attempt_id: Number.isInteger(esc.attempt_id) ? esc.attempt_id : null,
        next_rung: closed(esc.next_rung, RUNGS),
        needs_kind: needsKind,
      },
    });
  }

  if (!report) {
    return {
      status: "FAILED",
      wp_id: ARGS.wp_id,
      built: [],
      files_changed: [],
      verification: { dispatched: 1, report: null },
      needs: { kind: "user-decision", payload: { reason: "no-report", failed_wp: ARGS.wp_id } },
      dispatch: dispatch,
      prior_attempts: priorAttempts,
      clarification_used: clarificationUsed,
    };
  }
  return Object.assign({}, report, clarification || {}, {
    dispatch: dispatch, prior_attempts: priorAttempts, clarification_used: clarificationUsed,
  });
}

/* <!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: claude-code-workflow-surface
    verified_against: "agent() opts.effort per call (workflow-authoring reference; #311 probe 2026-09-24: low 0 vs max 1,795 thinking tokens)"
    verified_on: "2026-09-24"
    volatility: high
--> */
