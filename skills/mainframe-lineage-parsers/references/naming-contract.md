# Mainframe Naming Contract (C1 — frozen FIRST)

This is the **frozen shared naming contract** for `mainframe-lineage-parsers` — the
deterministic v1.1 plug-in track under `lineage-extract-static` anti-pattern #7
(a *complement*, not a replacement, of the LLM-as-parser family).

It is **load-bearing**: every extractor (`jcl_extract`, `cobol_extract`,
`sql_extract`) and the OpenLineage emitter (`openlineage_emit`) MUST produce
ids / namespaces / gap markers that conform to the rules below, BYTE-FOR-BYTE.
It is written and frozen **before** any extractor exists so the build target is
fixed and the side-by-side comparison against the LLM tool is meaningful.

This contract **extends** the existing
`skills/lineage-extract-static/references/dataset-identity.md` for the mainframe
cases that reference deliberately punts on. Both skills cite this file as the
shared frozen reference for mainframe identity. (The reciprocal cross-cite from
`lineage-extract-static/references/dataset-identity.md` back to this file is added
in WP-12.) Where `dataset-identity.md` already gives a rule (e.g. the SQL-FQN
waterfall, the repo-relative path rule, the alias map, basename-merge OFF), that
rule still applies; this contract only pins the mainframe extensions.

The language here is model-neutral. The deterministic engine described by this
contract runs the same way regardless of which CLI host invokes it (Claude Code,
Codex CLI, Copilot CLI, Antigravity CLI). There is **no LLM in the deterministic
loop** — ever.

---

## 0. Purpose: testing & comparison, not a diff harness

The user runs **two** lineage flows over the same mainframe estate and compares
them himself:

1. THIS deterministic flow (`mainframe-lineage-parsers`), and
2. the LLM-as-parser flow (`lineage-extract-static`).

There is **no comparison / diff / scoring harness** in scope. The whole point of
this contract is to make the *naming discipline identical on both sides* so that
when the user diffs the two OpenLineage outputs, the differences he sees are
**real extraction differences**, not naming noise.

### Honesty note (carried from design §5 — applies to BOTH models)

The LLM tool's naming is itself judgment-dependent: two runs of the LLM flow can
disagree on a borderline id. So the realistic, honest target of this contract is:

> **same naming *discipline* + identical gap-marking**, NOT guaranteed
> byte-identical rows.

This contract makes the discipline explicit and testable. Parity in
`test_naming_parity` is therefore asserted **output-vs-FROZEN-CONTRACT, NEVER
output-vs-live-LLM** — asserting byte-equality against a live LLM tool would be
flaky and wrong (see §7 and §8).

---

## 1. DB2 dataset identity (the `:host-var → table.column` edge target)

DB2 tables/columns referenced from embedded `EXEC SQL` are datasets.

- **Namespace**: `db2://<host>:<port>/<db>`
- **Name**: `<schema>.<table>`

### Placeholder forms emitted VERBATIM when unresolved

DB2 **z/OS has no default schema** and the host/port/db are usually not visible
in the source. When a component is not resolvable from the inputs supplied
(no `--db2-catalog` / no `--schema`, no connection metadata in the chunk), emit
the placeholder token **verbatim** — do NOT invent a value:

| Component | Resolved form | Unresolved form (verbatim) |
|---|---|---|
| host | `dwhprd1` | `<host>` |
| port | `446` | `<port>` |
| db | `DSNDB` | `<db>` |
| schema | `PAYROLL` | `<schema>` |
| table | `EMPLOYEE` | (always present — it is the literal token) |

Examples:

```
-- fully unresolved (no catalog, no schema, no connection metadata)
namespace = db2://<host>:<port>/<db>
name      = <schema>.EMPLOYEE          + gap: catalog_less_column on each column edge

-- schema supplied via --schema PAYROLL, host/port/db still unknown
namespace = db2://<host>:<port>/<db>
name      = PAYROLL.EMPLOYEE
```

This is the **same gap the LLM tool emits**, written identically: when DB2 z/OS
gives no default schema and none is supplied, emit `gap: catalog_less_column`
(see §5) and keep the placeholder — never silently pick `public`, the connection
user, or any other default. (This mirrors the `DB2 z/OS → (Schema clause
required); No default; emit gap if absent` row already in `dataset-identity.md`.)

