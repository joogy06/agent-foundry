"""Fixture: direct xadd + helper-wrapper publish."""
from shared.constants import STREAM_CANDLES, STREAM_NEWS, MAXLEN_CANDLES
from shared.redis_client import publish_to_stream


def publish_candle(redis, symbol, price):
    redis.xadd(STREAM_CANDLES, {"symbol": symbol, "price": price},
               maxlen=MAXLEN_CANDLES)


def publish_news(redis, payload):
    publish_to_stream(redis, STREAM_NEWS, payload)


def publish_from_config(redis, payload):
    # Gap: dynamic stream name from a runtime attribute we cannot resolve.
    # This is NOT a helper (no parameter forwarding); it's a true unresolved
    # call site that should surface as a gap rather than an edge.
    cfg = _get_runtime_config()
    redis.xadd(cfg.stream, payload)


def _get_runtime_config():
    return None  # placeholder — fixture only needs the AST shape above.
