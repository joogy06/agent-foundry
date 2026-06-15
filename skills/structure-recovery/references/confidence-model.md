# Reference: confidence / honesty model (design §5, P1)

`structure-recovery` reverse-engineers DECLARED structure from static artifacts.
Every entity, field, offset, and relationship carries a **confidence** tag that
flags how the fact was learned. This is the same bright-line, syntactic classifier
the sibling skills use (`lineage-extract-static`, `legacy-code-intel`), adapted to
structural facts. **Confidence flags uncertainty, not incorrectness** — a grounded
fact can still be wrong if the LLM misread; that residual is covered by a future
`gold/` schema-oracle accuracy gate, not by this tag.

## The three axes

A structural fact is tagged on three independent closed-enum axes:

```
confidence   ∈ {grounded, inferred, speculative}
evidence_kind ∈ {declared_constraint, declared_column, inferred_naming, observed_usage}
enforcement  ∈ {declared, unknown}
```

### `confidence` — how certain the extraction is

| Tier | Rule | Rendering / use |
|---|---|---|
| `grounded` | The fact is LITERALLY DECLARED in the chunk: a `CREATE TABLE` column with a declared type; a SQL `FOREIGN KEY`/`PRIMARY KEY`/`UNIQUE`; a COBOL field whose `PIC`/`USAGE` chain computes a clean byte offset; a declared positional layout (`Field|Start|End|Len`); a DSX declared key flag. | Live in HTML schema table; eligible for a LIVE DDL constraint (grounded + declared FK only). |
| `inferred` | Resolved by an IN-ARTIFACT heuristic: a convention `<base>_id` → `<base>.id` join hint; a group-propagated COBOL `USAGE`; a column inferred from an `INSERT` column list. | Advisory. Commented `-- INFERRED …` in DDL; dashed in HTML. |
| `speculative` | A dynamic / interpolation / unresolved marker (below), OR a cross-boundary orphan, OR a COBOL cross-record FK. | Never authoritative. Commented-only in DDL; dotted in HTML. |

### `evidence_kind` — what kind of evidence produced the fact

| Value | Meaning | Typical confidence ceiling |
|---|---|---|
| `declared_constraint` | A real DDL constraint (SQL `FK`/`PK`/`UNIQUE`, DSX declared key). | `grounded` |
| `declared_column` | A declared column/field (type, ordinal, nullability). | `grounded` |
| `inferred_naming` | A name heuristic (`*_id` convention; COBOL cross-record name match). | `inferred` (SQL) / `speculative` (COBOL cross-record) |
| `observed_usage` | Learned from usage, not declaration (a SQL `JOIN ON`, an `INSERT` column list). | `inferred` |

### `enforcement` — whether a constraint is actually enforced

| Value | Meaning |
|---|---|
| `declared` | The artifact declares the constraint (SQL `FOREIGN KEY`, `NOT NULL`, DSX key flag). |
| `unknown` | No enforcement is declared — an inferred / observed / convention fact. |

## Forced-`speculative` markers (deterministic, defense-in-depth)

These are re-checked **deterministically** in `relationships.py` (`_looks_dynamic`)
and in `cobol_offset_calc.py`, on TOP of whatever the LLM emitted — the LLM cannot
accidentally over-promote a dynamic edge:

- DSX `RCP` (runtime column propagation) — the column set is runtime-determined.
- `#PARAM#` (DSX parameter interpolation).
- `${VAR}` / `$(...)` (shell interpolation / command substitution).
- `%s` / `%d` (printf-style interpolation).
- `.format(` / `f'…'` / `f"…"` (Python string interpolation).
- COBOL `COPY … REPLACING …` (post-replace names not statically knowable) → the
  affected subtree is forced `speculative`.
- COBOL `OCCURS DEPENDING ON` → the post-ODO tail is ranged + `variable_length`, and
  a single authoritative offset is REFUSED.
- COBOL `SYNCHRONIZED` → offsets are emitted RANGED/UNKNOWN + `gap:sync_alignment`,
  NEVER a confident "without-slack" value.
- An unresolved `COPY` member → the spliced subtree is `speculative` + a gap.

## Offsets carry their own confidence

A computed COBOL byte offset is NOT automatically grounded. `cobol_offset_calc.py`
tags each field's `offset_confidence`:

- `grounded` — a clean `DISPLAY`/`COMP`/`COMP-3` chain with no SYNC/ODO/unresolved-COPY.
- `inferred` — a group-propagated `USAGE` (the child's usage was inherited, not declared).
- `speculative` — anything downstream of SYNC, an ODO tail, or an unresolved `COPY`.

An accumulated field's reported `confidence` is the lower-confidence-wins fold of its
declared confidence and its `offset_confidence`.

## Relationship / FK caps (K2 — also enforced in `relationships.py`)

The relationship resolution pass (`relationships.py:resolve_relationships`) applies
these caps deterministically after the per-file accumulator:

| Source | `kind` | `evidence_kind` | confidence | enforcement | DDL rendering |
|---|---|---|---|---|---|
| SQL declared `FOREIGN KEY` | `fk` | `declared_constraint` | `grounded` | `declared` | **LIVE** `FOREIGN KEY` constraint |
| SQL declared `PRIMARY KEY` / `UNIQUE` | `pk` / `unique` | `declared_constraint` | `grounded` | `declared` | **LIVE** `PRIMARY KEY` / `UNIQUE` |
| DSX declared key flag | `pk` | `declared_constraint` | `grounded` | `declared` | LIVE PK hint |
| Convention `<base>_id` → `<base>.id` | `fk` | `inferred_naming` | `inferred` (capped) | `unknown` | commented `-- INFERRED FK:` |
| SQL `JOIN … ON` | `join` (never `fk`) | `observed_usage` | `inferred` (capped) | `unknown` | commented `-- INFERRED FK:` |
| COBOL cross-record FK | `fk` | `inferred_naming` | `speculative` (HARD cap) | `unknown` | commented `-- INFERRED FK:` |

**COBOL cross-record FKs are produced ONLY when `--infer-relationships` is set
(decision O2).** When the flag is off, ZERO COBOL cross-record FKs appear in
`relationships[]` (DoD #5). When on, each one additionally requires a
**name + normalized-type + byte-length match** between the referencing field and the
target record's key field, and is HARD-capped at `speculative` — it can never become
a live constraint (COBOL records render as non-relational commented field manifests).

`confidence` only ever moves DOWN in this pass (lower-confidence-wins). The pass never
promotes an edge above what its `evidence_kind` allows.

## Gate-never-feed (design §5 / §6 — non-negotiable)

> FK/relationship edges advisory until a `gold/` schema oracle clears an accuracy
> gate (legacy-code-intel precedent) — **never feed a gate**.

- Inferred DDL + speculative FKs are **advisory-only**, carry a mandatory human-review
  header, and are **NEVER executed**.
- No confidence tag, no relationship, and no inferred DDL line is ever consumed as a
  gate input. `relationships.py` ships **no gate hook**, by design.
- The confidence tag is per-fact and syntactic; empirical accuracy (precision/recall
  against a gold schema) is a separate, future, per-format concern — complementary,
  not redundant.
