---
name: pdf-processing
description: Use when reading, creating, modifying or securing PDFs from Python or the command line — library and licence selection, text and table extraction from digital versus scanned files, OCR, generating PDFs from code or HTML, merging, splitting, watermarking, encryption and metadata, filling and flattening forms, genuine redaction as opposed to drawing black boxes, PDF/A archival, and treating an inbound PDF as untrusted input. Covers Windows, macOS and Linux including the command-line tools.
disambiguation: PDFs as a FORMAT — extract, create, modify, secure, redact. Turning bank statements and invoices into ledger entries is financial-document-ingestion; converting Office documents to PDF is the ms-office-python family; rendering a deck is presentation-renderer; chunking extracted text for retrieval is rag-architecture; working around the context window on a huge file is large-file-analysis.
---

# PDF processing

<!-- REVIEW-BY: 2027-01-31 -->
**Verified 2026-07-29.** Library positions and licences change; **re-check the licence before adopting
any library named here** — §1 explains why that is not a formality.

## 0. The framing that prevents most PDF mistakes

**PDF is a print format, not a data format.** It records where marks go on a page. It does not record
paragraphs, reading order, table structure, or which number is a total. Everything downstream —
extraction, tables, reading order — is *reconstruction*, and reconstruction is sometimes wrong.

**Where the source data exists, use it instead of the PDF.** A CSV export, an API, or the database
behind the report will always beat parsing its printed output. Parse PDFs when the PDF genuinely is
the only artefact — which, for invoices and statements arriving from third parties, it usually is.

## 1. Two traps that cause real damage

### The licence trap

**PyMuPDF (`fitz`) is AGPL-3.0.** It is the fastest option by a wide margin — roughly an order of
magnitude over pdfplumber on plain text extraction — and that speed is why it ends up in prototypes.
**AGPL reaches network use**: shipping it inside a service you offer to others obliges you to release
your source, or to buy a commercial licence.

**Ghostscript is likewise AGPL**, and it hides inside conversion pipelines and Docker images.

| Library | Licence | Strength |
|---|---|---|
| **`pypdf`** | BSD | Pure Python. Merge, split, rotate, metadata, basic text. No compiled deps |
| **`pdfplumber`** | MIT | **Best tables** and per-character geometry. Slow |
| **`pikepdf`** | MPL-2.0 | qpdf bindings — structural repair, encryption, linearisation |
| **`PyMuPDF` / `fitz`** | **AGPL-3.0** or commercial | Fastest extraction and rendering |
| **`reportlab`** | BSD (open core) | Programmatic generation |
| **`WeasyPrint`** | BSD | HTML/CSS → PDF |
| **`ocrmypdf`** | MPL-2.0 | Adds an OCR text layer, outputs PDF/A |

**Decide the licence before the benchmark.** Discovering the constraint after the pipeline is built
is the expensive order, and "we'll swap it later" rarely survives contact with a schedule.

### The redaction trap

**Drawing a black rectangle over text does not remove the text.** The characters remain in the
content stream; select-all and copy retrieves them, and so does any extraction library. This has
leaked real documents from real institutions, repeatedly.

**Worse on scanned files:** OCR adds an *invisible text layer* under the image. Covering the visible
image leaves that layer fully searchable.

**Word, Google Docs and macOS Preview perform overlay, not redaction — including where the UI says
"redact".**

**Genuine redaction removes the content-stream operators**, then rewrites the file:

```python
import fitz  # PyMuPDF — check §1 licence before using
doc = fitz.open("in.pdf")
for page in doc:
    for rect in page.search_for("Confidential Name"):
        page.add_redact_annot(rect, fill=(0, 0, 0))
    page.apply_redactions()          # THIS is the step that deletes content
doc.save("out.pdf", garbage=4, deflate=True, clean=True)
```

**Then verify, every time, and treat verification as part of the job:**

```bash
pdftotext out.pdf - | grep -i "confidential name"   # must return NOTHING
qpdf --show-npages out.pdf
exiftool out.pdf                                     # metadata, author, prior filenames
pdfimages -list out.pdf                              # embedded images retain their own metadata
```

**Also scrub what is not on the page**: document metadata, XMP, annotations and comments, embedded
attachments, bookmarks, form-field values, and earlier revisions retained by incremental saves. A
`save()` without `garbage=4, clean=True` can leave the removed objects present but unreferenced.

