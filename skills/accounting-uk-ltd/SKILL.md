---
name: accounting-uk-ltd
description: Use when running the accounts of a small UK VAT-registered limited company — the full cycle of bookkeeping, bank and control-account reconciliation, VAT returns under MTD, year-end statutory accounts, CT600 corporation tax, payroll RTI, and the Companies House and HMRC deadline map. Routes to the specialist siblings and owns the engagement flow, the deadline calendar, and the current-year rates reference. Trigger on - my company accounts, VAT return, year end, CT600, corporation tax return, Companies House filing, annual accounts, bookkeeping, trial balance, payroll, HMRC deadline, small company accounts.
disambiguation: The PARENT of the UK small-company accounting family and the owner of the engagement flow, deadline map and rates reference. Individual mechanics live in the siblings — bookkeeping-double-entry, uk-vat, uk-corporation-tax, uk-statutory-accounts, uk-payroll, financial-document-ingestion. Project budget-vs-actual and earned value is project-finance, not this.
---

# Accounting — UK small VAT-registered Ltd

The operating skill for a small UK limited company that is VAT-registered: keep the books, reconcile
them, file VAT, close the year, compute corporation tax, run payroll, and hit every deadline.

## 1. What this family cannot do — read first

**These skills do not file anything, and must never imply they do.**

The joint HMRC/Companies House online filing service **closed on 31 March 2026**. Since then:

| Submission | Route |
|---|---|
| **CT600 + computations + iXBRL accounts → HMRC** | **Commercial software effectively mandatory.** Paper only with a reasonable excuse or in Welsh. Or an authorised agent. |
| **Annual accounts → Companies House** | Still flexible — CH online, third-party software, or paper by post. Software-only is coming **April 2028** (deferred from 2027). |
| **VAT return → HMRC** | MTD-compatible software with an unbroken **digital link**. |
| **Payroll → HMRC** | RTI submissions from payroll software. |

So the job here is everything **up to** submission: ingest the documents, keep the books, reconcile,
compute, validate, produce the figures and the audit trail, and name the deadline. Then hand to
recognised software or an accountant.

**Say this out loud to the user when they ask you to "file" something.** A skill that lets someone
believe a return was submitted is worse than one that refuses.

## 2. THE ROUTINE — run this every time this skill is invoked

**Do this before answering anything.** It takes seconds and it is what makes the skill an operating
system for the company rather than a reference book.

```bash
T=.accounting/tracker.json          # per-company, in the project

# 1. FIRST CONTACT ONLY — no tracker yet? Analyse the business and build one.
python3 ~/.claude/skills/accounting-uk-ltd/scripts/tracker.py \
    init --company company.json --out "$T"

# 2. EVERY invocation — what is overdue, due soon, or newly in force
python3 ~/.claude/skills/accounting-uk-ltd/scripts/tracker.py status --tracker "$T"

# 2b. EVERY invocation — what CHANGED about the business itself
python3 ~/.claude/skills/business-profile/scripts/profile.py \
    --profile .accounting/business-profile.json check

# 3. Record progress as it happens (evidence is REQUIRED to mark done)
python3 ~/.claude/skills/accounting-uk-ltd/scripts/tracker.py \
    update --tracker "$T" --id vat_return-quarter-ending-2026-09-30 \
    --status done --evidence "HMRC receipt IRmark ABC123"

# 4. Periodically — what law/rates need re-verifying
python3 ~/.claude/skills/accounting-uk-ltd/scripts/tracker.py law-check --tracker "$T"
```

**No tracker → run `init` first.** Establish §3's facts by asking, build the calendar, and say what
was assumed. Do not answer a VAT or year-end question for a company you have not profiled: the
answer depends on the scheme, the ARD and the framework, and guessing those produces a confident
wrong answer.

**Tracker exists → run `status` first**, and lead your reply with anything overdue. The user asking
about one thing does not make the other obligations stop running.

**Run the profile `check` too.** The tracker knows what is DUE; the profile knows what the business
normally LOOKS like — who each vendor is, how they bill, what they normally cost. It answers "who is
this transaction?" without rediscovering it every session, and it flags a recurring bill that stopped
arriving, which no balance check can see. See `business-profile`.

### What the routine guarantees

- **Due dates are computed** from the profile plus the statutory rule, and each obligation carries
  the rule it came from — so a date you disagree with can be argued with rather than just distrusted.
