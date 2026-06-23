---
name: mainframe-lineage-parsers
description: "Use when you want a STANDALONE, RUNNABLE, DETERMINISTIC (no-LLM) data-lineage extractor for legacy mainframe code — fixed-format COBOL + JCL + embedded EXEC SQL (DB2) -> OpenLineage 2.0.2 ndjson. The sanctioned deterministic v1.1 plug-in track under lineage-extract-static (a COMPLEMENT, not a replacement, of the LLM-as-parser family): run THIS deterministic flow and the LLM flow separately and compare yourself (NO comparison/diff harness in scope). Pure stdlib + OPTIONAL sqlglot (regex fallback, NO silent LLM fallback) + OPTIONAL networkx. Fully non-interactive CLI (run_lineage.py): all inputs are flags, zero prompts, scriptable in CI/cron, fail-loud handoff when deps absent. Static analysis only (v1). The mainframe sibling of lineage-extract-static (flow), structure-recovery (shape), legacy-code-intel (symbols). Also handles deterministic Control-M Automation-API jobs-as-code (scheduler->program->data lineage, job->job event DAG, the scheduler->program stitch). Also trigger on \"deterministic mainframe lineage\", \"COBOL/JCL/DB2 lineage\", \"EXEC SQL lineage\", \"OpenLineage from mainframe\", \"DD-join lineage\", \"host-var to column lineage\", \"Control-M lineage\", \"Control-M jobs-as-code lineage\", \"scheduler lineage\"."
---

# mainframe-lineage-parsers — deterministic COBOL/JCL/DB2 lineage extractor

Design at `docs/plans/2026-06-16-mainframe-lineage-parsers-design.md`.

## What it does

Reads fixed-format COBOL, JCL (incl. PROC/symbol expansion), embedded
`EXEC SQL` (DB2), and **Control-M Automation-API jobs-as-code JSON**, and emits
**OpenLineage 2.0.2 ndjson** describing the data lineage — entirely
**deterministically, with NO LLM in the loop, ever** (C2).
Re-running with the same inputs produces a **byte-identical** `ndjson` (the
emitter sorts keys and uses a fixed default `eventTime`; set `SOURCE_DATE_EPOCH`
for a reproducible non-default `eventTime`).

The pipeline (design §3):

```
preprocess        — source-format detect (fixed v1; free -> gap), col 8-72 strip,
                    comment/continuation folding, EXEC SQL block split
  -> copybook_resolver  — COPY ... REPLACING resolution over --copybook-path
    -> jcl_extract / cobol_extract / sql_extract / controlm_extract  — 4 extractors, ONE internal IR
      -> graph_assemble   — networkx-or-stdlib canonical sort + dedupe + DDNAME stitch
        -> openlineage_emit — IR -> OL 2.0.2 ndjson (extractor_id, engine,
                              confidence/provenance + columnLineage / controlmDependencies
                              / contentSha256 facets)
```

Output is one `JobEvent` / `DatasetEvent` per line, each carrying
`extractor_id=mainframe-lineage-parsers`, the SQL `engine` actually used, and
**confidence/provenance facets** (`grounded` / `inferred` / `speculative`) plus
explicit **gaps** (`unresolved_copy`, `free_format_unsupported`, `symbolic_dsn`,
`catalog_less_column`, and the Control-M `unresolved_variable`,
`unresolved_connection`, `runtime_path`, `unresolved_event_dep`). Gaps are normal
output — they are diagnostics, never a blocking question.

## Purpose — testing & comparison (NO comparison harness in scope)

This skill is the sanctioned **deterministic v1.1 plug-in track** under the
`lineage-extract-static` anti-pattern #7 — a **complement, not a replacement**,
of the LLM-as-parser family. The intended workflow is:

1. Run **this** deterministic flow over a mainframe estate.
2. Run the **LLM-as-parser** flow (`lineage-extract-static`) over the same estate
   separately.
3. **Compare the two outputs yourself.**

There is **NO comparison / diff / scoring harness in scope** (decision A): the
skill produces lineage; you do the comparison. The two flows deliberately use
**distinct producer URIs** so their `ndjson` is easy to diff side by side.

## When to use it

