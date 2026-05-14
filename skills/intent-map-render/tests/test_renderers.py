"""Unit tests for the 4 diagram renderers (D1, D2, D3, D4) + run.py CLI."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import d1_sequence  # noqa: E402
import d2_cytoscape  # noqa: E402
import d3_sankey  # noqa: E402
import d4_heatmap  # noqa: E402
import run  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _sample_intent_map() -> dict:
    return {
        "components": [
            {
                "component_id": "auth-service",
                "function_class": "auth",
                "entry_points": [
                    {"kind": "http_route", "detail": "POST /verify",
                     "handler_symbol": "x:y", "evidence_edges": ["e1", "e2"]}
                ],
                "side_effects": [
                    {"kind": "cache_write", "target": "redis://cache",
                     "evidence_edges": ["e7"]}
                ],
                "error_paths": [
                    {"condition": "JWT invalid", "error_kind": "raises",
                     "propagates_to": "caller", "evidence_edges": ["e11"]}
                ],
                "test_seeds": [
                    {"seed_id": "S-001", "scenario": "x", "given": "y",
                     "when": "z", "then": "ok"},
                    {"seed_id": "S-002", "scenario": "a", "given": "b",
                     "when": "c", "then": "d"},
                ],
                "intent": {"one_line": "Validates auth tokens",
                           "confidence_level": "grounded"},
            },
            {
                "component_id": "rbac-service",
                "function_class": "rbac",
                "entry_points": [],
                "side_effects": [],
                "error_paths": [],
                "test_seeds": [],
                "intent": {"one_line": "Role lookups",
                           "confidence_level": "interpretive"},
            },
        ],
    }


def _sample_wiring_snapshot() -> dict:
    return {
        "schema_version": "1.1.0",
        "edges": [
            {"edge_id": "e1", "src_component": "auth-service",
             "src_symbol": "verify", "dst_component": "rbac-service",
             "dst_symbol": "lookup", "edge_kind": "calls"},
            {"edge_id": "e2", "src_component": "auth-service",
             "src_symbol": "verify", "dst_component": "cache-svc",
             "dst_symbol": "get", "edge_kind": "calls"},
        ],
        "components": [],
    }


def _sample_api_delta() -> dict:
    return {
        "package": "pandas",
        "old_version": "1.5.3",
        "new_version": "2.2.3",
        "breaking_lines": ["Series.append removed", "rename axis kw"],
        "affected_components": [
            {"name": "data-loader", "call_sites": 8},
            {"name": "analytics", "call_sites": 5},
        ],
    }


# ---------------------------------------------------------------------------
# D1
# ---------------------------------------------------------------------------


def test_d1_renders_components() -> None:
    out = d1_sequence.render(_sample_intent_map())
    assert "## D1" in out
    assert "auth-service" in out
    assert "rbac-service" in out
    assert "sequenceDiagram" in out


def test_d1_collapses_when_over_threshold() -> None:
    intent = {
        "components": [
            {"component_id": f"c{i}", "function_class": "auth",
             "entry_points": [], "side_effects": [], "error_paths": [],
             "test_seeds": []}
            for i in range(25)
        ]
    }
    out = d1_sequence.render(intent)
    assert "<details>" in out


def test_d1_no_collapse_below_threshold() -> None:
    out = d1_sequence.render(_sample_intent_map())
    assert "<details>" not in out
    assert "### auth-service" in out


def test_d1_empty_components() -> None:
    assert "no components" in d1_sequence.render({"components": []})


def test_d1_byte_identical_on_rerun() -> None:
    intent = _sample_intent_map()
    assert d1_sequence.render(intent) == d1_sequence.render(intent)


def test_d1_includes_entry_points() -> None:
    out = d1_sequence.render(_sample_intent_map())
    assert "POST /verify" in out


def test_d1_includes_error_notes() -> None:
    out = d1_sequence.render(_sample_intent_map())
    assert "JWT invalid" in out


def test_d1_render_single_component() -> None:
    c = _sample_intent_map()["components"][0]
    out = d1_sequence.render_single_component(c)
    assert out.startswith("```mermaid")
    assert out.endswith("```")


def test_d1_sanitize_dashes_and_spaces() -> None:
    out = d1_sequence.render({
        "components": [{
            "component_id": "my-svc with space",
            "function_class": "auth",
            "entry_points": [], "side_effects": [], "error_paths": [],
            "test_seeds": [],
        }]
    })
    assert "my_svc_with_space" in out


# ---------------------------------------------------------------------------
# D2
# ---------------------------------------------------------------------------


def test_d2_returns_elements_and_truncated() -> None:
    out = d2_cytoscape.render(_sample_intent_map(), _sample_wiring_snapshot())
    assert "elements" in out
    assert "truncated" in out


def test_d2_includes_anchor_nodes() -> None:
    out = d2_cytoscape.render(_sample_intent_map(), _sample_wiring_snapshot())
    node_ids = {e["data"]["id"] for e in out["elements"] if e["data"]["kind"] == "node"}
    assert "auth-service" in node_ids


def test_d2_includes_edges() -> None:
    out = d2_cytoscape.render(_sample_intent_map(), _sample_wiring_snapshot())
    edge_ids = {e["data"]["id"] for e in out["elements"] if e["data"]["kind"] == "edge"}
    assert edge_ids == {"e1", "e2"}


def test_d2_truncation_flag() -> None:
    snap = {
        "edges": [
            {"edge_id": f"e{i:03d}", "src_component": "auth", "dst_component": f"x{i}",
             "src_symbol": "s", "dst_symbol": "t", "edge_kind": "calls"}
            for i in range(20)
        ]
    }
    out = d2_cytoscape.render({"components": [{"component_id": "auth"}]},
                               snap, max_edges=5)
    assert out["truncated"] is True
    edges = [e for e in out["elements"] if e["data"]["kind"] == "edge"]
    assert len(edges) == 5


def test_d2_byte_identical_on_rerun() -> None:
    s1 = d2_cytoscape.render_string(_sample_intent_map(), _sample_wiring_snapshot())
    s2 = d2_cytoscape.render_string(_sample_intent_map(), _sample_wiring_snapshot())
    assert s1 == s2


def test_d2_no_anchors_filters_to_intent_components() -> None:
    """When anchors=None, all intent components become anchors."""
    out = d2_cytoscape.render(_sample_intent_map(), _sample_wiring_snapshot())
    assert out["anchor_count"] >= 1


def test_d2_explicit_anchors() -> None:
    """Pass anchors=[...] to filter."""
    out = d2_cytoscape.render(_sample_intent_map(), _sample_wiring_snapshot(),
                               anchors=["auth-service"])
    assert out["anchor_count"] == 1


# ---------------------------------------------------------------------------
# D3
# ---------------------------------------------------------------------------


def test_d3_renders_sankey() -> None:
    out = d3_sankey.render(_sample_api_delta())
    assert "sankey-beta" in out
    assert "pandas" in out
    assert "data-loader" in out


def test_d3_no_affected_components() -> None:
    delta = {"package": "x", "old_version": "1", "new_version": "2",
             "breaking_lines": ["a"], "affected_components": []}
    out = d3_sankey.render(delta)
    assert "no affected components" in out
    assert "sankey-beta" not in out


def test_d3_empty_input() -> None:
    out = d3_sankey.render({})
    assert "no api_delta" in out


def test_d3_advisory_when_over_30_breaking_lines() -> None:
    delta = _sample_api_delta()
    delta["breaking_lines"] = [f"bl{i}" for i in range(40)]
    out = d3_sankey.render(delta)
    assert "Advisory" in out


def test_d3_no_advisory_under_30() -> None:
    out = d3_sankey.render(_sample_api_delta())
    assert "Advisory" not in out


def test_d3_byte_identical_on_rerun() -> None:
    assert d3_sankey.render(_sample_api_delta()) == d3_sankey.render(_sample_api_delta())


def test_d3_components_sorted_alphabetically() -> None:
    """Affected components appear alphabetically in the output."""
    delta = _sample_api_delta()
    delta["affected_components"] = [
        {"name": "zebra", "call_sites": 1},
        {"name": "alpha", "call_sites": 1},
    ]
    out = d3_sankey.render(delta)
    # alpha should come before zebra
    assert out.index("alpha") < out.index("zebra")


# ---------------------------------------------------------------------------
# D4
# ---------------------------------------------------------------------------


def test_d4_renders_table() -> None:
    out = d4_heatmap.render(_sample_intent_map())
    assert "| Component" in out
    assert "auth-service" in out


def test_d4_empty_components() -> None:
    out = d4_heatmap.render({"components": []})
    assert "No components" in out


def test_d4_byte_identical_on_rerun() -> None:
    assert d4_heatmap.render(_sample_intent_map()) == d4_heatmap.render(_sample_intent_map())


def test_d4_counts_seeds_errors_edges() -> None:
    out = d4_heatmap.render(_sample_intent_map())
    # auth-service: 2 seeds, 1 error, 4 evidence edges (2+1+1)
    auth_line = [l for l in out.split("\n") if "auth-service" in l][0]
    assert " 2 " in auth_line  # test_seeds
    assert " 1 " in auth_line  # error_paths


def test_d4_totals_row() -> None:
    out = d4_heatmap.render(_sample_intent_map())
    assert "Totals" in out


def test_d4_grounded_count() -> None:
    """Totals row reports grounded count."""
    out = d4_heatmap.render(_sample_intent_map())
    assert "grounded: 1" in out


# ---------------------------------------------------------------------------
# CLI / run.py
# ---------------------------------------------------------------------------


def test_cli_emit_d1_d4(tmp_path: Path) -> None:
    intent = tmp_path / "intent.yaml"
    intent.write_text(yaml.safe_dump(_sample_intent_map()))
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(_sample_wiring_snapshot()))
    out_dir = tmp_path / "out"
    rc = run.main([
        "--intent-map", str(intent),
        "--wiring-snapshot", str(snap),
        "--emit", "D1,D4",
        "--output-dir", str(out_dir),
    ])
    assert rc == 0
    assert (out_dir / "D1.md").exists()
    assert (out_dir / "D4.md").exists()


def test_cli_rejects_function_level(tmp_path: Path) -> None:
    intent = tmp_path / "intent.yaml"
    intent.write_text(yaml.safe_dump(_sample_intent_map()))
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(_sample_wiring_snapshot()))
    rc = run.main([
        "--intent-map", str(intent),
        "--wiring-snapshot", str(snap),
        "--emit", "function_level",
    ])
    assert rc == 2


def test_cli_rejects_too_many_distinct_diagrams(tmp_path: Path) -> None:
    intent = tmp_path / "intent.yaml"
    intent.write_text(yaml.safe_dump(_sample_intent_map()))
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(_sample_wiring_snapshot()))
    rc = run.main([
        "--intent-map", str(intent),
        "--wiring-snapshot", str(snap),
        "--emit", "D1,D2,D3,D4",  # 4 — exceeds cap
    ])
    assert rc == 2


def test_cli_unknown_diagram_code(tmp_path: Path) -> None:
    intent = tmp_path / "intent.yaml"
    intent.write_text(yaml.safe_dump(_sample_intent_map()))
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(_sample_wiring_snapshot()))
    rc = run.main([
        "--intent-map", str(intent),
        "--wiring-snapshot", str(snap),
        "--emit", "D9",
    ])
    assert rc == 2


def test_cli_missing_intent_map_returns_env_error(tmp_path: Path) -> None:
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(_sample_wiring_snapshot()))
    rc = run.main([
        "--intent-map", str(tmp_path / "missing.yaml"),
        "--wiring-snapshot", str(snap),
        "--emit", "D1",
    ])
    assert rc == 3


def test_cli_d3_without_api_delta_soft_fallback(tmp_path: Path) -> None:
    intent = tmp_path / "intent.yaml"
    intent.write_text(yaml.safe_dump(_sample_intent_map()))
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(_sample_wiring_snapshot()))
    out_dir = tmp_path / "out"
    rc = run.main([
        "--intent-map", str(intent),
        "--wiring-snapshot", str(snap),
        "--emit", "D3",
        "--output-dir", str(out_dir),
    ])
    # D3 without api_delta is a soft fallback — exit 0
    assert rc == 0
    content = (out_dir / "D3.md").read_text()
    assert "--api-delta not provided" in content
