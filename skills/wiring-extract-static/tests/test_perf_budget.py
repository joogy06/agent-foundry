#!/usr/bin/env python3
"""test_perf_budget.py — SC2 performance envelope for wiring-extract-static.

Invariant (per contract-map.yaml success_criteria + bob task #60):
    extracting >= 10,000 edges from a synthetic Python+TS corpus must
    complete in < 10 seconds of wall time.

This is a tighter per-run throughput check than SC2's baseline ("Completes
within 2min on 50k-LOC TS+Python repo"); at 10s / 10k edges = 1kHz sustained
edge emission, well inside the 2-minute envelope.

Methodology
-----------
1. Deterministic seeded fixture generation (seed=20260415).
2. Generate ~400 Python files + ~400 JS files. Each carries:
     - ~16 `import` statements (=> external:<pkg> imports edges)
     - N intra-file helper functions h_0..h_{N-1}, each of which calls the
       next one: h_0() -> h_1() -> ... => the extractor emits ~N-1 `calls`
       edges per file via its FunctionDef-walking codepath.
   Target ~16,000 edges total (margin above the 10,000 assertion floor).
3. Run the generic-treesitter fallback extractor directly (no subprocess).
4. Assert:
     edges >= 10_000       (SC2 volume floor)
     wall_time < 10.0      (SC2 throughput budget)

Why the generic-treesitter plug-in
----------------------------------
The framework plug-ins (fastapi/express) emit tens of edges per fixture;
generic-treesitter is the mass-edge path. Real projects hit this same
codepath for imports and intra-file calls, so timing it directly exercises
the production hot path.

Extractor codepath specifics
----------------------------
- Python: `_python_edges` walks `FunctionDef` bodies and emits a `calls`
  edge for each `ast.Call` whose callee is a `Name` defined in the same
  file. Self-recursion is excluded. So N sequential helpers produce N-1
  edges, plus the M imports.
- JS: `_js_edges` uses regex. Imports via `_IMPORT_RE`; calls only when the
  identifier appears in `_FUNC_DEF_RE`'s set (`function X(` or
  `const X = (`). Module-level calls to defined functions count.

Determinism
-----------
- Fixed seed (20260415). Fixture bytes are bit-identical every run.
- Extractor edge_ids are deterministic (sha256 of tuple).
- The wall-time assertion has a 10s ceiling with >3x typical headroom
  (~2-3s on modern hardware). Flake here = real regression.
"""
from __future__ import annotations

import random
import sys
import tempfile
import time
from pathlib import Path

_SKILL = Path.home() / ".claude" / "skills" / "wiring-extract-static"
sys.path.insert(0, str(_SKILL / "scripts"))
sys.path.insert(0, str(_SKILL / "extractors" / "generic-treesitter"))

from plugin_loader import discover_plugins  # noqa: E402
from component_resolver import ComponentResolver  # noqa: E402


SEED = 20260415
PY_FILES = 400
JS_FILES = 400
IMPORTS_PER_FILE = 16            # exact; contributes 16 * (PY_FILES+JS_FILES) imports edges
HELPERS_PER_FILE = (18, 24)      # inclusive range; per-file intra calls = N-1

# Safety floor: generated edges must exceed 10,000. Target is ~22k
# (800 files * 16 imports + 800 files * ~20 calls).
EDGE_FLOOR = 10_000

# Wall-time budget (seconds).
WALL_BUDGET_S = 10.0

_PKG_VOCAB = [
    "aardvark", "bellbird", "capybara", "dugong", "echidna",
    "flamingo", "gecko", "hornbill", "iguana", "jaguar",
    "kookaburra", "lemur", "manta", "numbat", "ocelot",
    "pangolin", "quokka", "raccoon", "serval", "tapir",
    "uakari", "vicuna", "wallaby", "xerus", "yabby", "zebu",
]


