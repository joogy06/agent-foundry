#!/usr/bin/env python3
"""test_plugin_fastapi.py — fixture-driven smoke test for the fastapi extractor."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SKILL = Path.home() / ".claude" / "skills" / "wiring-extract-static"
sys.path.insert(0, str(_SKILL / "scripts"))

from plugin_loader import discover_plugins  # noqa: E402
from component_resolver import ComponentResolver  # noqa: E402
import jsonschema  # noqa: E402

EDGE_SCHEMA = json.loads((_SKILL / "schemas" / "wiring-source-edge.v1.json").read_text())
FMT = jsonschema.FormatChecker()

FIXTURE = _SKILL / "fixtures" / "fastapi-minimal"
EXPECTED = json.loads((FIXTURE / "expected-edges.json").read_text())["expected"]


def _run_plugin():
    plugins = discover_plugins()
    assert "fastapi" in plugins, f"fastapi plugin missing; found={list(plugins)}"
    fp = plugins["fastapi"]
    resolver = ComponentResolver(FIXTURE / "progress" / "contract-map.yaml", FIXTURE)
    sources = sorted((FIXTURE / "app").rglob("*.py"))
    edges = list(fp.extract_edges(
        project_dir=FIXTURE,
        symbols={"by_file": {}, "by_name": {}},
        source_files=sources,
        workspace_tree_hash="0" * 40,
        extractor_version=fp.version,
        config={},
        resolve_component=resolver.resolve,
    ))
    return edges


def test_fastapi_expected_subset():
    actual = _run_plugin()
    def key(e):
        return (e["src_component"], e["src_symbol"], e["dst_component"], e["dst_symbol"], e["edge_kind"])
    actual_keys = {key(e) for e in actual}
    missing = []
    for exp in EXPECTED:
        k = (exp["src_component"], exp["src_symbol"], exp["dst_component"], exp["dst_symbol"], exp["edge_kind"])
        if k not in actual_keys:
            missing.append(k)
    assert not missing, f"missing edges: {missing}\nactual: {sorted(actual_keys)}"


def test_fastapi_edges_validate():
    actual = _run_plugin()
    assert actual, "extractor returned no edges"
    for e in actual:
        e.setdefault("emitted_at", "2026-04-15T00:00:00Z")
        jsonschema.validate(e, EDGE_SCHEMA, format_checker=FMT)


def test_fastapi_deterministic():
    a = _run_plugin()
    b = _run_plugin()
    assert [e["edge_id"] for e in a] == [e["edge_id"] for e in b]


def main():
    tests = [test_fastapi_expected_subset, test_fastapi_edges_validate, test_fastapi_deterministic]
    failed = []
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed.append(f"{t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failed.append(f"{t.__name__}: {type(e).__name__}: {e}")
    if failed:
        print(f"FAIL {len(failed)}/{len(tests)}")
        for f in failed:
            print(f"  - {f}")
        sys.exit(1)
    print(f"PASS {len(tests)}/{len(tests)}")


if __name__ == "__main__":
    main()
