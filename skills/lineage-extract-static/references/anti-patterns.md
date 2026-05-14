# Anti-Patterns — STOP If You Catch Yourself

Reference for `lineage-extract-static`. These patterns lead to bad lineage that pollutes downstream catalogs, breaks gates, or violates HARD-RULEs. Every item below is mechanically tested where possible.

## 1. Emitting `Run` by default

**HARD-RULE 1 violation.** The canonical OL output for static lineage is `JobEvent + DatasetEvent` with NO `Run` wrapper. Phantom runs pollute downstream catalogs (Marquez, Atlan, DataHub) — they fill the runs table with synthetic entries that aren't actual job executions.

```
# WRONG (don't do this by default)
{"eventType": "START", "run": {"runId": "..."}, "job": {...}, "inputs": [...]}

# RIGHT
{"eventType": "JOB_EVENT", "job": {...}, "inputs": [...]}
{"eventType": "DATASET_EVENT", "dataset": {...}}
```

When a downstream consumer requires RunEvents, use `--with-static-run` (opt-in). The synthesized runId is deterministic (`uuid5(workspace_tree_hash + scan_started_at)`) so re-runs don't multiply rows.

## 2. Inferring `grounded` confidence on dynamic-resolution evidence

**HARD-RULE 2 violation.** If `evidence_snippet` contains ANY of:
- `f"..."` or `f'...'` Python f-string
- `.format()` call
- `%`-format (`"... %s" % var`)
- `${...}` shell/env template
- `{{ ... }}` Jinja/Handlebars template

→ the edge MUST be `speculative`. NEVER `grounded`. Even if you're 99% sure the dynamic value resolves to a literal at runtime, the static analysis cannot prove it.

```
# WRONG
{"confidence": "grounded", "confidence_reason": "f-string with literal default"}

# RIGHT
{"confidence": "speculative", "confidence_reason": "f-string interpolation"}
```

The post-emission validator in `scripts/validate_ol.py` enforces this.

## 3. Merging datasets by basename alone

Two datasets with the same basename but different paths/namespaces are DIFFERENT datasets:

- `file://my-pipeline/data/landing/users.csv`
- `s3://acme-data/landing/users.csv`

These represent different storage tiers. Silently merging them by basename produces wrong lineage.

When `--merge-by-basename` is explicitly enabled, the renderer adds an ADVISORY edge with `confidence: speculative` and a `possible_alias` facet linking the candidates. The original two datasets remain distinct in the OL output. NEVER silently merged.

The user-facing alias map (`.lineage/aliases.yaml`) gives precise control over canonical mappings:

```yaml
aliases:
  - canonical: {namespace: "s3://acme-data", name: "landing/users.csv"}
    matches:
      - "/mnt/landing/users.csv"   # NFS mount mirror
```

## 4. Writing to `/tmp` for the run cache

**HARD-RULE 5 violation.** The per-run cache MUST live at `~/.cache/lineage-extract-static/runs/<run_id>/` mode `0700`. NEVER under `/tmp`.

Reasons:
- `/tmp` is world-readable on many systems (security: lineage may include path names of sensitive datasets).
- `/tmp` is volatile across reboots; the cache should persist for warm reruns.
- `/tmp` has size limits on tmpfs configurations.

Atomic writes via `.tmp.<pid>` + `os.replace()`. Same convention as S028 ledger discipline.

## 5. Emitting partial output after a redaction error

**HARD-RULE 4 violation.** `scripts/redact.py` is fail-closed. Any error during redaction MUST abort the run with a non-zero exit code. NEVER emit partial output that might contain unscrubbed credentials.

Two-layer redaction (prompt-level + script-level regex) reduces the chance of a credential leak, but if EITHER layer fails to apply a pattern cleanly, abort. Trust nothing.

## 6. Synthesising a `Run` "for compatibility" without the user asking

`--with-static-run` is OPT-IN for a reason. Synthesising on every run pollutes catalogs and trains users to ignore the runs table. Make the user opt in deliberately, then explain the consequence (phantom rows in Marquez).

## 7. Building per-format parsers in `scripts/`

The LLM is the parser. v1 has NO `sqlglot` / `tree-sitter` / `xml.sax` plug-ins in `scripts/`. If accuracy is insufficient for a specific format (e.g. complex SQL with CTEs), the right fix is:

- **First**: improve `prompts/analyze-file.md` with better examples for that format.
- **Second**: add a deterministic plug-in in v1.1 against a frozen contract.

Never bloat `scripts/` with format-specific parsing logic. The "framework, not parser" architecture is the entire point of the LLM-driven design.