def _fixture_dir() -> Path:
    """Create a temporary synthetic corpus and return its path."""
    root = Path(tempfile.mkdtemp(prefix="wiring-extract-perf-"))
    rng_master = random.Random(SEED)

    # Contract map so ComponentResolver maps these files to two real
    # components; otherwise every edge ends up unresolved.
    (root / "progress").mkdir(parents=True)
    (root / "progress" / "contract-map.yaml").write_text(
        'schema_version: "1.0.0"\nrevision: 1\ncomponents:\n'
        '  - id: py-app\n    source_paths:\n      - "src/py/"\n'
        '  - id: js-app\n    source_paths:\n      - "src/js/"\n'
    )
    (root / "src" / "py").mkdir(parents=True)
    (root / "src" / "js").mkdir(parents=True)

    # IMPORTANT: the extractor dedupes by edge_id within a single invocation.
    # Since edge_id = sha256(src_component, src_symbol, dst_component,
    # dst_symbol, edge_kind), every file in `py-app` that imports
    # `aardvark_0` would collapse to one edge. To get >=10k distinct edges
    # we must vary the dst_symbol per file. We do that by giving each file
    # its own per-file import package suffix (`pkg_{i}_{k}` not `pkg_{k}`)
    # AND its own per-file helper namespace (`h_{i}_{k}` not `h_{k}`).
    # Then every emitted edge has a unique (src, dst, kind) tuple.

    # Python files — emit `n_helpers` functions h_{i}_0..h_{i}_{n-1} where
    # h_{i}_k calls h_{i}_{k+1}. This yields (n_helpers - 1) `calls` edges
    # per file via the FunctionDef-walk in _python_edges. Plus
    # IMPORTS_PER_FILE imports edges with file-unique dst_symbols.
    for i in range(PY_FILES):
        rng_local = random.Random(SEED + i)
        n_helpers = rng_local.randint(*HELPERS_PER_FILE)
        lines = []
        for k in range(IMPORTS_PER_FILE):
            pkg = _PKG_VOCAB[(i + k) % len(_PKG_VOCAB)]
            # File-unique import name -> file-unique dst_component+dst_symbol
            lines.append(f"import {pkg}_{i}_{k}")
        lines.append("")
        for k in range(n_helpers):
            if k < n_helpers - 1:
                lines.append(f"def h_{i}_{k}():\n    return h_{i}_{k + 1}()")
            else:
                lines.append(f"def h_{i}_{k}():\n    return {k}")
        (root / "src" / "py" / f"mod_{i}.py").write_text("\n".join(lines) + "\n")

    # JS files — same per-file uniqueness pattern. Module-level calls go at
    # the bottom referencing each declared function so _CALL_RE picks them
    # up (names appear in `defined`).
    for i in range(JS_FILES):
        rng_local = random.Random(SEED + 100_000 + i)
        n_helpers = rng_local.randint(*HELPERS_PER_FILE)
        lines = []
        for k in range(IMPORTS_PER_FILE):
            pkg = _PKG_VOCAB[(i + k) % len(_PKG_VOCAB)]
            lines.append(f"import {{ thing_{i}_{k} }} from '{pkg}_{i}_{k}';")
        lines.append("")
        for k in range(n_helpers):
            if k < n_helpers - 1:
                lines.append(
                    f"function h_{i}_{k}() {{ return h_{i}_{k + 1}(); }}"
                )
            else:
                lines.append(f"function h_{i}_{k}() {{ return {k}; }}")
        # Module-bottom calls so _CALL_RE picks the names up against `defined`.
        for k in range(n_helpers):
            lines.append(f"h_{i}_{k}();")
        (root / "src" / "js" / f"mod_{i}.js").write_text("\n".join(lines) + "\n")

    return root


def test_sc2_perf_budget_10k_edges_under_10s():
    """SC2: extract >= 10k edges in < 10s wall time (generic-treesitter)."""
    root = _fixture_dir()
    plugins = discover_plugins()
    fallback = plugins["generic-treesitter"]
    resolver = ComponentResolver(root / "progress" / "contract-map.yaml", root)

    py_files = sorted((root / "src" / "py").glob("*.py"))
    js_files = sorted((root / "src" / "js").glob("*.js"))
    source_files = py_files + js_files

    t0 = time.perf_counter()
    edges = list(fallback.extract_edges(
        project_dir=root,
        symbols={"by_file": {}, "by_name": {}},
        source_files=source_files,
        workspace_tree_hash="0" * 40,
        extractor_version=fallback.version,
        config={},
        resolve_component=resolver.resolve,
    ))
    wall = time.perf_counter() - t0

    imports_edges = sum(1 for e in edges if e["edge_kind"] == "imports")
    calls_edges = sum(1 for e in edges if e["edge_kind"] == "calls")

    # Concrete evidence printed for audit visibility.
    print(
        f"[SC2] total_edges={len(edges)} imports={imports_edges} "
        f"calls={calls_edges} wall_s={wall:.3f} "
        f"py_files={len(py_files)} js_files={len(js_files)} "
        f"throughput_eps={len(edges)/wall:.0f}"
    )

    assert len(edges) >= EDGE_FLOOR, (
        f"SC2 volume floor: expected >= {EDGE_FLOOR} edges, got {len(edges)}. "
        f"imports={imports_edges}, calls={calls_edges}."
    )
    assert wall < WALL_BUDGET_S, (
        f"SC2 throughput budget: extraction took {wall:.3f}s, budget is "
        f"{WALL_BUDGET_S}s for {len(edges)} edges "
        f"(throughput = {len(edges)/wall:.0f} edges/s)."
    )

    # Sanity on a sampled subset: every emitted edge carries load-bearing fields.
    for e in edges[: min(200, len(edges))]:
        assert e.get("edge_id"), f"edge missing edge_id: {e}"
        assert e.get("edge_kind") in {"imports", "calls"}, (
            f"unexpected edge_kind: {e.get('edge_kind')}"
        )
        assert e.get("evidence_source") == "static_extract"
        assert e.get("extractor_id") == "generic-treesitter"
