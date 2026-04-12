---
name: day-trading-patterns
description: Use when implementing intraday trading strategies, scalping algorithms, VWAP/TWAP execution, candlestick pattern recognition, volume profile analysis, order flow interpretation, or time-of-day effect modelling
---

# Day Trading Patterns

## Overview

Day trading operates on minute-to-hour timeframes. Success depends on **execution quality**, **time-of-day awareness**, and **pattern recognition** in price/volume. Most retail patterns fail; focus on statistically validated ones with clear entry/exit rules.

**Core principle:** Most intraday edges are execution-dependent. A pattern profitable at market close may be unprofitable at market open spreads.

## When to Use

- Implementing scalping or intraday momentum strategies
- Building VWAP/TWAP-anchored execution algorithms
- Recognising candlestick patterns programmatically
- Modelling volume profile (POC, VAH, VAL) for support/resistance
- Understanding order flow imbalance signals

## VWAP and TWAP Execution

```python
import pandas as pd
import numpy as np

def calculate_vwap(ohlcv: pd.DataFrame, session_start: str = '09:30') -> pd.Series:
    """
    Volume-Weighted Average Price. Resets each session.
    Standard anchor for institutional execution benchmarking.
    """
    typical_price = (ohlcv['high'] + ohlcv['low'] + ohlcv['close']) / 3
    tp_volume = typical_price * ohlcv['volume']

    # Group by date for session reset
    vwap = (tp_volume.groupby(ohlcv.index.date).cumsum() /
            ohlcv['volume'].groupby(ohlcv.index.date).cumsum())
    return vwap


def vwap_signal(ohlcv: pd.DataFrame) -> pd.Series:
    """
    VWAP mean-reversion signal.
    Buy when price crosses below VWAP, sell when above.
    Only reliable during trending sessions; avoid in choppy markets.
    """
    vwap = calculate_vwap(ohlcv)
    close = ohlcv['close']

    signal = pd.Series(0, index=ohlcv.index)
    signal[close < vwap * 0.998] = 1   # 0.2% below VWAP = buy
    signal[close > vwap * 1.002] = -1  # 0.2% above VWAP = sell

    return signal


def twap_schedule(total_qty: float, start_time, end_time,
                   n_slices: int = 20) -> pd.DataFrame:
    """
    Generate TWAP order schedule.
    Splits total_qty into equal slices at regular intervals.
    """
    times = pd.date_range(start_time, end_time, periods=n_slices)
    slice_qty = total_qty / n_slices
    return pd.DataFrame({
        'time': times,
        'quantity': slice_qty,
        'type': 'limit',  # use limit orders for TWAP
    })
```

## Candlestick Pattern Detection

```python
def detect_candlestick_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect key candlestick reversal patterns.
    Returns dataframe with boolean columns for each pattern.
    """
    o, h, l, c = df['open'], df['high'], df['low'], df['close']
    body = (c - o).abs()
    total_range = h - l
    upper_wick = h - df[['open', 'close']].max(axis=1)
    lower_wick = df[['open', 'close']].min(axis=1) - l

    df = df.copy()

    # Doji: body < 10% of total range
    df['doji'] = body < (total_range * 0.1)

    # Hammer (bullish reversal): small body at top, long lower wick
    df['hammer'] = (
        (lower_wick > body * 2) &
        (upper_wick < body * 0.5) &
        (c > o)  # bullish close
    )

    # Shooting Star (bearish reversal): small body at bottom, long upper wick
    df['shooting_star'] = (
        (upper_wick > body * 2) &
        (lower_wick < body * 0.5) &
        (c < o)  # bearish close
    )

    # Engulfing (bullish): current bullish candle completely engulfs previous bearish
    prev_o, prev_c = o.shift(1), c.shift(1)
    df['bullish_engulfing'] = (
        (c > o) &           # current candle is bullish
        (prev_c < prev_o) & # previous candle is bearish
        (o < prev_c) &      # open below previous close
        (c > prev_o)        # close above previous open
    )

    # Bearish engulfing
    df['bearish_engulfing'] = (
        (c < o) &
        (prev_c > prev_o) &
        (o > prev_c) &
        (c < prev_o)
    )

    # Pinbar: rejection candle (long wick on one side)
    df['pinbar_bullish'] = (lower_wick > total_range * 0.6) & (body < total_range * 0.25)
    df['pinbar_bearish'] = (upper_wick > total_range * 0.6) & (body < total_range * 0.25)

    return df
```

## Volume Profile (POC, VAH, VAL)

```python
def calculate_volume_profile(
    df: pd.DataFrame,
    n_bins: int = 50,
) -> dict:
    """
    Volume Profile: distribution of volume across price levels.
    POC = Point of Control (highest volume price)
    VAH = Value Area High (top of 70% value area)
    VAL = Value Area Low (bottom of 70% value area)
    """
    price_min, price_max = df['low'].min(), df['high'].max()
    price_bins = pd.cut(df['close'], bins=n_bins)

    # Volume per price bin
    vol_profile = df.groupby(price_bins, observed=True)['volume'].sum()
    vol_profile = vol_profile.sort_index()

    # POC: price level with highest volume
    poc_bin = vol_profile.idxmax()
    poc_price = poc_bin.mid

    # Value Area: 70% of total volume around POC
    total_vol = vol_profile.sum()
    target_vol = total_vol * 0.70

    # Expand outward from POC until 70% volume captured
    poc_idx = vol_profile.index.get_loc(poc_bin)
    lower_idx, upper_idx = poc_idx, poc_idx
    captured_vol = vol_profile.iloc[poc_idx]

    while captured_vol < target_vol:
        lower_can_expand = lower_idx > 0
        upper_can_expand = upper_idx < len(vol_profile) - 1

        lower_vol = vol_profile.iloc[lower_idx - 1] if lower_can_expand else 0
        upper_vol = vol_profile.iloc[upper_idx + 1] if upper_can_expand else 0

        if lower_vol >= upper_vol and lower_can_expand:
            lower_idx -= 1
            captured_vol += lower_vol
        elif upper_can_expand:
            upper_idx += 1
            captured_vol += upper_vol
        else:
            break

    return {
        'poc': poc_price,
        'vah': vol_profile.index[upper_idx].right,
        'val': vol_profile.index[lower_idx].left,
        'profile': vol_profile,
    }
```