- You have legacy **fixed-format COBOL + JCL + embedded `EXEC SQL` (DB2)** and you
  want **reproducible, no-model** lineage you can re-run in CI/cron and trust to
  be byte-identical.
- You want a **deterministic baseline** to compare against the LLM-as-parser
  lineage flow.
- You need the **two precision-win edge classes** — JCL `DD`/`DSN` -> `DDNAME`
  bind-key stitch to the COBOL `SELECT ... ASSIGN TO`, and embedded-SQL
  host-variable -> `table.column` — with honest confidence/provenance facets.

NOT for (non-goals — explicit diagnostics, not silent best-effort, design §8):
**Pick/MultiValue** (no grammar — use `lineage-extract-static` for the LLM lineage path,
`legacy-code-intel` for symbols, `pick-developer` for reading the source);
**Java** (not mainframe legacy, and outside this stdlib-only / no-JVM engine by design
D1 — use `lineage-extract-static` for Java lineage, `legacy-code-intel` /
`java-backend` / `java-frontend` for symbols + source);
**free-format COBOL** (`gap: free_format_unsupported`); **dynamic SQL**;
**CICS/IMS/VSAM-internal/GDG-temporal** semantics beyond dataset identity;
**full field-level dataflow**; **non-DB2 SQL dialects**;
**Control-M `Job:EmbeddedScript` inline bodies** (opaque — a job node + diagnostic
only, NOT parsed; that is the LLM path); **cron / shell-stream schedulers** (still
LLM-only — optional deterministic later); the **L3 functional-fusion view**
(deferred to v1.1).

## Engine flag, sqlglot-optional, regex fallback — NO silent LLM fallback

The SQL extractor has two deterministic engines and **never** falls back to a
model (C2):

- `--engine auto` (default) — use `sqlglot` if importable, else the stdlib
  **regex** engine (with an `sql.engine_degraded` diagnostic, lower SQL
  precision, never a failure).
