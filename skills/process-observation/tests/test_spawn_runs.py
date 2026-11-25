#!/usr/bin/env python3
"""Tests for spawn_runs.record_spawn_run — the cost/latency sidecar writer.

S046 / S039-review #124 verification (observe-only cost telemetry):
  * a spawn-runs.jsonl record is written with ALL correlation fields;
  * the writer is best-effort never-raise (a broken backend cannot perturb the
    caller) -> telemetry byte-invariance under a forced writer ImportError;
  * the NEW sidecar never touches the existing friction ledger / gate-runs
    denominator (the taxonomy + efficacy denominator alf consumes stay clean).

Run:
    pytest skills/process-observation/tests/test_spawn_runs.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import spawn_runs  # noqa: E402


def _read_spawn_runs(root: Path):
    p = root / ".process-observations" / spawn_runs.SPAWN_RUNS_FILENAME
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# Happy path — full record with all correlation fields
# ---------------------------------------------------------------------------

def test_writes_record_with_all_correlation_fields(tmp_path):
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    spawn_runs.record_spawn_run(
        tool="verification_arbiter",
        status="VERIFIED",
        cost_usd=0.0123,
        duration_ms=4210,
        num_turns=2,
        wall_clock_s=4.4,
        model="claude-opus-4-6[1m]",
        cycle_id="S046",
        component_id="wiring-extract-static",
        bundle_hash="a" * 64,
        request_id="b" * 32,
        invocation_id="inv-123",
        project_root_override=root,
    )
    recs = _read_spawn_runs(root)
    assert len(recs) == 1
    r = recs[0]
    # Every required correlation field present (design §G).
    for k in ("ts", "invocation_id", "cycle_id", "component_id", "bundle_hash",
              "request_id", "tool", "model", "status", "cost_usd",
              "duration_ms", "num_turns", "wall_clock_s"):
        assert k in r, f"missing correlation field {k!r}"
    assert r["invocation_id"] == "inv-123"
    assert r["component_id"] == "wiring-extract-static"
    assert r["bundle_hash"] == "a" * 64
    assert r["request_id"] == "b" * 32
    assert r["tool"] == "verification_arbiter"
    assert r["status"] == "VERIFIED"
    assert r["cost_usd"] == 0.0123
    assert r["duration_ms"] == 4210
    assert r["num_turns"] == 2
    assert r["wall_clock_s"] == 4.4


def test_null_usage_fields_persist_as_null(tmp_path):
    """The Codex / non-JSON path passes None for cost/duration/turns -> the
    record stores JSON null, not 0 or a crash."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    spawn_runs.record_spawn_run(
        tool="audit_codex",
        status="pass",
        cost_usd=None,
        duration_ms=None,
        num_turns=None,
        wall_clock_s=12.0,
        component_id="comp-x",
        project_root_override=root,
    )
    r = _read_spawn_runs(root)[0]
    assert r["cost_usd"] is None
    assert r["duration_ms"] is None
    assert r["num_turns"] is None
    assert r["wall_clock_s"] == 12.0
    # Unsupplied optional correlation fields default to null, not absent.
    assert r["request_id"] is None
    assert r["bundle_hash"] is None
    assert r["cycle_id"] is None
    # invocation_id is always minted even when not supplied.
    assert isinstance(r["invocation_id"], str) and r["invocation_id"]


def test_numeric_string_coercion(tmp_path):
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    spawn_runs.record_spawn_run(
        tool="audit_claude", status="pass",
        cost_usd="0.0456", duration_ms="3300", num_turns="1",
        wall_clock_s="3.5", project_root_override=root)
    r = _read_spawn_runs(root)[0]
    assert r["cost_usd"] == 0.0456
    assert r["duration_ms"] == 3300
    assert r["num_turns"] == 1
    assert r["wall_clock_s"] == 3.5


def test_appends_multiple_records(tmp_path):
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    for i in range(3):
        spawn_runs.record_spawn_run(
            tool="verification_arbiter", status="VERIFIED",
            cost_usd=0.01 * (i + 1), duration_ms=100 * (i + 1), num_turns=1,
            wall_clock_s=1.0, project_root_override=root)
    recs = _read_spawn_runs(root)
    assert len(recs) == 3
    assert [r["cost_usd"] for r in recs] == [0.01, 0.02, 0.03]


# ---------------------------------------------------------------------------
# Never-raise + byte-invariance
# ---------------------------------------------------------------------------

