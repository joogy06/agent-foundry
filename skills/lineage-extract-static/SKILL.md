---
name: lineage-extract-static
description: "Use when extracting data/process lineage from a codebase or file tree — Python/SQL/DSX/Control-M/dbt/COBOL/scheduler configs/log files into spec-correct OpenLineage 2.0.2 JobEvent + DatasetEvent ndjson plus dual visual report (HTML Cytoscape DAG + Mermaid markdown + CSV). Skill is a framework — model-neutral prompts the in-session AI CLI (Claude Code, Codex CLI, Antigravity CLI (agy), Copilot CLI) uses to analyse chunks via its own LLM context, NOT per-format parser plug-ins. Static analysis only (v1); runtime producers in v2. Also trigger on \"lineage report\", \"data flow extraction\", \"openlineage\", \"trace data through the codebase\", \"where does this dataset come from\"."
---

# lineage-extract-static — Cross-System Data/Process Lineage Skill

S033 design at `docs/plans/2026-05-14-lineage-extract-static-skill-design.md`.

## What it does

Reads any file tree and emits:

- **`openlineage.ndjson`** — canonical stream of `JobEvent` + `DatasetEvent` (one event per line). Spec-correct static lineage per OpenLineage 2.0.2 — NO synthesised `Run` by default. HARD-RULE 1.
- **`openlineage.json`** — derived `{"events": [...]}` bundle for tooling that prefers single-document input.
- **`lineage_edges.csv`** — single denormalized CSV: `src_dataset_namespace, src_dataset_name, src_kind, target_job_namespace, target_job_name, target_job_kind, edge_kind, confidence, evidence_file, evidence_line, extractor_id`. Opt-in `--output-format=ol-relational` splits into 4 CSVs.
- **`report.html`** — self-contained Cytoscape DAG with sortable tables and download links. Air-gap safe (vendored cytoscape.min.js OR CDN fallback OR `--no-vendor` Mermaid-only).
- **`report.md`** — GitHub-renderable Mermaid summary (flowchart capped at 50 nodes + truncation pointer to `report.html` for over-cap).
- **`manifest.json`** — per-run metadata (run_id, costs, counters, redaction_count, errors). Validated against `schemas/lineage-manifest.v1.json`.
- **`errors.jsonl`** — per-file extraction failures.

## When to use it

Trigger on these user phrasings:
- "build me a lineage report on /path/to/project"
- "trace data flow through this codebase"
- "where does this dataset come from"
- "extract lineage to OpenLineage format"
- "generate a data flow visualisation"
- "what jobs read/write to this table"

Skip when:
- The user wants RUNTIME lineage (job execution traces) — that's openlineage-spark / openlineage-airflow producers, v2.
- The user wants COLUMN-level lineage — defer to v1.1 (needs schema metadata not available statically).
- The user wants CROSS-REPO lineage — single project root only in v1.
- The user wants BUSINESS / FUNCTIONAL lineage (semantic annotations on jobs) — post-v1 enrichment composing `intent-extract`.

## Architecture (the LLM-driven framework)

The skill is the **framework**, the in-session AI CLI is the **parser**. There are NO per-format AST parsers (`sqlglot` / `tree-sitter` / `xml.sax`) in `scripts/`. The agent's LLM handles arbitrary input formats — Python, SQL, DSX, Control-M, dbt, COBOL, log files — anything in its training coverage. The skill provides:

- **5 model-neutral prompts** in `prompts/*.md` — instructions the agent uses for per-chunk analysis, chunk merging, identity resolution, and redaction.
- **7 deterministic Python scripts** in `scripts/*.py` — chunk_file, accumulate, merge_into_ol, validate_ol, redact, render_report, install_vendor.
- **6 reference docs** in `references/*.md` — OL spec, confidence classifier, dataset identity, output formats, chunking strategy, anti-patterns.
- **3 JSON schemas** in `schemas/` — lineage-finding.v1, lineage-manifest.v1, openlineage-2.0.2-vendored.

