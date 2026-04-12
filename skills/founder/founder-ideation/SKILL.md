---
name: founder-ideation
description: >
  Use when the user asks to generate business ideas, evaluate an existing idea adversarially,
  find underserved niches, or check what's heating up in an industry. Phase 1 flagship subskill of
  the founder family. Runs adversarial team brainstorm (4 parallel founding lenses with cross-fire)
  grounded in real Reddit pain data and GDELT inflection data. Modes: generate_ideas, evaluate_idea,
  find_niches, heat_check. Optional deep_tech_mode flag for inventor / hardware / patent work.
  Routes via parent `founder` skill. Trigger on: "generate N ideas", "business ideas generator",
  "what should I build", "attack my idea", "underserved niches in X", "what's hot in Y industry".
---

# Founder Ideation (Phase 1 Flagship)

Child of `founder`. This skill is the flagship of the founder family — the most differentiated
subskill. It generates (or attacks) business ideas via adversarial team brainstorm grounded in
real Reddit pain data and GDELT event velocity data.

**Scope:** Pre-execution ideation. Produces ideas with kill criteria, first experiments, data
citations, and cross-fire attack histories. Writes results to `.founder/venture-brief.yaml`.

**Siblings (parent = `founder`):**
- `founder-validation` — Phase 2 — Mom Test, assumption ledger, experiment sequencing
- `founder-business-model` — Phase 2 — unit economics calculator mode
- `founder-gtm` — Phase 2 — positioning, distribution, channel selection
- `founder-sprint` — Phase 2 — stage machine coordinating all of the above, forge handoff

---

<HARD-RULE>
**Every idea MUST have ≥1 real data source citation.** Reddit (subreddit + post date), GDELT
(event id), or user-supplied input. This enforces founder HR-5. The arbiter in
`adversarial-team-brainstorm` is configured to reject outputs without grounding.
</HARD-RULE>

<HARD-RULE>
**Every idea MUST have ≥2 kill criteria AND a non-empty first experiment.** Enforces founder
HR-4. This is the anti-"polished guru" mechanism. Without kill criteria, every idea is equally
defendable and equally useless.
</HARD-RULE>

<HARD-RULE>
**Parent intake required before routing.** `founder-ideation` refuses to run without
`venture-brief.yaml` populated with minimum intake (biz_type + geography + niche). If the parent
forgot to capture intake, halt and return to parent with a clear error. Do NOT run on partial
context.
</HARD-RULE>

<HARD-RULE>
**Contrarian team CANNOT produce "just be better" ideas.** The contrarian lens must find
structural counter-positioning — why does the obvious idea NOT already exist, what consensus is
wrong, where's the arbitrage. "Same thing but with better UX" is pseudo-contrarianism and the
arbiter rejects it.
</HARD-RULE>

<HARD-RULE>
**Arbiter refuses to output ranked list if Round 2 cross-fire did not happen.** If for any reason
cross-fire was skipped (timeouts, agent spawn failures), the whole ideation run is marked FAILED
and returned with a degraded-mode warning. Cross-fire is not optional — it IS the value
proposition of the skill.
</HARD-RULE>

<HARD-RULE>
**`deep_tech_mode: true` activates mandatory IP + regulatory + DFM questions.** When a caller
passes `deep_tech_mode`, every team output must include answers to: (1) IP landscape —
existing patents / prior art, (2) regulatory triggers — which regulators will care, (3) DFM
considerations — what makes this manufacturable at scale. Outputs without these are rejected.
</HARD-RULE>

<HARD-RULE>
**HR-4/HR-5 applicability by output class.** The `generate_ideas`, `evaluate_idea`, and
`find_niches` modes emit outputs classed as **"ideas"** — HR-4 (kill criteria + first experiment)
AND HR-5 (data provenance) apply. The `heat_check` mode emits **"signals"** (hypotheses attached
to raw data) — HR-5 applies but HR-4 does NOT (kill criteria + first experiment are not meaningful
for a raw heat reading). The mode wiring to adversarial-team-brainstorm sets `output_class`
accordingly.
</HARD-RULE>

