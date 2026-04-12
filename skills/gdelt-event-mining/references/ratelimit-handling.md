# Rate Limit Handling — GDELT 429, Backoff, RSS Fallback

The trading wiki explicitly documents: `GDELT hits rate-limit (429) periodically`. This is a
known pain, not a bug in your code. This reference ports the trading pattern and adapts it for
one-shot research use.

---

## Backoff Protocol

```
attempt 1: immediate
attempt 2: wait 1s
attempt 3: wait 2s
attempt 4: wait 4s
attempt 5: wait 8s
attempt 6: wait 16s
attempt 7+: circuit breaker opens (see below)
```

Max 6 attempts per request. After that, the skill gives up on this query and either:
1. Moves to RSS fallback (if applicable)
2. Marks the query as failed in metadata
3. Returns partial results (if some queries succeeded)

### When to treat a response as retry-worthy

Retry on:
- HTTP 429 (explicit rate limit)
- HTTP 500, 502, 503, 504 (transient server errors)
- Network timeout
- Empty response body with 200 status (observed GDELT quirk — sometimes returns empty JSON)
- Malformed JSON (another observed quirk under load)

Do NOT retry on:
- HTTP 400, 404, 422 (bad query — won't improve with retry)
- HTTP 403 (blocked — retry won't fix)
- HTTP 413 (query too large — reduce `maxrecords` and re-submit as a new request)

---

## Circuit Breaker

Per-session GDELT failure counter:

```
failure_count < 3: CLOSED (normal)
failure_count >= 3: OPEN — mark GDELT unavailable
  - skip further GDELT queries for 5 minutes
  - switch all pending queries to RSS fallback
after 5 minutes: HALF_OPEN
  - attempt one test query
  - on success: reset counter, reopen GDELT
  - on failure: stay OPEN, wait another 5 minutes
```

This is a direct port of the trading wiki's circuit breaker pattern. `reddit.py` uses the same
"3 failures in a row → 5min skip" pattern for Reddit; `news.py` for GDELT.

### What counts as a "failure" for the counter

Consecutive retry-exhaustions. A single 429 that succeeds on the second attempt does NOT
increment the counter. The counter tracks requests that failed all 6 attempts in a row.

A successful request resets the counter to 0.

---

## RSS Fallback Decision Tree

When GDELT circuit opens, the skill switches to RSS fallback:

```
1. Do we have an RSS feed list configured for this query's theme/location?
   YES → proceed to step 2
   NO  → return empty result with metadata.data_source = "gdelt_unavailable_no_rss"

2. Fetch each RSS feed in parallel (up to 5 concurrent)
3. Parse RSS items into event-like records:
   - event_id: "rss:<feed_url>:<guid>"
   - date: pub_date
   - actor1: feed title (e.g., "Reuters Business")
   - event_code: null
   - event_description: RSS title
   - themes: [caller-provided theme, since RSS has no theme coding]
   - locations: []
   - tone: null
   - source_url: item link
   - source_name: feed title
4. Dedup by source_url
5. Return with metadata.data_source = "gdelt+rss_fallback v1"
   and metadata.gaps = ["gdelt_unavailable: circuit_open", "tone_unavailable", "cameo_codes_unavailable"]
```

### What RSS fallback cannot do

- Compute velocity ratios (no historical baseline from RSS fetches)
- Provide CAMEO event codes
- Provide tone scores
- Provide entity extraction (actor1 / actor2 structured fields)
- Cover non-English sources

Callers MUST check `metadata.data_source` and degrade gracefully. Founder-ideation's trend-first
team, for example, should mark outputs derived from RSS-fallback data as `confidence:
"speculative"` by default because inflection signal is not computable.

---

## Default RSS Feed List

Callers can override, but the default fallback list is:

```yaml
business_technology:
  - https://feeds.reuters.com/reuters/businessNews
  - https://feeds.reuters.com/reuters/technologyNews
  - https://feeds.arstechnica.com/arstechnica/index
  - https://techcrunch.com/feed/
  - https://feeds.feedburner.com/TheHackersNews
regulatory_policy:
  - https://www.regulations.gov/search?filter=rule&sortBy=docketId  # HTML, not RSS — handle carefully
  - https://feeds.reuters.com/Reuters/PoliticsNews
healthcare:
  - https://feeds.statnews.com/statnews
  - https://feeds.feedburner.com/fierce-healthcare
energy_environment:
  - https://feeds.reuters.com/reuters/environment
  - https://www.greentechmedia.com/rss/all
```

These are examples — callers should maintain their own per-niche feed lists. The skill exposes a
`rss_feed_override` parameter.

---

## Monitoring Rate-Limit Health

The skill tracks per-session:
- Total GDELT queries attempted
- Total 429s encountered
- Total retries
- Total circuit breaker openings
- Total RSS fallback activations

All are included in output metadata as `rate_limit_stats`. Callers can use this to detect
degraded conditions and decide whether to escalate to the user ("GDELT was flaky this session, 3
of your 5 queries fell back to RSS — signal quality is degraded").

---

## Observed GDELT Quirks (from trading wiki experience)

1. **Weekend ramp-down** — GDELT endpoint is slower / more 429-prone on Sundays. Allegedly due to
   reduced server capacity during low-traffic periods.
2. **Empty JSON with 200 status** — GDELT occasionally returns `{"articles": []}` with a 200 code
   when it actually rate-limited. Treat as a soft failure and retry after a short wait (2s).
3. **Malformed JSON under load** — Under heavy load, JSON responses can be truncated. Catch
   JSONDecodeError and retry.
4. **`mode=TimelineVolInfo` sometimes returns a date far outside requested range** — known bug.
   Filter client-side after fetching.
5. **Large `maxrecords`** — values > 250 tend to 429 faster. Stick to ≤ 250 per request, paginate
   if more needed.
6. **`timespan` vs explicit date range** — `timespan` is more reliable; explicit date ranges
   sometimes return empty. Prefer `timespan` when possible.

Don't try to fix GDELT's server-side issues. Handle them gracefully and document the gap.
