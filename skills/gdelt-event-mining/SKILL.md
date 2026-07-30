---
name: gdelt-event-mining
description: >
  Use when a caller needs to query GDELT 2.0 (Global Database of Events, Language, and Tone) for
  industry events, theme velocity, inflection detection, or macro trend grounding. Supports
  events_by_theme, inflection_scan, and location_events operations. Reusable by founder-ideation
  (for trend-first team data), research-*, geopolitical-market-impact, and any caller that needs
  global event signal grounding. One-shot fetch-analyze-return. Trigger on: "query GDELT",
  "industry inflections", "event velocity for theme X", "what global events relate to Y",
  "macro trends in Z".
disambiguation: GDELT 2.0 — global news events, themes and tone at macro scale. First-person pain points and community sentiment from Reddit are reddit-signal-mining.
---

# GDELT Event Mining

Extract structured event signal from GDELT 2.0 — the public global news event cube. Returns
normalized event records, theme velocity, and inflection tier detection with provenance. One-shot
research tool, not a live stream.

**Scope:** GDELT 2.0 Event DB, Global Knowledge Graph (GKG), Doc DB. Does NOT provide idea
generation — callers do that with the data.

**Callers:**
- `founder-ideation` (Phase 1) — feeds `trend-first` team with inflection signal
- `geopolitical-market-impact` — cross-references event codes with market impact modeling
- Any research workflow that needs macro-grounded data

**Proven pattern source:** The trading wiki's `signals:news` stream (`news.py` at
`/path/to/projects/trading/src/data_pipeline/news.py`) combines GDELT + RSS with `TopicMatcher` and
heat scoring. Documented pain: `GDELT hits rate-limit (429) periodically`. This skill ports the
pattern (GDELT query + 429 retry + RSS fallback + theme heat scoring) but not the
Redis-streaming / live-poller infrastructure. Research use case = one-shot.

---

<HARD-RULE>
**Respect GDELT API rate limits.** GDELT's public endpoints are shared and under documented rate
pressure. On 429, back off exponentially (1s → 2s → 4s → 8s → 16s → skip) and circuit-breaker at
3 consecutive failures. Never hammer. Never parallelize more than 2 GDELT queries simultaneously.
</HARD-RULE>

<HARD-RULE>
**Fall back to RSS when GDELT fails.** If GDELT returns 429 three or more times in a row, switch
to RSS feed fallback (configurable feed list) and mark the output with `data_source: "gdelt+rss_fallback"`
and `gaps: ["gdelt_unavailable: <reason>"]`. The caller MUST see degradation explicitly.
</HARD-RULE>

<HARD-RULE>
**Cite GDELT event IDs in all output.** Every event record, every inflection, every theme velocity
reading must include the underlying GDELT event ID (or RSS URL for fallback). Provenance is
mandatory — callers rely on this for the HR-5 "every idea must cite data source" rule in
founder-ideation.
</HARD-RULE>

<HARD-RULE>
**No over-extraction.** Cap per-query result sets at reasonable limits (default 500 events per
query, 50 inflections per scan). Never request unbounded result sets. Respect GDELT's "please
don't abuse us" docs.
</HARD-RULE>

<HARD-RULE>
**Minimum baseline ≥ 7 days.** The inflection scan requires a baseline of at least 7 days to
avoid false inflection signals from single-day noise. Reject caller requests that pass
`baseline_days < 7` with a clear error.
</HARD-RULE>

---

## Operations

### 1. `events_by_theme`

Fetch events in one or more GDELT themes within a time window.

**Inputs:**
```yaml
operation: "events_by_theme"
themes: list[string]            # V2Theme codes, e.g. ["ECON_TAXATION", "LEG_REGULATORY"]
locations: list[string]         # optional — ISO-3 country codes (e.g. ["USA", "GBR"])
lookback_days: int              # default 30
limit: int                      # default 500, max 2000
```

**Approach:**
1. Build GDELT 2.0 Event DB query using the GDELT Doc API 2.0 (`api.gdeltproject.org/api/v2/doc/doc`)
2. Filter by theme + optional location + time range
3. Parse returned records into normalized event format
4. Dedup by `SOURCEURL` (same URL reported by multiple outlets)
5. Return up to `limit` records sorted by date desc

**Output:**
```yaml
events:
  - event_id: string            # GDELT GlobalEventID
    date: string                # ISO date
    actor1:
      name: string
      country: string
      type: string              # CAMEO actor type code
    actor2: { ... }             # optional
    event_code: string          # CAMEO event code (e.g. "030" = "Express Intent to Cooperate")
    event_description: string   # human-readable from CAMEO
    themes: list[string]        # V2Themes
    locations: list[string]
    tone: float                 # -100..+100 from GDELT's tone analysis
    source_url: string
    source_name: string
metadata:
  data_source: "gdelt-event-mining v1, pulled YYYY-MM-DD"
  operation: "events_by_theme"
  queried_at: timestamp
  query_count: int
  gaps: list[string]
```

