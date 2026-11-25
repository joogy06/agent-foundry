#!/usr/bin/env python3
"""Tests for escalation.py -- the model-escalation ladder (S081 rev 4, WP-B1).

Every positive claim has its CONTROL, because a ladder that always escalates and
a ladder that never escalates would each pass a suite of positives alone.

  identity is derived            <-> a supplied id is REFUSED, and the control is
                                     that omitting it works and counts up by one
  a new plan_hash CONTINUES      <-> a new plan_id STARTS FRESH
  a sticky verdict stands        <-> a capability failure with no sticky record
                                     ahead of it is recorded normally
  each never-escalating member   <-> a plain implementation failure ADVANCES
  `ok` needs evidence            <-> a bare "it worked" is refused, so the ladder
                                     does not treat it as a success

HOME DISCIPLINE. Every test passes `home=` explicitly, so no test can reach the
real `~/.claude/projects/<slug>/model-attempts.jsonl` even if the environment
misbehaves -- an argument is a stronger guarantee than an env var, and
`test_no_real_store_is_ever_created` asserts the real one is still absent.
"""
import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_META = _HERE.parent
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))

import escalation as esc  # noqa: E402
import review_risk as rr  # noqa: E402

PLAN = "S081-demo"
WP = "WP-B1"
KEY = PLAN + ":" + WP
HASH_A = "a" * 64
HASH_B = "b" * 64
PLAN_HASH_X = "x" * 64
PLAN_HASH_Y = "y" * 64


