---
name: legacy-code-intel
description: "Use when you want a PERSISTENT, queryable, SCIP-inspired code-intelligence library over legacy artifacts — COBOL, DataStage .dsx (XML), ETL scripts (shell/SQL/Python), Java (legacy JEE/Spring estates), and Pick/MultiValue BASIC (UniVerse/UniData/D3/jBASE/OpenQM) — built ONCE into a content-addressed store and exposed via a deterministic graph-query layer + a self-contained HTML navigator. An LLM-as-parser framework (mirrors lineage-extract-static): model-neutral prompts the in-session AI CLI uses to extract symbols/occurrences/relationships, NOT per-format AST parsers. Triggerable as a single skill (ingest one artifact/dir) and via agent-teams (batch, one worker per artifact — NO new agent). Static analysis only (v1). Also trigger on \"index this COBOL\", \"symbol graph for DataStage jobs\", \"where is this paragraph called\", \"impact of changing this copybook\", \"index this Pick/MultiValue BASIC\", \"index this Java\", \"symbol graph for this Java service\", \"code intelligence for legacy\", \"build a navigator for this mainframe code\"."
---

# legacy-code-intel — persistent SCIP-inspired code-intelligence library

S-cycle design at `docs/plans/2026-06-09-legacy-code-intel-skill-design.md`.

## What it does

