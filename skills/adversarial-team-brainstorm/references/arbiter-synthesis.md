# Arbiter Synthesis Protocol — Round 4 Rules

The arbiter is the final synthesis agent. It reads every Round 3 refined output, every attack
history, and every rejection reasoning, then produces the final ranked list.

**The arbiter is NOT just another team.** It has authority to filter, hybridize, and score — but it
does not generate new outputs from scratch. Its job is to judge survival, not to invent.

---

## Arbiter Mode (top-level switch)

`arbiter_mode` selects WHAT the arbiter produces. It is the **top-level switch**; the Steps below are
written for the default and are overridden per-mode where noted.

| `arbiter_mode` | Produces | Consults `output_class`? | Primary caller |
|---|---|---|---|
| `ideas` (**default**) | Ranked list of surviving outputs (tournament semantics) | **YES** — the `output_class` sub-switch (Step 7) operates unchanged beneath it | ATB inline, founder-ideation, alf, adversarial-tournament workflow |
| `decision` | ONE selected decision + a dissent record (not a ranked list) | **NO** | avengers (ratification / generative families) |
| `deliverable` | ONE consolidated deliverable + a dissent record | **NO** | avengers (deliverable outcome) |
| `forge_brief` | ONE `avengers_brief` block (build path) + a dissent record | **NO** | avengers (build path → forge Step 3 intake) |

**An absent `arbiter_mode` defaults to `ideas`** — existing callers are untouched by construction.
Under `arbiter_mode: ideas`, EVERYTHING in this document behaves exactly as it did before this switch
was introduced: Steps 1–7 run verbatim, the `output_class: ideas|signals|proposals|designs` sub-switch
(Step 7) is the only per-output-shape control, and the output is the ranked list (see Arbiter Output
Format). This is the semantic-equivalence guarantee — no behavior change for tournament callers.

**The three non-`ideas` modes do NOT consult `output_class` at all.** They replace the ranked-list
output with a single-decision-plus-dissent schema (see "Non-`ideas` modes" below), and they key
survivor selection on the deliberation's obligation ledger rather than on tournament rounds. These
modes are used by `avengers`; the four tournament callers never set `arbiter_mode`.

### Caller sweep (regression contract)

| Caller | `arbiter_mode` | Behavior |
|---|---|---|
| ATB inline | `ideas` (default, unset) | unchanged tournament ranked list |
| founder-ideation | `ideas` (default, unset) | unchanged; still passes its kill-criteria-library reference |
| alf | `ideas` (default, unset) | unchanged adversarial-review ranking |
| adversarial-tournament workflow | `ideas` (default, unset) | unchanged |
| avengers | `decision` \| `deliverable` \| `forge_brief` | new single-decision + dissent path |

None of the four pre-existing callers set `arbiter_mode`; they inherit `ideas` and are semantically
unchanged. This table is the caller-sweep regression contract enforced by
`tests/test_arbiter_mode_regression.py`.

---

## Arbiter Model Selection

- Default: **Claude** (good at long-context synthesis across multiple Round 3 documents)
- Alternative: **Antigravity (agy)** (when cross-fire involved >50 total attacks — large-context synthesis helps)
- **Never**: the same model as the contrarian team (correlated blind spots at the final gate)

---

## Step 1: Survivor Selection

For each Round 3 output, decide if it survives:

1. **Withdrawn outputs** (team marked `status: "withdrawn"` in refine) → dropped
2. **Outputs with unabsorbed critical attacks** (Round 2 severity=critical, Round 3 did not absorb
   AND the rejection reasoning is weak) → dropped
3. **Outputs with no grounding** (if `kill_criteria_required: true` and no `data_sources`) → dropped
4. **Outputs with duplicate content across teams** (cosine similarity > 0.85 in content) →
   candidates for hybridization (see Step 2)
5. **All others** → survive to ranking

If fewer than `max_total_outputs` survive, that's fine — the primitive returns what it has. Do NOT
inflate the list with marginal outputs to hit a target count.

## Step 2: Hybridization

When two or more teams produced similar outputs, the arbiter MAY hybridize them:

- **When to hybridize**: if the outputs' content overlaps >60% AND the kill criteria and first
  experiments are complementary (not contradictory)
- **When NOT to hybridize**: if the teams disagree on core mechanism, customer, or unit economics
  — keep them as separate entries
- Hybrids get `source_team: "hybrid(A+B)"` and combined kill criteria + first experiments + attack
  history

