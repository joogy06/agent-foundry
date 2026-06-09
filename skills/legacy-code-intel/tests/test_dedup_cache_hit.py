"""test_dedup_cache_hit — ANTI-REQUIREMENT #4 (design §10).

The discarded agy build trusted a pipeline_fingerprint field it never set, so
re-ingesting the same bytes never hit the cache. The fingerprint is COMPUTED in the
ingest path (fingerprint.py) and round-trips through the store. This test asserts:
  - re-ingesting identical bytes with the same pipeline => store-HIT (probe true),
    so the ingest can skip the LLM pass entirely (ZERO LLM calls),
  - a prompt/model bump changes the fingerprint => store-MISS (re-extract),
  - the fingerprint round-trips intact through persist/promote.

The "zero LLM calls" claim is verified structurally: a fake ingest function that
probes-first and counts how many times it would invoke the (mocked) LLM extractor.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import emit_index as ei  # noqa: E402
import fingerprint as fp  # noqa: E402
import store as st  # noqa: E402


ARTIFACT_BYTES = b"IDENTIFICATION DIVISION.\nPROGRAM-ID. CACHED.\n"


def _build_index(sha, fingerprint):
    def sid(n):
        return f"codelib://sha256/{sha}#sym/{n}"
    summary = {
        "symbols": [{"symbol_id": sid("CACHED"), "kind": "program", "name": "CACHED"}],
        "occurrences": [{"symbol_id": sid("CACHED"), "role": "definition", "range": {"start_line": 2, "end_line": 2},
                         "evidence_snippet": "PROGRAM-ID. CACHED.", "confidence": "grounded", "confidence_reason": "lit"}],
        "relationships": [], "gaps": [],
    }
    return ei.emit_index(summary, content_sha256=sha, fmt="cobol", source_path="CACHED.cbl", line_count=2,
                         model_id="m", prompt_hash="a" * 64, pipeline_fingerprint=fingerprint, validate=True)


def _ingest_with_probe(root, content_bytes, prompt_hash, model_id, llm_calls):
    """A minimal ingest that probes the store first and ONLY invokes the (counted)
    LLM extractor on a MISS. Mirrors the SKILL.md flow steps 2-3-5-7-9."""
    sha = fp.content_sha256_of_bytes(content_bytes)
    fingerprint = fp.pipeline_fingerprint(prompt_hash, model_id)
    if st.probe(root, sha, fingerprint):
        return {"sha": sha, "fingerprint": fingerprint, "hit": True}
    # MISS -> would run the LLM. Count it, then build + persist the index.
    llm_calls.append((sha, fingerprint))
    index = _build_index(sha, fingerprint)
    st.persist(root, index)
    return {"sha": sha, "fingerprint": fingerprint, "hit": False}


def test_reingest_same_bytes_is_store_hit_zero_llm_calls(store_root):
    root = st.resolve_store_root(str(store_root))
    llm_calls: list = []

    r1 = _ingest_with_probe(root, ARTIFACT_BYTES, prompt_hash="a" * 64, model_id="m", llm_calls=llm_calls)
    assert r1["hit"] is False  # first ingest: MISS -> one LLM call
    assert len(llm_calls) == 1

    # Re-ingest identical bytes with the SAME pipeline: must HIT, zero new LLM calls.
    r2 = _ingest_with_probe(root, ARTIFACT_BYTES, prompt_hash="a" * 64, model_id="m", llm_calls=llm_calls)
    assert r2["hit"] is True
    assert len(llm_calls) == 1, "re-ingest must NOT invoke the LLM again (store-hit = process once)"
    assert r1["fingerprint"] == r2["fingerprint"]


def test_model_bump_misses_and_reextracts(store_root):
    root = st.resolve_store_root(str(store_root))
    llm_calls: list = []

    _ingest_with_probe(root, ARTIFACT_BYTES, prompt_hash="a" * 64, model_id="claude-code", llm_calls=llm_calls)
    assert len(llm_calls) == 1

    # Same bytes, DIFFERENT model => different fingerprint => MISS => re-extract.
    _ingest_with_probe(root, ARTIFACT_BYTES, prompt_hash="a" * 64, model_id="codex-cli", llm_calls=llm_calls)
    assert len(llm_calls) == 2, "a model change must re-extract (no stale cache hit)"


def test_prompt_bump_misses_and_reextracts(store_root):
    root = st.resolve_store_root(str(store_root))
    llm_calls: list = []

    _ingest_with_probe(root, ARTIFACT_BYTES, prompt_hash="a" * 64, model_id="m", llm_calls=llm_calls)
    # Same bytes + model, DIFFERENT prompt_hash => different fingerprint => MISS.
    _ingest_with_probe(root, ARTIFACT_BYTES, prompt_hash="c" * 64, model_id="m", llm_calls=llm_calls)
    assert len(llm_calls) == 2, "a prompt change must re-extract"


def test_fingerprint_round_trips_through_store(store_root):
    root = st.resolve_store_root(str(store_root))
    sha = fp.content_sha256_of_bytes(ARTIFACT_BYTES)
    fingerprint = fp.pipeline_fingerprint("a" * 64, "m")
    index = _build_index(sha, fingerprint)
    st.persist(root, index)

    # The stored object derivation must carry the SAME fingerprint we computed.
    obj_path = st.index_path(root, sha, fingerprint)
    assert obj_path.is_file()
    import json
    stored = json.loads(obj_path.read_text(encoding="utf-8"))
    assert stored["artifact"]["pipeline_fingerprint"] == fingerprint
    assert stored["artifact"]["content_sha256"] == sha


def test_fingerprint_is_deterministic_and_sensitive():
    f1 = fp.pipeline_fingerprint("a" * 64, "m")
    f2 = fp.pipeline_fingerprint("a" * 64, "m")
    assert f1 == f2
    assert f1 != fp.pipeline_fingerprint("a" * 64, "m2")  # model
    assert f1 != fp.pipeline_fingerprint("b" * 64, "m")   # prompt
    assert f1 != fp.pipeline_fingerprint("a" * 64, "m", extractor_version="9.9.9")  # extractor
    assert len(f1) == 64
