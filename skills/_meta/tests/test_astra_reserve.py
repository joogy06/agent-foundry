#!/usr/bin/env python3
"""The astra reserve (design docs/plans/2026-09-27-astra-reserve-design.md, U1-U4, section 4a F1-F8).

Sol (the codex std tier) is the default codex seat. The roster TOP (astra today) is kept in reserve for the
`escalation` seat and the complex / risk-promoted `code_reviewer`, plus two bounded paths back to it:
  * U2 / F3: a std seat that failed on capacity or a malformed answer twice gets ONE TOP retry
    (`seat_model.py argv --top-retry`, budget use `top_retry`, a `top_retry` event row);
  * U3 / F5: a D21 loop that exhausts its bound gets ONE escalation-role review (`exhausted_review`,
    keyed on the cycle id + the review id), which never admits a third automatic fix round.

Every guarantee is paired with a CONTROL showing the same fixture can produce the other answer. The fixture
HOME, the budget store and the codex CLI lookup come from test_seat_model.py (imported by name, so none of
its tests are collected twice).
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_META = _HERE.parent
# Put THIS tree's _meta first, unconditionally: this module is collected early, and a tree already on sys.path
# behind another copy (a test that imported the installed ~/.claude/skills/_meta) would otherwise resolve the
# harness modules from that copy for the rest of the session.
for _p in (_HERE, _META):
    sys.path.insert(0, str(_p))

import codex_quota  # type: ignore  # noqa: E402
import effort_policy as ep  # type: ignore  # noqa: E402
import model_roster  # type: ignore  # noqa: E402
import seat_model as sm  # type: ignore  # noqa: E402
import skill_corpus  # type: ignore  # noqa: E402

#: Every live-tree read names THIS tree, so the module that was imported first cannot choose it.
_SKILLS = _META.parent
from test_seat_model import (  # type: ignore  # noqa: E402,F401
    MAIN, STD, argv_use, cli, codex_cli, fixture_home, project, store_rows, substitution_rows,
    write_codex_roster, write_pins, write_rollout,
)

TOP = "gpt-6-astra"


def top_retry_rows(rows):
    return [r for r in rows if r.get("kind") == "top_retry"]


def admitted(rows, use):
    return [r for r in rows if r.get("use") == use and r.get("admitted") is True]


# --------------------------------------------------------------------------- #
# DW-1: the seat table after the change, at every size
# --------------------------------------------------------------------------- #
def test_the_role_rows_are_the_design_section_3_table():
    codex = {role: sm.ROLE_TABLE[role][sm.CODEX] for role in sm.ROLES}
    assert (codex["code_reviewer"].kind, codex["code_reviewer"].effort) == (sm.KIND_TOP, "xhigh")
    assert (codex["consultant_main"].kind, codex["consultant_main"].value, codex["consultant_main"].effort) == \
        (sm.KIND_LITERAL, model_roster.CODEX_STD, "xhigh")
    assert (codex["arbiter"].kind, codex["arbiter"].value, codex["arbiter"].effort) == \
        (sm.KIND_LITERAL, model_roster.CODEX_STD, "xhigh")                               # U4: xhigh, not max
    assert (codex["escalation"].kind, codex["escalation"].effort) == (sm.KIND_TOP, "max")
    assert sm.SIZED_ROLES == frozenset({"code_reviewer"})                                 # escalation is never sized down
    assert (codex["consultant_support"].kind, codex["consultant_support"].value) == \
        (sm.KIND_LITERAL, model_roster.CODEX_SUPPORT)                                     # unchanged


@pytest.mark.parametrize("size", [None, "light", "medium", "complex"])
def test_emit_serves_the_reserve_table_at_every_size(fixture_home, size):
    write_codex_roster(fixture_home)
    doc = sm.emit() if size is None else sm.emit(size)
    pins = {role: doc["pins"][role]["codex"] for role in sm.ROLES}
    reviewer = STD if size in ("light", "medium") else TOP
    assert (pins["code_reviewer"]["model"], pins["code_reviewer"]["effort"]) == (reviewer, "xhigh")
    assert (pins["consultant_main"]["model"], pins["consultant_main"]["effort"]) == (STD, "xhigh")
    assert (pins["arbiter"]["model"], pins["arbiter"]["effort"]) == (STD, "xhigh")
    assert (pins["escalation"]["model"], pins["escalation"]["effort"]) == (TOP, "max")
    assert pins["consultant_main"]["provenance"]["roster_rev"] == model_roster.REVISION


def test_user_request_still_promotes_consultant_main_to_top(fixture_home):
    """F7: an explicit user request on consultant_main resolves TOP; without one it is Sol at every size."""
    write_codex_roster(fixture_home)
    promoted = sm.resolve("consultant_main", "codex", size="light", user_request=True)
    assert (promoted.model, promoted.effort, promoted.provenance.get("requested_by")) == (TOP, "xhigh", "user")
    assert sm.pin_model_class(promoted) == codex_quota.MODEL_CLASS_TOP
    plain = sm.resolve("consultant_main", "codex", size="complex")                         # CONTROL
    assert (plain.model, sm.pin_model_class(plain)) == (STD, codex_quota.MODEL_CLASS_STD)
    # the arbiter is NOT promotable: the seat that arbitrates follows the table, never a caller.
    assert sm.resolve("arbiter", "codex", size="light", user_request=True).model == STD


def test_a_freeze_no_longer_reaches_the_literal_rows(fixture_home):
    """F8: the emergency freeze applies to TOP rows only; Sol seats stay on Sol."""
    write_codex_roster(fixture_home)
    write_pins(fixture_home, {"codex": "gpt-5.6-sol"})
    assert sm.resolve("escalation", "codex").model == "gpt-5.6-sol"                        # CONTROL: TOP row frozen
    assert sm.resolve("consultant_main", "codex").model == STD
    assert sm.resolve("arbiter", "codex").model == STD


# --------------------------------------------------------------------------- #
# DW-2: roster rev 4, CODEX_TOP_ROLES and the import-time invariant
# --------------------------------------------------------------------------- #
def test_roster_revision_4_records_the_reserve():
    assert model_roster.REVISION >= 4
    assert model_roster.CODEX_TOP_ROLES == ("code_reviewer@complex", "escalation")
    (rev4,) = [row for row in model_roster.HISTORY if row["rev"] == 4]   # later swaps append, never rewrite
    assert rev4["codex_top_roles"] == model_roster.CODEX_TOP_ROLES
    assert "astra reserved" in rev4["reason"]


def test_the_shipped_role_table_agrees_with_the_roster():
    assert sm.role_table_violations() == []


class _Roster:
    def __init__(self, **overrides):
        for name in dir(model_roster):
            if name.isupper():
                setattr(self, name, getattr(model_roster, name))
        for name, value in overrides.items():
            setattr(self, name, value)


def _table_with(role, row):
    table = {r: dict(rows) for r, rows in sm.ROLE_TABLE.items()}
    table[role][sm.CODEX] = row
    return table


@pytest.mark.parametrize("table,sized,roster,needle", [
    (_table_with("consultant_main", sm.RoleRow(sm.KIND_TOP, effort="xhigh")), None, None, "consultant_main"),
    (_table_with("escalation", sm.RoleRow(sm.KIND_LITERAL, value=model_roster.CODEX_STD, effort="max")), None,
     None, "escalation"),
    (_table_with("arbiter", sm.RoleRow(sm.KIND_LITERAL, value="gpt-5.6-sol", effort="xhigh")), None, None,
     "arbiter"),
    (None, frozenset({"code_reviewer", "escalation"}), None, "escalation"),
    (None, frozenset(), None, "code_reviewer"),
    (None, None, _Roster(CODEX_TOP_ROLES=("code_reviewer@complex",)), "escalation"),
    (None, None, _Roster(CODEX_TOP_ROLES=("code_reviewer@complex", "escalation", "arbiter")), "arbiter"),
    (None, None, _Roster(CODEX_TOP_ROLES=("code_reviewer@light", "escalation")), "code_reviewer@light"),
    (None, None, _Roster(CODEX_TOP_ROLES=["code_reviewer@complex", "escalation"]), "tuple"),
    # fix round 1 item 5: a non-protected role can never be reserved, and EVERY codex TOP row must be declared
    (None, None, _Roster(CODEX_TOP_ROLES=("code_reviewer@complex", "escalation", "consultant_support")),
     "consultant_support"),
    (_table_with("consultant_support", sm.RoleRow(sm.KIND_TOP, effort="medium")), None, None, "consultant_support"),
])
def test_a_role_table_that_disagrees_with_the_roster_is_a_violation(table, sized, roster, needle):
    problems = sm.role_table_violations(table=table, sized=sized, roster=roster)
    assert problems and any(needle in p for p in problems), problems


def test_the_import_time_invariant_refuses_a_disagreeing_table():
    """Fail closed: a roster that reserves a different set of roles stops every importer. Fix round 1 item 11:
    the HISTORY row is kept CONSISTENT with the planted reserve, so ONLY the role-table guard can fire, and the
    assertion names that guard's own message."""
    script = ("import sys; sys.path.insert(0, sys.argv[1]); import model_roster as r; roles = %s; "
              "r.CODEX_TOP_ROLES = roles; r.HISTORY = r.HISTORY[:-1] + (dict(r.HISTORY[-1], codex_top_roles=roles),); "
              "import seat_model")
    bad = subprocess.run([sys.executable, "-B", "-c", script % "('code_reviewer@complex',)", str(_META)],
                         capture_output=True, text=True, timeout=60)
    assert bad.returncode != 0, bad.stderr
    assert "ROLE_TABLE disagrees with model_roster.CODEX_TOP_ROLES" in bad.stderr, bad.stderr
    assert "violates its invariants" not in bad.stderr                   # not the HISTORY/roster guard
    ok = subprocess.run([sys.executable, "-B", "-c", script % "('code_reviewer@complex', 'escalation')", str(_META)],
                        capture_output=True, text=True, timeout=60)
    assert ok.returncode == 0, ok.stderr                                  # CONTROL


