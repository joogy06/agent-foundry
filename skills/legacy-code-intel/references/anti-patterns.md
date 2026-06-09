# Reference: anti-patterns — STOP if you catch yourself

The first four are the EXACT bugs of the discarded `agy` build (design §10). They are
the explicit anti-requirements; each has a regression test that fails if it recurs.

## 1. Uppercase / non-validating schema types (→ `test_schema_valid`)
The agy schema used `"type": "STRING"` / `"OBJECT"` (uppercase) and could never
validate. JSON-Schema draft-07 types are LOWERCASE (`string`, `object`, `array`,
`integer`, `number`, `boolean`, `null`). Every schema MUST pass
`jsonschema.Draft7Validator.check_schema`. Do not hand-write a type in any other case.

## 2. Naive catalog read-modify-write (→ `test_concurrent_promote`)
The agy build read `catalog/latest.json`, mutated it in memory, and wrote it back —
racing under the agent-teams batch trigger (lost updates, torn files). The catalog is
written ONLY by `store.promote()` under `fcntl.flock(.promote.lock)` + atomic
`os.replace`. Producers write disjoint `objects/<sha>/` dirs and NEVER the catalog
(CB4). Do not add a second writer of `catalog/latest.json`.

## 3. Re-rolled BFS / byte-sliced "token budget" (→ `test_query_determinism`)
The agy query reimplemented BFS ad-hoc, byte-sliced rendered markdown for its
"budget", and never sorted edges — so two runs produced different bytes. `query.py`
ports `wiring-query/graph_ops.py`: adjacency index built ONCE, edges sorted by a stable
key `(rel, from_id, to_id)`, a REAL `min(max_edges, max_tokens // TOKENS_PER_EDGE)`
budget. stdout is canonical JSON. Two runs MUST be byte-identical.

## 4. Trusting an unset dedup field (→ `test_dedup_cache_hit`)
The agy build trusted a `pipeline_fingerprint` field it never set, so re-ingesting the
same bytes never hit the cache (and a prompt change could have false-hit). The
fingerprint is COMPUTED in the ingest path (`fingerprint.py`) and round-trips through
the store. Re-ingesting identical bytes with the same pipeline → store-hit, zero LLM
calls. A prompt/model bump → MISS, re-extract.

## 5. Emitting a partial store after a redaction error (HARD-RULE 1)
`redact.py` is fail-closed. Any redaction error aborts the WHOLE artifact — never write
a partially-redacted index to the store. Legacy code is credential-dense; a leaked DSN
password is a real incident.

## 6. Promoting an unredacted index
Redaction runs in the ingest path BEFORE `store.persist`. Do not persist a raw
`code-index.v1` straight from `emit_index.py` — run `redact.redact_index` first (the
ingest flow in SKILL.md does this; a custom caller must too).

## 7. Path-derived symbol IDs
Symbol IDs are `codelib://sha256/<artifact_hash>#sym/<scoped-name>` — content-addressed,
NOT path-derived. Path-derived IDs break content-hash dedup (the same copybook in two
repos would get two IDs). Paths live in `refs.by_path`, never in the ID.

## 8. Presenting `impact()` as authoritative below the gold threshold
`impact()` is ADVISORY by default. Until a format's gold-file call-edge precision clears
0.85, `impact()` results carry the speculative framing and the `advisory: true` flag.
Do not strip the advisory note or render dynamic edges as solid.

## 9. Writing the store under /tmp
`store.resolve_store_root` refuses any `/tmp` root and creates the store 0700
(HARD-RULE 8). Do not override this for "convenience" — legacy indexes hold sensitive
structure.

## 10. Building per-format AST parsers in `scripts/`
The LLM is the parser (the lineage-extract-static precedent). `scripts/` has NO
`sqlglot` / `tree-sitter` / COBOL grammar. Per-format logic lives ONLY in the prompt
addenda + the `kind` enum. The one parser dependency is `defusedxml` for DSX (XXE
protection), and it is used for safe XML loading, not semantic parsing.

## 11. Auto-traversing the call graph to invent edges
Emit only edges with evidence in the analysed chunk. Never synthesise a transitive edge
("A calls B, B calls C, so emit A calls C"). `impact()` computes transitive reach at
QUERY time over the stored direct edges; the store holds only directly-evidenced edges.
