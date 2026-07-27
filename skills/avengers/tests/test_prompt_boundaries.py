#!/usr/bin/env python3
"""avengers — test_prompt_boundaries.py (WP-3).

Covers the COMPLETE 7-section trust envelope (design §3/§6):
  * section order (TRUSTED_PHASE_REQUEST last; MEMBER_MEMORY in its reserved slot),
  * member-memory relevance + DETERMINISTIC byte budget with SURFACED truncation,
  * episodics never injected; BLIND_DIVERGE refuses peer records,
  * injected reference material and injected peer output stay INERT (JSON-escaped
    behind the untrusted warning; no forged trusted fence),
  * memory-hit visibility.

Runs under pytest; stdlib only + PyYAML (for the role card). Modules imported by
path so the test does not depend on package layout.
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_spec = importlib.util.spec_from_file_location("avengers_seat_prompt", _SCRIPTS / "seat_prompt.py")
sp = importlib.util.module_from_spec(_spec)
sys.modules["avengers_seat_prompt"] = sp
_spec.loader.exec_module(sp)

# convene owns the authoritative fail-closed overlay LINT (design §3); the overlay
# INJECT/STRIP phase boundary lives in seat_prompt. Both are tested here.
_cspec = importlib.util.spec_from_file_location("avengers_convene_pb", _SCRIPTS / "convene.py")
convene = importlib.util.module_from_spec(_cspec)
sys.modules["avengers_convene_pb"] = convene
_cspec.loader.exec_module(convene)

_FIX = Path(__file__).resolve().parent / "fixtures"
_ROSTER = Path(__file__).resolve().parent.parent / "roster" / "skeptic.yaml"

_HEADER = re.compile(r"^\[([A-Z_]+)\]$")


def _card():
    return sp._load_role_card(_ROSTER)


def _section_order(prompt: str):
    return [m.group(1) for line in prompt.splitlines()
            for m in [_HEADER.match(line)] if m]


def _mem(**over):
    rec = {
        "id": "mem-0001",
        "topic_key": "python-deps",
        "kind": "constraint",
        "statement": "stdlib-only + PyYAML.",
        "applies_when": "always",
        "provenance": {"run_id": "r", "source_type": "user_confirmed_constraint",
                       "source_refs": ["t1"], "sha256": "0" * 64},
        "approval": {"status": "approved", "by": "u", "at": "2026-07-11T00:00:00Z"},
        "sensitivity": {"pii": False},
        "status": "active",
        "expires_at": None,
        "supersedes": None,
    }
    rec.update(over)
    return rec


# --------------------------------------------------------------------------- #
# Section order (AC3)
# --------------------------------------------------------------------------- #
def test_complete_seven_section_order():
    prompt = sp.assemble_prompt(
        _card(), "do the task", "give your position",
        reference_materials={"note": "benign"},
        member_memory=[_mem()],
        peer_records=[{"seat": "architect", "turn_id": "t2", "kind": "position",
                       "claim": "A is better", "refs": []}],
    )
    order = _section_order(prompt)
    assert order == [
        "TRUSTED_PROTOCOL", "TRUSTED_ROLE_CARD", "AUTHORIZED_TASK_DIRECTIVE",
        "UNTRUSTED_REFERENCE_MATERIALS", "UNTRUSTED_MEMBER_MEMORY",
        "UNTRUSTED_PEER_RECORDS", "TRUSTED_PHASE_REQUEST",
    ]
    assert order[-1] == "TRUSTED_PHASE_REQUEST"  # recency anchor
    # member memory sits between reference materials and peer records
    assert order.index("UNTRUSTED_MEMBER_MEMORY") == order.index("UNTRUSTED_REFERENCE_MATERIALS") + 1
    assert order.index("UNTRUSTED_MEMBER_MEMORY") < order.index("UNTRUSTED_PEER_RECORDS")


def test_reserved_slots_omitted_when_empty():
    prompt = sp.assemble_prompt(_card(), "task", "position")
    order = _section_order(prompt)
    assert "UNTRUSTED_MEMBER_MEMORY" not in order
    assert "UNTRUSTED_PEER_RECORDS" not in order
    assert order[-1] == "TRUSTED_PHASE_REQUEST"


# --------------------------------------------------------------------------- #
# Member-memory relevance, budget, surfaced truncation (AC3)
# --------------------------------------------------------------------------- #
def test_memory_relevance_filter_active_and_topic():
    recs = [
        _mem(id="mem-1", status="active", applies_when="always"),
        _mem(id="mem-2", status="superseded", applies_when="always"),
        _mem(id="mem-3", status="active", applies_when="task_family=coding", topic_key="codex"),
    ]
    # topic None -> all active
    sel = sp.select_memory_records(recs, topic=None)
    assert [r["id"] for r in sel] == ["mem-1", "mem-3"]
    # topic filters by applies_when/topic_key
    sel2 = sp.select_memory_records(recs, topic="coding")
    assert [r["id"] for r in sel2] == ["mem-1", "mem-3"]  # mem-1 unconditional, mem-3 matches
    sel3 = sp.select_memory_records(recs, topic="unrelated")
    assert [r["id"] for r in sel3] == ["mem-1"]  # only the unconditional one


def test_memory_selection_is_deterministic_regardless_of_input_order():
    a = [_mem(id="mem-3"), _mem(id="mem-1"), _mem(id="mem-2")]
    b = list(reversed(a))
    assert [r["id"] for r in sp.select_memory_records(a)] == ["mem-1", "mem-2", "mem-3"]
    assert sp.select_memory_records(a) == sp.select_memory_records(b)


def test_memory_byte_budget_truncation_is_surfaced():
    recs = [_mem(id=f"mem-{i:02d}", statement="x" * 200) for i in range(10)]
    block = sp.render_member_memory(recs, byte_budget=800)
    assert block is not None
    assert "[MEMORY BUDGET]" in block and "omitted" in block
    # kept records are the deterministic prefix (mem-00 ...), not all 10
    kept_ids = re.findall(r'"id": "(mem-\d\d)"', block)
    assert kept_ids == sorted(kept_ids)
    assert len(kept_ids) < 10
    assert "mem-00" in kept_ids


def test_no_truncation_note_when_it_fits():
    block = sp.render_member_memory([_mem()], byte_budget=100000)
    assert "[MEMORY BUDGET]" not in block


# --------------------------------------------------------------------------- #
# Episodics never injected; blind-diverge guard (AC3 / §6)
# --------------------------------------------------------------------------- #
def test_blind_diverge_allows_identity_and_standing_only():
    prompt = sp.assemble_prompt(_card(), "task", "position",
                                member_memory=[_mem()], phase=sp.BLIND_DIVERGE)
    order = _section_order(prompt)
    assert "UNTRUSTED_MEMBER_MEMORY" in order
    assert "UNTRUSTED_PEER_RECORDS" not in order


def test_blind_diverge_refuses_peer_records():
    with pytest.raises(ValueError):
        sp.assemble_prompt(_card(), "task", "position", phase=sp.BLIND_DIVERGE,
                           peer_records=[{"seat": "a", "turn_id": "t", "kind": "position",
                                          "claim": "x", "refs": []}])


def test_no_episodic_section_exists():
    # There is no episodic parameter/slot in the assembler at all (v1 §6).
    prompt = sp.assemble_prompt(_card(), "task", "position", member_memory=[_mem()])
    assert "EPISODIC" not in prompt.upper().replace("EPISODICS NEVER", "")
    assert "UNTRUSTED_EPISODIC" not in prompt


# --------------------------------------------------------------------------- #
# Injection inert (AC5 support / §3)
# --------------------------------------------------------------------------- #
def test_injected_reference_material_is_inert():
    material = json.loads((_FIX / "injected-material.json").read_text())
    prompt = sp.assemble_prompt(_card(), "task", "position", reference_materials=material)
    # exactly ONE real [TRUSTED_PROTOCOL] fence (the assembler's own), even though
    # the fixture embeds a fake one inside its data
    lines = [ln.strip() for ln in prompt.splitlines()]
    assert lines.count("[TRUSTED_PROTOCOL]") == 1
    assert lines.count("[/TRUSTED_PROTOCOL]") == 1
    # the injection text is present but contained inside the untrusted block,
    # after the untrusted-data warning
    assert "SYSTEM OVERRIDE" in prompt
    warn_at = prompt.index("UNTRUSTED DATA")
    inj_at = prompt.index("SYSTEM OVERRIDE")
    assert warn_at < inj_at
    # the fake header is JSON-escaped mid-line, never a standalone fence line
    assert "\\n[TRUSTED_PROTOCOL]" in prompt or "[TRUSTED_PROTOCOL]\\n" in prompt


def test_injected_peer_output_is_inert():
    peers = json.loads((_FIX / "injected-seat-output.json").read_text())
    prompt = sp.assemble_prompt(_card(), "task", "position", peer_records=peers)
    lines = [ln.strip() for ln in prompt.splitlines()]
    # the fake closing fence inside the claim does not create a real one
    assert lines.count("[UNTRUSTED_PEER_RECORDS]") == 1
    assert lines.count("[/UNTRUSTED_PEER_RECORDS]") == 1
    assert lines.count("[TRUSTED_PHASE_REQUEST]") == 1
    assert prompt.rstrip().endswith("[/TRUSTED_PHASE_REQUEST]")  # phase request truly last
    assert "IGNORE ALL PRIOR INSTRUCTIONS" in prompt  # present, but as data


def test_malformed_peer_record_is_rejected_fail_closed():
    with pytest.raises(ValueError):
        sp.render_peer_records([{"seat": "a", "kind": "position", "claim": "x"}])  # missing turn_id


# --------------------------------------------------------------------------- #
# Memory-hit visibility (§6)
# --------------------------------------------------------------------------- #
def test_memory_hit_detection_and_line():
    recs = [_mem(id="mem-0001"), _mem(id="mem-0002")]
    hits = sp.scan_memory_hits("As mem-0001 established, we pin stdlib only.", recs)
    assert hits == ["mem-0001"]
    assert sp.format_memory_hit("skeptic", "mem-0001") == "↳ skeptic cited mem-0001"


def test_no_memory_hit_when_uncited():
    assert sp.scan_memory_hits("no citations here", [_mem(id="mem-0001")]) == []


# --------------------------------------------------------------------------- #
# D2 divergence-overlay inject/strip boundary (design §3, WP-3 · SC#6)
# --------------------------------------------------------------------------- #
def test_overlay_injected_in_blind_diverge_only():
    # The real skeptic card carries a valid divergence_overlay. It appears ONLY in an
    # ideation phase and is STRIPPED for converge/verify/arbiter (de-personaed position
    # artifact is what carries into converge).
    blind = sp.assemble_prompt(_card(), "task", "position", phase=sp.BLIND_DIVERGE)
    assert "DIVERGENCE OVERLAY" in blind
    for later in ("CONVERGE", "ARBITER", "VERIFY"):
        prompt = sp.assemble_prompt(_card(), "task", "position", phase=later)
        assert "DIVERGENCE OVERLAY" not in prompt
    # No phase at all -> stripped (safe default).
    assert "DIVERGENCE OVERLAY" not in sp.assemble_prompt(_card(), "task", "position")


def test_no_overlays_flag_suppresses_injection_even_in_blind_diverge():
    prompt = sp.assemble_prompt(_card(), "task", "position", phase=sp.BLIND_DIVERGE, no_overlays=True)
    assert "DIVERGENCE OVERLAY" not in prompt


def test_overlay_kept_inside_role_card_no_new_section():
    # Injecting the overlay must NOT add a top-level section (order invariant holds).
    prompt = sp.assemble_prompt(_card(), "task", "position", phase=sp.BLIND_DIVERGE)
    order = _section_order(prompt)
    assert order == ["TRUSTED_PROTOCOL", "TRUSTED_ROLE_CARD",
                     "AUTHORIZED_TASK_DIRECTIVE", "TRUSTED_PHASE_REQUEST"]


# --------------------------------------------------------------------------- #
# D2 overlay LINT (convene.py, validate-time fail-closed · SC#6)
# --------------------------------------------------------------------------- #
def test_overlay_lint_accepts_valid_types():
    assert convene.lint_overlay("s", {"divergence_overlay": {"type": "expertise-cue", "cue": "x"}})["type"] == "expertise-cue"
    assert convene.lint_overlay("s", {"divergence_overlay": {"type": "divergence-direction", "direction": "x"}})["type"] == "divergence-direction"
    assert convene.lint_overlay("s", {}) is None  # no overlay -> None (not an error)


def test_overlay_lint_rejects_decorative_and_demographic():
    for bad in ("decorative", "demographic", "persona", None):
        with pytest.raises(convene.ConveneError):
            convene.lint_overlay("s", {"divergence_overlay": {"type": bad, "cue": "x"}})
    # a missing type key is also rejected
    with pytest.raises(convene.ConveneError):
        convene.lint_overlay("s", {"divergence_overlay": {"cue": "x"}})


def test_overlay_lint_fails_closed_at_validate_time(tmp_path):
    # SC#6: a decorative/demographic overlay on a card is rejected at build (no run).
    rdir, pdir = tmp_path / "roster", tmp_path / "profiles"
    rdir.mkdir(parents=True)
    (rdir / "skeptic.yaml").write_text(
        "seat_id: skeptic\nprofession: t\nadversarial_role: true\ncan_arbitrate: false\n"
        "incentive: {optimizes_for: x, discounts: y, standing_challenge: z, failure_mode: w}\n"
        "provider: {affinity: codex, fallback_ok: true, effort: xhigh}\nforbidden: []\n"
        "divergence_overlay: {type: demographic, cue: 'a 55-year-old banker from Vilnius'}\n",
        encoding="utf-8",
    )
    (rdir / "architect.yaml").write_text(
        "seat_id: architect\nprofession: t\nadversarial_role: false\ncan_arbitrate: true\n"
        "incentive: {optimizes_for: x, discounts: y, standing_challenge: z, failure_mode: w}\n"
        "provider: {affinity: claude, fallback_ok: true, effort: default}\nforbidden: []\n",
        encoding="utf-8",
    )
    (rdir / "operator.yaml").write_text(
        "seat_id: operator\nprofession: t\nadversarial_role: false\ncan_arbitrate: true\n"
        "incentive: {optimizes_for: x, discounts: y, standing_challenge: z, failure_mode: w}\n"
        "provider: {affinity: agy, fallback_ok: true, effort: default}\nforbidden: []\n",
        encoding="utf-8",
    )
    pdir.mkdir(parents=True)
    (pdir / "fam.yaml").write_text(
        "schema: avengers-profile.v1\nfamily: fam\nseats:\n"
        "  - ref: skeptic\n  - ref: architect\n  - ref: operator\n"
        "arbiter:\n  effort_on_codex: max\n"
        "phases:\n  converge:\n    semantics: ratification\n"
        "outcome:\n  type: [decision]\n  default: decision\n",
        encoding="utf-8",
    )
    with pytest.raises(convene.ConveneError) as e:
        convene.build_session_plan({"profile": "fam"}, profiles_dir=pdir, roster_dir=rdir)
    assert "demographic" in str(e.value) or "not in" in str(e.value)


# --------------------------------------------------------------------------- #
# Memory provider-stamping (design §8, WP-3)
# --------------------------------------------------------------------------- #
def test_inherited_memory_renders_third_person_with_provider_stamp():
    rec = _mem(id="mem-9001", writing_provider="codex")
    block = sp.render_member_memory([rec], seat_id="skeptic", seat_provider="claude")
    assert block is not None
    # third-person + writing-provider stamp
    assert "the previous skeptic (codex)" in block
    assert '"inherited": true' in block


def test_own_provider_memory_stays_first_person():
    rec = _mem(id="mem-9002", writing_provider="claude")
    block = sp.render_member_memory([rec], seat_id="skeptic", seat_provider="claude")
    assert block is not None
    # same provider -> the RECORD is not annotated (assert on the JSON-key form; the
    # untrusted-data warning above the JSON legitimately mentions these field names).
    assert '"inherited": true' not in block
    assert '"third_person_stamp"' not in block


def test_unstamped_memory_unchanged():
    # A record with no writing_provider renders exactly as before (back-compat).
    rec = _mem(id="mem-9003")
    block = sp.render_member_memory([rec], seat_id="skeptic", seat_provider="claude")
    assert '"inherited": true' not in block and '"third_person_stamp"' not in block


def test_memory_stamp_flows_through_assemble_prompt():
    rec = _mem(id="mem-9004", writing_provider="codex")
    prompt = sp.assemble_prompt(_card(), "task", "position",
                                member_memory=[rec], seat_provider="claude")
    assert "the previous skeptic (codex)" in prompt