def test_the_history_row_must_carry_the_live_reserve():
    history = model_roster.HISTORY[:-1] + (dict(model_roster.HISTORY[-1], codex_top_roles=("escalation",)),)
    problems = sm.roster_violations(_Roster(HISTORY=history))
    assert any("codex_top_roles" in p for p in problems), problems
    assert sm.roster_violations(_Roster()) == []                                               # CONTROL


def test_the_std_efforts_the_check_judges_include_every_literal_std_row():
    """F6: the check derives the std efforts from the sized rows AND every literal CODEX_STD row."""
    efforts = sm.codex_std_efforts()
    assert "xhigh" in efforts                       # consultant_main / arbiter @ xhigh on Sol
    assert "medium" in efforts                      # codex_model's std fallbacks
    # fix round 1 item 4: avengers' ratification_arbiter seat class runs the std literal @ max (codex_model's
    # std-pinned role pins carry every seat-class effort), so the check must judge Sol at max too.
    assert "max" in efforts
    assert {pin.effort for pin in sm.codex_model._ROLE_PINS.values()} <= efforts


# --------------------------------------------------------------------------- #
# DW-3a: F1 (admission and D6 on the literal rows) and F2 (escalation's own use)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("use", ["challenger", "consult"])
def test_consultant_main_is_admitted_on_sol_under_the_std_budget(fixture_home, project, codex_cli, capsys, use):
    write_codex_roster(fixture_home)
    code, out, err = cli(capsys, argv_use("consultant_main", use, project, "--cycle-id", "c1"))
    assert (code, out) == (sm.EXIT_OK, f"-m {STD} -c model_reasoning_effort=xhigh\n"), err
    rows = store_rows(project)
    assert [(r["use"], r["model_class"], r["role"]) for r in rows] == [(use, "std", "consultant_main")]
    # the std limit for consult/challenger is 2 per cycle
    assert cli(capsys, argv_use("consultant_main", use, project, "--cycle-id", "c1"))[0] == sm.EXIT_OK
    code, out, _ = cli(capsys, argv_use("consultant_main", use, project, "--cycle-id", "c1"))
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"budget_spent\n{MAIN}\n")                 # D6, not a gap


@pytest.mark.parametrize("role", ["consultant_main", "arbiter"])
def test_a_d6_substitution_on_the_sol_seats_exits_3_with_the_claude_main_tier(fixture_home, project, capsys, role):
    code, out, err = cli(capsys, ["substitute", "--role", role, "--use", "ballot", "--reason", "capacity_twice",
                                  "--project-root", str(project), "--requested-model", STD])
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"capacity_twice\n{MAIN}\n"), err
    sub = substitution_rows(store_rows(project))
    assert [(s["role"], s["requested_model"], s["served_model"]) for s in sub] == [(role, STD, MAIN)]
    pin = sm.substitute(role, "deliberation", "budget_spent", project_root=project)       # the convene path (F1)
    assert pin.model == MAIN
    with pytest.raises(sm.SeatModelError):                                                # CONTROL: support is not
        sm.substitute("consultant_support", "deliberation", "budget_spent", project_root=project)


def test_the_escalation_seat_has_its_own_budget_and_is_top_at_every_size(fixture_home, project, codex_cli, capsys):
    write_codex_roster(fixture_home)
    # the explorer's consult is spent first: it no longer competes with the escalation seat (F2)
    for _ in range(2):
        assert cli(capsys, argv_use("consultant_main", "consult", project, "--cycle-id", "c1"))[0] == sm.EXIT_OK
    esc = argv_use("escalation", "escalation", project, "--cycle-id", "c1", "--size", "light")
    code, out, err = cli(capsys, esc)
    assert (code, out) == (sm.EXIT_OK, f"-m {TOP} -c model_reasoning_effort=max\n"), err
    assert cli(capsys, esc)[:2] == (sm.EXIT_SUBSTITUTE, f"budget_spent\n{MAIN}\n")          # top 1 per cycle
    assert [r["model_class"] for r in admitted(store_rows(project), "escalation")] == ["top"]


def test_the_escalation_use_belongs_to_the_escalation_role(fixture_home, project, codex_cli, capsys):
    write_codex_roster(fixture_home)
    code, _, err = cli(capsys, argv_use("consultant_main", "escalation", project))
    assert code == sm.EXIT_USAGE and "escalation" in err
    assert store_rows(project) == []


def test_the_budget_table_has_the_three_new_uses():
    limits = codex_quota.BUDGET_LIMITS
    assert dict(limits["escalation"]) == {"top": 1, "std": None}
    assert dict(limits["top_retry"]) == {"top": 1, "std": None}
    assert dict(limits["exhausted_review"]) == {"top": 1, "std": None}
    assert codex_quota.USE_FALLBACK_ROLE["escalation"] == "escalation"
    assert codex_quota.USE_FALLBACK_ROLE["exhausted_review"] == "escalation"
    assert "top_retry" in codex_quota.USE_FALLBACK_ROLE
    assert {"escalation", "top_retry", "exhausted_review"} <= codex_quota.SUBSTITUTION_USES


# --------------------------------------------------------------------------- #
# DW-3 / DW-3a: the U2 Sol -> TOP retry (F3)
# --------------------------------------------------------------------------- #
def receipt(project):
    path = project / "receipt.txt"
    return path.read_text(encoding="utf-8").split() if path.exists() else None


def admit_sol(capsys, role, use, project, *extra):
    """An admitted `argv --use` that leaves its receipt (`<admission_id> <key>`); returns the admission id."""
    code, out, err = cli(capsys, argv_use(role, use, project, "--receipt-file", str(project / "receipt.txt"), *extra))
    assert code == sm.EXIT_OK, err
    return receipt(project)[0]


