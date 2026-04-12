---
name: reddit-signal-mining
description: >
  Use when a caller needs to extract real pain points, velocity heat, or sentiment from Reddit for
  research, niche detection, idea validation, or market signal grounding. Supports discover_subs,
  mine_pains, heat_scan, and sentiment operations. Reusable by founder-ideation, alf, research-*,
  and any caller that needs physical-world grounding from public Reddit data. One-shot fetch-analyze-
  return — NOT a real-time stream. Trigger on: "mine Reddit for X", "find pain points in r/Y",
  "what's hot on Reddit about Z", "subreddit discovery", "Reddit sentiment".
---

# Reddit Signal Mining

Extract structured research signal from Reddit: pain points, velocity heat, subreddit discovery,
sentiment. One-shot research tool — fetches on demand, returns structured records with provenance,
does not maintain persistent state.

**Scope:** Public Reddit data (PRAW authenticated OR public JSON endpoints). Returns normalized
pain / heat / sentiment records. Does NOT provide idea generation — callers do that with the data.

**Callers:**
- `founder-ideation` — mines pain for `problem-first` team, checks sub heat for niche velocity
- `alf` — searches for drift signals ("people are complaining that skill X is stale")
- Any research workflow that needs physical-world pain signal

**Proven pattern source:** The trading wiki's `signals:reddit` stream (PRAW poller at
`/path/to/projects/trading/src/data_pipeline/reddit.py`, FinBERT sentiment pipeline at
`sentiment.py`, velocity heat scoring at `heat_scanner.py`). This skill PORTS the patterns
(PRAW auth, rate-limit handling, circuit breaker, velocity baselines) but does NOT port the
infrastructure (Redis streams, TimescaleDB, async workers) — founder research is one-shot,
not a live signal path.

---

<HARD-RULE>
**Respect Reddit API ToS + robots.txt.** This skill does not scrape. PRAW-authenticated access is
preferred; the public JSON endpoint (`https://www.reddit.com/r/<sub>.json`) is the fallback when
credentials are unavailable. No headless browser scraping. No circumventing rate limits. No access
to subreddits where scraping is explicitly prohibited by the mod team. Refuse to bypass any robots
rule, any Reddit API block, any private/quarantined sub.
</HARD-RULE>

<HARD-RULE>
**No persistent storage of usernames.** Usernames are transient — used only within the extraction
session to fetch post/comment content, never written to disk, never returned in output records
except where the user is the author of a quoted pain (and even then, see the privacy rule below).
No user profiling. No tracking of a single user's post history across sessions. This skill is a
research tool, not a surveillance tool.
</HARD-RULE>

<HARD-RULE>
**Paraphrase-first for `example_quotes`.** When returning example pain quotes (the `example_quotes`
field), paraphrase them unless the original is clearly anonymized AND the user's identity is not
revealed by the quote itself. Default behavior: paraphrase. Exception: 1-2 word phrases that are not
identifying may be quoted verbatim if they are load-bearing. Never quote posts that reveal the
author's employer, location, health status, or financial details. This is HR-11 from the founder
family hard rules.
</HARD-RULE>

<HARD-RULE>
**Rate-limit with exponential backoff.** On any 429 response from Reddit API or JSON endpoint, back
off exponentially (1s → 2s → 4s → 8s → 16s → skip). Circuit breaker: if 3 consecutive 429s, skip
this subreddit for the rest of the session and note the gap in output metadata. Never hammer the
endpoint.
</HARD-RULE>

<HARD-RULE>
**All mined pains must cite source.** Every pain record in the output must include `subreddits`,
`example_quotes_paraphrased` (or empty), and at least one post date. Data without provenance is
rejected by the skill. Callers rely on this for the HR-5 "every idea must cite data source" rule
in founder-ideation.
</HARD-RULE>

---

## Operations

The skill exposes four operations. Callers select one per invocation via the `operation` field.

### 1. `discover_subs`

Find subreddits relevant to a niche.

**Inputs:**
```yaml
operation: "discover_subs"
niche: string                # e.g. "small accounting firms", "3D printing hobbyists"
min_subscribers: int         # default 1000 — filter dead subs
max_subscribers: int         # default 2000000 — filter mega-subs that dilute niche signal
exclude_nsfw: bool           # default true
exclude_inactive_days: int   # default 30 — drop subs with no new posts in N days
limit: int                   # default 20 max subs to return
```

