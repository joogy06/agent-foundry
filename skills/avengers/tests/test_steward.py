#!/usr/bin/env python3
"""avengers — test_steward.py (WP-3).

The steward principal-proxy seat (design §5): roster wiring, resolver integration
(missing-provider fail-closed), the coding-ratification 4-seat + external-arbiter
resolution, and the intent-artifact reader (trust-class, forward-compatible parsing,
provisional-extract-and-flag) + the converge intent-alignment assessment (push-on-drift
trip-wire; escalate-missing-as-confirm). Proves success criterion #4 + the §5 wiring.

Runs under pytest; stdlib + PyYAML only. Modules imported by path.
"""
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_REAL_PROFILES = _ROOT / "profiles"
_REAL_ROSTER = _ROOT / "roster"


def _load(mod_name, rel):
    spec = importlib.util.spec_from_file_location(mod_name, _ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


convene = _load("avengers_convene_stw", "scripts/convene.py")
sp = _load("avengers_seat_prompt_stw", "scripts/seat_prompt.py")


# --------------------------------------------------------------------------- #
# Roster card wiring (design §5)
# --------------------------------------------------------------------------- #
def test_steward_card_wiring():
    card = yaml.safe_load((_REAL_ROSTER / "steward.yaml").read_text(encoding="utf-8"))
    assert card["seat_id"] == "steward"
    assert card["adversarial_role"] is False
    # can_arbitrate is documentary/inert under v2, but must not be true.
    assert card.get("can_arbitrate", False) is False
    prov = card["provider"]
    assert prov["affinity"] == "agy"
    assert prov["fallback_ok"] is True
    assert prov["effort"] == "default"


def test_steward_missing_provider_fails_closed(tmp_path):
    # A steward card with NO provider block -> affinity None -> resolve_seats
    # ConveneError (design §5 wiring proven).
    rdir = tmp_path / "roster"
    rdir.mkdir()
    (rdir / "steward.yaml").write_text(
        "seat_id: steward\nprofession: proxy\nadversarial_role: false\n"
        "incentive: {optimizes_for: x, discounts: y, standing_challenge: z, failure_mode: w}\n"
        "forbidden: []\n",  # NOTE: no provider block
        encoding="utf-8",
    )
    profile = {"seats": [{"ref": "steward"}]}
    with pytest.raises(convene.ConveneError) as e:
        convene.resolve_seats(profile, rdir)
    assert "provider" in str(e.value)


# --------------------------------------------------------------------------- #
# coding-ratification: 4 deliberation seats + external arbiter, steward never arbiter
# --------------------------------------------------------------------------- #
def test_coding_ratification_four_seats_and_external_arbiter():
    plan = convene.build_session_plan(
        {"profile": "coding-ratification", "task": "t"},
        profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER, session_id="stw-1",
    )
    seat_ids = [s["seat_id"] for s in plan["seats"]]
    assert seat_ids == ["skeptic", "architect", "operator", "steward"]
    assert plan["quorum"]["member_seats"] == 4
    assert plan["budgets"]["max_seat_calls"] == 13
    steward = next(s for s in plan["seats"] if s["seat_id"] == "steward")
    assert steward["provider"] == "agy"
    assert steward["adversarial_role"] is False
    # NEVER selected as arbiter: the arbiter is a fresh EXTERNAL seatless call (no seat).
    arb = plan["arbiter"]
    assert arb["is_external"] is True and "seat" not in arb
    assert arb["provider"] == "claude"          # strongest non-adversarial prior
    assert arb["path"] == "fallback"
    assert convene.schema_validate(plan, convene.load_schema()) == []


def test_coding_ratification_dry_run_clean():
    # WP-3 leaves the profile dry-run-clean (WP-5 does the final capstone).
    plan = convene.build_session_plan(
        {"profile": "coding-ratification", "task": "t"},
        profiles_dir=_REAL_PROFILES, roster_dir=_REAL_ROSTER,
    )
    review = convene.render_pre_spend_review(plan)
    assert "4 member seats" in review
    assert "steward" in review
    # ~13 calls so no phase is truncated (4 diverge + 4 cross-exam + 4 converge + 1 arb).
    est = convene.estimate(plan)
    assert est["planned_calls"] == 13 and est["call_ceiling"] == 13


# --------------------------------------------------------------------------- #
# intent.md trust-class (design §5)
# --------------------------------------------------------------------------- #
def test_intent_trust_convene_supplied_is_trusted(tmp_path):
    f = tmp_path / "intent.md"
    f.write_text("# Desired outcome\nShip it.\n", encoding="utf-8")
    # convene-supplied path -> trusted regardless of location.
    res = sp.read_intent(f, convene_supplied=True, project_root=tmp_path, home=tmp_path / "nope")
    assert res["trust_class"] == sp.INTENT_TRUSTED
    assert res["flags"] == []
    assert res["sections"]["desired_outcome"] == "Ship it."


def test_intent_trust_home_tier_is_trusted(tmp_path):
    home = tmp_path / "home"
    (home).mkdir()
    f = home / "intent.md"
    f.write_text("# Outcome\nHome-authored.\n", encoding="utf-8")
    res = sp.read_intent(f, convene_supplied=False, project_root=tmp_path / "repo", home=home)
    assert res["trust_class"] == sp.INTENT_TRUSTED
    assert res["flags"] == []


def test_intent_trust_repo_only_is_untrusted_and_flagged(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    f = repo / "intent.md"
    f.write_text("# Outcome\nRepo-committed (PR-editable).\n", encoding="utf-8")
    res = sp.read_intent(f, convene_supplied=False, project_root=repo, home=tmp_path / "elsewhere")
    assert res["trust_class"] == sp.INTENT_UNTRUSTED
    assert "unverified intent source — confirm" in res["flags"]


def test_intent_provisional_extract_and_flag():
    # No path -> provisional intent extracted from the ask + the inferred-intent flag.
    res = sp.read_intent(None, original_ask="Lower the default effort without losing quality.")
    assert res["trust_class"] == sp.INTENT_PROVISIONAL
    assert res["provisional"] is True
    assert "operating on inferred intent — confirm" in res["flags"]
    assert res["sections"]["desired_outcome"] == "Lower the default effort without losing quality."


def test_intent_parsing_is_forward_compatible():
    # Unknown headings (the deferred autonomy charter) are IGNORED, not rejected.
    text = (
        "# Desired outcome\nShip a bounded review.\n\n"
        "# May-decide\nSwap challenger provider within policy.\n\n"
        "# Acceptable-tradeoffs\nA little latency.\n"
    )
    parsed = sp.parse_intent_markdown(text)
    assert parsed["sections"]["desired_outcome"] == "Ship a bounded review."
    # charter sections land in additional_sections (kept, not rejected)
    assert "May-decide" in parsed["additional_sections"]
    assert "Acceptable-tradeoffs" in parsed["additional_sections"]


# --------------------------------------------------------------------------- #
# Converge intent-alignment assessment (design §5) — SC#4 push-on-drift
# --------------------------------------------------------------------------- #
def test_alignment_pushes_on_planted_drift_producing_trip_wire():
    intent = sp.read_intent(None, original_ask="Do NOT touch the interactive session model.")
    # Add an explicit non_goals item so we have >1 checkable item.
    intent["sections"]["non_goals"] = "Do not touch the interactive session model."
    items = sp.intent_items(intent)
    # deliberation drifted on the non_goals item (planted drift).
    findings = {"non_goals": {"aligned": False}, "desired_outcome": {"aligned": True}}
    result = sp.assess_intent_alignment(items, findings)
    by_id = {a["id"]: a["status"] for a in result["assessment"]}
    assert by_id["non_goals"] == "fail"
    assert by_id["desired_outcome"] == "pass"
    assert any("non_goals" in tw and "drifted" in tw for tw in result["trip_wires"])


def test_alignment_escalates_missing_item_as_confirm_not_invent():
    intent = sp.read_intent(None, original_ask="Ship the outcome.")
    intent["sections"]["standards"] = "Meets the sol benchmark quality ceiling."
    items = sp.intent_items(intent)
    # no finding at all for `standards` -> unknown -> confirm flag (do NOT invent a pass).
    findings = {"desired_outcome": True}
    result = sp.assess_intent_alignment(items, findings)
    by_id = {a["id"]: a["status"] for a in result["assessment"]}
    assert by_id["standards"] == "unknown"
    assert any("standards" in fl and "confirm" in fl for fl in result["flags"])
    assert result["summary"] == {"pass": 1, "fail": 0, "unknown": 1}
