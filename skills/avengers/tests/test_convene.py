#!/usr/bin/env python3
"""avengers — test_convene.py (WP-2).

Covers the resolver acceptance areas: fail-closed structural validate (sub-quorum,
provider-family floor, arbiter/adversarial-provider invariant, >=1 adversarial),
retired-tier rejection ('high'), two-layer merge (no repo-local override layer),
guard-stack injection, session-plan schema validation, and --dry-run pre-spend
review. Runs under pytest; stdlib + PyYAML only.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_CONVENE = Path(__file__).resolve().parent.parent / "scripts" / "convene.py"
_spec = importlib.util.spec_from_file_location("avengers_convene", _CONVENE)
convene = importlib.util.module_from_spec(_spec)
sys.modules["avengers_convene"] = convene
_spec.loader.exec_module(convene)

_REAL_PROFILES = Path(__file__).resolve().parent.parent / "profiles"
_REAL_ROSTER = Path(__file__).resolve().parent.parent / "roster"


# --------------------------------------------------------------------------- #
# Synthetic fixture builders
# --------------------------------------------------------------------------- #
def _write_card(rdir, seat_id, provider, effort, adversarial, can_arbitrate, fallback_ok=True):
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / f"{seat_id}.yaml").write_text(
        "seat_id: %s\n"
        "profession: test\n"
        "adversarial_role: %s\n"
        "can_arbitrate: %s\n"
        "incentive: {optimizes_for: x, discounts: y, standing_challenge: z, failure_mode: w}\n"
        "provider: {affinity: %s, fallback_ok: %s, effort: %s}\n"
        "forbidden: []\n"
        % (seat_id, str(adversarial).lower(), str(can_arbitrate).lower(),
           provider, str(fallback_ok).lower(), effort),
        encoding="utf-8",
    )


def _write_profile(pdir, family, seats, arbiter_prefer=None, semantics="ratification",
                   budgets=None, outcome=("decision",)):
    pdir.mkdir(parents=True, exist_ok=True)
    seat_lines = ""
    for s in seats:
        seat_lines += f"  - ref: {s['ref']}\n    provider: {s['provider']}\n    effort: {s['effort']}\n"
        if s.get("adversarial_role") is not None:
            seat_lines += f"    adversarial_role: {str(s['adversarial_role']).lower()}\n"
    budget_lines = ""
    if budgets:
        budget_lines = "budgets:\n" + "".join(f"  {k}: {v}\n" for k, v in budgets.items())
    prefer_line = f"  prefer: {arbiter_prefer}\n" if arbiter_prefer else ""
    outcome_list = ", ".join(outcome)
    (pdir / f"{family}.yaml").write_text(
        f"schema: avengers-profile.v1\n"
        f"family: {family}\n"
        f"seats:\n{seat_lines}"
        f"arbiter:\n{prefer_line}  effort_on_codex: max\n"
        f"phases:\n  converge:\n    semantics: {semantics}\n"
        f"outcome:\n  type: [{outcome_list}]\n  default: {outcome[0]}\n"
        f"{budget_lines}",
        encoding="utf-8",
    )


def _std_roster(rdir):
    _write_card(rdir, "skeptic", "codex", "xhigh", True, False)
    _write_card(rdir, "architect", "claude", "default", False, True)
    _write_card(rdir, "operator", "agy", "default", False, True)


# --------------------------------------------------------------------------- #
# Happy path against the REAL shipped profile
# --------------------------------------------------------------------------- #
def test_real_profile_resolves_and_validates():
    plan = convene.build_session_plan(
        {"profile": "coding-ratification", "task": "t", "outcome": "decision"},
        profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER, session_id="fixed-id",
    )
    assert plan["schema"] == "session-plan.v1"
    assert plan["session_id"] == "fixed-id"
    assert len(plan["profile_sha256"]) == 64
    assert plan["quorum"]["member_seats"] == 3
    assert set(plan["quorum"]["provider_families"]) == {"codex", "claude", "agy"}
    assert plan["arbiter"]["seat"] == "architect"
    assert plan["arbiter"]["provider"] == "claude"  # != adversarial codex
    # schema validation clean
    assert convene.schema_validate(plan, convene.load_schema()) == []


def test_guard_stacks_injected():
    plan = convene.build_session_plan(
        {"profile": "coding-ratification", "task": "t"},
        profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER,
    )
    seats = {s["seat_id"]: s for s in plan["seats"]}
    # codex challenger: --ephemeral -s read-only, pinned effort
    assert "--ephemeral -s read-only" in seats["skeptic"]["guard_stack"]
    assert "model_reasoning_effort=xhigh" in seats["skeptic"]["guard_stack"]
    assert seats["skeptic"]["guard_stack"].startswith("timeout ")
    # agy: --sandbox with flags BEFORE -p
    agy = seats["operator"]["guard_stack"]
    assert agy.startswith("timeout 600 agy --sandbox -p ")
    assert agy.index("--sandbox") < agy.index("-p")


# --------------------------------------------------------------------------- #
# Retired-tier rejection
# --------------------------------------------------------------------------- #
def test_reject_high_effort(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    _write_card(rdir, "skeptic", "codex", "high", True, False)  # 'high' retired
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "high"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ], arbiter_prefer="architect")
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert "RETIRED" in str(e.value)


def test_reject_unpinned_codex(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "default"},  # un-pinned codex
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ], arbiter_prefer="architect")
    with pytest.raises(convene.ConveneError):
        convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)


# --------------------------------------------------------------------------- #
# Fail-closed structural sub-quorum
# --------------------------------------------------------------------------- #
def test_fail_closed_too_few_seats(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
    ], arbiter_prefer="architect")
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert "sub-quorum" in str(e.value)


def test_fail_closed_single_family_no_fallback(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "skeptic", "codex", "xhigh", True, False, fallback_ok=False)
    _write_card(rdir, "s2", "codex", "medium", False, True, fallback_ok=False)
    _write_card(rdir, "s3", "codex", "medium", False, True, fallback_ok=False)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "s2", "provider": "codex", "effort": "medium"},
        {"ref": "s3", "provider": "codex", "effort": "medium"},
    ], arbiter_prefer="s2")
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert "provider family" in str(e.value)


def test_single_family_with_fallback_relaxes(tmp_path):
    # <2 families but a declared fallback -> allowed (design §4 exception), and the
    # arbiter must still be satisfiable, so make one non-adversarial codex seat.
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "skeptic", "codex", "xhigh", True, False, fallback_ok=True)
    _write_card(rdir, "s2", "codex", "medium", False, True, fallback_ok=True)
    _write_card(rdir, "s3", "codex", "medium", False, True, fallback_ok=True)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "s2", "provider": "codex", "effort": "medium"},
        {"ref": "s3", "provider": "codex", "effort": "medium"},
    ], arbiter_prefer="s2")
    # single family but fallback declared: families check passes; BUT arbiter
    # constraint fails (every provider is the adversarial family) -> still fail-closed.
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert "arbiter constraint" in str(e.value)


def test_fail_closed_arbiter_unsatisfiable(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "skeptic", "codex", "xhigh", True, False)          # codex adversarial
    _write_card(rdir, "advagy", "agy", "default", True, True)            # agy adversarial + can_arbitrate
    _write_card(rdir, "arch", "codex", "medium", False, True)           # codex can_arbitrate
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "advagy", "provider": "agy", "effort": "default"},
        {"ref": "arch", "provider": "codex", "effort": "medium"},
    ], arbiter_prefer="arch")
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert "arbiter constraint" in str(e.value)


def test_fail_closed_no_adversarial(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "a", "codex", "medium", False, True)
    _write_card(rdir, "b", "claude", "default", False, True)
    _write_card(rdir, "c", "agy", "default", False, True)
    _write_profile(pdir, "fam", [
        {"ref": "a", "provider": "codex", "effort": "medium"},
        {"ref": "b", "provider": "claude", "effort": "default"},
        {"ref": "c", "provider": "agy", "effort": "default"},
    ], arbiter_prefer="b")
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert "adversarial" in str(e.value)


# --------------------------------------------------------------------------- #
# Two-layer merge + no repo-local override
# --------------------------------------------------------------------------- #
def test_two_layer_merge_defaults_and_profile(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ], arbiter_prefer="architect", budgets={"max_cycles": 2})
    plan = convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    # profile wins where set; shipped default fills the rest
    assert plan["budgets"]["max_cycles"] == 2         # from profile
    assert plan["budgets"]["max_seat_calls"] == 10    # from shipped default
    assert plan["budgets"]["wall_clock_s"] == 900     # from shipped default
    assert plan["merge_provenance"]["layers"] == ["shipped_defaults", "profile"]


def test_caller_budget_request_applied_and_recorded(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ], arbiter_prefer="architect")
    plan = convene.build_session_plan(
        {"profile": "fam", "budget": {"max_seat_calls": 4}},
        profiles_dir=pdir, roster_dir=rdir,
    )
    assert plan["budgets"]["max_seat_calls"] == 4
    assert plan["merge_provenance"]["budget_from_caller_request"] is True


def test_no_repo_local_override_layer(tmp_path):
    # A stray repo-local config must NOT influence the plan (design §3/§14).
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ], arbiter_prefer="architect")
    # Plant repo-local override files convene must ignore.
    (tmp_path / ".avengers").mkdir()
    (tmp_path / ".avengers" / "config.yaml").write_text("budgets: {max_seat_calls: 999}\n")
    (pdir / "override.yaml").write_text("budgets: {max_seat_calls: 888}\n")
    plan = convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert plan["budgets"]["max_seat_calls"] == 10  # shipped default, NOT 999/888
    assert plan["merge_provenance"]["repo_local_overrides"].startswith("none")


# --------------------------------------------------------------------------- #
# Schema validation catches a corrupt plan
# --------------------------------------------------------------------------- #
def test_schema_rejects_high_effort_in_plan():
    plan = convene.build_session_plan(
        {"profile": "coding-ratification", "task": "t"},
        profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER,
    )
    plan["seats"][0]["effort"] = "high"
    errs = convene.schema_validate(plan, convene.load_schema())
    assert errs and any("enum" in e for e in errs)


def test_schema_rejects_missing_required():
    plan = convene.build_session_plan(
        {"profile": "coding-ratification", "task": "t"},
        profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER,
    )
    del plan["arbiter"]
    errs = convene.schema_validate(plan, convene.load_schema())
    assert any("arbiter" in e for e in errs)


# --------------------------------------------------------------------------- #
# --dry-run review + write flow
# --------------------------------------------------------------------------- #
def test_dry_run_review_text():
    plan = convene.build_session_plan(
        {"profile": "coding-ratification", "task": "lower the default?"},
        profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER,
    )
    review = convene.render_pre_spend_review(plan)
    assert "PRE-SPEND REVIEW" in review
    assert "NO run performed" in review
    assert "retired effort tiers rejected: high" in review


def test_cli_dry_run_writes_nothing(tmp_path, capsys):
    rc = convene.main([
        "--profile", "coding-ratification", "--task", "t", "--dry-run",
        "--profiles-dir", str(_REAL_PROFILES), "--roster-dir", str(_REAL_ROSTER),
        "--project-root", str(tmp_path),
    ])
    assert rc == 0
    assert not (tmp_path / ".avengers").exists()  # no session dir on dry-run


def test_cli_writes_session_plan(tmp_path):
    rc = convene.main([
        "--profile", "coding-ratification", "--task", "write it",
        "--profiles-dir", str(_REAL_PROFILES), "--roster-dir", str(_REAL_ROSTER),
        "--project-root", str(tmp_path), "--session-id", "sid-1",
    ])
    assert rc == 0
    plan_path = tmp_path / ".avengers" / "sessions" / "sid-1" / "session-plan.json"
    assert plan_path.exists()
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    assert data["session_id"] == "sid-1"
    assert convene.schema_validate(data, convene.load_schema()) == []


def test_cli_fail_closed_returns_nonzero(tmp_path):
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _std_roster(rdir)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "architect", "provider": "claude", "effort": "default"},
    ], arbiter_prefer="architect")
    rc = convene.main([
        "--profile", "fam", "--profiles-dir", str(pdir), "--roster-dir", str(rdir),
        "--project-root", str(tmp_path),
    ])
    assert rc == 2  # fail-closed, no spend
