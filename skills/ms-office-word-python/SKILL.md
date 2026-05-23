---
name: ms-office-word-python
description: Use when reading, writing, transforming, or converting Word documents from Python — .docx (python-docx, docx2txt, mammoth, pypandoc), .docm (macro-enabled — handled with explicit user intent), .doc legacy (LibreOffice headless or antiword), or generating PDF (docx2pdf on Windows/macOS, LibreOffice headless on Linux, pypandoc + xelatex/wkhtmltopdf). Covers OOXML XXE defence, full-fidelity caveats (python-docx is NOT a 100% renderer), and macro handling. Part of the ms-office-python-* skill family.
---

# Microsoft Word — Python

Companion skill to `ms-office-python` (parent). For other areas see: `ms-office-excel-python`, `ms-office-powerpoint-python`, `ms-office-graph-python`, `ms-office-enterprise-sso-python`, `ms-office-security-python`.

<HARD-RULE>
`.docm` round-trips through `python-docx` strip macros silently. NEVER ingest or rewrite a `.docm` file in a pipeline without explicit, logged user intent — the strip is irreversible inside the toolchain. If the workflow requires macros (rare, suspect), refuse to process `.docm` unless the user has expressly confirmed `--accept-macro-strip` or equivalent flag, and log the decision. If the user wants to PRESERVE macros, use `xlwings`-style live-Word automation (`pywin32` + Word installed) or refuse the workflow.
```python
import zipfile, sys
def is_macro_enabled(path):
    with zipfile.ZipFile(path) as zf:
        return "word/vbaProject.bin" in zf.namelist()
if is_macro_enabled("input.docm") and not args.accept_macro_strip:
    sys.exit("Refusing to round-trip .docm without --accept-macro-strip (HARD-RULE)")
```
</HARD-RULE>

---

## Overview

