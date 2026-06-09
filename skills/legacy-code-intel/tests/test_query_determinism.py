"""test_query_determinism — ANTI-REQUIREMENT #3 (design §10).

The discarded agy build re-rolled BFS, byte-sliced markdown for its "token budget",
and never sorted edges — so two runs produced different bytes. query.py ports the
graph_ops.py shape (adjacency index built once, stable edge sort, real budget) and
emits canonical JSON. This test asserts two runs of every op over the same catalog are
BYTE-IDENTICAL, that impact() is hop-bounded + advisory-by-default, and that the budget
is a real edge cap (not a byte slice).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import emit_index as ei  # noqa: E402
import query as q  # noqa: E402
import store as st  # noqa: E402


def _seed_catalog(root) -> dict:
    """A chain MAIN->A->B->C plus a couple of side edges, for determinism + budget."""
    sha = "1" * 64
    fp = "b" * 64

    def sid(n):
        return f"codelib://sha256/{sha}#sym/{n}"

    names = ["MAIN", "A", "B", "C", "D"]
    symbols = [{"symbol_id": sid(f"P/{n}"), "kind": "paragraph", "name": n} for n in names]
    occ = [{"symbol_id": sid(f"P/{n}"), "role": "definition", "range": {"start_line": 10 + i, "end_line": 10 + i},
            "evidence_snippet": f"{n}.", "confidence": "grounded", "confidence_reason": "lit"}
           for i, n in enumerate(names)]
    rels = [
        {"rel": "calls", "from_id": sid("P/MAIN"), "to_id": sid("P/A"), "evidence_line": 11, "confidence": "grounded"},
        {"rel": "calls", "from_id": sid("P/A"), "to_id": sid("P/B"), "evidence_line": 21, "confidence": "grounded"},
        {"rel": "calls", "from_id": sid("P/B"), "to_id": sid("P/C"), "evidence_line": 31, "confidence": "inferred"},
        {"rel": "calls", "from_id": sid("P/MAIN"), "to_id": sid("P/D"), "evidence_line": 12, "confidence": "speculative"},
    ]
    summary = {"symbols": symbols, "occurrences": occ, "relationships": rels, "gaps": []}
    index = ei.emit_index(summary, content_sha256=sha, fmt="cobol", source_path="CHAIN.cbl", line_count=40,
                          model_id="t", prompt_hash="a" * 64, pipeline_fingerprint=fp, validate=True)
    st.persist(st.resolve_store_root(str(root)), index)
    return q.load_catalog(st.resolve_store_root(str(root)))


def _emit_bytes(op, catalog, **kw):
    class A:
        pass
    a = A()
    a.query = kw.get("query")
    a.anchors = kw.get("anchors")
    a.max_depth = kw.get("max_depth", 3)
    a.max_edges = kw.get("max_edges", 200)
    a.max_tokens = kw.get("max_tokens", 50000)
    a.include_speculative = kw.get("include_speculative", True)
    res, _ = q.run_query(op, a, catalog)
    return json.dumps(res, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@pytest.mark.parametrize("op,kw", [
    ("find_symbol", {"query": "MAIN"}),
    ("defs", {"query": "A"}),
    ("refs", {"query": "A"}),
    ("impact", {"query": "MAIN"}),
    ("list_artifacts", {}),
    ("subgraph_for_llm", {"anchors": ["MAIN", "C"]}),
])
def test_query_byte_identical_across_runs(store_root, op, kw):
    catalog = _seed_catalog(store_root)
    b1 = _emit_bytes(op, catalog, **kw)
    b2 = _emit_bytes(op, catalog, **kw)
    b3 = _emit_bytes(op, catalog, **kw)
    assert b1 == b2 == b3, f"op {op} is NON-DETERMINISTIC"


def test_impact_hop_bounded(store_root):
    catalog = _seed_catalog(store_root)
    index = q.build_symbol_index(catalog)
    # depth 1 from MAIN reaches A and D only (not B/C).
    im1 = q.op_impact(catalog, index, "MAIN", max_depth=1)
    reached = {e["to_id"] for e in im1["edges"]} | {e["from_id"] for e in im1["edges"]}
    names = {catalog and s["name"] for s in catalog["symbols"] if s["symbol_id"] in reached}
    assert "B" not in names and "C" not in names
    # depth 3 reaches everything in the chain.
    im3 = q.op_impact(catalog, index, "MAIN", max_depth=3)
    assert im3["edge_count"] >= 3


def test_impact_advisory_by_default(store_root):
    catalog = _seed_catalog(store_root)
    index = q.build_symbol_index(catalog)
    im = q.op_impact(catalog, index, "MAIN")
    assert im["advisory"] is True, "impact() must be advisory until gold precision clears (design §8)"


def test_budget_is_real_edge_cap_not_byte_slice(store_root):
    catalog = _seed_catalog(store_root)
    index = q.build_symbol_index(catalog)
    # max_edges=2 must truncate the union to exactly 2 edges + report omitted count.
    sg = q.op_subgraph_for_llm(catalog, index, ["MAIN", "C"], max_depth=3, max_edges=2)
    assert sg["edge_count"] == 2
    assert sg["truncated"] is True
    assert sg["omitted_edge_count"] >= 1
    # the budget cap is on EDGES (structured), not a substring of rendered text:
    # every emitted edge is a full dict with the four identity keys.
    for e in sg["edges"]:
        assert {"rel", "from_id", "to_id", "confidence"}.issubset(e.keys())


def test_token_budget_caps_edges(store_root):
    catalog = _seed_catalog(store_root)
    index = q.build_symbol_index(catalog)
    # max_tokens // TOKENS_PER_EDGE(160) = 1 edge at 200 tokens.
    sg = q.op_subgraph_for_llm(catalog, index, ["MAIN", "C"], max_depth=3, max_edges=1000, max_tokens=200)
    assert sg["edge_count"] == 1
    assert sg["truncated"] is True


def test_fuzzy_suggestions_when_not_found(store_root):
    catalog = _seed_catalog(store_root)
    index = q.build_symbol_index(catalog)
    fs = q.op_find_symbol(catalog, index, "MAIM")  # typo for MAIN
    assert fs["match_count"] == 0
    assert "MAIN" in fs["suggestions"]