@pytest.fixture()
def home(tmp_path):
    """A fixture HOME. Never the real one."""
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture()
def root(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    return r


def fail(home, root, *, cls="implementation-failure", wp=WP, plan=PLAN,
         evidence=None, plan_hash=None, rung=None, source=esc.SOURCE_BOB):
    return esc.record(plan, wp, outcome=esc.OUTCOME_FAILED, project_root=root,
                      failure_class=cls, evidence_hash=evidence,
                      plan_hash=plan_hash, rung=rung, source=source, home=home)


def ladder(home, root, key=KEY, **kw):
    return esc.next_rung(key, project_root=root, home=home, **kw)


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
def test_the_store_lands_beside_the_budget_store_under_the_same_slug(home, root):
    path = esc.store_path_for(root, home=home)
    assert path.name == "model-attempts.jsonl"
    assert path.parent.parent == home / ".claude" / "projects"
    # The SAME slug rule as the budget store, not a second spelling of it, and
    # the same directory -- "beside astra-budget.jsonl" is literal.
    import codex_quota as cq
    assert path.parent.name == cq.project_slug(root)
    assert path.parent.name == cq.budget_path_for(root).parent.name


def test_the_store_is_append_only_jsonl_one_row_per_attempt(home, root):
    fail(home, root)
    fail(home, root)
    path = esc.store_path_for(root, home=home)
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2
    rows = [json.loads(ln) for ln in lines]
    assert [r["attempt_id"] for r in rows] == [1, 2]
    assert all(r["schema"] == esc.SCHEMA_VERSION for r in rows)


def test_the_lock_sidecar_sits_next_to_the_store(home, root):
    fail(home, root)
    store = esc.store_path_for(root, home=home)
    assert esc.lock_path_for(store) == store.with_name(store.name + ".lock")


def test_no_real_store_is_ever_created(home, root):
    """The hazard this WP adds: a model-attempts.jsonl under a REAL slug."""
    fail(home, root)
    real = Path.home() / ".claude" / "projects"
    if real.exists():
        strays = sorted(p for p in real.glob("*/model-attempts.jsonl"))
        assert strays == [], "a real model-attempts store appeared: {0}".format(strays)


# --------------------------------------------------------------------------- #
# Property 1 -- attempt identity is DERIVED, never supplied
# --------------------------------------------------------------------------- #
def test_a_caller_supplied_attempt_id_is_refused(home, root):
    with pytest.raises(esc.EscalationUsageError) as exc:
        esc.record(PLAN, WP, outcome=esc.OUTCOME_FAILED, project_root=root,
                   failure_class="implementation-failure", home=home, attempt_id=1)
    assert "derived" in str(exc.value).lower()


def test_control_omitting_the_id_works_and_the_counter_is_ours(home, root):
    """The control for the refusal: without a supplied id, recording works and
    the id counts up by one. A refusal that also broke the normal path would
    look identical from the failing test alone."""
    ids = [fail(home, root).attempt_id for _ in range(3)]
    assert ids == [1, 2, 3]


def test_a_caller_cannot_reset_its_own_history(home, root):
    """The property the refusal exists for, stated as behaviour rather than as
    an exception type."""
    for _ in range(2):
        fail(home, root)
    with pytest.raises(esc.EscalationUsageError):
        esc.record(PLAN, WP, outcome=esc.OUTCOME_FAILED, project_root=root,
                   failure_class="implementation-failure", home=home, attempt_id=1)
    # The history is untouched, so the ladder has not rewound.
    assert ladder(home, root).failed_attempts == 2
    assert ladder(home, root).rung == esc.RUNG_TAKEOVER


def test_the_id_is_per_task_key_not_global(home, root):
    fail(home, root, wp="WP-B1")
    fail(home, root, wp="WP-B1")
    assert fail(home, root, wp="WP-B2").attempt_id == 1


# --------------------------------------------------------------------------- #
# Property 2 -- revision lineage
# --------------------------------------------------------------------------- #
def test_a_new_plan_hash_continues_the_history(home, root):
    """The exact hazard the design calls out: re-planning is not a reset."""
    fail(home, root, plan_hash=PLAN_HASH_X)
    fail(home, root, plan_hash=PLAN_HASH_X)
    fail(home, root, plan_hash=PLAN_HASH_Y)
    assert ladder(home, root).failed_attempts == 3


def test_control_a_different_plan_id_starts_fresh(home, root):
    fail(home, root, plan_hash=PLAN_HASH_X)
    fail(home, root, plan_hash=PLAN_HASH_X)
    other = esc.task_key_for("S081-other", WP)
    assert ladder(home, root, key=other).failed_attempts == 0
    assert ladder(home, root, key=other).rung == esc.RUNG_OPUS


def test_the_plan_hash_is_recorded_but_is_not_part_of_the_key(home, root):
    fail(home, root, plan_hash=PLAN_HASH_X)
    row = json.loads(esc.store_path_for(root, home=home).read_text(
        encoding="utf-8").splitlines()[0])
    assert row["plan_hash"] == PLAN_HASH_X
    assert row["task_key"] == KEY and PLAN_HASH_X not in row["task_key"]


def test_task_key_is_plan_id_colon_wp_id_and_splits_back_exactly(home, root):
    assert esc.task_key_for(PLAN, WP) == KEY
    assert esc.split_task_key(KEY) == (PLAN, WP)


@pytest.mark.parametrize("plan_id,wp_id", [
    ("S081:demo", "WP-B1"),      # a colon in either half would make the split a guess
    ("S081-demo", "WP:B1"),
    ("", "WP-B1"),
    ("S081-demo", ""),
])
def test_an_ambiguous_task_key_is_refused(plan_id, wp_id):
    with pytest.raises(esc.EscalationUsageError):
        esc.task_key_for(plan_id, wp_id)


# --------------------------------------------------------------------------- #
# Property 3 -- sticky records
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("verdict", sorted(esc.STICKY_CLASSES))
def test_a_sticky_record_refuses_a_downgrade_to_capability_failure(home, root, verdict):
    """The criterion's own test: record a gate verdict, then try to record a
    capability failure for the same attempt -- the sticky record stands."""
    first = fail(home, root, cls=verdict)
    assert first.recorded
    result = fail(home, root, cls="capability-failure")
    assert result.recorded is False
    assert result.reason == esc.REASON_STICKY
    assert result.standing["failure_class"] == verdict
    # Nothing was appended: the store still holds exactly the sticky row.
    lines = [ln for ln in esc.store_path_for(root, home=home).read_text(
        encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1


def test_control_a_capability_failure_with_no_sticky_record_is_recorded(home, root):
    result = fail(home, root, cls="capability-failure")
    assert result.recorded is True
    assert result.attempt_id == 1


def test_the_sticky_refusal_covers_every_escalating_class_not_just_one(home, root):
    """Written against the CLASS, not against the one instance the criterion
    names: laundering a gate verdict as `implementation-failure` would buy a
    stronger model just as surely as laundering it as `capability-failure`.

    JUDGEMENT CALL, recorded and vetoable -- the criterion names only
    capability-failure; this is strictly stronger and implements the design's
    stated purpose ("a stronger model must never launder a failed gate")."""
    fail(home, root, cls="RED")
    for cls in sorted(esc.ESCALATING_CLASSES):
        assert fail(home, root, cls=cls).recorded is False


def test_a_sticky_record_is_superseded_by_FRESH_evidence(home, root):
    """The escape, in the design's own words: "a later PASS never erases an
    earlier RED/REJECTED WITHOUT FRESH EVIDENCE through the same gates". Without
    it a task that the user resolved could never resume."""
    fail(home, root, cls="RED", evidence=HASH_A)
    stale = fail(home, root, cls="trusted-runner-red", evidence=HASH_A)
    assert stale.recorded is False, "the SAME bundle is not fresh evidence"
    fresh = fail(home, root, cls="trusted-runner-red", evidence=HASH_B)
    assert fresh.recorded is True


def test_recording_another_never_escalating_class_is_not_a_downgrade(home, root):
    fail(home, root, cls="user-decision")
    assert fail(home, root, cls="REJECTED").recorded is True


def test_the_sticky_flag_is_written_on_the_row(home, root):
    fail(home, root, cls="AUDIT_UNAVAILABLE")
    row = json.loads(esc.store_path_for(root, home=home).read_text(
        encoding="utf-8").splitlines()[0])
    assert row["sticky"] is True


def test_a_plain_failure_row_is_not_sticky(home, root):
    fail(home, root, cls="implementation-failure")
    row = json.loads(esc.store_path_for(root, home=home).read_text(
        encoding="utf-8").splitlines()[0])
    assert row["sticky"] is False


def test_sticky_is_a_subset_of_never_escalates(home, root):
    assert esc.STICKY_CLASSES <= esc.NEVER_ESCALATES


# --------------------------------------------------------------------------- #
# D21 fix round 1 -- F1, F2, f8: the STANDING sticky row (plan L29).
#
# A sticky verdict STANDS until a later row carries FRESH evidence: a trusted-
# runner hash that appears on NO earlier row of the same task key. The standing
# row is found by a SCAN with supersession, never by reading mine[-1]; while it
# stands an advancing failure AND an `ok` need fresh evidence; an `ok` is
# terminal only while no failed row follows it; and next_rung() consults the
# standing sticky row BEFORE any success.
#
# Each red below was run against the round-base escalation.py (13a3e04) and
# FAILED there; the controls pass on both sides.
# --------------------------------------------------------------------------- #
HASH_C = "c" * 64

#: The never-escalating classes that are NOT sticky: routing facts that may be
#: recorded while a verdict stands, and so the rows that used to launder one.
NON_STICKY_NEVER_ESCALATES = sorted(esc.NEVER_ESCALATES - esc.STICKY_CLASSES)


def ok(home, root, evidence, *, wp=WP, plan=PLAN):
    return esc.record(plan, wp, outcome=esc.OUTCOME_OK, project_root=root,
                      evidence_hash=evidence, home=home)


def _rows(home, root):
    return [json.loads(ln) for ln in esc.store_path_for(root, home=home).read_text(
        encoding="utf-8").splitlines() if ln.strip()]


def _failed_row(cls, evidence=None):
    row = {"outcome": esc.OUTCOME_FAILED, "failure_class": cls,
           "sticky": cls in esc.STICKY_CLASSES}
    if evidence is not None:
        row["evidence_hash"] = evidence
    return row


def _ok_row(evidence):
    return {"outcome": esc.OUTCOME_OK, "evidence_hash": evidence, "sticky": False}


def _write_store(home, root, rows):
    """A store written DIRECTLY, bypassing record(): rows written before this fix,
    or a store edited by hand -- the case `_is_ok` already guards."""
    store = esc.store_path_for(root, home=home)
    store.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, extra in enumerate(rows, 1):
        row = {"schema": esc.SCHEMA_VERSION, "at": "2026-09-22T00:00:00Z",
               "task_key": KEY, "plan_id": PLAN, "wp_id": WP, "attempt_id": i,
               "source": esc.SOURCE_BOB}
        row.update(extra)
        lines.append(json.dumps(row, sort_keys=True))
    store.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_the_intervening_classes_are_exactly_the_seven_non_sticky_classes():
    """Vocabulary guard for the F1 grid below: if a class moves between the sets,
    the grid must be re-derived, not silently shrink. #313 added `clarification`:
    a question, non-sticky, so the answer can supersede it."""
    assert NON_STICKY_NEVER_ESCALATES == sorted([
        "budget-floor", "plan-recompile", "forge-amendment-mode",
        "reviewer-disagreement", "quota-exhausted", "auth-or-missing-tool", "clarification"])


# ---- F1: one intervening non-sticky row used to unshield a standing verdict ----
@pytest.mark.parametrize("between", NON_STICKY_NEVER_ESCALATES)
@pytest.mark.parametrize("sticky", sorted(esc.STICKY_CLASSES))
def test_f1_one_intervening_non_sticky_row_does_not_unshield_a_standing_verdict(
        home, root, sticky, between):
    """codex-1 / fable-p1-3: `record()` read only mine[-1], so RED -> budget-floor
    -> capability-failure was recorded and the ladder climbed to `diagnosis` --
    two writes achieved what one is refused."""
    assert fail(home, root, cls=sticky).recorded
    assert fail(home, root, cls=between).recorded, (
        "a non-advancing routing fact is still recordable while a verdict stands")
    third = fail(home, root, cls="capability-failure")
    assert third.recorded is False, "the intervening row laundered the standing verdict"
    assert third.reason == esc.REASON_STICKY
    assert third.standing["failure_class"] == sticky
    assert len(_rows(home, root)) == 2, "nothing was appended by the refused record"
    verdict = ladder(home, root)
    assert verdict.rung == esc.RUNG_USER
    assert verdict.reason == esc.REASON_STICKY
    assert verdict.standing["failure_class"] == sticky


@pytest.mark.parametrize("sticky", sorted(esc.STICKY_CLASSES))
def test_f1_two_intervening_rows_do_not_unshield_it_either(home, root, sticky):
    fail(home, root, cls=sticky)
    assert fail(home, root, cls="budget-floor").recorded
    assert fail(home, root, cls="plan-recompile").recorded
    for cls in sorted(esc.ESCALATING_CLASSES):
        result = fail(home, root, cls=cls)
        assert result.recorded is False, cls
        assert result.standing["failure_class"] == sticky, cls
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.RUNG_USER, esc.REASON_STICKY)
    assert verdict.standing["failure_class"] == sticky


def test_f1_a_store_already_holding_the_laundered_rows_goes_to_the_user(home, root):
    """The review's reproduction as rows ALREADY on disk (written before this
    fix): RED -> budget-floor -> capability-failure used to yield `diagnosis`."""
    _write_store(home, root, [_failed_row("RED"), _failed_row("budget-floor"),
                              _failed_row("capability-failure")])
    verdict = ladder(home, root)
    assert verdict.rung == esc.RUNG_USER, "a laundered RED bought the diagnosis seat"
    assert verdict.reason == esc.REASON_STICKY
    assert verdict.standing["attempt_id"] == 1


# ---- F2: an `ok` masked a later verdict, and an `ok` on the RED's own hash erased it ----
@pytest.mark.parametrize("sticky", sorted(esc.STICKY_CLASSES))
def test_f2_an_earlier_ok_does_not_mask_a_later_standing_verdict(home, root, sticky):
    """codex-4: `any(_is_ok)` was checked BEFORE the standing verdict, so
    ok(A) -> RED(B) returned none / already-ok-with-evidence."""
    assert ok(home, root, HASH_A).recorded
    assert fail(home, root, cls=sticky, evidence=HASH_B).recorded
    verdict = ladder(home, root)
    assert verdict.rung == esc.RUNG_USER, "a historical ok masked the verdict"
    assert verdict.reason == esc.REASON_STICKY
    assert verdict.standing["failure_class"] == sticky


def test_f2_an_ok_is_terminal_only_while_no_failure_follows_it(home, root):
    """The same mechanism without a gate: a success followed by a failure
    re-enters the ladder at that failure count (plan L29 (d), (e)).

    Listed by the plan among the controls; MEASURED RED at the round base
    (next_rung returned none), so it is counted as an F2 red, not a control."""
    ok(home, root, HASH_A)
    assert fail(home, root, cls="implementation-failure").recorded
    verdict = ladder(home, root)
    assert verdict.rung == esc.LADDER[1]
    assert verdict.reason == esc.REASON_LADDER
    assert verdict.failed_attempts == 1


@pytest.mark.parametrize("sticky", sorted(esc.STICKY_CLASSES))
def test_f2_an_ok_carrying_the_standing_verdicts_own_hash_is_refused(home, root, sticky):
    """fable-p1-2: "a later PASS never erases an earlier RED WITHOUT FRESH
    EVIDENCE" was enforced on a later FAILURE only; an ok on the RED's own
    hash was accepted and made the key terminal."""
    fail(home, root, cls=sticky, evidence=HASH_A)
    result = ok(home, root, HASH_A)
    assert result.recorded is False, "an ok on the verdict's own bundle erased it"
    assert result.reason == esc.REASON_STICKY
    assert result.standing["failure_class"] == sticky
    assert len(_rows(home, root)) == 1
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.RUNG_USER, esc.REASON_STICKY)


def test_f2_a_store_holding_red_then_ok_on_the_same_hash_goes_to_the_user(home, root):
    """The hand-edited (or pre-fix) store: RED(H) -> ok(H) on disk. The sticky
    check precedes the ok check (plan L29 (d), THE REFINEMENT), so the stale ok
    cannot answer `none`."""
    _write_store(home, root, [_failed_row("RED", HASH_A), _ok_row(HASH_A)])
    verdict = ladder(home, root)
    assert verdict.rung == esc.RUNG_USER, "a stale ok erased a standing RED"
    assert verdict.reason == esc.REASON_STICKY
    assert verdict.standing["failure_class"] == "RED"


# ---- f8: "fresh" means a hash NO earlier row of the key carried ----
def test_f8_a_hash_an_earlier_row_carried_is_not_fresh_for_a_failure(home, root):
    """fable-p1-7: freshness compared only the standing row's hash, so a bundle
    the key had already seen passed as fresh evidence."""
    fail(home, root, cls="implementation-failure", evidence=HASH_A)   # H1
    fail(home, root, cls="RED", evidence=HASH_B)                      # H2
    result = fail(home, root, cls="trusted-runner-red", evidence=HASH_A)
    assert result.recorded is False, "a reused bundle passed as fresh evidence"
    assert result.reason == esc.REASON_STICKY
    assert result.standing["failure_class"] == "RED"
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.RUNG_USER, esc.REASON_STICKY)