def top_retry(role, use, project, failed_id, failed_reason, *extra):
    return ["argv", "--role", role, "--provider", "codex", "--use", use, "--top-retry",
            "--failed-admission-id", failed_id, "--failed-reason", failed_reason, "--project-root", str(project),
            "--receipt-file", str(project / "receipt.txt"), *extra]


def forge_cycle(project, cycle):
    (project / ".forge").mkdir(exist_ok=True)
    (project / ".forge" / "cycle-id").write_text(cycle + "\n", encoding="utf-8")


def test_the_receipt_names_the_admission_and_its_key_and_only_on_admission(fixture_home, project, codex_cli, capsys):
    write_codex_roster(fixture_home)
    aid = admit_sol(capsys, "consultant_main", "challenger", project, "--cycle-id", "t1")
    row = admitted(store_rows(project), "challenger")[0]
    assert receipt(project) == [row["admission_id"], "t1"] and aid == row["admission_id"]
    (project / "receipt.txt").unlink()
    for _ in range(2):
        cli(capsys, argv_use("consultant_main", "challenger", project, "--cycle-id", "t1",
                             "--receipt-file", str(project / "receipt.txt")))
    assert receipt(project) is not None                                   # the 2nd std slot was admitted
    (project / "receipt.txt").unlink()
    code, _, _ = cli(capsys, argv_use("consultant_main", "challenger", project, "--cycle-id", "t1",
                                      "--receipt-file", str(project / "receipt.txt")))
    assert code == sm.EXIT_SUBSTITUTE and receipt(project) is None        # a refusal leaves no receipt


@pytest.mark.parametrize("reason", ["capacity_twice", "malformed_twice"])
def test_a_capability_failure_on_sol_is_retried_once_on_top(fixture_home, project, codex_cli, capsys, reason):
    write_codex_roster(fixture_home)
    forge_cycle(project, "cyc-1")
    failed = admit_sol(capsys, "consultant_main", "challenger", project, "--cycle-id", "tournament-a")
    code, out, err = cli(capsys, top_retry("consultant_main", "challenger", project, failed, reason,
                                           "--cycle-id", "tournament-a"))
    assert (code, out) == (sm.EXIT_OK, f"-m {TOP} -c model_reasoning_effort=xhigh\n"), err
    rows = store_rows(project)
    retry = admitted(rows, "top_retry")
    # F1: the retry spends the FORGE CYCLE's one top_retry, never the originating (tournament) key's
    assert [(r["model_class"], r["requested_model"], r["role"], r["key"]) for r in retry] == [
        ("top", TOP, "consultant_main", "cyc-1")]
    [ev] = top_retry_rows(rows)
    assert (ev["origin_use"], ev["origin_key"], ev["key"], ev["failed_model"], ev["failed_reason"],
            ev["retry_model"], ev["outcome"]) == ("challenger", "tournament-a", "cyc-1", STD, reason, TOP, "admitted")
    assert (ev["failed_admission_id"], ev["retry_admission_id"]) == (failed, retry[0]["admission_id"])
    assert "admitted" not in ev and substitution_rows(rows) == []
    assert receipt(project) == [retry[0]["admission_id"], "cyc-1"]         # F3: the retry's exact key
    assert codex_quota._count_admitted(codex_quota.budget_path_for(project), "tournament-a", "challenger", None,
                                       model_class="std") == 1              # the failed Sol call is not netted


def test_the_retry_is_one_per_forge_cycle_whatever_the_originating_key(fixture_home, project, codex_cli, capsys):
    """F1: two ballots (two originating keys) in ONE forge cycle get ONE TOP retry between them."""
    write_codex_roster(fixture_home)
    forge_cycle(project, "cyc-1")
    a = admit_sol(capsys, "consultant_main", "ballot", project, "--cycle-id", "ballot-a")
    b = admit_sol(capsys, "arbiter", "ballot", project, "--cycle-id", "ballot-b")
    assert cli(capsys, top_retry("consultant_main", "ballot", project, a, "capacity_twice",
                                 "--cycle-id", "ballot-a"))[0] == sm.EXIT_OK
    code, out, _ = cli(capsys, top_retry("arbiter", "ballot", project, b, "malformed_twice", "--cycle-id", "ballot-b"))
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"budget_spent\n{MAIN}\n")
    subs = substitution_rows(store_rows(project))
    assert [(s["use"], s["role"], s["reason"], s["key"]) for s in subs] == [("top_retry", "arbiter", "budget_spent",
                                                                             "cyc-1")]
    # CONTROL: the next forge cycle has its own retry
    forge_cycle(project, "cyc-2")
    c = admit_sol(capsys, "arbiter", "ballot", project, "--cycle-id", "ballot-c")
    assert cli(capsys, top_retry("arbiter", "ballot", project, c, "capacity_twice",
                                 "--cycle-id", "ballot-c"))[0] == sm.EXIT_OK


def test_the_event_links_the_exact_failed_admission_not_the_latest(fixture_home, project, codex_cli, capsys):
    """F2/F4: two Sol admissions on one key; the retry of the FIRST names the first, never the newest."""
    write_codex_roster(fixture_home)
    first = admit_sol(capsys, "consultant_main", "consult", project, "--cycle-id", "c1")
    second = admit_sol(capsys, "consultant_main", "consult", project, "--cycle-id", "c1")
    assert first != second
    assert cli(capsys, top_retry("consultant_main", "consult", project, first, "capacity_twice",
                                 "--cycle-id", "c1"))[0] == sm.EXIT_OK
    [ev] = top_retry_rows(store_rows(project))
    assert ev["failed_admission_id"] == first


def _other_admission(capsys, project, fixture_home, case):
    """An admission that is NOT the failed Sol seat's: another use, role, key, class, or none at all."""
    if case == "unknown":
        return "0" * 32
    if case == "wrong_use":
        return admit_sol(capsys, "consultant_main", "consult", project, "--cycle-id", "c1")
    if case == "wrong_role":
        return admit_sol(capsys, "arbiter", "challenger", project, "--cycle-id", "c1")
    if case == "wrong_key":
        return admit_sol(capsys, "consultant_main", "challenger", project, "--cycle-id", "other")
    if case == "top_class":
        return admit_sol(capsys, "consultant_main", "challenger", project, "--cycle-id", "c1", "--user-request")
    if case == "refused":
        cli(capsys, argv_use("code_reviewer", "review_std", project, "--cycle-id", "c1"))   # class_not_budgeted
        return store_rows(project)[-1]["admission_id"]
    raise AssertionError(case)


@pytest.mark.parametrize("case", ["unknown", "wrong_use", "wrong_role", "wrong_key", "top_class", "refused"])
def test_the_retry_trusts_only_the_exact_failed_std_admission(fixture_home, project, codex_cli, capsys, case):
    """F2: the failed attempt is identified by its admission id, which must be an ADMITTED std-class row of
    this role, use and key. Anything else is refused BEFORE anything is written (exit 2)."""
    write_codex_roster(fixture_home)
    bogus = _other_admission(capsys, project, fixture_home, case)
    before = store_rows(project)
    code, out, err = cli(capsys, top_retry("consultant_main", "challenger", project, bogus, "capacity_twice",
                                           "--cycle-id", "c1"))
    assert (code, out) == (sm.EXIT_USAGE, ""), err
    assert "--failed-admission-id" in err
    assert store_rows(project) == before                                  # nothing written
    # CONTROL: the genuine failed admission is retried
    good = admit_sol(capsys, "consultant_main", "challenger", project, "--cycle-id", "c1")
    assert cli(capsys, top_retry("consultant_main", "challenger", project, good, "capacity_twice",
                                 "--cycle-id", "c1"))[0] == sm.EXIT_OK


