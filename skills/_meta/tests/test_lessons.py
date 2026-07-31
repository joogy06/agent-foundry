#!/usr/bin/env python3
"""Tests for lessons.py — S076, the defect-to-skill loop's consumption half.

The tests that matter are the ones pinning the TAXONOMY, because the taxonomy is the
mechanism. If `execution_failure` can route to a skill edit, the loop answers every
incident by adding prose — which lengthens skills, which makes them less likely to be
read, which produces more execution failures. So `destination` is DERIVED from
classification and there is deliberately no way to set it by hand.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

META = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_lt_{name}", META / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


les = _load("lessons")
lint = _load("portability_lint")


def run(ledger: Path, *argv: str) -> int:
    old = sys.argv
    sys.argv = ["lessons.py", "--ledger", str(ledger), *argv]
    try:
        return les.main()
    finally:
        sys.argv = old


@pytest.fixture
def ledger(tmp_path) -> Path:
    return tmp_path / ".lessons" / "lessons.jsonl"


def records(ledger: Path) -> list[dict]:
    return les._read(ledger)


# --------------------------------------------------------------------------
# The taxonomy — destination is derived, never chosen
# --------------------------------------------------------------------------

def test_capability_gap_routes_to_a_skill():
    assert les.CLASSIFICATIONS["capability_gap"] == "skill"


def test_execution_failure_routes_to_a_mechanism_not_a_skill():
    """THE LOAD-BEARING ASSERTION. A sibling project's audit found ~half of its defects were
    execution failures — the check existed and was not honoured — where 'no skill change
    would have helped'. Routing those to skill edits is how a feedback loop makes a system
    worse while appearing to improve it."""
    assert les.CLASSIFICATIONS["execution_failure"] == "mechanism"
    assert les.CLASSIFICATIONS["execution_failure"] != "skill"


def test_one_off_routes_nowhere():
    assert les.CLASSIFICATIONS["one_off"] == "none"


def test_there_is_no_way_to_set_destination_by_hand(ledger):
    """Derivation is the guard. If a caller could pass destination directly, the taxonomy
    becomes advisory and the loop drifts back to 'add a rule' for everything."""
    run(ledger, "add", "x", "--classify", "execution_failure")
    with pytest.raises(SystemExit):
        run(ledger, "add", "y", "--destination", "skill")


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------

def test_add_records_open_when_unclassified(ledger):
    run(ledger, "add", "something broke", "--session", "S076", "--found-by", "user")
    r = records(ledger)[0]
    assert r["status"] == "open"
    assert r["classification"] is None and r["destination"] is None
    assert r["found_by"] == "user"


def test_classify_sets_the_destination(ledger):
    run(ledger, "add", "encoding rule ignored")
    assert run(ledger, "classify", "L001", "--as", "execution_failure") == 0
    r = records(ledger)[0]
    assert r["destination"] == "mechanism" and r["status"] == "classified"


def test_route_refuses_an_unclassified_lesson(ledger):
    run(ledger, "add", "untriaged")
    assert run(ledger, "route", "L001", "some-skill") == 3


def test_route_refuses_a_one_off(ledger):
    """A one-off with a target is how noise enters a skill."""
    run(ledger, "add", "flaky network", "--classify", "one_off")
    assert run(ledger, "route", "L001", "some-skill") == 3


def test_route_accepts_a_classified_lesson(ledger):
    run(ledger, "add", "no portability knowledge", "--classify", "capability_gap")
    assert run(ledger, "route", "L001", "writing-portable-python") == 0
    assert records(ledger)[0]["target"] == "writing-portable-python"


def test_reject_without_a_rationale_is_refused(ledger):
    """A rejected lesson with no reason is indistinguishable from one nobody looked at —
    which is precisely the failure this ledger exists to end."""
    run(ledger, "add", "x", "--classify", "one_off")
    assert run(ledger, "close", "L001", "--reject") == 3
    assert run(ledger, "close", "L001", "--reject", "--rationale", "env-specific") == 0
    assert records(ledger)[0]["status"] == "rejected"


def test_ids_increment_and_do_not_collide(ledger):
    for i in range(3):
        run(ledger, "add", f"lesson {i}")
    assert [r["id"] for r in records(ledger)] == ["L001", "L002", "L003"]


def test_unknown_id_is_an_input_error_not_a_crash(ledger):
    run(ledger, "add", "x")
    assert run(ledger, "classify", "L999", "--as", "one_off") == 3


# --------------------------------------------------------------------------
# Reporting — follow-through has to be visible or it does not happen
# --------------------------------------------------------------------------

def test_report_is_nonzero_while_work_is_outstanding(ledger):
    run(ledger, "add", "open item", "--classify", "capability_gap")
    assert run(ledger, "report") == 2


def test_report_is_zero_once_everything_is_applied(ledger):
    run(ledger, "add", "done item", "--classify", "capability_gap")
    run(ledger, "route", "L001", "writing-portable-python")
    run(ledger, "close", "L001", "--rationale", "rule added")
    assert run(ledger, "report") == 0


def test_report_on_an_empty_ledger_is_clean(ledger):
    assert run(ledger, "report") == 0


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

def test_round_trips_non_ascii(ledger):
    """The ledger records encoding defects, so it had better survive one."""
    run(ledger, "add", "cp1252 killed the digest → exit 0", "--classify", "one_off")
    assert "→" in records(ledger)[0]["title"]
    raw = ledger.read_text(encoding="utf-8")
    assert "→" in raw and json.loads(raw.splitlines()[0])


def test_write_is_atomic_and_leaves_no_temp_files(ledger):
    run(ledger, "add", "a")
    run(ledger, "add", "b")
    leftovers = [p.name for p in ledger.parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_missing_ledger_reads_as_empty_not_an_error(tmp_path):
    assert les._read(tmp_path / "nope.jsonl") == []


# --------------------------------------------------------------------------
# Dogfood
# --------------------------------------------------------------------------

def test_lessons_module_is_itself_portable():
    """It is infrastructure that must run on the Windows box that produced the lessons."""
    assert lint.check_path(META / "lessons.py") == []
