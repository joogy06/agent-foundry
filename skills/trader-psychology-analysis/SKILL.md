---
name: trader-psychology-analysis
description: Use when analysing retail vs institutional trader behaviour, modelling cognitive biases in market data, detecting FOMO/FUD cycles, identifying contrarian signals, or implementing behavioural finance models for trading decisions
---

# Trader Psychology Analysis

## Overview

Markets are driven by human psychology as much as fundamentals. Understanding **cognitive biases**, **herding dynamics**, and **fear/greed cycles** allows you to anticipate price movements caused by irrational behaviour. This skill maps behavioural finance theory to quantifiable trading signals.

## When to Use

- Modelling retail vs. institutional behaviour from order flow or positioning data
- Building contrarian indicators from extreme sentiment
- Detecting FOMO-driven momentum and FUD-driven capitulation
- Interpreting sentiment extremes as mean-reversion signals
- Explaining anomalous price movements through behavioural lens

## Key Cognitive Biases and Market Impact

| Bias | Description | Market Effect | Signal |
|------|-------------|---------------|--------|
| **Loss Aversion** | Losses hurt ~2× more than gains | Reluctance to cut losers → trend prolongation | Large open loss concentration = reversal risk |
| **Recency Bias** | Overweight recent events | Momentum overshoot | High recent returns → mean reversion expectation |
| **Anchoring** | Over-rely on reference price | Support/resistance at round numbers | Volume clusters at .00 prices |
| **Herding** | Follow the crowd | Bubble formation, panics | Extreme long/short positioning |
| **Overconfidence** | Overestimate skill | Excessive trading, risk-taking | High retail volume in bull markets |
| **Disposition Effect** | Sell winners too early, hold losers | Suppressed upside momentum | Low volume on new highs |
| **FOMO** | Fear of missing out | Late-cycle volume spikes | Volume surge + price acceleration |
| **FUD** | Fear, uncertainty, doubt | Overcorrection on bad news | Price gap down on moderate news |

## Prospect Theory Model

```python
import numpy as np

def prospect_theory_value(outcome: float, reference: float,
                           lambda_loss: float = 2.25,
                           alpha: float = 0.88) -> float:
    """
    Kahneman-Tversky prospect theory utility function.
    lambda_loss: loss aversion coefficient (default 2.25 from original paper)
    alpha: diminishing sensitivity (default 0.88)
    Reference: Kahneman & Tversky (1979)
    """
    delta = outcome - reference
    if delta >= 0:
        return delta ** alpha
    else:
        return -lambda_loss * ((-delta) ** alpha)

def aggregate_portfolio_pain(
    positions: list[dict],   # [{entry_price, current_price, size}]
) -> dict:
    """
    Estimates aggregate psychological pain of a portfolio.
    High pain = elevated sell pressure likely.
    """
    total_pain = 0.0
    losing_positions = 0

    for pos in positions:
        pnl = (pos['current_price'] - pos['entry_price']) * pos['size']
        pv = prospect_theory_value(pos['current_price'], pos['entry_price'])
        total_pain += pv
        if pnl < 0:
            losing_positions += 1

    return {
        'aggregate_utility': total_pain,
        'losing_pct': losing_positions / len(positions) if positions else 0,
        'sell_pressure_estimate': 'HIGH' if total_pain < -50 else 'MEDIUM' if total_pain < 0 else 'LOW',
    }
```

## Fear & Greed Cycle Detection

```python
import pandas as pd
import numpy as np

def fear_greed_index(
    price_data: pd.DataFrame,   # OHLCV
    volume_data: pd.Series,
    funding_rate: pd.Series,    # crypto perpetual funding
    long_short_ratio: pd.Series,
    lookback: int = 30,
) -> pd.Series:
    """
    Composite Fear & Greed index [0-100].
    0 = Extreme Fear, 100 = Extreme Greed.
    """
    def normalise(series, window=lookback):
        rolling_min = series.rolling(window).min()
        rolling_max = series.rolling(window).max()
        return (series - rolling_min) / (rolling_max - rolling_min + 1e-8) * 100

    # Component signals
    price_momentum = price_data['close'].pct_change(7)           # 7-day return
    volatility     = price_data['close'].pct_change().rolling(30).std()
    volume_trend   = volume_data.rolling(7).mean() / volume_data.rolling(30).mean()

    # Funding rate: positive = greed (longs paying shorts)
    funding_norm = normalise(funding_rate)

    # Long/short ratio: >1.5 = crowded longs (greed)
    ls_norm = normalise(long_short_ratio)

    # Composite (equal weights)
    composite = (
        normalise(price_momentum) * 0.25 +
        (100 - normalise(volatility)) * 0.15 +  # low vol = greed
        normalise(volume_trend) * 0.20 +
        funding_norm * 0.25 +
        ls_norm * 0.15
    )
    return composite


def detect_fomo_signal(price: pd.Series, volume: pd.Series,
                        price_threshold: float = 0.05,
                        volume_threshold: float = 2.0) -> pd.Series:
    """
    FOMO = price up >5% in 24h with volume >2× 30-day average.
    Returns boolean series.
    """
    price_surge = price.pct_change(24) > price_threshold
    volume_spike = volume > (volume.rolling(720).mean() * volume_threshold)
    return price_surge & volume_spike
```

