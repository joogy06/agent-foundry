# Forge reference — spec review

Checklist steps 8b and 8c — previous: step 8a, the contract map; next: step 8d, the hard rules checkpoint, then step 9, spawn bob.
When this file is read, return to the SKILL.md checklist.

"Model selection per spawn" is in `references/02-design-team.md`; the reviewer's model command is repeated in Stage 2 below.

## Contents

- Stage 1 — Self-review (inline)
- Stage 1.5 — External-finding verification, then goal-fit
- Fast path — the `ratify-design` workflow
- Stage 2 — Subagent review (dispatched), then the user reviews the spec

## Spec Review

After writing the design doc (step 8), run a two-stage review:

**Stage 1 — Self-review (inline):**
1. **Placeholder scan:** Any "TBD", "TODO", incomplete sections, vague requirements? Fix them.
2. **Internal consistency:** Do any sections contradict each other? Does the architecture match the feature descriptions?
3. **Scope check:** Is this focused enough for a single implementation plan, or does it need decomposition?
4. **Ambiguity check:** Could any requirement be interpreted two different ways? Pick one and make it explicit.

Fix issues inline. Then proceed to stage 2.

**Stage 1.5 — External-finding verification (S030-quickwins #37):**

If Stage 2 will dispatch external-model reviewers (Codex, agy), or if
external-model findings already exist from earlier in the design (Step 4b
challengers, the agy analyst), run the **verification pass** BEFORE
merging any of those findings into the consolidated review report.

For each external-model finding that cites a specific code/file/symbol:

1. Open the cited artifact and confirm the citation actually exists.
2. Mark the finding `VERIFIED` (citation + claim match), `FALSE-POSITIVE`
   (citation does not match the claim — e.g. spec text contradicts the
   model's interpretation), or `NEEDS-FOLLOWUP` (citation is unclear or
   needs human judgement).
3. Only `VERIFIED` findings flow into the consolidated review report. Move
   `FALSE-POSITIVE` findings to a separate "False positives, with grep
   evidence" section. Move `NEEDS-FOLLOWUP` to a third section for the
   user to adjudicate.

Codex and agy have observed false-positive rates of 60-65% on adversarial
spec/design review (DLP pilot 2026-04-09; S030-init WP-0). Skipping this
verification pass would propagate model hallucinations into the design doc
and waste user attention. The protocol — including worked examples of how
to distinguish a real bug from a model misread — lives at
`references/external-finding-verification.md`.

**Fast path — `ratify-design` workflow (S055, optional, main-loop only).**
When the orchestration tier (Step 4b) is the fast path (`probe.sh get
capabilities.workflow_tool` true AND `probe.sh context == main-loop`), Stage 1.5
MAY run as the `ratify-design` saved workflow, which MECHANIZES this verification
pass: deliberate (child `cross-cli-deliberation` — ratify-design is invoked
TOP-LEVEL via `Workflow({name})`, NEVER via `workflow()` from another script, so
its child consumes the single nesting level, WP-2 finding 7) → extract-findings
(substring-checks every quote against the ballot transcript; non-matching ⇒
`extraction_suspect` ⇒ NEEDS-FOLLOWUP) → verify-findings (ONE cold-context
verifier PER cited finding; deterministic-first `grep -n -F "<quote>"` at the
cited path — quote absent verbatim ⇒ FALSE-POSITIVE `citation-not-found`,
MANDATORY; a VERIFIED verdict without `cited_text_verbatim` + a grep line is
SCHEMA-INVALID) → assemble (`ratification-record.v1` with the per-run measured
`fp_rate`). Budget exhaustion mid-verify ⇒ ALL remaining findings NEEDS-FOLLOWUP
(never auto-VERIFIED) + `degraded: true`. The workflow NEVER edits the doc;
forge merges VERIFIED findings inline after goal-fit (below) and spot-checks (re-greps ≥1 VERIFIED
finding per run). External consultant transcripts are PRE-LAUNCHED inline
(agy is unreachable from stages, WP-2). On any fast-path failure, fall back to
the inline Stage-1.5 protocol above (byte-identical, portable).

**Goal-fit, after verification (#345).** Verification asks whether the citation is real. Goal-fit then asks whether acting on the finding serves the design's Purpose. The main loop asks it of every VERIFIED finding: every severity, owner-decision items included, from every reviewer (Claude, Codex, agy). When the fast path ran it comes after `ratify-design` returns; the workflow and its schema do not change. It judges the **fix**, never the existence of the defect. With `Purpose: none stated` it is skipped and the report says so.

- **First branch, before any ruling: `constraint-question`.** A finding that exists only because of a `lead-inferred` constraint is not ruled. It goes to the owner as a question about the constraint, with no fix proposed. This branch comes before the must-resolve list, except for security, data loss and payment findings.
- **Otherwise rule the proposed fix** `serves`, `neutral` or `works-against`. `serves` and `neutral` take the existing path.
- **`works-against`, for a real defect:** look for a fix that resolves the defect without harming the Purpose. If one exists it is the fix for a critical or major, and is offered, not applied, for a minor or an owner-decision item. If none exists the finding goes to the user labelled `works-against`, with both sides and no default fix, unless it is on the must-resolve list.

The steps and two worked examples are in `references/external-finding-verification.md`, step 5. The limits on the ruling are in `references/10-close-out.md`, step 1a, and they apply here too.

**Stage 2 — Subagent review (dispatched):**
Dispatch a spec reviewer subagent on the protected `code_reviewer` model. It resolves through the seat registry, never smart-config or a project policy (see "Model selection per spawn"):

```
# m=$(python3 ~/.claude/skills/_meta/seat_model.py model --role code_reviewer --provider claude)
# Non-zero exit / empty m: the registry is broken — fix it; never dispatch the reviewer on the inherited model.
<!-- spawn-brief.v1 id=forge.spec-reviewer -->
Agent(subagent_type="general-purpose", model=m):
"You are a spec document reviewer. Verify this spec is complete and ready for planning.
Spec to review: [SPEC_FILE_PATH]
Purpose: [the design doc's Purpose line, verbatim, or "none stated"]
Constraints: [each with its label, or "see design doc"]
Goal: say whether the spec can be planned and built as written.
Non-goals: redesigning; new features; style; file changes.
Open questions: none may be returned — decide, note the assumption, proceed.
Done when: Status is given, and each issue names its section and why it would cause a real problem;
  the spec's `## Done when` DWs are checked to be numbered and checkable.
Stop when: the spec is read once through; this is iteration [n] of at most 3.
Brief block: skills/_meta/spawn-brief.md

Check for: completeness (TODOs, placeholders), consistency (contradictions),
clarity (ambiguous requirements), scope (single plan or needs decomposition),
YAGNI (unrequested features). Only flag issues that would cause real problems
during implementation. Approve unless there are serious gaps.
Flag a finding whose natural fix would work against the Purpose.
Treat a `lead-inferred` constraint as challengeable, not binding.

Output: Status (Approved / Issues Found), Issues (if any), Recommendations."
```

If issues found: rule goal-fit on each first (Stage 1.5: a `constraint-question` goes to the owner with no fix proposed, a `works-against` fix takes its route), fix the rest and re-dispatch (max 3 iterations). Then present to user:

> "Spec written to `<path>`. Please review before we proceed to implementation."

Wait for user approval before continuing.
