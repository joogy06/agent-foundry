"""test_roundtrip_and_gold — end-to-end ingest->query->render + the gold accuracy gate.

Exercises the full deterministic pipeline on the PAYROLL.cbl fixture using the
hand-authored finding (the LLM-as-parser stand-in from conftest), then:
  - redact must scrub the embedded CONNECT credential before store,
  - emit_index must force the dynamic CALL occurrence to speculative,
  - store/promote must land the catalog,
  - query must answer defs/refs/impact correctly,
  - render must produce a navigator + exports,
  - goldcheck must compute call-edge precision/recall against gold/cobol/sample.gold.json,
  - precision must clear 0.85 (the vertical-slice acceptance), flipping impact() to
    authoritative.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_ROOT / "scripts"
GOLD = SKILL_ROOT / "gold" / "cobol" / "sample.gold.json"
sys.path.insert(0, str(SCRIPTS))

import accumulate as ac  # noqa: E402
import emit_index as ei  # noqa: E402
import goldcheck as gc  # noqa: E402
import query as q  # noqa: E402
import redact as rd  # noqa: E402
import render_navigator as rn  # noqa: E402
import store as st  # noqa: E402


def _full_ingest(store_root, finding, sha, payroll_path):
    """Run finding -> accumulate -> emit -> redact -> store/promote. Returns (root, index)."""
    # accumulate (single chunk -> rollup)
    summary = {
        "symbols": ac.merge_symbols([finding]),
        "occurrences": ac.merge_occurrences([finding]),
        "relationships": ac.merge_relationships([finding], 50)[0],
        "gaps": finding["gaps"],
    }
    index = ei.emit_index(
        summary, content_sha256=sha, fmt="cobol",
        source_path=str(payroll_path), line_count=62,
        model_id="test-llm", prompt_hash="a" * 64, pipeline_fingerprint="b" * 64, validate=True,
    )
    # redact (fail-closed) BEFORE store
    redacted = rd.redact_index(index)
    root = st.resolve_store_root(str(store_root))
    st.persist(root, redacted)
    return root, redacted


def test_credential_scrubbed_before_store(store_root, payroll_finding_fixture, payroll_sha, payroll_path):
    root, redacted = _full_ingest(store_root, payroll_finding_fixture, payroll_sha, payroll_path)
    # The stored catalog must not contain the plaintext password anywhere.
    cat_text = (root / "catalog" / "latest.json").read_text(encoding="utf-8")
    assert "sup3rs3cr3tpw" not in cat_text, "credential leaked into the stored catalog!"
    assert redacted["redaction_count"] >= 1


def test_dynamic_call_is_speculative_in_store(store_root, payroll_finding_fixture, payroll_sha, payroll_path):
    root, redacted = _full_ingest(store_root, payroll_finding_fixture, payroll_sha, payroll_path)
    dyn = [o for o in redacted["occurrences"]
           if o["symbol_id"].endswith("#sym/PAYROLL/dyn/WS-PROGRAM-NAME")]
    assert dyn and dyn[0]["confidence"] == "speculative"


def test_query_defs_refs_impact(store_root, payroll_finding_fixture, payroll_sha, payroll_path):
    root, _ = _full_ingest(store_root, payroll_finding_fixture, payroll_sha, payroll_path)
    catalog = q.load_catalog(root)
    index = q.build_symbol_index(catalog)

    # defs: 2100-COMPUTE-PAY is defined once
    d = q.op_defs(catalog, index, "2100-COMPUTE-PAY")
    assert d["anchor_found"] and d["occurrence_count"] == 1

    # impact from MAIN reaches the whole transitive call chain
    im = q.op_impact(catalog, index, "0000-MAIN-CONTROL", max_depth=5)
    assert im["anchor_found"]
    # MAIN -> {1000,2000,9000}; 1000 -> 1100; 2000 -> 2100; 2100 -> {TAXCALC, 2200}; 2200 -> WS-PROGRAM-NAME
    assert im["edge_count"] >= 7

    # list_artifacts
    la = q.op_list_artifacts(catalog, index)
    assert la["artifact_count"] == 1


def test_navigator_and_exports_rendered(store_base, payroll_finding_fixture, payroll_sha, payroll_path):
    root, _ = _full_ingest(store_base / "codelib", payroll_finding_fixture, payroll_sha, payroll_path)
    catalog = rn.load_catalog(root)
    out = store_base / "nav"
    res = rn.render_navigator(catalog, out, no_vendor=True, store_label="payroll-test")
    assert (out / "navigator.html").is_file()
    for f in ["symbols.csv", "occurrences.csv", "relationships.csv", "index.ndjson"]:
        assert (out / f).is_file(), f
    # navigator must not leak the credential either
    assert "sup3rs3cr3tpw" not in (out / "navigator.html").read_text(encoding="utf-8")


def test_gold_precision_clears_threshold(store_root, payroll_finding_fixture, payroll_sha, payroll_path):
    """The vertical-slice acceptance (design §8): COBOL gold call-edge precision must
    clear 0.85 on the fixture, and recording it must flip impact() to authoritative."""
    root, redacted = _full_ingest(store_root, payroll_finding_fixture, payroll_sha, payroll_path)
    gold = json.loads(GOLD.read_text(encoding="utf-8"))

    result = gc.score(redacted, gold)
    # The hand-authored extraction encodes exactly the gold call-edges, so precision
    # AND recall should be perfect (1.0) on the fixture.
    assert result["precision"] is not None
    assert result["precision"] >= 0.85, f"COBOL gold precision {result['precision']} below 0.85"
    assert result["recall"] is not None and result["recall"] >= 0.85
    assert result["correct_edges"] == result["gold_edges"]  # all gold edges found

    # Record it and confirm impact() flips advisory -> authoritative.
    gc.score(redacted, gold)
    st.set_accuracy(root, "cobol", precision=result["precision"], recall=result["recall"],
                    gold_program="PAYROLL", precision_threshold=0.85)
    catalog = q.load_catalog(root)
    index = q.build_symbol_index(catalog)
    im = q.op_impact(catalog, index, "0000-MAIN-CONTROL")
    assert im["advisory"] is False, "after gold precision >= 0.85, impact() must be authoritative"


def test_full_pipeline_deterministic(store_base, payroll_finding_fixture, payroll_sha, payroll_path):
    """Two independent full ingests of the same fixture produce identical catalog bodies
    and identical navigators (HARD-RULE 3)."""
    r1, _ = _full_ingest(store_base / "s1", payroll_finding_fixture, payroll_sha, payroll_path)
    r2, _ = _full_ingest(store_base / "s2", payroll_finding_fixture, payroll_sha, payroll_path)
    c1 = json.loads((r1 / "catalog" / "latest.json").read_text(encoding="utf-8"))
    c2 = json.loads((r2 / "catalog" / "latest.json").read_text(encoding="utf-8"))
    body1 = {k: c1[k] for k in ("artifacts", "symbols", "occurrences", "relationships", "refs")}
    body2 = {k: c2[k] for k in ("artifacts", "symbols", "occurrences", "relationships", "refs")}
    assert json.dumps(body1, sort_keys=True) == json.dumps(body2, sort_keys=True)

    n1 = store_base / "n1"
    n2 = store_base / "n2"
    rn.render_navigator(c1, n1, no_vendor=True, store_label="d")
    rn.render_navigator(c2, n2, no_vendor=True, store_label="d")
    assert (n1 / "navigator.html").read_text() == (n2 / "navigator.html").read_text()
