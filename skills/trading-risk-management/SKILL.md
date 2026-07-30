---
name: trading-risk-management
description: Use when implementing kill switches, circuit breakers, position sizing, drawdown controls, VaR/CVaR calculations, Kelly criterion, or correlation-based portfolio risk management for automated trading systems. Also covers risk-constrained allocation overlays (applying constraints, risk budgets, and feasibility checks over externally-supplied point-in-time forecasts - never producing forecasts), benchmark and return conventions, factor/benchmark exposure analysis, cost-aware rebalance/turnover analysis, ex-ante vs realized risk attribution (risk contribution, not performance attribution), and serializing kill-switch state into the runtime's append-only persistent halt record. Trigger on - portfolio construction, risk budget, risk-constrained allocation, risk attribution, risk contribution, rebalance turnover, factor exposure, persistent halt state
family: trading
---

# Trading Risk Management

## Overview

Risk management is the most critical component of any automated trading system. A profitable strategy without risk controls will eventually blow up. Design for the **worst case**, not the average case.

**Core principle:** Risk controls must be **enforced at the infrastructure level**, not as suggestions in strategy code.

## When to Use

- Designing position sizing algorithms
- Implementing kill switches and circuit breakers
- Setting up drawdown monitoring and auto-halt systems
- Calculating VaR/CVaR for portfolio risk
- Managing correlated position exposure
- Exchange-specific risk limit configuration

## Kill Switch Architecture

```python
import asyncio
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

class TradingState(Enum):
    ACTIVE = "active"
    HALTED = "halted"
    EMERGENCY_EXIT = "emergency_exit"

@dataclass
class RiskMetrics:
    daily_pnl: float
    drawdown_pct: float
    open_positions: int
    gross_exposure: float
    last_updated: datetime

class KillSwitch:
    """Infrastructure-level kill switch. Checked before EVERY order."""

    def __init__(self, config: dict):
        self.state = TradingState.ACTIVE
        self.max_daily_loss_pct = config['max_daily_loss_pct']   # e.g. 0.02 = 2%
        self.max_drawdown_pct   = config['max_drawdown_pct']     # e.g. 0.05 = 5%
        self.max_positions      = config['max_positions']         # e.g. 10
        self.max_gross_exposure = config['max_gross_exposure']    # e.g. 1.5 = 150% NAV
        self.halt_reasons: list[str] = []

    def check(self, metrics: RiskMetrics, capital: float) -> bool:
        """Returns True if trading is permitted. False = halt."""
        self.halt_reasons.clear()

        if metrics.daily_pnl / capital < -self.max_daily_loss_pct:
            self.halt_reasons.append(f"Daily loss limit: {metrics.daily_pnl/capital:.2%}")

        if metrics.drawdown_pct > self.max_drawdown_pct:
            self.halt_reasons.append(f"Drawdown limit: {metrics.drawdown_pct:.2%}")

        if metrics.open_positions > self.max_positions:
            self.halt_reasons.append(f"Position count: {metrics.open_positions}")

        if metrics.gross_exposure / capital > self.max_gross_exposure:
            self.halt_reasons.append(f"Gross exposure: {metrics.gross_exposure/capital:.2%}")

        if self.halt_reasons:
            self.state = TradingState.HALTED
            return False

        return self.state == TradingState.ACTIVE

    def emergency_exit(self, reason: str):
        """Trigger immediate close-all-positions mode."""
        self.state = TradingState.EMERGENCY_EXIT
        self.halt_reasons.append(f"EMERGENCY: {reason}")
```

## Registered Pre-Trade Guards

The `KillSwitch` check chain runs registered pre-trade guards before EVERY
order. For US equities, `equity-trading-compliance` registers its day-trade
guard here — **for EXPOSURE-INCREASING orders only**:

```python
def check_pretrade_guards(order_intent, account_snapshot,
                          broker_policy_snapshot, as_of):
    # Registered by equity-trading-compliance for exposure-increasing orders.
    # Canonical signature + full contract:
    #   equity-trading-compliance/references/guard-contract.md
    verdict = day_trade_permitted(order_intent, account_snapshot,
                                  broker_policy_snapshot, as_of)
    if verdict.verdict == "reject_fail_closed":
        return False                     # block new exposure
    if verdict.verdict == "liquidation_only":
        return "cancel_and_reduce_only"  # exits only, no new exposure
    return True                          # "permit" -> other checks decide
```

