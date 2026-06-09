# Reference: the content-addressed library store (design §4)

`store.py` is the SOLE writer of `catalog/latest.json`. This document is the store
contract; read it before changing `store.py`.

## On-disk layout
```
<store>/                                   0700, NEVER /tmp; default ~/.codelib
                                           (--store .codelib for project-local)
├── objects/<sha[:2]>/<sha>/
│   └── derivations/<pipeline_fingerprint>/index.json   immutable code-index.v1
├── refs/by-path/<urlenc_path>.json        mutable pointer {current, history[]}
├── catalog/latest.json                    PROMOTED projection — query reads ONLY this
├── catalog/generation                     monotonic promote counter
├── catalog/runs/<run_id>/...              pre-promote scratch (reserved)
└── .promote.lock                          flock(LOCK_EX) target
```

## The two halves of the dedup key
A stored derivation is keyed by the PAIR `(content_sha256, pipeline_fingerprint)`:
- `content_sha256` — sha256 of the artifact bytes.
- `pipeline_fingerprint` — `sha256(schema_version + prompt_hash + extractor_version +
  model_id + normalizer_version)` (see `fingerprint.py`).

A `probe(content_sha256, pipeline_fingerprint)` HIT means the LLM pass is skipped
entirely ("process once" — zero LLM calls on re-ingest). A prompt edit / model swap /
extractor bump changes the fingerprint, so the SAME bytes correctly MISS and
re-extract — never a stale cache hit. This is the anti-requirement-#4 fix: a prompt or
model change must NOT serve a stale derivation. A new derivation is ADDED under a new
`<pipeline_fingerprint>/` dir; the old one is retained (immutable, version history).

## Concurrency model (anti-requirement #2)
- Producers (parallel agent-teams workers, one per artifact) write ONLY their own
  `objects/<sha>/derivations/<fp>/index.json` — disjoint paths, no contention.
- `catalog/latest.json` is written ONLY by `promote()`, under an exclusive
  `fcntl.flock(.promote.lock)` + atomic `os.replace`. Concurrent promotes serialize on
  the flock; a reader never sees a partial catalog.
- Producers NEVER touch `catalog/latest.json` (CB4). The discarded agy build did naive
  read-modify-write on the catalog and raced — this layout makes that impossible.
- The flock+atomic-replace pattern is ported from `wiring-reconcile/promote.py` and
  `project-state/reconcile.py`.

## Atomicity
Every write (object, ref, catalog, generation) uses `.tmp.<pid>` + `fsync` +
`os.replace` (atomic on POSIX). The catalog is schema-validated against
`library-catalog.v1.json` BEFORE the replace, so an invalid projection never lands.

## Determinism (HARD-RULE 3)
`build_catalog` flattens all promoted artifacts into one deduped view with stable
ordering (`sort_keys`, symbols by ID, occurrences by line, relationships by
(rel, from, to)). The `promoted_at` field uses the `SOURCE_DATE_EPOCH` sentinel by
default so two promotes of the same object set produce a byte-identical body (the
`generation` counter still increments — it is metadata, not content).

## Accuracy block
`goldcheck.py --record` calls `store.set_accuracy(format, precision, recall, …)`, which
re-promotes with the accuracy recorded in the catalog header. `query.impact()` reads
`accuracy.by_format[<fmt>].advisory` to decide whether to present results as
authoritative or speculative (design §8).