Scripts have NO LLM calls. Prompts have NO Python code. The two halves are interoperable across Claude Code / Codex CLI / Antigravity CLI (agy) / Copilot CLI because the prompts are model-neutral (HARD-RULE 8).

## Invocation flow

When a user issues `lineage-extract-static <project_root>` (or equivalent NL: *"build me a lineage report on /path/to/project"*):

```
1. Agent reads this SKILL.md (the orchestration playbook).
2. Agent runs `scripts/chunk_file.py` over the project tree.
   Output: per-file `manifest.json` at ~/.cache/lineage-extract-static/runs/<run_id>/files/<file_sha256>/
   carrying path, sha256, size, line_count, chunked: bool, chunk_count.
3. For each file:
   3a. Small file (<= 5 MB / <= 20k lines) → agent reads the whole file,
       applies `prompts/analyze-file.md`, emits ONE `lineage-finding.v1`
       JSON object to `chunk_0001.jsonl` (single chunk).
   3b. Large file → agent reads chunk-by-chunk (default 2000 lines/chunk
       with 50-line overlap), applies `prompts/analyze-file.md` per chunk,
       writes per-chunk JSONL. Then applies
       `prompts/merge-chunks-within-file.md` to reconcile boundary_status
       markers; agent calls `scripts/accumulate.py` to perform the deterministic
       boundary-pairing predicate (NOT an LLM judgment) and emit the file-level
       rollup at `summary.json`.
4. After all files done, agent applies `prompts/merge-across-files.md`
   to combine per-file rollups + runs `prompts/resolve-identity.md` to
   canonicalize dataset URIs (3-step waterfall: SQL FQN → repo-rel path → alias map).
5. Agent runs `scripts/redact.py` on the combined rollup (fail-closed).
6. Agent runs `scripts/merge_into_ol.py` → emits openlineage.ndjson + openlineage.json
   + lineage_edges.csv to /tmp/lineage-extract-static-<session>/.
7. Agent runs `scripts/render_report.py` → produces report.html + report.md
   + datasets.csv + jobs.csv + edges.csv (the OL-relational opt-in) to same dir.
8. Agent prints the location of the report directory to the user.
```

## CLI flags

```
lineage-extract-static analyze <project_root>
  --output-dir <path>            (default: /tmp/lineage-extract-static-<session>/)
  --include-low-precision        (opt-in for plug-ins with precision_floor < 0.85)
  --output-format=ol-relational  (opt-in for 4-CSV split; default = single denormalized)
  --with-static-run              (opt-in for RunEvent-wrapped compatibility export)
  --merge-by-basename            (advisory speculative-confidence basename matching)
  --no-vendor                    (Mermaid-only output if Cytoscape vendor absent)
  --since <git-ref>              (incremental scan)
  --parallel N                   (per-file ProcessPoolExecutor workers; default = CPU)
  --aliases <path>               (alias map; default .lineage/aliases.yaml)

lineage-extract-static diff <baseline.json> <head.json>
  exit 0 = no breaking changes / exit 1 = datasets removed / exit 2 = jobs removed
```

## HARD-RULEs

1. **Spec-correct OL output, NOT synthesised runs.** Canonical emission is `JobEvent` + `DatasetEvent` with NO `Run` wrapper. `RunEvent` wrapping is opt-in via `--with-static-run` for consumer compatibility only. Phantom runs pollute downstream catalogs (Marquez, Atlan, DataHub).

2. **Bright-line confidence classifier.** Any extraction whose `evidence_snippet` contains f-string syntax, `.format()`, `%`-format, env-var template, OR any symbol the LLM cannot resolve to a literal within the chunk → forced `speculative`. NEVER `grounded` when interpolation/dynamic-resolution is present. Enforced by the prompt template + post-emission validator in `scripts/validate_ol.py`.

3. **Identity waterfall pre-computed, never inferred by LLM.** The 3-step resolution (SQL FQN → repo-root-relative path → alias map) runs in `prompts/resolve-identity.md` BEFORE OL emission. Basename-only merge OFF by default; advisory speculative only when `--merge-by-basename` is explicitly enabled.

