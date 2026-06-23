# Preprocessing Recipe — the deterministic stdlib core

This is the canonical reference for the **preprocessing core** of
`mainframe-lineage-parsers` — the first stage of the deterministic pipeline
(design §3, research §5 `clean_and_extract_cbl`). It documents the behaviour
implemented in `scripts/preprocess.py`; the two are kept in lockstep.

The preprocessing core turns raw **fixed-format COBOL source** into:

1. a **clean program-area stream** (comment / debug / blank lines dropped,
   continuation lines folded, `EXEC SQL` regions removed), plus
2. a **source-map** that traces every clean logical line back to its original
   `(file, line)`, plus
3. the list of extracted **`EXEC SQL ... END-EXEC` blocks** with their original
   source spans,
4. and any typed **gaps** (e.g. `free_format_unsupported`).

This is the part that breaks naive parsers (research §5): an ANTLR/ProLeap
grammar fails outright without the column strip, the copybook expansion, and the
`EXEC SQL` removal. Doing it deterministically here, once, with full provenance,
is what lets the downstream extractors stay simple and correct.

It is **pure stdlib** — NO LLM, NO `sqlglot`/`networkx`, NO new pip deps, NO
network, NO shell, NO runtime pip install (design D1). The deterministic engine
has no LLM in the loop, ever (C2). It is also **pure in-memory** by default: the
public entry points take source text (or read a file) and RETURN dataclasses; no
cache is written in v1.

The language here is model-neutral. The core runs the same way under any CLI host
(Claude Code, Codex CLI, Copilot CLI, Antigravity CLI).

---

## 1. Source-format detection (v1 is FIXED-only)

A `>>SOURCE FORMAT FREE` / `>>SET SOURCEFORMAT"FREE"` / `>>SOURCE FORMAT IS FREE`
directive (case-insensitive, with or without quotes) selects **free-format**,
which v1 does **not** support. The **last** directive wins (Enterprise COBOL
allows the format to switch mid-source; if free appears anywhere, a fixed strip
is unsafe). The default with no directive is **fixed** (the legacy-estate
default).

- **FIXED** → proceed with the fixed-format pipeline below.
- **FREE** → emit a typed `free_format_unsupported` gap + a diagnostic and return
  WITHOUT attempting a fixed-format strip. Best-effort-parsing free-format as if
  it were fixed would corrupt every column offset, so we refuse rather than guess
  (C2/C3). This is the **same gap the LLM tool surfaces, named identically**
  (naming-contract §5), and the diagnostic points at the documented handoff: use
  `lineage-extract-static` for the free-format / LLM path.

Implementation: `detect_source_format(text) -> "fixed" | "free"`.

---

## 2. Fixed-format column model

A fixed-format COBOL line (IBM Enterprise COBOL baseline) is laid out as
1-indexed columns:

| Cols | Area | Handling |
|---|---|---|
| 1-6 | sequence-number area | **dropped** |
| 7 | indicator area | `*` or `/` = comment · `-` = continuation · `D`/`d` = debug · ` ` = normal |
| 8-72 | program area | **the code** (Area A cols 8-11, Area B cols 12-72) |
| 73-80 | identification area | **ignored** (and anything past col 80) |

In 0-indexed Python slices:

```
seq        = line[0:6]      # cols 1-6  (dropped)
indicator  = line[6]        # col  7    (safe on short lines)
program    = line[7:72]     # cols 8-72 (the clean code)
ignored    = line[72:80]    # cols 73-80
```

Notes that matter for correctness:

- **Tabs are expanded first** (`str.expandtabs()`) before slicing, so a tab in
  the sequence area does not shift the column math on tab-indented sources.
- The program area is **right-stripped** (trailing blanks in the fixed field
  carry no meaning) but **not left-stripped** (Area A vs Area B indentation can
  matter to a downstream parser).
- Research §5's reference collapsed indicator + program into one slice
  (`line[6:72]`); this core keeps the **indicator and program area as distinct
  fields** so the indicator semantics (comment / continuation / debug) are
  explicit and testable, and the clean text returned is exactly cols 8-72.

---

## 3. Comment, debug, and blank handling

While folding physical lines into logical lines:

- **Comment lines** (indicator `*` or `/`) are dropped — they carry no
  lineage-bearing code.
- **Debug lines** (indicator `D`/`d`) are dropped — they are only active under
  `WITH DEBUGGING MODE`, which v1 does not honour, so they are not part of the
  program text.
- **Blank program areas** are skipped — every clean logical line therefore has
  real content, which keeps the clean stream tight and the source-map meaningful.

---

## 4. Continuation handling (token-preserving)

