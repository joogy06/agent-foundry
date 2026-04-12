# Data Integration — Calling Reddit + GDELT from founder-ideation

This reference documents how `founder-ideation` invokes `reddit-signal-mining` and
`gdelt-event-mining` in parallel, how to pass the resulting data into the adversarial brainstorm
teams, and what to do when data gathering fails.

---

## Invocation pattern

### Step 1: Determine what to mine

From the intake (`venture-brief.yaml`):

```yaml
niche: "small accounting firms (1-5 employees) in UK"
biz_type: "software"
geography: "GBR,USA"
```

Determine:
- **Subreddits to mine**: start with `reddit-signal-mining:discover_subs` using the niche; cache
  result in `venture-brief.yaml` for re-use within the session
- **GDELT themes to query**: use the industry mapping table in
  `gdelt-event-mining/references/theme-taxonomy.md` (e.g. "accounting" → `ECON_TAXATION`,
  `LEG_REGULATORY`, `ECON_INFLATION`, `TECH_AUTOMATION`)

### Step 2: Parallel spawn

Spawn two subagents in a single message (parallel tool calls):

**Subagent 1: Reddit mining**
```
Agent(subagent_type: "general-purpose", prompt: """
Invoke the `reddit-signal-mining` skill with:

operation: "mine_pains"
niche: "{NICHE}"
subreddits: {SUBREDDITS_LIST}
lookback_days: 30
limit_posts: 150

Return the structured output. Time-bound: 90 seconds.

Privacy: the skill enforces paraphrase-first on example_quotes. Do not override.

If the skill errors / times out / falls back to public JSON mode, include the gap note in
your return.
""")
```

**Subagent 2: GDELT mining**
```
Agent(subagent_type: "general-purpose", prompt: """
Invoke the `gdelt-event-mining` skill with:

operation: "inflection_scan"
themes: {THEMES_LIST}
locations: {GEO_LIST}
lookback_days: 7
baseline_days: 30
threshold_ratio: 2.0
limit: 30

Return the structured output. Time-bound: 90 seconds.

Use RSS fallback if GDELT rate-limits. Include the fallback flag in your return so
founder-ideation knows the grounding is degraded.
""")
```

### Step 3: Aggregate results

```yaml
reddit_pain_data:
  pains: list[pain_record]         # from reddit-signal-mining output
  gaps: list[string]                # empty if clean fetch
  auth_mode: "praw" | "public_json" | "blocked"
  total_posts_fetched: int

gdelt_inflection_data:
  inflections: list[inflection]    # from gdelt-event-mining output
  gaps: list[string]
  data_source: "gdelt" | "gdelt+rss_fallback"
  total_events_fetched: int
```

Both fields are passed to the adversarial brainstorm via the `context` parameter:

```yaml
context:
  reddit_pain_data: <above>
  gdelt_inflection_data: <above>
  user_assets: <from venture-brief.intake.user_assets>
```

---

## How each team receives data

The adversarial brainstorm primitive does NOT merge the data streams for the teams. Each team
gets a slice:

- **problem-first** — gets `reddit_pain_data` only. Does NOT see GDELT data. Does NOT see user
  assets. This forces it to stay grounded in pain signal.
- **asset-first** — gets `user_assets` only. Does NOT see Reddit / GDELT. This forces it to stay
  grounded in the user's unique leverage.
- **trend-first** — gets `gdelt_inflection_data` only. Does NOT see Reddit / user_assets.
- **contrarian** — gets NOTHING in Round 1. In Round 2 it sees the other teams' outputs and
  attacks them.

This slicing is deliberate. Giving every team all the data causes them to converge — they all
start to sound the same. Slicing forces orthogonal perspectives in Round 1; cross-fire in
Round 2 is where the perspectives collide.

The arbiter sees all the data in Round 4 for synthesis.

---

## Failure modes

### Reddit mining fails (all subs blocked / timeout / ToS block)

