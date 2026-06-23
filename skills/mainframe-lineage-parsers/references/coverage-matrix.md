# Lineage coverage matrix — scheduler × language × engine (design §8)

This shared reference makes explicit **which estate surfaces are covered by the
DETERMINISTIC engine (`mainframe-lineage-parsers`, no-LLM, stdlib) vs the
LLM-as-parser engine (`lineage-extract-static`)**. Both engines emit OpenLineage
2.0.2 ndjson over the same naming discipline (`references/naming-contract.md`), so
you run the relevant engine per surface and compare the outputs yourself (there is
**no comparison / diff / scoring harness in scope** — decision A).

The language here is model-neutral: the deterministic engine runs the same way
regardless of which CLI host invokes it (Claude Code, Codex CLI, Copilot CLI,
Antigravity CLI). There is **no LLM in the deterministic loop, ever**.

---

## Engine legend

- **DET** — `mainframe-lineage-parsers`: deterministic, pure stdlib (+ optional
  `sqlglot`/`networkx`), byte-identical re-runs, NO LLM ever.
- **LLM** — `lineage-extract-static`: the LLM-as-parser flow (temperature-0
  extraction; judgment-dependent; the engine for grammars the deterministic track
  does not cover).
- **—** — not covered by either engine in v1 (a documented non-goal).

---

## Scheduler layer

| Scheduler | DET (`mainframe-lineage-parsers`) | LLM (`lineage-extract-static`) | Notes |
|---|---|---|---|
| **JCL** (`//JOB`, `//EXEC`, PROC/symbol expansion) | ✅ `jcl_extract.py` | ✅ (fallback) | DET is the canonical path; DD-join stitch to COBOL. |
| **Control-M** (Automation-API jobs-as-code JSON) | ✅ `controlm_extract.py` | ✅ (selectable) | DET added in this cycle (design §3). `Job:Command/Script/FileTransfer/Database:*/Dummy` mapped; `Job:EmbeddedScript` body opaque → diagnostic only (LLM path). Job→job event DAG. |
| **cron / shell-stream** (`crontab`, `.sh` driver scripts) | — (optional deterministic later) | ✅ | LLM-only in v1. A deterministic cron/`.sh` extractor is a possible future addition (out of v1 scope, design §11). |
| **other schedulers** (Autosys, TWS/IWS, Airflow…) | — | ✅ (best-effort) | LLM-only. |

---

## Language layer

| Language | DET (`mainframe-lineage-parsers`) | LLM (`lineage-extract-static`) | Notes |
|---|---|---|---|
| **COBOL (fixed-format)** | ✅ `cobol_extract.py` | ✅ (fallback) | DET canonical; `SELECT…ASSIGN TO ddname`, FD records, READ/WRITE. |
| **COBOL (free-format)** | — (`gap: free_format_unsupported`) | ✅ | DET emits the typed gap + the documented handoff; free-format is the LLM path. |
| **Embedded `EXEC SQL` (DB2)** | ✅ `sql_extract.py` | ✅ | DET: literal table edges grounded; host-var→column advisory-until-gold. |
| **Dynamic SQL** (`EXECUTE IMMEDIATE` / `PREPARE`) | — (flagged, not extracted) | ✅ | DET flags it; the statement text is a host-var → LLM path. |
| **non-DB2 SQL dialects** | — | ✅ | LLM-only. |
| **Pick / MultiValue** | — | ✅ | **LLM-only** (no grammar). `legacy-code-intel` for symbols, `pick-developer` for source. |
| **Java** | — (out of the stdlib-only / no-JVM engine by design D1) | ✅ | **LLM-only.** `java-backend` / `java-frontend` for symbols + source. |

---

## Facet coverage (both engines emit, OpenLineage 2.0.2 core pinned)

| Facet | DET | LLM | Notes |
|---|---|---|---|
| `mainframeLineage` (custom: kind + confidence + provenance) | ✅ | n/a | DET-only confidence facet. |
| standard **`columnLineage` (1-2-0)** | ✅ | ✅ (consumes same facet) | host-var→column; `INDIRECT`/`CONDITIONAL`. Both streams speak `columnLineage 1-2-0`. |
| custom **`controlmDependencies`** JOB facet | ✅ | n/a | static design-time scheduling deps; field names mirror `JobDependenciesRunFacet` (NOT a Run facet). |
| standard **`sourceCodeLocation.contentSha256`** JOB facet | ✅ | ✅ | the v1.1 JOB↔artifact join key. **Byte-identical definition across both engines** (raw on-disk bytes, pre-expansion, no encoding normalization). |
| **OpenLineage core spec object** | `2-0-2` | `2-0-2` | pinned; NOT bumped (live-verified current). |

---

## How to choose

1. **Deterministic surface (JCL / Control-M / fixed COBOL / DB2 SQL)** → run the
   DET engine (`mainframe-lineage-parsers`) — reproducible, no-model, CI-safe.
2. **LLM-only surface (Pick, Java, free-format COBOL, dynamic SQL, cron/shell,
   other schedulers)** → run the LLM engine (`lineage-extract-static`).
3. **Mixed estate** → run both, compare the two ndjson streams yourself (distinct
   producer URIs make the diff clean).

See also:
- `references/naming-contract.md` — the frozen shared naming discipline (incl. the
  Control-M §2a identity + §5 gap rows).
- `references/decision-framework.md` — when to use DET vs LLM vs hybrid.
- `gold/expected-edges.yaml` / `gold/expected-controlm-edges.yaml` — the advisory
  precision oracles.
