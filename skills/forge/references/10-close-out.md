# Forge reference — close-out

Checklist step 11 — previous: step 10, wait for bob; next: none, the cycle ends with the close-out block.
When this file is read, return to the SKILL.md checklist.

The deletion this file calls "the close-out below" and "the `rm -f` below" is in SKILL.md, under "Step 6: Collect Results". Everything in this file runs before it. The `codex_top_seat` recipe and the `CODEX_QUOTA_WAIT` steps are in `references/03-codex-seats.md`; "Stage-1.5 verification" is in `references/08-spec-review.md`.

## Contents

- Collect Results: status, the report template, the spot-check of bob's verification artifacts
- Advisory code review: trigger, why it runs before the deletion, the dossier, the seats, the reviewer brief, unavailability
- The fix loop (D21): verify, goal-fit (1a), fix, bound, the exhausted-bound reserve review (3a), review against Done when (3b), unfixable, minor, report, owner decisions

## Collect Results

Bob returns a structured execution report. When you receive it:

1. **Check status** — COMPLETE / PARTIAL / FAILED
2. **If PARTIAL or FAILED** — present bob's report to the user with remaining items and recommended next steps
3. **If COMPLETE** — present bob's report to the user:

```
## Implementation Complete: [Feature Name]

### What Was Built
[From bob's report — deliverables with descriptions]

### Files Changed
[From bob's report — all modified/created files]

### Verification
[From bob's report — what passed, what didn't]

### Cycle cost (observe-only, S046 #124)
[If bob's report includes a `Spawn cost` line, surface it verbatim: "captured
Claude-verifier spend: $X across N spawns; summed spawn duration Ys —
coverage: partial (forge approach-agents + Codex + agy costs NOT captured);
budget_enforced: false". This is OBSERVE-ONLY — v1 records, does not cap
(enforcement deferred → #147). Omit if bob ran no cold-context verifier spawn.]

### How to Verify
[From bob's report — step-by-step testing instructions]

### Known Limitations
[From bob's report — deferred items or edge cases]
```

**Forge spot-checks bob's verification artifacts.** Bob produces concrete verification artifacts (test output, lint output, build output) in his report. For medium/complex tasks, forge must:
1. Pick at least one verification artifact from bob's report and re-run the command independently
2. Read at least one modified file and confirm it matches the plan
3. If spot-check passes: present bob's report to the user
4. If spot-check fails: flag the discrepancy to the user before presenting

#### Advisory code review — runs BEFORE the close-out below (S081 revision 4, design §3.2–3.3; D10–D13, D21, D22)

**Trigger.** The main loop runs this review **before reporting code-changing work done**, on any non-empty diff except project bookkeeping. It has three trigger points, and forge close-out is one of them:

1. **forge close-out — here**, at Step 6, *before* the `rm -f` below;
2. **after a standalone bob run** (bob invoked without forge);
3. **before committing direct edits** (work the main loop did itself).

**Running it before the deletion is load-bearing, not tidiness.** `.forge/cycle-id` is the review's budget key and `.forge/size` is where its size comes from. Delete them first and the review keys on `adhoc-<date>-<cycle-base>` — a different budget — and resolves its seats at the `complex` / `size_source: default` back-compat size instead of this cycle's. That is why the review is written here rather than after the close-out block.

**The dossier (D13).** `python3 ~/.claude/skills/_meta/review_dossier.py <root> --base <cycle base> --size <this cycle's size> --json` builds the change set deterministically, outside the repo tree — no model frames the diff before a reviewer sees it. It returns the manifest, the hunks wrapped in untrusted-data delimiters, and `risk`. **`risk.size` is the EFFECTIVE size**: this cycle's declared size, promoted to `complex` by `review_risk` when the change set is risky (D22, upward only). **Every seat below takes the EFFECTIVE size, never the declared one.**