---

## Modes

### 1. `generate_ideas`

"Give me N business ideas for niche X" — the primary mode.

**Input:**
```yaml
mode: "generate_ideas"
niche: string                     # from venture-brief intake, or user override
n_ideas: int                      # default 10, max 30
biz_type: enum                    # from venture-brief (software | service | marketplace | ...)
user_assets: map                  # from venture-brief (skills, networks, distribution, unique_access)
deep_tech_mode: bool              # default false
team_model_overrides: map         # optional; default {contrarian: codex}
```

**Flow:**

1. **Read `venture-brief.yaml`** — load intake, existing ideas, user assets. Refuse if missing.
2. **Parallel data gathering (before team spawn):**
   - Invoke `reddit-signal-mining` with `operation: mine_pains` + niche → pain records
   - Invoke `gdelt-event-mining` with `operation: inflection_scan` + theme-map(niche) → inflection records
   - Both run in parallel, time-bounded (default 90s total)
3. **Run `adversarial-team-brainstorm` with:**
   - `question: "Generate {n_ideas + 4} {biz_type} ideas for {niche}"` (extra budget for arbiter trim)
   - `team_angles: ["problem-first", "asset-first", "trend-first", "contrarian"]`
   - `rounds: 4`
   - `n_per_team: ceil((n_ideas + 4) / 4)`
   - `context`:
     - `reddit_pain_data`: mined pain records
     - `gdelt_inflection_data`: inflection records
     - `user_assets`: from venture-brief
   - `kill_criteria_required: true`
   - `team_model_override`: `{contrarian: codex}` (default) unless caller overrides
   - `output_class: "ideas"` (enforces HR-4 + HR-5 in arbiter)
4. **Arbiter returns ranked outputs** with kill criteria, first experiments, attack histories
5. **Trim to `n_ideas`** (arbiter already ranked; take top-N)
6. **Write to `venture-brief.yaml.ideas_considered[]`** — each idea as a new record with
   `status: candidate`, full attack history, refinement history, data sources
7. **Return structured output** for display to user

**Output (to user):**
```yaml
mode: generate_ideas
ideas:
  - rank: 1
    content: string
    source_team: string
    confidence: enum
    kill_criteria: list[string]
    first_experiment: string
    data_sources: list[string]
    attack_history: list[...]
    revisions:
      before: string
      after: string
      critique_absorbed: list[string]
arbiter_notes: string           # synthesis patterns, minority reports, confidence distribution
data_grounding:
  reddit:
    subreddits_queried: list[string]
    pains_extracted: int
  gdelt:
    themes_queried: list[string]
    inflections_detected: int
venture_brief_path: string
```

### 2. `evaluate_idea`

"I have this idea. Attack it."

**Input:**
```yaml
mode: "evaluate_idea"
idea: string                      # the user's proposed idea
biz_type: enum                    # from intake
niche: string                     # from intake
user_assets: map
deep_tech_mode: bool
```

**Flow:**