```yaml
reddit_pain_data:
  pains: []
  gaps: ["all_subs_blocked", "timeout"]
  auth_mode: "blocked"
```

**Founder-ideation response:**
- Continue with GDELT only
- problem-first team has NO grounding data → skip that team entirely (3-team tournament)
- OR spawn problem-first with a degraded prompt: "no Reddit data available, generate ideas based
  on your general knowledge of this niche, but ALL outputs capped at `speculative` confidence"
- Mark the final ideation output with `reddit: "unavailable"` in metadata
- User sees a clear warning: "Reddit data unavailable — ideas are ungrounded on the pain
  dimension"

### GDELT mining fails (rate-limited past retry budget)

```yaml
gdelt_inflection_data:
  inflections: []
  gaps: ["gdelt_unavailable: circuit_open"]
  data_source: "gdelt_unavailable_no_rss"
```

**Founder-ideation response:**
- Continue with Reddit only
- trend-first team skipped OR degraded
- Warning to user: "Trend grounding unavailable — ideas are ungrounded on the inflection dimension"

### Both fail

**For `generate_ideas` / `evaluate_idea` / `find_niches`:**
- Run adversarial brainstorm with `context: {}` and a smaller team (contrarian + first-principles,
  2 teams only)
- Arbiter caps ALL confidence at `speculative`
- Final output has `data_source: "ungrounded_degraded"` and a warning
- Kill criteria from the library fallback

**For `heat_check`:**
- HALT. Heat check without data is meaningless — there's literally no signal to attach hypotheses
  to.
- Return `mode: "halted", reason: "no_data_sources_available"` to the parent

### Partial success (one of the two returns weak data)

- Proceed with what you have
- Note the gap in the output metadata
- The arbiter sees the gap and adjusts confidence accordingly

---

## Privacy filtering

Before passing Reddit data to the adversarial teams, re-filter for privacy per HR-11:

1. Verify every `pain_record.example_quotes_paraphrased` field — if any contains identifying
   details (names, employers, specific locations, dollar amounts), reject the record
2. Drop rejected records from the team input
3. Note in metadata: `privacy_filter_dropped: N records`

The `reddit-signal-mining` skill already paraphrases by default, but founder-ideation re-enforces
as a second layer. The user should never see raw Reddit content that could identify a poster.

---

## Caching (Phase 1: session-only)

Within a single session, cache data mining results in
`venture-brief.yaml.data_cache` so follow-up ideation calls (e.g., running `generate_ideas`
twice for the same niche with different `n_ideas` values) don't re-fetch:

```yaml
data_cache:
  reddit_pain_data:
    fetched_at: timestamp
    niche: string                  # cache key
    pains: list[...]
    ttl_minutes: 30                # invalidate after 30 min within session
  gdelt_inflection_data:
    fetched_at: timestamp
    themes: list[string]           # cache key
    inflections: list[...]
    ttl_minutes: 30
```

**Cache hit rules:**
- Same niche + within TTL → reuse
- Different niche → fetch fresh
- User explicitly says "get fresh data" → fetch fresh

**Phase 2 cache seam:** if Phase 2 extends caching across sessions (file-backed cache), it MUST
be opt-in. Phase 1 default is session-only, in-memory-via-venture-brief.

---

## Budget management

Data mining is slow. Founder-ideation budgets:

- Reddit `mine_pains`: 30-90 seconds typical, 120 seconds max
- GDELT `inflection_scan`: 20-60 seconds typical, 90 seconds max
- Total parallel budget: 90 seconds (both run in parallel)
- If either is still running at 90 seconds, grab partial results and proceed

The adversarial brainstorm itself takes 3-8 minutes (4 rounds × 4 teams × model latency). Data
mining is NOT the bottleneck for founder-ideation end-to-end; the tournament is.

Don't optimize data mining at the cost of quality. A slow, grounded 8-minute ideation is worth
more than a fast, ungrounded 2-minute ideation. The user asked for ideas with kill criteria and
data citations — that's the product.