**Liquidation carve-out (binding):** kill-switch `HALTED` / `EMERGENCY_EXIT`
states and guard `reject_fail_closed` verdicts block NEW exposure while
authorizing cancel-and-reduce operations — **exits are never gated shut**.

This registration point holds the CALL SITE and enforcement mapping ONLY. All
regime/tax knowledge (PDT vs risk-based intraday margin, wash sale, §475(f),
locate) lives in `equity-trading-compliance` — one gate, one knowledge owner.
See the shared conformance checklist at
`equity-trading-compliance/references/guard-contract.md`.

### KillSwitch state serialization (persistent halt record)

`trading-automation-runtime` persists halt state across restarts (a restart must never
silently clear a halt). To make `KillSwitch` state durable, serialize it into the
runtime's **append-only, versioned halt-record shape** — `(source, epoch, reason,
asserted_at, cleared_at, cleared_by)` written with compare-and-swap semantics so a stale
writer cannot erase a newer halt. **No threshold logic moves** — the thresholds,
`RiskMetrics`, and the `check()` decision stay here; only a serializable projection of the
current state crosses the seam.

```python
def to_halt_record(kill_switch, source: str, epoch: int, now):
    """Project KillSwitch state into the runtime's append-only halt-record shape.

    The runtime PERSISTS and RELOADS this; it never writes the risk halt cause itself.
    """
    if kill_switch.state.value == "active":
        return None                               # no active halt to persist
    return {
        "source": source,                         # this skill owns the 'risk' cause
        "epoch": epoch,                            # monotonic; CAS rejects stale writers
        "reason": "; ".join(kill_switch.halt_reasons),
        "asserted_at": now,
        "cleared_at": None,
        "cleared_by": None,                        # explicit, audited unhalt only
    }