## 2. Reading and extracting

**First establish which kind of PDF you have** — the two need completely different handling, and
guessing wrong produces empty output or silent nonsense:

```python
import pypdf
r = pypdf.PdfReader("in.pdf")
chars = sum(len((p.extract_text() or "")) for p in r.pages[:3])
kind = "digital" if chars > 100 else "scanned-or-image"   # needs OCR (§3)
```

```bash
pdffonts in.pdf      # no fonts listed → it is images, not text
pdftotext -layout in.pdf -   # fast triage from the shell
```

- **Reading order is not guaranteed.** Extraction returns marks in content-stream order, which for
  multi-column layouts interleaves columns. `pdfplumber`'s coordinates let you sort or crop by
  region; `pdftotext -layout` preserves visual arrangement well enough for many cases.
- **Tables are the hard part.** `pdfplumber` is the strongest open, permissively-licensed option, and
  ruled tables extract far better than whitespace-aligned ones.
- **Ligatures, hyphenation and soft hyphens** corrupt naive string matching — `ﬁ` is one character,
  and a word split across lines rejoins with an embedded hyphen.
- **Never trust a number you extracted without a check that can fail.** For financial documents that
  check is a running-balance or total reconciliation — see `financial-document-ingestion`.

For document-understanding rather than string extraction — complex layouts, borderless tables,
mixed content — **layout-aware parsers (Docling, Marker) produce markedly better structured output**
than coordinate heuristics, at a real cost in speed and dependencies. For a genuinely awkward table,
**rendering the page to an image and asking a vision model often beats every deterministic parser** —
treat that as a fallback with a verification step, never as the default.

## 3. OCR

```bash
ocrmypdf --skip-text in.pdf out.pdf          # add a text layer, keep existing text
ocrmypdf --force-ocr --output-type pdfa in.pdf out.pdf
ocrmypdf --sidecar out.txt in.pdf out.pdf    # PDF plus a plain-text sidecar
ocrmypdf -l eng+deu in.pdf out.pdf           # multiple languages
```

- **`--skip-text` vs `--force-ocr` matters.** `--force-ocr` rasterises pages that already had real
  text, degrading quality and losing selectable accuracy. Default to `--skip-text`.
- **OCR output is a hypothesis, not a reading.** `0`/`O`, `1`/`l`, `5`/`S` and decimal points are the
  usual casualties. Anything financial needs an arithmetic check downstream.
- **Image quality dominates accuracy** far more than engine choice — deskew and clean first
  (`--deskew --clean`); 300 DPI is the practical floor.

## 4. Creating PDFs

| Route | Best for | Watch |
|---|---|---|
| **`reportlab`** | Precise programmatic layout: statements, certificates, labels | Verbose; you place everything |
| **`WeasyPrint`** (HTML/CSS) | Invoices, reports, anything with a designer | No JavaScript — charts must be pre-rendered |
| **Headless browser** (Playwright/Puppeteer) | Pages needing JS charting | Much heavier; substantially larger output |
| **LibreOffice headless** | Converting existing Office documents | Fidelity close but not Word-identical |

**HTML plus CSS Paged Media is the pragmatic default** for business documents — the template is
editable by someone who is not a Python developer, and CSS handles page breaks, running headers and
page numbers properly.

**The browser route is faster per document and produces much larger files**; WeasyPrint is slower per
document and produces far smaller ones. **Choose on whether you need JavaScript**, then on volume —
not on the benchmark alone.

**PDF/A for anything with a retention obligation.** `ocrmypdf --output-type pdfa` is the least
painful route, and archival compliance is a requirement you cannot retrofit cheaply once a million
documents exist.

## 5. Modifying

```python
from pypdf import PdfReader, PdfWriter

w = PdfWriter()
for src in ("a.pdf", "b.pdf"):
    w.append(src)                       # merge
w.add_metadata({"/Title": "Merged", "/Producer": ""})
w.encrypt("user-pw", "owner-pw", algorithm="AES-256")
with open("out.pdf", "wb") as fh:
    w.write(fh)
```