**Approach:**
1. Search Reddit's sub discovery endpoint (PRAW: `reddit.subreddits.search(niche)`)
2. Score each candidate: `subscribers`, `active_user_count`, `post_velocity` (posts / day / sub),
   `moderator_tone` (strictness — heuristic from sidebar content)
3. Filter by thresholds in input
4. Rank by a composite score (see `references/subreddit-discovery.md`)

**Output:**
```yaml
subreddits:
  - name: string              # e.g. "r/Accounting"
    subscribers: int
    active_users: int
    post_velocity_per_day: float
    niche_relevance_score: float  # 0-1
    mod_strictness: enum        # permissive | moderate | strict
    sample_recent_titles: list[string]  # 3-5, paraphrased
    url: string
metadata:
  data_source: "reddit-signal-mining v1"
  operation: "discover_subs"
  queried_at: timestamp
  auth_mode: "praw" | "public_json"
  gaps: list[string]           # subs that 429'd or were blocked
```

See `references/subreddit-discovery.md` for scoring logic details.

### 2. `mine_pains`

Extract structured pain records from subreddits.

**Inputs:**
```yaml
operation: "mine_pains"
niche: string                # for context
subreddits: list[string]     # explicit list; if empty, run discover_subs first
lookback_days: int           # default 30
limit_posts: int             # default 200 per sub
pain_prompt_variants: list[string]  # optional — override default prompts (see references/pain-point-queries.md)
```

**Approach:**
1. Fetch posts + top comments per sub (PRAW `subreddit.new()` with time filter, OR public JSON
   `/r/<sub>/new.json` with `after` pagination)