4. **Secret redaction is fail-closed.** `scripts/redact.py` runs on every aggregated rollup BEFORE OL emission. Any redaction error = abort, NEVER emit partial. Two-layer redaction: prompt-level (LLM instructed not to emit credentials) + post-LLM (regex-based scrubbing).

5. **Sandbox + cache discipline.** Per-run cache at `~/.cache/lineage-extract-static/runs/<run_id>/` mode `0700` (NEVER `/tmp`). Atomic writes via `.tmp.<pid>` + `os.replace()`. TTL 30 days + LRU eviction at `LINEAGE_CACHE_MAX_GB=10`.

6. **DoS hard caps.** `LINEAGE_HARD_FILE_LIMIT_MB=50` skip-with-warn, `LINEAGE_MAX_DURATION_S=3600` global wall-clock cap, `LINEAGE_CACHE_MAX_GB=10` cache cap. Exit `PARTIAL` (not failure) when caps hit; surface in `manifest.json`.

7. **XSS-safe rendering.** Every user-controlled string (file paths, dataset names, evidence snippets) interpolated into HTML via `html.escape()` server-side + `textContent =` (never `innerHTML =`) client-side. Required test `test_html_escape_hostile_filenames` enforces this. Hostile filenames must NOT execute.

8. **Cross-tool portability.** Prompts in `prompts/*.md` are model-neutral — no Anthropic-specific anchors, no Claude-only facets, no `<>` tags. Tested against Claude Code + Codex CLI + Gemini CLI (pre-retirement) + Copilot CLI; the gemini CLI retired 2026-06-18 — use Antigravity CLI (agy) instead.

## Confidence taxonomy (bright-line classifier)

See `references/confidence-classifier.md` for worked examples. Quick reference:

| Tier | Rule | OL emission |
|---|---|---|
| `grounded` | Literal string token (path/table-name); all symbols resolve in the local context (function args, top-level constants) | Solid edge; feeds gate decisions |
| `inferred` | Name-resolution heuristic — env-var resolved against in-repo `.env` / `config.yaml`; relative path resolved against `__file__`; SQL `FROM <alias>` resolved against same-file CTE | Dashed edge; advisory only |
| `speculative` | String interpolation (f-string / `.format()` / `%`-format / template literal) within ±20 lines; env-var without in-repo resolution; unresolved symbol; `SELECT *` without schema metadata; basename-only match | Dotted edge; collapsed by default in HTML; never feeds gates |

## Identity resolution (3-step waterfall)

See `references/dataset-identity.md` for full rules. Quick reference:

1. **SQL FQN** (highest precedence). `namespace = <db-engine>://<host>:<port>/<db>`, `name = <schema>.<table>`. Default schemas: PostgreSQL `public`, Oracle `<USER>`, Snowflake `<account>.<warehouse>`.
2. **Repo-root-relative absolute path** (filesystem datasets). `realpath` to dereference symlinks. `namespace = file://<repo-root-anchor>`, `name = <repo-relative path>`.
3. **Configurable alias map** (`.lineage/aliases.yaml`, optional). Resolves DSN strings, NFS mount mirrors, etc., to canonical URIs.

Basename-only merge is OFF by default. Behind `--merge-by-basename` flag (advisory), basename matches emit edges with `confidence: speculative` + `possible_alias` facet linking candidates — NEVER silently merged.

## Output layout

```
/tmp/lineage-extract-static-<session>/
├── openlineage.ndjson          ← canonical OL stream (JobEvent + DatasetEvent per line)
├── openlineage.json            ← derived bundle {"events": [...]}
├── lineage_edges.csv           ← single denormalized CSV (default)
├── datasets.csv                ← OL-relational opt-in
├── jobs.csv                    ← OL-relational opt-in
├── edges.csv                   ← OL-relational opt-in
├── runs.csv                    ← OL-relational opt-in (only when --with-static-run)
├── manifest.json               ← per-run metadata (validated against lineage-manifest.v1)
├── errors.jsonl                ← per-file extraction failures
├── report.md                   ← Mermaid summary
└── report.html                 ← Cytoscape DAG + sortable tables + download links
```