def test_never_raises_on_broken_writer(tmp_path, monkeypatch):
    """If the underlying append explodes, record_spawn_run swallows it."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)

    def _boom(*a, **k):
        raise RuntimeError("simulated writer explosion")

    monkeypatch.setattr(spawn_runs, "_append_event_line", _boom)
    # Must NOT raise.
    spawn_runs.record_spawn_run(
        tool="verification_arbiter", status="VERIFIED",
        cost_usd=0.01, duration_ms=100, num_turns=1, wall_clock_s=1.0,
        project_root_override=root)
    # And nothing was written.
    assert _read_spawn_runs(root) == []


def test_no_project_root_is_noop(tmp_path, monkeypatch):
    """With no discoverable project root and no override -> silent no-op."""
    monkeypatch.setattr(spawn_runs, "_discover_project_root", lambda *a, **k: None)
    # Must NOT raise and must NOT write anywhere.
    spawn_runs.record_spawn_run(
        tool="audit_claude", status="pass",
        cost_usd=0.01, duration_ms=100, num_turns=1, wall_clock_s=1.0)


def test_sidecar_does_not_touch_friction_or_gate_runs(tmp_path):
    """Byte-invariance of the EXISTING ledgers: writing a spawn-run leaves
    active.yaml / events.jsonl / gate-runs.jsonl untouched (design §4 #5)."""
    root = tmp_path / "proj"
    obs = root / ".process-observations"
    obs.mkdir(parents=True)
    # Seed pre-existing sibling ledgers.
    (obs / "active.yaml").write_text("seed-active\n", encoding="utf-8")
    (obs / "events.jsonl").write_text('{"seed":"event"}\n', encoding="utf-8")
    (obs / "gate-runs.jsonl").write_text('{"seed":"gate"}\n', encoding="utf-8")
    before = {p.name: p.read_bytes() for p in obs.iterdir() if p.is_file()}

    spawn_runs.record_spawn_run(
        tool="verification_arbiter", status="VERIFIED",
        cost_usd=0.01, duration_ms=100, num_turns=1, wall_clock_s=1.0,
        project_root_override=root)

    # The siblings are byte-identical; only spawn-runs.jsonl is new.
    for name, data in before.items():
        assert (obs / name).read_bytes() == data, f"{name} was perturbed"
    assert (obs / spawn_runs.SPAWN_RUNS_FILENAME).is_file()


def test_records_are_canonical_json(tmp_path):
    """Each line is canonical JSON (sorted keys, compact) like events.jsonl."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    spawn_runs.record_spawn_run(
        tool="audit_claude", status="pass",
        cost_usd=0.01, duration_ms=100, num_turns=1, wall_clock_s=1.0,
        project_root_override=root)
    raw = (root / ".process-observations" / spawn_runs.SPAWN_RUNS_FILENAME
           ).read_text(encoding="utf-8").strip()
    # Re-serialize canonically and compare -> proves sorted-keys/compact.
    obj = json.loads(raw)
    assert raw == json.dumps(obj, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False)


# ---------------------------------------------------------------------------
# S081 WP-R01 (design §4.11) — optional provenance / quota fields
# ---------------------------------------------------------------------------

# The row shape every pre-S081 caller produces. It must not change.
_LEGACY_KEYS = frozenset({
    "ts", "invocation_id", "cycle_id", "component_id", "bundle_hash",
    "request_id", "tool", "model", "status", "cost_usd", "duration_ms",
    "num_turns", "wall_clock_s",
})

_OPTIONAL_VALUES = {
    "requested_model": "gpt-5.6-sol",
    "served_model": "gpt-5.6-sol",
    "tokens": {"input": 1200, "output": 340},
    "quota_before": {"primary_used_percent": 42, "secondary_used_percent": 7},
    "quota_after": {"primary_used_percent": 43, "secondary_used_percent": 7},
    "quota_source": "rollout",
    "role": "code_reviewer",
    "env_override_refused": {"var": "AUDIT_CODEX_MODEL", "value": "gpt-5.5"},
}


def _record_minimal(root, **extra):
    spawn_runs.record_spawn_run(
        tool="audit_codex", status="pass",
        cost_usd=None, duration_ms=None, num_turns=None, wall_clock_s=2.0,
        project_root_override=root, **extra)


def test_optional_fields_absent_keep_the_legacy_row_shape(tmp_path):
    """Existing callers pass none of the new keywords -> the row carries
    exactly the legacy keys (byte-shape unchanged for every current caller)."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    _record_minimal(root)
    r = _read_spawn_runs(root)[0]
    assert set(r) == _LEGACY_KEYS


def test_optional_fields_passed_as_none_are_omitted(tmp_path):
    """A key is emitted only for a non-None value: passing None explicitly is
    indistinguishable from not passing it."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    _record_minimal(root, **{k: None for k in _OPTIONAL_VALUES})
    r = _read_spawn_runs(root)[0]
    assert set(r) == _LEGACY_KEYS


def test_optional_fields_present_when_passed(tmp_path):
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    _record_minimal(root, **_OPTIONAL_VALUES)
    r = _read_spawn_runs(root)[0]
    assert set(r) == _LEGACY_KEYS | set(_OPTIONAL_VALUES)
    for key, value in _OPTIONAL_VALUES.items():
        assert r[key] == value, key


def test_optional_fields_are_independent(tmp_path):
    """Each optional key appears on its own; one does not drag in the others."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    for key, value in _OPTIONAL_VALUES.items():
        _record_minimal(root, **{key: value})
    recs = _read_spawn_runs(root)
    assert len(recs) == len(_OPTIONAL_VALUES)
    for rec, (key, value) in zip(recs, _OPTIONAL_VALUES.items()):
        assert set(rec) == _LEGACY_KEYS | {key}
        assert rec[key] == value


def test_unserialisable_optional_value_still_writes_the_row(tmp_path, capsys):
    """Never-raise holds for the new fields: a value json cannot encode is
    coerced to str and the row is still written (not swallowed as a failure)."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)

    class Opaque:
        def __str__(self):
            return "opaque-token-counter"

    circular = {"input": 5}
    circular["self"] = circular

    _record_minimal(
        root,
        tokens=Opaque(),                                   # wholly unserialisable
        quota_before={"primary": 42, "at": Opaque()},      # unserialisable leaf
        quota_after=circular,                              # json raises ValueError
        role="code_reviewer",
    )
    recs = _read_spawn_runs(root)
    assert len(recs) == 1, "the row must be written, not dropped"
    r = recs[0]
    assert r["tokens"] == "opaque-token-counter"
    assert r["quota_before"] == {"primary": 42, "at": "opaque-token-counter"}
    assert isinstance(r["quota_after"], str)
    assert r["role"] == "code_reviewer"
    assert "SPAWN_RUN_RECORD_FAIL" not in capsys.readouterr().err


def test_unserialisable_value_whose_str_raises_still_writes_the_row(tmp_path):
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)

    class Hostile:
        def __str__(self):
            raise RuntimeError("no str for you")

        def __repr__(self):
            raise RuntimeError("no repr either")

    _record_minimal(root, tokens=Hostile(), role="arbiter")
    recs = _read_spawn_runs(root)
    assert len(recs) == 1
    assert isinstance(recs[0]["tokens"], str)
    assert recs[0]["role"] == "arbiter"


# ---------------------------------------------------------------------------
# S081 WP-F03 (amendment 1 D6, plan J15) — substitution fields
# ---------------------------------------------------------------------------
#
# When astra cannot serve the VERIFIED-gate audit's codex arm, a fresh Fable
# auditor takes the slot and the arm's row says so. The three keys follow the
# same rule as the S081 optional fields: written only for a non-None value, so
# every row that is not a substitution keeps its exact key set.

_SUBSTITUTION_VALUES = {
    "substitute_for": "codex",
    "substitution_reason": "quota_exhausted",
    "use": "audit",
}


def test_substitution_fields_absent_keep_the_legacy_row_shape(tmp_path):
    """A caller that passes none of them writes exactly the legacy keys, and
    passing None explicitly is the same as not passing them."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    _record_minimal(root)
    _record_minimal(root, **{k: None for k in _SUBSTITUTION_VALUES})
    recs = _read_spawn_runs(root)
    assert len(recs) == 2
    for r in recs:
        assert set(r) == _LEGACY_KEYS
        for key in _SUBSTITUTION_VALUES:
            assert key not in r


def test_substitution_fields_present_when_passed(tmp_path):
    """CONTROL for the test above: the same call with values writes all three,
    alongside every earlier optional field (none displaces another)."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    _record_minimal(root, **_SUBSTITUTION_VALUES)
    _record_minimal(root, **_OPTIONAL_VALUES, **_SUBSTITUTION_VALUES)
    first, both = _read_spawn_runs(root)
    assert set(first) == _LEGACY_KEYS | set(_SUBSTITUTION_VALUES)
    assert set(both) == _LEGACY_KEYS | set(_OPTIONAL_VALUES) | set(_SUBSTITUTION_VALUES)
    for rec in (first, both):
        for key, value in _SUBSTITUTION_VALUES.items():
            assert rec[key] == value, key


def test_substitution_fields_are_independent(tmp_path):
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    for key, value in _SUBSTITUTION_VALUES.items():
        _record_minimal(root, **{key: value})
    recs = _read_spawn_runs(root)
    assert len(recs) == len(_SUBSTITUTION_VALUES)
    for rec, (key, value) in zip(recs, _SUBSTITUTION_VALUES.items()):
        assert set(rec) == _LEGACY_KEYS | {key}
        assert rec[key] == value


def test_unserialisable_substitution_value_still_writes_the_row(tmp_path, capsys):
    """Never-raise holds for the new fields too: the row is written, the value
    coerced to str, and nothing is reported as a record failure."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)

    class Opaque:
        def __str__(self):
            return "opaque-reason"

    class Hostile:
        def __str__(self):
            raise RuntimeError("no str")

        def __repr__(self):
            raise RuntimeError("no repr")

    _record_minimal(root, substitution_reason=Opaque(), substitute_for={"to": Opaque()},
                    use=Hostile())
    recs = _read_spawn_runs(root)
    assert len(recs) == 1, "the row must be written, not dropped"
    assert recs[0]["substitution_reason"] == "opaque-reason"
    assert recs[0]["substitute_for"] == {"to": "opaque-reason"}
    assert isinstance(recs[0]["use"], str)
    assert "SPAWN_RUN_RECORD_FAIL" not in capsys.readouterr().err


def test_substitution_fields_never_raise_on_a_broken_writer(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)

    def _boom(*a, **k):
        raise RuntimeError("simulated writer explosion")

    monkeypatch.setattr(spawn_runs, "_append_event_line", _boom)
    _record_minimal(root, **_SUBSTITUTION_VALUES)  # must NOT raise
    assert _read_spawn_runs(root) == []


# ---------------------------------------------------------------------------
# #282 R3 (plan K5) — the served-model fields of a claude reviewer row
# ---------------------------------------------------------------------------
#
# `served_model_usage` ({model id: outputTokens}, every modelUsage key) and
# `served_model_mismatch` (true, present only on a mismatch) follow the same rule
# as every optional field: written only for a non-None value, so a row that does
# not pass them keeps its exact key set.

_SERVED_VALUES = {
    "served_model_usage": {"claude-haiku-x": 50, "claude-fable-5-1": 900},
    "served_model_mismatch": True,
}


def test_served_model_fields_absent_when_none_keep_every_existing_key_set(tmp_path):
    """Not passed, or passed as None -> absent: the legacy row, the S081 optional row and the
    substitution row each keep exactly the key set they had before #282."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    none = {k: None for k in _SERVED_VALUES}
    _record_minimal(root)
    _record_minimal(root, **none)
    _record_minimal(root, **_OPTIONAL_VALUES, **none)
    _record_minimal(root, **_OPTIONAL_VALUES, **_SUBSTITUTION_VALUES, **none)
    legacy, legacy_none, optional, substituted = _read_spawn_runs(root)
    assert set(legacy) == set(legacy_none) == _LEGACY_KEYS
    assert set(optional) == _LEGACY_KEYS | set(_OPTIONAL_VALUES)
    assert set(substituted) == _LEGACY_KEYS | set(_OPTIONAL_VALUES) | set(_SUBSTITUTION_VALUES)
    for rec in (legacy, legacy_none, optional, substituted):
        for key in _SERVED_VALUES:
            assert key not in rec, key


def test_served_model_fields_written_when_given(tmp_path):
    """CONTROL for the absence above: the same calls with values write both keys verbatim,
    alongside every earlier optional and substitution field; each key also stands alone."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    _record_minimal(root, **_OPTIONAL_VALUES, **_SUBSTITUTION_VALUES, **_SERVED_VALUES)
    for key, value in _SERVED_VALUES.items():
        _record_minimal(root, **{key: value})
    everything, usage_only, mismatch_only = _read_spawn_runs(root)
    assert set(everything) == (_LEGACY_KEYS | set(_OPTIONAL_VALUES) | set(_SUBSTITUTION_VALUES)
                               | set(_SERVED_VALUES))
    for key, value in _SERVED_VALUES.items():
        assert everything[key] == value, key
    assert set(usage_only) == _LEGACY_KEYS | {"served_model_usage"}
    assert usage_only["served_model_usage"] == {"claude-haiku-x": 50, "claude-fable-5-1": 900}
    assert set(mismatch_only) == _LEGACY_KEYS | {"served_model_mismatch"}
    assert mismatch_only["served_model_mismatch"] is True


# ---------------------------------------------------------------------------
# S081 rev 4 WP-A01b (team-lead ruling 1) — the D24 watchdog fields
# ---------------------------------------------------------------------------
#
# skills/_meta/codex_watch.py offers these five on every call. `max_silence_s`
# is the one that earns the amendment: it is the only field that can say how
# close a HEALTHY call came to tripping the idle timeout, which is the question
# the D24 thresholds have to be tuned against — `wall_clock_s` and `status`
# describe calls that stopped, not the margin on the ones that did not.
#
# Same rule as every optional field before them: written only for a non-None
# value, so no existing caller's row changes at all.

_WATCHDOG_VALUES = {
    "max_silence_s": 312.5,
    "stop_reason": "idle_timeout",
    "exit_code": 111,
    "idle_timeout_s": 300,
    "hard_cap_s": 2400,
}


def test_watchdog_fields_absent_keep_every_existing_row_byte_shape(tmp_path):
    """THE BACKWARD-COMPATIBILITY CONTROL. A caller passing TODAY'S EXACT
    ARGUMENTS — none of the five new parameters — still records correctly, and
    its row is not merely 'unchanged apart from five nulls' but BYTE-IDENTICAL
    in key set to the row it wrote before the amendment: the five default to
    None and this module never emits a None optional.

    Checked against the legacy row, the S081 optional row and the substitution
    row, and with the five passed explicitly as None (indistinguishable from
    not passing them).
    """
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    none = {k: None for k in _WATCHDOG_VALUES}
    _record_minimal(root)                                       # today's call
    _record_minimal(root, **none)                               # explicit None
    _record_minimal(root, **_OPTIONAL_VALUES)
    _record_minimal(root, **_OPTIONAL_VALUES, **_SUBSTITUTION_VALUES, **none)
    legacy, legacy_none, optional, substituted = _read_spawn_runs(root)
    assert set(legacy) == set(legacy_none) == _LEGACY_KEYS
    assert set(optional) == _LEGACY_KEYS | set(_OPTIONAL_VALUES)
    assert set(substituted) == (_LEGACY_KEYS | set(_OPTIONAL_VALUES)
                                | set(_SUBSTITUTION_VALUES))
    for rec in (legacy, legacy_none, optional, substituted):
        for key in _WATCHDOG_VALUES:
            assert key not in rec, key
    # The row still records correctly, not just narrowly: same content as ever.
    assert legacy["tool"] == "audit_codex"
    assert legacy["status"] == "pass"
    assert legacy["wall_clock_s"] == 2.0


def test_watchdog_fields_each_round_trip_when_passed(tmp_path):
    """CONTROL for the absence above: every one of the five is written verbatim
    when given, together and on its own (one never drags in another)."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    _record_minimal(root, **_WATCHDOG_VALUES)
    for key, value in _WATCHDOG_VALUES.items():
        _record_minimal(root, **{key: value})
    recs = _read_spawn_runs(root)
    assert len(recs) == 1 + len(_WATCHDOG_VALUES)
    together = recs[0]
    assert set(together) == _LEGACY_KEYS | set(_WATCHDOG_VALUES)
    for key, value in _WATCHDOG_VALUES.items():
        assert together[key] == value, key
    for rec, (key, value) in zip(recs[1:], _WATCHDOG_VALUES.items()):
        assert set(rec) == _LEGACY_KEYS | {key}
        assert rec[key] == value


def test_watchdog_fields_coexist_with_every_earlier_optional_block(tmp_path):
    """The five do not displace the S081, substitution or #282 R3 fields."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    _record_minimal(root, **_OPTIONAL_VALUES, **_SUBSTITUTION_VALUES,
                    **_SERVED_VALUES, **_WATCHDOG_VALUES)
    r = _read_spawn_runs(root)[0]
    assert set(r) == (_LEGACY_KEYS | set(_OPTIONAL_VALUES)
                      | set(_SUBSTITUTION_VALUES) | set(_SERVED_VALUES)
                      | set(_WATCHDOG_VALUES))
    for source in (_OPTIONAL_VALUES, _SUBSTITUTION_VALUES, _SERVED_VALUES,
                   _WATCHDOG_VALUES):
        for key, value in source.items():
            assert r[key] == value, key