> **Advisory-until-gold (#158):** `:host-var → table.column` edges are
> **advisory** in v1 and MUST NEVER feed a gate. They are promoted above advisory
> only after clearing the `gold/` precision fixtures (added in WP-12). The
> `confidence` facet on a catalog-less column edge is forced to `speculative`
> (see §4).

---

## 2. JCL job identity

- **Namespace**: `mainframe://<jobname>`
  - `<jobname>` is the name on the `//JOBNAME JOB ...` statement, case-folded
    (see §6).
- **Name** (the job/step identity within that namespace):
  - Plain EXEC of a program: `<stepname>.<pgm>`
  - PROC-step-qualified (a program executed inside an expanded PROC step):
    `<stepname>.<procstep>.<pgm>`

Where:

- `<stepname>` — the name on the `//STEPNAME EXEC ...` statement in the job.
- `<procstep>` — the step name inside the invoked PROC (present only when the
  EXEC ran a PROC and the program lives in a PROC step).
- `<pgm>` — the value of `PGM=` on the resolved EXEC statement.

Examples:

```
//PAYJOB   JOB ...
//STEP010  EXEC PGM=PAYCALC
-- → namespace = mainframe://PAYJOB, name = STEP010.PAYCALC

//PAYJOB   JOB ...
//STEP020  EXEC PROC=LOADPRC          (PROC LOADPRC has step DBLOAD EXEC PGM=DSNUTILB)
-- → namespace = mainframe://PAYJOB, name = STEP020.DBLOAD.DSNUTILB
```

---

## 2a. Control-M scheduler job identity (v1 amendment — design §3, WP-2)

A Control-M Automation-API jobs-as-code job is a scheduler-layer **job** node.

- **Namespace**: `controlm://<folder>`
- **Name**: `<jobname>`

**Case-sensitivity divergence (LOCKED, design §3).** Unlike JCL/COBOL/DSN
identity (§6 rule 5, upper-folded), **Control-M folder and job names are
CASE-SENSITIVE and are NOT upper-folded.** Control-M treats `PayJob` and `PAYJOB`
as distinct jobs, so upper-folding would silently merge distinct jobs. This is a
deliberate divergence from §6 rule 5, documented here and re-stated in §6.

**The scheduler→program stitch.** A `Job:Command` whose `Command` is e.g.
`PAYCALC.sh ...` binds to the COBOL/program node `mainframe://<program-id>`. The
program-id is the **basename of argv[0], extension stripped, UPPER-FOLDED** — and
ONLY the program-id side of that edge is upper-folded, so it collides with the
COBOL extractor's upper-folded `mainframe://PAYCALC` node (§3). The job-identity
side (`controlm://<folder>` / `<jobname>`) stays case-sensitive. The
scheduler→program bind is `kind=inferred`, ceiling `inferred` (a cross-artifact
name bind — same discipline as the JCL→COBOL DDNAME stitch); it is NEVER
`grounded` (it is a name bind across two separate artifacts, not a literal token).

Examples:

```
"PayrollFolder": { "PayCalcJob": { "Type": "Job:Command", "Command": "PAYCALC.sh -v" } }
-- → job node:     namespace = controlm://PayrollFolder, name = PayCalcJob   (case-preserved)
--   program node: namespace = mainframe://PAYCALC,      name = PAYCALC      (upper-folded — the stitch)
--   edge:         program-node -> job-node, kind=inferred, confidence=inferred
```

---

## 3. COBOL program job identity

For a COBOL program analysed on its own (no JCL context), the job identity is the
`PROGRAM-ID`:

- **Namespace**: `mainframe://<program-id>`
- **Name**: `<program-id>`

`<program-id>` is the value of `PROGRAM-ID.` in the IDENTIFICATION DIVISION,
case-folded per §6. When the same program is also reached through JCL (via
`PGM=<program-id>`), the JCL job identity (§2) is the authoritative job node for
that run; the COBOL-only identity is used when the program is analysed without a
driving JCL job.

---

## 4. Dataset identity for physical DSNs, and DDNAME as the bind key

JCL `DD` statements bind a **DDNAME** to a physical **DSN**. The DDNAME is the
**bind key** that bridges JCL to COBOL: COBOL `SELECT file ASSIGN TO <ddname>`
joins on the very same DDNAME (the precision-win join #1, stitched in WP-8).

### Physical DSN canonicalisation

- **Namespace**: `mainframe://DSN` (the on-host dataset namespace)
- **Name**: the canonicalised DSN.

Canonicalisation rules (deterministic, see §6):

1. **Case-fold** the DSN to upper case (mainframe DSNs are case-insensitive).
2. **GDG**: a generation-data-group reference `MY.GDG.BASE(+1)` /
   `MY.GDG.BASE(0)` / `MY.GDG.BASE(-1)` canonicalises to the **GDG base**
   `MY.GDG.BASE`; the relative generation `(+1)` / `(0)` / `(-1)` is preserved as
   a `gdg_generation` **facet**, NOT folded into the node name. (Two steps that
   touch `(+1)` and `(0)` of the same base are edges on the same base dataset
   node, distinguished by the facet.)
3. **Symbolic / interpolated DSN**: a DSN that still contains an unresolved
   symbolic parameter after PROC/SET/symbol expansion (e.g.
   `&HLQ..PAYROLL.MASTER` where `&HLQ` was never set) is **NOT invented**. Emit:
   - `kind = unresolved`
   - `confidence = speculative` (forced — see the forcing rules in `ir.py`)
   - a `symbolic_dsn` gap node (see §5)
   - the raw unresolved DSN string kept as a `raw_dsn` facet.

Examples:

```
//SYSUT1  DD DSN=PROD.PAYROLL.MASTER,DISP=SHR
-- → DSN node: namespace = mainframe://DSN, name = PROD.PAYROLL.MASTER
--   DDNAME bind key: SYSUT1

//OUT01   DD DSN=PROD.PAY.GDG.BASE(+1),DISP=(NEW,CATLG)
-- → DSN node: namespace = mainframe://DSN, name = PROD.PAY.GDG.BASE
--   facet gdg_generation = "+1" ; DDNAME bind key: OUT01

//IN01    DD DSN=&HLQ..PAYROLL.MASTER,DISP=SHR     (&HLQ never set)
-- → kind=unresolved, confidence=speculative, gap: symbolic_dsn
--   facet raw_dsn = "&HLQ..PAYROLL.MASTER" ; DDNAME bind key: IN01
```

### `confidence` facet — BYTE-IDENTICAL to the siblings (C3 parity)

The `confidence` facet on every edge uses **exactly** the sibling enum:

```
CONFIDENCE_ENUM = {"grounded", "inferred", "speculative"}
```

This is byte-identical to
`skills/structure-recovery/scripts/validate_finding.py` `CONFIDENCE_ENUM` (the
IR in WP-4 imports and asserts against that value). `confidence` is the
**evidence tier**.

`kind` is a **separate, independent facet** with its own enum
`{direct, inferred, unresolved, interproc_unknown}` (the **structural edge
type**). The two are NOT conflated: `inferred` is a member of both enums but means
different things (an `inferred`-kind edge can still be `grounded`-confidence; an
`unresolved`-kind edge is always forced to `speculative`-confidence). The forcing
rules that bind `kind` → minimum `confidence` live in `ir.py` (WP-4); this
contract only pins the *vocabulary*.

---

## 5. Gaps marked IDENTICALLY to the LLM tool

A gap is a typed node emitted in place of an edge that cannot be honestly claimed.
The deterministic engine emits the **same gap types, with the same names**, that
the LLM tool (`lineage-extract-static`) emits, so a side-by-side diff shows real
differences, not naming noise. The frozen gap-type vocabulary:

| Gap type | Emitted when | Confidence |
|---|---|---|
| `unresolved_copy` | a `COPY` member is not found on any `--copybook-path` (WP-3) | `speculative` |
| `free_format_unsupported` | source is free-format COBOL (`>>SOURCE FORMAT FREE`); v1 is fixed-only (WP-2) | n/a (diagnostic) |
| `symbolic_dsn` | a DSN still contains an unresolved `&SYMBOL` after expansion (§4, WP-5) | `speculative` |
| `catalog_less_column` | a DB2 column cannot be resolved to a real catalog column (no `--db2-catalog`/`--schema`) (§1, WP-7) | `speculative` |

### Control-M scheduler gaps (v1 amendment — design §4, WP-1)

The deterministic Control-M extractor (`controlm_extract.py`, WP-2) adds four
scheduler-layer gap kinds. This is a **versioned contract amendment** of the
previously frozen-closed set, not a casual edit: `ir.GAP_TYPE_ENUM` and
`make_gap_node` were extended in WP-1 **before** the extractor may emit them
(`make_gap_node` rejects an out-of-set type). All four are `speculative`.

| Gap type | Emitted when | raw facet | Confidence |
|---|---|---|---|
| `unresolved_variable` | a `%%VAR` is still unresolved after `Variables` substitution | `raw_variable` | `speculative` |
| `unresolved_connection` | a `ConnectionProfile` is absent from the `--controlm-connection-profiles` map | `raw_connection_profile` | `speculative` |
| `runtime_path` | a `FileName`/`Src`/`Dest` is `%%`-interpolated or `AssignFileNameToVariable` runtime-bound | `raw_path` | `speculative` |
| `unresolved_event_dep` | an `eventsToWaitFor` event has no in-scope `eventsToAdd` producer | `raw_event` | `speculative` |

`%%`-variable substitution reuses the JCL `&SYMBOL` precedent
(`jcl_extract.substitute_symbols`): a variable literal-in-document is substituted
deterministically; an unresolved one forces `speculative` + the
`unresolved_variable` gap (never an invented value — C3).

Rules:

- A gap is **NEVER** replaced by an invented edge (C3). Unresolved COPY, symbolic
  DSN, and catalog-less column always become the gap above, never a guessed
  binding.
- A gap node keeps the raw evidence as a facet (`raw_copy_member`, `raw_dsn`,
  `raw_host_var`, …) so the user can see what was unresolved.
- The gap **name** is part of this frozen contract — extractors MUST use these
  exact strings (the IR in WP-4 provides the gap-node constructors).

This list is the v1 closed set. Any new gap type is a contract change (a new row
here) before an extractor may emit it.

---

## 6. Determinism rules

The deterministic engine produces **byte-identical** OpenLineage output on
re-run of the same inputs. The rules:

1. **Stable ids from canonical fields ONLY.** A node/edge id is derived solely
   from canonical fields (canonicalised namespace + name + canonical edge
   endpoints). Raw values (raw DSN, raw host-var, host/port when later resolved,
   GDG generation) are kept as **facets**, never folded into the id. This means
   resolving a placeholder later does not silently re-id an existing node beyond
   the canonical change.
2. **Canonical sort.** Nodes are sorted by `(namespace, name)`; edges are sorted
   by their canonical edge key (see rule 4). Sorting is byte-lexicographic on the
   canonical strings.
3. **Dedupe by canonical edge key.** Two edges with the same canonical edge key
   collapse to one; their provenance facets (source spans, rule ids) are merged
   into a list, deterministically ordered.
4. **Canonical edge key** = `(source_node_id, target_node_id, kind)`. (Two edges
   between the same nodes with *different* `kind` are distinct edges; two with the
   same `kind` are duplicates and collapse.)
5. **Case-folding** is applied per the rules above (DSN upper-case, jobname /
   stepname / program-id upper-case) **before** id derivation, so case variants
   of the same artifact map to one node. **EXCEPTION (Control-M, §2a):**
   Control-M `<folder>` and `<jobname>` are CASE-SENSITIVE and are NOT
   upper-folded — Control-M treats case-variant names as distinct jobs, so
   folding would wrongly merge them. The scheduler→program edge upper-folds ONLY
   the program-id side (so it still collides onto the upper-folded COBOL program
   node); the `controlm://` job identity keeps its original case. This is the one
   deliberate divergence from the upper-fold rule, locked by design §3.
6. **No timestamps in identity.** Event `eventTime` and similar runtime fields
   are not part of any node/edge id (mirrors the sibling `SOURCE_DATE_EPOCH`
   determinism discipline). The OpenLineage emitter (WP-9) controls event-time
   determinism.

The graph assembler (WP-8) applies the canonical sort + dedupe; this contract is
the authority it sorts/dedupes against.

---

## 7. The `test_naming_parity` fixture and contract

`test_naming_parity` (authored here in WP-1, un-skipped in WP-9 once
`openlineage_emit.py` exists) pins this discipline:

- It runs the deterministic flow over a **small COBOL + JCL pair** (the parity
  fixture in `tests/fixtures/mainframe-lineage-parsers/naming-parity/`).
- It asserts the emitted ids / namespaces / gap markers match the **FROZEN
  EXPECTED-IDS table** declared alongside the fixture — i.e. **this contract**.
- It does **NOT** run, call, or compare against live `lineage-extract-static`
  output. Parity is **output-vs-FROZEN-CONTRACT**, never **output-vs-live-LLM**
  (per the honesty note in §0 — a live-LLM equality assertion would be flaky).

Because the extractors and the emitter do not exist yet at WP-1, the test is
authored as the frozen expected-ids table **plus a skip-guarded assertion
harness** (it skips until `openlineage_emit.py` is importable). WP-9 un-skips and
wires it to the real emitter. At WP-1 the test runs **clean with skips, no
errors**.

---

## 8. What this contract does NOT do

- It does **not** assert byte-equality against the LLM tool (§0, §7).
- It does **not** define a comparison/diff/scoring harness (out of scope —
  decision A).
- It does **not** introduce a default DB2 schema, host, or port (§1 — placeholders
  are emitted verbatim).
- It does **not** invent edges for unresolved COPY / symbolic DSN / catalog-less
  column (§5 — those are gaps, always).
- It does **not** cover the non-goals (Pick/MultiValue, free-format COBOL,
  dynamic SQL, non-DB2 dialects) beyond emitting the typed diagnostic/gap — those
  remain the LLM tool's job, surfaced via the documented handoff.

---

## See also

- `skills/lineage-extract-static/references/dataset-identity.md` — the base
  dataset/job identity reference this contract extends (SQL-FQN waterfall,
  repo-relative paths, alias map, basename-merge OFF). The reciprocal cross-cite
  back to this file is added in WP-12.
- `skills/structure-recovery/scripts/validate_finding.py` — the source of the
  byte-identical `CONFIDENCE_ENUM` (C3 parity).
- `skills/mainframe-lineage-parsers/references/decision-framework.md` (WP-11) —
  when to use the deterministic flow vs the LLM-as-parser flow vs hybrid.