See `references/gdelt-api-reference.md` for query syntax.

### 2. `inflection_scan`

Detect themes that are inflecting (current velocity / baseline velocity ratio exceeds threshold).

**Inputs:**
```yaml
operation: "inflection_scan"
themes: list[string]            # themes to scan
locations: list[string]         # optional geographic filter
lookback_days: int              # current window, default 7
baseline_days: int              # baseline window, default 30 (must be ≥ 7)
threshold_ratio: float          # minimum inflection ratio, default 2.0
limit: int                      # max inflections to return, default 50
```

**Approach:**
1. For each theme, query event count in lookback window
2. Query event count in baseline window (disjoint from lookback)
3. Compute `velocity_current = count_lookback / lookback_days`
4. Compute `velocity_baseline = count_baseline / baseline_days`
5. Compute `ratio = velocity_current / velocity_baseline`
6. Tier (see `references/industry-inflection.md`):
   - `WARM`: 1.5 ≤ ratio < 2.5
   - `HOT`: 2.5 ≤ ratio < 5
   - `FIRE`: ratio ≥ 5
7. For each inflecting theme, fetch top 5 events from the current window as exemplars
8. Generate a one-sentence LLM hypothesis for WHY it's inflecting (optional; degrades to empty
   string if no LLM budget)

**Output:**
```yaml
inflections:
  - theme: string
    velocity_current: float     # events per day in lookback
    velocity_baseline: float    # events per day in baseline
    ratio: float
    tier: enum                  # WARM | HOT | FIRE
    top_events:
      - event_id: string
        date: string
        location: string
        actor1: string
        actor2: string
        event_description: string
        source_url: string
        tone: float
    hypothesis: string          # 1-sentence LLM-generated "why is this inflecting"
                                # prefixed with "hypothesis:" so caller knows it's not evidence
metadata:
  data_source: "gdelt-event-mining v1"
  operation: "inflection_scan"
  queried_at: timestamp
  lookback_days: int
  baseline_days: int
  gaps: list[string]
```

### 3. `location_events`

Fetch events by location (useful for "what's happening in {country} around {industry}").

**Inputs:**
```yaml
operation: "location_events"
locations: list[string]         # ISO-3 country codes
themes: list[string]            # optional filter
lookback_days: int              # default 30
limit: int                      # default 500
```

Same output format as `events_by_theme`, just filtered by location.

---

## Theme Taxonomy

GDELT 2.0 uses the V2Themes taxonomy — a hierarchical catalog with tens of thousands of codes. For
founder-ideation use cases, callers don't need the full catalog — they need the common themes
that map to industries.

See `references/theme-taxonomy.md` for the curated founder-relevant theme list, including:
- Economic (tax, regulation, finance, labor, inflation, currency)
- Technology (AI, crypto, cyber, data, infrastructure)
- Healthcare (drugs, devices, policy, providers, payers)
- Energy (oil, renewables, nuclear, grid)
- Regulatory (new laws, enforcement, compliance)
- Labor (unions, workforce, automation impact)
- Geopolitical (sanctions, conflict, trade)
- Consumer (retail, e-commerce, CPG)

Plus mapping tables: theme → industry → typical founder use case.

---

## CAMEO Event Codes

GDELT 2.0 uses CAMEO (Conflict and Mediation Event Observations) event codes for event types. For
founder use cases, the interesting subsets are:

- `01x` — Make public statement (announcement signals)
- `02x` — Appeal (demand signals)
- `03x` — Express intent to cooperate (deal signals)
- `04x` — Consult (due-diligence signals)
- `05x` — Engage in diplomatic cooperation (alliance signals)
- `06x` — Engage in material cooperation (deal-signed signals)
- `07x` — Provide aid (funding signals)
- `08x` — Yield (concession / policy change signals)
- `09x-19x` — Investigate / demand / reject / threaten (escalation signals)
- `20x` — Use conventional military force
- etc.

For ideation, codes `01x-08x` are usually most relevant (signals of activity, not conflict). For
risk / regulatory / geopolitical ideation, `10x-20x` are also useful.

See `references/theme-taxonomy.md#cameo-codes` for the full list with founder use-case examples.

---

## GDELT API Endpoints Used

### Doc API 2.0 (primary)

```
https://api.gdeltproject.org/api/v2/doc/doc?query=<query>&mode=ArtList&format=json&timespan=<N>days
```

- Full-text query support
- Theme filter: `theme:ECON_TAXATION`
- Location filter: `sourcelang:eng sourcecountry:US`
- Date filter: `timespan:7days` or explicit date range
- Modes: `ArtList` (article list), `TimelineVolInfo` (volume over time), `ToneChart` (tone histogram)