def test_a_zero_watchdog_value_is_written_not_dropped_as_falsy(tmp_path):
    """`exit_code=0` (a codex call that succeeded) and `max_silence_s=0.0` (one
    that never went quiet) are REAL readings. The rule is `is not None`, not
    truthiness — a falsy-drop here would silently erase exactly the healthy
    calls the telemetry exists to measure."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    _record_minimal(root, exit_code=0, max_silence_s=0.0, stop_reason="ok",
                    idle_timeout_s=0, hard_cap_s=0.0)
    r = _read_spawn_runs(root)[0]
    assert r["exit_code"] == 0
    assert r["max_silence_s"] == 0.0
    assert r["stop_reason"] == "ok"
    assert r["idle_timeout_s"] == 0
    assert r["hard_cap_s"] == 0.0


def test_an_agy_row_omits_idle_timeout_because_none_applies(tmp_path):
    """The shape codex_watch actually writes for an agy call: agy has no idle
    timeout at all (it is silent while reasoning, so stdout growth cannot tell
    thinking from hung), so the field is None and the key is absent. The other
    four are still there — the absence is a statement, not a gap."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    _record_minimal(root, max_silence_s=900.0, stop_reason="hard_cap",
                    exit_code=112, idle_timeout_s=None, hard_cap_s=900)
    r = _read_spawn_runs(root)[0]
    assert "idle_timeout_s" not in r
    assert r["hard_cap_s"] == 900
    assert r["stop_reason"] == "hard_cap"
    assert r["exit_code"] == 112
    assert r["max_silence_s"] == 900.0


