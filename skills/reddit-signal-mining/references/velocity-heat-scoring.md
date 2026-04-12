# Velocity Heat Scoring — WARM/HOT/FIRE Tiers

Ported from the trading wiki's `heat_scanner.py` pattern. Same structure, re-calibrated for
research use cases (not real-time trading signals).

## Core formula

```
ratio = current_velocity / baseline_velocity

current_velocity  = posts_in_lookback / lookback_days
baseline_velocity = posts_in_baseline / baseline_days
```

Where:
- `lookback_days` = recent window (default 7 days)
- `baseline_days` = trailing baseline (default 30 days) — must NOT overlap with lookback

The skill computes `baseline` from day `-baseline_days` to day `-lookback_days`, so the two windows
are disjoint.

## Tier thresholds

```
ratio < 1.5       → COLD   (no heat)
1.5 ≤ ratio < 2.5 → WARM   (noticeable increase)
2.5 ≤ ratio < 5   → HOT    (significant surge)
ratio ≥ 5         → FIRE   (dramatic inflection)
```

**Calibration note:** These thresholds are slightly more conservative than the trading wiki's
thresholds. Trading's signals feed a live algo where false positives are expensive; research
use cases can afford to be slightly more sensitive, but over-sensitivity produces too much "oh
something is slightly above average" noise. The founder use case is "spot real inflections, not
minor waves."

## Engagement velocity (second dimension)

Post velocity alone can be gamed (a single viral post from a crosspost doesn't mean the community
is talking more about X). Second dimension: engagement velocity.

```
engagement_current  = sum(upvotes + comments, current_posts) / lookback_days
engagement_baseline = sum(upvotes + comments, baseline_posts) / baseline_days

engagement_ratio    = engagement_current / engagement_baseline
```

**Combined tier rule:**
- If `ratio ≥ 5` AND `engagement_ratio ≥ 3`: real FIRE
- If `ratio ≥ 5` AND `engagement_ratio < 3`: FIRE_SUSPICIOUS (flagged — may be a single viral
  post inflating the count; check `top_trending_posts` to confirm)
- If `ratio ≥ 2.5` AND `engagement_ratio ≥ 2`: HOT
- Similar logic for WARM (both dimensions ≥ 1.5)

## False-signal guards

Flag these in output metadata (do NOT auto-suppress — let the caller decide):

### 1. Too-small baseline

If `posts_in_baseline < min_baseline_posts` (default 50), the ratio is unreliable. Tier is forced
to `INSUFFICIENT_BASELINE` and the caller is warned.

### 2. Crosspost inflation

Count the proportion of `is_crosspost` posts in the lookback. If > 30%, flag as
`CROSSPOST_INFLATED`. A sub's velocity can spike artificially when a meme from a large sub gets
cross-posted en masse.

### 3. Single-post dominance

If one post accounts for > 50% of the engagement in the lookback, flag as `SINGLE_POST_DOMINATED`.
The "heat" is actually about one viral thread, not a broader shift.

### 4. Automod / bot inflation

Count posts by the top 3 most active accounts in lookback. If > 40% of posts are from 3 accounts,
flag as `BOT_OR_POWER_USER_INFLATED`.

## Niche calibration

Different subs have very different baseline volatility. An r/Accounting spike to 2x baseline is a
real signal; an r/wallstreetbets spike to 2x baseline is just a normal Tuesday.

Calibration guidance:

| Subreddit type | Expected baseline volatility | Threshold adjustment |
|---|---|---|
| Professional niche (r/Accounting, r/msp) | Low | Default thresholds — 1.5/2.5/5 |
| Hobby community (r/3Dprinting, r/homelab) | Low-Medium | Default |
| Tech/software (r/webdev, r/devops) | Medium | +0.5 on all thresholds |
| Finance/crypto (r/stocks, r/CryptoCurrency) | High | +1.0 on all thresholds |
| Meme-driven (r/wallstreetbets, r/antiwork) | Very high | +1.5 on all thresholds |
| News/event-driven (r/worldnews) | Volatile | Skip heat scan; use event-mining instead |

Callers can pass a `threshold_adjustment` parameter to tune per sub. Default is 0 (no adjustment).

## Output considerations

For each sub in the heat output, include:
- The raw `ratio` AND the `engagement_ratio` (both dimensions)
- The tier with any false-signal flags attached
- Up to 5 `top_trending_posts` (paraphrased titles only — for caller spot-check and for
  founder-ideation's `trend-first` team to read as raw grounding data)
- `metadata.gaps` for any subs that failed to fetch

Never return the full post bodies in the heat scan output — that's for the `mine_pains` operation.
`heat_scan` is a velocity signal, not a content extraction.
