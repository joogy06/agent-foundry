---
name: trade-journaling-and-review
description: Use when logging, reviewing, or analyzing your own executed trades — a canonical append-only trade/execution ledger schema for live fills (also consumed by equity-trading-compliance for tax views), realized expectancy and R-multiple distributions on actual fills with explicit sign and cost conventions, win-rate and hold-time breakdowns by setup, a setup/mistake/rule-violation/tilt tagging taxonomy, and the day-2 review-and-improvement loop with precommitted thresholds. Trigger on - trading journal, trade log, review my trades, expectancy, R-multiple, win rate by setup, tilt log, rule violation, post-market review. Historical strategy validation on simulated fills lives in trading-strategy-backtester; market-crowd psychology signals live in trader-psychology-analysis; live risk controls and tilt circuit-breakers live in trading-risk-management.
---

# Trade Journaling and Review

## 1. Overview + routing

This skill records and reviews **your own executed fills** — a different
artifact from backtest output. `trading-strategy-backtester` computes stats on
SIMULATED fills from historical data (and defers live logic);
`trader-psychology-analysis` models the market CROWD, never your own trades.
Neither owns the live-fill journal.

**Routing:** historical strategy validation on simulated fills →
`trading-strategy-backtester`; market-crowd psychology →
`trader-psychology-analysis`; live risk controls + tilt circuit-breakers →
`trading-risk-management` (this skill's tilt tags FEED that review); tax views
over the ledger → `equity-trading-compliance`.

## 2. Canonical trade ledger schema (single owner — shared with compliance)

This skill OWNS the canonical trade/execution ledger. `equity-trading-compliance`
CONSUMES this schema for wash-sale / 1099-B views. **One ledger, two view
owners** — this skill owns behavioral + performance views; compliance owns tax
views.

**Append-only and correction-aware:** broker corrections and busts are recorded
as NEW events, never in-place edits. History is immutable.

```
execution_record:          # immutable, one per fill
  execution_id: str        # broker-authoritative, immutable
  event_type: str          # "fill" | "correction" | "bust"
  supersedes: str | null   # execution_id this correction/bust adjusts
  ts: datetime
  symbol: str
  side: str                # buy | sell | sell_short | buy_to_cover
  quantity: int
  price: float
  fees: float
  venue: str

trade_record:              # aggregation over executions
  trade_id: str
  symbol: str
  intended_entry: float
  actual_entry: float      # slippage = actual - intended (signed by side)
  intended_exit: float
  actual_exit: float
  lot_links: list          # lot linkage for tax views (consumed by compliance)
  account_scope: str
  external_accounts_unknown: bool   # explicit when single-account
  setup_tag: str
  market_context: {gap_pct, rvol}   # from the scanning watchlist artifact
```

## 3. Realized expectancy + R-multiples (conventions explicit)

```python
def expectancy(win_rate: float, avg_win: float, avg_loss_magnitude: float):
    """Realized expectancy, net of fees.

    avg_loss_magnitude is a POSITIVE number (magnitude), not a negative return.
    """
    loss_rate = 1.0 - win_rate
    return win_rate * avg_win - loss_rate * avg_loss_magnitude


def r_multiple(realized_pnl: float, initial_risk: float):
    """R = realized P&L / initial risk (entry-to-stop at FIRST entry).

    For scale-ins/scale-outs, R is measured against the initial risk, not a
    re-based risk per add.
    """
    if initial_risk <= 0:
        raise ValueError("initial risk must be positive")
    return realized_pnl / initial_risk
```

- Expectancy is **net of fees/costs**; **avg loss is a POSITIVE magnitude** (the
  most common sign-error that inflates expectancy).
- The R **denominator** is the **initial risk at entry**; define it once and
  keep it stable across scale-ins/outs.
- **Minimum-sample honesty:** frame small samples with a confidence statement,
  not a bare n<30 cutoff.

## 4. Breakdowns

Break realized results down by **setup, time-of-day, hold-time, day-of-week**,
and inspect **drawdown sequences on realized equity** (not simulated).

## 5. Tagging taxonomy

Four tag families: **setup / mistake / rule-violation / tilt**. Tilt tags feed
`trading-risk-management`'s circuit-breaker review (a repeated tilt tag is a
signal to tighten the live kill switch, not just a journal note).

## 6. Day-2 review loop

- Yesterday's rule-violations become **today's pre-market checklist**.
- Aggregate weekly.
- **PRECOMMITTED kill/review thresholds** for a setup are registered BEFORE the
  review period, so variance cannot be rationalized away ad hoc after the fact.

## 7. Privacy note (binding)

Journals contain account balances, P&L, and personal data. Store restricted /
encrypted; **mask account IDs**; keep **no verbatim credential or
account-number content**; **redact before sharing**.

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Journaling only winners | Survivorship bias hides the losing edge | Log every executed trade, win or lose |
| Retro-tagging bias | Tagging after you know the outcome rewrites the decision | Tag setup/mistake at or near execution time |
| Editing history in place | Destroys the audit trail; corrections vanish | Append-only; record corrections/busts as new events that supersede |
| Sign-convention expectancy inflation | Treating avg loss as negative double-counts and inflates expectancy | avg loss is a positive magnitude; net of fees |
| Expectancy on tiny samples without confidence | A 5-trade "edge" is noise | Frame small samples with confidence, not a bare cutoff |
| Post-hoc kill criteria | Thresholds set after the fact rationalize bad variance | Pre-commit setup kill/review thresholds before the review period |
| Conflating backtest stats with realized stats | Simulated fills are not your fills; slippage/queue differ | Keep the live-fill journal separate from backtester output |
