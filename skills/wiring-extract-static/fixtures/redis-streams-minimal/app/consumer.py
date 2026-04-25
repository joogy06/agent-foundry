"""Fixture: local _consume_stream helper + direct xreadgroup + module attr."""
from shared import constants
from shared.constants import STREAM_CANDLES, STREAM_KILL_SWITCH


async def _consume_stream(stream, handler, r=None):
    """Local helper that forwards `stream` to xreadgroup."""
    messages = await r.xreadgroup("group-0", "consumer-0",
                                  {stream: ">"}, count=10, block=5000)
    for _name, entries in messages:
        for _msg_id, data in entries:
            await handler(data)


async def consume_candles(handler):
    await _consume_stream(STREAM_CANDLES, handler)


async def consume_kill_switch(handler):
    # Attribute access through module alias.
    await _consume_stream(constants.STREAM_KILL_SWITCH, handler)


async def consume_direct(r, handler):
    # Direct xreadgroup with dict literal, stream name as STREAM_CANDLES.
    messages = await r.xreadgroup("g", "c", {STREAM_CANDLES: ">"}, count=1)
    return messages
