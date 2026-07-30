---
name: quickbooks-api
description: Use when connecting to QuickBooks Online programmatically — Intuit's first-party MCP server, the Accounting API, OAuth 2.0 setup on the Intuit Developer Portal, sandbox versus production apps, refresh-token lifecycle, read-only versus write configuration, and pulling reports such as trial balance, profit and loss, balance sheet and aged debtors into an accounting workflow. Covers credential handling and the safety posture for an AI agent holding write access to live books.
disambiguation: The QuickBooks Online CONNECTION — MCP server, API, OAuth, credentials, safety posture. What to DO with the data once retrieved is the accounting family — bookkeeping-double-entry for reconciliation, uk-vat, uk-corporation-tax, uk-statutory-accounts. Reading exported files instead of the API is financial-document-ingestion.
---

# QuickBooks Online — MCP and API

## 1. The answer to "do we need a third party?" — no

**Intuit publishes and maintains a first-party MCP server.** It lives in Intuit's own GitHub
organisation (`intuit/quickbooks-online-mcp-server`) and is the supported bridge between MCP clients
and the QuickBooks Online REST API. A registered developer account is all that is required.

| | |
|---|---|
| **Tools** | **144** — 29 entity types with full CRUD, plus 11 financial reports |
| **Reports** | Balance Sheet, P&L, Cash Flow, **Trial Balance**, General Ledger, Aged Receivables/Payables, Customer/Vendor summaries |
| **Auth** | OAuth 2.0 authorization-code flow via the Intuit Developer Portal |
| **Transport** | **stdio only** — runs as a local subprocess |
| **Install** | Clone + `npm install` + `npm run build` — **not** distributed via npx or Docker |
| **Environments** | sandbox and production |

Third-party connectors exist and are **not needed** for direct access. Prefer the first-party server:
fewer parties holding credentials to live books, and it tracks the API it is built against.

## 2. Can you actually get tokens for your own company? — yes, with a gate

**This is developer/partner territory, not an end-user feature.** A QBO subscriber cannot generate
API tokens from inside QuickBooks; access comes from a registered app on the Intuit Developer Portal.
Having a developer registration is the prerequisite, and it is step one of three.

| Step | Status | Gate |
|---|---|---|
| 1. Developer account | **Prerequisite** | Free registration |
| 2. Create app → **sandbox** keys | **Immediate** | None — works today |
| 3. **Production** keys | **Gated** | App assessment / security questionnaire, reviewed by Intuit |

**You do NOT need to publish to the QuickBooks App Store** to connect your own company. Publishing is
for distributing to other people's companies. Own-company use needs production *keys*, not a listing.

**But production keys are not automatic.** Per Intuit's developer help, you complete an app
assessment questionnaire and production credentials are released once their security team approves.
A live QBO company can only be connected using **production** keys — sandbox keys will not reach it.

Intuit replaced the legacy developer programme with the **Intuit App Partner Program** (tiers
Builder / Silver / Gold / Platinum). **Check which tier a registration sits in**, because the
programme structure changed and an older registration may need action.

### What to check on the portal — in this order

1. **Does the account have an app created?** Registration alone does not create one.
2. **Are sandbox keys present?** If yes, you can build and test **today**.
3. **Has the app assessment been submitted?** This is the gate to production, and it is easy to have
   registered without ever starting it.
4. **What is the production-key status** — not started / submitted / approved?
5. **Which App Partner Program tier** does the account sit in?

> **This skill cannot check that status for you** — it needs an authenticated portal session. Reading
> the answer off the Developer Portal is a two-minute human task, and guessing at it wastes far more
> time than checking.

### How long does the assessment take? — separate the two timelines

These get conflated constantly, and the conflation is what makes people give up.

| | Time |
|---|---|
| **Completing the questionnaire** | ~30–60 minutes once you have the answers to hand |
| **Self-assessment approval status** | shown on the portal **(almost) immediately** |
| **App Store listing / publication** | **6 weeks to 6+ months** — security review, QA environment, demo to the review team |

**The 6-weeks-to-6-months figure is for PUBLISHING to the App Store. You do not need that.** For
own-company production keys the path is the questionnaire, and the status appears essentially at once.

Two honest caveats: the questionnaire asks real security questions (data handling, storage,
access control, incident response) — have those answers ready rather than improvising. And there are
recurring developer-forum reports of the production keys not appearing even after an approved
questionnaire, so budget for a support ticket rather than assuming a clean run.