```

**Axis ownership (binding).** In the runtime's orthogonal state axes, the `risk_mode` axis
(`NORMAL | HALTED | LIQUIDATION_ONLY`) is **risk-owned**: this skill is the only writer of
the risk halt cause and the only clearer of it. The runtime orchestrates and persists the
record but **never writes the `risk_mode` axis** — one halt cause, one owner (the same
one-owner discipline as the pre-trade guard registration above).

## Position Sizing

### Kelly Criterion (Full & Fractional)

```python
def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Full Kelly. Use fractional (0.25x) in practice to reduce variance."""
    if avg_loss == 0:
        return 0.0
    b = avg_win / avg_loss  # win/loss ratio
    p = win_rate
    q = 1 - p
    kelly = (b * p - q) / b
    return max(0.0, kelly)

def position_size(
    capital: float,
    entry_price: float,
    stop_loss_price: float,
    risk_per_trade_pct: float = 0.01,  # 1% of capital per trade
    kelly_fraction: float = 0.25,       # conservative fraction
    max_position_pct: float = 0.10,     # never more than 10% in one trade
) -> float:
    """Risk-based position sizing. Returns quantity."""
    risk_per_unit = abs(entry_price - stop_loss_price)
    if risk_per_unit == 0:
        return 0.0

    risk_capital = capital * risk_per_trade_pct * kelly_fraction
    qty = risk_capital / risk_per_unit

    # Apply maximum position cap
    max_qty = (capital * max_position_pct) / entry_price
    return min(qty, max_qty)
```

### ATR-Based Stop Loss

```python
def atr_stop(prices_df, entry_price: float, atr_multiplier: float = 2.0,
             direction: str = 'long') -> float:
    """Dynamic stop based on Average True Range."""
    atr = ta.ATR(prices_df['high'], prices_df['low'],
                 prices_df['close'], timeperiod=14).iloc[-1]
    if direction == 'long':
        return entry_price - (atr * atr_multiplier)
    return entry_price + (atr * atr_multiplier)
```

## VaR and CVaR

```python
import numpy as np
from scipy import stats

def calculate_var_cvar(returns: np.ndarray, confidence: float = 0.95) -> dict:
    """
    Value at Risk and Conditional VaR (Expected Shortfall).
    Returns 1-day VaR and CVaR at given confidence level.
    """
    # Historical simulation (non-parametric)
    sorted_returns = np.sort(returns)
    index = int((1 - confidence) * len(sorted_returns))
    var = -sorted_returns[index]

    # CVaR = average loss beyond VaR threshold
    tail_returns = sorted_returns[:index]
    cvar = -tail_returns.mean() if len(tail_returns) > 0 else var

    # Parametric (normal) VaR for comparison
    mu, sigma = returns.mean(), returns.std()
    var_parametric = -stats.norm.ppf(1 - confidence, mu, sigma)

    return {
        'var_historical': var,
        'cvar_historical': cvar,
        'var_parametric': var_parametric,
        'daily_var_95': var,
        'annual_var_95': var * np.sqrt(252),
    }
```

## Correlation & Concentration Risk

```python
import pandas as pd

def portfolio_concentration_check(
    positions: dict,       # {symbol: usd_value}
    returns_df: pd.DataFrame,  # columns = symbols, rows = daily returns
    max_corr: float = 0.80,
    max_concentration: float = 0.25,
) -> list[str]:
    """Returns list of risk warnings."""
    warnings = []
    total = sum(positions.values())

    # Concentration check
    for sym, val in positions.items():
        if val / total > max_concentration:
            warnings.append(f"Concentration risk: {sym} = {val/total:.1%} of portfolio")

    # Correlation check
    corr = returns_df[list(positions.keys())].corr()
    for i, s1 in enumerate(corr.columns):
        for j, s2 in enumerate(corr.columns):
            if i < j and abs(corr.loc[s1, s2]) > max_corr:
                warnings.append(
                    f"High correlation: {s1}/{s2} = {corr.loc[s1,s2]:.2f} — reduce one position"
                )
    return warnings
```

## Risk-Constrained Allocation & Risk Attribution

Portfolio construction **as a risk overlay** and **risk** attribution — for multi-day /
positional books as well as intraday. It stays strictly inside the risk charter.

**Boundary (binding — read before using anything below):**

- **This skill NEVER produces forecasts, alphas, or expected returns.** Allocation here is
  an OVERLAY that takes **externally-supplied, point-in-time** forecast / alpha /
  expected-return inputs and applies **constraints, risk budgets, and feasibility checks**
  on top of them. Where the forecasts come from is out of scope.
- **Output is a constrained target weight vector / risk verdict — NEVER orders and NEVER
  an executable trade list.** Turning a target into orders (sizing to lots, routing, TIF)
  is `equity-broker-execution` / `crypto-exchange-integration`, orchestrated by
  `trading-automation-runtime`.
- **RISK attribution only, not performance attribution.** Realized-P&L attribution and
  trade review live in `trade-journaling-and-review`; backtest statistical significance
  lives in `trading-strategy-backtester`. This section attributes **risk** (ex-ante and
  realized risk contribution), not returns.

### Return & benchmark conventions (state them explicitly)

Every allocation/attribution result must state its conventions or it is meaningless — sign,
return period (and annualization basis), cash/financing treatment, FX base currency,
fee/cost inclusion, and the leverage / gross-vs-net definition. Two "risk contributions"
that disagree usually disagree only on conventions.

### Risk-constrained allocation (overlay)

```python
import numpy as np

def constrained_target(expected_returns, cov, constraints, prev_weights):
    """Risk-overlay allocation. `expected_returns` is an EXTERNAL, point-in-time input;
    this function never forecasts. Returns TARGET WEIGHTS, never orders.

    constraints carries the risk budget (max portfolio vol), box/gross/net limits, and a
    turnover cap — feasibility is checked, never silently relaxed.
    """
    mu = np.asarray(expected_returns, dtype=float)   # supplied by the caller
    sigma = np.asarray(cov, dtype=float)
    # Solve for weights maximising a risk-adjusted objective subject to constraints;
    # FLAG infeasible rather than returning an unconstrained/relaxed solution.
    w = _solve_or_flag_infeasible(mu, sigma, constraints, prev_weights)
    return w                                          # a constrained target, not a trade list
```

### Factor / benchmark exposure & risk attribution

- **Exposure analysis:** decompose the target (or current) portfolio onto factor /
  benchmark exposures; report **active** exposure versus the stated benchmark.
- **Ex-ante vs realized risk contribution:** attribute portfolio risk to positions/factors
  (marginal and component contribution to variance/vol). Compare **ex-ante** (from `cov`)
  against **realized** risk contribution; a large gap flags a model/regime break — a RISK
  signal, not a performance number.

```python
def risk_contributions(weights, cov):
    """Component contribution to portfolio variance (risk attribution, not P&L)."""
    import numpy as np
    w = np.asarray(weights, dtype=float)
    c = np.asarray(cov, dtype=float)
    port_var = float(w @ c @ w)
    if port_var <= 0:
        return np.zeros_like(w)
    marginal = c @ w                       # d(variance)/dw
    return (w * marginal) / port_var       # fractions summing to 1.0
```

### Rebalance / turnover (cost-aware)

Rebalancing weighs expected risk reduction against **turnover cost**; a constrained target
that ignores the cost of getting there is incomplete. The turnover cap is a constraint in
`constrained_target`, and realized turnover is reported alongside the target.

## Circuit Breaker Thresholds (Recommended Defaults)

| Trigger | Conservative | Moderate | Aggressive |
|---------|-------------|---------|------------|
| Daily loss limit | 1% NAV | 2% NAV | 3% NAV |
| Max drawdown halt | 5% | 8% | 15% |
| Position count | 5 | 10 | 20 |
| Gross exposure | 100% NAV | 150% | 200% |
| Single position max | 5% NAV | 10% | 15% |
| Consecutive losses | 3 | 5 | 7 |

## Exchange-Specific Risk Notes

**Binance Futures:**
- Set leverage per symbol via `fapiPrivate_post_leverage`
- Use `reduceOnly=True` for exit-only orders during halt
- Monitor `marginRatio` — liquidation starts at 100%

**Kraken:**
- Margin call at 40% of initial margin consumed
- Max leverage 5x on most pairs

**General:**
- Always place stop-loss server-side (exchange OCO orders), not client-side only
- Test kill switch in paper trading before live deployment
- Log every risk check with timestamp for post-mortem analysis

## Common Mistakes

1. **Soft kills** — kill switch checks that can be bypassed by restarting the bot
2. **No emergency exit** — halting without closing positions leaves risk on
3. **Ignoring funding** — on perpetuals, an open position bleeds funding even when halted
4. **Kelly without drawdown buffer** — full Kelly leads to 50%+ drawdowns; use 0.25x max
5. **Fixed stop-loss** — volatile markets require ATR-based stops
6. **Not logging reason** — always log WHY a halt was triggered for debugging

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Not implementing a kill switch | A bug in trading logic can drain an account in minutes; no manual intervention is fast enough | Implement automated kill switch: max loss per hour, max position size, max drawdown — hard stop, no override |
| Using Kelly criterion without fractional sizing | Full Kelly sizing produces extreme volatility; a few bad trades can draw down 50%+ | Use fractional Kelly (0.25-0.5x); full Kelly is theoretically optimal but practically unbearable |
| VaR as the only risk metric | VaR says nothing about tail risk severity; "95% VaR is $10K" tells you nothing about the 5% scenarios | Supplement VaR with CVaR (Expected Shortfall) and stress testing against historical worst-case scenarios |
| Position sizing based on conviction rather than volatility | "I feel confident" is not a risk management strategy; leads to concentrated bets that blow up | Size positions based on ATR or realized volatility; equal risk contribution across positions |
| No correlation monitoring across positions | Seemingly diversified portfolio is actually 90% correlated in a crisis; all positions move against you simultaneously | Monitor rolling correlation matrix; reduce total exposure when average pairwise correlation exceeds threshold |
| Producing return forecasts inside the risk layer | Conflates alpha generation with risk control; the risk overlay loses its independence | Take forecasts as an external, point-in-time input; this skill only constrains and attributes risk |
| Emitting orders or an executable trade list from allocation | Crosses the risk/execution boundary; unpermitted trades bypass the pre-trade gate chain | Output constrained target weights / a risk verdict; execution skills turn targets into orders |
| Reporting risk attribution as performance attribution | Risk contribution and P&L attribution answer different questions; mixing them misleads | Attribute RISK here; route realized-P&L attribution to trade-journaling-and-review and significance to trading-strategy-backtester |