2. For each post/comment, run LLM pain-extraction prompts (see
   `references/pain-point-queries.md` for templates — "What's painful", "What workaround did the
   user build", "What request is ignored by incumbents", "What complaint about existing tools")
3. Normalize extracted pains into records with dedup (merge if cosine similarity > 0.85)
4. Score `unmet_need_score` as a function of frequency, engagement (upvotes + comment count), and
   absence of satisfactory incumbent response
5. Apply paraphrase-first rule to `example_quotes`

**Output:**
```yaml
pains:
  - pain: string                   # "Reconciling QBO with bank feed when fees differ by cents"
    frequency: int                 # how many posts mentioned it
    subreddits: list[string]       # where it came from
    example_quotes_paraphrased: list[string]  # 2-3 paraphrased representative quotes
    post_dates: list[string]       # ISO dates of mentioning posts (for provenance)
    engagement:
      total_upvotes: int
      total_comments: int
    existing_workarounds: list[string]
    incumbent_mentions: list[string]  # tools/products users mentioned as failing to solve this
    unmet_need_score: float        # 0-1
    post_refs: list[string]        # reddit:<sub>/<post_id> for citation
metadata:
  data_source: "reddit-signal-mining v1"
  operation: "mine_pains"
  queried_at: timestamp
  auth_mode: "praw" | "public_json"
  subreddits_queried: list[string]
  gaps: list[string]               # subs that 429'd, were private, etc.
  total_posts_fetched: int
```

See `references/pain-point-queries.md` for prompt templates and dedup rules.

### 3. `heat_scan`

Detect velocity heat in a set of subreddits — WARM/HOT/FIRE tiers (ported from trading
`heat_scanner.py`).

**Inputs:**
```yaml
operation: "heat_scan"
subreddits: list[string]
lookback_days: int           # default 7 — current window
baseline_days: int           # default 30 — trailing baseline
min_baseline_posts: int      # default 50 — reject subs with too-few baseline posts for meaningful comparison
```

**Approach:**
1. For each sub, fetch all posts in `lookback_days` + all posts in `baseline_days`
2. Compute `current_velocity = posts_in_lookback / lookback_days`
3. Compute `baseline_velocity = posts_in_baseline / baseline_days`
4. Compute `ratio = current_velocity / baseline_velocity`
5. Tier by thresholds (see `references/velocity-heat-scoring.md`):
   - `WARM`: 1.5 ≤ ratio < 2.5
   - `HOT`: 2.5 ≤ ratio < 5
   - `FIRE`: ratio ≥ 5

Also track engagement velocity (upvotes + comments per post) as a second dimension.

**Output:**
```yaml
heat:
  - subreddit: string
    tier: enum                     # COLD | WARM | HOT | FIRE
    current_velocity: float        # posts per day in lookback
    baseline_velocity: float       # posts per day in baseline
    ratio: float
    engagement_ratio: float        # upvote/comment velocity same comparison
    top_trending_posts: list[     # the posts driving the heat (paraphrased titles)
      { title_paraphrased, upvotes, comments, date, post_ref }
    ]
metadata:
  data_source: "reddit-signal-mining v1"
  operation: "heat_scan"
  queried_at: timestamp
  auth_mode: "praw" | "public_json"
  gaps: list[string]
```

See `references/velocity-heat-scoring.md` for threshold rationale and false-signal guards.

### 4. `sentiment`

Score sentiment on a set of posts (FinBERT by default, transformer fallback). Optional — callers
that want sentiment on the pain or heat output.

**Inputs:**
```yaml
operation: "sentiment"
post_refs: list[string]            # reddit:<sub>/<post_id> references from a prior operation
model: enum                        # "finbert" (default) | "all_minilm_l6_v2" | "llm_prompt"
include_comments: bool             # default true — include top-level comments
```

**Approach:**
1. Fetch each post + top comments
2. Run the chosen sentiment model per text
3. Aggregate per post (mean + weighted by upvotes)
4. Return per-post scores + one aggregate score for the batch

**Output:**
```yaml
sentiment_scores:
  - post_ref: string
    post_sentiment: float           # -1..1 (bearish..bullish) or emotion vector if llm_prompt
    comment_sentiment_mean: float
    comment_sentiment_weighted: float  # weighted by upvotes
    sample_size: int                # number of texts scored
aggregate:
  batch_mean: float
  batch_std: float
metadata:
  data_source: "reddit-signal-mining v1"
  operation: "sentiment"
  model: string
  queried_at: timestamp
```

**Note on FinBERT misfire:** FinBERT is trained on financial news headlines. For non-financial pain
posts (accounting workflow complaints, for example), FinBERT may misclassify. For non-financial
niches, prefer `all_minilm_l6_v2` or `llm_prompt`. Callers MUST pass `model` explicitly when the
niche is non-financial.

---

## Authentication

The skill supports two auth modes:

### PRAW mode (preferred)

Uses Reddit's authenticated API via [PRAW](https://praw.readthedocs.io/). Higher rate limits,
comment thread expansion, structured responses.

**Setup:**
```bash
# ~/.config/reddit-signal-mining/praw.env
REDDIT_CLIENT_ID=<your app id>
REDDIT_CLIENT_SECRET=<your app secret>
REDDIT_USER_AGENT=reddit-signal-mining/1.0 by <your username>
# Optional — script-type apps use username/password
REDDIT_USERNAME=<username>
REDDIT_PASSWORD=<password>
```

The caller (or user) creates a Reddit app at https://www.reddit.com/prefs/apps (script type). The
skill loads credentials from the env file OR from the caller's environment vars. If the env file
doesn't exist and the env vars aren't set, the skill falls back to public JSON mode and emits a
metadata warning.

See `references/ethics-and-ratelimits.md#praw-setup` for the full onboarding walkthrough.

### Public JSON mode (fallback)

Uses the public `/r/<sub>.json` endpoints. No auth required. Lower rate limits (60 req/min). No
comment thread expansion beyond the top-level listing.

**Limitations:**
- Top-level comments only (no nested thread traversal)
- Rate-limited more aggressively
- Some subs block public JSON (mostly quarantined or NSFW — skill respects the block)

---

## Circuit Breaker

Ported from trading wiki pattern. Per-subreddit failure counter:

```
failure_count < 3: CLOSED (normal fetching)
failure_count >= 3: OPEN (skip sub, note in gaps for 5 minutes)
after 5 minutes: HALF_OPEN (one test fetch; if success → CLOSED, else → OPEN)
```

Failures counted: 429 rate-limit, 403 Forbidden, 500/502/503/504 server errors, timeout.

This matches the trading wiki's pattern: `reddit.py` uses the same "3 failures in a row → skip"
behavior before emitting to Redis.

---

## Circuit Breaker + Rate Limit Interaction

- Backoff happens FIRST (exponential per-request)
- Circuit breaker tracks CONSECUTIVE failures across the backoff sequence
- A successful fetch between 429s resets the counter
- When circuit opens, the sub is added to `metadata.gaps` so callers know the data is incomplete

---

## Dedup (for `mine_pains`)

Pains extracted across multiple posts / subs are deduplicated:
1. Tokenize + stem each `pain` field
2. Compute cosine similarity over the token sets
3. Merge pairs with similarity > 0.85
4. Merged record's `frequency` is the sum; `subreddits` is the union; `example_quotes_paraphrased`
   takes the highest-engagement 3; `post_refs` concatenates

See `references/pain-point-queries.md#dedup` for the full merge algorithm.

---

## Reference Files

- `references/subreddit-discovery.md` — scoring logic, threshold tuning, heuristics for mod_tone
  detection, exclusion rules for toxic/inactive/dead subs
- `references/pain-point-queries.md` — LLM pain-extraction prompt templates, dedup algorithm,
  unmet_need_score formula, incumbent_mentions extraction
- `references/velocity-heat-scoring.md` — WARM/HOT/FIRE thresholds (ported from trading heat_scanner),
  false-signal guards, engagement velocity normalization
- `references/ethics-and-ratelimits.md` — PRAW setup walkthrough, rate-limit behavior, ToS
  compliance rules, privacy/anonymization handling, paraphrase protocol (HR-11)

---

## Implementation Notes

### One-shot vs streaming

The trading wiki's `reddit.py` is a long-lived poller that writes to a Redis stream every 120-180
seconds. This skill is invoked once per user query, fetches once, and returns. No background
process, no Redis, no persistence.

**Phase 2 cache seam:** If Phase 2 introduces a per-session file cache (to avoid re-fetching within
a single design session), it MUST be an opt-in decorator. Phase 1 callers continue to work
unchanged when cache is disabled. The canonical behavior is fetch-analyze-return.

### Language

The skill is model-neutral pseudo-code + prompt templates. It does NOT ship executable Python.
Callers (LLM agents) interpret the operation specs and emit bash/python as needed for their
runtime. This matches the skill-family convention (agent-teams, research-for-skills, etc.).

For agents that need to actually fetch Reddit data, the recommended invocation is:

```python
# Pseudo-code — agent emits this at runtime
import os
try:
    import praw
    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ.get("REDDIT_USER_AGENT", "reddit-signal-mining/1.0"),
    )
    for post in reddit.subreddit(sub).new(limit=200):
        yield normalize(post)
except ImportError:
    # fall back to public JSON
    import urllib.request, json
    url = f"https://www.reddit.com/r/{sub}/new.json?limit=100"
    req = urllib.request.Request(url, headers={"User-Agent": "reddit-signal-mining/1.0"})
    for child in json.load(urllib.request.urlopen(req))["data"]["children"]:
        yield normalize(child["data"])
```

Agents running without Python available can use `curl` + `jq` for public JSON mode, but PRAW mode
requires Python.

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Scraping behind a Reddit block / quarantine | ToS violation; Reddit will ban the client | Respect all blocks; skip quarantined subs; note in gaps |
| Returning raw `example_quotes` verbatim | Privacy violation; HR-11 violation; may identify users | Paraphrase by default; verbatim only for 1-2 word phrases that are non-identifying |
| Using FinBERT on non-financial pain posts | FinBERT trained on financial news — misclassifies accounting workflow complaints, hobby forums, etc. | Use `all_minilm_l6_v2` or `llm_prompt` for non-financial niches; make model selection explicit |
| Treating one 429 as a permanent block | Overreacts to transient rate limits, loses data | Exponential backoff (1→2→4→8→16s), then circuit breaker at 3 consecutive failures |
| Fetching without lookback filter | Gets stale posts from 2 years ago, bloats signal with irrelevant history | Always pass `lookback_days` and honor it in the fetch |
| Storing usernames persistently | Surveillance risk, ToS violation, no operational reason to keep them | Transient-only usage; never written to disk |
| Hammering small subs | Low subscriber count → fewer natural posts → fewer rate-limit headers → easy to trip ban | Honor `min_subscribers` threshold in discover_subs; throttle more aggressively on small subs |
| Reusing heat thresholds from trading wiki without niche calibration | Trading thresholds calibrated for crypto subs (very noisy); generic subs have different baselines | See `references/velocity-heat-scoring.md` for niche calibration guidance |

---

## When NOT to Use This Skill

- **Real-time signal paths** — use the trading wiki's Redis stream pattern directly, not this
  one-shot skill
- **Anything that requires user-level tracking** — not supported, by policy
- **Private / quarantined subreddits** — blocked by policy
- **Non-Reddit platforms** — use `gdelt-event-mining` for news events, or a separate skill (HN /
  Product Hunt are on the Phase 2 roadmap)
- **Sentiment-only on a single known piece of text** — use `financial-sentiment-analysis` directly
  if you already have the text; this skill is for Reddit-sourced text
