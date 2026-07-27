#!/usr/bin/env python3
"""avengers — test_convene.py (WP-2 base; WP-1 effort-layer rewrite).

Covers the resolver acceptance areas: fail-closed structural validate (sub-quorum,
provider-family floor, arbiter/adversarial-provider invariant, >=1 adversarial),
retired-tier rejection ('high'), two-layer merge (no repo-local override layer),
guard-stack injection, session-plan schema validation, and --dry-run pre-spend
review. Runs under pytest; stdlib + PyYAML only.

WP-1 (design §2a) rewrote the effort tests to the SEAT-CLASS contract: effort pins
resolve per (provider, seat-class) through resolve_effort(); a challenger provider-
swap off codex resolves via the challenger_floor seat-class instead of crashing
(success criterion #2); 'high' stays retired; guard_stack_for + the ratification-
arbiter max/1200 case re-key on (provider, seat-class).

WP-2 (design §4/§9.8) rewrote the ARBITER-SELECTION tests to the EXTERNAL SEATLESS
arbiter contract: the arbiter is a fresh cold-context CALL (is_external/cold_context,
no `seat`), its provider != every deliberation seat (widened from adversarial-only),
clean vs fallback paths, fallback_arbiter_residual on the fallback path, and the ONLY
unsatisfiable case (all-adversarial) fails CLOSED. The plan schema is now
session-plan.v2. Cross-cutting arbiter-behavior tests live in test_arbiter_external.py.
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
        seat_lines += f"  - ref: {s['ref']}\n"
        # WP-2: provider/effort pins are OPTIONAL (a seat dict may omit them to
        # rely on the roster card's affinity — success criterion #1).
        if s.get("provider") is not None:
            seat_lines += f"    provider: {s['provider']}\n"
        if s.get("effort") is not None:
            seat_lines += f"    effort: {s['effort']}\n"
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
    assert plan["schema"] == "session-plan.v2"
    assert plan["session_id"] == "fixed-id"
    assert len(plan["profile_sha256"]) == 64
    # WP-3 (design §5/§7): coding-ratification gains the steward as the 4th deliberation
    # seat (skeptic + architect + operator + steward), so member_seats is now 4. The
    # steward is agy, so provider_families is unchanged {codex, claude, agy}, and the
    # arbiter is still the external claude fallback (asserted below).
    assert plan["quorum"]["member_seats"] == 4
    assert set(plan["quorum"]["provider_families"]) == {"codex", "claude", "agy"}
    # WP-2: the arbiter is a fresh EXTERNAL cold-context call — no `seat` field.
    arb = plan["arbiter"]
    assert "seat" not in arb
    assert arb["is_external"] is True and arb["cold_context"] is True
    assert arb["provider"] == "claude"        # strongest adjudication prior, != adversarial codex
    # coding-ratification pins all 3 families -> the arbiter ALWAYS takes the fallback path
    assert arb["path"] == "fallback"
    assert arb["fallback_arbiter_residual"] is True
    # no member seat is the arbiter (the participant-judge violation is gone)
    assert all("arbiter" not in s.get("seat_class", "") for s in plan["seats"])
    # schema validation clean (now v2)
    assert convene.schema_validate(plan, convene.load_schema()) == []


def test_no_per_seat_pins_resolves_via_affinity(tmp_path):
    # SUCCESS CRITERION #1: a profile with NO per-seat provider pins resolves to a
    # valid, constraint-satisfying staffing (>=2 families, external arbiter,
    # effort-compatible) via the roster cards' affinity — proving provider locks are
    # now opt-in DATA, not schema. A per-seat provider: override still wins.
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "skeptic", "codex", "xhigh", True, False)          # affinity codex, adversarial
    _write_card(rdir, "architect", "claude", "default", False, False)
    _write_card(rdir, "operator", "agy", "default", False, False)
    # seat entries omit provider/effort -> the resolver falls back to card affinity.
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": None, "effort": None, "adversarial_role": None},
        {"ref": "architect", "provider": None, "effort": None},
        {"ref": "operator", "provider": None, "effort": None},
    ])
    plan = convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    seats = {s["seat_id"]: s for s in plan["seats"]}
    assert seats["skeptic"]["provider"] == "codex"       # from card affinity, no pin
    assert seats["architect"]["provider"] == "claude"
    assert seats["operator"]["provider"] == "agy"
    assert set(plan["quorum"]["provider_families"]) == {"codex", "claude", "agy"}  # >=2 families
    assert plan["arbiter"]["is_external"] is True
    assert convene.schema_validate(plan, convene.load_schema()) == []

    # A per-seat provider: override still WINS over the card affinity (opt-in lock).
    _write_profile(pdir, "fam2", [
        {"ref": "skeptic", "provider": None, "effort": None, "adversarial_role": None},
        {"ref": "architect", "provider": None, "effort": None},
        {"ref": "operator", "provider": "claude", "effort": "default"},   # override agy -> claude
    ])
    plan2 = convene.build_session_plan({"profile": "fam2"}, profiles_dir=pdir, roster_dir=rdir)
    seats2 = {s["seat_id"]: s for s in plan2["seats"]}
    assert seats2["operator"]["provider"] == "claude"    # override won over affinity


def test_run_record_written_alongside_session_plan(tmp_path):
    # SUCCESS CRITERION #7: every materialized run writes run-record.json validating
    # against run-record.v1.schema.json with the §6a instrumentation (provider +
    # effort per seat with the seat-class name, fallback_arbiter_residual, the
    # post-run dissent-margin + 1-5 outcome-grade slots).
    rc = convene.main([
        "--profile", "coding-ratification", "--task", "t",
        "--profiles-dir", str(_REAL_PROFILES), "--roster-dir", str(_REAL_ROSTER),
        "--project-root", str(tmp_path), "--session-id", "rr-1",
    ])
    assert rc == 0
    rr_path = tmp_path / ".avengers" / "sessions" / "rr-1" / "run-record.json"
    assert rr_path.exists()
    rr = json.loads(rr_path.read_text(encoding="utf-8"))
    assert convene.schema_validate(rr, convene.load_run_record_schema()) == []
    assert rr["schema"] == "run-record.v1"
    # provider + effort + seat-class name recorded per seat
    sk = next(s for s in rr["staffing"]["seats"] if s["seat_id"] == "skeptic")
    assert (sk["provider"], sk["effort"], sk["seat_class"]) == ("codex", "xhigh", "xhigh")
    # coding-ratification -> fallback arbiter path -> residual flagged
    assert rr["arbiter"]["path"] == "fallback"
    assert rr["fallback_arbiter_residual"] is True
    # post-run outcome slots present but ungraded at materialization time
    assert rr["outcome"] == {"dissent_margin": None, "outcome_grade": None, "graded": False}


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
    # WP-1 seat-class contract: every resolved seat carries its seat_class + an
    # (optional) advisory note. A native raw-tier pin keeps the tier as its class.
    assert seats["skeptic"]["seat_class"] == "xhigh"
    assert seats["skeptic"]["effort_note"] is None
    assert seats["skeptic"]["effort"] == "xhigh"
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
    # WP-1 seat-class contract: 'high' is retired regardless of provider (the old
    # code only checked it before the codex/non-codex branch — now it is first,
    # so a non-codex 'high' pin is rejected too, not silently resolved down).
    with pytest.raises(convene.ConveneError) as e2:
        convene.resolve_effort("skeptic", "claude", "high")
    assert "RETIRED" in str(e2.value)


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
# Seat-class effort semantics (WP-1, design §2a)
# --------------------------------------------------------------------------- #
def test_seat_class_challenger_floor_resolves_per_provider():
    # The challenger_floor seat-class resolves per (provider, seat-class):
    # codex -> xhigh (native, no note); claude/agy -> default + advisory note.
    assert convene.resolve_effort("skeptic", "codex", "challenger_floor") == ("xhigh", "challenger_floor", None)
    c_eff, c_cls, c_note = convene.resolve_effort("skeptic", "claude", "challenger_floor")
    assert (c_eff, c_cls) == ("default", "challenger_floor")
    assert "no codex-equivalent anti-sycophancy floor for this provider" in c_note
    a_eff, a_cls, a_note = convene.resolve_effort("skeptic", "agy", "challenger_floor")
    assert (a_eff, a_cls) == ("default", "challenger_floor")
    assert a_note and "anti-sycophancy floor" in a_note


def test_raw_tier_cross_provider_resolves_not_crash():
    # SUCCESS CRITERION #2 (unit level): the old non-codex + non-'default'
    # fail-closed (former validate_effort:184-189) no longer crashes — a raw
    # codex-band tier pinned on a claude/agy seat resolves DOWN with a note.
    eff, cls, note = convene.resolve_effort("skeptic", "claude", "xhigh")
    assert (eff, cls) == ("default", "xhigh")
    assert note and "no claude-native equivalent" in note
    # codex still MUST be explicitly pinned (un-pinned/illegal codex fails closed).
    with pytest.raises(convene.ConveneError):
        convene.resolve_effort("skeptic", "codex", "default")
    # a truly unknown token (typo'd seat-class) fails closed, not silently resolved.
    with pytest.raises(convene.ConveneError):
        convene.resolve_effort("skeptic", "claude", "challenger_flooor")


def test_challenger_provider_swap_off_codex(tmp_path):
    # SUCCESS CRITERION #2: rotating the challenger (skeptic) OFF codex resolves
    # via the challenger_floor seat-class instead of raising ConveneError, and
    # surfaces the 'no anti-sycophancy floor' note (destined for the run record).
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "skeptic", "claude", "challenger_floor", True, False)
    _write_card(rdir, "architect", "codex", "medium", False, True)
    _write_card(rdir, "operator", "agy", "default", False, True)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "claude", "effort": "challenger_floor"},
        {"ref": "architect", "provider": "codex", "effort": "medium"},
        {"ref": "operator", "provider": "agy", "effort": "default"},
    ], arbiter_prefer="operator")
    plan = convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    seats = {s["seat_id"]: s for s in plan["seats"]}
    sk = seats["skeptic"]
    assert sk["provider"] == "claude"
    assert sk["effort"] == "default"                 # resolved down — NO crash
    assert sk["seat_class"] == "challenger_floor"    # semantic name preserved
    assert "no codex-equivalent anti-sycophancy floor for this provider" in (sk["effort_note"] or "")
    # the codex seat still pins its native tier into its guard stack
    assert "model_reasoning_effort=medium" in seats["architect"]["guard_stack"]
    # the plan still validates against the (unchanged) v1 schema
    assert convene.schema_validate(plan, convene.load_schema()) == []


def test_ratification_arbiter_codex_max_1200_rekey(tmp_path):
    # AC3 (WP-2 external-arbiter rewrite): the ratification-arbiter max/1200 special
    # case is keyed on (provider, seat-class). To force a CODEX external arbiter,
    # codex must be the sole NON-adversarial provider (skeptic=claude + arch=agy are
    # adversarial; operator=codex is not) -> the fallback path selects codex, which
    # resolves to 'max' via the RATIFICATION_ARBITER seat-class and gets 1200s —
    # NOT by matching the literal effort string 'max'.
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "skeptic", "claude", "challenger_floor", True, False)  # adversarial claude
    _write_card(rdir, "arch", "agy", "default", True, False)                 # adversarial agy
    _write_card(rdir, "operator", "codex", "medium", False, False)           # non-adversarial codex
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "claude", "effort": "challenger_floor"},
        {"ref": "arch", "provider": "agy", "effort": "default"},
        {"ref": "operator", "provider": "codex", "effort": "medium"},
    ])
    plan = convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    arb = plan["arbiter"]
    assert arb["is_external"] is True and "seat" not in arb
    assert arb["provider"] == "codex"          # sole non-adversarial provider
    assert arb["path"] == "fallback"           # codex deliberated (as operator)
    assert arb["effort"] == "max"
    assert arb["seat_class"] == convene.RATIFICATION_ARBITER
    assert "timeout 1200" in arb["guard_stack"]
    assert "model_reasoning_effort=max" in arb["guard_stack"]


def test_guard_stack_for_rekeys_on_seat_class():
    # guard_stack_for re-keys the 1200 timeout on the seat-class, not literal max:
    # a plain codex 'max' member seat (seat_class 'max', not RATIFICATION_ARBITER)
    # gets the normal 300s ceiling; only the RATIFICATION_ARBITER class gets 1200.
    member = convene.guard_stack_for("codex", "max", seat_class="max",
                                     is_arbiter=False, is_ratification=True)
    assert "timeout 300" in member
    arbiter = convene.guard_stack_for("codex", "max", seat_class=convene.RATIFICATION_ARBITER,
                                      is_arbiter=True, is_ratification=True)
    assert "timeout 1200" in arbiter


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
    # <2 families but a declared fallback -> the family floor relaxes (design §4).
    # WP-2: the EXTERNAL arbiter then resolves on the CLEAN path — a provider used
    # by NO deliberation seat (all seats are codex, so claude/agy are both unused;
    # the strongest-prior one, claude, is picked). No fail-closed here: the only
    # unsatisfiable arbiter case is all-adversarial-across-all-three-providers.
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "skeptic", "codex", "xhigh", True, False, fallback_ok=True)
    _write_card(rdir, "s2", "codex", "medium", False, True, fallback_ok=True)
    _write_card(rdir, "s3", "codex", "medium", False, True, fallback_ok=True)
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "s2", "provider": "codex", "effort": "medium"},
        {"ref": "s3", "provider": "codex", "effort": "medium"},
    ])
    plan = convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert plan["quorum"]["fallback_relaxed"] is True
    arb = plan["arbiter"]
    assert arb["is_external"] is True
    assert arb["path"] == "clean"                    # arbiter provider used by no seat
    assert arb["provider"] == "claude"               # strongest adjudication prior among {claude, agy}
    assert arb["fallback_arbiter_residual"] is False  # clean path -> no residual
    assert convene.schema_validate(plan, convene.load_schema()) == []


def test_fail_closed_arbiter_unsatisfiable(tmp_path):
    # WP-2: the ONLY unsatisfiable arbiter case — every provider deliberated AND
    # every one is adversarial, so no non-adversarial external arbiter exists.
    # Fails CLOSED (never hangs). All 3 families + all adversarial passes the
    # structural gate (>=1 adversarial), so the failure is specifically the arbiter.
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    _write_card(rdir, "skeptic", "codex", "xhigh", True, False)     # codex adversarial
    _write_card(rdir, "advclaude", "claude", "default", True, False)  # claude adversarial
    _write_card(rdir, "advagy", "agy", "default", True, False)      # agy adversarial
    _write_profile(pdir, "fam", [
        {"ref": "skeptic", "provider": "codex", "effort": "xhigh"},
        {"ref": "advclaude", "provider": "claude", "effort": "default"},
        {"ref": "advagy", "provider": "agy", "effort": "default"},
    ])
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    msg = str(e.value)
    assert "arbiter constraint unsatisfiable" in msg and "adversarial" in msg


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