### Third-party access — possible, and wrong for this

Unified accounting API providers hold the Intuit relationship and expose their own interface, so you
can reach QuickBooks without your own production keys. **Codat** (deepest financial-data coverage —
bank feeds, reconciliation), **Merge**, **Apideck**, **Rutter** (e-commerce lean) and **Unified.to**
all cover QBO alongside Xero, Sage, NetSuite and FreshBooks.

**For one company reading its own books, do not do this.** Indicative published pricing sits around
**$599–$750 per month** — Merge ~$650/mo for 10 linked accounts, Apideck ~$599/mo, Unified.to ~$750/mo
(verify current figures; they move). That is **£6,000–9,000 a year to avoid a free 30-minute
questionnaire.**

The pricing is not unreasonable — it is aimed at a different buyer. These platforms exist for SaaS
vendors connecting *hundreds of their customers'* accounting systems, where one integration replaces
many. A single business accessing its own books is not that buyer, and the per-account economics
invert completely.

There is also a security argument, and for accounting data it is the stronger one: a third party
means **another organisation holding standing credentials to your books**, with its own breach
surface and its own data-retention terms. The first-party route keeps that circle at two parties.

**Use an aggregator only if** you later need several accounting platforms behind one interface, or
you are building something multi-tenant for other companies. Neither applies to running your own
accounts.

### Nothing is blocked while you wait

**Build against sandbox now.** The tool surface, OAuth flow, entity shapes and report structures are
identical; only the data and the keys differ. When production keys land, swap
`QUICKBOOKS_ENVIRONMENT`, `CLIENT_ID`, `CLIENT_SECRET` and re-run the handshake — no rework.

Do the sandbox work first regardless. Pointing an untested integration at live books is the wrong
order even when you *can*.

## 3. Setup

### Sandbox first — always

```bash
git clone https://github.com/intuit/quickbooks-online-mcp-server.git
cd quickbooks-online-mcp-server && npm install && npm run build
npm run auth          # browser handshake
```

1. Register an app on the **Intuit Developer Portal** and select the **QuickBooks Online Accounting**
   scope.
2. Add redirect URI `http://localhost:8000/callback`.
3. Set `QUICKBOOKS_ENVIRONMENT=sandbox` and run the handshake.

### Production differs in one awkward way

**Production rejects `localhost` redirect URIs.** You need a public HTTPS callback — an ngrok tunnel
or a deployed handler. Plan for it; it surprises people at the point they are ready to go live.

The redirect URI must match **exactly** — protocol, host, port and path.

### Credentials

| Variable | |
|---|---|
| `QUICKBOOKS_CLIENT_ID` | from the Developer Portal app |
| `QUICKBOOKS_CLIENT_SECRET` | ” |
| `QUICKBOOKS_REFRESH_TOKEN` | from the one-time handshake |
| `QUICKBOOKS_REALM_ID` | the QBO company id |
| `QUICKBOOKS_ENVIRONMENT` | `sandbox` \| `production` |

**These belong in `~/.secrets/<project>.env` (0600), never in the repo** — see
`secret-scanning/references/storage-standard.md`. A client secret and refresh token together are
standing access to the company's books.

Two operational notes that cause real outages:
- **Refresh tokens auto-rotate** and the server persists the new one. Do not pin an old value.
- **There is a ~100-day refresh window.** An integration left idle past it needs a fresh browser
  handshake — which nobody remembers at year end. Put it in the tracker.
- The `.env` must sit in the **compiled module directory**, not the shell CWD, when launched by a
  desktop client.

## 4. Safety posture — default to read-only

This is an AI agent holding credentials to a company's live accounting records. Writes are real,
immediate, and land in the books that become a tax return.

**Set the write-suppression flags unless a write is specifically intended:**

```bash
QUICKBOOKS_DISABLE_WRITE=true
QUICKBOOKS_DISABLE_UPDATE=true
QUICKBOOKS_DISABLE_DELETE=true
```

Read tools (`get_*`, `search_*`) remain available regardless, which is the right default: **almost
everything the accounting family needs is read.** Pull the trial balance, reconcile, compute, report
— none of that requires write access.

House rules for this connection:

- **Read-only by default.** Enabling writes is a deliberate, stated act, not a convenience.
- **Never delete.** There is no accounting reason for an agent to delete a transaction; a correction
  is a new entry, and the audit trail is the point.