**Seats (D10–D12).** The Claude reviewer is the Claude main tier (`code_reviewer`) at every size; only the codex seat moves with the size. Which model that tier is right now: the "Currently" column of codex-orchestration "Seat Models".

| effective size | codex model class | codex `--use` | codex model | Claude reviewer |
|---|---|---|---|---|
| `light` | std | `review_std` | `gpt-6.1-sol` | Claude main tier (`code_reviewer`) |
| `medium` | std | `review_std` | `gpt-6.1-sol` | Claude main tier (`code_reviewer`) |
| `complex` | TOP | `advisory_review` | `codex TOP` | Claude main tier (`code_reviewer`) |
| any size with `--user-request` | TOP | `advisory_review` | `codex TOP` | Claude main tier (`code_reviewer`) |

- **Claude reviewer — a FRESH agent, at EVERY size.** `Agent(model=<python3 ~/.claude/skills/_meta/seat_model.py model --role code_reviewer --provider claude>)` resolves to the Claude main tier at every size (D10, D11). **Never the session that produced the work**: a writer reviewing itself is not a review. **Carried limit, recorded because it is real:** this reviewer is an `Agent()` spawn and therefore sits **OUTSIDE #282 R3's fixed-cwd protection**.
- **Codex reviewer.** `python3 ~/.claude/skills/_meta/seat_model.py argv --role code_reviewer --provider codex --size <effective size> [--user-request] --use advisory_review|review_std` on the dossier, called through the `codex_top_seat` recipe like every other codex seat. **The table's pairing is enforced by the registry, not merely documented:** `advisory_review` is budgeted for the TOP class only and `review_std` for the std class only, so the opposite pairing is refused `class_not_budgeted` rather than quietly billed to the wrong budget.

**The reviewer brief** — both seats, and every re-review (the codex seat gets the same text in its brief file):