- `--engine regex` — force the stdlib regex engine.
- `--engine sqlglot-sql` — **require** `sqlglot`; if it is absent the CLI exits
  **2** and prints a **fail-loud handoff** pointer ("for the LLM-as-parser path
  use `lineage-extract-static`"). A model is **never** auto-invoked.

`sqlglot` and `networkx` are both **optional, import-if-present**. There is **no
pip install at runtime**, **no new mandatory dependency**, **no network/egress**,
and **no shell beyond `python3`** (design §11.2 / D1).

## Confidence / provenance facets & advisory-until-gold host-var edges

Every edge carries a confidence facet:

- **`grounded`** — literally present in the source (e.g. a literal `DSN=` in JCL,
  a `table` named in `EXEC SQL`).
- **`inferred`** — derived by a documented rule (e.g. the DD-join stitch bridge;
  a host-var -> column binding resolved with `--schema`).
- **`speculative`** — best-available but unverified (e.g. a host-var -> column
  edge with **no** `--db2-catalog`/`--schema`, which also emits a
  `catalog_less_column` gap).

The two **precision-win edge classes** (DD-join, host-var -> column) are
**advisory until a `gold/` fixture clears a precision bar** (#158): they are for
human review and comparison, and **never feed a gate** — there is no `G_*`, no
`INTEGRATED -> VERIFIED` arc, and no CI hard-block driven by them. See
[`gold/README.md`](gold/README.md).

## Control-M scheduler lineage (deterministic; design §3)

The skill also extracts **deterministic lineage from Control-M Automation-API
jobs-as-code JSON** — a structural twin of the JCL extractor, parsed with stdlib
`json` only (no LLM, no new dep). It augments the **scheduler** layer; it does not
touch COBOL/SQL extraction.

**Flags:**

- `--controlm <path>` — a Control-M jobs-as-code JSON file (repeatable).
  **Explicit-flag-authoritative**: files passed here are forced `kind=controlm`
  and **bypass the COBOL/JCL classifier** (a Control-M `.json` is neither a JCL nor
  a COBOL suffix). This is the **canonical, documented** Control-M invocation. As a
  convenience only, a `.json` passed via `--src` that carries a `"Type": "Job:"`
  leaf is sniffed and tagged `controlm` ahead of the COBOL fallback.
- `--controlm-connection-profiles <json>` — a JSON object (inline or a file path)
  mapping `profile_name -> {host,port,db,schema}` (the Control-M analogue of
  `--db2-catalog`). A `Job:Database` edge resolves to a real DB2 table node **only**
  when its `ConnectionProfile` is present here **and** the SQL is literal; otherwise
  the edge is forced `speculative` + a gap.

**Job-type coverage (design §3 table):**

| `Type` | Emission |
|---|---|
| `Job:Command` | `argv[0]` → program node `mainframe://<program-id>` (program-id = basename of argv[0], extension stripped, **upper-folded** — the locked stitch key that collides with the COBOL upper-folded `PROGRAM-ID`); bind `kind=inferred` (cross-artifact name bind, never grounded) |
| `Job:Script` | `FileName`+`FilePath` → script artifact edge (`grounded` when both literal) |
| `Job:EmbeddedScript` | job node + diagnostic only — the inline body is **opaque** (NOT parsed; LLM path) |
| `Job:FileTransfer` | `Src`→job (read) + job→`Dest` (write) file edges; an `AssignFileNameToVariable` runtime watched name → `speculative` + `runtime_path` gap |
| `Job:Database:*` | DB2-style table edges only if the SQL is literal AND the `ConnectionProfile` resolves; else `speculative` + gap |
| `Job:Dummy` | DAG node only (a scheduling placeholder) |

**Job→job DAG:** `eventsToAdd` (Out) raised by job A and `eventsToWaitFor` (In)
awaited by job B are matched on the event-name string → an A→B dependency edge,
resolved deterministically across the folder set.

**Case-sensitivity divergence (naming-contract §2a):** Control-M `<folder>` and
`<jobname>` are **case-sensitive** and are **NOT upper-folded** (Control-M treats
case-variant names as distinct jobs). Only the program-id side of the
scheduler→program edge is upper-folded so it still collides onto the COBOL node.

**New gap kinds (naming-contract §5):** `unresolved_variable` (a `%%VAR`
unresolved after `Variables` substitution), `unresolved_connection` (a
`ConnectionProfile` absent from the map), `runtime_path` (a `%%`-interpolated /
runtime-assigned path), `unresolved_event_dep` (an `eventsToWaitFor` with no
in-scope producer). All four are `speculative` — never an invented binding (C3).

**New OpenLineage facets (additive; OL core stays pinned at 2-0-2):**

- standard **`columnLineage` (1-2-0)** on the output table dataset for
  host-var→column edges (`INDIRECT`/`CONDITIONAL` transformations; the custom
  `mainframeLineage` confidence facet stays alongside);
- custom **`controlmDependencies`** JOB facet (static design-time scheduling deps;
  field names mirror `JobDependenciesRunFacet` for a future Run-stream migration —
  it is **NOT** a Run facet);
- standard **`sourceCodeLocation.contentSha256`** JOB facet (the v1.1 join key) —
  `contentSha256` = sha256 of the **raw on-disk source bytes, pre-copybook-
  expansion / pre-symbol-substitution, no encoding normalization** (byte-identical
  to the `lineage-extract-static` definition so the future JOB↔artifact join holds).

**Run it (three-way modes):**

```bash
# Control-M only
python3 scripts/run_lineage.py --controlm jobs.json --out lineage.ndjson

# Control-M + DB2 connection profiles
python3 scripts/run_lineage.py --controlm jobs.json \
  --controlm-connection-profiles profiles.json --out lineage.ndjson

# Control-M + COBOL/JCL in one estate (the scheduler→program stitch collides
# GOLDPAY.sh onto the COBOL PROGRAM-ID GOLDPAY)
python3 scripts/run_lineage.py \
  --controlm jobs.json --src cobol_and_jcl/ --out lineage.ndjson
```

## The three ways to run it (design §11)

### 1. Interactive front-loaded-inputs flow

When invoked conversationally, gather **all inputs and the required permissions
ONCE at the start**, confirm once, then hand off to the non-interactive CLI with
**zero further prompts**:

1. Ask for the inputs up front (one round):
   - `--src` — source root(s) / file(s) / glob(s) for COBOL/JCL (repeatable;
     at least one of `--src` / `--controlm` is required)
   - `--controlm` — Control-M jobs-as-code JSON file(s) (repeatable;
     explicit-flag-authoritative — forces `kind=controlm`)
   - `--controlm-connection-profiles` — JSON object/file: `profile -> {host,port,db,schema}`
   - `--copybook-path` — copybook search dir(s) for `COPY` resolution (repeatable)
   - `--jcl-proc-path` — JCL PROC/INCLUDE lib dir(s) (repeatable)
   - `--out` — OpenLineage `ndjson` output path (required)
   - `--engine` — `auto` (default) | `regex` | `sqlglot-sql`
   - `--source-format` — `fixed` (v1 default; `free` -> gap)
   - `--db2-catalog` / `--schema` — optional, for host-var -> column resolution
     (absent -> column edges `speculative` + `catalog_less_column` gap)
   - `--copybook-missing` — `gap` (default) | `fail`
2. **Surface the allow-list ONCE and confirm:**
   > This run needs: **read** `<src>` + `<copybook-path>` + `<jcl-proc-path>`,
   > **write** `<out>`. **NO network, NO shell beyond `python3`, NO pip install.**
3. After the single confirmation, **run `run_lineage.py` to completion with zero
   further questions.** Gaps (unresolved copybook, free-format, symbolic DSN,
   catalog-less column) become diagnostics / `speculative` edges — never a
   mid-run prompt.

### 2. Direct headless path — truest automation (bypasses this instructions file)

The engine is pure deterministic Python, so full automation needs **no model, no
SKILL.md, no LLM** at all. Invoke the CLI directly — scriptable in CI / cron /
batch:

```bash
python3 skills/mainframe-lineage-parsers/scripts/run_lineage.py \
  --src /path/to/cobol_and_jcl \
  --copybook-path /path/to/copybooks \
  --jcl-proc-path /path/to/proclib \
  --out /tmp/lineage.ndjson \
  --engine auto < /dev/null
```

All inputs are flags; the CLI **never reads stdin and never asks a question**.
A machine-readable JSON summary is printed on **stdout**; diagnostics go to
**stderr**. Exit codes:

| Exit | Meaning |
|------|---------|
| `0`  | success (even with gaps — gaps are normal output) |
| `1`  | fatal: no usable input, unreadable `--src`, or fail-closed emit/validation |
| `2`  | fail-loud handoff: `--engine=sqlglot-sql` but `sqlglot` is absent (no model auto-invoked) |
| `3`  | `--copybook-missing=fail` and an unresolved `COPY` remained |

This direct path is **model-neutral**: Claude Code, Codex CLI, Copilot CLI, and
the Antigravity CLI (`agy`) can all invoke the same CLI (library rule).

### 3. Claude-orchestrated headless path (`claude -p`)

To run unattended through an AI CLI's permission layer:

```bash
claude -p "run mainframe-lineage-parsers: \
  --src /path/to/cobol_and_jcl \
  --copybook-path /path/to/copybooks \
  --out /tmp/lineage.ndjson" \
  --dangerously-skip-permissions < /dev/null
```

**Security caveat — `--dangerously-skip-permissions`:** this flag auto-approves
the read/write allows so the run never stops on a prompt, but it **bypasses ALL
permission gating**. Use it **only in trusted / CI sandbox contexts**, and
**scope the run to a known tree** (a checked-out repo or a copied estate) so an
unattended run cannot touch anything outside the intended source + output paths.
For a manually-supervised run, prefer path 1 or the direct path 2.

## Copy-paste headless example

A complete, runnable example over the shipped `gold/` precision fixtures
(`--schema PAYROLL` resolves the host-var -> column edges to `inferred`):

```bash
python3 skills/mainframe-lineage-parsers/scripts/run_lineage.py \
  --src skills/mainframe-lineage-parsers/gold/cobol/GOLDPAY.cbl \
  --src skills/mainframe-lineage-parsers/gold/jcl/GOLDPAY.jcl \
  --out /tmp/goldpay.ndjson \
  --schema PAYROLL < /dev/null
# -> exit 0; prints a JSON summary on stdout (events_emitted, job_events,
#    dataset_events, engine, gaps, ...); writes /tmp/goldpay.ndjson.
```

Without `--schema` / `--db2-catalog`, the same run still exits `0` but the
host-var -> column edges are forced `speculative` and a `catalog_less_column`
gap is emitted per unresolved column — honest, never guessed.

## Dependencies & environments (CLI / VS Code end users)

The **core is pure stdlib and always runs** — Control-M/COBOL/JCL/EXEC-SQL
extraction, the IR, and OpenLineage 2.0.2 ndjson need **zero** third-party
packages. The libraries in `requirements-optional.txt` are **OPTIONAL enhancers**
(import-if-present, graceful degradation); this skill **never pip-installs at
runtime** (D1 / air-gap invariant).

**See your situation first — the doctor never installs anything:**

```bash
python3 scripts/run_lineage.py --check-deps   # or: python3 scripts/check_deps.py
```

It prints the **active interpreter**, which enhancers are present/missing, exactly
what degrades when one is absent, a **PEP-668-safe** install recipe, and — if it
finds a sibling interpreter that already has the deps — points you at it.

| Enhancer | Unlocks | If absent |
|---|---|---|
| `jsonschema` | write-time OL 2.0.2 schema validation | emit runs unvalidated |
| `sqlglot` | higher-precision EXEC SQL | stdlib regex engine (lower precision) + `sql.engine_degraded` diagnostic |
| `networkx` | graph assembly via networkx | stdlib fallback (same output, slower on huge estates) |

**Install (only if you want the enhancers).** Modern distros mark the system
`python3` **PEP-668 externally-managed**, so a bare `pip install` is BLOCKED —
use one of:

```bash
# Recommended — PEP-668-safe project venv (CLI or VS Code):
python3 -m venv .venv && .venv/bin/pip install -r requirements-optional.txt
.venv/bin/python scripts/run_lineage.py --controlm jobs.json --out out.ndjson

# Per-user (where allowed):   python3 -m pip install --user -r requirements-optional.txt
# Last resort (system py):    python3 -m pip install --break-system-packages -r requirements-optional.txt
# Air-gapped (offline wheels): python3 -m pip install --no-index --find-links=<wheel-dir> -r requirements-optional.txt
```

**VS Code:** select the venv interpreter (`.venv/bin/python`) as the workspace
interpreter, or point the integrated terminal at it — the skill runs under whatever
`python3` the CLI/extension invokes, so an env without `sqlglot` silently uses the
regex engine. Run `--check-deps` in the integrated terminal to confirm which
interpreter is active.

## References

- [`references/naming-contract.md`](references/naming-contract.md) — the frozen
  shared naming contract (C1): DB2 / JCL job / COBOL program / dataset DSN
  canonicalisation, DDNAME bind keys, determinism rules, and the frozen gap set.
  Parity is asserted **output-vs-FROZEN-CONTRACT**, never output-vs-live-LLM.
- [`references/preprocessing.md`](references/preprocessing.md) — the deterministic
  stdlib preprocessing recipe (kept in lockstep with `scripts/preprocess.py`).
- [`references/decision-framework.md`](references/decision-framework.md) — keyed
  guidance for choosing deterministic vs LLM-as-parser vs hybrid for a given
  legacy estate.
- [`gold/README.md`](gold/README.md) — the advisory-until-gold precision fixtures
  (#158) and the "never feeds a gate" rule.

## Sibling skills

The mainframe member of the legacy-comprehension lineage family — each covers a
different axis of a legacy estate:

- **`lineage-extract-static`** — data/process **flow** (the LLM-as-parser family
  this skill is the deterministic plug-in track of; run both and compare).
- **`structure-recovery`** — data **shape** (column lists/types, COBOL record
  layouts + byte offsets, inferred DDL).
- **`legacy-code-intel`** — code **symbols** (a queryable SCIP-style symbol /
  occurrence graph; mirrors the same 0.85 advisory-until-gold bar).
- **`cobol-developer`** / **`ibm-mainframe`** — reading/writing the COBOL + JCL +
  DB2 source this skill consumes.
