# Industry Inflection — Velocity Scoring and False-Signal Guards

The `inflection_scan` operation detects themes that are inflecting (current velocity significantly
above baseline). Thresholds and guards ported from the trading wiki's `heat_scanner.py` pattern,
calibrated for GDELT's event-volume characteristics.

---

## Velocity formula

```
velocity_current  = events_in_lookback / lookback_days
velocity_baseline = events_in_baseline / baseline_days

ratio = velocity_current / velocity_baseline
```

Baseline window MUST be ≥ 7 days (HARD rule) and MUST be disjoint from lookback. The skill
computes baseline as `[-baseline_days, -lookback_days]` to keep them non-overlapping.

## Tier thresholds

```
ratio < 1.5         → COLD   (no inflection)
1.5 ≤ ratio < 2.5   → WARM   (noticeable acceleration)
2.5 ≤ ratio < 5     → HOT    (significant surge)
ratio ≥ 5           → FIRE   (major inflection)
```

These match the reddit-signal-mining skill's thresholds for consistency across the data-mining
family.

## Tone momentum (second dimension)

GDELT records a `tone` value per event. Inflection ratio tells you volume is up; tone momentum
tells you sentiment is shifting.

```
tone_mean_current  = mean(AvgTone, current_events)
tone_mean_baseline = mean(AvgTone, baseline_events)

tone_delta = tone_mean_current - tone_mean_baseline
```

Use cases:
- `ratio ≥ 2.5` + `tone_delta < -2` → HOT_NEGATIVE (volume up, tone worse — crisis or backlash)
- `ratio ≥ 2.5` + `tone_delta > +2` → HOT_POSITIVE (volume up, tone better — breakout / adoption)
- `ratio ≥ 2.5` + `|tone_delta| < 2` → HOT_NEUTRAL (volume up, tone unchanged — volume-only signal)

For founder-ideation, HOT_NEGATIVE is often the most actionable (where's the pain emerging?) but
HOT_POSITIVE is where growth ideation lives.

## False-signal guards

Flag these in output metadata — do NOT auto-suppress unless the caller explicitly requests it.

### 1. Sparse baseline

If `events_in_baseline < 50`, the ratio is unreliable. Tier is forced to `INSUFFICIENT_BASELINE`
and a warning is added to metadata. Default threshold is 50 because GDELT event density varies
enormously across themes (some themes get thousands per day, some get a dozen per month).

Caller can override via `min_baseline_events` parameter.

### 2. Single-source dominance

If one source domain (`SOURCEURL` pattern) accounts for > 40% of lookback events, flag as
`SINGLE_SOURCE_INFLATED`. A single outlet running a series of related articles can dominate
theme volume without indicating a broader shift.

### 3. Event-chain inflation

If > 50% of lookback events have the same `GLOBALEVENTID` root (events that are reports ABOUT the
same underlying event), flag as `EVENT_CHAIN_INFLATED`. This happens when one big event gets
reported 100 times — it's ONE inflection point, not a broad trend.

Dedup events by clustering URLs with the same domain + date + near-identical title before
counting.

### 4. Language bias

GDELT's English coverage is much deeper than non-English. If `lookback_events` are ≥ 95% English,
flag as `EN_BIAS` and note that this may reflect English-news cycle more than global reality.

### 5. Holiday / weekend artifacts

News volume drops on weekends and holidays. A baseline that includes many weekends vs a lookback
that avoids them can create false inflections. For short lookback windows (< 14 days), normalize
by business-day count rather than calendar days:

```
velocity_current_adj  = events_in_lookback / business_days_in_lookback
velocity_baseline_adj = events_in_baseline / business_days_in_baseline
```

Use `workalendar` or a simple Monday-Friday filter.

---

## Niche calibration

Different themes have different baseline volatility. `TECH_CYBER_ATTACK` has high baseline
volatility (cyber incidents happen constantly); `TECH_QUANTUM` has low baseline volatility
(quantum milestones are rare).

Rough calibration guidance:

| Theme family | Baseline volatility | Threshold adjustment |
|---|---|---|
| Regulatory (`LEG_*`) | Low | Default — 1.5/2.5/5 is reasonable |
| Tax / economic (`ECON_*`) | Medium | Default |
| Cyber (`TECH_CYBER_*`) | High | +0.5 on all thresholds |
| Geopolitical (`CONFLICT_*`, `TERROR_*`) | Very high | +1.0 on all thresholds |
| Pandemic / health crisis (`HEALTH_PANDEMIC`) | Bursty (quiet → sudden surge) | Default thresholds OK; expect FIRE tier during actual outbreaks |

---

## Example inflection output

```yaml
inflections:
  - theme: ECON_TAXATION
    velocity_current: 42.8       # events per day (last 7 days)
    velocity_baseline: 18.3      # events per day (last 30, excluding last 7)
    ratio: 2.34
    tier: WARM
    tone_mean_current: -4.1      # slightly negative
    tone_mean_baseline: -2.2
    tone_delta: -1.9             # tone slightly worse
    top_events:
      - event_id: "1234567890"
        date: "2026-04-08"
        location: "United Kingdom"
        actor1: "HM Revenue & Customs"
        actor2: null
        event_description: "Make statement: new VAT enforcement"
        source_url: "https://www.gov.uk/..."
        tone: -3.5
    hypothesis: "hypothesis: UK tax authority appears to be stepping up enforcement activity"
    false_signal_flags: []
```

The `hypothesis` field is always prefixed `hypothesis:` so callers (and founder-ideation's
trend-first team) know it's LLM-interpretive, not raw signal.