1. Read venture-brief. Refuse on missing intake.
2. Parallel data gathering (same as generate_ideas)
3. Run `adversarial-team-brainstorm` with:
   - `question: "Attack this idea: {idea}. Find flaws, kill criteria, first experiments, hybrid variants."`
   - `team_angles: ["contrarian", "first-principles", "arbitrage", "constraint-inverted"]`
     (different angles for attack-mode)
   - `rounds: 4` (same structure — teams first propose attacks, then cross-fire each other's attacks, then refine, then arbiter)
   - `n_per_team: 3` (fewer outputs per team, but deeper attacks)
   - `context`:
     - `user_idea: idea`
     - `reddit_pain_data`: mined pain records
     - `gdelt_inflection_data`: inflection records
     - `user_assets`
   - `kill_criteria_required: true`
   - `output_class: "ideas"` (HR-4 + HR-5 still apply — attack outputs must cite data)
4. Arbiter produces a single structured attack report:
   - Surviving-or-not verdict for the original idea
   - Top 3-5 most severe attacks
   - Suggested pivots (if any) — hybrid ideas that absorb the attacks
   - Suggested first experiment to validate the core claim
5. Write to `venture-brief.yaml.ideas_considered[]` with the original idea + refined pivots as
   separate entries

**Output:**
```yaml
mode: evaluate_idea
verdict: enum                     # "survives_with_pivot" | "survives_as_is" | "killed" | "needs_data"
original_idea:
  content: string
  status: enum                    # candidate | validated | killed
  attack_history: list[...]
  unabsorbed_critical_attacks: list[...]  # if any — these are the deal-breakers
pivots:
  - content: string               # pivot that absorbs the attacks
    delta_from_original: string   # what changed
    kill_criteria: list[string]
    first_experiment: string
    data_sources: list[string]
recommended_next: string          # "run the first experiment", "validate with N users", "pivot to X"
```

### 3. `find_niches`

"What underserved niches exist in [broader space X]?"

**Input:**
```yaml
mode: "find_niches"
broader_space: string             # e.g. "B2B fintech", "home construction", "elderly care"
biz_type: enum
user_assets: map
n_niches: int                     # default 5
```

**Flow:**

1. Read venture-brief
2. Heavy data gathering:
   - `reddit-signal-mining` with `discover_subs` to find all sub-communities in the broader space
   - `reddit-signal-mining` with `mine_pains` across discovered subs
   - `gdelt-event-mining` with `events_by_theme` + `inflection_scan` for the broader space
3. Run `adversarial-team-brainstorm` with:
   - `question: "Identify {n_niches + 3} underserved niches within {broader_space}"`
   - `team_angles: ["problem-first", "trend-first", "contrarian", "constraint-inverted"]`
     (no asset-first — niche discovery isn't about leveraging user assets yet)
   - `rounds: 4`
   - `n_per_team: ceil((n_niches + 3) / 4)`
   - `output_class: "ideas"` (niches are structured with kill criteria — HR-4 still applies)
4. Arbiter returns ranked niches with:
   - Why each niche is underserved (evidence from Reddit + GDELT)
   - Who the customer is
   - Why incumbents aren't serving them
   - What would kill the niche (consolidation, regulation, etc.)
5. Write to venture-brief; don't generate ideas yet — that's a follow-up `generate_ideas` call

**Output:** ranked niches with provenance + kill criteria + "why underserved" rationale.

### 4. `heat_check`

"What's getting hot in [industry Y] right now?"

**Input:**
```yaml
mode: "heat_check"
industry: string
lookback_days: int                # default 7
baseline_days: int                # default 30
```

**Flow:**

1. Read venture-brief (minimal — heat_check is read-only for venture state)
2. Data mining ONLY:
   - `reddit-signal-mining` with `heat_scan` on industry subreddits
   - `gdelt-event-mining` with `inflection_scan` on industry themes
3. **NO adversarial brainstorm.** Heat check is pure data mining with LLM hypothesis attachment.
4. For each HOT / FIRE signal, invoke a single LLM pass to generate a 1-sentence hypothesis
   (prefixed `hypothesis:` so callers know it's interpretive).
5. Return structured heat report. Do NOT write to `ideas_considered[]` — heat check produces
   `signals`, not ideas. Signals don't need kill criteria or first experiments.

**Output:**
```yaml
mode: heat_check
reddit_heat:
  - subreddit: string
    tier: enum                    # WARM | HOT | FIRE
    ratio: float
    top_trending_posts: list[...]
    hypothesis: string            # "hypothesis: ..."
gdelt_heat:
  - theme: string
    tier: enum
    ratio: float
    top_events: list[...]
    hypothesis: string
caveat: >
  Heat check signals are hypotheses attached to raw data, not ideas.
  They are NOT validated, not kill-criteria-attached, and NOT first-experiment-ready.
  To turn a hot signal into an investable idea, run `generate_ideas` with the hot
  niche as input.
```

### 5. `deep_tech_mode` (flag, not a standalone mode)

Overlays all four modes with inventor-specific frameworks. Activated via `deep_tech_mode: true`.

When active:

- Team outputs must additionally include:
  - **IP landscape** — existing patents / prior art / freedom-to-operate questions
  - **Regulatory triggers** — which regulators will care (FDA, FCC, CE, UKCA, ISO, etc.)
  - **DFM (Design for Manufacturability)** — what makes this manufacturable at scale
  - **TRL / SRL / BRL assessment** — Technology / System / Business Readiness Levels (0-9 scale)
- The `first-principles` angle is added to the default team_angles list (replacing one of the
  weaker angles for deep-tech)
- The `heat_check` mode additionally queries GDELT for `TECH_*` themes tied to the invention
  category
- The arbiter adds a `deep_tech_concerns` section to its notes

See `references/deep-tech-mode.md` for the full overlay specification.

---

## Reference Files

- `references/team-lenses.md` — detailed specs for problem-first / asset-first / trend-first /
  contrarian, how to feed data into each, expected output shape per lens
- `references/data-integration.md` — how to call `reddit-signal-mining` and `gdelt-event-mining`
  from within this skill, how to pass data to team spawns, what to do on data gathering failure
- `references/deep-tech-mode.md` — TRL/SRL/BRL overlay, IP landscape questions, regulatory trigger
  list, DFM considerations
- `references/business-idea-prompts.md` — prompt templates per biz_type (software / service /
  marketplace / hardware / deep-tech / physical-retail / other)
- `references/kill-criteria-library.md` — standard kill criteria library: distribution gap,
  unit econ negative, regulatory block, saturated market, no switching cost, no compounding moat,
  etc. Arbiter falls back to these when teams don't produce sharper ones.

---

## Data Integration Pattern

The skill is the OWNER of the call to data-mining skills. See `references/data-integration.md`
for the full contract. Summary:

1. **Determine which subreddits to mine** — either from user input, from venture-brief, or via
   `reddit-signal-mining:discover_subs` with the niche
2. **Determine which GDELT themes to query** — via the `theme-taxonomy.md` industry-mapping table
   (reddit-signal-mining doesn't provide these — founder-ideation's own knowledge)
3. **Invoke both in parallel:**
   - Spawn a subagent for `reddit-signal-mining` operation
   - Spawn a subagent for `gdelt-event-mining` operation
   - Time-bound: 90 seconds wall clock, return partial results on timeout
4. **If both fail:**
   - For `generate_ideas` / `evaluate_idea` / `find_niches`: DEGRADE. Run adversarial brainstorm
     with `context: {}`. Arbiter will cap confidence at `speculative`. Mark the output with
     `data_source: "ungrounded_degraded"`.
   - For `heat_check`: HALT. Heat check without data is meaningless.
5. **If one fails and one succeeds:** continue with the partial grounding and note the gap.

---

## Cross-Skill Invocation Flow (Phase 1)

```
founder (parent)
  │ intake populated → route to founder-ideation
  ▼
founder-ideation (this skill)
  │ read venture-brief
  │
  ├──parallel──▶ reddit-signal-mining (mine_pains or heat_scan)
  │              │
  │              ▶ returns pain records or heat tier
  │
  └──parallel──▶ gdelt-event-mining (inflection_scan or events_by_theme)
                 │
                 ▶ returns inflection records or events
  │
  ▼
adversarial-team-brainstorm
  ├──Round 1──▶ 4 parallel teams (each gets its own slice of data)
  ├──Round 2──▶ cross-fire (each team attacks 3 other teams)
  ├──Round 3──▶ refine (each team absorbs / rejects attacks)
  └──Round 4──▶ arbiter (synthesize, rank, kill-criteria, confidence)
  │
  ▼
founder-ideation (this skill)
  │ write to venture-brief.ideas_considered[]
  │ return structured output
  ▼
founder (parent)
  │ display to user
```

---

## Failure Modes

| Failure | Detection | Response |
|---|---|---|
| No venture-brief / missing intake | Parent should have caught; if not, halt and return error | Return to parent with "intake missing: biz_type/geography/niche"; parent asks the user |
| Reddit data mining fails entirely | `reddit-signal-mining` returns empty + gap list | Continue with GDELT only; mark `reddit: "unavailable"`; arbiter caps grounded confidence |
| GDELT data mining fails entirely | Same for GDELT | Continue with Reddit only; same cap |
| Both data sources fail | Detected in parallel fetch | For modes needing grounding: degrade to ungrounded, cap all confidence at `speculative`, warn user; for `heat_check`: halt |
| Adversarial brainstorm Round 2 (cross-fire) fails | No attacks from 2+ teams | Rerun Round 2 once; if still fails, halt and mark FAILED per HR (refuse to output ranked list without cross-fire) |
| Contrarian team produces pseudo-contrarian output | Arbiter validator flags it | Reject, re-spawn contrarian with sharper prompt; max 1 retry |
| Arbiter cannot produce 2+ kill criteria per output | Arbiter validator fails | Drop the output from the final list (HR-4 enforcement) |
| Venture-brief write fails (disk full, perms) | IO error | Return the output to the user anyway, but mark `venture_brief_updated: false` and warn |
| `deep_tech_mode` outputs missing IP / reg / DFM answers | Validator fails | Re-spawn the team with stricter prompt; max 1 retry; drop output if still missing |

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Running `generate_ideas` without first mining Reddit/GDELT data | Teams produce LLM-vs-LLM consensus with no grounding; HR-5 violated | Always mine data first, pass to teams via context, fail gracefully if data unavailable |
| Using the same 4 angles for every mode | Different modes need different lenses (attack modes should skew contrarian + first-principles) | `generate_ideas` uses problem/asset/trend/contrarian; `evaluate_idea` uses contrarian/first-principles/arbitrage/constraint-inverted |
| Ignoring the contrarian team because it produces harsh output | Harsh output IS the point; harshness is the anti-groupthink mechanism | Preserve contrarian outputs in the ranked list even if they contradict the other teams |
| Hiding kill criteria in appendices to make ideas look more compelling | Defeats HR-4; user makes decisions with false confidence | Kill criteria are first-class output, alongside the idea content, not footnoted |
| Returning raw Reddit quotes with identifying details to illustrate pain | Violates HR-11; privacy breach | `reddit-signal-mining` paraphrases by default; re-enforce at output formatting |
| Running `heat_check` and treating signals as investable ideas | Signals are hypotheses, not validated ideas; no kill criteria attached | Heat check output explicitly says "to turn signals into ideas, run generate_ideas"; user must take the next step |
| Skipping `deep_tech_mode` overlay for hardware / invention requests | Loses critical IP / regulatory / DFM grounding; produces software-shaped advice for non-software problems | Parent intake detects deep-tech intent and passes `deep_tech_mode: true`; check venture-brief on entry |
| Running with `n_ideas > 30` | Team output quality degrades dramatically above ~30; cross-fire becomes noise | Cap at 30; tell the user to run multiple rounds if they need more |

---

## When NOT to Use This Skill

- **User wants to validate an idea with real users** (not just attack it with LLMs) — Phase 2
  `founder-validation` will do that. For Phase 1, `evaluate_idea` is the closest substitute.
- **User wants business model / unit economics work** — Phase 2 `founder-business-model`; for
  Phase 1, explain that it's coming and offer to help prepare the inputs.
- **User wants to write a pitch deck** — Phase 1 has `presentation-builder` + `yc-pitch` /
  `sequoia-pitch` flow stubs (WP-F8); route there via parent
- **User wants to start building** — hand off to `forge` via the Scope→Launch gate (parent
  handles the routing)
- **Pure market research without ideation intent** — use `reddit-signal-mining` + `gdelt-event-mining`
  directly; this skill's overhead (adversarial brainstorm) is wasted
- **Legal / tax / valuation / fundraising questions** — REFUSED by parent (HR-1, HR-2, HR-3)