def test_f8_a_hash_an_earlier_row_carried_is_not_fresh_for_an_ok(home, root):
    fail(home, root, cls="implementation-failure", evidence=HASH_A)   # H1
    fail(home, root, cls="RED", evidence=HASH_B)                      # H2
    result = ok(home, root, HASH_A)
    assert result.recorded is False, "an ok on a reused bundle erased the RED"
    assert result.reason == esc.REASON_STICKY
    assert result.standing["failure_class"] == "RED"


def test_f8_supersession_on_read_needs_a_hash_no_earlier_row_carried(home, root):
    """The same rule on READ: rows on disk implementation-failure(H1) -> RED(H2)
    -> trusted-runner-red(H1) do not supersede the RED (H1 is not fresh)."""
    _write_store(home, root, [_failed_row("implementation-failure", HASH_A),
                              _failed_row("RED", HASH_B),
                              _failed_row("trusted-runner-red", HASH_A)])
    verdict = ladder(home, root)
    assert verdict.rung == esc.RUNG_USER, "a reused bundle superseded the RED on read"
    assert verdict.reason == esc.REASON_STICKY
    assert verdict.standing["failure_class"] == "RED"


# ---- CONTROLS: the escape and the ordinary ladder survive (green on both sides) ----
def test_control_fresh_evidence_on_a_failure_supersedes_and_the_ladder_advances(home, root):
    fail(home, root, cls="RED", evidence=HASH_A)
    assert fail(home, root, cls="trusted-runner-red", evidence=HASH_C).recorded is True
    verdict = ladder(home, root)
    assert verdict.reason == esc.REASON_LADDER
    assert verdict.failed_attempts == 2, "every failed row still counts on the ladder"
    assert verdict.rung == esc.LADDER[2]


def test_control_fresh_evidence_on_an_ok_supersedes_and_the_key_is_done(home, root):
    fail(home, root, cls="RED", evidence=HASH_A)
    assert ok(home, root, HASH_C).recorded is True
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.RUNG_NONE, esc.REASON_ALREADY_OK)


def test_control_after_supersession_nothing_stands(home, root):
    """Once fresh evidence superseded the verdict, an evidence-less advancing
    failure is an ordinary failure again -- the escape must not become a
    permanent lock."""
    fail(home, root, cls="RED", evidence=HASH_A)
    ok(home, root, HASH_C)
    assert fail(home, root, cls="implementation-failure").recorded is True


def test_control_a_newer_sticky_row_becomes_the_standing_row(home, root):
    fail(home, root, cls="RED", evidence=HASH_A)
    fail(home, root, cls="trusted-runner-red", evidence=HASH_C)       # supersedes the RED
    fail(home, root, cls="REJECTED", evidence=HASH_B)                 # a newer verdict
    result = fail(home, root, cls="capability-failure")
    assert result.recorded is False
    assert result.standing["failure_class"] == "REJECTED"
    verdict = ladder(home, root)
    assert verdict.reason == esc.REASON_STICKY
    assert verdict.standing["failure_class"] == "REJECTED"


def test_control_a_newer_sticky_row_replaces_an_older_one_with_nothing_between(home, root):
    """L29 (b): the standing row is the LATEST sticky row. Added after the
    mutation round: mutant M4 ("the first sticky row keeps standing") escaped
    every other test, because the control above puts a superseding row between
    the two verdicts. The standing row is what the user is shown to resolve."""
    fail(home, root, cls="RED", evidence=HASH_A)
    fail(home, root, cls="REJECTED", evidence=HASH_B)
    result = fail(home, root, cls="capability-failure")
    assert result.recorded is False
    assert result.standing["failure_class"] == "REJECTED"
    assert result.attempt_id == 2
    verdict = ladder(home, root)
    assert verdict.standing["failure_class"] == "REJECTED"


def test_control_an_ok_alone_is_terminal(home, root):
    ok(home, root, HASH_A)
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.RUNG_NONE, esc.REASON_ALREADY_OK)


@pytest.mark.parametrize("member", NON_STICKY_NEVER_ESCALATES)
def test_control_a_non_sticky_never_escalating_row_alone_never_escalates(home, root, member):
    fail(home, root, cls=member)
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.RUNG_USER, esc.REASON_NEVER_ESCALATES)
    assert verdict.standing["failure_class"] == member


# --------------------------------------------------------------------------- #
# The NEVER-ESCALATES list -- a closed set, member by member
# --------------------------------------------------------------------------- #
def test_the_never_escalates_set_is_exactly_the_designs_list():
    assert esc.NEVER_ESCALATES == frozenset({
        "user-decision", "forge-amendment-mode", "plan-recompile", "budget-floor",
        "RED", "REJECTED", "AUDIT_UNAVAILABLE", "INDETERMINATE",
        "reviewer-disagreement", "quota-exhausted", "auth-or-missing-tool",
        "clarification",
    })


def test_the_two_vocabularies_are_disjoint():
    assert not (esc.NEVER_ESCALATES & esc.ESCALATING_CLASSES)


@pytest.mark.parametrize("member", sorted(esc.NEVER_ESCALATES))
def test_each_never_escalating_member_goes_to_the_user(home, root, member):
    fail(home, root, cls=member)
    verdict = ladder(home, root)
    assert verdict.rung == esc.RUNG_USER
    assert verdict.needs_kind == "user-decision"
    assert verdict.reason in (esc.REASON_STICKY, esc.REASON_NEVER_ESCALATES)


@pytest.mark.parametrize("member", sorted(esc.NEVER_ESCALATES))
def test_a_never_escalating_member_never_reaches_a_stronger_model(home, root, member):
    """Stronger than the rung check: no number of these ever buys fable or
    diagnosis, which is the laundering route."""
    for _ in range(4):
        fail(home, root, cls=member)
    assert ladder(home, root).rung == esc.RUNG_USER


@pytest.mark.parametrize("member", sorted(esc.ESCALATING_CLASSES))
def test_control_an_escalating_class_does_advance_the_ladder(home, root, member):
    fail(home, root, cls=member)
    assert ladder(home, root).rung == esc.RUNG_OPUS
    assert ladder(home, root).failed_attempts == 1


def test_control_a_plain_implementation_failure_advances(home, root):
    """The criterion's named control."""
    assert ladder(home, root).rung == esc.RUNG_OPUS
    fail(home, root, cls="implementation-failure")
    assert ladder(home, root).rung == esc.RUNG_OPUS
    fail(home, root, cls="implementation-failure")
    assert ladder(home, root).rung == esc.RUNG_TAKEOVER


def test_a_failure_class_outside_the_closed_set_is_refused(home, root):
    with pytest.raises(esc.EscalationUsageError):
        fail(home, root, cls="something-new")


def test_on_READ_an_unknown_class_does_not_escalate(home, root):
    """Strict on write, conservative on read: a row written by a later version
    with a class this one does not know must not be the row that buys a stronger
    model."""
    store = esc.store_path_for(root, home=home)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({
        "schema": esc.SCHEMA_VERSION, "task_key": KEY, "plan_id": PLAN, "wp_id": WP,
        "attempt_id": 1, "outcome": esc.OUTCOME_FAILED,
        "failure_class": "a-class-from-the-future"}) + "\n", encoding="utf-8")
    assert ladder(home, root).rung == esc.RUNG_USER


# --------------------------------------------------------------------------- #
# The ladder
# --------------------------------------------------------------------------- #
def test_the_ladder_climbs_opus_opus_takeover_diagnosis_user(home, root):
    assert ladder(home, root).rung == esc.RUNG_OPUS          # attempt 1
    fail(home, root)
    assert ladder(home, root).rung == esc.RUNG_OPUS          # attempt 2
    fail(home, root)
    assert ladder(home, root).rung == esc.RUNG_TAKEOVER      # takeover
    fail(home, root)
    assert ladder(home, root).rung == esc.RUNG_DIAGNOSIS     # read-only codex
    fail(home, root)
    assert ladder(home, root).rung == esc.RUNG_USER


def test_the_attempt_id_next_rung_reports_is_the_one_the_next_attempt_gets(home, root):
    assert ladder(home, root).attempt_id == 1
    assert fail(home, root).attempt_id == 1
    assert ladder(home, root).attempt_id == 2


@pytest.mark.parametrize("flag", ["takeover_touches_tests", "fable_touches_tests"])
def test_a_takeover_that_would_edit_a_test_file_goes_to_the_user(home, root, flag):
    """`fable_touches_tests` is the pre-#291 spelling and must keep working."""
    fail(home, root)
    fail(home, root)
    assert ladder(home, root).rung == esc.RUNG_TAKEOVER
    verdict = ladder(home, root, **{flag: True})
    assert verdict.rung == esc.RUNG_USER
    assert verdict.needs_kind == "user-decision"
    assert verdict.reason == esc.REASON_TAKEOVER_WOULD_EDIT_TESTS


@pytest.mark.parametrize("flag", ["takeover_touches_tests", "fable_touches_tests"])
def test_control_the_test_file_flag_only_bites_on_the_takeover_rung(home, root, flag):
    """At the opus rungs the flag changes nothing -- otherwise it would be a
    blanket "any test edit goes to the user", which is not the design."""
    assert ladder(home, root, **{flag: True}).rung == esc.RUNG_OPUS
    fail(home, root)
    assert ladder(home, root, **{flag: True}).rung == esc.RUNG_OPUS
    fail(home, root)
    fail(home, root)
    assert ladder(home, root, **{flag: True}).rung == esc.RUNG_DIAGNOSIS


def test_the_diagnosis_rung_carries_a_risk_promoted_size(home, root):
    for _ in range(3):
        fail(home, root)
    verdict = ladder(home, root, paths=["skills/_meta/gates.py"], size="light")
    assert verdict.rung == esc.RUNG_DIAGNOSIS
    assert verdict.size == "complex"
    assert verdict.size_source == rr.RISK_SIZE_SOURCE
    assert "gates_and_verification" in verdict.risk_families


