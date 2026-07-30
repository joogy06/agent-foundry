---
name: ms-office-excel-python
description: Use when reading, writing, transforming, decrypting, or converting Excel files from Python — .xlsx (openpyxl, xlsxwriter, pandas), .xls legacy (xlrd <2.0), .xlsb (pyxlsb), encrypted workbooks (msoffcrypto-tool), Excel automation on Windows/macOS with Office installed (xlwings, pywin32 COM), or formula evaluation without Excel (pycel, formulas). Covers formula injection (CWE-1236) sanitization, XXE defence for parsed XML, and large-file streaming patterns. Part of the ms-office-python-* skill family.
family: ms-office
disambiguation: Excel files from Python. Word documents are ms-office-word-python; decks are ms-office-powerpoint-python.
---

# Microsoft Excel — Python

Companion skill to `ms-office-python` (parent). For other areas see: `ms-office-word-python`, `ms-office-powerpoint-python`, `ms-office-graph-python`, `ms-office-enterprise-sso-python`, `ms-office-security-python`.

<HARD-RULE>
Sanitize cell content against formula injection (CWE-1236). When writing user-controlled values into a workbook, strip or escape leading `=`, `+`, `-`, `@`, `\t`, `\r`. Excel interprets a leading equals sign as a formula; combined with `WEBSERVICE()`, `HYPERLINK()`, or `DDE()`, this is a data-exfiltration vector when the workbook is opened by an end user.
```python
def safe_cell(value):
    if isinstance(value, str) and value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value  # leading apostrophe forces text interpretation
    return value
```
</HARD-RULE>

<HARD-RULE>
`xlrd >= 2.0` cannot read `.xlsx`. Pin `xlrd<2.0` for `.xls` legacy ONLY and use `openpyxl` or `pandas[excel]` for `.xlsx`. Mixing the two in one project is the most common Excel-on-Python regression — engine selection in pandas defaults shifted in 1.2.0, and silent fallbacks have been removed. Greenfield code: `openpyxl` (read/write) or `xlsxwriter` (write-only, faster).
</HARD-RULE>

---

## Overview

`.xlsx` (Office Open XML, OOXML) is a zip of XML parts. Python can produce and consume it without Office installed using pure-Python libraries. Where Excel itself is required (formula recalculation, COM automation, fidelity-perfect rendering), the codepath is Windows/macOS-only and depends on a local Office install. The 2026 ecosystem state is mature for `.xlsx` (openpyxl + xlsxwriter + pandas), legacy for `.xls` (xlrd<2.0), and niche for `.xlsb` (pyxlsb, read-only).

Formula injection (CWE-1236) is the single most common security mistake in Python Excel code — covered above as HARD-RULE 1. XXE in OOXML parsing is the second; `defusedxml` is the family-wide remedy.

## Library Selection

