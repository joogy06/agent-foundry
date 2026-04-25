#!/usr/bin/env python3
"""test_plugin_redis_streams.py — fixture-driven tests for the redis-streams extractor.

Mirrors test_plugin_fastapi.py / test_plugin_express.py structure:
- loads the plugin via discover_plugins (skill entry contract)
- runs it against a minimal fixture under fixtures/redis-streams-minimal/
- validates every edge against wiring-source-edge.v1
- asserts expected-edges.json is a strict subset of actual output
- verifies determinism by re-running and comparing edge_ids

Also includes tests for:
  * the augment-mode activation flag in plugin.json and loader.
  * gap telemetry via _LAST_GAPS (parameter-only xadd → recorded gap).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SKILL = Path.home() / ".claude" / "skills" / "wiring-extract-static"
sys.path.insert(0, str(_SKILL / "scripts"))

from plugin_loader import discover_plugins, augment_plugins_for_language  # noqa: E402
from component_resolver import ComponentResolver  # noqa: E402
import jsonschema  # noqa: E402

EDGE_SCHEMA = json.loads((_SKILL / "schemas" / "wiring-source-edge.v1.json").read_text())
FMT = jsonschema.FormatChecker()

FIXTURE = _SKILL / "fixtures" / "redis-streams-minimal"
EXPECTED = json.loads((FIXTURE / "expected-edges.json").read_text())["expected"]


def _plugin():
    plugins = discover_plugins()
    assert "redis-streams" in plugins, (
        f"redis-streams plugin missing; found={sorted(plugins)}"
    )
    return plugins["redis-streams"], plugins


def _run_plugin():
    plugin, _ = _plugin()
    resolver = ComponentResolver(
        FIXTURE / "progress" / "contract-map.yaml", FIXTURE
    )
    sources = sorted(FIXTURE.rglob("*.py"))
    edges = list(plugin.extract_edges(
        project_dir=FIXTURE,
        symbols={"by_file": {}, "by_name": {}},
        source_files=sources,
        workspace_tree_hash="0" * 40,
        extractor_version=plugin.version,
        config={"redis_streams": {"constants_modules": ["shared.constants"]}},
        resolve_component=resolver.resolve,
    ))
    return edges


# ---------------------------------------------------------------------------
# Activation-mode contract
# ---------------------------------------------------------------------------


def test_plugin_declares_augment_mode():
    plugin, _ = _plugin()
    assert plugin.activation_mode == "augment", (
        f"expected activation_mode=augment, got {plugin.activation_mode!r}"
    )
    assert plugin.is_augment is True
    assert plugin.is_fallback is False


def test_augment_plugins_for_language_includes_redis_streams():
    _, plugins = _plugin()
    py_augment = augment_plugins_for_language(plugins, "python")
    ids = [p.id for p in py_augment]
    assert "redis-streams" in ids, (
        f"augment_plugins_for_language(python) did not include redis-streams; got {ids}"
    )


# ---------------------------------------------------------------------------
# Edge extraction
# ---------------------------------------------------------------------------


def test_redis_streams_expected_subset():
    actual = _run_plugin()
    def key(e):
        return (e["src_component"], e["src_symbol"],
                e["dst_component"], e["dst_symbol"], e["edge_kind"])
    actual_keys = {key(e) for e in actual}
    missing = []
    for exp in EXPECTED:
        k = (exp["src_component"], exp["src_symbol"],
             exp["dst_component"], exp["dst_symbol"], exp["edge_kind"])
        if k not in actual_keys:
            missing.append(k)
    assert not missing, (
        f"missing edges: {missing}\nactual: {sorted(actual_keys)}"
    )


def test_redis_streams_edges_validate():
    actual = _run_plugin()
    assert actual, "extractor returned no edges"
    for e in actual:
        # Runner auto-fills emitted_at; tests stamp a synthetic value.
        e.setdefault("emitted_at", "2026-04-18T00:00:00Z")
        jsonschema.validate(e, EDGE_SCHEMA, format_checker=FMT)


def test_redis_streams_deterministic():
    a = _run_plugin()
    b = _run_plugin()
    # edge_id preservation across runs given identical AST.
    assert [e["edge_id"] for e in a] == [e["edge_id"] for e in b]


def test_emitted_edge_has_stream_metadata():
    actual = _run_plugin()
    # Pick one known emits edge and confirm the stream name is embedded.
    hits = [e for e in actual if e["edge_kind"] == "emits"
            and "candles" in e.get("src_symbol", "")]
    assert hits, f"no emits edge for candles found in {actual}"
    hit = hits[0]
    assert hit.get("metadata", {}).get("stream_name") == "equity:market:candles"
    assert hit["dst_component"] == "shared-redis"
    assert hit["src_symbol"].startswith("publisher.emits:")


def test_unresolved_xadd_is_reported_as_gap():
    # _run_plugin() sets module-level _LAST_GAPS on the extractor module.
    # Find the module via plugin_loader's registered namespace.
    _run_plugin()  # populate
    modname = "wiring_extractor_redis_streams"
    assert modname in sys.modules, (
        f"extractor module not registered under {modname}; "
        f"got: {sorted(k for k in sys.modules if 'redis' in k)}"
    )
    gaps = getattr(sys.modules[modname], "_LAST_GAPS", [])
    # `publish_from_config` calls redis.xadd(cfg.stream, ...) where
    # cfg is a locally-bound Name not in our constants index. The
    # resolver returns "missing-constant:cfg" (Name lookup step). Any
    # gap flavour is acceptable for the fixture — the core assertion
    # is that unresolved call sites are surfaced at all.
    assert gaps, f"expected at least one unresolved-stream gap; got: {gaps}"
    unresolved_kinds = {g.split(":", 2)[1] for g in gaps}
    assert unresolved_kinds, (
        f"expected gap kind labels; got raw: {gaps}"
    )


def main():
    tests = [
        test_plugin_declares_augment_mode,
        test_augment_plugins_for_language_includes_redis_streams,
        test_redis_streams_expected_subset,
        test_redis_streams_edges_validate,
        test_redis_streams_deterministic,
        test_emitted_edge_has_stream_metadata,
        test_unresolved_xadd_is_reported_as_gap,
    ]
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