- **`overdue` cannot be asserted away.** It is derived from the due date and today, every run. You
  may record that something is *done*; nobody can record that it is *not due*.
- **`done` requires evidence.** A submission reference, receipt or filing id. "Done" with nothing
  behind it is indistinguishable from forgotten.
- **`init` refuses to invent a profile.** A missing accounting reference date is a question, not a
  default.

### The law-watch loop, and its honest limit

`law-check` computes staleness and prints the sources to verify. **It cannot browse.** You fetch
them, then record what you found:

```bash
python3 .../tracker.py law-check --tracker "$T" \
    --record-checked "CT rates unchanged; employer thresholds unchanged; Apr-2028 accounts reform confirmed"
```

**Recording a check without actually fetching is the failure this is built to make visible.** It
flags when the rates reference passes its `REVIEW_BY`, when the check interval lapses (default 90
days), and when a watched change comes within a year of taking effect — currently the April 2027
CT600 boxes and the April 2028 accounts reform.

When something HAS changed, update `references/rates-2026-27.md` **and** its `REVIEW_BY`, then say
which figures moved and what they affect. A rates file that silently outlives its review date is
this family's worst failure mode: it produces confidently wrong tax figures that nobody can see are
wrong.

## 3. The engagement flow

```
ONBOARD ─► BOOKKEEP ─► RECONCILE ─► VAT QUARTER ─► YEAR-END ─► TAX ─► HANDOFF
   │           │            │            │             │         │        │
   │           │            │            │             │         │        └─ recognised software / agent
   │           │            │            │             │         └─ uk-corporation-tax (CT600, computations)
   │           │            │            │             └─ uk-statutory-accounts (FRS 105 / 102 1A, CH accounts)
   │           │            │            └─ uk-vat (9 boxes, scheme, MTD digital link)
   │           │            └─ bookkeeping-double-entry (bank rec, control + clearing accounts, TB)
   │           └─ financial-document-ingestion (PDF statements, PDF invoices, CSV exports)
   └─ this skill (§4 facts to establish, §5 deadline map)

  uk-payroll runs on its own monthly cycle throughout, feeding wages/PAYE/NI into the books.
```

## 4. ONBOARD — establish these before doing any work

Get these wrong and everything downstream is wrong. Record each as **confirmed** or **assumed**, and
treat an assumed one exactly as `business-edge` treats an assumed margin: it cannot carry a
conclusion on its own.

| Fact | Why it changes the work |
|---|---|
| **Accounting reference date (ARD)** | Sets year end, CH filing date, CT period. From the CH register, not from memory. |
| **Company number + UTR + VAT number + PAYE ref** | Every submission keys off these |
| **VAT scheme** — standard accrual · cash accounting · flat rate · annual · margin/retail | **Changes the arithmetic of every box.** Never assume standard. |
| **VAT stagger** (which quarters) | Sets four deadlines a year |
| **Accounting framework** — FRS 105 (micro) vs FRS 102 Section 1A (small) | Different statements, different disclosure, different numbers |
| **Associated companies** | **Divides** the CT marginal-relief limits — a classic small-company error |
| **Payroll**: employees, directors, auto-enrolment status, Employment Allowance eligibility | Single-director companies have specific EA restrictions |
| **Period length** | A short or long first period pro-rates CT limits and may need two CT600s |

## 5. The deadline map — the highest-value thing in this file

Deadlines are the errors that cost real money, and the pairs below are the ones people conflate.

| Obligation | Deadline | Common mistake |
|---|---|---|
| **VAT return + payment** | 1 month + 7 days after quarter end | Filing on time, paying late — still a penalty |
| **Corporation tax PAYMENT** | **9 months + 1 day** after period end | Assuming it follows the filing date |
| **CT600 FILING** | **12 months** after period end | Assuming it matches the payment date |
| **Companies House accounts** | 9 months after ARD (**21 months** from incorporation for a first period) | Missing that first-year periods differ |
| **Confirmation statement** | Annually, within 14 days of the **review period** end | Believing it is part of the accounts filing — it is separate, with its own cycle. One is due **even if nothing changed**. See `references/confirmation-statement.md` |
| **Payroll FPS** | **On or before every payday** | Filing after paying |
| **PAYE/NIC payment** | 22nd (electronic) of the following month | 19th is the *postal* deadline |
| **P60 to employees** | 31 May | — |
| **P11D / Class 1A** | 6 July / 22 July | — |

**Payment and filing are different obligations with different dates and separate penalties.** Say
which one you mean, every time.

