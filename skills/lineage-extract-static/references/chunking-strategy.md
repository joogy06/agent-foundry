# Chunking Strategy — Two-Phase with Deterministic Boundary Reconciliation

Reference for `scripts/chunk_file.py` + `scripts/accumulate.py`. The two phases handle the long-tail of large files without losing lineage edges at chunk boundaries.

## Phase 1 — Inline (handles ≥95% of files)

Files satisfying ALL of these go through the inline path:

- Size ≤ `LINEAGE_INLINE_LIMIT_MB` (default 5 MB)
- Line count ≤ `LINEAGE_INLINE_LIMIT_LINES` (default 20000 lines)

→ The whole file is passed to the LLM in one prompt. `boundary_status` is always `complete`.

## Phase 2 — Chunked (the long-tail 5%)

When a file exceeds either threshold:

- `scripts/chunk_file.py` splits at line boundaries with `LINEAGE_CHUNK_LINES` (default 2000) lines per chunk and `LINEAGE_OVERLAP_LINES` (default 50) carry-over between adjacent chunks.
- Each chunk is passed to the LLM separately via `prompts/analyze-file.md`. The LLM emits one `lineage-finding.v1` JSON per chunk with `boundary_status ∈ {complete, partial_start, partial_end, partial_both}`.
- `prompts/merge-chunks-within-file.md` aggregates the per-chunk JSONs into a file-level rollup (no boundary pairing yet — that's deterministic).
- `scripts/accumulate.py` runs the **deterministic boundary-pairing predicate** to reconcile partials into complete edges.

## Boundary-pairing predicate (deterministic — HARD-RULE in design §9)

Two partial-boundary edges are paired if and only if ALL of:

```
same(edge.edge_kind)
same(edge.source_dataset.namespace, edge.source_dataset.name)
same(edge.target_job.namespace, edge.target_job.name)
chunk_N+1.start_line - chunk_N.end_line <= LINEAGE_OVERLAP_LINES (default 50)
```

### Pairing decisions

| Situation | Outcome |
|---|---|
| One `partial_end` in chunk N + one `partial_start` in chunk N+1 with matching key + within overlap | **Merged**: single edge with `start_line = min(N.partial.start, N+1.partial.start)`, `end_line = max(N.partial.end, N+1.partial.end)`. Confidence = more conservative of the two. |
| Two `partial_start` candidates in chunk N+1 for the same `partial_end` in chunk N | Take the one with smaller line-distance from chunk N's boundary. |
| Tied line-distance (rare; two adjacent partials at same line) | **BOTH downgraded** to `confidence: speculative` + `boundary_issue: true`. |
| `partial_end` with no matching `partial_start` in chunk N+1 | **Orphan**: downgraded to `confidence: speculative` + `boundary_issue: true`. |
| `partial_start` in chunk N+1 with no matching `partial_end` in chunk N | **Orphan**: downgraded same way. |
| `complete` boundary | Pass-through; no pairing needed. |

### Why deterministic — not LLM judgment

The pairing predicate is a pure function of `(edge_kind, source_dataset, target_job, line_distance)`. Two re-runs with the same chunks produce byte-identical pairings. No LLM call participates in the decision (the LLM only emits per-chunk edges with `boundary_status` markers).

This is the same discipline `wiring-reconcile` uses for its `static.jsonl` snapshot reconciliation.

## Confidence inheritance on merge

When two paired partials have different `confidence` values, the merged edge inherits the **more conservative** one:

```
speculative > inferred > grounded   (where ">" means "more conservative")
```

I.e. if one partial says `grounded` and the other says `inferred`, the merged edge is `inferred`. If one says `inferred` and the other says `speculative`, the merged edge is `speculative`. This prevents the LLM from "upgrading" confidence by emitting the same edge twice in adjacent chunks.

## Hard caps (DoS guard — HARD-RULE 6)

| Cap | Default | Behavior |
|---|---|---|
| `LINEAGE_HARD_FILE_LIMIT_MB` | 50 | Files exceeding this are SKIPPED with `gap: oversized_file` (non-fatal; surfaced in manifest) |
| `LINEAGE_MAX_DURATION_S` | 3600 | Global wall-clock cap; exit `PARTIAL` if exceeded |
| `LINEAGE_CACHE_MAX_GB` | 10 | Cache directory size cap with LRU eviction |

Files between `LINEAGE_INLINE_LIMIT_MB` (5) and `LINEAGE_HARD_FILE_LIMIT_MB` (50) go through the chunked path.

## Cache layout (per HARD-RULE 5)

```
~/.cache/lineage-extract-static/runs/<run_id>/   (mode 0700)
├── files/
│   ├── <file_sha256_1>/
│   │   ├── manifest.json
│   │   ├── chunk_0001.jsonl.placeholder    ← chunk-file emits placeholders
│   │   ├── chunk_0001.jsonl                ← agent populates via LLM
│   │   ├── chunk_0002.jsonl.placeholder
│   │   ├── chunk_0002.jsonl
│   │   ...
│   │   └── summary.json                    ← accumulate emits the file-level rollup
│   ├── <file_sha256_2>/
│   │   └── ...
│   └── ...
└── (no top-level state here — bob/agent state lives elsewhere)
```

### Per-file cache invariants

- The directory name is `<file_sha256>` of the FULL file content (NOT the chunk).
- All writes are atomic: `.tmp.<pid>` + `os.replace()`.
- Directory mode is `0700` (NEVER `0755`, NEVER under `/tmp`).
- `manifest.json` carries `path`, `sha256`, `size_bytes`, `line_count`, `chunked: bool`, `chunk_count`, `language_hint`, `binary: bool`, `gaps[]`.

### Idempotency

If `summary.json` exists and the `manifest.json` indicates the file was fully analyzed, the agent can skip re-running the LLM (cache hit). Cache key = `sha256(file_content + prompt_template_hash + extractor_version + model_id)`.

## Format-agnostic chunking

`scripts/chunk_file.py` is pure I/O. It does NOT parse the file. The LLM (via `prompts/analyze-file.md`) decides what to emit for each chunk based on the `language_hint` from the file extension. This is why the skill supports arbitrary input formats — the chunker doesn't care.

Edge cases:
- **No trailing newline**: handled by `count_lines_and_bytes()` which streams through file iter.
- **Empty file**: emits one degenerate chunk `(1, 1)` with no edges.
- **Mixed line endings** (CRLF + LF): each `\n` increments the line counter; CR is part of the line. Byte positions are CORRECT.
- **Files with only blank lines**: emits one chunk; LLM emits empty edges + empty gaps.

## Cross-language portability

The chunking is line-based (not byte-based), which is robust across:
- Python (`.py`)
- SQL (`.sql`, `.ddl`)
- DataStage (`.dsx`)
- COBOL (`.cbl`, `.cob`)
- YAML / JSON / TOML config
- Shell scripts
- Log files

The LLM's `prompts/analyze-file.md` is told which language hint applies; it tailors extraction accordingly. For unsupported languages, the LLM emits `gap: language_unsupported`.

## Tests

`tests/lineage-extract-static/unit/test_chunk_file.py` and `test_accumulate.py` enforce:
- Inline vs chunked path selection
- Hard-cap behavior (oversized files skip with gap)
- Sandbox path mode 0700 (no `/tmp`)
- Atomic write recovery (kill-mid-write doesn't corrupt summary.json)
- Boundary pairing predicate cases (paired, tied, orphan)
- Determinism (byte-identical re-run output)
