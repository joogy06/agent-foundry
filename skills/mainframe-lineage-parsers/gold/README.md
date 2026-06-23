# gold/ — precision fixtures (advisory-until-gold, #158)

This directory holds **#158-style precision fixtures** for the two precision-win
edge classes of `mainframe-lineage-parsers`:

1. **DD-join** — JCL `DD`/`DSN` → `DDNAME` bind key stitched to the COBOL
   `SELECT ... ASSIGN TO <ddname>` → file → `READ`/`WRITE` (the first
   precision-win edge class).
2. **host-var → column** — embedded `EXEC SQL` host-variable (`:WS-NAME`) →
   `table.column` (the second precision-win edge class).

The frozen oracle is [`expected-edges.yaml`](expected-edges.yaml); the inputs
are [`cobol/GOLDPAY.cbl`](cobol/GOLDPAY.cbl) + [`jcl/GOLDPAY.jcl`](jcl/GOLDPAY.jcl).

## ADVISORY ONLY — these fixtures NEVER feed a gate

This is the single load-bearing rule of this directory (design §6):

> Host-var/column edges (and the DD-join stitch) stay **advisory** until a
> `gold/` fixture clears a precision bar; **they never feed gates.**

Concretely, `gold/` and `expected-edges.yaml`:

- are **NOT** consumed by any `G_*` gate in `_meta/gates.py`;
- are **NOT** part of bob's `INTEGRATED → VERIFIED` dual-verdict arc (this is an
  N/A `skill_text` cycle anyway — no contract map, no ledger transitions);
- are **NOT** a CI hard-block — a measurement below the bar does not fail a build;
- exist purely so the maintainer can **measure** precision of the two
  precision-win edge classes after a change, by hand or with a one-off script
  kept **out of** `scripts/` (so the runtime stays gate-free and dependency-free).

This mirrors `legacy-code-intel`'s gold-file harness, where `impact()` stays
advisory until a format's gold precision clears **0.85** — same `#158` pattern,
same advisory posture. The `precision_floor: 0.85` in `expected-edges.yaml` is an
advisory target, not an enforced threshold.

## Parity discipline

Expected values in `expected-edges.yaml` are derived **strictly from the frozen
naming contract** (`references/naming-contract.md`, §0 and §7) over the fixtures
here — **output-vs-FROZEN-CONTRACT, never output-vs-live-LLM**. Asserting
byte-equality against the LLM tool (`lineage-extract-static`) would be flaky and
wrong; the realistic target is "same naming *discipline* + identical
gap-marking", made explicit and checkable by the contract.

## How to run the gold check (advisory)

The check is a manual / one-off comparison — there is intentionally no script in
`scripts/` for it (keeping the runtime gate-free). Run the deterministic flow
over the gold fixtures two ways and compare the emitted edges against
`expected-edges.yaml` by eye (or with a throwaway diff script you keep outside
the skill).

Catalog-less (host-var/column edges → `unresolved` / `speculative` +
`catalog_less_column` gap):

```bash
python3 skills/mainframe-lineage-parsers/scripts/run_lineage.py \
  --src   skills/mainframe-lineage-parsers/gold/cobol/GOLDPAY.cbl \
  --src   skills/mainframe-lineage-parsers/gold/jcl/GOLDPAY.jcl \
  --out   /tmp/gold-catalog-less.ndjson \
  --engine regex < /dev/null
```

With a schema (host-var/column edges → `inferred`; **still never grounded**):

```bash
python3 skills/mainframe-lineage-parsers/scripts/run_lineage.py \
  --src    skills/mainframe-lineage-parsers/gold/cobol/GOLDPAY.cbl \
  --src    skills/mainframe-lineage-parsers/gold/jcl/GOLDPAY.jcl \
  --schema PAYROLL \
  --out    /tmp/gold-with-schema.ndjson \
  --engine regex < /dev/null
```

Then compare the `mainframeLineage` edge facets (`kind` + `confidence`) and the
`mainframeGap` facets in the two `.ndjson` outputs against the `dd_join_edges`,
`hostvar_column_edges`, `table_edges`, and the per-edge `catalog_less` /
`with_schema` rows in `expected-edges.yaml`.

Exit codes (from `run_lineage.py`): `0` = success (gaps are normal), `1` = fatal
input, `2` = `--engine=sqlglot-sql` requested but `sqlglot` absent (fail-loud
handoff to `lineage-extract-static`, never an LLM), `3` = `--copybook-missing=fail`
with an unresolved `COPY`.

## See also

- [`../references/naming-contract.md`](../references/naming-contract.md) — the
  frozen shared naming contract (the precision oracle's parity source).
- [`../references/decision-framework.md`](../references/decision-framework.md) —
  deterministic vs LLM-as-parser vs hybrid.
- `legacy-code-intel` — the `#158` gold-file harness this advisory bar mirrors
  (`goldcheck.py`, `gold/cobol/sample.gold.json`, the 0.85 call-edge bar).
- `lineage-extract-static` — the LLM-as-parser sibling; this skill is its
  sanctioned anti-pattern-#7 deterministic v1.1 plug-in track.
