---
name: financial-document-ingestion
description: Use when turning business source documents into postable transactions — PDF bank and card statements, PDF sales and purchase invoices, CSV bank exports, marketplace and payment-processor settlement files, and receipts. Covers extraction routes by document type, the validation contract every extraction must pass before it reaches the books, duplicate detection, and how to record provenance so every posted figure traces back to the document it came from.
disambiguation: Turns SOURCE DOCUMENTS into validated transaction rows. Posting those rows, reconciling and closing is bookkeeping-double-entry. Spreadsheet library mechanics are ms-office-excel-python; a CSV too large for context is large-file-analysis; UK tax treatment of what was extracted is the uk-* skills.
---

# Financial document ingestion

Source documents in, validated transaction rows out. Everything downstream — reconciliation, VAT,
year-end, tax — inherits whatever this step gets wrong.

## 1. The rule

**Extracted financial data is untrusted until it passes §4.** An OCR or table-parse error does not
announce itself: a transposed digit, a dropped minus sign or a missed page produces a clean-looking
row that is simply false. The validation contract exists because plausibility is not evidence.

**Never post an unvalidated extraction.** Any figure that fails validation is a **query**, not a
transaction.

## 2. Route by document type

| Document | Preferred route | Notes |
|---|---|---|
| **CSV bank export** | Native parse (`csv`, stdlib) | Best source when available — **always prefer it over the PDF of the same statement** |
| **PDF bank statement, text-based** | Text/table extraction | Most bank PDFs carry a real text layer; try text before OCR |
| **PDF statement, scanned** | OCR | Lowest confidence — validate hardest, expect digit errors |
| **PDF sales/purchase invoice** | Text extraction + field targeting | Needs the fields in §3, not the whole text |
| **Marketplace / processor settlement** | CSV report from the platform | **Never derive from the bank payout alone** — see §6 |
| **Receipts / photos** | OCR | Treat as evidence for a claim, not as the primary record |
| **Spreadsheet (.xlsx)** | `ms-office-excel-python` | |
| **Very large CSV** | `large-file-analysis` | Chunked, never load whole |

**Ask for the CSV first.** A minute spent requesting a bank's CSV export saves an hour of PDF
extraction and removes a whole class of error. Most banks provide CSV/OFX/QIF.

**Settlements have a runnable check**: `scripts/settlement_reconcile.py` proves a payout
decomposes into its orders, fees and refunds before anything is posted, flags period straddle, and
prints the clearing-account journal shape. Money is integer pence throughout — it **refuses a float**
rather than accumulating a penny of drift nobody can later explain.

### Tooling reality on this host

`pdfplumber`, `pypdf`, `fitz`, `pandas` and `openpyxl` are **not installed** here. CSV and the
validation script below are **stdlib-only and work now**. PDF extraction needs a declared optional
dependency — install it deliberately and record it, rather than assuming it is present. **State the
route you actually used in the provenance record (§5)**, because "extracted from PDF" and "parsed
from CSV" carry very different confidence.

**`pdf-processing` covers the mechanics** — which library to choose and on what licence (`fitz` is
AGPL, which matters if this ever ships as a service), digital-versus-scanned detection, OCR flags,
and the extraction traps. This skill owns what the numbers must satisfy *afterwards*; that one owns
getting them off the page.

## 3. Fields to extract

**Bank/card statement line:** date · description/narrative · money in · money out · running balance
(when present) · account identifier

**Invoice** (sales or purchase): supplier/customer name · **their VAT number** · invoice number ·
invoice date · **tax point** (if different) · net · **VAT amount** · **VAT rate** · gross · currency ·
description

> The **VAT amount must be captured as shown on the invoice**, never recomputed from the net. Rounding
> differences, mixed-rate invoices and margin-scheme documents all make a recomputed figure wrong —
> and for a VAT-registered company the invoice figure is the one that supports the claim.

**A purchase invoice without a valid VAT number and VAT amount does not support an input-VAT claim.**
Flag it; do not infer it.

