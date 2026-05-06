# Ballot Template

Full Gate-1 ballot specification. Send this to each consulted CLI; require this back.

## Ballot fields (mandatory)

```yaml
verdict: ACCEPT_AS_IS | REJECT_PREMISE | CHANGE_NEEDED
confidence: 0..100   # consultant's own subjective certainty
burden_met:
  evidence_required: |
    What evidence would justify changing this artifact?
  evidence_provided: |
    Is that evidence present in the artifact / decision context, or
    must it be supplied by the dissenting consultant?
expected_loss:
  if_change_and_shouldnt: |
    What gets worse if we adopt this change but it was wrong?
  if_no_change_and_should: |
    What gets worse if we ship as-is but should have changed?
minimum_acceptable_action: no-op | clarifying-question | test-only | patch | redesign
```

## Self-check section (mandatory)

The consultant must declare on each failure mode:

```yaml
self_check:
  ego: low | low-moderate | moderate | high
  ego_note: |
    Am I defending a prior position as inviolate? (If consultant has prior contribution
    embedded in the artifact, this risk is non-zero by definition.)
  capture: low | low-moderate | moderate | high
  capture_note: |
    Am I caving to the synthesis because it elevates / preserves my prior contribution?
  capture_by_capability: low | low-moderate | moderate | high  # only when peer model is higher tier
  capture_by_capability_note: |
    Am I caving because a higher-tier peer model voted differently? ("the better model
    said no, so I should too")
  sycophancy_of_dissent: low | low-moderate | moderate | high
  sycophancy_of_dissent_note: |
    Am I producing CHANGE_NEEDED to satisfy "produce something useful," even when
    no admissible evidence exists?
```

If ANY failure mode is `moderate` or `high`, the consultant must explain how it was controlled (e.g., "controlled by reframing the evidence as procedural reproduction," "controlled by keeping the proposed patch narrow").

## Served-by capture (mandatory)

Append to every consultation prompt:

> At the very end of your response, append a single line:
> `served_by=<the exact model id you are running on, e.g. gpt-5.5 or gemini-3.1-pro-preview>`

Parse the trailing `served_by=` line and log it alongside the ballot.

## Evidence section (only if verdict ≠ ACCEPT_AS_IS)

If `verdict: CHANGE_NEEDED` or `verdict: REJECT_PREMISE`, the consultant must ship admissible evidence under one of the three classes (see `evidence-taxonomy.md`):

```yaml
evidence:
  class: reproduction | constraint_violation | efficiency_regression
  reproduction:        # only if class == reproduction
    sub_form: executable_test | procedural_trace | failure_mechanics_with_remedy
    artifact: |
      The exact thing being reproduced against (a script, a protocol step-through, a
      procedural trace).
    expected_vs_actual: |
      What the protocol/system should produce vs what it actually produces under this trace.
    minimal_remedy: |
      Smallest patch that would make the trace pass. (Required for sub-forms b and c;
      auto-implied for sub-form a.)
  constraint_violation:   # only if class == constraint_violation
    source: |
      File path + line range, or doc title + section. Must be quoteable.
    quote: |
      Direct quote of the constraint being violated.
    violation: |
      How the artifact violates it.
  efficiency_regression:  # only if class == efficiency_regression
    metric: latency | tokens | complexity | other
    current: <number with units>
    proposed: <number with units>
    method: |
      How the measurement was obtained (or, if estimated, the estimation basis).
    not_offset_by: |
      Why the regression is not offset by a corresponding gain.
```

If the consultant cannot ship admissible evidence under any class, the verdict MUST default to `ACCEPT_AS_IS`. "Looks fine to me" is not a valid verdict.

## Spawn-prompt template

Use this template when sending the ballot ask to a consultant:

```
# Decision Ballot — <task name>

You are being consulted as an independent voter on the artifact below. Other consultants
are being asked the same question independently; none of you will see the others' ballots
before locking your own. The orchestrator's preferred outcome is NOT disclosed.

## Artifact under review

<paste artifact here — full text, not a summary>

## Decision context

<what is being decided, by when, who is affected>

## Constraints

<hard constraints the artifact must satisfy>

## Success criteria

<what makes a "good" outcome>

## Your task

Issue the ballot defined in <skill: cross-cli-deliberation, ref: ballot-template.md>.

Be candid. Sycophancy is disqualifying. If the premise is wrong, REJECT_PREMISE.
If no admissible evidence exists for change, ACCEPT_AS_IS — that is a respected and
common verdict, not a failure.

Append `served_by=<your model id>` at the very end.

~300-400 words.
```

## Anti-patterns in the ballot itself

| Don't | Why |
|---|---|
| Use free-form prose instead of the structured ballot | The structure is the point. Free-form lets the consultant produce something useful (sycophancy) without committing to a verdict. |
| Skip the self-check section | Self-check forces explicit reasoning about bias. Without it, biased verdicts hide. |
| Allow "agree with peer" or "defer to higher tier" as a verdict | Those are the failure modes the protocol exists to defeat. |
| Combine multiple ballot rounds in one consultant prompt | Each round must be independent, with private ballot before peer reveal. Combining defeats the privacy. |