def test_control_an_unrisky_diagnosis_keeps_its_declared_size(home, root):
    for _ in range(3):
        fail(home, root)
    verdict = ladder(home, root, paths=["README.md"], size="light",
                     size_source="forge")
    assert verdict.rung == esc.RUNG_DIAGNOSIS
    assert verdict.size == "light"
    assert verdict.size_source == "forge"


def test_only_the_diagnosis_rung_carries_a_size(home, root):
    assert ladder(home, root, paths=["skills/_meta/gates.py"], size="light").size is None


def test_the_diagnosis_rung_asks_for_the_escalation_diagnosis_needs_kind(home, root):
    for _ in range(3):
        fail(home, root)
    assert ladder(home, root).needs_kind == "escalation-diagnosis"


# --------------------------------------------------------------------------- #
# `ok` requires trusted-runner evidence
# --------------------------------------------------------------------------- #
def test_an_ok_needs_an_evidence_hash(home, root):
    with pytest.raises(esc.EscalationUsageError) as exc:
        esc.record(PLAN, WP, outcome=esc.OUTCOME_OK, project_root=root, home=home)
    assert "evidence" in str(exc.value).lower()


def test_control_an_ok_with_an_evidence_hash_is_recorded_and_is_terminal(home, root):
    result = esc.record(PLAN, WP, outcome=esc.OUTCOME_OK, project_root=root,
                        evidence_hash=HASH_A, home=home)
    assert result.recorded is True
    assert ladder(home, root).rung == esc.RUNG_NONE
    assert ladder(home, root).reason == esc.REASON_ALREADY_OK


def test_a_bare_it_worked_leaves_the_ladder_where_it_was(home, root):
    """The behavioural half of "no hash -> not ok": the refusal must not look
    like a success to the next caller."""
    fail(home, root)
    with pytest.raises(esc.EscalationUsageError):
        esc.record(PLAN, WP, outcome=esc.OUTCOME_OK, project_root=root, home=home)
    assert ladder(home, root).rung == esc.RUNG_OPUS
    assert ladder(home, root).rung != esc.RUNG_NONE


@pytest.mark.parametrize("bad", ["", "not-a-hash", "A" * 64, "a" * 63, "a" * 65, 123])
def test_a_malformed_evidence_hash_is_not_evidence(home, root, bad):
    with pytest.raises(esc.EscalationUsageError):
        esc.record(PLAN, WP, outcome=esc.OUTCOME_OK, project_root=root,
                   evidence_hash=bad, home=home)


def test_an_ok_row_hand_written_without_evidence_is_not_a_success(home, root):
    """`record()` refuses to write one, so this guards a store edited by hand."""
    store = esc.store_path_for(root, home=home)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({
        "schema": esc.SCHEMA_VERSION, "task_key": KEY, "plan_id": PLAN, "wp_id": WP,
        "attempt_id": 1, "outcome": esc.OUTCOME_OK}) + "\n", encoding="utf-8")
    assert ladder(home, root).rung != esc.RUNG_NONE


def test_an_ok_carries_no_failure_class(home, root):
    with pytest.raises(esc.EscalationUsageError):
        esc.record(PLAN, WP, outcome=esc.OUTCOME_OK, project_root=root,
                   evidence_hash=HASH_A, failure_class="implementation-failure",
                   home=home)


# --------------------------------------------------------------------------- #
# The per-plan cap
# --------------------------------------------------------------------------- #
def test_the_cap_sums_failures_across_every_wp_of_one_plan(home, root):
    """A renamed WP cannot loop: the cap is per plan_id, not per task key."""
    for i in range(6):
        fail(home, root, wp="WP-{0}".format(i))
    fresh = esc.task_key_for(PLAN, "WP-brand-new")
    verdict = ladder(home, root, key=fresh)
    assert verdict.rung == esc.RUNG_USER
    assert verdict.reason == esc.REASON_PLAN_CAP
    assert verdict.plan_failed_attempts == 6


def test_control_five_failures_still_leave_a_rung(home, root):
    """The boundary, named: six are allowed, the seventh is not."""
    for i in range(5):
        fail(home, root, wp="WP-{0}".format(i))
    verdict = ladder(home, root, key=esc.task_key_for(PLAN, "WP-brand-new"))
    assert verdict.rung == esc.RUNG_OPUS
    assert verdict.plan_failed_attempts == 5


def test_control_another_plans_failures_do_not_count(home, root):
    for i in range(6):
        fail(home, root, plan="S081-other", wp="WP-{0}".format(i))
    assert ladder(home, root).rung == esc.RUNG_OPUS


def test_the_cap_beats_the_ladder_regardless_of_rung(home, root):
    for i in range(6):
        fail(home, root, wp="WP-{0}".format(i))
    # This key has ZERO failures of its own, so the ladder alone would say opus.
    verdict = ladder(home, root, key=esc.task_key_for(PLAN, "WP-untouched"))
    assert verdict.failed_attempts == 0
    assert verdict.rung == esc.RUNG_USER


# --------------------------------------------------------------------------- #
# Fail-soft -- a broken store degrades to the user, never to a success
# --------------------------------------------------------------------------- #
def test_an_absent_store_is_a_first_attempt_not_a_broken_one(home, root):
    assert not esc.store_path_for(root, home=home).exists()
    verdict = ladder(home, root)
    assert verdict.rung == esc.RUNG_OPUS
    assert verdict.degraded is None


