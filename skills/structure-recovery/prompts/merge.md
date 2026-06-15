# Merge / Cross-File Reconciliation Prompt

You are reconciling multiple per-chunk `structure-finding.v1` objects (and, in
the cross-file pass, multiple per-file `summary.json` catalogs) into a single
coherent structure for each object. This prompt describes the **merge
semantics** so the deterministic accumulator
(`scripts/accumulate_structure.py`) and the cross-file pass behave consistently.
It is model-neutral (Claude Code / Codex CLI / GitHub Copilot CLI / Antigravity
CLI `agy`).

> **Where the authority lives.** The byte-exact arithmetic (offsets, lengths) and
> the lower-confidence-wins bookkeeping are performed by **Python**, not by you:
> `accumulate_structure.py` reuses the lineage-family `conf_rank`
> lower-confidence-wins logic verbatim and invokes `cobol_offset_calc.py` for
> COBOL offsets. Your role when this prompt is used for an LLM-assisted reconcile
> is to apply the **pairing and union rules** below and to surface honest
> `boundary_issue` / gap downgrades — never to compute or guess an offset, and
> never to "promote" a confidence tier.

## 1. Pairing predicate (which findings describe the same object)

Two findings describe the **same object** — and are merged — iff **all** hold:

1. `object_kind` is identical (`table` ↔ `table`, `cobol_record` ↔
   `cobol_record`, etc. — never merge across kinds).
2. `qualified_name` is identical (after trivial normalisation: trim surrounding
   whitespace; treat case per the source dialect — SQL identifiers are typically
   case-insensitive unless quoted, COBOL record names are case-insensitive).
3. The findings are **adjacent** — consecutive chunks of the same file, OR the
   same object declared across files in the cross-file pass — and any
   chunk-spanning field overlap falls within the carried overlap window.

If any of these fails, the findings are **distinct objects** — keep both.

## 2. Field union (within a paired object)

- Union the `fields` arrays **by `(name, ordinal)`**. A field present in both
  findings is the same field; deduplicate it (do not emit it twice).
- Preserve declaration order by `ordinal` within each parent group. For COBOL,
  ordinal is **per parent group**, so the group hierarchy must be respected when
  ordering — never flatten a group's children into the parent's ordinal space.
- When the same `(name, ordinal)` field appears in both findings with
  **conflicting** attributes (e.g. one chunk saw `PIC X(30)`, the partial tail of
  the previous chunk saw only `PIC X`), keep the **more complete / more
  conservative** record per §3 below.

## 3. Lower-confidence-wins (the conservative merge)

When merging duplicate facts, the **lower** confidence tier wins — never the
higher. Ranking (from the lineage family, reused verbatim):

```
grounded (3) > inferred (2) > speculative (1)   →   keep the MINIMUM
```

- If one copy is `grounded` and the other `speculative`, the merged field is
  `speculative`. We never upgrade a fact because a second chunk happened to see
  it more cleanly; a single doubtful sighting taints the merge. (Rationale:
  honesty over optimism — the catalog must not over-claim.)
- A **tie that cannot be cleanly resolved** (e.g. two equally-confident but
  conflicting type strings) → downgrade to `speculative` AND attach a
  `boundary_issue` marker on the field. Do NOT pick one arbitrarily and present
  it as confident.

## 4. Orphans and boundary issues

- A field or object that arrived from an **unpaired partial chunk** (a finding
  whose `boundary_status` upstream indicated it was cut, with no adjacent finding
  to complete it) is an **orphan**. Mark it `boundary_issue: true` and force its
  confidence to `speculative`. Keep it (it is real, declared structure) but flag
  that the merge could not confirm it.
- Never silently drop an orphan, and never silently complete it by guessing the
  missing part.

## 5. COBOL offset computation (delegated, not inferred)

- After a COBOL record's **declared field tree** is fully unioned (including any
  cross-file `COPY` member spliced in — see §6), the accumulator invokes
  `cobol_offset_calc.py` to compute `byte_offset` / `length` /
  `byte_offset_min` / `byte_offset_max` / `variable_length` / `ranged` and the
  offset-confidence per field, plus any `sync_alignment` / `odo_variable_length`
  gaps. You never compute these. The chunk-level findings carried
  `byte_offset: null` / `length: null`; the computed values appear only in the
  accumulated `structure-index.v1` catalog.

## 6. Cross-file reconciliation (the cross-file pass)

When merging across files (not just chunks of one file):

- **Identity canonicalisation:** a `CREATE TABLE` followed by later `ALTER TABLE`
  statements for the same `qualified_name` → union the columns; the **latest
  ALTER wins** for a changed column (this is the one place a later, equally-or
  -more authoritative declaration supersedes an earlier one — it is a declared
  schema evolution, not a confidence upgrade).
- **Copybook `COPY` splicing:** an `unresolved_copybook` gap from a COBOL chunk is
  resolved by locating the copybook member's own `cobol_record` finding,
  **splicing its field subtree in at the COPY point** (preserving levels and
  per-group ordinals), and only THEN computing offsets. Fields spliced from a
  `COPY ... REPLACING` are forced `speculative` (post-replace names are not
  statically certain).
- **Relationship resolution** (see also `references/confidence-model.md` and
  decision K2):
  - SQL **declared** `FOREIGN KEY` → `grounded` fk (enforcement `declared`).
  - Convention `*_id` → `id` → `inferred` join hint (`kind: join`,
    `inferred_naming`), never a live FK.
  - SQL `JOIN ON` → `kind: join` (inferred, `observed_usage`), never fk.
  - DataStage key flags → `grounded` PK hints (enforcement `unknown`).
  - COBOL cross-record FK → **only** when `--infer-relationships` is enabled,
    capped at `speculative`, requires name+type+length match, and is emitted ONLY
    as a commented `-- INFERRED FK:` DDL line — never a live constraint, never
    above `speculative`.

## 7. Cross-check declared flat-file positions

When a flat-file finding carried `position_declared: true` with
`declared_start` / `declared_end`, the accumulator cross-checks those declared
positions against the **computed** field sequence. On mismatch: **downgrade** the
affected field and attach a gap (the doc's declared positions disagree with the
computed layout — surface the discrepancy honestly, do not silently trust either).

## Determinism and output

- Merges are **idempotent**: re-running over the same inputs yields a
  byte-identical `summary.json` / catalog. Sort fields by `(parent-group,
  ordinal)`; sort relationships by a stable key (`kind`, `from_field`,
  `to_object`).
- The accumulator writes atomically (`.tmp` + rename) under the run lock.

## Anti-patterns — DO NOT DO

- Do NOT merge findings of different `object_kind` or different `qualified_name`.
- Do NOT **upgrade** a confidence tier on merge — lower-confidence-wins, always.
- Do NOT pick arbitrarily on an unresolved tie — downgrade + `boundary_issue`.
- Do NOT compute or guess any byte offset/length — that is `cobol_offset_calc.py`.
- Do NOT drop orphans or silently complete partial records.
- Do NOT promote a COBOL cross-record FK above `speculative`, and never emit it as
  a live constraint.
