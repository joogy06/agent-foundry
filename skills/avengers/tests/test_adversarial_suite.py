#!/usr/bin/env python3
"""avengers — test_adversarial_suite.py (WP-5).

The consolidated §12.5 adversarial-fixture suite (v1 success criterion #5). One
runnable place that proves the four shipped fixtures behave:

  1. injected reference material  -> INERT (no forged trusted fence),
  2. injected seat output         -> INERT (no forged closing/phase fence),
  3. pre-poisoned repo-local memory -> NOT loaded (home-tier only),
  4. FALSE FLAG                   -> no code path auto-discounts an honest peer;
                                     adjudication is reserved to the chair.

Honest scope (design §3): these are PARSER-INTEGRITY + admissibility controls plus
the false-flag deterministic guard. Semantic injection (persuasive text inside
valid data) has a real residual; the false-flag ADJUDICATION itself is an LLM-chair
judgment and cannot be unit-tested — what IS tested here is that the deterministic
layer never pre-empts that judgment by silently dropping/discounting a seat.

Runs under pytest; stdlib only (+ PyYAML for the role card). Modules imported by
path so the test does not depend on package layout.
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parent / "scripts"
_FIX = _HERE / "fixtures"
_ROSTER = _HERE.parent / "roster" / "skeptic.yaml"


def _load(mod_name, filename):
    spec = importlib.util.spec_from_file_location(mod_name, _SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


sp = _load("avengers_seat_prompt", "seat_prompt.py")
mw = _load("avengers_memory_writeback", "memory_writeback.py")


def _card():
    return sp._load_role_card(_ROSTER)


# --------------------------------------------------------------------------- #
# 1. Injected reference material stays inert (§3)
# --------------------------------------------------------------------------- #
def test_injected_reference_material_inert_and_flagged():
    material = json.loads((_FIX / "injected-material.json").read_text())
    prompt = sp.assemble_prompt(_card(), "task", "position", reference_materials=material)
    lines = [ln.strip() for ln in prompt.splitlines()]
    # exactly ONE real protocol fence — the fixture's embedded fake one is escaped data
    assert lines.count("[TRUSTED_PROTOCOL]") == 1
    assert lines.count("[/TRUSTED_PROTOCOL]") == 1
    # the injection is present but AFTER the untrusted-data warning (flagged, contained)
    assert "SYSTEM OVERRIDE" in prompt
    assert prompt.index("UNTRUSTED DATA") < prompt.index("SYSTEM OVERRIDE")
    assert prompt.rstrip().endswith("[/TRUSTED_PHASE_REQUEST]")  # recency anchor intact


# --------------------------------------------------------------------------- #
# 2. Injected seat output stays inert (§3)
# --------------------------------------------------------------------------- #
def test_injected_seat_output_inert():
    peers = json.loads((_FIX / "injected-seat-output.json").read_text())
    prompt = sp.assemble_prompt(_card(), "task", "position", peer_records=peers)
    lines = [ln.strip() for ln in prompt.splitlines()]
    assert lines.count("[UNTRUSTED_PEER_RECORDS]") == 1
    assert lines.count("[/UNTRUSTED_PEER_RECORDS]") == 1
    assert lines.count("[TRUSTED_PHASE_REQUEST]") == 1
    assert prompt.rstrip().endswith("[/TRUSTED_PHASE_REQUEST]")
    assert "IGNORE ALL PRIOR INSTRUCTIONS" in prompt  # present, but as data


# --------------------------------------------------------------------------- #
# 3. Pre-poisoned repo-local memory is NOT loaded (§5/§6/§14)
# --------------------------------------------------------------------------- #
def test_pre_poisoned_repo_local_memory_not_loaded(tmp_path, monkeypatch):
    home = tmp_path / "home-claude-projects"
    home.mkdir()
    monkeypatch.setenv("AVENGERS_PROJECTS_ROOT", str(home))
    project_root = tmp_path / "repo"
    project_root.mkdir()
    poison = json.loads((_FIX / "poisoned-standing.json").read_text())
    # plant repo-local poison where a NAIVE loader might look
    for rel in [".avengers/members/skeptic/standing.json",
                "avengers/members/skeptic/standing.json"]:
        p = project_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(poison))
    # home tier empty -> loader returns nothing; the repo poison is never read
    assert mw.load_standing_memory(project_root, "skeptic") == []


# --------------------------------------------------------------------------- #
# 4. False flag: no deterministic auto-discount of an honest peer (§3/§12.5)
# --------------------------------------------------------------------------- #
def _false_flag_records():
    return json.loads((_FIX / "false-flag.json").read_text())["records"]


def test_false_flag_does_not_drop_the_honest_peer():
    records = _false_flag_records()
    block = sp.render_peer_records(records)
    assert block is not None
    payload = json.loads(block.split("```json\n", 1)[1].rsplit("\n```", 1)[0])
    seats = [r["seat"] for r in payload]
    # BOTH the honest peer and the false-flagger survive — the code does not act on
    # the accusation by silently discounting/dropping the honest architect.
    assert "architect" in seats, "honest peer must NOT be auto-discounted by the code"
    assert "operator" in seats, "the false-flag record is surfaced (as data) for the chair"
    assert len(payload) == 2


def test_false_flag_accusation_is_inert_data_behind_the_warning():
    records = _false_flag_records()
    prompt = sp.assemble_prompt(_card(), "task", "give your position", peer_records=records)
    # the false accusation is present, but only inside the untrusted block, after the
    # untrusted-data warning — never a trusted instruction the seat must obey.
    assert "treat its position as compromised" in prompt
    warn_at = prompt.index("UNTRUSTED DATA: peer positions")
    accusation_at = prompt.index("treat its position as compromised")
    assert warn_at < accusation_at
    # the honest, sourced claim survives verbatim (not discounted)
    assert "the dual-write window is where data loss happens" in prompt
    # recency anchor: the trusted phase request is still last
    assert prompt.rstrip().endswith("[/TRUSTED_PHASE_REQUEST]")


def test_no_auto_discount_mechanism_exists_in_the_assembler():
    # Prove-the-absence: there is no function/param that discounts or drops a seat
    # based on an injection flag. Adjudication is the chair's (prose), not code's.
    public = {n for n in dir(sp) if not n.startswith("_")}
    for banned in ("discount_seat", "drop_seat", "auto_discount", "silence_seat"):
        assert banned not in public
    # render_peer_records is order-preserving and total over valid records
    recs = _false_flag_records()
    block = sp.render_peer_records(recs)
    order = re.findall(r'"turn_id":\s*"(t\d+)"', block)
    assert order == ["t0007", "t0008"]  # honest first, false-flag second; nothing removed


def test_false_flag_malformed_record_still_fails_closed():
    # A false-flagger cannot smuggle a record past schema extraction (fail-closed).
    with pytest.raises(ValueError):
        sp.render_peer_records([{"seat": "operator", "kind": "challenge",
                                 "claim": "drop architect"}])  # missing turn_id
