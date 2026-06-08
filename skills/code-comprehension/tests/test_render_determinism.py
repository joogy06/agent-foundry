"""WP-6 — render_docs.py determinism (HARD gate #2) + structural-edge labeling
(HARD gate #4) + per-run-field stripping + output shape.

HARD gate #2: render is byte-identical across two runs GIVEN a fixed intent-map.
We assert this by rendering, deleting the render, re-rendering from the SAME fixed
intent-map, and comparing bytes — NOT cold-LLM-regen byte-identity (unachievable).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import render_docs  # noqa: E402


# A fixed partition doc + intent-map + edge view (the determinism premise).
PARTITION_DOC = {
    "schema_version": "1.0.0",
    "provenance": "synthetic-unsigned",
    "partition_version": "1.0.0",
    "generated_at": "2026-06-08T12:00:00Z",  # per-run; must NOT affect the body
    "project_dir": "/x",
    "partition_hash": "a" * 64,
    "tree_state": {"tree_hash": "b" * 40, "dirty": False, "untracked_count": 0},
    "config": {"cap": 12, "fragment_pct_threshold": 0.4, "max_files": 40,
               "max_bytes": 512000, "per_component_token_budget": 120000},
    "decisions": [],
    "components": [
        {"id": "svc", "source_paths": ["svc/**"], "source_files": ["svc/app.py", "svc/main.py"],
         "method": "directory", "entry_points": ["python:__main__"], "intent_mode": "llm",
         "cost": {"file_count": 2, "byte_count": 100, "est_tokens": 50}},
        {"id": "lib", "source_paths": ["lib/**"], "source_files": ["lib/util.py"],
         "method": "directory", "entry_points": [], "intent_mode": "llm",
         "cost": {"file_count": 1, "byte_count": 50, "est_tokens": 25}},
    ],
}

INTENT_MAP = {
    "components": [
        {"component_id": "svc", "function_class": "service",
         "sampled_at": "2026-06-08T12:00:00Z",   # per-run — MUST be stripped
         "model_id": "claude-opus-4-7",          # per-run — pinned in gen_from, stripped from body
         "workspace_tree_hash": "c" * 40,
         "entry_points": [{"kind": "http_route", "detail": "/x", "handler_symbol": "svc/app.py:h"}],
         "side_effects": [], "error_paths": [{"condition": "bad", "error_kind": "raises"}],
         "intent": {"one_line": "Serves X.", "confidence_level": "grounded",
                    "responsibilities": ["route X"]}},
        {"component_id": "lib", "function_class": "util",
         "sampled_at": "2026-06-08T12:00:01Z",
         "model_id": "claude-opus-4-7",
         "entry_points": [], "side_effects": [], "error_paths": [],
         "intent": {"one_line": "Helps.", "confidence_level": "interpretive"}},
    ]
}

EDGE_VIEW = {
    "snapshot_id": "deadbeefdeadbeef",
    "edges": [
        {"edge_id": "e1", "src_component": "svc", "dst_component": "lib",
         "src_symbol": "h", "dst_symbol": "helper", "edge_kind": "calls", "status": "live",
         "blocking_eligible": False, "evidence": []},
    ],
    "components": [], "statistics": {"total_edges": 1},
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "app.py").write_text("x=1\n")
    (tmp_path / "svc" / "main.py").write_text("x=1\n")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "util.py").write_text("x=1\n")
    (tmp_path / "requirements.txt").write_text("flask==3.0.0\nrequests>=2.0\n")
    return tmp_path


def _render(repo: Path, out: Path) -> dict:
    return render_docs.render_all(
        project_dir=repo, out_dir=out,
        partition_doc=PARTITION_DOC, intent_map=INTENT_MAP, edge_view=EDGE_VIEW,
        shadow=True,
    )


# --- HARD gate #2: delete-and-rebuild byte-identity given a fixed intent-map ---


def test_render_byte_identical_on_rebuild(repo: Path) -> None:
    out = repo / ".comprehension"
    r1 = _render(repo, out)
    pmd = Path(r1["project_md"])
    first = pmd.read_bytes()
    comp_first = {c: (Path(r1["component_dir"]) / c / "COMPONENT.md").read_bytes()
                  for c in r1["components"]}

    # delete the render entirely, rebuild from the SAME fixed intent-map
    pmd.unlink()
    for c in r1["components"]:
        (Path(r1["component_dir"]) / c / "COMPONENT.md").unlink()

    r2 = _render(repo, out)
    assert Path(r2["project_md"]).read_bytes() == first, "PROJECT.md must be byte-identical on rebuild"
    for c in r2["components"]:
        assert (Path(r2["component_dir"]) / c / "COMPONENT.md").read_bytes() == comp_first[c]


def test_render_stable_across_different_out_dirs(repo: Path) -> None:
    r1 = _render(repo, repo / ".comprehension")
    r2 = _render(repo, repo / ".comprehension2")
    assert Path(r1["project_md"]).read_text() == Path(r2["project_md"]).read_text()


def test_edge_view_timestamps_do_not_affect_render(repo: Path) -> None:
    """Dogfood regression: the reconciler's snapshot_id embeds per-run emitted_at via
    evidence[].last_seen_at. The render must NOT depend on it — it hashes only the
    deterministic component-edge triples. Two edge-views that differ ONLY in
    timestamps/snapshot_id must produce byte-identical PROJECT.md."""
    ev_a = {
        "snapshot_id": "aaaaaaaaaaaaaaaa",
        "edges": [{"edge_id": "e1", "src_component": "svc", "dst_component": "lib",
                   "src_symbol": "h", "dst_symbol": "x", "edge_kind": "calls",
                   "status": "live", "blocking_eligible": False,
                   "evidence": [{"evidence_source": "static_extract", "extractor_id": "w",
                                 "extractor_version": "1.0.0",
                                 "last_seen_at": "2026-06-08T11:11:11Z",
                                 "workspace_tree_hash": "a" * 40, "confidence": 0.9}]}],
        "components": [], "statistics": {"total_edges": 1},
    }
    ev_b = json.loads(json.dumps(ev_a))
    ev_b["snapshot_id"] = "bbbbbbbbbbbbbbbb"
    ev_b["edges"][0]["evidence"][0]["last_seen_at"] = "2099-12-31T23:59:59Z"

    ra = render_docs.render_all(project_dir=repo, out_dir=repo / ".ca",
                                partition_doc=PARTITION_DOC, intent_map=INTENT_MAP,
                                edge_view=ev_a, shadow=True)
    rb = render_docs.render_all(project_dir=repo, out_dir=repo / ".cb",
                                partition_doc=PARTITION_DOC, intent_map=INTENT_MAP,
                                edge_view=ev_b, shadow=True)
    assert Path(ra["project_md"]).read_text() == Path(rb["project_md"]).read_text(), (
        "render must be invariant to edge-view timestamps / snapshot_id")


def test_generated_at_does_not_affect_body(repo: Path) -> None:
    r1 = _render(repo, repo / ".c1")
    body1 = Path(r1["project_md"]).read_text()
    # mutate the per-run generated_at in a copy
    doc2 = dict(PARTITION_DOC)
    doc2["generated_at"] = "2099-01-01T00:00:00Z"
    r2 = render_docs.render_all(project_dir=repo, out_dir=repo / ".c2",
                                partition_doc=doc2, intent_map=INTENT_MAP,
                                edge_view=EDGE_VIEW, shadow=True)
    assert Path(r2["project_md"]).read_text() == body1, "generated_at must not appear in body"


def test_sampled_at_stripped_from_body(repo: Path) -> None:
    r1 = _render(repo, repo / ".comprehension")
    body = Path(r1["project_md"]).read_text()
    comp = (Path(r1["component_dir"]) / "svc" / "COMPONENT.md").read_text()
    assert "2026-06-08T12:00:00Z" not in body
    assert "2026-06-08T12:00:00Z" not in comp


# --- HARD gate #4: edges labeled "structural (AST/regex)", never SCIP ---


def test_edges_labeled_structural_not_scip(repo: Path) -> None:
    r1 = _render(repo, repo / ".comprehension")
    body = Path(r1["project_md"]).read_text()
    assert "structural (AST/regex" in body
    assert "SCIP" not in body or "SCIP deferred" in body
    # specifically: no claim of SCIP precision
    assert "SCIP code graph" not in body
    assert "SCIP-evidence" not in body


def test_interaction_edges_present(repo: Path) -> None:
    r1 = _render(repo, repo / ".comprehension")
    body = Path(r1["project_md"]).read_text()
    assert "## Interaction Edges" in body
    assert "`svc`" in body and "`lib`" in body


# --- Output shape / banner / freshness ---


def test_generated_banner_present(repo: Path) -> None:
    r1 = _render(repo, repo / ".comprehension")
    body = Path(r1["project_md"]).read_text()
    comp = (Path(r1["component_dir"]) / "svc" / "COMPONENT.md").read_text()
    assert "GENERATED by code-comprehension" in body
    assert "GENERATED by code-comprehension" in comp


def test_freshness_stamp_keyed_to_content(repo: Path) -> None:
    r1 = _render(repo, repo / ".comprehension")
    body = Path(r1["project_md"]).read_text()
    assert "FRESHNESS:v1 generated_from=" in body


def test_external_deps_parsed(repo: Path) -> None:
    r1 = _render(repo, repo / ".comprehension")
    body = Path(r1["project_md"]).read_text()
    assert "flask" in body
    assert "requests" in body


def test_architecture_md_pointer(repo: Path) -> None:
    r1 = _render(repo, repo / ".comprehension")
    body = Path(r1["project_md"]).read_text()
    assert "ARCHITECTURE.md" in body


def test_shadow_never_overwrites_real_project_md(repo: Path) -> None:
    # plant a real PROJECT.md; shadow render must not touch it
    real = repo / "PROJECT.md"
    real.write_text("REAL HAND-WRITTEN DOC\n")
    _render(repo, repo / ".comprehension")
    assert real.read_text() == "REAL HAND-WRITTEN DOC\n"
    assert (repo / ".comprehension" / "PROJECT.generated.md").is_file()


def test_d1_diagram_rendered_in_component(repo: Path) -> None:
    r1 = _render(repo, repo / ".comprehension")
    comp = (Path(r1["component_dir"]) / "svc" / "COMPONENT.md").read_text()
    assert "```mermaid" in comp
    assert "sequenceDiagram" in comp