```bash
qpdf --empty --pages in.pdf 1-5 -- out.pdf        # split
qpdf --decrypt --password=PW in.pdf out.pdf       # remove known encryption
qpdf --check in.pdf                               # structural validation
qpdf --linearize in.pdf out.pdf                   # fast web view
qpdf --qdf in.pdf out.pdf                         # readable internals, for debugging
```

**`pikepdf`/`qpdf` is the right tool for a structurally broken file** that other libraries refuse —
it repairs cross-reference tables and rebuilds object streams.

**Incremental saves retain history.** Writing a fully rebuilt file (`qpdf`, or PyMuPDF with
`garbage=4, clean=True`) is what actually removes deleted content.

## 6. Forms

```python
from pypdf import PdfReader, PdfWriter
r = PdfReader("form.pdf"); w = PdfWriter(clone_from=r)
w.update_page_form_field_values(w.pages[0], {"full_name": "A Person"})
w.set_need_appearances_writer(True)      # or values render blank in some viewers
```

- **AcroForm is the standard; XFA is Adobe's deprecated XML alternative** and most Python tooling
  cannot fill it. An XFA form usually needs Acrobat or a commercial library — identify which you have
  before promising a delivery date.
- **`NeedAppearances` is the classic bug**: values are set in the file but render blank because no
  appearance stream was generated.
- **Flatten before sending anything final.** An unflattened form is still editable by the recipient.
- **A filled field is not redacted** — clearing a value can leave it in the appearance stream.

## 7. Security, honestly

- **PDF passwords and permissions are advisory.** The "no printing / no copying" flags are honoured
  by cooperative viewers and ignored by everything else; `qpdf --decrypt` removes them given the user
  password. **Encryption protects content only while the password is unknown — permissions protect
  nothing.** Do not present them to anyone as a control.
- **AES-256 for real encryption**; RC4 and 40/128-bit are legacy and broken.
- **A PDF is untrusted input.** It can carry JavaScript, embedded files, external references and
  malformed structures that have historically driven parser exploits. Parse in a constrained
  environment, cap page counts and file sizes, and set timeouts.
- **PDFs feeding an LLM pipeline can carry prompt injection**, including in white-on-white text or
  the invisible OCR layer — invisible to the reviewer, fully visible to the model. This is a
  documented technique, not a hypothetical. See `llm-security`.
- **Digital signatures** are outside pure-Python comfort; `pyHanko` is the credible open option, and
  signing needs a real certificate and a timestamp authority, not just a library.

## 8. Command line, per platform

**Everywhere** (poppler-utils + qpdf — the fastest triage available):

```bash
pdftotext -layout f.pdf -      # extract text
pdfinfo f.pdf                  # pages, size, producer, encryption
pdffonts f.pdf                 # empty → scanned
pdfimages -list f.pdf
pdftoppm -r 300 -png f.pdf page   # render to images
qpdf --check f.pdf
```

| | Install | Native extras |
|---|---|---|
| **macOS** | `brew install poppler qpdf ocrmypdf` | `sips`; Quartz filters; Preview and Automator/Shortcuts. **Preview's "redact" is overlay only** |
| **Windows** | `winget install ... ` / `choco install poppler qpdf` | "Microsoft Print to PDF" printer; PowerShell over COM where Acrobat is installed |
| **Linux** | `apt install poppler-utils qpdf ocrmypdf` | Native home for the whole toolchain |

**On macOS, `sips` and Quartz filters compress and convert without extra installs**, but neither
redacts. **On Windows, "Print to PDF" flattens everything** — sometimes exactly what you want, and it
does destroy text selectability, so it is not a substitute for redaction either (the marks under a
black box are gone, but so is every other piece of extractable text).

## 9. Anti-patterns

- **Drawing black boxes and calling it redaction.**
- **Redacting without verifying** by extracting text from the output.
- **Forgetting metadata, annotations, attachments and prior revisions** when sanitising.
- **Adopting PyMuPDF or Ghostscript in a commercial service** without reading the AGPL.
- **Treating PDF permissions as a security control.**
- **RC4 or 40-bit encryption** on anything current.
- **Assuming extraction order is reading order.**
- **`--force-ocr`** on a PDF that already had real text.
- **Trusting extracted numbers** with no arithmetic check that can fail.
- **Parsing a PDF** when a CSV, API or database holds the same data.
- **Feeding untrusted PDF text straight into a prompt.**
- **Shipping an unflattened form** as a final document.