## 6. Rates and thresholds

**Never quote a rate from memory, and never inline one into prose.** All current figures live in
one place with a review date and a primary-source URL per figure:

→ `references/rates-2026-27.md`

Two of three secondary summaries checked while building this family were materially wrong — one
reported the CT main rate as 19% (that is the *small profits* rate), another gave the employer
secondary threshold 10× too high. That is why the rule is absolute: **cite the reference, state the
tax year the figure belongs to, and refuse to apply a rate to a period it does not cover.**

## 7. Routing

| Task | Skill |
|---|---|
| Read a PDF bank statement, PDF invoice, CSV export | `financial-document-ingestion` |
| Post entries, reconcile bank, clear a suspense/clearing account, build a trial balance | `bookkeeping-double-entry` |
| **It does not balance / does not reconcile** — diagnose and correct the error | `ledger-error-diagnosis` |
| Working inside QuickBooks — feed, rules, matching, reconcile, sync gaps | `quickbooks-bookkeeping` |
| Is this a capital asset or an expense? How do I depreciate it? | `business-expenses-and-assets` |
| Splits, processor fees, supplier credits, refunds, part-payments | `bookkeeping-double-entry/references/transaction-patterns.md` |
| Who is this vendor, how do they bill, and has anything **changed**? | `business-profile` |
| Gmail/Drive/Sheets from Python (invoice capture) | `google-workspace-python` |
| How long to keep records, and backing them up properly | `financial-document-ingestion/references/retention-and-backup.md` |
| **Cash flow, working capital, salary vs dividend, what to watch monthly** | `small-business-finance` |
| VAT scheme choice, the 9 boxes, MTD digital links, correcting an error | `uk-vat` |
| CT600, tax computation, add-backs, capital allowances, losses | `uk-corporation-tax` |
| FRS 105 / FRS 102 1A statements, Companies House accounts | `uk-statutory-accounts` |
| RTI, FPS/EPS, PAYE/NI, auto-enrolment, director payroll | `uk-payroll` |
| Confirmation statement, PSC register, SIC codes, identity verification | `references/confirmation-statement.md` |
| Full vs filleted vs abridged accounts, audit exemption, size thresholds | `uk-statutory-accounts` §5–§7 |
| Pull live data from QuickBooks Online (MCP/API) | `quickbooks-api` |
| Bank / Gmail / WooCommerce / PayPal / Worldpay / Klarna feeds and their gates | `references/data-feeds.md` |
| Where received documents are stored and indexed | `financial-document-ingestion` §6 |
| Spreadsheet mechanics for any of the above | `ms-office-excel-python` |
| A CSV too large to read whole | `large-file-analysis` |

## 8. Standing rules

- **Reconcile before you conclude.** A VAT return or a set of accounts drawn from unreconciled books
  is a guess with a number on it. Bank, VAT control and wages control must agree first.
- **Every figure traces to a document.** Statement line, invoice, or payroll run. If it cannot be
  traced, it is a query, not an entry.
- **Show the arithmetic.** A tax figure without its computation cannot be checked by the user, their
  accountant, or HMRC.
- **Round only at the end**, and to the direction the relevant rule requires.
- **Flag, never quietly fix.** An unexplained difference is a finding. Forcing it into suspense to
  make the books balance hides exactly what the user needs to see.
- **Work with the records that exist.** Missing paperwork means a stated limitation and a best
  available read — not a refusal to produce anything. Say what is unresolved, what it could move,
  and what document would settle it.
- **You are not the company's accountant of record.** For anything with penalty exposure —
  a first CT600, a scheme change, a disclosure, an HMRC enquiry — recommend a qualified accountant
  reviews it before submission, and say why.

## 9. Anti-patterns

- **Answering without running the routine (§2).** Status first, overdue items led with.
- **Re-deriving what the business is** every session instead of consulting the profile.
- **Recording a law-check that was never actually fetched.**
- **Marking an obligation done without evidence.**
- **Claiming to have filed.** You cannot submit. Prepare and hand off.
- **Quoting a rate from memory** instead of the rates reference.
- **Confusing the CT payment date with the CT filing date.**
- **Assuming the standard VAT scheme** when the company is on flat rate or cash accounting.
- **Ignoring associated companies** when applying marginal relief.
- **Treating the confirmation statement as part of the accounts filing.**
- **Balancing to suspense** and calling the books reconciled.
- **Giving a confident answer from unreconciled or partial records** without labelling it as such.
