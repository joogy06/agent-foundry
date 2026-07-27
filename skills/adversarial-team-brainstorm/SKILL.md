---
name: adversarial-team-brainstorm
description: >
  Use when a question needs structured-contention exploration across multiple parallel founding / design
  / analysis lenses with cross-fire critique, not a single-agent monologue. Runs a reusable multi-team
  tournament: diverge (N teams generate independently) → cross-fire (teams attack each other) → refine
  (teams revise) → arbiter (synthesizes winners, attaches kill criteria). Reusable by forge (design
  exploration), alf (review cycles), agent-teams (tournament mode), founder-ideation, and any caller
  that needs adversarially-validated outputs with explicit kill criteria. Trigger on: "generate N ideas
  for X", "tournament", "cross-fire review", "four teams on this problem", "adversarial brainstorm",
  "kill-criteria ranked outputs".
---

# Adversarial Team Brainstorm

Multi-team tournament primitive. Spawns N parallel teams with distinct lenses, runs them through a
structured four-round process, and returns ranked outputs with attached kill criteria, first experiments,
and cross-fire attack histories. Reusable by any caller — not tied to a specific domain.

**Scope:** Pure prompt-orchestration primitive. Does NOT own the question, the data feeds, or the
output storage. The caller owns those.

**Callers:**
- `forge` — design exploration tournaments (alternative to the current single-team exploration)
- `agent-teams` — "tournament" mode exposing this primitive for generic orchestration
- `founder-ideation` — generates business ideas with adversarial team quad
- `alf` — adversarial review of skills/code/products
- Any caller that passes a question + team angles + optional context

---

<HARD-RULE>
**Parallel diverge is mandatory.** Round 1 teams MUST run in parallel, not sequentially. Sequential
execution defeats the entire point of divergence — the later team sees the earlier team's output and
anchors to it. Always spawn all teams simultaneously via `Agent` tool (Claude) / `codex exec` (Codex) /
`agy -p` (Antigravity) calls batched in a single message.
</HARD-RULE>

<HARD-RULE>
**Cross-fire must attack.** In Round 2, every attacking team MUST produce ≥1 flaw per output from every
team it reviews. A "looks good" verdict is a failure mode — the attacker is punting. If a team cannot
find a flaw, it must either (a) propose a sharper test that would surface one, or (b) explicitly mark
the output as "attack-resistant under {constraint}" and name the constraint that makes it so. Generic
"this is solid" verdicts are rejected by the arbiter.
</HARD-RULE>

<HARD-RULE>
**Kill criteria are mandatory, not optional.** The arbiter refuses to output a ranked list without
≥2 kill criteria per output. The primitive exists to defeat "polished guru" failure mode — without
kill criteria, every output is equally defendable and equally useless. If the caller passes
`kill_criteria_required: false`, this primitive refuses to run.
</HARD-RULE>

<HARD-RULE>
**Refine round must show before/after.** Round 3 (refine) must produce explicit before/after for each
revised output. No silent rewrites — the attack history must be traceable into the revised version
so the arbiter can judge whether the critique was absorbed or dismissed.
</HARD-RULE>

<HARD-RULE>
**Grounding requirement for high-confidence promotion.** The arbiter cannot promote an output above
`speculative` confidence without ≥1 piece of external data grounding (from `context` feeds — Reddit,
GDELT, user-supplied data, prior wiki entries, etc.). Without grounding, max confidence is
`speculative`. This is the primary mechanism against LLM-vs-LLM hallucination.
</HARD-RULE>

---

## Invocation Contract

### Input

```yaml
question: string                # "Generate 20 SaaS ideas for accountants"
team_angles: list[string]       # lens names, see references/team-angles.md
rounds: int                     # default 4 (diverge, cross-fire, refine, arbiter)
n_per_team: int                 # outputs each team should produce in Round 1
context: map                    # optional data feeds keyed by name
                                # e.g. { reddit_pain_data: ..., gdelt_inflection_data: ..., user_assets: ... }
kill_criteria_required: bool    # default true; false rejected (see HARD-RULE)
team_model_override: map        # optional: { contrarian: "codex", trend_first: "agy" }
                                # default all teams run on Claude
max_total_outputs: int          # optional cap after arbiter synthesis (default = n_per_team * len(team_angles))
output_class: string            # "ideas" (default) | "signals" | "proposals" | "designs"
                                # affects which hard rules apply downstream — ideas require kill_criteria
                                # and first_experiment; signals require only data citation
```

