#!/usr/bin/env python3
"""Tests for drift_runner.py (Evergreening v1, S041) — the binding flap rules.

§9.1: drift 2-consecutive-removal rule + extractor-error separation.

These import drift_runner from ../scripts. Pure-logic tests (no live --help calls),
so they run in CI (NOT manual). Run via pytest (the affordance-advisor suite) or:
  python3 -m pytest ~/.claude/skills/affordance-advisor/tests/test_drift_runner.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import drift_runner as dr  # noqa: E402


def test_addition_reported_immediately():
    state = {}
    res = {"registry": "x", "status": "probed",
           "added_in_help": ["newcmd"], "removed_from_help": []}
    dr.apply_flap_rules(res, state)
    assert res["reportable"]["additions"] == ["newcmd"]
    assert res["reportable"]["removals_confirmed"] == []


def test_removal_requires_two_consecutive():
    state = {}
    # first observation -> pending
    r1 = {"registry": "x", "status": "probed", "added_in_help": [],
          "removed_from_help": ["gone"]}
    dr.apply_flap_rules(r1, state)
    assert r1["reportable"]["removals_pending"] == ["gone"]
    assert r1["reportable"]["removals_confirmed"] == []
    # second consecutive observation of the SAME removal -> confirmed
    r2 = {"registry": "x", "status": "probed", "added_in_help": [],
          "removed_from_help": ["gone"]}
    dr.apply_flap_rules(r2, state)
    assert r2["reportable"]["removals_confirmed"] == ["gone"]
    assert r2["reportable"]["removals_pending"] == []


def test_removal_not_confirmed_if_not_repeated():
    state = {}
    r1 = {"registry": "x", "status": "probed", "added_in_help": [],
          "removed_from_help": ["a"]}
    dr.apply_flap_rules(r1, state)
    # next run a DIFFERENT removal -> "a" is no longer pending, "b" is newly pending
    r2 = {"registry": "x", "status": "probed", "added_in_help": [],
          "removed_from_help": ["b"]}
    dr.apply_flap_rules(r2, state)
    assert r2["reportable"]["removals_confirmed"] == []  # neither confirmed
    assert r2["reportable"]["removals_pending"] == ["b"]


def test_extractor_error_reports_no_drift_and_clears_state():
    state = {"x": {"removed_from_help": ["pending"]}}
    res = {"registry": "x", "status": "extractor_error",
           "detail": "regex got nothing"}
    dr.apply_flap_rules(res, state)
    assert res["reportable"]["additions"] == []
    assert res["reportable"]["removals_confirmed"] == []
    assert res["reportable"]["removals_pending"] == []
    assert "x" not in state  # cleared (cannot confirm without a real probe)


def test_help_failed_is_not_drift():
    state = {}
    res = {"registry": "x", "status": "help_failed", "detail": "timeout"}
    dr.apply_flap_rules(res, state)
    assert res["reportable"]["removals_confirmed"] == []
    assert res["reportable"]["additions"] == []


def test_binary_absent_is_not_drift():
    state = {}
    res = {"registry": "x", "status": "binary_absent"}
    dr.apply_flap_rules(res, state)
    assert res["reportable"]["additions"] == []
    assert res["reportable"]["removals_confirmed"] == []


def test_not_a_drift_target():
    rep = dr.run_drift(["copilot-chat.yaml"], use_state=False)
    statuses = {r["registry"]: r["status"] for r in rep["results"]}
    assert statuses["copilot-chat.yaml"] == "not_a_drift_target"


# --- #139: floor-aware extraction-status classifier -------------------------------

def test_extraction_status_empty_is_error():
    assert dr._extraction_status(set(), frozenset()) == "extractor_error"


def test_extraction_status_floor_satisfied_is_ok():
    assert dr._extraction_status({"-p", "--add-dir", "models"},
                                 frozenset({"-p", "--add-dir"})) == "ok"


def test_extraction_status_floor_missing_is_error():
    """The live #139 signature: a parse that drops agy's bedrock flags must be an
    extractor_error, NOT a probe that then reports those flags as removed."""
    # extraction missing -p / --add-dir (the broken-parse case)
    assert dr._extraction_status({"changelog", "models", "install"},
                                 frozenset({"-p", "--add-dir"})) == "extractor_error"


def test_no_floor_means_no_floor_check():
    # CLIs without a defined floor only fail on empty extraction.
    assert dr._extraction_status({"anything"}, frozenset()) == "ok"
