---
name: structure-recovery
description: "Use when you want to reverse-engineer the SHAPE of data — table column lists+types, COBOL record layouts (PIC/USAGE/COMP, computed byte offsets, REDEFINES, OCCURS), flat-file positional layouts, inferred CREATE TABLE DDL — from legacy artifacts (SQL/DDL, DataStage .dsx, COBOL+copybooks, flat-files). The 3rd lineage-family sibling (flow=lineage-extract-static, symbols=legacy-code-intel, structure=this). A cross-model LLM-as-parser framework: model-neutral prompts the in-session AI CLI runs against chunks via its OWN context — NO per-format parser deps; Python does only chunk I/O, validation, DETERMINISTIC COBOL byte-offset computation, accumulation, rendering. Handles large-file chunking + resumable partial reports; renders HTML/CSV/Excel/wiki/inferred-DDL/OpenLineage SchemaDatasetFacet. Static only (v1). Also trigger on \"reverse engineer table structure\", \"COBOL record layout\", \"copybook byte offsets\", \"infer DDL from\", \"flat-file layout\", \"schema from DSX\"."
---

# structure-recovery — reverse-engineer table/file structure from legacy artifacts

S-cycle design at `docs/plans/2026-06-15-structure-recovery-skill-design.md`.

## What it does

Reads SQL/DDL, DataStage `.dsx`, COBOL programs + copybooks, and flat-file layout
docs, and reconstructs the **structure of the data** the lineage family did not
cover (data **flow** = `lineage-extract-static`; code **symbols** = `legacy-code-intel`):

- **`structure-index.json`** — the queryable accumulated catalog (`structure-index.v1`):
  entities (tables / views / COBOL records / flat-file layouts) with fields, types,
  computed byte offsets/lengths, resolved relationships, per-entity/per-field
  `confidence × evidence_kind × enforcement`, and gaps.
- **`structure.html`** — one schema table per entity + a relationship DAG (Cytoscape),
  confidence color-coded, `SOURCE_DATE_EPOCH`-deterministic, XSS-safe, air-gap-safe.
- **`fields.csv` + `relationships.csv`** — flat exports (spreadsheet-injection-safe).
- **`structure.xlsx`** — one sheet per entity + summary + relationships (composes
  `ms-office-excel-python`; formula-injection-safe cells).
- **`wiki/`** — one interlinked markdown page per entity, every fact cited to
  `file:line` (composes the `wiki` skill, under `.wiki.lock`, anti-pollution-safe).
- **`structure.ddl.sql`** — inferred `CREATE TABLE` DDL with a mandatory
  human-review header; LIVE constraints only at `grounded` confidence; everything
  inferred/speculative emitted as commented `-- INFERRED FK:` lines, never executed.
- **`structure.schema-facets.json`** — OpenLineage `SchemaDatasetFacet` (fields+types)
  per dataset, enriching the existing lineage datasets (M1; extends `merge_into_ol.py`).

## When to use it

- You have legacy SQL/DDL, DataStage exports, COBOL+copybooks, or flat-file layout
  docs and you need the **column lists, types, and record layouts** — including
  **byte-accurate COBOL field offsets** — not just the data flow.
- You need an **inferred DDL** characterization aid for a system whose schema lives
  only in code.
- The artifact set is **large** — chunking + resumable partial reports across many
  files is built in (re-run resumes; nothing is re-analyzed that is already persisted).

NOT for: data flow / lineage edges (use `lineage-extract-static`); a queryable
symbol/occurrence graph (use `legacy-code-intel`); runtime/dynamic structure
(static only, v1); executing the inferred DDL (it is advisory-only, never run).

## Architecture (the LLM-driven framework)

The skill is the **framework**, the in-session AI CLI is the **parser** (decision
**N2**). There are NO per-format parsers (`sqlglot` / `tree-sitter` / `xml.sax`) in
`scripts/`. The agent's LLM extracts **declared facts** per chunk; Python is the
**calculator** (it computes COBOL byte offsets deterministically — the LLM never
declares an offset). The skill provides:

- **6 model-neutral prompts** in `prompts/*.md` — `analyze-sql`, `analyze-dsx`,
  `analyze-cobol`, `analyze-flatfile`, `merge`, `redact`. Each `analyze-*` emits ONE
  `structure-finding.v1` JSON object per chunk, no prose.
- **8 deterministic Python scripts** in `scripts/*.py` — `boundary_hints`,
  `validate_finding`, `cobol_offset_calc`, `run_state`, `accumulate_structure`,
  `relationships`, `render_structure`, `run_structure_recovery` (the driver).
  Plus the extended sibling `lineage-extract-static/scripts/chunk_file.py`.
- **2 reference docs** in `references/*.md` — `confidence-model`, `chunking`.
- **2 JSON schemas** in `schemas/` — `structure-finding.v1` (per-chunk emission),
  `structure-index.v1` (accumulated catalog).