### Output

```yaml
ranked_outputs:
  - content: string              # the idea / proposal / design
    rank: int                    # 1..N
    source_team: string          # which lens produced it, or "hybrid(A+B)" if merged
    kill_criteria: list[string]  # what would invalidate this (min 2)
    first_experiment: string     # smallest test of viability (1-2 sentences)
    attack_history:
      - from_team: string
        severity: enum           # critical | moderate | minor
        issue: string
        fix_proposed: string
    revisions:
      before: string             # the Round 1 version
      after: string               # the Round 3 refined version
      critique_absorbed: list[string]  # which attacks led to which edits
    confidence: enum             # high | medium | low | speculative
    grounding_sources: list[string]  # keys from input.context that supported this
arbiter_notes: string            # synthesis rationale, patterns observed, surviving minority reports
meta:
  rounds_run: int
  teams_used: list[string]
  total_raw_outputs: int         # n_per_team * len(team_angles) before trim
  total_final_outputs: int
  duration_seconds: int
  model_mix: map                 # which model ran which team
```

---

## The Four Rounds

### Round 1: Diverge

Each team generates `n_per_team` outputs **in parallel** and **without seeing the others' work**.

**Per-team spawn prompt template:**

```
You are Team {NAME}, running the {LENS} lens.
Your lens definition: {READ references/team-angles.md for {LENS}}

Question: {QUESTION}

{IF context[team_data_key] exists for this lens:}
Data grounding (you MUST cite at least one source from this feed in each output):
{INLINE THE DATA FEED, e.g. Reddit pain posts, GDELT events, user assets}
{END IF}

Produce exactly {N} outputs. For each output:
1. content: the idea/proposal/design
2. initial_kill_criteria: 2 things that would invalidate it (draft — arbiter will refine)
3. first_experiment: smallest test of viability
4. data_sources: list of grounding cites (reddit:sub/id, gdelt:event_id, user_asset:key, or "unfounded")

CRITICAL:
- Do NOT hedge. Commit to specific proposals, not option lists.
- Do NOT copy the question into the output.
- Do NOT use the other teams' work — you haven't seen it and that's intentional.
- If data grounding is required and you cannot find a cite for an output, mark it "unfounded"
  and the arbiter will filter it.
```

Spawn all teams simultaneously in one message (Claude via `Agent`, Codex via `codex exec`, Antigravity
via `timeout 600 agy --sandbox -p "..." < /dev/null` as a background Bash task — `--sandbox` is
mandatory for these advise-only calls, per the `antigravity-cli` SANDBOX RULE).

### Round 2: Cross-fire

Each team receives the other teams' Round 1 outputs and must attack them. See
`references/cross-fire-protocol.md` for the full protocol. Summary:

- Each team attacks **every other team's outputs** (N-1 targets)
- Minimum ≥1 attack per output (no "all good" verdicts — HARD-RULE)
- Attacks must include: severity (critical / moderate / minor), issue, fix_proposed
- Codex-powered teams are preferred for the `contrarian` / devil's-advocate role

Attacks MUST be structured — free-form commentary is rejected.

### Round 3: Refine

Each team receives the attacks on its own outputs and revises. See
`references/cross-fire-protocol.md#refine-rules` for rules.

- Every revised output must include `before` + `after` + `critique_absorbed` list
- A team may mark an attack as "rejected" with reasoning — not every critique is absorbed, but
  ignoring it silently is a failure mode
- Kill criteria are sharpened during refine (Round 1 drafts → Round 3 hardened versions)

### Round 4: Arbiter Synthesis

A single arbiter agent (Claude by default; caller may override) reads all Round 3 outputs + attack
histories and produces the final ranked list. See `references/arbiter-synthesis.md` for the full
protocol. Summary:

- Identify surviving outputs (did not receive critical attacks, or absorbed them in refine)
- Hybridize where cross-team ideas complement (mark `source_team: "hybrid(A+B)"`)
- Attach final kill criteria (minimum 2 per output — HARD-RULE)
- Assign confidence: `high` / `medium` / `low` / `speculative`
  - `speculative` is the max if there is no external data grounding
