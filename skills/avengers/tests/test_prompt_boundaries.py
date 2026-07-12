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