def test_an_unparseable_row_degrades_the_ladder_to_the_user(home, root):
    fail(home, root)
    store = esc.store_path_for(root, home=home)
    with open(store, "a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    verdict = ladder(home, root)
    assert verdict.rung == esc.RUNG_USER
    assert verdict.reason == esc.REASON_STORE_DEGRADED
    assert verdict.degraded


def test_a_degraded_store_never_reports_a_success(home, root):
    """The direction that matters: degrading must not look like `ok`."""
    esc.record(PLAN, WP, outcome=esc.OUTCOME_OK, project_root=root,
               evidence_hash=HASH_A, home=home)
    store = esc.store_path_for(root, home=home)
    with open(store, "a", encoding="utf-8") as fh:
        fh.write("[]\n")
    assert ladder(home, root).rung == esc.RUNG_USER


def test_an_unreadable_store_degrades_rather_than_raising(home, root):
    store = esc.store_path_for(root, home=home)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.mkdir()                       # a directory where a file belongs
    history = esc.read_history(store)
    assert history.degraded
    assert ladder(home, root).rung == esc.RUNG_USER


def test_blank_lines_are_not_corruption(home, root):
    fail(home, root)
    store = esc.store_path_for(root, home=home)
    with open(store, "a", encoding="utf-8") as fh:
        fh.write("\n\n")
    verdict = ladder(home, root)
    assert verdict.degraded is None
    assert verdict.failed_attempts == 1


def test_an_unwritable_store_returns_a_result_instead_of_crashing_the_caller(home, root):
    store = esc.store_path_for(root, home=home)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.mkdir()
    result = fail(home, root)
    assert result.recorded is False
    assert result.reason == esc.REASON_STORE_UNWRITABLE
    assert result.error


# --------------------------------------------------------------------------- #
# Vocabulary and wiring
# --------------------------------------------------------------------------- #
def test_every_rung_has_a_needs_kind_entry():
    assert set(esc.NEEDS_KIND_BY_RUNG) == set(esc.RUNGS)


def test_the_ladder_constant_is_the_designs_ladder():
    assert esc.LADDER == ("opus", "opus", "takeover", "diagnosis")


def test_the_workflow_source_can_add_a_failure(home, root):
    """Design section 4.5: the workflow passes prior_attempts[] and they are
    recorded with source `workflow` -- it can add failures, never erase one."""
    result = fail(home, root, source=esc.SOURCE_WORKFLOW)
    assert result.row["source"] == esc.SOURCE_WORKFLOW
    assert ladder(home, root).failed_attempts == 1


def test_an_unknown_source_is_refused(home, root):
    with pytest.raises(esc.EscalationUsageError):
        fail(home, root, source="somewhere-else")


def test_next_rung_resolves_no_model(home, root):
    """This module must not be a second resolver inside the trust boundary:
    it names a RUNG, and seat_model turns that into a model."""
    verdict = ladder(home, root)
    assert "model" not in verdict.to_dict()


def test_to_dict_is_json_serialisable(home, root):
    fail(home, root)
    json.dumps(ladder(home, root).to_dict())
    json.dumps(fail(home, root).to_dict())


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def test_cli_next_reports_the_rung(home, root, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert esc.main(["--project-root", str(root), "next", "--task-key", KEY]) == 0
    assert "rung=opus" in capsys.readouterr().out


def test_cli_record_then_next(home, root, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert esc.main(["--project-root", str(root), "record", "--plan-id", PLAN,
                     "--wp-id", WP, "--outcome", "failed",
                     "--failure-class", "implementation-failure"]) == 0
    capsys.readouterr()
    assert esc.main(["--project-root", str(root), "next", "--task-key", KEY,
                     "--json"]) == 0
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["rung"] == "opus" and verdict["failed_attempts"] == 1


def test_cli_a_refused_record_exits_refused(home, root, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    base = ["--project-root", str(root), "record", "--plan-id", PLAN, "--wp-id", WP,
            "--outcome", "failed"]
    assert esc.main(base + ["--failure-class", "RED"]) == 0
    assert esc.main(base + ["--failure-class", "capability-failure"]) == esc.EXIT_REFUSED
    assert esc.REASON_STICKY in capsys.readouterr().out


def test_cli_an_ok_without_evidence_is_a_usage_error(home, root, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    code = esc.main(["--project-root", str(root), "record", "--plan-id", PLAN,
                     "--wp-id", WP, "--outcome", "ok"])
    assert code == esc.EXIT_USAGE
    assert "evidence" in capsys.readouterr().err.lower()


def test_cli_has_no_attempt_id_flag():
    """Identity is derived: there is no surface through which to supply one."""
    with pytest.raises(SystemExit):
        esc.main(["record", "--plan-id", PLAN, "--wp-id", WP, "--outcome", "failed",
                  "--failure-class", "implementation-failure", "--attempt-id", "1"])


# --------------------------------------------------------------------------- #
# WP-B3 -- the rung/next_rung round-trip against the LIVE schema.
#
# WP-B2 made the spelling drift a loud validation failure (the escalation object
# is `additionalProperties: false`) and wrote the mapping into bob.md. What was
# still open is that nothing PROVED a real NextRung survives the trip.
#
# Nothing PERFORMS the mapping in code, and nothing can: the producer of an
# execution report is the bob AGENT emitting structured output, not a module.
# Adding a `to_report_escalation()` helper here would ship a function with no
# production caller. So the mapping is asserted from the PRODUCER side instead,
# against the canonical schema on disk, with the unmapped form as the control.
#
# These also bind escalation.py's vocabulary to the schema's IN BOTH DIRECTIONS:
# a rung added here without being added there (or the reverse) fails.
# --------------------------------------------------------------------------- #

_SCHEMA_PATH = _META / "schemas" / "execution-report.v1.json"

try:
    import jsonschema as _jsonschema
except ImportError:                      # pragma: no cover - env-dependent
    _jsonschema = None

_needs_jsonschema = pytest.mark.skipif(_jsonschema is None, reason="jsonschema not installed")


def _schema():
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _report(**over):
    r = {"status": "PARTIAL", "built": [], "files_changed": [], "verification": {}}
    r.update(over)
    return r


def _as_report_escalation(verdict):
    """THE MAPPING, exactly as bob.md instructs an agent to perform it: rename
    `rung` to `next_rung` and project down to the three declared members."""
    d = verdict.to_dict()
    return {"next_rung": d["rung"], "task_key": d["task_key"], "attempt_id": d["attempt_id"]}


@_needs_jsonschema
@pytest.mark.parametrize("failures,expected", [
    (0, esc.RUNG_OPUS),
    (1, esc.RUNG_OPUS),
    (2, esc.RUNG_TAKEOVER),
    (3, esc.RUNG_DIAGNOSIS),
    (4, esc.RUNG_USER),
])
def test_a_real_next_rung_round_trips_through_the_schema(home, root, failures, expected):
    for _ in range(failures):
        fail(home, root)
    verdict = ladder(home, root)
    assert verdict.rung == expected
    block = _as_report_escalation(verdict)
    _jsonschema.validate(instance=_report(escalation=block), schema=_schema())
    assert block["next_rung"] == verdict.rung
    assert block["task_key"] == KEY
    assert block["attempt_id"] == failures + 1


@_needs_jsonschema
def test_control_the_unmapped_to_dict_is_REFUSED_by_the_schema(home, root):
    """The drift guard, proven from the producer side. A stage that dumps
    to_dict() wholesale hands the workflow a block whose rung it can never read,
    so the schema must reject it rather than let the ladder die silently."""
    verdict = ladder(home, root)
    raw = verdict.to_dict()
    assert "rung" in raw and "next_rung" not in raw, "to_dict() still spells it `rung`"
    with pytest.raises(_jsonschema.ValidationError):
        _jsonschema.validate(instance=_report(escalation=raw), schema=_schema())


@_needs_jsonschema
@pytest.mark.parametrize("drop", ["next_rung", "task_key", "attempt_id"])
def test_control_a_half_filled_block_is_refused(home, root, drop):
    block = _as_report_escalation(ladder(home, root))
    block.pop(drop)
    with pytest.raises(_jsonschema.ValidationError):
        _jsonschema.validate(instance=_report(escalation=block), schema=_schema())


@_needs_jsonschema
def test_every_rung_escalation_can_emit_is_accepted_by_the_schema():
    """Vocabulary binding, escalation.py -> schema. A rung added to RUNGS without
    being added to the schema enum fails HERE rather than in production. The
    schema enum is READABLE_RUNGS: the written rungs plus the legacy aliases."""
    allowed = _schema()["properties"]["escalation"]["properties"]["next_rung"]["enum"]
    assert set(esc.READABLE_RUNGS) == set(allowed), (
        "escalation.READABLE_RUNGS and the schema enum have drifted: "
        "READABLE_RUNGS={0} schema={1}".format(sorted(esc.READABLE_RUNGS), sorted(allowed))
    )
    for rung in esc.READABLE_RUNGS:
        _jsonschema.validate(
            instance=_report(escalation={"next_rung": rung, "task_key": KEY, "attempt_id": 1}),
            schema=_schema())


@_needs_jsonschema
def test_every_needs_kind_the_ladder_emits_is_in_the_schema_enum():
    """Vocabulary binding for the OTHER half of the ladder: the terminal rungs'
    needs.kind values must be spellable in a report."""
    allowed = _schema()["properties"]["needs"]["properties"]["kind"]["enum"]
    emitted = {k for k in esc.NEEDS_KIND_BY_RUNG.values() if k is not None}
    assert emitted, "the ladder emits no needs.kind at all -- the map is empty"
    assert emitted <= set(allowed), "ladder emits a needs.kind the schema rejects: {0}".format(
        sorted(emitted - set(allowed)))
    for kind in sorted(emitted):
        _jsonschema.validate(instance=_report(needs={"kind": kind}), schema=_schema())


@_needs_jsonschema
def test_the_retry_rungs_carry_no_needs_kind(home, root):
    """opus and takeover are RETRY rungs: the workflow re-runs them itself, so they
    must not surface a needs block. Only diagnosis and user are terminal."""
    for rung in (esc.RUNG_OPUS, esc.RUNG_TAKEOVER):
        assert esc.NEEDS_KIND_BY_RUNG[rung] is None
    assert esc.NEEDS_KIND_BY_RUNG[esc.RUNG_DIAGNOSIS] == "escalation-diagnosis"
    assert esc.NEEDS_KIND_BY_RUNG[esc.RUNG_USER] == "user-decision"


# --------------------------------------------------------------------------- #
# D21 fix round 2 -- N2 and R2-01 (plan L56, revision 44).
#
# N2 (fable-r2-2): a standing sticky verdict is superseded ONLY by an evidence-
# bearing gate outcome -- an `ok` or an ADVANCING failure -- that carries FRESH
# evidence. A non-advancing routing row (quota-exhausted, budget-floor, ...)
# NEVER supersedes, whatever hash it carries, and its hash still joins the seen
# set, so it can never be re-cited later as fresh.
#
# R2-01 (WP-X1 FOUND 1, widened at revision 44): an `ok` must cite a hash NO
# earlier row of the key carried -- any row, ok / failed / routing, superseded
# or not. record() refuses one and writes nothing (reason
# `ok-cites-seen-evidence` when no verdict stands; the sticky refusal still fires
# first while one does), and on READ such an `ok` is DISCOUNTED and TRANSPARENT
# to next_rung()'s success and latest-row checks.
#
# Every red below was run against the round-base escalation.py (615231b,
# sha256 d21bcc43) and FAILED there; every control passes on both sides.
# --------------------------------------------------------------------------- #
HASH_D = "d" * 64

#: The one new output value of the round, spelled as a LITERAL on purpose: a
#: report prints it, so a rename must fail here, by name.
OK_CITES_SEEN = "ok-cites-seen-evidence"


# ---- N2: a routing row carrying an UNSEEN hash used to supersede a verdict ----
@pytest.mark.parametrize("between", NON_STICKY_NEVER_ESCALATES)
@pytest.mark.parametrize("sticky", sorted(esc.STICKY_CLASSES))
def test_y2_N2_a_routing_row_carrying_an_unseen_hash_does_not_unshield_a_verdict(
        home, root, sticky, between):
    """fable-r2-2: STICKY(H1) -> <routing>(H2) -> capability-failure used to be
    recorded, and the ladder climbed -- F1's shape with a hash on the
    intervening row. The round base let ANY row with a fresh hash supersede."""
    assert fail(home, root, cls=sticky, evidence=HASH_A).recorded
    assert fail(home, root, cls=between, evidence=HASH_B).recorded, (
        "a non-advancing routing fact is still recordable while a verdict stands")
    third = fail(home, root, cls="capability-failure")
    assert third.recorded is False, "a routing row's unseen hash unshielded the verdict"
    assert third.reason == esc.REASON_STICKY
    assert third.standing["failure_class"] == sticky
    assert third.standing["attempt_id"] == 1
    assert len(_rows(home, root)) == 2, "nothing was appended by the refused record"
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.RUNG_USER, esc.REASON_STICKY)
    assert verdict.standing["failure_class"] == sticky


@pytest.mark.parametrize("between", NON_STICKY_NEVER_ESCALATES)
@pytest.mark.parametrize("sticky", sorted(esc.STICKY_CLASSES))
def test_y2_N2_seen_half_a_failure_re_citing_the_routing_rows_hash_is_refused(
        home, root, sticky, between):
    """The routing row's hash joins the seen set although the row never
    supersedes: an advancing failure re-citing it is not fresh evidence."""
    fail(home, root, cls=sticky, evidence=HASH_A)
    fail(home, root, cls=between, evidence=HASH_B)
    third = fail(home, root, cls="trusted-runner-red", evidence=HASH_B)
    assert third.recorded is False, "a hash the routing row carried passed as fresh"
    assert third.reason == esc.REASON_STICKY
    assert third.standing["failure_class"] == sticky
    assert len(_rows(home, root)) == 2
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.RUNG_USER, esc.REASON_STICKY)


@pytest.mark.parametrize("between", NON_STICKY_NEVER_ESCALATES)
def test_y2_N2_an_ok_re_citing_the_routing_rows_hash_meets_the_verdict_first(
        home, root, between):
    """While a verdict stands the sticky refusal fires FIRST and keeps its reason
    (L56 (c)); at the round base the routing row had already superseded the RED,
    so this `ok` was recorded and made the key terminal."""
    fail(home, root, cls="RED", evidence=HASH_A)
    fail(home, root, cls=between, evidence=HASH_B)
    result = ok(home, root, HASH_B)
    assert result.recorded is False
    assert result.reason == esc.REASON_STICKY
    assert result.standing["failure_class"] == "RED"
    assert len(_rows(home, root)) == 2
    assert ladder(home, root).rung == esc.RUNG_USER


@pytest.mark.parametrize("between", NON_STICKY_NEVER_ESCALATES)
def test_y2_N2_a_store_already_holding_the_laundered_rows_goes_to_the_user(
        home, root, between):
    """The review's reproduction as rows ALREADY on disk: RED(H1) ->
    quota-exhausted(H2) -> capability-failure yielded `diagnosis`."""
    _write_store(home, root, [_failed_row("RED", HASH_A), _failed_row(between, HASH_B),
                              _failed_row("capability-failure")])
    verdict = ladder(home, root)
    assert verdict.rung == esc.RUNG_USER, "a routing row's hash bought the diagnosis seat"
    assert verdict.reason == esc.REASON_STICKY
    assert verdict.standing["attempt_id"] == 1


@pytest.mark.parametrize("between", NON_STICKY_NEVER_ESCALATES)
def test_y2_N2_on_read_a_failure_re_citing_the_routing_rows_hash_supersedes_nothing(
        home, root, between):
    """The SEEN half on READ: RED(H1) -> <routing>(H2) -> trusted-runner-red(H2)
    on disk. The routing row's hash is seen, so the later failure is not fresh."""
    _write_store(home, root, [_failed_row("RED", HASH_A), _failed_row(between, HASH_B),
                              _failed_row("trusted-runner-red", HASH_B)])
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.RUNG_USER, esc.REASON_STICKY)
    assert verdict.standing["failure_class"] == "RED"


# ---- R2-01: an `ok` always cites a hash no earlier row of the key carried ----
def test_y2_R2_01_after_supersession_an_ok_on_the_superseded_verdicts_hash_is_refused(
        home, root):
    """WP-X1 FOUND 1: RED(H1) -> trusted-runner-red(H3, fresh, supersedes) ->
    ok(H1) was recorded and terminal -- the RED's own bundle re-certified."""
    assert fail(home, root, cls="RED", evidence=HASH_A).recorded
    assert fail(home, root, cls="trusted-runner-red", evidence=HASH_C).recorded
    result = ok(home, root, HASH_A)
    assert result.recorded is False, "an ok on the superseded RED's own bundle was recorded"
    assert result.reason == OK_CITES_SEEN
    assert result.standing["failure_class"] == "RED", "standing = the latest row that carried H1"
    assert result.attempt_id == 1
    assert len(_rows(home, root)) == 2, "the refusal wrote nothing"
    verdict = ladder(home, root)
    assert verdict.rung != esc.RUNG_NONE
    assert (verdict.rung, verdict.reason) == (esc.LADDER[2], esc.REASON_LADDER)


def test_y2_R2_01_with_no_verdict_at_all_an_ok_on_a_failed_rows_hash_is_refused(home, root):
    assert fail(home, root, cls="implementation-failure", evidence=HASH_A).recorded
    result = ok(home, root, HASH_A)
    assert result.recorded is False, "an ok re-certified the failed attempt's own bundle"
    assert result.reason == OK_CITES_SEEN
    assert result.standing["failure_class"] == "implementation-failure"
    assert len(_rows(home, root)) == 1
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.LADDER[1], esc.REASON_LADDER)


def test_y2_R2_01_an_ok_re_citing_an_earlier_oks_hash_after_a_failure_is_refused(home, root):
    """THE REVISION-44 RED (L56 (e) vetoed): ok(H1) -> wp-timeout -> ok(H1)
    re-certifies a re-run with stale evidence, F2's class."""
    assert ok(home, root, HASH_A).recorded
    assert fail(home, root, cls="wp-timeout").recorded
    result = ok(home, root, HASH_A)
    assert result.recorded is False, "a re-run was re-certified on the first run's bundle"
    assert result.reason == OK_CITES_SEEN
    assert result.standing["outcome"] == esc.OUTCOME_OK
    assert result.standing["attempt_id"] == 1
    assert len(_rows(home, root)) == 2
    verdict = ladder(home, root)
    assert verdict.rung != esc.RUNG_NONE
    assert (verdict.rung, verdict.reason) == (esc.LADDER[1], esc.REASON_LADDER)
    assert verdict.failed_attempts == 1


def test_y2_R2_01_the_same_ok_twice_is_refused_the_second_time(home, root):
    assert ok(home, root, HASH_A).recorded
    result = ok(home, root, HASH_A)
    assert result.recorded is False
    assert result.reason == OK_CITES_SEEN
    assert result.standing["attempt_id"] == 1
    assert len(_rows(home, root)) == 1
    assert ladder(home, root).rung == esc.RUNG_NONE, "the FIRST ok is still a genuine success"


def test_y2_R2_01_the_refusal_names_the_latest_row_that_carried_the_hash(home, root):
    """L56 (c): `standing` is the LATEST row that carried the hash -- here the
    second of two failures on the same bundle (no verdict stands, so both are
    recordable)."""
    assert fail(home, root, cls="implementation-failure", evidence=HASH_A).recorded
    assert fail(home, root, cls="trusted-runner-red", evidence=HASH_A).recorded
    result = ok(home, root, HASH_A)
    assert result.recorded is False
    assert result.reason == OK_CITES_SEEN
    assert (result.standing["attempt_id"], result.standing["failure_class"]) == (
        2, "trusted-runner-red")
    assert result.attempt_id == 2
    assert len(_rows(home, root)) == 2


def test_y2_R2_01_on_read_an_ok_on_a_superseded_verdicts_hash_is_not_a_success(home, root):
    """RED(H1), trusted-runner-red(H3), ok(H1) already on disk (a store written
    by hand or before this rule): the stale ok must not answer `none`."""
    _write_store(home, root, [_failed_row("RED", HASH_A),
                              _failed_row("trusted-runner-red", HASH_C), _ok_row(HASH_A)])
    verdict = ladder(home, root)
    assert verdict.rung != esc.RUNG_NONE, "a stale ok answered `none`"
    assert (verdict.rung, verdict.reason) == (esc.LADDER[2], esc.REASON_LADDER)


def test_y2_R2_01_on_read_an_ok_re_citing_an_earlier_oks_hash_is_not_a_success(home, root):
    """ok(H1), wp-timeout, ok(H1) on disk: the second ok's hash is on an earlier
    OK row, which counts exactly like any other earlier row."""
    _write_store(home, root, [_ok_row(HASH_A), _failed_row("wp-timeout"), _ok_row(HASH_A)])
    verdict = ladder(home, root)
    assert verdict.rung != esc.RUNG_NONE, "a re-run's stale ok answered `none`"
    assert (verdict.rung, verdict.reason) == (esc.LADDER[1], esc.REASON_LADDER)


def test_y2_R2_01_a_discounted_ok_is_transparent_to_the_latest_row_check(home, root):
    """L56 (d), WHY TRANSPARENT: RED(H1) -> capability-failure(H3) -> budget-floor
    -> ok(H1). Discounting alone would leave the stale ok LAST, hiding the
    budget-floor from the never-escalates check -- `diagnosis` instead of
    `user`, F1's exact shape through the read side."""
    _write_store(home, root, [_failed_row("RED", HASH_A),
                              _failed_row("capability-failure", HASH_C),
                              _failed_row("budget-floor"), _ok_row(HASH_A)])
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.RUNG_USER, esc.REASON_NEVER_ESCALATES)
    assert verdict.standing["failure_class"] == "budget-floor"