- Preserve minority reports: if one team strongly disagrees with the ranking, the arbiter notes
  it in `arbiter_notes` rather than hiding it
- Filter any outputs marked `unfounded` that cannot be hybridized with a grounded output

---

## Team Angles

See `references/team-angles.md` for the full library. Common angles:

| Angle | Typical use | Best model |
|---|---|---|
| `problem-first` | Ideation from user pain data | Claude |
| `asset-first` | Ideation from user's existing capabilities / distribution | Claude |
| `trend-first` | Ideation from macro event velocity (GDELT inflections) | Claude |
| `contrarian` | Attacks consensus, finds counter-positioning | Codex (default) |
| `first-principles` | Reasoning from physics / unit economics / constraints | Codex |
| `arbitrage` | Finds price / information / capability gaps | Codex |
| `blue-ocean` | Creates new demand categories | Antigravity (agy) |
| `constraint-inverted` | Starts from what's forbidden / impossible today | Claude |

Callers pass the list they want; the primitive does NOT prescribe which angles to use — that is
domain knowledge owned by the caller.

---

## Fast path — `adversarial-tournament` workflow (S055, optional, main-loop only)

When the orchestrator is the main loop with the orchestration surface available
(`probe.sh get capabilities.workflow_tool` true AND `probe.sh context ==
main-loop` — the ONLY capability API; `capabilities.*` alone never authorizes,
session files are shared with subagents), the four rounds MAY run as the
`adversarial-tournament` saved workflow: parallel `diverge` (one isolated agent
per team angle, `team-output.v1` with `initial_kill_criteria` minItems:2 — role
collapse mechanically prevented) → parallel `crossfire` (each attacker sees ONLY
other teams' outputs, `attack-set.v1` minItems:1 per target makes "all good"
schema-invalid; the script validates target coverage with a deterministic single
retry on a sycophantic miss) → `refine` → single `arbiter` (`tournament-result.v1`;
the script forces confidence to `speculative` when `grounding_sources` is empty —
DOWNGRADE only, never upgrade). Below the budget floor before `refine` ⇒ skip
refine, cap confidence `low`, `meta.degraded_to: "quick_tournament"` (documented
mode, not silent loss). The script REFUSES configs that would drop kill criteria.

Stays inline: question scoping, angle selection, grounding-feed acquisition
(reddit/gdelt run BEFORE and passed as `context_paths`), final selection, all
user decisions. External team overrides ride W-EXT wrappers with args-supplied
commands. The schemas live in `schemas/`; `design-tournament` does NOT wrap this
workflow (B's ruling — standalone callers are this skill's own inline
invocations). On any fast-path failure, fall back to the inline four rounds below.

## Implementation Notes

### Spawning Teams

**Claude teams** — use `Agent` tool with `subagent_type: "general-purpose"` and a spawn prompt that
includes:
1. The team lens definition (read from `references/team-angles.md`)
2. The question
3. Any data feeds from `context`
4. The Round 1 output format

**Codex teams** — use `codex exec` (preferred for `contrarian`, `first-principles`, `arbitrage`
angles):

```bash
timeout 600 codex exec --ephemeral --skip-git-repo-check -s read-only \
  -o "$WORK/team-contrarian-round1.md" \
  "You are the contrarian team. Question: $QUESTION. Data: see $CONTEXT_FILE.
   Produce $N outputs per the format in $OUTPUT_SPEC." < /dev/null
```

