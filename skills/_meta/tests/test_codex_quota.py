#!/usr/bin/env python3
"""Tests for codex_quota.py — the codex rate-limit meter and the per-cycle astra budget.

Design §4.7 (D4), §2.4, §11 Quota; plan interpretations I8 (cycle_id from files) and
I10 (a CLI, and a row for BOTH admitted and refused decisions). Amendment 1 D7 and the
revision-2b lead decision J3 (J3a, J3b, J4): the budget key is a fresh per-cycle
`.forge/cycle-id` (written at forge Step 1, deleted at forge close-out, ignored after
24h); `.forge/session-id` is never read. Amendment 1 D6 (revision 2b WP-F01; J6-J9, J3
on rows): `unavailable()`, the Claude `fallback` on admit decisions, the call-time
failure classifier and substitution rows — the astra trial is skipped, never substituted.

ISOLATION. Every test runs under a fixture HOME (autouse `fixture_home`), so the
default `~/.codex/sessions` and `~/.claude/projects/<slug>/astra-budget.jsonl` paths
resolve inside tmp. The first test proves the redirect is active, so the isolation is
demonstrated rather than assumed. No test reads the live `~/.codex` or writes the live
`~/.claude/projects` tree. Rollouts are fixtures written in the LIVE shape observed on
2026-09-14: `payload.rate_limits{limit_id, primary{used_percent, window_minutes,
resets_at}, secondary{...}, plan_type, rate_limit_reached_type}`, including the
`limit_id: "premium"` entry with `primary: null` that closes a real session.
"""
import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_META = _HERE.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import codex_quota as cq  # type: ignore  # noqa: E402

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import skill_corpus  # type: ignore  # noqa: E402  (beside this file; reads THIS tree's skills by path)


def _codex_orchestration_docs():
    """(entry, whole), whitespace-collapsed. `entry` is SKILL.md, where "Seat Models" lives and where a
    PRESENT assertion pins it. `whole` is SKILL.md plus references/*.md plus the two reference files beside
    SKILL.md (patterns.md, templates.md): an ABSENT assertion reads it, because since the #344 split a
    retired sentence could come back in a file the entry-only reader never opens."""
    root = _META.parent
    entry = " ".join(skill_corpus.read("codex-orchestration", root=root).split())
    whole = " ".join(skill_corpus.corpus("codex-orchestration", root=root, root_level=True).split())
    return entry, whole

_REAL_HOME = Path.home()
_MODULE_PATH = _META / "codex_quota.py"

#: 2026-09-14T15:33:20Z. A fixed clock keeps every age and reset comparison exact.
NOW = 1789400000.0
HOUR = 3600.0
#: RE-POINTED by S081 revision 4 WP-A3 (design §2.2 budget-row schema, §2.1 "every row"):
#: `key` (the design's name for the budget key; `cycle_id` is RETAINED beside it so the live
#: stores' existing rows keep parsing), and `size` / `size_source` / `model_class` /
#: `requested_model`, which every row now carries unconditionally.
ROW_KEYS = {"at", "key", "cycle_id", "use", "size", "size_source", "requested_model",
            "model_class", "admitted", "reason", "snapshot_state", "primary", "weekly"}
#: Added by D7 / J3 whenever admit() is given a project_root (the existing keys are unchanged).
CYCLE_SOURCE_KEYS = {"cycle_id_source", "cycle_id_file_age_s"}
#: #282 r10 (K12): every admit row, admitted OR refused, carries its admission id.
ADMISSION_ID_KEYS = {"admission_id"}


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def fixture_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


@pytest.fixture()
def sessions(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    return root


@pytest.fixture()
def project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    return root


def iso(epoch):
    dt = datetime.fromtimestamp(epoch, timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def rl_event(observed, primary, weekly, *, p_resets=None, w_resets=None, limit_id="codex",
             timestamp=True, reached_type=None):
    """One token_count event in the live rollout shape. `reached_type` sets
    rate_limit_reached_type (null in every live rollout observed so far, J6)."""
    rate_limits = {
        "limit_id": limit_id,
        "limit_name": None,
        "primary": None if primary is None else {
            "used_percent": primary,
            "window_minutes": 300,
            "resets_at": int(observed + 2 * HOUR) if p_resets is None else p_resets,
        },
        "secondary": None if weekly is None else {
            "used_percent": weekly,
            "window_minutes": 10080,
            "resets_at": int(observed + 72 * HOUR) if w_resets is None else w_resets,
        },
        "credits": {"has_credits": False, "unlimited": False, "balance": "0"},
        "individual_limit": None,
        "plan_type": "plus",
        "rate_limit_reached_type": reached_type,
    }
    event = {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {"total_token_usage": {"input_tokens": 1000, "output_tokens": 10}},
            "rate_limits": rate_limits,
        },
    }
    if timestamp:
        event["timestamp"] = iso(observed)
    return event


def premium_null(observed, reached_type=None):
    return rl_event(observed, None, None, limit_id="premium", reached_type=reached_type)


def other_line(observed, text="hello"):
    return {"timestamp": iso(observed), "type": "response_item",
            "payload": {"type": "message", "content": text}}


def write_rollout(sessions_root, day, name, events, *, raw_suffix=b""):
    d = sessions_root / day
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    body = b"".join(json.dumps(e).encode("utf-8") + b"\n" for e in events) + raw_suffix
    path.write_bytes(body)
    return path


def fresh_rollout(sessions_root, primary, weekly, *, age=60.0, day="2026/09/14",
                  name="rollout-2026-09-14T15-00-00-aaaa.jsonl", **kw):
    observed = NOW - age
    return write_rollout(sessions_root, day, name, [
        other_line(observed - 5),
        rl_event(observed, primary, weekly, **kw),
        premium_null(observed + 0.2),
    ])


def set_mtime(path, epoch):
    """Pin a rollout's mtime (#282 R6 ranks candidates by it)."""
    os.utime(path, (epoch, epoch))
    return path


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def budget(tmp_path):
    return tmp_path / "budget" / "astra-budget.jsonl"


# --------------------------------------------------------------------------- #
# Isolation
# --------------------------------------------------------------------------- #
def test_fixture_home_isolation_is_active(fixture_home, project):
    assert Path.home() == fixture_home
    assert Path.home() != _REAL_HOME
    assert cq.default_sessions_dir() == fixture_home / ".codex" / "sessions"
    expected = fixture_home / ".claude" / "projects" / cq.project_slug(project) / "astra-budget.jsonl"
    assert cq.budget_path_for(project) == expected


def test_module_imports_no_network_or_process_modules():
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"socket", "subprocess", "urllib", "http", "requests", "httpx", "fcntl"})
    assert "portable_lock" in imported


# --------------------------------------------------------------------------- #
# #282 fix round 2 G7a (plan K59a): the `_scan_rollout` 3-tuple caller contract
#
# F6 widened `_scan_rollout` from 2 values to 3 (the read-failed flag). A caller left at the
# old two-name unpack would not fail loudly — it would raise ValueError deep inside `_scan`,
# or, worse, a two-name unpack of a 3-tuple simply cannot bind and the meter's uncertainty
# signal would be lost. This is a REGRESSION GUARD, not a defect closure: both production
# call sites were verified correct when it was written (`_scan_rollout(path)[0]` and a
# 3-name unpack). It exists so a future edit cannot quietly reintroduce the stale shape.
# --------------------------------------------------------------------------- #
SCAN_ROLLOUT = "_scan_rollout"


def _scan_rollout_call_sites(source):
    """-> [(lineno, verdict)] for every `_scan_rollout(...)` CALL in `source`. Pure.

    verdict is "index" (subscripted, e.g. `[0]`), "unpack-N" (assigned to an N-name tuple),
    or "other" (anything the contract does not sanction — a bare call, a single-name bind,
    a call passed straight into something else).
    """
    tree = ast.parse(source)
    classified = {}
    for node in ast.walk(tree):
        call = None
        verdict = None
        if isinstance(node, ast.Subscript) and _is_scan_call(node.value):
            call, verdict = node.value, "index"
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and _is_scan_call(node.value):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if len(targets) == 1 and isinstance(targets[0], (ast.Tuple, ast.List)):
                call, verdict = node.value, "unpack-%d" % len(targets[0].elts)
        if call is not None:
            classified[id(call)] = verdict
    return sorted((node.lineno, classified.get(id(node), "other"))
                  for node in ast.walk(tree) if _is_scan_call(node))


def _is_scan_call(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == SCAN_ROLLOUT)


def test_fr2_g7a_scan_rollout_returns_exactly_three_values():
    """The contract the guard below enforces, read from the definition itself."""
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    defs = [n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == SCAN_ROLLOUT]
    assert len(defs) == 1
    returns = defs[0].returns
    # `-> Tuple[Optional[Dict[str, Any]], _LimitStates, bool]`
    assert isinstance(returns, ast.Subscript) and returns.value.id == "Tuple"
    assert len(returns.slice.elts) == 3
    # And every `return` in the body is a 3-element tuple.
    bodies = [n.value for n in ast.walk(defs[0]) if isinstance(n, ast.Return)]
    assert bodies and all(isinstance(r, ast.Tuple) and len(r.elts) == 3 for r in bodies)


def test_fr2_g7a_no_caller_unpacks_scan_rollout_with_the_stale_two_value_shape():
    """G7a: every `_scan_rollout(` call site indexes or unpacks THREE names."""
    sites = _scan_rollout_call_sites(_MODULE_PATH.read_text(encoding="utf-8"))
    assert sites, "the guard found no call site at all — it would pass vacuously"
    bad = [s for s in sites if s[1] not in ("index", "unpack-3")]
    assert bad == [], "stale `_scan_rollout` call site(s): %r" % (bad,)


def test_fr2_g7a_the_caller_guard_catches_a_two_value_unpack_negative_control():
    """NEGATIVE CONTROL: the guard must FAIL on a source that has the stale shape.

    Without this, a guard that silently classified everything as fine would still pass.
    """
    mutated = textwrap.dedent(
        """
        def _scan_rollout(path):
            return None, {}, True

        def caller_ok_index(path):
            return _scan_rollout(path)[0]

        def caller_ok_three(path):
            reading, limits, read_failed = _scan_rollout(path)
            return reading, limits, read_failed

        def caller_stale(path):
            reading, limits = _scan_rollout(path)      # the stale F6 shape
            return reading, limits

        def caller_bare(path):
            _scan_rollout(path)
        """
    )
    verdicts = dict((lineno, v) for lineno, v in _scan_rollout_call_sites(mutated))
    assert sorted(verdicts.values()) == ["index", "other", "unpack-2", "unpack-3"]
    bad = [v for v in verdicts.values() if v not in ("index", "unpack-3")]
    assert sorted(bad) == ["other", "unpack-2"]

    # CONTROL: the same fixture WITHOUT the two stale call sites passes the guard, so the
    # failure above is caused by the stale shapes and not by the fixture being unparseable.
    clean = textwrap.dedent(
        """
        def _scan_rollout(path):
            return None, {}, True

        def caller_ok_index(path):
            return _scan_rollout(path)[0]

        def caller_ok_three(path):
            reading, limits, read_failed = _scan_rollout(path)
            return reading, limits, read_failed
        """
    )
    clean_verdicts = [v for _lineno, v in _scan_rollout_call_sites(clean)]
    assert sorted(clean_verdicts) == ["index", "unpack-3"]
    assert [v for v in clean_verdicts if v not in ("index", "unpack-3")] == []


def test_fr2_g7a_the_two_production_call_sites_are_the_ones_the_finding_named():
    """The guard's subject, pinned: an index read and a 3-name unpack, nothing else."""
    sites = _scan_rollout_call_sites(_MODULE_PATH.read_text(encoding="utf-8"))
    assert [v for _lineno, v in sites] == ["index", "unpack-3"]


# --------------------------------------------------------------------------- #
# snapshot()
# --------------------------------------------------------------------------- #
SNAPSHOT_KEYS = {"state", "primary_used_percent", "primary_resets_at", "secondary_used_percent",
                 "secondary_resets_at", "observed_at", "source"}


def test_snapshot_fresh_reads_the_live_shape_and_skips_the_null_premium_entry(sessions):
    path = fresh_rollout(sessions, 10.0, 3.0, age=60.0)
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert SNAPSHOT_KEYS <= set(snap)
    assert snap["state"] == "fresh"
    assert snap["primary_used_percent"] == 10.0
    assert snap["secondary_used_percent"] == 3.0
    assert snap["primary_resets_at"] == int(NOW - 60 + 2 * HOUR)
    assert snap["secondary_resets_at"] == int(NOW - 60 + 72 * HOUR)
    assert snap["observed_at"] == datetime.fromtimestamp(NOW - 60, timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    assert snap["source"] == str(path)
    assert snap["limit_id"] == "codex"


def test_snapshot_only_a_null_primary_entry_is_unknown(sessions):
    write_rollout(sessions, "2026/09/14", "rollout-a.jsonl", [premium_null(NOW - 30)])
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert snap["state"] == "unknown"
    assert snap["primary_used_percent"] is None


def test_snapshot_last_usable_entry_in_the_file_wins(sessions):
    write_rollout(sessions, "2026/09/14", "rollout-a.jsonl", [
        rl_event(NOW - 300, 20.0, 4.0),
        rl_event(NOW - 120, 26.0, 5.0),
        premium_null(NOW - 119),
    ])
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert (snap["state"], snap["primary_used_percent"], snap["secondary_used_percent"]) == (
        "fresh", 26.0, 5.0)


def test_snapshot_exactly_thirty_minutes_old_is_fresh(sessions):
    fresh_rollout(sessions, 10.0, 3.0, age=1800.0)
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["state"] == "fresh"


def test_snapshot_forty_minutes_old_is_stale_but_keeps_its_readings(sessions):
    fresh_rollout(sessions, 95.0, 3.0, age=2400.0)
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert snap["state"] == "stale"
    assert snap["primary_used_percent"] == 95.0


def test_snapshot_past_primary_resets_at_is_not_fresh(sessions):
    fresh_rollout(sessions, 10.0, 3.0, age=60.0, p_resets=int(NOW - 1))
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["state"] == "stale"


def test_snapshot_at_primary_resets_at_is_not_fresh(sessions):
    fresh_rollout(sessions, 10.0, 3.0, age=60.0, p_resets=int(NOW))
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["state"] == "stale"


def test_snapshot_past_weekly_resets_at_is_not_fresh(sessions):
    fresh_rollout(sessions, 10.0, 3.0, age=60.0, w_resets=int(NOW - 1))
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["state"] == "stale"


def test_snapshot_without_a_weekly_window_can_still_be_fresh(sessions):
    fresh_rollout(sessions, 10.0, None, age=60.0)
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert snap["state"] == "fresh"
    assert snap["secondary_used_percent"] is None and snap["secondary_resets_at"] is None


def test_snapshot_missing_resets_at_is_not_fresh(sessions):
    event = rl_event(NOW - 60, 10.0, 3.0)
    del event["payload"]["rate_limits"]["primary"]["resets_at"]
    write_rollout(sessions, "2026/09/14", "rollout-a.jsonl", [event])
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert snap["state"] == "stale"
    assert snap["primary_used_percent"] == 10.0


def test_snapshot_missing_timestamp_is_stale(sessions):
    write_rollout(sessions, "2026/09/14", "rollout-a.jsonl",
                  [rl_event(NOW - 60, 10.0, 3.0, timestamp=False)])
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert snap["state"] == "stale"
    assert snap["observed_at"] is None


def test_snapshot_far_future_timestamp_is_stale(sessions):
    fresh_rollout(sessions, 10.0, 3.0, age=-(cq.FUTURE_SKEW_S + 60))
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["state"] == "stale"


def test_snapshot_small_clock_skew_is_tolerated(sessions):
    fresh_rollout(sessions, 10.0, 3.0, age=-30.0)
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["state"] == "fresh"


@pytest.mark.parametrize("body", [
    b"\x00\xff\xfe garbage \x80\n",
    b'{"type": "event_msg", "payload": {"rate_limits": {"primary": {"used_pe\n',
    b'{"payload": {"rate_limits": "not-a-dict"}}\n',
    b'{"payload": {"rate_limits": {"primary": "ten percent"}}}\n',
    b'{"payload": {"rate_limits": {"primary": {"used_percent": true, "resets_at": 1}}}}\n',
    b'{"payload": {"rate_limits": {"primary": {"used_percent": NaN, "resets_at": 1}}}}\n',
    b'{"payload": {"rate_limits": {"primary": {"used_percent": -5, "resets_at": 1}}}}\n',
    b'["rate_limits"]\n',
    b'{"payload": ["rate_limits"]}\n',
    b"",
])
def test_snapshot_corrupt_rollout_is_unknown_without_raising(sessions, body):
    d = sessions / "2026" / "09" / "14"
    d.mkdir(parents=True)
    (d / "rollout-corrupt.jsonl").write_bytes(body)
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert snap["state"] == "unknown"
    assert snap["primary_used_percent"] is None


def test_snapshot_missing_sessions_dir_is_unknown(tmp_path):
    snap = cq.snapshot(sessions_dir=tmp_path / "does-not-exist", now=NOW)
    assert snap["state"] == "unknown" and snap["source"] is None


def test_snapshot_sessions_dir_that_is_a_file_is_unknown(tmp_path):
    f = tmp_path / "sessions"
    f.write_text("not a directory", encoding="utf-8")
    assert cq.snapshot(sessions_dir=f, now=NOW)["state"] == "unknown"


def test_snapshot_day_dir_without_rollouts_is_unknown(sessions):
    d = sessions / "2026" / "09" / "14"
    d.mkdir(parents=True)
    (d / "notes.jsonl").write_text(json.dumps(rl_event(NOW - 60, 10.0, 3.0)) + "\n", encoding="utf-8")
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["state"] == "unknown"


def test_snapshot_default_sessions_dir_is_read_at_call_time(fixture_home):
    fresh_rollout(fixture_home / ".codex" / "sessions", 12.0, 3.0)
    snap = cq.snapshot(now=NOW)
    assert (snap["state"], snap["primary_used_percent"]) == ("fresh", 12.0)


def test_snapshot_bad_now_never_raises(sessions):
    fresh_rollout(sessions, 10.0, 3.0)
    snap = cq.snapshot(sessions_dir=sessions, now="yesterday")
    assert snap["state"] == "unknown"


def test_snapshot_accepts_an_aware_datetime_for_now(sessions):
    fresh_rollout(sessions, 10.0, 3.0, age=60.0)
    snap = cq.snapshot(sessions_dir=sessions, now=datetime.fromtimestamp(NOW, timezone.utc))
    assert snap["state"] == "fresh"


def test_snapshot_newest_observation_wins_over_the_newest_file_name(sessions):
    """Concurrent codex sessions interleave: on 2026-09-14 a rollout named 14-09-12
    carried a later rate_limits event than one named 14-11-28."""
    write_rollout(sessions, "2026/09/14", "rollout-2026-09-14T14-11-28-b.jsonl",
                  [rl_event(NOW - 200, 50.0, 10.0)])
    write_rollout(sessions, "2026/09/14", "rollout-2026-09-14T14-09-12-a.jsonl",
                  [rl_event(NOW - 100, 97.0, 15.0)])
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert snap["primary_used_percent"] == 97.0
    assert snap["source"].endswith("rollout-2026-09-14T14-09-12-a.jsonl")


def test_snapshot_newest_file_without_rate_limits_falls_back_to_the_previous_one(sessions):
    write_rollout(sessions, "2026/09/14", "rollout-2026-09-14T15-00-00-new.jsonl",
                  [other_line(NOW - 10)])
    write_rollout(sessions, "2026/09/14", "rollout-2026-09-14T14-00-00-old.jsonl",
                  [rl_event(NOW - 90, 33.0, 6.0)])
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert (snap["state"], snap["primary_used_percent"]) == ("fresh", 33.0)


def test_snapshot_walk_is_bounded_to_the_three_newest_day_dirs(sessions):
    """RE-POINTED (#282 R6): the bound is the ROLLOUT_WINDOW_DAYS date window, no longer the
    three newest directories. Three in-window directories without a reading and a reading in
    a directory ten days old, across a month boundary: the old one is outside the window."""
    for day in ("2026/09/14", "2026/09/13", "2026/09/12"):
        write_rollout(sessions, day, "rollout-x.jsonl", [other_line(NOW - 50)])
    write_rollout(sessions, "2026/09/04", "rollout-x.jsonl", [rl_event(NOW - 60, 10.0, 3.0)])
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["state"] == "unknown"


def test_snapshot_walk_reaches_the_third_newest_day_dir_across_a_year_boundary(sessions):
    """CONTROL for the bound above, RE-POINTED (#282 R6): with `now` on 2027-01-02 the window
    starts 2026-12-25, so 2026/12/31 IS read across the year boundary and 2026/12/24 is not."""
    now = datetime(2027, 1, 2, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    for day in ("2027/01/02", "2027/01/01"):
        write_rollout(sessions, day, "rollout-x.jsonl", [other_line(now - 50)])
    write_rollout(sessions, "2026/12/31", "rollout-x.jsonl", [rl_event(now - 60, 10.0, 3.0)])
    snap = cq.snapshot(sessions_dir=sessions, now=now)
    assert (snap["state"], snap["primary_used_percent"]) == ("fresh", 10.0)
    for day in ("2027/01/02", "2027/01/01", "2026/12/31"):
        shutil.rmtree(sessions / day)
    write_rollout(sessions, "2026/12/24", "rollout-x.jsonl", [rl_event(now - 60, 10.0, 3.0)])
    assert cq.snapshot(sessions_dir=sessions, now=now)["state"] == "unknown"


def test_snapshot_walk_ignores_non_date_directories(sessions):
    (sessions / "archive" / "99" / "99").mkdir(parents=True)
    write_rollout(sessions, "archive/99/99", "rollout-z.jsonl", [rl_event(NOW - 60, 99.0, 3.0)])
    write_rollout(sessions, "2026/09/14", "rollout-a.jsonl", [rl_event(NOW - 60, 11.0, 3.0)])
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["primary_used_percent"] == 11.0


def test_322_fr1_reading_less_rollouts_do_not_spend_the_file_limit(sessions):
    """#322 fix round 1 (F1). Was test_snapshot_reads_at_most_the_newest_rollout_file_limit, which pinned
    the blinding: ROLLOUT_FILE_LIMIT newer rollouts WITHOUT a reading hid the older reading (-> unknown).
    A rollout with no usable reading no longer spends a slot, so the reading behind them is found.
    Explicit mtimes (#282 R6 ranks by mtime): the reading sits in the file with the OLDEST mtime,
    deliberately given the NEWEST name, so a name-ranked walk would have read it."""
    n = cq.ROLLOUT_FILE_LIMIT
    old = write_rollout(sessions, "2026/09/14", "rollout-99-old-mtime.jsonl", [rl_event(NOW - 60, 10.0, 3.0)])
    set_mtime(old, NOW - 55)
    for i in range(1, n + 1):
        set_mtime(write_rollout(sessions, "2026/09/14", f"rollout-{i:02d}.jsonl", [other_line(NOW - 50)]),
                  NOW - 50 + i)
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert (snap["state"], snap["primary_used_percent"]) == ("fresh", 10.0)


def test_322_fr1_the_reading_less_reads_are_bounded(sessions):
    """The walk's I/O stays bounded: ROLLOUT_FILE_LIMIT + ROLLOUT_EMPTY_READ_LIMIT reading-less rollouts end
    it, and the reading behind them is unread. RE-POINTED by #322 fix round 2 (N3): that is `uncertain`
    (newer_candidate_unread), no longer `unknown` -- the unread reading may be an exhausted one."""
    n = cq.ROLLOUT_FILE_LIMIT + cq.ROLLOUT_EMPTY_READ_LIMIT
    old = write_rollout(sessions, "2026/09/14", "rollout-99-old-mtime.jsonl", [rl_event(NOW - 60, 10.0, 3.0)])
    set_mtime(old, NOW - 55)
    for i in range(1, n + 1):
        set_mtime(write_rollout(sessions, "2026/09/14", f"rollout-{i:02d}.jsonl", [other_line(NOW - 50)]),
                  NOW - 50 + i / 100)
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert (snap["state"], snap["reason"]) == ("uncertain", "newer_candidate_unread")


def test_322_fr1_four_usable_readings_still_end_the_walk(sessions):
    """CONTROL: the usable-reading bound itself is unchanged -- ROLLOUT_FILE_LIMIT newer rollouts WITH a
    reading end the walk, and the chosen reading is the newest of them."""
    n = cq.ROLLOUT_FILE_LIMIT
    old = write_rollout(sessions, "2026/09/14", "rollout-99-old-mtime.jsonl", [rl_event(NOW - 60, 99.9, 3.0)])
    set_mtime(old, NOW - 55)
    for i in range(1, n + 1):
        set_mtime(write_rollout(sessions, "2026/09/14", f"rollout-{i:02d}.jsonl",
                                [rl_event(NOW - 50 + i, 10.0 + i, 3.0)]), NOW - 50 + i)
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["primary_used_percent"] == 10.0 + n


def test_snapshot_reads_the_last_file_within_the_limit(sessions):
    """CONTROL for the file bound: the ROLLOUT_FILE_LIMIT-th newest file BY MTIME IS read."""
    n = cq.ROLLOUT_FILE_LIMIT
    old = write_rollout(sessions, "2026/09/14", "rollout-99-old-mtime.jsonl", [rl_event(NOW - 60, 10.0, 3.0)])
    set_mtime(old, NOW - 55)
    for i in range(1, n):
        set_mtime(write_rollout(sessions, "2026/09/14", f"rollout-{i:02d}.jsonl", [other_line(NOW - 50)]),
                  NOW - 50 + i)
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["primary_used_percent"] == 10.0


def test_snapshot_tail_read_is_bounded(sessions, monkeypatch):
    monkeypatch.setattr(cq, "TAIL_BYTES", 4096)
    padding = [other_line(NOW - 50, "x" * 200) for _ in range(40)]  # > 4096 bytes
    write_rollout(sessions, "2026/09/14", "rollout-a.jsonl",
                  [rl_event(NOW - 60, 10.0, 3.0)] + padding)
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["state"] == "unknown"


def test_snapshot_tail_read_finds_a_reading_inside_the_bound(sessions, monkeypatch):
    """CONTROL for the tail bound; the partial first line of the tail is discarded."""
    monkeypatch.setattr(cq, "TAIL_BYTES", 4096)
    padding = [other_line(NOW - 70, "x" * 200) for _ in range(40)]
    write_rollout(sessions, "2026/09/14", "rollout-a.jsonl",
                  padding + [rl_event(NOW - 60, 10.0, 3.0)] + padding[:3])
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert (snap["state"], snap["primary_used_percent"]) == ("fresh", 10.0)


def test_snapshot_never_parses_a_torn_first_line_of_the_tail(sessions, monkeypatch):
    """The tail may begin mid-line. That fragment is discarded even when it happens to
    be valid JSON on its own: read whole, the line `garbage{...}` is corrupt, so the
    bounded read must not turn it into a reading."""
    monkeypatch.setattr(cq, "TAIL_BYTES", 4096)
    event = rl_event(NOW - 60, 10.0, 3.0)
    event["pad"] = ""
    base_len = len(json.dumps(event).encode("utf-8")) + 1  # + newline
    event["pad"] = "p" * (cq.TAIL_BYTES - base_len)
    line = json.dumps(event).encode("utf-8") + b"\n"
    assert len(line) == cq.TAIL_BYTES
    d = sessions / "2026" / "09" / "14"
    d.mkdir(parents=True)
    (d / "rollout-torn.jsonl").write_bytes(b"garbage-prefix-without-newline" + line)
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["state"] == "unknown"


def test_snapshot_tolerates_a_partially_written_last_line(sessions):
    write_rollout(sessions, "2026/09/14", "rollout-a.jsonl", [rl_event(NOW - 60, 10.0, 3.0)],
                  raw_suffix=b'{"timestamp": "2026-09-14T15:33:00.000Z", "payload": {"rate_li')
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["primary_used_percent"] == 10.0


# --------------------------------------------------------------------------- #
# admit() — thresholds
# --------------------------------------------------------------------------- #
def _admit(use, cycle, sessions, tmp_path, **kw):
    kw.setdefault("project_root", tmp_path / "proj")
    kw.setdefault("budget_path", budget(tmp_path))
    return cq.admit(use, cycle, now=NOW, sessions_dir=sessions, **kw)


def test_admit_fresh_ten_percent_consult_is_admitted(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    d = _admit("consult", "c1", sessions, tmp_path)
    assert d["admitted"] is True
    assert d["snapshot_state"] == "fresh"
    assert d["row_written"] is True
    rows = read_rows(budget(tmp_path))
    assert len(rows) == 1 and rows[0]["admitted"] is True and rows[0]["use"] == "consult"


# #322 (2026-09-27): THE 70% THRESHOLD NO LONGER REFUSES. The four tests that pinned it are INVERTED
# and renamed here (was: test_admit_fresh_high_primary_refuses_budgeted_uses,
# test_admit_threshold_is_inclusive_at_seventy, test_admit_fresh_high_weekly_refuses_consult,
# test_admit_stale_snapshot_is_a_lower_bound_while_its_windows_have_not_reset). The CONTROL that proves
# they can still see a refusal is the >= 99% reading, which refuses `quota_exhausted` with its reset time.
@pytest.mark.parametrize("use", ["consult", "challenger", "advisory_review", "diagnosis"])
@pytest.mark.parametrize("primary", [72.0, 94.0, 98.9])
def test_322_a_fresh_high_primary_below_exhaustion_is_admitted(sessions, tmp_path, use, primary):
    """DW-1: 94% (the reading that put three Opus stand-ins in the Proxmox review seats) admits."""
    fresh_rollout(sessions, primary, 3.0)
    d = _admit(use, "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"]) == (True, "within_budget")
    assert "wait_advice" not in d and "unavailable" not in d
    rows = read_rows(budget(tmp_path))
    assert len(rows) == 1 and rows[0]["admitted"] is True


def test_322_the_old_threshold_boundary_admits_and_nothing_produces_the_token(sessions, tmp_path):
    fresh_rollout(sessions, 70.0, 70.0)
    d = _admit("consult", "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"]) == (True, "within_budget")
    # The token is KEPT so old rows parse: it is still a substitution reason and a skip reason.
    assert "threshold" in cq.SUBSTITUTION_REASONS and cq.REASON_THRESHOLD in cq.SKIP_REASONS
    assert cq.THRESHOLD_PERCENT == 70.0


@pytest.mark.parametrize("primary,weekly,window", [(99.0, 3.0, "primary"), (10.0, 99.0, "secondary"),
                                                    (99.5, 99.5, "secondary")])
def test_322_a_fresh_exhausted_reading_refuses_with_its_reset_time(sessions, tmp_path, primary, weekly, window):
    """DW-1: at 99% or more (fresh) the refusal names the binding window, when it resets and the advice.
    Both windows exhausted: the one that resets LATER binds (the weekly one here)."""
    fresh_rollout(sessions, primary, weekly)
    d = _admit("consult", "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"], d["unavailable"]) == (False, "quota_exhausted", "quota_exhausted")
    observed = NOW - 60.0
    resets = int(observed + 2 * HOUR) if window == "primary" else int(observed + 72 * HOUR)
    assert (d["binding_window"], d["resets_at"], d["resets_in_s"]) == (window, resets, resets - int(NOW))
    assert d["wait_advice"] == "notify"


def test_322_a_near_reset_advises_wait(sessions, tmp_path):
    fresh_rollout(sessions, 99.0, 3.0, p_resets=int(NOW + 600))
    d = _admit("consult", "c1", sessions, tmp_path)
    assert (d["binding_window"], d["resets_in_s"], d["wait_advice"]) == ("primary", 600, "wait")


@pytest.mark.parametrize("seconds,advice", [(1, "wait"), (1199, "wait"), (1200, "wait"), (1201, "notify")])
def test_322_the_wait_advice_boundary_is_1200_seconds_inclusive(sessions, tmp_path, seconds, advice):
    """DW-2: exactly 1200 s away is `wait`, 1201 s is `notify`."""
    fresh_rollout(sessions, 99.0, 3.0, p_resets=int(NOW + seconds))
    d = _admit("consult", "c1", sessions, tmp_path)
    assert (d["resets_in_s"], d["wait_advice"]) == (seconds, advice)
    assert cq.wait_advice_for(seconds) == advice


def test_322_an_unknown_reset_time_advises_notify():
    assert cq.wait_advice_for(None) == "notify"


def test_322_a_rate_limit_reached_refusal_names_the_window_its_type_names(sessions, tmp_path):
    closing_rollout(sessions, 40.0, 10.0, reached_type="secondary")
    d = _admit("consult", "c1", sessions, tmp_path)
    assert (d["reason"], d["binding_window"], d["wait_advice"]) == ("rate_limit_reached", "secondary", "notify")
    # The closing `premium` entry that set the type carries no reset time: unknown, so `notify`.
    assert (d["resets_at"], d["resets_in_s"]) == (None, None)


def test_322_a_stale_reading_at_or_over_99_is_admitted(sessions, tmp_path):
    """DW-1: only a FRESH reading can refuse for quota. INVERTED from #282 r9's lower-bound rule, which
    refused a stale-by-age reading whose window had not reset: a call that hits the wall now is
    classify_codex_failure()'s business. The trial still needs fresh."""
    fresh_rollout(sessions, 99.5, 99.5, age=2400.0)  # 40 minutes old; resets in the future
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["reason"] == "observed_too_long_ago"
    d = _admit("consult", "c1", sessions, tmp_path)
    assert (d["snapshot_state"], d["admitted"], d["reason"]) == ("stale", True, "within_budget")
    t = _admit("trial", "c1", sessions, tmp_path)
    assert (t["admitted"], t["reason"]) == (False, "trial_requires_fresh_snapshot")


def test_322_an_uncertain_reading_at_or_over_99_is_admitted(pre_fr1_walk, sessions, tmp_path):
    """DW-1: an UNCERTAIN scan (a newer candidate unread) never refuses for quota (#282 F5)."""
    for i in range(3):
        blank_rollout(sessions, TODAY, f"rollout-blank-{i}.jsonl", mtime=NOW - 10 - i)
    reading_rollout(sessions, TODAY, "rollout-chosen.jsonl", 99.5, weekly=99.5,
                    observed=NOW - 2400, mtime=NOW - 20)
    blank_rollout(sessions, TODAY, "rollout-unread.jsonl", mtime=NOW - 100)
    assert _snap(sessions)["state"] == "uncertain"
    d = _admit("consult", "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"]) == (True, "within_budget")
    assert "wait_advice" not in d


def test_admit_unknown_snapshot_admits_consult_and_refuses_trial(tmp_path):
    empty = tmp_path / "no-sessions"
    d = cq.admit("consult", "c1", project_root=tmp_path, now=NOW, sessions_dir=empty,
                 budget_path=budget(tmp_path))
    assert (d["snapshot_state"], d["admitted"]) == ("unknown", True)
    t = cq.admit("trial", "c1", project_root=tmp_path, now=NOW, sessions_dir=empty,
                 budget_path=budget(tmp_path))
    assert t["admitted"] is False


@pytest.mark.parametrize("primary,weekly,admitted", [
    (30.0, 30.0, True),
    (45.0, 30.0, False),
    (30.0, 45.0, False),
    (40.0, 30.0, False),
    (30.0, 40.0, False),
    (39.9, 39.9, True),
])
def test_admit_trial_needs_fresh_and_both_below_forty(sessions, tmp_path, primary, weekly, admitted):
    fresh_rollout(sessions, primary, weekly)
    d = _admit("trial", "c1", sessions, tmp_path)
    assert d["admitted"] is admitted
    if not admitted:
        assert d["reason"] == "trial_threshold"


def test_admit_trial_refused_when_the_weekly_window_is_unobserved(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, None)
    d = _admit("trial", "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"]) == (False, "trial_threshold")


def test_admit_trial_has_no_per_cycle_budget(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 10.0)
    assert all(_admit("trial", "c1", sessions, tmp_path)["admitted"] for _ in range(3))


# --------------------------------------------------------------------------- #
# admit() — audit and budgets
# --------------------------------------------------------------------------- #
def test_admit_audit_is_admitted_at_ninety_five_percent_and_after_the_budget_is_spent(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    assert _admit("consult", "c1", sessions, tmp_path)["admitted"] is True
    assert _admit("consult", "c1", sessions, tmp_path)["admitted"] is False  # budget spent
    fresh_rollout(sessions, 95.0, 95.0, name="rollout-2026-09-14T15-10-00-zzzz.jsonl", age=10.0)
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["primary_used_percent"] == 95.0
    for _ in range(3):
        d = _admit("audit", "c1", sessions, tmp_path)
        assert (d["admitted"], d["reason"], d["snapshot_state"]) == (True, "audit_exempt", "fresh")
    rows = read_rows(budget(tmp_path))
    assert [r["use"] for r in rows] == ["consult", "consult", "audit", "audit", "audit"]
    assert all(r["admitted"] for r in rows if r["use"] == "audit")


def test_admit_second_consult_in_the_same_cycle_is_refused(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    assert _admit("consult", "cycle-a", sessions, tmp_path)["admitted"] is True
    second = _admit("consult", "cycle-a", sessions, tmp_path)
    assert (second["admitted"], second["reason"]) == (False, "budget_spent")
    assert second["budget_used"] == 1 and second["budget_limit"] == 1
    # CONTROL: a different cycle has its own budget.
    assert _admit("consult", "cycle-b", sessions, tmp_path)["admitted"] is True


def test_admit_budgets_are_independent_per_use(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    for use in ("consult", "challenger", "advisory_review"):
        assert _admit(use, "c1", sessions, tmp_path)["admitted"] is True
    for use in ("consult", "challenger", "advisory_review"):
        assert _admit(use, "c1", sessions, tmp_path)["reason"] == "budget_spent"


def test_admit_diagnosis_budget_is_per_task_key(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    assert _admit("diagnosis", "c1", sessions, tmp_path, task_key="WP-1")["admitted"] is True
    assert _admit("diagnosis", "c1", sessions, tmp_path, task_key="WP-1")["admitted"] is False
    assert _admit("diagnosis", "c1", sessions, tmp_path, task_key="WP-2")["admitted"] is True
    rows = read_rows(budget(tmp_path))
    assert [r.get("task_key") for r in rows] == ["WP-1", "WP-1", "WP-2"]


def test_admit_diagnosis_without_task_key_is_per_cycle(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    assert _admit("diagnosis", "c1", sessions, tmp_path)["admitted"] is True
    assert _admit("diagnosis", "c1", sessions, tmp_path)["admitted"] is False
    # A keyed diagnosis in the same cycle is a different budget.
    assert _admit("diagnosis", "c1", sessions, tmp_path, task_key="WP-9")["admitted"] is True
    assert "task_key" not in read_rows(budget(tmp_path))[0]


def test_admit_a_refusal_does_not_spend_the_budget(sessions, tmp_path):
    fresh_rollout(sessions, 99.5, 3.0)  # RE-POINTED by #322: the threshold no longer refuses, so the refusal on its merits is a quota one.
    assert _admit("consult", "c1", sessions, tmp_path)["reason"] == "quota_exhausted"
    fresh_rollout(sessions, 12.0, 3.0, name="rollout-2026-09-14T15-20-00-later.jsonl", age=5.0)
    assert _admit("consult", "c1", sessions, tmp_path)["admitted"] is True


def test_admit_writes_rows_for_admitted_and_refused_decisions_with_the_row_schema(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    _admit("consult", "c1", sessions, tmp_path)
    _admit("consult", "c1", sessions, tmp_path)
    rows = read_rows(budget(tmp_path))
    assert [r["admitted"] for r in rows] == [True, False]
    for r in rows:
        # _admit passes a project_root, so the D7 source pair is present; nothing else changed.
        # RE-POINTED by #282 r10 (K12): + admission_id.
        assert set(r) == ROW_KEYS | CYCLE_SOURCE_KEYS | ADMISSION_ID_KEYS
        assert r["cycle_id"] == "c1" and r["snapshot_state"] == "fresh"
        assert r["primary"] == 10.0 and r["weekly"] == 3.0
        assert r["at"] == "2026-09-14T15:33:20Z"


def test_admit_tolerates_malformed_budget_lines(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    path = budget(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('garbage\n[1,2]\n{"cycle_id": "c1", "use": "consult", "admitted": "yes"}\n',
                    encoding="utf-8")
    assert _admit("consult", "c1", sessions, tmp_path)["admitted"] is True
    assert _admit("consult", "c1", sessions, tmp_path)["admitted"] is False


def test_admit_default_budget_path_is_under_the_project_slug(sessions, fixture_home, project):
    fresh_rollout(sessions, 10.0, 3.0)
    d = cq.admit("consult", "c1", project_root=project, now=NOW, sessions_dir=sessions)
    expected = fixture_home / ".claude" / "projects" / cq.project_slug(project) / "astra-budget.jsonl"
    assert d["budget_path"] == str(expected)
    assert len(read_rows(expected)) == 1


@pytest.mark.parametrize("kwargs", [
    {"use": "explore"},
    {"use": "AUDIT"},
    {"cycle_id": ""},
    {"cycle_id": "   "},
    {"cycle_id": None},
    {"use": "consult", "task_key": "WP-1"},
    {"task_key": ""},
    {"now": "noon"},
])
def test_admit_caller_bugs_raise_value_error_and_write_nothing(sessions, tmp_path, kwargs):
    fresh_rollout(sessions, 10.0, 3.0)
    args = {"use": "diagnosis", "cycle_id": "c1"}
    args.update({k: v for k, v in kwargs.items() if k in args})
    extra = {k: v for k, v in kwargs.items() if k not in args}
    extra.setdefault("now", NOW)
    with pytest.raises(ValueError):
        cq.admit(args["use"], args["cycle_id"], project_root=tmp_path, sessions_dir=sessions,
                 budget_path=budget(tmp_path), **extra)
    assert not budget(tmp_path).exists()


# --------------------------------------------------------------------------- #
# admit() — the budget store failing
# --------------------------------------------------------------------------- #
@pytest.fixture()
def broken_budget(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a regular file where a directory is needed", encoding="utf-8")
    return blocker / "astra-budget.jsonl"


def test_store_failure_never_blocks_an_audit(sessions, broken_budget):
    fresh_rollout(sessions, 10.0, 3.0)
    d = cq.admit("audit", "c1", project_root=broken_budget.parent, now=NOW, sessions_dir=sessions,
                 budget_path=broken_budget)
    assert d["admitted"] is True and d["row_written"] is False and d["error"]


@pytest.mark.parametrize("use", ["consult", "challenger", "advisory_review", "diagnosis", "trial"])
def test_store_failure_refuses_discretionary_uses(sessions, broken_budget, use):
    fresh_rollout(sessions, 10.0, 10.0)
    d = cq.admit(use, "c1", project_root=broken_budget.parent, now=NOW, sessions_dir=sessions,
                 budget_path=broken_budget)
    assert (d["admitted"], d["reason"], d["row_written"]) == (False, "budget_store_unavailable", False)
    assert d["error"]


def test_store_failure_keeps_a_quota_refusal_on_its_merits(sessions, broken_budget):
    """RE-POINTED AND RENAMED by #322 (was ..._keeps_a_threshold_refusal_on_its_merits)."""
    fresh_rollout(sessions, 99.5, 10.0)
    d = cq.admit("consult", "c1", project_root=broken_budget.parent, now=NOW, sessions_dir=sessions,
                 budget_path=broken_budget)
    assert (d["admitted"], d["reason"], d["row_written"]) == (False, "quota_exhausted", False)
    assert d["wait_advice"] == "notify"                          # the reset fields survive a broken store


def test_append_failure_revokes_an_admission_but_keeps_budget_spent(sessions, tmp_path, monkeypatch):
    fresh_rollout(sessions, 10.0, 3.0)
    assert _admit("consult", "c1", sessions, tmp_path)["admitted"] is True

    def _refuse_append(path, row):
        raise OSError("disk full")

    monkeypatch.setattr(cq, "_append_row", _refuse_append)
    spent = _admit("consult", "c1", sessions, tmp_path)
    assert (spent["admitted"], spent["reason"], spent["row_written"]) == (False, "budget_spent", False)
    unrecorded = _admit("challenger", "c1", sessions, tmp_path)
    assert (unrecorded["admitted"], unrecorded["reason"]) == (False, "budget_store_unavailable")
    assert "disk full" in unrecorded["error"]
    audit = _admit("audit", "c1", sessions, tmp_path)
    assert (audit["admitted"], audit["row_written"]) == (True, False)


def test_admit_requires_a_project_root_or_a_budget_path(sessions):
    with pytest.raises(ValueError):
        cq.admit("audit", "c1", project_root=None, now=NOW, sessions_dir=sessions)


@pytest.mark.skipif(sys.platform == "win32", reason="same-process flock contention is POSIX")
def test_a_held_lock_times_out_into_store_unavailable(sessions, tmp_path, monkeypatch):
    import portable_lock  # type: ignore

    fresh_rollout(sessions, 10.0, 3.0)
    monkeypatch.setattr(cq, "LOCK_TIMEOUT_S", 0.2)
    path = budget(tmp_path)
    with portable_lock.file_lock(cq.lock_path_for(path)):
        d = _admit("consult", "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"]) == (False, "budget_store_unavailable")
    # CONTROL: released, the same call is admitted.
    assert _admit("consult", "c1", sessions, tmp_path)["admitted"] is True


# --------------------------------------------------------------------------- #
# No socket, no subprocess
# --------------------------------------------------------------------------- #
def test_snapshot_and_admit_open_no_socket_and_spawn_no_process(sessions, tmp_path, project, monkeypatch):
    import socket

    fresh_rollout(sessions, 10.0, 3.0)
    calls = []

    def _boom(*a, **k):
        calls.append(a)
        raise AssertionError("codex_quota must not touch the network or spawn a process")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(cq, "_model_policy_slug_fn", None)
    monkeypatch.setattr(cq, "_model_policy_loaded", False)

    assert cq.snapshot(sessions_dir=sessions, now=NOW)["state"] == "fresh"
    # The default budget path exercises the model_policy slug import under the patch.
    assert cq.admit("consult", "c1", project_root=project, now=NOW, sessions_dir=sessions)["admitted"]
    assert cq.admit("audit", "c1", project_root=project, now=NOW, sessions_dir=sessions)["admitted"]
    assert cq.cycle_id_for(project, now=NOW) == "adhoc-20260914-nobase"
    assert calls == []


# --------------------------------------------------------------------------- #
# Concurrency — real processes
# --------------------------------------------------------------------------- #
_WORKER = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, sys.argv[1])
    import codex_quota as cq
    use, cycle_prefix, n, budget, sessions, now, start_at = sys.argv[2:9]
    delay = float(start_at) - time.time()
    if delay > 0:
        time.sleep(delay)  # both workers begin together, so their admits interleave
    for i in range(int(n)):
        cq.admit(use, f"{cycle_prefix}-{i}", project_root=sys.argv[1], now=float(now),
                 sessions_dir=sessions, budget_path=budget)
""")


def _run_workers(tmp_path, sessions, specs):
    import time

    script = tmp_path / "worker.py"
    script.write_text(_WORKER, encoding="utf-8")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    start_at = str(time.time() + 1.5)
    procs = [subprocess.Popen([sys.executable, str(script), str(_META), use, prefix, str(n),
                               str(budget(tmp_path)), str(sessions), str(NOW), start_at],
                              cwd=str(tmp_path), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
             for use, prefix, n in specs]
    for p in procs:
        _out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err.decode("utf-8", "replace")


def test_two_concurrent_appenders_produce_an_exact_row_count(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    _run_workers(tmp_path, sessions, [("audit", "wa", 150), ("audit", "wb", 150)])
    raw = budget(tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(raw) == 300
    rows = [json.loads(line) for line in raw]  # every line is one whole row
    assert sum(r["cycle_id"].startswith("wa-") for r in rows) == 150
    assert sum(r["cycle_id"].startswith("wb-") for r in rows) == 150


def test_concurrent_consults_admit_exactly_once_per_cycle(sessions, tmp_path):
    """Both workers walk the SAME 150 cycles at the same moment. The count and the
    append share one lock, so no cycle can be admitted twice."""
    fresh_rollout(sessions, 10.0, 3.0)
    _run_workers(tmp_path, sessions, [("consult", "shared", 150), ("consult", "shared", 150)])
    rows = read_rows(budget(tmp_path))
    assert len(rows) == 300
    admitted = {}
    for r in rows:
        admitted[r["cycle_id"]] = admitted.get(r["cycle_id"], 0) + int(r["admitted"])
    assert len(admitted) == 150
    assert set(admitted.values()) == {1}


# --------------------------------------------------------------------------- #
# Project slug
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw", ["/path/to/project", "/tmp/a b/c.d_e", "relative/dir",
                                 "/x/été"])
def test_project_slug_agrees_with_model_policy(raw):
    fn = cq._load_model_policy_slug()
    assert fn is not None, "model_policy._project_slug must import for the agreement to mean anything"
    assert fn(raw) == cq._fallback_project_slug(raw) == cq.project_slug(raw)


def test_project_slug_falls_back_when_model_policy_is_unavailable(monkeypatch, tmp_path):
    expected = cq._fallback_project_slug("/path/to/project")
    monkeypatch.setattr(cq, "_MODEL_POLICY_PATH", tmp_path / "missing" / "model_policy.py")
    monkeypatch.setattr(cq, "_model_policy_slug_fn", None)
    monkeypatch.setattr(cq, "_model_policy_loaded", False)
    assert cq._load_model_policy_slug() is None
    assert cq.project_slug("/path/to/project") == expected == "-path-to-project"


# --------------------------------------------------------------------------- #
# cycle_id_for()
# --------------------------------------------------------------------------- #
SESSION_UUID = "0b1c2d3e-aaaa-bbbb-cccc-1234567890ab"
CYCLE_UUID = "5f0e8a1c-9d2b-4c3e-8f7a-6b5d4c3b2a19"
DAY = 24 * HOUR


def forge_file(project, name, text, *, mtime=None):
    """Write .forge/<name>; `mtime` (epoch) is applied with os.utime so ages are exact."""
    forge = project / ".forge"
    forge.mkdir(exist_ok=True)
    path = forge / name
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_cycle_id_ignores_a_stale_session_id(project):
    """D7 INVERSION of the old test_cycle_id_uses_the_forge_session_id: session-id is the
    contract-signing id, never re-minted, so keying the budget on it refused every later
    cycle (the WP-A02 halt). Its presence must change nothing."""
    forge_file(project, "session-id", SESSION_UUID + "\n")
    forge_file(project, "cycle-base", "1234567890abcdef\n")
    assert cq.cycle_id_for(project, now=NOW) == "adhoc-20260914-1234567"
    assert cq.cycle_id_and_source(project, now=NOW) == ("adhoc-20260914-1234567", "adhoc-base", None)
    # CONTROL: the same tree plus a fresh .forge/cycle-id returns the cycle-id.
    forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW)
    assert cq.cycle_id_for(project, now=NOW) == CYCLE_UUID


def test_cycle_id_never_opens_the_session_id(project, monkeypatch):
    forge_file(project, "session-id", SESSION_UUID + "\n")
    forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW)
    forge_file(project, "cycle-base", "1234567890abcdef\n")
    seen = []
    real_open = open

    def _spy(file, *a, **k):
        seen.append(os.fspath(file))
        return real_open(file, *a, **k)

    monkeypatch.setattr("builtins.open", _spy)
    monkeypatch.setattr(Path, "read_text",
                        lambda self, *a, **k: (seen.append(str(self)), real_open(self, *a, **k).read())[1])
    assert cq.cycle_id_for(project, now=NOW) == CYCLE_UUID
    os.remove(project / ".forge" / "cycle-id")
    assert cq.cycle_id_for(project, now=NOW) == "adhoc-20260914-1234567"
    assert seen, "the spy must observe the cycle-id / cycle-base reads"
    assert not [p for p in seen if p.endswith("session-id")]


def test_cycle_id_wins_over_the_cycle_base(project):
    forge_file(project, "cycle-base", "7E93293321abcdef\n")
    forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW)
    assert cq.cycle_id_and_source(project, now=NOW) == (CYCLE_UUID, "cycle-id", 0)


def test_cycle_id_falls_back_to_the_cycle_base(project):
    (project / ".forge").mkdir()
    (project / ".forge" / "cycle-base").write_text("7E93293321abcdef\n", encoding="utf-8")
    assert cq.cycle_id_for(project, now=NOW) == "adhoc-20260914-7e93293"


def test_cycle_id_without_forge_files_is_nobase(project):
    assert cq.cycle_id_for(project, now=NOW) == "adhoc-20260914-nobase"
    assert cq.cycle_id_and_source(project, now=NOW) == ("adhoc-20260914-nobase", "adhoc-nobase", None)


def test_cycle_id_empty_cycle_id_falls_through(project):
    """Re-pointed from the old empty-session-id test: an empty cycle-id still falls through."""
    forge_file(project, "cycle-id", "  \n", mtime=NOW)
    (project / ".forge" / "cycle-base").write_text("abcdef0123\n", encoding="utf-8")
    assert cq.cycle_id_for(project, now=NOW) == "adhoc-20260914-abcdef0"
    # The file exists, so its age is recorded even though its content was rejected.
    assert cq.cycle_id_and_source(project, now=NOW) == ("adhoc-20260914-abcdef0", "adhoc-base", 0)


@pytest.mark.parametrize("base", ["fatal: not a git repository", "abc", "", "zzzzzzzzzz"])
def test_cycle_id_unusable_cycle_base_is_nobase(project, base):
    (project / ".forge").mkdir()
    (project / ".forge" / "cycle-base").write_text(base, encoding="utf-8")
    assert cq.cycle_id_for(project, now=NOW) == "adhoc-20260914-nobase"


def test_cycle_id_unreadable_cycle_id_falls_through(project):
    """Re-pointed from the old unreadable-session-id test."""
    (project / ".forge" / "cycle-id").mkdir(parents=True)  # a directory, not a file
    assert cq.cycle_id_for(project, now=NOW) == "adhoc-20260914-nobase"


def test_cycle_id_date_is_utc(project):
    late = datetime(2026, 9, 14, 23, 59, 59, tzinfo=timezone.utc).timestamp()
    assert cq.cycle_id_for(project, now=late) == "adhoc-20260914-nobase"
    assert cq.cycle_id_for(project, now=late + 1) == "adhoc-20260915-nobase"


@pytest.mark.parametrize("content", [
    "\n",                        # newline-only
    "a" * 200,                   # too long
    "a" * 129,                   # one over the 128-character bound
    "abc def",                   # a space inside the id
    "abc;rm -rf ~",              # a shell metacharacter
    "$(id)",                     # command substitution
    "-leading-dash",             # must start alphanumeric
    "\ncycle-on-line-two",       # the FIRST line is what counts
])
def test_cycle_id_invalid_contents_fall_through(project, content):
    forge_file(project, "cycle-base", "abcdef0123\n")
    forge_file(project, "cycle-id", content, mtime=NOW)
    assert cq.cycle_id_and_source(project, now=NOW) == ("adhoc-20260914-abcdef0", "adhoc-base", 0)


def test_cycle_id_directory_falls_through(project):
    forge_file(project, "cycle-base", "abcdef0123\n")
    (project / ".forge" / "cycle-id").mkdir()
    cycle_id, source, _age = cq.cycle_id_and_source(project, now=NOW)
    assert (cycle_id, source) == ("adhoc-20260914-abcdef0", "adhoc-base")


@pytest.mark.parametrize("content", [CYCLE_UUID, CYCLE_UUID.upper() + "\r\n", "a" * 128,
                                     "S081.cycle_3:rev-2b"])
def test_cycle_id_valid_contents_are_used(project, content):
    """CONTROL for the invalid-content cases: a uuid (either case, CRLF), the 128-character
    bound, and the allowed punctuation are accepted."""
    forge_file(project, "cycle-base", "abcdef0123\n")
    forge_file(project, "cycle-id", content, mtime=NOW)
    assert cq.cycle_id_and_source(project, now=NOW) == (content.strip(), "cycle-id", 0)


def test_cycle_id_max_age_is_twenty_four_hours():
    assert cq.CYCLE_ID_MAX_AGE_S == 24 * 3600


def test_cycle_id_fresh_file_is_used(project):
    forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW)
    assert cq.cycle_id_and_source(project, now=NOW) == (CYCLE_UUID, "cycle-id", 0)


def test_cycle_id_twenty_five_hours_old_is_ignored(project):
    forge_file(project, "cycle-base", "abcdef0123\n")
    forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW - 25 * HOUR)
    assert cq.cycle_id_and_source(project, now=NOW) == ("adhoc-20260914-abcdef0", "adhoc-base", 90000)
    assert cq.cycle_id_for(project, now=NOW) == "adhoc-20260914-abcdef0"


def test_cycle_id_twenty_three_hours_old_is_used(project):
    """CONTROL for the 25h age-out: a long forge cycle must NOT roll over mid-cycle."""
    forge_file(project, "cycle-base", "abcdef0123\n")
    forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW - 23 * HOUR)
    assert cq.cycle_id_and_source(project, now=NOW) == (CYCLE_UUID, "cycle-id", 82800)


def test_cycle_id_age_out_boundary(project):
    forge_file(project, "cycle-base", "abcdef0123\n")
    path = forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW - DAY)
    assert cq.cycle_id_and_source(project, now=NOW) == (CYCLE_UUID, "cycle-id", 86400)  # exactly 24h: used
    os.utime(path, (NOW - DAY - 1, NOW - DAY - 1))
    assert cq.cycle_id_and_source(project, now=NOW) == ("adhoc-20260914-abcdef0", "adhoc-base", 86401)


def test_cycle_id_far_future_mtime_is_ignored(project):
    """A skewed or planted timestamp cannot keep a key alive forever (J3b)."""
    forge_file(project, "cycle-base", "abcdef0123\n")
    forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW + 300)
    assert cq.cycle_id_and_source(project, now=NOW) == ("adhoc-20260914-abcdef0", "adhoc-base", -300)


def test_cycle_id_small_future_mtime_is_used(project):
    """CONTROL for the far-future case: FUTURE_SKEW_S of clock skew is tolerated."""
    forge_file(project, "cycle-base", "abcdef0123\n")
    forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW + 60)
    assert cq.cycle_id_and_source(project, now=NOW) == (CYCLE_UUID, "cycle-id", -60)


def test_cycle_id_unreadable_mtime_counts_as_absent(project, monkeypatch):
    forge_file(project, "cycle-base", "abcdef0123\n")
    path = forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW)
    real_stat = os.stat

    def _stat(p, *a, **k):
        if os.fspath(p) == os.fspath(path):
            raise PermissionError("mtime unreadable")
        return real_stat(p, *a, **k)

    monkeypatch.setattr(cq.os, "stat", _stat)
    assert cq.cycle_id_and_source(project, now=NOW) == ("adhoc-20260914-abcdef0", "adhoc-base", None)


def _forge_tree_state(project):
    state = {}
    for p in sorted((project / ".forge").rglob("*")):
        st = p.stat()
        state[str(p)] = (p.read_bytes() if p.is_file() else None, st.st_mtime_ns, st.st_mode)
    return state


def test_cycle_id_reads_are_read_only_even_for_an_aged_out_file(project):
    forge_file(project, "session-id", SESSION_UUID + "\n", mtime=NOW - 400 * DAY)
    forge_file(project, "cycle-base", "abcdef0123\n", mtime=NOW - HOUR)
    aged = forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW - 25 * HOUR)
    before = _forge_tree_state(project)
    for _ in range(3):
        cq.cycle_id_for(project, now=NOW)
        cq.cycle_id_and_source(project, now=NOW)
    cq.admit("audit", cq.cycle_id_for(project, now=NOW), project_root=project, now=NOW,
             sessions_dir=project / "no-sessions", budget_path=project / "budget.jsonl")
    assert _forge_tree_state(project) == before  # bytes and mtimes, nothing created or removed
    assert aged.read_text(encoding="utf-8") == CYCLE_UUID + "\n"


def test_cycle_id_after_close_out_deletion_is_the_adhoc_key(project):
    forge_file(project, "cycle-base", "abcdef0123\n")
    path = forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW)
    assert cq.cycle_id_for(project, now=NOW) == CYCLE_UUID
    path.unlink()  # forge Step 6 close-out: rm -f .forge/cycle-id
    assert cq.cycle_id_and_source(project, now=NOW) == ("adhoc-20260914-abcdef0", "adhoc-base", None)


def test_cycle_id_and_source_never_raises(project):
    assert cq.cycle_id_and_source(project / "missing" / "root", now=NOW) == (
        "adhoc-20260914-nobase", "adhoc-nobase", None)
    blocker = project / "blocker"
    blocker.write_text("a file where a project directory is expected", encoding="utf-8")
    assert cq.cycle_id_and_source(blocker, now=NOW)[1] == "adhoc-nobase"


# --------------------------------------------------------------------------- #
# admit() — cycle id provenance (J3 (2)) and the per-cycle roll-over (D7)
# --------------------------------------------------------------------------- #
def test_admit_rows_record_the_cycle_id_source_and_age(sessions, tmp_path, project):
    fresh_rollout(sessions, 10.0, 3.0)
    forge_file(project, "cycle-base", "abcdef0123\n")
    forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW - 2 * HOUR)
    cid = cq.cycle_id_for(project, now=NOW)
    d = cq.admit("consult", cid, project_root=project, now=NOW, sessions_dir=sessions,
                 budget_path=budget(tmp_path))
    assert (d["cycle_id_source"], d["cycle_id_file_age_s"]) == ("cycle-id", 7200)
    row = read_rows(budget(tmp_path))[-1]
    assert (row["cycle_id"], row["cycle_id_source"], row["cycle_id_file_age_s"]) == (CYCLE_UUID, "cycle-id", 7200)
    assert ROW_KEYS <= set(row)
    # adhoc-base: close-out removed the cycle-id.
    (project / ".forge" / "cycle-id").unlink()
    d = cq.admit("challenger", cq.cycle_id_for(project, now=NOW), project_root=project, now=NOW,
                 sessions_dir=sessions, budget_path=budget(tmp_path))
    assert (d["cycle_id"], d["cycle_id_source"], d["cycle_id_file_age_s"]) == (
        "adhoc-20260914-abcdef0", "adhoc-base", None)
    # adhoc-nobase, with an aged-out cycle-id still on disk: its age is recorded.
    (project / ".forge" / "cycle-base").unlink()
    forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW - 30 * HOUR)
    d = cq.admit("challenger", cq.cycle_id_for(project, now=NOW), project_root=project, now=NOW,
                 sessions_dir=sessions, budget_path=budget(tmp_path))
    assert (d["cycle_id"], d["cycle_id_source"], d["cycle_id_file_age_s"]) == (
        "adhoc-20260914-nobase", "adhoc-nobase", 108000)
    rows = read_rows(budget(tmp_path))
    assert [(r["cycle_id_source"], r["cycle_id_file_age_s"]) for r in rows] == [
        ("cycle-id", 7200), ("adhoc-base", None), ("adhoc-nobase", 108000)]


def test_admit_an_explicit_differing_cycle_id_records_explicit_and_no_age(sessions, tmp_path, project):
    """CONTROL for the source derivation: an id the caller chose is never guessed at."""
    fresh_rollout(sessions, 10.0, 3.0)
    forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW - 2 * HOUR)
    d = cq.admit("consult", "caller-chosen-id", project_root=project, now=NOW, sessions_dir=sessions,
                 budget_path=budget(tmp_path))
    assert (d["cycle_id_source"], d["cycle_id_file_age_s"]) == ("explicit", None)
    row = read_rows(budget(tmp_path))[-1]
    assert (row["cycle_id"], row["cycle_id_source"], row["cycle_id_file_age_s"]) == (
        "caller-chosen-id", "explicit", None)


def test_admit_without_a_project_root_omits_the_source_pair(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    d = cq.admit("consult", "c1", project_root=None, now=NOW, sessions_dir=sessions,
                 budget_path=budget(tmp_path))
    assert d["admitted"] is True
    assert not (CYCLE_SOURCE_KEYS & set(d))
    assert set(read_rows(budget(tmp_path))[0]) == ROW_KEYS | ADMISSION_ID_KEYS  # RE-POINTED by #282 r10 (K12)


def test_two_cycles_with_two_cycle_ids_each_get_a_consult(sessions, tmp_path, project):
    """D7 ROLL-OVER: forge Step 1 writes a fresh cycle-id every cycle, so every cycle has its
    own budget (the WP-A02 halt refused cycle 2+ forever)."""
    fresh_rollout(sessions, 10.0, 3.0)
    forge_file(project, "session-id", SESSION_UUID + "\n")  # present, and irrelevant
    decisions = []
    for n, cycle in enumerate((CYCLE_UUID, "9a8b7c6d-0000-4000-8000-000000000002")):
        forge_file(project, "cycle-id", cycle + "\n", mtime=NOW - 60 + n)
        decisions.append(cq.admit("consult", cq.cycle_id_for(project, now=NOW), project_root=project,
                                  now=NOW, sessions_dir=sessions, budget_path=budget(tmp_path)))
    assert [(d["cycle_id"], d["admitted"], d["reason"]) for d in decisions] == [
        (CYCLE_UUID, True, "within_budget"),
        ("9a8b7c6d-0000-4000-8000-000000000002", True, "within_budget")]


def test_two_consults_under_one_cycle_id_refuse_the_second(sessions, tmp_path, project):
    """CONTROL for the roll-over: the budget still binds inside one cycle."""
    fresh_rollout(sessions, 10.0, 3.0)
    forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW - 60)
    first = cq.admit("consult", cq.cycle_id_for(project, now=NOW), project_root=project, now=NOW,
                     sessions_dir=sessions, budget_path=budget(tmp_path))
    second = cq.admit("consult", cq.cycle_id_for(project, now=NOW), project_root=project, now=NOW,
                      sessions_dir=sessions, budget_path=budget(tmp_path))
    assert (first["admitted"], second["admitted"], second["reason"]) == (True, False, "budget_spent")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _cli(args, home, cwd, extra_env=None):
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), PYTHONDONTWRITEBYTECODE="1")
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(_MODULE_PATH)] + args, cwd=str(cwd), env=env,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)


def _live_rollout(home, primary, weekly):
    import time

    now = time.time()
    day = datetime.fromtimestamp(now, timezone.utc).strftime("%Y/%m/%d")
    write_rollout(home / ".codex" / "sessions", day, "rollout-cli.jsonl",
                  [rl_event(now - 30, primary, weekly), premium_null(now - 29)])


def test_cli_snapshot_json(fixture_home, project):
    _live_rollout(fixture_home, 42.0, 7.0)
    r = _cli(["snapshot", "--json"], fixture_home, project)
    assert r.returncode == 0, r.stderr
    snap = json.loads(r.stdout)
    assert (snap["state"], snap["primary_used_percent"], snap["secondary_used_percent"]) == (
        "fresh", 42.0, 7.0)


def test_cli_snapshot_human_line_is_ascii(fixture_home, project):
    _live_rollout(fixture_home, 42.0, 7.0)
    r = _cli(["snapshot"], fixture_home, project, {"PYTHONIOENCODING": "cp1252"})
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "codex-quota: 5h 42% / weekly 7% (fresh)"
    assert r.stdout.isascii()


def test_cli_snapshot_unknown_exits_zero(fixture_home, project):
    r = _cli(["snapshot"], fixture_home, project)
    assert r.returncode == 0
    assert r.stdout.startswith("codex-quota: unknown")


def test_cli_admit_exit_codes_zero_then_ten(fixture_home, project):
    """RE-POINTED by #282 r15 (K17): the CLI records only with --record, so both calls pass it."""
    _live_rollout(fixture_home, 10.0, 3.0)
    first = _cli(["admit", "--record", "--use", "consult", "--cycle-id", "cli-1", "--project-root", str(project)],
                 fixture_home, project)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["admitted"] is True
    second = _cli(["admit", "--record", "--use", "consult", "--cycle-id", "cli-1", "--project-root", str(project)],
                  fixture_home, project)
    assert second.returncode == 10, second.stderr
    decision = json.loads(second.stdout)
    assert (decision["admitted"], decision["reason"]) == (False, "budget_spent")
    rows = read_rows(fixture_home / ".claude" / "projects" / cq.project_slug(project) / "astra-budget.jsonl")
    assert [r["admitted"] for r in rows] == [True, False]


def test_cli_admit_project_root_defaults_to_cwd(fixture_home, project):
    """RE-POINTED by #282 r15 (K17): the store under the cwd's slug is written only with --record."""
    r = _cli(["admit", "--record", "--use", "audit", "--cycle-id", "cli-2"], fixture_home, project)
    assert r.returncode == 0, r.stderr
    assert (fixture_home / ".claude" / "projects" / cq.project_slug(project.resolve())
            / "astra-budget.jsonl").is_file()


def test_cli_admit_diagnosis_task_key(fixture_home, project):
    """RE-POINTED by #282 r15 (K17): the per-task budget is spent only by recorded admissions (--record)."""
    base = ["admit", "--record", "--use", "diagnosis", "--cycle-id", "cli-3", "--project-root", str(project)]
    assert _cli(base + ["--task-key", "WP-1"], fixture_home, project).returncode == 0
    assert _cli(base + ["--task-key", "WP-1"], fixture_home, project).returncode == 10
    assert _cli(base + ["--task-key", "WP-2"], fixture_home, project).returncode == 0


@pytest.mark.parametrize("args", [
    [],
    ["bogus"],
    ["admit", "--use", "explore", "--cycle-id", "c"],
    ["admit", "--use", "consult"],
    ["admit", "--use", "consult", "--cycle-id", ""],
    ["admit", "--use", "consult", "--cycle-id", "c", "--task-key", "WP-1"],
    ["snapshot", "--bogus"],
])
def test_cli_usage_errors_exit_three(fixture_home, project, args):
    r = _cli(args, fixture_home, project)
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)


@pytest.mark.parametrize("mode", [[], ["--record"]], ids=["check_only", "record"])
def test_cli_admit_store_failure_exits_three(fixture_home, project, mode):
    """EXTENDED by #282 r15 (K17): the exit codes are identical in the check-only and --record modes."""
    (fixture_home / ".claude").mkdir()
    (fixture_home / ".claude" / "projects").write_text("not a directory", encoding="utf-8")
    r = _cli(["admit", *mode, "--use", "consult", "--cycle-id", "c", "--project-root", str(project)],
             fixture_home, project)
    assert r.returncode == 3
    assert json.loads(r.stdout)["reason"] == "budget_store_unavailable"
    # CONTROL: the audit still passes through a broken store.
    a = _cli(["admit", *mode, "--use", "audit", "--cycle-id", "c", "--project-root", str(project)],
             fixture_home, project)
    assert a.returncode == 0 and json.loads(a.stdout)["admitted"] is True


def test_cli_cycle_id(fixture_home, project):
    """Re-pointed from session-id to cycle-id (D7). The output shape is unchanged: the id only."""
    (project / ".forge").mkdir()
    (project / ".forge" / "cycle-id").write_text("cycle-123\n", encoding="utf-8")
    r = _cli(["cycle-id", "--project-root", str(project)], fixture_home, fixture_home)
    assert r.returncode == 0 and r.stdout.strip() == "cycle-123"
    assert r.stdout == "cycle-123\n"
    here = _cli(["cycle-id"], fixture_home, project)
    assert here.returncode == 0 and here.stdout.strip() == "cycle-123"


def test_cli_cycle_id_ignores_a_session_id(fixture_home, project):
    (project / ".forge").mkdir()
    (project / ".forge" / "session-id").write_text("sess-123\n", encoding="utf-8")
    r = _cli(["cycle-id", "--project-root", str(project)], fixture_home, fixture_home)
    assert r.returncode == 0
    assert r.stdout.startswith("adhoc-") and r.stdout.strip().endswith("-nobase")
    assert "sess-123" not in r.stdout


def test_cli_cycle_id_help_names_the_lifecycle_and_is_ascii(fixture_home, project):
    r = _cli(["cycle-id", "--help"], fixture_home, project, {"PYTHONIOENCODING": "cp1252"})
    assert r.returncode == 0, r.stderr
    text = " ".join(r.stdout.split())
    assert r.stdout.isascii()
    for needle in (".forge/cycle-id", "24h", "Step 1", "close-out", "session-id", "never re-minted"):
        assert needle in text, needle


def test_cli_admit_output_carries_the_cycle_id_source(fixture_home, project):
    (project / ".forge").mkdir()
    (project / ".forge" / "cycle-id").write_text(CYCLE_UUID + "\n", encoding="utf-8")
    r = _cli(["admit", "--use", "consult", "--cycle-id", CYCLE_UUID, "--project-root", str(project)],
             fixture_home, project)
    assert r.returncode == 0, r.stderr
    decision = json.loads(r.stdout)
    assert decision["cycle_id_source"] == "cycle-id"
    assert isinstance(decision["cycle_id_file_age_s"], int) and 0 <= decision["cycle_id_file_age_s"] < 120
    other = _cli(["admit", "--use", "challenger", "--cycle-id", "elsewhere", "--project-root", str(project)],
                 fixture_home, project)
    assert (json.loads(other.stdout)["cycle_id_source"], json.loads(other.stdout)["cycle_id_file_age_s"]) == (
        "explicit", None)


# =========================================================================== #
# Amendment 1 D6 — astra unavailable -> a fresh Fable substitute (WP-F01)
# =========================================================================== #
# --------------------------------------------------------------------------- #
# unavailable() — J6
# --------------------------------------------------------------------------- #
def closing_rollout(sessions_root, primary, weekly, *, age=60.0, reached_type=None,
                    name="rollout-2026-09-14T15-00-00-aaaa.jsonl", day="2026/09/14"):
    """A session in the live shape whose CLOSING entry (limit_id premium, primary null)
    carries `reached_type`."""
    observed = NOW - age
    return write_rollout(sessions_root, day, name, [
        other_line(observed - 5),
        rl_event(observed, primary, weekly),
        premium_null(observed + 0.2, reached_type=reached_type),
    ])


def test_snapshot_output_keys_are_unchanged(sessions):
    """WP-F01 may add keys to snapshot(); it adds none, so every consumer's view is intact."""
    expected = {"state", "primary_used_percent", "primary_resets_at", "secondary_used_percent",
                "secondary_resets_at", "observed_at", "source", "limit_id", "reason"}
    closing_rollout(sessions, 10.0, 3.0, reached_type="primary")
    assert set(cq.snapshot(sessions_dir=sessions, now=NOW)) == expected
    assert set(cq.snapshot(sessions_dir=sessions / "absent", now=NOW)) == expected


def test_unavailable_rate_limit_reached_on_a_fresh_closing_entry_with_a_null_primary(sessions):
    closing_rollout(sessions, 40.0, 10.0, reached_type="primary")
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["primary_used_percent"] == 40.0
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "rate_limit_reached"


@pytest.mark.parametrize("value", [None, False, "", "   ", [], {}])
def test_unavailable_null_false_or_empty_reached_type_is_available(sessions, value):
    """CONTROL for the rate_limit_reached case: the same fixture with the live null value."""
    closing_rollout(sessions, 40.0, 10.0, reached_type=value)
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None


def test_unavailable_reached_type_on_the_codex_limit_is_not_hidden_by_a_later_premium_entry(sessions):
    """Readings are per limit_id: the session-closing premium entry is a DIFFERENT limit, so
    its null type does not clear a type set on the codex limit a second earlier."""
    write_rollout(sessions, "2026/09/14", "rollout-a.jsonl", [
        rl_event(NOW - 61, 50.0, 10.0, reached_type="secondary"),
        premium_null(NOW - 60),
    ])
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "rate_limit_reached"


def test_unavailable_a_newer_entry_of_the_same_limit_clears_the_type(sessions):
    """CONTROL for the per-limit rule: the codex limit's NEWEST object decides."""
    write_rollout(sessions, "2026/09/14", "rollout-a.jsonl", [
        rl_event(NOW - 120, 50.0, 10.0, reached_type="primary"),
        rl_event(NOW - 61, 51.0, 10.0),
        premium_null(NOW - 60),
    ])
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None


def test_unavailable_newest_same_limit_object_wins_across_files(sessions):
    """Concurrent sessions interleave: the newest TIMESTAMP per limit decides, not the file name."""
    write_rollout(sessions, "2026/09/14", "rollout-2026-09-14T15-20-00-late-name.jsonl",
                  [rl_event(NOW - 300, 50.0, 10.0, reached_type="primary")])
    write_rollout(sessions, "2026/09/14", "rollout-2026-09-14T15-10-00-early-name.jsonl",
                  [rl_event(NOW - 100, 52.0, 10.0)])
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None
    # CONTROL: swap which object is newer and the type is the current state again.
    write_rollout(sessions, "2026/09/14", "rollout-2026-09-14T15-20-00-late-name.jsonl",
                  [rl_event(NOW - 50, 50.0, 10.0, reached_type="primary")])
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "rate_limit_reached"


def test_unavailable_fresh_primary_99_is_quota_exhausted(sessions):
    closing_rollout(sessions, 99.0, 10.0)
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "quota_exhausted"


def test_unavailable_fresh_primary_98_is_available(sessions):
    """CONTROL for the 99% boundary."""
    closing_rollout(sessions, 98.0, 10.0)
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None


def test_unavailable_fresh_weekly_99_is_quota_exhausted(sessions):
    closing_rollout(sessions, 10.0, 99.0)
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "quota_exhausted"


def test_unavailable_prefers_rate_limit_reached_over_quota_exhausted(sessions):
    closing_rollout(sessions, 100.0, 100.0, reached_type="primary")
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "rate_limit_reached"


@pytest.mark.parametrize("age", [2400.0, -(cq.FUTURE_SKEW_S + 60.0)])
def test_unavailable_stale_or_far_future_readings_are_none(sessions, age):
    closing_rollout(sessions, 100.0, 100.0, age=age, reached_type="primary")
    assert cq.snapshot(sessions_dir=sessions, now=NOW)["state"] == "stale"
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None


def test_unavailable_a_window_that_already_reset_is_not_exhausted(sessions):
    closing_rollout(sessions, 100.0, 10.0)
    fresh_rollout(sessions, 100.0, 10.0, p_resets=int(NOW - 1), name="rollout-2026-09-14T15-00-00-aaaa.jsonl")
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None


@pytest.mark.parametrize("body", [
    b"\x00\xff\xfe garbage \x80\n",
    b'{"payload": {"rate_limits": {"rate_limit_reached_type": "primary"\n',
    b'{"payload": {"rate_limits": "primary"}}\n',
    b'{"timestamp": 12, "payload": {"rate_limits": {"rate_limit_reached_type": "primary"}}}\n',
    b'["rate_limits"]\n',
    b"",
])
def test_unavailable_corrupt_rollout_is_none_without_raising(sessions, body):
    d = sessions / "2026" / "09" / "14"
    d.mkdir(parents=True)
    (d / "rollout-corrupt.jsonl").write_bytes(body)
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None


def test_unavailable_missing_sessions_or_bad_now_is_none(sessions, tmp_path):
    closing_rollout(sessions, 40.0, 10.0, reached_type="primary")
    assert cq.unavailable(sessions_dir=tmp_path / "absent", now=NOW) is None
    assert cq.unavailable(sessions_dir=sessions, now="noon") is None


def test_unavailable_default_sessions_dir_is_read_at_call_time(fixture_home):
    closing_rollout(fixture_home / ".codex" / "sessions", 40.0, 10.0, reached_type="primary")
    assert cq.unavailable(now=NOW) == "rate_limit_reached"


def test_unavailable_walk_is_bounded_to_the_newest_day_dirs(sessions):
    """RE-POINTED (#282 R6): bounded by the date window, not the three newest directories."""
    for day in ("2026/09/14", "2026/09/13", "2026/09/12"):
        write_rollout(sessions, day, "rollout-x.jsonl", [other_line(NOW - 50)])
    write_rollout(sessions, "2026/09/04", "rollout-x.jsonl", [premium_null(NOW - 60, reached_type="primary")])
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None
    # CONTROL: the same object inside a directory seven days old IS read.
    write_rollout(sessions, "2026/09/07", "rollout-x.jsonl", [premium_null(NOW - 60, reached_type="primary")])
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "rate_limit_reached"


def test_unavailable_tail_read_is_bounded(sessions, monkeypatch):
    monkeypatch.setattr(cq, "TAIL_BYTES", 4096)
    padding = [other_line(NOW - 50, "x" * 200) for _ in range(40)]
    write_rollout(sessions, "2026/09/14", "rollout-a.jsonl",
                  [premium_null(NOW - 60, reached_type="primary")] + padding)
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None
    # CONTROL: inside the bound it is found.
    write_rollout(sessions, "2026/09/14", "rollout-a.jsonl",
                  padding + [premium_null(NOW - 60, reached_type="primary")])
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "rate_limit_reached"


# --------------------------------------------------------------------------- #
# admit() consults unavailable() first — J7
# --------------------------------------------------------------------------- #
SIGNALS = {
    "rate_limit_reached": dict(primary=40.0, weekly=10.0, reached_type="primary"),
    "quota_exhausted": dict(primary=99.5, weekly=10.0, reached_type=None),
}


def signal_rollout(sessions_root, signal, **kw):
    spec = SIGNALS[signal]
    return closing_rollout(sessions_root, spec["primary"], spec["weekly"],
                           reached_type=spec["reached_type"], **kw)


@pytest.mark.parametrize("signal", sorted(SIGNALS))
@pytest.mark.parametrize("use", ["consult", "challenger", "advisory_review", "diagnosis", "trial"])
def test_admit_refuses_with_the_unavailable_token_while_the_budget_is_unspent(sessions, tmp_path, use, signal):
    signal_rollout(sessions, signal)
    d = _admit(use, "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"], d["unavailable"]) == (False, signal, signal)
    # RE-POINTED by #322 fix round 1 (F2): the budget is counted FIRST (was None: quota short-circuited it),
    # and the row says where the quota token came from (`unavailable_source`).
    assert d["budget_used"] == (None if use == "trial" else 0) and d["row_written"] is True
    row = read_rows(budget(tmp_path))[-1]
    assert (row["admitted"], row["reason"], row["unavailable"], row["unavailable_source"]) == (
        False, signal, signal, "meter")
    assert set(row) == ROW_KEYS | CYCLE_SOURCE_KEYS | ADMISSION_ID_KEYS | {"unavailable", "unavailable_source"}


@pytest.mark.parametrize("use", ["consult", "challenger", "advisory_review", "diagnosis"])
def test_admit_the_same_budget_without_a_signal_is_admitted(sessions, tmp_path, use):
    """CONTROL for the refusal above: the refused row spent nothing, and without the signal
    the same cycle's budget admits the call."""
    signal_rollout(sessions, "rate_limit_reached")
    assert _admit(use, "c1", sessions, tmp_path)["admitted"] is False
    quiet = tmp_path / "quiet-sessions"
    # RE-POINTED by #322 fix round 2 (N1): the refusal persisted the exhausted record with the evidence time of
    # the rate_limits object that SET the flag (NOW - 59.8). The quiet reading must be newer than that to
    # supersede it (it was NOW - 60, 0.2 s older, and superseded only because the evidence time was wrong).
    closing_rollout(quiet, 40.0, 10.0, age=30.0)
    d = _admit(use, "c1", quiet, tmp_path)
    assert (d["admitted"], d["reason"]) == (True, "within_budget")
    assert "unavailable" not in d
    assert "unavailable" not in read_rows(budget(tmp_path))[-1]


def test_admit_quota_exhausted_starts_at_99(sessions, tmp_path):
    """RE-POINTED AND RENAMED by #322 (was test_admit_quota_exhausted_outranks_the_threshold)."""
    closing_rollout(sessions, 99.0, 3.0)
    assert _admit("consult", "c1", sessions, tmp_path)["reason"] == "quota_exhausted"
    # CONTROL: 98% was a threshold refusal until #322; now it is admitted and carries no reset fields.
    closing_rollout(sessions, 98.0, 3.0, name="rollout-2026-09-14T15-10-00-bbbb.jsonl", age=10.0)
    d = _admit("consult", "c2", sessions, tmp_path)
    assert (d["reason"], "unavailable" in d, "wait_advice" in d) == ("within_budget", False, False)


@pytest.mark.parametrize("signal", sorted(SIGNALS))
def test_admit_audit_is_admitted_with_unavailable_set(sessions, tmp_path, signal):
    signal_rollout(sessions, signal)
    d = _admit("audit", "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"], d["unavailable"]) == (True, "audit_exempt", signal)
    row = read_rows(budget(tmp_path))[-1]
    assert (row["admitted"], row["unavailable"]) == (True, signal)


def test_admit_audit_without_a_signal_has_no_unavailable_key(sessions, tmp_path):
    """CONTROL: the audit row and decision are unchanged when codex is available."""
    closing_rollout(sessions, 95.0, 96.0)
    d = _admit("audit", "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"]) == (True, "audit_exempt") and "unavailable" not in d
    assert set(read_rows(budget(tmp_path))[-1]) == ROW_KEYS | CYCLE_SOURCE_KEYS | ADMISSION_ID_KEYS  # RE-POINTED by #282 r10


def test_admit_unavailable_refusal_survives_a_broken_store(sessions, broken_budget):
    signal_rollout(sessions, "rate_limit_reached")
    d = cq.admit("consult", "c1", project_root=broken_budget.parent, now=NOW, sessions_dir=sessions,
                 budget_path=broken_budget)
    assert (d["admitted"], d["reason"], d["row_written"]) == (False, "rate_limit_reached", False)
    a = cq.admit("audit", "c1", project_root=broken_budget.parent, now=NOW, sessions_dir=sessions,
                 budget_path=broken_budget)
    assert (a["admitted"], a["unavailable"], a["row_written"]) == (True, "rate_limit_reached", False)


# --------------------------------------------------------------------------- #
# admit() decisions carry the Claude fallback — J8
# --------------------------------------------------------------------------- #
def test_use_fallback_role_table_is_exact():
    """RE-POINTED by S081 revision 4 WP-A3 (design §2.2, the four new uses): a review falls
    back to the reviewer seat, a consultancy / tournament / ballot / avengers seat to the
    consultancy seat, a diagnosis to escalation. The set assertion below is what makes the
    vocabularies land together — a new use with no Claude seat fails here."""
    assert dict(cq.USE_FALLBACK_ROLE) == {
        "audit": "code_reviewer", "advisory_review": "code_reviewer",
        "review_std": "code_reviewer", "consult": "consultant_main",
        "challenger": "consultant_main", "brainstorm": "consultant_main",
        "ballot": "consultant_main", "deliberation": "consultant_main",
        "diagnosis": "escalation",
        # The astra reserve (roster rev 4): escalation's own use, the Sol -> TOP retry and the
        # exhausted-loop review. A retry stands in for the seat it retries (all Claude main tier).
        "escalation": "escalation", "exhausted_review": "escalation", "top_retry": "consultant_main"}
    assert set(cq.USE_FALLBACK_ROLE) == set(cq.USES) - {"trial"}


@pytest.mark.parametrize("use", ["audit", "advisory_review", "consult", "challenger", "diagnosis"])
def test_every_non_trial_decision_carries_the_claude_fallback(sessions, tmp_path, use):
    import seat_model  # type: ignore

    closing_rollout(sessions, 10.0, 3.0)
    first = _admit(use, "c1", sessions, tmp_path)
    second = _admit(use, "c1", sessions, tmp_path)  # refused budget_spent (audit: admitted again)
    assert first["admitted"] is True
    assert second["admitted"] is (use == "audit")
    role = cq.USE_FALLBACK_ROLE[use]
    expected = {"provider": "claude", "role": role, "model": seat_model.resolve(role, "claude").model}
    assert expected["model"] and not expected["model"].lower().startswith("gpt-")
    for d in (first, second):
        assert d["fallback"] == expected
        assert "fallback_error" not in d
    # The fallback is a decision key only; the budget rows keep their shape.
    assert all("fallback" not in row for row in read_rows(budget(tmp_path)))


def test_refused_decisions_carry_the_fallback_too(sessions, tmp_path):
    signal_rollout(sessions, "quota_exhausted")
    d = _admit("challenger", "c1", sessions, tmp_path)
    assert d["admitted"] is False
    assert (d["fallback"]["provider"], d["fallback"]["role"]) == ("claude", "consultant_main")
    assert d["fallback"]["model"]


def test_trial_decisions_carry_a_null_fallback(sessions, tmp_path):
    closing_rollout(sessions, 10.0, 10.0)
    admitted = _admit("trial", "c1", sessions, tmp_path)
    assert admitted["admitted"] is True and admitted["fallback"] is None
    closing_rollout(sessions, 50.0, 10.0, name="rollout-2026-09-14T15-10-00-bbbb.jsonl", age=10.0)
    refused = _admit("trial", "c1", sessions, tmp_path)
    assert (refused["admitted"], refused["reason"], refused["fallback"]) == (False, "trial_threshold", None)
    signal_rollout(sessions, "rate_limit_reached", name="rollout-2026-09-14T15-20-00-cccc.jsonl", age=5.0)
    unavailable = _admit("trial", "c1", sessions, tmp_path)
    assert (unavailable["reason"], unavailable["fallback"]) == ("rate_limit_reached", None)
    assert all("fallback_error" not in d for d in (admitted, refused, unavailable))


def test_fallback_import_failure_yields_a_null_model_and_an_error(sessions, tmp_path, monkeypatch):
    closing_rollout(sessions, 10.0, 3.0)
    monkeypatch.setitem(sys.modules, "seat_model", None)  # `import seat_model` now raises
    d = _admit("consult", "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"]) == (True, "within_budget")
    assert d["fallback"] == {"provider": "claude", "role": "consultant_main", "model": None}
    assert "ModuleNotFoundError" in d["fallback_error"] or "ImportError" in d["fallback_error"]
    # CONTROL: import restored -> the model resolves again.
    monkeypatch.delitem(sys.modules, "seat_model")
    ok = _admit("challenger", "c1", sessions, tmp_path)
    assert ok["fallback"]["model"] and "fallback_error" not in ok


def test_fallback_resolution_failure_yields_a_null_model_and_an_error(sessions, tmp_path, monkeypatch):
    import seat_model  # type: ignore

    def _broken(*a, **k):
        raise seat_model.SeatModelError("role table unreadable")

    closing_rollout(sessions, 10.0, 3.0)
    monkeypatch.setattr(seat_model, "resolve", _broken)
    d = _admit("audit", "c1", sessions, tmp_path)
    assert d["admitted"] is True
    assert d["fallback"] == {"provider": "claude", "role": "code_reviewer", "model": None}
    assert "role table unreadable" in d["fallback_error"]


def test_fallback_never_accepts_a_codex_model(sessions, tmp_path, monkeypatch):
    """Defense in depth: even a resolver bug that hands back a gpt- slug is not a fallback."""
    import seat_model  # type: ignore

    real = seat_model.resolve

    def _sol(role, provider, **k):
        pin = real(role, provider, **k)
        return seat_model.SeatPin(model="gpt-5.6-sol", effort=None, timeout=pin.timeout,
                                  argv_fragment=pin.argv_fragment, provenance=pin.provenance)

    closing_rollout(sessions, 10.0, 3.0)
    monkeypatch.setattr(seat_model, "resolve", _sol)
    d = _admit("consult", "c1", sessions, tmp_path)
    assert d["fallback"]["model"] is None and "gpt-5.6-sol" in d["fallback_error"]


def test_cli_admit_output_carries_the_fallback(fixture_home, project):
    r = _cli(["admit", "--use", "consult", "--cycle-id", "cli-fb", "--project-root", str(project)],
             fixture_home, project)
    assert r.returncode == 0, r.stderr
    decision = json.loads(r.stdout)
    assert (decision["fallback"]["provider"], decision["fallback"]["role"]) == ("claude", "consultant_main")
    assert decision["fallback"]["model"] and "fallback_error" not in decision


# --------------------------------------------------------------------------- #
# classify_codex_failure() — J9
# --------------------------------------------------------------------------- #
BANNER = "OpenAI Codex v0.154.0\n--------\nmodel: gpt-5.6-sol\nsession id: 01a0a02a-bdf9-7281\n--------\nuser\n"
CLASSIFY_TABLE = [
    # (returncode, stderr, timed_out, output_ok, attempt) -> (action, reason)
    ((0, BANNER, False, True, 1), ("ok", None)),
    ((0, BANNER, False, True, 2), ("ok", None)),
    ((None, BANNER, True, False, 1), ("retry", "timeout")),
    ((None, BANNER, True, False, 2), ("substitute", "timeout_twice")),
    ((124, BANNER, True, False, 3), ("substitute", "timeout_twice")),
    ((0, BANNER, False, False, 1), ("retry", "malformed")),
    ((0, BANNER, False, False, 2), ("substitute", "malformed_twice")),
    ((127, "bash: codex: command not found\n", False, False, 1), ("substitute", "cli_missing")),
    ((1, BANNER + "ERROR: exceeded retry limit, last status: 429 Too Many Requests\n", False, False, 1),
     ("substitute", "quota_exhausted")),
    ((1, BANNER + "ERROR: 429 Too Many Requests\n", False, False, 1), ("substitute", "quota_exhausted")),
    ((1, BANNER + "ERROR: You've hit your usage limit. Upgrade to Plus to continue using Codex\n", False, False, 1),
     ("substitute", "quota_exhausted")),
    # INVERTED by #282 R2 (a signal counts only on a codex error line, or with meter agreement): a
    # bare "stream error: ..." line is not codex-owned -> gap. Carried forward on an ERROR line.
    ((1, BANNER + "stream error: rate limit exceeded: try again later\n", False, False, 1),
     ("gap", "codex_error")),
    ((1, BANNER + "ERROR: stream error: rate limit exceeded: try again later\n", False, False, 1),
     ("substitute", "quota_exhausted")),
    # INVERTED by #282 R2: the bare JSON line -> gap; carried forward on an ERROR line.
    ((1, BANNER + '{"rate_limit_reached_type": "primary"}\n', False, False, 1), ("gap", "codex_error")),
    ((1, BANNER + 'ERROR: {"rate_limit_reached_type": "primary"}\n', False, False, 1),
     ("substitute", "quota_exhausted")),
    ((1, BANNER + '{"rate_limit_reached_type": null}\n', False, False, 1), ("gap", "codex_error")),
    ((1, BANNER + "ERROR: Your access token could not be refreshed because your refresh token has expired. "
                  "Please log out and sign in again.\n", False, False, 1), ("substitute", "auth_failure")),
    ((1, BANNER + "ERROR: Your access token could not be refreshed. Please log out and sign in again.\n",
      False, False, 1), ("substitute", "auth_failure")),
    # INVERTED by #282 R2: a bare "Not logged in" line -> gap; carried forward on an ERROR line.
    ((1, "Not logged in\n", False, False, 1), ("gap", "codex_error")),
    ((1, "ERROR: Not logged in\n", False, False, 1), ("substitute", "auth_failure")),
    ((1, BANNER + "ERROR: unexpected status 401 Unauthorized: {}\n", False, False, 1),
     ("substitute", "auth_failure")),
    ((2, "error: unexpected argument '--bogus' found\n", False, False, 1), ("gap", "codex_error")),
    ((1, BANNER + "ERROR: stream disconnected before completion\n", False, False, 1), ("gap", "codex_error")),
    ((-9, "", False, False, 1), ("gap", "codex_error")),
    ((None, "", False, False, 1), ("gap", "codex_error")),
    # A retried 429 that still returned usable output did not stop the call.
    ((0, BANNER + "exceeded retry limit, last status: 429\n", False, True, 1), ("ok", None)),
    # A quota signal on a timed-out call substitutes at once: a same-model retry is doomed.
    # INVERTED by #282 R2: on a bare line it is no signal, so the timeout retries; carried forward
    # on an ERROR line, where it still substitutes at once.
    ((None, BANNER + "last status: 429\n", True, False, 1), ("retry", "timeout")),
    ((None, BANNER + "ERROR: exceeded retry limit, last status: 429\n", True, False, 1),
     ("substitute", "quota_exhausted")),
    # #282 classifier vocabulary: "Quota exceeded" is a quota stop; a model at capacity retries once.
    ((1, BANNER + "ERROR: Quota exceeded. Check your plan and billing details.\n", False, False, 1),
     ("substitute", "quota_exhausted")),
    ((1, BANNER + "ERROR: Selected model is at capacity. Please try a different model.\n", False, False, 1),
     ("retry", "capacity")),
    ((1, BANNER + "ERROR: Selected model is at capacity. Please try a different model.\n", False, False, 2),
     ("substitute", "capacity_twice")),
    ((0, BANNER + "ERROR: Selected model is at capacity. Please try a different model.\n", False, True, 1),
     ("ok", None)),
    # The tracing shape (the #282 probe fixture's 401).
    ((1, "2026-09-15T16:56:37.647031Z ERROR codex_api::endpoint::responses_websocket: failed to connect to "
         "websocket: HTTP error: 401 Unauthorized, url: wss://api.openai.com/v1/responses\n", False, False, 1),
     ("substitute", "auth_failure")),
]


@pytest.mark.parametrize("args,expected", CLASSIFY_TABLE)
def test_classify_codex_failure_table(args, expected):
    rc, stderr, timed_out, output_ok, attempt = args
    assert cq.classify_codex_failure(rc, stderr, timed_out=timed_out, output_ok=output_ok,
                                     attempt=attempt) == expected


PROMPT = ("You are a cold-context reviewer. Evidence bundle follows.\n"
          "log: exceeded retry limit, last status: 429\n"
          "log: Your access token could not be refreshed. Please log out and sign in again.\n"
          "log: rate_limit_reached_type: primary\n")


def test_classify_ignores_signals_inside_the_prompt_echo():
    stderr = BANNER + PROMPT + "\nERROR: stream disconnected before completion\n"
    assert cq.classify_codex_failure(1, stderr, timed_out=False, output_ok=False, attempt=1,
                                     prompt=PROMPT) == ("gap", "codex_error")


def test_classify_a_real_signal_outside_the_prompt_echo_still_counts():
    """CONTROL for the echo guard: the same stderr plus a genuine 429 after the echo."""
    stderr = BANNER + PROMPT + "\nERROR: exceeded retry limit, last status: 429\n"
    assert cq.classify_codex_failure(1, stderr, timed_out=False, output_ok=False, attempt=1,
                                     prompt=PROMPT) == ("substitute", "quota_exhausted")
    # And without the prompt the echo itself would have been mistaken for a signal.
    # RE-POINTED by #282 R2: PROMPT's lines are bare ("log: ..."), so the echo reads as a stop only
    # when the meter agrees — then the guard is what keeps it out. Bare and uncorroborated -> gap.
    agreeing = {"codex_error_lines": [], "unavailable_token": "quota_exhausted"}
    assert cq.classify_codex_failure(1, BANNER + PROMPT, timed_out=False, output_ok=False,
                                     attempt=1, corroboration=agreeing) == ("substitute", "quota_exhausted")
    assert cq.classify_codex_failure(1, BANNER + PROMPT, timed_out=False, output_ok=False, attempt=1,
                                     prompt=PROMPT, corroboration=agreeing) == ("gap", "codex_error")
    assert cq.classify_codex_failure(1, BANNER + PROMPT, timed_out=False, output_ok=False,
                                     attempt=1) == ("gap", "codex_error")


def test_classify_prompt_echo_guard_tolerates_a_trailing_newline_difference():
    """A prompt read back through `$(cat file)` loses its trailing newlines."""
    stderr = BANNER + PROMPT.rstrip("\n") + "\nERROR: stream disconnected\n"
    assert cq.classify_codex_failure(1, stderr, timed_out=False, output_ok=False, attempt=1,
                                     prompt=PROMPT) == ("gap", "codex_error")


def test_classify_accepts_bytes_stderr():
    assert cq.classify_codex_failure(1, b"ERROR: 429 Too Many Requests\xff\n", timed_out=False,
                                     output_ok=False, attempt=1) == ("substitute", "quota_exhausted")


@pytest.mark.parametrize("attempt", [0, -1, True, "1", 1.0, None])
def test_classify_rejects_a_malformed_attempt(attempt):
    with pytest.raises(ValueError):
        cq.classify_codex_failure(1, "", timed_out=False, output_ok=False, attempt=attempt)


def test_classify_is_pure():
    """No file is opened, stat'ed or scanned and no socket is made: open(), os.stat, os.scandir and
    socket.socket are made to record and raise — with and without a corroboration object (#282 R2
    (e)). The patch is undone BEFORE any assertion, so a failure report can still read source files."""
    import builtins
    import socket

    touched = []

    def _no_io(*a, **k):
        touched.append(a)
        raise AssertionError("classify_codex_failure must do no I/O")

    results, corroborated, errors = [], [], []
    real_open, real_stat, real_scandir, real_socket = builtins.open, os.stat, os.scandir, socket.socket
    builtins.open, os.stat, os.scandir, socket.socket = _no_io, _no_io, _no_io, _no_io
    try:
        for args, _expected in CLASSIFY_TABLE:
            rc, stderr, timed_out, output_ok, attempt = args
            try:
                results.append(cq.classify_codex_failure(rc, stderr, timed_out=timed_out,
                                                         output_ok=output_ok, attempt=attempt))
                corroborated.append(cq.classify_codex_failure(
                    rc, stderr, timed_out=timed_out, output_ok=output_ok, attempt=attempt,
                    corroboration={"codex_error_lines": cq.codex_error_lines(stderr), "unavailable_token": None}))
            except BaseException as exc:  # noqa: BLE001 — reported after the patch is undone
                errors.append(repr(exc))
    finally:
        builtins.open, os.stat, os.scandir, socket.socket = real_open, real_stat, real_scandir, real_socket
    assert touched == [] and errors == []
    assert results == [expected for _args, expected in CLASSIFY_TABLE]
    # A corroboration carrying the same error lines and no token decides exactly what None decides.
    assert corroborated == results


def test_corroboration_for_reads_the_sessions_tree_once(sessions, monkeypatch):
    """#282 R2 (e): corroboration_for's only I/O is ONE unavailable() walk; its token is that walk's."""
    signal_rollout(sessions, "quota_exhausted")
    walks = []
    real_scan = cq._scan

    def _counting_scan(*a, **k):
        walks.append(a)
        return real_scan(*a, **k)

    monkeypatch.setattr(cq, "_scan", _counting_scan)
    stderr = BANNER + "log: You've hit your usage limit\nERROR: 429 Too Many Requests\n"
    c = cq.corroboration_for(stderr, sessions_dir=sessions, now=NOW)
    assert len(walks) == 1
    assert c == {"codex_error_lines": ["ERROR: 429 Too Many Requests"], "unavailable_token": "quota_exhausted"}
    # CONTROL: no sessions -> no token, still exactly one more walk.
    assert cq.corroboration_for(stderr, sessions_dir=sessions / "absent", now=NOW)["unavailable_token"] is None
    assert len(walks) == 2


def test_exhaustion_and_auth_signal_helpers_name_the_pattern():
    assert cq.exhaustion_signal("ERROR: You've hit your usage limit.") == "usage_limit"
    assert cq.exhaustion_signal("last status: 429") == "http_429"
    assert cq.exhaustion_signal("nothing here") is None
    assert cq.auth_signal("Please sign in again.") == "sign_in_again"
    assert cq.auth_signal("log: 429", prompt="log: 429") is None


def test_cli_classify_prints_action_and_reason(fixture_home, tmp_path):
    err = tmp_path / "stderr.txt"
    err.write_text(BANNER + "ERROR: exceeded retry limit, last status: 429\n", encoding="utf-8")
    r = _cli(["classify", "--exit-code", "1", "--attempt", "1", "--stderr-file", str(err)],
             fixture_home, tmp_path, {"PYTHONIOENCODING": "cp1252"})
    assert (r.returncode, r.stdout) == (0, "substitute quota_exhausted\n"), r.stderr


def test_cli_classify_output_file_decides_ok_or_malformed(fixture_home, tmp_path):
    out = tmp_path / "out.txt"
    out.write_text("A finding.\n", encoding="utf-8")
    base = ["classify", "--exit-code", "0", "--output-file", str(out)]
    assert _cli(base + ["--attempt", "1"], fixture_home, tmp_path).stdout == "ok -\n"
    out.write_text(" \n\n", encoding="utf-8")
    assert _cli(base + ["--attempt", "1"], fixture_home, tmp_path).stdout == "retry malformed\n"
    assert _cli(base + ["--attempt", "2"], fixture_home, tmp_path).stdout == "substitute malformed_twice\n"
    out.unlink()  # codex never wrote it
    assert _cli(base + ["--attempt", "1"], fixture_home, tmp_path).stdout == "retry malformed\n"
    # Without --output-file the output is not judged: exit 0 is ok.
    assert _cli(["classify", "--exit-code", "0", "--attempt", "1"], fixture_home, tmp_path).stdout == "ok -\n"


def test_cli_classify_timed_out(fixture_home, tmp_path):
    base = ["classify", "--exit-code", "124", "--timed-out"]
    assert _cli(base + ["--attempt", "1"], fixture_home, tmp_path).stdout == "retry timeout\n"
    assert _cli(base + ["--attempt", "2"], fixture_home, tmp_path).stdout == "substitute timeout_twice\n"


def test_cli_classify_prompt_file_guards_the_echo(fixture_home, tmp_path):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text(PROMPT, encoding="utf-8")
    err = tmp_path / "stderr.txt"
    err.write_text(BANNER + PROMPT + "\nERROR: stream disconnected\n", encoding="utf-8")
    base = ["classify", "--exit-code", "1", "--attempt", "1", "--stderr-file", str(err)]
    guarded = _cli(base + ["--prompt-file", str(prompt)], fixture_home, tmp_path)
    assert (guarded.returncode, guarded.stdout) == (0, "gap codex_error\n"), guarded.stderr
    # CONTROL: without the prompt file the echoed evidence reads as a quota stop.
    # RE-POINTED by #282 R2: PROMPT's lines are bare, so that needs an agreeing meter — a fresh
    # >= 99% reading under the fixture HOME, which the CLI reads once itself. Without it -> gap.
    assert _cli(base, fixture_home, tmp_path).stdout == "gap codex_error\n"
    _live_rollout(fixture_home, 99.5, 10.0)
    assert _cli(base, fixture_home, tmp_path).stdout == "substitute quota_exhausted\n"
    guarded = _cli(base + ["--prompt-file", str(prompt)], fixture_home, tmp_path)
    assert (guarded.returncode, guarded.stdout) == (0, "gap codex_error\n"), guarded.stderr


@pytest.mark.parametrize("args", [
    ["classify"],
    ["classify", "--attempt", "1"],
    ["classify", "--exit-code", "1"],
    ["classify", "--exit-code", "one", "--attempt", "1"],
    ["classify", "--exit-code", "1", "--attempt", "0"],
    ["classify", "--exit-code", "1", "--attempt", "1", "--stderr-file", "/nonexistent/stderr.txt"],
    ["classify", "--exit-code", "1", "--attempt", "1", "--prompt-file", "/nonexistent/prompt.txt"],
])
def test_cli_classify_usage_and_environment_errors_exit_three(fixture_home, tmp_path, args):
    r = _cli(args, fixture_home, tmp_path)
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
    assert r.stdout == ""
    assert "invalid choice: 'classify'" not in r.stderr  # the subcommand exists; the ARGS are wrong


def test_cli_classify_oversized_stderr_is_an_environment_error(tmp_path, monkeypatch, capsys):
    """A truncated read could leave half a prompt echo behind, so an over-cap file is exit 3,
    never a guess. In-process, with the cap lowered; CONTROL: exactly at the cap is read."""
    err = tmp_path / "stderr.txt"
    err.write_bytes(b"ERROR: 429 Too Many Requests\n" + b"x" * 35)  # 64 bytes
    argv = ["classify", "--exit-code", "1", "--attempt", "1", "--stderr-file", str(err)]
    monkeypatch.setattr(cq, "CLASSIFY_READ_BYTES", 63)
    assert cq.main(argv) == 3
    out = capsys.readouterr()
    assert out.out == "" and "larger than 63 bytes" in out.err
    monkeypatch.setattr(cq, "CLASSIFY_READ_BYTES", 64)
    assert cq.main(argv) == 0
    assert capsys.readouterr().out == "substitute quota_exhausted\n"


def test_cli_classify_writes_only_the_exhausted_record_under_home(fixture_home, tmp_path):
    """RE-POINTED by #322 fix round 1 (F1); was test_cli_classify_writes_nothing_under_home. A QUOTA stop now
    persists the account-wide exhausted-until record (~/.claude/state/codex-exhausted.json + its lock) and
    NOTHING else -- no budget store. CONTROL: a non-quota verdict still writes nothing."""
    err = tmp_path / "stderr.txt"
    err.write_text("ERROR: something else broke\n", encoding="utf-8")
    before = sorted(p.relative_to(fixture_home) for p in fixture_home.rglob("*"))
    r = _cli(["classify", "--exit-code", "1", "--attempt", "2", "--stderr-file", str(err)], fixture_home, tmp_path)
    assert r.stdout == "gap codex_error\n"
    assert sorted(p.relative_to(fixture_home) for p in fixture_home.rglob("*")) == before
    err.write_text("ERROR: 429 Too Many Requests\n", encoding="utf-8")
    r = _cli(["classify", "--exit-code", "1", "--attempt", "2", "--stderr-file", str(err)],
             fixture_home, tmp_path)
    assert r.stdout == "substitute quota_exhausted\n"
    state = Path(".claude") / "state"
    assert sorted(p.relative_to(fixture_home) for p in fixture_home.rglob("*")) == sorted(
        before + [Path(".claude"), state, state / "codex-exhausted.json", state / "codex-exhausted.json.lock"])
    record = cq.read_exhausted(path=fixture_home / state / "codex-exhausted.json")
    assert record["source"] == "classify" and record["reset_known"] is False   # 429 names no reset: the hold


# --------------------------------------------------------------------------- #
# #282 R2 — a stderr phrase is proof only on a codex-owned error line (or with meter agreement)
# --------------------------------------------------------------------------- #
#: The quota-free probe's stderr error lines (codex 0.154.0, 2026-09-15). Its "# " header records the
#: command, the capture date, the omitted non-error lines and the unobserved usage-limit line shape.
_PROBE_FIXTURE = _HERE / "fixtures" / "codex" / "exec-401-error-lines.txt"
_TRACING_401 = ("2026-09-15T16:56:37.647031Z ERROR codex_api::endpoint::responses_websocket: failed to connect "
                "to websocket: HTTP error: 401 Unauthorized, url: wss://api.openai.com/v1/responses")
_FALLBACK_WARNING = ("warning: Falling back from WebSockets to HTTPS transport. unexpected status 401 Unauthorized: "
                     "Missing bearer or basic authentication in header, url: wss://api.openai.com/v1/responses, "
                     "cf-ray: <CF_RAY>")


def _probe_lines():
    text = _PROBE_FIXTURE.read_text(encoding="utf-8")
    header = [line for line in text.splitlines() if line.startswith("# ")]
    body = [line for line in text.splitlines() if line and not line.startswith("# ")]
    return header, body


def _shapes(line):
    return [name for name, pattern in cq.CODEX_ERROR_LINE_PATTERNS if pattern.match(line)]


def test_r2_every_probe_fixture_line_matches_exactly_one_error_shape():
    """(a) The fixture pins both regexes: each body line is exactly one shape, both shapes occur, header
    lines are skipped, and the header records what the spec requires."""
    header, body = _probe_lines()
    assert body and all(len(_shapes(line)) == 1 for line in body), [line for line in body if len(_shapes(line)) != 1]
    assert {s for line in body for s in _shapes(line)} == {"error", "tracing"}
    assert all(_shapes(line) == [] for line in header)
    joined = "\n".join(header)
    for needle in ("codex-cli 0.154.0", "env -u OPENAI_API_KEY CODEX_HOME=$(mktemp -d)",
                   "The real 401 appears in the tracing form", "usage-limit ERROR LINE shape is NOT observed live"):
        assert needle in joined
    assert _TRACING_401 in body
    # Every body line is an error line as the classifier extracts it (header lines are not stderr).
    assert cq.codex_error_lines("\n".join(body)) == body
    # NEGATIVE CONTROL: the fallback warning the probe printed is not an error line.
    assert _shapes(_FALLBACK_WARNING) == [] and cq.codex_error_lines(_FALLBACK_WARNING) == []


def test_r2_the_probe_401_substitutes_auth_failure_on_either_shape():
    """(a) The tracing 401 line + exit 1 -> substitute auth_failure; so does the probe's whole stderr and its
    `ERROR: unexpected status 401` line. CONTROL: the same 401 on the non-error fallback warning -> gap."""
    _header, body = _probe_lines()
    for stderr in (_TRACING_401 + "\n", "\n".join(body) + "\n", [l for l in body if l.startswith("ERROR: unexpected")][0]):
        assert cq.classify_codex_failure(1, stderr, timed_out=False, output_ok=False, attempt=1) == (
            "substitute", "auth_failure")
    assert cq.classify_codex_failure(1, _FALLBACK_WARNING + "\n", timed_out=False, output_ok=False, attempt=1) == (
        "gap", "codex_error")


#: (phrase, the action/reason on a codex error line at attempt 1)
_R2_PHRASES = [
    ("You've hit your usage limit.", ("substitute", "quota_exhausted")),
    ("exceeded retry limit, last status: 429 Too Many Requests", ("substitute", "quota_exhausted")),
    ("Quota exceeded. Check your plan and billing details.", ("substitute", "quota_exhausted")),
    ("Selected model is at capacity. Please try a different model.", ("retry", "capacity")),
    ("Your access token could not be refreshed. Please sign in again.", ("substitute", "auth_failure")),
]


def _tool_output_forms(phrase):
    """The phrase as codex copies tool output onto stderr: plain, indented, inside a `cat` listing, after a
    mid-line "ERROR:" and on a lower-case "error:" line. None of them is a codex-owned error line."""
    return {
        "plain": BANNER + phrase + "\n",
        "indented": BANNER + "    " + phrase + "\n",
        "cat_listing": (BANNER + "exec\n/bin/bash -lc 'cat docs/incident.md' in /repo\n succeeded in 9ms:\n"
                        "# Incident\n" + phrase + "\nend of file\n"),
        "mid_line_error": BANNER + "log: ERROR: " + phrase + "\n",
        "lower_case_error": BANNER + "error: " + phrase + "\n",
    }


@pytest.mark.parametrize("phrase,on_error_line", _R2_PHRASES, ids=[p.split()[0] for p, _ in _R2_PHRASES])
def test_r2_a_phrase_in_tool_output_is_never_a_substitution(phrase, on_error_line):
    """(b) R2 NEGATIVE: each phrase inside tool output + exit 1 -> gap; + exit 0 with empty output on attempt 1
    -> retry malformed. Never substitute, never retry capacity. CONTROL: the same phrase on an `ERROR: ` line and
    on a tracing line -> the vocabulary's decision."""
    for form, stderr in _tool_output_forms(phrase).items():
        assert cq.classify_codex_failure(1, stderr, timed_out=False, output_ok=False, attempt=1) == (
            "gap", "codex_error"), form
        assert cq.classify_codex_failure(0, stderr, timed_out=False, output_ok=False, attempt=1) == (
            "retry", "malformed"), form
    tracing = "2026-09-15T16:56:37.647031Z ERROR codex_core::client: " + phrase + "\n"
    for stderr in (BANNER + "ERROR: " + phrase + "\n", BANNER + tracing, BANNER + "2026-09-15T16:56:37Z ERROR codex_x: "
                   + phrase + "\n"):
        assert cq.classify_codex_failure(1, stderr, timed_out=False, output_ok=False, attempt=1) == on_error_line


@pytest.mark.parametrize("line", [
    " ERROR: 429 Too Many Requests",                                    # leading space
    "Error: 429 Too Many Requests",                                     # case
    "ERROR:429 Too Many Requests",                                      # no space
    "2026-09-15 16:56:37Z ERROR codex_api: 429 Too Many Requests",       # not ISO-8601 T
    "2026-09-15T16:56:37.647031 ERROR codex_api: 429 Too Many Requests",  # no Z
    "2026-09-15T16:56:37Z WARN codex_api: 429 Too Many Requests",         # not ERROR
    "2026-09-15T16:56:37Z ERROR reqwest::client: 429 Too Many Requests",  # not a codex_ module
    "2026-09-15T16:56:37Z  ERROR codex_api: 429 Too Many Requests",       # two spaces
    "x\x0cERROR: 429 Too Many Requests",                                # a form feed is not a line break
])
def test_r2_near_miss_error_line_shapes_are_not_codex_owned(line):
    """The shapes are exact: each near miss is tool output (gap). CONTROL rows in the table above."""
    assert cq.codex_error_lines(line) == []
    assert cq.classify_codex_failure(1, line + "\n", timed_out=False, output_ok=False, attempt=1) == (
        "gap", "codex_error")


def test_r2_crlf_error_lines_still_count():
    """CONTROL for the line split: a Windows "\\r\\n" ending does not hide a codex error line."""
    stderr = "OpenAI Codex v0.154.0\r\nERROR: 429 Too Many Requests\r\n"
    assert cq.codex_error_lines(stderr) == ["ERROR: 429 Too Many Requests"]
    assert cq.classify_codex_failure(1, stderr, timed_out=False, output_ok=False, attempt=1) == (
        "substitute", "quota_exhausted")


@pytest.mark.parametrize("token", ["quota_exhausted", "rate_limit_reached"])
def test_r2_meter_agreement_lets_a_bare_exhaustion_phrase_count(token):
    """(c) A bare-line exhaustion phrase + an agreeing unavailable_token -> substitute quota_exhausted.
    CONTROLS: token None -> gap; an auth or capacity phrase + the token -> gap (no token exists for them);
    the token with no phrase -> gap; an unknown token string -> gap."""
    bare = BANNER + "log: You've hit your usage limit\n"
    agreeing = {"codex_error_lines": cq.codex_error_lines(bare), "unavailable_token": token}

    def classify(stderr, corroboration):
        return cq.classify_codex_failure(1, stderr, timed_out=False, output_ok=False, attempt=1,
                                         corroboration=corroboration)

    assert classify(bare, agreeing) == ("substitute", "quota_exhausted")
    assert classify(bare, dict(agreeing, unavailable_token=None)) == ("gap", "codex_error")
    assert classify(bare, dict(agreeing, unavailable_token="weird")) == ("gap", "codex_error")
    for phrase in ("Please sign in again.", "Selected model is at capacity"):
        stderr = BANNER + "log: " + phrase + "\n"
        assert classify(stderr, {"codex_error_lines": [], "unavailable_token": token}) == ("gap", "codex_error")
    assert classify(BANNER + "ERROR: stream disconnected\n",
                    {"codex_error_lines": ["ERROR: stream disconnected"], "unavailable_token": token}) == (
        "gap", "codex_error")
    # A token never turns a timeout or an empty answer into anything but its own retry.
    assert cq.classify_codex_failure(None, BANNER, timed_out=True, output_ok=False, attempt=1,
                                     corroboration={"codex_error_lines": [], "unavailable_token": token}) == (
        "retry", "timeout")


def test_r2_a_corroboration_line_that_is_not_an_error_line_adds_nothing():
    """The classifier re-checks the passed lines: a hand-built corroboration cannot smuggle tool output in.
    CONTROL: the same text as a real `ERROR: ` line counts."""
    stderr = BANNER + "log: You've hit your usage limit\n"
    smuggled = {"codex_error_lines": ["log: You've hit your usage limit"], "unavailable_token": None}
    assert cq.classify_codex_failure(1, stderr, timed_out=False, output_ok=False, attempt=1,
                                     corroboration=smuggled) == ("gap", "codex_error")
    real = {"codex_error_lines": ["ERROR: You've hit your usage limit"], "unavailable_token": None}
    assert cq.classify_codex_failure(1, stderr, timed_out=False, output_ok=False, attempt=1,
                                     corroboration=real) == ("substitute", "quota_exhausted")


@pytest.mark.parametrize("bad", [
    "not a mapping", ["ERROR: x"], {"codex_error_lines": []}, {"unavailable_token": None},
    {"codex_error_lines": "ERROR: 429", "unavailable_token": None},
    {"codex_error_lines": [b"ERROR: 429"], "unavailable_token": None},
    {"codex_error_lines": [], "unavailable_token": 7},
])
def test_r2_a_malformed_corroboration_is_a_caller_bug(bad):
    with pytest.raises(ValueError):
        cq.classify_codex_failure(1, "", timed_out=False, output_ok=False, attempt=1, corroboration=bad)


@pytest.mark.parametrize("stderr", [
    BANNER + "ERROR: Selected model is at capacity. Please try a different model.\n",
    "2026-09-15T16:56:37.647031Z ERROR codex_core::client: Selected model is at capacity.\n",
])
def test_r2_capacity_retries_once_then_substitutes_capacity_twice(stderr):
    """(d) Attempt 1 -> retry capacity; attempt 2 and later -> substitute capacity_twice, which the
    substitution vocabulary accepts. A capacity stop on a timed-out call is still the capacity retry."""
    def classify(attempt, **kw):
        return cq.classify_codex_failure(kw.pop("rc", 1), stderr, timed_out=kw.pop("timed_out", False),
                                         output_ok=False, attempt=attempt)

    assert classify(1) == ("retry", "capacity")
    assert classify(2) == ("substitute", "capacity_twice")
    assert classify(3) == ("substitute", "capacity_twice")
    assert classify(1, rc=None, timed_out=True) == ("retry", "capacity")
    assert "capacity_twice" in cq.SUBSTITUTION_REASONS and "capacity" not in cq.SUBSTITUTION_REASONS


def test_r2_a_prompt_echoing_an_error_line_is_removed_before_line_extraction():
    """(f) A prompt that itself contains `ERROR: 429 Too Many Requests` is echoed onto stderr: the echo is
    removed before the error lines are extracted -> gap. CONTROL: without the prompt that echoed line IS an
    error-line shape -> substitute. The existing prompt-echo tests above still pass unchanged."""
    prompt = "Review this log excerpt:\nERROR: 429 Too Many Requests\nand say whether the retry was right.\n"
    stderr = BANNER + prompt + "ERROR: stream disconnected before completion\n"
    assert cq.codex_error_lines(stderr, prompt) == ["ERROR: stream disconnected before completion"]
    assert cq.classify_codex_failure(1, stderr, timed_out=False, output_ok=False, attempt=1, prompt=prompt) == (
        "gap", "codex_error")
    assert cq.corroboration_for(stderr, prompt, sessions_dir=Path("/nonexistent-sessions"), now=NOW) == {
        "codex_error_lines": ["ERROR: stream disconnected before completion"], "unavailable_token": None}
    assert cq.classify_codex_failure(1, stderr, timed_out=False, output_ok=False, attempt=1) == (
        "substitute", "quota_exhausted")


def test_r2_cli_classify_reads_the_meter_for_a_bare_phrase(fixture_home, tmp_path):
    """(h) The CLI builds ONE corroboration itself: a bare-line phrase + a fresh >= 99% reading under the
    fixture HOME -> "substitute quota_exhausted". CONTROL: no sessions -> "gap codex_error"; the same phrase on
    an ERROR line needs no meter. The output format is unchanged."""
    err = tmp_path / "stderr.txt"
    err.write_text(BANNER + "log: You've hit your usage limit\n", encoding="utf-8")
    base = ["classify", "--exit-code", "1", "--attempt", "1", "--stderr-file", str(err)]
    assert _cli(base, fixture_home, tmp_path).stdout == "gap codex_error\n"
    _live_rollout(fixture_home, 99.5, 10.0)
    r = _cli(base, fixture_home, tmp_path)
    assert (r.returncode, r.stdout) == (0, "substitute quota_exhausted\n"), r.stderr
    capacity = tmp_path / "capacity.txt"
    capacity.write_text(BANNER + "ERROR: Selected model is at capacity. Please try a different model.\n",
                        encoding="utf-8")
    cap = ["classify", "--exit-code", "1", "--stderr-file", str(capacity)]
    assert _cli(cap + ["--attempt", "1"], fixture_home, tmp_path).stdout == "retry capacity\n"
    assert _cli(cap + ["--attempt", "2"], fixture_home, tmp_path).stdout == "substitute capacity_twice\n"


def test_r2_cli_classify_help_is_ascii_and_names_the_line_rule(fixture_home, tmp_path):
    """(h) The help prints under a cp1252 console and documents the rule, the capacity retry and the limits."""
    r = _cli(["classify", "--help"], fixture_home, tmp_path, {"PYTHONIOENCODING": "cp1252"})
    assert r.returncode == 0, r.stderr
    assert r.stdout.isascii() and cq._CLASSIFY_HELP.isascii()
    for needle in ("codex error line", "retry capacity", "capacity_twice", "Quota exceeded",
                   "meter", "unobserved", "forge"):
        assert needle in r.stdout, needle


def test_r2_cli_classify_reads_no_meter_for_a_successful_call(fixture_home, tmp_path, monkeypatch, capsys):
    """A call that succeeded builds no corroboration (in-process spy). CONTROL: a failed call builds one."""
    out = tmp_path / "out.txt"
    out.write_text("A finding.\n", encoding="utf-8")
    calls = []
    real = cq.corroboration_for
    monkeypatch.setattr(cq, "corroboration_for", lambda *a, **k: calls.append(a) or real(*a, **k))
    assert cq.main(["classify", "--exit-code", "0", "--attempt", "1", "--output-file", str(out)]) == 0
    assert capsys.readouterr().out == "ok -\n" and calls == []
    assert cq.main(["classify", "--exit-code", "1", "--attempt", "1"]) == 0
    assert capsys.readouterr().out == "gap codex_error\n" and len(calls) == 1


# --------------------------------------------------------------------------- #
# record_substitution() — substitution rows (J3 tags; D6 "every substitution recorded")
# --------------------------------------------------------------------------- #
SUBSTITUTION_ROW_KEYS = {
    "at", "kind", "cycle_id", "cycle_id_source", "cycle_id_file_age_s", "use", "substitute_for",
    "requested_model", "served_model", "role", "reason", "snapshot_state", "primary", "weekly",
    "prior_admitted_in_cycle",
    "admission_id",  # RE-POINTED by #282 r10 (K12): always present, the replaced admission's id or null
    # RE-POINTED by S081 revision 4 WP-A3 (design §2.1 "every ROW ... records size, size_source"):
    # WHICH SIZE of call was refused, plus `key` so every row in the store names its budget key
    # the same way. `requested_by` is conditional (a user request only) and is not in this set.
    "key", "size", "size_source"}


def _substitute(use, cycle, reason, tmp_path, sessions, **kw):
    kw.setdefault("project_root", tmp_path / "proj")
    kw.setdefault("budget_path", budget(tmp_path))
    kw.setdefault("role", "consultant_main")
    kw.setdefault("served_model", "fable")
    return cq.record_substitution(use, cycle, reason, now=NOW, sessions_dir=sessions, **kw)


def test_record_substitution_writes_a_full_row_that_is_never_counted(sessions, tmp_path, project):
    closing_rollout(sessions, 99.5, 3.0)  # RE-POINTED by #322: the threshold no longer refuses, so the refusal on its merits is a quota one.
    forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW - HOUR)
    cid = cq.cycle_id_for(project, now=NOW)
    refused = cq.admit("consult", cid, project_root=project, now=NOW, sessions_dir=sessions,
                       budget_path=budget(tmp_path))
    assert refused["reason"] == "quota_exhausted"
    result = _substitute("consult", cid, refused["reason"], tmp_path, sessions, project_root=project,
                         requested_model="gpt-6-astra")
    assert result["row_written"] is True and "error" not in result
    assert result["budget_path"] == str(budget(tmp_path))
    row = read_rows(budget(tmp_path))[-1]
    assert set(row) == SUBSTITUTION_ROW_KEYS
    assert row == {
        "at": "2026-09-14T15:33:20Z", "kind": "substitution", "cycle_id": CYCLE_UUID,
        "cycle_id_source": "cycle-id", "cycle_id_file_age_s": 3600, "use": "consult",
        "substitute_for": "codex", "requested_model": "gpt-6-astra", "served_model": "fable",
        "role": "consultant_main", "reason": "quota_exhausted", "snapshot_state": "fresh", "primary": 99.5,
        "weekly": 3.0, "prior_admitted_in_cycle": 0,
        "admission_id": None,  # RE-POINTED by #282 r10: an uncorrelated substitution names no admission
        # RE-POINTED by S081 revision 4 WP-A3: `key` mirrors cycle_id, and an UNSIZED caller
        # records the L7 rule-6 back-compat pair rather than leaving the size unrecorded.
        "key": CYCLE_UUID, "size": "complex", "size_source": "default"}
    assert {k: result[k] for k in SUBSTITUTION_ROW_KEYS} == row
    assert "admitted" not in row
    assert cq._count_admitted(budget(tmp_path), cid, "consult", None) == 0
    # The substitution did not spend the budget: a later admit in the same cycle is admitted.
    closing_rollout(sessions, 10.0, 3.0, name="rollout-2026-09-14T15-10-00-bbbb.jsonl", age=10.0)
    admitted = cq.admit("consult", cid, project_root=project, now=NOW, sessions_dir=sessions,
                        budget_path=budget(tmp_path))
    assert admitted["admitted"] is True
    # CONTROL: an admitted row IS counted.
    assert cq._count_admitted(budget(tmp_path), cid, "consult", None) == 1


def test_record_substitution_counts_prior_admitted_calls_in_the_cycle(sessions, tmp_path):
    closing_rollout(sessions, 10.0, 3.0)
    for use in ("consult", "challenger"):
        assert _admit(use, "c1", sessions, tmp_path)["admitted"] is True
    assert _admit("consult", "c1", sessions, tmp_path)["admitted"] is False  # budget_spent, not counted
    assert _admit("consult", "c-other", sessions, tmp_path)["admitted"] is True  # another cycle
    result = _substitute("consult", "c1", "budget_spent", tmp_path, sessions)
    assert result["prior_admitted_in_cycle"] == 2
    assert _substitute("consult", "c-new", "budget_spent", tmp_path, sessions)["prior_admitted_in_cycle"] == 0


@pytest.mark.parametrize("kwargs", [
    {"use": "trial"},
    {"use": "explore"},
    {"use": "AUDIT"},
    {"cycle_id": ""},
    {"cycle_id": None},
    {"reason": "felt_like_it"},
    {"reason": ""},
    {"reason": "trial_threshold"},
    {"role": "consultant_support"},
    {"role": "execution"},
    {"served_model": "gpt-5.6-sol"},
    {"served_model": "GPT-6-astra"},
    {"served_model": ""},
    {"served_model": None},
    {"served_model": "fable; rm -rf ~"},
    {"served_model": "a" * 129},
    {"requested_model": "gpt 6"},
    {"now": "noon"},
    {"project_root": None, "budget_path": None},
])
def test_record_substitution_caller_bugs_raise_and_write_nothing(sessions, tmp_path, kwargs):
    closing_rollout(sessions, 10.0, 3.0)
    args = {"use": "consult", "cycle_id": "c1", "reason": "budget_spent"}
    args.update({k: v for k, v in kwargs.items() if k in args})
    extra = {"project_root": tmp_path / "proj", "budget_path": budget(tmp_path), "role": "consultant_main",
             "served_model": "fable", "now": NOW, "sessions_dir": sessions}
    extra.update({k: v for k, v in kwargs.items() if k not in args})
    with pytest.raises(ValueError):
        cq.record_substitution(args["use"], args["cycle_id"], args["reason"], **extra)
    assert not budget(tmp_path).exists()


def test_record_substitution_trial_is_skipped_never_substituted(sessions, tmp_path):
    closing_rollout(sessions, 10.0, 3.0)
    with pytest.raises(ValueError, match="trial"):
        _substitute("trial", "c1", "rate_limit_reached", tmp_path, sessions)
    assert not budget(tmp_path).exists()


@pytest.mark.parametrize("served", ["fable", "opus", "sonnet", "claude-fable-5", "claude-opus-5-20260101"])
def test_record_substitution_accepts_claude_models(sessions, tmp_path, served):
    """CONTROL for the served_model refusals."""
    closing_rollout(sessions, 10.0, 3.0)
    assert _substitute("audit", "c1", "cli_missing", tmp_path, sessions, role="code_reviewer",
                       served_model=served)["row_written"] is True


@pytest.mark.parametrize("use", sorted({"audit", "advisory_review", "consult", "challenger", "diagnosis",
                                        "deliberation"}))
@pytest.mark.parametrize("reason", ["threshold", "budget_spent", "budget_store_unavailable",
                                    "rate_limit_reached", "quota_exhausted", "cli_missing", "auth_failure",
                                    "timeout_twice", "malformed_twice", "no_eligible_model",
                                    "capacity_twice"])  # #282 classifier vocabulary
def test_record_substitution_uses_and_reasons(sessions, tmp_path, use, reason):
    closing_rollout(sessions, 10.0, 3.0)
    # RE-POINTED by S081 revision 4 WP-A3: every use but the trial (design §2.2, L9).
    assert set(cq.SUBSTITUTION_USES) == {"audit", "advisory_review", "review_std", "consult",
                                         "challenger", "brainstorm", "ballot", "deliberation",
                                         "diagnosis",
                                         # the astra reserve (roster rev 4)
                                         "escalation", "top_retry", "exhausted_review"}
    r = _substitute(use, "c1", reason, tmp_path, sessions)
    assert (r["row_written"], r["use"], r["reason"]) == (True, use, reason)


def test_record_substitution_cycle_id_sources(sessions, tmp_path, project):
    closing_rollout(sessions, 10.0, 3.0)
    forge_file(project, "cycle-base", "abcdef0123\n")
    path = forge_file(project, "cycle-id", CYCLE_UUID + "\n", mtime=NOW - 60)
    fresh = _substitute("consult", cq.cycle_id_for(project, now=NOW), "budget_spent", tmp_path, sessions,
                        project_root=project)
    assert (fresh["cycle_id"], fresh["cycle_id_source"], fresh["cycle_id_file_age_s"]) == (CYCLE_UUID, "cycle-id", 60)
    # J3: a 25h-old cycle-id is aged out -> adhoc-base, its age recorded.
    os.utime(path, (NOW - 25 * HOUR, NOW - 25 * HOUR))
    aged = _substitute("consult", cq.cycle_id_for(project, now=NOW), "budget_spent", tmp_path, sessions,
                       project_root=project)
    assert (aged["cycle_id"], aged["cycle_id_source"], aged["cycle_id_file_age_s"]) == (
        "adhoc-20260914-abcdef0", "adhoc-base", 90000)
    path.unlink()
    (project / ".forge" / "cycle-base").unlink()
    nobase = _substitute("consult", cq.cycle_id_for(project, now=NOW), "budget_spent", tmp_path, sessions,
                         project_root=project)
    assert (nobase["cycle_id_source"], nobase["cycle_id_file_age_s"]) == ("adhoc-nobase", None)
    explicit = _substitute("consult", "caller-chosen", "budget_spent", tmp_path, sessions, project_root=project)
    assert (explicit["cycle_id_source"], explicit["cycle_id_file_age_s"]) == ("explicit", None)
    rootless = _substitute("consult", "c9", "budget_spent", tmp_path, sessions, project_root=None)
    assert (rootless["cycle_id_source"], rootless["cycle_id_file_age_s"]) == ("explicit", None)
    rows = read_rows(budget(tmp_path))
    assert [r["cycle_id_source"] for r in rows] == ["cycle-id", "adhoc-base", "adhoc-nobase", "explicit", "explicit"]
    assert all(set(r) == SUBSTITUTION_ROW_KEYS for r in rows)


def test_record_substitution_default_budget_path_is_under_the_project_slug(sessions, fixture_home, project):
    closing_rollout(sessions, 10.0, 3.0)
    r = cq.record_substitution("consult", "c1", "budget_spent", project_root=project, role="consultant_main",
                               served_model="fable", now=NOW, sessions_dir=sessions)
    expected = fixture_home / ".claude" / "projects" / cq.project_slug(project) / "astra-budget.jsonl"
    assert r["budget_path"] == str(expected) and len(read_rows(expected)) == 1


def test_record_substitution_store_failure_never_raises(sessions, broken_budget):
    closing_rollout(sessions, 10.0, 3.0)
    r = cq.record_substitution("audit", "c1", "cli_missing", project_root=broken_budget.parent,
                               role="code_reviewer", served_model="fable", now=NOW, sessions_dir=sessions,
                               budget_path=broken_budget)
    assert r["row_written"] is False and r["error"]
    assert r["prior_admitted_in_cycle"] is None


def test_record_substitution_unknown_snapshot_is_recorded_as_such(tmp_path):
    r = cq.record_substitution("consult", "c1", "cli_missing", project_root=tmp_path, role="consultant_main",
                               served_model="fable", now=NOW, sessions_dir=tmp_path / "no-sessions",
                               budget_path=budget(tmp_path))
    assert (r["row_written"], r["snapshot_state"], r["primary"], r["weekly"]) == (True, "unknown", None, None)


# --------------------------------------------------------------------------- #
# No socket, no subprocess — the WP-F01 surface
# --------------------------------------------------------------------------- #
def test_f01_surface_opens_no_socket_and_spawns_no_process(sessions, tmp_path, project, monkeypatch):
    import socket

    signal_rollout(sessions, "rate_limit_reached")
    calls = []

    def _boom(*a, **k):
        calls.append(a)
        raise AssertionError("codex_quota must not touch the network or spawn a process")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    # Re-import seat_model / codex_model under the patch, so the lazy fallback import is covered too.
    monkeypatch.delitem(sys.modules, "seat_model", raising=False)
    monkeypatch.delitem(sys.modules, "codex_model", raising=False)

    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "rate_limit_reached"
    d = cq.admit("consult", "c1", project_root=project, now=NOW, sessions_dir=sessions)
    assert (d["reason"], d["fallback"]["role"]) == ("rate_limit_reached", "consultant_main")
    assert d["fallback"]["model"], d.get("fallback_error")
    a = cq.admit("audit", "c1", project_root=project, now=NOW, sessions_dir=sessions)
    assert (a["admitted"], a["unavailable"]) == (True, "rate_limit_reached")
    # RE-POINTED by #282 R2: the signal is carried on an ERROR line; the bare form is now a gap.
    assert cq.classify_codex_failure(1, "ERROR: 429 Too Many Requests", timed_out=False, output_ok=False,
                                     attempt=1) == ("substitute", "quota_exhausted")
    assert cq.classify_codex_failure(1, "429 Too Many Requests", timed_out=False, output_ok=False,
                                     attempt=1) == ("gap", "codex_error")
    corroboration = cq.corroboration_for("429 Too Many Requests", sessions_dir=sessions, now=NOW)
    assert corroboration["unavailable_token"] == "rate_limit_reached"
    assert cq.classify_codex_failure(1, "429 Too Many Requests", timed_out=False, output_ok=False, attempt=1,
                                     corroboration=corroboration) == ("substitute", "quota_exhausted")
    r = cq.record_substitution("consult", "c1", d["reason"], project_root=project, role="consultant_main",
                               served_model=d["fallback"]["model"], now=NOW, sessions_dir=sessions)
    assert r["row_written"] is True
    assert calls == []


# --------------------------------------------------------------------------- #
# Concurrency — substitution and admit appenders in real processes
# --------------------------------------------------------------------------- #
_MIXED_WORKER = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, sys.argv[1])
    import codex_quota as cq
    kind, cycle_prefix, n, budget, sessions, now, start_at = sys.argv[2:9]
    delay = float(start_at) - time.time()
    if delay > 0:
        time.sleep(delay)
    for i in range(int(n)):
        if kind == "substitution":
            cq.record_substitution("consult", f"{cycle_prefix}-{i}", "budget_spent", project_root=sys.argv[1],
                                   role="consultant_main", served_model="fable", now=float(now),
                                   sessions_dir=sessions, budget_path=budget)
        else:
            cq.admit(kind, f"{cycle_prefix}-{i}", project_root=sys.argv[1], now=float(now),
                     sessions_dir=sessions, budget_path=budget)
""")


def test_concurrent_substitution_and_admit_appenders_produce_an_exact_row_count(sessions, tmp_path):
    import time

    closing_rollout(sessions, 10.0, 3.0)
    script = tmp_path / "mixed_worker.py"
    script.write_text(_MIXED_WORKER, encoding="utf-8")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    start_at = str(time.time() + 1.5)
    procs = [subprocess.Popen([sys.executable, str(script), str(_META), kind, prefix, "120",
                               str(budget(tmp_path)), str(sessions), str(NOW), start_at],
                              cwd=str(tmp_path), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
             for kind, prefix in (("substitution", "sub"), ("consult", "adm"))]
    for p in procs:
        _out, err = p.communicate(timeout=180)
        assert p.returncode == 0, err.decode("utf-8", "replace")
    raw = budget(tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(raw) == 240
    rows = [json.loads(line) for line in raw]  # every line is one whole row
    subs = [r for r in rows if r.get("kind") == "substitution"]
    admits = [r for r in rows if "admitted" in r]
    assert (len(subs), len(admits)) == (120, 120)
    assert all(set(r) == SUBSTITUTION_ROW_KEYS for r in subs)
    assert all(r["admitted"] is True for r in admits)


# =========================================================================== #
# #282 R5 — a reached limit expires at its reset
# =========================================================================== #
_FUTURE = int(NOW + 3 * HOUR)
_PAST = int(NOW - 1)


def reached_event(observed, reached_type, *, primary_resets, secondary_resets, primary=True, secondary=True):
    """One rate_limits object carrying `reached_type`, its windows resetting at the given times
    (a reset of None = a window object whose resets_at is null; primary/secondary False = a
    null window, as on a session-closing entry)."""
    event = rl_event(observed, 40.0 if primary else None, 10.0 if secondary else None,
                     reached_type=reached_type)
    rate_limits = event["payload"]["rate_limits"]
    if primary:
        rate_limits["primary"]["resets_at"] = primary_resets
    if secondary:
        rate_limits["secondary"]["resets_at"] = secondary_resets
    return event


def write_reached(sessions_root, reached_type, *, age=60.0, **kw):
    return write_rollout(sessions_root, "2026/09/14", "rollout-2026-09-14T15-00-00-reached.jsonl",
                         [reached_event(NOW - age, reached_type, **kw)])


def _unavailable(sessions):
    return cq.unavailable(sessions_dir=sessions, now=NOW)


@pytest.mark.parametrize("reached_type,primary,secondary,expected", [
    ("primary", 100, 200, 100),
    ("primary", None, 200, 200),       # a null named reset falls back to the other
    ("primary", 300, None, 300),
    ("secondary", 100, 200, 200),
    ("secondary", 100, None, 100),     # a null named reset falls back to the other
    ("weird", 300, 200, 200),          # unrecognised -> the earliest
    ("Primary", 100, 50, 50),          # the vocabulary is exact: case differs -> unrecognised
    (True, 100, 200, 100),
    ({"x": 1}, None, 50, 50),
    ("primary", None, None, None),     # both null -> the age bound alone
    ("weird", None, None, None),
])
def test_r5_void_time_table(reached_type, primary, secondary, expected):
    assert cq._reached_void_at(reached_type, primary, secondary) == expected


@pytest.mark.parametrize("reset", [int(NOW + 1), _FUTURE])
def test_r5_a_primary_type_counts_before_primary_resets_at(sessions, reset):
    write_reached(sessions, "primary", primary_resets=reset, secondary_resets=_FUTURE)
    assert _unavailable(sessions) == "rate_limit_reached"


@pytest.mark.parametrize("offset", [0, -1, -HOUR])
def test_r5_a_primary_type_is_void_at_and_after_primary_resets_at(sessions, offset):
    write_reached(sessions, "primary", primary_resets=int(NOW + offset), secondary_resets=_FUTURE)
    assert _unavailable(sessions) is None


def test_r5_a_past_secondary_reset_does_not_void_a_primary_type(sessions):
    """CONTROL: "primary" voids at primary_resets_at, not at the other window's reset."""
    write_reached(sessions, "primary", primary_resets=_FUTURE, secondary_resets=_PAST)
    assert _unavailable(sessions) == "rate_limit_reached"


@pytest.mark.parametrize("reset", [int(NOW + 1), _FUTURE])
def test_r5_a_secondary_type_counts_before_secondary_resets_at(sessions, reset):
    write_reached(sessions, "secondary", primary_resets=_FUTURE, secondary_resets=reset)
    assert _unavailable(sessions) == "rate_limit_reached"


@pytest.mark.parametrize("offset", [0, -1, -HOUR])
def test_r5_a_secondary_type_is_void_at_and_after_secondary_resets_at(sessions, offset):
    write_reached(sessions, "secondary", primary_resets=_FUTURE, secondary_resets=int(NOW + offset))
    assert _unavailable(sessions) is None


def test_r5_a_past_primary_reset_does_not_void_a_secondary_type(sessions):
    """CONTROL: "secondary" voids at secondary_resets_at, not at the other window's reset."""
    write_reached(sessions, "secondary", primary_resets=_PAST, secondary_resets=_FUTURE)
    assert _unavailable(sessions) == "rate_limit_reached"


@pytest.mark.parametrize("value", ["weird", True, {"x": 1}, ["primary"], "Primary", 7])
def test_r5_an_unrecognised_type_voids_at_the_earliest_reset(sessions, value):
    write_reached(sessions, value, primary_resets=_PAST, secondary_resets=_FUTURE)
    assert _unavailable(sessions) is None
    write_reached(sessions, value, primary_resets=_FUTURE, secondary_resets=_PAST)
    assert _unavailable(sessions) is None
    # CONTROL: the later reset alone would still count — the same object typed by that window.
    write_reached(sessions, "secondary", primary_resets=_PAST, secondary_resets=_FUTURE)
    assert _unavailable(sessions) == "rate_limit_reached"
    # CONTROL: both resets in the future, the unrecognised value still counts.
    write_reached(sessions, value, primary_resets=_FUTURE, secondary_resets=_FUTURE + int(HOUR))
    assert _unavailable(sessions) == "rate_limit_reached"


def test_r5_a_null_named_reset_falls_back_to_the_other_reset(sessions):
    write_reached(sessions, "primary", primary_resets=None, secondary_resets=_PAST)
    assert _unavailable(sessions) is None
    write_reached(sessions, "primary", primary_resets=None, secondary_resets=_FUTURE)
    assert _unavailable(sessions) == "rate_limit_reached"                     # CONTROL
    write_reached(sessions, "secondary", primary_resets=_PAST, secondary_resets=None)
    assert _unavailable(sessions) is None
    write_reached(sessions, "secondary", primary_resets=_FUTURE, secondary_resets=None)
    assert _unavailable(sessions) == "rate_limit_reached"                     # CONTROL
    # A NULL WINDOW (primary: null, as on a closing entry) is a null reset too.
    write_reached(sessions, "primary", primary=False, primary_resets=None, secondary_resets=_PAST)
    assert _unavailable(sessions) is None
    write_reached(sessions, "primary", primary=False, primary_resets=None, secondary_resets=_FUTURE)
    assert _unavailable(sessions) == "rate_limit_reached"                     # CONTROL


def test_r5_both_resets_null_leaves_the_age_bound_alone(sessions):
    write_reached(sessions, "primary", primary_resets=None, secondary_resets=None, age=60.0)
    assert _unavailable(sessions) == "rate_limit_reached"
    # CONTROL: 31 minutes old -> the age bound voids it.
    write_reached(sessions, "primary", primary_resets=None, secondary_resets=None, age=31 * 60.0)
    assert _unavailable(sessions) is None


def test_r5_the_age_bound_still_applies_inside_a_future_reset(sessions):
    write_reached(sessions, "primary", primary_resets=_FUTURE, secondary_resets=_FUTURE, age=31 * 60.0)
    assert _unavailable(sessions) is None
    write_reached(sessions, "primary", primary_resets=_FUTURE, secondary_resets=_FUTURE,
                  age=-(cq.FUTURE_SKEW_S + 60.0))
    assert _unavailable(sessions) is None
    # CONTROL: 29 minutes old, inside the same future reset -> it counts.
    write_reached(sessions, "primary", primary_resets=_FUTURE, secondary_resets=_FUTURE, age=29 * 60.0)
    assert _unavailable(sessions) == "rate_limit_reached"


def test_r5_a_voided_type_no_longer_refuses_admit(sessions, tmp_path):
    write_reached(sessions, "primary", primary_resets=_PAST, secondary_resets=_FUTURE)
    d = _admit("consult", "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"]) == (True, "within_budget") and "unavailable" not in d
    # CONTROL: before its reset the token refuses every use but audit.
    write_reached(sessions, "primary", primary_resets=_FUTURE, secondary_resets=_FUTURE)
    d = _admit("consult", "c2", sessions, tmp_path)
    assert (d["admitted"], d["reason"], d["unavailable"]) == (False, "rate_limit_reached", "rate_limit_reached")


# =========================================================================== #
# #282 R6 — the meter reads the newest reading, else says uncertain
# =========================================================================== #
FULL_SNAPSHOT_KEYS = {"state", "primary_used_percent", "primary_resets_at", "secondary_used_percent",
                      "secondary_resets_at", "observed_at", "source", "limit_id", "reason"}
TODAY = "2026/09/14"


def reading_rollout(sessions_root, day, name, primary, *, observed, mtime, weekly=10.0, **kw):
    """A rollout holding one reading observed at `observed`, its file mtime pinned to `mtime`."""
    path = write_rollout(sessions_root, day, name, [
        other_line(observed - 5), rl_event(observed, primary, weekly, **kw), premium_null(observed + 0.2)])
    return set_mtime(path, mtime)


def blank_rollout(sessions_root, day, name, *, mtime):
    """A rollout with no rate_limits object in it, its mtime pinned."""
    return set_mtime(write_rollout(sessions_root, day, name, [other_line(mtime - 1)]), mtime)


def _snap(sessions):
    return cq.snapshot(sessions_dir=sessions, now=NOW)


@pytest.fixture()
def pre_fr1_walk(monkeypatch):
    """The walk as it was before #322 fix round 1: exactly ROLLOUT_FILE_LIMIT rollouts tail-read, reading or
    not. The #282 R6 uncertainty tests build their unread newer candidate from reading-less rollouts, which
    the fixed walk reads (up to ROLLOUT_EMPTY_READ_LIMIT more); with this fixture the rule they pin (an
    unread newer candidate -> uncertain) is exercised on the same small fixture."""
    monkeypatch.setattr(cq, "ROLLOUT_EMPTY_READ_LIMIT", 0)


def test_r6_the_walk_constants():
    assert (cq.ROLLOUT_WINDOW_DAYS, cq.ROLLOUT_STAT_BUDGET, cq.ROLLOUT_FILE_LIMIT) == (7, 2000, 4)
    assert (cq.STATE_UNCERTAIN, cq.REASON_NEWER_CANDIDATE_UNREAD, cq.REASON_STAT_BUDGET_EXHAUSTED) == (
        "uncertain", "newer_candidate_unread", "stat_budget_exhausted")
    # DAY_DIR_LIMIT is kept for audit_spawn's own-rollout lookup, not the meter.
    assert cq.DAY_DIR_LIMIT == 3


def test_r6_spec_case_an_older_named_rollout_with_the_newest_mtime_wins(sessions):
    """Spec R6: four NEWER-named rollouts in today's directory at 20% with older mtimes, and one
    OLDER-named rollout in a directory four days old with the newest mtime and a fresh 100%."""
    for i in range(4):
        reading_rollout(sessions, TODAY, f"rollout-2026-09-14T15-2{i}-00-new.jsonl", 20.0,
                        observed=NOW - 300 + i * 10, mtime=NOW - 295 + i * 10)
    old = reading_rollout(sessions, "2026/09/10", "rollout-2026-09-10T08-00-00-old.jsonl", 100.0,
                          observed=NOW - 60, mtime=NOW - 30)
    snap = _snap(sessions)
    assert (snap["state"], snap["primary_used_percent"], snap["source"]) == ("fresh", 100.0, str(old))
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "quota_exhausted"
    # CONTROL: remove its mtime advantage (older than every other mtime and every reading) -> 20%.
    set_mtime(old, NOW - HOUR)
    snap = _snap(sessions)
    assert (snap["state"], snap["primary_used_percent"], snap["reason"]) == ("fresh", 20.0, None)
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None


def test_r6_only_the_newest_rollout_file_limit_by_mtime_are_tail_read(sessions, monkeypatch):
    paths = []
    for i in range(10):  # names ASCENDING with i, mtimes DESCENDING with i
        mtime = NOW - 100 - 10 * i
        paths.append(reading_rollout(sessions, TODAY, f"rollout-{i:02d}.jsonl", 10.0 + i,
                                     observed=mtime - 1, mtime=mtime))
    read = []
    real_scan_rollout = cq._scan_rollout

    def spy(path):
        read.append(path)
        return real_scan_rollout(path)

    monkeypatch.setattr(cq, "_scan_rollout", spy)
    snap = _snap(sessions)
    assert read == paths[:cq.ROLLOUT_FILE_LIMIT]          # newest mtime first, not newest name
    assert (snap["state"], snap["primary_used_percent"], snap["source"]) == ("fresh", 10.0, str(paths[0]))


def test_r6_equal_mtimes_rank_by_name_descending(sessions, monkeypatch):
    for i in range(5):
        reading_rollout(sessions, TODAY, f"rollout-{i}.jsonl", 10.0 + i, observed=NOW - 60 - i, mtime=NOW - 30)
    read = []
    real_scan_rollout = cq._scan_rollout
    monkeypatch.setattr(cq, "_scan_rollout", lambda path: (read.append(path.name), real_scan_rollout(path))[1])
    snap = _snap(sessions)
    assert read == ["rollout-4.jsonl", "rollout-3.jsonl", "rollout-2.jsonl", "rollout-1.jsonl"]
    # rollout-0 is unread and its mtime is later than every reading: uncertain, readings reported.
    assert (snap["state"], snap["reason"], snap["primary_used_percent"]) == (
        "uncertain", "newer_candidate_unread", 11.0)


@pytest.mark.parametrize("percent", [95.0, 99.5])
def test_r6_uncertain_when_an_unread_candidate_is_newer_than_the_chosen_reading(pre_fr1_walk, sessions, tmp_path, monkeypatch,
                                                                             percent):
    """Three of the four newest-by-mtime rollouts carry no usable reading; the fourth holds a
    reading observed 15 minutes ago; a fifth, UNREAD rollout was modified after that reading."""
    for i in range(3):
        blank_rollout(sessions, TODAY, f"rollout-blank-{i}.jsonl", mtime=NOW - 10 - i)
    chosen = reading_rollout(sessions, TODAY, "rollout-chosen.jsonl", percent, weekly=percent,
                             observed=NOW - 900, mtime=NOW - 20)
    fifth = reading_rollout(sessions, TODAY, "rollout-fifth.jsonl", percent, weekly=percent,
                            observed=NOW - 120, mtime=NOW - 100)
    snap = _snap(sessions)
    assert set(snap) == FULL_SNAPSHOT_KEYS
    assert (snap["state"], snap["reason"], snap["primary_used_percent"], snap["source"]) == (
        "uncertain", "newer_candidate_unread", percent, str(chosen))
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None             # never quota_exhausted
    consult = _admit("consult", "c1", sessions, tmp_path)
    assert (consult["admitted"], consult["reason"], consult["snapshot_state"]) == (True, "within_budget", "uncertain")
    trial = _admit("trial", "t1", sessions, tmp_path)
    assert (trial["admitted"], trial["reason"]) == (False, "trial_requires_fresh_snapshot")
    # CONTROL: read five files -> the fifth's newer reading is chosen and the snapshot is fresh.
    monkeypatch.setattr(cq, "ROLLOUT_FILE_LIMIT", 5)
    snap = _snap(sessions)
    assert (snap["state"], snap["reason"], snap["source"]) == ("fresh", None, str(fifth))
    exhausted = percent >= cq.EXHAUSTED_PERCENT
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == ("quota_exhausted" if exhausted else None)
    control = _admit("consult", "c2", sessions, tmp_path)
    # RE-POINTED by #322: a 95% fresh reading was a `threshold` refusal; now it is admitted.
    assert (control["admitted"], control["reason"]) == ((False, "quota_exhausted") if exhausted
                                                        else (True, "within_budget"))


def test_r6_an_older_unread_candidate_does_not_make_the_snapshot_uncertain(sessions):
    """CONTROL for the rule above: the fifth, unread rollout was last modified BEFORE the chosen
    reading was observed, so it cannot hold a newer one."""
    for i in range(3):
        blank_rollout(sessions, TODAY, f"rollout-blank-{i}.jsonl", mtime=NOW - 10 - i)
    reading_rollout(sessions, TODAY, "rollout-chosen.jsonl", 40.0, observed=NOW - 900, mtime=NOW - 20)
    blank_rollout(sessions, TODAY, "rollout-fifth.jsonl", mtime=NOW - 901)
    assert (_snap(sessions)["state"], _snap(sessions)["primary_used_percent"]) == ("fresh", 40.0)


def test_r6_uncertain_wins_over_the_chosen_readings_own_staleness(pre_fr1_walk, sessions):
    for i in range(3):
        blank_rollout(sessions, TODAY, f"rollout-blank-{i}.jsonl", mtime=NOW - 10 - i)
    reading_rollout(sessions, TODAY, "rollout-chosen.jsonl", 81.0, observed=NOW - 2400, mtime=NOW - 20)
    blank_rollout(sessions, TODAY, "rollout-fifth.jsonl", mtime=NOW - 100)
    snap = _snap(sessions)
    assert (snap["state"], snap["reason"], snap["primary_used_percent"]) == ("uncertain", "newer_candidate_unread", 81.0)
    # CONTROL: without the unread newer candidate the same reading is stale, too old.
    (sessions / TODAY / "rollout-fifth.jsonl").unlink()
    assert (_snap(sessions)["state"], _snap(sessions)["reason"]) == ("stale", "observed_too_long_ago")


def test_r6_an_unparseable_observation_is_older_than_every_unread_candidate(pre_fr1_walk, sessions):
    for i in range(3):
        blank_rollout(sessions, TODAY, f"rollout-blank-{i}.jsonl", mtime=NOW - 10 - i)
    path = write_rollout(sessions, TODAY, "rollout-chosen.jsonl", [rl_event(NOW - 60, 40.0, 3.0, timestamp=False)])
    set_mtime(path, NOW - 20)
    blank_rollout(sessions, TODAY, "rollout-fifth.jsonl", mtime=NOW - 5 * 24 * HOUR)
    snap = _snap(sessions)
    assert (snap["state"], snap["reason"], snap["observed_at"]) == ("uncertain", "newer_candidate_unread", None)
    # CONTROL: nothing unread -> stale, as before R6.
    (sessions / TODAY / "rollout-fifth.jsonl").unlink()
    assert (_snap(sessions)["state"], _snap(sessions)["reason"]) == ("stale", "observed_at_unparseable")


def test_r6_no_usable_reading_in_the_read_files_is_uncertain_when_candidates_are_left_unread(pre_fr1_walk, sessions):
    """RE-POINTED by #322 fix round 2 (N3); was `..._is_unknown_not_uncertain`, which pinned the defect: the walk
    stopped at its bound with a reading left unread, and `unknown` let admit() through while that reading could
    be an exhausted one. Nothing usable read + candidates left beyond the bound = `uncertain`."""
    for i in range(4):
        blank_rollout(sessions, TODAY, f"rollout-blank-{i}.jsonl", mtime=NOW - 10 - i)
    reading_rollout(sessions, TODAY, "rollout-unread.jsonl", 40.0, observed=NOW - 30, mtime=NOW - 100)
    snap = _snap(sessions)
    assert (snap["state"], snap["reason"], snap["primary_used_percent"]) == (
        "uncertain", "newer_candidate_unread", None)
    # CONTROL: nothing beyond the bound -> `unknown`, as before.
    (sessions / TODAY / "rollout-unread.jsonl").unlink()
    assert (_snap(sessions)["state"], _snap(sessions)["reason"]) == ("unknown", "no_rate_limits")


def _five_readings(sessions):
    for i in range(5):
        mtime = NOW - 600 + i * 60
        reading_rollout(sessions, TODAY, f"rollout-{i}.jsonl", 30.0 + i, observed=mtime - 5, mtime=mtime)


def test_r6_uncertain_when_the_stat_budget_runs_out(sessions, tmp_path, monkeypatch):
    _five_readings(sessions)
    monkeypatch.setattr(cq, "ROLLOUT_STAT_BUDGET", 3)
    snap = _snap(sessions)
    assert set(snap) == FULL_SNAPSHOT_KEYS
    # the three stat'ed are rollout-4, -3, -2 (names descending); the newest reading is reported
    assert (snap["state"], snap["reason"], snap["primary_used_percent"]) == ("uncertain", "stat_budget_exhausted", 34.0)
    assert _admit("trial", "t1", sessions, tmp_path)["reason"] == "trial_requires_fresh_snapshot"
    # CONTROL: a budget of 10 stats all five -> fresh.
    monkeypatch.setattr(cq, "ROLLOUT_STAT_BUDGET", 10)
    assert (_snap(sessions)["state"], _snap(sessions)["primary_used_percent"]) == ("fresh", 34.0)
    # BOUNDARY: a budget equal to the number of entries leaves nothing unstat'ed -> fresh.
    monkeypatch.setattr(cq, "ROLLOUT_STAT_BUDGET", 5)
    assert _snap(sessions)["state"] == "fresh"


def test_r6_the_stat_budget_counts_across_day_directories(sessions, monkeypatch):
    reading_rollout(sessions, TODAY, "rollout-a.jsonl", 20.0, observed=NOW - 65, mtime=NOW - 60)
    reading_rollout(sessions, TODAY, "rollout-b.jsonl", 21.0, observed=NOW - 55, mtime=NOW - 50)
    monkeypatch.setattr(cq, "ROLLOUT_STAT_BUDGET", 2)
    assert _snap(sessions)["state"] == "fresh"               # budget spent exactly, nothing left
    blank_rollout(sessions, "2026/09/13", "rollout-c.jsonl", mtime=NOW - 2 * HOUR)
    snap = _snap(sessions)
    assert (snap["state"], snap["reason"]) == ("uncertain", "stat_budget_exhausted")
    # CONTROL: a non-rollout file in the older directory is not a window entry.
    (sessions / "2026/09/13" / "rollout-c.jsonl").unlink()
    (sessions / "2026/09/13" / "notes.jsonl").write_text("{}\n", encoding="utf-8")
    assert _snap(sessions)["state"] == "fresh"


@pytest.mark.parametrize("days_old,visited", [(-1, True), (0, True), (7, True), (8, True), (9, False), (10, False)])
def test_r6_the_window_is_the_weekly_window_plus_one_day(sessions, monkeypatch, days_old, visited):
    day = (datetime.fromtimestamp(NOW, timezone.utc) - timedelta(days=days_old)).strftime("%Y/%m/%d")
    path = reading_rollout(sessions, day, "rollout-x.jsonl", 10.0, observed=NOW - 60, mtime=NOW - 30)
    scanned = []
    real_scandir = os.scandir

    def spy(target="."):
        scanned.append(Path(target))
        return real_scandir(target)

    monkeypatch.setattr(os, "scandir", spy)
    snap = _snap(sessions)
    monkeypatch.setattr(os, "scandir", real_scandir)
    assert ((sessions / day) in scanned) is visited          # outside the window: never listed, never stat'ed
    assert (snap["source"] == str(path)) is visited
    assert snap["state"] == ("fresh" if visited else "unknown")


def test_r6_the_window_never_raises_on_impossible_dates(sessions):
    write_rollout(sessions, "2026/02/31", "rollout-x.jsonl", [other_line(NOW - 50)])
    write_rollout(sessions, "2026/13/01", "rollout-x.jsonl", [other_line(NOW - 50)])
    reading_rollout(sessions, TODAY, "rollout-a.jsonl", 12.0, observed=NOW - 60, mtime=NOW - 30)
    assert (_snap(sessions)["state"], _snap(sessions)["primary_used_percent"]) == ("fresh", 12.0)


def test_r6_a_rollout_that_is_not_a_regular_file_is_not_a_candidate(sessions):
    (sessions / "2026" / "09" / "14" / "rollout-dir.jsonl").mkdir(parents=True)
    reading_rollout(sessions, TODAY, "rollout-a.jsonl", 12.0, observed=NOW - 60, mtime=NOW - 30)
    assert (_snap(sessions)["state"], _snap(sessions)["primary_used_percent"]) == ("fresh", 12.0)


def test_r6_the_walk_reads_no_content_of_an_unread_candidate(sessions, monkeypatch):
    for i in range(8):
        mtime = NOW - 100 - 10 * i
        reading_rollout(sessions, TODAY, f"rollout-{i}.jsonl", 10.0, observed=mtime - 1, mtime=mtime)
    opened = []
    real_tail = cq._tail_lines
    monkeypatch.setattr(cq, "_tail_lines", lambda path, limit: (opened.append(path.name), real_tail(path, limit))[1])
    _snap(sessions)
    assert opened == [f"rollout-{i}.jsonl" for i in range(cq.ROLLOUT_FILE_LIMIT)]


# =========================================================================== #
# #282 r9 — stale-but-unexpired readings are a lower bound
# =========================================================================== #
BUDGETED_USES = ["consult", "challenger", "advisory_review", "diagnosis"]


# #322 (2026-09-27): the r9 LOWER-BOUND rule refused `threshold` on a stale-by-age reading >= 70% whose
# window had not reset. With the threshold retired it has nothing left to refuse: the three tests that
# pinned it (test_r9_a_too_old_primary_reading_counts_while_its_window_has_not_reset,
# test_r9_a_too_old_weekly_reading_counts_while_its_window_has_not_reset, test_r9_boundaries) are
# INVERTED into the one below. Only a FRESH reading >= 99% refuses for quota (the CONTROL).
@pytest.mark.parametrize("use", BUDGETED_USES)
@pytest.mark.parametrize("primary,weekly,p_offset,w_offset", [
    (75.0, 10.0, HOUR, HOUR), (10.0, 75.0, HOUR, HOUR), (70.0, 70.0, 1, 1), (99.5, 99.5, HOUR, HOUR)])
def test_322_a_too_old_reading_never_refuses_whatever_it_reads(sessions, tmp_path, use, primary, weekly,
                                                               p_offset, w_offset):
    fresh_rollout(sessions, primary, weekly, age=2400.0, p_resets=int(NOW + p_offset), w_resets=int(NOW + w_offset))
    d = _admit(use, "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"], d["snapshot_state"]) == (True, "within_budget", "stale")
    # CONTROL: the same windows, read FRESH at 99.5%, refuse for quota.
    fresh_rollout(sessions, 99.5, weekly, age=60.0, p_resets=int(NOW + p_offset + HOUR),
                  w_resets=int(NOW + w_offset + HOUR))
    d = _admit(use, "c2", sessions, tmp_path)
    assert (d["admitted"], d["reason"]) == (False, "quota_exhausted")


def _other_stale(sessions, case):
    if case == "primary_window_reset":
        fresh_rollout(sessions, 75.0, 75.0, age=60.0, p_resets=_PAST)
    elif case == "secondary_window_reset":
        fresh_rollout(sessions, 75.0, 75.0, age=60.0, w_resets=_PAST)
    elif case == "observed_in_the_future":
        fresh_rollout(sessions, 75.0, 75.0, age=-(cq.FUTURE_SKEW_S + 60.0))
    elif case == "observed_at_unparseable":
        write_rollout(sessions, TODAY, "rollout-a.jsonl", [rl_event(NOW - 2400, 75.0, 75.0, timestamp=False)])
    elif case == "primary_resets_at_missing":
        event = rl_event(NOW - 60, 75.0, 10.0)  # the age check runs first, so it must be recent
        del event["payload"]["rate_limits"]["primary"]["resets_at"]
        write_rollout(sessions, TODAY, "rollout-a.jsonl", [event])


@pytest.mark.parametrize("use", BUDGETED_USES)
@pytest.mark.parametrize("case", ["primary_window_reset", "secondary_window_reset", "observed_in_the_future",
                                  "observed_at_unparseable", "primary_resets_at_missing"])
def test_r9_any_other_stale_reason_never_counts(sessions, tmp_path, use, case):
    _other_stale(sessions, case)
    snap = _snap(sessions)
    assert (snap["state"], snap["reason"]) == ("stale", case)
    d = _admit(use, "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"]) == (True, "within_budget")


@pytest.mark.parametrize("use", BUDGETED_USES)
def test_r9_an_uncertain_reading_never_counts(pre_fr1_walk, sessions, tmp_path, use):
    for i in range(3):
        blank_rollout(sessions, TODAY, f"rollout-blank-{i}.jsonl", mtime=NOW - 10 - i)
    reading_rollout(sessions, TODAY, "rollout-chosen.jsonl", 95.0, weekly=95.0, observed=NOW - 2400, mtime=NOW - 20)
    blank_rollout(sessions, TODAY, "rollout-unread.jsonl", mtime=NOW - 100)
    assert _snap(sessions)["state"] == "uncertain"
    d = _admit(use, "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"], d["snapshot_state"]) == (True, "within_budget", "uncertain")
    # CONTROL (re-pointed by #322): a FRESH 99.5% reading, with nothing unread, is refused for quota.
    shutil.rmtree(sessions / TODAY)
    fresh_rollout(sessions, 99.5, 10.0)
    d = _admit(use, "c2", sessions, tmp_path)
    assert (d["admitted"], d["reason"], d["snapshot_state"]) == (False, "quota_exhausted", "fresh")


def test_r9_a_trial_still_requires_a_fresh_reading(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 10.0, age=2400.0)
    t = _admit("trial", "t1", sessions, tmp_path)
    assert (t["admitted"], t["reason"]) == (False, "trial_requires_fresh_snapshot")
    # CONTROL: the same 10/10 reading, fresh -> admitted.
    fresh_rollout(sessions, 10.0, 10.0, age=60.0)
    assert _admit("trial", "t2", sessions, tmp_path)["admitted"] is True


def test_r9_audit_is_never_refused_by_the_lower_bound(sessions, tmp_path):
    fresh_rollout(sessions, 75.0, 75.0, age=2400.0)
    a = _admit("audit", "c1", sessions, tmp_path)
    assert (a["admitted"], a["reason"], a["snapshot_state"]) == (True, "audit_exempt", "stale")
    # #322: the same reading no longer refuses a budgeted use either (it did, `threshold`, until then).
    assert _admit("consult", "c1", sessions, tmp_path)["reason"] == "within_budget"


def test_r9_unavailable_is_unchanged_by_the_lower_bound(sessions):
    fresh_rollout(sessions, 100.0, 100.0, age=2400.0)
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None


# =========================================================================== #
# #282 r10 — substituted audits are not admitted TOP calls (K12)
# =========================================================================== #
def _is_admission_id(value):
    return isinstance(value, str) and len(value) == 32 and set(value) <= set("0123456789abcdef")


def test_r10_every_admit_row_and_decision_carries_a_distinct_valid_admission_id(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    decisions = [
        _admit("consult", "c1", sessions, tmp_path),     # admitted within_budget
        _admit("consult", "c1", sessions, tmp_path),     # refused budget_spent
        _admit("audit", "c1", sessions, tmp_path),       # admitted audit_exempt
        _admit("trial", "c1", sessions, tmp_path),       # admitted within_trial_ceiling
    ]
    fresh_rollout(sessions, 99.5, 3.0, name="rollout-2026-09-14T15-20-00-later.jsonl", age=5.0)
    decisions.append(_admit("challenger", "c1", sessions, tmp_path))  # refused quota_exhausted (#322)
    assert [(d["admitted"], d["reason"]) for d in decisions] == [
        (True, "within_budget"), (False, "budget_spent"), (True, "audit_exempt"), (True, "within_trial_ceiling"),
        (False, "quota_exhausted")]
    assert all(_is_admission_id(d["admission_id"]) for d in decisions), decisions
    assert len({d["admission_id"] for d in decisions}) == len(decisions)
    rows = read_rows(budget(tmp_path))
    assert [r["admission_id"] for r in rows] == [d["admission_id"] for d in decisions]


def test_r10_a_decision_whose_row_was_not_written_still_carries_an_admission_id(sessions, broken_budget):
    fresh_rollout(sessions, 10.0, 3.0)
    d = cq.admit("audit", "c1", project_root=broken_budget.parent, now=NOW, sessions_dir=sessions,
                 budget_path=broken_budget)
    assert (d["admitted"], d["row_written"]) == (True, False)
    assert _is_admission_id(d["admission_id"])


def test_r10_substitution_rows_carry_the_passed_admission_id_or_null(sessions, tmp_path):
    closing_rollout(sessions, 10.0, 3.0)
    audit = _admit("audit", "c1", sessions, tmp_path)
    correlated = _substitute("audit", "c1", "timeout_twice", tmp_path, sessions, role="code_reviewer",
                             admission_id=audit["admission_id"])
    uncorrelated = _substitute("consult", "c1", "budget_spent", tmp_path, sessions)
    assert (correlated["admission_id"], uncorrelated["admission_id"]) == (audit["admission_id"], None)
    subs = [r for r in read_rows(budget(tmp_path)) if r.get("kind") == "substitution"]
    assert [r["admission_id"] for r in subs] == [audit["admission_id"], None]
    assert all(set(r) == SUBSTITUTION_ROW_KEYS for r in subs)


def test_r10_a_correlated_audit_admission_is_netted_out_of_the_counts(sessions, tmp_path):
    closing_rollout(sessions, 10.0, 3.0)
    audit = _admit("audit", "c1", sessions, tmp_path)
    assert _admit("consult", "c1", sessions, tmp_path)["admitted"] is True
    path = budget(tmp_path)
    assert (cq._count_admitted(path, "c1", None, None), cq._count_admitted(path, "c1", "audit", None)) == (2, 1)
    sub = _substitute("audit", "c1", "quota_exhausted", tmp_path, sessions, role="code_reviewer",
                      admission_id=audit["admission_id"])
    # The row's own prior count already nets the admission it replaces: only the consult was a TOP call.
    assert (sub["row_written"], sub["prior_admitted_in_cycle"]) == (True, 1)
    assert (cq._count_admitted(path, "c1", None, None), cq._count_admitted(path, "c1", "audit", None)) == (1, 0)
    # A later substitution in the cycle inherits the netting.
    assert _substitute("consult", "c1", "budget_spent", tmp_path, sessions)["prior_admitted_in_cycle"] == 1


@pytest.mark.parametrize("admission_id", [None, "0123456789abcdef0123456789abcdef"])
def test_r10_control_an_uncorrelated_substitution_does_not_reduce_the_count(sessions, tmp_path, admission_id):
    closing_rollout(sessions, 10.0, 3.0)
    audit = _admit("audit", "c1", sessions, tmp_path)
    assert admission_id != audit["admission_id"]
    assert _admit("consult", "c1", sessions, tmp_path)["admitted"] is True
    sub = _substitute("audit", "c1", "quota_exhausted", tmp_path, sessions, role="code_reviewer",
                      admission_id=admission_id)
    assert (sub["admission_id"], sub["prior_admitted_in_cycle"]) == (admission_id, 2)
    path = budget(tmp_path)
    assert (cq._count_admitted(path, "c1", None, None), cq._count_admitted(path, "c1", "audit", None)) == (2, 1)


@pytest.mark.parametrize("admission_id", [None, "fedcba9876543210fedcba9876543210"])
def test_r10_budget_unchanged_an_uncorrelated_substitution_never_reopens_a_budget(sessions, tmp_path, admission_id):
    closing_rollout(sessions, 10.0, 3.0)
    assert _admit("consult", "c1", sessions, tmp_path)["admitted"] is True
    assert _substitute("consult", "c1", "budget_spent", tmp_path, sessions,
                       admission_id=admission_id)["row_written"] is True
    second = _admit("consult", "c1", sessions, tmp_path)
    assert (second["admitted"], second["reason"], second["budget_used"]) == (False, "budget_spent", 1)


@pytest.mark.parametrize("bad", [
    "",
    "0123456789ABCDEF0123456789ABCDEF",       # upper case
    "0123456789abcdef0123456789abcde",        # 31
    "0123456789abcdef0123456789abcdef0",      # 33
    "0123456789abcdef0123456789abcdef\n",     # a trailing newline must not slip past an anchor
    "01234567-89ab-cdef-0123-456789abcdef",   # the dashed uuid form
    "g123456789abcdef0123456789abcdef",
    "\u0660123456789abcdef0123456789abcdef",  # a non-ASCII digit (U+0660)
    12345,
    b"0123456789abcdef0123456789abcdef",
    ["0123456789abcdef0123456789abcdef"],
])
def test_r10_a_malformed_admission_id_is_a_caller_bug(sessions, tmp_path, bad):
    closing_rollout(sessions, 10.0, 3.0)
    with pytest.raises(ValueError, match="admission_id"):
        _substitute("audit", "c1", "cli_missing", tmp_path, sessions, role="code_reviewer", admission_id=bad)
    assert not budget(tmp_path).exists()


def test_r10_history_rows_without_admission_id_count_as_today(sessions, tmp_path):
    closing_rollout(sessions, 10.0, 3.0)
    path = budget(tmp_path)
    path.parent.mkdir(parents=True)
    history = [
        {"at": "2026-09-14T10:00:00Z", "cycle_id": "c1", "use": "audit", "admitted": True, "reason": "audit_exempt"},
        {"at": "2026-09-14T10:00:01Z", "cycle_id": "c1", "use": "consult", "admitted": True,
         "reason": "within_budget"},
        {"at": "2026-09-14T10:05:00Z", "kind": "substitution", "cycle_id": "c1", "use": "audit",
         "reason": "quota_exhausted"},
        {"at": "2026-09-14T10:06:00Z", "kind": "substitution", "cycle_id": "c1", "use": "audit",
         "reason": "quota_exhausted", "admission_id": None},
        # Not ids: an empty string on both sides nets nothing.
        {"at": "2026-09-14T10:07:00Z", "cycle_id": "c1", "use": "challenger", "admitted": True,
         "reason": "within_budget", "admission_id": ""},
        {"at": "2026-09-14T10:08:00Z", "kind": "substitution", "cycle_id": "c1", "use": "challenger",
         "reason": "timeout_twice", "admission_id": ""},
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in history), encoding="utf-8")
    assert cq._count_admitted(path, "c1", None, None) == 3
    assert cq._count_admitted(path, "c1", "consult", None) == 1
    assert _admit("consult", "c1", sessions, tmp_path)["reason"] == "budget_spent"
    assert _admit("challenger", "c1", sessions, tmp_path)["reason"] == "budget_spent"
    assert _substitute("audit", "c1", "cli_missing", tmp_path, sessions,
                       role="code_reviewer")["prior_admitted_in_cycle"] == 3


def test_r10_netting_follows_the_id_not_the_cycle_and_only_a_substitution_row_nets(sessions, tmp_path):
    """An audit admitted just before the UTC date rolls an adhoc key over is replaced under the next day's
    key: the id still nets it. CONTROL: a row that is not a substitution row carrying the same id nets nothing."""
    closing_rollout(sessions, 10.0, 3.0)
    audit = _admit("audit", "adhoc-20260914-nobase", sessions, tmp_path)
    path = budget(tmp_path)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": "2026-09-14T15:34:00Z", "cycle_id": "adhoc-20260914-nobase", "use": "audit",
                             "admitted": False, "reason": "hand-written", "admission_id": audit["admission_id"]})
                 + "\n")
    assert cq._count_admitted(path, "adhoc-20260914-nobase", None, None) == 1
    _substitute("audit", "adhoc-20260915-nobase", "timeout_twice", tmp_path, sessions, role="code_reviewer",
                admission_id=audit["admission_id"])
    assert cq._count_admitted(path, "adhoc-20260914-nobase", None, None) == 0


# =========================================================================== #
# #282 r15 — the standalone admit CLI is check-only unless --record (K17)
# =========================================================================== #
#: The keys every admit() decision carries in BOTH modes (task_key, the cycle provenance, unavailable,
#: fallback_error and error ride on top when they apply).
#: RE-POINTED by S081 revision 4 WP-A3: the decision mirrors the row's new fields, so a
#: check-only caller sees exactly what a recording one would have written.
R15_DECISION_KEYS = {"admitted", "use", "key", "cycle_id", "size", "size_source", "requested_model",
                     "model_class", "reason", "snapshot_state", "primary", "weekly", "budget_limit",
                     "budget_used", "row_written", "recorded", "budget_path", "admission_id", "fallback"}


def _store_state(path):
    """(store bytes or None, .lock present, store directory present): what a check must never change."""
    path = Path(path)
    return (path.read_bytes() if path.is_file() else None, cq.lock_path_for(path).exists(), path.parent.exists())


def _decided(decision):
    """A decision without what only the recording differs in (its id, the flags and the store path)."""
    # #322 fix round 1: `exhausted_recorded` says whether the RECORDED path persisted the exhausted-until record.
    return {k: v for k, v in decision.items()
            if k not in ("admission_id", "recorded", "row_written", "budget_path", "exhausted_recorded")}


def test_r15_python_admit_still_records_by_default_and_says_so(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    d = _admit("consult", "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"], d["recorded"], d["row_written"]) == (True, "within_budget", True, True)
    assert set(d) == R15_DECISION_KEYS | CYCLE_SOURCE_KEYS
    rows = read_rows(budget(tmp_path))
    assert [r["admission_id"] for r in rows] == [d["admission_id"]] and cq.is_admission_id(d["admission_id"])
    assert "recorded" not in rows[0]                                      # the flag is on the decision, not the row


@pytest.mark.parametrize("use", ["consult", "challenger", "advisory_review", "diagnosis"])
def test_r15_check_only_decides_like_a_recording_admit_and_writes_nothing(sessions, tmp_path, use):
    fresh_rollout(sessions, 10.0, 3.0)
    check_path = tmp_path / "check" / "astra-budget.jsonl"
    record_path = tmp_path / "record" / "astra-budget.jsonl"
    checked = _admit(use, "c1", sessions, tmp_path, budget_path=check_path, record=False)
    assert (checked["admitted"], checked["reason"], checked["budget_used"]) == (True, "within_budget", 0)
    assert (checked["recorded"], checked["row_written"], checked["admission_id"]) == (False, False, None)
    assert "error" not in checked
    assert _store_state(check_path) == (None, False, False)               # no store, no .lock, no directory
    assert not (tmp_path / "check").exists()
    # CONTROL: the recording admit on the same reading decides the same, with the same keys, and writes.
    recorded = _admit(use, "c1", sessions, tmp_path, budget_path=record_path)
    assert set(checked) == set(recorded)
    assert _decided(checked) == _decided(recorded)
    assert (recorded["recorded"], recorded["row_written"]) == (True, True)
    assert cq.is_admission_id(recorded["admission_id"])
    assert len(read_rows(record_path)) == 1


@pytest.mark.parametrize("use, primary, reason, admitted", [
    ("consult", 99.5, "quota_exhausted", False),   # RE-POINTED by #322: was 80.0, a `threshold` refusal
    ("challenger", 99.0, "quota_exhausted", False),
    ("trial", 45.0, "trial_threshold", False),
    ("trial", 10.0, "within_trial_ceiling", True),
    ("audit", 99.0, "audit_exempt", True),
])
def test_r15_check_only_decisions_on_their_merits_touch_no_store(sessions, tmp_path, use, primary, reason, admitted):
    fresh_rollout(sessions, primary, 3.0)
    check_path = tmp_path / "check" / "astra-budget.jsonl"
    checked = _admit(use, "c1", sessions, tmp_path, budget_path=check_path, record=False)
    # #322 fix round 1 (F2): the budget is counted BEFORE quota, so a budgeted use's quota refusal says 0 used.
    counted = None if use in ("trial", "audit") else 0
    assert (checked["admitted"], checked["reason"], checked["budget_used"]) == (admitted, reason, counted)
    assert (checked["recorded"], checked["row_written"], checked["admission_id"]) == (False, False, None)
    assert not (tmp_path / "check").exists()
    # CONTROL: recorded, the same decision appends its row (admitted OR refused).
    record_path = tmp_path / "record" / "astra-budget.jsonl"
    recorded = _admit(use, "c1", sessions, tmp_path, budget_path=record_path)
    assert _decided(checked) == _decided(recorded)
    assert [(r["admitted"], r["reason"]) for r in read_rows(record_path)] == [(admitted, reason)]


@pytest.mark.skipif(sys.platform == "win32", reason="same-process flock contention is POSIX")
def test_r15_check_only_reads_the_budget_without_the_lock_and_changes_nothing(sessions, tmp_path, monkeypatch):
    import portable_lock  # type: ignore

    fresh_rollout(sessions, 10.0, 3.0)
    path = budget(tmp_path)
    assert _admit("consult", "c1", sessions, tmp_path)["admitted"] is True
    before = _store_state(path)
    monkeypatch.setattr(cq, "LOCK_TIMEOUT_S", 0.2)
    with portable_lock.file_lock(cq.lock_path_for(path)):                 # a recording writer holds the lock
        spent = _admit("consult", "c1", sessions, tmp_path, record=False)
        unspent = _admit("challenger", "c1", sessions, tmp_path, record=False)
        # CONTROL: a recording admit under the same held lock cannot count the budget at all.
        blocked = _admit("challenger", "c1", sessions, tmp_path)
    assert (spent["admitted"], spent["reason"], spent["budget_used"], spent["row_written"]) == (
        False, "budget_spent", 1, False)
    assert (unspent["admitted"], unspent["reason"], unspent["budget_used"]) == (True, "within_budget", 0)
    assert (blocked["admitted"], blocked["reason"]) == (False, "budget_store_unavailable")
    assert _store_state(path) == before


def test_r15_check_only_on_an_unreadable_existing_store_is_store_unavailable_and_leaves_it_untouched(sessions,
                                                                                                     tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    path = budget(tmp_path)
    path.mkdir(parents=True)                                              # it exists and cannot be read as a file
    listing = sorted(os.listdir(path.parent))
    d = _admit("consult", "c1", sessions, tmp_path, record=False)
    assert (d["admitted"], d["reason"], d["budget_used"], d["recorded"], d["row_written"]) == (
        False, "budget_store_unavailable", None, False, False)
    assert d["error"] and d["admission_id"] is None
    assert path.is_dir() and os.listdir(path) == [] and sorted(os.listdir(path.parent)) == listing   # no .lock
    # CONTROL: a decision on its merits reads no store, and the audit is never refused.
    assert _admit("audit", "c1", sessions, tmp_path, record=False)["reason"] == "audit_exempt"
    if os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() == 0:
        return                                                            # root reads a mode-0 file anyway
    locked = tmp_path / "unreadable" / "astra-budget.jsonl"
    locked.parent.mkdir()
    locked.write_text(json.dumps({"at": "2026-09-14T15:00:00Z", "cycle_id": "c1", "use": "consult",
                                  "admitted": True, "reason": "within_budget"}) + "\n", encoding="utf-8")
    body = locked.read_bytes()
    locked.chmod(0)
    try:
        unreadable = _admit("consult", "c1", sessions, tmp_path, budget_path=locked, record=False)
    finally:
        locked.chmod(0o600)
    assert (unreadable["admitted"], unreadable["reason"], unreadable["row_written"]) == (
        False, "budget_store_unavailable", False)
    assert locked.read_bytes() == body and not cq.lock_path_for(locked).exists()


def test_r15_cli_admit_is_check_only_by_default_and_records_only_with_record(fixture_home, project):
    _live_rollout(fixture_home, 10.0, 3.0)
    store = fixture_home / ".claude" / "projects" / cq.project_slug(project) / "astra-budget.jsonl"
    check = ["admit", "--use", "consult", "--cycle-id", "cli-r15", "--project-root", str(project)]
    for _ in range(2):                                                    # a check spends nothing, so it repeats
        r = _cli(check, fixture_home, project)
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert (d["admitted"], d["reason"], d["recorded"], d["row_written"], d["admission_id"]) == (
            True, "within_budget", False, False, None)
        assert d["budget_path"] == str(store)
    assert _store_state(store) == (None, False, False)                    # no store, no .lock, no directory
    assert not (fixture_home / ".claude" / "projects").exists()

    recorded = _cli(["admit", "--record", *check[1:]], fixture_home, project)
    assert recorded.returncode == 0, recorded.stderr
    rd = json.loads(recorded.stdout)
    assert (rd["recorded"], rd["row_written"]) == (True, True) and cq.is_admission_id(rd["admission_id"])
    assert [(r["admitted"], r["reason"], r["admission_id"]) for r in read_rows(store)] == [
        (True, "within_budget", rd["admission_id"])]

    before = (hashlib.sha256(store.read_bytes()).hexdigest(), sorted(os.listdir(store.parent)))
    spent = _cli(check, fixture_home, project)
    assert spent.returncode == 10, spent.stderr
    sd = json.loads(spent.stdout)
    assert (sd["admitted"], sd["reason"], sd["budget_used"], sd["recorded"], sd["row_written"]) == (
        False, "budget_spent", 1, False, False)
    assert (hashlib.sha256(store.read_bytes()).hexdigest(), sorted(os.listdir(store.parent))) == before
    # CONTROL: the same refusal with --record exits the same and appends its row.
    again = _cli(["admit", "--record", *check[1:]], fixture_home, project)
    assert again.returncode == 10, again.stderr
    assert [(r["admitted"], r["reason"]) for r in read_rows(store)] == [(True, "within_budget"), (False, "budget_spent")]


@pytest.mark.parametrize("mode", [[], ["--record"]], ids=["check_only", "record"])
def test_r15_cli_exit_codes_are_identical_in_both_modes(fixture_home, project, mode):
    _live_rollout(fixture_home, 99.5, 3.0)
    base = ["--cycle-id", "cli-modes", "--project-root", str(project)]
    assert _cli(["admit", *mode, "--use", "consult", *base], fixture_home, project).returncode == 10   # quota (#322)
    assert _cli(["admit", *mode, "--use", "trial", *base], fixture_home, project).returncode == 10
    assert _cli(["admit", *mode, "--use", "audit", *base], fixture_home, project).returncode == 0
    assert _cli(["admit", *mode, "--use", "consult", "--cycle-id", ""], fixture_home, project).returncode == 3
    store = fixture_home / ".claude" / "projects" / cq.project_slug(project) / "astra-budget.jsonl"
    assert store.exists() is bool(mode)                                   # only --record wrote anything


def test_r15_cli_admit_help_names_check_only_the_record_flag_and_the_recording_path(fixture_home, project):
    r = _cli(["admit", "--help"], fixture_home, project, {"PYTHONIOENCODING": "cp1252"})
    assert r.returncode == 0, r.stderr
    assert r.stdout.isascii()
    text = " ".join(r.stdout.split())
    for needle in ("check-only", "--record", "writes nothing", "seat_model.py argv --role R --provider codex --use U",
                   "twice", "0 admitted, 10 refused", "recorded"):
        assert needle in text, needle
    top = _cli(["--help"], fixture_home, project, {"PYTHONIOENCODING": "cp1252"})
    assert top.returncode == 0 and top.stdout.isascii()
    assert "check-only unless --record" in " ".join(top.stdout.split())


def test_r15_the_module_docstring_states_check_only_and_names_the_recording_path():
    doc = cq.__doc__
    surface = " ".join(doc[doc.index("\nTHE SURFACE"):doc.index("\nTHE BUDGET KEY")].split())
    for needle in ("record=False", "check-only", "--record", "seat_model.py argv --use"):
        assert needle.lower() in surface.lower(), needle
    store = " ".join(doc[doc.index("\nTHE BUDGET STORE"):doc.index("\nHONEST LIMITS")].split()).lower()
    assert "check-only" in store and "without the lock" in store


def test_r15_the_codex_docs_name_the_recording_forms():
    """codex-orchestration's low-level form records with --record; external-facts' no-probing warning names both
    recording calls. Both files sit next to _meta in both trees (PROJECT.md is repo-only and is not read here)."""
    skill, whole = _codex_orchestration_docs()
    assert "`codex_quota.py admit --record --use U --cycle-id C`" in skill
    assert "`codex_quota.py admit --use U --cycle-id C` stays available" not in whole
    assert "check-only" in skill
    facts = " ".join((_META / "external-facts.md").read_text(encoding="utf-8").split())
    assert "`seat_model.py argv … --use`" in facts and "`codex_quota.py admit --record`" in facts
    assert "check-only" in facts


# =========================================================================== #
# #282 fix round 1 F5 / F6 — an uncertain meter never stops a call, and a
# rollout whose read FAILED is an unread candidate, not silence (K41, K42)
# =========================================================================== #
def _failing_tail(monkeypatch, *names):
    """Make `_tail_lines` raise for the named rollouts, exactly as an unreadable file does.
    Portable by construction: a chmod 000 fixture is meaningless under root and on Windows."""
    real = cq._tail_lines

    def fake(path, limit):
        if path.name in names:
            raise OSError(13, "Permission denied")
        return real(path, limit)

    monkeypatch.setattr(cq, "_tail_lines", fake)


def _f5_uncertain_over_an_older_reached_flag(sessions, percent=20.0):
    """Four READ rollouts whose codex object carries an older reached flag, plus a FIFTH,
    UNREAD rollout — newer than the chosen reading — whose codex object CLEARS it. Returns
    the clearing rollout."""
    for i in range(4):                       # mtimes NOW-10 .. NOW-13: the four newest, all read
        reading_rollout(sessions, TODAY, f"rollout-reached-{i}.jsonl", percent, weekly=percent,
                        observed=NOW - 600 - 100 * i, mtime=NOW - 10 - i, reached_type="primary")
    return reading_rollout(sessions, TODAY, "rollout-clears.jsonl", 20.0,
                           observed=NOW - 120, mtime=NOW - 100)


def test_fr1_f5_an_uncertain_snapshot_never_returns_rate_limit_reached(sessions, monkeypatch):
    """F5: `_unavailable_from` used to answer from the reached flags BEFORE looking at the
    snapshot state, so a scan that admits it may have missed a newer rollout still stopped the
    call — on evidence the unread rollout clears. Only a CERTAIN scan may stop a call."""
    clearing = _f5_uncertain_over_an_older_reached_flag(sessions)
    snap = _snap(sessions)
    assert (snap["state"], snap["reason"]) == ("uncertain", "newer_candidate_unread")
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None
    # CONTROL: widen the read limit so the clearing rollout IS read -> fresh, None, no false stop.
    monkeypatch.setattr(cq, "ROLLOUT_FILE_LIMIT", 5)
    snap = _snap(sessions)
    assert (snap["state"], snap["reason"], snap["source"]) == ("fresh", None, str(clearing))
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None


def test_fr1_f5_a_fresh_certain_scan_with_a_reached_flag_still_stops_the_call(sessions):
    """CONTROL: F5 takes the token away from `uncertain` ONLY. Certain positive evidence — a
    reached flag read inside the age bound, before its void time — still stops the call."""
    reading_rollout(sessions, TODAY, "rollout-only.jsonl", 20.0, observed=NOW - 60, mtime=NOW - 50,
                    reached_type="primary")
    snap = _snap(sessions)
    assert (snap["state"], snap["reason"]) == ("fresh", None)
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "rate_limit_reached"


def test_fr1_f5_a_stale_snapshot_still_returns_rate_limit_reached(sessions):
    """CONTROL for K41's other half: a `stale` snapshot keeps today's rule. Here the reading is
    stale because its primary window already reset, while the reached flag itself was observed
    inside the age bound and is still before its own (secondary) void time."""
    reading_rollout(sessions, TODAY, "rollout-reset.jsonl", 20.0, observed=NOW - 60, mtime=NOW - 50,
                    reached_type="secondary", p_resets=int(NOW - 1))
    snap = _snap(sessions)
    assert (snap["state"], snap["reason"]) == ("stale", "primary_window_reset")
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "rate_limit_reached"


def test_fr1_f5_uncertain_admits_nothing_it_should_not_and_never_refuses_audit(sessions, tmp_path):
    """ADMISSION SAFETY under the F5 rule, at a reading that is over EVERY ceiling: an uncertain
    snapshot still never trips the 70 % rule, never admits a trial and never yields
    quota_exhausted — and `audit` is still never refused, now without an `unavailable` token
    riding on its decision."""
    _f5_uncertain_over_an_older_reached_flag(sessions, percent=99.5)
    assert _snap(sessions)["state"] == "uncertain"
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None
    consult = _admit("consult", "c1", sessions, tmp_path)
    assert (consult["admitted"], consult["reason"], consult["snapshot_state"]) == (
        True, "within_budget", "uncertain")
    trial = _admit("trial", "t1", sessions, tmp_path)
    assert (trial["admitted"], trial["reason"]) == (False, "trial_requires_fresh_snapshot")
    audit = _admit("audit", "a1", sessions, tmp_path)
    assert (audit["admitted"], audit["reason"]) == (True, "audit_exempt")
    assert "unavailable" not in audit


def test_fr1_f6_scan_rollout_distinguishes_a_failed_read_from_an_empty_one(sessions, monkeypatch):
    """The API half of F6: `_scan_rollout` reports WHETHER the tail read failed, which is what
    lets `_scan` tell silence from absence. A read that succeeds and finds nothing is not a
    failure."""
    blank = blank_rollout(sessions, TODAY, "rollout-blank.jsonl", mtime=NOW - 10)
    assert cq._scan_rollout(blank) == (None, {}, False)
    _failing_tail(monkeypatch, "rollout-blank.jsonl")
    assert cq._scan_rollout(blank) == (None, {}, True)


def test_fr1_f6_a_newer_rollout_whose_read_failed_makes_the_snapshot_uncertain(sessions, tmp_path,
                                                                               monkeypatch):
    """F6: a read failure on a selected rollout used to be silently skipped, so an older reading
    was reported `fresh` and a trial was admitted on it."""
    older = reading_rollout(sessions, TODAY, "rollout-older.jsonl", 20.0, observed=NOW - 60,
                            mtime=NOW - 50)
    blank_rollout(sessions, TODAY, "rollout-newest.jsonl", mtime=NOW - 10)
    # CONTROL FIRST: the newest rollout READS, it simply carries no usable reading -> fresh 20 %.
    snap = _snap(sessions)
    assert (snap["state"], snap["reason"], snap["primary_used_percent"], snap["source"]) == (
        "fresh", None, 20.0, str(older))
    assert _admit("trial", "t0", sessions, tmp_path)["reason"] == "within_trial_ceiling"
    # The SAME tree with that newest rollout UNREADABLE: its silence is no longer read as absence.
    _failing_tail(monkeypatch, "rollout-newest.jsonl")
    snap = _snap(sessions)
    assert (snap["state"], snap["reason"], snap["primary_used_percent"], snap["source"]) == (
        "uncertain", "newer_candidate_unread", 20.0, str(older))
    trial = _admit("trial", "t1", sessions, tmp_path)
    assert (trial["admitted"], trial["reason"], trial["snapshot_state"]) == (
        False, "trial_requires_fresh_snapshot", "uncertain")


def test_fr1_f6_a_failed_read_older_than_the_chosen_reading_changes_nothing(sessions, monkeypatch):
    """CONTROL, and K42's explicit clause: only a failed read whose mtime is NEWER than the
    chosen observation can be hiding a newer reading."""
    older = reading_rollout(sessions, TODAY, "rollout-chosen.jsonl", 20.0, observed=NOW - 60,
                            mtime=NOW - 50)
    blank_rollout(sessions, TODAY, "rollout-ancient.jsonl", mtime=NOW - 600)
    _failing_tail(monkeypatch, "rollout-ancient.jsonl")
    snap = _snap(sessions)
    assert (snap["state"], snap["reason"], snap["source"]) == ("fresh", None, str(older))


def test_fr1_f6_when_every_read_fails_the_snapshot_stays_unknown(sessions, tmp_path, monkeypatch):
    """K42: a failed read is an unread CANDIDATE, never a reading. With no reading at all the
    snapshot stays `unknown` / `no_rate_limits` — it never becomes `uncertain` out of nothing,
    and it admits nothing that needs a fresh meter."""
    reading_rollout(sessions, TODAY, "rollout-a.jsonl", 20.0, observed=NOW - 60, mtime=NOW - 50)
    reading_rollout(sessions, TODAY, "rollout-b.jsonl", 30.0, observed=NOW - 70, mtime=NOW - 40)
    _failing_tail(monkeypatch, "rollout-a.jsonl", "rollout-b.jsonl")
    snap = _snap(sessions)
    assert (snap["state"], snap["reason"], snap["primary_used_percent"]) == (
        "unknown", "no_rate_limits", None)
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None
    assert _admit("trial", "t1", sessions, tmp_path)["reason"] == "trial_requires_fresh_snapshot"


def test_fr1_f5_f6_the_module_docstring_no_longer_says_uncertain_keeps_the_reached_flags():
    """The docstring half of F5: the ASTRA UNAVAILABLE clause said an uncertain snapshot KEEPS
    the reached flags, which is exactly the behaviour F5 removes."""
    doc = cq.__doc__
    astra = " ".join(doc[doc.index("\nASTRA UNAVAILABLE"):doc.index("\n  fallback (J8)")].split())
    assert "an uncertain snapshot keeps them" not in astra
    assert "uncertain" in astra and "None" in astra
    assert "including a stale, uncertain or unknown reading" in astra
    unavail = " ".join((cq.unavailable.__doc__ or "").split())
    assert "A stale, uncertain or unknown reading is None" in unavail


# =========================================================================== #
# S081 revision 4, WP-A3 — the per-use budget table, the budget-row schema and
# the account-wide trip-wire (design §2.2; D14, D16, D20)
# =========================================================================== #
#: The design §2.2 table, verbatim. `None` is the table's "—" cell.
A3_TABLE = {
    "consult":         {"top": 1,    "std": 2},
    "challenger":      {"top": 1,    "std": 2},
    "advisory_review": {"top": 1,    "std": None},
    "review_std":      {"top": None, "std": 2},
    "brainstorm":      {"top": 2,    "std": 4},
    "ballot":          {"top": 1,    "std": 2},
    "deliberation":    {"top": 1,    "std": 1},
    "diagnosis":       {"top": 1,    "std": 2},
    # The astra reserve (roster rev 4): TOP-only uses, one each per key (exhausted_review: per review id).
    "escalation":       {"top": 1,    "std": None},
    "top_retry":        {"top": 1,    "std": None},
    "exhausted_review": {"top": 1,    "std": None},
}
#: (use, model_class) pairs the table budgets — every cell that is not "—".
A3_BUDGETED = sorted((use, cls) for use, row in A3_TABLE.items()
                     for cls, limit in row.items() if limit is not None)
#: The two "—" cells: a class the table does not budget for that use.
A3_UNBUDGETED = [("advisory_review", "std"), ("review_std", "top"),
                 # the astra reserve: the reserve is never billed as std
                 ("escalation", "std"), ("exhausted_review", "std"), ("top_retry", "std")]
#: The design §2.2 budget-row schema, plus the meter keys admit() has always written.
A3_ROW_KEYS = {"at", "key", "cycle_id", "use", "size", "size_source", "requested_model",
               "model_class", "admitted", "reason", "admission_id",
               "snapshot_state", "primary", "weekly"}


def _sized(use, key, sessions, tmp_path, **kw):
    """admit() with a size and a class, the D16 call shape."""
    kw.setdefault("size", "complex")
    kw.setdefault("size_source", "routing")
    kw.setdefault("model_class", "top")
    if use == "exhausted_review":
        kw.setdefault("task_key", "docs/plans/x.md")   # REQUIRED: one exhausted review per D21 review id
    return _admit(use, key, sessions, tmp_path, **kw)


# --------------------------------------------------------------------------- #
# The vocabulary lands together
# --------------------------------------------------------------------------- #
def test_a3_the_use_vocabulary_is_the_design_table():
    assert set(cq.USES) == {"audit", "advisory_review", "review_std", "consult", "challenger",
                            "brainstorm", "ballot", "deliberation", "diagnosis", "trial",
                            # the astra reserve (roster rev 4, design 2026-09-27 s4a F2/F3/F5)
                            "escalation", "top_retry", "exhausted_review"}


def test_a3_every_vocabulary_lands_together():
    """The defect this test exists to prevent: a use that exists in one vocabulary and not
    another. SUBSTITUTION_USES is every use but the trial (which is skipped, never
    substituted); USE_FALLBACK_ROLE names a Claude seat for the same set; BUDGET_LIMITS
    budgets every use but `audit` (never budgeted) and `trial` (paced by its own ceiling)."""
    assert set(cq.SUBSTITUTION_USES) == set(cq.USES) - {"trial"}
    assert set(cq.USE_FALLBACK_ROLE) == set(cq.USES) - {"trial"}
    assert set(cq.BUDGET_LIMITS) == set(cq.USES) - {"audit", "trial"}


def test_a3_the_budget_table_is_the_design_table():
    assert {use: dict(row) for use, row in cq.BUDGET_LIMITS.items()} == A3_TABLE
    assert set(cq.MODEL_CLASSES) == {"top", "std"}
    assert (cq.MODEL_CLASS_TOP, cq.MODEL_CLASS_STD) == ("top", "std")


def test_a3_l9_deliberation_is_the_avengers_seat_and_ballot_is_cross_cli():
    """L9, pinned so a stage cannot key `deliberation` on a cross-cli id: both exist, and
    `deliberation` keeps the seat-per-session limit the avengers row has."""
    assert cq.BUDGET_LIMITS["deliberation"] == {"top": 1, "std": 1}
    assert cq.BUDGET_LIMITS["ballot"] == {"top": 1, "std": 2}
    assert "deliberation" in cq.SUBSTITUTION_USES and "ballot" in cq.SUBSTITUTION_USES


def test_a3_the_budget_table_is_not_mutable_by_a_caller():
    with pytest.raises(TypeError):
        cq.BUDGET_LIMITS["consult"] = {"top": 99, "std": 99}    # type: ignore[index]
    with pytest.raises(TypeError):
        cq.BUDGET_LIMITS["consult"]["top"] = 99                 # type: ignore[index]


# --------------------------------------------------------------------------- #
# D16: a complex call and a light/medium call on the SAME key count separately
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("use", sorted(u for u in A3_TABLE
                                       if A3_TABLE[u]["top"] and A3_TABLE[u]["std"]))
def test_a3_top_and_std_budgets_are_independent_on_the_same_key(sessions, tmp_path, use):
    """The D16 rule. CONTROL, both directions: exhausting one class leaves the other's
    whole budget intact on the SAME key — the point of keying the limit on model_class."""
    fresh_rollout(sessions, 10.0, 3.0)
    top_limit, std_limit = A3_TABLE[use]["top"], A3_TABLE[use]["std"]
    for _ in range(top_limit):
        assert _sized(use, "k1", sessions, tmp_path)["admitted"] is True
    assert _sized(use, "k1", sessions, tmp_path)["reason"] == "budget_spent"
    # The std budget on the SAME key is untouched.
    for _ in range(std_limit):
        d = _sized(use, "k1", sessions, tmp_path, size="light", model_class="std")
        assert (d["admitted"], d["reason"]) == (True, "within_budget")
    assert _sized(use, "k1", sessions, tmp_path, size="light",
                  model_class="std")["reason"] == "budget_spent"
    # CONTROL the other way: a fresh key spends std first and the top budget still admits.
    for _ in range(std_limit):
        assert _sized(use, "k2", sessions, tmp_path, size="medium", model_class="std")["admitted"] is True
    assert _sized(use, "k2", sessions, tmp_path, size="medium",
                  model_class="std")["reason"] == "budget_spent"
    assert _sized(use, "k2", sessions, tmp_path)["admitted"] is True


@pytest.mark.parametrize("use,cls", A3_BUDGETED)
def test_a3_each_cell_admits_exactly_its_limit(sessions, tmp_path, use, cls):
    fresh_rollout(sessions, 10.0, 3.0)
    limit = A3_TABLE[use][cls]
    size = "complex" if cls == "top" else "light"
    for i in range(limit):
        d = _sized(use, "k1", sessions, tmp_path, size=size, model_class=cls)
        assert (d["admitted"], d["reason"], d["budget_limit"], d["budget_used"]) == (
            True, "within_budget", limit, i)
    d = _sized(use, "k1", sessions, tmp_path, size=size, model_class=cls)
    assert (d["admitted"], d["reason"], d["budget_used"]) == (False, "budget_spent", limit)


@pytest.mark.parametrize("use,cls", A3_UNBUDGETED)
def test_a3_a_class_the_table_does_not_budget_is_refused(sessions, tmp_path, use, cls):
    """The "—" cells fail CLOSED. `advisory_review` IS the complex review and `review_std`
    IS the light/medium one, so the other pairing is a call the table does not define: it is
    refused and recorded, never admitted unbudgeted. CONTROL: the budgeted class admits."""
    fresh_rollout(sessions, 10.0, 3.0)
    size = "complex" if cls == "top" else "light"
    d = _sized(use, "k1", sessions, tmp_path, size=size, model_class=cls)
    assert (d["admitted"], d["reason"], d["budget_limit"]) == (False, "class_not_budgeted", None)
    row = read_rows(budget(tmp_path))[-1]
    assert (row["admitted"], row["reason"], row["model_class"]) == (False, "class_not_budgeted", cls)
    other = "std" if cls == "top" else "top"
    control = _sized(use, "k1", sessions, tmp_path,
                     size="light" if other == "std" else "complex", model_class=other)
    assert (control["admitted"], control["reason"]) == (True, "within_budget")


@pytest.mark.parametrize("use,cls", A3_BUDGETED)
def test_a3_every_budgeted_use_inherits_the_quota_rule(sessions, tmp_path, use, cls):
    """RE-POINTED AND RENAMED by #322 (was ..._inherits_the_threshold_rule): quota exhaustion is decided
    BEFORE the budget, so it refuses every use alike, and a 75% reading refuses none of them. Each use is
    exercised on a class the table actually budgets, so a `class_not_budgeted` refusal can never be
    mistaken for a quota one."""
    size = "complex" if cls == "top" else "light"
    fresh_rollout(sessions, 75.0, 3.0)                  # the old threshold: admitted now
    assert _sized(use, "k0", sessions, tmp_path, size=size, model_class=cls)["admitted"] is True
    fresh_rollout(sessions, 99.5, 3.0)
    d = _sized(use, "k1", sessions, tmp_path, size=size, model_class=cls)
    assert (d["admitted"], d["reason"]) == (False, "quota_exhausted")
    fresh_rollout(sessions, 10.0, 3.0)          # CONTROL: below exhaustion it admits
    assert _sized(use, "k2", sessions, tmp_path, size=size, model_class=cls)["admitted"] is True


# --------------------------------------------------------------------------- #
# Key shapes
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("key", [
    "S081-cycle-7",                                     # a forge cycle id
    "review-0f9c4b2a8e1d4f6ab3c5d7e9f1a2b3c4",          # advisory_review / review_std
    "ballot-0f9c4b2a8e1d4f6ab3c5d7e9f1a2b3c4",          # cross-cli (L9)
    "tournament-0f9c4b2a8e1d4f6ab3c5d7e9f1a2b3c4",      # brainstorm
    "trial-2026-09-16",                                 # trial
    "avengers-2026-09-16T10:00:00",                     # an avengers session id (deliberation)
    "adhoc-20260916-abc1234",
])
def test_a3_every_use_key_shape_matches_the_cycle_id_pattern(key):
    """CYCLE_ID_PATTERN already accepts `tournament-<uuid>`; the new uses' keys are the same
    shape. Proven for `ballot-<uuid>` and `review-<uuid>` by name, as the criterion asks."""
    assert cq.CYCLE_ID_PATTERN.fullmatch(key) is not None


@pytest.mark.parametrize("key", ["-leading-dash", "has space", "has/slash", ""])
def test_a3_the_key_pattern_still_refuses_a_shape_it_never_accepted(key):
    """NEGATIVE CONTROL: the pattern is not a rubber stamp."""
    assert cq.CYCLE_ID_PATTERN.fullmatch(key) is None


# --------------------------------------------------------------------------- #
# Caller bugs still raise
# --------------------------------------------------------------------------- #
def test_a3_an_unknown_use_still_raises_value_error(sessions, tmp_path):
    with pytest.raises(ValueError, match="unknown use"):
        _sized("consultancy", "k1", sessions, tmp_path)


def test_a3_task_key_still_applies_to_diagnosis_only(sessions, tmp_path):
    """RE-POINTED by the astra reserve (F5): the exhausted-loop review is keyed per D21 review id too."""
    fresh_rollout(sessions, 10.0, 3.0)
    for use in sorted(set(cq.USES) - cq.TASK_KEY_USES):
        with pytest.raises(ValueError, match="task_key applies to uses"):
            _sized(use, "k1", sessions, tmp_path, task_key="WP-1")
    d = _sized("diagnosis", "k1", sessions, tmp_path, task_key="WP-1")
    assert (d["admitted"], d["task_key"]) == (True, "WP-1")
    assert cq.TASK_KEY_USES == frozenset({"diagnosis", "exhausted_review"})


@pytest.mark.parametrize("kw,match", [
    ({"model_class": "middle"}, "model_class"),
    ({"size": "enormous", "size_source": "routing"}, "size"),
    ({"size": "light", "size_source": "vibes"}, "size_source"),
    ({"size": "light", "size_source": None}, "size_source"),
    ({"size": None, "size_source": "routing"}, "size"),
    ({"requested_by": "the boss"}, "requested_by"),
    ({"requested_model": "not a word"}, "requested_model"),
])
def test_a3_a_malformed_size_or_class_is_a_caller_bug(sessions, tmp_path, kw, match):
    fresh_rollout(sessions, 10.0, 3.0)
    base = {"size": "complex", "size_source": "routing", "model_class": "top"}
    base.update(kw)
    with pytest.raises(ValueError, match=match):
        _admit("consult", "k1", sessions, tmp_path, **base)
    assert not budget(tmp_path).exists()      # a caller bug leaves no row behind


# --------------------------------------------------------------------------- #
# The budget-row schema (design §2.2) — every row, unconditionally
# --------------------------------------------------------------------------- #
def test_a3_the_budget_row_carries_the_design_schema(sessions, tmp_path, project):
    fresh_rollout(sessions, 10.0, 3.0)
    d = cq.admit("advisory_review", "review-abc", project_root=project, now=NOW,
                 sessions_dir=sessions, budget_path=budget(tmp_path), size="complex",
                 size_source="forge", model_class="top", requested_model="gpt-6-astra")
    row = read_rows(budget(tmp_path))[-1]
    assert set(row) == A3_ROW_KEYS | CYCLE_SOURCE_KEYS
    assert (row["key"], row["cycle_id"], row["use"]) == ("review-abc", "review-abc", "advisory_review")
    assert (row["size"], row["size_source"], row["model_class"], row["requested_model"]) == (
        "complex", "forge", "top", "gpt-6-astra")
    for field in ("key", "size", "size_source", "model_class", "requested_model"):
        assert d[field] == row[field]


def test_a3_every_row_records_a_size_and_a_size_source_unconditionally(sessions, tmp_path):
    """Design §2.2 line 95: EVERY row records `size` and `size_source`. An un-migrated caller
    passes neither, and L7 rule 6 makes that `complex` / `default` — the back-compat reading,
    recorded rather than left absent, so the 2026-09-28 review never sees a hole it must guess at."""
    fresh_rollout(sessions, 10.0, 3.0)
    d = _admit("consult", "k1", sessions, tmp_path)            # no size, no class
    assert (d["size"], d["size_source"], d["model_class"]) == ("complex", "default", "top")
    row = read_rows(budget(tmp_path))[-1]
    assert (row["size"], row["size_source"], row["model_class"]) == ("complex", "default", "top")


def test_a3_requested_by_user_rides_the_row_only_for_a_user_request(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    d = _sized("consult", "k1", sessions, tmp_path, size="light", size_source="user",
               requested_by="user")
    assert d["requested_by"] == "user"
    assert read_rows(budget(tmp_path))[-1]["requested_by"] == "user"
    control = _sized("consult", "k2", sessions, tmp_path)       # CONTROL: no user request
    assert "requested_by" not in control
    assert "requested_by" not in read_rows(budget(tmp_path))[-1]


def test_a3_a_refused_row_carries_the_schema_too(sessions, tmp_path):
    fresh_rollout(sessions, 99.5, 3.0)  # RE-POINTED by #322: the threshold no longer refuses, so the refusal on its merits is a quota one.
    _sized("brainstorm", "tournament-1", sessions, tmp_path, size="light", size_source="routing",
           model_class="std", requested_model="gpt-5.6-sol")
    row = read_rows(budget(tmp_path))[-1]
    assert (row["admitted"], row["reason"]) == (False, "quota_exhausted")
    assert (row["size"], row["size_source"], row["model_class"], row["requested_model"]) == (
        "light", "routing", "std", "gpt-5.6-sol")


# --------------------------------------------------------------------------- #
# BACKWARD COMPATIBILITY — the three live stores hold 15 rows in the OLD shape
# --------------------------------------------------------------------------- #
#: One admitted row and one substitution row exactly as the live stores hold them today:
#: no `key`, no `size`, no `size_source`, no `model_class`.
A3_OLD_ROWS = [
    {"at": "2026-09-15T09:00:00Z", "cycle_id": "S081-old", "use": "consult", "admitted": True,
     "reason": "within_budget", "snapshot_state": "fresh", "primary": 12.0, "weekly": 3.0,
     "admission_id": "0f9c4b2a8e1d4f6ab3c5d7e9f1a2b3c4", "cycle_id_source": "cycle-id",
     "cycle_id_file_age_s": 12.0},
    {"at": "2026-09-15T09:05:00Z", "kind": "substitution", "cycle_id": "S081-old",
     "cycle_id_source": "cycle-id", "cycle_id_file_age_s": 17.0, "use": "challenger",
     "substitute_for": "codex", "requested_model": "gpt-6-astra", "served_model": "fable",
     "role": "consultant_main", "reason": "threshold", "snapshot_state": "fresh",
     "primary": 78.0, "weekly": 20.0, "prior_admitted_in_cycle": 0, "admission_id": None},
]


def _old_shape_store(tmp_path):
    path = budget(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in A3_OLD_ROWS), encoding="utf-8")
    return path


def test_a3_old_shape_rows_still_parse_and_still_count(sessions, tmp_path):
    """THE BACKWARD-COMPATIBILITY CONTROL. A store written before D16 has no `key` and no
    `model_class`. Its rows must still be read (from `cycle_id`) and must still COUNT — and
    they count as TOP, because every budgeted call before D16 was an astra call."""
    _old_shape_store(tmp_path)
    fresh_rollout(sessions, 10.0, 3.0)
    d = _sized("consult", "S081-old", sessions, tmp_path)
    assert (d["admitted"], d["reason"], d["budget_used"]) == (False, "budget_spent", 1)
    # The same old row does NOT spend the std budget: an un-classed row is a TOP call.
    std = _sized("consult", "S081-old", sessions, tmp_path, size="light", model_class="std")
    assert (std["admitted"], std["reason"], std["budget_used"]) == (True, "within_budget", 0)


def test_a3_an_old_shape_store_survives_every_reader(sessions, tmp_path):
    path = _old_shape_store(tmp_path)
    assert cq._count_admitted(path, "S081-old", None, None) == 1
    assert cq._count_admitted(path, "S081-old", "consult", None) == 1
    assert cq._count_admitted(path, "S081-old", "consult", None, model_class="std") == 0
    rows = read_rows(path)
    assert [r.get("key") for r in rows] == [None, None]       # the old shape is untouched


# --------------------------------------------------------------------------- #
# record=False stays fully check-only with the new fields
# --------------------------------------------------------------------------- #
def test_a3_check_only_stays_check_only_with_the_new_fields(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    d = _sized("ballot", "ballot-1", sessions, tmp_path, record=False)
    assert (d["admitted"], d["reason"], d["recorded"], d["row_written"]) == (
        True, "within_budget", False, False)
    assert d["admission_id"] is None
    assert (d["size"], d["size_source"], d["model_class"]) == ("complex", "routing", "top")
    assert not budget(tmp_path).exists()
    assert not budget(tmp_path).parent.exists()
    assert not cq.lock_path_for(budget(tmp_path)).exists()


# --------------------------------------------------------------------------- #
# D20 — the account-wide trip-wire EVERY codex call checks
# --------------------------------------------------------------------------- #
def _tripwire(seat_class, sessions, **kw):
    return cq.tripwire(seat_class, sessions_dir=sessions, now=NOW, **kw)


def test_a3_tripwire_a_supporting_seat_on_real_exhaustion_is_skipped(sessions):
    """D20: a supporting `consultant_support` sol seat is trip-wire-checked but NOT budgeted,
    and on real exhaustion it takes a RECORDED SKIP, never a substitute. RE-POINTED AND RENAMED by
    #322 (was ..._above_the_threshold_is_skipped): 75% now RUNS, the reading still reported."""
    fresh_rollout(sessions, 75.0, 3.0)
    t = _tripwire("supporting", sessions)
    assert (t["action"], t["proceed"], t["reason"]) == ("run", True, "below_threshold")
    assert t["threshold_tripped"] is True                       # informational only
    fresh_rollout(sessions, 99.5, 3.0)
    t = _tripwire("supporting", sessions)
    assert (t["action"], t["proceed"], t["reason"]) == ("skip", False, "quota_exhausted")


def test_a3_tripwire_a_supporting_seat_below_the_threshold_runs(sessions):
    """THE CONTROL for the test above: the trip-wire is a threshold, not a blanket refusal."""
    fresh_rollout(sessions, 69.9, 69.9)
    t = _tripwire("supporting", sessions)
    assert (t["action"], t["proceed"], t["reason"]) == ("run", True, "below_threshold")
    assert t["threshold_tripped"] is False


def test_a3_tripwire_a_discretionary_seat_on_real_exhaustion_is_substituted(sessions):
    """RE-POINTED AND RENAMED by #322 (was ..._above_the_threshold_is_substituted)."""
    fresh_rollout(sessions, 75.0, 3.0)
    assert _tripwire("discretionary", sessions)["action"] == "run"      # the old threshold runs now
    fresh_rollout(sessions, 99.5, 3.0)
    t = _tripwire("discretionary", sessions)
    assert (t["action"], t["proceed"], t["reason"]) == ("substitute", False, "quota_exhausted")
    # CONTROL: below it, the same seat runs.
    fresh_rollout(sessions, 10.0, 3.0)
    assert _tripwire("discretionary", sessions)["action"] == "run"


def test_a3_tripwire_the_audit_above_the_threshold_still_runs(sessions):
    """The VERIFIED-gate audit stops only on REAL exhaustion; 70% never stops it. This is the
    trip-wire half of `audit_exempt`."""
    fresh_rollout(sessions, 98.0, 98.0)
    t = _tripwire("audit", sessions)
    assert (t["action"], t["proceed"], t["reason"]) == ("run", True, "audit_exempt")
    assert t["threshold_tripped"] is True


@pytest.mark.parametrize("signal", sorted(SIGNALS))
def test_a3_tripwire_real_exhaustion_stops_every_seat_class(sessions, signal):
    signal_rollout(sessions, signal)
    token = cq.unavailable(sessions_dir=sessions, now=NOW)
    assert token is not None
    assert _tripwire("audit", sessions)["action"] == "substitute"
    assert _tripwire("discretionary", sessions)["action"] == "substitute"
    assert _tripwire("supporting", sessions)["action"] == "skip"
    for seat_class in ("audit", "discretionary", "supporting"):
        assert _tripwire(seat_class, sessions)["unavailable"] == token


def test_a3_tripwire_writes_nothing_at_all(sessions, tmp_path):
    """CHECK-ONLY, no budget: it reads the meter and creates no store, directory or lock."""
    fresh_rollout(sessions, 75.0, 3.0)
    before = sorted(p.name for p in tmp_path.iterdir())
    _tripwire("supporting", sessions)
    _tripwire("discretionary", sessions)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert not budget(tmp_path).parent.exists()


def test_a3_tripwire_an_unknown_seat_class_is_a_caller_bug(sessions):
    with pytest.raises(ValueError, match="seat_class"):
        _tripwire("passenger", sessions)


def test_a3_tripwire_an_uncertain_reading_is_not_a_refusal(pre_fr1_walk, sessions):
    """#282 F5, inherited EXACTLY: `unavailable()` returns None for an uncertain snapshot and
    an uncertain reading never trips the threshold rule. Side one — it must not become a refusal."""
    for i in range(3):
        blank_rollout(sessions, TODAY, f"rollout-blank-{i}.jsonl", mtime=NOW - 10 - i)
    reading_rollout(sessions, TODAY, "rollout-chosen.jsonl", 95.0, weekly=95.0,
                    observed=NOW - 2400, mtime=NOW - 20)
    blank_rollout(sessions, TODAY, "rollout-unread.jsonl", mtime=NOW - 100)
    assert _snap(sessions)["state"] == "uncertain"
    for seat_class in ("audit", "discretionary", "supporting"):
        t = _tripwire(seat_class, sessions)
        assert (t["action"], t["proceed"]) == ("run", True)
        assert (t["unavailable"], t["threshold_tripped"]) == (None, False)


def test_a3_tripwire_an_uncertain_reading_is_not_a_silent_admit(pre_fr1_walk, sessions):
    """Side two. The reading it proceeded on is REPORTED — an uncertain proceed is visible as
    uncertain, never dressed up as a clean one. CONTROL: the same numbers, read cleanly, trip."""
    for i in range(3):
        blank_rollout(sessions, TODAY, f"rollout-blank-{i}.jsonl", mtime=NOW - 10 - i)
    reading_rollout(sessions, TODAY, "rollout-chosen.jsonl", 99.5, weekly=99.5,
                    observed=NOW - 2400, mtime=NOW - 20)
    blank_rollout(sessions, TODAY, "rollout-unread.jsonl", mtime=NOW - 100)
    t = _tripwire("discretionary", sessions)
    assert (t["snapshot_state"], t["primary"], t["weekly"]) == ("uncertain", 99.5, 99.5)
    # CONTROL (re-pointed by #322: 99.5, was 95): the same reading, FRESH, trips the wire.
    shutil.rmtree(sessions / TODAY)
    fresh_rollout(sessions, 99.5, 99.5)
    control = _tripwire("discretionary", sessions)
    assert (control["snapshot_state"], control["action"]) == ("fresh", "substitute")


def test_a3_tripwire_reports_the_threshold_it_applied(sessions):
    fresh_rollout(sessions, 10.0, 3.0)
    assert _tripwire("discretionary", sessions)["threshold_percent"] == cq.THRESHOLD_PERCENT


# --------------------------------------------------------------------------- #
# record_skip() — the RECORDED half of a supporting seat's skip
# --------------------------------------------------------------------------- #
A3_SKIP_ROW_KEYS = {"at", "kind", "key", "cycle_id", "cycle_id_source", "cycle_id_file_age_s",
                    "use", "seat_class", "role", "requested_model", "reason", "size",
                    "size_source", "snapshot_state", "primary", "weekly"}


def _skip(reason, tmp_path, sessions, **kw):
    kw.setdefault("project_root", tmp_path / "proj")
    kw.setdefault("budget_path", budget(tmp_path))
    kw.setdefault("role", "consultant_support")
    kw.setdefault("seat_class", "supporting")
    kw.setdefault("use", None)
    return cq.record_skip(kw.pop("use"), "k1", reason, now=NOW, sessions_dir=sessions, **kw)


def test_a3_record_skip_writes_a_skip_row_that_is_never_counted(sessions, tmp_path):
    fresh_rollout(sessions, 75.0, 3.0)
    r = _skip("threshold", tmp_path, sessions, requested_model="gpt-5.6-sol")
    assert (r["row_written"], r["kind"], r["reason"]) == (True, "skip", "threshold")
    row = read_rows(budget(tmp_path))[-1]
    assert set(row) == A3_SKIP_ROW_KEYS
    assert (row["seat_class"], row["role"], row["use"]) == ("supporting", "consultant_support", None)
    assert "admitted" not in row               # a skip never spends a budget
    assert cq._count_admitted(budget(tmp_path), "k1", None, None) == 0


def test_a3_a_skip_row_is_not_a_substitution_row(sessions, tmp_path):
    """freshness_nudge's astra segment counts rows carrying `substitute_for`; a skip is not a
    substitution and must not inflate the 2026-09-28 review's substitution count."""
    fresh_rollout(sessions, 75.0, 3.0)
    _skip("threshold", tmp_path, sessions)
    row = read_rows(budget(tmp_path))[-1]
    assert "substitute_for" not in row
    assert row["kind"] == "skip" != cq.ROW_KIND_SUBSTITUTION


def test_a3_record_skip_records_a_size_and_a_size_source_unconditionally(sessions, tmp_path):
    fresh_rollout(sessions, 75.0, 3.0)
    unsized = _skip("threshold", tmp_path, sessions)
    assert (unsized["size"], unsized["size_source"]) == ("complex", "default")
    sized = _skip("threshold", tmp_path, sessions, size="light", size_source="forge")
    assert (sized["size"], sized["size_source"]) == ("light", "forge")
    user = _skip("threshold", tmp_path, sessions, size="light", size_source="user",
                 requested_by="user")
    assert user["requested_by"] == "user"
    assert read_rows(budget(tmp_path))[-1]["requested_by"] == "user"
    assert "requested_by" not in read_rows(budget(tmp_path))[0]     # CONTROL


def test_a3_record_skip_never_skips_the_audit(sessions, tmp_path):
    fresh_rollout(sessions, 75.0, 3.0)
    with pytest.raises(ValueError, match="audit"):
        _skip("threshold", tmp_path, sessions, seat_class="audit", role="code_reviewer")
    assert not budget(tmp_path).exists()


@pytest.mark.parametrize("kw,match", [
    ({"role": "chief_architect"}, "role"),
    ({"seat_class": "passenger"}, "seat_class"),
    ({"use": "consultancy"}, "use"),
])
def test_a3_record_skip_refuses_a_caller_bug(sessions, tmp_path, kw, match):
    fresh_rollout(sessions, 75.0, 3.0)
    with pytest.raises(ValueError, match=match):
        _skip("threshold", tmp_path, sessions, **kw)
    assert not budget(tmp_path).exists()


def test_a3_record_skip_refuses_a_reason_the_tripwire_cannot_produce(sessions, tmp_path):
    fresh_rollout(sessions, 75.0, 3.0)
    with pytest.raises(ValueError, match="reason"):
        _skip("budget_spent", tmp_path, sessions)
    for reason in sorted(cq.SKIP_REASONS):
        assert _skip(reason, tmp_path, sessions)["row_written"] is True


def test_a3_record_skip_accepts_a_use_from_the_vocabulary(sessions, tmp_path):
    fresh_rollout(sessions, 75.0, 3.0)
    r = _skip("threshold", tmp_path, sessions, use="ballot", role="consultant_main",
              seat_class="discretionary")
    assert (r["use"], r["seat_class"]) == ("ballot", "discretionary")


def test_a3_record_skip_survives_a_broken_store(sessions, tmp_path):
    fresh_rollout(sessions, 75.0, 3.0)
    path = budget(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()                                   # the store path is a DIRECTORY
    r = _skip("threshold", tmp_path, sessions)
    assert r["row_written"] is False and r["error"]


# --------------------------------------------------------------------------- #
# Substitution rows carry the size too (design line 95: EVERY row)
# --------------------------------------------------------------------------- #
def test_a3_substitution_rows_carry_size_and_size_source(sessions, tmp_path):
    closing_rollout(sessions, 10.0, 3.0)
    unsized = _substitute("consult", "c1", "threshold", tmp_path, sessions)
    assert (unsized["size"], unsized["size_source"]) == ("complex", "default")
    assert "requested_by" not in unsized                                  # CONTROL
    sized = _substitute("ballot", "ballot-1", "threshold", tmp_path, sessions,
                        size="light", size_source="user", requested_by="user")
    assert (sized["size"], sized["size_source"], sized["requested_by"]) == ("light", "user", "user")
    row = read_rows(budget(tmp_path))[-1]
    assert (row["size"], row["size_source"], row["requested_by"], row["key"]) == (
        "light", "user", "user", "ballot-1")


def test_a3_a_substitution_row_still_spends_no_budget(sessions, tmp_path):
    closing_rollout(sessions, 10.0, 3.0)
    _substitute("consult", "c1", "threshold", tmp_path, sessions, size="light", size_source="forge")
    assert cq._count_admitted(budget(tmp_path), "c1", None, None) == 0


# --------------------------------------------------------------------------- #
# The CLI carries the vocabulary and the schema
# --------------------------------------------------------------------------- #
def test_a3_cli_use_choices_are_the_whole_vocabulary(fixture_home, tmp_path):
    """The choices come from USES, so reading USES here would pass against ANY vocabulary —
    the false-green class. The FOUR NEW uses are named as literals instead, so a use that
    reached the table but not the CLI fails this test."""
    r = _cli(["admit", "--help"], fixture_home, tmp_path)
    assert r.returncode == 0
    for use in ("review_std", "brainstorm", "ballot", "deliberation"):
        assert use in r.stdout
    for use in sorted(cq.USES):
        assert use in r.stdout


def test_a3_cli_admit_records_the_size_and_the_class(fixture_home, tmp_path):
    _live_rollout(fixture_home, 10.0, 3.0)
    r = _cli(["admit", "--record", "--use", "review_std", "--cycle-id", "review-abc",
              "--project-root", str(tmp_path), "--size", "light", "--size-source", "forge",
              "--model-class", "std", "--requested-model", "gpt-5.6-sol"], fixture_home, tmp_path)
    assert r.returncode == 0
    d = json.loads(r.stdout)
    assert (d["admitted"], d["size"], d["size_source"], d["model_class"]) == (
        True, "light", "forge", "std")
    assert d["requested_model"] == "gpt-5.6-sol"


def test_a3_cli_admit_size_without_a_size_source_is_a_usage_error(fixture_home, tmp_path):
    _live_rollout(fixture_home, 10.0, 3.0)
    r = _cli(["admit", "--use", "consult", "--cycle-id", "c1", "--project-root", str(tmp_path),
              "--size", "light"], fixture_home, tmp_path)
    assert r.returncode == cq.EXIT_ERROR
    assert "size-source" in r.stderr or "size_source" in r.stderr


def test_a3_cli_admit_user_request_records_requested_by(fixture_home, tmp_path):
    _live_rollout(fixture_home, 10.0, 3.0)
    r = _cli(["admit", "--use", "consult", "--cycle-id", "c1", "--project-root", str(tmp_path),
              "--size", "light", "--size-source", "user", "--user-request"], fixture_home, tmp_path)
    assert r.returncode == 0
    assert json.loads(r.stdout)["requested_by"] == "user"


def test_a3_cli_admit_without_a_size_records_the_back_compat_default(fixture_home, tmp_path):
    _live_rollout(fixture_home, 10.0, 3.0)
    r = _cli(["admit", "--use", "consult", "--cycle-id", "c1", "--project-root", str(tmp_path)],
             fixture_home, tmp_path)
    assert r.returncode == 0
    d = json.loads(r.stdout)
    assert (d["size"], d["size_source"], d["model_class"]) == ("complex", "default", "top")


def test_a3_cli_admit_refuses_an_unbudgeted_class(fixture_home, tmp_path):
    _live_rollout(fixture_home, 10.0, 3.0)
    r = _cli(["admit", "--use", "review_std", "--cycle-id", "review-abc", "--project-root",
              str(tmp_path), "--size", "complex", "--size-source", "routing",
              "--model-class", "top"], fixture_home, tmp_path)
    assert r.returncode == cq.EXIT_REFUSED
    assert json.loads(r.stdout)["reason"] == "class_not_budgeted"


# --------------------------------------------------------------------------- #
# The docstring is part of the contract
# --------------------------------------------------------------------------- #
def test_a3_the_docstring_documents_the_tripwire_and_the_row_schema():
    doc = cq.__doc__ or ""
    assert "tripwire(" in doc and "record_skip(" in doc
    for token in ("model_class", "size_source", "review_std", "brainstorm", "ballot"):
        assert token in doc


# --------------------------------------------------------------------------- #
# S081 revision 4, WP-A4: the tokens freshness_nudge's digest depends on
# --------------------------------------------------------------------------- #
def test_a4_the_digest_depends_on_these_snapshot_tokens():
    """`freshness_nudge._quota_segment` renders `codex-quota: … (uncertain: <reason>)` from
    the snapshot's `state` and `reason`. It reaches them through `cq.STATE_UNCERTAIN` and
    `snap["reason"]`, so a rename here would send the digest back to SILENCE on an uncertain
    meter — the exact #282 D5 defect WP-A4 discharged — and it would do it quietly, because
    the digest swallows a broken segment by design rather than breaking the whole line.
    This is the drift guard for that coupling."""
    assert cq.STATE_UNCERTAIN == "uncertain"
    assert cq.STATE_UNKNOWN == "unknown"           # still silent: no data at all
    assert cq.STATE_FRESH == "fresh" and cq.STATE_STALE == "stale"
    assert "reason" in cq.snapshot(sessions_dir=None, now=NOW)


def test_a4_observed_too_long_ago_is_a_stale_reason_never_an_uncertain_one():
    """FINDING, recorded rather than coded around (WP-A4). The plan sources the digest's
    reason token as `STATE_UNCERTAIN / REASON_OBSERVED_TOO_LONG_AGO`, but those two never
    pair: `observed_too_long_ago` is what `_classify` returns WITH `STATE_STALE`, while
    uncertain carries `newer_candidate_unread` or `stat_budget_exhausted`. The digest
    therefore reads whatever reason the snapshot reports instead of assuming the pairing,
    which is correct either way and survives a new reason being added."""
    state, reason = cq._classify(
        {"observed_epoch": NOW - (cq.FRESH_WINDOW_S + 60),
         "primary_resets_at": None, "secondary_resets_at": None}, NOW)
    assert (state, reason) == (cq.STATE_STALE, cq.REASON_OBSERVED_TOO_LONG_AGO)
    # CONTROL: the two reasons that DO accompany uncertain are distinct from it.
    assert cq.REASON_OBSERVED_TOO_LONG_AGO not in (cq.REASON_NEWER_CANDIDATE_UNREAD,
                                                   cq.REASON_STAT_BUDGET_EXHAUSTED)


# --------------------------------------------------------------------------- #
# S081 revision 4, WP-A5: the budget row says WHICH SEAT it was
#
# L18 upheld billing a frozen TOP seat as `std` — the budget rations what is
# actually SPENT. This is what keeps that decision LEGIBLE: `requested_model`
# holds the RESOLVED model, so without a role an `arbiter` frozen to sol reads
# exactly like an ordinary `consultant_support` sol call.
# --------------------------------------------------------------------------- #
def test_a5_the_admit_role_vocabulary_is_the_skip_role_vocabulary():
    """One set, not two literals: a role that can be skipped is exactly a role that can be
    admitted. Identity (not equality) is asserted because a copy could later drift."""
    assert cq.ADMIT_ROLES is cq.SKIP_ROLES
    assert set(cq.ADMIT_ROLES) == {"code_reviewer", "consultant_main", "arbiter",
                                   "escalation", "consultant_support"}


def test_a5_an_arbiter_frozen_to_sol_is_legible_from_the_row_alone(sessions, tmp_path):
    """THE CASE THE RULING RESTS ON. Both rows are a `deliberation` call served by sol and
    billed `std`; before `role` they were IDENTICAL but for their key and ids, so telling
    an arbiter's frozen TOP seat from a support seat's ordinary call meant consulting
    freeze state held elsewhere. The discrepancy (`role: arbiter` while `model_class: std`)
    must be readable from the ROW, with nothing else loaded."""
    fresh_rollout(sessions, 10.0, 3.0)
    _sized("deliberation", "sess-arb", sessions, tmp_path, model_class="std",
           requested_model="gpt-5.6-sol", role="arbiter")
    arbiter = read_rows(budget(tmp_path))[-1]
    # CONTROL: the ordinary support call these rows used to be indistinguishable from.
    _sized("deliberation", "sess-sup", sessions, tmp_path, model_class="std",
           requested_model="gpt-5.6-sol", role="consultant_support")
    support = read_rows(budget(tmp_path))[-1]

    assert (arbiter["role"], arbiter["model_class"], arbiter["requested_model"]) == (
        "arbiter", "std", "gpt-5.6-sol")
    assert (support["role"], support["model_class"]) == ("consultant_support", "std")
    # The rows are now distinguishable, and ONLY the role distinguishes them: everything
    # that is not the seat, the budget key or a per-row id is byte-for-byte the same.
    per_row = {"at", "key", "cycle_id", "admission_id"}
    assert {k: v for k, v in arbiter.items() if k not in per_row | {"role"}} == \
           {k: v for k, v in support.items() if k not in per_row | {"role"}}
    assert arbiter["role"] != support["role"]


def test_a5_a_sized_role_frozen_to_sol_gains_corroboration_rather_than_changing(sessions, tmp_path):
    """SIZED-ROLE CONTROL. `code_reviewer` is sized, so `size: complex` + `model_class: std`
    ALREADY exposed the freeze on its own. That reading is unchanged — `role` is added
    beside it, corroborating what the pair said rather than replacing it."""
    fresh_rollout(sessions, 10.0, 3.0)
    d = _sized("advisory_review", "review-abc", sessions, tmp_path, size="complex",
               size_source="risk", model_class="std", requested_model="gpt-5.6-sol",
               role="code_reviewer")
    row = read_rows(budget(tmp_path))[-1]
    assert (row["size"], row["model_class"]) == ("complex", "std")   # the pre-existing tell
    assert row["role"] == "code_reviewer"                            # now corroborated
    assert d["role"] == row["role"]


def test_a5_a_refused_row_carries_the_role_too(sessions, tmp_path):
    """A refusal is exactly when the review asks which seat went without: a threshold
    refusal must not be the one row shape that drops the seat."""
    fresh_rollout(sessions, 99.5, 3.0)                               # RE-POINTED by #322: the threshold no longer refuses, so the refusal on its merits is a quota one.
    d = _sized("consult", "c1", sessions, tmp_path, role="consultant_main")
    assert (d["admitted"], d["reason"], d["role"]) == (False, "quota_exhausted", "consultant_main")
    assert read_rows(budget(tmp_path))[-1]["role"] == "consultant_main"


def test_a5_the_role_is_absent_when_the_caller_names_none(sessions, tmp_path):
    """ADDITIVE ONLY. An un-migrated call site writes no `role` key at all — the same
    absence every existing reader already tolerates for the other post-D16 keys."""
    fresh_rollout(sessions, 10.0, 3.0)
    d = _sized("consult", "c1", sessions, tmp_path)                  # no role
    assert "role" not in d
    assert "role" not in read_rows(budget(tmp_path))[-1]


def test_a5_an_old_shape_row_without_a_role_still_parses(sessions, tmp_path):
    """The live stores' rows carry no `role` and must keep counting. Seeded as the store
    actually holds them, then read back by the counter that enforces the budget."""
    fresh_rollout(sessions, 10.0, 3.0)
    path = budget(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({                                     # a pre-WP-A5 row
        "at": "2026-09-15T20:41:25Z", "cycle_id": "c1", "use": "consult",
        "requested_model": "gpt-6-astra", "model_class": "top", "admitted": True,
        "reason": "within_budget", "snapshot_state": "fresh", "primary": 10.0,
        "weekly": 3.0}) + "\n", encoding="utf-8")
    assert cq._count_admitted(path, "c1", "consult", None, model_class="top") == 1
    # And it still counts against a NEW roled admission on the same key: one store, one budget.
    d = _sized("consult", "c1", sessions, tmp_path, role="consultant_main")
    assert (d["admitted"], d["budget_used"]) == (False, 1)
    assert d["reason"] == "budget_spent"


@pytest.mark.parametrize("role", ["reviewer", "consultant", "", "ARBITER", 7, "bob"])
def test_a5_a_role_outside_the_seat_vocabulary_is_a_caller_bug(sessions, tmp_path, role):
    """Vocabularies are closed here, as they are for use / size / model_class: a seat the
    role table does not have cannot be recorded as having spent a slot."""
    fresh_rollout(sessions, 10.0, 3.0)
    with pytest.raises(ValueError, match="has no codex seat"):
        _sized("consult", "c1", sessions, tmp_path, role=role)
    assert not budget(tmp_path).exists()          # a caller bug leaves no row behind


# =========================================================================== #
# S081 revision 4 - D21 FIX ROUND 1, WP-X4 (docs/reviews/2026-09-22-S081-rev4-review.md)
#
# F7 (major): a "-" cell refusal, `class_not_budgeted`, was not a SUBSTITUTION_REASONS member, so the
# ONE caller that turns an admit refusal into a substitution (`seat_model.py argv --use`) crashed on
# it: exit 1, empty stdout, the seat neither run nor substituted. It is now an ordinary member and takes
# the existing D6 path (plan L36) - no new code path, never admitted unbudgeted. The CLI-level proof is
# in test_seat_model.py; this file pins the vocabulary half, DERIVED from the live table.
#
# F10 (major): a call the watchdog stopped at its RUNAWAY CAP (codex_watch.EXIT_HARD_CAP, 112, handed
# over with timed_out False) is a GAP. The classifier used to reach its exhaustion / auth / capacity
# rules first, so a runaway whose transcript carried a codex error line was retried or substituted.
# The 112 branch is now the classifier's FIRST decision after argument validation (plan L39); the gap
# keeps the reason `codex_error`, the value a plain 112 already had.
# =========================================================================== #
import codex_watch  # type: ignore  # noqa: E402  (the owner of the 112 exit; imports no _meta module)

#: The table's "-" cells, derived from the LIVE table rather than restated, so a future "-" cell is
#: covered the day it lands. Asserted equal to A3_UNBUDGETED below, so the derivation cannot go empty.
X4_UNBUDGETED_CELLS = sorted((use, cls) for use, row in cq.BUDGET_LIMITS.items()
                             for cls, limit in row.items() if limit is None)


def test_x4_F7_major_the_unbudgeted_cells_are_derived_from_the_live_table():
    assert X4_UNBUDGETED_CELLS == sorted(A3_UNBUDGETED)
    assert X4_UNBUDGETED_CELLS, "GUARD: the derivation found no cell - it looked in the wrong place"


@pytest.mark.parametrize("use,cls", X4_UNBUDGETED_CELLS)
def test_x4_F7_major_an_unbudgeted_cell_refuses_with_a_recordable_substitution_reason(sessions, tmp_path, use, cls):
    """F7, the vocabulary half: the refusal a "-" cell produces must be recordable as a substitution,
    because a refused TOP seat is served by its Claude row (D6) - and a reason record_substitution()
    rejects is a caller bug, which is how `argv --use` came to exit 1 with nothing on stdout."""
    fresh_rollout(sessions, 10.0, 3.0)
    size = "complex" if cls == "top" else "light"
    d = _sized(use, "k1", sessions, tmp_path, size=size, model_class=cls, role="code_reviewer")
    assert (d["admitted"], d["reason"]) == (False, cq.REASON_CLASS_NOT_BUDGETED)
    assert d["reason"] in cq.SUBSTITUTION_REASONS
    requested = "gpt-6-astra" if cls == "top" else "gpt-5.6-sol"
    result = cq.record_substitution(use, "k1", d["reason"], project_root=tmp_path / "proj", role="code_reviewer",
                                    served_model="fable", requested_model=requested, now=NOW,
                                    budget_path=budget(tmp_path), sessions_dir=sessions,
                                    size=size, size_source="routing")
    assert result["row_written"] is True
    rows = read_rows(budget(tmp_path))
    subs = [r for r in rows if r.get("kind") == "substitution"]
    assert [(r["reason"], r["use"], r["served_model"], r["requested_model"], r["admission_id"]) for r in subs] == \
        [(cq.REASON_CLASS_NOT_BUDGETED, use, "fable", requested, None)]
    # Never admitted unbudgeted (design s2.2 kept): the refusal row is the only admit row, and it refused.
    assert [(r["admitted"], r["reason"]) for r in rows if "admitted" in r] == [(False, cq.REASON_CLASS_NOT_BUDGETED)]


def test_x4_F7_control_a_reason_outside_the_vocabulary_is_still_a_caller_bug(tmp_path):
    """CONTROL: joining the set did not open it. A reason no refusal can produce is still refused, and
    nothing is written."""
    with pytest.raises(ValueError, match="unknown substitution reason"):
        cq.record_substitution("advisory_review", "k1", "class_budgeted_elsewhere", project_root=tmp_path / "proj",
                               role="code_reviewer", served_model="fable", now=NOW, budget_path=budget(tmp_path))
    assert not budget(tmp_path).exists()


#: A codex-owned error line of every signal family the classifier reads, in both error-line shapes.
X4_ERROR_LINES = {
    "capacity": "ERROR: Selected model is at capacity. Please try a different model.\n",
    "exhaustion_429": "ERROR: exceeded retry limit, last status: 429 Too Many Requests\n",
    "usage_limit": "ERROR: You've hit your usage limit. Upgrade to Plus to continue using Codex\n",
    "quota_exceeded": "ERROR: Quota exceeded. Check your plan and billing details.\n",
    "auth_401": "ERROR: unexpected status 401 Unauthorized: {}\n",
    "auth_tracing": ("2026-09-15T16:56:37.647031Z ERROR codex_api::endpoint::responses_websocket: failed to "
                     "connect to websocket: HTTP error: 401 Unauthorized, url: wss://api.openai.com/v1/responses\n"),
}
#: What each line decides on an ORDINARY failed exit (returncode 1): today's classification, which F10
#: must not move. Attempt 3 behaves as attempt 2.
X4_RC1_EXPECTED = {
    "capacity": {1: ("retry", "capacity"), 2: ("substitute", "capacity_twice")},
    "exhaustion_429": {1: ("substitute", "quota_exhausted"), 2: ("substitute", "quota_exhausted")},
    "usage_limit": {1: ("substitute", "quota_exhausted"), 2: ("substitute", "quota_exhausted")},
    "quota_exceeded": {1: ("substitute", "quota_exhausted"), 2: ("substitute", "quota_exhausted")},
    "auth_401": {1: ("substitute", "auth_failure"), 2: ("substitute", "auth_failure")},
    "auth_tracing": {1: ("substitute", "auth_failure"), 2: ("substitute", "auth_failure")},
}
X4_GAP = ("gap", "codex_error")


def test_x4_F10_the_line_tables_cover_the_same_signals():
    assert set(X4_ERROR_LINES) == set(X4_RC1_EXPECTED) and len(X4_ERROR_LINES) == 6


@pytest.mark.parametrize("attempt", [1, 2, 3])
@pytest.mark.parametrize("line", sorted(X4_ERROR_LINES))
def test_x4_F10_major_a_hard_capped_call_is_a_gap_whatever_its_stderr_says(line, attempt):
    """F10: a call that stayed ACTIVE to its runaway cap is not the retryable kind of stop, and a codex
    error line in its transcript does not make it one - not on the first attempt, not on a later one."""
    stderr = BANNER + X4_ERROR_LINES[line]
    assert cq.classify_codex_failure(codex_watch.EXIT_HARD_CAP, stderr, timed_out=False, output_ok=False,
                                     attempt=attempt) == X4_GAP


@pytest.mark.parametrize("token", ["quota_exhausted", "rate_limit_reached"])
def test_x4_F10_major_an_agreeing_meter_does_not_turn_a_hard_cap_into_a_substitution(token):
    """The meter-agreement rule (#282 R2) read a bare exhaustion phrase as a quota stop when the meter
    agreed. On a hard-capped call that is still a runaway, not a quota stop."""
    stderr = BANNER + "log: You've hit your usage limit.\n"
    agreeing = {"codex_error_lines": [], "unavailable_token": token}
    for attempt in (1, 2):
        assert cq.classify_codex_failure(codex_watch.EXIT_HARD_CAP, stderr, timed_out=False, output_ok=False,
                                         attempt=attempt, corroboration=agreeing) == X4_GAP
    # CONTROL: the same evidence on an ordinary failed exit is the meter-agreement substitution, as today.
    assert cq.classify_codex_failure(1, stderr, timed_out=False, output_ok=False, attempt=1,
                                     corroboration=agreeing) == ("substitute", "quota_exhausted")


@pytest.mark.parametrize("attempt", [1, 2])
@pytest.mark.parametrize("line", ["capacity", "exhaustion_429", "auth_401"])
def test_x4_F10_major_the_classify_cli_gaps_a_hard_capped_call(fixture_home, tmp_path, line, attempt):
    """The path the codex_top_seat block runs: the watchdog's exit is handed to `classify --exit-code`."""
    err = tmp_path / "stderr.txt"
    err.write_text(BANNER + X4_ERROR_LINES[line], encoding="utf-8")
    r = _cli(["classify", "--exit-code", str(codex_watch.EXIT_HARD_CAP), "--attempt", str(attempt),
              "--stderr-file", str(err), "--output-file", str(tmp_path / "absent-output.txt")],
             fixture_home, tmp_path)
    assert (r.returncode, r.stdout) == (0, "gap codex_error\n"), r.stderr
    # CONTROL, same file: an ordinary failed exit classifies exactly as today.
    r1 = _cli(["classify", "--exit-code", "1", "--attempt", str(attempt), "--stderr-file", str(err),
               "--output-file", str(tmp_path / "absent-output.txt")], fixture_home, tmp_path)
    assert (r1.returncode, r1.stdout) == (0, "%s %s\n" % X4_RC1_EXPECTED[line][attempt]), r1.stderr


@pytest.mark.parametrize("attempt", [1, 2, 3])
@pytest.mark.parametrize("line", sorted(X4_ERROR_LINES))
def test_x4_F10_control_an_ordinary_failure_with_the_same_lines_classifies_as_today(line, attempt):
    stderr = BANNER + X4_ERROR_LINES[line]
    assert cq.classify_codex_failure(1, stderr, timed_out=False, output_ok=False,
                                     attempt=attempt) == X4_RC1_EXPECTED[line][min(attempt, 2)]


def test_x4_F10_control_the_idle_stop_still_retries_then_substitutes():
    """The watchdog's OTHER stop (111, handed over as returncode None + timed_out True) keeps its retry."""
    assert cq.classify_codex_failure(None, BANNER, timed_out=True, output_ok=False, attempt=1) == ("retry", "timeout")
    assert cq.classify_codex_failure(None, BANNER, timed_out=True, output_ok=False,
                                     attempt=2) == ("substitute", "timeout_twice")


def test_x4_F10_control_a_plain_hard_cap_is_unchanged():
    for attempt in (1, 2, 3):
        assert cq.classify_codex_failure(codex_watch.EXIT_HARD_CAP, BANNER, timed_out=False, output_ok=False,
                                         attempt=attempt) == X4_GAP
        assert cq.classify_codex_failure(codex_watch.EXIT_HARD_CAP, "", timed_out=False, output_ok=False,
                                         attempt=attempt) == X4_GAP


def test_x4_F10_control_the_rule_is_for_a_call_that_did_not_time_out():
    """The rule reads `not timed_out and returncode == 112`. A caller that reports a TIMED-OUT call keeps
    the timeout rules whatever its exit status (GNU timeout exits 124; a 112 flagged timed out is treated
    the same), so the retryable stop is never swallowed by the runaway rule."""
    rc = codex_watch.EXIT_HARD_CAP
    assert cq.classify_codex_failure(rc, BANNER, timed_out=True, output_ok=False, attempt=1) == ("retry", "timeout")
    assert cq.classify_codex_failure(rc, BANNER, timed_out=True, output_ok=False,
                                     attempt=2) == ("substitute", "timeout_twice")
    assert cq.classify_codex_failure(rc, BANNER + X4_ERROR_LINES["capacity"], timed_out=True, output_ok=False,
                                     attempt=1) == ("retry", "capacity")


def test_x4_F10_control_argument_validation_still_precedes_the_hard_cap_rule():
    """A caller bug is still a caller bug on a 112: validation is not skipped by the first decision."""
    with pytest.raises(ValueError):
        cq.classify_codex_failure(codex_watch.EXIT_HARD_CAP, "", timed_out=False, output_ok=False, attempt=0)
    with pytest.raises(ValueError):
        cq.classify_codex_failure(codex_watch.EXIT_HARD_CAP, "", timed_out=False, output_ok=False, attempt=1,
                                  corroboration={"codex_error_lines": "ERROR: x"})


def _int_constants(source, value):
    return [node.lineno for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant) and type(node.value) is int and node.value == value]


def test_x4_F10_the_hard_cap_exit_has_one_definition():
    """ONE definition of 112 (plan L39): codex_watch owns it and codex_quota binds it by import, so the
    watchdog and the classifier cannot drift apart. codex_watch imports no _meta module (no cycle)."""
    assert cq.EXIT_HARD_CAP == codex_watch.EXIT_HARD_CAP == 112
    assert _int_constants(_MODULE_PATH.read_text(encoding="utf-8"), codex_watch.EXIT_HARD_CAP) == []
    # No cycle: codex_watch's MODULE-LEVEL imports (what runs when codex_quota imports it) name no _meta
    # module. Its `__main__` block (portable_cli) and its function-local imports run only when called.
    watch_body = ast.parse((_META / "codex_watch.py").read_text(encoding="utf-8")).body
    watch_imports = {alias.name.split(".")[0] for node in watch_body
                     if isinstance(node, ast.Import) for alias in node.names}
    watch_imports |= {node.module.split(".")[0] for node in watch_body
                      if isinstance(node, ast.ImportFrom) and node.module}
    local = {path.stem for path in _META.glob("*.py")}
    assert watch_imports and watch_imports & local == set(), watch_imports & local
    # NEGATIVE CONTROL: the literal check does find a second definition.
    assert _int_constants("EXIT_HARD_CAP = 112\n", codex_watch.EXIT_HARD_CAP) == [1]


#: The CLI help's "Actions" list as it stood at the round base (13a3e04), first two lines VERBATIM -
#: NEGATIVE CONTROL only (~/.claude is not a git repository, so it is embedded, never read through git).
_X4_BASE_HELP_ACTIONS = """\
Actions, first match wins:
  ok -                         exit 0, usable output, not timed out
  substitute cli_missing       exit 127 (command not found)
"""
#: The module docstring's classifier order as it stood at the round base, first entries VERBATIM.
_X4_BASE_DOC_ORDER = """\
  corroboration) -> (action, reason), in this order:
    ok          exit 0 with usable output (not timed out). A signal on stderr of such a
                run (a retried 429) did not stop the call and changes nothing.
    substitute  cli_missing       exit 127 (a spawn FileNotFoundError is passed as 127);
"""


def _x4_first_help_action(text):
    lines = text[text.index("Actions, first match wins:"):].splitlines()[1:]
    return next(line for line in lines if line.strip())


def _x4_first_doc_action(text):
    lines = text[text.index("-> (action, reason), in this order:"):].splitlines()[1:]
    return next(line for line in lines if line.strip())


def _x4_names_the_hard_cap_gap(line):
    return line.split()[:2] == ["gap", "codex_error"] and "112" in line


def test_x4_F10_the_help_and_the_docstring_state_the_hard_cap_rule_first():
    """GUARD: the order is documented where a reader looks for it - the classify CLI's help and the
    module docstring's ASTRA UNAVAILABLE list - with the hard-cap gap FIRST."""
    assert _x4_names_the_hard_cap_gap(_x4_first_help_action(cq._CLASSIFY_HELP))
    assert _x4_names_the_hard_cap_gap(_x4_first_doc_action(cq.__doc__))
    assert cq._CLASSIFY_HELP.isascii()
    # NEGATIVE CONTROL: the guard fires on the base text, whose first action is `ok`.
    assert not _x4_names_the_hard_cap_gap(_x4_first_help_action(_X4_BASE_HELP_ACTIONS))
    assert not _x4_names_the_hard_cap_gap(_x4_first_doc_action(_X4_BASE_DOC_ORDER))


# --------------------------------------------------------------------------- #
# #302 WP-4 (design §3.5, challenger #2) — per-model attribution on a SHARED admission
# --------------------------------------------------------------------------- #
# The avengers once-per-class admission covers EVERY codex seat of that class in a session. From
# roster rev 3 one std admission can cover two different models (a sized std main seat on
# gpt-6-sol and a supporting seat on gpt-5.6-terra), so the row names every model and role it
# covers. The literals below are SYNTHETIC inputs (this module never resolves a model).
_302_STD_MAIN = "gpt-6-sol"
_302_SUPPORT = "gpt-5.6-terra"


def test_302_a_shared_admission_stores_every_model_and_counts_once_against_std(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    d = _sized("deliberation", "sess-302", sessions, tmp_path, model_class="std",
               requested_model=_302_STD_MAIN, role="consultant_main",
               models=[_302_STD_MAIN, _302_SUPPORT], roles=["consultant_main", "consultant_support"])
    assert d["admitted"] is True
    assert d["models"] == [_302_STD_MAIN, _302_SUPPORT]
    assert d["roles"] == ["consultant_main", "consultant_support"]
    rows = read_rows(budget(tmp_path))
    assert len(rows) == 1
    assert rows[0]["models"] == [_302_STD_MAIN, _302_SUPPORT]
    assert rows[0]["roles"] == ["consultant_main", "consultant_support"]
    assert rows[0]["model_class"] == "std"
    # ONE admission, ONE slot: two models on the row do not spend two std slots.
    path = budget(tmp_path)
    assert cq._count_admitted(path, "sess-302", "deliberation", None, model_class="std") == 1
    assert cq._count_admitted(path, "sess-302", "deliberation", None, model_class="top") == 0
    # The session's std budget (1 seat/session) is now spent, whatever the second call names.
    again = _sized("deliberation", "sess-302", sessions, tmp_path, model_class="std",
                   requested_model=_302_SUPPORT, models=[_302_SUPPORT])
    assert (again["admitted"], again["reason"]) == (False, "budget_spent")


def test_302_a_legacy_row_without_models_loads_and_counts_as_before(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    path = budget(tmp_path)
    path.parent.mkdir(parents=True)
    legacy = {"at": "2026-09-14T15:00:00Z", "key": "sess-old", "cycle_id": "sess-old",
              "use": "deliberation", "size": "complex", "size_source": "default",
              "requested_model": "gpt-5.6-sol", "model_class": "std", "admitted": True,
              "reason": "within_budget", "snapshot_state": "fresh", "primary": 10.0, "weekly": 3.0,
              "admission_id": "0" * 32, "role": "consultant_support"}
    path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    assert cq._count_admitted(path, "sess-old", "deliberation", None, model_class="std") == 1
    d = _sized("deliberation", "sess-old", sessions, tmp_path, model_class="std",
               requested_model=_302_SUPPORT)
    assert (d["admitted"], d["reason"]) == (False, "budget_spent")
    # A caller that names no models writes no key (additive, like `role`).
    assert "models" not in d and "roles" not in d
    assert "models" not in read_rows(path)[-1] and "roles" not in read_rows(path)[-1]


def test_302_model_classes_and_budgets_are_unchanged_by_the_support_tier():
    assert set(cq.MODEL_CLASSES) == {"top", "std"}
    assert dict(cq.BUDGET_LIMITS["deliberation"]) == {"top": 1, "std": 1}


@pytest.mark.parametrize("kwargs", [
    {"models": []},
    {"models": "gpt-6-sol"},
    {"models": ["gpt 6 sol"]},
    {"models": [None]},
    {"models": ["gpt-6-sol", "gpt-6-sol"]},
    {"roles": ["not_a_seat"]},
    {"roles": []},
    {"roles": "consultant_main"},
    {"requested_model": "gpt-6-astra", "models": ["gpt-6-sol"]},
])
def test_302_malformed_models_or_roles_are_caller_bugs_and_write_nothing(sessions, tmp_path, kwargs):
    fresh_rollout(sessions, 10.0, 3.0)
    kwargs = dict(kwargs)
    kwargs.setdefault("requested_model", "gpt-6-sol")
    with pytest.raises(ValueError):
        _sized("deliberation", "sess-bad", sessions, tmp_path, model_class="std", **kwargs)
    assert not budget(tmp_path).exists()


def test_302_check_only_decision_carries_the_models_it_would_record(sessions, tmp_path):
    fresh_rollout(sessions, 10.0, 3.0)
    d = _sized("deliberation", "sess-co", sessions, tmp_path, model_class="std", record=False,
               requested_model=_302_STD_MAIN, models=[_302_STD_MAIN, _302_SUPPORT])
    assert d["recorded"] is False and d["admission_id"] is None
    assert d["models"] == [_302_STD_MAIN, _302_SUPPORT]
    assert not budget(tmp_path).exists()


def test_302_the_module_names_no_std_or_support_slug_outside_dated_history():
    """design §3.8: codex_quota's prose uses tier wording; the one surviving `gpt-5.6-sol` is the
    dated 2026-09 probe command (history)."""
    source = Path(cq.__file__).read_text(encoding="utf-8")
    hits = [line for line in source.splitlines() if "gpt-5.6-sol" in line]
    assert len(hits) == 1 and "codex exec" in hits[0], hits


# =========================================================================== #
# #322 — await-reset: wait for a quota reset, probing codex (DW-3, DW-5)
#
# Every test injects the clock, the sleep and the probe: nothing here sleeps for real or calls codex.
# The real probe's own path (run_probe) is driven through a fake codex_watch, never a codex binary.
# =========================================================================== #
class _FakeTime:
    """An epoch clock that only moves when the code under test sleeps."""

    def __init__(self, start=NOW):
        self.t = float(start)
        self.sleeps = []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        assert seconds > 0, seconds
        self.sleeps.append(round(seconds, 6))
        self.t += seconds


def _scripted_probe(clock, outcomes, on_available=None):
    """A probe that returns `outcomes` in order (the last one repeats) and logs WHEN it was called.
    `on_available` runs on an answering probe (it writes the probe's own rollout, as a real one would)."""
    calls = []

    def probe():
        calls.append(clock())
        outcome = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if outcome == "available" and on_available is not None:
            on_available()
        return outcome, (0 if outcome == "available" else 1)

    probe.calls = calls
    return probe


_PROBE_SEQ = [0]


def _probe_rollout(sessions, observed, primary, weekly=3.0, p_resets=None):
    """The rollout an answering probe writes: a reading observed at `observed`, the newest file by mtime."""
    _PROBE_SEQ[0] += 1
    path = write_rollout(sessions, "2026/09/14", f"rollout-probe-{_PROBE_SEQ[0]:04d}.jsonl",
                         [rl_event(observed, primary, weekly, p_resets=p_resets)])
    return set_mtime(path, observed)


def _await(tmp_path, sessions, clock, probe, **kw):
    return cq.await_reset(project_root=tmp_path / "proj", sessions_dir=sessions, budget_path=budget(tmp_path),
                          clock=clock, sleep=clock.sleep, probe=probe, **kw)


def test_322_await_reset_close_sleeps_to_the_reset_plus_margin_then_probes(sessions, tmp_path):
    """DW-3 reset close (`wait`): probe at once, sleep until resets_at + margin, confirm with one probe."""
    fresh_rollout(sessions, 99.5, 3.0, p_resets=int(NOW + 600))
    clock = _FakeTime()
    probe = _scripted_probe(clock, ["exhausted", "available"])
    code, out = _await(tmp_path, sessions, clock, probe)
    assert code == 0
    assert clock.sleeps == [660.0]                                   # 600 s to the reset + the 60 s margin
    assert probe.calls == [NOW, NOW + 660.0]                         # the confirming probe comes AFTER the sleep
    assert out == {"available": True, "waited_s": 660, "probes": 2, "source": "reset",
                   "binding_window": "primary", "resets_at": int(NOW + 600), "resets_in_s": 600,
                   "wait_advice": "wait"}


def test_322_await_reset_far_polls_and_reports_a_user_reset(sessions, tmp_path):
    """DW-3 reset far (`notify`): poll every --poll seconds; codex answering BEFORE resets_at is user_reset.
    RE-POINTED by #322 fix round 1 (minor 1): the answering probe's own rollout shows the headroom (a reading
    NEWER than the probe, below 99%) -- user_reset is reported only on that evidence."""
    fresh_rollout(sessions, 99.5, 3.0)                                # the primary resets ~2 h away
    clock = _FakeTime()
    probe = _scripted_probe(clock, ["exhausted", "exhausted", "available"],
                            on_available=lambda: _probe_rollout(sessions, clock(), 4.0))
    code, out = _await(tmp_path, sessions, clock, probe, poll=120)
    assert (code, out["available"], out["source"], out["probes"]) == (0, True, "user_reset", 3)
    assert clock.sleeps == [120.0, 120.0]
    assert out["wait_advice"] == "notify" and out["waited_s"] == 240


def test_322_await_reset_a_probe_after_the_reset_time_is_a_plain_reset(sessions, tmp_path):
    """CONTROL for user_reset: the same success AFTER resets_at is `reset`."""
    fresh_rollout(sessions, 99.5, 3.0, p_resets=int(NOW + 1500))       # 25 min: notify, not wait
    clock = _FakeTime()
    probe = _scripted_probe(clock, ["exhausted"] * 13 + ["available"])
    code, out = _await(tmp_path, sessions, clock, probe, poll=120)
    assert (code, out["source"], out["wait_advice"]) == (0, "reset", "notify")
    assert clock() >= NOW + 1500


def test_322_await_reset_times_out_with_exit_4(sessions, tmp_path):
    """DW-3 timeout: still exhausted at --max-wait -> exit 4. RE-POINTED by #322 fix round 2 (m3): a probe
    needs PROBE_MIN_LEFT_S; the one that used to land ON the deadline (0 s left, run on a 30 s floor that
    overran --max-wait) is skipped, so 3 probes, the last at NOW + 240."""
    fresh_rollout(sessions, 99.5, 3.0)
    clock = _FakeTime()
    probe = _scripted_probe(clock, ["exhausted"])
    code, out = _await(tmp_path, sessions, clock, probe, max_wait=300, poll=120)
    assert code == cq.EXIT_AWAIT_TIMEOUT == 4
    assert clock.sleeps == [120.0, 120.0, 60.0]
    assert probe.calls[-1] == NOW + 240
    assert (out["available"], out["source"], out["probes"], out["waited_s"]) == (False, "timeout", 3, 300)


def test_322_await_reset_close_that_is_still_exhausted_after_the_reset_keeps_polling(sessions, tmp_path):
    fresh_rollout(sessions, 99.5, 3.0, p_resets=int(NOW + 600))
    clock = _FakeTime()
    probe = _scripted_probe(clock, ["exhausted", "exhausted", "exhausted", "available"])
    code, out = _await(tmp_path, sessions, clock, probe, poll=120)
    assert (code, out["probes"]) == (0, 4)
    assert clock.sleeps == [660.0, 120.0, 120.0]


@pytest.mark.parametrize("outcomes,sleeps", [(["auth"], []), (["exhausted", "auth"], [120.0])])
def test_322_await_reset_an_auth_failure_exits_5_without_waiting(sessions, tmp_path, outcomes, sleeps):
    """DW-3 auth failure: exit 5 at once, never another sleep. Auth is not quota (design item 6)."""
    fresh_rollout(sessions, 99.5, 3.0)
    clock = _FakeTime()
    probe = _scripted_probe(clock, outcomes)
    code, out = _await(tmp_path, sessions, clock, probe, poll=120)
    assert code == cq.EXIT_AWAIT_AUTH == 5
    assert clock.sleeps == sleeps
    assert (out["available"], out["source"], out["probes"]) == (False, "auth_failure", len(outcomes))


def test_322_await_reset_a_missing_cli_exits_3_without_waiting(sessions, tmp_path):
    fresh_rollout(sessions, 99.5, 3.0)
    clock = _FakeTime()
    code, out = _await(tmp_path, sessions, clock, _scripted_probe(clock, ["cli_missing"]))
    assert (code, out["source"], clock.sleeps) == (3, "cli_missing", [])


def test_322_await_reset_an_already_available_codex_returns_at_once(sessions, tmp_path):
    fresh_rollout(sessions, 99.5, 3.0)
    clock = _FakeTime()
    code, out = _await(tmp_path, sessions, clock, _scripted_probe(clock, ["available"]))
    assert (code, out["probes"], clock.sleeps) == (0, 1, [])


@pytest.mark.parametrize("bad", [{"max_wait": 0}, {"poll": 0}, {"margin": -1}, {"poll": float("nan")},
                                 {"max_wait": True}])
def test_322_await_reset_rejects_bad_timings(sessions, tmp_path, bad):
    clock = _FakeTime()
    with pytest.raises(ValueError):
        _await(tmp_path, sessions, clock, _scripted_probe(clock, ["available"]), **bad)


def test_322_every_probe_is_a_probe_row_that_spends_no_budget(sessions, tmp_path):
    """DW-5: each probe is recorded as `kind: probe`, `use: probe`; it has no `admitted` key, so it never
    counts against a per-round budget, and no `substitute_for`, so it never counts as a substitution."""
    fresh_rollout(sessions, 99.5, 3.0)
    clock = _FakeTime()
    _await(tmp_path, sessions, clock, _scripted_probe(clock, ["exhausted", "exhausted", "available"]), poll=120)
    rows = read_rows(budget(tmp_path))
    assert [(r["kind"], r["use"], r["outcome"]) for r in rows] == [
        ("probe", "probe", "exhausted"), ("probe", "probe", "exhausted"), ("probe", "probe", "available")]
    for r in rows:
        assert "admitted" not in r and "substitute_for" not in r
        assert r["requested_model"] == cq.probe_model()
    key = rows[0]["key"]
    assert cq._count_admitted(budget(tmp_path), key, "consult", None) == 0
    # The probes spent nothing: a consult on the same key is still admitted once the meter recovers.
    fresh_rollout(sessions, 10.0, 3.0)
    assert _admit("consult", key, sessions, tmp_path)["reason"] == "within_budget"


def test_322_record_probe_refuses_an_unknown_outcome_and_survives_a_broken_store(sessions, broken_budget):
    with pytest.raises(ValueError):
        cq.record_probe("maybe", project_root=None, budget_path=broken_budget, now=NOW, sessions_dir=sessions)
    r = cq.record_probe("exhausted", project_root=None, budget_path=broken_budget, now=NOW, sessions_dir=sessions)
    assert r["row_written"] is False and r["error"]


def test_322_the_real_probe_is_never_ephemeral_and_runs_the_support_tier_at_low_effort(tmp_path):
    import model_roster  # type: ignore

    argv = cq.probe_argv(cq.probe_model(), tmp_path / "out.txt")
    assert "--ephemeral" not in argv
    assert argv[:2] == ["codex", "exec"] and argv[-1] == cq.PROBE_PROMPT
    assert argv[argv.index("-m") + 1] == model_roster.CODEX_SUPPORT
    assert "model_reasoning_effort=low" in argv and argv[argv.index("-s") + 1] == "read-only"


def _fake_watch(monkeypatch, *, exit_code, stderr="", output="OK\n"):
    """Stand in for codex_watch.codex_watch: write the planned stderr and -o file, return a result."""
    seen = {}

    def fake(argv, *, effort, stdout_path, stderr_path, **kw):
        seen.update(argv=list(argv), effort=effort, kw=kw)
        Path(stderr_path).write_text(stderr, encoding="utf-8")
        Path(stdout_path).write_text("", encoding="utf-8")
        out = Path(argv[argv.index("-o") + 1])
        if output:
            out.write_text(output, encoding="utf-8")

        class _R:
            pass
        r = _R()
        r.exit_code, r.timed_out = exit_code, False
        return r

    monkeypatch.setattr(cq.codex_watch, "codex_watch", fake)
    return seen


@pytest.mark.parametrize("exit_code,stderr,output,outcome", [
    (0, "", "OK\n", "available"),
    (1, "ERROR: You've hit your usage limit. Upgrade to Pro or try again later.\n", "", "exhausted"),
    (1, "ERROR: unexpected status 401 Unauthorized: Incorrect API key provided\n", "", "auth"),
    (1, "something else broke\n", "", "error"),
])
def test_322_run_probe_classifies_through_the_one_classifier(monkeypatch, sessions, exit_code, stderr, output,
                                                             outcome):
    seen = _fake_watch(monkeypatch, exit_code=exit_code, stderr=stderr, output=output)
    assert cq.run_probe(model="gpt-5.6-terra", sessions_dir=sessions) == (outcome, exit_code)
    assert "--ephemeral" not in seen["argv"] and seen["effort"] == "low"
    assert seen["kw"]["hard_cap_s"] == cq.PROBE_HARD_CAP_S and seen["kw"]["record_telemetry"] is False


def test_322_run_probe_a_missing_codex_is_cli_missing(monkeypatch, sessions):
    def missing(*a, **k):
        raise FileNotFoundError("codex")
    monkeypatch.setattr(cq.codex_watch, "codex_watch", missing)
    assert cq.run_probe(model="gpt-5.6-terra", sessions_dir=sessions) == ("cli_missing", 127)


@pytest.mark.parametrize("outcome,code", [("available", 0), ("auth", 5)])
def test_322_cli_await_reset_prints_one_json_line(monkeypatch, capsys, fixture_home, project, outcome, code):
    monkeypatch.setattr(cq, "run_probe", lambda **kw: (outcome, 0))
    rc = cq.main(["await-reset", "--project-root", str(project)])
    out, err = capsys.readouterr()
    assert rc == code
    lines = out.strip().splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert set(result) >= {"available", "waited_s", "probes", "source"}
    assert result["available"] is (outcome == "available")
    if outcome == "auth":
        assert "codex login" in err


def test_322_cli_await_reset_times_out_with_exit_4(monkeypatch, capsys, fixture_home, project):
    clock = _FakeTime(start=1_000_000.0)
    monkeypatch.setattr(cq, "run_probe", lambda **kw: ("exhausted", 1))
    monkeypatch.setattr(cq.time, "time", clock)
    monkeypatch.setattr(cq.time, "sleep", clock.sleep)
    rc = cq.main(["await-reset", "--max-wait", "10", "--poll", "4", "--project-root", str(project)])
    out, _ = capsys.readouterr()
    assert rc == 4 and json.loads(out)["source"] == "timeout"
    # RE-POINTED by #322 fix round 2 (m3): at 8 s only 2 s are left (< PROBE_MIN_LEFT_S): no probe, no sleep.
    assert clock.sleeps == [4.0, 4.0]


def test_322_cli_await_reset_help_is_ascii_and_names_the_exit_codes(fixture_home, project):
    r = _cli(["await-reset", "--help"], fixture_home, project, {"PYTHONIOENCODING": "cp1252"})
    assert r.returncode == 0 and r.stdout.isascii()
    text = " ".join(r.stdout.split())
    for needle in ("BACKGROUND", "0 available, 4", "5 auth", "quota_exhausted_timeout", "NOT --ephemeral"):
        assert needle in text, needle


def test_322_quota_exhausted_timeout_is_a_substitution_reason(sessions, tmp_path):
    """DW-5: record_substitution accepts the new reason; the row is an ordinary substitution row."""
    assert cq.REASON_QUOTA_EXHAUSTED_TIMEOUT == "quota_exhausted_timeout" in cq.SUBSTITUTION_REASONS
    r = cq.record_substitution("consult", "c1", "quota_exhausted_timeout", project_root=tmp_path / "proj",
                               role="consultant_main", served_model="opus", now=NOW, sessions_dir=sessions,
                               budget_path=budget(tmp_path))
    assert r["row_written"] is True
    row = read_rows(budget(tmp_path))[-1]
    assert (row["kind"], row["reason"], row["substitute_for"]) == ("substitution", "quota_exhausted_timeout", "codex")


def test_322_the_docstring_records_the_retired_threshold_with_its_date_and_quote():
    doc = " ".join(cq.__doc__.split())
    assert "#322 (2026-09-27): THE 70% THRESHOLD NO LONGER REFUSES" in doc
    assert "use codex and let me know when is used 100% i will reset it" in doc
    assert "await-reset" in doc and 'kind: "probe"' in doc


# =========================================================================== #
# #322 fix round 1 — F1 (probes blind the meter; a stale reading admits), F2 (quota before budget),
# minors 1-4 and the --cycle-id nit. Every test injects the clock, the sleep and the probe.
# =========================================================================== #
def _real_then_probes(sessions, n_probes, *, primary=100.0, p_resets=None):
    """The live 2026-09-28 shape: the real exhausted reading, then n usage-limit probe rollouts NEWER by
    mtime whose only rate_limits object is `limit_id: premium, primary: null`."""
    real = write_rollout(sessions, TODAY, "rollout-a-real.jsonl",
                         [rl_event(NOW - 600, primary, 50.0, p_resets=p_resets or int(NOW + 2400))])
    set_mtime(real, NOW - 600)
    for i in range(1, n_probes + 1):
        set_mtime(write_rollout(sessions, TODAY, f"rollout-p{i}.jsonl", [premium_null(NOW - 500 + i * 60)]),
                  NOW - 500 + i * 60)


@pytest.mark.parametrize("n_probes", [4, 5, 12])
def test_322_fr1_usage_limit_probe_rollouts_no_longer_blind_the_meter(sessions, tmp_path, n_probes):
    """F1 part 1 (the stand-in's blind.py): before the fix, 4+ probe rollouts pushed the real 100% reading
    out of the 4-file window -> `unknown (no_rate_limits)` -> admit let the seat through."""
    _real_then_probes(sessions, n_probes)
    snap = _snap(sessions)
    assert (snap["state"], snap["primary_used_percent"]) == ("fresh", 100.0)
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "quota_exhausted"
    d = _admit("challenger", "k1", sessions, tmp_path, model_class="std")
    assert (d["admitted"], d["reason"], d["unavailable_source"]) == (False, "quota_exhausted", "meter")
    assert d["resets_at"] == int(NOW + 2400)


def test_322_fr1_a_stale_reading_after_a_30_minute_wait_still_refuses(sessions, tmp_path, fixture_home):
    """F1 part 2: the recorded refusal persists "exhausted until resets_at"; 31 minutes later the reading is
    stale (it no longer refuses on its own) but the record does, with the SAME reset time. CONTROL: the same
    stale reading without the record admits (the pre-fix hole)."""
    fresh_rollout(sessions, 100.0, 3.0, p_resets=int(NOW + 2 * HOUR))
    first = _admit("consult", "c1", sessions, tmp_path)
    assert (first["reason"], first["exhausted_recorded"]) == ("quota_exhausted", True)
    later = NOW + 31 * 60
    assert cq.snapshot(sessions_dir=sessions, now=later)["state"] == "stale"
    d = cq.admit("consult", "c2", project_root=tmp_path / "proj", budget_path=budget(tmp_path), now=later,
                 sessions_dir=sessions)
    assert (d["admitted"], d["reason"], d["unavailable_source"]) == (False, "quota_exhausted", "exhausted_record")
    assert (d["resets_at"], d["resets_in_s"], d["wait_advice"]) == (int(NOW + 2 * HOUR), int(2 * HOUR - 31 * 60),
                                                                   "notify")
    (fixture_home / ".claude" / "state" / "codex-exhausted.json").unlink()
    control = cq.admit("consult", "c3", project_root=tmp_path / "proj", budget_path=budget(tmp_path), now=later,
                       sessions_dir=sessions)
    assert (control["admitted"], control["reason"]) == (True, "within_budget")


def test_322_fr1_a_newer_reading_with_headroom_supersedes_the_record(sessions, tmp_path):
    fresh_rollout(sessions, 100.0, 3.0, p_resets=int(NOW + 2 * HOUR))
    assert _admit("consult", "c1", sessions, tmp_path)["reason"] == "quota_exhausted"
    later = NOW + 40 * 60
    # still exhausted on a NEWER reading -> the meter itself refuses (and the record stands)
    _probe_rollout(sessions, later - 30, 99.5, p_resets=int(NOW + 2 * HOUR))
    d = cq.admit("consult", "c2", project_root=tmp_path / "proj", budget_path=budget(tmp_path), now=later,
                 sessions_dir=sessions)
    assert (d["reason"], d["unavailable_source"]) == ("quota_exhausted", "meter")
    # the user reset the plan: a newer reading below 99% on both windows clears it at once
    _probe_rollout(sessions, later - 10, 4.0)
    d = cq.admit("consult", "c3", project_root=tmp_path / "proj", budget_path=budget(tmp_path), now=later,
                 sessions_dir=sessions)
    assert (d["admitted"], d["reason"]) == (True, "within_budget")


def test_322_fr1_the_record_expires_at_its_reset_time(sessions, tmp_path):
    path = tmp_path / "state" / "codex-exhausted.json"
    assert cq.record_exhausted(NOW + 600, source="probe", now=NOW, path=path)["written"] is True
    empty = tmp_path / "no-sessions"
    assert cq.quota_wait_now(sessions_dir=empty, now=NOW + 599, exhausted_path=path)["resets_in_s"] == 1
    assert cq.quota_wait_now(sessions_dir=empty, now=NOW + 600, exhausted_path=path) is None


def test_322_fr1_an_unknown_reset_holds_and_never_shortens_or_extends_a_known_one(tmp_path):
    path = tmp_path / "codex-exhausted.json"
    r = cq.record_exhausted(None, source="classify", now=NOW, path=path)
    assert (r["exhausted_until"], r["reset_known"]) == (int(NOW + cq.EXHAUSTED_UNKNOWN_HOLD_S), False)
    r = cq.record_exhausted(NOW + 5000, source="probe", binding_window="primary", now=NOW + 10, path=path)
    assert (r["exhausted_until"], r["reset_known"]) == (int(NOW + 5000), True)
    r = cq.record_exhausted(None, source="classify", now=NOW + 20, path=path)
    assert (r["exhausted_until"], r["reset_known"], r["binding_window"]) == (int(NOW + 5000), True, "primary")
    assert cq.record_exhausted(NOW - 1, source="probe", now=NOW, path=path)["written"] is False
    with pytest.raises(ValueError):
        cq.record_exhausted(None, source="guess", now=NOW, path=path)


def test_322_fr1_a_broken_record_store_never_breaks_admit(sessions, tmp_path):
    fresh_rollout(sessions, 100.0, 3.0)
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x", encoding="utf-8")
    d = _admit("consult", "c1", sessions, tmp_path, exhausted_path=blocker / "codex-exhausted.json")
    assert (d["reason"], d["exhausted_recorded"]) == ("quota_exhausted", False)


@pytest.fixture()
def london(monkeypatch):
    import time as _time
    monkeypatch.setenv("TZ", "Europe/London")
    _time.tzset()
    yield
    monkeypatch.undo()
    _time.tzset()


@pytest.mark.parametrize("text,expect", [
    # 2026-09-27 23:45 UTC == 00:45 BST; "1:50 AM" is 00:50 UTC on the 28th
    ("You've hit your usage limit. ... or try again at 1:50 AM.", "2026-09-28T00:50:00+00:00"),
    # RE-POINTED by #322 fix round 2 (N2): 00:10 BST passed 35 min ago -- the text was read LATE, the reset has
    # just happened; fix round 1 made it a +24 h hold. None -> the 30-minute hold and the probe decide.
    ("try again at 12:10 AM.", None),
    ("try again at 3:05 pm", "2026-09-28T14:05:00+00:00"),
    ("try again at Oct 3rd, 2026 2:15 PM.", "2026-10-03T13:15:00+00:00"),
    ("try again at 13:30", "2026-09-28T12:30:00+00:00"),
    ("try again later", None),
    ("try again at 25:00", None),
])
def test_322_fr1_the_reset_time_is_parsed_from_the_usage_limit_text(london, text, expect):
    now = datetime(2026, 9, 27, 23, 45, tzinfo=timezone.utc).timestamp()
    got = cq.retry_at_from_text(text, now)
    if expect is None:
        assert got is None
    else:
        want = datetime.fromisoformat(expect).timestamp()
        assert got == int(want)


def test_322_fr1_an_exhausted_real_probe_persists_the_reset_its_text_names(monkeypatch, sessions, tmp_path, london):
    """run_probe: the probe's rollout carries no usable reading, so codex's own text is the reset time."""
    import time as _time
    now = datetime(2026, 9, 27, 23, 45, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(_time, "time", lambda: now)
    _fake_watch(monkeypatch, exit_code=1, output="",
                stderr="ERROR: You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), "
                       "visit https://chatgpt.com/codex/settings/usage to purchase more credits or try again at "
                       "1:50 AM.\n")
    path = tmp_path / "codex-exhausted.json"
    assert cq.run_probe(model="gpt-5.6-terra", sessions_dir=sessions, exhausted_path=path) == ("exhausted", 1)
    record = cq.read_exhausted(path=path)
    assert (record["exhausted_until"], record["source"], record["reset_known"]) == (
        int(datetime(2026, 9, 28, 0, 50, tzinfo=timezone.utc).timestamp()), "probe", True)


def test_322_fr1_cli_classify_persists_the_text_reset(fixture_home, tmp_path):
    # Fix round 2 (N2): the CLI reads the real clock, and a time that passed under 12 h ago is now None, so the
    # text names a time two hours AHEAD of now in London (it was a fixed "1:50 AM": wall-clock dependent).
    import zoneinfo
    ahead = datetime.now(zoneinfo.ZoneInfo("Europe/London")) + timedelta(hours=2)
    err = tmp_path / "stderr.txt"
    err.write_text(f"ERROR: You've hit your usage limit. ... or try again at {ahead:%H:%M}.\n", encoding="utf-8")
    r = _cli(["classify", "--exit-code", "1", "--attempt", "1", "--stderr-file", str(err)], fixture_home, tmp_path,
             {"TZ": "Europe/London"})
    assert r.stdout == "substitute quota_exhausted\n"
    record = cq.read_exhausted(path=fixture_home / ".claude" / "state" / "codex-exhausted.json")
    assert (record["source"], record["reset_known"]) == ("classify", True)


def test_322_fr1_await_reset_records_an_exhausted_probe_and_clears_on_headroom(sessions, tmp_path, fixture_home):
    fresh_rollout(sessions, 99.5, 3.0)
    record = fixture_home / ".claude" / "state" / "codex-exhausted.json"
    clock = _FakeTime()
    seen = []
    probe = _scripted_probe(clock, ["exhausted", "available"],
                            on_available=lambda: (seen.append(record.exists()),
                                                  _probe_rollout(sessions, clock(), 3.0)))
    code, out = _await(tmp_path, sessions, clock, probe, poll=120)
    assert (code, out["source"]) == (0, "user_reset")
    assert seen == [True] and not record.exists()


# ---- F2: budget and class are decided before quota (the stand-in's order.py) ---------------------------- #
def test_322_fr1_a_spent_budget_is_refused_as_budget_spent_with_no_reset_advice(sessions, tmp_path):
    low = tmp_path / "low"
    fresh_rollout(low, 50.0, 3.0)
    for _ in range(2):
        assert _admit("challenger", "k", low, tmp_path, model_class="std")["admitted"] is True
    fresh_rollout(sessions, 100.0, 3.0)
    d = _admit("challenger", "k", sessions, tmp_path, model_class="std")
    assert (d["admitted"], d["reason"], d["unavailable"]) == (False, "budget_spent", "quota_exhausted")
    assert not {"wait_advice", "resets_at", "resets_in_s", "binding_window"} & set(d)


def test_322_fr1_an_unbudgeted_class_is_refused_as_such_with_no_reset_advice(sessions, tmp_path):
    fresh_rollout(sessions, 100.0, 3.0)
    d = _admit("advisory_review", "k2", sessions, tmp_path, model_class="std")
    assert (d["admitted"], d["reason"]) == (False, "class_not_budgeted")
    assert "wait_advice" not in d


def test_322_fr1_control_a_seat_the_budget_would_admit_is_refused_for_quota_with_advice(sessions, tmp_path):
    fresh_rollout(sessions, 100.0, 3.0)
    d = _admit("challenger", "k3", sessions, tmp_path, model_class="std")
    assert (d["reason"], d["budget_used"]) == ("quota_exhausted", 0)
    assert d["wait_advice"] in ("wait", "notify") and d["resets_at"] is not None


# ---- minor 1: an answering probe counts only when the meter clears ------------------------------------- #
def test_322_fr1_an_answer_whose_newer_reading_is_still_exhausted_keeps_polling(sessions, tmp_path):
    fresh_rollout(sessions, 99.5, 3.0)
    clock = _FakeTime()
    readings = iter([99.6, 99.2, 12.0])
    probe = _scripted_probe(clock, ["available"],
                            on_available=lambda: _probe_rollout(sessions, clock(), next(readings)))
    code, out = _await(tmp_path, sessions, clock, probe, poll=120)
    assert (code, out["probes"], out["source"]) == (0, 3, "user_reset")
    assert clock.sleeps == [120.0, 120.0]


def test_322_fr1_an_answer_with_no_newer_reading_is_a_plain_reset_not_user_reset(sessions, tmp_path):
    fresh_rollout(sessions, 99.5, 3.0)                         # resets ~2 h away; the probe writes no reading
    clock = _FakeTime()
    code, out = _await(tmp_path, sessions, clock, _scripted_probe(clock, ["exhausted", "available"]), poll=120)
    assert (code, out["source"]) == (0, "reset")


# ---- minor 2: non-quota probe errors -------------------------------------------------------------------- #
def test_322_fr1_three_consecutive_probe_errors_exit_6_probe_error(sessions, tmp_path):
    fresh_rollout(sessions, 99.5, 3.0)
    clock = _FakeTime()
    code, out = _await(tmp_path, sessions, clock, _scripted_probe(clock, ["error"]), poll=120)
    assert (code, out["source"], out["probes"]) == (cq.EXIT_AWAIT_PROBE_ERROR, "probe_error", 3) and code == 6
    assert clock.sleeps == [120.0, 120.0]


def test_322_fr1_an_exhausted_result_resets_the_error_count(sessions, tmp_path):
    """CONTROL: errors broken by an exhausted verdict are not three in a row; the wait times out instead."""
    fresh_rollout(sessions, 99.5, 3.0)
    clock = _FakeTime()
    probe = _scripted_probe(clock, ["error", "error", "exhausted", "error", "error", "exhausted"])
    code, out = _await(tmp_path, sessions, clock, probe, poll=120, max_wait=600)
    assert (code, out["source"]) == (4, "timeout")


def test_322_fr1_quota_probe_error_is_a_substitution_reason():
    assert cq.REASON_QUOTA_PROBE_ERROR == "quota_probe_error" in cq.SUBSTITUTION_REASONS


# ---- minor 3: the probe's cap never overruns --max-wait by more than the floor --------------------------- #
def test_322_fr1_the_real_probe_is_capped_at_the_time_left(monkeypatch, sessions, tmp_path):
    fresh_rollout(sessions, 99.5, 3.0)
    clock = _FakeTime()
    caps = []

    def fake_run_probe(**kw):
        caps.append(kw["hard_cap_s"])
        return "exhausted", 1

    monkeypatch.setattr(cq, "run_probe", fake_run_probe)
    code, _out = cq.await_reset(project_root=tmp_path / "proj", sessions_dir=sessions, budget_path=budget(tmp_path),
                                clock=clock, sleep=clock.sleep, max_wait=500, poll=120)
    assert code == 4
    # time left at each probe: 500, 380, 260, 140, 20. RE-POINTED by #322 fix round 2 (m3): the cap is the time
    # left with no 30 s floor (it was [300, 300, 260, 140, 30, 30]: the last two overran --max-wait), and at
    # the deadline (0 s left, < PROBE_MIN_LEFT_S) no probe runs at all.
    assert caps == [300, 300, 260, 140, 20]


# ---- minor 4: one await-reset per project, one notification per wave ------------------------------------ #
@pytest.mark.skipif(sys.platform == "win32", reason="same-process flock contention is POSIX")
def test_322_fr1_a_second_await_reset_joins_the_running_one(sessions, tmp_path, fixture_home):
    from portable_lock import file_lock  # type: ignore
    fresh_rollout(sessions, 99.5, 3.0)
    lock_dir = fixture_home / ".claude" / "state"   # fix round 2 (item 10): account-wide, not per project
    lock_dir.mkdir(parents=True)
    clock = _FakeTime()
    holder = file_lock(lock_dir / cq.AWAIT_LOCK_FILENAME)
    holder.__enter__()
    released = []

    def sleep(seconds):
        clock.sleep(seconds)
        if not released:   # the first caller finishes while the joiner waits
            (lock_dir / cq.AWAIT_RESULT_FILENAME).write_text(json.dumps(
                {"finished_at": clock(), "code": 0, "result": {"available": True, "waited_s": 400, "probes": 4,
                                                                "source": "user_reset"}}), encoding="utf-8")
            holder.__exit__(None, None, None)
            released.append(True)

    probe = _scripted_probe(clock, ["exhausted"])
    code, out = cq.await_reset(project_root=tmp_path / "proj", sessions_dir=sessions, budget_path=budget(tmp_path),
                               clock=clock, sleep=sleep, probe=probe)
    assert (code, out["available"], out["source"], out["joined"], out["probes"]) == (0, True, "user_reset", True, 0)
    assert probe.calls == []                                    # the joiner never probed
    assert clock.sleeps == [float(cq.AWAIT_JOIN_POLL_S)]


@pytest.mark.skipif(sys.platform == "win32", reason="same-process flock contention is POSIX")
def test_322_fr1_a_joiner_does_not_take_an_old_result_it_did_not_wait_for(sessions, tmp_path, fixture_home):
    """CONTROL: a result finished BEFORE this caller started is the previous wave's; it waits itself."""
    fresh_rollout(sessions, 99.5, 3.0)
    lock_dir = fixture_home / ".claude" / "state"   # fix round 2 (item 10): account-wide, not per project
    lock_dir.mkdir(parents=True)
    (lock_dir / cq.AWAIT_RESULT_FILENAME).write_text(json.dumps(
        {"finished_at": NOW - 5, "code": 0, "result": {"available": True, "source": "reset"}}), encoding="utf-8")
    clock = _FakeTime()
    probe = _scripted_probe(clock, ["exhausted"])
    code, out = _await(tmp_path, sessions, clock, probe, max_wait=240, poll=120)
    # 2 probes (0, 120): fix round 2 (m3) skips the one that landed on the deadline with 0 s left.
    assert (code, out["source"], "joined" in out, len(probe.calls)) == (4, "timeout", False, 2)
    written = json.loads((lock_dir / cq.AWAIT_RESULT_FILENAME).read_text(encoding="utf-8"))
    assert (written["code"], written["result"]["source"]) == (4, "timeout")


def test_322_fr1_one_notification_per_refusal_wave(sessions, tmp_path):
    bp = budget(tmp_path)
    assert cq.notify_claim(budget_path=bp, now=NOW) is True
    assert cq.notify_claim(budget_path=bp, now=NOW + 5) is False          # a parallel seat of the same wave
    assert cq.notify_claim(budget_path=bp, now=NOW + cq.AWAIT_MAX_WAIT_S) is True   # the wave aged out
    # codex answered again (await-reset exit 0) -> the wave ends, the next refusal notifies
    assert cq.notify_claim(budget_path=bp, now=NOW + cq.AWAIT_MAX_WAIT_S + 1) is False
    fresh_rollout(sessions, 99.5, 3.0)
    clock = _FakeTime(start=NOW + cq.AWAIT_MAX_WAIT_S + 2)
    assert _await(tmp_path, sessions, clock, _scripted_probe(clock, ["available"]))[0] == 0
    assert cq.notify_claim(budget_path=bp, now=NOW + cq.AWAIT_MAX_WAIT_S + 3) is True


def test_322_fr1_cli_notify_claim_prints_notify_then_skip(fixture_home, project):
    first = _cli(["notify-claim", "--project-root", str(project)], fixture_home, project)
    second = _cli(["notify-claim", "--project-root", str(project)], fixture_home, project)
    assert (first.returncode, first.stdout, second.returncode, second.stdout) == (0, "notify\n", 10, "skip\n")


# ---- nit: --cycle-id puts the seat's key on the probe rows ---------------------------------------------- #
def test_322_fr1_cli_await_reset_cycle_id_reaches_the_probe_rows(monkeypatch, capsys, fixture_home, project):
    monkeypatch.setattr(cq, "run_probe", lambda **kw: ("available", 0))
    assert cq.main(["await-reset", "--cycle-id", "tournament-abc", "--project-root", str(project)]) == 0
    rows = read_rows(cq.budget_path_for(project))
    assert [(r["kind"], r["key"]) for r in rows] == [("probe", "tournament-abc")]
    assert cq.main(["await-reset", "--cycle-id", "bad key!", "--project-root", str(project)]) == 3


# =========================================================================== #
# #322 fix round 2 -- items 1, 2, 4-10 (item 3 is in test_astra_reserve.py, item 11 a doc test there).
# Every test injects the clock, the sleep and the probe; state files live under the fixture HOME.
# =========================================================================== #
def _state(home):
    return home / ".claude" / "state"


def _record_path(home):
    return _state(home) / "codex-exhausted.json"


def _admit_at(use, key, sessions, tmp_path, now, **kw):
    return cq.admit(use, key, project_root=tmp_path / "proj", budget_path=budget(tmp_path), now=now,
                    sessions_dir=sessions, **kw)


# ---- item 1: a superseded record is retired, so it cannot bind again -------------------------------------- #
def test_322_fr2_a_superseded_record_is_retired_and_does_not_bind_again(sessions, tmp_path, fixture_home):
    fresh_rollout(sessions, 100.0, 3.0, p_resets=int(NOW + 2 * HOUR))
    assert _admit("consult", "c1", sessions, tmp_path)["reason"] == "quota_exhausted"
    assert _record_path(fixture_home).exists()
    later = NOW + 40 * 60
    headroom = _probe_rollout(sessions, later - 10, 4.0)
    assert _admit_at("consult", "c2", sessions, tmp_path, later)["admitted"] is True
    assert not _record_path(fixture_home).exists()                   # retired, not merely ignored
    headroom.unlink()                                                # the headroom reading leaves the walk
    d = _admit_at("consult", "c3", sessions, tmp_path, later + 60)
    assert (d["admitted"], d["reason"]) == (True, "within_budget")   # fix round 1: quota_exhausted again


def test_322_fr2_retiring_keeps_a_concurrent_newer_exhaustion_signal(tmp_path):
    path = tmp_path / "codex-exhausted.json"
    cq.record_exhausted(NOW + 3600, source="probe", now=NOW, path=path, evidence_at=NOW - 5)
    assert cq.retire_exhausted(NOW - 10, path=path) is False         # evidence newer than the reading: kept
    assert cq.read_exhausted(path=path) is not None
    assert cq.retire_exhausted(NOW, path=path) is True               # CONTROL: an older signal is retired
    assert cq.read_exhausted(path=path) is None


def test_322_fr2_a_check_only_admit_does_not_retire(sessions, tmp_path, fixture_home):
    """CONTROL: record=False writes nothing -- it reads the superseded record as not binding, and leaves it."""
    fresh_rollout(sessions, 100.0, 3.0, p_resets=int(NOW + 2 * HOUR))
    _admit("consult", "c1", sessions, tmp_path)
    later = NOW + 40 * 60
    _probe_rollout(sessions, later - 10, 4.0)
    assert _admit_at("consult", "c2", sessions, tmp_path, later, record=False)["admitted"] is True
    assert _record_path(fixture_home).exists()


# ---- item 2: headroom needs an explicit reading of the record's binding window ---------------------------- #
@pytest.mark.parametrize("weekly,admitted", [(None, False), (50.0, True)])
def test_322_fr2_missing_weekly_data_never_clears_a_weekly_record(sessions, tmp_path, fixture_home, weekly, admitted):
    cq.record_exhausted(NOW + 3 * 24 * HOUR, source="admit", binding_window="secondary", now=NOW - 120,
                        evidence_at=NOW - 120, path=_record_path(fixture_home))
    fresh_rollout(sessions, 2.0, weekly)                              # observed NOW - 60: newer than the evidence
    d = _admit("consult", "c1", sessions, tmp_path)
    assert d["admitted"] is admitted
    if not admitted:   # weekly None: no evidence about the weekly window (fix round 1 read it as headroom)
        assert (d["reason"], d["unavailable_source"], d["binding_window"]) == (
            "quota_exhausted", "exhausted_record", "secondary")


def test_322_fr2_headroom_is_judged_on_the_binding_window():
    snap = {"observed_at": iso(NOW), "primary_used_percent": 2.0, "secondary_used_percent": None}
    assert cq._reading_headroom_since(snap, NOW - 1, "secondary") is None
    assert cq._reading_headroom_since(snap, NOW - 1, "primary") is True
    assert cq._reading_headroom_since(snap, NOW - 1, None) is None
    snap["secondary_used_percent"] = 99.0
    assert cq._reading_headroom_since(snap, NOW - 1, "primary") is False   # any window at 99% is no headroom


# ---- item 4: the trip-wire honours the exhausted record ---------------------------------------------------- #
@pytest.mark.parametrize("seat_class,action", [("supporting", "skip"), ("discretionary", "substitute")])
def test_322_fr2_tripwire_stops_on_an_active_exhausted_record(sessions, fixture_home, seat_class, action):
    cq.record_exhausted(NOW + 3600, source="probe", now=NOW, path=_record_path(fixture_home))
    t = cq.tripwire(seat_class, sessions_dir=sessions, now=NOW)        # no reading at all: the meter is unknown
    assert (t["action"], t["unavailable"], t["unavailable_source"]) == (action, "quota_exhausted",
                                                                       "exhausted_record")
    _record_path(fixture_home).unlink()                                # CONTROL: no record -> it runs
    assert cq.tripwire(seat_class, sessions_dir=sessions, now=NOW)["action"] == "run"


# ---- item 5 (N4): one full wait per exhausted record ------------------------------------------------------- #
def test_322_fr2_a_record_whose_wait_timed_out_is_not_waited_for_again(sessions, tmp_path, fixture_home):
    fresh_rollout(sessions, 99.5, 3.0, p_resets=int(NOW + 4 * HOUR))   # a far reset: notify
    assert _admit("consult", "c1", sessions, tmp_path)["wait_advice"] == "notify"
    wave = cq.record_wave(cq.read_exhausted(path=_record_path(fixture_home)))
    assert cq.notify_claim(now=NOW) is True                           # the first seat tells the user
    clock = _FakeTime()
    first = _scripted_probe(clock, ["exhausted"])
    code, out = _await(tmp_path, sessions, clock, first, poll=120)
    assert (code, out["source"]) == (4, "timeout") and len(first.calls) > 1
    # the probes re-confirmed the record; its wave is unchanged
    assert cq.record_wave(cq.read_exhausted(path=_record_path(fixture_home))) == wave
    # a later seat (a second later: a result finished AT a caller's start is taken as a joined result)
    clock.t += 1
    second = _scripted_probe(clock, ["exhausted"])
    sleeps_before = list(clock.sleeps)
    code, out = _await(tmp_path, sessions, clock, second, poll=120)
    assert (code, out["source"], out["probes"]) == (4, "timed_out_for_record", 1)
    assert clock.sleeps == sleeps_before
    # ...and it notifies nobody: the wave's claim holds past 30 minutes
    assert cq.notify_claim(now=clock() - 1) is False


def test_322_fr2_a_timed_out_record_still_sees_a_reset_by_hand(sessions, tmp_path, fixture_home):
    fresh_rollout(sessions, 99.5, 3.0, p_resets=int(NOW + 4 * HOUR))
    _admit("consult", "c1", sessions, tmp_path)
    clock = _FakeTime()
    assert _await(tmp_path, sessions, clock, _scripted_probe(clock, ["exhausted"]), poll=120)[0] == 4
    clock.t += 1
    probe = _scripted_probe(clock, ["available"], on_available=lambda: _probe_rollout(sessions, clock(), 3.0))
    code, out = _await(tmp_path, sessions, clock, probe, poll=120)
    assert (code, out["source"]) == (0, "user_reset")
    assert not _record_path(fixture_home).exists()


def test_322_fr2_a_new_record_gets_a_new_full_wait(sessions, tmp_path, fixture_home):
    """CONTROL: the marker belongs to the record's wave; a record opened after the last one cleared waits."""
    fresh_rollout(sessions, 99.5, 3.0, p_resets=int(NOW + 4 * HOUR))
    _admit("consult", "c1", sessions, tmp_path)
    clock = _FakeTime()
    assert _await(tmp_path, sessions, clock, _scripted_probe(clock, ["exhausted"]), poll=120, max_wait=300)[0] == 4
    cq.clear_exhausted(path=_record_path(fixture_home))
    cq.record_exhausted(NOW + 5 * HOUR, source="probe", now=clock(), path=_record_path(fixture_home))
    clock.t += 1
    probe = _scripted_probe(clock, ["exhausted"])
    code, out = _await(tmp_path, sessions, clock, probe, poll=120, max_wait=300)
    assert (code, out["source"]) == (4, "timeout") and len(probe.calls) > 1


# ---- item 6 (m3): no probe overruns --max-wait -------------------------------------------------------------- #
def test_322_fr2_a_probe_never_overruns_the_wait(monkeypatch, sessions, tmp_path):
    fresh_rollout(sessions, 99.5, 3.0)
    clock = _FakeTime()
    caps = []

    def fake_run_probe(**kw):
        caps.append(kw["hard_cap_s"])
        clock.t += kw["hard_cap_s"]          # the probe runs to its cap
        return "exhausted", 1

    monkeypatch.setattr(cq, "run_probe", fake_run_probe)
    code, out = cq.await_reset(project_root=tmp_path / "proj", sessions_dir=sessions, budget_path=budget(tmp_path),
                               clock=clock, sleep=clock.sleep, max_wait=301, poll=300)
    # probe at 0 (cap 300) -> at 300 only 1 s is left: fix round 1 probed with a 30 s cap (overran by 29 s)
    assert (code, caps) == (4, [300])
    assert clock() <= NOW + 301


# ---- item 7 (N1): a rate_limit_reached record's evidence is the flag's own time ----------------------------- #
def test_322_fr2_a_reached_flag_records_its_own_evidence_time(sessions, tmp_path, fixture_home):
    reading = write_rollout(sessions, TODAY, "rollout-a-reading.jsonl", [rl_event(NOW - 600, 50.0, 10.0)])
    set_mtime(reading, NOW - 600)
    flag = write_rollout(sessions, TODAY, "rollout-b-flag.jsonl", [premium_null(NOW - 60, reached_type="primary")])
    set_mtime(flag, NOW - 60)
    d = _admit("consult", "c1", sessions, tmp_path)
    assert (d["reason"], d["exhausted_recorded"]) == ("rate_limit_reached", True)
    record = cq.read_exhausted(path=_record_path(fixture_home))
    assert record["evidence_at"] == pytest.approx(NOW - 60, abs=0.01)   # fix round 1: NOW - 600 (the reading)
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert cq.active_exhausted(snap, NOW, path=_record_path(fixture_home)) is not None


# ---- item 8 (N2): late or far parses are rejected ----------------------------------------------------------- #
@pytest.mark.parametrize("text", [
    "try again at Sep 1st, 2026 2:15 PM.",      # a dated form in the past (fix round 1: that past epoch)
    "try again at Sep 1st 2:15 PM.",            # the same without a year (fix round 1: next year, +365 d)
    "try again at Dec 25th, 2026 9:00 AM.",     # more than 7 days ahead
])
def test_322_fr2_a_past_or_far_retry_time_is_none(london, text):
    now = datetime(2026, 9, 27, 23, 45, tzinfo=timezone.utc).timestamp()
    assert cq.retry_at_from_text(text, now) is None


def test_322_fr2_a_near_dated_retry_time_still_parses(london):
    """CONTROL: a dated form inside the 7-day bound parses."""
    now = datetime(2026, 9, 27, 23, 45, tzinfo=timezone.utc).timestamp()
    got = cq.retry_at_from_text("try again at Oct 3rd, 2026 2:15 PM.", now)
    assert got == int(datetime(2026, 10, 3, 13, 15, tzinfo=timezone.utc).timestamp())


# ---- item 9 (N3): our own probe rollouts no longer blind the meter; an exhausted walk is uncertain ----------- #
def _probe_rollout_live(sessions_root, name, observed, *, prompt=None):
    """An exhausted await-reset probe in the live shape: the probe prompt as the USER message, then the
    `premium, primary: null` rate_limits object -- no usable reading."""
    user = {"timestamp": iso(observed - 1), "type": "response_item",
            "payload": {"type": "message", "role": "user",
                        "content": [{"type": "input_text", "text": prompt or cq.PROBE_PROMPT}]}}
    return set_mtime(write_rollout(sessions_root, TODAY, name, [user, premium_null(observed)]), observed)


def test_322_fr2_codexs_37_probe_scenario_does_not_admit(sessions, tmp_path, fixture_home):
    """codex's round-1 reproduction: 37 reading-less rollouts newer than a 100% reading, and an EXPIRED
    unknown-reset record. Fix round 1: `unknown/no_rate_limits` and admit True/within_budget."""
    real = write_rollout(sessions, TODAY, "rollout-a-real.jsonl",
                         [rl_event(NOW - 900, 100.0, 50.0, p_resets=int(NOW + 2400))])
    set_mtime(real, NOW - 900)
    for i in range(37):
        _probe_rollout_live(sessions, f"rollout-p{i:02d}.jsonl", NOW - 800 + i * 20)
    cq.record_exhausted(None, source="probe", now=NOW - 3 * HOUR, path=_record_path(fixture_home))
    assert cq.active_exhausted(cq.snapshot(sessions_dir=sessions, now=NOW), NOW,
                               path=_record_path(fixture_home)) is None      # the record has expired
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert (snap["state"], snap["primary_used_percent"]) == ("fresh", 100.0)
    for record in (False, True):
        d = _admit("consult", "c1", sessions, tmp_path, record=record)
        assert (d["admitted"], d["reason"]) == (False, "quota_exhausted")


def test_322_fr2_reading_less_non_probe_rollouts_past_the_bound_are_uncertain(sessions):
    real = write_rollout(sessions, TODAY, "rollout-a-real.jsonl", [rl_event(NOW - 900, 100.0, 50.0)])
    set_mtime(real, NOW - 900)
    for i in range(37):
        set_mtime(write_rollout(sessions, TODAY, f"rollout-k{i:02d}.jsonl", [premium_null(NOW - 800 + i * 20)]),
                  NOW - 800 + i * 20)
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert (snap["state"], snap["reason"]) == ("uncertain", "newer_candidate_unread")


def test_322_fr2_a_rollout_that_only_quotes_the_probe_prompt_is_not_a_probe(sessions):
    quoted = cq.PROBE_PROMPT + " (quoted in a review)"
    path = _probe_rollout_live(sessions, "rollout-q.jsonl", NOW - 60, prompt=quoted)
    assert cq._is_own_probe(path) is False
    assert cq._is_own_probe(_probe_rollout_live(sessions, "rollout-r.jsonl", NOW - 50)) is True


# ---- item 10: the notification claim and the await lock are account-wide ------------------------------------ #
def test_322_fr2_one_notification_per_record_across_projects(sessions, tmp_path, fixture_home):
    a, b = tmp_path / "proj-a", tmp_path / "proj-b"
    cq.record_exhausted(NOW + 4 * HOUR, source="probe", now=NOW, path=_record_path(fixture_home))
    assert cq.notify_claim(project_root=a, now=NOW) is True
    assert cq.notify_claim(project_root=b, now=NOW + 5) is False          # fix round 1: True (per project)
    assert cq.notify_claim(project_root=a, now=NOW + 2 * HOUR) is False   # the record's whole life, not 30 min
    assert (_state(fixture_home) / cq.NOTIFY_WAVE_FILENAME).exists()
    # the record clears -> the claim goes with it; a new record is a new wave
    assert cq.retire_exhausted(NOW + 2 * HOUR, path=_record_path(fixture_home)) is True
    assert not (_state(fixture_home) / cq.NOTIFY_WAVE_FILENAME).exists()
    cq.record_exhausted(NOW + 5 * HOUR, source="probe", now=NOW + 2 * HOUR + 1, path=_record_path(fixture_home))
    assert cq.notify_claim(project_root=b, now=NOW + 2 * HOUR + 2) is True


def test_322_fr2_a_re_confirmed_record_keeps_its_wave(tmp_path):
    path = tmp_path / "codex-exhausted.json"
    first = cq.record_exhausted(None, source="classify", now=NOW, path=path)
    again = cq.record_exhausted(NOW + 7200, source="probe", now=NOW + 60, path=path)
    assert cq.record_wave(cq.read_exhausted(path=path)) == [float(first["exhausted_until"]), float(NOW)]
    assert again["evidence_at"] == NOW + 60


@pytest.mark.skipif(sys.platform == "win32", reason="same-process flock contention is POSIX")
def test_322_fr2_an_await_reset_in_another_project_joins(sessions, tmp_path, fixture_home):
    from portable_lock import file_lock  # type: ignore
    fresh_rollout(sessions, 99.5, 3.0)
    state = _state(fixture_home)
    state.mkdir(parents=True, exist_ok=True)
    holder = file_lock(state / cq.AWAIT_LOCK_FILENAME)   # project A's wait holds the account's lock
    holder.__enter__()
    clock = _FakeTime()

    def sleep(seconds):
        clock.sleep(seconds)
        (state / cq.AWAIT_RESULT_FILENAME).write_text(json.dumps(
            {"finished_at": clock(), "code": 0, "result": {"available": True, "source": "reset"}}), encoding="utf-8")
        holder.__exit__(None, None, None)

    probe = _scripted_probe(clock, ["exhausted"])
    code, out = cq.await_reset(project_root=tmp_path / "proj-b", sessions_dir=sessions,
                               budget_path=tmp_path / "other" / "astra-budget.jsonl", clock=clock, sleep=sleep,
                               probe=probe)
    assert (code, out["joined"], probe.calls) == (0, True, [])


def test_322_fr2_the_seat_steps_say_one_wait_per_record_and_account_wide():
    """Items 5 and 10 in the codex-orchestration CODEX_QUOTA_WAIT steps: the claim and the wait are
    account-wide, a timed-out record's later seats go straight to the stand-in without notifying, and
    `timed_out_for_record` maps to the timeout stand-in reason."""
    skill, whole = _codex_orchestration_docs()
    assert "One await-reset per account" in skill and "One await-reset per project" not in whole
    assert "One full wait per exhausted record" in skill
    assert "`timed_out_for_record` (this record's wait already timed out) → `quota_exhausted_timeout`" in skill
    assert "sends no notification" in skill and "goes straight to step 4" in skill
    assert "keyed on the active exhausted record" in skill


# =========================================================================== #
# #322 user-scoped round -- items 1-4 and 6-8 (items 5 and 9 are in test_astra_reserve.py). Each test failed
# before its fix. Clock, sleep and probe are injected; state lives under the fixture HOME.
# =========================================================================== #
def _probe_rollout_mixed(sessions_root, name, observed, contents, reached_type=None):
    """A reading-less rollout whose USER message is `contents` (a list of input_text strings)."""
    user = {"timestamp": iso(observed - 1), "type": "response_item",
            "payload": {"type": "message", "role": "user",
                        "content": [{"type": "input_text", "text": t} for t in contents]}}
    return set_mtime(write_rollout(sessions_root, TODAY, name, [user, premium_null(observed, reached_type)]),
                     observed)


# ---- item 1: a refused retirement re-reads the record instead of admitting -------------------------------- #
def test_322_usr_a_refused_retirement_judges_the_current_record(monkeypatch, sessions, tmp_path, fixture_home):
    rp = _record_path(fixture_home)
    cq.record_exhausted(NOW + 2 * HOUR, source="probe", now=NOW - 100, path=rp, evidence_at=NOW - 100)
    fresh_rollout(sessions, 10.0, 3.0, age=10)          # headroom observed at NOW-10: supersedes that record
    real_retire = cq.retire_exhausted

    def racing_retire(observed_at, *, path=None):
        # a NEWER exhaustion signal lands between active_exhausted's read and the retirement
        cq.record_exhausted(NOW + 3 * HOUR, source="probe", now=NOW - 5, path=rp, evidence_at=NOW - 5)
        return real_retire(observed_at, path=path)

    monkeypatch.setattr(cq, "retire_exhausted", racing_retire)
    snap, limits = cq._scan(sessions, NOW)
    assert cq._quota_state(snap, limits, NOW, exhausted_path=rp)[:2] == ("quota_exhausted", "exhausted_record")
    assert rp.exists() and cq.read_exhausted(path=rp)["evidence_at"] == NOW - 5


def test_322_final_a_retirement_refused_every_time_fails_closed(monkeypatch, sessions, tmp_path, fixture_home):
    """#322 final verification (codex item 1): when every re-read's retirement is refused because a newer
    signal keeps landing, the record on disk still binds -- the seat is never admitted across it."""
    rp = _record_path(fixture_home)
    cq.record_exhausted(NOW + 2 * HOUR, source="probe", now=NOW - 100, path=rp, evidence_at=NOW - 100)
    fresh_rollout(sessions, 10.0, 3.0, age=10)
    monkeypatch.setattr(cq, "retire_exhausted", lambda observed_at, *, path=None: False)
    snap, limits = cq._scan(sessions, NOW)
    assert cq._quota_state(snap, limits, NOW, exhausted_path=rp)[:2] == ("quota_exhausted", "exhausted_record")


def test_322_final_an_arbitrary_angle_bracket_message_is_not_a_probe(sessions):
    """#322 final verification (codex item 2): only codex's own named context blocks sit beside a probe."""
    path = _probe_rollout_mixed(sessions, "rollout-r.jsonl", NOW - 30, [cq.PROBE_PROMPT])
    extra = {"timestamp": iso(NOW - 29), "type": "response_item",
             "payload": {"type": "message", "role": "user",
                         "content": [{"type": "input_text", "text": "<request>do more</request>"}]}}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(extra) + "\n")
    set_mtime(path, NOW - 30)
    assert cq._is_own_probe(path) is False
    ctx = _probe_rollout_mixed(sessions, "rollout-c.jsonl", NOW - 40, ["<environment_context>\n <cwd>/x</cwd>"])
    with open(ctx, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"timestamp": iso(NOW - 39), "type": "response_item",
                             "payload": {"type": "message", "role": "user",
                                         "content": [{"type": "input_text", "text": cq.PROBE_PROMPT}]}}) + "\n")
    set_mtime(ctx, NOW - 40)
    assert cq._is_own_probe(ctx) is True                                   # CONTROL: the injected context is


def test_322_usr_a_superseded_record_is_still_retired(sessions, tmp_path, fixture_home):
    """CONTROL: with no concurrent signal the superseded record is retired and the seat goes through."""
    rp = _record_path(fixture_home)
    cq.record_exhausted(NOW + 2 * HOUR, source="probe", now=NOW - 100, path=rp, evidence_at=NOW - 100)
    fresh_rollout(sessions, 10.0, 3.0, age=10)
    snap, limits = cq._scan(sessions, NOW)
    assert cq._quota_state(snap, limits, NOW, exhausted_path=rp) == (None, None, None)
    assert not rp.exists()


# ---- item 2: only a WHOLE user message equal to the probe request is a probe; a probe keeps its flags ------- #
@pytest.mark.parametrize("contents", [
    [cq.PROBE_PROMPT, "Also summarise the design doc."],       # the exact prompt plus another part
    ["Also summarise the design doc.", cq.PROBE_PROMPT],
])
def test_322_usr_a_mixed_user_message_is_not_a_probe(sessions, contents):
    path = _probe_rollout_mixed(sessions, "rollout-m.jsonl", NOW - 30, contents)
    assert cq._is_own_probe(path) is False


def test_322_usr_a_mixed_user_message_event_is_not_a_probe(sessions):
    event = {"timestamp": iso(NOW - 31), "type": "event_msg",
             "payload": {"type": "user_message", "message": cq.PROBE_PROMPT + "\nAlso run the tests."}}
    path = set_mtime(write_rollout(sessions, TODAY, "rollout-e.jsonl", [event, premium_null(NOW - 30)]), NOW - 30)
    assert cq._is_own_probe(path) is False
    exact = {"timestamp": iso(NOW - 31), "type": "event_msg",
             "payload": {"type": "user_message", "message": cq.PROBE_PROMPT}}
    path = set_mtime(write_rollout(sessions, TODAY, "rollout-f.jsonl", [exact, premium_null(NOW - 30)]), NOW - 30)
    assert cq._is_own_probe(path) is True                                  # CONTROL: the exact request is


def test_322_usr_a_mixed_message_keeps_its_rate_limit_reached_flag(sessions):
    fresh_rollout(sessions, 40.0, 10.0, age=600)
    _probe_rollout_mixed(sessions, "rollout-m.jsonl", NOW - 30, [cq.PROBE_PROMPT, "Also do X."],
                         reached_type="primary")
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "rate_limit_reached"


def test_322_usr_a_skipped_probe_keeps_its_rate_limit_reached_flag(sessions):
    """Opus N3: a probe rollout with no reading is skipped, but its rate_limit_reached flag is evidence."""
    fresh_rollout(sessions, 40.0, 10.0, age=600)
    _probe_rollout_mixed(sessions, "rollout-p.jsonl", NOW - 30, [cq.PROBE_PROMPT], reached_type="primary")
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "rate_limit_reached"


# ---- item 3: probes never spend read slots; the probe bound keeps a quota-blocking signal ------------------- #
@pytest.mark.parametrize("n_probes", [100, 300])
def test_322_usr_many_probes_never_hide_the_exhausted_reading(sessions, tmp_path, fixture_home, n_probes):
    real = write_rollout(sessions, TODAY, "rollout-a-real.jsonl",
                         [rl_event(NOW - 1500, 100.0, 50.0, p_resets=int(NOW + 2400))])
    set_mtime(real, NOW - 1500)
    step = 1400.0 / n_probes
    for i in range(n_probes):
        _probe_rollout_live(sessions, f"rollout-p{i:03d}.jsonl", NOW - 1450 + i * step)
    cq.record_exhausted(None, source="probe", now=NOW - 3 * HOUR, path=_record_path(fixture_home))  # expired
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert (snap["state"], snap["primary_used_percent"]) == ("fresh", 100.0)
    for record in (False, True):
        d = _admit("consult", "c1", sessions, tmp_path, record=record)
        assert (d["admitted"], d["reason"]) == (False, "quota_exhausted")


def test_322_usr_the_probe_bound_keeps_the_seat_blocked(monkeypatch, sessions, tmp_path, fixture_home):
    """More probes than the walk will check: the newest evidence is exhausted probes, so it stays exhausted."""
    monkeypatch.setattr(cq, "ROLLOUT_PROBE_READ_LIMIT", 20)       # the bound, scaled down for the test
    real = write_rollout(sessions, TODAY, "rollout-a-real.jsonl",
                         [rl_event(NOW - 1500, 100.0, 50.0, p_resets=int(NOW + 2400))])
    set_mtime(real, NOW - 1500)
    for i in range(30):
        _probe_rollout_live(sessions, f"rollout-p{i:03d}.jsonl", NOW - 1400 + i * 40)
    cq.record_exhausted(None, source="probe", now=NOW - 3 * HOUR, path=_record_path(fixture_home))  # expired
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert (snap["state"], snap["reason"]) == ("uncertain", cq.REASON_PROBE_BOUND_EXHAUSTED)
    assert cq.unavailable(sessions_dir=sessions, now=NOW) == "quota_exhausted"
    d = _admit("consult", "c1", sessions, tmp_path)
    assert (d["admitted"], d["reason"]) == (False, "quota_exhausted")


def test_322_usr_the_default_probe_bound_is_512():
    assert cq.ROLLOUT_PROBE_READ_LIMIT == 512


def test_322_usr_killed_probes_at_the_bound_stay_uncertain(monkeypatch, sessions):
    """CONTROL: probes with no rate_limits object at all (killed) are no exhaustion evidence."""
    monkeypatch.setattr(cq, "ROLLOUT_PROBE_READ_LIMIT", 5)
    for i in range(8):
        user = {"timestamp": iso(NOW - 300 + i), "type": "response_item",
                "payload": {"type": "message", "role": "user",
                            "content": [{"type": "input_text", "text": cq.PROBE_PROMPT}]}}
        set_mtime(write_rollout(sessions, TODAY, f"rollout-k{i}.jsonl", [user]), NOW - 300 + i)
    snap = cq.snapshot(sessions_dir=sessions, now=NOW)
    assert (snap["state"], snap["reason"]) == ("uncertain", "newer_candidate_unread")
    assert cq.unavailable(sessions_dir=sessions, now=NOW) is None


# ---- item 4: the timeout marks the wave that was WAITED ON, only while it is still active ------------------- #
def test_322_usr_a_timeout_never_marks_a_new_records_wave(sessions, tmp_path, fixture_home):
    rp = _record_path(fixture_home)
    cq.record_exhausted(NOW + 4 * HOUR, source="admit", now=NOW, path=rp, evidence_at=NOW)
    clock = _FakeTime()
    swapped = []

    def probe():
        if clock() >= NOW + cq.AWAIT_MAX_WAIT_S - 200 and not swapped:
            # the record is replaced during the wait: a new exhaustion, a new wave
            cq.clear_exhausted(path=rp)
            cq.record_exhausted(NOW + 6 * HOUR, source="probe", now=clock(), path=rp, evidence_at=clock())
            swapped.append(cq.record_wave(cq.read_exhausted(path=rp)))
        return "exhausted", 1

    code, out = _await(tmp_path, sessions, clock, probe, poll=120)
    assert (code, out["source"]) == (4, "timeout") and swapped
    assert cq.record_wave(cq.read_exhausted(path=rp)) == swapped[0]
    # the wave waited on is gone, and the new one was never waited for: nothing is marked
    assert not (_state(fixture_home) / cq.AWAIT_TIMEOUT_FILENAME).exists()


# ---- item 7: a re-exhaustion naming a different reset window opens a new wave ------------------------------ #
def test_322_usr_a_re_exhaustion_after_an_unseen_reset_is_a_new_wave(sessions, tmp_path, fixture_home):
    rp = _record_path(fixture_home)
    cq.record_exhausted(NOW + 4 * HOUR, source="admit", now=NOW, path=rp, evidence_at=NOW)
    old = cq.record_wave(cq.read_exhausted(path=rp))
    assert cq.notify_claim(now=NOW) is True
    clock = _FakeTime()
    assert _await(tmp_path, sessions, clock, _scripted_probe(clock, ["exhausted"]), poll=120)[1]["source"] \
        == "timeout"
    assert cq._timed_out_wave(_state(fixture_home)) == old
    # the user reset codex unseen, then used it to 100% again: the newest reading names a LATER reset
    t = NOW + 2 * HOUR
    write_rollout(sessions, TODAY, "rollout-z-headroom.jsonl", [rl_event(t - 1200, 5.0, 5.0)])
    set_mtime(sessions / TODAY / "rollout-z-headroom.jsonl", t - 1200)
    write_rollout(sessions, TODAY, "rollout-zz-full.jsonl", [rl_event(t - 60, 100.0, 5.0, p_resets=int(t + 3 * HOUR))])
    set_mtime(sessions / TODAY / "rollout-zz-full.jsonl", t - 60)
    assert _admit_at("consult", "c9", sessions, tmp_path, t)["reason"] == "quota_exhausted"
    new = cq.record_wave(cq.read_exhausted(path=rp))
    assert new != old and new[0] == int(t + 3 * HOUR)
    assert cq.notify_claim(now=t) is True                                   # a new wave notifies again
    clock2 = _FakeTime(t)
    probe = _scripted_probe(clock2, ["exhausted"])
    code, out = _await(tmp_path, sessions, clock2, probe, poll=120)
    assert (code, out["source"]) == (4, "timeout") and len(probe.calls) > 1   # a full wait, not one probe


def test_322_usr_a_re_confirmation_within_the_margin_keeps_the_wave(tmp_path):
    """CONTROL: the same reset (within AWAIT_MARGIN_S) and an unknown reset keep the wave."""
    rp = tmp_path / "state" / "codex-exhausted.json"
    cq.record_exhausted(NOW + 4 * HOUR, source="admit", now=NOW, path=rp, evidence_at=NOW)
    wave = cq.record_wave(cq.read_exhausted(path=rp))
    cq.record_exhausted(NOW + 4 * HOUR + 30, source="probe", now=NOW + 60, path=rp)
    cq.record_exhausted(None, source="probe", now=NOW + 120, path=rp)
    assert cq.record_wave(cq.read_exhausted(path=rp)) == wave


def test_322_usr_a_known_reset_after_an_unknown_hold_keeps_the_wave(tmp_path):
    """CONTROL: a wave opened on the unknown-reset hold is not a reset WINDOW; learning the time keeps it."""
    rp = tmp_path / "state" / "codex-exhausted.json"
    cq.record_exhausted(None, source="classify", now=NOW, path=rp)
    wave = cq.record_wave(cq.read_exhausted(path=rp))
    cq.record_exhausted(NOW + 3 * HOUR, source="probe", now=NOW + 60, path=rp)
    assert cq.record_wave(cq.read_exhausted(path=rp)) == wave


# ---- item 8: only a FULL await-reset that polled marks the wave --------------------------------------------- #
@pytest.mark.parametrize("max_wait", [3, 300, cq.AWAIT_MAX_WAIT_S - 1])
def test_322_usr_a_short_wait_does_not_mark_the_wave(sessions, tmp_path, fixture_home, max_wait):
    cq.record_exhausted(NOW + 4 * HOUR, source="admit", now=NOW, path=_record_path(fixture_home))
    clock = _FakeTime()
    code, out = _await(tmp_path, sessions, clock, _scripted_probe(clock, ["exhausted"]), poll=120,
                       max_wait=max_wait)
    assert (code, out["source"]) == (4, "timeout")
    assert not (_state(fixture_home) / cq.AWAIT_TIMEOUT_FILENAME).exists()


def test_322_usr_a_full_wait_with_no_poll_cycle_does_not_mark_the_wave(sessions, tmp_path, fixture_home):
    cq.record_exhausted(NOW + 4 * HOUR, source="admit", now=NOW, path=_record_path(fixture_home))
    clock = _FakeTime()

    def probe():                     # the first probe runs to the deadline: no poll cycle ever ran
        clock.t += cq.AWAIT_MAX_WAIT_S
        return "exhausted", 1

    code, out = _await(tmp_path, sessions, clock, probe, poll=120)
    assert (code, out["source"]) == (4, "timeout")
    assert not (_state(fixture_home) / cq.AWAIT_TIMEOUT_FILENAME).exists()


def test_322_usr_a_full_polled_wait_marks_the_wave(sessions, tmp_path, fixture_home):
    """CONTROL: the default wait, polled, still marks the record's wave."""
    cq.record_exhausted(NOW + 4 * HOUR, source="admit", now=NOW, path=_record_path(fixture_home))
    wave = cq.record_wave(cq.read_exhausted(path=_record_path(fixture_home)))
    clock = _FakeTime()
    assert _await(tmp_path, sessions, clock, _scripted_probe(clock, ["exhausted"]), poll=120)[0] == 4
    assert cq._timed_out_wave(_state(fixture_home)) == wave


# ---- item 6: the retry-at bound is exactly seven days ------------------------------------------------------ #
def test_322_usr_the_retry_at_bound_is_exactly_seven_days(london):
    assert cq.RETRY_AT_MAX_AHEAD_S == 7 * 24 * 3600
    now = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc).timestamp()
    # Oct 3rd 1:30 PM BST is 12:30 UTC: 7 days 30 minutes ahead -> refused
    assert cq.retry_at_from_text("try again at Oct 3rd, 2026 1:30 PM.", now) is None
    # Oct 3rd 12:30 PM BST is 11:30 UTC: 6 days 23.5 hours ahead -> parsed
    assert cq.retry_at_from_text("try again at Oct 3rd, 2026 12:30 PM.", now) == \
        int(datetime(2026, 10, 3, 11, 30, tzinfo=timezone.utc).timestamp())
