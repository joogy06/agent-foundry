# Decision Framework — Deterministic vs LLM-as-Parser vs Hybrid (F2)

This is the **centerpiece** of `mainframe-lineage-parsers`: keyed guidance for
choosing **how** to extract lineage from a legacy estate — a *deterministic*
stdlib parser (this skill), an *LLM-as-parser* flow (`lineage-extract-static`),
or a *hybrid* of the two. There is no single right answer; the right tool is a
function of five concrete keys (below).

The two flows are **complements, not competitors** (this skill is the sanctioned
deterministic v1.1 plug-in track under `lineage-extract-static` anti-pattern #7).
The intended use is **testing & comparison**: run THIS deterministic flow and the
LLM flow separately on the same inputs and compare the results yourself. No
comparison / diff / scoring harness is in scope — the two flows emit the same
OpenLineage 2.0.2 shape with distinct `extractor_id`s so a side-by-side diff is
attributable to a human reader.

The language here is model-neutral. Everything below applies the same way under
any CLI host (Claude Code, Codex CLI, Copilot CLI, Antigravity CLI). The
deterministic engine has **no LLM in the loop, ever** (C2); the LLM flow is the
separate `lineage-extract-static` run, never an automatic fallback of this one.

---

## TL;DR — when to reach for which

- **Deterministic (this skill)** when the artifact has a **stable, published
  grammar** (fixed-format COBOL / JCL / embedded DB2 `EXEC SQL`), you need
  **column-level / DD-join / host-var precision**, you want **cheap, reproducible,
  byte-identical** runs at estate scale, and you can keep the deps to stdlib
  (+ optional `sqlglot` for SQL).
- **LLM-as-parser (`lineage-extract-static`)** when the artifact has **no usable
  grammar** (Pick/MultiValue, free-format COBOL, an exotic dialect), you need
  **fuzzy intent / semantic** lineage rather than exact tokens, or the format is
  **one-off / unknown** and writing a deterministic parser is not worth it.
- **Hybrid** when you want the deterministic core's **clean, provenance-rich
  preprocessing** (column strip, copybook expansion, `EXEC SQL` split) to feed
  EITHER engine — deterministic *structure* + LLM *semantics*.

---

## The five decision keys

### 1. Grammar / format availability
The single most decisive key. A **stable published grammar** that the input
actually conforms to is what makes a deterministic parser correct rather than a
pile of fragile regexes.

| Situation | Lean |
|---|---|
| Fixed-format COBOL (IBM Enterprise COBOL baseline), JCL, embedded DB2 `EXEC SQL` | **Deterministic** — grammar is stable and published; this skill parses it directly. |
| Copybooks (`COPY ... REPLACING`) | **Deterministic** — resolved + inline-expanded before parsing (this skill's `copybook_resolver`). |
| Free-format COBOL | **LLM** — out of v1 scope; this skill emits a typed `free_format_unsupported` gap, never a silent best-effort. |
| Pick / MultiValue (UniVerse, UniData, D3, jBASE, OpenQM) | **LLM** — no usable grammar; `lineage-extract-static` covers the lineage, `legacy-code-intel` / `pick-developer` the symbols/source. |
| Java (JDBC / JPA / Spark-Java / messaging) | **LLM** — Java *has* a stable grammar, but this skill is stdlib-only with NO JVM / NO ANTLR (design D1) and Java is not mainframe legacy; `lineage-extract-static` covers Java lineage. |
| Exotic / undocumented 4GL or vendor dialect | **LLM** — a deterministic parser is not worth writing for a one-off. |

### 2. Precision-criticality
What precision does the downstream consumer actually need?

| Need | Lean |
|---|---|
| **Column-level** lineage (`EXEC SQL` host-var `:VAR` → DB2 `table.column`) | **Deterministic** — the LLM loses the host-var → column bridge across chunk boundaries. |
| **Physical-dataset → program-file join** (JCL `DSN` → `DDNAME` → COBOL `SELECT … ASSIGN TO` → FD → `READ`/`WRITE`) | **Deterministic** — the three-hop stitch is exactly where determinism beats the LLM. |
| Fuzzy **intent / "what does this program mean"** semantics | **LLM** — natural-language summarisation is the LLM's strength. |
| "Roughly, where does this data come from" at a coarse grain | **Either** — the LLM is faster to stand up; the deterministic flow is more exact. |

The two precision wins (design §4) are the concrete reason this skill exists:
the LLM, working chunk-by-chunk, cannot reliably reconstruct the JCL→COBOL
three-hop join or the host-var→column bridge; the deterministic engine can,
because it holds the whole resolved structure at once.

### 3. Dependency / air-gap posture
What can you actually install and run where the estate lives?

| Constraint | Lean |
|---|---|
| `sqlglot` installable (pure-Python, optional) | **Deterministic SQL** at full precision (`--engine sqlglot-sql` or `auto`). |
| Air-gapped / `sqlglot` absent | **Deterministic SQL degraded to regex** + a diagnostic (still no LLM), OR the **LLM** flow if you accept its trade-offs. This skill NEVER silently invokes an LLM when a dep is missing — it degrades to regex and surfaces the documented handoff. |
| No Python LLM tooling / no model access at all | **Deterministic** — the whole engine is stdlib (+ optional `sqlglot`/`networkx`, both import-if-present); it runs fully offline with zero model calls. |
| Hard constraint: NO ANTLR / NO ProLeap / NO JVM / NO new mandatory pip dep / NO runtime pip install | **Deterministic** — this skill is built to exactly that constraint (design D1). |

### 4. Volume / cost
How much are you scanning, how often?

| Situation | Lean |
|---|---|
| **Estate-scale, repeatable** (CI/cron, re-scanned on every change) | **Deterministic** — cheap (no per-token model cost), fast, and **byte-identical on re-run** (canonical sort + dedupe, stable ids). |
| **One-off / exploratory** on an unfamiliar format | **LLM** — lower setup cost than building/validating a deterministic path for a format you may never see again. |
| Large estate where reproducibility / auditability matters | **Deterministic** — provenance facets on every edge, deterministic output, no model drift between runs. |

### 5. Hybrid
You do not have to pick one engine end-to-end.

- The deterministic **preprocessing core** is reusable on its own: source-format
  detect, column 8-72 strip, comment/continuation handling, copybook
  `COPY ... REPLACING` expansion, and `EXEC SQL` block extraction — all with a
  source-map back to the original `(file, line)`. That clean, provenance-tagged
  output can feed EITHER the deterministic extractors OR an LLM prompt.
- **Deterministic structure + LLM semantics**: use this skill for the exact
  structural edges (DD-joins, host-var→column, FD records) and the LLM flow for
  the fuzzy intent layer, then compare/merge yourself.
- A hybrid is also the natural answer when **part** of the estate has a grammar
  (COBOL/JCL/DB2 → deterministic) and **part** does not (Pick/MV → LLM).

---

## Decision table (quick reference)

| If… | …then |
|---|---|
| Fixed-format COBOL + JCL + DB2 `EXEC SQL`, need column/DD-join precision, estate-scale | **Deterministic** (this skill) |
| Pick/MV, free-format COBOL, or an exotic dialect | **LLM** (`lineage-extract-static`) |
| Java (JDBC/JPA/messaging), or any non-mainframe language | **LLM** (`lineage-extract-static`) |
| Need fuzzy *intent*, not exact tokens | **LLM** |
| Air-gapped, no model access | **Deterministic** (degrade SQL to regex if `sqlglot` absent) |
| One-off, unknown format, low volume | **LLM** |
| Want clean structure for an LLM prompt, or mixed estate | **Hybrid** |
| Reproducibility / auditability is a hard requirement | **Deterministic** |
| You want to validate one approach against the other | **Run both, compare** (see below) |

---

## Worked examples

**Example A — payroll batch (deterministic).** A JCL job runs `PAYCALC` against
a VSAM master keyed off a `DD` statement, and `PAYCALC` has `EXEC SQL SELECT …
INTO :WS-NAME FROM PAYROLL.EMPLOYEE`. You need to know which physical dataset
feeds which program file AND which DB2 columns land in which working-storage
fields. Fixed-format, stable grammar, column-precision required, runs nightly →
**deterministic**. The DD→DDNAME→`ASSIGN TO`→FD join and the `:WS-NAME` →
`PAYROLL.EMPLOYEE.<column>` bridge are exactly the two precision wins.

**Example B — a Pick/MultiValue order system (LLM).** A 1980s UniVerse
application in Data/BASIC with dictionary-defined virtual fields. No published
grammar this skill can parse; the data model lives in the dictionary, not the
code. → **LLM** (`lineage-extract-static`, with `pick-developer` for reading the
code). This skill would (correctly) refuse rather than guess.

**Example C — air-gapped DB2 estate, no `sqlglot` (deterministic, degraded).**
You can run Python but cannot `pip install` and have no model access. → run this
skill with `--engine regex` (or `auto`, which auto-selects regex when `sqlglot`
is absent). SQL precision drops to the regex engine and a diagnostic is emitted;
COBOL/JCL precision is unaffected. **No LLM is invoked** — the documented handoff
("use `lineage-extract-static` for the LLM path") is surfaced, not auto-taken.

**Example D — mixed estate (hybrid).** A modernisation programme has COBOL/JCL/DB2
batch (grammar available) AND a Pick subsystem (no grammar). → **hybrid**: this
skill for the COBOL/JCL/DB2 lineage, `lineage-extract-static` for the Pick
subsystem, both emitting OpenLineage 2.0.2 so the two halves stitch into one
graph.

**Example E — validating the approach (run both, compare).** You are deciding
which flow to standardise on for an estate. Run THIS deterministic flow and the
LLM `lineage-extract-static` flow on the same COBOL+JCL+SQL sample, then diff the
two OpenLineage outputs. Because both honour the **same frozen naming contract**
(`references/naming-contract.md`) and **mark gaps identically**, the diff shows
*real* differences (coverage, precision, confidence) rather than naming noise.
The distinct `extractor_id` on each event tells you which flow produced which
edge.

---

## How comparison stays meaningful (the honesty note)

Asserting **byte-identical** output between the deterministic and LLM flows would
be wrong: the LLM's naming is itself judgment-dependent, and the two flows have
genuinely different coverage. The realistic, testable target is **same naming
*discipline* + identical gap-marking** (design §5). That is what the frozen
naming contract guarantees and what `test_naming_parity` enforces —
**output-vs-FROZEN-CONTRACT, never output-vs-live-LLM**. With the discipline
pinned, a side-by-side comparison is a fair read of where each approach actually
wins.

---

## See also

- `references/naming-contract.md` — the frozen shared naming contract both flows cite.
- `references/preprocessing.md` — the canonical deterministic preprocessing recipe.
- `skills/lineage-extract-static/` — the LLM-as-parser flow (the other half of the comparison).
- `skills/lineage-extract-static/references/confidence-classifier.md` — the shared confidence model.
- `skills/cobol-developer/`, `skills/ibm-mainframe/`, `skills/db2-mainframe/` — domain reading skills for the source artifacts.
- `skills/pick-developer/`, `skills/legacy-code-intel/` — the Pick/MultiValue path (LLM-only).
- `skills/java-backend/`, `skills/java-frontend/`, `skills/legacy-code-intel/` — the Java path (LLM-only; `lineage-extract-static` for the lineage).