### GKG 2.1 (extended metadata)

```
http://data.gdeltproject.org/gdeltv2/<timestamp>.gkg.csv.zip
```

Downloadable 15-minute update files. Richer metadata (themes, tone, people, orgs, locations). Used
when caller needs full entity extraction rather than headlines. Heavier, use sparingly.

### Events 2.0 (structured event records)

```
http://data.gdeltproject.org/gdeltv2/<timestamp>.export.CSV.zip
```

CAMEO-coded event records. Actor1, Actor2, event code, tone, location, URL.

See `references/gdelt-api-reference.md` for full query syntax, rate limits, and response schemas.

---

## RSS Fallback

When GDELT rate-limits or is down, the skill falls back to a curated RSS feed list per industry.
The fallback is NOT equivalent in coverage (RSS is English-only, typically US/UK outlets, no CAMEO
codes) but provides degraded continuity.

Default RSS feed list (configurable per caller):
- `feeds.reuters.com/reuters/businessNews`
- `feeds.reuters.com/reuters/technologyNews`
- `www.ft.com/?format=rss` (where accessible)
- `www.bloomberg.com/feed/podcast/etf-report.xml`
- `news.google.com/rss/search?q=<theme>&hl=en-US`

RSS fallback mode:
- Cannot compute velocity ratios (no historical baseline from RSS)
- Cannot resolve CAMEO codes
- Returns `event_code: null`, `tone: null`, `event_id: rss:<feed>:<guid>`
- `metadata.data_source: "gdelt+rss_fallback v1"`
- `metadata.gaps: ["gdelt_unavailable: <reason>"]`

See `references/ratelimit-handling.md` for the full fallback decision tree.

---

## Rate Limit Handling

```python
# Pseudo-code — agent emits this at runtime
import time, urllib.request

def fetch_with_backoff(url, max_retries=5):
    backoff = 1
    for attempt in range(max_retries):
        try:
            return urllib.request.urlopen(url, timeout=30).read()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise
        except Exception:
            time.sleep(backoff)
            backoff *= 2
            continue
    raise RuntimeError("GDELT unavailable after retries")
```

Circuit breaker:
- 3 consecutive 429s → mark GDELT unavailable for 5 minutes
- Switch to RSS fallback
- After 5 minutes, HALF_OPEN → try one GDELT query; success reopens, failure stays degraded

See `references/ratelimit-handling.md` for the full protocol.

---

## Reference Files

- `references/gdelt-api-reference.md` — Doc API / GKG / Events endpoint reference, query syntax,
  response schemas, example queries
- `references/theme-taxonomy.md` — Curated V2Themes list, CAMEO event codes, industry mapping
  tables
- `references/industry-inflection.md` — Velocity scoring, tier thresholds, false-signal guards,
  niche calibration
- `references/ratelimit-handling.md` — Backoff protocol, circuit breaker, RSS fallback decision
  tree, known GDELT pain points (ported from trading wiki)

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Parallelizing > 2 GDELT queries | GDELT's shared infra responds with 429 under load; parallelism makes it worse, not better | Sequentialize with small concurrency cap; use RSS fallback if needed |
| Hitting GDELT with broad queries and filtering client-side | Wastes bandwidth, trips rate limits faster | Push filters server-side via theme + location + date params |
| Trusting tone scores as sentiment ground truth | GDELT tone is approximate; tuned for news articles, not social media | Use tone as a secondary signal, cross-reference with content |
| Treating 429 as a permanent error | Over-reacts to transient rate limits, loses access | Exponential backoff (1→2→4→8→16s); circuit breaker at 3 consecutive failures |
| Baseline < 7 days for inflection scan | Single-day noise triggers false inflections | Enforce `baseline_days >= 7` at input validation |
| Skipping RSS fallback because "RSS is worse" | Degraded data is better than no data when GDELT is down | Always configure RSS fallback, mark output with degradation flag |
| Emitting inflection hypotheses without the "hypothesis:" prefix | Callers mistake LLM speculation for GDELT evidence | Always prefix LLM-generated hypothesis with `hypothesis:` so callers (and founder-ideation) know it's interpretive, not raw signal |

---

## When NOT to Use This Skill

- **Real-time event streaming** — use trading wiki's live poller + Redis stream pattern
- **Social media signal** — use `reddit-signal-mining` or (Phase 2) `hn-pain-mining`, etc.
- **Company-level news** — GDELT is macro-grade; for company news, use a dedicated RSS feed or
  a focused crawler
- **Sub-national / city-level events** — GDELT's location resolution is country + region,
  city-level is inconsistent
- **Non-English content coverage** — GDELT covers many languages but non-English theme coding is
  less reliable
