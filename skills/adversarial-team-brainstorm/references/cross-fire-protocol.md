# Cross-fire Protocol — Round 2 Rules

Round 2 is where the primitive earns its name. Every team attacks every other team's Round 1 outputs.
No passive review. No "looks good." No polite critique.

---

## Target Selection

Given N teams with `n_per_team` outputs each:

- Every team attacks **every other team's outputs** (N-1 targets, `n_per_team` outputs per target).
- For a 4-team tournament with `n_per_team=6`, each attacker produces 18 attacks (3 targets × 6
  outputs), and the tournament pool sees 72 total attacks.
- Attacks are NOT cross-attacker reviewed in Round 2 — that's Round 3's job (refine) and Round 4's
  job (arbiter).

## Attack Format

Every attack is a structured record:

```yaml
target:
  team: string                   # which team produced the output
  output_index: int              # which output (1..n_per_team)
  output_summary: string         # 1-line restatement so the arbiter can verify the target
attacker: string                 # the attacking team name
severity: enum                   # critical | moderate | minor
category: enum                   # distribution | unit_economics | regulatory | saturation | 
                                 # execution_risk | no_moat | wrong_customer | timing | hallucinated_data |
                                 # other (with explanation)
issue: string                    # the specific flaw (2-4 sentences; concrete, not generic)
evidence: string                 # what makes this a real flaw, not speculation
                                 # (ideally cites data from the tournament context)
fix_proposed: string             # if the critique could be absorbed, what would the fix look like?
                                 # "no fix possible" is valid but must be justified
kill_if_unfixed: bool            # does this attack, unrefuted, kill the output?
```

## Severity Rubric

**critical** — if left unaddressed, this flaw alone makes the output a bad investment of time. Examples:
- Unit economics are negative at any reasonable scale
- Regulatory block with no legal workaround
- Fundamental distribution channel missing and none plausible
- The "pain" cited does not actually exist in the data
- The proposed mechanism violates a named physical or market constraint

**moderate** — the flaw requires a material pivot to fix but doesn't kill the proposal. Examples:
- Saturated incumbent market (needs a sharper wedge)
- The first experiment doesn't actually test what it claims
- A key assumption is unproven but testable
- The asset cited is weaker than the team claimed

**minor** — fixable in a revision without changing the core thesis. Examples:
- Naming / framing issue
- Missing a secondary market signal
- A kill criterion is too vague

The arbiter weights severity during Round 4. Moderate flaws absorbed in refine are scored the same as
never-attacked outputs. Critical flaws left unaddressed drop the output from the ranked list.

## The "Looks Good" Rejection

A Round 2 output that contains fewer than 1 attack per target, OR where attacks are uniformly
"minor," is rejected by the Round 2 validator and the attacking team is re-spawned with a sharper
prompt:

```
Your Round 2 output was rejected because {reason}.
Your attacks must include:
- At least one CRITICAL or MODERATE severity flaw per target team (not per output — per target team is minimum)
- Evidence-grounded issues, not "this might be hard"
- Specific fix_proposed or explicit "no fix possible" with reasoning
Re-run Round 2 for this target: {target_team}
```

Max 1 retry per attacker per target. If the attacker fails twice, the arbiter notes it ("attacker X
could not find flaws in team Y's outputs") and proceeds. This is a signal the attacker / lens pair
is a poor fit and should be tracked in tournament metadata.

## Attack Categories

Standard categories (callers can extend via the `category: "other"` field):

| Category | What to look for |
|---|---|
| `distribution` | No plausible channel to reach the customer at acceptable CAC |
| `unit_economics` | Negative contribution margin, unscalable cost structure |
| `regulatory` | Legal/compliance block in the target jurisdiction |
| `saturation` | Crowded market with no meaningful wedge |
| `execution_risk` | Requires capabilities the user / team does not have and cannot hire |
| `no_moat` | First competitor to copy wins, no compounding advantage |
| `wrong_customer` | Target persona does not buy, or buys differently than assumed |
| `timing` | Too early (no adopters) or too late (saturation / regulation) |
| `hallucinated_data` | The Round 1 output cited data that doesn't support the claim |
| `other` | Fallback — must include an explanation |

## Model Mix for Cross-fire

Cross-fire is the round where homogeneous models are most damaging. If all attackers are on the same
model, they will miss the same flaws. Recommended mix:

- **contrarian attacker** → Codex (critical role — often the only team that finds structural flaws)
- **at least one other attacker** → Claude or Gemini (for diversity)
- Never run all 4 attackers on the same provider

## Refine Rules (Round 3)

Each team receives the attacks on its own Round 1 outputs and produces a refined Round 3 version for
each. For every revised output:

```yaml
output_id: string
before: string                     # the Round 1 content (verbatim)
after: string                      # the Round 3 revised content
critique_absorbed:                 # list of attacks that led to edits
  - attack_index: int
    edit: string                   # what changed and why
critique_rejected:                 # list of attacks the team declined to absorb
  - attack_index: int
    reasoning: string              # why the attack does not apply (or is wrong)
kill_criteria_refined: list[string]  # hardened from Round 1 drafts
first_experiment_refined: string
```

**Rules:**
1. Every attack must be acknowledged — either absorbed or rejected with reasoning. Silent ignoring
   is a refine failure.
2. Teams may not delete their own Round 1 output in Round 3 — if they believe the attacks are fatal,
   they mark the output `status: "withdrawn"` and state the reason. The arbiter then excludes it.
3. A revision cannot make the output worse (arbiter judges). If the refine weakens the proposal,
   Round 1 content is kept.
4. Kill criteria are sharpened, not softened. A refined output has more specific kill criteria than
   the Round 1 draft, not fewer or vaguer.

## What cross-fire is NOT

- **Not a code review.** This primitive isn't checking syntax.
- **Not a politeness optimization.** Sycophantic critique ("great idea! one small thing...") is
  rejected.
- **Not a consensus machine.** The goal is NOT to arrive at one answer; it's to produce a ranked
  list with explicit survival conditions.
- **Not a voting system.** Arbiter doesn't count votes; it evaluates which attacks were absorbed and
  which outputs survived.