def test_y2_R2_01_an_ok_row_without_a_valid_hash_is_transparent_too(home, root):
    """L56 (d): the same transparency for an ok row with NO valid hash (a
    hand-edited store) -- it must not hide the routing row before it either."""
    _write_store(home, root, [_failed_row("implementation-failure"),
                              _failed_row("budget-floor"),
                              {"outcome": esc.OUTCOME_OK, "sticky": False}])
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.RUNG_USER, esc.REASON_NEVER_ESCALATES)
    assert verdict.standing["failure_class"] == "budget-floor"


def test_y2_R2_01_cli_a_refused_ok_exits_refused_and_prints_the_new_reason(
        home, root, monkeypatch, capsys):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    base = ["--project-root", str(root), "record", "--plan-id", PLAN, "--wp-id", WP]
    assert esc.main(base + ["--outcome", "ok", "--evidence-hash", HASH_A]) == esc.EXIT_OK
    capsys.readouterr()
    assert esc.main(base + ["--outcome", "ok", "--evidence-hash", HASH_A]) == esc.EXIT_REFUSED
    assert OK_CITES_SEEN in capsys.readouterr().out


# ---- CONTROLS: green at the round base AND after (never counted as reds) ----
@pytest.mark.parametrize("between", NON_STICKY_NEVER_ESCALATES)
def test_y2_control_a_routing_row_then_a_failure_with_its_own_fresh_hash_supersedes(
        home, root, between):
    """The escape survives N2: fresh evidence on an ADVANCING failure still
    supersedes a verdict that a routing row (with a hash of its own) sat after."""
    fail(home, root, cls="RED", evidence=HASH_A)
    fail(home, root, cls=between, evidence=HASH_B)
    assert fail(home, root, cls="trusted-runner-red", evidence=HASH_D).recorded is True
    verdict = ladder(home, root)
    assert verdict.reason == esc.REASON_LADDER
    counted = 3 - (between in esc.NOT_AN_ATTEMPT)     # #313: a clarification is not an attempt
    assert verdict.failed_attempts == counted
    assert verdict.rung == esc.LADDER[counted]


