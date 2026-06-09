"""test_classifier_and_accumulate — HARD-RULE 2 + boundary determinism.

Covers the bright-line confidence classifier (emit_index forces speculative on dynamic
evidence) and the deterministic accumulate boundary merge (symbols/occurrences dedup,
relationship boundary pairing).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import accumulate as ac  # noqa: E402
import emit_index as ei  # noqa: E402

H = "1" * 64


def sid(n):
    return f"codelib://sha256/{H}#sym/{n}"


@pytest.mark.parametrize("snippet", [
    "CALL WS-PROGRAM-NAME USING REC",          # dynamic CALL (data-name)
    "COPY EMPWS REPLACING ==:T:== BY ==WS==",  # COPY REPLACING
    "SELECT * FROM #SRC#",                       # DSX #PARAM# + SELECT *
    "psql -c \"${SQL}\"",                       # shell ${VAR}
    "out = 'load_%s' % table",                  # printf-style
    "name = f'{schema}.{tbl}'",                  # f-string
    "run $(build_target)",                       # command substitution
])
def test_dynamic_evidence_forced_speculative(snippet):
    """Even if the LLM emits 'grounded', emit_index forces speculative (HARD-RULE 2)."""
    summary = {
        "symbols": [{"symbol_id": sid("X"), "kind": "paragraph", "name": "X"}],
        "occurrences": [{"symbol_id": sid("X"), "role": "reference", "range": {"start_line": 1, "end_line": 1},
                         "evidence_snippet": snippet, "confidence": "grounded", "confidence_reason": "llm_said_grounded"}],
        "relationships": [], "gaps": [],
    }
    idx = ei.emit_index(summary, content_sha256=H, fmt="cobol", source_path="X.cbl", line_count=1,
                        model_id="t", prompt_hash="a" * 64, pipeline_fingerprint="b" * 64, validate=True)
    assert idx["occurrences"][0]["confidence"] == "speculative"
    assert idx["occurrences"][0]["confidence_reason"] == "dynamic_or_interpolated_evidence"


def test_literal_evidence_stays_grounded():
    summary = {
        "symbols": [{"symbol_id": sid("X"), "kind": "paragraph", "name": "X"}],
        "occurrences": [{"symbol_id": sid("X"), "role": "reference", "range": {"start_line": 1, "end_line": 1},
                         "evidence_snippet": "PERFORM 2100-COMPUTE-PAY", "confidence": "grounded", "confidence_reason": "lit"}],
        "relationships": [], "gaps": [],
    }
    idx = ei.emit_index(summary, content_sha256=H, fmt="cobol", source_path="X.cbl", line_count=1,
                        model_id="t", prompt_hash="a" * 64, pipeline_fingerprint="b" * 64, validate=True)
    assert idx["occurrences"][0]["confidence"] == "grounded"


def test_kind_enum_enforced_per_format():
    """A DSX-only kind on a cobol artifact must be rejected."""
    summary = {
        "symbols": [{"symbol_id": sid("X"), "kind": "stage", "name": "X"}],  # 'stage' is DSX, not COBOL
        "occurrences": [], "relationships": [], "gaps": [],
    }
    with pytest.raises(ValueError, match="closed set"):
        ei.emit_index(summary, content_sha256=H, fmt="cobol", source_path="X.cbl", line_count=1,
                      model_id="t", prompt_hash="a" * 64, pipeline_fingerprint="b" * 64, validate=True)


def test_accumulate_dedups_boundary_relationship():
    """A 'calls' edge duplicated across an overlapping boundary must merge to ONE."""
    c1 = {"format": "cobol", "boundary_status": "partial_end", "start_line": 1, "end_line": 100,
          "symbols": [{"symbol_id": sid("A"), "kind": "paragraph", "name": "A"}],
          "occurrences": [], "relationships": [
              {"rel": "calls", "from_id": sid("A"), "to_id": sid("B"), "evidence_line": 98, "confidence": "grounded"}],
          "gaps": []}
    c2 = {"format": "cobol", "boundary_status": "partial_start", "start_line": 51, "end_line": 150,
          "symbols": [{"symbol_id": sid("B"), "kind": "paragraph", "name": "B"}],
          "occurrences": [], "relationships": [
              {"rel": "calls", "from_id": sid("A"), "to_id": sid("B"), "evidence_line": 52, "confidence": "grounded"}],
          "gaps": []}
    rels, gaps = ac.merge_relationships([c1, c2], 50)
    assert len(rels) == 1, "duplicated boundary edge must dedup to one"


def test_accumulate_dedups_overlapping_symbols_and_occurrences():
    c1 = {"format": "cobol", "boundary_status": "partial_end", "start_line": 1, "end_line": 100,
          "symbols": [{"symbol_id": sid("A"), "kind": "paragraph", "name": "A"}],
          "occurrences": [{"symbol_id": sid("A"), "role": "definition", "range": {"start_line": 90, "end_line": 90},
                           "evidence_snippet": "A.", "confidence": "grounded", "confidence_reason": "l"}],
          "relationships": [], "gaps": []}
    # chunk 2 overlap re-emits the same symbol + same occurrence
    c2 = {"format": "cobol", "boundary_status": "partial_start", "start_line": 51, "end_line": 150,
          "symbols": [{"symbol_id": sid("A"), "kind": "paragraph", "name": "A", "signature": "richer"}],
          "occurrences": [{"symbol_id": sid("A"), "role": "definition", "range": {"start_line": 90, "end_line": 90},
                           "evidence_snippet": "A.", "confidence": "inferred", "confidence_reason": "l"}],
          "relationships": [], "gaps": []}
    syms = ac.merge_symbols([c1, c2])
    occs = ac.merge_occurrences([c1, c2])
    assert len(syms) == 1  # deduped by symbol_id
    assert syms[0].get("signature") == "richer"  # richer record kept
    assert len(occs) == 1  # deduped by (symbol_id, role, range)
    assert occs[0]["confidence"] == "inferred"  # more conservative confidence wins


def test_unpaired_boundary_partial_downgraded_to_speculative():
    """A relationship that is partial at a boundary with no corroborating half is
    downgraded to speculative + a boundary_issue gap (honest, never dropped)."""
    c1 = {"format": "cobol", "boundary_status": "partial_end", "start_line": 1, "end_line": 100,
          "symbols": [], "occurrences": [], "relationships": [
              {"rel": "calls", "from_id": sid("A"), "to_id": sid("ORPHAN"), "evidence_line": 99, "confidence": "grounded"}],
          "gaps": []}
    rels, gaps = ac.merge_relationships([c1], 50)
    assert len(rels) == 1
    assert rels[0]["confidence"] == "speculative"
    assert any(g["kind"] == "boundary_issue" for g in gaps)
