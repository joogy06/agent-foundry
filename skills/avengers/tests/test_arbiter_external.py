#!/usr/bin/env python3
"""avengers — test_arbiter_external.py (WP-2, design §4).

Focused coverage for the EXTERNAL, SEATLESS, cold-context arbiter — the
highest-value v2 fix (the participant-judge violation). Complements the
resolver-integration tests in test_convene.py:

  * CLEAN path — arbiter provider used by NO deliberation seat (total exclusion,
    no residual).
  * FALLBACK path — all providers deliberated (coding-ratification always lands
    here): the strongest-adjudication-prior NON-adversarial provider, cold-context,
    with the ACCEPTED style-recognition residual FLAGGED (fallback_arbiter_residual)
    in run-record.json (§6a).
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
    # codex(adv) + claude seats -> agy unused -> clean arbiter on agy (only candidate).
    seats = [_seat("codex", True), _seat("claude", False), _seat("claude", False)]
    arb = convene.resolve_arbiter({}, seats, is_ratification=True)
    assert arb["path"] == "clean"
    assert arb["provider"] == "agy"
    assert arb["fallback_arbiter_residual"] is False


# --------------------------------------------------------------------------- #
# FALLBACK path — all providers deliberated (the coding-ratification reality)
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
    # If claude is the adversary, the fallback picks the next non-adversarial prior
    # (agy 2 > codex 1) among {codex, agy}.
    seats = [_seat("claude", True), _seat("codex", False), _seat("agy", False)]
    arb = convene.resolve_arbiter({}, seats, is_ratification=True)
    assert arb["path"] == "fallback"
    assert arb["provider"] == "agy"


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
    (tmp_path / "priors.yaml").write_text(
        "schema: avengers-capability-priors.v1\n"
        "adjudication_prior: {agy: 9, claude: 1, codex: 1}\n",
        encoding="utf-8",
    )
    priors = convene.load_capability_priors(tmp_path / "priors.yaml")
    seats = [_seat("codex", True), _seat("claude", False), _seat("agy", False)]
    arb = convene.resolve_arbiter({}, seats, is_ratification=True, priors=priors)
    assert arb["path"] == "fallback"
    assert arb["provider"] == "agy"          # DATA-driven, overrides the builtin claude>agy
