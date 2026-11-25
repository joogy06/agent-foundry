# Spawn brief — the one canonical block (#313)

Every spawned or unattended agent (bob, alf, challengers, reviewers, team leads, specialists,
codex/agy seats, workflow stages) starts cold: its brief is the only definition of done it will
ever see. So every spawn brief carries this block, even when a field is one line. Source:
`docs/ai-prompts-claude-5-5.md` §2.1 and design `docs/plans/2026-09-25-apply-the-contract-design.md` §3.

<!-- spawn-brief.v1 id=spawn-brief.canonical -->
```text
Goal: <outcome, for whom, why>
Context: <paths to read; settled decisions — do not reopen>
Non-goals: <out of scope; what must not change>
Open questions: material ones only (answers would change the work) — return once as
  needs.kind: clarification BEFORE starting; otherwise decide, note the assumption, proceed.
Done when: <checkable; cite DW-n where a design exists>
Stop when: done-when holds | the round bound is reached | blocked (state the blocker)
Report: what you did, what you found, what you need from the requester.
```

## How the fields are filled

- **Done when** is checkable by someone other than the author: tests named, files produced,
  criteria met. Where a design doc exists, cite its `DW-n` ids; a reviewer reads the DWs from the
  design doc, never from the brief, and rules each one `met | unmet | unverified` with evidence
  (`unverified` counts as not met).
- **Stop when** always names the bound of the loop the spawn sits in: a D21 fix round, a qa
  re-review, a challenger re-challenge. The bound is an outer-loop count (at most 2 fix rounds, then
  the user decides); exhausting it is a stop, never a pass.
- **Open questions** — only executors (bob via the Agent tool or `bob-stage`, and alf) may return a
  `needs.kind: clarification`, once per approved brief, before any mutation. Its payload:
  `{questions: [≤3, each with "work changes if…"], default_if_unanswered}`, with `status: PARTIAL`
  and `files_changed: []`. A second request becomes `user-decision`. D21 fix-round spawns and
  escalation retries may not ask: the verified finding, or the prior attempt, is their brief.
  Reviewers and challengers get the text only: they decide, note the assumption and proceed.
- **The caller persists the allowance.** The main loop answers from settled context where it can,
  bundles only the genuinely open questions into one user turn, and respawns with `Answers:` plus
  `clarification_used: true`. The asking agent writes nothing; the caller holds the allowance —
  the forge cycle directory for an Agent-tool spawn, and for `bob-stage` the outcome rows
  themselves, read back by `effort_policy.py admit-clarification --plan-id <plan>` (keyed on the
  plan, so later WPs inherit it and no flag can re-grant it).

## Where this block lives

An Agent prompt string cannot include a file, so each spawn template keeps the Non-goals, Done
when and Stop when slots **inline** and adds a one-line pointer here. The templates are pinned in
`skills/_meta/contract_lint.py` (`SPAWN_BRIEFS`), each behind a `spawn-brief.v1` marker line; the
bounded loops are pinned there too (`LOOPS`), each behind a `contract:loop` marker line.

**What the lint is, and what it is not.** It is template regression protection: it fails when a
pinned template loses a field or a pinned loop loses its bound. It is **not** universal runtime
enforcement — a brief the main loop composes by hand is only as good as the author's use of this
block. The one runtime producer that renders the block itself is `workflows/bob-stage.js`.

**Documented gap — script brief producers.** Some briefs are built by Python or shell code, not
by a Markdown template, and the lint does not reach them: `skills/_meta/audit_spawn.py`,
`skills/_meta/verification_arbiter_spawn.py`, `skills/_meta/visual_arbiter_spawn.py`,
`skills/_meta/design_drift_arbiter_spawn.py` (the cold-context verifier seats, whose bar is their
rubric and schema), and `skills/smart-config/scripts/model_policy.py` / `skills/_meta/spawn_usage.py`
(which resolve models and record usage but compose no brief). They are neither marked nor
excluded; bringing a script producer under the contract is a separate change.

**Honest limits of the enforcement (#313 D21 fix round 2).**
- The loop and clarification records are agent-writable JSONL
  (`.process-observations/spawn-runs.jsonl`). Deleting or truncating rows resets the fix-round
  count and the clarification allowance. That is a trust-model limit of an append-only file, not
  something the checks can close.
- `bob-stage` cannot see the store. It validates the admissions the dispatcher passes; a forged
  or replayed fix admission is refused at `effort_policy.py record-dispatch` (under the store's
  write lock) and flagged by `effort_rollup.py` (`unbound_fix_dispatches`). A forged
  `clarification_admission` is refused only as far as its shape can show (its state must agree
  with its flag); the allowance itself is enforced where the outcome rows are recorded.
- `admit-clarification` fails CLOSED: a dispatch of the plan with no outcome row yet makes the
  allowance `unknown`, which may run but may not ask.
- `--user-ref` on a user-directed round is provenance (who is claimed to have asked), not
  authentication.
- The D21 loop is keyed on the design doc's path: a renamed, copied or hard-linked design doc
  starts a new loop. Linked git worktrees share the main worktree's ledger.
- The Done-when parser fails closed on the forms it knows (fences, duplicate or unclassifiable
  headings, dash-like / quoted / linked / struck DW ids). Unicode confusables beyond those, and
  HTML-comment tricks beyond the duplicate-heading refusal, are not handled.
- These checks target honest mistakes, not a determined agent that can edit the store or the
  design doc.

**Clarification and mutation, checked by the dispatcher.** A stage that asks must have changed
nothing. `bob-stage` rejects a clarification whose report lists files, but a report can omit
them, so the dispatcher also compares `git status --porcelain` before and after a clarification
dispatch and treats any difference as a mutation (a `user-decision`, and the attempt counts).

## Scale by ask size

Interactive asks do not carry this ceremony (CLAUDE.md "Ask size sets the contract"): a trivial
ask is its own brief, a medium ask restates itself with a one-line done-when. Only spawns always
carry the full block. Contract prose is **never** an input to effort grading (`effort_policy.py`
grades from `complexity` and `files` only).
