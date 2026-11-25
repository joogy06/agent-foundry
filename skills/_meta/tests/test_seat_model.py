#!/usr/bin/env python3
"""Tests for seat_model.py — the role table, auto-follow, freeze pins, the agy family rule, the CLI.

S081 design §4.2 (role table), §4.3 (auto-follow + its safety), §4.4 (protected roles),
§11 (Auto-follow / Trust / Argv shape); plan interpretations I4, I5, I6, I13, I17, I21.
Amendment 1 item 2 + item 7 (revision 2b WP-F02; J10, J11, J12): "no eligible TOP" told apart
from a broken resolver, `substitute()`, and the CLI's `argv --use` / `substitute` exit-code
contract (0 pin / 3 substitute / 10 skipped / 1 broken / 2 usage). Those tests also redirect
the astra budget store: it lives under the fixture HOME (asserted), never the live one.

ISOLATION. Every test runs under a fixture HOME (autouse `fixture_home`): the codex roster,
the agy roster cache, the freeze pins, the tops record and the codex sessions tree all
resolve inside tmp. `test_fixture_home_is_active_and_the_resolver_reads_it` proves the
redirect is live by resolving a fixture-only sentinel slug, so the isolation is shown and
not assumed. No test reads the live `~/.codex` or `~/.claude/state`.

Rosters are fixtures in the LIVE shapes observed on 2026-09-14: codex entries carry
`supported_reasoning_levels` as OBJECTS keyed `effort`, and `fetched_at` with nanosecond
precision; the agy cache is `agy-models.v1` (I17).

Every guarantee is paired with a CONTROL that shows the same fixture can produce the other
answer, so a test cannot pass because the code path under test never ran.
"""
import ast
import json
import os
import shutil
import socket
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType

import pytest

_HERE = Path(__file__).resolve().parent
_META = _HERE.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import codex_model  # type: ignore  # noqa: E402
import codex_quota  # type: ignore  # noqa: E402
import seat_model as sm  # type: ignore  # noqa: E402
import model_roster  # type: ignore  # noqa: E402
import codex_roster_fixture as crf  # type: ignore  # noqa: E402

#: #291: the model a Claude seat serves is ROSTER DATA, not a fact of this file. Where a test
#: below means "the role's model" it asserts against these tier constants, read from
#: model_roster (the data), never from the resolver under test. The literal values are pinned
#: once, by hand, in test_model_roster_golden.py, and the resolver's use of the tiers is
#: checked against explicit literal pairs by test_roster_reversibility_* at the end of this
#: file. Synthetic served ids and fake pins stay literal.
MAIN = model_roster.CLAUDE_MAIN          # code_reviewer / consultant_main / arbiter / escalation
SUPPORT = model_roster.CLAUDE_SUPPORT    # consultant_support
#: #302 WP-1: the codex tiers, read the same way. STD = the light/medium sized main seats and the
#: `std` spend class; CODEX_SUP = the consultant_support codex row (CODEX_STD before roster rev 3).
#: Read through functions so a test that monkeypatches model_roster sees its own values.
STD = crf.codex_std()
CODEX_SUP = crf.codex_support()

_REAL_HOME = Path.home()
_MODULE_PATH = _META / "seat_model.py"

#: 2026-09-14T15:33:20Z. The resolver's clock is pinned to it, so roster ages are exact.
NOW = 1789400000.0
DAY = 86400.0

FORBIDDEN_AGY = (
    "gemini-3.8-flash-high",       # #367: flash is refused once argon is the roster family
    "gemini-4-flash-medium",
    "gemini-4-pro-high",
    "gemini-3.1-pro-high",
    "claude-sonnet-4-6",
    "claude-opus-4-6-thinking",
    "gpt-oss-120b-medium",
)

_POSIX_SHELL = pytest.mark.skipif(
    os.name == "nt" or shutil.which("bash") is None or shutil.which("timeout") is None,
    reason="argv-shape stubs need bash, coreutils timeout and POSIX shebangs",
)


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def fixture_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "state").mkdir(parents=True)
    (home / ".codex").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(sm, "_now", lambda: NOW)
    # #291 WP-6: pin the working directory to an EMPTY tmp dir. The CLI reads `<cwd>/.forge/size`
    # and `<cwd>/.forge/cycle-id`, so without this a live forge cycle in the directory pytest was
    # started from (the repo root, with `.forge/size = complex`) turned 8 CLI tests red (the
    # default size resolved TOP instead of the std model). A test that means a specific cwd still
    # sets it with its own monkeypatch.chdir, which runs after this one.
    neutral_cwd = tmp_path / "neutral-cwd"
    neutral_cwd.mkdir()
    monkeypatch.chdir(neutral_cwd)
    for var in ("SEAT_TEST_ENV",):
        monkeypatch.delenv(var, raising=False)
    return home


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_nanos(epoch):
    """The live codex `fetched_at` shape: nine fractional digits."""
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + ".887906859Z"


def entry(slug, priority, *, visibility="list", api=True, efforts=("low", "medium", "high", "xhigh", "max", "ultra"),
          upgrade=None):
    return crf.entry(slug, priority, visibility=visibility, api=api, efforts=efforts, upgrade=upgrade)


def live_like_codex_entries(**opts):
    """The 2026-09-14 live roster, reduced to the selection-relevant fields, listing the roster's
    codex tiers (#302 WP-1: the shared synthetic roster, skills/_meta/tests/codex_roster_fixture.py)."""
    return crf.codex_entries(**opts)


def write_codex_roster(home, entries=None, *, fetched_at=None):
    return crf.write_codex_roster(home, live_like_codex_entries() if entries is None else entries,
                                  fetched_at=iso_nanos(NOW - 3600) if fetched_at is None else fetched_at)


def live_like_agy_models():
    return [
        "gemini-4-argon-high", "gemini-4-argon-medium", "gemini-4-argon-low",
        "gemini-3.7-argon-high", "gemini-3.7-argon-medium", "gemini-3.7-argon-low",
        "gemini-3.6-argon-high", "gemini-3.6-argon-medium", "gemini-3.6-argon-low",
        # #367: the live cache still lists the retired flash line; the family rule never selects it.
        "gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-3.8-flash-low",
        "gemini-3.1-pro-high", "gemini-3.1-pro-low",
        "claude-sonnet-4-6", "claude-opus-4-6-thinking", "gpt-oss-120b-medium",
    ]


def write_agy_cache(home, models=None, *, fetched_at=None, schema="agy-models.v1"):
    doc = {
        "schema": schema,
        "fetched_at": iso(NOW - 3600) if fetched_at is None else fetched_at,
        "agy_version": "1.2.2",
        "models": live_like_agy_models() if models is None else models,
    }
    path = home / ".claude" / "state" / "agy-models.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def write_pins(home, pins, *, raw=None):
    path = home / ".claude" / "state" / "seat-model-pins.json"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
        return path
    doc = {"schema": "seat-model-pins.v1", "pins": {
        provider: {"top": top, "set_at": iso(NOW), "reason": "fixture"} for provider, top in pins.items()
    }}
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def tops_path(home):
    return home / ".claude" / "state" / "seat-model-tops.json"


def read_tops(home):
    return json.loads(tops_path(home).read_text(encoding="utf-8"))


def write_tops(home, tops):
    doc = {"schema": "seat-model-tops.v1", "tops": {
        provider: {"top": top, "previous": None, "changed_at": None, "resolved_at": iso(NOW - 10 * DAY),
                   "roster_fetched_at": None}
        for provider, top in tops.items()
    }}
    tops_path(home).write_text(json.dumps(doc), encoding="utf-8")


def tree_snapshot(root):
    """relative path -> file bytes (directories -> None) for everything under root."""
    snap = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for d in dirnames:
            snap[os.path.relpath(os.path.join(dirpath, d), root)] = None
        for f in filenames:
            full = os.path.join(dirpath, f)
            with open(full, "rb") as fh:
                snap[os.path.relpath(full, root)] = fh.read()
    return snap


def run_cli(args, *, env_extra=None, cwd=None, timeout=60):
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(_MODULE_PATH), *args],
        capture_output=True, text=True, encoding="utf-8", env=env,
        cwd=str(cwd) if cwd is not None else None, timeout=timeout, stdin=subprocess.DEVNULL,
    )


# --------------------------------------------------------------------------- #
# Isolation guard
# --------------------------------------------------------------------------- #
def test_fixture_home_is_active_and_the_resolver_reads_it(fixture_home):
    assert Path.home() == fixture_home
    assert Path.home() != _REAL_HOME
    paths = sm._paths()
    for p in (paths.codex_roster, paths.codex_sessions, paths.agy_roster, paths.pins, paths.tops):
        assert fixture_home in p.parents, p
    # A slug that exists ONLY in this fixture resolves, so the resolver really read it.
    write_codex_roster(fixture_home, [entry("gpt-fixture-sentinel", 0)] + live_like_codex_entries())
    pin = sm.resolve("code_reviewer", "codex")
    assert pin.model == "gpt-fixture-sentinel"
    assert pin.provenance["source"] == "roster"


def test_paths_are_derived_from_home_at_call_time(tmp_path, monkeypatch):
    first = sm._paths().pins
    other = tmp_path / "other-home"
    monkeypatch.setenv("HOME", str(other))
    monkeypatch.setenv("USERPROFILE", str(other))
    assert sm._paths().pins == other / ".claude" / "state" / "seat-model-pins.json"
    assert first != sm._paths().pins


# --------------------------------------------------------------------------- #
# Role table
# --------------------------------------------------------------------------- #
def _row_view(row):
    return (row.kind, row.value, row.effort, row.level, row.timeout)


def _claude_effort(role):
    """A Claude seat's pinned effort, read from the one authority (seat_model.ROLE_TABLE)."""
    return sm.ROLE_TABLE[role]["claude"].effort


def test_role_table_is_exactly_design_4_2():
    expected = {
        "code_reviewer": {
            "claude": ("alias", MAIN, "medium", None, 600),      # #311 U3; medium since 2026-10-29
            "codex": ("top", None, "xhigh", None, None),
        },
        "consultant_main": {
            "claude": ("alias", MAIN, "medium", None, 600),
            # RE-POINTED by the astra reserve (roster rev 4, U1): Sol @ xhigh at every size.
            "codex": ("literal", STD, "xhigh", None, None),
            "agy": ("top_agy", None, None, "high", 600),
        },
        "consultant_support": {
            "claude": ("alias", SUPPORT, "medium", None, 600),
            "codex": ("literal", CODEX_SUP, "medium", None, None),
            "agy": ("top_agy", None, None, "medium", 600),
        },
        "arbiter": {
            "claude": ("alias", MAIN, "medium", None, 1200),
            "codex": ("literal", STD, "xhigh", None, None),       # the astra reserve U4: Sol @ xhigh
            "agy": ("top_agy", None, None, "high", 600),
        },
        "escalation": {
            "claude": ("alias", MAIN, "xhigh", None, 1200),
            "codex": ("top", None, "max", None, None),
        },
    }
    actual = {role: {prov: _row_view(row) for prov, row in rows.items()} for role, rows in sm.ROLE_TABLE.items()}
    assert actual == expected
    assert tuple(sm.ROLES) == ("code_reviewer", "consultant_main", "consultant_support", "arbiter", "escalation")
    assert sm.PROTECTED == frozenset({"code_reviewer", "consultant_main", "arbiter", "escalation"})


def test_role_table_is_not_mutable_at_runtime():
    with pytest.raises(TypeError):
        sm.ROLE_TABLE["execution"] = {}
    with pytest.raises(TypeError):
        sm.ROLE_TABLE["code_reviewer"]["agy"] = sm.ROLE_TABLE["arbiter"]["agy"]


@pytest.mark.parametrize("role,provider", [("code_reviewer", "agy"), ("escalation", "agy")])
@pytest.mark.parametrize("fail_open", [False, True])
def test_missing_row_raises_even_fail_open(role, provider, fail_open):
    with pytest.raises(sm.SeatModelError, match="no row"):
        sm.resolve(role, provider, fail_open=fail_open)


@pytest.mark.parametrize("role,provider", [
    ("execution", "claude"), ("executor", "codex"), ("Code_Reviewer", "claude"),
    ("code_reviewer", "gemini"), ("code_reviewer", ""), ("arbiter", "Claude"),
])
def test_unknown_role_or_provider_raises_even_fail_open(role, provider):
    with pytest.raises(sm.SeatModelError):
        sm.resolve(role, provider, fail_open=True)


def test_legacy_role_map_documents_every_codex_model_role_with_the_same_effort(fixture_home):
    assert set(sm.LEGACY_ROLE_MAP) == set(codex_model.ROLES)
    assert sm.LEGACY_ROLE_MAP == {
        "challenger_floor": ("consultant_main", "codex"),
        "ratification_arbiter": ("arbiter", "codex"),
        "audit_codex_arm": ("code_reviewer", "codex"),
    }
    for legacy, (role, provider) in sm.LEGACY_ROLE_MAP.items():
        if legacy == "ratification_arbiter":
            # The astra reserve U4: the arbiter ROW is Sol @ xhigh; the RATIFICATION seat class keeps max.
            assert (sm.ROLE_TABLE[role][provider].effort, codex_model._ROLE_PINS[legacy].effort) == ("xhigh", "max")
            continue
        assert sm.ROLE_TABLE[role][provider].effort == codex_model._ROLE_PINS[legacy].effort


def test_codex_timeouts_are_owned_by_codex_model_timeout_for(fixture_home, monkeypatch):
    write_codex_roster(fixture_home)
    for role in sm.ROLES:
        pin = sm.resolve(role, "codex")
        assert pin.timeout == codex_model.timeout_for(pin.model, pin.effort)
    assert sm.resolve("escalation", "codex").timeout == 3600
    assert sm.resolve("arbiter", "codex").timeout == 2400          # the astra reserve U4: xhigh
    assert sm.resolve("code_reviewer", "codex").timeout == 2400
    # CONTROL: changing the codex floor table is what changes the seat's timeout.
    monkeypatch.setitem(codex_model._MODEL_TIMEOUT_OVERRIDES_S, ("gpt-6-astra", "xhigh"), 777)
    assert sm.resolve("code_reviewer", "codex").timeout == 777


def test_claude_and_agy_timeouts_come_from_the_role_table(fixture_home):
    write_agy_cache(fixture_home)
    assert [sm.resolve(r, "claude").timeout for r in sm.ROLES] == [600, 600, 600, 1200, 1200]
    assert [sm.resolve(r, "agy").timeout for r in ("consultant_main", "consultant_support", "arbiter")] == [600] * 3


# --------------------------------------------------------------------------- #
# S081 revision 4, D24 (WP-A02) — the WHOLE seat timeout matrix, in one place.
#
# The raise lives in codex_model._TIMEOUT_FLOOR_S, so it reaches every CODEX
# cell and no other. This test exists because the registry delta of stream A0 is
# enumerated IN ADVANCE: five codex `timeout` paths move and nothing else does.
# Reading it as a matrix is what makes "and nothing else" checkable rather than
# asserted — a claude or agy cell drifting onto codex_model's table fails HERE.
#
# L13 (settled 2026-09-16, team lead): the agy SEAT timeout STAYS 600 this
# revision. `codex_watch.AGY_HARD_CAP_S = 900` carries the agy cap as a
# WATCHDOG-only constant, exactly as the codex idle timeout already is. The agy
# rows below are therefore a DELIBERATE 600, not an oversight.
# --------------------------------------------------------------------------- #
D24_SEAT_TIMEOUT_MATRIX = {
    # (role, provider): timeout.  codex := codex_model._TIMEOUT_FLOOR_S[effort]
    #                             claude/agy := ROLE_TABLE harness literals
    ("code_reviewer", "claude"): 600,      ("code_reviewer", "codex"): 2400,      # xhigh
    ("consultant_main", "claude"): 600,    ("consultant_main", "codex"): 2400,    # xhigh
    ("consultant_main", "agy"): 600,
    ("consultant_support", "claude"): 600, ("consultant_support", "codex"): 1200,  # medium
    ("consultant_support", "agy"): 600,
    ("arbiter", "claude"): 1200,           ("arbiter", "codex"): 2400,            # xhigh (astra reserve U4)
    ("arbiter", "agy"): 600,
    ("escalation", "claude"): 1200,        ("escalation", "codex"): 3600,         # max
}


def test_d24_every_seat_cell_resolves_to_its_pinned_timeout(fixture_home):
    """Every (role, provider) cell in the table, pinned. The codex column is the
    D24 raise; the claude and agy columns are UNCHANGED harness literals."""
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    resolved = {}
    for role, provs in sm.ROLE_TABLE.items():
        for provider in provs:
            resolved[(role, provider)] = sm.resolve(role, provider).timeout
    assert resolved == D24_SEAT_TIMEOUT_MATRIX
    # The codex column comes from codex_model, cell by cell — not from a second table here.
    for (role, provider), timeout in D24_SEAT_TIMEOUT_MATRIX.items():
        if provider != "codex":
            continue
        pin = sm.resolve(role, "codex")
        assert codex_model.timeout_for(pin.model, pin.effort) == timeout, role
        assert codex_model._TIMEOUT_FLOOR_S[pin.effort] == timeout, role


def test_d24_seat_timeouts_match_the_watchdog_hard_caps(fixture_home):
    """NEGATIVE CONTROL for the raise: the point of D24 is that the registry a
    caller asks for its timeout and the watchdog that enforces the runaway cap
    agree. A caller that gets 600 here and runs codex_watch at 2400 (or the
    reverse) is the exact defect the raise removes, so the two tables are pinned
    to each other for every effort the seat registry can actually reach."""
    codex_watch = pytest.importorskip("codex_watch")
    write_codex_roster(fixture_home)
    reachable = {sm.resolve(r, "codex").effort for r in sm.ROLES}
    assert reachable == {"medium", "xhigh", "max"}          # ROLE_TABLE's whole codex column
    for effort in sorted(reachable):
        assert codex_model._TIMEOUT_FLOOR_S[effort] == codex_watch.HARD_CAP_S[effort], effort
    # CONTROL: they are distinct tables that happen to agree, not one aliased to
    # the other — codex_watch deliberately tabulates NO `minimal` row (it raises),
    # while codex_model keeps its own 120 s floor for an effort no seat can reach.
    assert codex_model._TIMEOUT_FLOOR_S is not codex_watch.HARD_CAP_S
    assert "minimal" in codex_model._TIMEOUT_FLOOR_S and "minimal" not in codex_watch.HARD_CAP_S
    with pytest.raises(codex_watch.CodexWatchError):
        codex_watch.hard_cap_for("minimal")


def test_is_top_names_the_top_selectors_only():
    assert sm.is_top("code_reviewer", "codex")
    # RE-POINTED by the astra reserve (roster rev 4): consultant_main and arbiter are Sol literals.
    assert not sm.is_top("consultant_main", "codex")
    assert not sm.is_top("arbiter", "codex")
    assert sm.is_top("escalation", "codex")
    assert not sm.is_top("consultant_support", "codex")
    assert sm.is_top("consultant_support", "agy")          # TOP-argon, level medium
    assert not sm.is_top("code_reviewer", "claude")
    with pytest.raises(sm.SeatModelError):
        sm.is_top("code_reviewer", "agy")


# --------------------------------------------------------------------------- #
# Codex auto-follow (design §4.3)
# --------------------------------------------------------------------------- #
def test_new_priority_one_listed_slug_is_followed(fixture_home):
    entries = live_like_codex_entries()
    entries[0]["priority"] = 2                           # astra drops to p2
    entries.append(entry("gpt-7-nova", 1))
    write_codex_roster(fixture_home, entries)
    pin = sm.resolve("code_reviewer", "codex")
    assert (pin.model, pin.effort, pin.provenance["source"]) == ("gpt-7-nova", "xhigh", "roster")
    assert pin.argv_fragment == ("-m", "gpt-7-nova", "-c", "model_reasoning_effort=xhigh")
    # CONTROL: without the new entry the same roster serves astra.
    write_codex_roster(fixture_home)
    assert sm.resolve("code_reviewer", "codex").model == "gpt-6-astra"


def test_hidden_entry_is_never_selected(fixture_home):
    entries = live_like_codex_entries()
    entries.append(entry("gpt-hidden-zero", 0, visibility="hide"))
    write_codex_roster(fixture_home, entries)
    assert sm.resolve("code_reviewer", "codex").model == "gpt-6-astra"
    # CONTROL: the same entry listed is selected.
    entries[-1]["visibility"] = "list"
    write_codex_roster(fixture_home, entries)
    assert sm.resolve("code_reviewer", "codex").model == "gpt-hidden-zero"


def test_entry_not_supported_in_api_is_never_selected(fixture_home):
    entries = live_like_codex_entries()
    entries.append(entry("gpt-no-api", 0, api=False))
    write_codex_roster(fixture_home, entries)
    assert sm.resolve("escalation", "codex").model == "gpt-6-astra"
    entries[-1]["supported_in_api"] = True                # CONTROL
    write_codex_roster(fixture_home, entries)
    assert sm.resolve("escalation", "codex").model == "gpt-no-api"


def test_effort_unsupported_by_the_top_falls_to_the_next_eligible(fixture_home):
    entries = live_like_codex_entries()
    entries[0]["supported_reasoning_levels"] = [{"effort": e} for e in ("low", "medium", "high", "xhigh")]
    write_codex_roster(fixture_home, entries)
    assert sm.resolve("arbiter", "codex").model == STD        # max: astra lacks it
    assert sm.resolve("escalation", "codex").model == STD
    assert sm.resolve("code_reviewer", "codex").model == "gpt-6-astra"  # CONTROL: xhigh still astra


def test_upgrade_field_is_followed_and_recorded(fixture_home):
    entries = live_like_codex_entries()
    entries[0]["upgrade"] = "gpt-5.6-terra"
    write_codex_roster(fixture_home, entries)
    pin = sm.resolve("code_reviewer", "codex")
    assert pin.model == "gpt-5.6-terra"
    assert pin.provenance["upgrade_followed"] is True
    # CONTROL: a null upgrade keeps the priority winner and records nothing.
    write_codex_roster(fixture_home)
    control = sm.resolve("code_reviewer", "codex")
    assert control.model == "gpt-6-astra"
    assert "upgrade_followed" not in control.provenance
    assert "upgrade_ignored_reason" not in control.provenance


def test_ignored_upgrade_is_recorded_not_hidden(fixture_home):
    entries = live_like_codex_entries()
    entries[0]["upgrade"] = "gpt-reserve"                 # hidden target
    write_codex_roster(fixture_home, entries)
    pin = sm.resolve("code_reviewer", "codex")
    assert pin.model == "gpt-6-astra"
    assert "gpt-reserve" in pin.provenance["upgrade_ignored_reason"]


@pytest.mark.parametrize("role", ["code_reviewer", "escalation"])
def test_roster_with_no_eligible_model_takes_the_call_site_failure_path(fixture_home, role):
    write_codex_roster(fixture_home, [entry("gpt-hidden", 1, visibility="hide"), entry("gpt-no-api", 2, api=False)])
    with pytest.raises(sm.SeatModelError, match="eligible"):
        sm.resolve(role, "codex", fail_open=False)
    pin = sm.resolve(role, "codex", fail_open=True)
    assert (pin.model, pin.provenance["source"]) == ("gpt-6-astra", "harness_literal")
    assert "eligible" in pin.provenance["fallback_reason"]


def test_stale_codex_roster_keeps_the_last_recorded_top(fixture_home):
    entries = live_like_codex_entries()
    entries.append(entry("gpt-7-nova", 0))
    write_codex_roster(fixture_home, entries, fetched_at=iso_nanos(NOW - 8 * DAY))
    write_tops(fixture_home, {"codex": "gpt-6-astra"})
    pin = sm.resolve("code_reviewer", "codex")
    assert (pin.model, pin.provenance["source"]) == ("gpt-6-astra", "roster")
    assert pin.provenance["roster_stale"] is True
    # CONTROL: the same roster when fresh follows the new top and is not flagged.
    write_codex_roster(fixture_home, entries, fetched_at=iso_nanos(NOW - 6 * DAY))
    fresh = sm.resolve("code_reviewer", "codex")
    assert fresh.model == "gpt-7-nova"
    assert "roster_stale" not in fresh.provenance


def test_stale_codex_roster_without_a_recorded_top_uses_the_stale_top_flagged(fixture_home):
    write_codex_roster(fixture_home, fetched_at=iso_nanos(NOW - 30 * DAY))
    pin = sm.resolve("code_reviewer", "codex")
    assert (pin.model, pin.provenance["source"], pin.provenance["roster_stale"]) == ("gpt-6-astra", "roster", True)


def test_stale_last_top_ineligible_for_the_effort_uses_the_stale_rosters_top(fixture_home):
    entries = live_like_codex_entries()
    write_codex_roster(fixture_home, entries, fetched_at=iso_nanos(NOW - 8 * DAY))
    write_tops(fixture_home, {"codex": "gpt-5.5"})        # gpt-5.5 has no `max`
    arb = sm.resolve("escalation", "codex")
    assert (arb.model, arb.provenance["roster_stale"]) == ("gpt-6-astra", True)
    # The per-effort fallback is served but does NOT replace the kept top ...
    assert read_tops(fixture_home)["tops"]["codex"]["top"] == "gpt-5.5"
    rev = sm.resolve("code_reviewer", "codex")            # CONTROL: xhigh keeps the last top
    assert rev.model == "gpt-5.5"


def test_stale_agy_fallback_does_not_replace_the_kept_top(fixture_home):
    write_agy_cache(fixture_home, ["gemini-4-argon-high", "gemini-4.9-argon-medium", "gemini-4.9-argon-high"],
                    fetched_at=iso(NOW - 9 * DAY))
    write_tops(fixture_home, {"agy": "gemini-4-argon"})              # 3.8 has no -medium listed
    assert sm.resolve("consultant_support", "agy").model == "gemini-4.9-argon-medium"
    assert read_tops(fixture_home)["tops"]["agy"]["top"] == "gemini-4-argon"
    assert sm.resolve("consultant_main", "agy").model == "gemini-4-argon-high"   # CONTROL: kept top


@pytest.mark.parametrize("fetched_at", [None, "", "yesterday", 12345])
def test_unusable_fetched_at_counts_as_stale(fixture_home, fetched_at):
    doc = {"client_version": "0.154.0", "models": live_like_codex_entries()}
    if fetched_at is not None:
        doc["fetched_at"] = fetched_at
    (fixture_home / ".codex" / "models_cache.json").write_text(json.dumps(doc), encoding="utf-8")
    assert sm.resolve("code_reviewer", "codex").provenance["roster_stale"] is True


def test_live_nanosecond_fetched_at_parses_as_fresh(fixture_home):
    write_codex_roster(fixture_home, fetched_at=iso_nanos(NOW - 60))
    pin = sm.resolve("code_reviewer", "codex")
    assert "roster_stale" not in pin.provenance
    assert pin.provenance["roster_fetched_at"] == iso_nanos(NOW - 60)


@pytest.mark.parametrize("fail_open", [False, True])
def test_no_codex_roster_resolves_the_harness_literal(fixture_home, fail_open):
    pin = sm.resolve("code_reviewer", "codex", fail_open=fail_open)
    assert (pin.model, pin.effort, pin.timeout) == ("gpt-6-astra", "xhigh", 2400)
    assert pin.provenance["source"] == "harness_literal"
    assert pin.provenance["roster_fetched_at"] is None
    assert "no codex roster" in pin.provenance["fallback_reason"]
    arb = sm.resolve("escalation", "codex", fail_open=fail_open)
    assert (arb.model, arb.effort, arb.timeout) == ("gpt-6-astra", "max", 3600)
    # the astra reserve: a Sol literal with no roster is its own slug (the sanctioned literal path)
    sol = sm.resolve("arbiter", "codex", fail_open=fail_open)
    assert (sol.model, sol.effort, sol.provenance["source"]) == (STD, "xhigh", "harness_literal")
    sup = sm.resolve("consultant_support", "codex", fail_open=fail_open)
    assert (sup.model, sup.effort, sup.provenance["source"]) == (CODEX_SUP, "medium", "harness_literal")


@pytest.mark.parametrize("raw", ["{not json", json.dumps({"models": "nope"}), json.dumps([1, 2]),
                                 json.dumps({"models": [{"no_slug": 1}]})])
def test_malformed_codex_roster_is_invalid_not_no_roster(fixture_home, raw):
    """INVERTED and RENAMED by #282 R4 (plan K14; was test_malformed_codex_roster_counts_as_no_roster):
    a malformed roster is INVALID, not absent. Fail-closed it raises (it served the harness literal
    before); fail-open it serves the literal and records roster_invalid."""
    (fixture_home / ".codex" / "models_cache.json").write_text(raw, encoding="utf-8")
    with pytest.raises(sm.SeatModelError, match="roster_invalid") as info:
        sm.resolve("code_reviewer", "codex", fail_open=False)
    assert not isinstance(info.value, sm.NoEligibleModelError)
    pin = sm.resolve("code_reviewer", "codex", fail_open=True)
    assert (pin.model, pin.provenance["source"], pin.provenance["roster_invalid"]) == (
        "gpt-6-astra", "harness_literal", True)


def test_support_literal_is_validated_against_the_roster(fixture_home):
    write_codex_roster(fixture_home, [e for e in live_like_codex_entries() if e["slug"] != CODEX_SUP])
    with pytest.raises(sm.SeatModelError, match=CODEX_SUP):
        sm.resolve("consultant_support", "codex", fail_open=False)
    pin = sm.resolve("consultant_support", "codex", fail_open=True)
    assert (pin.model, pin.provenance["source"]) == (CODEX_SUP, "harness_literal")
    assert CODEX_SUP in pin.provenance["fallback_reason"]
    # CONTROL: present in the roster -> roster-sourced, no fallback.
    write_codex_roster(fixture_home)
    ok = sm.resolve("consultant_support", "codex", fail_open=False)
    assert (ok.model, ok.effort, ok.timeout, ok.provenance["source"]) == (CODEX_SUP, "medium", 1200, "roster")
    assert "fallback_reason" not in ok.provenance


@pytest.mark.parametrize("slug", ["gpt 6", "gpt-6;rm", "$(boom)", "gpt*", "-m", "gpt-6\n"])
def test_a_roster_slug_unsafe_for_a_shell_word_is_rejected(fixture_home, slug):
    write_codex_roster(fixture_home, [entry(slug, 0)] + live_like_codex_entries())
    with pytest.raises(sm.SeatModelError):
        sm.resolve("code_reviewer", "codex", fail_open=False)
    # CONTROL: a safe slug at the same priority is served.
    write_codex_roster(fixture_home, [entry("gpt-safe.1", 0)] + live_like_codex_entries())
    assert sm.resolve("code_reviewer", "codex").model == "gpt-safe.1"


# --------------------------------------------------------------------------- #
# effort= (I5)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("provider,role", [("claude", "code_reviewer"), ("agy", "consultant_main")])
def test_effort_override_is_codex_only(fixture_home, provider, role):
    write_agy_cache(fixture_home)
    with pytest.raises(sm.SeatModelError, match="codex only"):
        sm.resolve(role, provider, effort="medium", fail_open=True)


def test_effort_override_is_validated_for_the_resolved_model(fixture_home):
    entries = live_like_codex_entries()
    entries[0]["supported_reasoning_levels"] = [{"effort": e} for e in ("medium", "xhigh")]
    write_codex_roster(fixture_home, entries)
    medium = sm.resolve("code_reviewer", "codex", effort="medium")
    assert (medium.model, medium.effort, medium.timeout) == ("gpt-6-astra", "medium", 1200)
    assert medium.argv_fragment == ("-m", "gpt-6-astra", "-c", "model_reasoning_effort=medium")
    assert medium.provenance["requested_selector"] == "TOP@medium"
    maxed = sm.resolve("code_reviewer", "codex", effort="max")          # astra lacks max -> next eligible
    assert (maxed.model, maxed.effort, maxed.timeout) == (STD, "max", 3600)
    with pytest.raises(sm.SeatModelError):
        sm.resolve("code_reviewer", "codex", effort="minimal", fail_open=False)   # nobody supports it
    with pytest.raises(sm.SeatModelError):
        sm.resolve("code_reviewer", "codex", effort="x high", fail_open=True)     # not a token
    with pytest.raises(sm.SeatModelError):
        sm.resolve("code_reviewer", "codex", effort="", fail_open=True)


def test_effort_override_on_the_support_literal(fixture_home):
    write_codex_roster(fixture_home)
    pin = sm.resolve("consultant_support", "codex", effort="xhigh")
    assert (pin.model, pin.effort, pin.provenance["requested_selector"]) == (CODEX_SUP, "xhigh", f"{CODEX_SUP}@xhigh")
    with pytest.raises(sm.SeatModelError, match="minimal"):
        sm.resolve("consultant_support", "codex", effort="minimal", fail_open=False)


def test_effort_override_without_a_roster_is_checked_by_the_timeout_table(fixture_home):
    assert sm.resolve("consultant_main", "codex", effort="high").timeout == 2400
    with pytest.raises(sm.SeatModelError):
        sm.resolve("consultant_main", "codex", effort="bogus", fail_open=True)


# --------------------------------------------------------------------------- #
# The agy family rule (#367, formerly FLASH-ONLY; in code, on every agy output path)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("slug", FORBIDDEN_AGY)
def test_agy_family_rejects_the_forbidden_models_by_name(slug):
    assert sm.is_agy_family(slug) is False


@pytest.mark.parametrize("slug", ["gemini-4.9-argon-high", "gemini-4-argon-medium", "gemini-5-argon-low",
                                  "gemini-4.10.2-argon-high"])
def test_agy_family_accepts_family_slugs_control(slug):
    assert sm.is_agy_family(slug) is True


@pytest.mark.parametrize("slug", ["gemini-4.9-argon-high\n", " gemini-4.9-argon-high", "GEMINI-4.9-argon-high", "gemini-4.9-flash-high",
                                  "gemini-4.9-argon-ultra", "gemini-4.9-argon", "gemini-٣.9-argon-high",
                                  "gemini-4.9-argon-lite-high", "gemini-.9-argon-high", None, 38])
def test_agy_family_rejects_near_misses(slug):
    assert sm.is_agy_family(slug) is False


def test_agy_family_pattern_is_the_documented_regex():
    """#282 fix round 2 G7c (K59c) RE-POINTED: each digit group is now BOUNDED at 9.

    The old literal `^gemini-\\d+(\\.\\d+)*-flash-(high|medium|low)$` pinned the very unbounded
    `\\d+` that let a 4,301-digit slug reach `int()` inside `_agy_top` and raise past the
    fail-open boundary. The bound is the same one F12 gave `codex_model._GENERATION`, and it
    is what `test_fr2_g7c_an_absurd_digit_run_is_not_agy_family` now owns.
    """
    assert sm.AGY_FAMILY_PATTERN == r"^gemini-\d{1,9}(\.\d{1,9})*-argon-(high|medium|low)$"


#: #282 fix round 2 G7c: one digit past CPython's 4300-digit str->int limit, so `int(part)`
#: on it raises ValueError. Unbounded `\d+` matched it; `\d{1,9}` does not.
_ABSURD_VERSION = "9" * 4301
_ABSURD_AGY_SLUG = "gemini-" + _ABSURD_VERSION + "-argon-high"


def test_fr2_g7c_an_absurd_digit_run_is_not_agy_family():
    """G7c: a 4,301-digit version does not match the agy family rule, so it never reaches `int()`."""
    assert sm.is_agy_family(_ABSURD_AGY_SLUG) is False
    # The raise it used to cause is real, and this proves it rather than assuming it.
    with pytest.raises(ValueError):
        int(_ABSURD_VERSION)


def test_fr2_g7c_a_nine_digit_version_still_matches_and_still_orders_control(fixture_home):
    """CONTROL: the bound is nine, not one. Nine digits still match and still compare."""
    nine = "gemini-" + "9" * 9 + "-argon-high"
    assert sm.is_agy_family(nine) is True
    assert sm.is_agy_family("gemini-4.10-argon-high") is True
    write_agy_cache(fixture_home, ["gemini-4.9-argon-high", "gemini-4.10-argon-high"])
    assert sm.resolve("consultant_main", "agy").model == "gemini-4.10-argon-high"   # 4.10 > 4.9
    write_agy_cache(fixture_home, ["gemini-4.10-argon-high", nine])
    assert sm.resolve("consultant_main", "agy").model == nine                       # 999999999 > 3.10


@pytest.mark.parametrize("fail_open", [True, False])
def test_fr2_g7c_an_absurd_agy_slug_cannot_raise_out_of_the_fail_open_path(fixture_home, fail_open):
    """G7c: the absurd slug is rejected by the EXISTING path, never by an escaping ValueError.

    `_resolve_agy` catches `_ResolutionFailure`, not ValueError, so the `int()` inside
    `_agy_top` escaped both the fail-open fallback AND the fail-closed SeatModelError contract.
    """
    write_agy_cache(fixture_home, [_ABSURD_AGY_SLUG])
    if fail_open:
        pin = sm.resolve("consultant_main", "agy", fail_open=True)
        assert (pin.model, pin.provenance["source"]) == ("gemini-4-argon-high", "harness_literal")
        assert "eligible" in pin.provenance["fallback_reason"]
    else:
        with pytest.raises(sm.SeatModelError, match="eligible"):
            sm.resolve("consultant_main", "agy", fail_open=False)


def test_fr2_g7c_an_absurd_slug_beside_a_good_one_does_not_poison_the_roster(fixture_home):
    """G7c: the good slug is still selected — the absurd one is simply not a candidate.

    CONTROL for the test above: it shows the roster path still RUNS rather than failing
    whenever the absurd slug is present.
    """
    write_agy_cache(fixture_home, [_ABSURD_AGY_SLUG, "gemini-4.9-argon-high"])
    pin = sm.resolve("consultant_main", "agy", fail_open=False)
    assert (pin.model, pin.provenance["source"]) == ("gemini-4.9-argon-high", "roster")


def test_fr2_g7c_an_absurd_freeze_pin_is_refused_not_raised(fixture_home):
    """G7c on the freeze input: the absurd pin is refused by the agy family rule, not raised through."""
    write_agy_cache(fixture_home)
    write_pins(fixture_home, {"agy": _ABSURD_AGY_SLUG})
    with pytest.raises(sm.SeatModelError, match="agy family rule"):
        sm.resolve("consultant_main", "agy", fail_open=False)
    pin = sm.resolve("consultant_main", "agy", fail_open=True)
    assert (pin.model, pin.provenance["source"]) == ("gemini-4-argon-high", "harness_literal")
    assert "agy family rule" in pin.provenance["fallback_reason"]


def test_fr2_g7c_an_absurd_env_override_is_refused_not_raised(fixture_home, monkeypatch):
    """G7c on the env input: the absurd value is refused with the agy family rule reason."""
    write_agy_cache(fixture_home)
    monkeypatch.setenv("SEAT_TEST_ENV", _ABSURD_AGY_SLUG)
    pin = sm.resolve("consultant_support", "agy", env_var="SEAT_TEST_ENV")
    assert (pin.model, pin.provenance["source"]) == ("gemini-4-argon-medium", "roster")
    assert pin.provenance["env_override_refused"]["value"] == _ABSURD_AGY_SLUG
    assert "agy family rule" in pin.provenance["env_override_refused"]["reason"]


def test_agy_roster_path_never_serves_a_forbidden_model(fixture_home):
    write_agy_cache(fixture_home, list(FORBIDDEN_AGY))
    for role in ("consultant_main", "consultant_support", "arbiter"):
        with pytest.raises(sm.SeatModelError, match="eligible"):
            sm.resolve(role, "agy", fail_open=False)
    # CONTROL: the same forbidden list plus one family slug serves the family slug.
    write_agy_cache(fixture_home, list(FORBIDDEN_AGY) + ["gemini-4.9-argon-high"])
    pin = sm.resolve("consultant_main", "agy")
    assert (pin.model, pin.provenance["source"]) == ("gemini-4.9-argon-high", "roster")
    assert pin.argv_fragment == ("--model", "gemini-4.9-argon-high")


@pytest.mark.parametrize("slug", FORBIDDEN_AGY)
def test_agy_freeze_pin_that_fails_the_family_rule_takes_the_failure_path(fixture_home, slug):
    write_agy_cache(fixture_home)
    write_pins(fixture_home, {"agy": slug})
    with pytest.raises(sm.SeatModelError, match="agy family rule"):
        sm.resolve("consultant_main", "agy", fail_open=False)
    pin = sm.resolve("consultant_main", "agy", fail_open=True)
    assert (pin.model, pin.provenance["source"]) == ("gemini-4-argon-high", "harness_literal")
    assert "agy family rule" in pin.provenance["fallback_reason"]


def test_agy_freeze_pin_family_control_is_accepted(fixture_home):
    write_agy_cache(fixture_home, live_like_agy_models() + ["gemini-4.9-argon-high", "gemini-4.9-argon-medium"])
    write_pins(fixture_home, {"agy": "gemini-4.9-argon-high"})
    pin = sm.resolve("consultant_main", "agy", fail_open=False)
    assert (pin.model, pin.provenance["source"]) == ("gemini-4.9-argon-high", "freeze")


@pytest.mark.parametrize("slug", FORBIDDEN_AGY)
def test_agy_env_override_that_fails_the_family_rule_is_refused(fixture_home, monkeypatch, slug):
    write_agy_cache(fixture_home)
    monkeypatch.setenv("SEAT_TEST_ENV", slug)
    pin = sm.resolve("consultant_support", "agy", env_var="SEAT_TEST_ENV")
    assert pin.model == "gemini-4-argon-medium"
    assert pin.provenance["source"] == "roster"
    assert pin.provenance["env_override_refused"]["value"] == slug


def test_agy_env_override_family_control_is_accepted_for_support(fixture_home, monkeypatch):
    write_agy_cache(fixture_home)
    monkeypatch.setenv("SEAT_TEST_ENV", "gemini-4.9-argon-high")
    pin = sm.resolve("consultant_support", "agy", env_var="SEAT_TEST_ENV")
    assert (pin.model, pin.provenance["source"]) == ("gemini-4.9-argon-high", "env")
    assert pin.provenance["resolved_model"] == "gemini-4-argon-medium"
    assert "env_override_refused" not in pin.provenance


def test_agy_harness_literal_is_agy_family_enforced_even_fail_open(fixture_home, monkeypatch):
    for role, level in (("consultant_main", "high"), ("consultant_support", "medium"), ("arbiter", "high")):
        pin = sm.resolve(role, "agy", fail_open=False)           # no cache -> literal
        assert (pin.model, pin.provenance["source"]) == (f"gemini-4-argon-{level}", "harness_literal")
    monkeypatch.setattr(sm, "AGY_HARNESS_TEMPLATE", "gemini-3.1-pro-{level}")
    for fail_open in (False, True):
        with pytest.raises(sm.SeatModelError, match="agy family rule"):
            sm.resolve("consultant_main", "agy", fail_open=fail_open)


def test_agy_top_family_is_the_highest_numeric_version_at_the_roles_level(fixture_home):
    models = ["gemini-4.9-argon-high", "gemini-4.10-argon-high", "gemini-4-argon-medium",
              "gemini-4.9-argon-medium", "gemini-3.1-pro-high", "gemini-4.10-argon-low"]
    write_agy_cache(fixture_home, models)
    assert sm.resolve("consultant_main", "agy").model == "gemini-4.10-argon-high"     # 4.10 > 4.9
    assert sm.resolve("consultant_support", "agy").model == "gemini-4.9-argon-medium"  # level-specific
    write_agy_cache(fixture_home, models + ["gemini-5-argon-high"])
    assert sm.resolve("arbiter", "agy").model == "gemini-5-argon-high"               # 5 > 4.10


def test_agy_stale_cache_keeps_the_last_recorded_top(fixture_home):
    write_agy_cache(fixture_home, live_like_agy_models() + ["gemini-4.9-argon-high", "gemini-4.9-argon-medium"],
                    fetched_at=iso(NOW - 9 * DAY))
    write_tops(fixture_home, {"agy": "gemini-4-argon"})
    pin = sm.resolve("consultant_support", "agy")
    assert (pin.model, pin.provenance["roster_stale"]) == ("gemini-4-argon-medium", True)
    write_agy_cache(fixture_home, live_like_agy_models() + ["gemini-4.9-argon-high", "gemini-4.9-argon-medium"])
    assert sm.resolve("consultant_support", "agy").model == "gemini-4.9-argon-medium"   # CONTROL fresh


@pytest.mark.parametrize("raw", ["{", json.dumps({"schema": "agy-models.v2", "models": ["gemini-4.9-argon-high"]}),
                                 json.dumps({"schema": "agy-models.v1", "models": "gemini-4.9-argon-high"})])
def test_malformed_agy_cache_counts_as_no_roster(fixture_home, raw):
    (fixture_home / ".claude" / "state" / "agy-models.json").write_text(raw, encoding="utf-8")
    pin = sm.resolve("arbiter", "agy", fail_open=False)
    assert (pin.model, pin.provenance["source"]) == ("gemini-4-argon-high", "harness_literal")


def test_agy_freeze_not_listed_in_a_readable_cache_takes_the_failure_path(fixture_home):
    write_agy_cache(fixture_home, ["gemini-4-argon-high"])                   # no -medium listed
    write_pins(fixture_home, {"agy": "gemini-4-argon-high"})
    assert sm.resolve("consultant_main", "agy").provenance["source"] == "freeze"   # CONTROL: listed
    with pytest.raises(sm.SeatModelError, match="not listed"):
        sm.resolve("consultant_support", "agy", fail_open=False)
    # With no readable cache the freeze is accepted on the agy family rule alone.
    (fixture_home / ".claude" / "state" / "agy-models.json").unlink()
    pin = sm.resolve("consultant_support", "agy", fail_open=False)
    assert (pin.model, pin.provenance["source"]) == ("gemini-4-argon-medium", "freeze")


# --------------------------------------------------------------------------- #
# Freeze pins (I4, I13)
# --------------------------------------------------------------------------- #
def test_freeze_wins_for_top_selectors_but_not_for_the_sol_literal(fixture_home):
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {"codex": "gpt-5.6-terra"})
    for role in ("code_reviewer", "escalation"):
        pin = sm.resolve(role, "codex")
        assert (pin.model, pin.provenance["source"]) == ("gpt-5.6-terra", "freeze"), role
    # the astra reserve F8: a freeze no longer reaches the Sol literals (consultant_main, arbiter)
    for role in ("consultant_main", "arbiter"):
        pin = sm.resolve(role, "codex")
        assert (pin.model, pin.provenance["source"]) == (STD, "roster"), role
    support = sm.resolve("consultant_support", "codex")
    assert (support.model, support.provenance["source"]) == (CODEX_SUP, "roster")
    # CONTROL: remove the freeze -> TOP roles follow the roster again.
    (fixture_home / ".claude" / "state" / "seat-model-pins.json").unlink()
    assert sm.resolve("code_reviewer", "codex").model == "gpt-6-astra"


def test_the_stream3_freeze_shape_holds_sol_for_every_codex_top_role(fixture_home):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    write_pins(fixture_home, {"codex": "gpt-5.6-sol", "agy": "gemini-4-argon-high"})
    got = {(r, p): (pin.model, pin.effort, pin.provenance["source"])
           for r, rows in sm.ROLE_TABLE.items() for p in rows if p != "claude"
           for pin in [sm.resolve(r, p)]}
    assert got == {
        ("code_reviewer", "codex"): ("gpt-5.6-sol", "xhigh", "freeze"),
        ("consultant_main", "codex"): (STD, "xhigh", "roster"),          # the astra reserve F8
        ("consultant_main", "agy"): ("gemini-4-argon-high", None, "freeze"),
        ("consultant_support", "codex"): (CODEX_SUP, "medium", "roster"),
        ("consultant_support", "agy"): ("gemini-4-argon-medium", None, "freeze"),
        ("arbiter", "codex"): (STD, "xhigh", "roster"),                  # the astra reserve F8
        ("arbiter", "agy"): ("gemini-4-argon-high", None, "freeze"),
        ("escalation", "codex"): ("gpt-5.6-sol", "max", "freeze"),
    }


def test_agy_freeze_fixes_the_version_and_the_role_supplies_the_level(fixture_home):
    write_agy_cache(fixture_home, live_like_agy_models() + ["gemini-4.9-argon-high", "gemini-4.9-argon-medium"])
    write_pins(fixture_home, {"agy": "gemini-4-argon-high"})
    assert sm.resolve("consultant_main", "agy").model == "gemini-4-argon-high"
    assert sm.resolve("arbiter", "agy").model == "gemini-4-argon-high"
    support = sm.resolve("consultant_support", "agy")
    assert (support.model, support.provenance["source"]) == ("gemini-4-argon-medium", "freeze")
    write_pins(fixture_home, {"agy": "gemini-3.7-argon-low"})           # a low pin still serves -high for main
    assert sm.resolve("consultant_main", "agy").model == "gemini-3.7-argon-high"


@pytest.mark.parametrize("slug,why", [
    ("gpt-reserve", "visibility"),               # hidden
    ("gpt-not-in-roster", "not in the codex roster"),
    ("gpt-5.5", "max"),                          # effort unsupported for escalation
    ("gpt 5", "shell"),
])
def test_invalid_codex_freeze_takes_the_call_site_failure_path(fixture_home, slug, why):
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {"codex": slug})
    with pytest.raises(sm.SeatModelError, match=why):
        sm.resolve("escalation", "codex", fail_open=False)
    pin = sm.resolve("escalation", "codex", fail_open=True)
    assert (pin.model, pin.provenance["source"]) == ("gpt-6-astra", "harness_literal")
    assert why in pin.provenance["fallback_reason"]
    assert sm.resolve("consultant_support", "codex").model == CODEX_SUP   # the literal is unaffected


def test_codex_freeze_is_accepted_without_a_readable_roster(fixture_home):
    write_pins(fixture_home, {"codex": "gpt-5.6-sol"})
    pin = sm.resolve("code_reviewer", "codex", fail_open=False)
    assert (pin.model, pin.effort, pin.timeout, pin.provenance["source"]) == ("gpt-5.6-sol", "xhigh", 2400, "freeze")
    assert pin.provenance["roster_fetched_at"] is None


@pytest.mark.parametrize("raw", [
    "{not json",
    json.dumps({"schema": "seat-model-pins.v0", "pins": {"codex": {"top": "gpt-5.6-sol"}}}),
    json.dumps({"schema": "seat-model-pins.v1", "pins": ["gpt-5.6-sol"]}),
    json.dumps({"schema": "seat-model-pins.v1", "pins": {"codex": "gpt-5.6-sol"}}),
    json.dumps({"schema": "seat-model-pins.v1", "pins": {"codex": {"top": ""}}}),
    json.dumps({"schema": "seat-model-pins.v1", "pins": {"codex": {"top": None}}}),
    json.dumps({"schema": "seat-model-pins.v1", "pins": {"codex": None}}),
    json.dumps(["seat-model-pins.v1"]),
])
def test_malformed_freeze_is_never_silently_ignored(fixture_home, raw):
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {}, raw=raw)
    with pytest.raises(sm.SeatModelError, match="freeze"):
        sm.resolve("code_reviewer", "codex", fail_open=False)
    pin = sm.resolve("code_reviewer", "codex", fail_open=True)
    assert pin.provenance["source"] == "harness_literal"
    assert "freeze" in pin.provenance["fallback_reason"]
    # The literal selector does not consult the freeze at all.
    assert sm.resolve("consultant_support", "codex", fail_open=False).model == CODEX_SUP


def test_a_freeze_for_one_provider_does_not_touch_the_other(fixture_home):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    write_pins(fixture_home, {"agy": "gemini-3.6-argon-high"})
    assert sm.resolve("code_reviewer", "codex").provenance["source"] == "roster"
    write_pins(fixture_home, {"codex": "gpt-5.6-sol"})
    assert sm.resolve("consultant_main", "agy").provenance["source"] == "roster"


# --------------------------------------------------------------------------- #
# Env rules (§4.1.3, §4.4, m1)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("role,provider,downgrade", [
    ("code_reviewer", "claude", "haiku"),
    ("arbiter", "claude", SUPPORT),
    ("code_reviewer", "codex", "gpt-5.5"),
    ("escalation", "codex", "gpt-5.6-sol"),
    ("consultant_main", "agy", "gemini-3.6-argon-high"),
])
def test_protected_env_downgrade_is_refused_and_recorded(fixture_home, monkeypatch, role, provider, downgrade):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    resolved = sm.resolve(role, provider).model
    monkeypatch.setenv("SEAT_TEST_ENV", downgrade)
    pin = sm.resolve(role, provider, env_var="SEAT_TEST_ENV")
    assert pin.model == resolved != downgrade
    assert pin.provenance["source"] != "env"
    assert pin.provenance["env_override_refused"] == {
        "var": "SEAT_TEST_ENV", "value": downgrade, "reason": pin.provenance["env_override_refused"]["reason"]}
    assert "protected" in pin.provenance["env_override_refused"]["reason"]
    # CONTROL: the env value equal to the resolved model is accepted.
    monkeypatch.setenv("SEAT_TEST_ENV", resolved)
    equal = sm.resolve(role, provider, env_var="SEAT_TEST_ENV")
    assert (equal.model, equal.provenance["source"]) == (resolved, "env")
    assert "env_override_refused" not in equal.provenance


def test_protected_env_refusal_also_holds_under_a_freeze(fixture_home, monkeypatch):
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {"codex": "gpt-5.6-sol"})
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-6-astra")                  # an UPGRADE is refused too
    pin = sm.resolve("code_reviewer", "codex", env_var="SEAT_TEST_ENV")
    assert (pin.model, pin.provenance["source"]) == ("gpt-5.6-sol", "freeze")
    assert pin.provenance["env_override_refused"]["value"] == "gpt-6-astra"


def test_support_codex_env_is_accepted_only_when_roster_valid(fixture_home, monkeypatch):
    write_codex_roster(fixture_home)
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-5.5")
    ok = sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV")
    assert (ok.model, ok.effort, ok.provenance["source"], ok.provenance["resolved_model"]) == \
        ("gpt-5.5", "medium", "env", CODEX_SUP)
    assert ok.argv_fragment == ("-m", "gpt-5.5", "-c", "model_reasoning_effort=medium")
    for bad in ("gpt-not-listed", "gpt 5"):
        monkeypatch.setenv("SEAT_TEST_ENV", bad)
        refused = sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV")
        assert refused.model == CODEX_SUP
        assert refused.provenance["env_override_refused"]["value"] == bad
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-5.5")                      # legal model, illegal effort
    refused = sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV", effort="max")
    assert refused.model == CODEX_SUP
    (fixture_home / ".codex" / "models_cache.json").unlink()            # no roster -> cannot validate
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-5.5")
    assert sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV").provenance["env_override_refused"]


# --- #282 r13: support-seat env must not buy unmetered astra (plan K21, NARROWED by
#     fix round 1 F7 / plan K46: a non-listed entry is now refused outright) ---
def r13_codex_entries(*, ceiling=True):
    """p2 listed (astra-class), p3 hidden, sol p4 listed, a p4 listed tie, p7 listed.

    Fix round 1 F7 adds `gpt-fixture-hidden-low` (p8 HIDDEN, ranked BELOW the ceiling): the
    entry that separates the two independent refusals — it is refused by visibility alone,
    with nothing to say about rank."""
    entries = [
        entry("gpt-fixture-top", 2),
        entry("gpt-fixture-hidden", 3, visibility="hide"),
        entry("gpt-fixture-tie", 4),
        entry("gpt-fixture-low", 7),
        entry("gpt-fixture-hidden-low", 8, visibility="hide"),
    ]
    if ceiling:
        entries.insert(2, entry(CODEX_SUP, 4))
    return entries


def _support_env(monkeypatch, value, **kwargs):
    monkeypatch.setenv("SEAT_TEST_ENV", value)
    return sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV", **kwargs)


def test_r13_support_env_slug_ranked_above_sol_among_listed_entries_is_refused(fixture_home, monkeypatch):
    """A LISTED slug with a lower priority than gpt-5.6-sol is refused, reason named, and the
    seat stays on sol. CONTROLS on the same roster: sol itself, a lower-ranked slug and a
    priority tie are accepted (source env)."""
    write_codex_roster(fixture_home, r13_codex_entries())
    refused = _support_env(monkeypatch, "gpt-fixture-top")
    assert (refused.model, refused.provenance["source"]) == (CODEX_SUP, "roster")
    assert refused.argv_fragment == ("-m", CODEX_SUP, "-c", "model_reasoning_effort=medium")
    record = refused.provenance["env_override_refused"]
    assert (record["var"], record["value"]) == ("SEAT_TEST_ENV", "gpt-fixture-top")
    assert f"ranks above {CODEX_SUP} among listed roster entries" in record["reason"]
    for accepted in (CODEX_SUP, "gpt-fixture-low", "gpt-fixture-tie"):
        pin = _support_env(monkeypatch, accepted)
        assert (pin.model, pin.provenance["source"]) == (accepted, "env"), accepted
        assert "env_override_refused" not in pin.provenance, accepted


def test_fr1_f7_a_hidden_slug_ranked_above_sol_is_refused_by_the_ceiling(fixture_home, monkeypatch):
    """INVERTED by #282 fix round 1 F7 (plan K46 SUPERSEDES K21). Was
    `test_r13_a_hidden_slug_ranked_above_sol_is_not_refused_by_the_ceiling`, which asserted that the
    literal `visibility == "list"` predicate let a HIDDEN p3 entry — the live gpt-reserve's shape —
    through the ceiling. That is the finding: env could buy an unmetered astra-class model as long
    as the vendor hid it. It is now REFUSED, and the seat stays on sol.

    CONTROLS on the same roster: the listed p2 slug is still refused (the rank rule is untouched),
    and the listed p7 slug is still accepted (the refusal is not blanket)."""
    write_codex_roster(fixture_home, r13_codex_entries())
    refused = _support_env(monkeypatch, "gpt-fixture-hidden")
    assert (refused.model, refused.provenance["source"]) == (CODEX_SUP, "roster")
    record = refused.provenance["env_override_refused"]
    assert (record["var"], record["value"]) == ("SEAT_TEST_ENV", "gpt-fixture-hidden")
    assert "not a listed codex roster entry" in record["reason"] and "hide" in record["reason"]
    assert _support_env(monkeypatch, "gpt-fixture-top").provenance["env_override_refused"]
    assert _support_env(monkeypatch, "gpt-fixture-low").model == "gpt-fixture-low"


def test_fr1_f7_visibility_and_rank_are_two_independent_refusals(fixture_home, monkeypatch):
    """K46's two clauses, each proven ALONE by an entry the other cannot explain.

    (a) VISIBILITY: `gpt-fixture-hidden-low` is p8 — ranked BELOW the ceiling, so the rank clause
        has nothing to say about it — and is refused purely for being hidden. Read fail-closed:
        a MISSING visibility field and a nonsense value are refused the same way.
    (b) RANK, regardless of visibility: the listed p2 entry is refused on rank.

    CONTROLS (all unchanged by F7): the seat's own base, a p4 tie with sol, and a listed entry
    ranked below the ceiling are accepted; a LISTED entry with NO numeric priority is NOT refused
    by this rule (K46 leaves unranked entries alone)."""
    write_codex_roster(fixture_home, r13_codex_entries())
    hidden_low = _support_env(monkeypatch, "gpt-fixture-hidden-low")
    assert hidden_low.model == CODEX_SUP
    reason = hidden_low.provenance["env_override_refused"]["reason"]
    assert "not a listed codex roster entry" in reason and "ranks above" not in reason

    ranked = _support_env(monkeypatch, "gpt-fixture-top").provenance["env_override_refused"]["reason"]
    assert f"ranks above {CODEX_SUP}" in ranked

    # (a) fail-closed on anything that is not exactly "list"
    for odd in ({k: v for k, v in entry("gpt-fixture-odd", 9).items() if k != "visibility"},
                dict(entry("gpt-fixture-odd", 9), visibility="LIST"),
                dict(entry("gpt-fixture-odd", 9), visibility=None)):
        write_codex_roster(fixture_home, r13_codex_entries() + [odd])
        pin = _support_env(monkeypatch, "gpt-fixture-odd")
        assert pin.model == CODEX_SUP, odd.get("visibility", "<absent>")
        assert "not a listed codex roster entry" in pin.provenance["env_override_refused"]["reason"]

    # CONTROLS
    write_codex_roster(fixture_home, r13_codex_entries() + [entry("gpt-fixture-unranked", None)])
    for accepted in (CODEX_SUP, "gpt-fixture-tie", "gpt-fixture-low", "gpt-fixture-unranked"):
        pin = _support_env(monkeypatch, accepted)
        assert (pin.model, pin.provenance["source"]) == (accepted, "env"), accepted
        assert "env_override_refused" not in pin.provenance, accepted


def test_r13_without_a_listed_ranked_ceiling_every_non_base_slug_is_refused(fixture_home, monkeypatch):
    """CONTROL for the ceiling rule: sol removed from the roster -> nothing can be ranked against
    it, so the p7 slug (accepted while sol is listed) is refused; the seat's base is still
    accepted first. The literal itself is then a fail-open harness literal. A sol entry that is
    present but unranked (null priority) or hidden counts as no ceiling too."""
    write_codex_roster(fixture_home, r13_codex_entries(ceiling=False))
    refused = _support_env(monkeypatch, "gpt-fixture-low", fail_open=True)
    assert refused.model == CODEX_SUP
    assert CODEX_SUP in refused.provenance["env_override_refused"]["reason"]
    assert "not a listed, ranked" in refused.provenance["env_override_refused"]["reason"]
    base = _support_env(monkeypatch, CODEX_SUP, fail_open=True)
    assert (base.model, base.provenance["source"]) == (CODEX_SUP, "env")
    for sol in (entry(CODEX_SUP, None), entry(CODEX_SUP, 4, visibility="hide")):
        write_codex_roster(fixture_home, r13_codex_entries(ceiling=False) + [sol])
        pin = _support_env(monkeypatch, "gpt-fixture-low")
        assert pin.model == CODEX_SUP and "not a listed, ranked" in pin.provenance["env_override_refused"]["reason"]
    # CONTROL: the same slug with sol listed and ranked is accepted.
    write_codex_roster(fixture_home, r13_codex_entries())
    assert _support_env(monkeypatch, "gpt-fixture-low").model == "gpt-fixture-low"


def test_r13_unreadable_roster_keeps_refusing_and_a_sol_freeze_never_refuses_sol(fixture_home, monkeypatch):
    """An unreadable roster refuses a non-base slug (it cannot be validated or ranked). A pins file
    freezing codex on gpt-5.6-sol + env sol is accepted (raw == base). CONTROL: a protected role is
    unchanged — code_reviewer with env = the p7 slug is still refused AS PROTECTED.

    "Unreadable" is the ABSENT roster here: the sanctioned no-roster path, whose meaning #282 R4
    (a later work package) keeps, unlike a malformed file."""
    assert not (fixture_home / ".codex" / "models_cache.json").exists()
    refused = _support_env(monkeypatch, "gpt-fixture-low")
    assert refused.model == CODEX_SUP
    assert refused.provenance["env_override_refused"]["reason"] == "no readable codex roster to validate it against"

    write_codex_roster(fixture_home, r13_codex_entries())
    write_pins(fixture_home, {"codex": CODEX_SUP})
    frozen = _support_env(monkeypatch, CODEX_SUP)
    assert (frozen.model, frozen.provenance["source"]) == (CODEX_SUP, "env")
    assert "env_override_refused" not in frozen.provenance

    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-fixture-low")
    protected = sm.resolve("code_reviewer", "codex", env_var="SEAT_TEST_ENV")
    assert protected.model == CODEX_SUP               # the freeze holds the TOP seat
    assert "protected" in protected.provenance["env_override_refused"]["reason"]
    assert "ranks above" not in protected.provenance["env_override_refused"]["reason"]


def test_r13_emit_is_unaffected_by_the_ceiling(fixture_home, monkeypatch):
    """emit resolves with env_var None, so a planted env value changes nothing it prints."""
    write_codex_roster(fixture_home, r13_codex_entries() + [entry(STD, 9)])   # + the Sol literal rows' model
    before = sm.emit()
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-fixture-top")
    assert sm.emit() == before


def test_support_claude_env_accepts_vendor_aliases_only(fixture_home, monkeypatch):
    monkeypatch.setenv("SEAT_TEST_ENV", "sonnet")
    ok = sm.resolve("consultant_support", "claude", env_var="SEAT_TEST_ENV")
    assert (ok.model, ok.provenance["source"]) == ("sonnet", "env")
    monkeypatch.setenv("SEAT_TEST_ENV", "claude-3-opus; rm")
    refused = sm.resolve("consultant_support", "claude", env_var="SEAT_TEST_ENV")
    assert refused.model == SUPPORT
    assert refused.provenance["env_override_refused"]["value"] == "claude-3-opus; rm"


def test_env_layer_is_skipped_when_unnamed_unset_or_blank(fixture_home, monkeypatch):
    monkeypatch.setenv("SEAT_TEST_ENV", "haiku")
    assert sm.resolve("code_reviewer", "claude").provenance.get("env_override_refused") is None  # env_var None
    monkeypatch.delenv("SEAT_TEST_ENV")
    pin = sm.resolve("code_reviewer", "claude", env_var="SEAT_TEST_ENV")
    assert (pin.model, pin.provenance["source"]) == (MAIN, "harness_literal")
    monkeypatch.setenv("SEAT_TEST_ENV", "   ")
    assert "env_override_refused" not in sm.resolve("code_reviewer", "claude", env_var="SEAT_TEST_ENV").provenance


# --------------------------------------------------------------------------- #
# Provenance, quota state, the Claude adapter
# --------------------------------------------------------------------------- #
REQUIRED_PROVENANCE = {"requested_selector", "resolved_model", "source", "roster_fetched_at", "quota_state"}
OPTIONAL_PROVENANCE = {"roster_stale", "env_override_refused", "fallback_reason", "upgrade_followed",
                       "upgrade_ignored_reason", "unavailable_reason",
                       "frozen_slug",   # #282 r14: only under a freeze (test_r14_* below)
                       "tie_break", "tied_with",   # #282 R16: only on a tied codex selection (test_r16_* below)
                       "effort_override_refused"}  # #311: only when an env effort is refused


def test_provenance_carries_the_documented_keys_and_optional_keys_only_on_their_event(fixture_home):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    for role, rows in sm.ROLE_TABLE.items():
        for provider in rows:
            prov = sm.resolve(role, provider).provenance
            # #291: roster_rev rides on every resolution the roster DECIDES - each Claude row and
            # the codex std literal (consultant_support) - and on no roster-followed TOP pin.
            # The astra reserve (roster rev 4): every codex LITERAL row is roster-decided (consultant_support,
            # and the Sol rows consultant_main / arbiter).
            roster_decided = provider == "claude" or (provider == "codex" and sm.ROLE_TABLE[role]["codex"].kind == "literal")
            required = REQUIRED_PROVENANCE | ({"roster_rev"} if roster_decided else set()) \
                | ({"effort", "effort_source"} if provider == "claude" else set())   # #311
            assert required <= set(prov) <= required | OPTIONAL_PROVENANCE, (role, provider)
            assert set(prov) == required, (role, provider, prov)   # healthy: no optional keys
            if roster_decided:
                assert prov["roster_rev"] == model_roster.REVISION, (role, provider)
            assert prov["source"] in sm.SOURCES
    assert sm.resolve("code_reviewer", "codex").provenance["requested_selector"] == "TOP@xhigh"
    assert sm.resolve("escalation", "codex").provenance["requested_selector"] == "TOP@max"
    assert sm.resolve("arbiter", "codex").provenance["requested_selector"] == f"{STD}@xhigh"
    assert sm.resolve("consultant_support", "codex").provenance["requested_selector"] == f"{CODEX_SUP}@medium"
    assert sm.resolve("consultant_support", "agy").provenance["requested_selector"] == "TOP-argon-medium"
    assert sm.resolve("code_reviewer", "claude").provenance["requested_selector"] == MAIN


def test_quota_state_is_read_from_codex_quota_for_codex_pins_only(fixture_home, monkeypatch):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    calls = []

    def fake_snapshot(*, sessions_dir=None, now=None):
        calls.append(sessions_dir)
        return {"state": "fresh"}

    monkeypatch.setattr(codex_quota, "snapshot", fake_snapshot)
    assert sm.resolve("code_reviewer", "codex").provenance["quota_state"] == "fresh"
    assert calls == [fixture_home / ".codex" / "sessions"]
    assert sm.resolve("code_reviewer", "claude").provenance["quota_state"] is None
    assert sm.resolve("consultant_main", "agy").provenance["quota_state"] is None
    assert len(calls) == 1

    def raising(**_kw):
        raise RuntimeError("meter broke")

    monkeypatch.setattr(codex_quota, "snapshot", raising)
    pin = sm.resolve("code_reviewer", "codex")
    assert (pin.model, pin.provenance["quota_state"]) == ("gpt-6-astra", "unknown")


def test_quota_state_without_a_sessions_tree_is_unknown(fixture_home):
    write_codex_roster(fixture_home)
    assert sm.resolve("consultant_support", "codex").provenance["quota_state"] == "unknown"


def _uncertain_sessions(home, *, fifth_newer=True):
    """A sessions tree on the REAL clock (codex_quota's clock) that codex_quota reads as uncertain
    (#282 R6): of the four newest rollouts by mtime three hold no reading and the fourth a reading
    observed 15 minutes ago; a fifth, unread rollout was modified after that reading — or, with
    fifth_newer False, before it (the control: fresh)."""
    now = time.time()
    day_dir = home / ".codex" / "sessions" / datetime.fromtimestamp(now, timezone.utc).strftime("%Y/%m/%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    def touch(path, mtime):
        os.utime(path, (mtime, mtime))

    for i in range(3):
        blank = day_dir / f"rollout-blank-{i}.jsonl"
        blank.write_text('{"type": "session_meta"}\n', encoding="utf-8")
        touch(blank, now - 10 - i)
    observed = now - 900
    event = {"timestamp": iso_ms(observed), "type": "event_msg",
             "payload": {"type": "token_count", "rate_limits": {
                 "limit_id": "codex",
                 "primary": {"used_percent": 30.0, "window_minutes": 300, "resets_at": int(now + 7200)},
                 "secondary": {"used_percent": 10.0, "window_minutes": 10080, "resets_at": int(now + 259200)},
                 "rate_limit_reached_type": None}}}
    chosen = day_dir / "rollout-chosen.jsonl"
    chosen.write_text(json.dumps(event) + "\n", encoding="utf-8")
    touch(chosen, now - 20)
    fifth = day_dir / "rollout-fifth.jsonl"
    fifth.write_text('{"type": "session_meta"}\n', encoding="utf-8")
    touch(fifth, now - 100 if fifth_newer else observed - 60)


def test_emit_passes_an_uncertain_meter_through_as_quota_state_uncertain(fixture_home, monkeypatch):
    """#282 R6: seat_model._quota_state passes `uncertain` through (it used to map any state
    outside fresh / stale / unknown to unknown). #322 fix round 1: the fixture's unread candidate is built
    from reading-less rollouts, which the fixed walk reads, so it runs on the pre-fix walk (empty reads 0)."""
    monkeypatch.setattr(codex_quota, "ROLLOUT_EMPTY_READ_LIMIT", 0)
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    _uncertain_sessions(fixture_home)
    assert codex_quota.snapshot()["state"] == "uncertain"
    doc = sm.emit()
    states = {(role, provider): item["provenance"]["quota_state"]
              for role, provs in doc["pins"].items() for provider, item in provs.items()}
    assert {s for (_r, p), s in states.items() if p == "codex"} == {"uncertain"}
    assert {s for (_r, p), s in states.items() if p != "codex"} == {None}
    # CONTROL: the fifth rollout older than the reading -> the same tree is fresh.
    _uncertain_sessions(fixture_home, fifth_newer=False)
    assert sm.resolve("code_reviewer", "codex").provenance["quota_state"] == "fresh"


def test_claude_adapter_proposes_nothing(fixture_home, monkeypatch):
    write_codex_roster(fixture_home, [entry("gpt-7-nova", 0)] + live_like_codex_entries())
    write_pins(fixture_home, {"claude": "haiku", "codex": "gpt-5.6-sol"})
    write_tops(fixture_home, {"codex": "gpt-6-astra"})
    before = tree_snapshot(fixture_home)

    def forbidden(*_a, **_kw):
        raise AssertionError("the Claude adapter must not read rosters, pins, tops or the meter")

    monkeypatch.setattr(sm, "_read_json", forbidden)
    monkeypatch.setattr(codex_model, "load_roster_entries", forbidden)
    monkeypatch.setattr(codex_quota, "snapshot", forbidden)
    expected = {"code_reviewer": MAIN, "consultant_main": MAIN, "consultant_support": SUPPORT,
                "arbiter": MAIN, "escalation": MAIN}
    for role, alias in expected.items():
        effort = _claude_effort(role)                                           # #311 U3
        for fail_open in (False, True):
            pin = sm.resolve(role, "claude", fail_open=fail_open)
            assert (pin.model, pin.effort, pin.argv_fragment) == (alias, effort, ("--model", alias, "--effort", effort))
            assert (pin.provenance["effort"], pin.provenance["effort_source"]) == (effort, "harness_literal")
            assert pin.provenance["source"] == "harness_literal"
            assert pin.provenance["roster_fetched_at"] is None
    assert tree_snapshot(fixture_home) == before                         # wrote nothing, tops included


# --------------------------------------------------------------------------- #
# Writes: only seat-model-tops.json
# --------------------------------------------------------------------------- #
def test_resolver_mutates_no_config_file(fixture_home, tmp_path, monkeypatch):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    write_pins(fixture_home, {"agy": "gemini-4-argon-high"})
    sessions = fixture_home / ".codex" / "sessions" / "2026" / "09" / "14"
    sessions.mkdir(parents=True)
    (sessions / "rollout-2026-09-14T15-00-00-x.jsonl").write_text("{}\n", encoding="utf-8")
    (fixture_home / ".codex" / "config.toml").write_text('model = "gpt-5.6-sol"\n', encoding="utf-8")
    (fixture_home / ".claude" / "model-policy.yaml").write_text("version: 1\n", encoding="utf-8")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    (cwd / "marker").write_text("x", encoding="utf-8")
    monkeypatch.chdir(cwd)
    home_before, cwd_before = tree_snapshot(fixture_home), tree_snapshot(cwd)
    assert not tops_path(fixture_home).exists()

    monkeypatch.setenv("SEAT_TEST_ENV", "gemini-3.7-argon-high")
    for role, rows in sm.ROLE_TABLE.items():
        for provider in rows:
            for fail_open in (False, True):
                sm.resolve(role, provider, fail_open=fail_open)
                sm.resolve(role, provider, fail_open=fail_open, env_var="SEAT_TEST_ENV")
    sm.emit()

    home_after = tree_snapshot(fixture_home)
    changed = {k for k in set(home_before) | set(home_after) if home_before.get(k, 0) != home_after.get(k, 0)}
    assert changed == {os.path.join(".claude", "state", "seat-model-tops.json")}
    assert tree_snapshot(cwd) == cwd_before
    assert tops_path(fixture_home).exists()                             # CONTROL: the one sanctioned write happened


def test_tops_record_shape_and_change_detection(fixture_home, monkeypatch):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    sm.resolve("code_reviewer", "codex")
    sm.resolve("consultant_support", "agy")
    doc = read_tops(fixture_home)
    assert doc["schema"] == "seat-model-tops.v1"
    assert doc["tops"]["codex"] == {"top": "gpt-6-astra", "previous": None, "changed_at": None,
                                    "resolved_at": iso(NOW), "roster_fetched_at": iso_nanos(NOW - 3600)}
    assert doc["tops"]["agy"]["top"] == "gemini-4-argon"               # the version family, not the level
    # A change records the previous top and when it changed.
    entries = live_like_codex_entries() + [entry("gpt-7-nova", 0)]
    write_codex_roster(fixture_home, entries)
    monkeypatch.setattr(sm, "_now", lambda: NOW + 60)
    sm.resolve("escalation", "codex")
    codex = read_tops(fixture_home)["tops"]["codex"]
    assert (codex["top"], codex["previous"], codex["changed_at"], codex["resolved_at"]) == \
        ("gpt-7-nova", "gpt-6-astra", iso(NOW + 60), iso(NOW + 60))
    assert read_tops(fixture_home)["tops"]["agy"]["top"] == "gemini-4-argon"   # other provider kept
    # An unchanged top keeps previous/changed_at and refreshes resolved_at only.
    monkeypatch.setattr(sm, "_now", lambda: NOW + 120)
    sm.resolve("code_reviewer", "codex")
    codex = read_tops(fixture_home)["tops"]["codex"]
    assert (codex["previous"], codex["changed_at"], codex["resolved_at"]) == ("gpt-6-astra", iso(NOW + 60), iso(NOW + 120))


def test_a_freeze_is_recorded_as_the_resolved_top_so_activation_is_announced(fixture_home):
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {"codex": "gpt-5.6-sol"})
    sm.resolve("code_reviewer", "codex")
    assert read_tops(fixture_home)["tops"]["codex"]["top"] == "gpt-5.6-sol"
    (fixture_home / ".claude" / "state" / "seat-model-pins.json").unlink()      # activation
    sm.resolve("code_reviewer", "codex")
    codex = read_tops(fixture_home)["tops"]["codex"]
    assert (codex["top"], codex["previous"]) == ("gpt-6-astra", "gpt-5.6-sol")


def test_literal_claude_and_fallback_resolutions_record_no_top(fixture_home):
    write_codex_roster(fixture_home)
    sm.resolve("consultant_support", "codex")
    sm.resolve("code_reviewer", "claude")
    assert not tops_path(fixture_home).exists()
    (fixture_home / ".codex" / "models_cache.json").unlink()
    sm.resolve("code_reviewer", "codex")                                       # harness literal
    sm.resolve("consultant_main", "agy")                                       # harness literal
    assert not tops_path(fixture_home).exists()
    write_codex_roster(fixture_home)                                           # CONTROL
    sm.resolve("code_reviewer", "codex")
    assert tops_path(fixture_home).exists()


def test_fail_open_failure_paths_record_no_top(fixture_home):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    write_pins(fixture_home, {"codex": "gpt-reserve", "agy": "claude-sonnet-4-6"})   # both invalid
    assert sm.resolve("code_reviewer", "codex", fail_open=True).provenance["source"] == "harness_literal"
    assert sm.resolve("consultant_main", "agy", fail_open=True).provenance["source"] == "harness_literal"
    assert not tops_path(fixture_home).exists()
    (fixture_home / ".claude" / "state" / "seat-model-pins.json").unlink()
    write_codex_roster(fixture_home, [entry("gpt-hidden", 1, visibility="hide")])      # no eligible
    assert sm.resolve("arbiter", "codex", fail_open=True).provenance["source"] == "harness_literal"
    write_agy_cache(fixture_home, list(FORBIDDEN_AGY))                               # no eligible
    assert sm.resolve("arbiter", "agy", fail_open=True).provenance["source"] == "harness_literal"
    assert not tops_path(fixture_home).exists()


def test_a_tops_write_failure_never_changes_the_resolution(fixture_home, monkeypatch):
    write_codex_roster(fixture_home)
    expected = sm.resolve("code_reviewer", "codex")
    tops_path(fixture_home).unlink()

    def boom(*_a, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr(sm.os, "replace", boom)
    pin = sm.resolve("code_reviewer", "codex")
    assert (pin.model, pin.effort, pin.timeout, pin.argv_fragment) == \
        (expected.model, expected.effort, expected.timeout, expected.argv_fragment)
    assert not tops_path(fixture_home).exists()
    assert sorted(p.name for p in (fixture_home / ".claude" / "state").iterdir()) == []   # no temp residue


def test_a_corrupt_tops_record_is_replaced_not_fatal(fixture_home):
    write_codex_roster(fixture_home)
    tops_path(fixture_home).write_text("{corrupt", encoding="utf-8")
    assert sm.resolve("code_reviewer", "codex").model == "gpt-6-astra"
    assert read_tops(fixture_home)["tops"]["codex"]["top"] == "gpt-6-astra"


# --------------------------------------------------------------------------- #
# Trust: no cwd, no project file, no smart-config, no network, no subprocess
# --------------------------------------------------------------------------- #
def test_a_poisoned_working_directory_changes_nothing(fixture_home, tmp_path, monkeypatch):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    baseline = {(r, p): sm.resolve(r, p).model for r, rows in sm.ROLE_TABLE.items() for p in rows}
    poisoned = tmp_path / "poisoned"
    (poisoned / ".claude" / "state").mkdir(parents=True)
    (poisoned / ".codex").mkdir(parents=True)
    (poisoned / ".claude" / "model-policy.yaml").write_text(
        "version: 1\ntiers:\n  complex:\n    claude-code: haiku\n", encoding="utf-8")
    (poisoned / ".claude" / "state" / "seat-model-pins.json").write_text(json.dumps(
        {"schema": "seat-model-pins.v1", "pins": {"codex": {"top": "gpt-5.5"}, "agy": {"top": "gemini-3.6-argon-low"}}}),
        encoding="utf-8")
    (poisoned / ".codex" / "models_cache.json").write_text(json.dumps(
        {"fetched_at": iso(NOW), "models": [entry("gpt-poison", 0)]}), encoding="utf-8")
    monkeypatch.chdir(poisoned)

    def no_cwd():
        raise AssertionError("seat_model must not read the working directory")

    monkeypatch.setattr(os, "getcwd", no_cwd)
    after = {(r, p): sm.resolve(r, p).model for r, rows in sm.ROLE_TABLE.items() for p in rows}
    assert after == baseline
    # CONTROL: the same pins file placed in the fixture HOME does change the answer.
    monkeypatch.undo()
    monkeypatch.setenv("HOME", str(fixture_home))
    monkeypatch.setenv("USERPROFILE", str(fixture_home))
    monkeypatch.setattr(sm, "_now", lambda: NOW)
    shutil.copy(poisoned / ".claude" / "state" / "seat-model-pins.json",
                fixture_home / ".claude" / "state" / "seat-model-pins.json")
    assert sm.resolve("code_reviewer", "codex").model == "gpt-5.5"


def test_emit_loads_no_smart_config_module(fixture_home, tmp_path):
    write_codex_roster(fixture_home)
    probe = textwrap.dedent(f"""
        import json, sys
        sys.path.insert(0, {str(_META)!r})
        import seat_model
        seat_model.emit()
        loaded = sorted(name for name, mod in sys.modules.items()
                        if 'model_policy' in name
                        or 'smart-config' in str(getattr(mod, '__file__', '') or ''))
        print(json.dumps(loaded))
    """)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8",
                         env=env, cwd=str(tmp_path), timeout=60, stdin=subprocess.DEVNULL)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == []


def test_resolve_and_emit_use_no_socket_or_subprocess(fixture_home, monkeypatch):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    write_pins(fixture_home, {"codex": "gpt-5.6-sol"})
    sessions = fixture_home / ".codex" / "sessions" / "2026" / "09" / "14"
    sessions.mkdir(parents=True)
    (sessions / "rollout-2026-09-14T15-00-00-x.jsonl").write_text("{}\n", encoding="utf-8")

    def forbidden(*_a, **_kw):
        raise AssertionError("no socket or subprocess inside seat_model resolution")

    for mod, name in ((socket, "socket"), (socket, "create_connection"), (subprocess, "run"),
                      (subprocess, "Popen"), (subprocess, "check_output"), (os, "system"), (os, "popen")):
        monkeypatch.setattr(mod, name, forbidden)
    for role, rows in sm.ROLE_TABLE.items():
        for provider in rows:
            sm.resolve(role, provider)
    assert set(sm.emit()["pins"]) == set(sm.ROLES)


def test_module_imports_no_network_or_process_library():
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"socket", "subprocess", "urllib", "http", "requests", "fcntl", "model_policy"}


# --------------------------------------------------------------------------- #
# emit()
# --------------------------------------------------------------------------- #
def test_emit_lists_every_pin_with_provenance(fixture_home):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    doc = sm.emit()
    assert doc["schema"] == "seat-model-emit.v1"
    assert {(r, p) for r, provs in doc["pins"].items() for p in provs} == \
        {(r, p) for r, rows in sm.ROLE_TABLE.items() for p in rows}
    item = doc["pins"]["code_reviewer"]["codex"]
    assert set(item) == {"model", "effort", "timeout", "argv_fragment", "provenance"}
    assert item["argv_fragment"] == ["-m", "gpt-6-astra", "-c", "model_reasoning_effort=xhigh"]
    json.dumps(doc)                                                      # JSON-serialisable


def test_emit_is_fail_closed_on_any_pin(fixture_home):
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {"agy": "gemini-3.1-pro-high"})
    with pytest.raises(sm.SeatModelError):
        sm.emit()


# --------------------------------------------------------------------------- #
# CLI (fail-closed: any failure -> non-zero AND empty stdout)
# --------------------------------------------------------------------------- #
def test_cli_argv_codex_prints_the_pinned_fragment(fixture_home):
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {"codex": "gpt-5.6-sol"})
    out = run_cli(["argv", "--role", "escalation", "--provider", "codex"])
    assert (out.returncode, out.stdout) == (0, "-m gpt-5.6-sol -c model_reasoning_effort=max\n")
    out = run_cli(["argv", "--role", "consultant_support", "--provider", "codex"])
    assert out.stdout == f"-m {CODEX_SUP} -c model_reasoning_effort=medium\n"


def test_cli_argv_agy_prints_the_model_flag(fixture_home):
    write_agy_cache(fixture_home)
    out = run_cli(["argv", "--role", "consultant_support", "--provider", "agy"])
    assert (out.returncode, out.stdout) == (0, "--model gemini-4-argon-medium\n")


def test_cli_model_prints_the_claude_alias(fixture_home):
    out = run_cli(["model", "--role", "code_reviewer", "--provider", "claude"])
    assert (out.returncode, out.stdout) == (0, f"{MAIN}\n")
    out = run_cli(["model", "--role", "consultant_support", "--provider", "claude"])
    assert out.stdout == f"{SUPPORT}\n"


def test_cli_emit_json_prints_every_pin(fixture_home):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    out = run_cli(["emit", "--json"])
    assert out.returncode == 0, out.stderr
    doc = json.loads(out.stdout)
    assert doc["pins"]["arbiter"]["agy"]["model"] == "gemini-4-argon-high"
    assert doc["pins"]["consultant_support"]["claude"]["model"] == SUPPORT


@pytest.mark.parametrize("args,setup", [
    (["argv", "--role", "code_reviewer", "--provider", "codex"], "invalid_codex_freeze"),
    (["argv", "--role", "consultant_main", "--provider", "agy"], "forbidden_agy_freeze"),
    (["argv", "--role", "code_reviewer", "--provider", "agy"], None),          # missing row
    (["argv", "--role", "code_reviewer", "--provider", "claude"], None),       # argv is codex/agy only
    (["model", "--role", "code_reviewer", "--provider", "codex"], None),       # model is claude only
    (["argv", "--role", "execution", "--provider", "codex"], None),
    (["emit", "--json"], "forbidden_agy_freeze"),
    (["emit"], None),
    ([], None),
    (["resolve", "--role", "code_reviewer"], None),
    (["argv", "--help"], None),
    (["argv", "--role", "code_reviewer", "--provider", "codex", "--effort", "max"], None),
])
def test_cli_failure_means_nonzero_exit_and_empty_stdout(fixture_home, args, setup):
    write_codex_roster(fixture_home)
    if setup == "invalid_codex_freeze":
        write_pins(fixture_home, {"codex": "gpt-reserve"})
    elif setup == "forbidden_agy_freeze":
        write_pins(fixture_home, {"agy": "claude-sonnet-4-6"})
    out = run_cli(args)
    assert out.returncode != 0
    assert out.stdout == ""
    assert out.stderr.strip()


def test_cli_succeeds_for_the_control_of_the_failure_cases(fixture_home):
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {"codex": "gpt-5.6-sol", "agy": "gemini-4-argon-high"})
    for args in (["argv", "--role", "code_reviewer", "--provider", "codex"],
                 ["argv", "--role", "consultant_main", "--provider", "agy"],
                 ["model", "--role", "code_reviewer", "--provider", "claude"],
                 ["emit", "--json"]):
        out = run_cli(args)
        assert out.returncode == 0 and out.stdout, (args, out.stderr)


@pytest.mark.parametrize("fragment,model", [(("-m", "gpt 6;rm", "-c", "model_reasoning_effort=xhigh"), "fable"),
                                            (("--model", "$(boom)"), "fable"),
                                            (("-m", "gpt-6-astra"), "fa ble")])
def test_cli_refuses_to_print_an_unsafe_shell_token(fixture_home, monkeypatch, capsys, fragment, model):
    """Defence in depth: even a resolver bug cannot put a shell metacharacter into `$PIN`."""
    fake = sm.SeatPin(model=model, effort="xhigh", timeout=600, argv_fragment=fragment, provenance={})
    monkeypatch.setattr(sm, "resolve", lambda *a, **kw: fake)
    provider_args = (["argv", "--role", "code_reviewer", "--provider", "codex"] if model == "fable"
                     else ["model", "--role", "code_reviewer", "--provider", "claude"])
    assert sm.main(provider_args) == sm.EXIT_RESOLUTION_FAILED
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unsafe" in captured.err
    # CONTROL: a safe fragment prints.
    safe = sm.SeatPin(model="fable", effort="xhigh", timeout=600,
                      argv_fragment=("-m", "gpt-6-astra", "-c", "model_reasoning_effort=xhigh"), provenance={})
    monkeypatch.setattr(sm, "resolve", lambda *a, **kw: safe)
    assert sm.main(provider_args) == sm.EXIT_OK
    assert capsys.readouterr().out.strip()


def test_cli_output_is_ascii(fixture_home):
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {}, raw=json.dumps({"schema": "seat-model-pins.v1",
                                                 "pins": {"codex": {"top": "gpt-5.6-sol", "reason": "§ 7"}}}))
    out = run_cli(["emit", "--json"])
    assert out.returncode == 0
    out.stdout.encode("ascii")


# --------------------------------------------------------------------------- #
# Argv shape with stub binaries (design §11 Argv shape)
# --------------------------------------------------------------------------- #
STUB = """#!/bin/sh
printf '%s\\n' "$@" > "$STUB_RECORD"
cat > /dev/null
printf 'eof\\n' > "$STUB_RECORD.eof"
"""


def _stub_env(tmp_path, name):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / name
    stub.write_text(STUB, encoding="utf-8")
    stub.chmod(0o755)
    record = tmp_path / f"{name}.argv"
    env = dict(os.environ)
    env.update(PATH=f"{bindir}{os.pathsep}{env.get('PATH', '')}", STUB_RECORD=str(record),
               PYTHONDONTWRITEBYTECODE="1", SEAT_MODEL=str(_MODULE_PATH), PY=sys.executable)
    return env, record


def _bash(script, env, *, stdin=subprocess.DEVNULL, timeout=30):
    return subprocess.run(["bash", "-c", script], env=env, stdin=stdin, capture_output=True, text=True,
                          encoding="utf-8", timeout=timeout)


def _bash_stdin_held_open(script, env, *, timeout=30):
    """Run `script` with bash's stdin a pipe that is NEVER written or closed while it runs.

    `subprocess.run(stdin=PIPE)` closes the pipe at once (communicate), which would hand the
    stub an EOF for free and make a `< /dev/null` assertion vacuous. Here the only way the
    stub reaches EOF is the redirection inside the script itself.
    """
    proc = subprocess.Popen(["bash", "-c", script], env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    finally:
        proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", "replace")
        proc.stdout.close()
        proc.stderr.close()
    return code, stderr


def _recorded(record):
    return record.read_text(encoding="utf-8").splitlines()


@_POSIX_SHELL
@pytest.mark.parametrize("role,effort", [("code_reviewer", "xhigh"), ("consultant_main", "xhigh"),
                                         ("consultant_support", "medium"), ("arbiter", "xhigh"),
                                         ("escalation", "max")])
def test_codex_exec_with_the_argv_substitution_always_carries_m(fixture_home, tmp_path, role, effort):
    write_codex_roster(fixture_home)
    env, record = _stub_env(tmp_path, "codex")
    script = (f'PIN="$("$PY" "$SEAT_MODEL" argv --role {role} --provider codex)" && '
              f'timeout 5 codex exec -s read-only $PIN "PROMPT TEXT" < /dev/null')
    out = _bash(script, env)
    assert out.returncode == 0, out.stderr
    argv = _recorded(record)
    assert argv[0] == "exec"
    assert "-m" in argv and argv.index("-m") < argv.index("PROMPT TEXT")
    model = argv[argv.index("-m") + 1]
    # the astra reserve (roster rev 4): consultant_main and arbiter are the Sol literal
    assert model == {"consultant_support": CODEX_SUP, "consultant_main": STD, "arbiter": STD}.get(role, "gpt-6-astra")
    assert f"model_reasoning_effort={effort}" in argv
    assert argv[-1] == "PROMPT TEXT"
    assert (tmp_path / "codex.argv.eof").exists()


@_POSIX_SHELL
def test_codex_never_runs_when_the_pin_cannot_be_resolved(fixture_home, tmp_path):
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {"codex": "gpt-reserve"})                   # invalid freeze
    env, record = _stub_env(tmp_path, "codex")
    script = ('PIN="$("$PY" "$SEAT_MODEL" argv --role code_reviewer --provider codex)" && '
              'timeout 5 codex exec $PIN "PROMPT" < /dev/null')
    out = _bash(script, env)
    assert out.returncode != 0
    assert not record.exists()
    # CONTROL: a valid freeze lets the same script run the stub.
    write_pins(fixture_home, {"codex": "gpt-5.6-sol"})
    assert _bash(script, env).returncode == 0
    assert record.exists()


@_POSIX_SHELL
def test_unpinned_codex_stack_fails_the_same_assertion(fixture_home, tmp_path):
    """NEGATIVE CONTROL for the -m assertion itself."""
    env, record = _stub_env(tmp_path, "codex")
    assert _bash('timeout 5 codex exec -s read-only "PROMPT TEXT" < /dev/null', env).returncode == 0
    assert "-m" not in _recorded(record)


@_POSIX_SHELL
@pytest.mark.parametrize("role,level", [("consultant_main", "high"), ("consultant_support", "medium"),
                                        ("arbiter", "high")])
def test_agy_stub_receives_sandbox_and_model_before_p_prompt_last_stdin_at_eof(fixture_home, tmp_path, role, level):
    write_agy_cache(fixture_home)
    env, record = _stub_env(tmp_path, "agy")
    script = (f'AGY_MODEL="$("$PY" "$SEAT_MODEL" argv --role {role} --provider agy)" && '
              f'(d="$(mktemp -d)" && cd "$d" && timeout 5 agy --sandbox --mode plan $AGY_MODEL -p "PROMPT TEXT" < /dev/null)')
    started = time.monotonic()
    code, stderr = _bash_stdin_held_open(script, env)
    assert code == 0, stderr
    assert time.monotonic() - started < 5
    assert _recorded(record) == ["--sandbox", "--mode", "plan", "--model", f"gemini-4-argon-{level}",
                                 "-p", "PROMPT TEXT"]
    assert (tmp_path / "agy.argv.eof").exists()                         # stdin reached EOF


@_POSIX_SHELL
def test_agy_stub_blocks_when_stdin_is_not_closed(fixture_home, tmp_path):
    """NEGATIVE CONTROL: without `< /dev/null` the stub never sees EOF and timeout kills it."""
    write_agy_cache(fixture_home)
    env, record = _stub_env(tmp_path, "agy")
    script = ('AGY_MODEL="$("$PY" "$SEAT_MODEL" argv --role consultant_main --provider agy)" && '
              '(d="$(mktemp -d)" && cd "$d" && timeout 2 agy --sandbox --mode plan $AGY_MODEL -p "PROMPT TEXT")')
    code, _stderr = _bash_stdin_held_open(script, env)
    assert code == 124                                                   # timeout(1) fired
    assert record.exists()                                               # the stub did start
    assert not (tmp_path / "agy.argv.eof").exists()


# --------------------------------------------------------------------------- #
# Astra unavailable -> a Claude substitute (amendment 1 item 2 + item 7; J10, J11, J12)
# --------------------------------------------------------------------------- #
#: RE-POINTED by the astra reserve (roster rev 4): the codex TOP rows are code_reviewer and escalation only.
#: consultant_main and arbiter are Sol literals, still admitted and substituted (ADMITTED_ROLES), whose
#: own tests live in test_astra_reserve.py.
TOP_CODEX_ROLES = ("code_reviewer", "escalation")
SUBSTITUTION_ROW_KEYS = {"at", "kind", "cycle_id", "cycle_id_source", "cycle_id_file_age_s", "use", "substitute_for",
                         "requested_model", "served_model", "role", "reason", "snapshot_state", "primary", "weekly",
                         "prior_admitted_in_cycle",
                         "admission_id",  # RE-POINTED by #282 r10 (K12): always present, an id or null
                         # RE-POINTED by S081 revision 4 WP-A3 (design §2.1 "every row records
                         # size, size_source"): WHICH SIZE of call was refused, plus the `key`
                         # every row in the store now names its budget key by. `requested_by`
                         # is conditional (a user request only) and is not in this set.
                         "key", "size", "size_source"}


@pytest.fixture()
def project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    return root


@pytest.fixture()
def codex_cli(monkeypatch):
    """`shutil.which("codex")` answers from this fixture (J12), never from the host PATH.

    `state["present"] = False` makes the codex CLI absent; `state["calls"]` counts lookups.
    """
    state = {"present": True, "calls": 0}
    real_which = shutil.which

    def fake_which(name, *args, **kwargs):
        if name == "codex":
            state["calls"] += 1
            return "/fixture/bin/codex" if state["present"] else None
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", fake_which)
    return state


def iso_ms(epoch):
    dt = datetime.fromtimestamp(epoch, timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def write_rollout(home, primary, weekly, *, age=60.0, reached_type=None, primary_resets_in=None):
    """One codex rollout reading in the live shape under the fixture HOME, timed on the REAL
    clock (codex_quota's clock; seat_model's pinned `_now` is only the roster clock).
    `primary_resets_in` (#322): seconds from NOW to the primary reset (default: observed + 2 h)."""
    observed = time.time() - age
    day_dir = home / ".codex" / "sessions" / datetime.fromtimestamp(observed, timezone.utc).strftime("%Y/%m/%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    rate_limits = {
        "limit_id": "codex", "limit_name": None,
        "primary": {"used_percent": primary, "window_minutes": 300,
                    "resets_at": int(observed + 7200) if primary_resets_in is None
                    else int(time.time() + primary_resets_in)},
        "secondary": {"used_percent": weekly, "window_minutes": 10080, "resets_at": int(observed + 259200)},
        "credits": {"has_credits": False, "unlimited": False, "balance": "0"},
        "individual_limit": None, "plan_type": "plus", "rate_limit_reached_type": reached_type,
    }
    event = {"timestamp": iso_ms(observed), "type": "event_msg",
             "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 1, "output_tokens": 1}},
                         "rate_limits": rate_limits}}
    path = day_dir / "rollout-2026-09-14T15-00-00-fixture.jsonl"
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")
    return path


def store_path(project):
    return codex_quota.budget_path_for(project)


def store_rows(project):
    path = store_path(project)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def admit_rows(rows):
    return [r for r in rows if "admitted" in r]


def substitution_rows(rows):
    return [r for r in rows if r.get("kind") == "substitution"]


def cli(capsys, args):
    code = sm.main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def split_exit3(out):
    """#322: `argv --use` exit 3 is TWO byte-identical lines (reason, Claude model) and, on a quota
    refusal, key=value lines after them. Returns (the two lines as printed, {key: value} of the rest)."""
    lines = out.splitlines()
    head = "\n".join(lines[:2]) + "\n"
    tail = dict(line.split("=", 1) for line in lines[2:])
    return head, tail


def argv_use(role, use, project, *extra):
    return ["argv", "--role", role, "--provider", "codex", "--use", use, "--project-root", str(project), *extra]


def test_the_budget_store_used_by_these_tests_is_under_the_fixture_home(fixture_home, project):
    assert fixture_home in store_path(project).parents
    assert _REAL_HOME not in store_path(project).parents


def test_exit_codes_are_named_constants():
    assert (sm.EXIT_OK, sm.EXIT_RESOLUTION_FAILED, sm.EXIT_USAGE, sm.EXIT_SUBSTITUTE, sm.EXIT_SKIPPED) == \
        (0, 1, 2, 3, 10)
    assert (sm.UNAVAILABLE_NO_ELIGIBLE, sm.UNAVAILABLE_CLI_MISSING) == ("no_eligible_model", "cli_missing")


def test_every_reason_the_cli_substitutes_with_is_in_the_substitution_vocabulary():
    """Drift guard: a non-trial admit refusal or a plan-time check the CLI turns into exit 3
    must be recordable, or the substitution row would be refused as a caller bug."""
    admit_refusals = {"threshold", "budget_spent", "budget_store_unavailable",
                      codex_quota.UNAVAILABLE_RATE_LIMIT_REACHED, codex_quota.UNAVAILABLE_QUOTA_EXHAUSTED,
                      # EXTENDED by S081 rev 4 D21 fix round 1 (WP-X4, F7): the "-" cell refusal was
                      # missing from this hand list, which is how it crashed `argv --use` unnoticed.
                      codex_quota.REASON_CLASS_NOT_BUDGETED}
    plan_time = {sm.UNAVAILABLE_NO_ELIGIBLE, sm.UNAVAILABLE_CLI_MISSING}
    assert admit_refusals | plan_time <= codex_quota.SUBSTITUTION_REASONS


# --- Python API: no eligible TOP is told apart from a broken resolver -------------------- #
def test_no_eligible_top_raises_a_distinguishable_seat_model_error(fixture_home):
    write_codex_roster(fixture_home, [entry("gpt-hidden", 1, visibility="hide"), entry("gpt-no-api", 2, api=False)])
    with pytest.raises(sm.NoEligibleModelError, match="eligible") as info:
        sm.resolve("code_reviewer", "codex", fail_open=False)
    assert isinstance(info.value, sm.SeatModelError)                     # fail-closed callers still get SeatModelError
    assert info.value.unavailable_reason == "no_eligible_model"
    pin = sm.resolve("code_reviewer", "codex", fail_open=True)
    assert (pin.model, pin.provenance["source"]) == ("gpt-6-astra", "harness_literal")
    assert pin.provenance["unavailable_reason"] == "no_eligible_model"
    assert "eligible" in pin.provenance["fallback_reason"]
    # The stale-roster branch reaches the same selection and the same answer.
    write_codex_roster(fixture_home, [entry("gpt-hidden", 1, visibility="hide")], fetched_at=iso_nanos(NOW - 9 * DAY))
    with pytest.raises(sm.NoEligibleModelError):
        sm.resolve("escalation", "codex")


def test_an_unranked_only_roster_is_no_eligible_model_like_select_top_says(fixture_home):
    """The no-eligible check mirrors select_top's own rule: an entry without a numeric priority
    cannot be ranked, so a roster of only such entries has no eligible TOP."""
    write_codex_roster(fixture_home, [entry("gpt-unranked", None)])
    with pytest.raises(sm.NoEligibleModelError):
        sm.resolve("code_reviewer", "codex")
    write_codex_roster(fixture_home, [entry("gpt-unranked", None), entry("gpt-ranked", 5)])   # CONTROL
    assert sm.resolve("code_reviewer", "codex").model == "gpt-ranked"


@pytest.mark.parametrize("setup", ["no_roster", "invalid_freeze", "malformed_pins", "unsafe_roster_slug",
                                   "select_top_unreadable", "support_literal_unlisted"])
def test_only_a_roster_without_an_eligible_top_is_named_unavailable(fixture_home, monkeypatch, setup):
    role = "consultant_support" if setup == "support_literal_unlisted" else "code_reviewer"
    if setup != "no_roster":
        write_codex_roster(fixture_home)
    if setup == "invalid_freeze":
        write_pins(fixture_home, {"codex": "gpt-reserve"})
    elif setup == "malformed_pins":
        write_pins(fixture_home, {}, raw="{not json")
    elif setup == "unsafe_roster_slug":
        write_codex_roster(fixture_home, [entry("gpt 6", 1)])
    elif setup == "select_top_unreadable":
        # The roster that was loaded lists an eligible TOP; select_top failing for another
        # reason (e.g. the file vanished between reads) is a broken resolver, not "no eligible".
        def unreadable(effort, *, cache_path=None, incumbent=None):   # #282 R16: select_top's signature
            raise codex_model.CodexModelError("codex roster unreadable: [Errno 2] gone")
        monkeypatch.setattr(codex_model, "select_top", unreadable)
    elif setup == "support_literal_unlisted":
        write_codex_roster(fixture_home, [entry("gpt-6-astra", 1)])
    if setup == "no_roster":
        pin = sm.resolve(role, "codex", fail_open=False)                 # sanctioned harness literal, not a failure
        assert pin.provenance["source"] == "harness_literal"
        assert "unavailable_reason" not in pin.provenance
        return
    with pytest.raises(sm.SeatModelError) as info:
        sm.resolve(role, "codex", fail_open=False)
    assert not isinstance(info.value, sm.NoEligibleModelError), info.value
    pin = sm.resolve(role, "codex", fail_open=True)
    assert pin.provenance["source"] == "harness_literal"
    assert "unavailable_reason" not in pin.provenance


# --- Python API: substitute() ---------------------------------------------------------- #
@pytest.mark.parametrize("role,timeout", [("code_reviewer", 600), ("consultant_main", 600), ("arbiter", 1200),
                                          ("escalation", 1200)])
def test_substitute_returns_the_claude_row_and_records_one_row(fixture_home, project, role, timeout):
    claude = sm.resolve(role, "claude")
    pin = sm.substitute(role, "consult", "budget_spent", project_root=project, requested_model="gpt-6-astra")
    assert (pin.model, pin.effort, pin.timeout, pin.argv_fragment) == \
        (claude.model, _claude_effort(role), timeout,
         ("--model", claude.model, "--effort", _claude_effort(role)))   # #311: the main tier's effort
    assert pin.model == MAIN
    # RE-POINTED (S081 rev 4 WP-A2, D16): a substitution now also says WHICH SIZE was refused.
    # This caller passes none, so it records the back-compat default - `complex` / `default` -
    # which is exactly what an un-migrated call site must produce. Kept as a FULL-EQUALITY
    # assertion rather than loosened to a subset: the point of it is that nothing else crept in.
    assert pin.provenance == {**claude.provenance, "substitute_for": "codex", "substitution_reason": "budget_spent",
                              "requested_model": "gpt-6-astra", "row_written": True,
                              "size": "complex", "size_source": "default"}
    rows = store_rows(project)
    assert len(rows) == 1 and set(rows[0]) == SUBSTITUTION_ROW_KEYS
    assert (rows[0]["role"], rows[0]["use"], rows[0]["reason"], rows[0]["served_model"], rows[0]["requested_model"],
            rows[0]["cycle_id"], rows[0]["cycle_id_source"]) == \
        (role, "consult", "budget_spent", MAIN, "gpt-6-astra", codex_quota.cycle_id_for(project), "adhoc-nobase")


def test_substitute_keys_on_the_projects_cycle_id_unless_one_is_given(fixture_home, project):
    (project / ".forge").mkdir()
    (project / ".forge" / "cycle-id").write_text("cyc-from-forge\n", encoding="utf-8")
    sm.substitute("consultant_main", "challenger", "threshold", project_root=project)
    sm.substitute("consultant_main", "challenger", "threshold", project_root=project, cycle_id="explicit-7")
    rows = store_rows(project)
    assert [(r["cycle_id"], r["cycle_id_source"], r["requested_model"]) for r in rows] == \
        [("cyc-from-forge", "cycle-id", None), ("explicit-7", "explicit", None)]


def test_substitute_accepts_the_avengers_deliberation_use(fixture_home, project):
    pin = sm.substitute("consultant_main", "deliberation", "cli_missing", project_root=project)
    assert pin.model == MAIN
    assert store_rows(project)[0]["use"] == "deliberation"


@pytest.mark.parametrize("kwargs,match", [
    ({"role": "consultant_support"}, "budgeted codex seat"),     # RE-POINTED by the astra reserve F1 (role gate)
    ({"role": "execution"}, "unknown role"),
    ({"use": "trial"}, "trial"),
    ({"use": "bogus"}, "use"),
    ({"reason": "sol_was_busy"}, "reason"),
    ({"requested_model": "gpt 6"}, "requested_model"),
    ({"cycle_id": ""}, "cycle_id"),
    ({"project_root": None}, "project_root"),
])
def test_substitute_refuses_caller_bugs_and_records_nothing(fixture_home, project, kwargs, match):
    call = {"role": "code_reviewer", "use": "consult", "reason": "budget_spent", "project_root": project}
    call.update(kwargs)
    role, use, reason = call.pop("role"), call.pop("use"), call.pop("reason")
    with pytest.raises(sm.SeatModelError, match=match):
        sm.substitute(role, use, reason, **call)
    assert not (fixture_home / ".claude" / "projects").exists()


@pytest.mark.parametrize("case", ["non_top_role", "trial", "no_project_root", "poisoned_claude_row"])
def test_substitute_refuses_its_own_caller_bugs_before_reaching_the_budget_layer(fixture_home, project, monkeypatch,
                                                                                case):
    """seat_model's own guards fire first: a caller bug never reaches codex_quota (defence in
    depth - codex_quota would refuse most of these too, which is why the order is tested)."""
    def unreachable(*_a, **_kw):
        raise AssertionError("the budget layer was reached")

    monkeypatch.setattr(codex_quota, "record_substitution", unreachable)
    monkeypatch.setattr(codex_quota, "cycle_id_for", unreachable)
    role, use, root = "code_reviewer", "consult", project
    if case == "non_top_role":
        role = "consultant_support"
    elif case == "trial":
        use = "trial"
    elif case == "no_project_root":
        root = None
    else:
        real = sm._resolve_claude
        monkeypatch.setattr(sm, "_resolve_claude", lambda r, row, env, effort_env=None: sm.SeatPin(
            model="gpt-6-astra", effort=None, timeout=600, argv_fragment=("--model", "gpt-6-astra"),
            provenance=real(r, row, env).provenance))
    with pytest.raises(sm.SeatModelError):
        sm.substitute(role, use, "budget_spent", project_root=root)
    # CONTROL: a valid call does reach the budget layer.
    if case != "poisoned_claude_row":
        with pytest.raises(AssertionError, match="budget layer"):
            sm.substitute("code_reviewer", "consult", "budget_spent", project_root=project)


def test_substitute_never_serves_a_codex_model_even_if_the_claude_row_were_wrong(fixture_home, project, codex_cli,
                                                                                 capsys, monkeypatch):
    """Defence in depth for SOL NEVER: a poisoned Claude resolution is refused, not served."""
    write_codex_roster(fixture_home)
    assert cli(capsys, argv_use("code_reviewer", "consult", project, "--cycle-id", "c1"))[0] == sm.EXIT_OK
    real = sm._resolve_claude

    def poisoned(role, row, env_var, effort_env_var=None):
        pin = real(role, row, env_var)
        return sm.SeatPin(model="gpt-5.6-sol", effort=None, timeout=pin.timeout,
                          argv_fragment=("--model", "gpt-5.6-sol"), provenance=pin.provenance)

    monkeypatch.setattr(sm, "_resolve_claude", poisoned)
    with pytest.raises(sm.SeatModelError, match="gpt"):
        sm.substitute("code_reviewer", "consult", "budget_spent", project_root=project)
    code, out, _ = cli(capsys, argv_use("code_reviewer", "consult", project, "--cycle-id", "c1"))  # budget spent
    assert (code, out) == (sm.EXIT_RESOLUTION_FAILED, "")
    code, out, _ = cli(capsys, ["substitute", "--role", "code_reviewer", "--use", "consult", "--reason",
                                "budget_spent", "--project-root", str(project)])
    assert (code, out) == (sm.EXIT_RESOLUTION_FAILED, "")
    assert substitution_rows(store_rows(project)) == []


def test_a_budget_store_failure_never_blocks_the_substitute(fixture_home, project, codex_cli, capsys):
    write_codex_roster(fixture_home)
    (fixture_home / ".claude" / "projects").write_text("not a directory", encoding="utf-8")
    pin = sm.substitute("consultant_main", "consult", "budget_store_unavailable", project_root=project)
    assert (pin.model, pin.provenance["row_written"]) == (MAIN, False)
    assert pin.provenance["row_error"]
    # admit cannot record -> refused budget_store_unavailable -> the seat is still served by Claude.
    code, out, err = cli(capsys, argv_use("consultant_main", "consult", project))
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"budget_store_unavailable\n{MAIN}\n")
    assert "not recorded" in err
    code, out, _ = cli(capsys, ["substitute", "--role", "consultant_main", "--use", "consult", "--reason",
                                "timeout_twice", "--project-root", str(project)])
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"timeout_twice\n{MAIN}\n")
    # CONTROL: with a working store the same call is admitted and recorded.
    (fixture_home / ".claude" / "projects").unlink()
    assert cli(capsys, argv_use("consultant_main", "consult", project))[0] == sm.EXIT_OK
    assert len(admit_rows(store_rows(project))) == 1


# --- CLI exit-code contract (J10) ------------------------------------------------------ #
@pytest.mark.parametrize("use", ["consult", "challenger", "advisory_review", "diagnosis", "audit"])
@pytest.mark.parametrize("role", TOP_CODEX_ROLES)
def test_use_admitted_prints_the_unchanged_pin_and_exits_0(fixture_home, project, codex_cli, capsys, role, use):
    write_codex_roster(fixture_home)
    assert sm.main(["argv", "--role", role, "--provider", "codex"]) == sm.EXIT_OK
    plain = capsys.readouterr().out
    code, out, _ = cli(capsys, argv_use(role, use, project, "--cycle-id", "cyc-1"))
    assert (code, out) == (sm.EXIT_OK, plain)
    rows = store_rows(project)
    assert [(r["use"], r["admitted"], r["cycle_id"]) for r in rows] == [(use, True, "cyc-1")]
    assert substitution_rows(rows) == []
    assert codex_cli["calls"] == 1


def test_use_trial_admitted_prints_the_pin(fixture_home, project, codex_cli, capsys):
    write_codex_roster(fixture_home)
    write_rollout(fixture_home, 10, 10)
    code, out, _ = cli(capsys, argv_use("code_reviewer", "trial", project))
    assert (code, out) == (sm.EXIT_OK, "-m gpt-6-astra -c model_reasoning_effort=xhigh\n")


@pytest.mark.parametrize("role", TOP_CODEX_ROLES)
def test_budget_spent_exits_3_reason_on_line_1_and_the_claude_alias_on_line_2(fixture_home, project, codex_cli,
                                                                              capsys, role):
    write_codex_roster(fixture_home)
    code, out, _ = cli(capsys, argv_use(role, "consult", project, "--cycle-id", "cyc-1"))
    assert code == sm.EXIT_OK and out.startswith("-m gpt-6-astra ")     # CONTROL: admitted -> astra
    code, out, err = cli(capsys, argv_use(role, "consult", project, "--cycle-id", "cyc-1"))
    assert code == sm.EXIT_SUBSTITUTE
    assert out.splitlines() == ["budget_spent", sm.resolve(role, "claude").model]
    assert out == f"budget_spent\n{MAIN}\n"
    assert "budget_spent" in err and "fresh" in err
    rows = store_rows(project)
    assert [r["reason"] for r in admit_rows(rows)] == ["within_budget", "budget_spent"]
    subs = substitution_rows(rows)
    assert len(subs) == 1 and set(subs[0]) == SUBSTITUTION_ROW_KEYS
    assert (subs[0]["role"], subs[0]["use"], subs[0]["reason"], subs[0]["served_model"], subs[0]["requested_model"],
            subs[0]["substitute_for"], subs[0]["cycle_id"], subs[0]["prior_admitted_in_cycle"]) == \
        (role, "consult", "budget_spent", MAIN, "gpt-6-astra", "codex", "cyc-1", 1)


def test_diagnosis_budget_is_per_task_key(fixture_home, project, codex_cli, capsys):
    write_codex_roster(fixture_home)
    first = argv_use("escalation", "diagnosis", project, "--cycle-id", "c", "--task-key", "t1")
    assert cli(capsys, first)[0] == sm.EXIT_OK
    assert cli(capsys, first)[:2] == (sm.EXIT_SUBSTITUTE, f"budget_spent\n{MAIN}\n")
    other = argv_use("escalation", "diagnosis", project, "--cycle-id", "c", "--task-key", "t2")
    assert cli(capsys, other)[0] == sm.EXIT_OK                          # CONTROL: another task has its own budget


def test_322_a_fresh_high_reading_below_exhaustion_is_admitted(fixture_home, project, codex_cli, capsys):
    """INVERTED AND RENAMED by #322 (was test_fresh_threshold_exits_3_threshold): 80% (and 94%) admit and
    run codex; only a fresh >= 99% reading exits 3. No substitution row is written for an admission."""
    write_codex_roster(fixture_home)
    for primary in (80, 94):
        write_rollout(fixture_home, primary, 10)
        code, out, _ = cli(capsys, argv_use("consultant_main", "challenger", project, "--cycle-id", f"c{primary}"))
        assert (code, out.startswith("-m ")) == (sm.EXIT_OK, True), out
    assert substitution_rows(store_rows(project)) == []
    write_rollout(fixture_home, 99, 10)                                  # CONTROL: real exhaustion refuses
    code, out, _ = cli(capsys, argv_use("consultant_main", "challenger", project, "--cycle-id", "c99"))
    assert (code, split_exit3(out)[0]) == (sm.EXIT_SUBSTITUTE, f"quota_exhausted\n{MAIN}\n")


@pytest.mark.parametrize("use", ["consult", "audit"])
def test_fixture_rate_limit_reached_exits_3_rate_limit_reached(fixture_home, project, codex_cli, capsys, use):
    write_codex_roster(fixture_home)
    write_rollout(fixture_home, 20, 20, reached_type="primary")
    code, out, _ = cli(capsys, argv_use("code_reviewer", use, project, "--cycle-id", "c"))
    head, tail = split_exit3(out)                                        # RE-POINTED by #322: + the wait lines
    assert (code, head) == (sm.EXIT_SUBSTITUTE, f"rate_limit_reached\n{MAIN}\n")
    assert (tail["binding_window"], tail["wait_advice"]) == ("primary", "notify")
    rows = store_rows(project)
    assert [r.get("unavailable") for r in admit_rows(rows)] == ["rate_limit_reached"]
    assert [r["reason"] for r in substitution_rows(rows)] == ["rate_limit_reached"]
    write_rollout(fixture_home, 20, 20, reached_type=None)               # CONTROL: the type is null
    code, out, _ = cli(capsys, argv_use("code_reviewer", use, project, "--cycle-id", "c"))
    assert (code, out) == (sm.EXIT_OK, "-m gpt-6-astra -c model_reasoning_effort=xhigh\n")


def test_fresh_exhausted_window_exits_3_quota_exhausted_even_for_the_audit(fixture_home, project, codex_cli, capsys):
    write_codex_roster(fixture_home)
    write_rollout(fixture_home, 99, 20)
    code, out, _ = cli(capsys, argv_use("code_reviewer", "audit", project))
    head, tail = split_exit3(out)                                        # RE-POINTED by #322: + the wait lines
    assert (code, head) == (sm.EXIT_SUBSTITUTE, f"quota_exhausted\n{MAIN}\n")
    assert set(tail) == {"binding_window", "resets_at", "resets_in_s", "wait_advice"}
    write_rollout(fixture_home, 98, 20)                                  # CONTROL: the audit is never thresholded
    assert cli(capsys, argv_use("code_reviewer", "audit", project))[0] == sm.EXIT_OK


@pytest.mark.parametrize("use", ["consult", "audit"])
def test_codex_cli_missing_exits_3_cli_missing_and_writes_no_admit_row(fixture_home, project, codex_cli, capsys, use):
    write_codex_roster(fixture_home)
    codex_cli["present"] = False
    code, out, _ = cli(capsys, argv_use("code_reviewer", use, project, "--cycle-id", "c"))
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"cli_missing\n{MAIN}\n")
    rows = store_rows(project)
    assert admit_rows(rows) == []                                        # no admit: no budget spent on a missing CLI
    assert [(r["reason"], r["requested_model"]) for r in substitution_rows(rows)] == [("cli_missing", "gpt-6-astra")]
    codex_cli["present"] = True                                          # CONTROL
    assert cli(capsys, argv_use("code_reviewer", use, project, "--cycle-id", "c"))[0] == sm.EXIT_OK
    assert len(admit_rows(store_rows(project))) == 1


@pytest.mark.parametrize("role", ["code_reviewer", "escalation"])
def test_no_eligible_top_exits_3_no_eligible_model_and_writes_no_admit_row(fixture_home, project, codex_cli, capsys,
                                                                           role):
    write_codex_roster(fixture_home, [entry("gpt-hidden", 1, visibility="hide"), entry("gpt-no-api", 2, api=False)])
    code, out, _ = cli(capsys, argv_use(role, "consult", project))
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"no_eligible_model\n{MAIN}\n")
    rows = store_rows(project)
    assert admit_rows(rows) == []
    assert [(r["reason"], r["requested_model"]) for r in substitution_rows(rows)] == [("no_eligible_model", None)]
    assert codex_cli["calls"] == 0
    (fixture_home / ".codex" / "models_cache.json").unlink()             # CONTROL: no roster = sanctioned literal
    code, out, _ = cli(capsys, argv_use(role, "consult", project))
    assert code == sm.EXIT_OK and out.startswith("-m gpt-6-astra -c model_reasoning_effort=")


@pytest.mark.parametrize("setup", ["hidden_freeze", "unlisted_freeze", "malformed_pins", "select_top_unreadable"])
def test_a_broken_resolver_exits_1_with_empty_stdout_and_records_nothing(fixture_home, project, codex_cli, capsys,
                                                                         monkeypatch, setup):
    write_codex_roster(fixture_home)
    real_select_top = codex_model.select_top
    if setup == "hidden_freeze":
        write_pins(fixture_home, {"codex": "gpt-reserve"})
    elif setup == "unlisted_freeze":
        write_pins(fixture_home, {"codex": "gpt-not-in-roster"})
    elif setup == "malformed_pins":
        write_pins(fixture_home, {}, raw="{not json")
    else:
        def unreadable(effort, *, cache_path=None, incumbent=None):   # #282 R16: select_top's signature
            raise codex_model.CodexModelError("codex roster unreadable")
        monkeypatch.setattr(codex_model, "select_top", unreadable)
    code, out, err = cli(capsys, argv_use("code_reviewer", "consult", project))
    assert (code, out) == (sm.EXIT_RESOLUTION_FAILED, "")
    assert err.strip()
    assert not store_path(project).exists()                              # not a substitution; no budget touched
    assert codex_cli["calls"] == 0
    # CONTROL: the same seat with a healthy resolver is admitted and pinned.
    monkeypatch.setattr(codex_model, "select_top", real_select_top)
    if setup == "select_top_unreadable":
        expected = "-m gpt-6-astra -c model_reasoning_effort=xhigh\n"    # no freeze in this setup
    else:
        write_pins(fixture_home, {"codex": "gpt-5.6-sol"})
        expected = "-m gpt-5.6-sol -c model_reasoning_effort=xhigh\n"
    code, out, _ = cli(capsys, argv_use("code_reviewer", "consult", project))
    assert (code, out) == (sm.EXIT_OK, expected)


def test_trial_refused_exits_10_with_empty_stdout_and_no_substitution(fixture_home, project, codex_cli, capsys):
    write_codex_roster(fixture_home)
    expected_reasons = []
    for setup, reason in ((None, "trial_requires_fresh_snapshot"), ((50, 10, None), "trial_threshold"),
                          ((10, 10, "primary"), "rate_limit_reached")):
        if setup is not None:
            write_rollout(fixture_home, setup[0], setup[1], reached_type=setup[2])
        code, out, err = cli(capsys, argv_use("consultant_main", "trial", project))
        assert (code, out) == (sm.EXIT_SKIPPED, ""), reason
        assert "skipped" in err
        expected_reasons.append(reason)
        rows = store_rows(project)
        assert [(r["use"], r["admitted"], r["reason"]) for r in admit_rows(rows)] == \
            [("trial", False, why) for why in expected_reasons]         # the refusal row IS recorded
        assert substitution_rows(rows) == []                             # ... and nothing is substituted
    write_rollout(fixture_home, 10, 10)                                  # CONTROL: fresh and under the ceiling
    assert cli(capsys, argv_use("consultant_main", "trial", project))[0] == sm.EXIT_OK


@pytest.mark.parametrize("cause", ["cli_missing", "no_eligible_model"])
def test_trial_is_skipped_not_substituted_when_astra_cannot_run_at_all(fixture_home, project, codex_cli, capsys,
                                                                       cause):
    if cause == "cli_missing":
        write_codex_roster(fixture_home)
        codex_cli["present"] = False
    else:
        write_codex_roster(fixture_home, [entry("gpt-hidden", 1, visibility="hide")])
    code, out, err = cli(capsys, argv_use("code_reviewer", "trial", project))
    assert (code, out) == (sm.EXIT_SKIPPED, "")
    assert cause in err
    assert not store_path(project).exists()
    # CONTROL: a non-trial use in the same state IS substituted.
    assert cli(capsys, argv_use("code_reviewer", "consult", project))[:2] == (sm.EXIT_SUBSTITUTE,
                                                                               f"{cause}\n{MAIN}\n")


_USAGE_CASES = [
    ["argv", "--role", "consultant_main", "--provider", "agy", "--use", "consult"],
    ["argv", "--role", "consultant_support", "--provider", "codex", "--use", "consult"],
    # RE-POINTED by S081 revision 4 WP-A3: `--use deliberation` WAS a usage error, because
    # `deliberation` lived in SUBSTITUTION_USES but not in USES. Design §2.2 budgets it (the
    # avengers codex member seat, 1 seat per session), so it is now a legal admit-gated use —
    # asserted positively in test_a3_the_avengers_deliberation_use_is_now_admit_gated. `bogus`
    # below keeps the negative control: an unknown use is still a usage error.
    ["argv", "--role", "code_reviewer", "--provider", "codex", "--use", "bogus"],
    ["argv", "--role", "code_reviewer", "--provider", "codex", "--use"],
    ["argv", "--role", "code_reviewer", "--provider", "codex", "--use", "consult", "--task-key", "k"],
    ["argv", "--role", "escalation", "--provider", "codex", "--use", "diagnosis", "--task-key", " "],
    ["argv", "--role", "code_reviewer", "--provider", "codex", "--use", "consult", "--cycle-id", " "],
    ["argv", "--role", "code_reviewer", "--provider", "codex", "--use", "consult", "--project-root", ""],
    ["argv", "--role", "code_reviewer", "--provider", "codex", "--project-root", "PROJECT"],
    ["argv", "--role", "code_reviewer", "--provider", "codex", "--cycle-id", "cyc"],
    ["argv", "--role", "escalation", "--provider", "codex", "--task-key", "k"],
    ["substitute", "--role", "consultant_support", "--use", "consult", "--reason", "budget_spent"],
    ["substitute", "--role", "execution", "--use", "consult", "--reason", "budget_spent"],
    ["substitute", "--role", "code_reviewer", "--use", "bogus", "--reason", "budget_spent"],
    ["substitute", "--role", "code_reviewer", "--use", "consult", "--reason", "sol_was_busy"],
    ["substitute", "--role", "code_reviewer", "--use", "consult"],
    ["substitute", "--role", "code_reviewer", "--use", "consult", "--reason", "budget_spent", "--requested-model",
     "gpt 6"],
    ["substitute", "--role", "code_reviewer", "--use", "consult", "--reason", "budget_spent", "--requested-model",
     "g" * 129],
    ["substitute", "--role", "code_reviewer", "--use", "consult", "--reason", "budget_spent", "--cycle-id", ""],
    ["substitute", "--role", "code_reviewer", "--use", "consult", "--reason", "budget_spent", "--project-root", ""],
    ["substitute", "--role", "code_reviewer", "--provider", "codex", "--use", "consult", "--reason", "budget_spent"],
    ["substitute", "--help"],
]


@pytest.mark.parametrize("args", _USAGE_CASES, ids=[" ".join(a[:1] + a[2:3] + a[4:]) for a in _USAGE_CASES])
def test_use_and_substitute_usage_errors_exit_2_with_empty_stdout_and_no_rows(fixture_home, project, codex_cli, capsys,
                                                                             monkeypatch, args):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    monkeypatch.chdir(project)                                           # a usage bug that fell through would key here
    args = [str(project) if a == "PROJECT" else a for a in args]
    code, out, err = cli(capsys, args)
    assert (code, out) == (sm.EXIT_USAGE, ""), err
    assert err.strip()
    assert not (fixture_home / ".claude" / "projects").exists()
    assert codex_cli["calls"] == 0


def test_substitute_subcommand_exits_3_with_the_same_two_lines_and_records_one_row(fixture_home, project, codex_cli,
                                                                                  capsys):
    code, out, err = cli(capsys, ["substitute", "--role", "code_reviewer", "--use", "audit", "--reason",
                                  "timeout_twice", "--project-root", str(project), "--requested-model", "gpt-6-astra"])
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"timeout_twice\n{MAIN}\n")
    assert "timeout_twice" in err
    rows = store_rows(project)
    assert len(rows) == 1 and set(rows[0]) == SUBSTITUTION_ROW_KEYS
    assert (rows[0]["role"], rows[0]["use"], rows[0]["reason"], rows[0]["served_model"], rows[0]["requested_model"]) \
        == ("code_reviewer", "audit", "timeout_twice", MAIN, "gpt-6-astra")
    # The plan-time branch prints the same shape, so one parser serves both.
    write_codex_roster(fixture_home)
    codex_cli["present"] = False
    plan_time = cli(capsys, argv_use("code_reviewer", "audit", project))
    assert plan_time[0] == code
    assert [len(out.splitlines()), out.splitlines()[1]] == [len(plan_time[1].splitlines()),
                                                            plan_time[1].splitlines()[1]]
    assert codex_cli["calls"] == 1                                       # the subcommand itself looks up no binary
    # --use deliberation (the avengers seats, J16) and a cycle id of the caller's.
    code, out, _ = cli(capsys, ["substitute", "--role", "consultant_main", "--use", "deliberation", "--reason",
                                "cli_missing", "--project-root", str(project), "--cycle-id", "session-9"])
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"cli_missing\n{MAIN}\n")
    assert store_rows(project)[-1]["cycle_id"] == "session-9"
    # CONTROL for the --requested-model length usage case: 128 characters is recorded.
    code, _, _ = cli(capsys, ["substitute", "--role", "arbiter", "--use", "consult", "--reason", "threshold",
                              "--project-root", str(project), "--requested-model", "g" * 128])
    assert code == sm.EXIT_SUBSTITUTE and store_rows(project)[-1]["requested_model"] == "g" * 128


def test_substitute_reason_capacity_twice_is_accepted_and_bogus_is_a_usage_error(fixture_home, project):
    """#282 classifier vocabulary (i) + plan K9: `substitute --reason` choices derive from
    codex_quota.SUBSTITUTION_REASONS, so the forge block's `${ACT#substitute }` carries capacity_twice
    with no seat_model edit. The REAL CLI in a child process under the fixture HOME: exit 3, the usual
    two lines, one row. CONTROL: --reason bogus -> argparse usage error exit 2, no row."""
    assert "capacity_twice" in codex_quota.SUBSTITUTION_REASONS
    env = {"HOME": str(fixture_home), "USERPROFILE": str(fixture_home)}
    r = run_cli(["substitute", "--role", "code_reviewer", "--use", "audit", "--reason", "capacity_twice",
                 "--project-root", str(project), "--requested-model", "gpt-6-astra"], env_extra=env, cwd=project)
    assert (r.returncode, r.stdout) == (sm.EXIT_SUBSTITUTE, f"capacity_twice\n{MAIN}\n"), r.stderr
    rows = store_rows(project)
    assert [(row["kind"], row["reason"], row["use"]) for row in rows] == [("substitution", "capacity_twice", "audit")]
    assert fixture_home in store_path(project).parents
    bogus = run_cli(["substitute", "--role", "code_reviewer", "--use", "audit", "--reason", "bogus",
                     "--project-root", str(project)], env_extra=env, cwd=project)
    assert (bogus.returncode, bogus.stdout) == (sm.EXIT_USAGE, ""), bogus.stderr
    assert "invalid choice" in bogus.stderr and len(store_rows(project)) == 1


def test_substitute_trial_exits_10_and_records_nothing(fixture_home, project, codex_cli, capsys):
    code, out, err = cli(capsys, ["substitute", "--role", "consultant_main", "--use", "trial", "--reason", "threshold",
                                  "--project-root", str(project)])
    assert (code, out) == (sm.EXIT_SKIPPED, "")
    assert "skipped" in err
    assert not store_path(project).exists()


# --- SOL NEVER -------------------------------------------------------------------------- #
# D21 fix round 1 (m4): the budget class each case spends is HARD-CODED, never derived from
# sm.model_class_of (the function under test): astra is TOP, and gpt-5.6-sol is no roster tier
# since rev 3, so a freeze onto it is TOP too (the R1 control test above).
@pytest.mark.parametrize("freeze,spent_class", [(None, "top"), ("gpt-5.6-sol", "top")])
@pytest.mark.parametrize("role", TOP_CODEX_ROLES)
def test_line_2_is_the_claude_row_and_never_a_codex_model(fixture_home, project, codex_cli, capsys, role, freeze,
                                                          spent_class):
    if freeze is not None and freeze in (model_roster.CODEX_STD, getattr(model_roster, "CODEX_SUPPORT", None)):
        pytest.skip(f"{freeze} is a roster tier on this roster")
    write_codex_roster(fixture_home)
    if freeze is not None:
        write_pins(fixture_home, {"codex": freeze})
    top = freeze or "gpt-6-astra"                                        # no freeze: TOP astra; stream-3 freeze: sol
    admitted = cli(capsys, argv_use(role, "consult", project, "--cycle-id", "c1"))
    assert admitted[0] == sm.EXIT_OK and admitted[1].split()[1] == top   # CONTROL: the seat would use this model
    # RE-POINTED by S081 revision 4 WP-A3 (design §2.2, D16): the consult budget is keyed by
    # MODEL CLASS now, and a seat FROZEN to sol genuinely resolves to the std model, whose
    # limit is 2 rather than 1. The class's budget is spent out in full so this test still
    # provokes the `budget_spent` substitution it is actually about — SOL NEVER on line 2.
    assert admit_rows(store_rows(project))[-1]["model_class"] == spent_class
    for _ in range(codex_quota.BUDGET_LIMITS["consult"][spent_class] - 1):
        assert cli(capsys, argv_use(role, "consult", project, "--cycle-id", "c1"))[0] == sm.EXIT_OK
    outs = [cli(capsys, argv_use(role, "consult", project, "--cycle-id", "c1"))]           # budget_spent
    codex_cli["present"] = False
    outs.append(cli(capsys, argv_use(role, "challenger", project, "--cycle-id", "c2")))    # cli_missing
    codex_cli["present"] = True
    write_rollout(fixture_home, 10, 10, reached_type="primary")
    outs.append(cli(capsys, argv_use(role, "advisory_review", project, "--cycle-id", "c3")))  # rate_limit_reached
    outs.append(cli(capsys, ["substitute", "--role", role, "--use", "diagnosis", "--reason", "auth_failure",
                             "--project-root", str(project), "--requested-model", top]))
    claude = sm.resolve(role, "claude").model
    for code, out, _ in outs:
        assert code == sm.EXIT_SUBSTITUTE
        line2 = out.splitlines()[1]
        assert line2 == claude
        assert not line2.lower().startswith("gpt-")
    subs = substitution_rows(store_rows(project))
    assert len(subs) == 4
    assert {r["served_model"] for r in subs} == {claude}
    assert {r["requested_model"] for r in subs} == {top}


# --- Shell shape: `PIN="$(... --use U)" && codex exec $PIN` ----------------------------- #
COUNTING_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "$STUB_RECORD"
cat > /dev/null
"""


@_POSIX_SHELL
def test_the_shell_gate_runs_codex_only_on_exit_0(fixture_home, project, tmp_path):
    write_codex_roster(fixture_home)
    env, record = _stub_env(tmp_path, "codex")
    (tmp_path / "bin" / "codex").write_text(COUNTING_STUB, encoding="utf-8")   # counts every invocation
    env["PROJECT"] = str(project)

    def gate(role, use, extra=""):
        script = (f'PIN="$("$PY" "$SEAT_MODEL" argv --role {role} --provider codex --use {use} '
                  f'--project-root "$PROJECT" {extra})" && codex exec $PIN "PROMPT" < /dev/null')
        return _bash(script, env)

    def calls():
        return _recorded(record) if record.exists() else []

    first = gate("code_reviewer", "consult", "--cycle-id cyc-1")
    assert first.returncode == 0, first.stderr                           # CONTROL: exit 0 runs the pinned call
    assert calls() == ["exec -m gpt-6-astra -c model_reasoning_effort=xhigh PROMPT"]
    assert gate("code_reviewer", "consult", "--cycle-id cyc-1").returncode == sm.EXIT_SUBSTITUTE
    assert gate("code_reviewer", "trial").returncode == sm.EXIT_SKIPPED
    assert gate("consultant_support", "consult").returncode == sm.EXIT_USAGE
    write_pins(fixture_home, {"codex": "gpt-reserve"})
    assert gate("code_reviewer", "consult", "--cycle-id cyc-2").returncode == sm.EXIT_RESOLUTION_FAILED
    assert calls() == ["exec -m gpt-6-astra -c model_reasoning_effort=xhigh PROMPT"]   # nothing else ever ran


# --- Trust: the working directory only keys the budget (J11) --------------------------- #
@_POSIX_SHELL
def test_use_paths_read_the_working_directory_only_for_the_budget_key(fixture_home, tmp_path):
    write_codex_roster(fixture_home)
    env, _record = _stub_env(tmp_path, "codex")                          # a codex binary on PATH (J12)
    path_only = {"PATH": env["PATH"]}
    clean = tmp_path / "clean"
    clean.mkdir()
    poisoned = tmp_path / "poisoned"
    (poisoned / ".forge").mkdir(parents=True)
    (poisoned / ".forge" / "cycle-id").write_text("planted-cycle-7\n", encoding="utf-8")
    (poisoned / ".claude" / "state").mkdir(parents=True)
    (poisoned / ".claude" / "model-policy.yaml").write_text(
        "version: 1\ntiers:\n  complex:\n    claude-code: haiku\n", encoding="utf-8")
    (poisoned / ".claude" / "state" / "seat-model-pins.json").write_text(json.dumps(
        {"schema": "seat-model-pins.v1", "pins": {"codex": {"top": "gpt-5.5"}}}), encoding="utf-8")
    (poisoned / ".codex").mkdir()
    (poisoned / ".codex" / "models_cache.json").write_text(json.dumps(
        {"fetched_at": iso(NOW), "models": [entry("gpt-poison", 0)]}), encoding="utf-8")
    use = ["argv", "--role", "code_reviewer", "--provider", "codex", "--use", "consult"]

    baseline = run_cli(["argv", "--role", "code_reviewer", "--provider", "codex"], cwd=clean, env_extra=path_only)
    assert baseline.returncode == 0 and baseline.stdout == "-m gpt-6-astra -c model_reasoning_effort=xhigh\n"
    first = run_cli(use, cwd=poisoned, env_extra=path_only)              # no --project-root: the cwd is the default
    assert (first.returncode, first.stdout) == (0, baseline.stdout), first.stderr
    second = run_cli(use, cwd=poisoned, env_extra=path_only)
    assert (second.returncode, second.stdout) == (3, f"budget_spent\n{MAIN}\n"), second.stderr
    sub = run_cli(["substitute", "--role", "code_reviewer", "--use", "consult", "--reason", "threshold"],
                  cwd=poisoned, env_extra=path_only)
    assert (sub.returncode, sub.stdout) == (3, f"threshold\n{MAIN}\n")
    rows = store_rows(poisoned)
    assert [(r["cycle_id"], r["cycle_id_source"]) for r in rows] == [("planted-cycle-7", "cycle-id")] * 4
    # CONTROL: the cwd DOES change the budget key, and only that.
    (poisoned / ".forge" / "cycle-id").unlink()
    third = run_cli(use, cwd=poisoned, env_extra=path_only)
    assert (third.returncode, third.stdout) == (0, baseline.stdout)
    assert (store_rows(poisoned)[-1]["cycle_id"].startswith("adhoc-"),
            store_rows(poisoned)[-1]["cycle_id_source"]) == (True, "adhoc-nobase")


# --- Writes: the budget store, its lock and the tops record, nothing else (J11) -------- #
def test_use_and_substitute_write_only_the_budget_store_its_lock_and_the_tops_record(fixture_home, project, codex_cli,
                                                                                   capsys):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    rel_budget = os.path.relpath(store_path(project), fixture_home)
    rel_lock = rel_budget + ".lock"
    rel_tops = os.path.join(".claude", "state", "seat-model-tops.json")

    def changed_files(before, after):
        return {k for k in set(before) | set(after)
                if before.get(k, 0) != after.get(k, 0) and (before.get(k) is not None or after.get(k) is not None)}

    def new_dirs(before, after):
        return {k for k in after if after[k] is None and k not in before}

    project_before = tree_snapshot(project)
    before = tree_snapshot(fixture_home)
    assert sm.main(["argv", "--role", "code_reviewer", "--provider", "codex"]) == sm.EXIT_OK
    after = tree_snapshot(fixture_home)
    assert changed_files(before, after) == {rel_tops}                    # without --use: the tops record only
    assert new_dirs(before, after) == set()

    before = after
    assert sm.main(argv_use("code_reviewer", "consult", project, "--cycle-id", "c")) == sm.EXIT_OK
    assert sm.main(argv_use("code_reviewer", "consult", project, "--cycle-id", "c")) == sm.EXIT_SUBSTITUTE
    assert sm.main(["substitute", "--role", "arbiter", "--use", "audit", "--reason", "malformed_twice",
                    "--project-root", str(project)]) == sm.EXIT_SUBSTITUTE
    capsys.readouterr()
    after = tree_snapshot(fixture_home)
    changed = changed_files(before, after)
    assert changed <= {rel_budget, rel_lock, rel_tops}, changed
    assert rel_budget in changed                                         # CONTROL: the store was written
    ancestors = {os.path.relpath(p, fixture_home) for p in store_path(project).parents if fixture_home in p.parents}
    assert new_dirs(before, after) <= ancestors
    assert tree_snapshot(project) == project_before                      # the project tree is never written


def test_use_and_substitute_paths_use_no_socket_or_subprocess(fixture_home, project, codex_cli, capsys, monkeypatch):
    write_codex_roster(fixture_home)
    write_rollout(fixture_home, 10, 10)                                  # the meter really runs
    codex_quota.budget_path_for(project)                                 # slug helper loaded before the patch

    def forbidden(*_a, **_kw):
        raise AssertionError("no socket or subprocess on the --use / substitute paths")

    for mod, name in ((socket, "socket"), (socket, "create_connection"), (subprocess, "run"),
                      (subprocess, "Popen"), (subprocess, "check_output"), (os, "system"), (os, "popen")):
        monkeypatch.setattr(mod, name, forbidden)
    codes = [sm.main(argv_use("code_reviewer", "consult", project, "--cycle-id", "c")),
             sm.main(argv_use("code_reviewer", "consult", project, "--cycle-id", "c")),
             sm.main(argv_use("code_reviewer", "audit", project)),
             sm.main(argv_use("code_reviewer", "trial", project))]
    codex_cli["present"] = False
    codes.append(sm.main(argv_use("code_reviewer", "consult", project, "--cycle-id", "d")))
    codex_cli["present"] = True
    write_codex_roster(fixture_home, [entry("gpt-hidden", 1, visibility="hide")])
    codes.append(sm.main(argv_use("escalation", "consult", project, "--cycle-id", "e")))
    codes.append(sm.main(["substitute", "--role", "escalation", "--use", "diagnosis", "--reason", "auth_failure",
                          "--project-root", str(project)]))
    codes.append(sm.main(["substitute", "--role", "escalation", "--use", "trial", "--reason", "auth_failure",
                          "--project-root", str(project)]))
    capsys.readouterr()
    assert codes == [0, 3, 0, 0, 3, 3, 3, 10]


# --------------------------------------------------------------------------- #
# #282 r10 - a substituted audit names the admission it replaces (plan K12)
# --------------------------------------------------------------------------- #
def _is_admission_id(value):
    return isinstance(value, str) and len(value) == 32 and set(value) <= set("0123456789abcdef")


def test_r10_argv_use_audit_substitution_names_the_admit_row_it_replaces(fixture_home, project, codex_cli, capsys):
    """A fresh >= 99% reading: the audit is ADMITTED carrying `unavailable` and substituted before the call.
    The substitution row names the admit row's admission_id, so that audit is netted out of the TOP-call
    counts. CONTROL: a consult REFUSED on the same reading -> its substitution row names no admission."""
    write_codex_roster(fixture_home)
    write_rollout(fixture_home, 99, 20)
    code, out, _ = cli(capsys, argv_use("code_reviewer", "audit", project, "--cycle-id", "c"))
    assert (code, split_exit3(out)[0]) == (sm.EXIT_SUBSTITUTE, f"quota_exhausted\n{MAIN}\n")   # #322: + wait lines
    rows = store_rows(project)
    (admit,), (sub,) = admit_rows(rows), substitution_rows(rows)
    assert (admit["use"], admit["admitted"], admit["unavailable"]) == ("audit", True, "quota_exhausted")
    assert _is_admission_id(admit["admission_id"])
    assert (sub["admission_id"], sub["prior_admitted_in_cycle"]) == (admit["admission_id"], 0)
    assert codex_quota._count_admitted(store_path(project), "c", None, None) == 0

    code, out, _ = cli(capsys, argv_use("consultant_main", "consult", project, "--cycle-id", "c"))
    assert (code, split_exit3(out)[0]) == (sm.EXIT_SUBSTITUTE, f"quota_exhausted\n{MAIN}\n")
    rows = store_rows(project)
    refused, control = admit_rows(rows)[-1], substitution_rows(rows)[-1]
    assert (refused["use"], refused["admitted"]) == ("consult", False) and _is_admission_id(refused["admission_id"])
    assert (control["use"], control["admission_id"]) == ("consult", None)


@pytest.mark.parametrize("case", ["cli_missing", "no_eligible_model"])
def test_r10_a_plan_time_substitution_names_no_admission(fixture_home, project, codex_cli, capsys, case):
    if case == "cli_missing":
        write_codex_roster(fixture_home)
        codex_cli["present"] = False
    else:
        write_codex_roster(fixture_home, [entry("gpt-hidden", 1, visibility="hide")])
    code, out, _ = cli(capsys, argv_use("code_reviewer", "audit", project, "--cycle-id", "c"))
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"{case}\n{MAIN}\n")
    rows = store_rows(project)
    assert admit_rows(rows) == [] and [r["admission_id"] for r in substitution_rows(rows)] == [None]


def test_r10_an_admission_whose_row_was_not_written_is_not_named(fixture_home, project, codex_cli, capsys, monkeypatch):
    """A decision the store never took has no row a substitution could replace, so the substitution names
    none. CONTROL: the same admitted-with-`unavailable` decision with its row written is named."""
    write_codex_roster(fixture_home)
    write_rollout(fixture_home, 99, 20)
    real_admit = codex_quota.admit

    def admit_unwritten(*args, **kwargs):
        return dict(real_admit(*args, **kwargs), row_written=False)

    monkeypatch.setattr(codex_quota, "admit", admit_unwritten)
    code, out, _ = cli(capsys, argv_use("code_reviewer", "audit", project, "--cycle-id", "c"))
    assert (code, split_exit3(out)[0]) == (sm.EXIT_SUBSTITUTE, f"quota_exhausted\n{MAIN}\n")   # #322: + wait lines
    assert substitution_rows(store_rows(project))[-1]["admission_id"] is None
    monkeypatch.setattr(codex_quota, "admit", real_admit)
    assert cli(capsys, argv_use("code_reviewer", "audit", project, "--cycle-id", "c"))[0] == sm.EXIT_SUBSTITUTE
    rows = store_rows(project)
    assert substitution_rows(rows)[-1]["admission_id"] == admit_rows(rows)[-1]["admission_id"]
    assert _is_admission_id(admit_rows(rows)[-1]["admission_id"])


def test_r10_substitute_passes_the_admission_id_through_and_the_cli_is_unchanged(fixture_home, project, capsys):
    admission = "0123456789abcdef0123456789abcdef"
    pin = sm.substitute("code_reviewer", "audit", "timeout_twice", project_root=project, admission_id=admission)
    sm.substitute("code_reviewer", "audit", "timeout_twice", project_root=project)
    assert pin.model == MAIN and "admission_id" not in pin.provenance      # provenance keys unchanged
    assert [r["admission_id"] for r in store_rows(project)] == [admission, None]
    with pytest.raises(sm.SeatModelError, match="admission_id"):
        sm.substitute("code_reviewer", "audit", "timeout_twice", project_root=project, admission_id="NOT-AN-ID")
    assert len(store_rows(project)) == 2
    # K12: the `substitute` CLI gains no flag (a prose call site cannot learn the id).
    code, out, err = cli(capsys, ["substitute", "--role", "code_reviewer", "--use", "audit", "--reason",
                                  "timeout_twice", "--project-root", str(project), "--admission-id", admission])
    assert (code, out) == (sm.EXIT_USAGE, "") and "--admission-id" in err
    assert len(store_rows(project)) == 2


# =========================================================================== #
# #282 R4 (plan K14) — the codex roster's THREE states, handled distinctly
#
#   absent       no models_cache.json         sanctioned harness literal, both modes (unchanged)
#   invalid      unreadable / malformed /     fail-open: harness literal + fallback_reason +
#                wrong field types            `roster_invalid: true`; fail-closed: SeatModelError
#                                             (never NoEligibleModelError); CLI argv / emit exit 1
#   no_eligible  a valid roster with no       NoEligibleModelError / unavailable_reason (unchanged)
#                eligible TOP
#
# A freeze pin with an invalid roster is honoured unvalidated, exactly as with an absent roster,
# and records roster_invalid. agy rosters are untouched.
# =========================================================================== #
def _hidden_only_entries():
    return [entry("gpt-hidden", 1, visibility="hide"), entry("gpt-no-api", 2, api=False)]


R4_INVALID_ROSTERS = {
    "srl_true": lambda: json.dumps({"fetched_at": iso_nanos(NOW - 3600), "models": [
        dict(entry("gpt-6-astra", 1), supported_reasoning_levels=True)] + live_like_codex_entries()[1:]}),
    "not_json": lambda: "{not json",
    "non_dict_entry": lambda: json.dumps({"fetched_at": iso_nanos(NOW - 3600),
                                          "models": [7] + live_like_codex_entries()}),
    "string_priority": lambda: json.dumps({"fetched_at": iso_nanos(NOW - 3600), "models": [
        dict(entry("gpt-6-astra", 1), priority="1")] + live_like_codex_entries()[1:]}),
    "empty_models": lambda: json.dumps({"fetched_at": iso_nanos(NOW - 3600), "models": []}),
}


def _write_raw_roster(home, raw):
    (home / ".codex" / "models_cache.json").write_text(raw, encoding="utf-8")


@pytest.mark.parametrize("shape", sorted(R4_INVALID_ROSTERS))
@pytest.mark.parametrize("role,literal,effort", [("code_reviewer", "gpt-6-astra", "xhigh"),
                                                 ("escalation", "gpt-6-astra", "max"),
                                                 ("arbiter", STD, "xhigh"),      # the astra reserve: a Sol literal
                                                 ("consultant_support", CODEX_SUP, "medium")])
def test_r4_an_invalid_roster_is_a_recorded_literal_fail_open_and_an_error_fail_closed(fixture_home, shape, role,
                                                                                      literal, effort):
    _write_raw_roster(fixture_home, R4_INVALID_ROSTERS[shape]())
    with pytest.raises(sm.SeatModelError) as info:
        sm.resolve(role, "codex", fail_open=False)
    assert type(info.value) is sm.SeatModelError and not isinstance(info.value, sm.NoEligibleModelError)
    assert "roster_invalid" in str(info.value) and f"{role} x codex" in str(info.value)
    pin = sm.resolve(role, "codex", fail_open=True)
    assert (pin.model, pin.effort, pin.provenance["source"]) == (literal, effort, "harness_literal")
    assert pin.provenance["roster_invalid"] is True
    assert pin.provenance["fallback_reason"] and "unavailable_reason" not in pin.provenance
    assert pin.provenance["roster_fetched_at"] is None
    assert not tops_path(fixture_home).exists()                           # a literal is not evidence
    # CONTROL: a valid roster in the same HOME resolves from the roster and records no event key
    write_codex_roster(fixture_home)
    ok = sm.resolve(role, "codex", fail_open=False)
    assert ok.provenance["source"] == "roster" and "roster_invalid" not in ok.provenance


@pytest.mark.parametrize("fail_open", [False, True])
def test_r4_an_absent_roster_stays_the_sanctioned_literal_in_both_modes(fixture_home, fail_open):
    for role, literal in (("code_reviewer", "gpt-6-astra"), ("consultant_support", CODEX_SUP)):
        pin = sm.resolve(role, "codex", fail_open=fail_open)
        assert (pin.model, pin.provenance["source"]) == (literal, "harness_literal")
        assert "roster_invalid" not in pin.provenance and "unavailable_reason" not in pin.provenance
        assert "no codex roster" in pin.provenance["fallback_reason"]


def test_r4_no_eligible_stays_no_eligible_and_never_records_roster_invalid(fixture_home):
    write_codex_roster(fixture_home, _hidden_only_entries())
    with pytest.raises(sm.NoEligibleModelError):
        sm.resolve("code_reviewer", "codex", fail_open=False)
    pin = sm.resolve("code_reviewer", "codex", fail_open=True)
    assert pin.provenance["unavailable_reason"] == "no_eligible_model" and "roster_invalid" not in pin.provenance


@pytest.mark.parametrize("fail_open", [False, True])
def test_r4_a_freeze_with_an_invalid_roster_is_honoured_unvalidated_and_recorded(fixture_home, fail_open):
    write_pins(fixture_home, {"codex": "gpt-5.6-sol"})
    _write_raw_roster(fixture_home, R4_INVALID_ROSTERS["srl_true"]())
    pin = sm.resolve("code_reviewer", "codex", fail_open=fail_open)
    assert (pin.model, pin.provenance["source"], pin.provenance["roster_invalid"]) == ("gpt-5.6-sol", "freeze", True)
    assert read_tops(fixture_home)["tops"]["codex"]["top"] == "gpt-5.6-sol"   # a freeze is recorded, as when absent
    # CONTROL: the same freeze with an ABSENT roster is the same answer without the event key
    (fixture_home / ".codex" / "models_cache.json").unlink()
    absent = sm.resolve("code_reviewer", "codex", fail_open=fail_open)
    assert (absent.model, absent.provenance["source"]) == ("gpt-5.6-sol", "freeze")
    assert "roster_invalid" not in absent.provenance


def test_r4_the_agy_roster_is_untouched_by_an_invalid_codex_roster(fixture_home):
    write_agy_cache(fixture_home)
    _write_raw_roster(fixture_home, R4_INVALID_ROSTERS["srl_true"]())
    pin = sm.resolve("consultant_main", "agy", fail_open=False)
    assert (pin.model, pin.provenance["source"]) == ("gemini-4-argon-high", "roster")
    assert "roster_invalid" not in pin.provenance
    assert sm.resolve("code_reviewer", "claude").model == MAIN


@pytest.mark.parametrize("args", [["argv", "--role", "code_reviewer", "--provider", "codex"],
                                  ["argv", "--role", "consultant_support", "--provider", "codex"],
                                  ["emit", "--json"]])
def test_r4_cli_argv_and_emit_exit_1_with_empty_stdout_on_an_invalid_roster(fixture_home, args):
    write_agy_cache(fixture_home)
    _write_raw_roster(fixture_home, R4_INVALID_ROSTERS["srl_true"]())
    out = run_cli(args)
    assert (out.returncode, out.stdout) == (sm.EXIT_RESOLUTION_FAILED, "")
    assert "roster_invalid" in out.stderr and "Traceback" not in out.stderr
    # CONTROL: a valid roster -> exit 0, roster-sourced
    write_codex_roster(fixture_home)
    ok = run_cli(args)
    assert ok.returncode == 0 and ok.stdout, ok.stderr
    if args[0] == "emit":
        assert json.loads(ok.stdout)["pins"]["code_reviewer"]["codex"]["provenance"]["source"] == "roster"
    # `model` is Claude-only and reads no roster: unaffected by an invalid codex roster
    _write_raw_roster(fixture_home, R4_INVALID_ROSTERS["srl_true"]())
    assert run_cli(["model", "--role", "code_reviewer", "--provider", "claude"]).stdout == f"{MAIN}\n"


def test_r4_argv_use_on_an_invalid_roster_is_a_broken_resolver_that_records_nothing(fixture_home, project, codex_cli,
                                                                                  capsys):
    _write_raw_roster(fixture_home, R4_INVALID_ROSTERS["not_json"]())
    code, out, err = cli(capsys, argv_use("code_reviewer", "consult", project))
    assert (code, out) == (sm.EXIT_RESOLUTION_FAILED, "") and "roster_invalid" in err
    assert not store_path(project).exists() and codex_cli["calls"] == 0     # never a substitution, no admit
    write_codex_roster(fixture_home)                                      # CONTROL
    assert cli(capsys, argv_use("code_reviewer", "consult", project))[:2] == (
        sm.EXIT_OK, "-m gpt-6-astra -c model_reasoning_effort=xhigh\n")


def test_r4_a_roster_that_breaks_between_reads_is_a_broken_resolver_not_no_eligible(fixture_home, monkeypatch):
    """The loaded roster lists no eligible TOP, but select_top's own re-read finds the file invalid
    (it broke between the two reads): that is a broken resolver, never "astra unavailable"."""
    write_codex_roster(fixture_home, _hidden_only_entries())

    def broke(effort, *, cache_path=None, incumbent=None):   # #282 R16: select_top's signature
        raise codex_model.CodexRosterInvalidError(f"codex roster at {cache_path} is not valid JSON")

    monkeypatch.setattr(codex_model, "select_top", broke)
    with pytest.raises(sm.SeatModelError) as info:
        sm.resolve("code_reviewer", "codex", fail_open=False)
    assert not isinstance(info.value, sm.NoEligibleModelError)
    assert "unavailable_reason" not in sm.resolve("code_reviewer", "codex", fail_open=True).provenance
    monkeypatch.undo()                                                    # CONTROL: the real re-read
    monkeypatch.setenv("HOME", str(fixture_home))
    monkeypatch.setenv("USERPROFILE", str(fixture_home))
    monkeypatch.setattr(sm, "_now", lambda: NOW)
    with pytest.raises(sm.NoEligibleModelError):
        sm.resolve("code_reviewer", "codex", fail_open=False)


def test_r4_the_docstring_splits_absent_from_invalid_and_states_the_cli_consequence():
    doc = sm.__doc__
    assert "roster_invalid" in doc
    assert "absent" in doc and "invalid" in doc
    assert "exit 1" in doc


# =========================================================================== #
# #282 r14 (plan K16) — `frozen_slug`: the pins-file `top` AS WRITTEN, only when source is freeze
#
# convene persists each materialised seat's provenance (skills/avengers); a freeze is auditable there
# only if the pin says what the pins file held. It is an EVENT key: present exactly when the pin's
# FINAL `source` is "freeze" — an accepted env override or a fail-open harness literal is not a freeze.
# =========================================================================== #
R14_CODEX_TOP_ROLES = ("code_reviewer", "escalation")      # the astra reserve: the codex TOP rows


def test_r14_frozen_slug_is_the_pins_file_top_as_written_for_codex_and_agy(fixture_home):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    write_pins(fixture_home, {"codex": "gpt-5.6-sol", "agy": "gemini-3.7-argon-low"})
    assert sm.FROZEN_SLUG == "frozen_slug"
    for role in R14_CODEX_TOP_ROLES:
        prov = sm.resolve(role, "codex").provenance
        assert (prov["source"], prov[sm.FROZEN_SLUG], prov["resolved_model"]) == (
            "freeze", "gpt-5.6-sol", "gpt-5.6-sol"), role
    # agy: the freeze fixes the VERSION and the role supplies the level, so the slug as written differs from
    # the resolved model on every agy seat. frozen_slug is the pins file's value, never the pin's model.
    for role, level in (("consultant_main", "high"), ("consultant_support", "medium"), ("arbiter", "high")):
        pin = sm.resolve(role, "agy")
        assert (pin.model, pin.provenance["source"], pin.provenance[sm.FROZEN_SLUG]) == (
            f"gemini-3.7-argon-{level}", "freeze", "gemini-3.7-argon-low"), role
    # CONTROLS in the same HOME: rows that never read the freeze carry no key.
    assert sm.FROZEN_SLUG not in sm.resolve("consultant_support", "codex").provenance      # the sol literal
    for role in sm.ROLE_TABLE:
        assert sm.FROZEN_SLUG not in sm.resolve(role, "claude").provenance, role


@pytest.mark.parametrize("pins", ["no_pins_file", "empty_pins_table", "agy_only"])
def test_r14_no_freeze_means_no_frozen_slug(fixture_home, pins):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    if pins == "empty_pins_table":
        write_pins(fixture_home, {})
    elif pins == "agy_only":
        write_pins(fixture_home, {"agy": "gemini-4-argon-high"})
    for role, rows in sm.ROLE_TABLE.items():
        for provider in rows:
            prov = sm.resolve(role, provider).provenance
            if pins == "agy_only" and provider == "agy":
                # CONTROL: the freeze that does exist is recorded, so the absence elsewhere is not an accident
                assert (prov["source"], prov[sm.FROZEN_SLUG]) == ("freeze", "gemini-4-argon-high"), role
            else:
                assert sm.FROZEN_SLUG not in prov, (role, provider, prov)
                assert prov["source"] != "freeze", (role, provider)


def test_r14_frozen_slug_follows_the_final_source_not_the_pins_file(fixture_home, monkeypatch):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    write_pins(fixture_home, {"codex": "gpt-5.6-sol", "agy": "gemini-4-argon-high"})
    # (a) a protected seat's env EQUAL to the frozen model is accepted: source env -> no frozen_slug
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-5.6-sol")
    equal = sm.resolve("code_reviewer", "codex", env_var="SEAT_TEST_ENV")
    assert (equal.model, equal.provenance["source"]) == ("gpt-5.6-sol", "env")
    assert sm.FROZEN_SLUG not in equal.provenance
    # (b) a non-protected agy seat whose env slug is accepted over the freeze: source env -> no frozen_slug
    monkeypatch.setenv("SEAT_TEST_ENV", "gemini-3.6-argon-medium")
    agy_env = sm.resolve("consultant_support", "agy", env_var="SEAT_TEST_ENV")
    assert (agy_env.model, agy_env.provenance["source"]) == ("gemini-3.6-argon-medium", "env")
    assert sm.FROZEN_SLUG not in agy_env.provenance
    # CONTROL: a REFUSED env keeps the freeze, and the freeze is recorded beside the refusal
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-6-astra")
    refused = sm.resolve("code_reviewer", "codex", env_var="SEAT_TEST_ENV")
    assert (refused.model, refused.provenance["source"], refused.provenance[sm.FROZEN_SLUG]) == (
        "gpt-5.6-sol", "freeze", "gpt-5.6-sol")
    assert refused.provenance["env_override_refused"]["value"] == "gpt-6-astra"
    monkeypatch.delenv("SEAT_TEST_ENV")
    # (c) an INVALID freeze served fail-open is a harness literal, not a freeze: no frozen_slug
    write_pins(fixture_home, {"codex": "gpt-reserve", "agy": "gemini-3.1-pro-high"})
    for provider, role in (("codex", "escalation"), ("agy", "arbiter")):     # the codex TOP row / an agy row
        literal = sm.resolve(role, provider, fail_open=True)
        assert literal.provenance["source"] == "harness_literal", provider
        assert sm.FROZEN_SLUG not in literal.provenance, provider
        with pytest.raises(sm.SeatModelError):
            sm.resolve(role, provider, fail_open=False)


def test_r14_a_freeze_honoured_without_a_usable_roster_still_records_its_slug(fixture_home):
    write_pins(fixture_home, {"codex": "gpt-5.6-sol", "agy": "gemini-3.7-argon-low"})
    # absent rosters: both freezes are honoured unvalidated
    codex_absent = sm.resolve("code_reviewer", "codex", fail_open=False).provenance
    assert (codex_absent["source"], codex_absent[sm.FROZEN_SLUG], codex_absent["roster_fetched_at"]) == (
        "freeze", "gpt-5.6-sol", None)
    agy_absent = sm.resolve("consultant_main", "agy", fail_open=False)
    assert (agy_absent.model, agy_absent.provenance["source"], agy_absent.provenance[sm.FROZEN_SLUG]) == (
        "gemini-3.7-argon-high", "freeze", "gemini-3.7-argon-low")
    # an INVALID codex roster (R4): still honoured, recorded roster_invalid AND frozen_slug
    _write_raw_roster(fixture_home, R4_INVALID_ROSTERS["srl_true"]())
    invalid = sm.resolve("escalation", "codex", fail_open=False).provenance
    assert (invalid["source"], invalid[sm.FROZEN_SLUG], invalid[sm.ROSTER_INVALID]) == ("freeze", "gpt-5.6-sol", True)


def test_r14_emit_carries_frozen_slug_under_a_freeze_and_is_unchanged_with_an_empty_pins_table(fixture_home):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)

    def slugs(doc):
        return {(role, provider): item["provenance"].get(sm.FROZEN_SLUG)
                for role, provs in doc["pins"].items() for provider, item in provs.items()}

    no_pins_file = sm.emit()
    write_pins(fixture_home, {})
    empty_table = sm.emit()
    assert empty_table == no_pins_file                                     # the empty table changes nothing
    assert set(slugs(empty_table).values()) == {None}
    assert not any(sm.FROZEN_SLUG in item["provenance"]
                   for provs in empty_table["pins"].values() for item in provs.values())
    # CONTROL: a freeze in the same HOME puts the pins-file slug on exactly the frozen TOP pins
    write_pins(fixture_home, {"codex": "gpt-5.6-sol", "agy": "gemini-4-argon-low"})
    frozen = sm.emit()
    expected = {(role, provider): None for (role, provider) in slugs(frozen)}
    expected.update({(role, "codex"): "gpt-5.6-sol" for role in R14_CODEX_TOP_ROLES})
    expected.update({(role, "agy"): "gemini-4-argon-low" for role in ("consultant_main", "consultant_support", "arbiter")})
    assert slugs(frozen) == expected
    for (role, provider), slug in expected.items():                      # provenance only: pins match resolve()
        item, pin = frozen["pins"][role][provider], sm.resolve(role, provider)
        assert (item["model"], item["effort"], item["timeout"]) == (pin.model, pin.effort, pin.timeout)
    json.dumps(frozen)


def test_r14_the_provenance_docstring_lists_frozen_slug():
    doc = sm.__doc__
    section = doc[doc.index("PROVENANCE = {"):doc.index("WRITES.")]
    assert "frozen_slug" in section and "freeze" in section and "as written" in section


# --- #282 r15: a standalone `codex_quota.py admit` before `argv --use` never double-charges (K17) --- #
_QUOTA_MODULE_PATH = _META / "codex_quota.py"


def _quota_cli(args, *, cwd):
    """The standalone codex_quota CLI in a child process; it inherits the fixture HOME from the environment."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, str(_QUOTA_MODULE_PATH), *args], capture_output=True, text=True,
                          encoding="utf-8", env=env, cwd=str(cwd), timeout=60, stdin=subprocess.DEVNULL)


def test_r15_a_standalone_admit_then_argv_use_charges_exactly_one_admitted_row(fixture_home, project, tmp_path,
                                                                             codex_cli, capsys):
    # RE-POINTED by S081 revision 4 WP-A3 (design §2.2, D16): BUDGET_LIMITS is keyed by
    # model_class now, and this flow is an unsized TOP call. Still limit 1, so the property
    # this test exists for — a second charge would refuse — is unchanged.
    assert codex_quota.BUDGET_LIMITS["consult"][codex_quota.MODEL_CLASS_TOP] == 1
    write_codex_roster(fixture_home)
    cycle = "r15-fresh-cycle"
    store = store_path(project)
    assert fixture_home in store.parents and store_rows(project) == []

    check = _quota_cli(["admit", "--use", "consult", "--cycle-id", cycle, "--project-root", str(project)], cwd=project)
    assert check.returncode == 0, check.stderr
    decision = json.loads(check.stdout)
    assert (decision["admitted"], decision["reason"], decision["recorded"], decision["row_written"],
            decision["admission_id"]) == (True, "within_budget", False, False, None)
    assert not store.exists() and not codex_quota.lock_path_for(store).exists() and not store.parent.exists()

    code, out, _ = cli(capsys, argv_use("code_reviewer", "consult", project, "--cycle-id", cycle))
    assert (code, out) == (sm.EXIT_OK, "-m gpt-6-astra -c model_reasoning_effort=xhigh\n")
    rows = store_rows(project)
    assert [(r["admitted"], r["reason"], r["use"], r["cycle_id"]) for r in admit_rows(rows)] == [
        (True, "within_budget", "consult", cycle)]
    assert len(rows) == 1 and substitution_rows(rows) == []

    # CONTROL: the same sequence with --record charges twice, so the gate refuses the call it should have admitted.
    other = tmp_path / "proj-control"
    other.mkdir()
    recorded = _quota_cli(["admit", "--record", "--use", "consult", "--cycle-id", cycle, "--project-root", str(other)],
                          cwd=other)
    assert recorded.returncode == 0, recorded.stderr
    assert json.loads(recorded.stdout)["recorded"] is True
    code, out, _ = cli(capsys, argv_use("code_reviewer", "consult", other, "--cycle-id", cycle))
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"budget_spent\n{MAIN}\n")
    rows = store_rows(other)
    assert [(r["admitted"], r["reason"]) for r in admit_rows(rows)] == [(True, "within_budget"), (False, "budget_spent")]
    assert [(r["use"], r["reason"]) for r in substitution_rows(rows)] == [("consult", "budget_spent")]
    assert sum(1 for r in rows if r.get("admitted") is True) == 1


# =========================================================================== #
# #282 r12 (plan K18, K19) — `timeout --role R --provider codex`: a codex seat's timeout, from the registry
#
# Every codex_top_seat copy (forge x2, codex-orchestration, adversarial-team-brainstorm,
# cross-cli-deliberation) ran `timeout 600 codex exec`, so an arbiter or escalation seat was killed at half
# its budget. The block now asks this subcommand AFTER `argv --use` admitted the call. The
# numbers below are the S081 revision-4 (D24) caps — the same values as codex_watch.HARD_CAP_S; they read
# 600/600/600/1200/1200 before WP-A02 raised codex_model._TIMEOUT_FLOOR_S to the watchdog's caps. The
# timeout is its own subcommand and never a second `argv` stdout line: the block word-splits `$OUT` into
# `codex exec $OUT`, so an extra line would become a prompt positional. The block itself is exercised by
# skills/forge/tests/test_codex_top_seat_block.py.
# =========================================================================== #
R12_TIMEOUTS = {"code_reviewer": 2400, "consultant_main": 2400, "consultant_support": 1200,
                "arbiter": 2400,                   # the astra reserve U4: Sol @ xhigh
                "escalation": 3600}


def timeout_args(role, provider="codex"):
    return ["timeout", "--role", role, "--provider", provider]


def test_r12_timeout_prints_one_integer_the_resolved_codex_pins_timeout(fixture_home, codex_cli, capsys):
    write_codex_roster(fixture_home)
    for role in sm.ROLES:
        pin = sm.resolve(role, "codex", fail_open=False)
        assert pin.timeout == codex_model.timeout_for(pin.model, pin.effort) == R12_TIMEOUTS[role], role
        code, out, err = cli(capsys, timeout_args(role))
        assert (code, out, err) == (sm.EXIT_OK, f"{R12_TIMEOUTS[role]}\n", ""), role
    # The real process: exactly one line, one integer.
    proc = run_cli(timeout_args("escalation"))
    assert (proc.returncode, proc.stdout) == (0, "3600\n"), proc.stderr
    assert proc.stdout.splitlines() == ["3600"] and proc.stdout.strip().isdigit()
    # CONTROL: `argv` is unchanged by the new subcommand - still the one-line fragment, no timeout in it.
    argv = run_cli(["argv", "--role", "escalation", "--provider", "codex"])
    assert (argv.returncode, argv.stdout) == (0, "-m gpt-6-astra -c model_reasoning_effort=max\n")
    assert codex_cli["calls"] == 0                                        # a timeout checks no binary


def test_r12_timeout_follows_the_resolved_pin_not_a_table_of_its_own(fixture_home, capsys, monkeypatch):
    """The number is the resolved pin's (codex_model.timeout_for owns it): a per-model override for the model a
    seat resolves to moves exactly that seat, and a freeze onto another model changes the model it is looked up for."""
    write_codex_roster(fixture_home)
    monkeypatch.setitem(codex_model._MODEL_TIMEOUT_OVERRIDES_S, ("gpt-6-astra", "max"), 1500)
    assert cli(capsys, timeout_args("escalation"))[:2] == (sm.EXIT_OK, "1500\n")
    assert cli(capsys, timeout_args("arbiter"))[:2] == (sm.EXIT_OK, "2400\n")          # CONTROL: Sol @ xhigh
    assert cli(capsys, timeout_args("consultant_main"))[:2] == (sm.EXIT_OK, "2400\n")    # CONTROL: xhigh untouched
    write_pins(fixture_home, {"codex": "gpt-5.6-sol"})                  # the override names astra, the freeze serves sol
    assert cli(capsys, timeout_args("escalation"))[:2] == (sm.EXIT_OK, "3600\n")
    assert sm.resolve("escalation", "codex").model == "gpt-5.6-sol"


@pytest.mark.parametrize("setup", ["invalid_freeze", "roster_invalid", "no_eligible_top", "valid_control"])
def test_r12_timeout_is_the_same_fail_closed_resolution_as_argv_without_use(fixture_home, project, codex_cli,
                                                                           capsys, monkeypatch, setup):
    write_codex_roster(fixture_home)
    if setup == "invalid_freeze":
        write_pins(fixture_home, {"codex": "gpt-reserve"})
    elif setup == "roster_invalid":
        _write_raw_roster(fixture_home, R4_INVALID_ROSTERS["srl_true"]())
    elif setup == "no_eligible_top":
        write_codex_roster(fixture_home, _hidden_only_entries())
    monkeypatch.chdir(project)                                           # a fall-through to the budget would key here
    for role in ("code_reviewer", "escalation"):      # the codex TOP rows (astra reserve)
        argv = cli(capsys, ["argv", "--role", role, "--provider", "codex"])
        timeout = cli(capsys, timeout_args(role))
        if setup == "valid_control":
            assert (argv[0], timeout[:2]) == (sm.EXIT_OK, (sm.EXIT_OK, f"{R12_TIMEOUTS[role]}\n")), role
            continue
        # exit 1 and EMPTY stdout, exactly like argv - never 3: a timeout lookup is not an admission and substitutes nothing
        assert argv[:2] == (sm.EXIT_RESOLUTION_FAILED, ""), (role, argv[2])
        assert timeout[:2] == (sm.EXIT_RESOLUTION_FAILED, ""), (role, timeout[2])
        assert timeout[2].startswith("seat_model.py: error:") and "Traceback" not in timeout[2]
    assert not (fixture_home / ".claude" / "projects").exists() and codex_cli["calls"] == 0
    if setup == "no_eligible_top":
        # CONTROL: the same HOME through `argv --use` IS a substitution (exit 3), so the exit 1 above is the timeout's own rule
        assert cli(capsys, argv_use("code_reviewer", "consult", project))[:2] == (
            sm.EXIT_SUBSTITUTE, f"no_eligible_model\n{MAIN}\n")


def test_r12_timeout_on_a_seat_without_a_codex_row_is_a_usage_error(fixture_home, capsys, monkeypatch):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    for provider in ("agy", "claude"):
        code, out, err = cli(capsys, timeout_args("consultant_main", provider))
        assert (code, out) == (sm.EXIT_USAGE, ""), provider
        assert "codex seats only" in err and provider in err
    # A role whose table row has no codex cell (none today; the rule must not depend on that).
    table = dict(sm.ROLE_TABLE)
    table["escalation"] = MappingProxyType({"claude": sm.ROLE_TABLE["escalation"]["claude"]})
    monkeypatch.setattr(sm, "ROLE_TABLE", MappingProxyType(table))
    code, out, err = cli(capsys, timeout_args("escalation"))
    assert (code, out) == (sm.EXIT_USAGE, "") and "no codex row" in err
    assert cli(capsys, timeout_args("arbiter"))[:2] == (sm.EXIT_OK, "2400\n")      # CONTROL: the same patched table


@pytest.mark.parametrize("args", [
    ["timeout", "--role", "arbiter"],
    ["timeout", "--provider", "codex"],
    ["timeout", "--role", "execution", "--provider", "codex"],
    ["timeout", "--role", "arbiter", "--provider", "codex", "--use", "consult"],
    ["timeout", "--role", "arbiter", "--provider", "codex", "--project-root", "PROJECT"],
    ["timeout", "--help"],
])
def test_r12_timeout_usage_errors_exit_2_with_empty_stdout(fixture_home, project, codex_cli, capsys, args):
    write_codex_roster(fixture_home)
    args = [str(project) if a == "PROJECT" else a for a in args]
    code, out, err = cli(capsys, args)
    assert (code, out) == (sm.EXIT_USAGE, "") and err.strip()
    assert not (fixture_home / ".claude" / "projects").exists() and codex_cli["calls"] == 0


@pytest.mark.parametrize("bad", [0, -600, True, "600", 600.0, None])
def test_r12_timeout_prints_only_a_positive_integer(fixture_home, capsys, monkeypatch, bad):
    """Defence in depth: `timeout "$TO"` must never receive a bool, a float, a string or a non-positive number."""
    fake = sm.SeatPin(model="gpt-6-astra", effort="max", timeout=bad, argv_fragment=("-m", "gpt-6-astra"), provenance={})
    monkeypatch.setattr(sm, "resolve", lambda *a, **kw: fake)
    code, out, err = cli(capsys, timeout_args("arbiter"))
    assert (code, out) == (sm.EXIT_RESOLUTION_FAILED, "") and "timeout" in err
    monkeypatch.setattr(sm, "resolve", lambda *a, **kw: sm.SeatPin(          # CONTROL
        model="gpt-6-astra", effort="max", timeout=1200, argv_fragment=("-m", "gpt-6-astra"), provenance={}))
    assert cli(capsys, timeout_args("arbiter"))[:2] == (sm.EXIT_OK, "1200\n")


def test_r12_timeout_writes_only_the_tops_record_like_argv(fixture_home, project, codex_cli, capsys, monkeypatch):
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    monkeypatch.chdir(project)
    rel_tops = os.path.join(".claude", "state", "seat-model-tops.json")
    before = tree_snapshot(fixture_home)
    assert cli(capsys, timeout_args("code_reviewer"))[:2] == (sm.EXIT_OK, "2400\n")
    after = tree_snapshot(fixture_home)
    assert {k for k in set(before) | set(after) if before.get(k, b"") != after.get(k, b"")} == {rel_tops}
    assert tree_snapshot(project) == {} and codex_cli["calls"] == 0
    # CONTROL: `argv` without --use writes the same single file
    tops_path(fixture_home).unlink()
    assert cli(capsys, ["argv", "--role", "code_reviewer", "--provider", "codex"])[0] == sm.EXIT_OK
    assert set(tree_snapshot(fixture_home)) == set(after)


def test_r12_the_docstring_and_the_parser_name_the_timeout_subcommand(capsys):
    doc = " ".join(sm.__doc__.split())
    cli_section = doc[doc.index("CLI "):doc.index("ASTRA UNAVAILABLE")]
    assert "`timeout --role R --provider codex`" in cli_section
    assert "one integer" in cli_section.lower() and "word-split" in cli_section
    code, out, err = cli(capsys, ["--help"])
    assert (code, out) == (sm.EXIT_USAGE, "") and "timeout" in err
    code, out, err = cli(capsys, [])
    assert (code, out) == (sm.EXIT_USAGE, "") and "timeout" in err


# =========================================================================== #
# #282 R16 (plan K25-K27) — a priority tie at the codex TOP is broken and recorded
#
# The live defect: the 2026-09-15T20:45:50Z roster refresh tied gpt-5.6-sol with gpt-6-astra at
# priority 1 and every codex TOP seat served sol (slug order). seat_model passes the recorded codex
# TOP as select_top's incumbent (read BEFORE the resolution rewrites the record), copies the tie
# into provenance and the tops record as event keys, and writes them only for a tied selection.
# The pre-R16 CONTROL replaces select_top with the old (priority, slug) ranking, so each fixture is
# shown to produce the other answer when the rule is absent.
# =========================================================================== #
R16_TIE_KEYS = ("tie_break", "tied_with")


def r16_tie_codex_entries():
    """The live roster after the 2026-09-15T20:45:50Z refresh (sol 4 -> 1), file order as live.

    DATED FIXTURE: its slugs stay literal. #302 WP-1: `crf.with_tiers` appends any roster tier the
    2026-09-15 roster did not list (none at rev 2), so the support seat still resolves from it."""
    return crf.with_tiers([
        entry("gpt-5.6-sol", 1),
        entry("gpt-6-astra", 1),
        entry("gpt-reserve", 3, visibility="hide", efforts=("low", "medium", "high", "xhigh", "max")),
        entry("gpt-5.6-terra", 7),
        entry("gpt-5.6-luna", 8, efforts=("low", "medium", "high", "xhigh", "max")),
        entry("gpt-5.5", 12, efforts=("low", "medium", "high", "xhigh")),
        entry("codex-auto-review", 43, visibility="hide", efforts=("low", "medium", "high", "xhigh", "max")),
    ])


def _pre_r16_select_top(effort, *, cache_path=None, incumbent=None):
    """select_top as it was before R16: the (priority, slug) order, no tie fields."""
    doc = codex_model.load_roster_entries(cache_path)
    ranked = sorted((e for e in doc.entries.values()
                     if e.priority is not None and codex_model._ineligibility(e, effort) is None),
                    key=lambda e: (e.priority, e.slug))
    if not ranked:
        raise codex_model.CodexModelError(f"no eligible codex TOP for effort {effort!r}")
    return codex_model.TopSelection(model=ranked[0].slug, effort=effort, priority_winner=ranked[0].slug,
                                    upgrade_followed=False, upgrade_ignored_reason=None,
                                    roster_fetched_at=doc.fetched_at, roster_client_version=doc.client_version)


def _tie_keys_anywhere(doc):
    return sorted((role, provider) for role, provs in doc["pins"].items() for provider, item in provs.items()
                  if any(key in item["provenance"] for key in R16_TIE_KEYS))


def test_r16_g_the_live_tie_roster_serves_astra_on_every_codex_top_seat_with_the_tie_recorded(
        fixture_home, monkeypatch, capsys):
    write_codex_roster(fixture_home, r16_tie_codex_entries())
    write_agy_cache(fixture_home)
    doc = sm.emit()
    # the astra reserve (roster rev 4): the codex TOP rows are code_reviewer and escalation only
    for role, effort, timeout in (("code_reviewer", "xhigh", 2400), ("escalation", "max", 3600)):
        item = doc["pins"][role]["codex"]
        assert (item["model"], item["effort"], item["timeout"]) == ("gpt-6-astra", effort, timeout), role
        assert item["argv_fragment"] == ["-m", "gpt-6-astra", "-c", f"model_reasoning_effort={effort}"]
        prov = item["provenance"]
        assert (prov["source"], prov["resolved_model"]) == ("roster", "gpt-6-astra")
        assert (prov["tie_break"], prov["tied_with"]) == ("generation", ["gpt-5.6-sol"]), role
        assert set(prov) == REQUIRED_PROVENANCE | set(R16_TIE_KEYS), (role, prov)
    support = doc["pins"]["consultant_support"]["codex"]                  # the literal calls no selection
    assert (support["model"], support["provenance"]["source"]) == (CODEX_SUP, "roster")
    assert _tie_keys_anywhere(doc) == sorted((role, "codex") for role in R14_CODEX_TOP_ROLES)
    record = read_tops(fixture_home)["tops"]["codex"]
    assert (record["top"], record["tie_break"], record["tied_with"]) == ("gpt-6-astra", "generation", ["gpt-5.6-sol"])
    assert "tie_break" not in read_tops(fixture_home)["tops"]["agy"]
    assert cli(capsys, ["argv", "--role", "code_reviewer", "--provider", "codex"])[:2] == (
        sm.EXIT_OK, "-m gpt-6-astra -c model_reasoning_effort=xhigh\n")
    json.dumps(doc)
    # CONTROL: the same HOME through the pre-R16 ordering serves sol on every TOP seat, untied.
    tops_path(fixture_home).unlink()
    monkeypatch.setattr(codex_model, "select_top", _pre_r16_select_top)
    before = sm.emit()
    assert {before["pins"][role]["codex"]["model"] for role in R14_CODEX_TOP_ROLES} == {"gpt-5.6-sol"}
    assert _tie_keys_anywhere(before) == []
    assert not any(key in read_tops(fixture_home)["tops"]["codex"] for key in R16_TIE_KEYS)


def test_r16_g_control_an_untied_roster_emits_exactly_what_it_emitted_before_r16(fixture_home, monkeypatch):
    write_codex_roster(fixture_home)                                     # the pre-refresh shape: astra 1, sol 4
    write_agy_cache(fixture_home)
    after = sm.emit()
    record_after = read_tops(fixture_home)
    assert _tie_keys_anywhere(after) == []
    assert set(record_after["tops"]["codex"]) == {"top", "previous", "changed_at", "resolved_at", "roster_fetched_at"}
    tops_path(fixture_home).unlink()
    monkeypatch.setattr(codex_model, "select_top", _pre_r16_select_top)
    before = sm.emit()
    assert after == before                                               # every pin, every provenance key
    assert read_tops(fixture_home) == record_after
    assert {after["pins"][role]["codex"]["model"] for role in R14_CODEX_TOP_ROLES} == {"gpt-6-astra"}


def test_r16_h_tie_keys_are_dropped_from_the_record_when_the_roster_no_longer_ties(fixture_home):
    write_codex_roster(fixture_home, r16_tie_codex_entries())
    assert sm.resolve("code_reviewer", "codex").provenance["tie_break"] == "generation"
    assert read_tops(fixture_home)["tops"]["codex"]["tie_break"] == "generation"
    write_codex_roster(fixture_home)                                     # the next refresh unties it
    pin = sm.resolve("code_reviewer", "codex")
    assert pin.model == "gpt-6-astra" and not any(key in pin.provenance for key in R16_TIE_KEYS)
    record = read_tops(fixture_home)["tops"]["codex"]
    assert set(record) == {"top", "previous", "changed_at", "resolved_at", "roster_fetched_at"}
    assert (record["top"], record["previous"], record["changed_at"]) == ("gpt-6-astra", None, None)
    # A STALE roster's kept TOP calls no tie-break: a stale tie roster keeps astra and records no tie.
    write_codex_roster(fixture_home, r16_tie_codex_entries())
    sm.resolve("code_reviewer", "codex")
    assert "tie_break" in read_tops(fixture_home)["tops"]["codex"]
    write_codex_roster(fixture_home, r16_tie_codex_entries(), fetched_at=iso(NOW - 8 * DAY))
    pin = sm.resolve("code_reviewer", "codex")
    assert (pin.model, pin.provenance.get("roster_stale")) == ("gpt-6-astra", True)
    assert not any(key in pin.provenance for key in R16_TIE_KEYS)
    assert not any(key in read_tops(fixture_home)["tops"]["codex"] for key in R16_TIE_KEYS)
    # CONTROL: the fresh tie roster records the tie again.
    write_codex_roster(fixture_home, r16_tie_codex_entries())
    sm.resolve("escalation", "codex")
    assert read_tops(fixture_home)["tops"]["codex"]["tied_with"] == ["gpt-5.6-sol"]


def test_r16_i_a_codex_freeze_or_a_harness_literal_on_the_tie_roster_carries_no_tie_keys(fixture_home):
    write_codex_roster(fixture_home, r16_tie_codex_entries())
    sm.resolve("code_reviewer", "codex")
    assert "tie_break" in read_tops(fixture_home)["tops"]["codex"]
    write_pins(fixture_home, {"codex": "gpt-6-astra"})                    # the main loop's live freeze shape
    for role in R14_CODEX_TOP_ROLES:
        prov = sm.resolve(role, "codex").provenance
        assert (prov["source"], prov[sm.FROZEN_SLUG]) == ("freeze", "gpt-6-astra"), role
        assert not any(key in prov for key in R16_TIE_KEYS), role
    assert not any(key in read_tops(fixture_home)["tops"]["codex"] for key in R16_TIE_KEYS)
    write_pins(fixture_home, {"codex": "gpt-reserve"})                    # invalid freeze -> fail-open literal
    prov = sm.resolve("code_reviewer", "codex", fail_open=True).provenance
    assert prov["source"] == "harness_literal" and not any(key in prov for key in R16_TIE_KEYS)
    # CONTROL: removing the freeze puts the tie back into provenance and the record.
    (fixture_home / ".claude" / "state" / "seat-model-pins.json").unlink()
    prov = sm.resolve("code_reviewer", "codex").provenance
    assert (prov["source"], prov["tie_break"], prov["tied_with"]) == ("roster", "generation", ["gpt-5.6-sol"])
    assert read_tops(fixture_home)["tops"]["codex"]["tie_break"] == "generation"


def test_r16_j_the_incumbent_is_the_recorded_top_read_before_this_resolution(fixture_home, monkeypatch):
    equal = [entry("gpt-5.6-sol", 1), entry("gpt-5.6-terra", 1), entry("gpt-5.5", 4)]
    write_codex_roster(fixture_home, equal)
    # CONTROL: no tops record -> no incumbent -> slug.
    prov = sm.resolve("code_reviewer", "codex").provenance
    assert (prov["resolved_model"], prov["tie_break"], prov["tied_with"]) == ("gpt-5.6-sol", "slug", ["gpt-5.6-terra"])
    write_tops(fixture_home, {"codex": "gpt-5.6-terra"})
    seen = []
    real = codex_model.select_top

    def spy(effort, *, cache_path=None, incumbent=None):
        seen.append(incumbent)
        return real(effort, cache_path=cache_path, incumbent=incumbent)

    monkeypatch.setattr(codex_model, "select_top", spy)
    pin = sm.resolve("code_reviewer", "codex")
    assert seen == ["gpt-5.6-terra"]
    assert (pin.model, pin.provenance["tie_break"], pin.provenance["tied_with"]) == \
        ("gpt-5.6-terra", "incumbent", ["gpt-5.6-sol"])
    record = read_tops(fixture_home)["tops"]["codex"]
    assert (record["top"], record["tie_break"], record["tied_with"]) == ("gpt-5.6-terra", "incumbent", ["gpt-5.6-sol"])
    assert sm.resolve("escalation", "codex").model == "gpt-5.6-terra"          # self-stabilising
    # An incumbent outside the tied set is not consulted.
    write_tops(fixture_home, {"codex": "gpt-6-astra"})
    assert (sm.resolve("code_reviewer", "codex").provenance["tie_break"], seen[-1]) == ("slug", "gpt-6-astra")


def test_r16_a_protected_env_override_equal_to_the_tie_winner_keeps_the_tie_keys(fixture_home, monkeypatch):
    """The tie keys describe the selection, like upgrade_followed: an env value equal to the selected
    model only relabels the source (a protected seat's model cannot move), so the keys stay."""
    write_codex_roster(fixture_home, r16_tie_codex_entries())
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-6-astra")
    prov = sm.resolve("code_reviewer", "codex", env_var="SEAT_TEST_ENV").provenance
    assert (prov["source"], prov["tie_break"], prov["tied_with"]) == ("env", "generation", ["gpt-5.6-sol"])
    # CONTROL: an env value naming the tie loser is refused; the tie still decided the model.
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-5.6-sol")
    pin = sm.resolve("code_reviewer", "codex", env_var="SEAT_TEST_ENV")
    assert (pin.model, pin.provenance["source"], pin.provenance["tie_break"]) == ("gpt-6-astra", "roster", "generation")
    assert pin.provenance["env_override_refused"]["value"] == "gpt-5.6-sol"


def test_r16_the_docstring_names_the_tie_keys_in_selection_provenance_and_writes():
    doc = " ".join(sm.__doc__.split())
    selection = doc[doc.index("SELECTION ("):doc.index("PRECEDENCE for")]
    provenance = doc[doc.index("PROVENANCE = {"):doc.index("WRITES.")]
    writes = doc[doc.index("WRITES."):doc.index("NO NETWORK")]
    assert "PRIORITY TIE" in selection and "incumbent" in selection and "generation" in selection
    for section in (provenance, writes):
        assert "tie_break" in section and "tied_with" in section
    assert (sm.TIE_BREAK, sm.TIED_WITH) == R16_TIE_KEYS


# =========================================================================== #
# #282 fix round 1 — F10 (plan K44): a FOLLOWED upgrade no longer loses the incumbent.
#
# The tops record's `top` is the SERVED model. When the tie winner's `upgrade` was
# followed, the served model sits OUTSIDE the tie, so R16's incumbent rule (which read
# `top`) found nothing in the tied set and the next resolution fell to slug — silently
# downgrading off the winner the vendor had just superseded. The record now carries
# `priority_winner` as an EVENT KEY, written only when it DIFFERS from `top`, and that
# is the incumbent seat_model passes. The stale-roster "keep the last TOP" rule still
# reads `top`: it is about the model that was served.
# =========================================================================== #
F10_ENTRIES = [entry("alpha", 1), entry("zeta", 1, upgrade="gpt-7-target"), entry("gpt-7-target", 9)]


def _seed_pre_round_record(home, top):
    """A tops record in the shape written BEFORE this round: no `priority_winner` key."""
    tops_path(home).parent.mkdir(parents=True, exist_ok=True)
    tops_path(home).write_text(json.dumps({"schema": sm.TOPS_SCHEMA, "tops": {"codex": {
        "top": top, "previous": None, "changed_at": None,
        "resolved_at": iso(NOW), "roster_fetched_at": iso(NOW - 3600),
    }}}), encoding="utf-8")


def test_f10_a_followed_upgrade_keeps_the_priority_winner_as_the_next_incumbent(fixture_home):
    """alpha / zeta tie at priority 1 with UNPARSEABLE generations, so the incumbent decides."""
    write_codex_roster(fixture_home, F10_ENTRIES)
    # A record written BEFORE this round still yields today's incumbent: `top` is the fallback.
    _seed_pre_round_record(fixture_home, "zeta")
    served = [sm.resolve(role, "codex").model
              for role in ("code_reviewer", "code_reviewer", "escalation")]   # the TOP rows
    assert served == ["gpt-7-target"] * 3        # never target -> alpha -> alpha
    record = read_tops(fixture_home)["tops"]["codex"]
    assert (record["top"], record["priority_winner"]) == ("gpt-7-target", "zeta")
    assert sm.resolve("code_reviewer", "codex").provenance["tie_break"] == "incumbent"
    # CONTROL (the pre-fix sequence): the same served TOP recorded WITHOUT `priority_winner`
    # has no incumbent inside the tied set, so the tie falls to slug and serves alpha.
    _seed_pre_round_record(fixture_home, "gpt-7-target")
    pin = sm.resolve("code_reviewer", "codex")
    assert (pin.model, pin.provenance["tie_break"]) == ("alpha", "slug")


def test_f10_a_freeze_or_a_stale_kept_top_preserves_the_recorded_priority_winner(fixture_home):
    write_codex_roster(fixture_home, F10_ENTRIES)
    _seed_pre_round_record(fixture_home, "zeta")
    assert sm.resolve("code_reviewer", "codex").model == "gpt-7-target"
    assert read_tops(fixture_home)["tops"]["codex"]["priority_winner"] == "zeta"
    # A FREEZE rewrites the record with the same `top`: the incumbent is carried forward.
    write_pins(fixture_home, {"codex": "gpt-7-target"})
    assert sm.resolve("code_reviewer", "codex").provenance["source"] == "freeze"
    assert read_tops(fixture_home)["tops"]["codex"]["priority_winner"] == "zeta"
    (fixture_home / ".claude" / "state" / "seat-model-pins.json").unlink()
    # A STALE roster keeps the last TOP — which reads `top`, not `priority_winner`, because it
    # is about the model that was served — and preserves the incumbent across the spell.
    write_codex_roster(fixture_home, F10_ENTRIES, fetched_at=iso(NOW - 8 * DAY))
    pin = sm.resolve("code_reviewer", "codex")
    assert (pin.model, pin.provenance.get("roster_stale")) == ("gpt-7-target", True)
    assert read_tops(fixture_home)["tops"]["codex"]["priority_winner"] == "zeta"
    # Fresh again: the carried incumbent still decides, so the upgrade target is served again.
    write_codex_roster(fixture_home, F10_ENTRIES)
    assert sm.resolve("code_reviewer", "codex").model == "gpt-7-target"


def test_f10_priority_winner_is_an_event_key_dropped_when_the_top_moves_without_one(fixture_home):
    # No upgrade -> served == priority winner -> the key is ABSENT (today's live record shape).
    write_codex_roster(fixture_home, r16_tie_codex_entries())
    sm.resolve("code_reviewer", "codex")
    record = read_tops(fixture_home)["tops"]["codex"]
    assert (record["top"], "priority_winner" not in record) == ("gpt-6-astra", True)
    assert set(record) == {"top", "previous", "changed_at", "resolved_at", "roster_fetched_at",
                           "tie_break", "tied_with"}
    # A later selection whose `top` MOVES and names no priority winner drops a stale one.
    write_codex_roster(fixture_home, F10_ENTRIES)
    _seed_pre_round_record(fixture_home, "zeta")
    sm.resolve("code_reviewer", "codex")
    assert read_tops(fixture_home)["tops"]["codex"]["priority_winner"] == "zeta"
    write_codex_roster(fixture_home)                       # the untied roster: astra alone at 1
    sm.resolve("code_reviewer", "codex")
    record = read_tops(fixture_home)["tops"]["codex"]
    assert (record["top"], "priority_winner" in record) == ("gpt-6-astra", False)


# =========================================================================== #
# #282 fix round 1 — F13 at the seat layer, and F12's fail-open boundary (plan K43).
#
# F13  A field-type fault on a never-selectable roster entry used to invalidate the whole
#      document, so EVERY fail-closed codex seat raised and every convene went down. Such an
#      entry is now skipped and its slug surfaced as the provenance EVENT KEY
#      `roster_entries_skipped` — present only when non-empty, and (per K30) added to neither
#      audit_spawn's verdict provenance nor convene's persisted provenance.
#
# F12  `_generation`'s `int()` raised ValueError from inside the tie-break — past the
#      fail-open boundary, since every caller here catches CodexModelError. Bounding the
#      digit groups makes the slug unparseable instead, so nothing escapes seat_model.
# =========================================================================== #
SKIPPED_KEY = "roster_entries_skipped"


def _fr1_skipped_codex_entries():
    """The live-like roster with the FAULT on an entry no effort could ever select."""
    entries = live_like_codex_entries()
    entries[crf.slug_index(entries, "gpt-reserve")] = dict(entry("gpt-reserve", 3, visibility="hide"),
                                                         supported_reasoning_levels=None)
    return entries


def test_fr1_f13_a_fault_on_a_never_selectable_entry_no_longer_takes_every_codex_seat_down(fixture_home):
    """F13 headline at the seat layer: fail-CLOSED is unaffected, and the skip is recorded."""
    write_codex_roster(fixture_home, _fr1_skipped_codex_entries())
    for role, model, effort in (("code_reviewer", "gpt-6-astra", "xhigh"),
                                ("escalation", "gpt-6-astra", "max"),
                                ("consultant_support", CODEX_SUP, "medium")):
        pin = sm.resolve(role, "codex", fail_open=False)       # pre-fix: SeatModelError roster_invalid
        assert (pin.model, pin.effort, pin.provenance["source"]) == (model, effort, "roster")
        assert pin.provenance[SKIPPED_KEY] == ["gpt-reserve"]
        assert "roster_invalid" not in pin.provenance and "fallback_reason" not in pin.provenance
    assert sm.resolve("code_reviewer", "codex", fail_open=True).provenance[SKIPPED_KEY] == ["gpt-reserve"]


def test_fr1_f13_the_key_is_absent_on_a_clean_roster_and_on_every_non_codex_seat(fixture_home):
    """CONTROL: an event key, never present-and-empty."""
    write_codex_roster(fixture_home)
    write_agy_cache(fixture_home)
    for role, provider in (("code_reviewer", "codex"), ("arbiter", "codex"),
                           ("consultant_main", "agy"), ("code_reviewer", "claude")):
        prov = sm.resolve(role, provider, fail_open=False).provenance
        assert SKIPPED_KEY not in prov, (role, provider)
    assert SKIPPED_KEY not in sm.emit()["pins"]["code_reviewer"]["codex"]["provenance"]


def test_fr1_f13_the_fail_open_literal_path_still_records_the_skip(fixture_home):
    """"seat_model fail-open records roster_entries_skipped": the key survives a resolution
    FAILURE too, exactly as roster_invalid does — it is a fact about the document that was read."""
    entries = [dict(entry("gpt-hidden", 1, visibility="hide"), priority=1.0),
               entry("gpt-5.6-terra", 7, efforts=("low",))]
    write_codex_roster(fixture_home, entries)
    with pytest.raises(sm.NoEligibleModelError) as info:
        sm.resolve("code_reviewer", "codex", fail_open=False)
    assert "roster_invalid" not in str(info.value)
    pin = sm.resolve("code_reviewer", "codex", fail_open=True)
    assert (pin.model, pin.provenance["source"]) == (sm.CODEX_TOP_HARNESS_LITERAL, "harness_literal")
    assert pin.provenance[SKIPPED_KEY] == ["gpt-hidden"]
    assert pin.provenance["unavailable_reason"] == sm.UNAVAILABLE_NO_ELIGIBLE
    assert "roster_invalid" not in pin.provenance


def test_fr1_f13_a_fault_on_a_selectable_entry_is_still_the_whole_document(fixture_home):
    """CONTROL for F13, the fail-closed half the finding must NOT weaken."""
    entries = live_like_codex_entries()
    entries[0] = dict(entry("gpt-6-astra", 1), supported_reasoning_levels=None)
    write_codex_roster(fixture_home, entries)
    with pytest.raises(sm.SeatModelError, match="roster_invalid") as info:
        sm.resolve("code_reviewer", "codex", fail_open=False)
    assert not isinstance(info.value, sm.NoEligibleModelError)
    pin = sm.resolve("code_reviewer", "codex", fail_open=True)
    assert (pin.model, pin.provenance["source"], pin.provenance["roster_invalid"]) == (
        sm.CODEX_TOP_HARNESS_LITERAL, "harness_literal", True)
    assert SKIPPED_KEY not in pin.provenance          # nothing was parsed, so nothing was skipped


def test_fr1_f13_the_skip_rides_the_literal_and_freeze_paths_too(fixture_home):
    """A codex LITERAL seat and a freeze both read the same document, so both report the skip."""
    write_codex_roster(fixture_home, _fr1_skipped_codex_entries())
    support = sm.resolve("consultant_support", "codex", fail_open=False)
    assert (support.model, support.provenance["source"]) == (CODEX_SUP, "roster")
    assert support.provenance[SKIPPED_KEY] == ["gpt-reserve"]
    write_pins(fixture_home, {"codex": "gpt-5.6-terra"})
    frozen = sm.resolve("code_reviewer", "codex", fail_open=False)
    assert (frozen.model, frozen.provenance["source"], frozen.provenance["frozen_slug"]) == (
        "gpt-5.6-terra", "freeze", "gpt-5.6-terra")
    assert frozen.provenance[SKIPPED_KEY] == ["gpt-reserve"]


def test_fr1_f13_the_cli_exits_0_on_a_partial_roster_and_1_on_a_selectable_fault(fixture_home):
    """The fail-closed CLI is the finding's real blast radius: a hidden entry must not exit 1."""
    write_codex_roster(fixture_home, _fr1_skipped_codex_entries())
    write_agy_cache(fixture_home)
    out = run_cli(["emit", "--json"])
    assert out.returncode == 0, out.stderr
    assert "Traceback" not in out.stderr
    doc = json.loads(out.stdout)
    assert doc["pins"]["code_reviewer"]["codex"]["model"] == "gpt-6-astra"
    assert doc["pins"]["code_reviewer"]["codex"]["provenance"][SKIPPED_KEY] == ["gpt-reserve"]
    # CONTROL: the same fault on the SELECTABLE entry still fails the CLI closed
    entries = live_like_codex_entries()
    entries[0] = dict(entry("gpt-6-astra", 1), supported_reasoning_levels=None)
    write_codex_roster(fixture_home, entries)
    out = run_cli(["emit", "--json"])
    assert out.returncode != 0 and "roster_invalid" in out.stderr and "Traceback" not in out.stderr


def test_fr2_g6_a_faulty_duplicate_of_a_selectable_entry_fails_the_seat_closed(fixture_home):
    """#282 fix round 2 (G6, K58a) at the seat layer: the silent-replacement path is closed.

    A hidden faulty duplicate of `gpt-6-astra` used to pop the TOP and leave the roster VALID,
    so every codex seat quietly moved to the next slug — a downgrade with no provenance at all.
    It is now the same fail-closed answer the fault gets on a selectable entry directly."""
    dup = dict(entry("gpt-6-astra", 1, visibility="hide"), supported_reasoning_levels=None)
    write_codex_roster(fixture_home, live_like_codex_entries() + [dup])
    write_agy_cache(fixture_home)
    with pytest.raises(sm.SeatModelError, match="roster_invalid") as info:
        sm.resolve("code_reviewer", "codex", fail_open=False)   # pre-fix: gpt-5.6-sol, silently
    assert not isinstance(info.value, sm.NoEligibleModelError)
    pin = sm.resolve("code_reviewer", "codex", fail_open=True)
    assert (pin.model, pin.provenance["source"], pin.provenance["roster_invalid"]) == (
        sm.CODEX_TOP_HARNESS_LITERAL, "harness_literal", True)
    assert SKIPPED_KEY not in pin.provenance         # nothing was parsed, so nothing was skipped
    out = run_cli(["emit", "--json"])
    assert out.returncode != 0 and "roster_invalid" in out.stderr and "Traceback" not in out.stderr
    # CONTROL (F13 intact): the same faulty hidden entry whose slug has NO earlier selectable
    # entry is still merely skipped, and the CLI still exits 0 on the partial roster.
    write_codex_roster(fixture_home, live_like_codex_entries()
                       + [dict(dup, slug="gpt-orphan")])
    ok = sm.resolve("code_reviewer", "codex", fail_open=False)
    assert (ok.model, ok.provenance["source"]) == ("gpt-6-astra", "roster")
    assert ok.provenance[SKIPPED_KEY] == ["gpt-orphan"] and "roster_invalid" not in ok.provenance
    out = run_cli(["emit", "--json"])
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["pins"]["code_reviewer"]["codex"]["model"] == "gpt-6-astra"


def test_fr2_g6_the_skip_key_never_names_a_slug_that_is_in_the_roster(fixture_home):
    """#282 fix round 2 (G6, K58b) at the seat layer: provenance stops contradicting itself.

    `roster_entries_skipped` is read by a human deciding whether to trust a seat. Naming a slug
    that is present — and selectable — made the key mean the opposite of what it says."""
    entries = live_like_codex_entries()
    entries[crf.slug_index(entries, "gpt-reserve")] = dict(entry("gpt-reserve", 3, visibility="hide"),
                                                         supported_reasoning_levels=None)
    healed = entries + [entry("gpt-reserve", 3, visibility="hide",
                              efforts=("low", "medium", "high", "xhigh", "max"))]
    write_codex_roster(fixture_home, healed)
    write_agy_cache(fixture_home)
    for role, model, effort in (("code_reviewer", "gpt-6-astra", "xhigh"),
                                ("escalation", "gpt-6-astra", "max"),
                                ("consultant_support", CODEX_SUP, "medium")):
        pin = sm.resolve(role, "codex", fail_open=False)
        assert (pin.model, pin.effort, pin.provenance["source"]) == (model, effort, "roster")
        assert SKIPPED_KEY not in pin.provenance, role   # pre-fix: ["gpt-reserve"], while present
        assert "roster_invalid" not in pin.provenance
    assert SKIPPED_KEY not in sm.resolve(
        "code_reviewer", "codex", fail_open=True).provenance
    assert SKIPPED_KEY not in json.loads(run_cli(["emit", "--json"]).stdout)[
        "pins"]["code_reviewer"]["codex"]["provenance"]
    # CONTROL: drop the later good entry and the key comes back, naming an ABSENT slug
    write_codex_roster(fixture_home, entries)
    assert sm.resolve("code_reviewer", "codex", fail_open=False).provenance[
        SKIPPED_KEY] == ["gpt-reserve"]


def test_fr1_f12_a_giant_generation_slug_never_escapes_seat_model(fixture_home):
    """F12 at the fail-open boundary: a ValueError is not a CodexModelError, so pre-fix it
    escaped BOTH modes. Now the slug is merely unparseable and the tie falls to astra."""
    giant = "gpt-" + "9" * 4301 + "-x"
    entries = live_like_codex_entries() + [entry(giant, 1)]
    write_codex_roster(fixture_home, entries)
    for fail_open in (False, True):
        pin = sm.resolve("code_reviewer", "codex", fail_open=fail_open)   # pre-fix: ValueError
        assert (pin.model, pin.provenance["source"]) == ("gpt-6-astra", "roster")
        assert (pin.provenance["tie_break"], pin.provenance["tied_with"]) == ("generation", [giant])
    assert read_tops(fixture_home)["tops"]["codex"]["top"] == "gpt-6-astra"


def test_fr1_the_docstring_names_the_skip_key_and_bounds_the_generation():
    """No docstring may keep claiming the rule the code no longer has (the F5/F6 lesson)."""
    doc = " ".join(sm.__doc__.split())
    provenance = doc[doc.index("PROVENANCE = {"):doc.index("WRITES.")]
    assert SKIPPED_KEY in provenance
    assert sm.ROSTER_ENTRIES_SKIPPED == SKIPPED_KEY
    # K30, unchanged by F13: the key is NOT in convene's persisted set or audit's verdict block
    persisted = provenance[provenance.index("convene persists"):]
    assert f"NOT {SKIPPED_KEY}" in persisted and "audit_spawn" in persisted
    writes = doc[doc.index("WRITES."):doc.index("NO NETWORK")]
    assert SKIPPED_KEY not in writes                  # not a tops-record key either
    cm_doc = " ".join(codex_model.__doc__.split())
    assert "SELECTABLE" in cm_doc and "entries_skipped" in cm_doc
    assert codex_model._GENERATION.pattern.count(r"\d{1,9}") == 2
    assert codex_model._generation("gpt-" + "9" * 4301 + "-x") is None


# --- #282 fix round 1: the docs say what F7, F15 and F16 changed (K46, K47, K48) ---
_FLAP_OBSERVATIONS = ("14:38:49", "20:45:50", "22:25:15", "22:38:08")


def test_fr1_the_roster_facts_record_the_priority_flap_and_the_docs_state_the_two_new_rules():
    """F16 (K48): every roster-fact sentence that DATES the gpt-5.6-sol tie must record the
    observed FLAP — all four observations — and must not claim the tie ended, because it did not
    (the live roster tied again at 22:38:08Z). F7 (K46) and F15 (K47): the ceiling docstring and
    the freeze rule say what the code now does.

    The completeness sweep itself (`grep -rn '20:45:50' skills/ agents/ PROJECT.md`) is a stage
    step, not a test: it reaches files no test imports. This pins the four PRODUCTION sentences."""
    sm_doc, cm_doc = " ".join(sm.__doc__.split()), " ".join(codex_model.__doc__.split())
    selection = sm_doc[sm_doc.index("SELECTION"):sm_doc.index("PRECEDENCE for a TOP selector")]
    ties = cm_doc[cm_doc.index("PRIORITY TIES"):]
    select_top_doc = " ".join(codex_model.select_top.__doc__.split())
    for where, text in (("seat_model SELECTION", selection), ("codex_model PRIORITY TIES", ties),
                        ("select_top", select_top_doc)):
        assert all(stamp in text for stamp in _FLAP_OBSERVATIONS), where
        assert "not stable" in text.lower() or "FLAPS" in text, where
        assert "tie ended" not in text, where            # the premise F16 was written on is FALSE

    # F7 (K46): the ceiling docstring states BOTH refusals and no longer claims K21's literal read
    ceiling = " ".join(sm._support_env_ceiling_refusal.__doc__.split())
    assert "K46" in ceiling and "K21" in ceiling         # names the rule and the one it supersedes
    assert "not exactly \"list\" is refused outright" in ceiling
    assert "regardless of visibility" in ceiling.lower()
    assert "is not refused by this rule" in ceiling      # unranked entries, unchanged

    # F15 (K47): the freeze-with-invalid-roster rule sits inside the THREE STATES block, and the
    # PROVENANCE block records that convene persists the key
    freeze = sm_doc[sm_doc.index("THE FREEZE EXCEPTION"):sm_doc.index("no_eligible a valid roster")]
    assert "honoured UNVALIDATED" in freeze and "EMERGENCY OVERRIDE" in freeze
    assert "roster_invalid" in freeze and "ABSENT" in freeze
    persisted = sm_doc[sm_doc.index("convene persists"):]
    assert "roster_invalid" in persisted and "K47" in persisted


# --------------------------------------------------------------------------- #
# S081 revision 4, stream A (WP-A2) - D16/D22: `--size` on the codex main seats.
#
# light/medium -> gpt-5.6-sol, complex / --user-request -> TOP, effort per role
# unchanged. Absent size resolves as complex with size_source `default`, which is
# the back-compat rule that keeps every un-migrated call site working - and is why
# the DEFAULT `emit --json` must stay byte-identical (plan L12).
# --------------------------------------------------------------------------- #
#: RE-POINTED by the astra reserve (roster rev 4): code_reviewer is the ONE sized seat. consultant_main is
#: Sol at every size (a user request still promotes it: USER_PROMOTED), escalation is TOP at every size.
SIZED = ("code_reviewer",)
USER_PROMOTED = ("code_reviewer", "consultant_main")
ROLE_EFFORT = {"code_reviewer": "xhigh", "consultant_main": "xhigh", "escalation": "max"}


def sized_home(home):
    write_codex_roster(home)
    write_agy_cache(home)
    return home


def write_forge_size(root, text):
    (root / ".forge").mkdir(exist_ok=True)
    (root / ".forge" / "size").write_text(text, encoding="utf-8")
    return root / ".forge" / "size"


@pytest.mark.parametrize("role", SIZED)
@pytest.mark.parametrize("size", ["light", "medium"])
def test_d16_a_light_or_medium_main_seat_serves_the_std_model(fixture_home, role, size):
    """D16: the whole point of the flag. The role's EFFORT does not move with it."""
    sized_home(fixture_home)
    pin = sm.resolve(role, "codex", size=size)
    assert pin.model == STD
    assert pin.effort == ROLE_EFFORT[role]
    assert pin.provenance["size"] == size
    assert pin.provenance["size_source"] == "routing"
    assert pin.provenance["resolved_model"] == STD
    assert "requested_by" not in pin.provenance


@pytest.mark.parametrize("role", SIZED)
def test_d16_complex_and_absent_both_serve_top_the_back_compat_control(fixture_home, role):
    """CONTROL for the test above, and the back-compat proof: `complex` and NO size
    both serve gpt-6-astra, and an absent size is `complex` / `default` (L7 rule 6)."""
    sized_home(fixture_home)
    explicit = sm.resolve(role, "codex", size="complex")
    assert explicit.model == "gpt-6-astra"
    assert explicit.effort == ROLE_EFFORT[role]
    assert (explicit.provenance["size"], explicit.provenance["size_source"]) == ("complex", "routing")

    assert sm.resolve_size(None) == sm.SizeDecision("complex", "default", None)
    unsized = sm.resolve(role, "codex")
    assert unsized.model == "gpt-6-astra"
    assert unsized.effort == ROLE_EFFORT[role]
    # BACK-COMPAT: an un-migrated caller's provenance is UNCHANGED, key for key. This is
    # what keeps the default `emit --json` byte-identical (plan L12).
    assert "size" not in unsized.provenance and "size_source" not in unsized.provenance


@pytest.mark.parametrize("role", USER_PROMOTED)
def test_d16_user_request_forces_top_at_every_size(fixture_home, role):
    """L7 rule 4: --user-request forces TOP regardless of size, and SAYS it did."""
    sized_home(fixture_home)
    pin = sm.resolve(role, "codex", size="light", user_request=True)
    assert pin.model == "gpt-6-astra"
    assert pin.effort == ROLE_EFFORT[role]
    assert pin.provenance["size"] == "light"          # the DECLARED size is still recorded
    assert pin.provenance["size_source"] == "user"
    assert pin.provenance["requested_by"] == "user"
    # CONTROL: the same light size WITHOUT the flag is the std model.
    assert sm.resolve(role, "codex", size="light").model == STD


@pytest.mark.parametrize("size", ["light", "medium", "complex"])
def test_d16_consultant_support_is_not_size_aware(fixture_home, size):
    """consultant_support is sol at EVERY size (design s2.1): it is not a TOP seat, so a
    size cannot move it. CONTROL: `complex` does not promote it to astra either."""
    sized_home(fixture_home)
    pin = sm.resolve("consultant_support", "codex", size=size)
    assert (pin.model, pin.effort) == (CODEX_SUP, "medium")
    assert "size" not in pin.provenance and "size_source" not in pin.provenance
    assert pin == sm.resolve("consultant_support", "codex")      # byte-for-byte unmoved


@pytest.mark.parametrize("size", ["light", "medium", "complex"])
def test_the_astra_reserve_consultant_main_is_sol_and_escalation_top_at_every_size(fixture_home, size):
    """The astra reserve (roster rev 4, U1): neither seat moves with the size - consultant_main is the Sol
    literal and escalation is the TOP reserve at every size, both at their role's own effort."""
    sized_home(fixture_home)
    sol = sm.resolve("consultant_main", "codex", size=size)
    assert (sol.model, sol.effort) == (STD, "xhigh") and "size" not in sol.provenance
    top = sm.resolve("escalation", "codex", size=size)
    assert (top.model, top.effort) == ("gpt-6-astra", "max") and "size" not in top.provenance
    assert top == sm.resolve("escalation", "codex")


@pytest.mark.parametrize("size", ["light", "medium", "complex"])
def test_d16_arbiter_is_not_size_aware_either(fixture_home, size):
    """ENUMERATED READING (WP-A2 report): the WP names code_reviewer, consultant_main and
    escalation. `arbiter` is a codex TOP seat that is NOT in that set, so a size is accepted
    and IGNORED rather than refused - the same treatment consultant_support gets, and never
    a silent downgrade of the seat that arbitrates."""
    sized_home(fixture_home)
    pin = sm.resolve("arbiter", "codex", size=size)
    assert (pin.model, pin.effort) == (STD, "xhigh")          # the astra reserve U4: Sol @ xhigh
    assert pin == sm.resolve("arbiter", "codex")


def test_d16_an_unknown_size_is_a_caller_bug_never_a_silent_default(fixture_home):
    sized_home(fixture_home)
    for bad in ("large", "LIGHT", "", "complex ", 3, True):
        with pytest.raises(sm.SeatModelError):
            sm.resolve("code_reviewer", "codex", size=bad)


def test_d16_size_applies_to_codex_and_agy_only(fixture_home):
    """A size on a claude seat is a caller bug; codex main seats and (#367 WP-C) agy seats are sized."""
    sized_home(fixture_home)
    with pytest.raises(sm.SeatModelError):
        sm.resolve("consultant_main", "claude", size="light")
    # CONTROL: the same seats resolve fine without a size.
    assert sm.resolve("consultant_main", "claude").model == MAIN
    assert sm.resolve("consultant_main", "agy").model == "gemini-4-argon-high"


AGY_LEVEL_BY_SIZE_LITERAL = {"light": "low", "medium": "medium", "complex": "high"}


@pytest.mark.parametrize("role,unsized", [("consultant_main", "high"), ("arbiter", "high"),
                                          ("consultant_support", "medium")])
def test_367c_the_agy_level_follows_the_size_and_the_role_level_stands_unsized(fixture_home, role, unsized):
    """#367 WP-C (roster rev 7): light -> low, medium -> medium, complex -> high on every agy role; with no
    size the role row's level stands. Literals, never re-derived from the roster."""
    sized_home(fixture_home)
    unsized_pin = sm.resolve(role, "agy")
    assert unsized_pin.model == f"gemini-4-argon-{unsized}"
    assert "size" not in unsized_pin.provenance and "size_source" not in unsized_pin.provenance
    for size, level in AGY_LEVEL_BY_SIZE_LITERAL.items():
        pin = sm.resolve(role, "agy", size=size)
        assert pin.model == f"gemini-4-argon-{level}", (role, size)
        assert pin.argv_fragment == ("--model", f"gemini-4-argon-{level}")
        assert (pin.provenance["size"], pin.provenance["size_source"]) == (size, "routing")
        assert pin.provenance["requested_selector"] == f"TOP-argon-{level}"
        assert pin.effort is None                      # the size picks the model (its level), never an effort


def test_367c_a_user_request_serves_the_high_agy_level_whatever_the_size(fixture_home):
    sized_home(fixture_home)
    pin = sm.resolve("consultant_support", "agy", size="light", user_request=True)
    assert pin.model == "gemini-4-argon-high"
    assert pin.provenance["requested_by"] == "user"


def test_367c_forge_size_drives_the_agy_level_only_when_the_call_opts_in(fixture_home, project):
    """`.forge/size` is read only by a call that opted in (a size or a user request), exactly as for
    codex; forge's size wins over the caller's, and a conflict takes the larger."""
    sized_home(fixture_home)
    write_forge_size(project, "complex\n")
    assert sm.resolve("consultant_support", "agy", size="light", project_root=project).model == \
        "gemini-4-argon-high"
    write_forge_size(project, "light\n")
    assert sm.resolve("consultant_main", "agy", size="light", project_root=project).model == "gemini-4-argon-low"
    # CONTROL: unsized, no forge file is read and the role level stands.
    assert sm.resolve("consultant_main", "agy").model == "gemini-4-argon-high"


def test_367c_the_cli_serves_the_sized_agy_level(fixture_home, capsys, monkeypatch):
    sized_home(fixture_home)
    monkeypatch.chdir(fixture_home)            # no .forge/size here
    base = ["argv", "--role", "consultant_main", "--provider", "agy"]
    assert cli(capsys, base + ["--size", "light"])[:2] == (sm.EXIT_OK, "--model gemini-4-argon-low\n")
    assert cli(capsys, base + ["--size", "medium"])[:2] == (sm.EXIT_OK, "--model gemini-4-argon-medium\n")
    assert cli(capsys, base + ["--size", "complex"])[:2] == (sm.EXIT_OK, "--model gemini-4-argon-high\n")
    assert cli(capsys, base)[:2] == (sm.EXIT_OK, "--model gemini-4-argon-high\n")
    support = ["argv", "--role", "consultant_support", "--provider", "agy"]
    assert cli(capsys, support + ["--size", "light"])[:2] == (sm.EXIT_OK, "--model gemini-4-argon-low\n")
    assert cli(capsys, support)[:2] == (sm.EXIT_OK, "--model gemini-4-argon-medium\n")


def test_367c_a_bad_level_map_fails_the_roster_invariants():
    import types
    good = dict(AGY_LEVEL_BY_SIZE_LITERAL)
    assert sm.agy_level_violations(good, {"agy_level_by_size": dict(good)}) == []
    for bad in ({"light": "low", "medium": "medium"}, {**good, "complex": "xhigh"}, None,
                {**good, "huge": "high"}):
        assert sm.agy_level_violations(bad, {"agy_level_by_size": bad}), bad
    # The last HISTORY row must record the live map.
    assert sm.agy_level_violations(good, {"agy_level_by_size": {**good, "light": "medium"}})
    assert sm.agy_level_violations(good, {})


# --------------------------------------------------------------------------- #
# L7 - where the size comes from, resolved ONCE
# --------------------------------------------------------------------------- #
def test_l7_forge_size_is_read_from_the_project_root(fixture_home, project):
    """L7 rule 2. A FIXTURE root drives it; no stage writes the real one."""
    write_forge_size(project, "light\n")
    assert sm.resolve_size(None, project_root=project) == sm.SizeDecision("light", "forge", None)
    sized_home(fixture_home)
    pin = sm.resolve("code_reviewer", "codex", project_root=project)
    assert pin.model == STD
    assert (pin.provenance["size"], pin.provenance["size_source"]) == ("light", "forge")


def test_l7_only_the_first_line_is_read_and_a_malformed_file_is_absent(fixture_home, project):
    """`.forge/size` is one line of light|medium|complex; anything else is ignored AS ABSENT
    (never a hard failure - a junk file must not break every seat in the cycle)."""
    write_forge_size(project, "medium\nignored trailing junk\n")
    assert sm.resolve_size(None, project_root=project).size == "medium"
    for junk in ("", "   \n", "large\n", "LIGHT\n", "light medium\n", "\nlight\n"):
        write_forge_size(project, junk)
        assert sm.resolve_size(None, project_root=project) == \
            sm.SizeDecision("complex", "default", None), junk
    # CONTROL: a VALID file changes the result, so the absent-verdict above is a real read.
    write_forge_size(project, "light")
    assert sm.resolve_size(None, project_root=project) == sm.SizeDecision("light", "forge", None)
    # An unreadable .forge/size (a directory) is absent too, not a crash.
    (project / ".forge" / "size").unlink()
    (project / ".forge" / "size").mkdir()
    assert sm.resolve_size(None, project_root=project).size_source == "default"


def test_l7_inside_forge_forge_wins_and_a_conflict_takes_the_larger(fixture_home, project):
    """L7: 'Inside forge, forge's size wins over a caller's; a genuine conflict resolves to
    the LARGER size.' Both directions, because 'larger' is the rule, not 'forge's value'."""
    write_forge_size(project, "complex\n")
    assert sm.resolve_size("light", project_root=project) == sm.SizeDecision("complex", "forge", None)
    write_forge_size(project, "light\n")
    assert sm.resolve_size("complex", project_root=project) == sm.SizeDecision("complex", "forge", None)
    write_forge_size(project, "medium\n")
    assert sm.resolve_size("medium", project_root=project) == sm.SizeDecision("medium", "forge", None)
    # CONTROL: OUTSIDE forge the caller's size stands on its own, sourced `routing`.
    assert sm.resolve_size("light", project_root=project / "nowhere") == \
        sm.SizeDecision("light", "routing", None)


def test_l7_user_request_outranks_forge_and_the_routing_class(fixture_home, project):
    write_forge_size(project, "complex\n")
    assert sm.resolve_size("light", project_root=project, user_request=True) == \
        sm.SizeDecision("complex", "user", "user")
    assert sm.resolve_size(None, user_request=True) == sm.SizeDecision("complex", "user", "user")


def test_d22_risk_promotion_is_delegated_to_review_risk(fixture_home, project):
    """L7 rule 5 / D22. seat_model does NOT reimplement the promotion contract: it hands the
    change set to review_risk.assess, which owns 'upward only, and size_source risk ONLY when
    the size actually moved' (WP-A1). These cases prove the wiring, not the tagger."""
    risky = ["skills/_meta/gates.py"]
    assert sm.resolve_size("light", paths=risky) == sm.SizeDecision("complex", "risk", None)
    # CONTROL 1: a NEIGHBOURING path that fires no family does not promote.
    assert sm.resolve_size("light", paths=["docs/plans/2026-09-15-note.md"]) == \
        sm.SizeDecision("light", "routing", None)
    # CONTROL 2: promotion never LOWERS, and never rewrites a source it did not move.
    assert sm.resolve_size("complex", paths=risky) == sm.SizeDecision("complex", "routing", None)
    # CONTROL 3: --user-request already forces TOP, so risk does not restate it.
    assert sm.resolve_size("light", paths=risky, user_request=True) == \
        sm.SizeDecision("light", "user", "user")
    sized_home(fixture_home)
    pin = sm.resolve("code_reviewer", "codex", size="light", changed_paths=risky)
    assert pin.model == "gpt-6-astra"                       # promoted to complex -> TOP
    assert (pin.provenance["size"], pin.provenance["size_source"]) == ("complex", "risk")


def test_d16_protection_is_unchanged_by_a_sized_resolution(fixture_home, monkeypatch):
    """`--size` is an ARGUMENT, never an env lever. A protected seat still refuses an env
    value that disagrees with the SIZED resolution - the flag must not become a new way to
    move a protected seat."""
    sized_home(fixture_home)
    assert set(SIZED) <= sm.PROTECTED
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-5.6-terra")
    pin = sm.resolve("code_reviewer", "codex", size="light", env_var="SEAT_TEST_ENV")
    assert pin.model == STD                       # the sized resolution, not the env
    assert pin.provenance["source"] != "env"
    assert pin.provenance["env_override_refused"]["value"] == "gpt-5.6-terra"
    # CONTROL: an env value EQUAL to the sized resolution is honoured, as for any protected seat.
    monkeypatch.setenv("SEAT_TEST_ENV", STD)
    equal = sm.resolve("code_reviewer", "codex", size="light", env_var="SEAT_TEST_ENV")
    assert equal.model == STD and equal.provenance["source"] == "env"


def test_d16_substitute_carries_the_size_it_refused(fixture_home, project):
    """`substitute` must say WHICH SIZE was refused, or the 2026-09-28 review cannot tell a
    refused std call from a refused TOP one.

    SCOPE BOUNDARY, stated rather than blurred: WP-A2 carries size / size_source in seat_model
    PROVENANCE. The budget ROW's `size` / `size_source` FIELDS belong to the design s2.2 row
    schema, which lives in `codex_quota.record_substitution` - WP-A3's file, not this WP's.
    So this asserts the provenance now, and that the row still writes and still parses."""
    sized_home(fixture_home)
    pin = sm.substitute("code_reviewer", "advisory_review", "threshold",
                        project_root=project, size="light", size_source="forge")
    assert pin.model == MAIN
    assert (pin.provenance["size"], pin.provenance["size_source"]) == ("light", "forge")
    assert pin.provenance["row_written"] is True
    store = (fixture_home / ".claude" / "projects" / codex_quota.project_slug(project)
             / "astra-budget.jsonl")
    row = json.loads(store.read_text(encoding="utf-8").splitlines()[-1])
    assert row["kind"] == "substitution" and row["use"] == "advisory_review"
    # CONTROL: an UNSIZED substitution still carries the back-compat default, so a row written
    # by an un-migrated call site is never mistaken for a refused light call.
    plain = sm.substitute("code_reviewer", "advisory_review", "threshold", project_root=project)
    assert (plain.provenance["size"], plain.provenance["size_source"]) == ("complex", "default")
    assert len(store.read_text(encoding="utf-8").splitlines()) == 2


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("role", SIZED)
@pytest.mark.parametrize("size,model", [("light", STD), ("medium", STD),
                                        ("complex", "gpt-6-astra")])
def test_d16_cli_argv_and_timeout_take_size(fixture_home, capsys, role, size, model):
    sized_home(fixture_home)
    code, out, err = cli(capsys, ["argv", "--role", role, "--provider", "codex", "--size", size])
    assert (code, out.strip()) == (sm.EXIT_OK, " ".join(
        codex_model.argv_fragment(model, ROLE_EFFORT[role]))), err
    code, out, err = cli(capsys, ["timeout", "--role", role, "--provider", "codex", "--size", size])
    assert code == sm.EXIT_OK and out.strip() == str(
        codex_model.timeout_for(model, ROLE_EFFORT[role])), err


def test_d16_cli_user_request_forces_top(fixture_home, capsys):
    sized_home(fixture_home)
    code, out, _ = cli(capsys, ["argv", "--role", "code_reviewer", "--provider", "codex",
                                "--size", "light", "--user-request"])
    assert (code, "gpt-6-astra" in out) == (sm.EXIT_OK, True)
    # CONTROL: the same call without the flag is the std model.
    assert STD in cli(capsys, ["argv", "--role", "code_reviewer", "--provider", "codex",
                                         "--size", "light"])[1]


@pytest.mark.parametrize("args,expect", [
    (["argv", "--role", "code_reviewer", "--provider", "codex", "--size", "large"], "size"),
    (["argv", "--role", "code_reviewer", "--provider", "codex", "--size", ""], "size"),
    (["timeout", "--role", "code_reviewer", "--provider", "agy", "--size", "light"], "codex"),
    (["emit", "--json", "--size", "large"], "size"),
])
def test_d16_cli_size_usage_errors_exit_2_with_empty_stdout(fixture_home, capsys, args, expect):
    """An unknown size, and a size on a non-codex seat, are usage errors - never a silent
    default, and never a pin, because `PIN="$(...)" && codex exec $PIN` must not run.

    `expect` and the `unrecognized` assertion exist because WITHOUT them every case here
    passed against the PRE-CHANGE code, for the wrong reason: argparse rejected `--size`
    as an unknown flag. A test that a missing feature satisfies proves nothing (the same
    defect WP-A02 caught in its own RULING-3 test), so each case now pins the SEMANTIC
    rule that must still hold once the flag exists."""
    sized_home(fixture_home)
    code, out, err = cli(capsys, args)
    assert (code, out) == (sm.EXIT_USAGE, "")
    assert expect in err.lower()
    assert "unrecognized" not in err.lower()


def test_d16_the_model_subcommand_never_takes_a_size(fixture_home, capsys):
    """`model` is the Claude-only accessor; it gains no `--size` in this WP or any other, so
    this one stays a PARSER-level rejection by design. Recorded as such rather than left to
    look like the semantic checks above."""
    sized_home(fixture_home)
    code, out, err = cli(capsys, ["model", "--role", "consultant_main", "--provider", "claude",
                                  "--size", "light"])
    assert (code, out) == (sm.EXIT_USAGE, "") and "unrecognized" in err.lower()


def test_d16_cli_user_request_on_agy_serves_the_high_level(fixture_home, capsys, monkeypatch):
    """#367 WP-C: --user-request is accepted on an agy seat (the high level), as on codex (TOP)."""
    sized_home(fixture_home)
    monkeypatch.chdir(fixture_home)
    code, out, _ = cli(capsys, ["argv", "--role", "consultant_support", "--provider", "agy",
                                "--user-request"])
    assert (code, out) == (sm.EXIT_OK, "--model gemini-4-argon-high\n")
    # CONTROL: the same flag on the codex seat is accepted and forces TOP.
    assert "gpt-6-astra" in cli(capsys, ["argv", "--role", "consultant_main", "--provider",
                                         "codex", "--size", "light", "--user-request"])[1]


def test_l7_cli_reads_forge_size_from_the_working_directory(fixture_home, project, capsys, monkeypatch):
    """The CLI's forge root is the WORKING DIRECTORY - forge runs in the project root, the same
    way `.forge/cycle-id` is found. No --project-root flag is added to `timeout`/`emit`: r12
    pins it as a usage error there and that assertion still stands.

    SIZING IS OPT-IN. A call that passes no size reads NO `.forge/size` and resolves exactly as
    it did before D16 - which is why the un-flagged control below is astra even standing in a
    forge cycle that says `light`, and why `test_use_paths_read_the_working_directory_only_for
    _the_budget_key` still holds."""
    sized_home(fixture_home)
    write_forge_size(project, "complex\n")
    monkeypatch.chdir(project)
    argv = ["argv", "--role", "code_reviewer", "--provider", "codex"]
    # Opted in at `light`, but forge's cycle says complex: forge wins, so the seat is TOP.
    assert "gpt-6-astra" in cli(capsys, argv + ["--size", "light"])[1]
    write_forge_size(project, "light\n")
    assert STD in cli(capsys, argv + ["--size", "light"])[1]
    # CONTROL 1: from a directory with no .forge/size the same sized call is unaffected by it.
    monkeypatch.chdir(fixture_home)
    assert STD in cli(capsys, argv + ["--size", "light"])[1]
    # CONTROL 2: un-flagged, inside the very cycle that says `light`, nothing is read: astra.
    monkeypatch.chdir(project)
    assert "gpt-6-astra" in cli(capsys, argv)[1]
    assert cli(capsys, ["timeout", "--role", "arbiter", "--provider", "codex",
                        "--project-root", str(project)])[0] == sm.EXIT_USAGE


# --------------------------------------------------------------------------- #
# The L12 invariant, asserted in the suite and not only in the stage report
# --------------------------------------------------------------------------- #
def test_l12_the_default_emit_is_unchanged_and_only_a_sized_emit_gains_keys(fixture_home):
    """PLAN L12, the load-bearing one: `emit --json` WITHOUT a size must be byte-identical to
    what it was before this WP, so every un-migrated call site keeps resolving astra. The ONLY
    permitted addition is a TOP-LEVEL size / size_source pair, and it appears ONLY when a size
    was asked for. A per-pin provenance key added on the default path would break this."""
    sized_home(fixture_home)
    default = sm.emit()
    # #291 adds ONE top-level key to every emit, sized or not: roster_rev (the roster REVISION).
    # #367 WP-C adds the agy size -> level map, also on every emit.
    assert set(default) == {"schema", "pins", "roster_rev", "agy_level_by_size"}
    assert default["agy_level_by_size"] == {"light": "low", "medium": "medium", "complex": "high"}
    assert default["roster_rev"] == model_roster.REVISION
    for role, providers in default["pins"].items():
        for provider, pin in providers.items():
            assert "size" not in pin["provenance"], (role, provider)
            assert "size_source" not in pin["provenance"], (role, provider)
    for role in SIZED:
        assert default["pins"][role]["codex"]["model"] == "gpt-6-astra"

    light = sm.emit(size="light")
    assert (light["size"], light["size_source"]) == ("light", "routing")
    assert set(light) == {"schema", "pins", "roster_rev", "agy_level_by_size", "size", "size_source"}
    for role in SIZED:
        assert light["pins"][role]["codex"]["model"] == STD
    # The seats that are NOT size-aware are identical in both emits (agy is: #367 WP-C, the level).
    for provider in ("claude", "codex"):
        assert light["pins"]["consultant_support"][provider] == default["pins"]["consultant_support"][provider]
    for role in ("consultant_main", "consultant_support", "arbiter"):
        assert light["pins"][role]["agy"]["model"] == "gemini-4-argon-low", role
    assert light["pins"]["arbiter"]["codex"]["model"] == STD            # the astra reserve: Sol at every size
    assert light["pins"]["escalation"]["codex"]["model"] == "gpt-6-astra"  # the reserve: TOP at every size
    for role in ("code_reviewer", "consultant_main", "arbiter", "escalation"):
        assert light["pins"][role].get("claude") == default["pins"][role].get("claude")


def test_l12_the_cli_default_emit_is_byte_identical_to_the_unsized_api(fixture_home, capsys):
    sized_home(fixture_home)
    code, out, _ = cli(capsys, ["emit", "--json"])
    assert code == sm.EXIT_OK
    assert json.loads(out) == sm.emit()
    code, sized, _ = cli(capsys, ["emit", "--json", "--size", "medium"])
    assert json.loads(sized)["size"] == "medium"
    assert json.loads(sized) != json.loads(out)


def test_l7_the_resolution_order_is_documented_once_in_the_module_docstring(fixture_home):
    """The criterion says the order is implemented ONCE and DOCUMENTED. A rule that lives only
    in code is the thing every call site then re-derives differently."""
    doc = " ".join(sm.__doc__.split())
    block = doc[doc.index("SIZE (D16"):]
    # #302 WP-2 (R3): the docstring names the TIER (CODEX_STD, CODEX_SUPPORT), not a slug that a swap
    # would leave stale.
    for token in ("light", "medium", "complex", "CODEX_STD", "CODEX_SUPPORT", "--user-request",
                  "forge", "routing", "user", "risk", "default"):
        assert token in block, token
    assert "LARGER" in block


# =========================================================================== #
# S081 revision 4, WP-A3 — the size and the model class reach the budget row
# (design §2.2; D16, D20). seat_model RESOLVES them; codex_quota RECORDS them.
# =========================================================================== #
def test_a3_the_size_sources_have_one_definition(fixture_home):
    """codex_quota owns the budget-ROW contract, so it owns the legal `size_source` values;
    seat_model borrows them. Two literals would be two things to keep in step."""
    assert sm.SIZE_SOURCES == frozenset(codex_quota.SIZE_SOURCES)
    assert sm.SIZE_SOURCES == {"forge", "routing", "user", "risk", "default"}


@pytest.mark.parametrize("size,expected", [("light", "std"), ("medium", "std"), ("complex", "top")])
def test_a3_the_model_class_follows_the_model_that_actually_resolved(fixture_home, size, expected):
    """D16. The class is read off the RESOLVED model, never re-derived from the size — which
    is what keeps a seat that ignores the size billed correctly (the next test)."""
    write_codex_roster(fixture_home)
    pin = sm.resolve("code_reviewer", "codex", size=size)
    assert sm.model_class_of(pin.model) == expected


def test_a3_a_seat_that_ignores_the_size_is_still_billed_as_top(fixture_home):
    """THE CONTROL that makes the rule above load-bearing: `arbiter` is outside SIZED_ROLES,
    so `--size light` does NOT move it off astra — and a size-derived class would have billed
    it to the std budget it never touched."""
    write_codex_roster(fixture_home)
    pin = sm.resolve("escalation", "codex", size="light")   # the astra reserve: TOP at every size
    assert pin.model != sm.CODEX_STD_MODEL
    assert sm.model_class_of(pin.model) == "top"


def test_a3_an_unsized_argv_use_records_the_back_compat_row(fixture_home, project, codex_cli, capsys):
    """An un-migrated call site passes no size: the row records complex / default / top, which
    is what that call actually is, and the budget it spends is unchanged from before D16."""
    write_codex_roster(fixture_home)
    assert cli(capsys, argv_use("code_reviewer", "consult", project))[0] == sm.EXIT_OK
    row = admit_rows(store_rows(project))[-1]
    assert (row["size"], row["size_source"], row["model_class"]) == ("complex", "default", "top")
    assert row["requested_model"] == sm.resolve("code_reviewer", "codex").model
    assert "requested_by" not in row


def test_a3_a_sized_argv_use_records_the_size_and_spends_the_std_budget(fixture_home, project,
                                                                       codex_cli, capsys):
    write_codex_roster(fixture_home)
    code, out, _ = cli(capsys, argv_use("consultant_main", "consult", project, "--size", "light"))
    assert code == sm.EXIT_OK and sm.CODEX_STD_MODEL in out
    row = admit_rows(store_rows(project))[-1]
    assert (row["size"], row["size_source"], row["model_class"]) == ("light", "routing", "std")
    assert row["requested_model"] == sm.CODEX_STD_MODEL


def test_a3_a_user_request_records_requested_by_on_the_row(fixture_home, project, codex_cli, capsys):
    write_codex_roster(fixture_home)
    code, _, _ = cli(capsys, argv_use("consultant_main", "consult", project,
                                      "--size", "light", "--user-request"))
    assert code == sm.EXIT_OK
    row = admit_rows(store_rows(project))[-1]
    assert (row["requested_by"], row["size_source"], row["model_class"]) == ("user", "user", "top")


def test_a3_the_two_classes_do_not_spend_each_other_on_one_cycle(fixture_home, project,
                                                                 codex_cli, capsys):
    """THE D16 RULE END TO END, through the CLI the call sites actually use: the complex call
    spends the TOP slot and the light call still runs on the SAME cycle id."""
    write_codex_roster(fixture_home)
    assert cli(capsys, argv_use("code_reviewer", "consult", project))[0] == sm.EXIT_OK
    assert cli(capsys, argv_use("code_reviewer", "consult", project))[0] == sm.EXIT_SUBSTITUTE
    assert cli(capsys, argv_use("code_reviewer", "consult", project, "--size", "light"))[0] == sm.EXIT_OK
    classes = [r["model_class"] for r in admit_rows(store_rows(project)) if r["admitted"]]
    assert classes == ["top", "std"]


def test_a3_the_avengers_deliberation_use_is_now_admit_gated(fixture_home, project, codex_cli, capsys):
    """RE-POINTED from _USAGE_CASES: `--use deliberation` was rejected as an unknown use while
    `deliberation` was in SUBSTITUTION_USES but not in USES. Design §2.2 budgets it at one seat
    per session, so it now admits — and the SECOND seat on the same session is refused, which is
    the limit doing its job rather than the flag merely being accepted."""
    write_codex_roster(fixture_home)
    session = "avengers-2026-09-16T10:00:00"
    first = cli(capsys, argv_use("consultant_main", "deliberation", project, "--cycle-id", session))
    assert first[0] == sm.EXIT_OK
    second = cli(capsys, argv_use("consultant_main", "deliberation", project, "--cycle-id", session))
    assert second[0] == sm.EXIT_SUBSTITUTE
    rows = admit_rows(store_rows(project))
    assert [r["use"] for r in rows] == ["deliberation", "deliberation"]
    assert [r["admitted"] for r in rows] == [True, False]
    assert rows[-1]["reason"] == "budget_spent"


@pytest.mark.parametrize("use", ["review_std", "brainstorm", "ballot"])
def test_a3_the_new_uses_reach_the_argv_gate(fixture_home, project, codex_cli, capsys, use):
    write_codex_roster(fixture_home)
    size = ["--size", "light"] if use == "review_std" else []
    code, _, _ = cli(capsys, argv_use("consultant_main", use, project, "--cycle-id",
                                      f"{use}-0f9c4b2a8e1d4f6ab3c5d7e9f1a2b3c4", *size))
    assert code == sm.EXIT_OK
    assert admit_rows(store_rows(project))[-1]["use"] == use


def test_a3_a_substitution_row_records_the_refused_size_and_the_requester(fixture_home, project):
    pin = sm.substitute("consultant_main", "ballot", "threshold", project_root=project,
                        cycle_id="ballot-0f9c4b2a8e1d4f6ab3c5d7e9f1a2b3c4", size="light",
                        size_source="user", requested_by="user")
    assert pin.provenance["size"] == "light"
    row = store_rows(project)[-1]
    assert (row["size"], row["size_source"], row["requested_by"]) == ("light", "user", "user")
    assert row["key"] == "ballot-0f9c4b2a8e1d4f6ab3c5d7e9f1a2b3c4"
    # The pin's provenance and the ROW agree — one resolved pair, written in both places.
    assert (row["size"], row["size_source"]) == (pin.provenance["size"], pin.provenance["size_source"])


def test_a3_an_unsized_substitution_still_records_the_default_pair(fixture_home, project):
    pin = sm.substitute("consultant_main", "consult", "threshold", project_root=project)
    row = store_rows(project)[-1]
    assert (row["size"], row["size_source"]) == ("complex", "default")
    assert "requested_by" not in row                       # CONTROL: no user asked for this one
    assert pin.provenance["size"] == "complex"


def test_a3_a_top_seat_frozen_to_sol_is_billed_as_a_std_call(fixture_home, project, codex_cli, capsys):
    """A CONSEQUENCE OF THE RULE, PINNED SO IT IS A DECISION RATHER THAN AN ACCIDENT.

    A home-tier freeze can point a codex TOP seat at sol. The seat then genuinely RUNS sol, so
    it spends the std budget (2) and not the astra one (1) — the budget rations astra, and a
    call that spends no astra should not charge the astra slot. This is what
    `test_line_2_is_the_claude_row_and_never_a_codex_model[*-gpt-5.6-sol]` was re-pointed for.
    CONTROL: without the freeze the same call is TOP class and the limit is 1.
    """
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {"codex": sm.CODEX_STD_MODEL})
    for _ in range(2):
        assert cli(capsys, argv_use("consultant_main", "consult", project, "--cycle-id", "c1"))[0] == sm.EXIT_OK
    assert cli(capsys, argv_use("consultant_main", "consult", project,
                                "--cycle-id", "c1"))[0] == sm.EXIT_SUBSTITUTE
    assert {r["model_class"] for r in admit_rows(store_rows(project))} == {"std"}


def test_a3_without_a_freeze_the_same_seat_is_top_class(fixture_home, project, codex_cli, capsys):
    """The CONTROL for the test above."""
    write_codex_roster(fixture_home)
    assert cli(capsys, argv_use("code_reviewer", "consult", project, "--cycle-id", "c1"))[0] == sm.EXIT_OK
    assert cli(capsys, argv_use("code_reviewer", "consult", project,
                                "--cycle-id", "c1"))[0] == sm.EXIT_SUBSTITUTE
    assert {r["model_class"] for r in admit_rows(store_rows(project))} == {"top"}


# --------------------------------------------------------------------------- #
# S081 revision 4, WP-A5: the CALLER populates the budget row's seat
#
# codex_quota gained `role` on the admit row; without this wiring no production
# caller passes it, so every real row would carry no seat and the 2026-09-28
# review would see exactly what it sees today. `role` is already in hand at the
# top of this function -- it was simply not forwarded.
# --------------------------------------------------------------------------- #
def test_a5_every_admit_gated_seat_is_an_admit_role():
    """The coupling that makes `role=role` TOTAL. `--use` is gated to seats whose codex row
    is KIND_TOP, and admit() rejects a role outside its vocabulary — so if a seat could be
    admit-gated WITHOUT being an admit role, the wiring would raise on a previously working
    call. Derived from the live tables, not restated, so a new seat cannot slip between them."""
    # RE-POINTED by the astra reserve F1: `--use` is gated on the ROLE (ADMITTED_ROLES), not the row kind.
    admit_gated = set(sm.ADMITTED_ROLES)
    assert admit_gated, "GUARD: no admit-gated seats found — the derivation looked in the wrong place"
    assert admit_gated <= set(codex_quota.ADMIT_ROLES)
    assert admit_gated == set(codex_quota.SUBSTITUTION_ROLES)
    top_rows = {r for r in sm.ROLES if sm._row(r, sm.CODEX).kind == sm.KIND_TOP}
    assert top_rows == set(TOP_CODEX_ROLES) and top_rows < admit_gated


@pytest.mark.parametrize("role", TOP_CODEX_ROLES)
def test_a5_a_real_resolution_records_the_role_on_the_budget_row(fixture_home, project, codex_cli, capsys, role):
    """A REAL resolution through the CLI — not a direct admit() call — writes a row naming
    the seat. This is the half that was missing: the schema already allowed `role`."""
    write_codex_roster(fixture_home)
    assert cli(capsys, argv_use(role, "consult", project, "--cycle-id", "cyc-1"))[0] == sm.EXIT_OK
    rows = admit_rows(store_rows(project))
    assert [r["role"] for r in rows] == [role]
    assert rows[0]["admitted"] is True


def test_a5_the_arbiter_frozen_to_sol_produces_a_row_naming_the_seat(fixture_home, project, codex_cli, capsys):
    """THE CASE THE WHOLE WP EXISTS FOR, end to end. A home-tier freeze holds codex on sol,
    so the arbiter — an UNSIZED seat — is billed `std` (L18: the budget rations what is
    actually SPENT). Before this wiring that row was indistinguishable from an ordinary
    support-seat sol call; now the row names the seat that spent it."""
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {"codex": STD})
    assert cli(capsys, argv_use("arbiter", "consult", project, "--cycle-id", "frozen-1"))[0] == sm.EXIT_OK
    row = admit_rows(store_rows(project))[-1]
    assert (row["role"], row["model_class"], row["requested_model"]) == ("arbiter", "std", STD)


def test_a5_the_seat_is_named_whether_or_not_a_freeze_is_in_force(fixture_home, project, codex_cli, capsys):
    """CONTROL for the test above: `role` is a property of the SEAT, not an artefact of the
    freeze. Unfrozen, the same seat resolves to astra and is billed `top` — and the row still
    names it, so a reader cannot mistake the field for a freeze marker."""
    write_codex_roster(fixture_home)
    assert cli(capsys, argv_use("escalation", "consult", project, "--cycle-id", "unfrozen-1"))[0] == sm.EXIT_OK
    row = admit_rows(store_rows(project))[-1]
    assert (row["role"], row["model_class"], row["requested_model"]) == ("escalation", "top", "gpt-6-astra")


def test_a5_a_refused_resolution_still_names_the_seat(fixture_home, project, codex_cli, capsys):
    """A refusal is exactly when the review asks WHICH SEAT went without. The second call on
    the same key is budget-refused, and its row must name the seat like any other."""
    write_codex_roster(fixture_home)
    assert cli(capsys, argv_use("code_reviewer", "advisory_review", project, "--cycle-id", "r1"))[0] == sm.EXIT_OK
    assert cli(capsys, argv_use("code_reviewer", "advisory_review", project,
                                "--cycle-id", "r1"))[0] == sm.EXIT_SUBSTITUTE
    rows = admit_rows(store_rows(project))
    assert [(r["role"], r["admitted"]) for r in rows] == [("code_reviewer", True), ("code_reviewer", False)]
    assert rows[-1]["reason"] == "budget_spent"


# =========================================================================== #
# S081 revision 4 - D21 FIX ROUND 1, WP-X4 (docs/reviews/2026-09-22-S081-rev4-review.md)
#
# F7 (MAJOR): `class_not_budgeted` - advisory_review served by the std class (a sol freeze, or a
#   light/medium size), review_std served by TOP - reached substitute(), which refused it as an unknown
#   reason: `argv --use` exited 1 with EMPTY stdout, so the seat neither ran nor was substituted. It is
#   now a SUBSTITUTION_REASONS member and takes the EXISTING D6 path (plan L36): exit 3, the reason and
#   the Claude model on stdout, one substitution row, nothing admitted unbudgeted.
# f6 (minor): a SIZED `argv --use` / `substitute` read `.forge/size` from the working directory while
#   keying the budget and naming the store from --project-root. It now reads the root it bills (L37).
# f7 (minor): substitute() given a size without its size_source (or the reverse) recorded a guessed
#   `default` for the missing half. A half pair is now a caller bug and records nothing (L37).
# f1 (minor): the module docstring said an unflagged `argv` / `timeout` reads `.forge/size`. Sizing is
#   opt-in on every subcommand; the docstring now says what the CLI does (L38).
# The test names say F7_major / f7_minor: the two findings share a number and nothing else.
# =========================================================================== #
X4_CODE_REVIEWER_ASTRA = "-m gpt-6-astra -c model_reasoning_effort=xhigh"
X4_CODE_REVIEWER_SOL = f"-m {STD} -c model_reasoning_effort=xhigh"

#: (label, pins, use, extra flags): the three pairings the review reproduced, each landing a code_reviewer
#: seat in a class its use has no budget for.
X4_F7_UNBUDGETED = [
    ("sol_freeze_advisory_review_unsized", {"codex": STD}, "advisory_review", []),
    ("top_review_std_unsized", None, "review_std", []),
    ("light_advisory_review", None, "advisory_review", ["--size", "light"]),
]


@pytest.mark.parametrize("label,pins,use,extra", X4_F7_UNBUDGETED, ids=[c[0] for c in X4_F7_UNBUDGETED])
def test_x4_F7_major_an_unbudgeted_class_substitutes_instead_of_crashing(fixture_home, project, codex_cli, capsys,
                                                                         label, pins, use, extra):
    write_codex_roster(fixture_home)
    if pins is not None:
        write_pins(fixture_home, pins)
    code, out, err = cli(capsys, argv_use("code_reviewer", use, project, "--cycle-id", "x4-f7", *extra))
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"class_not_budgeted\n{MAIN}\n"), err
    assert "astra unavailable (class_not_budgeted)" in err
    rows = store_rows(project)
    # The admit refusal is recorded as before; nothing was admitted unbudgeted (design s2.2 kept).
    assert [(r["admitted"], r["reason"]) for r in admit_rows(rows)] == [(False, "class_not_budgeted")]
    subs = substitution_rows(rows)
    assert [(s["reason"], s["use"], s["role"], s["served_model"], s["admission_id"], s["cycle_id"]) for s in subs] == \
        [("class_not_budgeted", use, "code_reviewer", MAIN, None, "x4-f7")]
    assert subs[0]["requested_model"] == admit_rows(rows)[0]["requested_model"]


@pytest.mark.parametrize("use,size,pin,model_class", [
    ("advisory_review", "complex", X4_CODE_REVIEWER_ASTRA, "top"),
    ("review_std", "light", X4_CODE_REVIEWER_SOL, "std"),
])
def test_x4_F7_control_the_budgeted_pairings_are_admitted(fixture_home, project, codex_cli, capsys, use, size, pin,
                                                          model_class):
    """CONTROL: the table's own pairings are untouched - admitted, exit 0, the pin, no substitution."""
    write_codex_roster(fixture_home)
    code, out, err = cli(capsys, argv_use("code_reviewer", use, project, "--cycle-id", "x4-f7c", "--size", size))
    assert (code, out) == (sm.EXIT_OK, pin + "\n"), err
    rows = store_rows(project)
    assert [(r["admitted"], r["reason"], r["model_class"]) for r in admit_rows(rows)] == \
        [(True, "within_budget", model_class)]
    assert substitution_rows(rows) == []


def test_x4_F7_major_the_substitute_cli_accepts_class_not_budgeted(fixture_home, project, capsys):
    """The call-time form derives its --reason choices from codex_quota.SUBSTITUTION_REASONS, so it
    gains the value with no second list."""
    code, out, err = cli(capsys, ["substitute", "--role", "code_reviewer", "--use", "advisory_review", "--reason",
                                  "class_not_budgeted", "--project-root", str(project)])
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"class_not_budgeted\n{MAIN}\n"), err
    assert [s["reason"] for s in substitution_rows(store_rows(project))] == ["class_not_budgeted"]


def test_x4_F7_control_the_substitute_cli_still_refuses_an_unknown_reason(fixture_home, project, capsys):
    code, out, err = cli(capsys, ["substitute", "--role", "code_reviewer", "--use", "advisory_review", "--reason",
                                  "class_budgeted_elsewhere", "--project-root", str(project)])
    assert (code, out) == (sm.EXIT_USAGE, "") and "invalid choice" in err
    assert store_rows(project) == []


# --- f6: a sized call reads `.forge/size` from the root it bills -------------------------------------- #
@pytest.fixture()
def elsewhere(tmp_path):
    """A working directory that is NOT the project root."""
    root = tmp_path / "elsewhere"
    root.mkdir()
    return root


def test_x4_f6_minor_a_sized_use_call_reads_forge_size_from_its_project_root(fixture_home, project, elsewhere,
                                                                            codex_cli, capsys, monkeypatch):
    write_codex_roster(fixture_home)
    write_forge_size(project, "complex\n")          # the cycle this call bills says complex
    monkeypatch.chdir(elsewhere)                    # ... and the shell stands somewhere else
    code, out, err = cli(capsys, argv_use("code_reviewer", "consult", project, "--cycle-id", "x4-f6",
                                          "--size", "light"))
    assert (code, out) == (sm.EXIT_OK, X4_CODE_REVIEWER_ASTRA + "\n"), err
    row = admit_rows(store_rows(project))[-1]
    assert (row["size"], row["size_source"], row["model_class"]) == ("complex", "forge", "top")


def test_x4_f6_minor_the_working_directory_is_not_consulted_when_a_project_root_is_given(
        fixture_home, project, elsewhere, codex_cli, capsys, monkeypatch):
    """The mirror: a `.forge/size` in the working directory must not size a call that bills ANOTHER root."""
    write_codex_roster(fixture_home)
    write_forge_size(elsewhere, "complex\n")
    monkeypatch.chdir(elsewhere)
    code, out, err = cli(capsys, argv_use("code_reviewer", "consult", project, "--cycle-id", "x4-f6m",
                                          "--size", "light"))
    assert (code, out) == (sm.EXIT_OK, X4_CODE_REVIEWER_SOL + "\n"), err
    row = admit_rows(store_rows(project))[-1]
    assert (row["size"], row["size_source"], row["model_class"]) == ("light", "routing", "std")


def test_x4_f6_minor_a_sized_substitute_records_the_size_of_the_root_it_bills(fixture_home, project, elsewhere,
                                                                              capsys, monkeypatch):
    write_forge_size(project, "complex\n")
    monkeypatch.chdir(elsewhere)
    code, out, err = cli(capsys, ["substitute", "--role", "code_reviewer", "--use", "consult", "--reason",
                                  "threshold", "--project-root", str(project), "--size", "light"])
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"threshold\n{MAIN}\n"), err
    row = substitution_rows(store_rows(project))[-1]
    assert (row["size"], row["size_source"]) == ("complex", "forge")


def test_x4_f6_control_without_a_project_root_the_working_directory_is_the_root(fixture_home, project, codex_cli,
                                                                               capsys, monkeypatch):
    """CONTROL (green before and after): no --project-root -> the working directory is the root, for
    the budget key AND for `.forge/size`, exactly as before."""
    write_codex_roster(fixture_home)
    write_forge_size(project, "complex\n")
    monkeypatch.chdir(project)
    code, out, err = cli(capsys, ["argv", "--role", "code_reviewer", "--provider", "codex", "--use", "consult",
                                  "--cycle-id", "x4-f6c", "--size", "light"])
    assert (code, out) == (sm.EXIT_OK, X4_CODE_REVIEWER_ASTRA + "\n"), err
    row = admit_rows(store_rows(project))[-1]
    assert (row["size"], row["size_source"]) == ("complex", "forge")


def test_x4_f6_control_an_unsized_call_reads_no_forge_size_anywhere(fixture_home, project, elsewhere, codex_cli,
                                                                   capsys, monkeypatch):
    """CONTROL (green before and after): sizing is OPT-IN. With no --size / --user-request nothing reads
    `.forge/size` - not in the project root, not in the working directory - and the seat is TOP with the
    back-compat default on its row. Proven by a spy on the one reader AND an open() recorder."""
    import builtins

    write_codex_roster(fixture_home)
    write_forge_size(project, "light\n")
    write_forge_size(elsewhere, "light\n")
    monkeypatch.chdir(elsewhere)
    roots = []
    real_reader = sm.read_forge_size
    monkeypatch.setattr(sm, "read_forge_size", lambda root: roots.append(root) or real_reader(root))
    opened = []
    real_open = builtins.open

    def recording_open(file, *args, **kwargs):
        if isinstance(file, (str, os.PathLike)):
            opened.append(os.fspath(file))
        return real_open(file, *args, **kwargs)

    builtins.open = recording_open
    try:
        code, out, err = cli(capsys, argv_use("code_reviewer", "consult", project, "--cycle-id", "x4-f6u"))
        sub = cli(capsys, ["substitute", "--role", "code_reviewer", "--use", "consult", "--reason", "threshold",
                           "--project-root", str(project)])
    finally:
        builtins.open = real_open
    assert (code, out) == (sm.EXIT_OK, X4_CODE_REVIEWER_ASTRA + "\n"), err
    assert sub[:2] == (sm.EXIT_SUBSTITUTE, f"threshold\n{MAIN}\n")
    assert [r for r in roots if r is not None] == []
    size_file = os.path.join(".forge", sm.FORGE_SIZE_FILE)
    assert [p for p in opened if p.endswith(size_file)] == []
    rows = store_rows(project)
    assert (admit_rows(rows)[-1]["size"], admit_rows(rows)[-1]["size_source"]) == ("complex", "default")
    assert (substitution_rows(rows)[-1]["size"], substitution_rows(rows)[-1]["size_source"]) == ("complex", "default")
    # INSTRUMENT CHECK: the same recorder DOES see the read when the call opts in. WHICH root is read is
    # f6's own question, pinned by the reds above; this control only proves the recorder can see one.
    builtins.open = recording_open
    try:
        cli(capsys, argv_use("code_reviewer", "consult", project, "--cycle-id", "x4-f6u2", "--size", "medium"))
    finally:
        builtins.open = real_open
    assert [p for p in opened if p.endswith(size_file)] != []


# --- f7: a substitution never fabricates its size provenance ---------------------------------------- #
@pytest.mark.parametrize("half", [{"size": "light"}, {"size_source": "forge"}], ids=["size_only", "source_only"])
def test_x4_f7_minor_half_a_size_pair_is_a_caller_bug_that_records_nothing(fixture_home, project, half):
    """A size without the source it came from (or the reverse) is a caller bug, exactly as
    codex_quota._checked_size already treats it: guessing `default` for the missing half recorded a
    provenance nobody decided."""
    with pytest.raises(sm.SeatModelError, match="size and size_source"):
        sm.substitute("code_reviewer", "consult", "threshold", project_root=project, **half)
    assert store_rows(project) == []
    assert not (fixture_home / ".claude" / "projects").exists()


@pytest.mark.parametrize("pair,recorded", [
    ({"size": "light", "size_source": "forge"}, ("light", "forge")),
    ({"size": "medium", "size_source": "routing"}, ("medium", "routing")),
    ({}, ("complex", "default")),
], ids=["both_forge", "both_routing", "neither"])
def test_x4_f7_control_a_whole_pair_or_none_is_recorded(fixture_home, project, pair, recorded):
    """CONTROL (green before and after): both halves are recorded as given; neither is the back-compat
    default - the one case where `default` IS the truth, because no size was decided."""
    pin = sm.substitute("code_reviewer", "consult", "threshold", project_root=project, **pair)
    row = substitution_rows(store_rows(project))[-1]
    assert (row["size"], row["size_source"]) == recorded
    assert (pin.provenance["size"], pin.provenance["size_source"]) == recorded


# --- f1: the docstring states the opt-in rule the CLI implements --------------------------------------- #
#: Retired claims (the round base's text): an unflagged argv/timeout read `.forge/size`, and the project
#: root is read ONLY for the budget key (false for a sized call since D16, and for --project-root after f6).
_X4_F1_RETIRED_DOC_CLAIMS = {
    "unflagged_calls_read_forge_size": "read `.forge/size` from the WORKING DIRECTORY even with no flag",
    "project_root_only_keys_the_budget": "else the working directory - ONLY to derive the budget key",
}
#: What the docstring must say instead, so deleting the passage cannot pass for fixing it.
_X4_F1_REQUIRED_DOC_FACTS = {
    "sizing_is_opt_in": "SIZING IS OPT-IN",
    "no_read_without_a_flag": "read NO `.forge/size`",
    "the_project_root_first": "from --project-root when",
    "else_the_working_directory": "from the WORKING DIRECTORY otherwise",
}
#: The two passages as they stood at the round base (seat_model.py bb1eec33), VERBATIM. NEGATIVE CONTROL
#: only; embedded because this file runs in BOTH trees and ~/.claude is not a git repository.
_X4_F1_BASE_PASSAGES = '''
  BACK-COMPAT, and why `emit --json` is pinned. A call that passes no size input at all
  resolves EXACTLY as it did before D16 - same model, same provenance keys - so every
  un-migrated call site keeps working. `argv` and `timeout` resolve one seat for a real
  call and so read `.forge/size` from the WORKING DIRECTORY even with no flag; `emit` is
  the REGISTRY DUMP and stays size-blind unless a size is asked for, which is what keeps
  the default document byte-identical.
no smart-config module at all. The astra paths (J11) read a PROJECT ROOT - --project-root,
else the working directory - ONLY to derive the budget key (codex_quota.cycle_id_for reads
its .forge/cycle-id / cycle-base) and the budget store path; codex_quota derives the store
'''


def _x4_norm(text):
    return " ".join(text.split()).lower()


def _x4_f1_retired_claims_in(text):
    norm = _x4_norm(text)
    return sorted(name for name, needle in _X4_F1_RETIRED_DOC_CLAIMS.items() if _x4_norm(needle) in norm)


def _x4_f1_missing_facts_in(text):
    norm = _x4_norm(text)
    return sorted(name for name, needle in _X4_F1_REQUIRED_DOC_FACTS.items() if _x4_norm(needle) not in norm)


def test_x4_f1_minor_the_docstring_states_the_opt_in_size_read():
    assert _x4_f1_retired_claims_in(sm.__doc__) == []
    assert _x4_f1_missing_facts_in(sm.__doc__) == []
    helper = _x4_norm(sm._size_args.__doc__ or "")
    assert "--project-root" in helper and "working directory" in helper


def test_x4_f1_CONTROL_the_guard_fires_on_the_base_text_and_not_on_a_true_sentence():
    assert _x4_f1_retired_claims_in(_X4_F1_BASE_PASSAGES) == sorted(_X4_F1_RETIRED_DOC_CLAIMS)
    assert _x4_f1_missing_facts_in(_X4_F1_BASE_PASSAGES) == sorted(_X4_F1_REQUIRED_DOC_FACTS)
    # A re-wrapped, re-cased copy of a retired claim is still found ...
    assert _x4_f1_retired_claims_in("...so READ `.forge/size` from the working\n  directory EVEN WITH NO FLAG") == \
        ["unflagged_calls_read_forge_size"]
    # ... and a TRUE sentence using the same words is not a claim.
    assert _x4_f1_retired_claims_in("With --size, `argv` reads `.forge/size` from the working directory when no "
                                    "--project-root is given; with no flag it reads nothing.") == []


# --- L36: codex-orchestration names class_not_budgeted among the exit-3 admit refusals ---------------- #
_CODEX_ORCHESTRATION_SKILL = _META.parent / "codex-orchestration" / "SKILL.md"


def _x4_admit_gate_bullet(text):
    start = text.index("**The admit gate")
    return " ".join(text[start:text.index("\n", start)].split())


def test_x4_F7_major_the_admit_gate_doc_names_class_not_budgeted_among_the_exit_3_refusals():
    """GUARD (L36): the admit-gate bullet enumerates the refusals behind exit 3; after F7 that list must
    name class_not_budgeted, or a reader of it is told the pairing still fails some other way."""
    bullet = _x4_admit_gate_bullet(_CODEX_ORCHESTRATION_SKILL.read_text(encoding="utf-8"))
    exit3 = bullet[bullet.index("Exit **3**"):bullet.index("Exit **10**")]
    # RE-POINTED by #322: `threshold` left the list (nothing produces it any more); the quota refusals and
    # their wait lines take its place.
    for reason in ("budget_spent", "budget_store_unavailable", "class_not_budgeted", "quota_exhausted",
                   "rate_limit_reached", "wait_advice=wait|notify", "CODEX_QUOTA_WAIT"):
        assert f"`{reason}`" in exit3, reason
    assert "`threshold`" not in exit3
    # the exit-3 handling is unchanged: a fresh-context Claude agent serves the seat. #291: the doc names
    # that agent by its TIER once the roster swap's docs land ("Claude main-tier"); the pre-swap wording
    # named the model. Either states the handling; stale model names are the WP-7 grep / `check` lint's job.
    import re
    assert re.search(r"fresh-context (Fable|Claude[ -]main[ -]tier) agent", exit3), exit3


# --------------------------------------------------------------------------- #
# #291 WP-6 (design s3.9) — REVERSIBILITY over two explicit roster fixture pairs
#
# The resolver must follow the roster DATA in both directions: forward to the committed rev-2 roster
# (opus / sonnet, fable benched) and back to the rev-1 roster it replaced (fable / opus, nothing
# benched). Each pair is injected by monkeypatching model_roster's attributes in-process and loading
# a FRESH seat_model over it (conftest.seat_model_under_roster: no production path override). Every
# expected value below is an explicit LITERAL of its pair, never re-derived from the resolver.
# --------------------------------------------------------------------------- #
_REVERSIBILITY_PAIRS = [
    pytest.param(
        "opus", "sonnet", frozenset({"fable"}),
        {"code_reviewer": "opus", "consultant_main": "opus", "consultant_support": "sonnet",
         "arbiter": "opus", "escalation": "opus"},
        "capacity_twice\nopus\n",
        True,                          # claude-fable-5-1 is benched
        ("sonnet", "harness_literal", True),   # env fable on consultant_support: refused, the row serves
        ("gpt-6-sol", "gpt-5.6-terra", True),  # #302 rev 3: codex std / support split
        id="rev3-main-opus-support-sonnet-benched-fable-codex-std-gpt-6-sol-support-gpt-5.6-terra"),
    pytest.param(
        "opus", "sonnet", frozenset({"fable"}),
        {"code_reviewer": "opus", "consultant_main": "opus", "consultant_support": "sonnet",
         "arbiter": "opus", "escalation": "opus"},
        "capacity_twice\nopus\n",
        True,
        ("sonnet", "harness_literal", True),
        ("gpt-5.6-sol", "gpt-5.6-sol", False),  # rev-2 codex shape: one tier, HISTORY without codex_support
        id="rev2-main-opus-support-sonnet-benched-fable"),
    pytest.param(
        "fable", "opus", frozenset(),
        {"code_reviewer": "fable", "consultant_main": "fable", "consultant_support": "opus",
         "arbiter": "fable", "escalation": "fable"},
        "capacity_twice\nfable\n",
        False,                         # nothing benched
        ("fable", "env", False),       # env fable on consultant_support: an accepted vendor alias
        ("gpt-5.6-sol", "gpt-5.6-sol", False),
        id="rev1-main-fable-support-opus-benched-none"),
]


@pytest.mark.parametrize("main,support,benched,claude_by_role,substitute_out,fable_id_benched,env_fable,codex",
                         _REVERSIBILITY_PAIRS)
def test_roster_reversibility_seat_model_follows_both_pairs(fixture_home, project, capsys, monkeypatch,
                                                            load_seat_model_under_roster, main, support, benched,
                                                            claude_by_role, substitute_out, fable_id_benched,
                                                            env_fable, codex):
    codex_std, codex_support, support_in_history = codex
    # every pair's codex literals listed: the base roster (gpt-5.6-sol p4, gpt-5.6-terra p7) plus gpt-6-sol p2
    write_codex_roster(fixture_home, crf.with_tiers(live_like_codex_entries()) + [
        entry("gpt-6-sol", 2) for _ in (0,) if "gpt-6-sol" not in {e["slug"] for e in live_like_codex_entries()}])
    write_agy_cache(fixture_home)
    fresh, rev = load_seat_model_under_roster(main, support, benched, codex_std=codex_std,
                                              codex_support=codex_support, support_in_history=support_in_history)
    assert fresh is not sm and fresh.roster_violations() == []           # the pair is a VALID roster
    monkeypatch.setattr(fresh, "_now", lambda: NOW)
    # the table, and every Claude resolution, in the pair's literals
    assert {role: rows["claude"].value for role, rows in fresh.ROLE_TABLE.items()} == claude_by_role
    for role, alias in claude_by_role.items():
        pin = fresh.resolve(role, "claude")
        assert (pin.model, pin.argv_fragment) == (alias, ("--model", alias, "--effort", pin.effort)), role
        assert pin.effort in fresh.CLAUDE_EFFORTS, role                   # #311 F1
        assert (pin.provenance["requested_selector"], pin.provenance["source"], pin.provenance["roster_rev"]) \
            == (alias, "harness_literal", rev), role
    doc = fresh.emit()
    assert doc["roster_rev"] == rev
    assert {role: doc["pins"][role]["claude"]["model"] for role in claude_by_role} == claude_by_role
    # the codex tiers follow the pair's codex literals; TOP and agy never move with any tier
    assert doc["pins"]["code_reviewer"]["codex"]["model"] == "gpt-6-astra"
    assert doc["pins"]["consultant_support"]["codex"]["model"] == codex_support
    assert fresh.resolve("code_reviewer", "codex", size="light").model == codex_std
    assert doc["pins"]["arbiter"]["agy"]["model"] == "gemini-4-argon-high"
    # astra unavailable -> the substitute is the role's Claude row, whichever tier that is
    code = fresh.main(["substitute", "--role", "code_reviewer", "--use", "audit", "--reason", "capacity_twice",
                       "--project-root", str(project), "--requested-model", "gpt-6-astra"])
    assert (code, capsys.readouterr().out) == (fresh.EXIT_SUBSTITUTE, substitute_out)
    # the benched set is read from the roster: a fable full id is benched only when fable is
    assert fresh.is_benched("claude-fable-5-1") is fable_id_benched
    monkeypatch.setenv("SEAT_TEST_ENV", "fable")
    pin = fresh.resolve("consultant_support", "claude", env_var="SEAT_TEST_ENV")
    assert (pin.model, pin.provenance["source"], "env_override_refused" in pin.provenance) == env_fable


def test_roster_reversibility_leaves_the_shared_seat_model_untouched(load_seat_model_under_roster):
    """CONTROL: loading a fixture pair builds a SEPARATE module; the `sm` every other test holds keeps
    the committed roster's table (so the pair tests cannot leak into the rest of the suite)."""
    before = {role: rows["claude"].value for role, rows in sm.ROLE_TABLE.items()}
    fresh, _rev = load_seat_model_under_roster("fable", "opus", frozenset())
    assert fresh.ROLE_TABLE["code_reviewer"]["claude"].value == "fable"
    assert {role: rows["claude"].value for role, rows in sm.ROLE_TABLE.items()} == before
    assert sm.ROLE_TABLE["code_reviewer"]["claude"].value == MAIN



# =========================================================================== #
# #302 WP-2 — the codex support tier (design #302 s3.1-s3.2; JC-1; main-loop ruling R1)
#
# Roster rev 3 splits the codex std tier: CODEX_STD serves the light/medium sized main seats, and the
# NEW CODEX_SUPPORT serves consultant_support. Budget class follows the RESOLVING ROW (a non-TOP row
# spends std) OR the SERVED model when that is a roster non-TOP tier (R1); a TOP selector that lands on
# a non-TOP tier records `top_resolved_to_std: true`. Tier values are read from model_roster; the
# ceiling fixture's other slugs are synthetic and literal.
# =========================================================================== #
def _tier_std():
    return model_roster.CODEX_STD


def _tier_support():
    return model_roster.CODEX_SUPPORT


def test_302_consultant_support_serves_the_support_tier(fixture_home):
    write_codex_roster(fixture_home)
    pin = sm.resolve("consultant_support", "codex")
    assert (pin.model, pin.effort, pin.provenance["source"]) == (_tier_support(), "medium", "roster")
    assert pin.provenance["requested_selector"] == f"{_tier_support()}@medium"
    assert pin.provenance["roster_rev"] == model_roster.REVISION
    assert sm.ROLE_TABLE["consultant_support"]["codex"] == sm.RoleRow(sm.KIND_LITERAL, value=_tier_support(),
                                                                      effort="medium")
    assert sm.CODEX_SUPPORT_MODEL == _tier_support()
    # CONTROL: the sized main seats still serve the std tier, not the support one.
    sized = sm.resolve("consultant_main", "codex", size="light")
    assert sized.model == _tier_std() and sized.provenance["roster_rev"] == model_roster.REVISION


@pytest.mark.parametrize("which,expected", [("std", "std"), ("support", "std"), ("gpt-6-astra", "top"),
                                            ("gpt-unknown-listed", "top")])
def test_302_model_class_of_the_slug_fallback(which, expected):
    slug = {"std": _tier_std, "support": _tier_support}.get(which, lambda: which)()
    assert sm.model_class_of(slug) == expected


def test_302_pin_model_class_follows_the_resolving_row(fixture_home):
    write_codex_roster(fixture_home)
    assert sm.pin_model_class(sm.resolve("consultant_support", "codex")) == "std"
    assert sm.pin_model_class(sm.resolve("code_reviewer", "codex", size="medium")) == "std"
    assert sm.pin_model_class(sm.resolve("code_reviewer", "codex")) == "top"
    assert sm.pin_model_class(sm.resolve("escalation", "codex", size="light")) == "top"
    assert sm.pin_model_class(sm.resolve("arbiter", "codex")) == "std"          # the astra reserve: a Sol literal
    # a pin built without a row (a fake, a caller that has only a slug) falls back to the slug
    fake = sm.SeatPin(model="gpt-6-astra", effort="xhigh", timeout=1, argv_fragment=(), provenance={})
    assert sm.pin_model_class(fake) == "top"


def test_302_a_support_env_pick_that_passes_the_ceiling_is_billed_std(fixture_home, monkeypatch):
    """R1 / challenger #7: gpt-5.6-luna is neither tier model, so a slug-only class would bill it as
    astra. It came from the consultant_support ROW, so it spends std."""
    write_codex_roster(fixture_home)
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-5.6-luna")
    pin = sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV")
    assert (pin.model, pin.provenance["source"]) == ("gpt-5.6-luna", "env")
    assert sm.model_class_of(pin.model) == "top"              # CONTROL: the slug alone says TOP
    assert sm.pin_model_class(pin) == "std"


def _ceiling_roster():
    """astra p1, the std tier p2, gpt-5.6-sol p4, gpt-5.6-terra p7, gpt-5.6-luna p8 (design #302 s4)."""
    return crf.codex_entries(slugs=("gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"),
                             priorities={_tier_std(): 2})


def test_302_the_support_env_ceiling_rebases_to_the_support_tier(fixture_home, monkeypatch):
    write_codex_roster(fixture_home, _ceiling_roster())
    support = _tier_support()
    for refused in (_tier_std(), "gpt-5.6-sol", "gpt-6-astra"):
        monkeypatch.setenv("SEAT_TEST_ENV", refused)
        pin = sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV")
        assert pin.model == support, refused
        assert f"ranks above {support}" in pin.provenance["env_override_refused"]["reason"], refused
    for accepted in ("gpt-5.6-terra", "gpt-5.6-luna"):
        monkeypatch.setenv("SEAT_TEST_ENV", accepted)
        pin = sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV")
        assert (pin.model, pin.provenance["source"]) == (accepted, "env"), accepted
        assert "env_override_refused" not in pin.provenance


def test_302_a_strict_inversion_serves_the_std_tier_on_top_and_flags_it(fixture_home):
    """Challenger #4: astra and gpt-6-sol are one generation, so a vendor priority flap is no longer
    broken by generation. The seat follows the roster (auto-follow) and the event is VISIBLE."""
    std = _tier_std()
    write_codex_roster(fixture_home, crf.codex_entries(priorities={std: 1, "gpt-6-astra": 2}))
    pin = sm.resolve("code_reviewer", "codex")
    assert pin.model == std
    assert pin.provenance["top_resolved_to_std"] is True
    # CONTROL: the ordinary roster serves astra and carries no flag at all.
    write_codex_roster(fixture_home)
    control = sm.resolve("code_reviewer", "codex")
    assert control.model == "gpt-6-astra" and "top_resolved_to_std" not in control.provenance


@pytest.mark.parametrize("tier", ["std", "support"])
def test_302_a_top_seat_frozen_onto_a_tier_model_is_flagged_and_billed_std(fixture_home, project, codex_cli,
                                                                           capsys, tier):
    """R1: a TOP seat FROZEN onto a roster non-TOP tier spends std (it spends no astra), and the TOP-
    inversion flag is recorded either way."""
    slug = _tier_std() if tier == "std" else _tier_support()
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {"codex": slug})
    pin = sm.resolve("code_reviewer", "codex")
    assert (pin.model, pin.provenance["source"], pin.provenance["top_resolved_to_std"]) == (slug, "freeze", True)
    assert sm.pin_model_class(pin) == "std"
    assert cli(capsys, argv_use("code_reviewer", "consult", project))[0] == sm.EXIT_OK
    assert admit_rows(store_rows(project))[-1]["model_class"] == "std"


def test_302_a_top_seat_frozen_onto_another_listed_model_stays_top(fixture_home, project, codex_cli, capsys):
    """CONTROL for R1: a freeze onto a model that is NOT a roster tier (the old std, gpt-5.6-sol, after
    rev 3) is TOP class and carries no inversion flag."""
    if "gpt-5.6-sol" in (_tier_std(), _tier_support()):
        pytest.skip("gpt-5.6-sol is a roster tier on this roster")
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {"codex": "gpt-5.6-sol"})
    pin = sm.resolve("code_reviewer", "codex")
    assert pin.model == "gpt-5.6-sol" and "top_resolved_to_std" not in pin.provenance
    assert sm.pin_model_class(pin) == "top"
    assert cli(capsys, argv_use("code_reviewer", "consult", project))[0] == sm.EXIT_OK
    assert admit_rows(store_rows(project))[-1]["model_class"] == "top"


def test_302_a_sol6_astra_tie_decided_by_the_incumbent_flags_the_inversion(fixture_home):
    std = _tier_std()
    write_codex_roster(fixture_home, crf.codex_entries(priorities={std: 1}))
    write_tops(fixture_home, {"codex": std})
    pin = sm.resolve("code_reviewer", "codex")
    if pin.provenance.get("tie_break") == "generation":
        pytest.skip("the std tier is not astra's generation on this roster")
    assert (pin.model, pin.provenance["tie_break"], pin.provenance["top_resolved_to_std"]) == \
        (std, "incumbent", True)


# =========================================================================== #
# #302 D21 fix round 1 — F1: the support env ceiling and the billing class must never let the
# current codex TOP (astra) reach a support seat, or be billed std, whatever the vendor priorities.
# (a) the ceiling refuses, INDEPENDENT of priority, an env slug that is the current codex TOP
#     resolution, or is CODEX_STD while the seat's base is not CODEX_STD - unless it is the base.
# (b) pin_model_class bills TOP whenever the served model is the ROSTER TOP resolution (roster doc +
#     tops record, the freeze excluded so R1's deliberate freeze-onto-a-tier still lowers to std).
# =========================================================================== #
def _f1_refused(pin):
    return pin.provenance.get("env_override_refused", {}).get("reason")


def test_f1_a_tied_priority_never_lets_env_serve_the_top_on_the_support_seat(fixture_home, monkeypatch):
    """terra p1 == astra p1: the old strict `<` rule accepted the TIE and served astra, unmetered.

    Ties break by model generation, so the TOP of the tied roster is astra while the support model is an
    older generation (gpt-5.6-terra) and the support model itself from gpt-6.1-terra on (rev 8). Either
    way the env override must not lift the support seat onto the OTHER tied model when that is the TOP."""
    support = _tier_support()
    write_codex_roster(fixture_home, crf.codex_entries(priorities={support: 1}))
    top = sm.resolve("code_reviewer", "codex").model                       # the TOP resolution
    assert top in ("gpt-6-astra", support)
    # CONTROL first, so it runs on every roster: a slug below the ceiling that is not the TOP still passes.
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-5.6-luna")
    ok = sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV")
    assert (ok.model, ok.provenance["source"]) == ("gpt-5.6-luna", "env") and _f1_refused(ok) is None
    if top == support:
        pytest.skip("the support model wins the tie by generation; no other tied model is the TOP here")
    monkeypatch.setenv("SEAT_TEST_ENV", top)
    pin = sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV")
    assert pin.model == support and pin.provenance["source"] == "roster"
    assert "current codex TOP" in _f1_refused(pin)
    assert sm.pin_model_class(pin) == "std"


def test_f1_env_std_on_the_support_seat_is_refused_even_ranked_below_the_ceiling(fixture_home, monkeypatch):
    """Never lift the support seat onto the std tier, even when a priority flap ranks std below it."""
    std, support = _tier_std(), _tier_support()
    if std == support:
        pytest.skip("std == support on this roster")
    write_codex_roster(fixture_home, crf.codex_entries(priorities={std: 9}))
    monkeypatch.setenv("SEAT_TEST_ENV", std)
    pin = sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV")
    assert pin.model == support
    assert "CODEX_STD" in _f1_refused(pin)


def test_f1_an_unranked_std_candidate_is_refused_an_unranked_other_is_not(fixture_home, monkeypatch):
    """An entry with no numeric priority escapes the rank rule; the tier rule does not care."""
    std, support = _tier_std(), _tier_support()
    if std == support:
        pytest.skip("std == support on this roster")
    extra = [crf.entry("gpt-unranked", None)]
    write_codex_roster(fixture_home, crf.codex_entries(priorities={std: None}, extra=extra))
    monkeypatch.setenv("SEAT_TEST_ENV", std)
    pin = sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV")
    assert pin.model == support and "CODEX_STD" in _f1_refused(pin)
    # CONTROL: an unranked listed slug that is neither the TOP nor a higher tier stays accepted.
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-unranked")
    ok = sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV")
    assert (ok.model, ok.provenance["source"]) == ("gpt-unranked", "env")


def test_f1_a_freeze_makes_its_slug_the_top_resolution_for_the_ceiling(fixture_home, monkeypatch):
    """A codex TOP frozen onto luna (p8, below the ceiling): the TOP seats serve luna, so env on the
    support seat may not buy it. CONTROL: the same env without the freeze passes."""
    write_codex_roster(fixture_home)
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-5.6-luna")
    ok = sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV")
    assert (ok.model, ok.provenance["source"]) == ("gpt-5.6-luna", "env")
    write_pins(fixture_home, {"codex": "gpt-5.6-luna"})
    pin = sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV")
    assert pin.model == _tier_support() and "current codex TOP" in _f1_refused(pin)


def test_f1_a_std_equal_support_revert_keeps_env_on_its_own_base_legal(fixture_home, monkeypatch,
                                                                       load_seat_model_under_roster):
    fresh, _rev = load_seat_model_under_roster(model_roster.CLAUDE_MAIN, model_roster.CLAUDE_SUPPORT,
                                               model_roster.CLAUDE_BENCHED, codex_std="gpt-5.6-sol",
                                               codex_support="gpt-5.6-sol", support_in_history=False)
    write_codex_roster(fixture_home)
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-5.6-sol")
    pin = fresh.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV")
    assert (pin.model, pin.provenance["source"]) == ("gpt-5.6-sol", "env")
    assert "env_override_refused" not in pin.provenance
    assert fresh.pin_model_class(pin) == "std"


#: A future vendor TOP the harness literal does not name (#302 NEW-1 moved the harness-literal case
#: to an import invariant; billing still guards a tier that collides with an AUTO-FOLLOWED TOP).
FUTURE_TOP = "gpt-7-astra"


def test_f1_a_support_tier_set_to_the_top_slug_is_billed_top(fixture_home, load_seat_model_under_roster):
    """m5: CODEX_SUPPORT mis-set to the (auto-followed) TOP slug. The literal support row serves that
    TOP; billing it std (the row is a literal) would ration nothing. The served model is the roster
    TOP -> TOP. The harness literal itself can no longer be a tier (import invariant, below)."""
    fresh, _rev = load_seat_model_under_roster(model_roster.CLAUDE_MAIN, model_roster.CLAUDE_SUPPORT,
                                               model_roster.CLAUDE_BENCHED, codex_support=FUTURE_TOP)
    write_codex_roster(fixture_home, crf.codex_entries(priorities={FUTURE_TOP: 1, "gpt-6-astra": 2}))
    assert fresh.resolve("code_reviewer", "codex").model == FUTURE_TOP
    pin = fresh.resolve("consultant_support", "codex")
    assert pin.model == FUTURE_TOP
    assert fresh.pin_model_class(pin) == "top"
    # CONTROL: the sized std seat on the same roster is still std, the TOP seat still top.
    assert fresh.pin_model_class(fresh.resolve("code_reviewer", "codex", size="light")) == "std"
    assert fresh.pin_model_class(fresh.resolve("code_reviewer", "codex")) == "top"


def test_f1_a_strict_inversion_onto_std_bills_the_served_top_as_top(fixture_home):
    """Without a freeze the vendor ranked std first: std IS the roster TOP now, so it is billed top
    (check FAILs this state). R1 still lowers a DELIBERATE freeze onto a tier (the freeze test above)."""
    std = _tier_std()
    write_codex_roster(fixture_home, crf.codex_entries(priorities={std: 1, "gpt-6-astra": 2}))
    pin = sm.resolve("code_reviewer", "codex")
    assert pin.model == std and sm.pin_model_class(pin) == "top"


def test_f1_billing_falls_back_to_the_row_rule_when_the_top_cannot_be_determined(fixture_home):
    """An invalid roster: the TOP cannot be determined, so the existing row/tier rule decides."""
    path = fixture_home / ".codex" / "models_cache.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    pin = sm.SeatPin(model="gpt-6-astra", effort="medium", timeout=1, argv_fragment=(), provenance={},
                     row_kind=sm.KIND_LITERAL)
    assert sm.pin_model_class(pin) == "std"


# =========================================================================== #
# #302 D21 fix round 2 — N1: billing's "freeze-excluded" TOP set must not be the freeze itself.
# A freeze makes _record_top write the FROZEN slug as the tops record's `top`; the stale keep-last
# rule and the tie incumbent then read it back, so the "roster TOP" was the freeze. N2: the
# ceiling's freeze-included TOP set names what the TOP seats would actually serve when the frozen
# slug no longer resolves (the harness literal), not only the delisted slug.
# =========================================================================== #
def test_n1_stale_roster_freeze_onto_std_is_not_read_back_as_the_roster_top(fixture_home):
    std = _tier_std()
    write_codex_roster(fixture_home, fetched_at=iso_nanos(NOW - 30 * DAY))
    write_pins(fixture_home, {"codex": std})
    frozen = sm.resolve("code_reviewer", "codex")
    assert frozen.model == std and read_tops(fixture_home)["tops"]["codex"]["top"] == std
    assert sm._codex_top_models(sm._paths(), None, include_freeze=False) == frozenset({"gpt-6-astra"})
    assert sm.pin_model_class(frozen) == "std"                                   # R1: freeze onto a tier
    assert sm.pin_model_class(sm.resolve("code_reviewer", "codex", size="light")) == "std"


def test_n1_fresh_tie_freeze_onto_std_is_not_the_incumbent_for_billing(fixture_home,
                                                                       load_seat_model_under_roster):
    # The std tier is pinned to astra's own generation (rev 5 moved the live std to gpt-6.1-sol, which
    # the generation rule would rank above astra before the incumbent rule is ever asked).
    std = "gpt-6-sol"
    fresh, _rev = load_seat_model_under_roster(model_roster.CLAUDE_MAIN, model_roster.CLAUDE_SUPPORT,
                                               model_roster.CLAUDE_BENCHED, codex_std=std)
    write_codex_roster(fixture_home, crf.codex_entries(priorities={std: 1}))
    write_pins(fixture_home, {"codex": std})
    frozen = fresh.resolve("code_reviewer", "codex")
    assert frozen.model == std and read_tops(fixture_home)["tops"]["codex"]["top"] == std
    # The roster alone (no incumbent) breaks the astra/sol tie by slug -> astra.
    assert fresh._codex_top_models(fresh._paths(), None, include_freeze=False) == frozenset({"gpt-6-astra"})
    assert fresh.pin_model_class(frozen) == "std"
    assert fresh.pin_model_class(fresh.resolve("code_reviewer", "codex", size="light")) == "std"


def test_n1_a_frozen_top_seat_on_a_tier_the_roster_also_ranks_top_is_still_billed_std(fixture_home):
    """R1 for the frozen TOP seats holds even when the roster itself resolves onto the frozen tier:
    the freeze is deliberate, so the m5b WARN's 'the frozen TOP seats are billed std' stays true."""
    std = _tier_std()
    write_codex_roster(fixture_home, crf.codex_entries(priorities={std: 1, "gpt-6-astra": 2}))
    write_pins(fixture_home, {"codex": std})
    frozen = sm.resolve("code_reviewer", "codex")
    assert frozen.model == std and sm.pin_model_class(frozen) == "std"


def test_n1_control_sized_std_without_a_freeze_is_std_and_the_top_is_top(fixture_home):
    write_codex_roster(fixture_home, fetched_at=iso_nanos(NOW - 30 * DAY))
    top = sm.resolve("code_reviewer", "codex")
    assert top.model == "gpt-6-astra" and sm.pin_model_class(top) == "top"
    assert sm.pin_model_class(sm.resolve("code_reviewer", "codex", size="light")) == "std"


def test_n1_a_freeze_onto_astra_still_bills_a_support_literal_serving_astra_top(fixture_home,
                                                                               load_seat_model_under_roster):
    """F1b kept: CODEX_SUPPORT mis-set to the TOP while the TOP is frozen onto it -> TOP."""
    fresh, _rev = load_seat_model_under_roster(model_roster.CLAUDE_MAIN, model_roster.CLAUDE_SUPPORT,
                                               model_roster.CLAUDE_BENCHED, codex_support=FUTURE_TOP)
    write_codex_roster(fixture_home, crf.codex_entries(priorities={FUTURE_TOP: 1, "gpt-6-astra": 2}),
                       fetched_at=iso_nanos(NOW - 30 * DAY))
    write_pins(fixture_home, {"codex": FUTURE_TOP})
    assert fresh.resolve("code_reviewer", "codex").model == FUTURE_TOP
    pin = fresh.resolve("consultant_support", "codex")
    assert pin.model == FUTURE_TOP and fresh.pin_model_class(pin) == "top"


@pytest.mark.parametrize("tier", ["codex_std", "codex_support"])
def test_new1_a_tier_equal_to_the_top_harness_literal_fails_closed_at_import(load_seat_model_under_roster,
                                                                             tier):
    """#302 NEW-1: a tier set to the TOP harness literal (+ a freeze on it) would bill every protected
    TOP seat std. It is now an import invariant: the roster cannot load at all."""
    # The fresh module raises ITS OWN SeatModelError class, so match by name, not identity.
    with pytest.raises(Exception, match="must not be the codex TOP harness literal") as info:
        load_seat_model_under_roster(model_roster.CLAUDE_MAIN, model_roster.CLAUDE_SUPPORT,
                                     model_roster.CLAUDE_BENCHED, **{tier: "gpt-6-astra"})
    assert type(info.value).__name__ == "SeatModelError"


def test_n2_a_delisted_freeze_puts_the_fallback_top_in_the_ceiling_set(fixture_home, monkeypatch):
    support = _tier_support()
    write_codex_roster(fixture_home, crf.codex_entries(priorities={support: 1}))
    write_pins(fixture_home, {"codex": "gpt-delisted"})
    assert sm.resolve("code_reviewer", "codex", fail_open=True).model == "gpt-6-astra"
    assert "gpt-6-astra" in sm._codex_top_models(sm._paths(), None, include_freeze=True)
    monkeypatch.setenv("SEAT_TEST_ENV", "gpt-6-astra")
    pin = sm.resolve("consultant_support", "codex", env_var="SEAT_TEST_ENV")
    assert pin.model == support and "current codex TOP" in (_f1_refused(pin) or "")


def test_n2_control_a_valid_freeze_set_is_the_frozen_slug(fixture_home):
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {"codex": "gpt-5.6-luna"})
    assert sm._codex_top_models(sm._paths(), None, include_freeze=True) == frozenset({"gpt-5.6-luna"})


# --------------------------------------------------------------------------- #
# #311: protected Claude effort (design 2026-09-24 s3.3, U3)
# --------------------------------------------------------------------------- #
def test_311_the_claude_effort_levels_equal_effort_policy():
    import effort_policy
    assert sm.CLAUDE_EFFORTS == effort_policy.LEVELS


def test_311_protected_seats_resolve_their_pinned_effort_with_provenance(fixture_home):
    for role in sorted(sm.PROTECTED):
        pin = sm.resolve(role, "claude")
        assert pin.effort == _claude_effort(role), role
        assert (pin.provenance["effort"], pin.provenance["effort_source"]) == (_claude_effort(role), "harness_literal")
    assert sm.resolve("consultant_support", "claude").effort == "medium"


def test_311_a_protected_env_effort_is_honoured_only_when_equal_to_the_literal(fixture_home, monkeypatch):
    monkeypatch.setenv("SEAT_EFFORT", _claude_effort("arbiter"))
    pin = sm.resolve("arbiter", "claude", effort_env_var="SEAT_EFFORT")
    assert (pin.effort, pin.provenance["effort_source"]) == (_claude_effort("arbiter"), "env")
    assert "effort_override_refused" not in pin.provenance
    pinned = _claude_effort("code_reviewer")
    for bad in [v for v in ("low", "medium", "high", "xhigh", "max") if v != pinned] + ["ultra; rm -rf"]:
        monkeypatch.setenv("SEAT_EFFORT", bad)
        pin = sm.resolve("code_reviewer", "claude", effort_env_var="SEAT_EFFORT")
        assert (pin.effort, pin.provenance["effort_source"]) == (pinned, "harness_literal"), bad
        assert pin.provenance["effort_override_refused"]["value"] == bad


def test_311_consultant_support_env_effort_accepts_levels_only(fixture_home, monkeypatch):
    monkeypatch.setenv("SEAT_EFFORT", "high")
    pin = sm.resolve("consultant_support", "claude", effort_env_var="SEAT_EFFORT")
    assert (pin.effort, pin.provenance["effort_source"]) == ("high", "env")
    monkeypatch.setenv("SEAT_EFFORT", "turbo")
    pin = sm.resolve("consultant_support", "claude", effort_env_var="SEAT_EFFORT")
    assert pin.effort == "medium" and pin.provenance["effort_override_refused"]["value"] == "turbo"


def test_311_effort_env_var_is_a_claude_only_argument(fixture_home):
    with pytest.raises(sm.SeatModelError):
        sm.resolve("code_reviewer", "codex", effort_env_var="SEAT_EFFORT")


def test_311_a_project_model_policy_cannot_change_a_protected_effort(fixture_home, tmp_path, monkeypatch):
    """No project file has a path to the protected effort: a planted policy that tries is ignored."""
    project = tmp_path / "proj"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "model-policy.yaml").write_text(
        "version: 1\ntiers:\n  complex: { claude-code: opus, effort: { claude-code: low } }\n"
        "code_reviewer: { effort: low }\nagents:\n  code_reviewer: haiku\n", encoding="utf-8")
    monkeypatch.chdir(project)
    for role in sorted(sm.PROTECTED):
        assert sm.resolve(role, "claude").effort == _claude_effort(role), role
    assert all(pins["claude"]["effort"] == _claude_effort(role)
               for role, pins in sm.emit()["pins"].items() if role in sm.PROTECTED)


def test_311_the_effort_cli_prints_one_word(fixture_home, capsys):
    assert cli(capsys, ["effort", "--role", "code_reviewer", "--provider", "claude"])[:2] == (
        sm.EXIT_OK, f"{_claude_effort('code_reviewer')}\n")
    assert cli(capsys, ["effort", "--role", "consultant_support", "--provider", "claude"])[:2] == (sm.EXIT_OK, "medium\n")
    code, out, _ = cli(capsys, ["effort", "--role", "code_reviewer", "--provider", "codex"])
    assert (code, out) == (sm.EXIT_USAGE, "")


def test_311_r2_item6_a_protected_row_without_an_effort_raises(fixture_home):
    row = sm.RoleRow(sm.KIND_ALIAS, value=MAIN, effort=None, timeout=600)
    for role in sorted(sm.PROTECTED):
        with pytest.raises(sm.SeatModelError):
            sm._resolve_claude(role, row, None)
    pin = sm._resolve_claude("consultant_support", sm.RoleRow(sm.KIND_ALIAS, value=SUPPORT, effort=None,
                                                                timeout=600), None)
    assert pin.argv_fragment == ("--model", SUPPORT)      # a non-protected seat may inherit
    with pytest.raises(sm.SeatModelError):
        sm._claude_argv(MAIN, None, protected=True)



# =========================================================================== #
# #322 — a quota refusal names its reset; `--await-quota` defers the stand-in (DW-4, DW-5)
# =========================================================================== #
def test_322_a_quota_refusal_keeps_its_two_lines_and_appends_the_wait_lines(fixture_home, project, codex_cli, capsys):
    """DW-4: lines 1 and 2 are BYTE-IDENTICAL to the pre-#322 output (what `substitute` prints for the same
    reason); the key=value lines come after them, in a fixed order, and only the known ones."""
    write_codex_roster(fixture_home)
    write_rollout(fixture_home, 99, 20, primary_resets_in=900)
    code, out, _ = cli(capsys, argv_use("consultant_main", "consult", project, "--cycle-id", "c"))
    lines = out.splitlines()
    assert code == sm.EXIT_SUBSTITUTE
    assert lines[:2] == ["quota_exhausted", MAIN]
    assert [line.split("=", 1)[0] for line in lines[2:]] == ["binding_window", "resets_at", "resets_in_s",
                                                             "wait_advice"]
    tail = split_exit3(out)[1]
    assert tail["binding_window"] == "primary" and tail["wait_advice"] == "wait"
    assert 880 <= int(tail["resets_in_s"]) <= 900
    # The substitution is still RECORDED without --await-quota (the pre-#322 behaviour).
    assert [r["reason"] for r in substitution_rows(store_rows(project))] == ["quota_exhausted"]
    # A consumer that reads line 2 gets the model; the `substitute` form prints the same two lines.
    code, sub, _ = cli(capsys, ["substitute", "--role", "consultant_main", "--use", "consult", "--reason",
                                "quota_exhausted", "--project-root", str(project), "--cycle-id", "c"])
    assert (code, sub) == (sm.EXIT_SUBSTITUTE, "\n".join(lines[:2]) + "\n")


def test_322_a_far_reset_advises_notify(fixture_home, project, codex_cli, capsys):
    write_codex_roster(fixture_home)
    write_rollout(fixture_home, 99, 20, primary_resets_in=1300)
    _, out, _ = cli(capsys, argv_use("consultant_main", "consult", project, "--cycle-id", "c"))
    assert split_exit3(out)[1]["wait_advice"] == "notify"


def test_322_a_non_quota_refusal_prints_exactly_the_two_lines(fixture_home, project, codex_cli, capsys):
    """CONTROL: budget_spent (and every other non-quota reason) is byte-identical to before #322."""
    write_codex_roster(fixture_home)
    write_rollout(fixture_home, 10, 10)
    assert cli(capsys, argv_use("consultant_main", "consult", project, "--cycle-id", "c"))[0] == sm.EXIT_OK
    assert cli(capsys, argv_use("consultant_main", "consult", project, "--cycle-id", "c"))[0] == sm.EXIT_OK
    code, out, _ = cli(capsys, argv_use("consultant_main", "consult", project, "--cycle-id", "c", "--await-quota"))
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"budget_spent\n{MAIN}\n")
    assert [r["reason"] for r in substitution_rows(store_rows(project))] == ["budget_spent"]   # still recorded


def test_322_await_quota_defers_the_substitution_row(fixture_home, project, codex_cli, capsys):
    """DW-4/DW-5: with --await-quota a quota refusal records its admit refusal but NO substitution: the
    stand-in may never serve (the wait may end in a re-admission). The output ends substitution=deferred."""
    write_codex_roster(fixture_home)
    write_rollout(fixture_home, 99, 20)
    code, out, err = cli(capsys, argv_use("consultant_main", "consult", project, "--cycle-id", "c", "--await-quota"))
    lines = out.splitlines()
    assert code == sm.EXIT_SUBSTITUTE and lines[:2] == ["quota_exhausted", MAIN]
    assert lines[-1] == "substitution=deferred" and split_exit3(out)[1]["wait_advice"] == "notify"
    rows = store_rows(project)
    assert [(r["admitted"], r["reason"]) for r in admit_rows(rows)] == [(False, "quota_exhausted")]
    assert substitution_rows(rows) == []
    assert "await-reset" in err and "quota_exhausted_timeout" in err
    # CONTROL: without the flag the same refusal records its substitution.
    cli(capsys, argv_use("consultant_main", "consult", project, "--cycle-id", "c"))
    assert len(substitution_rows(store_rows(project))) == 1


def test_322_await_quota_needs_use(fixture_home, capsys):
    code, out, err = cli(capsys, ["argv", "--role", "consultant_main", "--provider", "codex", "--await-quota"])
    assert (code, out) == (sm.EXIT_USAGE, "") and "--await-quota" in err


def test_322_the_timeout_stand_in_is_recorded_with_its_own_reason(fixture_home, project, capsys):
    """DW-5: after await-reset exits 4, `substitute --reason quota_exhausted_timeout` prints the usual two
    lines and writes one substitution row with that reason."""
    code, out, _ = cli(capsys, ["substitute", "--role", "code_reviewer", "--use", "advisory_review", "--reason",
                                "quota_exhausted_timeout", "--project-root", str(project), "--cycle-id", "c"])
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"quota_exhausted_timeout\n{MAIN}\n")
    assert [(r["reason"], r["served_model"]) for r in substitution_rows(store_rows(project))] == [
        ("quota_exhausted_timeout", MAIN)]


# =========================================================================== #
# #322 fix round 1 — the deferred output names what the later `substitute` must name (item 5)
# =========================================================================== #
def test_322_fr1_a_deferred_refusal_names_its_use_key_and_codex_model(fixture_home, project, codex_cli, capsys):
    """Lines 1-2 unchanged; after the wait lines come use=, key= and requested_model= (the pin that was
    refused), then substitution=deferred -- so step 4's `substitute` passes --cycle-id and --requested-model."""
    write_codex_roster(fixture_home)
    write_rollout(fixture_home, 99.5, 20)
    code, out, _ = cli(capsys, argv_use("consultant_main", "consult", project, "--cycle-id", "tournament-x",
                                        "--await-quota"))
    lines = out.splitlines()
    assert code == sm.EXIT_SUBSTITUTE and lines[:2] == ["quota_exhausted", MAIN]
    tail = split_exit3(out)[1]
    assert (tail["use"], tail["key"]) == ("consult", "tournament-x")
    assert tail["requested_model"] == sm.resolve("consultant_main", "codex").model
    assert [line.split("=", 1)[0] for line in lines[2:]][-4:] == ["use", "key", "requested_model", "substitution"]
    # the recorded stand-in, as step 4 composes it, lands on the seat's own key with its model
    cli(capsys, ["substitute", "--role", "consultant_main", "--use", tail["use"], "--cycle-id", tail["key"],
                 "--requested-model", tail["requested_model"], "--reason", "quota_exhausted_timeout",
                 "--project-root", str(project)])
    row = substitution_rows(store_rows(project))[-1]
    assert (row["key"], row["requested_model"], row["reason"]) == ("tournament-x", tail["requested_model"],
                                                                  "quota_exhausted_timeout")


def test_322_fr1_quota_probe_error_is_accepted_by_substitute(fixture_home, project, capsys):
    code, out, _ = cli(capsys, ["substitute", "--role", "code_reviewer", "--use", "advisory_review", "--reason",
                                "quota_probe_error", "--project-root", str(project), "--cycle-id", "c"])
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"quota_probe_error\n{MAIN}\n")


# =========================================================================== #
# #367 WP-A - the agy family is roster DATA (model_roster.AGY_FAMILY, rev 6: argon)
#
# Flash, the family agy served until rev 6, is refused on every agy path (roster, freeze, env and
# harness literal); a recorded flash incumbent is replaced even on a stale cache; and an invalid
# family, harness version or HISTORY row stops the import (fail closed).
# =========================================================================== #
FLASH_SLUG = "gemini-3.8-flash-high"


def test_367_the_family_rule_is_built_from_the_roster():
    assert sm.AGY_FAMILY == model_roster.AGY_FAMILY == "argon"
    assert sm.AGY_HARNESS_VERSION == model_roster.AGY_HARNESS_VERSION == "4"
    assert sm.AGY_FAMILY_PATTERN == r"^gemini-\d{1,9}(\.\d{1,9})*-" + sm.AGY_FAMILY + r"-(high|medium|low)$"
    assert sm.KIND_TOP_AGY == "top_agy"
    assert {role: sm.ROLE_TABLE[role]["agy"].kind for role in ("consultant_main", "consultant_support", "arbiter")} \
        == dict.fromkeys(("consultant_main", "consultant_support", "arbiter"), "top_agy")
    assert not hasattr(sm, "is_flash_only") and not hasattr(sm, "FLASH_ONLY_PATTERN")   # no compat alias
    assert sm.agy_roster_violations() == []


def test_367_a_flash_slug_is_refused_on_the_roster_path(fixture_home):
    write_agy_cache(fixture_home, ["gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-3.9-flash-high"])
    with pytest.raises(sm.SeatModelError, match="agy family rule"):
        sm.resolve("consultant_main", "agy", fail_open=False)
    pin = sm.resolve("consultant_main", "agy", fail_open=True)            # fail_open: the argon literal
    assert (pin.model, pin.provenance["source"]) == ("gemini-4-argon-high", "harness_literal")
    assert "agy family rule" in pin.provenance["fallback_reason"]


def test_367_a_flash_slug_is_refused_on_the_freeze_path(fixture_home):
    write_agy_cache(fixture_home)
    write_pins(fixture_home, {"agy": FLASH_SLUG})
    with pytest.raises(sm.SeatModelError, match="agy freeze pin 'gemini-3.8-flash-high' violates the agy family"):
        sm.resolve("arbiter", "agy", fail_open=False)
    write_agy_cache(fixture_home, None)                                     # no readable cache: still refused
    (fixture_home / ".claude" / "state" / "agy-models.json").unlink()
    with pytest.raises(sm.SeatModelError, match="agy family rule"):
        sm.resolve("arbiter", "agy", fail_open=False)


def test_367_a_flash_slug_is_refused_on_the_env_path(fixture_home, monkeypatch):
    write_agy_cache(fixture_home)
    monkeypatch.setenv("SEAT_TEST_ENV", FLASH_SLUG)
    pin = sm.resolve("consultant_support", "agy", env_var="SEAT_TEST_ENV")
    assert (pin.model, pin.provenance["source"]) == ("gemini-4-argon-medium", "roster")
    assert pin.provenance["env_override_refused"]["value"] == FLASH_SLUG
    assert "agy serves Gemini argon only" in pin.provenance["env_override_refused"]["reason"]


def test_367_a_flash_slug_is_refused_on_the_harness_literal_path(fixture_home, monkeypatch):
    monkeypatch.setattr(sm, "AGY_HARNESS_TEMPLATE", "gemini-3.8-flash-{level}")
    for fail_open in (False, True):
        with pytest.raises(sm.SeatModelError, match="agy serves Gemini argon only"):
            sm.resolve("consultant_main", "agy", fail_open=fail_open)


def test_367_a_cache_listing_both_families_picks_argon(fixture_home):
    write_agy_cache(fixture_home, ["gemini-9.9-flash-high", "gemini-9.9-flash-medium",   # a NEWER flash version
                                   "gemini-4-argon-high", "gemini-4-argon-medium", "gemini-4-argon-low"])
    assert sm.resolve("consultant_main", "agy").model == "gemini-4-argon-high"
    assert sm.resolve("consultant_support", "agy").model == "gemini-4-argon-medium"
    assert sm.resolve("arbiter", "agy").provenance["requested_selector"] == "TOP-argon-high"


def test_367_a_cache_listing_only_flash_fails_closed_or_falls_to_the_argon_literal(fixture_home):
    write_agy_cache(fixture_home, ["gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-3.8-flash-low"])
    for role, level in (("consultant_main", "high"), ("consultant_support", "medium"), ("arbiter", "high")):
        with pytest.raises(sm.SeatModelError, match="no eligible agy model"):
            sm.resolve(role, "agy", fail_open=False)
        pin = sm.resolve(role, "agy", fail_open=True)
        assert (pin.model, pin.provenance["source"]) == (f"gemini-4-argon-{level}", "harness_literal"), role


def test_367_a_newer_argon_version_wins(fixture_home):
    write_agy_cache(fixture_home, ["gemini-4-argon-high", "gemini-4.1-argon-high", "gemini-4-argon-medium"])
    assert sm.resolve("consultant_main", "agy").model == "gemini-4.1-argon-high"
    assert sm.resolve("consultant_support", "agy").model == "gemini-4-argon-medium"      # level-specific


def test_367_a_stale_flash_incumbent_is_replaced_recorded_and_announced_once(fixture_home):
    """Sol C9: a recorded flash top (the live state before rev 6) is never kept, even on a stale cache that
    still lists flash. The argon family is recorded with the flash family as `previous`, which the digest
    announces; a second resolution rewrites nothing that would re-arm the announcement."""
    mixed = ["gemini-3.8-flash-high", "gemini-3.8-flash-medium", "gemini-4-argon-high", "gemini-4-argon-medium"]
    write_agy_cache(fixture_home, mixed, fetched_at=iso(NOW - 9 * DAY))   # stale
    write_tops(fixture_home, {"agy": "gemini-3.8-flash"})
    pin = sm.resolve("consultant_main", "agy")
    assert (pin.model, pin.provenance.get("roster_stale")) == ("gemini-4-argon-high", True)
    first = read_tops(fixture_home)["tops"]["agy"]
    assert (first["top"], first["previous"]) == ("gemini-4-argon", "gemini-3.8-flash")
    assert first["changed_at"] == iso(NOW)
    # A later resolution (another level, a later time) keeps the recorded change as it was.
    sm_now = NOW + 3600
    sm._now = lambda: sm_now                                               # restored by fixture_home's monkeypatch
    assert sm.resolve("consultant_support", "agy").model == "gemini-4-argon-medium"
    second = read_tops(fixture_home)["tops"]["agy"]
    assert (second["top"], second["previous"], second["changed_at"]) == \
        ("gemini-4-argon", "gemini-3.8-flash", first["changed_at"])


def test_367_a_same_family_stale_incumbent_is_still_kept(fixture_home):
    """CONTROL: the stale-cache rule for an incumbent OF the family is unchanged - it is kept, unrecorded."""
    write_agy_cache(fixture_home, ["gemini-4-argon-high", "gemini-4.1-argon-high"], fetched_at=iso(NOW - 9 * DAY))
    write_tops(fixture_home, {"agy": "gemini-4-argon"})
    assert sm.resolve("consultant_main", "agy").model == "gemini-4-argon-high"
    assert read_tops(fixture_home)["tops"]["agy"]["previous"] is None


def _import_with_roster(tmp_path, assignments: str) -> subprocess.CompletedProcess:
    meta = str(Path(sm.__file__).resolve().parent)
    home = tmp_path / "import-home"
    (home / ".claude" / "state").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    env.pop("PYTHONPATH", None)
    code = (f"import sys\nsys.path.insert(0, {meta!r})\nimport model_roster as r\n"
            + textwrap.dedent(assignments) + "\nimport seat_model\nprint('IMPORTED')\n")
    return subprocess.run([sys.executable, "-B", "-c", code], cwd=str(tmp_path), env=env,
                          capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("assignments,needle", [
    ("r.AGY_FAMILY = 'Argon'\nr.HISTORY = r.HISTORY[:-1] + (dict(r.HISTORY[-1], agy_family='Argon'),)",
     "AGY_FAMILY must match"),
    ("r.AGY_FAMILY = 'fl(ash'\nr.HISTORY = r.HISTORY[:-1] + (dict(r.HISTORY[-1], agy_family='fl(ash'),)",
     "AGY_FAMILY must match"),
    ("r.AGY_FAMILY = None", "AGY_FAMILY must match"),
    ("del r.AGY_FAMILY", "AGY_FAMILY must match"),
    ("r.AGY_HARNESS_VERSION = '4-rc'", "AGY_HARNESS_VERSION must match"),
    ("r.AGY_HARNESS_VERSION = 4", "AGY_HARNESS_VERSION must match"),
    ("r.HISTORY = r.HISTORY[:-1] + (dict(r.HISTORY[-1], agy_family='flash'),)", "HISTORY[-1]['agy_family']"),
    ("r.HISTORY = r.HISTORY[:-1] + ({k: v for k, v in r.HISTORY[-1].items() if k != 'agy_family'},)",
     "a missing key reads as 'flash'"),
], ids=["upper-case", "regex-syntax", "none", "absent", "version-word", "version-int", "history-flash",
        "history-missing"])
def test_367_an_invalid_agy_family_fails_the_import(tmp_path, assignments, needle):
    result = _import_with_roster(tmp_path, assignments)
    assert result.returncode != 0 and "IMPORTED" not in result.stdout, result.stdout
    assert "SeatModelError" in result.stderr and "model_roster.py violates its invariants" in result.stderr
    assert needle in result.stderr, result.stderr


def test_367_a_consistent_family_swap_imports(tmp_path):
    """CONTROL: a family swap that moves AGY_FAMILY, AGY_HARNESS_VERSION and the HISTORY row together
    imports, and the harness literal follows it."""
    result = _import_with_roster(tmp_path, "\n".join((
        "r.AGY_FAMILY = 'neon'",
        "r.AGY_HARNESS_VERSION = '5.2'",
        "r.HISTORY = r.HISTORY[:-1] + (dict(r.HISTORY[-1], agy_family='neon'),)",
        "import seat_model as s",
        "print(s.resolve('arbiter', 'agy').model)")))
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["gemini-5.2-neon-high", "IMPORTED"]