**Antigravity (agy) teams** — use the agy CLI for large-context angles (`blue-ocean`, `trend-first`
with deep event history). Output is plain text on stdout — the orchestrator parses it (STDIN RULE:
stdin MUST be closed or agy hangs in background shells, #135; SANDBOX RULE: `--sandbox` on every
advise-only call or agy may write files/commit instead of answering, #157):

```bash
timeout 600 agy --sandbox -p "You are the blue-ocean team. Question: ... Data: see $CONTEXT_FILE. Produce $N outputs per the format in $OUTPUT_SPEC. Advisory only — do not modify any files; answer on stdout." < /dev/null > "$WORK/team-blue-ocean-round1.md"
```



### Bridge Mode

session mode. Codex is unaffected (it always runs locally).

### Batching the Spawns

All Round 1 team spawns MUST go in a single message with parallel tool calls. This is enforced by the
"parallel diverge is mandatory" hard rule. The primitive is incompatible with sequential spawning.

### Failure Modes

| Failure | Detection | Response |
|---|---|---|
| A team times out / returns empty | Round 1 aggregator sees no output for team X | Mark team X "no-show", continue with remaining teams, note in arbiter |
| A team refuses to attack in Round 2 | Round 2 aggregator sees "all good" verdicts or attacks without severity | Reject the attack output, re-spawn the team with sharper prompt; max 1 retry |
| Arbiter cannot produce 2+ kill criteria for an output | Arbiter validation fails | Drop the output from the final list rather than fake kill criteria |
| No output has external grounding | No `context` was passed, or all teams returned `unfounded` | Cap all confidence at `speculative`; emit warning in `arbiter_notes` |
| Cross-fire produces sycophantic attacks (common LLM failure) | Round 2 attacks are uniformly "minor" severity with trivial fixes | Re-spawn attackers with Codex model override and explicit "find CRITICAL flaws" prompt |

---

## Mode: `quick_tournament` (optional shortcut)

For callers who need fast outputs and accept reduced rigor, a `quick_tournament` mode runs:
- 2 teams instead of 4
- 2 rounds (diverge + arbiter, no cross-fire or refine)
- max confidence `low` (enforced)
- useful for low-stakes brainstorms where the full 4-round cost is excessive

Callers opt in via `rounds: 2`. The primitive warns that cross-fire was skipped.

**Do NOT use quick_tournament for founder-ideation, alf review, or any high-stakes decision.** It
exists only for exploration / discovery modes.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Spawning teams sequentially to save token budget | The second team anchors on the first team's output; divergence collapses into a single voice | Always batch all team spawns in one message with parallel tool calls |
| Allowing "all good" verdicts in cross-fire | The primitive's value is structural contention; passive review produces polished consensus, which is exactly the failure mode we're trying to avoid | Reject any Round 2 output that doesn't include ≥1 attack per target; re-spawn the attacker |
| Hiding attacks from the refining team | Teams can't absorb critique they don't see; refine becomes cosmetic | Pipe attack_history directly into each team's Round 3 prompt |
| Skipping the arbiter because the outputs "look good enough" | Without synthesis, hybrid insights are lost and confidence assignment is unreliable | Always run Round 4, even for small tournaments; the arbiter is the quality gate |
| Letting the arbiter promote to `high` confidence without data grounding | LLM-vs-LLM confidence is meaningless; external grounding is the anti-hallucination seatbelt | Enforce the grounding rule in arbiter code: no external cite = cap at `speculative` |
| Forcing a single model on all teams | Different models have different blind spots; homogeneous teams have correlated failures | Use model diversity (Claude + Codex + Antigravity mixed) especially for contrarian / devil's-advocate roles |
| Prescribing team angles the caller didn't request | Domain knowledge lives in the caller (founder-ideation, forge, etc.); the primitive is lens-agnostic | Accept `team_angles` as input, never hardcode a default set inside the primitive |

---

## Reference Files

Read these as needed during orchestration:

- `references/team-angles.md` — the founding-lens library (problem-first, asset-first, trend-first, contrarian, first-principles, arbitrage, blue-ocean, constraint-inverted) with spawn-prompt guidance per angle
- `references/cross-fire-protocol.md` — Round 2 attack protocol: target selection, severity rubric, fix-proposal format, rejected-attack fallback
- `references/arbiter-synthesis.md` — Round 4 synthesis protocol: survivor selection, hybridization rules, kill-criteria attachment, confidence scoring, minority-report preservation

---

## When NOT to Use This Skill

- **Single-agent question** — if one specialist can answer, use that specialist directly. The
  tournament overhead is wasted on simple lookups.
- **No cross-fire value** — if the caller's question has one correct answer (e.g., "what's the syntax
  for X"), adversarial brainstorm is noise.
- **No grounding and no exploratory intent** — if you have no data feeds AND you're not trying to
  explore, you're just asking LLMs to argue with each other. Use a single agent and save the cost.
- **Live production paths** — this primitive is slow (4 rounds × N teams). Don't put it on a
  user-facing latency budget.