def test_y2_control_an_ok_with_a_fresh_hash_after_ordinary_failures_is_terminal(home, root):
    fail(home, root, cls="implementation-failure", evidence=HASH_A)
    fail(home, root, cls="wp-timeout")
    assert ok(home, root, HASH_B).recorded is True
    assert (ladder(home, root).rung, ladder(home, root).reason) == (
        esc.RUNG_NONE, esc.REASON_ALREADY_OK)


def test_y2_control_an_ok_after_a_failure_with_a_FRESH_hash_is_recorded_and_terminal(home, root):
    """The revision-44 control that replaces (e)'s: ok(H1) -> wp-timeout ->
    ok(H2, fresh) is a genuine new success."""
    assert ok(home, root, HASH_A).recorded
    assert fail(home, root, cls="wp-timeout").recorded
    assert ok(home, root, HASH_B).recorded is True
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.RUNG_NONE, esc.REASON_ALREADY_OK)


def test_y2_control_on_read_a_fresh_ok_after_a_failure_is_terminal(home, root):
    _write_store(home, root, [_ok_row(HASH_A), _failed_row("wp-timeout"), _ok_row(HASH_B)])
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.RUNG_NONE, esc.REASON_ALREADY_OK)


def test_y2_control_on_read_the_first_ok_on_a_hash_still_counts(home, root):
    """The discount removes the RE-citing ok only; the first ok on the hash is
    a genuine success and still answers `none`."""
    _write_store(home, root, [_ok_row(HASH_A), _ok_row(HASH_A)])
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.RUNG_NONE, esc.REASON_ALREADY_OK)


# ---- the docstring states the rule (GUARD -- reported, never counted as the fix) ----
#: Retired claims -- each FALSE (or no longer the whole rule) after N2 / R2-01.
#: Searched, case-insensitively and whitespace-normalised, over EVERY docstring
#: and comment of escalation.py.
_Y2_RETIRED = {
    # any later row with fresh evidence supersedes (N2: only an ok or an advancing failure)
    "unscoped-supersession":
        r"STANDS until a LATER row of the same task key carries FRESH evidence",
    "any-row-supersedes": r"a later row carrying FRESH evidence",
    "only-fresh-evidence-unscoped": r"only fresh evidence supersedes it",
    # true but no longer the whole rule: a row WITH fresh evidence may change nothing too
    "whatever-its-class": r"A row without fresh evidence changes nothing, whatever its class",
    # R2-01: an ok needs a fresh hash whether or not a verdict stands
    "ok-fresh-only-under-a-verdict": r"while a sticky row stands, a FRESH one",
}

#: Required facts -- each must appear in property 3 of the module docstring AND
#: in `_standing_sticky`'s docstring.
_Y2_REQUIRED = {
    "ok-or-advancing-only": r"ONLY by an `ok` or an ADVANCING failure",
    "routing-never-supersedes": r"NEVER supersedes, whatever hash it carries",
    "ok-never-cites-seen": r"an `ok` whose hash ANY earlier row of the key carried",
}

# The round-base passages, VERBATIM from escalation.py at 615231b (~/.claude is
# not a git repository, so they are embedded, never read through git). They are
# the NEGATIVE CONTROL: every retired claim must fire on them, and no required
# fact may be present in them.
_Y2_BASE_PROPERTY_3 = """3. USER DECISIONS AND GATE VERDICTS ARE STICKY. A standing `user-decision` or
   gate verdict (RED, REJECTED, AUDIT_UNAVAILABLE, INDETERMINATE) cannot be
   rewritten by a later classification into something that buys a stronger
   model. A stronger model must never launder a failed gate or decide a question
   the user owns.

   A sticky row STANDS until a LATER row of the same task key carries FRESH
   evidence: a trusted-runner hash that appears on NO earlier row of that key --
   any row, not only the sticky one. The standing row is found by scanning the
   key's whole history, never by reading its last row, so:
     * while it stands, an advancing failure AND an `ok` are both refused unless
       they carry fresh evidence (fresh against every row of the key);
     * a non-advancing routing fact (budget-floor, plan-recompile, ...) may still
       be recorded while it stands, and does NOT unshield it;
     * `next_rung()` consults the standing row BEFORE any success, and an `ok` is
       terminal only while no failed row follows it.
   Neither an intervening row, nor a historical `ok`, nor a reused hash can
   launder it; only fresh evidence supersedes it, and a newer sticky row then
   becomes the standing one itself.
"""

_Y2_BASE_LADDER_OK = """An `ok` outcome REQUIRES a trusted-runner evidence hash -- and, while a sticky
row stands, a FRESH one (property 3). A model saying "done" is not a result.
"""

_Y2_BASE_SCAN_DOC = """    One forward scan: a sticky row becomes the standing row (a newer verdict
    replaces an older one); a later row carrying FRESH evidence -- a hash on no
    earlier row of the key -- supersedes it, and nothing stands until a newer
    sticky row. A row without fresh evidence changes nothing, whatever its
    class, so an intervening routing fact cannot unshield a verdict (review
    finding F1) and a reused bundle cannot supersede one (f8).
"""

#: TRUE scoped sentences that reuse the retired words and must trip NOTHING.
_Y2_TRUE_SCOPED = (
    "A sticky row STANDS until a LATER `ok` or ADVANCING failure of the same task key"
    " carries FRESH evidence.",
    "A later `ok` or ADVANCING failure carrying FRESH evidence supersedes it.",
    "Only fresh evidence on an `ok` or an ADVANCING failure supersedes it.",
    "A routing row changes nothing, whatever its class and whatever hash it carries.",
    "An `ok` needs a FRESH hash whether or not a sticky row stands.",
)


def _y2_norm(text):
    return " ".join(text.split())


def _y2_hits(patterns, text):
    norm = _y2_norm(text)
    return {name for name, pat in patterns.items() if re.search(pat, norm, re.IGNORECASE)}


