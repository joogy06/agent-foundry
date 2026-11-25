#!/usr/bin/env python3
"""avengers — test_arbiter_external.py (WP-2, design §4).

Focused coverage for the EXTERNAL, SEATLESS, cold-context arbiter — the
highest-value v2 fix (the participant-judge violation). Complements the
resolver-integration tests in test_convene.py:

  * CLEAN path — an eligible arbiter provider used by NO deliberation seat (total
    exclusion, no residual).
  * FALLBACK path — no eligible provider is free of deliberation: the
    strongest-adjudication-prior NON-adversarial provider, cold-context, with the
    ACCEPTED style-recognition residual FLAGGED (fallback_arbiter_residual) in
    run-record.json (§6a). In a healthy session coding-ratification lands here
    (agy, the one provider its seats do not use, is barred from a healthy
    session's selection); under any codex refusal its arbiter is agy on the fallback
    path (agy holds a seat there since #368).
  * ALL-ADVERSARIAL — the ONLY unsatisfiable arbiter case -> fails CLOSED, no hang.
  * No seat is ever the adjudicator (participant-judge gone); `can_arbitrate` inert.
  * capability-priors DATA drives adjudication selection and fails OPEN.

stdlib + PyYAML only; runs under pytest.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_CONVENE = _ROOT / "scripts" / "convene.py"
_spec = importlib.util.spec_from_file_location("avengers_convene", _CONVENE)
convene = importlib.util.module_from_spec(_spec)
sys.modules["avengers_convene"] = convene
_spec.loader.exec_module(convene)

_REAL_PROFILES = _ROOT / "profiles"
_REAL_ROSTER = _ROOT / "roster"

_META = _ROOT.parent / "_meta"
if str(_META) not in sys.path:
    sys.path.insert(0, str(_META))
import model_roster  # type: ignore  # noqa: E402

#: #291: the Claude tier models are ROSTER DATA (model_roster), never literals of this file. A
#: main-weight Claude member serves MAIN; a declared consultant_support arbiter serves SUPPORT.
MAIN = model_roster.CLAUDE_MAIN
SUPPORT = model_roster.CLAUDE_SUPPORT

# #282 H2 (live-HOME tests): resolve_arbiter / main resolve seat models through seat_model, which records
# a TOP into ~/.claude/state/seat-model-tops.json under the process HOME. Every test here runs under an
# EMPTY temp HOME with a stub `codex` PREPENDED to PATH (conftest.py's `empty_live_home`). The stub
# matters: with no codex on PATH every codex seat substitutes, and
# test_real_profile_fallback_residual_in_run_record would see a different arbiter.
pytestmark = pytest.mark.usefixtures("empty_live_home")


def _seat(provider, adversarial):
    """Minimal seat dict as resolve_arbiter consumes it."""
    return {"seat_id": f"{provider}-seat", "provider": provider, "adversarial_role": adversarial}


# --------------------------------------------------------------------------- #
# The arbiter object shape (design §4 / §10 — the schema contract)
# --------------------------------------------------------------------------- #
def test_arbiter_object_is_seatless_and_external():
    seats = [_seat("codex", True), _seat("claude", False), _seat("agy", False)]
    arb = convene.resolve_arbiter({}, seats, is_ratification=True)
    # DROPS seat; ADDS {is_external, cold_context, path}; KEEPS {provider, effort, guard_stack}.
    assert "seat" not in arb
    assert arb["is_external"] is True
    assert arb["cold_context"] is True
    assert arb["path"] in ("clean", "fallback")
    for k in ("provider", "effort", "guard_stack"):
        assert k in arb


# --------------------------------------------------------------------------- #
# CLEAN path — a provider used by no deliberation seat
# --------------------------------------------------------------------------- #
def test_clean_path_arbiter_provider_used_by_no_seat():
    # All seats codex -> claude & agy are both unused -> CLEAN external arbiter,
    # strongest adjudication prior (claude) wins, no residual.
    seats = [_seat("codex", True), _seat("codex", False), _seat("codex", False)]
    arb = convene.resolve_arbiter({}, seats, is_ratification=True)
    assert arb["path"] == "clean"
    assert arb["provider"] == "claude"
    assert arb["fallback_arbiter_residual"] is False
    # arbiter provider is genuinely external — no deliberation seat used it
    deliberation = {s["provider"] for s in seats}
    assert arb["provider"] not in deliberation


def test_clean_path_two_provider_team_excludes_third():
    # RE-POINTED at amendment 3 (D25/D23): codex(adv) + claude seats leave agy unused, and agy WAS the
    # clean arbiter here. agy is no longer an arbiter candidate in a HEALTHY session
    # (convene.ARBITER_INELIGIBLE_PROVIDERS), so the only unused provider is barred and the session falls
    # back to the non-adversarial claude WITH the residual flagged. The assertion is inverted rather than
    # deleted: it now pins that agy is NOT reached, which is the property D25 bought.
    seats = [_seat("codex", True), _seat("claude", False), _seat("claude", False)]
    arb = convene.resolve_arbiter({}, seats, is_ratification=True)
    assert arb["provider"] != "agy"
    assert (arb["path"], arb["provider"], arb["fallback_arbiter_residual"]) == ("fallback", "claude", True)


def test_a_degraded_session_still_reaches_agy_rather_than_failing_closed():
    # CONTROL for the bar's SCOPE, and the reason it is scoped: once a provider is UNAVAILABLE the
    # session has already lost an arm, and agy is its last-resort arbiter. Barring agy here instead made
    # 32 substitution paths fail closed and would have made coding-ratification unrunnable without codex.
    seats = [_seat("claude", True), _seat("claude", False)]
    arb = convene.resolve_arbiter({}, seats, is_ratification=True, unavailable_providers=frozenset({"codex"}))
    assert (arb["path"], arb["provider"]) == ("clean", "agy")
    # and the healthy twin of the SAME seats does not reach agy
    assert convene.resolve_arbiter({}, seats, is_ratification=True)["provider"] != "agy"


# --------------------------------------------------------------------------- #
# FALLBACK path — no eligible provider is free of deliberation (here all three providers deliberate).
# In a healthy session coding-ratification lands on this path through the agy bar instead
# (test_clean_path_two_provider_team_excludes_third); under any codex refusal its arbiter is agy on the
# fallback path, since #368 seats agy there (test_a_degraded_session_still_reaches_agy_rather_than_failing_closed).
# --------------------------------------------------------------------------- #
def test_fallback_path_flags_residual():
    # SUCCESS CRITERION #3 (fallback): all 3 providers deliberate; codex is the
    # adversary; the arbiter is the strongest-prior NON-adversarial provider
    # (claude), cold-context, with the residual FLAGGED.
    seats = [_seat("codex", True), _seat("claude", False), _seat("agy", False)]
    arb = convene.resolve_arbiter({}, seats, is_ratification=True)
    assert arb["path"] == "fallback"
    assert arb["provider"] == "claude"                 # prior 3 > agy 2
    assert arb["fallback_arbiter_residual"] is True
    # arbiter is NOT one of the adversarial providers (it did not ballot as the adversary)
    adversarial = {s["provider"] for s in seats if s["adversarial_role"]}
    assert arb["provider"] not in adversarial


def test_fallback_prefers_strongest_adjudication_prior():
    # If claude is the adversary, the fallback ranks the non-adversarial providers by prior.
    # RE-POINTED at amendment 3: the candidates were {codex, agy} and agy won on prior 2 > 1; agy is now
    # barred from a HEALTHY session's arbiter, so codex is the only candidate left. The PRIOR ORDER is
    # still what this test is for, and it is proven below on a pair that does not include the barred
    # provider, so the re-point does not quietly turn a ranking test into a one-candidate tautology.
    seats = [_seat("claude", True), _seat("codex", False), _seat("agy", False)]
    arb = convene.resolve_arbiter({}, seats, is_ratification=True)
    assert arb["path"] == "fallback"
    assert arb["provider"] == "codex"
    # the ranking itself, on claude(3) vs codex(1) with neither barred
    ranked = [_seat("agy", True), _seat("claude", False), _seat("codex", False)]
    assert convene.resolve_arbiter({}, ranked, is_ratification=True)["provider"] == "claude"


# --------------------------------------------------------------------------- #
# ALL-ADVERSARIAL — the only unsatisfiable arbiter case -> fail CLOSED
# --------------------------------------------------------------------------- #
def test_all_adversarial_fails_closed():
    seats = [_seat("codex", True), _seat("claude", True), _seat("agy", True)]
    with pytest.raises(convene.ConveneError) as e:
        convene.resolve_arbiter({}, seats, is_ratification=True)
    msg = str(e.value)
    assert "unsatisfiable" in msg and "adversarial" in msg


def test_two_adversarial_providers_still_resolvable_via_clean():
    # codex(adv) + agy(adv) but claude unused -> NOT all-adversarial; the clean
    # path resolves on claude. (All-adversarial requires all THREE providers used
    # AND all adversarial.)
    seats = [_seat("codex", True), _seat("agy", True), _seat("codex", False)]
    arb = convene.resolve_arbiter({}, seats, is_ratification=True)
    assert arb["path"] == "clean"
    assert arb["provider"] == "claude"


# --------------------------------------------------------------------------- #
# End-to-end: the fallback residual reaches run-record.json (§6a)
# --------------------------------------------------------------------------- #
def test_real_profile_fallback_residual_in_run_record(tmp_path):
    rc = convene.main([
        "--profile", "coding-ratification", "--task", "t",
        "--profiles-dir", str(_REAL_PROFILES), "--roster-dir", str(_REAL_ROSTER),
        "--project-root", str(tmp_path), "--session-id", "arb-1",
    ])
    assert rc == 0
    rr = json.loads((tmp_path / ".avengers" / "sessions" / "arb-1" / "run-record.json").read_text())
    assert rr["arbiter"]["provider"] == "claude"
    assert rr["arbiter"]["path"] == "fallback"
    assert rr["arbiter"]["is_external"] is True and rr["arbiter"]["cold_context"] is True
    assert rr["fallback_arbiter_residual"] is True


# --------------------------------------------------------------------------- #
# capability-priors DATA — drives selection AND fails OPEN
# --------------------------------------------------------------------------- #
def test_capability_priors_loads_from_data():
    priors = convene.load_capability_priors()
    assert priors["sha256"]                                   # the DATA file exists + is hashed
    assert priors["adjudication_prior"]["claude"] > priors["adjudication_prior"]["codex"]


def test_capability_priors_fail_open_on_missing_file(tmp_path):
    # A missing DATA file must NOT crash the gate — fall back to builtin defaults.
    priors = convene.load_capability_priors(tmp_path / "does-not-exist.yaml")
    assert priors["sha256"] == ""
    assert priors["adjudication_prior"] == convene.BUILTIN_ADJUDICATION_PRIOR


def test_priors_override_changes_arbiter_selection(tmp_path):
    # The DATA is genuinely load-bearing: flip the adjudication priors so agy
    # outranks claude, and the fallback arbiter follows the DATA to agy.
    # RE-POINTED at amendment 3: the override used to be proven by promoting agy over claude, which a
    # healthy session now bars — proving it on a BARRED provider would have tested the bar, not the DATA.
    # codex carries the same weight of proof: the builtin says claude 3 > codex 1, and the DATA inverts it.
    (tmp_path / "priors.yaml").write_text(
        "schema: avengers-capability-priors.v1\n"
        "adjudication_prior: {agy: 1, claude: 1, codex: 9}\n",
        encoding="utf-8",
    )
    priors = convene.load_capability_priors(tmp_path / "priors.yaml")
    seats = [_seat("codex", True), _seat("claude", False), _seat("agy", False)]
    arb = convene.resolve_arbiter({}, seats, is_ratification=True, priors=priors)
    assert arb["path"] == "fallback"
    assert arb["provider"] == "claude"       # codex is the adversary here, so the DATA cannot lift it
    # the DATA is load-bearing: same seats, codex NOT adversarial -> the override takes it over claude
    lifted = [_seat("agy", True), _seat("claude", False), _seat("codex", False)]
    assert convene.resolve_arbiter({}, lifted, is_ratification=True, priors=priors)["provider"] == "codex"
    # CONTROL: with the builtin priors the same seats resolve claude (3 > 1)
    assert convene.resolve_arbiter({}, lifted, is_ratification=True)["provider"] == "claude"


# --------------------------------------------------------------------------- #
# D23 DECLARED arbiter (S081 revision 4, WP-D3; design §3.4, plan L6) — the relaxed rule on resolve_arbiter itself.
# A profile that declares `arbiter: {provider, role}` with the top-level `arbiter_independence: separate-session`
# is HONOURED: the provider-exclusion rule gives way to "the arbiter's MODEL differs from every seat's model, and
# it runs in its own session". The rule compares MODELS, so the seats must be materialised first.
# --------------------------------------------------------------------------- #
_DECLARED_OPUS = {"arbiter": {"provider": "claude", "role": "consultant_support"},
                  "arbiter_independence": "separate-session"}


def _modelled(provider, adversarial, model):
    return dict(_seat(provider, adversarial), model=model)


def test_a_declared_arbiter_is_honoured_over_the_selection_algorithm():
    seats = [_modelled("claude", True, MAIN), _modelled("codex", False, "gpt-5.6-sol"),
             _modelled("agy", False, "gemini-4-argon-medium")]
    # CONTROL: undeclared, the algorithm excludes the adversarial claude and lands on codex (agy is
    # barred from a healthy session's arbiter since amendment 3; it was agy on prior 2 > codex 1)
    assert convene.resolve_arbiter({}, seats, is_ratification=False)["provider"] == "codex"
    arb = convene.resolve_arbiter(_DECLARED_OPUS, seats, is_ratification=False)
    assert (arb["provider"], arb["model"], arb["seat_model_role"], arb["timeout_s"]) == (
        "claude", SUPPORT, "consultant_support", 600)
    assert (arb["selection"], arb["independence"]) == ("declared", "separate-session")
    # claude deliberated, so the path is fallback and the residual stays flagged
    assert (arb["path"], arb["fallback_arbiter_residual"]) == ("fallback", True)
    assert arb["is_external"] is True and arb["cold_context"] is True and "seat" not in arb


def test_a_declared_arbiter_on_a_provider_no_seat_used_takes_the_clean_path():
    seats = [_modelled("codex", True, "gpt-5.6-sol"), _modelled("agy", False, "gemini-4-argon-medium"),
             _modelled("codex", False, "gpt-5.6-sol")]
    arb = convene.resolve_arbiter(_DECLARED_OPUS, seats, is_ratification=True)
    assert (arb["provider"], arb["path"], arb["fallback_arbiter_residual"], arb["selection"]) == (
        "claude", "clean", False, "declared")


def test_a_declared_arbiter_needs_materialised_seat_models():
    seats = [_seat("claude", True), _seat("codex", False), _seat("agy", False)]
    with pytest.raises(convene.ConveneError) as e:
        convene.resolve_arbiter(_DECLARED_OPUS, seats, is_ratification=False)
    assert "carry no resolved model" in str(e.value)
    # CONTROL: the same model-less seats are all the undeclared algorithm needs
    assert convene.resolve_arbiter({}, seats, is_ratification=False)["provider"] == "codex"


def test_a_declared_arbiter_sharing_a_seat_model_is_refused_even_when_the_provider_rule_would_allow_it():
    # a support-tier arbiter over a support-tier NON-adversarial claude seat: the provider rule never looked at models
    seats = [_modelled("codex", True, "gpt-5.6-sol"), _modelled("claude", False, SUPPORT),
             _modelled("agy", False, "gemini-4-argon-medium")]
    assert convene.resolve_arbiter({}, seats, is_ratification=False)["provider"] == "claude"   # CONTROL: allowed
    with pytest.raises(convene.ConveneError) as e:
        convene.resolve_arbiter(_DECLARED_OPUS, seats, is_ratification=False)
    assert "same model as member seat(s) ['claude-seat']" in str(e.value)


# --------------------------------------------------------------------------- #
# #302 WP-4 (design §3.5): D23 is unchanged by the support tier — codex members never arbitrate
# outside the declared rules, on every shipped profile
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("profile", sorted(p.stem for p in _REAL_PROFILES.glob("*.yaml")))
def test_302_d23_holds_on_every_profile_with_the_support_tier(profile):
    plan = convene.build_session_plan({"profile": profile, "task": "t"}, profiles_dir=_REAL_PROFILES,
                                      roster_dir=_REAL_ROSTER, session_id=f"d23-{profile}")
    arb = plan["arbiter"]
    assert "seat" not in arb and arb["is_external"] is True             # the arbiter is never a member seat
    members = {s["model"] for s in plan["seats"]}
    if arb.get("selection") == convene.DECLARED_ARBITER_SELECTION:
        # the relaxed rule: a declared arbiter's MODEL differs from every member seat's model
        assert arb["model"] not in members, (profile, arb["model"], sorted(members))
    else:
        # the provider-exclusion rule: an adversarial provider never arbitrates
        adversarial = {s["provider"] for s in plan["seats"] if s.get("adversarial_role")}
        assert arb["provider"] not in adversarial or arb["path"] == "fallback", profile
    # every supporting codex seat now serves the support tier, and still never arbitrates
    for seat in plan["seats"]:
        if seat["provider"] == "codex" and seat["seat_model_role"] == "consultant_support":
            assert seat["model"] == model_roster.CODEX_SUPPORT
            assert not (arb["provider"] == "codex" and arb.get("model") == seat["model"])