## 4. The validation contract — run before anything is posted

| # | Check | Why |
|---|---|---|
| **V1** | **Running balance continuity** — each line's balance = previous ± movement | Catches dropped, duplicated and mis-signed lines. The single strongest check available. |
| **V2** | **Opening/closing balance** matches the statement header/footer | Catches a missed page |
| **V3** | **Page coverage** — every page accounted for | A missed page passes every per-line check |
| **V4** | **Date range** within the expected period, monotonic | Catches misread years |
| **V5** | **Sign convention** consistent | A dropped minus inverts a transaction |
| **V6** | **Invoice arithmetic** — net + VAT = gross, and VAT ≈ net × rate within rounding | Catches transposed digits |
| **V7** | **Duplicate detection** — same date + amount + reference | Statements overlap at period boundaries |
| **V8** | **Currency** identified and consistent | A foreign line posted at face value is silently wrong |

**V1 is the one that earns its keep.** If a statement carries a running balance, arithmetic proves
the extraction — no other check comes close. Where there is no running balance, say so explicitly:
confidence is materially lower and that belongs in the record.

A helper implementing V1/V2/V6/V7 on extracted rows, stdlib-only:

```bash
python3 ~/.claude/skills/financial-document-ingestion/scripts/validate_extraction.py \
    --rows rows.json --opening 1234.56 --closing 2345.67
```

## 5. Provenance — every row traces back

Record per extraction batch: source filename + **content hash** · document type · extraction route
(csv / pdf-text / pdf-ocr) · page range · period covered · row count · which validations passed ·
unresolved queries.

**Hash the source file.** It is the only way to prove later that the document behind a figure has
not changed, and it makes re-runs idempotent.

**A row whose provenance cannot be stated is not postable.**

## 6. The document store — organise once, reuse for years

Every document that arrives is evidence for a figure that may be questioned years later. HMRC
generally expects company records to be kept for **six years** from the end of the accounting period,
and an enquiry asks for the document, not your recollection of it.

**Store on arrival, index on arrival.** Filing later never happens, and a document you cannot find is
a document you do not have.

### Layout

```
documents/
  bank/<account>/<YYYY>/<YYYY-MM>-statement.pdf
  purchases/<YYYY>/<YYYY-MM>/<supplier>-<invoice-no>.pdf
  sales/<YYYY>/<YYYY-MM>/<invoice-no>.pdf
  payroll/<YYYY>/<YYYY-MM>-payroll-run.pdf
  settlements/<provider>/<YYYY>/<YYYY-MM>-settlement.csv
  filings/<YYYY>/vat-q<N>.json · ct600.pdf · accounts.pdf · confirmation-statement.pdf
  index.json
```

Period-first paths mean a VAT quarter or a year end is one directory listing, which is exactly how
the work is actually organised.

### The index is the point

**This is a command, not a convention** — `scripts/doc_store.py`, schema
`schemas/document-index.v1.json` (26 tests):

```bash
doc_store.py --store documents add --file <path> --doc-type statement \
             --period 2026-06 --account "Barclays Business" --tax-point 2026-06-30
doc_store.py --store documents open-items      # exits 2 while anything is unposted
doc_store.py --store documents link --id <sha-prefix> --posted-ref JNL-2026-06-011
doc_store.py --store documents verify          # re-hash: OK / CHANGED / MISSING
doc_store.py --store documents supersede --old <sha> --new <sha>
```

The placement rules below are enforced rather than described: `sha256` is computed and cannot be
supplied, `stored_path` is derived from the type and period, a byte-different file landing on an
occupied path is **refused**, and re-adding identical bytes is reported as already indexed instead of
creating a second entry. It will not extract, post or prune.

One `index.json` entry per document:

