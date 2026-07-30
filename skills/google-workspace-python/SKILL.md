---
name: google-workspace-python
description: Use when calling Google APIs from Python — Gmail for reading mail and downloading attachments, Drive and Sheets for files and data, and Calendar. Covers Google Cloud project setup, OAuth 2.0 versus service accounts with domain-wide delegation, scope selection and least privilege, the consent-screen and verification path, token storage and refresh, batching and pagination, and the quota model. The Google-side counterpart to the ms-office-python family.
disambiguation: GOOGLE APIs from Python — Gmail, Drive, Sheets, Calendar, and their auth model. Microsoft Graph, Outlook, SharePoint and Entra ID are the ms-office-python family; scraping a mailbox is not this — use the API.
---

# Google Workspace APIs from Python

The Google counterpart to `ms-office-python`. Written for the case that actually recurs: **pulling
invoices out of a mailbox** without anyone re-keying them.

## 1. Setup

1. **Google Cloud project** → enable the specific APIs you need (Gmail, Drive, Sheets, Calendar).
   Enabling is per-API; a project with Gmail on does not have Drive on.
2. **Choose the auth model** — §2. This is the decision that is expensive to change later.
3. **Configure the OAuth consent screen** — internal or external, and the scopes.
4. **Create credentials** — OAuth client ID (user-delegated) or a service account.

```bash
pip install google-api-python-client google-auth google-auth-oauthlib
```

## 2. OAuth vs service account — pick deliberately

| | **OAuth user credentials** | **Service account** |
|---|---|---|
| Acts as | A specific person, who consents | The application itself |
| Best for | One operator's own mailbox | Server-to-server, automated |
| Gmail access | Direct, after consent | **Only via domain-wide delegation** (Workspace, admin-granted) |
| Refresh | Refresh token, long-lived | Self-signed JWT, no user step |
| Gotcha | Tokens can be revoked or expire; needs a browser once | **A plain service account cannot read a personal Gmail mailbox** |

**The trap worth stating plainly:** people reach for a service account because it sounds like the
"proper" automated route, then discover it cannot touch Gmail without Workspace domain-wide
delegation. **For one operator reading their own mailbox, OAuth user credentials are the correct
answer**, not a compromise.

**Testing/internal consent screens** are fine for a single operator. External + sensitive scopes
triggers Google's verification review — plan for it or stay internal.

## 3. Scopes — least privilege, and it is enforced socially

| Scope | Grants |
|---|---|
| `gmail.readonly` | Read messages and download attachments |
| `gmail.modify` | Read plus label/mark — **no delete** |
| `gmail.send` | Send only |
| `drive.readonly` / `drive.file` | Read all / only files the app created |
| `spreadsheets.readonly` | Read Sheets |

**Request the narrowest scope that does the job.** For invoice capture that is `gmail.readonly` and
nothing else. Broader scopes make consent scarier, push you toward verification, and widen the blast
radius if a token leaks.

**`drive.file` over `drive` wherever possible** — it limits the app to files it created.

## 4. Gmail — the invoice-capture pattern

The reliable shape, and it is not "search the whole mailbox with clever heuristics":

1. **Filter at source.** A Gmail filter applies a label (e.g. `invoices/`) on arrival.
2. **Query the label**, not the world: `q="label:invoices has:attachment"`.
3. **Paginate** — `nextPageToken`; never assume one page.
4. **Fetch attachments** by `attachmentId`, decode base64url.
5. **Record the message id** so a re-run is idempotent.

**Why the label beats a smart search:** a heuristic search silently changes its result set as mail
volume grows, so coverage drifts without anyone noticing. A label is deterministic and a human
maintains it.

**Store the original attachment and hash it** — the PDF is the evidence, the email body is not
(`financial-document-ingestion` §6). Record the message id, received date and sender alongside it.

**`internalDate` is the reliable timestamp**; header dates are sender-supplied and can be wrong.

## 5. Tokens

- Store the refresh token in `~/.secrets/<project>.env` (0600), **never in the repo** —
  `secret-scanning/references/storage-standard.md`.
- The client library will refresh access tokens automatically; **persist the refreshed credential**
  or you will re-consent every run.
- A refresh token can be revoked by the user, by a password change, or by long disuse. **Handle
  re-auth as a normal path, not an exception** — for an unattended job, that means alerting rather
  than silently stopping.
- **Put the re-auth risk in the tracker.** An integration that quietly stops is discovered at a
  deadline (`accounting-uk-ltd` §2).

## 6. Quotas and batching

Google quotas are **per-project and per-user, measured in units** — different calls cost different
amounts, so "requests per second" is the wrong mental model.

- **Batch** related requests rather than looping single calls.
- **Exponential backoff with jitter** on 429 and 5xx. The client libraries support it; use it.
- **Fetch metadata first**, full bodies only for what you actually need — `format=metadata` is far
  cheaper than `format=full` across a large mailbox.

## 7. Anti-patterns

- **Reaching for a service account for personal Gmail.** It cannot, without Workspace delegation.
- **Requesting `gmail.modify` when `gmail.readonly` would do.**
- **Heuristic mailbox search** instead of a label maintained by a human.
- **Not paginating** and quietly processing only the first page.
- **Trusting the header date** over `internalDate`.
- **Committing `credentials.json` or `token.json`.** Both are secrets.
- **Treating re-auth as an error path** for an unattended job — it is expected, and it needs an alert.
- **Scraping the mailbox** through IMAP hacks when the API exists.
