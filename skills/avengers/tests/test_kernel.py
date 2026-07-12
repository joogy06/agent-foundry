#!/usr/bin/env python3
"""avengers — test_kernel.py (WP-2).

Covers the four acceptance areas: phase transitions, budgets, quorum, and atomic
transcript append — plus the stalemate termination guarantee and obligation
bookkeeping (chair sets answered/conceded; kernel sets stalemate).

Runs under pytest; stdlib only. The kernel module is imported by path so the test
does not depend on package layout.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_KERNEL = Path(__file__).resolve().parent.parent / "scripts" / "kernel.py"
_spec = importlib.util.spec_from_file_location("avengers_kernel", _KERNEL)
kernel = importlib.util.module_from_spec(_spec)
# Register before exec so dataclass forward-refs (from __future__ import
# annotations) resolve via sys.modules[cls.__module__].
sys.modules["avengers_kernel"] = kernel
_spec.loader.exec_module(kernel)


BUDGETS = {"max_seat_calls": 10, "wall_clock_s": 900, "max_cycles": 1}


def _sess(**overrides):
    b = dict(BUDGETS)
    b.update(overrides.pop("budgets", {}))
    return kernel.new_session("test-session", b, **overrides)


# --------------------------------------------------------------------------- #
# Phase transitions
# --------------------------------------------------------------------------- #
def test_happy_path_full_sequence():
    s = _sess()
    kernel.start_session(s, now=0.0)
    order = [
        kernel.BLIND_DIVERGE, kernel.DOCKET, kernel.CROSS_EXAM, kernel.CONVERGE,
        kernel.ARBITER, kernel.ROUTE, kernel.WRITEBACK_PROPOSE, kernel.CLOSED,
    ]
    for ph in order:
        kernel.transition(s, ph)
    assert s.phase == kernel.CLOSED
    assert s.cross_exam_cycle == 1


def test_illegal_transition_raises():
    s = _sess()
    with pytest.raises(kernel.PhaseError):
        kernel.transition(s, kernel.ARBITER)  # CONVENE -> ARBITER is illegal


def test_cannot_leave_terminal_phase():
    s = _sess()
    kernel.transition(s, kernel.ABORTED)  # CONVENE -> ABORTED is legal
    assert s.phase == kernel.ABORTED
    with pytest.raises(kernel.PhaseError):
        kernel.transition(s, kernel.CLOSED)


def test_abort_reachable_from_nonterminal():
    for start_to in (kernel.BLIND_DIVERGE, kernel.DOCKET):
        s = _sess()
        kernel.transition(s, kernel.BLIND_DIVERGE)
        if start_to == kernel.DOCKET:
            kernel.transition(s, kernel.DOCKET)
        kernel.abort(s, reason="unrecoverable")
        assert s.phase == kernel.ABORTED


def test_is_legal_transition_table():
    assert kernel.is_legal_transition(kernel.DOCKET, kernel.CROSS_EXAM)
    assert kernel.is_legal_transition(kernel.CROSS_EXAM, kernel.CROSS_EXAM)
    assert not kernel.is_legal_transition(kernel.CONVERGE, kernel.CROSS_EXAM)
    assert not kernel.is_legal_transition(kernel.CLOSED, kernel.ROUTE)


# --------------------------------------------------------------------------- #
# Budgets
# --------------------------------------------------------------------------- #
def test_max_seat_calls_enforced():
    s = _sess(budgets={"max_seat_calls": 3})
    kernel.record_seat_call(s)
    kernel.record_seat_call(s)
    assert kernel.record_seat_call(s) == 0  # remaining
    with pytest.raises(kernel.BudgetExceeded):
        kernel.record_seat_call(s)


def test_max_cycles_blocks_extra_cross_exam():
    s = _sess(budgets={"max_cycles": 1})
    kernel.transition(s, kernel.BLIND_DIVERGE)
    kernel.transition(s, kernel.DOCKET)
    kernel.transition(s, kernel.CROSS_EXAM)  # cycle 1
    assert not kernel.can_open_next_cycle(s)
    with pytest.raises(kernel.BudgetExceeded):
        kernel.transition(s, kernel.CROSS_EXAM)  # cycle 2 exceeds max_cycles=1
    # But CONVERGE is still legal -> termination guaranteed
    kernel.transition(s, kernel.CONVERGE)
    assert s.phase == kernel.CONVERGE


def test_two_cycles_allowed_when_budgeted():
    s = _sess(budgets={"max_cycles": 2})
    kernel.transition(s, kernel.BLIND_DIVERGE)
    kernel.transition(s, kernel.DOCKET)
    kernel.transition(s, kernel.CROSS_EXAM)  # 1
    kernel.transition(s, kernel.CROSS_EXAM)  # 2
    assert s.cross_exam_cycle == 2
    with pytest.raises(kernel.BudgetExceeded):
        kernel.transition(s, kernel.CROSS_EXAM)  # 3 > max_cycles


def test_wall_clock_budget():
    s = _sess(budgets={"wall_clock_s": 100})
    kernel.start_session(s, now=1000.0)
    assert not kernel.wall_clock_exhausted(s, now=1050.0)
    kernel.check_wall_clock(s, now=1050.0)  # no raise
    assert kernel.wall_clock_remaining(s, now=1050.0) == 50.0
    assert kernel.wall_clock_exhausted(s, now=1100.0)
    with pytest.raises(kernel.BudgetExceeded):
        kernel.check_wall_clock(s, now=1200.0)


# --------------------------------------------------------------------------- #
# Quorum
# --------------------------------------------------------------------------- #
def test_classify_runtime_quorum():
    assert kernel.classify_runtime_quorum(3) == kernel.QUORUM_OK
    assert kernel.classify_runtime_quorum(4) == kernel.QUORUM_OK
    assert kernel.classify_runtime_quorum(2) == kernel.QUORUM_LOW
    assert kernel.classify_runtime_quorum(1) == kernel.QUORUM_ABORTED
    assert kernel.classify_runtime_quorum(0) == kernel.QUORUM_ABORTED


def test_apply_runtime_quorum_low_continues():
    s = _sess()
    kernel.transition(s, kernel.BLIND_DIVERGE)
    status = kernel.apply_runtime_quorum(s, 2)
    assert status == kernel.QUORUM_LOW
    assert s.phase == kernel.BLIND_DIVERGE  # run continues
    assert s.quorum_status == kernel.QUORUM_LOW


def test_apply_runtime_quorum_abort_drives_terminal():
    s = _sess()
    kernel.transition(s, kernel.BLIND_DIVERGE)
    status = kernel.apply_runtime_quorum(s, 1)
    assert status == kernel.QUORUM_ABORTED
    assert s.phase == kernel.ABORTED  # <2 seats -> ABORTED, never silent success


# --------------------------------------------------------------------------- #
# Obligation bookkeeping + stalemate termination
# --------------------------------------------------------------------------- #
def test_create_and_chair_status():
    s = _sess()
    ob = kernel.create_obligation(s, "skeptic", "architect", "medium vs xhigh")
    assert ob == "OB-1"
    assert s.obligations[0].status == kernel.OBLIGATION_OPEN
    kernel.set_obligation_status(s, ob, kernel.OBLIGATION_ANSWERED, resolution="defended")
    assert s.obligations[0].status == kernel.OBLIGATION_ANSWERED


def test_chair_cannot_set_stalemate_or_open():
    s = _sess()
    ob = kernel.create_obligation(s, "a", "b", "t")
    with pytest.raises(kernel.ObligationError):
        kernel.set_obligation_status(s, ob, kernel.OBLIGATION_STALEMATE)
    with pytest.raises(kernel.ObligationError):
        kernel.set_obligation_status(s, ob, kernel.OBLIGATION_OPEN)


def test_unknown_obligation_raises():
    s = _sess()
    with pytest.raises(kernel.ObligationError):
        kernel.set_obligation_status(s, "OB-99", kernel.OBLIGATION_ANSWERED)


def test_stalemate_after_two_unchanged_exchanges():
    s = _sess()
    ob = kernel.create_obligation(s, "skeptic", "architect", "unresolved")
    r1 = kernel.record_exchange(s, ob, changed=False)
    assert r1["stalemate"] is False and r1["unchanged_exchanges"] == 1
    r2 = kernel.record_exchange(s, ob, changed=False)
    assert r2["stalemate"] is True and r2["status"] == kernel.OBLIGATION_STALEMATE
    # stalemate flows to arbiter as unresolved dissent
    assert ob in [o.id for o in kernel.unresolved_for_arbiter(s)]


def test_changed_exchange_resets_counter():
    s = _sess()
    ob = kernel.create_obligation(s, "a", "b", "t")
    kernel.record_exchange(s, ob, changed=False)
    kernel.record_exchange(s, ob, changed=True)  # progress resets
    assert s.obligations[0].unchanged_exchanges == 0
    r = kernel.record_exchange(s, ob, changed=False)
    assert r["stalemate"] is False  # only 1 unchanged since reset


def test_stalemate_threshold_distinct_from_max_cycles():
    # A large max_cycles must not change the stalemate threshold (they are distinct).
    s = _sess(budgets={"max_cycles": 5}, stalemate_threshold=2)
    ob = kernel.create_obligation(s, "a", "b", "t")
    kernel.record_exchange(s, ob, changed=False)
    r = kernel.record_exchange(s, ob, changed=False)
    assert r["stalemate"] is True


def test_answered_obligation_not_unresolved():
    s = _sess()
    ob = kernel.create_obligation(s, "a", "b", "t")
    kernel.set_obligation_status(s, ob, kernel.OBLIGATION_CONCEDED)
    assert kernel.unresolved_for_arbiter(s) == []


# --------------------------------------------------------------------------- #
# Atomic transcript append + digest
# --------------------------------------------------------------------------- #
def test_append_turn_writes_atomically_with_digest(tmp_path):
    tpath = tmp_path / "transcript.md"
    epath = tmp_path / "events.jsonl"
    s = _sess(transcript_path=tpath, event_log_path=epath)
    kernel.start_session(s, now=0.0)
    kernel.transition(s, kernel.BLIND_DIVERGE)
    r = kernel.append_turn(
        s, seat="skeptic", provider="codex", served_by="gpt-5.6-sol",
        ts="2026-07-11T20:05:00Z", body="Position: medium under-powers unpinned hard tasks.",
    )
    text = tpath.read_text(encoding="utf-8")
    assert "### TURN 0001 · BLIND_DIVERGE · skeptic · codex · gpt-5.6-sol" in text
    assert f"sha256:{r['digest']}" in text
    # digest recomputes deterministically from the same inputs
    recompute = kernel.turn_digest(
        turn_no=1, phase=kernel.BLIND_DIVERGE, seat="skeptic", provider="codex",
        served_by="gpt-5.6-sol", ts="2026-07-11T20:05:00Z",
        body="Position: medium under-powers unpinned hard tasks.",
    )
    assert recompute == r["digest"]
    # no temp files left behind (atomic rename cleaned up)
    assert not list(tmp_path.glob("*.tmp"))


def test_multiple_appends_accumulate_and_numbering(tmp_path):
    tpath = tmp_path / "t.md"
    s = _sess(transcript_path=tpath)
    kernel.transition(s, kernel.BLIND_DIVERGE)
    kernel.append_turn(s, seat="skeptic", provider="codex", ts="t1", body="one")
    kernel.append_turn(s, seat="architect", provider="claude", ts="t2", body="two")
    text = tpath.read_text(encoding="utf-8")
    assert "### TURN 0001" in text and "### TURN 0002" in text
    assert s.turn_no == 2
    assert s.seat_calls_used == 2  # each turn charged one seat call


def test_append_turn_seat_call_budget(tmp_path):
    s = _sess(budgets={"max_seat_calls": 1}, transcript_path=tmp_path / "t.md")
    kernel.transition(s, kernel.BLIND_DIVERGE)
    kernel.append_turn(s, seat="a", provider="codex", ts="t1", body="x")
    with pytest.raises(kernel.BudgetExceeded):
        kernel.append_turn(s, seat="b", provider="codex", ts="t2", body="y")


def test_cannot_append_in_terminal_phase(tmp_path):
    s = _sess(transcript_path=tmp_path / "t.md")
    kernel.transition(s, kernel.ABORTED)
    with pytest.raises(kernel.PhaseError):
        kernel.append_turn(s, seat="a", provider="codex", ts="t", body="x")


def test_event_log_is_valid_jsonl(tmp_path):
    epath = tmp_path / "events.jsonl"
    s = _sess(event_log_path=epath)
    kernel.start_session(s, now=0.0)
    kernel.transition(s, kernel.BLIND_DIVERGE)
    kernel.create_obligation(s, "a", "b", "t")
    lines = [ln for ln in epath.read_text(encoding="utf-8").splitlines() if ln.strip()]
    events = [json.loads(ln) for ln in lines]
    kinds = [e["event"] for e in events]
    assert "session_start" in kinds and "phase_transition" in kinds and "obligation_created" in kinds


# --------------------------------------------------------------------------- #
# Projection
# --------------------------------------------------------------------------- #
def test_projection_shape():
    s = _sess()
    kernel.start_session(s, now=0.0)
    kernel.transition(s, kernel.BLIND_DIVERGE)
    ob = kernel.create_obligation(s, "a", "b", "t")
    kernel.set_obligation_status(s, ob, kernel.OBLIGATION_ANSWERED)
    proj = kernel.session_projection(s, now=10.0)
    assert proj["phase"] == kernel.BLIND_DIVERGE
    assert proj["obligations_total"] == 1
    assert proj["obligations_by_status"].get("answered") == 1
    assert proj["seat_calls_remaining"] == BUDGETS["max_seat_calls"]
    assert proj["wall_clock_elapsed"] == 10.0


def test_write_ledger_roundtrip(tmp_path):
    s = _sess()
    kernel.create_obligation(s, "skeptic", "architect", "topic-1")
    lpath = tmp_path / "ledger.json"
    kernel.write_ledger(s, lpath)
    data = json.loads(lpath.read_text(encoding="utf-8"))
    assert data["session_id"] == "test-session"
    assert data["obligations"][0]["id"] == "OB-1"
    assert "projection" in data
