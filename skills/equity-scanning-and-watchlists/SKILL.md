---
name: equity-scanning-and-watchlists
description: Use when building the pre-market routine or intraday universe screening for US equity day trading — universe definition and tradability filters, gapper scans with price/volume/float thresholds and corporate-action-adjusted baselines, earnings and catalyst calendar ingestion, LULD/halt status tracking, float and short-interest/days-to-cover lookup, relative volume (RVOL) computation, and ranked watchlist construction with a scoring template and freshness metadata. Trigger on - stock scanner, gappers, pre-market movers, watchlist, relative volume, RVOL, low float, short interest, days to cover, catalyst calendar, what to trade today. Chart-pattern recognition on a chosen symbol lives in day-trading-patterns; social and news sentiment inputs live in reddit-signal-mining, gdelt-event-mining, and financial-sentiment-analysis; historical validation lives in trading-strategy-backtester.
family: equity
---

# Equity Scanning and Watchlists

## 1. Overview + routing

This skill is the **workflow ENTRY** for equity day trading (screening stages 1
and 2 merged): it builds the tradeable universe and the ranked watchlist.
`day-trading-patterns` CONSUMES the watchlist to work a chosen symbol; this
skill selects WHICH symbols.

**Routing:** chart-pattern recognition on a chosen symbol →
`day-trading-patterns`; social/news sentiment inputs → `reddit-signal-mining` /
`gdelt-event-mining` / `financial-sentiment-analysis`; historical validation →
`trading-strategy-backtester`; order handling on a halted/resuming name →
`equity-broker-execution` §6.

## 2. Universe definition + data sources

**What is IN the universe:** NMS common stocks (vs OTC), with explicit handling
of ETF/ADR/warrant/right, recent-IPO and symbol-change cases; use stable
instrument identifiers; and run a **broker tradability/shortability check**
before a name becomes actionable.

**Data sources (verify tiers/cadence at use — see
`research/equity-day-trading-skills/scanning-journaling-research.md`):**

| Source | Fields | Cadence |
|---|---|---|
| Polygon.io | quotes/trades, reference tickers, shares outstanding, splits/dividends | real-time (paid) / delayed |
| Financial Modeling Prep | float, shares outstanding, earnings calendar | daily-ish |
| Finnhub | quotes, basic financials, earnings | mixed |
| Nasdaq Data Link | curated short-interest datasets | dataset-specific |
| Broker scanners (IBKR / Schwab) | movers + tradability/shortability | broker-authoritative |

Record, per field, WHICH source it came from and its update cadence.

## 3. Gapper scan procedure

Pre-market and intraday variants over a threshold template: gap %, price band,
minimum dollar-volume, float band, minimum-history requirement, and
exchange-calendar / early-close awareness.

**CORPORATE-ACTION-ADJUSTED baselines are mandatory.** A 10-for-1 split must not
read as a −90% gap, nor a reverse split as a +900% gap. Adjust the prior-close
baseline by corporate-action factors before computing the gap.

```python
def gap_pct(prev_close: float, premarket_price: float, split_factor: float = 1.0):
    """Corporate-action-adjusted gap. split_factor adjusts the baseline."""
    adjusted_prev = prev_close / split_factor
    if adjusted_prev <= 0:
        raise ValueError("invalid adjusted baseline")
    return (premarket_price - adjusted_prev) / adjusted_prev * 100.0
```

## 4. Catalyst calendar ingestion

Ingest earnings, FDA/PDUFA-class binary events, and macro prints; each modifies
watchlist rank. Sources: earnings calendars (FMP/Finnhub/Nasdaq/Zacks), biotech
(BioPharmaCatalyst / FDA), macro (BLS/BEA/Fed / Trading Economics / Econoday).

## 5. Float / short-interest / days-to-cover

Lookup with explicit field lineage:

> **PROHIBITION (binding).** FINRA **short interest** is a **twice-monthly
> POSITION snapshot**, published on a lag (settlement mid-month and month-end;
> take the publication date from FINRA's annual schedule — 2026 dates are
> generally about seven business days after settlement, not a fixed invariant).
> Daily **short-sale VOLUME** (FINRA daily
> files / exchange Reg SHO daily files) is an **ENTIRELY DIFFERENT FACT** and
> must **NEVER be substituted** for short interest. High daily short volume does
> NOT mean high short interest.

- **Days-to-cover** = short interest ÷ average daily volume; **define the ADV
  denominator window explicitly** (e.g. 20-day).
- Expose the **settlement date AND publication date** of any short-interest
  figure in the output so staleness is visible.

## 6. Relative volume (RVOL)

Standard form: cumulative volume to the current time-of-day ÷ the average
cumulative volume at the **same time of day** over a lookback (e.g. 20
sessions). Time-of-day normalization is essential — 2× at 09:45 differs from 2×
at 15:45. Guard new listings / thin history with a minimum-history check.

## 7. LULD / halt status tracking

Track pre-open halt lists and resumption status. LULD bands and pauses apply
during regular hours only (WATCH as of 2026-07-14 — an SEC overnight price-band
amendment, SR filing 34-105596, is pending; re-verify before overnight use).
For ORDER handling on a halted/resuming name, hand
off to `equity-broker-execution` §6 — this skill tracks status, it does not
place orders.

## 8. Ranked watchlist construction

Combine gap, RVOL, float, and catalyst weight into a scoring template; enforce a
**max-size discipline** (a bounded watchlist). The output artifact carries
REQUIRED per-field metadata:

```
watchlist_item:
  symbol: str
  score: float
  fields:
    gap_pct:        {value, source, as_of, latency_class, adjustment_state}
    rvol:           {value, source, as_of, latency_class}
    float_shares:   {value, source, as_of}
    short_interest: {value, source, settlement_date, publication_date}
```

Every field carries source, as-of timestamp, latency class, and adjustment
state — a number with no provenance is not actionable.

## 9. Unattended-mode caveat (TW-4) — first-class

**Attended mode is the default framing** — a human bridges gaps in seconds, so
attended failure is SAFE (worst case: no trades).

**UNATTENDED mode FAILS CLOSED on more than emptiness.** Halt the pipeline and
ALERT — never trade off — when the watchlist is:

- **empty** (no candidates),
- **stale** (as-of older than the freshness threshold),
- **degraded** (missing required fields or a required source is down),
- **divergent** (sources disagree beyond tolerance), or
- **anomalously large** (output far bigger than the historical norm).

A stale watchlist that LOOKS healthy is more dangerous than a silent no-op — it
invites trading on yesterday's world. Fail closed and alert; do not proceed on a
non-empty-but-unverified list.

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Scanning without RVOL normalization | Raw volume favors large caps and misreads time-of-day | Use time-of-day-normalized RVOL over a lookback window |
| Passing daily short-sale volume off as short interest | They are different facts; the derived signal is wrong | Use the twice-monthly SI snapshot for SI; never substitute daily short volume |
| Unadjusted gap baselines across splits/dividends | A split reads as a huge phantom gap | Apply corporate-action-adjusted baselines before computing gaps |
| Treating stale short interest as current | SI publishes on a lag; the position may have unwound | Expose settlement + publication dates; judge staleness explicitly |
| Unbounded watchlists | Too many names dilute focus and rank | Enforce a max-size discipline in construction |
| Sentiment-only universes | Social buzz without price/float/volume structure is noise | Build the universe on price/volume/float; treat sentiment as an input, not the universe |
| Unattended trust in a non-empty list | Stale/degraded/divergent lists look healthy but are wrong | Fail closed on empty/stale/degraded/divergent/anomalous; alert, never trade off it |
