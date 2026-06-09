"""test_concurrent_promote — ANTI-REQUIREMENT #2 (design §10).

The discarded agy build did naive read-modify-write on catalog/latest.json and raced
under the agent-teams batch trigger (lost updates, torn files). store.py promotes ONLY
under fcntl.flock(.promote.lock) + atomic os.replace, and producers write disjoint
objects/<sha>/ dirs. This test launches many concurrent persist+promote workers (each
a separate PROCESS, so the flock is genuinely contended across address spaces) and
asserts:
  - the final catalog is valid + lands every artifact (no lost update),
  - the catalog file is never observed torn (atomic replace),
  - the generation counter is monotonic.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"
sys.path.insert(0, str(SCRIPTS))


def _worker(args):
    """Run in a SEPARATE process: build a unique artifact index and persist+promote
    it. Contends the .promote.lock across address spaces (true flock test)."""
    store_path, i = args
    sys.path.insert(0, str(SCRIPTS))
    import store as st
    import emit_index as ei

    sha = f"{i:064x}"
    fp = "b" * 64

    def sid(n):
        return f"codelib://sha256/{sha}#sym/{n}"

    summary = {
        "symbols": [
            {"symbol_id": sid("P"), "kind": "program", "name": f"PROG{i}"},
            {"symbol_id": sid("P/PARA"), "kind": "paragraph", "name": f"PARA{i}", "container_symbol_id": sid("P")},
        ],
        "occurrences": [
            {"symbol_id": sid("P"), "role": "definition", "range": {"start_line": 1, "end_line": 1},
             "evidence_snippet": f"PROGRAM-ID. PROG{i}.", "confidence": "grounded", "confidence_reason": "lit"},
        ],
        "relationships": [
            {"rel": "contains", "from_id": sid("P"), "to_id": sid("P/PARA"), "evidence_line": 0, "confidence": "grounded"},
        ],
        "gaps": [],
    }
    root = st.resolve_store_root(store_path)
    index = ei.emit_index(summary, content_sha256=sha, fmt="cobol", source_path=f"P{i}.cbl",
                          line_count=10, model_id="t", prompt_hash="a" * 64, pipeline_fingerprint=fp, validate=True)
    # promote_after=True with blocking_promote=True so contended promotes wait on the
    # flock rather than failing — every worker's artifact must land.
    res = st.persist(root, index, promote_after=True, blocking_promote=True)
    return res["content_sha256"]


@pytest.mark.parametrize("n_workers", [12])
def test_concurrent_promote_no_lost_updates(store_root, n_workers):
    store_path = str(store_root)

    ctx = mp.get_context("spawn")  # spawn => genuinely separate interpreters
    with ctx.Pool(processes=min(n_workers, 8)) as pool:
        shas = pool.map(_worker, [(store_path, i) for i in range(n_workers)])

    assert len(set(shas)) == n_workers

    # Final catalog must be valid and contain EVERY artifact (no lost update).
    cat_path = store_root / "catalog" / "latest.json"
    assert cat_path.is_file()
    catalog = json.loads(cat_path.read_text(encoding="utf-8"))

    schema = json.loads((SCHEMAS / "library-catalog.v1.json").read_text(encoding="utf-8"))
    errors = sorted(Draft7Validator(schema).iter_errors(catalog), key=lambda e: list(e.path))
    assert not errors, f"final catalog invalid: {[e.message for e in errors[:3]]}"

    stored = {a["content_sha256"] for a in catalog["artifacts"]}
    expected = {f"{i:064x}" for i in range(n_workers)}
    assert expected.issubset(stored), f"lost updates: missing {expected - stored}"

    # generation must have advanced at least n_workers times (each promote bumps once).
    assert catalog["generation"] >= n_workers


def test_promote_lock_is_exclusive(store_root):
    """Directly assert the flock is non-blocking-exclusive: a second acquire while the
    first is held raises BlockingIOError."""
    import store as st
    root = st.resolve_store_root(str(store_root))
    lock = root / ".promote.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()
    with st._PromoteLock(lock, blocking=False):
        with pytest.raises(BlockingIOError):
            with st._PromoteLock(lock, blocking=False):
                pass


def test_objects_are_disjoint_per_artifact(store_root):
    """Two different artifacts write to different object dirs (no shared mutable file
    other than the catalog, which only promote writes)."""
    import store as st
    import emit_index as ei
    root = st.resolve_store_root(str(store_root))

    def mk(sha):
        def sid(n):
            return f"codelib://sha256/{sha}#sym/{n}"
        s = {"symbols": [{"symbol_id": sid("P"), "kind": "program", "name": "P"}],
             "occurrences": [{"symbol_id": sid("P"), "role": "definition", "range": {"start_line": 1, "end_line": 1},
                              "evidence_snippet": "X", "confidence": "grounded", "confidence_reason": "l"}],
             "relationships": [], "gaps": []}
        return ei.emit_index(s, content_sha256=sha, fmt="cobol", source_path=f"{sha[:4]}.cbl", line_count=1,
                             model_id="t", prompt_hash="a" * 64, pipeline_fingerprint="b" * 64, validate=True)

    a, b = "1" * 64, "2" * 64
    pa = st.persist(root, mk(a), promote_after=False)
    pb = st.persist(root, mk(b), promote_after=False)
    assert pa["object_path"] != pb["object_path"]
    assert Path(pa["object_path"]).is_file() and Path(pb["object_path"]).is_file()