## 8. Hard-coding file extensions in chunk_file.py

`scripts/chunk_file.py` is pure I/O — it does NOT parse files. The LLM decides which formats it can extract from. The extension-based `language_hint` is a hint only; the LLM is free to emit `gap: language_unsupported` for any chunk it can't extract from.

If the chunker were extension-bound, adding a new format would require a code change. With LLM-driven extraction, adding a new format just means adding worked examples to `prompts/analyze-file.md`.

## 9. Letting `evidence_snippet` exceed 1024 chars

The `lineage-finding.v1` schema caps `evidence_snippet` at 1024 chars. Beyond that, the snippet stops being useful (it's not a code review tool; it's a lineage extractor). The LLM is instructed to truncate with `…` when the relevant statement exceeds 1024 chars.

Long snippets also bloat the OL ndjson, slowing downstream catalog ingestion.

## 10. Emitting edges from import statements alone

```python
import pandas as pd
```

This is NOT a lineage edge. The import says "this script uses pandas", which is a dependency, not a data flow. Only emit edges when the code actually performs I/O (read, write, schedule, depend).

The LLM is told this in `prompts/analyze-file.md`, but it's easy to forget when looking at import-heavy modules. If a chunk contains only imports and no I/O calls, emit `edges: []`.

## 11. Speculating about what a function call MIGHT do

```python
result = some_unknown_function(path)
```

If `some_unknown_function` is not visible in the chunk, the LLM cannot extract a confident edge. Emit `gap: unresolved_symbol` rather than guessing `reads_from` or `writes_to`.

The LLM might be tempted to extrapolate ("`process_data` sounds like it reads then writes"). RESIST. Static analysis is fundamentally lossy on opaque functions.

## 12. Putting credentials in `evidence_snippet`

**HARD-RULE 4 prompt-level enforcement.** The LLM is told to substitute `<REDACTED:reason>` for any credentials it sees in source code. The post-LLM `scripts/redact.py` provides a second pass. If BOTH layers miss it, the credential leaks into `openlineage.ndjson` — a security issue.

The LLM's first-pass redaction is the cheap insurance; `redact.py` is the expensive belt. Both run.

## 13. Using `os.system()`/`subprocess.call()` style mutability in scripts

All Python scripts in `scripts/` are deterministic helpers. They MUST NOT make external network calls, fork subprocesses for arbitrary execution, or alter global state outside their own cache directory.

The only legitimate external touchpoint is `scripts/install_vendor.sh`, which is a one-time setup helper, not part of the runtime analyze flow.

## 14. Emitting non-deterministic output

`scripts/merge_into_ol.py`, `scripts/render_report.py`, and `scripts/accumulate.py` all promise byte-identical output on re-run with identical inputs. To preserve this:

- Sort lists before emission (edges, gaps, datasets, jobs).
- Use `json.dumps(..., sort_keys=True)` for JSON output.
- Honor `SOURCE_DATE_EPOCH` for timestamps when set.
- Never use `time.time()` or `uuid.uuid4()` for the canonical output (use `uuid.uuid5()` with a deterministic seed instead, as merge_into_ol does for synthetic runIds).

The determinism guarantee is what makes git-tracked OL output diffable across PRs.

## 15. Scope creep into runtime / column-level lineage

v1 is STATIC, TABLE-LEVEL only. Out-of-scope for v1:

- Column-level lineage (defer to v1.1; needs schema metadata).
- Runtime producers (Spark/Airflow/dbt SDK — that's v2).
- Cross-repo lineage (single project root only in v1).
- Cross-environment identity (dev/staging/prod — needs alias manifests, v1.5).
- Real-time / streaming (OL runtime producers cover this better, v2).
- Functional / business lineage (post-v1 enrichment composing `intent-extract`).
- Web UI / interactive backend (resist Marquez-envy; static HTML only).
- Direct catalog ingestion (Marquez API push, Atlan webhook — emit OL ndjson, let users feed their own catalogs).

When a user asks "can we add X?", check this list first. If X is here, decline politely and point to the v1.5/v2 roadmap.

## 16. Cross-tool portability slip

**HARD-RULE 8 violation.** Prompts in `prompts/*.md` MUST be model-neutral:

- No `<system>`/`<user>`/`<assistant>` tags
- No `<thinking>` blocks
- No Anthropic-specific facets ("here are your tools:")
- No Claude-only references ("you are Claude")

Tested by `~/.claude/skills/cross-tool-portability/verify-skill-portability.sh`. The prompts must work for Claude Code, Codex CLI, Gemini CLI, and Copilot CLI equivalently.
