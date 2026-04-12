---
name: market-data-engineering
description: Use when building financial data pipelines, processing OHLCV data, cleaning market time-series, handling gaps and resampling, storing signals in TimescaleDB, or deduplicating tick and bar data
---

# Market Data Engineering

## Overview

Financial time-series data is fundamentally different from regular data: it has **gaps** (weekends, halts), **irregular timestamps** (tick data), **corporate actions** (splits, dividends), and strict **point-in-time** requirements. Treat it with more care than typical data engineering.

## When to Use

- Building OHLCV ingestion and storage pipelines
- Cleaning and normalising raw market data feeds
- Implementing TimescaleDB hypertables for financial data
- Resampling tick data to bars (1m, 5m, 1h)
- Deduplicating duplicate ticks from exchange feeds

## OHLCV Processing Pipeline

```python
import pandas as pd
import numpy as np
from typing import Optional

def clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Standardises OHLCV dataframe. Expects columns: open, high, low, close, volume.
    Returns cleaned, sorted, deduplicated dataframe indexed by UTC datetime.
    """
    df = df.copy()

    # Ensure UTC datetime index
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    elif df.index.tz is None:
        df.index = df.index.tz_localize('UTC')
    else:
        df.index = df.index.tz_convert('UTC')

    # Sort ascending
    df = df.sort_index()

    # Remove exact duplicate timestamps (keep last)
    df = df[~df.index.duplicated(keep='last')]

    # Validate OHLCV constraints
    # High must be >= Open, Close, Low
    invalid_high = (df['high'] < df[['open', 'close', 'low']].max(axis=1))
    df.loc[invalid_high, 'high'] = df.loc[invalid_high, ['open', 'close', 'low']].max(axis=1)

    # Low must be <= Open, Close, High
    invalid_low = (df['low'] > df[['open', 'close', 'high']].min(axis=1))
    df.loc[invalid_low, 'low'] = df.loc[invalid_low, ['open', 'close', 'high']].min(axis=1)

    # Remove zero/negative prices
    price_cols = ['open', 'high', 'low', 'close']
    df = df[(df[price_cols] > 0).all(axis=1)]

    # Remove zero volume (for crypto, volume 0 = no trades, often data error)
    df = df[df['volume'] > 0]

    return df


def fill_gaps(df: pd.DataFrame, freq: str = '1h',
              method: str = 'forward_fill',
              max_gap_periods: int = 3) -> pd.DataFrame:
    """
    Fill missing periods in time series.
    method: 'forward_fill' | 'zero_volume' | 'interpolate'
    max_gap_periods: gaps larger than this are left as NaN (don't fill large outages)
    """
    full_index = pd.date_range(df.index[0], df.index[-1], freq=freq, tz='UTC')
    df = df.reindex(full_index)

    if method == 'forward_fill':
        # Forward fill price, zero out volume for synthetic bars
        df[['open', 'high', 'low', 'close']] = df[['open', 'high', 'low', 'close']].ffill(
            limit=max_gap_periods
        )
        df['volume'] = df['volume'].fillna(0)

    elif method == 'zero_volume':
        # Fill close price only, set OHLC to close
        df['close'] = df['close'].ffill(limit=max_gap_periods)
        for col in ['open', 'high', 'low']:
            df[col] = df[col].fillna(df['close'])
        df['volume'] = df['volume'].fillna(0)

    return df
```

## Tick-to-Bar Resampling

```python
def resample_ticks_to_ohlcv(ticks: pd.DataFrame, freq: str = '1min') -> pd.DataFrame:
    """
    Convert tick data (price, volume per tick) to OHLCV bars.
    ticks must have DatetimeIndex with 'price' and 'size' columns.
    """
    resampled = ticks['price'].resample(freq).ohlc()
    resampled['volume'] = ticks['size'].resample(freq).sum()

    # Drop empty bars
    resampled = resampled.dropna(subset=['open'])
    return resampled


def resample_ohlcv(df: pd.DataFrame, from_freq: str, to_freq: str) -> pd.DataFrame:
    """Downsample OHLCV bars (e.g., 1m -> 1h)."""
    resampled = df['open'].resample(to_freq).first().to_frame()
    resampled['high']   = df['high'].resample(to_freq).max()
    resampled['low']    = df['low'].resample(to_freq).min()
    resampled['close']  = df['close'].resample(to_freq).last()
    resampled['volume'] = df['volume'].resample(to_freq).sum()
    return resampled.dropna()
```

## TimescaleDB Schema

