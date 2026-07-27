---
name: trading-strategy-backtester
description: Use when backtesting trading strategies, implementing walk-forward validation, detecting overfitting, modelling transaction costs, or evaluating statistical significance of strategy results using vectorbt, backtrader, or Freqtrade
---

# Trading Strategy Backtester

## Overview

Backtesting evaluates a trading strategy on historical data. The core pitfall is **overfitting** — a strategy that looks brilliant historically but fails live. Every design decision must guard against it.

## When to Use

- Implementing a new strategy and evaluating its historical performance
- Converting a hypothesis into a testable system
- Comparing multiple strategies with statistical rigour
- Generating walk-forward validation reports
- Diagnosing why a live strategy underperforms its backtest

**When NOT to use:** For live execution logic — use `equity-broker-execution` for equities (or `crypto-exchange-integration` for crypto) instead.

## Core Pitfalls

| Pitfall | Consequence | Fix |
|---------|-------------|-----|
| Look-ahead bias | Inflated returns | Use `.shift(1)` for entry; never use future prices |
| Survivorship bias | Overstated returns | Include delisted assets in test universe |
| Ignored transaction costs | Unrealistic Sharpe | Model slippage + fee on every trade |
| In-sample overfitting | Curve-fitting | Walk-forward validation; IS/OOS split |
| Multiple comparison bias | False discovery | Bonferroni correction |
| Liquidity illusion | Bad fill assumptions | Cap size at % of avg volume |

## Walk-Forward Validation

```python
from vectorbt.portfolio.base import Portfolio
import pandas as pd
import numpy as np

def walk_forward_test(price_data, signal_fn, n_splits=5, train_pct=0.7):
    """N-fold walk-forward. Returns OOS metrics only."""
    results = []
    fold_size = len(price_data) // n_splits

    for i in range(n_splits):
        start = i * fold_size
        end = start + fold_size if i < n_splits - 1 else len(price_data)
        fold = price_data.iloc[start:end]
        split = int(len(fold) * train_pct)
        train, test = fold.iloc[:split], fold.iloc[split:]

        # Optimise params on train only — DO NOT look at test
        signals_test = signal_fn(test)
        pf = Portfolio.from_signals(
            test['close'], signals_test['entries'], signals_test['exits'],
            fees=0.001, slippage=0.0005
        )
        results.append({
            'fold': i,
            'sharpe': pf.sharpe_ratio(),
            'max_dd': pf.max_drawdown(),
            'total_return': pf.total_return(),
        })

    return {
        'folds': results,
        'mean_sharpe': np.mean([r['sharpe'] for r in results]),
        'consistency': sum(1 for r in results if r['total_return'] > 0) / n_splits,
    }
```

## Transaction Cost Model

```python
# Realistic crypto costs
FEES = {'binance_taker': 0.001, 'kraken_taker': 0.0026}

def estimate_slippage(order_size_usd, avg_volume_usd):
    """Square-root market impact model."""
    return 0.001 * ((order_size_usd / avg_volume_usd) ** 0.5)

pf = Portfolio.from_signals(
    close=prices, entries=long_signals, exits=exit_signals,
    fees=0.001, slippage=0.0005, size=0.95,
)
```

## Statistical Significance

```python
from scipy import stats
import numpy as np

def significance_test(strategy_returns, benchmark_returns, alpha=0.05):
    t_stat, p_value = stats.ttest_ind(strategy_returns, benchmark_returns)
    n = len(strategy_returns)
    sr = strategy_returns.mean() / strategy_returns.std() * np.sqrt(252)
    sr_se = np.sqrt((1 + 0.5 * sr**2) / n)
    sr_p = 2 * (1 - stats.norm.cdf(abs(sr / sr_se)))
    return {'p_value': p_value, 'sharpe': sr, 'sharpe_p': sr_p,
            'significant': p_value < alpha}

def bonferroni_threshold(n_strategies, alpha=0.05):
    return alpha / n_strategies  # adjust for multiple comparisons
```

## Freqtrade Strategy Pattern

```python
from freqtrade.strategy import IStrategy, DecimalParameter
from pandas import DataFrame

class ExampleStrategy(IStrategy):
    buy_rsi  = DecimalParameter(20, 40, default=30, space='buy')
    sell_rsi = DecimalParameter(60, 80, default=70, space='sell')
    minimal_roi = {"0": 0.02}
    stoploss = -0.05

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['rsi'] = ta.RSI(dataframe['close'], timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[(dataframe['rsi'] < self.buy_rsi.value) &
                      (dataframe['volume'] > 0), 'enter_long'] = 1
        return dataframe
```

## Quick Reference — Key Metrics

| Metric | Formula | Good OOS Value |
|--------|---------|----------------|
| Sharpe Ratio | `mean_ret / std_ret * sqrt(252)` | > 1.0 |
| Max Drawdown | `peak_to_trough / peak` | < 20% |
| Calmar Ratio | `annual_return / max_drawdown` | > 0.5 |
| Profit Factor | `gross_profit / gross_loss` | > 1.3 |
| Win Rate | `winning / total` | > 40% |

## Overfitting Red Flags

- OOS Sharpe < 0.5 × IS Sharpe
- Fewer than 30 trades per year
- Sharpe drops >50% on adjacent time windows
- More than 5 free parameters
- Strategy works on only 1 instrument

## Common Mistakes

1. Optimising on full dataset — hold out a final test set never touched during development
2. Ignoring crypto funding rates — major cost on multi-day perpetual holds
3. Using `close` for entry price — entry is next bar `open`
4. Testing one ticker only — results rarely generalise
5. Forgetting survivorship bias — use point-in-time universe

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Optimizing parameters on the full dataset without out-of-sample testing | Curve-fitting to historical noise; strategy looks amazing in backtest, fails immediately in live trading | Use walk-forward validation: train on rolling window, test on unseen period, repeat across the full dataset |
| Ignoring transaction costs in backtests | A strategy with 0.5% edge per trade becomes negative after spreads, commissions, and slippage on every entry/exit | Model realistic costs: commission, spread (bid-ask), slippage (market impact), and funding costs for leveraged positions |
| Using survivorship-biased data | Backtesting on current S&P 500 constituents ignores delisted companies; inflates returns by 1-2% annually | Use point-in-time datasets that include delisted securities; verify data vendor handles survivorship correctly |
| Backtesting hundreds of parameter combinations and picking the best | Data mining bias: with enough combinations, random noise produces "significant" results | Limit parameter search; require statistical significance (p < 0.01); validate with Monte Carlo permutation tests |
| No regime awareness in strategy design | A trend-following strategy tested across 2010-2020 mostly captured a bull market; fails in bear/sideways regimes | Test across multiple market regimes; build regime detection (volatility, trend, correlation) into the strategy |