def _y2_prose(source):
    """Every docstring and every comment of a module -- never code, and never a
    string constant that is not a docstring."""
    tree = ast.parse(source)
    out = []
    for node in [tree] + [n for n in ast.walk(tree) if isinstance(
            n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]:
        doc = ast.get_docstring(node, clean=False)
        if doc:
            out.append(doc)
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            out.append(tok.string)
    return out


def _y2_property_3(module_doc):
    """Property 3 of the module docstring: from its heading to "THE LADDER".
    FAILS LOUDLY when either end is missing -- an empty section must never pass
    a required-fact check by being empty."""
    start = module_doc.find("3. USER DECISIONS AND GATE VERDICTS ARE STICKY.")
    end = module_doc.find("THE LADDER", start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        pytest.fail("escalation.py's module docstring has no property-3 section")
    section = module_doc[start:end]
    assert section.strip(), "the property-3 section is empty"
    return section


def _y2_function_doc(source, name):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            doc = ast.get_docstring(node, clean=False)
            if doc:
                return doc
    pytest.fail("escalation.py has no docstring on {0}()".format(name))


def _y2_escalation_source():
    return Path(esc.__file__).read_text(encoding="utf-8")


def test_y2_doc_no_retired_supersession_claim_survives_in_escalation_py():
    """GUARD (L56 (f)): no docstring or comment still states the round-base rule.
    FAILS on the round-base module, whose prose carries all five claims."""
    source = _y2_escalation_source()
    found = {}
    for prose in _y2_prose(source):
        for name in _y2_hits(_Y2_RETIRED, prose):
            found.setdefault(name, []).append(_y2_norm(prose)[:120])
    assert found == {}, "retired claims still stated: {0}".format(found)


@pytest.mark.parametrize("where", ["module-docstring-property-3", "standing-sticky-docstring"])
def test_y2_doc_property_3_and_the_scan_docstring_state_the_rule(where):
    """GUARD (L56 (f)): both places state N2 and R2-01 as implemented --
    supersession ONLY by an ok or an advancing failure, a routing fact never
    superseding whatever hash it carries, and an ok never citing a hash any
    earlier row of the key carried."""
    source = _y2_escalation_source()
    if where == "standing-sticky-docstring":
        text = _y2_function_doc(source, "_standing_sticky")
    else:
        text = _y2_property_3(ast.get_docstring(ast.parse(source), clean=False) or "")
    missing = sorted(set(_Y2_REQUIRED) - _y2_hits(_Y2_REQUIRED, text))
    assert missing == [], "{0} does not state: {1}".format(where, missing)


def test_y2_doc_control_the_needles_fire_on_the_base_passages_and_nothing_else():
    """CONTROL (green on both sides): every retired claim fires on its embedded
    round-base passage -- the per-passage map EXACTLY -- no required fact is in
    them, and the TRUE scoped sentences trip nothing."""
    claim_map = {
        "property 3": _y2_hits(_Y2_RETIRED, _Y2_BASE_PROPERTY_3),
        "the ladder's ok sentence": _y2_hits(_Y2_RETIRED, _Y2_BASE_LADDER_OK),
        "_standing_sticky()": _y2_hits(_Y2_RETIRED, _Y2_BASE_SCAN_DOC),
    }
    assert claim_map == {
        "property 3": {"unscoped-supersession", "only-fresh-evidence-unscoped"},
        "the ladder's ok sentence": {"ok-fresh-only-under-a-verdict"},
        "_standing_sticky()": {"any-row-supersedes", "whatever-its-class"},
    }
    assert set().union(*claim_map.values()) == set(_Y2_RETIRED), "a needle fires on no base text"
    for passage in (_Y2_BASE_PROPERTY_3, _Y2_BASE_SCAN_DOC):
        assert _y2_hits(_Y2_REQUIRED, passage) == set()
    for sentence in _Y2_TRUE_SCOPED:
        assert _y2_hits(_Y2_RETIRED, sentence) == set(), sentence


def test_y2_doc_control_the_extractors_are_demonstrated():
    """CONTROL: the prose extractor returns docstrings and comments and NEVER a
    plain string constant; the section extractor stops at THE LADDER (a required
    fact placed after it does not satisfy it) and fails LOUDLY without its
    heading."""
    synthetic = (
        '"""Module doc.\n\n3. USER DECISIONS AND GATE VERDICTS ARE STICKY. x\n\n'
        'THE LADDER\n----------\nNEVER supersedes, whatever hash it carries.\n"""\n'
        '# a comment here\n'
        'REASON = "a later row carrying FRESH evidence"\n'
        'def f():\n    """F doc."""\n    return 1\n')
    prose = _y2_prose(synthetic)
    assert any("Module doc." in p for p in prose)
    assert "F doc." in prose
    assert "# a comment here" in prose
    assert not any("a later row carrying" in p for p in prose), "a string constant was scanned"
    section = _y2_property_3(ast.get_docstring(ast.parse(synthetic), clean=False))
    assert "USER DECISIONS" in section and "THE LADDER" not in section
    assert "routing-never-supersedes" not in _y2_hits(_Y2_REQUIRED, section)
    with pytest.raises(pytest.fail.Exception):
        _y2_property_3("no such heading here\n\nTHE LADDER\n")
    with pytest.raises(pytest.fail.Exception):
        _y2_function_doc("def other():\n    pass\n", "_standing_sticky")


# ---- R2-02: one definition per name (STRUCTURE -- reported, never counted) ----
def _y2_duplicate_defs(source):
    names = [n.name for n in ast.parse(source).body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    return sorted({n for n in names if names.count(n) > 1})


def test_y2_R2_02_no_test_in_this_file_is_defined_twice():
    """A second module-level `def` of a name silently REPLACES the first, so only
    one is collected: test_the_retry_rungs_carry_no_needs_kind was defined twice
    (WP-X1 FOUND 2). The earlier two-assertion copy is deleted; the later
    superset stays. The negative control is a synthetic source with a repeat."""
    assert _y2_duplicate_defs("def t():\n    pass\n\n\ndef t():\n    pass\n") == ["t"]
    assert _y2_duplicate_defs(Path(__file__).read_text(encoding="utf-8")) == []


# --------------------------------------------------------------------------- #
# #291 WP-4 -- the takeover rung (renamed from `fable`, kept as a legacy READ
# alias). Written rungs are RUNGS; stored rows and reports may still carry the
# legacy spelling and must keep their meaning.
# --------------------------------------------------------------------------- #
#: The legacy spellings, LITERAL on purpose: they are what is already on disk.
LEGACY_RUNG = "fable"
LEGACY_REASON = "fable-takeover-would-edit-tests"


def _write_rows(home, root, rows):
    store = esc.store_path_for(root, home=home)
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _legacy_row(attempt_id, rung):
    return {"schema": esc.SCHEMA_VERSION, "task_key": KEY, "plan_id": PLAN, "wp_id": WP,
            "attempt_id": attempt_id, "outcome": esc.OUTCOME_FAILED, "source": esc.SOURCE_BOB,
            "sticky": False, "failure_class": "implementation-failure", "rung": rung}


def test_291_the_third_ladder_rung_is_takeover():
    assert esc.RUNG_TAKEOVER == "takeover"
    assert esc.LADDER[2] == esc.RUNG_TAKEOVER
    assert LEGACY_RUNG not in esc.RUNGS, "the legacy spelling is never a WRITTEN rung"
    assert LEGACY_RUNG not in esc.LADDER


def test_291_the_legacy_rung_is_readable_and_means_takeover():
    assert esc.is_readable_rung(LEGACY_RUNG)
    assert esc.canonical_rung(LEGACY_RUNG) == esc.RUNG_TAKEOVER
    for rung in esc.RUNGS:
        assert esc.canonical_rung(rung) == rung
    assert set(esc.READABLE_RUNGS) == set(esc.RUNGS) | {LEGACY_RUNG}
    assert not esc.is_readable_rung("gpt-9-omega")


def test_291_a_legacy_reason_string_is_recognised_on_read():
    assert esc.REASON_TAKEOVER_WOULD_EDIT_TESTS == "takeover-would-edit-tests"
    assert esc.canonical_reason(LEGACY_REASON) == esc.REASON_TAKEOVER_WOULD_EDIT_TESTS
    assert esc.canonical_reason(esc.REASON_LADDER) == esc.REASON_LADDER


def test_291_a_legacy_history_with_a_fable_rung_row_advances_correctly(home, root):
    """History written before the rename: two opus failures and a failed `fable`
    takeover. Read today it is clean (not degraded) and lands on diagnosis."""
    _write_rows(home, root, [_legacy_row(1, "opus"), _legacy_row(2, "opus"),
                             _legacy_row(3, LEGACY_RUNG)])
    history = esc.read_history(esc.store_path_for(root, home=home))
    assert not history.degraded
    assert all(esc.is_readable_rung(r["rung"]) for r in history.rows)
    verdict = ladder(home, root)
    assert verdict.failed_attempts == 3
    assert verdict.rung == esc.RUNG_DIAGNOSIS
    assert verdict.attempt_id == 4
    # ...and a new failure appended after it continues the same history.
    assert fail(home, root, rung=esc.RUNG_DIAGNOSIS).attempt_id == 4
    assert ladder(home, root).rung == esc.RUNG_USER


def test_291_control_a_legacy_history_before_the_takeover_reaches_takeover(home, root):
    _write_rows(home, root, [_legacy_row(1, "opus"), _legacy_row(2, "opus")])
    assert ladder(home, root).rung == esc.RUNG_TAKEOVER


def test_291_the_legacy_rung_is_never_written(home, root):
    with pytest.raises(esc.EscalationUsageError, match="legacy"):
        fail(home, root, rung=LEGACY_RUNG)
    assert not esc.store_path_for(root, home=home).exists(), "a refused write writes nothing"
    assert fail(home, root, rung=esc.RUNG_TAKEOVER).row["rung"] == esc.RUNG_TAKEOVER


def test_291_cli_record_does_not_offer_the_legacy_rung(home, root, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    base = ["--project-root", str(root), "record", "--plan-id", PLAN, "--wp-id", WP,
            "--outcome", "failed", "--failure-class", "implementation-failure"]
    with pytest.raises(SystemExit):
        esc.main(base + ["--rung", LEGACY_RUNG])
    assert esc.main(base + ["--rung", esc.RUNG_TAKEOVER]) == 0


@pytest.mark.parametrize("flag", ["--takeover-touches-tests", "--fable-touches-tests"])
def test_291_cli_both_test_edit_flags_refuse_a_test_editing_takeover(home, root, monkeypatch,
                                                                     capsys, flag):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    fail(home, root)
    fail(home, root)
    assert esc.main(["--project-root", str(root), "next", "--task-key", KEY, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["rung"] == esc.RUNG_TAKEOVER
    assert esc.main(["--project-root", str(root), "next", "--task-key", KEY, flag,
                     "--json"]) == 0
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["rung"] == esc.RUNG_USER
    assert verdict["reason"] == esc.REASON_TAKEOVER_WOULD_EDIT_TESTS


def test_291_cli_the_legacy_flag_is_hidden_from_help(capsys):
    with pytest.raises(SystemExit):
        esc.main(["next", "--help"])
    out = capsys.readouterr().out
    assert "--takeover-touches-tests" in out
    assert "--fable-touches-tests" not in out


@_needs_jsonschema
@pytest.mark.parametrize("rung", [esc.RUNG_TAKEOVER, LEGACY_RUNG])
def test_291_a_takeover_report_and_a_legacy_fable_report_both_validate(rung):
    _jsonschema.validate(
        instance=_report(escalation={"next_rung": rung, "task_key": KEY, "attempt_id": 3}),
        schema=_schema())


# --------------------------------------------------------------------------- #
# #313 section 5 -- a clarification is a question, never an attempt
# --------------------------------------------------------------------------- #
def test_313_a_clarification_never_escalates_and_goes_to_the_user(home, root):
    fail(home, root, cls="clarification")
    verdict = ladder(home, root)
    assert (verdict.rung, verdict.reason) == (esc.RUNG_USER, esc.REASON_NEVER_ESCALATES)
    assert "clarification" not in esc.STICKY_CLASSES


def test_313_clarifications_never_count_toward_the_ladder_or_the_plan_cap(home, root):
    for _ in range(esc.MAX_FAILED_ATTEMPTS_PER_PLAN + 2):
        fail(home, root, cls="clarification")
    fail(home, root, cls="implementation-failure")
    verdict = ladder(home, root)
    assert verdict.failed_attempts == 1
    assert verdict.plan_failed_attempts == 1
    assert (verdict.rung, verdict.reason) == (esc.LADDER[1], esc.REASON_LADDER)