| Field | Why |
|---|---|
| `sha256` | **Identity.** Detects duplicates and proves the file behind a figure has not changed |
| `original_filename` | What the sender called it — often the only clue when a reference is missing |
| `stored_path` | Where it went |
| `doc_type` | statement · purchase_invoice · sales_invoice · settlement · payroll · filing |
| `period` | The period it belongs to, **not** the date it arrived |
| `source` | email · download · woocommerce · bank_export · scan |
| `received_at` / `tax_point` | Arrival vs the date that drives VAT |
| `extracted` | Whether rows were extracted, and whether they passed §4 |
| `posted_ref` | The journal or transaction it became — the link from evidence to entry |
| `superseded_by` | A corrected invoice replaces, never overwrites, the original |

**Hash before you store.** It makes re-ingestion idempotent — the same statement handed over twice is
detected, not double-posted — and it is what lets you prove, later, that this file is the one the
figure came from.

**`posted_ref` is the field that earns its keep.** It closes the loop from document → validated rows
→ posted entry. Without it you have a folder of PDFs and a set of books with no demonstrable
relationship, which is precisely what an enquiry probes.

### Rules

- **Never overwrite.** A corrected document is a new entry with `superseded_by` on the old one. The
  original was the basis of a filed return and remains part of the record.
- **Never rename to "tidy up"** once indexed — the hash and index carry identity, not the filename.
- **Store the original format.** Keep the PDF. A CSV you derived is a convenience copy, not evidence.
- **An indexed document with no `posted_ref` is an open item**, and should appear in the period-end
  review alongside unreconciled differences.
- **Keep for at least six years**, and do not prune by size. Retention periods, the 3-2-1 rule and
  restore testing are in `references/retention-and-backup.md` — **backing up the documents without
  `index.json` leaves a folder of unlabelled PDFs**.

## 7. Traps that produce quietly wrong books

- **The marketplace/processor net-payout trap.** A platform pays out gross sales minus its fees. Post
  only the payout and you understate **turnover** and **costs** simultaneously, and understate output
  VAT — an error with penalty exposure. Always take the settlement report and post gross sales, fees
  and net payout through a clearing account (`bookkeeping-double-entry` §5).
- **Statement overlap.** Consecutive statements repeat boundary transactions. V7 or you double-post.
- **Card vs bank double-counting.** The card feed and the bank direct debit paying the card are the
  same money. One is the expense; the other is the settlement.
- **Transfers between own accounts** are not income or expense; they are one movement seen twice.
- **Refunds and chargebacks** are negative income, not costs — a refund posted as an expense
  overstates both turnover and costs and misstates VAT.
- **Foreign currency** posted at face value. Capture the currency and the rate used.
- **Invoice date vs tax point vs payment date** are three different dates that drive three different
  things (accounts period, VAT period, cash flow).
- **OCR digit confusion** — 0/O, 1/l/7, 5/S, 8/B. V1 catches these; nothing else reliably does.

## 8. When the records are incomplete

Missing paperwork is normal, and it is not a reason to produce nothing. Extract what exists, validate
it, and report the gap in the shape the rest of this harness uses:

```
INCOMPLETE — 11 of 12 statement months extracted
  extracted:   Apr 2026 – Feb 2027, V1 continuity proved across all 11
  missing:     Mar 2027 (statement not supplied)
  impact:      turnover and input VAT understated by an unknown amount for one month
  to resolve:  the March statement, or a bank CSV export for that period
```

State what you have, what it supports, what is missing and what would settle it. **Do not silently
proceed on 11 months and present it as a year**, and do not refuse to work because the twelfth is
absent.

## 9. Anti-patterns

- **Posting an extraction that has not passed V1.**
- **Recomputing invoice VAT instead of reading it.**
- **Accepting the PDF when a CSV of the same data exists.**
- **Trusting OCR digits without arithmetic proof.**
- **Posting net marketplace payouts as turnover.**
- **Losing provenance** — a figure nobody can trace back is unauditable.
- **Presenting a partial extraction as complete.**
- **Filing documents later.** Store and index on arrival, or it does not happen.
- **Overwriting a superseded invoice** — the original was the basis of a filed return.
- **Leaving an indexed document with no `posted_ref`** — evidence with no entry is an open item.
