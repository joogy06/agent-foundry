---
name: crypto-exchange-integration
description: Use when integrating with cryptocurrency exchanges via CCXT, handling WebSocket market data, managing rate limits, implementing order management, or handling Binance/Kraken/IBKR-specific API quirks and reconnection patterns
---

# Crypto Exchange Integration

## Overview

Exchange integration involves three distinct concerns: **REST** (order management, account state), **WebSocket** (real-time data, order updates), and **error handling** (rate limits, disconnections, rejections). Treat each separately.

## When to Use

- Implementing CCXT-based exchange connectors
- Building WebSocket data feeds with reconnection
- Managing rate limits across multiple API calls
- Handling exchange-specific order types and quirks
- Implementing order lifecycle tracking (new → filled → closed)

## CCXT Unified Pattern

```python
import ccxt.async_support as ccxt
import asyncio
from typing import Optional

class ExchangeConnector:
    def __init__(self, exchange_id: str, api_key: str, secret: str,
                 sandbox: bool = True):
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret,
            'sandbox': sandbox,
            'enableRateLimit': True,   # REQUIRED — uses CCXT's built-in limiter
            'options': {
                'defaultType': 'future',  # 'spot' | 'future' | 'margin'
                'adjustForTimeDifference': True,
            },
        })

    async def safe_fetch_ohlcv(self, symbol: str, timeframe: str = '1h',
                                limit: int = 500) -> list:
        """Fetch OHLCV with retry on rate limit."""
        for attempt in range(3):
            try:
                return await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            except ccxt.RateLimitExceeded:
                wait = 2 ** attempt
                await asyncio.sleep(wait)
            except ccxt.NetworkError as e:
                if attempt == 2:
                    raise
                await asyncio.sleep(1)
        return []

    async def place_order(self, symbol: str, side: str, order_type: str,
                          amount: float, price: Optional[float] = None,
                          params: dict = None) -> dict:
        """Place order with exchange-normalised error handling."""
        params = params or {}
        try:
            if order_type == 'market':
                return await self.exchange.create_market_order(symbol, side, amount, params)
            elif order_type == 'limit':
                return await self.exchange.create_limit_order(symbol, side, amount, price, params)
        except ccxt.InsufficientFunds as e:
            raise ValueError(f"Insufficient funds for {side} {amount} {symbol}") from e
        except ccxt.InvalidOrder as e:
            raise ValueError(f"Invalid order params: {e}") from e
        except ccxt.ExchangeError as e:
            # Log and re-raise — do not silently swallow
            raise

    async def close(self):
        await self.exchange.close()
```

## WebSocket Feed with Reconnection

```python
import websockets
import json
import asyncio
from datetime import datetime

class BinanceWebSocketFeed:
    """Robust WebSocket with exponential backoff reconnection."""

    def __init__(self, symbols: list[str], on_tick_callback):
        self.symbols = symbols
        self.on_tick = on_tick_callback
        self.running = False
        self._reconnect_delay = 1

    def _build_ws_url(self) -> str:
        streams = '/'.join(f"{s.lower()}@trade" for s in self.symbols)
        return f"wss://stream.binance.com:9443/stream?streams={streams}"

    async def start(self):
        self.running = True
        while self.running:
            try:
                async with websockets.connect(
                    self._build_ws_url(),
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._reconnect_delay = 1  # reset on successful connect
                    async for message in ws:
                        data = json.loads(message)
                        await self.on_tick(data['data'])
            except (websockets.ConnectionClosed,
                    websockets.WebSocketException,
                    ConnectionRefusedError) as e:
                if not self.running:
                    break
                # Exponential backoff, capped at 60s
                await asyncio.sleep(min(self._reconnect_delay, 60))
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)

    def stop(self):
        self.running = False
```

## Rate Limit Management

```python
import time
from collections import deque

class RateLimiter:
    """Token bucket rate limiter for exchange APIs."""

    def __init__(self, max_calls: int, period_seconds: float):
        self.max_calls = max_calls
        self.period = period_seconds
        self.calls = deque()

    def wait(self):
        """Block until a request slot is available."""
        now = time.monotonic()
        # Remove calls outside the window
        while self.calls and self.calls[0] <= now - self.period:
            self.calls.popleft()

        if len(self.calls) >= self.max_calls:
            sleep_time = self.period - (now - self.calls[0])
            if sleep_time > 0:
                time.sleep(sleep_time)

        self.calls.append(time.monotonic())

# Exchange rate limits (requests per minute)
RATE_LIMITS = {
    'binance_spot':   {'max_calls': 1200, 'period': 60},
    'binance_future': {'max_calls': 2400, 'period': 60},
    'kraken':         {'max_calls': 60,   'period': 60},
}
```

