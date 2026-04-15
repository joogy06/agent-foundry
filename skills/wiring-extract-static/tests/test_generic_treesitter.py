#!/usr/bin/env python3
"""test_generic_treesitter.py — unit tests for generic-treesitter fallback extractor."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_SKILL = Path.home() / ".claude" / "skills" / "wiring-extract-static"
sys.path.insert(0, str(_SKILL / "scripts"))
sys.path.insert(0, str(_SKILL / "extractors" / "generic-treesitter"))

# plugin loader + schemas
from plugin_loader import discover_plugins  # noqa: E402
import jsonschema  # noqa: E402
from component_resolver import ComponentResolver  # noqa: E402

SCHEMAS = _SKILL / "schemas"
EDGE_SCHEMA = json.loads((SCHEMAS / "wiring-source-edge.v1.json").read_text())
FMT = jsonschema.FormatChecker()


def _emit(plugin, files, resolver, tree_hash="0" * 40):
    return list(plugin.extract_edges(
        project_dir=files[0].parent.parent if files else Path("/"),
        symbols={"by_file": {}, "by_name": {}},
        source_files=files,
        workspace_tree_hash=tree_hash,
        extractor_version=plugin.version,
        config={},
        resolve_component=resolver.resolve,
    ))


def test_python_imports_and_calls():
    plugins = discover_plugins()
    fb = plugins["generic-treesitter"]
    with tempfile.TemporaryDirectory() as td:
        project = Path(td)
        # Contract map
        (project / "progress").mkdir()
        (project / "progress" / "contract-map.yaml").write_text(
            'schema_version: "1.0.0"\nrevision: 1\ncomponents:\n'
            '  - id: mymod\n    source_paths:\n      - "src/"\n'
        )
        (project / "src").mkdir()
        src = project / "src" / "thing.py"
        src.write_text(
            "import os\nfrom requests import get\n\n"
            "def helper():\n    return 1\n\n"
            "def caller():\n    helper()\n    return helper()\n"
        )
        resolver = ComponentResolver(project / "progress" / "contract-map.yaml", project)
        edges = _emit(fb, [src], resolver)
        # should have imports + calls edges
        kinds = [e["edge_kind"] for e in edges]
        assert "imports" in kinds, f"no imports edges: {edges}"
        assert "calls" in kinds, f"no calls edges: {edges}"
        # each edge must validate
        for e in edges:
            e.setdefault("emitted_at", "2026-04-15T00:00:00Z")
            jsonschema.validate(e, EDGE_SCHEMA, format_checker=FMT)
        # src_component must be 'mymod'
        assert all(e["src_component"] == "mymod" for e in edges)
        # imports reference external:os or external:requests
        ext = [e for e in edges if e["edge_kind"] == "imports"]
        ext_dst_comps = {e["dst_component"] for e in ext}
        assert any(c.startswith("external:") for c in ext_dst_comps), f"no external imports: {ext_dst_comps}"


def test_js_imports():
    plugins = discover_plugins()
    fb = plugins["generic-treesitter"]
    with tempfile.TemporaryDirectory() as td:
        project = Path(td)
        (project / "progress").mkdir()
        (project / "progress" / "contract-map.yaml").write_text(
            'schema_version: "1.0.0"\nrevision: 1\ncomponents:\n'
            '  - id: api\n    source_paths:\n      - "src/"\n'
        )
        (project / "src").mkdir()
        src = project / "src" / "app.js"
        src.write_text(
            "import express from 'express';\n"
            "const fs = require('fs');\n"
            "function hello() { return 1; }\n"
            "hello();\n"
        )
        resolver = ComponentResolver(project / "progress" / "contract-map.yaml", project)
        edges = _emit(fb, [src], resolver)
        kinds = [e["edge_kind"] for e in edges]
        assert "imports" in kinds
        # express + fs
        dst_comps = {e["dst_component"] for e in edges if e["edge_kind"] == "imports"}
        assert "external:express" in dst_comps, dst_comps
        assert "external:fs" in dst_comps, dst_comps
        for e in edges:
            e.setdefault("emitted_at", "2026-04-15T00:00:00Z")
            jsonschema.validate(e, EDGE_SCHEMA, format_checker=FMT)


def test_unmapped_file_yields_no_edges():
    plugins = discover_plugins()
    fb = plugins["generic-treesitter"]
    with tempfile.TemporaryDirectory() as td:
        project = Path(td)
        (project / "progress").mkdir()
        (project / "progress" / "contract-map.yaml").write_text(
            'schema_version: "1.0.0"\nrevision: 1\ncomponents:\n'
            '  - id: only-auth\n    source_paths:\n      - "auth/"\n'
        )
        outside = project / "unmapped"
        outside.mkdir()
        fp = outside / "loose.py"
        fp.write_text("import os\n")
        resolver = ComponentResolver(project / "progress" / "contract-map.yaml", project)
        edges = _emit(fb, [fp], resolver)
        assert edges == []
        assert any("loose.py" in p for p in resolver.unmapped_paths)


def test_deterministic_edge_ids():
    """Two runs over the same input produce the same edge_ids in the same order."""
    plugins = discover_plugins()
    fb = plugins["generic-treesitter"]
    with tempfile.TemporaryDirectory() as td:
        project = Path(td)
        (project / "progress").mkdir()
        (project / "progress" / "contract-map.yaml").write_text(
            'schema_version: "1.0.0"\nrevision: 1\ncomponents:\n'
            '  - id: det\n    source_paths:\n      - "src/"\n'
        )
        (project / "src").mkdir()
        src = project / "src" / "d.py"
        src.write_text("import os\ndef a(): return 1\ndef b(): a()\n")
        resolver = ComponentResolver(project / "progress" / "contract-map.yaml", project)
        e1 = [e["edge_id"] for e in _emit(fb, [src], resolver)]
        e2 = [e["edge_id"] for e in _emit(fb, [src], resolver)]
        assert e1 == e2, f"non-deterministic: {e1} vs {e2}"


def main():
    tests = [
        test_python_imports_and_calls,
        test_js_imports,
        test_unmapped_file_yields_no_edges,
        test_deterministic_edge_ids,
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