- **Sandbox for anything new.** Test the shape of a call against sandbox before pointing it at real
  books.
- **Say which company you are connected to.** `REALM_ID` identifies it. Acting on the wrong company
  is the failure mode that a multi-company user will hit eventually.
- **Never echo credentials** into a transcript, a log, or a commit.

## 5. Using it with the accounting family

The MCP server is a **source**, not a replacement for the accounting skills. It gives you the data;
the family tells you whether it is right and what to do with it.

| Want | Pull | Then |
|---|---|---|
| Reconcile | Trial Balance, General Ledger | `bookkeeping-double-entry` — control-account proofs |
| VAT quarter | P&L, transaction detail by tax code | `uk-vat` — scheme, 9 boxes, control proof |
| Year end | Balance Sheet, P&L, Trial Balance | `uk-statutory-accounts` — FRS framework, formats |
| Corporation tax | Trial Balance + fixed-asset detail | `uk-corporation-tax` — add-backs, allowances |
| Debt chasing | Aged Receivables | operational |

**A figure from QuickBooks is not automatically correct.** It is correctly *recorded* only if the
books were reconciled and coded properly. The bank reconciliation and control-account proofs in
`bookkeeping-double-entry` still apply — pulling a trial balance from an API does not prove the
underlying books agree with the bank.

## 6. UK specifics

QuickBooks Online UK handles **MTD VAT submission inside its own product**, as recognised software.
That does not change this family's position: **these skills still do not file.** They prepare, prove
and reconcile; the submission happens in QBO (or another recognised product), by a human who has
reviewed it.

Check current VAT scheme handling in the connected company rather than assuming standard accrual —
QBO holds the scheme setting, and `uk-vat` §1 explains why that single fact changes every box.

## 7. Practical limits

- **stdio only** — a local subprocess, so it runs where the agent runs. No hosted endpoint.
- **Rate limits apply** per realm; check the current figures in Intuit's developer documentation
  rather than assuming, and batch report pulls instead of looping single-entity fetches.
- **Sandbox data is not your data.** Shapes match; balances do not.
- **API and minor versions move.** Pin what you depend on and re-verify after upgrading the server.

## 8. Anti-patterns

- **Assuming a third party is required.** Intuit's first-party MCP server exists.
- **Assuming production access is automatic** because a developer account exists — the assessment is a separate, gated step.
- **Waiting on production approval before building.** Sandbox is identical in shape; build now.
- **Expecting an end user to generate tokens from inside QuickBooks.** They cannot; it is a developer-portal app.
- **Confusing the App Store publication timeline (6 weeks to 6+ months) with the questionnaire**, which returns a status almost immediately. That confusion is what makes people abandon the first-party route.
- **Paying an aggregator ~$600-750/month to read one company's own books** — the wrong buyer for that product, and an extra party holding credentials.
- **Running with writes enabled by default.**
- **Putting credentials in the repo** instead of `~/.secrets/`.
- **Testing against production** because the sandbox handshake was inconvenient.
- **Trusting a pulled figure as reconciled** — the API reports what was recorded, not what is right.
- **Letting the 100-day refresh window lapse** and discovering it at a deadline.
- **Not stating which realm/company is connected.**

## Sources

- [Intuit QuickBooks Online MCP Server](https://github.com/intuit/quickbooks-online-mcp-server)
- [Server README — setup, tools, environment variables](https://github.com/intuit/quickbooks-online-mcp-server/blob/main/README.md)
- [Intuit Developer — production keys help](https://help.developer.intuit.com/s/topic/0TOG00000004r1SOAQ/production-keys)
- [App assessment and compliance FAQ](https://help.developer.intuit.com/s/article/New-app-assessment-process-FAQ)
- [Security requirements for apps](https://developer.intuit.com/app/developer/qbo/docs/go-live/publish-app/security-requirements)

**Verification note.** The MCP server facts in §1 and §3 were read from Intuit's repository README
directly. The production-key gating in §2 comes from Intuit's developer help pages and the App
Partner Program announcement, **not** from a primary developer-docs fetch (that page returned
truncated). Treat §2's process as accurate in shape and **confirm the current detail on the portal**
before planning around a date. **Aggregator pricing is indicative from vendor pages and moves — re-check
before quoting it to anyone.**
