#!/usr/bin/env python3
"""spawn_usage.py — shared null-safe usage extractor for cold-context spawners.

S046 / S039-review #124 (observe-only cost telemetry, v1).

Both cold-context verifier spawners — `audit_spawn.py` (Claude + Codex dual
arm) and `verification_arbiter_spawn.py` (single Claude arm) — invoke
`claude -p --output-format json`. That envelope's terminal `{"type":"result"}`
element (claude 2.1.x stream-array shape) carries three cost/latency fields the
spawners currently parse-then-discard:

    total_cost_usd   (float)   — USD billed for the whole headless run
    duration_ms      (int)     — wall time the CLI reports for the run
    num_turns        (int)     — assistant turns taken

This module exposes ONE function, `extract_usage(envelope)`, that pulls those
fields out of an already-parsed envelope (or a raw stdout string) and returns a
normalized dict. It is deliberately:

  * **Null-safe** — every field defaults to None. A non-JSON path (e.g. the
    Codex arm's `codex exec` plain output), a missing `result` element, a
    truncated envelope, or absent fields all yield None for that field. The
    function NEVER raises (wrapped in a top-level try/except BaseException),
    so threading it through a spawner's hot path can never perturb the
    spawner's verdict-return API or exit code (#124 scope guard, mirrors the
    `gate_runs.py` / `claude_observe` never-raise discipline).

  * **API-preserving** — it READS an envelope; it does not mutate it, does not
    touch the evidence bundle, and does not touch the arbiter's stdout verdict
    (which is `additionalProperties:false` per verdict_schema.json:7 and would
    reject extras). Callers keep returning exactly what they returned before.

Design refs:
    docs/plans/2026-06-07-s039-batch1-telemetry-rollback-lease-design.md §A, §G
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

# Canonical result keys (stable across callers + the sidecar writer).
USAGE_KEYS = ("cost_usd", "duration_ms", "num_turns")

# The three source fields on the claude -p --output-format json result envelope.
_SRC_COST = "total_cost_usd"
_SRC_DURATION = "duration_ms"
_SRC_TURNS = "num_turns"


def _null_usage() -> Dict[str, Optional[float]]:
    """A fresh all-None usage dict. Every code path returns one of these
    shapes (same keys, only the values differ), so a caller can blindly
    `.get("cost_usd")` without a KeyError regardless of input."""
    return {"cost_usd": None, "duration_ms": None, "num_turns": None}


def _coerce_number(value: Any) -> Optional[float]:
    """Coerce a JSON number-ish value to float/int, else None.

    bool is an int subclass but is never a valid cost/duration/turn count, so
    it is explicitly rejected (a stray `true` must not read as 1.0)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    # Some CLIs stringify numbers ("0.0123"). Accept a clean numeric string.
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            if "." in s or "e" in s or "E" in s:
                return float(s)
            return int(s)
        except ValueError:
            return None
    return None


def _usage_from_result_dict(result_msg: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Pull the three fields off a single `{"type":"result", ...}` message."""
    out = _null_usage()
    out["cost_usd"] = _coerce_number(result_msg.get(_SRC_COST))
    out["duration_ms"] = _coerce_number(result_msg.get(_SRC_DURATION))
    out["num_turns"] = _coerce_number(result_msg.get(_SRC_TURNS))
    return out


def extract_usage(envelope: Any) -> Dict[str, Optional[float]]:
    """Extract {cost_usd, duration_ms, num_turns} from a claude -p JSON envelope.

    Accepts any of:
      * the already-parsed envelope (list-of-stream-messages, shape (a)) —
        the preferred input; the caller parses stdout once and passes the
        parsed object so we don't double-parse;
      * a parsed legacy dict envelope (shape (b)) that itself carries the
        cost fields at the top level OR nested under a "result" object;
      * a raw stdout str (we parse it as JSON best-effort);
      * anything else / None / non-JSON (the Codex arm) -> all-None.

    NEVER raises. On ANY failure (bad type, parse error, unexpected shape)
    returns an all-None usage dict. This is the #124 null-safety contract:
    "absent on non-JSON/Codex paths -> null, never raise".
    """
    try:
        obj = envelope

        # Raw string -> parse once (best-effort). Non-JSON -> all-None.
        if isinstance(obj, str):
            s = obj.strip()
            if not s:
                return _null_usage()
            try:
                obj = json.loads(s)
            except (json.JSONDecodeError, ValueError):
                return _null_usage()

        # Shape (a): top-level array of stream messages. The terminal
        # {"type":"result", ...} element carries the cost/latency fields.
        if isinstance(obj, list):
            for msg in reversed(obj):
                if isinstance(msg, dict) and msg.get("type") == "result":
                    return _usage_from_result_dict(msg)
            # No result element -> nothing to bill (e.g. truncated stream).
            return _null_usage()

        # Shape (b): dict envelope. The fields may be at the top level, or
        # nested under a "result" object (defensive across CLI versions).
        if isinstance(obj, dict):
            # Direct top-level fields win.
            top = _usage_from_result_dict(obj)
            if any(top[k] is not None for k in USAGE_KEYS):
                return top
            inner = obj.get("result")
            if isinstance(inner, dict):
                return _usage_from_result_dict(inner)
            return _null_usage()

        # Any other type (None, int, ...) -> nothing to extract.
        return _null_usage()
    except BaseException:  # noqa: BLE001 — null-safety contract: never raise.
        return _null_usage()