def test_a_seat_whose_own_pin_bills_top_is_no_retry(fixture_home, project, codex_cli, capsys):
    """F2: when the role's own pin now bills TOP (the vendor ranks Sol TOP), a TOP retry would buy nothing
    new: D6 for the original failure, recorded, no TOP slot spent."""
    import test_seat_model as tsm  # type: ignore
    write_codex_roster(fixture_home)
    failed = admit_sol(capsys, "consultant_main", "challenger", project, "--cycle-id", "c1")
    write_codex_roster(fixture_home, tsm.crf.codex_entries(priorities={STD: 0}))
    code, out, _ = cli(capsys, top_retry("consultant_main", "challenger", project, failed, "capacity_twice",
                                         "--cycle-id", "c1"))
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"capacity_twice\n{MAIN}\n")
    rows = store_rows(project)
    assert admitted(rows, "top_retry") == []
    assert [e["reason"] for e in top_retry_rows(rows)] == ["top_retry_seat_is_top"]


@pytest.mark.parametrize("freeze,reason", [(model_roster.CODEX_SUPPORT, "top_retry_not_top"),
                                           ("gpt-5.6-sol", "top_retry_not_top"),
                                           (STD, "top_retry_same_pin")])
def test_a_frozen_retry_pin_must_be_the_roster_top(fixture_home, project, codex_cli, capsys, freeze, reason):
    """F3 + opus 4: a freeze onto a tier model, or onto ANY model the roster does not rank TOP (gpt-5.6-sol),
    is no TOP retry; a freeze onto Sol is the failed pin itself. D6 for the original failure, no slot spent."""
    write_codex_roster(fixture_home)
    failed = admit_sol(capsys, "consultant_main", "consult", project, "--cycle-id", "c1")
    write_pins(fixture_home, {"codex": freeze})
    code, out, _ = cli(capsys, top_retry("consultant_main", "consult", project, failed, "malformed_twice",
                                         "--cycle-id", "c1"))
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"malformed_twice\n{MAIN}\n")
    rows = store_rows(project)
    assert [e["reason"] for e in top_retry_rows(rows)] == [reason] and admitted(rows, "top_retry") == []
    # CONTROL: a freeze onto the roster TOP itself is a real retry
    write_pins(fixture_home, {"codex": TOP})
    again = admit_sol(capsys, "consultant_main", "consult", project, "--cycle-id", "c1")
    assert cli(capsys, top_retry("consultant_main", "consult", project, again, "malformed_twice",
                                 "--cycle-id", "c1"))[0] == sm.EXIT_OK


def test_an_unavailable_top_falls_to_the_opus_stand_in(fixture_home, project, codex_cli, capsys):
    write_codex_roster(fixture_home)
    failed = admit_sol(capsys, "consultant_main", "consult", project)
    write_rollout(fixture_home, 99.5, 20)
    code, out, _ = cli(capsys, top_retry("consultant_main", "consult", project, failed, "capacity_twice"))
    # #322: a quota refusal names its reset after the two lines (#322 fix round 1: on a TOP retry too)
    assert (code, out.splitlines()[:2]) == (sm.EXIT_SUBSTITUTE, ["quota_exhausted", MAIN])
    assert out.splitlines()[-1].startswith("wait_advice=")
    # the meter is healthy again: a NEWER reading with headroom (#322 fix round 1: deleting the rollouts is
    # not enough -- the refusal persisted "exhausted until the reset", which only a newer reading clears) ...
    write_rollout(fixture_home, 10, 10, age=0)
    again = admit_sol(capsys, "consultant_main", "consult", project)     # ... a NEW failed attempt (fix round 2:
    codex_cli["present"] = False                                          # one retry per failed admission)
    code, out, _ = cli(capsys, top_retry("consultant_main", "consult", project, again, "capacity_twice"))
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"cli_missing\n{MAIN}\n")


@pytest.mark.parametrize("reason", ["quota_exhausted", "rate_limit_reached", "auth_failure", "budget_spent",
                                    "threshold", "timeout_twice", "cli_missing", "codex_error"])
def test_quota_auth_budget_and_timeout_never_trigger_a_top_retry(fixture_home, project, codex_cli, capsys, reason):
    write_codex_roster(fixture_home)
    failed = admit_sol(capsys, "consultant_main", "consult", project)
    before = store_rows(project)
    code, out, err = cli(capsys, top_retry("consultant_main", "consult", project, failed, reason))
    assert (code, out) == (sm.EXIT_USAGE, "") and "capacity_twice" in err
    assert store_rows(project) == before


@pytest.mark.parametrize("use", ["exhausted_review", "trial", "audit", "top_retry"])
def test_a_skipped_or_unretryable_origin_is_refused_before_anything_is_written(fixture_home, project, codex_cli,
                                                                                capsys, use):
    """Opus 2: exhausted_review is skipped, never substituted, so it can never be the origin of a retry; the
    refusal happens at usage, before any row (the crash wrote an event row and then exited 1)."""
    write_codex_roster(fixture_home)
    code, out, err = cli(capsys, top_retry("escalation", use, project, "a" * 32, "capacity_twice",
                                           "--task-key", "docs/plans/a.md"))
    assert (code, out) == (sm.EXIT_USAGE, "") and use in err, err
    assert store_rows(project) == []
    assert use not in sm.TOP_RETRY_ORIGIN_USES
    with pytest.raises(ValueError):
        codex_quota.record_top_retry("c", project_root=project, role="escalation", origin_use=use,
                                     origin_key="c", failed_admission_id=None, failed_model=STD,
                                     failed_reason="capacity_twice", retry_model=TOP, outcome="admitted")


@pytest.mark.parametrize("args,needle", [
    (["--use", "top_retry"], "--top-retry"),
    (["--use", "consult", "--top-retry"], "--failed-admission-id"),
    (["--use", "consult", "--failed-admission-id", "a" * 32, "--failed-reason", "capacity_twice"], "--top-retry"),
    (["--use", "consult", "--top-retry", "--failed-model", "x", "--failed-reason", "capacity_twice"],
     "--failed-model"),
    (["--use", "consult", "--top-retry", "--failed-admission-id", "nothex", "--failed-reason", "capacity_twice"],
     "--failed-admission-id"),
])
def test_the_retry_flags_are_all_or_nothing(fixture_home, project, codex_cli, capsys, args, needle):
    write_codex_roster(fixture_home)
    code, out, err = cli(capsys, ["argv", "--role", "consultant_main", "--provider", "codex", *args,
                                  "--project-root", str(project)])
    assert (code, out) == (sm.EXIT_USAGE, "") and needle in err, err


def test_the_retry_timeout_is_the_top_pins(fixture_home, monkeypatch, capsys):
    write_codex_roster(fixture_home)
    monkeypatch.setitem(sm.codex_model._MODEL_TIMEOUT_OVERRIDES_S, (TOP, "xhigh"), 777)
    assert cli(capsys, ["timeout", "--role", "consultant_main", "--provider", "codex", "--top-retry"])[1] == "777\n"
    assert cli(capsys, ["timeout", "--role", "consultant_main", "--provider", "codex"])[1] != "777\n"   # CONTROL


# --------------------------------------------------------------------------- #
# DW-4: the exhausted-bound review (U3 / F5)
# --------------------------------------------------------------------------- #
def exhausted(role, project, *extra):
    return argv_use(role, "exhausted_review", project, *extra)


def test_the_exhausted_review_is_one_top_escalation_call_per_review(fixture_home, project, codex_cli, capsys):
    write_codex_roster(fixture_home)
    first = exhausted("escalation", project, "--cycle-id", "c1", "--task-key", "docs/plans/a.md", "--size", "light")
    code, out, err = cli(capsys, first)
    assert (code, out) == (sm.EXIT_OK, f"-m {TOP} -c model_reasoning_effort=max\n"), err   # light: no class refusal
    assert cli(capsys, first)[:2] == (sm.EXIT_SKIPPED, "")                                  # 1 per review_id
    other = exhausted("escalation", project, "--cycle-id", "c1", "--task-key", "docs/plans/b.md")
    assert cli(capsys, other)[0] == sm.EXIT_OK                                             # CONTROL: another review
    assert [r["task_key"] for r in admitted(store_rows(project), "exhausted_review")] == \
        ["docs/plans/a.md", "docs/plans/b.md"]


