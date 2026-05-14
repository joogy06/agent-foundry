"""Unit tests for anchor_expand.py — 1-hop call neighbourhood extraction."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import anchor_expand  # noqa: E402


def _write_jsonl(path: Path, edges: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for e in edges:
            fh.write(json.dumps(e) + "\n")


def _edge(eid: str, sc: str, ss: str, dc: str, ds: str, kind: str = "calls") -> dict:
    return {
        "edge_id": eid,
        "src_component": sc,
        "src_symbol": ss,
        "dst_component": dc,
        "dst_symbol": ds,
        "edge_kind": kind,
        "callsite_refs": [{"path": f"src/{sc}/{ss}.py", "line": 10}],
    }


def test_direct_edges_only(tmp_path: Path) -> None:
    """Anchor with no neighbours returns just direct edges."""
    jsonl = tmp_path / "static.jsonl"
    _write_jsonl(jsonl, [
        _edge("e1", "auth", "verify", "auth", "decode"),
    ])
    exp = anchor_expand.anchor_and_expand(jsonl, "auth")
    assert len(exp.direct_edges) == 1
    assert exp.neighbour_edges == []
    assert "e1" in exp.evidence_edge_ids


def test_one_hop_neighbours(tmp_path: Path) -> None:
    """1-hop reaches outward but not 2-hop.

    Note: any edge whose src OR dst component == anchor is a DIRECT edge,
    not a neighbour. Neighbours are edges whose endpoints touch a symbol
    that the anchor calls but aren't themselves in the anchor's component.
    """
    jsonl = tmp_path / "static.jsonl"
    _write_jsonl(jsonl, [
        # e1: direct (auth.verify → auth.decode)
        _edge("e1", "auth", "verify", "auth", "decode"),
        # e2: also direct (src is auth) — auth.decode → crypto.rsa
        _edge("e2", "auth", "decode", "crypto", "rsa"),
        # e3: 1-hop from auth → crypto.rsa (src is crypto, dst symbol used by auth)
        _edge("e3", "crypto", "rsa", "math", "exp"),
        # e4: 2-hop — touches math.exp but no auth symbol
        _edge("e4", "math", "exp", "calc", "raise"),
    ])
    exp = anchor_expand.anchor_and_expand(jsonl, "auth")
    direct_ids = {e["edge_id"] for e in exp.direct_edges}
    neighbour_ids = {e["edge_id"] for e in exp.neighbour_edges}
    # Both e1 and e2 are direct (src_component == auth)
    assert direct_ids == {"e1", "e2"}
    # e3 touches (crypto, rsa) which is in the direct_symbols set → 1-hop
    assert "e3" in neighbour_ids
    # e4 touches math.exp which is NOT in any direct edge of auth → 2-hop
    assert "e4" not in neighbour_ids


def test_anchor_with_no_edges(tmp_path: Path) -> None:
    """Component absent from static.jsonl → empty expansion."""
    jsonl = tmp_path / "static.jsonl"
    _write_jsonl(jsonl, [_edge("e1", "auth", "x", "auth", "y")])
    exp = anchor_expand.anchor_and_expand(jsonl, "nonexistent")
    assert exp.direct_edges == []
    assert exp.neighbour_edges == []
    assert exp.evidence_edge_ids == []


def test_jsonl_missing_returns_empty(tmp_path: Path) -> None:
    """Missing static.jsonl is non-fatal (degraded path)."""
    jsonl = tmp_path / "missing.jsonl"
    exp = anchor_expand.anchor_and_expand(jsonl, "anything")
    assert exp.direct_edges == []


def test_jsonl_with_malformed_lines(tmp_path: Path) -> None:
    """Malformed lines are skipped, valid ones still processed."""
    jsonl = tmp_path / "static.jsonl"
    with jsonl.open("w") as fh:
        fh.write("{ not json }\n")
        fh.write(json.dumps(_edge("e1", "auth", "x", "rbac", "y")) + "\n")
        fh.write("\n")  # blank line
        fh.write("plain text\n")
    exp = anchor_expand.anchor_and_expand(jsonl, "auth")
    assert len(exp.direct_edges) == 1


def test_max_neighbour_edges_cap(tmp_path: Path) -> None:
    """1-hop expansion truncates at max_neighbour_edges."""
    jsonl = tmp_path / "static.jsonl"
    edges = [_edge("e0", "auth", "main", "X", f"f{i}") for i in range(50)]
    edges += [_edge(f"n{i}", "X", f"f{i}", "Y", f"g{i}") for i in range(50)]
    _write_jsonl(jsonl, edges)
    exp = anchor_expand.anchor_and_expand(jsonl, "auth", max_neighbour_edges=10)
    assert len(exp.neighbour_edges) <= 10


def test_evidence_edge_ids_sorted_unique(tmp_path: Path) -> None:
    """evidence_edge_ids is sorted unique."""
    jsonl = tmp_path / "static.jsonl"
    _write_jsonl(jsonl, [
        _edge("e3", "auth", "a", "auth", "b"),
        _edge("e1", "auth", "c", "x", "d"),
        _edge("e2", "y", "p", "auth", "q"),
    ])
    exp = anchor_expand.anchor_and_expand(jsonl, "auth")
    assert exp.evidence_edge_ids == ["e1", "e2", "e3"]


def test_participating_files_from_callsite_refs(tmp_path: Path) -> None:
    """File list pulled from callsite_refs[].path, sorted unique."""
    jsonl = tmp_path / "static.jsonl"
    _write_jsonl(jsonl, [
        {**_edge("e1", "auth", "x", "auth", "y"),
         "callsite_refs": [{"path": "src/auth/x.py"}, {"path": "src/auth/y.py"}]},
        {**_edge("e2", "auth", "z", "rbac", "w"),
         "callsite_refs": [{"path": "src/auth/x.py"}]},
    ])
    exp = anchor_expand.anchor_and_expand(jsonl, "auth")
    assert exp.participating_files == ["src/auth/x.py", "src/auth/y.py"]


def test_load_component_source_paths(tmp_path: Path) -> None:
    """source_paths resolves project-relative globs."""
    (tmp_path / "src" / "auth").mkdir(parents=True)
    (tmp_path / "src" / "auth" / "routes.py").write_text("# routes\n")
    (tmp_path / "src" / "auth" / "jwt.py").write_text("# jwt\n")
    cm = {
        "components": [
            {"id": "auth-service", "source_paths": ["src/auth/*.py"]},
        ]
    }
    paths = anchor_expand.load_component_source_paths(cm, "auth-service", tmp_path)
    names = {p.name for p in paths}
    assert names == {"routes.py", "jwt.py"}


def test_load_component_source_paths_missing_component(tmp_path: Path) -> None:
    """Unknown component_id → empty list."""
    cm = {"components": [{"id": "auth-service", "source_paths": ["src/auth/*.py"]}]}
    paths = anchor_expand.load_component_source_paths(cm, "missing", tmp_path)
    assert paths == []


def test_evidence_edge_ids_for_convenience(tmp_path: Path) -> None:
    """Convenience function returns just the sorted ids."""
    jsonl = tmp_path / "static.jsonl"
    _write_jsonl(jsonl, [
        _edge("e2", "auth", "a", "auth", "b"),
        _edge("e1", "auth", "c", "x", "d"),
    ])
    ids = anchor_expand.evidence_edge_ids_for(jsonl, "auth")
    assert ids == ["e1", "e2"]