```sql
-- TimescaleDB hypertable for OHLCV data
CREATE TABLE ohlcv (
    time        TIMESTAMPTZ NOT NULL,
    symbol      TEXT        NOT NULL,
    exchange    TEXT        NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      DOUBLE PRECISION,
    PRIMARY KEY (time, symbol, exchange)
);

-- Convert to hypertable (partition by time, 1-day chunks for tick data)
SELECT create_hypertable('ohlcv', 'time', chunk_time_interval => INTERVAL '1 day');

-- Index for symbol lookups
CREATE INDEX ON ohlcv (symbol, time DESC);

-- Continuous aggregate for hourly OHLCV from minute data
CREATE MATERIALIZED VIEW ohlcv_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    symbol,
    exchange,
    first(open, time)  AS open,
    max(high)          AS high,
    min(low)           AS low,
    last(close, time)  AS close,
    sum(volume)        AS volume
FROM ohlcv
GROUP BY bucket, symbol, exchange
WITH NO DATA;

SELECT add_continuous_aggregate_policy('ohlcv_1h',
    start_offset => INTERVAL '2 hours',
    end_offset   => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 hour');
```

## Python TimescaleDB Integration

```python
import asyncpg
import pandas as pd
from datetime import datetime

async def upsert_ohlcv(conn: asyncpg.Connection, df: pd.DataFrame,
                        symbol: str, exchange: str):
    """Efficient bulk upsert to TimescaleDB."""
    records = [
        (row.Index.to_pydatetime(), symbol, exchange,
         row.open, row.high, row.low, row.close, row.volume)
        for row in df.itertuples()
    ]
    await conn.executemany(
        """
        INSERT INTO ohlcv (time, symbol, exchange, open, high, low, close, volume)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (time, symbol, exchange) DO UPDATE
          SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
              close=EXCLUDED.close, volume=EXCLUDED.volume
        """,
        records
    )

async def fetch_ohlcv(conn: asyncpg.Connection, symbol: str,
                       start: datetime, end: datetime,
                       timeframe: str = '1h') -> pd.DataFrame:
    """Fetch OHLCV from TimescaleDB continuous aggregate."""
    view = f'ohlcv_{timeframe}'
    rows = await conn.fetch(
        f"SELECT * FROM {view} WHERE symbol=$1 AND bucket BETWEEN $2 AND $3 ORDER BY bucket",
        symbol, start, end
    )
    return pd.DataFrame(rows, columns=['time', 'symbol', 'exchange',
                                        'open', 'high', 'low', 'close', 'volume']
                        ).set_index('time')
```

## Deduplication Strategy

```python
def deduplicate_ticks(ticks: pd.DataFrame,
                       timestamp_col: str = 'timestamp',
                       dedupe_window_ms: int = 100) -> pd.DataFrame:
    """
    Remove near-duplicate ticks within a time window.
    Exchange feeds often re-send ticks on reconnect.
    """
    ticks = ticks.sort_values(timestamp_col)

    # Round timestamps to dedupe window
    ticks['_bucket'] = (ticks[timestamp_col].astype('int64') //
                         (dedupe_window_ms * 1_000_000))

    # Keep first tick per (symbol, price, bucket)
    deduped = ticks.drop_duplicates(
        subset=['symbol', 'price', '_bucket'],
        keep='first'
    ).drop(columns=['_bucket'])

    return deduped
```

## Quick Reference

| Operation | Tool | Notes |
|-----------|------|-------|
| OHLCV storage | TimescaleDB | Use hypertable + continuous aggregates |
| Tick storage | TimescaleDB | 1-day chunk interval |
| Resampling | pandas `.resample()` | Always sort first |
| Gap filling | ffill with `limit` | Cap limit to avoid fantasy data |
| Deduplication | drop_duplicates | Per-symbol, with time bucket |
| Adjustments (splits) | pandas_market_calendars | Use adjusted prices for signals |

## Common Mistakes

1. **Mixed timezones** — always store in UTC, convert at query time
2. **Not capping ffill** — filling 1000 bars of weekend gap creates phantom data
3. **Using adjusted prices for live trading** — adjust for backtesting only; use raw prices live
4. **No conflict handling on insert** — duplicate data corrupts aggregates; always use `ON CONFLICT`
5. **Storing indicators in DB** — compute on-the-fly or in Redis; DB is for raw/resampled OHLCV only

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Storing timestamps in local timezone instead of UTC | DST transitions cause duplicate or missing bars; cross-market analysis becomes a timezone conversion nightmare | Always store in UTC; convert to display timezone at query time; store original exchange timezone as metadata |
| Forward-filling gaps without a maximum fill limit | Weekend/holiday gaps get filled with 1000+ phantom bars; indicators calculated on fake data produce false signals | Cap ffill to a maximum number of bars (e.g., 5 for 1-minute data); mark filled bars with a flag column |
| Using adjusted prices for live trading signals | Adjusted prices are recalculated historically; live prices are unadjusted — mixing them creates ghost signals | Use raw prices for live trading; adjusted prices only for backtesting; store both and document which is which |
| No deduplication on data ingestion | Duplicate ticks from multiple feeds corrupt volume calculations and OHLCV aggregation | Use ON CONFLICT (upsert) on insert; deduplicate by timestamp + source; validate row counts after ingestion |
| Storing computed indicators in the database | Indicator parameters change frequently; stored indicators become stale; storage bloats | Store raw OHLCV only; compute indicators on-the-fly or cache in Redis; database is for source-of-truth data |