## Retail vs Institutional Behaviour

```python
def classify_order_flow(trades_df: pd.DataFrame) -> pd.DataFrame:
    """
    Classify trades as likely retail (small) or institutional (large).
    Uses Kyle's lambda and trade size distribution.
    """
    # Median trade size
    median_size = trades_df['size'].median()

    trades_df['type'] = 'retail'
    trades_df.loc[trades_df['size'] > median_size * 10, 'type'] = 'institutional'

    # Retail typically trades in round numbers
    trades_df['is_round_number'] = (
        (trades_df['price'] * 100).round(0) == (trades_df['price'] * 100)
    )

    return trades_df


def institutional_accumulation_signal(ohlcv: pd.DataFrame,
                                       window: int = 20) -> pd.Series:
    """
    Detect institutional accumulation: price flat/rising on above-average volume
    without breakout. Classic Wyckoff accumulation signature.
    """
    price_range = (ohlcv['high'] - ohlcv['low']) / ohlcv['close']
    avg_volume = ohlcv['volume'].rolling(window).mean()
    high_volume = ohlcv['volume'] > avg_volume * 1.5
    tight_range = price_range < price_range.rolling(window).median()

    return (high_volume & tight_range).astype(int)
```

## Contrarian Indicators

```python
def contrarian_signal(fear_greed: pd.Series,
                       extreme_greed_threshold: float = 80,
                       extreme_fear_threshold: float = 20) -> pd.Series:
    """
    Contrarian signal: buy extreme fear, sell extreme greed.
    Returns: -1 (sell), 0 (neutral), +1 (buy)
    """
    signal = pd.Series(0, index=fear_greed.index)
    signal[fear_greed <= extreme_fear_threshold] = 1   # buy the fear
    signal[fear_greed >= extreme_greed_threshold] = -1  # sell the greed
    return signal


def herd_intensity(long_short_ratio: pd.Series, window: int = 14) -> pd.Series:
    """
    Measures deviation from 50/50 positioning.
    High values = dangerous herding (setup for short squeeze or flush).
    """
    deviation = (long_short_ratio - 1.0).abs()
    return deviation / deviation.rolling(window).std()
```

## Behavioural Patterns Quick Reference

| Pattern | Setup | Trade Direction |
|---------|-------|----------------|
| **Capitulation** | Volume spike down + fear >90 | Buy (bottom fishing) |
| **Blow-off top** | Volume spike up + greed >90 | Sell (distribution) |
| **FOMO chase** | Price up 10%+ with retail surge | Fade (short) |
| **Smart money divergence** | Price rising but institutional selling | Short |
| **Panic selling** | Price falls >15% in 24h, LSR <0.5 | Buy (oversold) |
| **Wyckoff accumulation** | Flat price, high volume, low volatility | Buy breakout |

## Common Mistakes

1. **Trading against trends prematurely** — contrarian signals need confirmation; wait for reversal candles
2. **Ignoring macro context** — fear in a bull market is different from fear in a bear market
3. **Using single indicator** — combine fear/greed + positioning + volume for robust signals
4. **Anthropomorphising** — markets don't "feel" anything; biases are statistical tendencies, not certainties
5. **Overweighting retail sentiment** — institutional flow dominates; retail sentiment is noise until extreme

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Modelling traders as purely rational agents | Ignores loss aversion, anchoring, herding, and overconfidence that systematically drive market behaviour | Incorporate behavioural finance models; calibrate against empirical data on bias magnitudes |
| Using put/call ratio in isolation as a sentiment indicator | Hedging activity, market-making, and structural flows contaminate the signal; raw ratio is misleading | Combine put/call with VIX term structure, fund flows, and positioning data for multi-factor sentiment |
| Treating all retail traders as a monolithic group | Reddit retail, institutional retail (wealth management), and day traders have very different behaviours | Segment retail by platform and behaviour: Reddit/social traders vs systematic retail vs passive retail |
| Going contrarian against every extreme sentiment reading | Sometimes the crowd is right; strong trends persist through extreme sentiment for weeks or months | Use contrarian signals only at structural levels (support/resistance); combine with technical confirmation |
| Ignoring institutional positioning data (COT reports) | Retail sentiment without institutional context misses the dominant market force | Overlay CFTC Commitment of Traders data; institutional positioning often leads retail sentiment shifts by days |

---

**See also:** this skill models the market CROWD — for logging and reviewing YOUR OWN executed trades and personal tilt/mistake tagging, use `trade-journaling-and-review`.