## Anti-patterns — STOP if you catch yourself

- **Emitting `Run` by default** — canonical OL spec for static lineage is JobEvent + DatasetEvent ONLY. RunEvent is opt-in (`--with-static-run`).
- **Inferring `grounded` confidence when evidence has f-string / `.format()` / `%`-format** — these are forced `speculative`. HARD-RULE 2.
- **Merging datasets by basename alone** — basename-only merge is OFF by default. When `--merge-by-basename` is enabled, the match still gets `confidence: speculative` + `possible_alias` facet.
- **Writing to `/tmp` for the run cache** — `~/.cache/lineage-extract-static/runs/<run_id>/` mode 0700 ONLY. HARD-RULE 5.
- **Emitting partial output after a redaction error** — `scripts/redact.py` is fail-closed. Any error aborts the run. HARD-RULE 4.
- **Synthesising a `Run` "for compatibility" without the user asking** — `--with-static-run` is OPT-IN. Synthesising on every run pollutes catalogs.
- **Building per-format parsers in `scripts/`** — the LLM is the parser. v1 has NO `sqlglot` / `tree-sitter` / `xml.sax` plug-ins. If accuracy is insufficient for a specific format, add a deterministic plug-in in v1.1 against a frozen contract.
- **Hard-coding file extensions** — chunk_file.py is format-agnostic (just I/O); the LLM decides which formats it can extract from. Unsupported formats produce `gap: language_unsupported` entries.

## Cross-tool portability

Prompts in `prompts/*.md` are tested against all four AI CLIs:
- Claude Code (Claude Opus 4.7)
- Codex CLI (GPT-5.4)
- Antigravity CLI (agy) — replaces Gemini CLI, retired 2026-06-18
- Copilot CLI (GPT-5.4 backend)

Run `~/.claude/skills/research-for-skills/cross-tool-portability/scripts/verify-skill-portability.sh` to confirm. HARD-RULE 8.

## Composition with other skills

- `wiring-extract-static` — produces source-code call graph; lineage-extract-static can use wiring snapshots to enrich job-to-job depends_on edges (v1.1 enhancement).
- `intent-extract` — adds per-job functional intent annotations (post-v1 enrichment for business / functional lineage).
- `intent-map-render` — dual Mermaid + Cytoscape rendering precedent reused for `scripts/render_report.py`.
- `visual-companion` — Cytoscape vendor templates extended at WP-7 (`scripts/install_vendor.sh`).
- `dep-currency-check` — confidence_level pattern precedent (grounded / inferred / speculative).

## See also

- `references/openlineage-spec-2.0.2.md` — what to emit, with worked examples
- `references/confidence-classifier.md` — bright-line grounded/inferred/speculative rules
- `references/dataset-identity.md` — 3-step waterfall codified pre-code
- `references/output-formats.md` — OL JSON + CSV + HTML + Mermaid contract
- `references/chunking-strategy.md` — two-phase + boundary_status reconciliation
- `references/anti-patterns.md` — synthetic Run, basename merge, scope creep

## Security — XML / XHTML parsing

<HARD-RULE>
When parsing any XML or XHTML payload from a remote API, untrusted file, or user-supplied source, NEVER use stdlib `xml.etree.ElementTree`, `xml.dom.minidom`, or `lxml.etree.fromstring` without XXE protection. Use `defusedxml` (`pip install defusedxml`) and replace `xml.etree.ElementTree` → `defusedxml.ElementTree`, `lxml.etree` → `defusedxml.lxml`. Stdlib XML parsers expand external entities by default and are vulnerable to billion-laughs / XXE / DTD-retrieval / SSRF-via-entity attacks (CWE-611). Local skill applicability:
- API payloads that may legitimately be XML (storage format, error responses)
- Imported / exported workflow files
- Bulk import / migration paths
</HARD-RULE>

For HTML/XHTML rendering of downstream output (storage format → display), sanitise with `bleach` or `nh3` BEFORE inserting into a browser context — never raw-render API-returned XHTML. See `llm-security` SKILL.md §4.4 for context-appropriate escaping rules.