def test_watchdog_fields_never_raise_on_a_broken_writer(tmp_path, monkeypatch):
    """The fail-soft contract is preserved verbatim: a broken backend still
    cannot perturb the caller, with the new fields in play."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)

    def _boom(*a, **k):
        raise RuntimeError("simulated writer explosion")

    monkeypatch.setattr(spawn_runs, "_append_event_line", _boom)
    _record_minimal(root, **_WATCHDOG_VALUES)  # must NOT raise
    assert _read_spawn_runs(root) == []


def test_unserialisable_watchdog_value_still_writes_the_row(tmp_path, capsys):
    """Never-raise holds for these too: an unencodable value is coerced and the
    row — the only record the call happened — is still written."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)

    class Opaque:
        def __str__(self):
            return "opaque-reason"

    _record_minimal(root, stop_reason=Opaque(), max_silence_s=42.0)
    recs = _read_spawn_runs(root)
    assert len(recs) == 1, "the row must be written, not dropped"
    assert recs[0]["stop_reason"] == "opaque-reason"
    assert recs[0]["max_silence_s"] == 42.0
    assert "SPAWN_RUN_RECORD_FAIL" not in capsys.readouterr().err


def test_a_watchdog_row_is_still_canonical_json(tmp_path):
    """The new keys keep the line canonical (sorted, compact) like every other
    sidecar line — the rollup reads these by line."""
    root = tmp_path / "proj"
    (root / ".process-observations").mkdir(parents=True)
    _record_minimal(root, **_WATCHDOG_VALUES)
    raw = (root / ".process-observations" / spawn_runs.SPAWN_RUNS_FILENAME
           ).read_text(encoding="utf-8").strip()
    assert raw == json.dumps(json.loads(raw), sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# S081 WP-R01 — CONTROL for test isolation
# ---------------------------------------------------------------------------
#
# The spawner test modules isolate telemetry by running inside a tmp project
# root, relying on cwd discovery. This proves that path really WRITES there, so
# an isolation test cannot pass merely because the recorder wrote nothing.

def test_cwd_discovery_writes_into_the_tmp_project_root(tmp_path, monkeypatch):
    root = tmp_path / "sandbox"
    (root / ".process-observations").mkdir(parents=True)
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)  # discovery must walk up to the sandbox marker
    spawn_runs.record_spawn_run(
        tool="verification_arbiter", status="VERIFIED",
        cost_usd=0.01, duration_ms=100, num_turns=1, wall_clock_s=1.0,
        component_id="comp-x", role="code_reviewer")
    recs = _read_spawn_runs(root)
    assert len(recs) == 1
    assert set(recs[0]) == _LEGACY_KEYS | {"role"}
    assert recs[0]["tool"] == "verification_arbiter"
    assert recs[0]["component_id"] == "comp-x"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