@pytest.mark.parametrize("args,needle", [
    (["--role", "escalation"], "--task-key"),
    (["--role", "code_reviewer", "--task-key", "docs/plans/a.md"], "escalation"),
])
def test_the_exhausted_review_needs_the_escalation_role_and_a_review_id(fixture_home, project, codex_cli, capsys,
                                                                        args, needle):
    write_codex_roster(fixture_home)
    code, _, err = cli(capsys, ["argv", "--provider", "codex", "--use", "exhausted_review",
                                "--project-root", str(project), *args])
    assert code == sm.EXIT_USAGE and needle in err, err


def test_admit_refuses_an_exhausted_review_without_its_review_id(project):
    with pytest.raises(ValueError, match="task_key"):
        codex_quota.admit("exhausted_review", "c1", project_root=project, model_class="top")


def _git_repo(root):
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    (root / "docs" / "plans").mkdir(parents=True)
    (root / "docs" / "plans" / "d.md").write_text("# d\n", encoding="utf-8")


class _Loop:
    def __init__(self, root):
        self.root = root
        self.rid = ep.review_id_for(root, "docs/plans/d.md")

    def review(self, disposition, verdict="NEEDS_FIXES", initial=False, verified=None):
        return ep.record_d21_review(self.root, review_id=self.rid, initial=initial,
                                    raised={"major": 2}, verified={"major": 1} if verified is None else verified,
                                    verdict=verdict, disposition=disposition)

    def exhaust(self):
        self.review("fixing", initial=True)
        ep.admit_fix_round(self.root, self.rid)
        self.review("fixing")
        ep.admit_fix_round(self.root, self.rid)
        return self.review("exhausted")


@pytest.fixture()
def loop():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        _git_repo(root)
        yield _Loop(root)


def test_the_exhausted_review_row_is_recorded_once_after_the_bound(loop):
    loop.exhaust()
    row = ep.record_exhausted_review(loop.root, loop.rid, outcome="ran", raised={"major": 1}, verified={"major": 1})
    assert (row["kind"], row["review_id"], row["after_round"], row["outcome"]) == \
        ("exhausted_review", loop.rid, 2, "ran")
    assert row["admits_fix_round"] is False
    with pytest.raises(ep.LoopBoundError):
        ep.record_exhausted_review(loop.root, loop.rid, outcome="ran")                  # one per review_id