Ingests legacy artifacts into a **SCIP-inspired custom code-intelligence index**
(symbols + occurrences + relationships — SCIP's package/type hierarchy dropped),
stores it **once** in a **content-addressed library** (`~/.codelib`), and exposes:

- a **deterministic query layer** (`query.py`) — `find_symbol`, `defs`, `refs`,
  `impact`, `list_artifacts`, `subgraph_for_llm` — byte-identical stdout across runs;
- a **self-contained HTML navigator** (`render_navigator.py`) — Cytoscape relationship
  DAG + sortable symbol/occurrence/relationship tables + client-side search + CSV /
  ndjson exports, XSS-safe and air-gap-safe.

It is a **framework**: the in-session AI CLI (Claude Code / Codex CLI / Antigravity CLI (agy) /
Copilot CLI) is the parser via model-neutral prompts; `scripts/` has NO per-format AST
parsers (the `lineage-extract-static` precedent). Scope: **COBOL + DataStage
DSX + ETL + Java + Pick/MultiValue BASIC**. Both triggers: **skill** (one artifact/dir) and
**agent-teams** (batch). **No new agent.**

## When to use it

- "build a code-intelligence index / navigator over this COBOL/DataStage/ETL tree"
- "where is paragraph X called from", "what does this copybook touch"
- "impact of changing this paragraph/stage/table" (advisory until gold-cleared)
- "give me a symbol graph for these legacy artifacts"

Skip when:
- The code is in a language with a native LSP/SCIP indexer (use that — this is for
  legacy formats without one).
- You want RUNTIME traces (this is static analysis only, v1).
- You want data/process LINEAGE (datasets → jobs) — that's `lineage-extract-static`
  (cross-linked here via the shared `content_sha256`).
- You want a generated PROJECT.md front-door for a modern repo — that's
  `code-comprehension`.

## Components (one skill; mirror lineage-extract-static)

```
prompts/     analyze-symbols.md (+ cobol.md / dsx.md / etl.md / java.md / pick.md addenda),
             merge-chunks-within-file.md, resolve-symbol-id.md, redact-secrets.md   (model-neutral)
scripts/     chunk_file.py, accumulate.py, redact.py (fail-closed), emit_index.py,
             store.py (SINGLE WRITER), query.py (deterministic), render_navigator.py,
             fingerprint.py, goldcheck.py
schemas/     code-index.v1.json, code-finding.v1.json, library-catalog.v1.json   (VALID draft-07, lowercase)
templates/   navigator.html.j2 (XSS-safe, air-gap, Cytoscape)
references/  symbol-vocabulary.md, confidence-classifier.md, store-layout.md, anti-patterns.md
gold/        cobol/sample.gold.json   (the accuracy oracle)
tests/       unit + 4 anti-requirement tests + gold harness + round-trip
```

## Ingest flow (single artifact)

When a user issues `legacy-code-intel ingest <artifact|dir>` (or equivalent NL):

```
1. Agent reads this SKILL.md (the orchestration playbook).
2. Compute content_sha256 (fingerprint.py content) + the pipeline_fingerprint
   (fingerprint.py pipeline --prompt-hash <prompt-hash> --model-id <this CLI>).
3. STORE PROBE (dedup): store.py probe --content-sha256 H --pipeline-fingerprint F.
   - exit 0 (HIT) -> already indexed with this exact pipeline; SKIP the LLM pass
     entirely (zero LLM calls) and go straight to promote/render. "Process once."
   - exit 3 (MISS) -> continue.
4. chunk_file.py <artifact> <run_id>  -> per-file manifest + chunk placeholders
   at ~/.cache/legacy-code-intel/runs/<run_id>/files/<sha>/ (0700, NEVER /tmp).
5. For each chunk: read it, apply prompts/analyze-symbols.md + the format addendum
   (auto-detected: cobol/dsx/etl/java/pick — `.java` extension picks java; Pick BASIC
   often has no extension, so it is detected by content: SUBROUTINE / READNEXT /
   <a,v,s> / OCONV / CRT), emit ONE code-finding.v1 JSON object into
   chunk_NNNN.jsonl. Classify confidence per the bright-line rule. Use
   prompts/resolve-symbol-id.md for path-INDEPENDENT IDs.
   DSX: the agent loads the .dsx XML via defusedxml (XXE HARD-RULE) before analysis.
6. accumulate.py <chunk_dir> <run_id> <sha>  -> deterministic boundary-merge ->
   summary.json (NOT an LLM judgment).
7. emit_index.py summary.json --output index.json --content-sha256 H --format <fmt>
   --source-path <path> --line-count N --model-id <CLI> --prompt-hash H
   --pipeline-fingerprint F   -> assembles + schema-validates code-index.v1
   (closed kind-enum + bright-line classifier re-check).
8. redact.py index.json --output index.redacted.json  (FAIL-CLOSED — abort on error,
   NEVER partial-store). Legacy is credential-dense.
9. store.py persist index.redacted.json  -> writes the immutable object derivation +
   path ref, then promotes catalog/latest.json under the flock (single writer).
10. render_navigator.py --output-dir <dir>  -> navigator.html + CSV/ndjson exports.
11. (optional) goldcheck.py index.redacted.json gold/cobol/sample.gold.json --record
    -> records call-edge precision; keeps impact() advisory below 0.85 (design §8).
12. Print the navigator location + the accuracy number to the user.
```

## Batch flow (agent-teams, NO agent)

```
1. discover + classify artifacts under the target tree (auto-detect format).
2. dedup pre-filter: for each, fingerprint + store.py probe; drop the HITs.
3. agent-teams fan-out: one worker per remaining artifact, each runs steps 2-9 of the
   ingest flow with a bob-issued claim token (workers write DISJOINT objects/<sha>/
   dirs — safe; only the catalog promote serializes on the flock).
4. ONE serialized promote (store.py promote) after all workers finish.
5. render_navigator.py once over the promoted catalog.
```
No new agent: `code-comprehension` proves a claimless skill + agent-teams does batch
with no agent, and a new agent would hit `bob_subagent_depth_restriction` (loses the
Task tool when spawned as a subagent → batch silently serializes).

## CLI

```
legacy-code-intel ingest <artifact|dir> [--store PATH] [--output-dir DIR] [--no-vendor]
legacy-code-intel query <op> [args] [--store PATH]
    ops: find_symbol <q> | defs <q> | refs <q> | impact <q> | list_artifacts
         | subgraph_for_llm --anchors A B …
legacy-code-intel render --output-dir DIR [--store PATH] [--no-vendor]
legacy-code-intel goldcheck <index.json> <gold.json> [--record] [--store PATH]
```
The scripts are independently runnable (e.g. `python3 scripts/query.py impact PAYROLL`).
`--store` defaults to `~/.codelib` (or `$LCI_STORE`); pass `--store .codelib` for a
project-local store.

## HARD-RULEs (enforced by tests)

1. **Fail-closed redaction** before any store write (legacy = DSN/credential-dense);
   a redaction error aborts the artifact — NEVER partial-store.
2. **Bright-line confidence classifier** (grounded/inferred/speculative); interpolation
   / dynamic CALL / COPY REPLACING / DSX RCP → forced speculative
   (`emit_index._looks_dynamic`, defense-in-depth over the prompt).
3. **Deterministic output** — store records + query stdout + navigator are
   byte-canonical (`sort_keys`, `SOURCE_DATE_EPOCH` sentinel, atomic `.tmp.<pid>` +
   `os.replace`).
4. **XSS-safe navigator** — `html.escape` server-side (Jinja `|e`) + `textContent`
   client-side; embedded JSON has `< > &` neutralised. `test_html_escape_hostile_symbols`.
5. **Single-writer store + flock'd promote** — producers NEVER write
   `catalog/latest.json` (CB4); the catalog is promoted only under
   `fcntl.flock(.promote.lock)` + atomic `os.replace`. `test_concurrent_promote`.
6. **Model-neutral prompts** (Claude Code / Codex CLI / Antigravity CLI (agy) / Copilot CLI — no
   vendor anchors, no instruction XML tags).
7. **DoS caps** — 50 MB/file skip-with-warn, 2000-line chunks, 0700 cache (reused from
   lineage).
8. **0700 store, NEVER /tmp; `defusedxml` for DSX (XXE); path-INDEPENDENT symbol IDs;
   pipeline-fingerprint dedup key.**

## Anti-requirements (the discarded agy build's bugs — MUST NOT recur)

The design was built CLEAN after a rogue `agy` analyst auto-committed a broken version
(reverted/deleted). Its four confirmed bugs are regression-tested:
- schema must validate under `Draft7Validator.check_schema` (lowercase) → `test_schema_valid`
- catalog writes must be flock'd single-writer → `test_concurrent_promote`
- query must be deterministic (adjacency index, edge sort, real budget) → `test_query_determinism`
- `pipeline_fingerprint` computed in the ingest path + round-trips → `test_dedup_cache_hit`

See `references/anti-patterns.md` for the full list (11 items).

## Accuracy gate (design §8)

The real failure mode: the LLM call-graph can be wrong, there is no native oracle for
COBOL/DSX, and the confidence tag flags uncertainty but not incorrectness — so without
measurement the store becomes a write-once never-trusted graveyard. Mitigation:
- **Gold-file harness**: `gold/cobol/sample.gold.json` (hand-labeled call-edges) +
  `goldcheck.py` computes call-edge precision/recall; the navigator header + the
  catalog report it.
- **`impact()` is advisory-by-default**: until a format's gold precision clears 0.85,
  `impact()` carries the speculative framing + `advisory: true`. COBOL ships its gold
  file in v1; DSX + ETL + Java + Pick extraction prompts ship too but their gold files
  are a tracked fast-follow — until then DSX/ETL/Java/Pick `impact()` stays advisory
  (same gate).

## Composition with other skills

- `lineage-extract-static` — data/process lineage over the SAME artifacts; cross-linked
  via the shared `content_sha256` (advisory join in the navigator).
- `code-comprehension` — generated PROJECT.md front-door for modern repos (claimless,
  agent-teams batch precedent reused here).
- `wiring-query` — the `graph_ops.py` adjacency-BFS shape ported into `query.py`.
- `wiring-reconcile` / `project-state` — the flock + atomic-`os.replace` promote pattern
  ported into `store.py`.
- `cobol-developer` / `datastage-developer` / `pick-developer` / `java-backend` / `java-frontend` — the per-format symbol vocabulary.
- `mainframe-lineage-parsers` — the **deterministic** (no-LLM) gold-file precision
  route for COBOL/JCL/embedded-`EXEC SQL` lineage (#158): where this skill's
  LLM-derived call-graph stays advisory until a `gold/` file clears the 0.85 bar,
  `mainframe-lineage-parsers` extracts the two precision-win edge classes
  (DD-join, host-var→column) deterministically against a frozen naming contract
  and ships its own advisory `gold/expected-edges.yaml` precision oracle (same
  #158 advisory-until-gold pattern, never feeds a gate). Run both and compare.

## Security — XML / XHTML parsing

<HARD-RULE>
When parsing any DSX (DataStage export) or other XML payload, NEVER use stdlib
`xml.etree.ElementTree`, `xml.dom.minidom`, or `lxml.etree.fromstring` without XXE
protection. Use `defusedxml` (`pip install defusedxml`): `defusedxml.ElementTree`
instead of `xml.etree.ElementTree`. Stdlib XML parsers expand external entities by
default and are vulnerable to billion-laughs / XXE / DTD-retrieval / SSRF-via-entity
(CWE-611). DSX files are the primary XML surface here (bulk import / migration paths).
</HARD-RULE>

For the navigator's HTML output, all user-controlled strings are `html.escape`-d
server-side and inserted via `textContent` client-side — never raw `innerHTML`.
See `llm-security` for context-appropriate escaping rules.
