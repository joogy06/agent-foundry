#!/usr/bin/env python3
"""test_plugin_loader.py — unit tests for plugin_loader."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SKILL = Path.home() / ".claude" / "skills" / "wiring-extract-static"
sys.path.insert(0, str(_SKILL / "scripts"))

from plugin_loader import discover_plugins, load_plugin, PluginLoadError, plugins_for_language, fallback_plugin  # noqa: E402


def test_discover_real_generic():
    plugins = discover_plugins()
    # generic-treesitter must be present (shipped with WP-2)
    assert "generic-treesitter" in plugins, f"missing generic-treesitter, found={list(plugins)}"
    fb = plugins["generic-treesitter"]
    assert fb.is_fallback is True
    assert fb.version == "1.0.0"
    assert callable(fb.extract_edges)


def test_fallback_picker():
    plugins = discover_plugins()
    fb = fallback_plugin(plugins)
    assert fb is not None
    assert fb.is_fallback is True


def test_plugins_for_language_priority():
    plugins = discover_plugins()
    py_plugins = plugins_for_language(plugins, "python")
    # fallback should appear after any framework
    assert len(py_plugins) >= 1
    if len(py_plugins) > 1:
        assert py_plugins[-1].is_fallback
        assert all(not p.is_fallback for p in py_plugins[:-1])


def test_malformed_manifest_is_skipped():
    with tempfile.TemporaryDirectory() as td:
        extractors = Path(td) / "extractors"
        bad = extractors / "bad-plugin"
        bad.mkdir(parents=True)
        (bad / "plugin.json").write_text("{ not valid json")
        (bad / "extractor.py").write_text("def extract_edges(**kw): return iter([])\n")
        got = discover_plugins(extractors_root=extractors)
        assert "bad-plugin" not in got


def test_missing_extractor_py_raises():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "x"
        d.mkdir()
        (d / "plugin.json").write_text(json.dumps({
            "id": "x", "version": "1.0.0", "target_framework": "generic",
            "languages": ["python"], "edge_kinds": ["calls"], "is_fallback": False,
            "description": "test",
        }))
        try:
            load_plugin(d)
        except PluginLoadError:
            return
        raise AssertionError("expected PluginLoadError for missing extractor.py")


def test_version_must_be_semver():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "x"
        d.mkdir()
        (d / "plugin.json").write_text(json.dumps({
            "id": "x", "version": "1.0", "target_framework": "generic",
            "languages": ["python"], "edge_kinds": ["calls"], "is_fallback": False,
            "description": "test",
        }))
        (d / "extractor.py").write_text("def extract_edges(**kw): return iter([])\n")
        try:
            load_plugin(d)
        except PluginLoadError:
            return
        raise AssertionError("expected PluginLoadError for non-semver version")


def main():
    tests = [
        test_discover_real_generic,
        test_fallback_picker,
        test_plugins_for_language_priority,
        test_malformed_manifest_is_skipped,
        test_missing_extractor_py_raises,
        test_version_must_be_semver,
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