A physical line whose indicator (col 7) is `-` **continues the previous logical
line**. Its program-area text folds onto the logical line being built. The join
is conservative and token-preserving:

- **Literal continuation** — if the running logical line ends inside an
  **unterminated quoted literal**, the continuation's program text (after its own
  leading continuation quote, if present) is appended **directly, with no
  separating space**, so the literal's bytes are preserved without a spurious
  token boundary. The open-literal scan honours COBOL's **doubled-quote escape**
  (`''` inside a `'`-literal is an escaped quote, not a terminator).
- **Non-literal continuation** — the continuation's left-stripped program text is
  appended with a **single separating space**, so two code tokens split across a
  continuation do not silently fuse into one. A single space is the safe,
  deterministic choice that keeps tokens intact for the word-boundary / regex
  based extractors.

This satisfies the acceptance criterion *"literal continuation does not corrupt
tokens"* in both directions: literals are not split, and non-literal tokens are
not fused.

Every clean logical line records the original `(file, line)` of its **first**
physical line; continuation lines fold into that logical line and are tracked in
`physical_lines` (all the original line numbers that contributed, in order).

---

## 5. `EXEC SQL ... END-EXEC` block extraction

A line-state machine scans the clean logical lines for `EXEC SQL` …
`END-EXEC` (case-insensitive, whitespace-flexible, multi-line). For each block:

- The **text between the markers** is collected as one SQL block body (the
  `EXEC SQL` and `END-EXEC` marker tokens are **excluded** — only the statement
  body is handed to the SQL extractor).
- A **source span** `(file, start_line, end_line)` records the original physical
  line range of the whole `EXEC SQL ... END-EXEC` region, so `sql_extract`
  (WP-7) can map any finding back to the exact source location.
- The `EXEC SQL` region is **removed from the clean COBOL stream** that
  `cobol_extract` (WP-6) consumes, so the COBOL extractor never trips over
  embedded SQL. (Research §5: extracting the SQL out is easier and cleaner than
  making a COBOL parser swallow it.)

The state machine is tolerant of:

- **single-line blocks** (`EXEC SQL … END-EXEC` on one logical line),
- an `EXEC SQL` marker that **shares its line with the start of the body**, and
- an **unterminated** `EXEC SQL` (no `END-EXEC`): it still yields a block with the
  text collected, spanning to the last line seen — the SQL is **never silently
  dropped**.

---

## 6. The source-map round-trip

The whole point of carrying spans is provenance. `PreprocessResult.origin_of(i)`
maps a **0-indexed clean-line index** back to its original `(file, line)`. It
raises `IndexError` for an out-of-range index (deterministic, no silent clamp).
This is the round-trip the acceptance criterion requires: a clean line resolves
to the correct original physical location, so every downstream edge can cite
exactly where in the source it came from.

---

## 7. Return shape (what downstream consumes)

`preprocess_source(text, file_label) -> PreprocessResult` (and
`preprocess_file(path)` which reads UTF-8 with `errors="replace"` — legacy
EBCDIC-transcoded sources occasionally carry stray bytes and the engine must not
crash on them). `PreprocessResult` carries:

| Field | Meaning |
|---|---|
| `clean_lines: List[CleanLine]` | clean logical program-area lines, EXEC SQL removed; each carries `text`, `origin` `(file, line)`, and `physical_lines`. |
| `sql_blocks: List[SqlBlock]` | extracted SQL bodies with `text`, `file`, `start_line`, `end_line`. |
| `gaps: List[Gap]` | typed diagnostics (e.g. `free_format_unsupported`) — never silently swallowed, never replaced by a guess. |
| `source_format: str` | `"fixed"` or `"free"`. |
| `file: str` | the source-file label, for provenance. |
| `clean_text()` | convenience: the clean program text as one newline-joined string. |
| `origin_of(i)` | the source-map round-trip (§6). |

This clean, provenance-rich output is what the JCL / COBOL / SQL extractors
consume, and is also exactly the structure a **hybrid** flow can hand to an LLM
prompt (see `references/decision-framework.md` §5).

---

## See also

- `references/decision-framework.md` — deterministic vs LLM vs hybrid (the preprocessing core is reusable by either).
- `references/naming-contract.md` — the frozen identity + gap-marking rules the gaps emitted here conform to.
- `scripts/copybook_resolver.py` — `COPY ... REPLACING` expansion (the other half of "preprocessing that breaks naive parsers"), with its own search-path / cycle / depth handling and source-span map.
- `skills/structure-recovery/scripts/cobol_offset_calc.py` — the reused deterministic COBOL PIC/USAGE/record machinery the COBOL extractor builds on.