Hybridization is the main value-add of the arbiter. It converts the "many teams, correlated outputs"
failure mode into a concentrated best-of-breed list.

## Step 3: Kill Criteria Attachment

Every surviving output must have ≥2 kill criteria in the final list.

Sources of kill criteria, in order of preference:
1. **Refined kill criteria from Round 3** (the team's own sharpened version)
2. **Absorbed critical attacks from Round 2** (attack categories converted to kill criteria:
   "distribution block: fails if CAC > $X" becomes a kill criterion)
3. **Standard library kill criteria** for the output_class (if caller provided one — e.g.,
   `founder-ideation` passes a kill-criteria-library reference for generic venture kills)
4. **Arbiter-generated kill criteria** (last resort — the arbiter writes 1-2 based on patterns it
   sees across the tournament)

If the arbiter cannot produce 2 kill criteria for an output after exhausting sources 1-4, the output
is DROPPED. Do NOT fake kill criteria. A kill criterion that cannot be tested is worse than none —
it produces false confidence.

## Step 4: Confidence Scoring

Assign one of: `high` / `medium` / `low` / `speculative`.

**The grounding rule:** No output can be promoted above `speculative` without ≥1 piece of external
data grounding in `data_sources`. This is a HARD rule enforced by the primitive.

Within the grounded subset, the scale is:

| Confidence | Criteria |
|---|---|
| `high` | 2+ data sources; absorbed all moderate/critical attacks OR attacks were convincingly refuted; kill criteria are specific + testable; first experiment is runnable in <4 weeks and has a clear pass/fail |
| `medium` | 1 data source OR 2+ but weaker; absorbed most attacks; kill criteria are specific; first experiment runnable in <8 weeks |
| `low` | 1 data source, weaker grounding; some attacks unabsorbed but the team reasoned about them; kill criteria vague but testable |
| `speculative` | No data source, OR data source disputed in cross-fire, OR multiple unabsorbed critical attacks, OR kill criteria untestable |

**Confidence can only be lowered by the arbiter, not raised.** A team's Round 1 self-rating is
input, not authority.

## Step 5: Ranking

Rank surviving outputs by:
1. Confidence tier (high > medium > low > speculative)
2. Within tier: number of orthogonal grounding sources (more = better)
3. Within same grounding: fewer unabsorbed moderate attacks
4. Within same attack profile: arbiter's judgment call on strategic fit (documented in `arbiter_notes`)

The ranking is NOT a popularity contest. It is a survival + grounding scoring.

## Step 6: Minority Report Preservation

If any team strongly disagreed with the arbiter's ranking in Round 3 (e.g., the contrarian team
argued the trend-first team's #1 output was fundamentally wrong), the arbiter MUST note this in
`arbiter_notes`:

```
## Minority Reports
- Contrarian team argued output #3 (trend-first) is false-signal: [summary of contrarian critique].
  Arbiter ranked it #3 anyway because [reasoning], but flagged as medium-confidence pending [test].
```

Minority reports are load-bearing. They are the primitive's defense against groupthink at the final
gate.

## Step 7: Output Class Sanity Check

**This step is the `output_class` sub-switch and applies ONLY under `arbiter_mode: ideas` (the default).**
The rules for the four `output_class` values below are unchanged from before the `arbiter_mode` switch
existed (semantic equivalence). The three non-`ideas` modes skip this step entirely.

If `output_class: ideas`:
- every output has kill_criteria + first_experiment + data_sources → enforced
- arbiter_notes mentions any output that failed the check and was dropped

If `output_class: signals`:
- every output has data_sources → enforced
- kill_criteria and first_experiment are NOT required (signals are hypotheses attached to raw
  data, not investable proposals)

If `output_class: proposals` or `designs`:
- every output has kill_criteria + first_experiment → enforced
- data_sources recommended but not required

Callers that need different rules pass a custom `output_class` and document the rules in their own
skill.

---

## Non-`ideas` modes (`decision` | `deliverable` | `forge_brief`)

These modes are used by `avengers`. They do NOT run tournament rounds and they do NOT consult
`output_class`. They consume a deliberation transcript + obligation ledger and produce ONE outcome plus
a **mandatory dissent record**. Steps 1–7 above (survivor selection by tournament round, hybridization,
the `output_class` sanity check, ranking) are REPLACED by the rules in this section.

### Candidate units per mode

- `decision`: the candidate units are the seats' converged **private final positions**, not team outputs.
- `deliverable`: the candidate unit is the single consolidated artifact drafted from the surviving position.
- `forge_brief`: the candidate unit is the front-runner **direction** plus the ruled-out approaches.

### Obligation-keyed survival rules (replaces Step 1 for these modes)

Survivor selection is keyed on the **obligation ledger**, not tournament rounds:

1. A position carrying an `open` or `stalemate` obligation against it cannot be selected as the outcome
   unless the arbiter records WHY it survives the open obligation.
2. `conceded` positions are dropped.
3. `stalemate` obligations flow into the dissent record as **unresolved dissent** — never silently
   dropped, never converted to consensus (termination guarantee: stalemate → dissent, not deadlock).
4. The arbiter does NOT invent novel proposals — it selects among positions the seats actually argued.

### Grounding & kill-criteria mapping

- **Grounding rule (unchanged spirit):** no confidence above `speculative` without ≥1 external grounding
  source (the same HARD rule as Step 4).
- `decision` / `forge_brief`: ≥2 kill-criteria / trip-wires attached to the selected outcome, each
  actionable ("reopen if X").
- `deliverable`: kill-criteria optional; the dissent record is still mandatory.

### Output schema (single decision + dissent — NOT a ranked list)

```yaml
arbiter_mode: decision            # or deliverable | forge_brief
decision:                         # renamed `deliverable:` / `avengers_brief:` for the other two modes
  statement: string
  selected_from_seat: string
  confidence: high|medium|low|speculative
  kill_criteria: list[string]     # >=2 for decision / forge_brief
  grounding: list[string]
dissent_record:                   # ALWAYS present, even when unanimous
  convergence_margin: unanimous | converged N-M | arbiter-broke-tie
  entries:
    - seat: string
      position: string
      status: open|stalemate|minority
      trip_wire: string
  honesty_line: string            # printed when unanimous + empty dissent
meta:
  obligations_open: int
  obligations_stalemate: int
  seats_used: list[string]
```

For `arbiter_mode: forge_brief` the `decision:` block is replaced by an `avengers_brief:` block whose
shape MUST match the forge Step 3 `came_from_avengers` intake: `problem`, `constraints`,
`success_criteria`, `ruled_out_approaches`, `recommended_direction` (advisory, not locked), `dissent[]`,
`confidence`, `deliberation_record` (path, never inlined), with `contract_map_signed: false` and
`bob_ready: false` **mechanically always-false** (avengers never signs a map or marks anything
bob-ready). See `skills/forge/SKILL.md` Step 3.

---

## Arbiter Output Format

```yaml
ranked_outputs:
  - rank: 1
    content: string
    source_team: string            # or "hybrid(A+B)"
    confidence: enum
    kill_criteria: list[string]    # min 2
    first_experiment: string
    data_sources: list[string]
    attack_history: list[...]      # Round 2 attacks on this output (summarized)
    revisions:
      before: string
      after: string
      critique_absorbed: list[...]
      critique_rejected: list[...]
arbiter_notes: |
  ## Observed patterns
  {across the tournament}
  
  ## Surviving outputs
  {survivor count vs initial count; dropped outputs with reasons}
  
  ## Hybridizations
  {which teams merged and why}
  
  ## Minority Reports
  {any team's dissent from final ranking}
  
  ## Confidence distribution
  {how many at each tier; why no `high` if that's the case}
meta:
  rounds_run: 4
  teams_used: list[string]
  total_raw_outputs: int
  total_final_outputs: int
  drop_reasons:
    withdrawn: int
    unabsorbed_critical_attacks: int
    no_grounding: int
    duplicate_not_hybridized: int
  model_mix:
    team_problem_first: claude
    team_contrarian: codex
    arbiter: claude
```

---

## Failure Modes for the Arbiter

| Failure | Symptom | Response |
|---|---|---|
| Arbiter refuses to drop outputs (completion bias) | Final list is identical to Round 3 input | Re-prompt with "drop at least {floor}% of outputs that lack grounding" |
| Arbiter inflates confidence to `high` without grounding | Grounding rule violated | Reject output, re-prompt with grounding rule restated |
| Arbiter hides minority reports | `arbiter_notes` has no "Minority Reports" section despite Round 2 showing severe disagreement | Re-prompt explicitly for minority reports |
| Arbiter invents kill criteria not traceable to the tournament | Kill criteria appear that don't match any Round 2 attack or Round 3 refine or library entry | Reject, re-prompt to cite source for every kill criterion |
| Arbiter over-hybridizes (merges non-overlapping ideas) | Hybrids destroy distinct insights | Reject merges with <60% content overlap, keep teams separate |