## Exchange-Specific Quirks

### Binance Futures
```python
# Binance requires separate endpoint for futures
exchange = ccxt.binance({
    'options': {'defaultType': 'future'},
})
# Set leverage before placing any order
await exchange.fapiPrivate_post_leverage({'symbol': 'BTCUSDT', 'leverage': 5})

# Position mode: one-way (default) or hedge
# Check with:
pos_mode = await exchange.fapiPrivateGetPositionSideDual()

# Binance timestamps must be within 5000ms of server time
# Use: exchange.options['adjustForTimeDifference'] = True
```

### Kraken
```python
# Kraken uses asset pairs with 'X' prefix for crypto, 'Z' for fiat
# BTC/USD = 'XBT/USD' on Kraken (not 'BTC/USD')
symbol = exchange.market_id('BTC/USD')  # -> 'XXBTZUSD'

# Nonce must be strictly increasing
# CCXT handles this automatically but watch for clock skew

# Kraken rate limiting: 'tier' based
# Verified accounts: 15 calls/s for private endpoints
```

### IBKR (Interactive Brokers via ib_insync)
```python
from ib_insync import IB, Stock, MarketOrder, LimitOrder

async def ibkr_place_order(contract, qty: float, order_type: str = 'MKT'):
    ib = IB()
    await ib.connectAsync('127.0.0.1', 7497, clientId=1)

    if order_type == 'MKT':
        order = MarketOrder('BUY', qty)
    else:
        order = LimitOrder('BUY', qty, price)

    trade = ib.placeOrder(contract, order)
    await ib.waitOnUpdateAsync()
    return trade.orderStatus.status
```

## Order Lifecycle Tracking

```python
from enum import Enum

class OrderStatus(Enum):
    PENDING   = 'pending'
    OPEN      = 'open'
    PARTIALLY_FILLED = 'partially_filled'
    FILLED    = 'filled'
    CANCELLED = 'cancelled'
    REJECTED  = 'rejected'

async def track_order(exchange, order_id: str, symbol: str,
                       timeout_s: float = 30) -> dict:
    """Poll order until terminal state or timeout."""
    start = asyncio.get_event_loop().time()
    while True:
        order = await exchange.fetch_order(order_id, symbol)
        status = order['status']

        if status in ('closed', 'canceled', 'rejected', 'expired'):
            return order

        if asyncio.get_event_loop().time() - start > timeout_s:
            raise TimeoutError(f"Order {order_id} not terminal after {timeout_s}s: {status}")

        await asyncio.sleep(0.5)
```

## Common Mistakes

1. **Not enabling `enableRateLimit`** — CCXT has a built-in limiter; always enable it
2. **Swallowing exceptions** — log every exchange error; silent failures cause position mismatches
3. **Testing on mainnet first** — always use sandbox/testnet; Binance Testnet: `testnet.binance.vision`
4. **WebSocket without ping** — connections drop silently without heartbeats; set `ping_interval`
5. **Ignoring symbol normalisation** — Kraken `XBT/USD` ≠ Binance `BTC/USDT`; use `exchange.market()`
6. **Sync calls in async context** — use `ccxt.async_support`, not `ccxt` in asyncio apps
7. **Assuming immediate fill** — always track order lifecycle; partial fills are common

---

## Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|---|---|---|
| Using market orders for entries in low-liquidity pairs | Slippage on thin order books can cost 1-5% per trade; wipes out strategy edge | Use limit orders within the bid-ask spread for entries; reserve market orders for emergency exits only |
| Single WebSocket connection without reconnection logic | Connections drop silently; stale data causes phantom positions or missed signals | Implement exponential backoff reconnection with heartbeat ping; detect stale data via timestamp comparison |
| Hardcoding exchange-specific symbol formats | Kraken uses XBT/USD, Binance uses BTC/USDT — code breaks when adding exchanges | Use CCXT's unified `exchange.market()` for symbol normalization across all exchanges |
| Storing API keys in source code or environment variables | Key theft from repo or environment dump leads to account compromise and fund loss | Use encrypted secret managers (Vault, AWS Secrets Manager); rotate keys on schedule; restrict IP whitelist on exchange |
| Testing trading logic on mainnet with real funds | A bug in order logic or position sizing can drain the account in seconds | Always validate on exchange sandbox/testnet first; use paper trading mode before any live deployment |