def test_the_exhausted_review_never_admits_a_third_automatic_round(loop):
    """Fix round 1 item 11: with a CONTROL. The same exhausted loop WITHOUT the exhausted-review row refuses
    round 3 for the same reason, so the row neither enables nor changes the bound - and it adds no admission."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td).resolve()
        _git_repo(root)
        control = _Loop(root)
        control.exhaust()
        with pytest.raises(ep.LoopBoundError) as without_row:
            ep.admit_fix_round(control.root, control.rid)
    loop.exhaust()
    ep.record_exhausted_review(loop.root, loop.rid, outcome="ran", raised={"major": 1}, verified={"major": 1})
    with pytest.raises(ep.LoopBoundError) as with_row:
        ep.admit_fix_round(loop.root, loop.rid)
    assert str(with_row.value) == str(without_row.value)
    assert [r["kind"] for r in ep.read_d21_rows(loop.root, loop.rid)].count("admitted") == 2
    kinds = [r["kind"] for r in ep.read_d21_rows(loop.root, loop.rid)]
    assert kinds.count("admitted") == 2 and kinds[-1] == "exhausted_review"
    # CONTROL: the user can still direct a round after it, exactly as before
    adm = ep.admit_fix_round(loop.root, loop.rid, user_directed=True, user_ref="2026-09-27 user: fix it")
    assert adm["fix_round"] == "user"


def test_the_exhausted_review_needs_an_exhausted_loop(loop):
    loop.review("fixing", initial=True)
    with pytest.raises(ep.LoopBoundError):
        ep.record_exhausted_review(loop.root, loop.rid, outcome="ran")                  # the loop is still running
    ep.admit_fix_round(loop.root, loop.rid)
    loop.review("converged", verdict="APPROVED", verified={})
    with pytest.raises(ep.LoopBoundError):
        ep.record_exhausted_review(loop.root, loop.rid, outcome="ran")                  # converged: nothing open


def test_the_exhausted_review_cli_records_the_unavailable_outcome(loop):
    loop.exhaust()
    proc = subprocess.run([sys.executable, str(_META / "effort_policy.py"), "record-exhausted-review",
                           "--project-root", str(loop.root), "--design-doc", "docs/plans/d.md",
                           "--outcome", "unavailable", "--unavailable-reason", "quota_exhausted"],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    row = json.loads(proc.stdout)["row"]
    assert (row["outcome"], row["unavailable_reason"]) == ("unavailable", "quota_exhausted")


def test_a_roster_that_does_not_serve_sol_substitutes_a_budgeted_seat_but_not_the_support_seat(
        fixture_home, project, codex_cli, capsys):
    """F1: a budgeted Sol seat that codex cannot serve (Sol unlisted, or listed without the seat's effort)
    is "no eligible model" - D6, exactly like a TOP seat with no eligible TOP. The support literal keeps its
    gap semantics (#302: consultant_support is never substituted)."""
    import test_seat_model as tsm  # type: ignore
    write_codex_roster(fixture_home, [e for e in tsm.live_like_codex_entries() if e["slug"] != STD])
    code, out, _ = cli(capsys, argv_use("consultant_main", "challenger", project))
    assert (code, out) == (sm.EXIT_SUBSTITUTE, f"no_eligible_model\n{MAIN}\n")
    with pytest.raises(sm.NoEligibleModelError):
        sm.resolve("arbiter", "codex")
    write_codex_roster(fixture_home, [tsm.entry(STD, 2, efforts=("low", "medium"))] + [
        e for e in tsm.live_like_codex_entries() if e["slug"] != STD])
    with pytest.raises(sm.NoEligibleModelError, match="xhigh"):
        sm.resolve("consultant_main", "codex")
    write_codex_roster(fixture_home, [e for e in tsm.live_like_codex_entries()
                                      if e["slug"] != model_roster.CODEX_SUPPORT])
    with pytest.raises(sm.SeatModelError) as info:                       # CONTROL: the support seat
        sm.resolve("consultant_support", "codex")
    assert not isinstance(info.value, sm.NoEligibleModelError)


def test_an_unavailable_exhausted_review_is_skipped_never_substituted(fixture_home, project, codex_cli, capsys):
    """U3: when TOP cannot serve the exhausted-bound review the loop goes to the user WITHOUT it - no Claude
    stand-in (it would add no independence), so the seat is SKIPPED (exit 10, like the trial) and no
    substitution row claims a stand-in that never ran. The refused admission is still recorded."""
    write_codex_roster(fixture_home)
    first = exhausted("escalation", project, "--cycle-id", "c1", "--task-key", "docs/plans/a.md")
    assert cli(capsys, first)[0] == sm.EXIT_OK
    code, out, err = cli(capsys, first)                                   # the review's one slot is spent
    assert (code, out) == (sm.EXIT_SKIPPED, "") and "budget_spent" in err
    rows = store_rows(project)
    assert substitution_rows(rows) == []
    assert [(r["admitted"], r["reason"]) for r in rows if r.get("use") == "exhausted_review"] == [
        (True, "within_budget"), (False, "budget_spent")]
    with pytest.raises(sm.SeatModelError):
        sm.substitute("escalation", "exhausted_review", "budget_spent", project_root=project)
    code, out, _ = cli(capsys, ["substitute", "--role", "escalation", "--use", "exhausted_review", "--reason",
                                "quota_exhausted", "--project-root", str(project)])
    assert (code, out) == (sm.EXIT_SKIPPED, "")


#: forge is an entry file plus step references (#344 WP-4). A PRESENT assertion names the one reference that has
#: to hold the text; an ABSENT assertion reads the whole corpus, so it still guards text that moved.
_FORGE_CLOSE_OUT = "references/10-close-out.md"     # the D21 review and its fix loop
_FORGE_ESCALATION = "references/05-escalation.md"   # the escalation seat recipe
_FORBIDDEN_ESCALATION_CALL = "codex_top_seat escalation consultant_main consult"


def test_forge_documents_the_exhausted_review_and_runs_escalation_on_its_own_role_and_use():
    """DW-4 / DW-3a, the prose half: forge's D21 names the one exhausted-bound review (its use, its record,
    and that it never admits a third round), and forge's escalation recipe is `--role escalation` on the
    `escalation` use (F2), never consultant_main's `consult`."""
    text = skill_corpus.read("forge", _FORGE_CLOSE_OUT, root=_SKILLS)
    d21 = text[text.index("3. **Bound.**"):text.index("4. **Unfixable.**")]
    for needle in ("exhausted_review", "record-exhausted-review", "NEVER start a third automatic round",
                   "--role escalation", "exits **10**", "#322"):
        assert needle in d21, needle
    escalation = skill_corpus.read("forge", _FORGE_ESCALATION, root=_SKILLS)
    assert "codex_top_seat escalation escalation escalation " in escalation
    assert _FORBIDDEN_ESCALATION_CALL not in skill_corpus.corpus("forge", root=_SKILLS)


def test_NEGATIVE_CONTROL_the_forbidden_escalation_call_is_caught_in_a_reference(tmp_path):
    """The absent-text assertion above must not be vacuous after the split: the forbidden call written into a
    REFERENCE is seen by the corpus reader, and is invisible to a reader of the entry file alone."""
    skill = tmp_path / "forge"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# entry\n", encoding="utf-8")
    (skill / "references" / "05-escalation.md").write_text(_FORBIDDEN_ESCALATION_CALL + " \"\" \"\"\n",
                                                           encoding="utf-8")
    assert _FORBIDDEN_ESCALATION_CALL not in skill_corpus.read("forge", root=tmp_path)
    assert _FORBIDDEN_ESCALATION_CALL in skill_corpus.corpus("forge", root=tmp_path)


@pytest.mark.parametrize("fault", [{"visibility": "hide"}, {"supported_in_api": False}])
def test_a_hidden_or_non_api_sol_is_no_eligible_model_on_a_budgeted_seat(fixture_home, fault):
    """Fix round 1 item 9: a budgeted Sol literal uses the TOP eligibility rule (listed, API, effort)."""
    import test_seat_model as tsm  # type: ignore
    entries = tsm.live_like_codex_entries()
    for e in entries:
        if e["slug"] == STD:
            e.update(fault)
    write_codex_roster(fixture_home, entries)
    with pytest.raises(sm.NoEligibleModelError):
        sm.resolve("consultant_main", "codex")
    # CONTROL: the support literal keeps its own (efforts-only) rule, and the healthy roster serves Sol
    write_codex_roster(fixture_home)
    assert sm.resolve("consultant_main", "codex").model == STD


# =========================================================================== #
# D21 fix round 2 - the receipt / proof plumbing
# =========================================================================== #
@pytest.mark.parametrize("size", ["light", "medium"])
def test_fr2_a_sized_std_review_is_retried_on_top(fixture_home, project, codex_cli, capsys, size):
    """Item 1: a light/medium code_reviewer review_std seat (Sol) is a std seat; the retry passes no --size, and
    the seat is judged by its PROVEN failed row, never by an unsized re-resolution (which is TOP)."""
    write_codex_roster(fixture_home)
    failed = admit_sol(capsys, "code_reviewer", "review_std", project, "--size", size)
    code, out, err = cli(capsys, top_retry("code_reviewer", "review_std", project, failed, "capacity_twice"))
    assert (code, out) == (sm.EXIT_OK, f"-m {TOP} -c model_reasoning_effort=xhigh\n"), err
    [ev] = top_retry_rows(store_rows(project))
    assert (ev["outcome"], ev["failed_model"]) == ("admitted", STD)


def test_fr2_the_origin_key_is_the_proven_rows_when_none_is_passed(fixture_home, project, codex_cli, capsys):
    """Item 2: the cycle id moved while Sol was failing (an age-out, a rewrite, midnight): without --cycle-id the
    origin key is the proven row's own, and the retry is billed to the cycle as it stands now."""
    write_codex_roster(fixture_home)
    forge_cycle(project, "cyc-1")
    failed = admit_sol(capsys, "consultant_main", "consult", project)
    forge_cycle(project, "cyc-2")
    code, out, err = cli(capsys, top_retry("consultant_main", "consult", project, failed, "capacity_twice"))
    assert code == sm.EXIT_OK, err
    [ev] = top_retry_rows(store_rows(project))
    assert (ev["origin_key"], ev["key"]) == ("cyc-1", "cyc-2")


def test_fr2_a_diagnosis_retry_must_name_the_same_task(fixture_home, project, codex_cli, capsys):
    """Item 4: a per-task use proves its task key too, and the event records it."""
    write_codex_roster(fixture_home)
    failed = admit_sol(capsys, "consultant_main", "diagnosis", project, "--task-key", "t1")
    before = store_rows(project)
    code, _, err = cli(capsys, top_retry("consultant_main", "diagnosis", project, failed, "capacity_twice",
                                         "--task-key", "t2"))
    assert code == sm.EXIT_USAGE and "task" in err, err
    assert store_rows(project) == before
    code, _, err = cli(capsys, top_retry("consultant_main", "diagnosis", project, failed, "capacity_twice",
                                         "--task-key", "t1"))
    assert code == sm.EXIT_OK, err
    assert top_retry_rows(store_rows(project))[-1]["task_key"] == "t1"


def test_fr2_one_failed_admission_buys_at_most_one_retry(fixture_home, project, codex_cli, capsys):
    """Item 5: a replay of the same failed admission - even in a later cycle - is refused, nothing written."""
    write_codex_roster(fixture_home)
    forge_cycle(project, "cyc-1")
    failed = admit_sol(capsys, "consultant_main", "consult", project, "--cycle-id", "c1")
    assert cli(capsys, top_retry("consultant_main", "consult", project, failed, "capacity_twice",
                                 "--cycle-id", "c1"))[0] == sm.EXIT_OK
    forge_cycle(project, "cyc-2")
    before = store_rows(project)
    code, out, err = cli(capsys, top_retry("consultant_main", "consult", project, failed, "capacity_twice",
                                           "--cycle-id", "c1"))
    assert (code, out) == (sm.EXIT_USAGE, "") and "already" in err, err
    assert store_rows(project) == before
    # the replay guard also covers a proven attempt that was NOT retried (D6 for its original failure)
    write_pins(fixture_home, {"codex": STD})
    other = admit_sol(capsys, "consultant_main", "consult", project, "--cycle-id", "c1")
    assert cli(capsys, top_retry("consultant_main", "consult", project, other, "capacity_twice",
                                 "--cycle-id", "c1"))[0] == sm.EXIT_SUBSTITUTE
    assert cli(capsys, top_retry("consultant_main", "consult", project, other, "capacity_twice",
                                 "--cycle-id", "c1"))[0] == sm.EXIT_USAGE


def test_fr2_sol_going_ineligible_after_it_failed_still_gets_the_top_retry(fixture_home, project, codex_cli, capsys):
    """Item 6: Sol leaves the roster after its failed attempts; a healthy TOP is still the retry."""
    import test_seat_model as tsm  # type: ignore
    write_codex_roster(fixture_home)
    failed = admit_sol(capsys, "consultant_main", "consult", project)
    write_codex_roster(fixture_home, [e for e in tsm.live_like_codex_entries() if e["slug"] != STD])
    code, out, err = cli(capsys, top_retry("consultant_main", "consult", project, failed, "malformed_twice"))
    assert (code, out) == (sm.EXIT_OK, f"-m {TOP} -c model_reasoning_effort=xhigh\n"), err
    assert [r["use"] for r in admitted(store_rows(project), "top_retry")] == ["top_retry"]


@pytest.mark.parametrize("key", ["bad key", "-x", "a;b", "k$1"])
def test_fr2_an_unsafe_cycle_id_is_refused_up_front(fixture_home, project, codex_cli, capsys, key):
    """Item 3(b): a key that could never ride a receipt or a shell word is a usage error before anything."""
    write_codex_roster(fixture_home)
    code, out, err = cli(capsys, ["argv", "--role", "consultant_main", "--provider", "codex", "--use", "consult",
                                  "--project-root", str(project), f"--cycle-id={key}"])
    assert (code, out) == (sm.EXIT_USAGE, "") and "--cycle-id" in err, err
    assert store_rows(project) == []


def test_fr2_a_retry_whose_receipt_cannot_be_written_fails(fixture_home, project, codex_cli, capsys):
    """Item 3(d): the retry's receipt names the key a later substitution bills; a TOP admission without it is a
    failure (exit 1, empty stdout), never a pin the caller cannot account for. The receipt is written
    atomically: no partial file is left behind."""
    write_codex_roster(fixture_home)
    failed = admit_sol(capsys, "consultant_main", "consult", project)
    args = top_retry("consultant_main", "consult", project, failed, "capacity_twice")
    args[args.index("--receipt-file") + 1] = str(project / "missing-dir" / "receipt.txt")
    code, out, _ = cli(capsys, args)
    assert (code, out) == (sm.EXIT_RESOLUTION_FAILED, "")
    assert not (project / "missing-dir").exists()
    assert list(project.glob("receipt.txt.*")) == []


def test_322_fr1_a_top_retry_refused_for_quota_defers_like_any_seat(fixture_home, project, codex_cli, capsys):
    """#322 fix round 1 (item 9): the U2 TOP retry admits with --await-quota too. A quota refusal then
    records no stand-in and names the retry's OWN use and key (top_retry on the forge cycle), so the block
    writes CODEX_QUOTA_WAIT. CONTROL: without the flag it substitutes at once (the pre-fix behaviour)."""
    write_codex_roster(fixture_home)
    forge_cycle(project, "cycle-1")
    failed = admit_sol(capsys, "consultant_main", "consult", project)
    write_rollout(fixture_home, 99.5, 20)
    code, out, _ = cli(capsys, top_retry("consultant_main", "consult", project, failed, "capacity_twice",
                                         "--await-quota"))
    lines = out.splitlines()
    assert code == sm.EXIT_SUBSTITUTE and lines[:2] == ["quota_exhausted", MAIN]
    assert lines[-1] == "substitution=deferred"
    fields = dict(line.split("=", 1) for line in lines[2:])
    assert (fields["use"], fields["key"]) == ("top_retry", "cycle-1")
    rows = codex_quota_rows(project)
    assert [r for r in rows if r.get("kind") == "substitution"] == []
    assert [r["reason"] for r in top_retry_rows(rows)] == ["quota_exhausted"]
    again = _fresh_failed_admission(capsys, project, fixture_home)
    write_rollout(fixture_home, 99.5, 20, age=0)
    code, out, _ = cli(capsys, top_retry("consultant_main", "consult", project, again, "capacity_twice"))
    assert code == sm.EXIT_SUBSTITUTE and "substitution=deferred" not in out
    assert [r["reason"] for r in codex_quota_rows(project) if r.get("kind") == "substitution"] == ["quota_exhausted"]


def test_322_fr2_a_deferred_top_retry_resumes_once_after_the_wait(fixture_home, project, codex_cli, capsys):
    """#322 fix round 2 (item 3), END TO END: refuse -> the wait succeeds -> the re-admission is allowed ONCE ->
    a second attempt is refused. Fix round 1 wrote the deferred refusal as a `substituted` top_retry event, so the
    replay guard refused the one allowed retry after the wait (red before: step 3 exited 2)."""
    write_codex_roster(fixture_home)
    forge_cycle(project, "cycle-1")
    failed = admit_sol(capsys, "consultant_main", "consult", project)
    # 1. refused for quota, deferred: a `pending` event, no stand-in
    write_rollout(fixture_home, 99.5, 20)
    code, out, _ = cli(capsys, top_retry("consultant_main", "consult", project, failed, "capacity_twice",
                                         "--await-quota"))
    assert code == sm.EXIT_SUBSTITUTE and out.splitlines()[-1] == "substitution=deferred"
    assert [r["outcome"] for r in top_retry_rows(codex_quota_rows(project))] == ["pending"]
    # 2. the wait succeeds: the probe answers and its rollout shows headroom
    sessions = fixture_home / ".codex" / "sessions"
    wait_code, result = codex_quota.await_reset(
        project_root=project, sessions_dir=sessions, sleep=lambda s: None,
        probe=lambda: (write_rollout(fixture_home, 10, 10, age=0), ("available", 0))[1])
    assert (wait_code, result["available"]) == (0, True)
    # 3. the SAME failed admission is re-admitted once, on TOP
    code, out, err = cli(capsys, top_retry("consultant_main", "consult", project, failed, "capacity_twice",
                                           "--await-quota"))
    assert code == sm.EXIT_OK, err
    assert TOP in out
    assert [r["outcome"] for r in top_retry_rows(codex_quota_rows(project))] == ["pending", "admitted"]
    # 4. a second attempt is refused by the replay guard, and writes nothing
    before = codex_quota_rows(project)
    code, _out, err = cli(capsys, top_retry("consultant_main", "consult", project, failed, "capacity_twice",
                                            "--await-quota"))
    assert code == sm.EXIT_USAGE and "retried at most once" in err
    assert codex_quota_rows(project) == before


def test_322_fr2_a_pending_retry_refused_for_quota_again_is_not_resumed_a_second_time(tmp_path):
    """CONTROL for the one-resumption rule: two `pending` events (the resumption was refused for quota again)
    close the guard; one `pending` event does not. A pending event needs a quota reason."""
    budget = tmp_path / "astra-budget.jsonl"
    aid = "a" * 32

    def pending():
        codex_quota.record_top_retry("c1", project_root=None, budget_path=budget, role="consultant_main",
                                     origin_use="consult", origin_key="c1", failed_admission_id=aid,
                                     failed_model="gpt-6-sol", failed_reason="capacity_twice",
                                     retry_model=TOP, outcome="pending", reason="quota_exhausted")
    budget.write_text(json.dumps({"admitted": True, "admission_id": aid, "use": "consult"}) + "\n",
                      encoding="utf-8")
    pending()
    assert codex_quota.find_admission(None, aid, budget_path=budget)[1] is False
    pending()
    assert codex_quota.find_admission(None, aid, budget_path=budget)[1] is True
    with pytest.raises(ValueError):
        codex_quota.record_top_retry("c1", project_root=None, budget_path=budget, role="consultant_main",
                                     origin_use="consult", origin_key="c1", failed_admission_id=aid,
                                     failed_model="gpt-6-sol", failed_reason="capacity_twice",
                                     retry_model=TOP, outcome="pending", reason="budget_spent")


def codex_quota_rows(project):
    path = codex_quota.budget_path_for(project)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _fresh_failed_admission(capsys, project, fixture_home):
    write_rollout(fixture_home, 10, 10, age=0)         # a newer reading with headroom clears the record
    return admit_sol(capsys, "consultant_main", "consult", project)


def test_322_fr2_the_check_only_exhausted_review_admit_is_never_chained_with_and():
    """#322 fix round 2 (item 11): forge 3a's CHECK-ONLY admit exits 10 on the refusal it exists to read, so a
    `&&` after it (or a chain it closes) stops the lead before the JSON is read. Fix round 1's snippet was a
    bare command a lead would chain; the doc now captures it with `; RC=$?` and says why."""
    import re
    text = skill_corpus.read("forge", _FORGE_CLOSE_OUT, root=_SKILLS)
    start = text.index("codex_quota.py admit --use exhausted_review")
    line_start = text.rfind("\n", 0, start) + 1
    line = text[line_start:text.index("\n", start)]
    cmd_at = line.index("codex_quota.py admit --use exhausted_review")
    # the command substitution holding the admit, and what directly follows it
    after = line[cmd_at:]
    close = after.index('--task-key "$RID" --project-root .)"') + len('--task-key "$RID" --project-root .)"')
    assert not after[close:].lstrip().startswith("&&"), after[close:close + 20]
    assert after[close:].startswith("; RC=$?")
    assert re.search(r"exits \*\*10\*\*.*never chain it with `&&`", line)


# =========================================================================== #
# #322 user-scoped round -- items 5 and 9. Each failed before its fix.
# =========================================================================== #
def _pending_retry(capsys, project, fixture_home):
    """A failed Sol admission whose TOP retry was refused for quota and DEFERRED: one `pending` event."""
    write_codex_roster(fixture_home)
    forge_cycle(project, "cycle-1")
    failed = admit_sol(capsys, "consultant_main", "consult", project)
    write_rollout(fixture_home, 99.5, 20)
    code, out, _ = cli(capsys, top_retry("consultant_main", "consult", project, failed, "capacity_twice",
                                         "--await-quota"))
    assert code == sm.EXIT_SUBSTITUTE and out.splitlines()[-1] == "substitution=deferred"
    assert [r["outcome"] for r in top_retry_rows(codex_quota_rows(project))] == ["pending"]
    return failed


def test_322_usr_two_concurrent_resumers_get_one_attempt(fixture_home, project, codex_cli, capsys, monkeypatch):
    """Item 5: two resumers of ONE pending event run at once. Fix round 2 checked the replay guard, admitted and
    appended the event in separate lock acquisitions, so both passed the guard and both reached admit()."""
    import threading
    failed = _pending_retry(capsys, project, fixture_home)
    write_rollout(fixture_home, 10, 10, age=0)                     # the reset: headroom again
    codex_quota.clear_exhausted()
    barrier = threading.Barrier(2, timeout=3)
    real_admit = codex_quota.admit
    admits = []

    def admit(use, *args, **kwargs):
        if use == "top_retry":
            admits.append(threading.current_thread().name)
            try:
                barrier.wait()      # both resumers inside the window between the guard and the event
            except threading.BrokenBarrierError:
                pass
        return real_admit(use, *args, **kwargs)

    monkeypatch.setattr(codex_quota, "admit", admit)
    codes = {}

    def run(name):
        codes[name] = sm.main(top_retry("consultant_main", "consult", project, failed, "capacity_twice",
                                        "--await-quota"))

    threads = [threading.Thread(target=run, args=(n,), name=n) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    capsys.readouterr()
    assert len(admits) == 1, admits
    assert sorted(codes.values()) == sorted([sm.EXIT_OK, sm.EXIT_USAGE])
    assert [r["outcome"] for r in top_retry_rows(codex_quota_rows(project))] == ["pending", "admitted"]


def test_322_usr_the_reservation_is_one_locked_step(tmp_path):
    """Item 5, at the store: the replay check and the reservation are one step, keyed by the admission alone.
    One pending event permits exactly one more reservation, whatever cycle key the callers hold."""
    budget = tmp_path / "astra-budget.jsonl"
    aid = "b" * 32
    budget.write_text(json.dumps({"admitted": True, "admission_id": aid, "use": "consult"}) + "\n",
                      encoding="utf-8")
    assert codex_quota.claim_top_retry(None, aid, budget_path=budget) == (True, "claimed")
    assert codex_quota.claim_top_retry(None, aid, budget_path=budget) == (False, "replay")   # a concurrent 2nd
    codex_quota.record_top_retry("c1", project_root=None, budget_path=budget, role="consultant_main",
                                 origin_use="consult", origin_key="c1", failed_admission_id=aid,
                                 failed_model="gpt-6-sol", failed_reason="capacity_twice",
                                 retry_model=TOP, outcome="pending", reason="quota_exhausted")
    assert codex_quota.claim_top_retry(None, aid, budget_path=budget) == (True, "claimed")   # the resumption
    assert codex_quota.claim_top_retry(None, aid, budget_path=budget) == (False, "replay")
    assert codex_quota.claim_top_retry(None, "c" * 32, budget_path=budget) == (False, "error")  # no admission
    # the reservations live beside the store, never in it
    assert [json.loads(l).get("kind") for l in budget.read_text(encoding="utf-8").splitlines()] == [
        None, "top_retry"]


def test_322_usr_a_legacy_pending_event_still_permits_one_resumption_only(tmp_path):
    """A pending event written before reservations existed: one resumption, then the guard."""
    budget = tmp_path / "astra-budget.jsonl"
    aid = "d" * 32
    budget.write_text(json.dumps({"admitted": True, "admission_id": aid, "use": "consult"}) + "\n",
                      encoding="utf-8")
    codex_quota.record_top_retry("c1", project_root=None, budget_path=budget, role="consultant_main",
                                 origin_use="consult", origin_key="c1", failed_admission_id=aid,
                                 failed_model="gpt-6-sol", failed_reason="capacity_twice",
                                 retry_model=TOP, outcome="pending", reason="quota_exhausted")
    assert codex_quota.claim_top_retry(None, aid, budget_path=budget) == (True, "claimed")
    assert codex_quota.claim_top_retry(None, aid, budget_path=budget) == (False, "replay")


def test_322_usr_a_pending_retry_that_ends_in_a_stand_in_is_spent(fixture_home, project, codex_cli, capsys):
    """Item 9 (Opus N4): the wait ends without codex, and step 4 records the stand-in on `top_retry`. That closes
    the pending event: a later resumption of the same failed admission is refused by the replay guard."""
    failed = _pending_retry(capsys, project, fixture_home)
    code, out, err = cli(capsys, ["substitute", "--role", "consultant_main", "--use", "top_retry",
                                  "--cycle-id", "cycle-1", "--requested-model", TOP,
                                  "--reason", "quota_exhausted_timeout", "--project-root", str(project)])
    assert code == sm.EXIT_SUBSTITUTE, err
    assert codex_quota.find_admission(project, failed)[1] is True
    write_rollout(fixture_home, 10, 10, age=0)
    codex_quota.clear_exhausted()
    before = codex_quota_rows(project)
    code, _out, err = cli(capsys, top_retry("consultant_main", "consult", project, failed, "capacity_twice",
                                            "--await-quota"))
    assert code == sm.EXIT_USAGE and "retried at most once" in err
    assert codex_quota_rows(project) == before


def test_322_usr_a_stand_in_on_another_key_or_role_does_not_close_the_pending_event(tmp_path):
    """CONTROL: only a `top_retry` substitution on the pending event's own key and role closes it."""
    budget = tmp_path / "astra-budget.jsonl"
    aid = "e" * 32
    budget.write_text(json.dumps({"admitted": True, "admission_id": aid, "use": "consult"}) + "\n",
                      encoding="utf-8")
    codex_quota.record_top_retry("c1", project_root=None, budget_path=budget, role="consultant_main",
                                 origin_use="consult", origin_key="c1", failed_admission_id=aid,
                                 failed_model="gpt-6-sol", failed_reason="capacity_twice",
                                 retry_model=TOP, outcome="pending", reason="quota_exhausted")
    for use, key, role in (("top_retry", "c2", "consultant_main"), ("top_retry", "c1", "arbiter"),
                           ("consult", "c1", "consultant_main")):
        with open(budget, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": "substitution", "use": use, "key": key, "role": role}) + "\n")
    assert codex_quota.find_admission(None, aid, budget_path=budget)[1] is False