| Library | Purpose | Status (2026-05) | OS support | When to use | When NOT to use |
|---|---|---|---|---|---|
| `openpyxl` | Read + write `.xlsx` / `.xlsm` | Active | All | Default for any new `.xlsx` work | Massive workbooks (use `read_only=True` mode); when you need full Excel fidelity (use Excel/LibreOffice) |
| `xlsxwriter` | Write-only `.xlsx` | Active | All | Generating large `.xlsx` from scratch (faster than openpyxl write) | Editing an existing file (it can't) |
| `pandas` (with `openpyxl` / `xlsxwriter` backends) | DataFrame I/O | Active | All | Tabular data round-tripping; analytical workflows | Cell-level formatting / formulas / charts |
| `xlrd` (<2.0) | Read `.xls` legacy | Active (legacy code path only) | All | Reading `.xls` (Office 97-2003) files | Reading `.xlsx` — `xlrd >= 2.0` removed `.xlsx` support |
| `pyxlsb` | Read `.xlsb` (binary) | Active | All | Reading binary Excel format produced by some enterprise workflows | Writing `.xlsb` — read-only |
| `xlwings` | Drive Excel application via COM | Active | Windows / macOS only (requires Excel) | Interactive Excel automation, recalculation, full-fidelity workflows | Linux, headless containers, CI runners |
| `pywin32` (`win32com.client`) | Low-level Windows COM | Active | Windows only | Niche COM automation patterns not covered by xlwings | Cross-platform code, server contexts (Service-broker COM is fragile) |
| `msoffcrypto-tool` | Decrypt password-protected workbooks | Active | All | Reading encrypted `.xlsx` (and other Office formats) | Encryption (not its purpose) |
| `pycel` | Pure-Python formula evaluator | Active | All | Computing formula results without Excel; targeted recalculation | Full workbook fidelity (limited formula coverage) |
| `formulas` | Formula evaluator (alternate) | Active | All | Same as pycel; different coverage profile | Same as pycel |
| `defusedxml` | XXE defence for stdlib XML | Active | All | Any XML parsing path you control (third-party libs may not honour it) | (always include) |

## Install Commands

### RHEL 9 / AlmaLinux 9 / Rocky 9

```bash
sudo dnf install -y python3.12 python3-pip python3-devel gcc-c++ libxml2-devel libxslt-devel
python3 -m pip install --upgrade pip
python3 -m pip install openpyxl xlsxwriter pandas msoffcrypto-tool defusedxml
# Optional, legacy:
#   python3 -m pip install 'xlrd<2.0'  # .xls only
# Optional, binary:
#   python3 -m pip install pyxlsb
```

### Debian 12 / Ubuntu 24.04

```bash
sudo apt update
sudo apt install -y python3.12 python3-pip python3-dev build-essential libxml2-dev libxslt1-dev
python3 -m pip install --upgrade pip
python3 -m pip install openpyxl xlsxwriter pandas msoffcrypto-tool defusedxml
# Same optional packages as RHEL.
```

### Windows 11

```powershell
winget install --id Python.Python.3.12 -e --silent
python -m pip install --upgrade pip
python -m pip install openpyxl xlsxwriter pandas msoffcrypto-tool defusedxml
# Optional, requires Excel installed:
#   python -m pip install xlwings pywin32
```

## Capability Matrix

| Feature | openpyxl | xlsxwriter | pandas | xlwings | pyxlsb |
|---|---|---|---|---|---|
| Read `.xlsx` | yes | no | yes (engine=openpyxl) | yes (Excel required) | no |
| Write `.xlsx` | yes | yes | yes (engine=openpyxl/xlsxwriter) | yes (Excel required) | no |
| Read `.xls` | no | no | yes (engine=xlrd<2.0) | yes (Excel required) | no |
| Read `.xlsb` | no | no | yes (engine=pyxlsb) | yes (Excel required) | yes |
| Read encrypted | partial (with msoffcrypto-tool preprocessor) | no | partial (same) | yes (Excel required) | no |
| Calculate formulas | no (reads cached values only) | no | no | yes (live Excel) | no |
| Charts | yes (basic) | yes (rich) | partial (via openpyxl) | yes | no |
| Conditional formatting | yes | yes | partial | yes | no |
| Streaming / large file | yes (`read_only=True` / `write_only=True`) | yes (write only) | yes (`chunksize` for read) | no | yes (streaming reader) |
| Cross-platform | yes | yes | yes | NO (Win/Mac) | yes |

## Decision Sections

### Read-vs-write performance

- **Reading a large file** (>50 MB): `openpyxl.load_workbook(path, read_only=True, data_only=True)` — streams rows lazily, ~10x memory reduction. `data_only=True` returns cached values (formula results) instead of formula text.
- **Writing a large file from scratch**: `xlsxwriter` outperforms openpyxl by 2-5x. Use `Workbook(path, {'constant_memory': True})` to drop in-memory row state after each `worksheet.write_row` call.
- **Editing an existing large file**: openpyxl is the only pure-Python option (xlsxwriter is write-only). Accept the memory cost or split the file.

### Formula handling

`openpyxl` and `xlsxwriter` write formula strings but **DO NOT evaluate them**. The workbook ships with stale cached values unless something recalculates. Options:

1. **Open in Excel/LibreOffice** to force recalculation (one-time, manual).
2. **Set `workbook.calc_properties.fullCalcOnLoad = True` (xlsxwriter)** — instructs Excel to recalculate when next opened.
3. **Use `xlwings`** — drives a live Excel instance to recalculate (Windows/macOS only).
4. **Use `pycel` or `formulas`** — pure-Python evaluators with partial coverage; verify against your specific formula set.

Shipping a workbook with stale cached values to an end user is a common bug — make this an explicit decision, not an oversight.

### Encrypted workbooks

```python
import io, msoffcrypto, openpyxl
with open("encrypted.xlsx", "rb") as fh:
    decrypted = io.BytesIO()
    office_file = msoffcrypto.OfficeFile(fh)
    office_file.load_key(password="secret")  # PASSWORD MUST COME FROM A VAULT, NOT A LITERAL
    office_file.decrypt(decrypted)
decrypted.seek(0)
workbook = openpyxl.load_workbook(decrypted, read_only=True)
```

The password is the input most likely to leak — see `ms-office-security-python` for vault patterns.

## Canonical Pattern (modified C3)

**Read a `.xlsx` file, transform a column, write to a new file** — the most common task in the family.

```python
# CONFIDENCE: minimal viable pattern — production hardening notes in the Security Hardening section below; full references/ guide planned (v1.1).
import openpyxl

def safe_cell(value):
    if isinstance(value, str) and value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value

wb = openpyxl.load_workbook("input.xlsx", read_only=False, data_only=True)
ws = wb.active
header = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
out = openpyxl.Workbook()
out_ws = out.active
out_ws.append(header)
for row in ws.iter_rows(min_row=2, values_only=True):
    transformed = [safe_cell(v.upper() if isinstance(v, str) else v) for v in row]
    out_ws.append(transformed)
out.save("output.xlsx")
```

Three things this pattern enforces: explicit `data_only` choice, formula-injection sanitization on every string write, no global state. References cover streaming-for-large-files, conditional formatting, and chart embedding.

## Security Hardening

See `ms-office-security-python` for the consolidated checklist. Area-specific items:

- Sanitize every user-controlled string written to a cell against formula injection (HARD-RULE 1).
- For untrusted `.xlsx` input, use `openpyxl.load_workbook(path, read_only=True, data_only=True)` and pair with `defusedxml` to neutralize XXE / billion-laughs payloads inside the embedded XML.
- NEVER pass user-controlled paths to `os.path.expanduser` / `os.path.expandvars` then to `load_workbook` — path traversal risk; canonicalize and confine to an explicit base directory.
- When `openpyxl` ingests a `.xlsm`, it strips macros silently. If the workflow must preserve macros, choose `xlwings` (live Excel) or document the macro-strip as intentional in code comments.
- Decrypt passwords come from a vault / Managed Identity / OS credential store — never from source, env vars containing plaintext, or config files in git.
- For large untrusted files, set a hard `MAX_ROWS` / `MAX_COLS` budget BEFORE iterating — pathological files can exhaust memory through column-sparse-row patterns even in `read_only` mode.
- When converting Excel to CSV or JSON, never blindly stringify cells — strip control characters (`\x00`-`\x08`, `\x0b`, `\x0c`, `\x0e`-`\x1f`) and serialize numbers / dates / booleans with explicit type handling. CSV downstream consumers (esp. Excel reopening the CSV) suffer formula injection if you skip sanitization a second time.
- Audit log every read of an encrypted workbook (filename + actor + timestamp). Forensically, the act of decryption is more important than the cell contents.
- Pin `lxml` and `openpyxl` versions explicitly. `lxml` has had several XXE CVEs; floating versions cause regressions.
- Workbook properties (`creator`, `last_modified_by`, `description`, custom doc properties) carry user-identifiable data — strip or sanitize before publishing externally.

## Selection Cheatsheet

- "Read a .xlsx file" → `openpyxl.load_workbook(path, read_only=True, data_only=True)`
- "Write a .xlsx file from scratch, performance matters" → `xlsxwriter.Workbook(path, {'constant_memory': True})`
- "Round-trip a DataFrame" → `pandas.read_excel(path, engine='openpyxl')` / `df.to_excel(path, engine='openpyxl')`
- "Decrypt a password-protected file" → `msoffcrypto-tool` → BytesIO → openpyxl
- "Run actual Excel to recalc formulas" → `xlwings` (Windows/macOS only)
- "Compute formulas without Excel" → `pycel` / `formulas` (partial coverage; verify)
- "Read .xls (legacy)" → `xlrd<2.0`
- "Read .xlsb (binary)" → `pyxlsb`

## Gotchas

- `openpyxl` and `xlsxwriter` do NOT calculate formulas — the workbook will contain stale cached values until something recalculates (Excel, LibreOffice, xlwings, pycel). Plan for this.
- `xlwings` is Windows/macOS-only AND requires a local Excel install. Headless Linux CI cannot use it.
- `xlrd` removed `.xlsx` support at v2.0 (2020). If `pip install xlrd` resolves to >=2.0, expect failures on `.xlsx`.
- `openpyxl`'s `data_only=True` returns cached values — if the file was written by a non-Excel library, those values may be missing or stale.
- `pandas.read_excel` engine selection is opinionated: `.xlsx` → openpyxl, `.xls` → xlrd<2.0, `.xlsb` → pyxlsb. Override explicitly when the inference is wrong.
- COM automation via `pywin32` in a service / scheduled-task context is fragile — Office prefers a desktop session. Prefer `xlwings` for interactive contexts and Graph + .xlsx file paths for server contexts.
- `.xlsm` round-trips through `openpyxl` strip macros (HARD-RULE in `ms-office-word-python` for .docm — same applies here in spirit). State this in code or refuse to process .xlsm without explicit user intent.
- Encrypted workbooks routed through `msoffcrypto-tool` produce an in-memory `BytesIO` — large files consume RAM proportional to file size. Stream-decrypt is not supported in 2026-05.

## Update Triggers (per Codex M-1 — alf will scan these)

- Major version bump of: `openpyxl`, `xlsxwriter`, `pandas`, `xlrd`, `lxml`, `msoffcrypto-tool`.
- New OOXML / `.xlsx` schema change announced by Microsoft (rare but happens).
- CVE published against `lxml` or `openpyxl` (XXE-class).
- Annual review on: 2027-05-22.

## See Also

| Need | Skill |
|---|---|
| Word / Markdown / PDF conversions | `ms-office-word-python` |
| PowerPoint generation | `ms-office-powerpoint-python` |
| Sending an Excel as Outlook attachment | `ms-office-graph-python` |
| Hardening / validator / checklist | `ms-office-security-python` |
| Reading enterprise-encrypted workbooks with cert-based DRM | `python-auth-security` + IRM/RMS coverage (not in v1) |
| Dependency CVE scanning | `dep-currency-check` |