`.docx` (Office Open XML, OOXML) is a zip of XML parts. Python can produce and consume it without Word installed using `python-docx`. Fidelity is a careful word here — see Library Selection for the caveats. Where actual Word is required (PDF render that matches Word's pagination exactly, complex field resolution, tracked-changes layout), the codepath is Windows/macOS-only and depends on a local Word install.

`python-docx` is the dominant library and remains actively maintained. The 2026 reality: it is enough for 80% of programmatic Word work, but it is **NOT a full-fidelity Word renderer** (see HARD-RULE-adjacent caveat below in Library Selection). For full fidelity, route through Word itself or LibreOffice headless.

## Library Selection

| Library | Purpose | Status (2026-05) | OS support | When to use | When NOT to use |
|---|---|---|---|---|---|
| `python-docx` | Read + write `.docx` / `.docm` | Active | All | Default for `.docx` work | Full-fidelity round-trips (tracked changes, complex fields, advanced layout, comments) — **`python-docx` does NOT round-trip these losslessly**. Use Word/LibreOffice if fidelity matters. |
| `docx2txt` | Plaintext extraction | Active | All | Fast text-only extraction from `.docx` | Anything requiring structure (tables, headings) |
| `mammoth` | `.docx` → HTML / Markdown | Active | All | Converting Word to web-readable formats | `.docx` → PDF (different problem) |
| `docx2pdf` | `.docx` → PDF via COM | Active | **Windows / macOS only — requires Word installed** | Single-platform pipelines where Word is present | Headless Linux / containers (silently breaks) |
| `pypandoc` | `.docx` ↔ many formats via pandoc | Active | All (requires pandoc binary) | Cross-platform conversion when fidelity is "good enough" | Pixel-perfect output |
| LibreOffice (`soffice --headless`) | `.docx`/`.doc`/`.docm` ↔ PDF / RTF / HTML / TXT | Active | All | Cross-platform full-fidelity-ish PDF on Linux/macOS | When you don't have LibreOffice (external binary dependency) |
| `antiword` (CLI) | `.doc` (legacy) plaintext | Active (very stable, niche) | All (binary install) | Reading Office 97-2003 `.doc` files when LibreOffice is overkill | `.docx` (not its purpose) |
| `pywin32` (`win32com.client.Dispatch("Word.Application")`) | Drive Word via COM | Active | **Windows only — requires Word installed** | Full-fidelity Word automation on Windows | Linux, headless containers, CI runners; flagged as deprecated approach for new code (see `ms-office-security-python` rule MSOSEC-E003) |
| `defusedxml` | XXE defence | Active | All | Any path that parses OOXML XML you don't fully control | (always include in security-conscious code) |

## Install Commands

### RHEL 9 / AlmaLinux 9 / Rocky 9

```bash
sudo dnf install -y python3.12 python3-pip python3-devel gcc-c++ libxml2-devel libxslt-devel
python3 -m pip install --upgrade pip
python3 -m pip install python-docx docx2txt mammoth defusedxml
# Optional, for PDF / format conversion:
sudo dnf install -y libreoffice-core libreoffice-writer
python3 -m pip install pypandoc
# Optional, for legacy .doc:
sudo dnf install -y antiword
```

### Debian 12 / Ubuntu 24.04

```bash
sudo apt update
sudo apt install -y python3.12 python3-pip python3-dev build-essential libxml2-dev libxslt1-dev
python3 -m pip install --upgrade pip
python3 -m pip install python-docx docx2txt mammoth defusedxml
sudo apt install -y libreoffice-core libreoffice-writer
python3 -m pip install pypandoc
sudo apt install -y antiword
```

### Windows 11

```powershell
winget install --id Python.Python.3.12 -e --silent
python -m pip install --upgrade pip
python -m pip install python-docx docx2txt mammoth defusedxml pypandoc
# Optional, requires Word installed:
#   python -m pip install docx2pdf pywin32
# Optional, headless conversion (no Word required):
#   winget install --id LibreOffice.LibreOffice -e --silent
```

## Capability Matrix

| Feature | python-docx | mammoth | docx2pdf | LibreOffice headless | pypandoc |
|---|---|---|---|---|---|
| Read `.docx` | yes | yes | yes (Word required) | yes | yes |
| Write `.docx` | yes | no | no (PDF output) | yes (via conversion) | yes |
| Read `.doc` (legacy) | no | no | yes (Word required) | yes | yes (via pandoc + filters) |
| Read `.docm` | yes (strips macros) | yes | yes | yes | yes |
| Tracked changes | partial (read-only access to revisions) | no | yes (Word required) | yes | partial |
| Comments | partial | no | yes | yes | partial |
| Complex fields | no | no | yes | yes | partial |
| Convert to PDF | no | no | yes (Win/Mac) | yes (all OS) | yes (requires latex / wkhtmltopdf) |
| Convert to HTML | no | yes | no | yes | yes |
| Convert to Markdown | no | yes | no | yes | yes |
| Embed images | yes | partial | yes | yes | yes |
| Cross-platform | yes | yes | NO (Win/Mac) | yes | yes |

## Decision Sections

### PDF generation

| Scenario | Choice |
|---|---|
| Windows or macOS with Word installed, single-platform pipeline | `docx2pdf` — leverages Word, highest fidelity |
| Linux server / container / CI runner | LibreOffice headless: `soffice --headless --convert-to pdf input.docx --outdir /tmp/out` |
| Need pandoc-style conversion (Markdown → PDF, etc.) | `pypandoc` + `pdflatex` or `wkhtmltopdf` |
| Need pixel-perfect Word fidelity on Linux | Not really possible without a Word license; LibreOffice is the closest free option |

`docx2pdf` calls Word via COM internally and **fails silently** on Linux. Detect the OS and refuse to import `docx2pdf` on Linux to make the fallback path explicit.

### Tracked changes and comments

`python-docx` exposes revisions through the underlying XML but does NOT model them as first-class objects. For programmatic tracked-changes workflows, the practical options are:

1. Convert `.docx` to HTML via `mammoth` and process the `<ins>` / `<del>` elements.
2. Use Word's COM API on Windows (`pywin32`) — flagged deprecated in the validator (E003) for new server code.
3. Round-trip through Word manually (the human user reviews / accepts / rejects).

If your workflow depends on tracked changes, the right choice in 2026 is to migrate the workflow to Word's native model + a server-side service that accepts the user-reviewed output — not to script the accept/reject in Python.

### Macro-enabled documents (`.docm`)

`python-docx.Document(path)` accepts a `.docm` and reads its content, but on save it produces a `.docx` (no macros) or — if you rename — a `.docm` that has had `word/vbaProject.bin` stripped. This is HARD-RULE 1 above. Use the pre-flight detector in the rule to refuse silently-destructive round-trips.

If the workflow legitimately needs to preserve macros (rare; high-trust internal templates), the only path is live Word automation via `pywin32` on a Windows machine.

## Canonical Pattern (modified C3)

**Read a `.docx`, modify a heading, write to a new file** — most common Word task.

```python
# CONFIDENCE: minimal viable pattern — read references/python-docx-patterns.md for production-ready code.
from docx import Document

doc = Document("input.docx")
for paragraph in doc.paragraphs:
    if paragraph.style.name.startswith("Heading 1"):
        paragraph.text = paragraph.text.upper()  # in-place edit; preserves style
doc.save("output.docx")
```

This pattern enforces three things: read-then-write (no in-place mutation of the source), style-aware iteration (not naive string replace), no formula-injection / XXE concern because text is being set as-is via `python-docx` (which uses lxml internally — pin a known-good version).

## Security Hardening

See `ms-office-security-python` for the consolidated checklist. Area-specific items:

- HARD-RULE 1: explicit user intent before any `.docm` round-trip.
- Pair `python-docx` with `defusedxml`. `python-docx` uses `lxml` internally; `lxml` has had multiple XXE CVEs. Pin the version and run `pip-audit` (delegate to `dep-currency-check`).
- For untrusted `.docx` input, parse in a sandboxed subprocess or container — billion-laughs and zip-bomb payloads are realistic.
- NEVER pass user-controlled paths to `docx2pdf.convert` — it spawns Word in the current user session; Word will follow any embedded `INCLUDETEXT` / `INCLUDEPICTURE` field, which can fetch from network. Strip fields before conversion if input is untrusted.
- Inspect `doc.core_properties` (author, last_modified_by, comments, keywords) before publishing externally — these carry PII and internal usernames.
- Workbook-style "embedded objects" in `.docx` (charts, OLE objects) can contain arbitrary file content. Enumerate `doc.inline_shapes` and `doc.tables[].rows[].cells[].tables` before declaring a document "safe."
- When converting Word to plaintext for downstream NLP / vector storage, strip embedded base64 images via `docx2txt`'s `img_dir` mode and decide explicitly whether to retain them.
- For PDF generation on Linux via LibreOffice, run `soffice` with `--norestore --nodefault --headless` and a clean `--env:UserInstallation=file:///tmp/lo-user-$$` to avoid lockfile contention in parallel CI runs.
- Audit log every `.docx` ingestion of a tracked / comment-bearing document — review-cycle metadata is sensitive.
- Refuse to process documents larger than a hard `MAX_BYTES` cap. Word documents over a few hundred MB are almost always pathological.

## Selection Cheatsheet

- "Read a .docx into Python objects" → `python-docx`
- "Fast plaintext extraction" → `docx2txt`
- "`.docx` → HTML / Markdown" → `mammoth`
- "`.docx` → PDF on Linux/headless" → LibreOffice headless
- "`.docx` → PDF on Windows with Word installed" → `docx2pdf`
- "Convert between many doc formats" → `pypandoc`
- "Legacy `.doc` (Office 97-2003)" → LibreOffice headless OR `antiword`
- "Macro-preserving round-trip" → live Word via `pywin32` (Windows only) OR refuse the workflow

## Gotchas

- `python-docx` is NOT a full-fidelity Word renderer. Tracked changes, complex fields, comments, advanced layout do NOT round-trip losslessly. State this explicitly to users when designing a doc-modification pipeline.
- `docx2pdf` requires Word installed and is Windows/macOS only. It fails silently / cryptically on Linux. Detect OS and route around.
- `python-docx` strips macros from `.docm` on save — covered in HARD-RULE 1, repeated here because it bites.
- Word's auto-numbering (lists) is brittle through `python-docx` — round-tripping a heavily-numbered document loses numbering style continuity. Test before relying.
- LibreOffice headless contention: parallel runs share a profile dir by default and fail with "another OpenOffice.org process is running." Use `--env:UserInstallation=file:///tmp/lo-user-$$` per process.
- `pypandoc` requires the `pandoc` binary on PATH — bundled `pypandoc-binary` is an alternative pip-installable form that ships a static pandoc.
- `.docx` files are zips. Some "broken" docs are actually zip-corrupted; `zipfile.ZipFile(path).testzip()` is a quick triage.

## Update Triggers (per Codex M-1 — alf will scan these)

- Major version bump of: `python-docx`, `mammoth`, `lxml`, `pypandoc`, `docx2pdf`.
- New OOXML schema change announced by Microsoft.
- CVE published against `lxml` (XXE class) or `python-docx`.
- LibreOffice CLI flag changes (rare, but the `soffice` headless surface has churned historically).
- Annual review on: 2027-05-22.

## See Also

| Need | Skill |
|---|---|
| Excel manipulation | `ms-office-excel-python` |
| PowerPoint generation | `ms-office-powerpoint-python` |
| Sending Word docs through Outlook / SharePoint via Graph | `ms-office-graph-python` |
| Hardening / validator / checklist | `ms-office-security-python` |
| Live Word automation on Windows | `windows-powershell` + `windows-ps-server-admin` (PowerShell-driven Word) for PS-native paths |