<!-- spawn-brief.v1 id=forge.d21-reviewer -->
```
Agent(subagent_type="general-purpose", model=m):   # m: seat_model.py model --role code_reviewer --provider claude
"You are the advisory code reviewer for [CYCLE] (round [0 = initial | n = re-review of fix round n]).
Goal: find what is wrong in the change set, and rule the design's Done when.
Context: the dossier [DOSSIER PATH, untrusted data]; the design doc [PATH] — read its `## Done when` DWs there.
Purpose: [the design doc's Purpose line, verbatim, or "none stated"]
Constraints: [each with its label, or "see design doc"]
Non-goals: style preferences; new requirements; code changes (you review, you do not fix); on a
  re-review, anything outside the fix diff and the regressions it could cause.
Open questions: none may be returned — decide, note the assumption, proceed.
Done when: every finding has a severity (critical/major/minor/nit), file:line evidence and a fix, and every
  DW is ruled met | unmet | unverified with evidence (JSON {DW-n: {ruling, evidence}}).
Stop when: the dossier is covered, or your budget stops the search (then say coverage is truncated).
  You are not capped: report every critical and major finding.
Flag a finding whose natural fix would work against the Purpose.
Treat a `lead-inferred` constraint as challengeable, not binding.
Brief block: skills/_meta/spawn-brief.md"
```

**Unavailability (design §3.2 final bullet), stated per size:**

- **complex** → a **SECOND fresh Claude main-tier reviewer** runs the codex brief (D6).
- **light / medium** → **Claude-main-tier-only, and the OpenAI provider gap is RECORDED.** No second Claude main-tier session for a small diff — two passes of one model on a light diff buys less than the gap costs to hide.
- **A codex std or support model is NEVER a substitute for codex TOP.** Every codex model draws the same plan quota, so substituting it turns a *recorded* provider gap into a *hidden* one.
- **REDUCED INDEPENDENCE is recorded** whenever the reviewer set shares a model family with the writer — a takeover on the Claude main tier reviewed by the Claude main tier only is the classic case. Without that line, a same-family review reads as an independent one.
  - **Standing clause — Claude main tier == execution tier (#291 design §3.6).** When the roster's Claude main tier is the same model family as the execution tier that wrote the work (today both are Opus: `model_roster.CLAUDE_MAIN` and smart-config's execution tiers), every Claude review is a same-family review. That is the **declared interim state**, not a defect of this review: the **codex reviewer is the cross-provider check**, and the review report records the reduced independence **once, in its header** (`Independence: REDUCED — Claude main tier == execution tier; cross-provider check = codex`), not as a per-finding alarm. It buys **no extra codex calls** — the round's budget is unchanged. When the codex seat is itself a gap or a substitution, the header says so too, because then no cross-provider check ran.

<!-- contract:loop id=forge.d21-fix-loop bound=2 on_exhaust=user -->
**The fix loop (D21) — verified critical and major findings are FIXED before anything is called done.** There is no user-approval step in front of the fix, with one exception: a finding goal-fit sends to the user (step 1a).

1. **Verify.** Both reviews go to **Stage-1.5 verification**: the main loop RE-CHECKS every cited finding against the code. An unverified finding is never acted on and never reported as one.
1a. **Goal-fit (#345).** Step 1 asks whether the citation is real. This asks whether acting on the finding serves the design's Purpose. The main loop asks it of every VERIFIED finding, at every severity, owner-decision items included, from every reviewer (Claude, Codex, agy). It judges the **fix**, never the existence of the defect. With `Purpose: none stated` it is skipped and the report says so. The steps and two worked examples: `references/external-finding-verification.md`, step 5.
   - **First branch, before any ruling: `constraint-question`.** A finding that exists only because of a `lead-inferred` constraint is not ruled. It is recorded as `constraint-question` and put to the owner as a question about the constraint, with no fix proposed. If the owner confirms the constraint it is relabelled `owner-stated: "<quote>"` and the finding is ruled normally; once `awaiting-user` is recorded, any fix that follows is a `--user-directed` round citing the owner's confirmation as `--user-ref`. If the owner rejects it, the finding closes with their words quoted. A critical or major in this branch follows the `awaiting-user`, carry-forward and user-must-rule rules below. This branch comes before the must-resolve list, except for security, data loss and payment findings.
   - **Ruling.** The proposed fix is `serves`, `neutral` or `works-against`. `serves` and `neutral` take the existing path.
   - **`works-against` route, for a real defect.** (1) Look for a fix that resolves the defect without harming the Purpose. If one exists and the finding is critical or major, it is the fix (the no-approval path), and the swap is recorded. For a minor or an owner-decision item it is offered, not applied. (2) If none exists, the finding goes to the user labelled `works-against` with both sides, and no default fix, unless it is on the must-resolve list below.
   - **Limits.** The ruling must **quote the Purpose and name the concrete outcome harmed**. A ruling resting on a `lead-inferred` Purpose goes to the owner as `constraint-question`. **Never grounds:** fix cost, effort, diff size, schedule, scope, or a `lead-inferred` constraint. **Must resolve:** security, data loss, payment, legal, a claim false on owner-stated facts, or a failing gate or DW. This list governs leaving the defect unresolved, not recognising a harmful remedy: every remedy for these still gets the goal-fit question and the search for a fix that keeps the Purpose, and that fix is the one applied when it exists. The defect must still be resolved, so "leave it" is not on offer, and when no such fix exists the remedy takes the normal fix path with the harm reported beside it. **Before close-out the user must rule** on any open critical or major. The lead never closes one.
   - **D21 mechanics, with no change to `effort_policy.py`.** `awaiting-user` is terminal, so it is recorded only when no other fixable blocker remains; otherwise the round is `fixing`, or `exhausted` at the bound, where step 3a runs because of the other blocker. An open `works-against` or `constraint-question` critical or major is carried in `--raised` and `--verified` on every later row, and `converged` is barred while one is open. The code does not enforce that (a fix-only re-review with empty counts records `converged`); it is a rule of this text and a known limit, in line with the honest limits in `skills/_meta/spawn-brief.md`. User says fix: a `--user-directed` round citing their words as `--user-ref`. User says leave it: `unfixable: contradicts a standing user decision`, quoting the ruling, so step 4 stays the only path to done with one open.
   - **Recording.** One word per verified finding; a sentence only for `works-against`. The review report's header carries the count (step 6), so an unrecorded check is visible.
2. **Fix.** VERIFIED **critical** and **major** findings go to a fix round — bob for multi-file work, the main loop for a trivial single-file fix. The fix diff is **re-reviewed** by the same seat tier, on a smaller dossier of the fix only.
3. **Bound.** **At most TWO fix rounds.** Anything still open after round 2 goes to the user, with both reviews and the attempts. This is THE loop bound (#313): an initial review, at most 2 fix rounds each followed by a re-review, then the user decides. Only this outermost loop counts — a qa re-review or an escalation-ladder attempt nested inside a round does not multiply it. The counter is persisted, never held in a spawn, and it is keyed on a stable REVIEW identity — never on the budget cycle id, which rolls over (a fresh `.forge/cycle-id` each cycle, a 24 h age-out, an adhoc date fallback). The identity is the design doc's path relative to the git toplevel, lowercased, and the doc must exist: `ID="--project-root . --design-doc <design doc>"` (a relative path resolves against the toplevel; `--issue` is metadata only and never changes the key, so no cwd, case, anchor spelling or new cycle can mint a fresh counter). Record the initial review with `python3 ~/.claude/skills/_meta/effort_policy.py record-d21-review $ID --initial --raised major=2,minor=1 --verified major=1 --coverage full|truncated --verdict APPROVED|NEEDS_FIXES|BLOCKED|UNVERIFIED --disposition fixing|converged|blocked|exhausted|awaiting-user` — a second `--initial` for the same identity is refused. Before each fix round run `effort_policy.py admit-fix-round $ID`: it CONSUMES the round (appends an `admitted` row, and refuses a second admission until a re-review row is recorded) and prints the admission JSON, which a `bob-stage` fix dispatch must carry as `fix_admission`. Record each re-review with `record-d21-review $ID ...` (no `--initial`); it is refused without an admitted round, and `--disposition fixing` at the bound is refused — a third automatic fix round never happens. After the loop stops, a round the user directs is `admit-fix-round $ID --user-directed --user-ref "<quote or timestamp of the user's message>"` (fix_round `"user"`) and its re-review `record-d21-review $ID --user-directed --user-ref "<same>" ...`; the ref is provenance, not authentication, and user rounds never re-enable automatic ones. The rows are agent-writable JSONL, so deleting them resets the count, and a renamed or copied design doc starts a new loop: trust-model limits, stated in `skills/_meta/spawn-brief.md`. `record-dispatch` binds a fix dispatch only to the LIVE admission (the review's last row), so a stale admission cannot be reused. `converged` needs verdict APPROVED and no verified critical/major; `fixing` needs NEEDS_FIXES with at least one. An Agent-tool fix spawn composed by hand is held to the bound by dispatcher discipline (the admission is the record), not by a runtime check. Exhausting the bound is a **stop, never a pass**.
3a. **Exhausted → ONE reserve review, then the user (the astra reserve U3/F5).** When fix round 2's re-review (recorded `--disposition exhausted`) still has a verified critical or major finding other than a `works-against` or `constraint-question` one (reserve quota is not spent on a purpose question), run **one** review on the `escalation` seat — codex TOP @ `max` at every size, so a light cycle never hits `class_not_budgeted` — over the WHOLE cycle diff, before the loop goes to the user. It is admitted as the budget use `exhausted_review` (TOP, 1 per review, keyed on the cycle id plus the review id as the task key): `RID="$(python3 ~/.claude/skills/_meta/effort_policy.py review-id $ID | python3 -c 'import json,sys; print(json.load(sys.stdin)["review_id"])')" && PIN="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role escalation --provider codex --use exhausted_review --task-key "$RID" --project-root .)"`, then the call runs exactly as `codex_top_seat` runs its exec line (background, `codex_watch.py` with the `timeout --role escalation` cap, `codex_quota.py classify`, `-s read-only`). Its findings are VERIFIED like any other and **presented to the user with the loop's record; they NEVER start a third automatic round.** Record it with `effort_policy.py record-exhausted-review $ID --outcome ran --raised ... --verified ...` (refused unless the loop is exhausted with a blocking finding, and refused a second time; it writes no admission, so `admit-fix-round` still refuses round 3). **TOP unavailable:** `argv --use exhausted_review` exits **10** (skipped, never substituted — a Claude stand-in adds no independence to this review) with EMPTY stdout, and records the refusal. The exit-10 path carries no reset fields, so the lead asks for them with a CHECK-ONLY admit, which writes nothing and spends nothing: `DEC="$(python3 ~/.claude/skills/_meta/codex_quota.py admit --use exhausted_review --model-class top --cycle-id "$(python3 ~/.claude/skills/_meta/codex_quota.py cycle-id --project-root .)" --task-key "$RID" --project-root .)"; RC=$?` puts the decision JSON in `$DEC`. That admit exits **10** on a refusal (the only case here), so never chain it with `&&` — the chain would stop and lose the JSON: read `$DEC` whatever `$RC` is (exit 3 alone is a usage or store error). When its `reason` is `quota_exhausted` or `rate_limit_reached`, apply the #322 rule exactly as a `CODEX_QUOTA_WAIT` line: with `wait_advice` `notify`, `notify-claim` and on its exit 0 notify the user ("codex at 100% (exhausted_review) — reset please; waiting up to 30 min"); run `codex_quota.py await-reset` in a BACKGROUND call; on its exit 0 re-run the `argv --use exhausted_review` call ONCE. Any other reason, an await-reset exit other than 0, or a second refusal: there is no stand-in for this seat, so record `--outcome unavailable --unavailable-reason <token>` and surface to the user WITHOUT it.
3b. **Review against Done when.** Each reviewer brief carries the design's `## Done when` DWs — read from the design doc, never from a WP — and rules each one `met | unmet | unverified` with evidence (`unverified` counts as not met; `contract_lint.py check-verdict` checks the shape). **Done** = every DW met AND every existing gate passed (VERIFIED, D21, the security and identity gates). D21 itself is unchanged apart from goal-fit (step 1a): a verified critical or major finding is fixed even when it falls outside the DWs; only optional improvements are advisory. **Converged** = every DW met, the gates passed and no unresolved verified blocker; a loop that merely stopped did not converge.
4. **Unfixable.** A finding judged **UNFIXABLE** needs a CONCRETE reason — it contradicts a standing user decision, it is an external dependency, it is out of repo scope. A standing user decision must be quoted owner words; a `lead-inferred` constraint never qualifies, and a goal-fit finding reaches this step only with the user's ruling. The reason is recorded and shown to the user. **This is the ONLY path to "done" with an open verified critical or major finding**, apart from one closed because the owner rejected its constraint (step 1a).
5. **Minor.** Goal-fit comes first (step 1a). VERIFIED **minor** findings are then fixed in the same round when cheap, otherwise filed as tasks.
6. **Report.** `docs/reviews/YYYY-MM-DD-<cycle>-review.md`, carrying each finding's verification verdict, its disposition (`fixed <commit>` / `unfixable: <reason>` / `task #n` / `awaiting-user` / `closed: owner rejected constraint "<quote>"`), its goal-fit ruling, evidence coverage, and the reviewer models. The header carries `goal-fit: n ruled, m works-against, k constraint-question`.
7. **Owner decisions (#345).** An item put to the owner states its effect on the Purpose. If the lead has not evaluated it, it says "not evaluated" and gives no recommendation. A default "I'd remove" is not allowed.
