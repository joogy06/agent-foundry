#!/usr/bin/env python3
"""Tests for spawn_usage.extract_usage — the shared null-safe usage extractor.

S046 / S039-review #124 verification (observe-only cost telemetry):
  * a captured `claude -p --output-format json` envelope -> cost/duration/
    num_turns present;
  * a non-JSON / Codex path -> null, NOT an error (the function never raises).

Run:
    pytest skills/_meta/tests/test_spawn_usage.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_META = Path(__file__).resolve().parent.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import spawn_usage  # noqa: E402


# ---------------------------------------------------------------------------
# Realistic envelopes
# ---------------------------------------------------------------------------

def _stream_array_envelope(cost=0.0123, dur=4210, turns=2):
    """Shape (a): claude 2.1.x top-level array of stream messages. The terminal
    result element carries total_cost_usd / duration_ms / num_turns."""
    return [
        {"type": "system", "subtype": "init", "session_id": "abc"},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": '{"verdict":"VERIFIED"}'}]}},
        {
            "type": "result",
            "subtype": "success",
            "result": '{"verdict":"VERIFIED"}',
            "total_cost_usd": cost,
            "duration_ms": dur,
            "num_turns": turns,
            "is_error": False,
        },
    ]


# ---------------------------------------------------------------------------
# Happy path — fields captured
# ---------------------------------------------------------------------------

def test_stream_array_parsed_object():
    env = _stream_array_envelope(cost=0.0123, dur=4210, turns=2)
    u = spawn_usage.extract_usage(env)
    assert u["cost_usd"] == 0.0123
    assert u["duration_ms"] == 4210
    assert u["num_turns"] == 2


def test_stream_array_raw_string():
    """Passing raw stdout text (not pre-parsed) also works — parsed once."""
    env = _stream_array_envelope(cost=0.5, dur=999, turns=1)
    raw = json.dumps(env)
    u = spawn_usage.extract_usage(raw)
    assert u["cost_usd"] == 0.5
    assert u["duration_ms"] == 999
    assert u["num_turns"] == 1


def test_legacy_dict_top_level_fields():
    """Shape (b): a dict envelope carrying the cost fields at top level."""
    env = {
        "result": '{"verdict":"VERIFIED"}',
        "total_cost_usd": 0.07,
        "duration_ms": 1500,
        "num_turns": 3,
    }
    u = spawn_usage.extract_usage(env)
    assert u["cost_usd"] == 0.07
    assert u["duration_ms"] == 1500
    assert u["num_turns"] == 3


def test_legacy_dict_nested_under_result():
    """Defensive: some CLI versions nest usage under a result OBJECT."""
    env = {"result": {"total_cost_usd": 0.02, "duration_ms": 800, "num_turns": 1}}
    u = spawn_usage.extract_usage(env)
    assert u["cost_usd"] == 0.02
    assert u["duration_ms"] == 800
    assert u["num_turns"] == 1


def test_numeric_string_coercion():
    env = _stream_array_envelope()
    env[-1]["total_cost_usd"] = "0.0456"
    env[-1]["duration_ms"] = "3300"
    u = spawn_usage.extract_usage(env)
    assert u["cost_usd"] == 0.0456
    assert u["duration_ms"] == 3300


# ---------------------------------------------------------------------------
# Null-safety — non-JSON / Codex / absent -> null, NEVER raise
# ---------------------------------------------------------------------------

def test_codex_plaintext_path_returns_null():
    """The Codex arm emits plain prose, not JSON. -> all-None, no raise."""
    u = spawn_usage.extract_usage("Looks fine to me. VERIFIED.\nNo issues.")
    assert u == {"cost_usd": None, "duration_ms": None, "num_turns": None}


def test_none_input_returns_null():
    assert spawn_usage.extract_usage(None) == {
        "cost_usd": None, "duration_ms": None, "num_turns": None}


def test_empty_string_returns_null():
    assert spawn_usage.extract_usage("") == {
        "cost_usd": None, "duration_ms": None, "num_turns": None}


def test_array_without_result_element_returns_null():
    """A truncated stream with no result element -> all-None."""
    env = [{"type": "system"}, {"type": "assistant", "message": {"content": []}}]
    assert spawn_usage.extract_usage(env) == {
        "cost_usd": None, "duration_ms": None, "num_turns": None}


def test_result_element_missing_fields_returns_null():
    """A result element that omits the cost fields -> all-None (no KeyError)."""
    env = [{"type": "result", "result": "{}", "subtype": "success"}]
    u = spawn_usage.extract_usage(env)
    assert u == {"cost_usd": None, "duration_ms": None, "num_turns": None}


def test_partial_fields_only_present_ones_filled():
    """If only cost is present, duration/turns stay None (independent fields)."""
    env = [{"type": "result", "total_cost_usd": 0.01}]
    u = spawn_usage.extract_usage(env)
    assert u["cost_usd"] == 0.01
    assert u["duration_ms"] is None
    assert u["num_turns"] is None


def test_bool_values_rejected():
    """A stray bool must NOT read as 1.0 (bool is an int subclass)."""
    env = [{"type": "result", "total_cost_usd": True, "duration_ms": False,
            "num_turns": True}]
    u = spawn_usage.extract_usage(env)
    assert u == {"cost_usd": None, "duration_ms": None, "num_turns": None}


def test_malformed_json_string_returns_null():
    assert spawn_usage.extract_usage("{not valid json") == {
        "cost_usd": None, "duration_ms": None, "num_turns": None}


def test_unexpected_type_returns_null():
    for bad in (42, 3.14, True, [1, 2, 3], {"x": object()}):
        u = spawn_usage.extract_usage(bad)
        assert set(u.keys()) == {"cost_usd", "duration_ms", "num_turns"}


def test_never_raises_on_pathological_object():
    """Even an object whose .get() explodes must not propagate."""
    class Evil(dict):
        def get(self, *a, **k):
            raise RuntimeError("boom")

    # extract_usage treats it as a dict; the internal .get() raises but the
    # top-level BaseException guard swallows it -> all-None.
    u = spawn_usage.extract_usage(Evil())
    assert u == {"cost_usd": None, "duration_ms": None, "num_turns": None}


def test_return_shape_is_always_three_keys():
    """Contract: every path returns exactly the 3 canonical keys."""
    for inp in (None, "", "[]", _stream_array_envelope(), {"result": "x"}):
        u = spawn_usage.extract_usage(inp)
        assert set(u.keys()) == set(spawn_usage.USAGE_KEYS)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