## Order Flow Imbalance

```python
def order_flow_imbalance(trades: pd.DataFrame,
                          window: int = 100) -> pd.Series:
    """
    Order flow imbalance = (buy_volume - sell_volume) / total_volume.
    Positive = buying pressure, negative = selling pressure.
    Uses tick rule: price up = buy-initiated, price down = sell-initiated.
    """
    # Classify trades by tick rule
    price_change = trades['price'].diff()
    trades['side'] = 0
    trades.loc[price_change > 0, 'side'] = 1   # buy
    trades.loc[price_change < 0, 'side'] = -1  # sell
    # Carry forward for unchanged prices
    trades['side'] = trades['side'].replace(0, np.nan).ffill().fillna(0)

    buy_vol = (trades['size'] * (trades['side'] == 1)).rolling(window).sum()
    sell_vol = (trades['size'] * (trades['side'] == -1)).rolling(window).sum()
    total_vol = (buy_vol + sell_vol).clip(lower=1)

    return (buy_vol - sell_vol) / total_vol
```

## Time-of-Day Effects

```python
# Intraday patterns (equity markets, US Eastern Time)
TIME_OF_DAY_NOTES = {
    '09:30-10:00': 'Opening auction — highest volatility, wide spreads. Avoid unless breakout strategy.',
    '10:00-11:30': 'First trend window — most reliable intraday trends form here.',
    '11:30-14:00': 'Midday chop — range-bound, low momentum. Reduce position sizes.',
    '14:00-15:00': 'London close overlap — moderate volatility, directional moves.',
    '15:00-16:00': 'Power hour — second highest volume, trends often extend or reverse.',
    '15:50-16:00': 'MOC imbalances published — large institutional moves, avoid fade.',
}

# Crypto (24/7 markets — UTC)
CRYPTO_TIME_PATTERNS = {
    '00:00-04:00 UTC': 'Asian session — generally lower volatility for BTC/ETH.',
    '07:00-09:00 UTC': 'European open — increased EUR pairs activity.',
    '13:00-15:00 UTC': 'US/EU overlap — highest liquidity window for crypto.',
    '21:00-23:59 UTC': 'Low liquidity — wider spreads, avoid large orders.',
    'Funding (every 8h)': 'Funding payments at 00:00, 08:00, 16:00 UTC — brief price manipulation common.',
}
```

## Quick Reference — Pattern Reliability

| Pattern | Win Rate (backtest) | Best Timeframe | Notes |
|---------|---------------------|---------------|-------|
| VWAP reversion | 52-58% | 5m-15m | Only in ranging markets |
| Bullish engulfing | 54-60% | 15m-1h | Requires volume confirmation |
| Opening range breakout | 55-65% | 5m (first 30min) | Direction of first 30min |
| Volume POC bounce | 55-62% | 1h+ | More reliable on higher timeframes |
| Hammer at support | 56-63% | 15m-4h | Needs identifiable support level |

**All win rates are indicative; verify on your specific instrument and timeframe.**

## Common Mistakes

1. **Trading the open** — first 15 minutes have the widest spreads and most noise; wait for range to form
2. **Ignoring volume** — a breakout without volume surge is 70% more likely to fail
3. **Over-trading midday** — equities 11:30-14:00 and crypto low-liquidity windows are choppy; reduce size
4. **Pattern hunting without context** — a hammer at a support level is a signal; a hammer in the middle of a range is noise
5. **Market orders for entries** — use limit orders within the bid-ask for entries; market orders on exits only
6. **No daily bias** — intraday direction should align with daily trend; fading a strong trend is low-probability

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Trading the first 15 minutes of market open | Widest spreads, maximum noise, institutional order flow distortion — most retail losses happen here | Wait for the opening range to form (first 15-30 min); trade the breakout or reversion, not the chaos |
| Entering breakouts without volume confirmation | A breakout on low volume is 70% more likely to be a false breakout that reverses | Require volume surge (1.5x+ average) to confirm breakout; no volume = no entry |
| Over-trading during midday chop (11:30-14:00 equities) | Low volume, tight ranges, mean-reversion dominates — directional strategies get whipsawed | Reduce position size or stop trading during low-liquidity windows; focus on open and close sessions |
| Using market orders for entries | Slippage on entries compounds over hundreds of trades; destroys edge on scalping strategies | Use limit orders within the bid-ask for entries; reserve market orders for stop-loss exits only |
| Fading a strong daily trend intraday | Counter-trend scalps have 30-40% win rates against strong trends; losses are larger than wins | Align intraday direction with the daily trend bias; only fade at major support/resistance with volume divergence |