Scripts have NO LLM calls. Prompts have NO Python code. The two halves are
interoperable across Claude Code / Codex CLI / Antigravity CLI (agy) / Copilot CLI
because the prompts are model-neutral.

## Invocation flow

When a user issues `structure-recovery <path>` (or NL: *"reverse-engineer the table
structure of /path/to/legacy"*):

```
1. Agent reads this SKILL.md (the orchestration playbook).
2. Agent runs scripts/run_structure_recovery.py over the target (file or tree).
   The driver discovers structure-bearing files (.sql/.ddl/.dsx/.cbl/.cob/.cpy/
   .fd/.layout/.txt), and for each file:
   2a. boundary-hint pre-pass (scripts/boundary_hints.py — pure, no LLM, no XML
       parser) emits SAFE split lines so a record is never bisected.
   2b. chunk (chunk_file.py with preferred_break_lines) into the 0700 run cache.
3. For each chunk, the AGENT applies the matching prompts/analyze-<format>.md and
   writes ONE structure-finding.v1 object to chunk_NNNN.jsonl
   (COBOL: DECLARED facts ONLY; byte_offset + length MUST be null — the validator
   rejects non-null; offsets are computed in step 4).
   The driver VALIDATES each finding (scripts/validate_finding.py) before it is
   trusted, then accumulates:
4. accumulate (scripts/accumulate_structure.py): merge per-chunk findings for the
   same (object_kind, qualified_name), dedup by (name, ordinal), lower-confidence-
   wins; for COBOL records, invoke scripts/cobol_offset_calc.py to compute
   byte_offset/length/ranged + gaps. Output: per-file summary.json.
5. Cross-file: the driver folds per-file summaries into the structure-index.v1
   catalog and runs scripts/relationships.py (K2 honesty caps: declared SQL FK =
   grounded; convention *_id = inferred; SQL JOIN = join; COBOL cross-record FK
   ONLY with --infer-relationships, capped speculative, name+type+length match).
6. render (scripts/render_structure.py): structure-index.json + structure.html +
   fields.csv + relationships.csv + structure.ddl.sql + structure.xlsx + wiki/ +
   structure.schema-facets.json.
7. Driver prints the output location + a status (complete|partial) summary.
```

The per-chunk LLM extraction (step 3) is the ONE step Python cannot do — it is the
LLM-as-parser seam. The driver exposes an `analyzer` hook so the in-session AI CLI
(or a wrapper) supplies the real analysis; when no finding is present for a chunk,
the catalog records an HONEST gap ("chunk N not yet analyzed") — never a fabricated
entity.

## CLI flags

```
run_structure_recovery.py <target> --output-dir <path>
  --infer-relationships     opt-in COBOL cross-record FK inference (decision O2;
                            capped speculative, commented DDL only, name+type+length match)
  --project-name <name>     label used in the HTML/wiki (default: target basename)
  --no-vendor               skip vendored Cytoscape; CDN/Mermaid fallback
  --source-date-epoch <int> pin output timestamps for byte-deterministic output
  --chunk-size-lines <int>  override STRUCT_CHUNK_LINES (default 1500)
  --overlap-lines <int>     override STRUCT_OVERLAP_LINES (default 200)
  --no-excel / --no-wiki / --no-ol   skip an optional emitter
  --list-only               discover + print the structure files (no analysis)
```

Env: `STRUCT_CHUNK_LINES`, `STRUCT_OVERLAP_LINES`, `STRUCT_MAX_DURATION_S`
(wall-clock cap → PARTIAL, default 3600), `STRUCT_MODEL_ID` (folds into the job
fingerprint so a deliberate model swap invalidates the warm cache).

## Resumability & PARTIAL contract

- **Job fingerprint** (`run_state.py`) = an OUTER sha256 folding project_root +
  selected-file-set snapshot (sorted `relpath:sha`) + options + `--infer-relationships`
  + prompt/extractor/schema/normalizer versions + model_id, **wrapping** (never
  widening) the reused `legacy-code-intel pipeline_fingerprint`. Same inputs → same
  fingerprint → resume; any input delta → a new job (no stale cache served).
- **Filesystem = truth.** A persisted `chunk_NNNN.jsonl` finding is a probe HIT and
  is NOT re-analyzed on re-invoke; a partial file resumes at the first missing chunk;
  a torn `run-state.json` self-heals (reconcile rebuilds `chunks_done` from disk).
- **PARTIAL is not failure.** The wall-clock cap finalizes `status:partial`, renders
  whatever is persisted, and lists `files_pending/files_partial/files_skipped`.
  Re-running resumes (every persisted file is a probe HIT).

## Confidence / honesty model (P1)

`confidence ∈ {grounded, inferred, speculative}` × `evidence_kind ∈
{declared_constraint, declared_column, inferred_naming, observed_usage}` ×
`enforcement ∈ {declared, unknown}` (DDL proves *declared*, not *deployed*).
Interpolation / dynamic (`#PARAM#`, RCP, `${...}`, f-strings) / unresolved-COPY /
ODO-tail / SYNC → forced `speculative`. Offsets carry their OWN confidence:
`grounded` for a clean DISPLAY/COMP/COMP-3 chain; `inferred` for group-propagated
USAGE; `speculative`/refused-with-gap for SYNC/ODO/unresolved-COPY (a SYNC or
post-ODO offset is emitted RANGED with a gap, **never** a confident value).
FK/relationship edges are **advisory until a `gold/` schema oracle clears an
accuracy gate** (legacy-code-intel precedent) — they **NEVER feed a gate**. Full
table in `references/confidence-model.md`.

## HARD-RULEs

1. **The LLM never declares a byte offset.** A non-null `byte_offset`/`length` on a
   chunk-level `structure-finding` is REJECTED by `validate_finding.py`. Offsets are
   computed downstream by `cobol_offset_calc.py` only.
2. **SYNC / OCCURS DEPENDING ON offsets are RANGED, never confident.** ODO emits
   `byte_offset_min`+`byte_offset_max`+`variable_length:true`; SYNC emits
   RANGED/UNKNOWN + `gap:sync_alignment`. Never a single authoritative value.
3. **COBOL cross-record FK is opt-in, capped, matched.** Only with
   `--infer-relationships`; capped `speculative`; requires name+type+length match;
   commented `-- INFERRED FK:` DDL only; never a live constraint.
4. **Inferred DDL is advisory.** Mandatory human-review header; never executed;
   never feeds a gate.
5. **No per-format parser deps; DSX read as text (N2).** No `sqlglot`, no XML parser.
   If structural DSX parsing is ever needed it MUST use `defusedxml` — but v1 uses
   regex/text-scan, so there is no XXE surface.
6. **Prompts are model-neutral** (Claude Code / Codex / agy / Copilot) — no
   model-specific phrasing.
7. **`chunk_file.py preferred_break_lines` is backward-compatible** — `None` default
   (NOT a mutable `[]`) ⇒ byte-identical to the pre-change chunker; the lineage
   chunk tests stay green.

## Output layout

```
<output-dir>/
  structure-index.json            # the queryable structure-index.v1 catalog
  structure.html                  # schema tables + relationship DAG (deterministic, XSS-safe)
  fields.csv  relationships.csv   # flat exports (injection-safe)
  structure.ddl.sql               # inferred DDL (human-review header; commented inferred FKs)
  structure.xlsx                  # one sheet/entity + summary + relationships (if openpyxl present)
  wiki/index.md  wiki/<entity>.md # interlinked, file:line-cited pages
  structure.schema-facets.json    # OL SchemaDatasetFacet enrichment (if the OL sibling present)
  .run/                           # 0700 resumable run cache (run-state + per-file chunk findings)
```

## Anti-patterns — STOP if you catch yourself

- Adding a per-format parser dependency (sqlglot / an XML parser) — N2 forbids it.
- Letting the LLM emit a byte offset — the validator rejects it; Python computes it.
- Emitting a confident COBOL offset past a SYNC or ODO field — must be ranged + gap.
- Promoting a COBOL cross-record FK above `speculative`, or rendering it as a live
  constraint — commented advisory only, opt-in only.
- Executing the inferred DDL, or feeding any relationship edge into a gate.
- Widening `legacy-code-intel pipeline_fingerprint`'s 5-field signature — wrap it.
- Fabricating an entity for an un-analyzed chunk — record an honest gap instead.

## Composition with other skills

- `lineage-extract-static` — reuses `chunk_file.py` (I/O substrate, extended with
  `preferred_break_lines`), the `accumulate.py` lower-confidence-wins idiom, the
  `render_report.py` HTML shape, `redact.py`, and extends `merge_into_ol.py` for the
  SchemaDatasetFacet (M1).
- `legacy-code-intel` — reuses the content-addressed `store.py` flock + skip-ladder
  and `fingerprint.py` (wrapped, never widened).
- `ms-office-excel-python` — composed for the `.xlsx` output (openpyxl + the
  formula-injection `safe_cell` rule).
- `wiki` — composed for the per-entity cited pages (`.wiki.lock`, anti-pollution).

## Security — XML / structure parsing

- 0700 cache dirs (NEVER `/tmp`); atomic `.tmp + os.replace + fsync` writes.
- Fail-closed secret redaction (`redact.py`) before any rendered output.
- DSX is read as **chunked text** (N2) — no XML parsing, so no XXE surface. The
  prompts flag RCP / `#PARAM#` dynamic layouts as gaps rather than guessing columns.
- All HTML/CSV/Excel/wiki cells are escaped/sanitized against XSS and
  spreadsheet-formula injection (CWE-1236).

## See also

- `docs/plans/2026-06-15-structure-recovery-skill-design.md` — full design + decisions.
- `references/confidence-model.md` — the 3-axis honesty model + K2 relationship caps.
- `references/chunking.md` — the chunking discipline (boundary hints, oversized-record gap).
