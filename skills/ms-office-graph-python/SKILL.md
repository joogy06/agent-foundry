---
name: ms-office-graph-python
description: Use when calling Microsoft Graph from Python for mail (Outlook), calendar, contacts, Teams chat / channels / meetings, SharePoint sites / lists / documents, OneDrive files, or Microsoft 365 user / group administration. Libraries — msgraph-sdk (primary, Microsoft-blessed, Kiota-generated), O365 (community wrapper, friendlier API), exchangelib (on-prem Exchange Server only — EWS retires for Exchange Online per Microsoft's announced schedule, disabled-by-default 2026-10-01 with permanent shutdown 2027-04-01; verify before relying), extract-msg / libpff-python (offline .msg / .pst parsing), botbuilder-* (full Teams bots), adaptive-cards-py (Adaptive Cards 1.5+). Covers delegated vs application permissions, RSC, throttling, paging, change-tracking, webhook validation. Part of the ms-office-python-* skill family.
family: ms-office
disambiguation: Microsoft Graph from Python — mail, calendar, Teams, SharePoint, OneDrive. Local file formats and the family overview are ms-office-python.
---

# Microsoft Graph — Python

Companion skill to `ms-office-python` (parent). For other areas see: `ms-office-excel-python`, `ms-office-word-python`, `ms-office-powerpoint-python`, `ms-office-enterprise-sso-python`, `ms-office-security-python`.

This skill **merges what would otherwise be separate Outlook, Teams, SharePoint, and OneDrive skills**. They share the same SDK (`msgraph-sdk`), the same auth (acquired via `ms-office-enterprise-sso-python`), the same throttling story (`Retry-After`, `429 Too Many Requests`), and the same threat model (delegated vs application permissions, audit logging, DLP). Splitting them by surface would produce four files that copy the same plumbing prose. Keeping them together makes the cloud-vs-on-prem decision tree and the cross-cutting concerns the centrepiece (§2).

<HARD-RULE>
EWS retirement: per Microsoft's currently announced schedule (as of 2026-05), Exchange Online disabled-by-default 2026-10-01 with permanent shutdown 2027-04-01. Verify on Microsoft Learn before locking dates into production migration plans. On-prem Exchange Server retains EWS. New Python code targeting Exchange Online MUST use `msgraph-sdk`. Existing `exchangelib` code against Exchange Online MUST be migrated; `exchangelib` against on-prem Exchange Server is correct and remains supported.
</HARD-RULE>

<HARD-RULE>
Application permissions (`Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`, `Files.ReadWrite.All`, `Sites.ReadWrite.All` and similar `.All` scopes) MUST be scoped via Application Access Policy (`New-ApplicationAccessPolicy` / `Set-ApplicationAccessPolicy`) to specific mailboxes / sites / groups. Tenant-wide application permissions without a policy gate are a HALT-class finding — one compromised service principal reads or sends mail for every user in the tenant. Application Access Policy is the difference between "service can email these 3 monitored mailboxes" and "service can email everyone." Default to scoped; require explicit user approval to widen scope.
</HARD-RULE>

<HARD-RULE>
Office 365 Connectors API (the legacy webhook surface that `pymsteams` targets) was retired by Microsoft 2024-2025. New webhook integrations into Teams MUST use Power Automate Workflows OR Graph `chatMessage` POST. `pymsteams` is **LEGACY** for new code — use it only for short-term maintenance of existing Connector integrations that haven't been migrated yet. The migration path is Workflows for the simple webhook-like cases, Graph for richer interactions.
</HARD-RULE>

<HARD-RULE>
NEVER log raw bearer tokens, refresh tokens, webhook validation URLs, or `Authorization: Bearer ...` headers. `msgraph-sdk` debug-level HTTP logging WILL emit the Authorization header by default; wrap the underlying logger with a redactor before turning debug on. Webhook URLs minted by Graph for change-notification subscriptions are bearer-like — anyone with the URL can POST events; treat them as secrets in storage, logs, and error reports.
</HARD-RULE>

---

## Overview

Microsoft Graph is the single API surface for Microsoft 365 user data and tenant administration. `msgraph-sdk` is the Microsoft-blessed Python client; `O365` is the community wrapper with a friendlier sync API; `exchangelib` is the on-prem Exchange Server path; `extract-msg` and `libpff-python` cover the offline / forensic / archival paths. For Teams there's `botbuilder-core` and `adaptive-cards-py` for full bots and rich cards.

The hardest question this skill answers is `#2 below` — cloud or on-prem, delegated or application, which library is right. Get that wrong, the rest produces working code that targets the wrong endpoint or holds the wrong permission.

For authentication itself, see `ms-office-enterprise-sso-python`. This skill takes for granted that you can get a token; it focuses on what to do with it.

## 2. First-class decision tree: which Graph endpoint, which auth flow

The opening section — answer this BEFORE choosing a library.

| Question | Answer | Path |
|---|---|---|
| Tenant: Exchange Online + delegated user (e.g., Outlook desktop user) | Yes | Graph + MSAL broker (Win) / browser (other) / device-code (last resort). See `ms-office-enterprise-sso-python` §6. |
| Tenant: Exchange Online + app-only daemon (e.g., monitoring service) | Yes | Graph + client credentials (cert preferred) + **Application Access Policy** (HARD-RULE 2) |
| Tenant: Exchange on-prem 2016 / 2019 / SE | Yes | `exchangelib` (EWS) — Graph CANNOT reach on-prem mailboxes without hybrid configuration |
| Tenant: Hybrid Exchange (some mailboxes on-prem, some O365) | Yes | Dispatch per mailbox — Graph for O365 mailboxes, `exchangelib` for on-prem mailboxes |
| Surface: Teams chat / channel post from a service | Yes | Graph `chatMessage` POST OR Power Automate Workflows. NOT `pymsteams` (HARD-RULE 3) |
| Surface: Teams bot (interactive, multi-turn) | Yes | `botbuilder-core` + Bot Framework registration (separate from Graph permissions) |
| Surface: SharePoint sites / lists / drive | Yes | Graph drive / sites endpoints. SharePoint REST is legacy for most cases. |
| Surface: OneDrive files | Yes | Graph drive endpoints (the same as SharePoint drive — they share the model) |
| Use case: Parse an offline `.pst` archive | Yes | `libpff-python` (offline; no auth needed). `libratom` is the higher-level alternative. |
| Use case: Parse an offline `.msg` file (Outlook saved email) | Yes | `extract-msg` (offline; no auth needed) |
| Use case: Send mail from a Linux server through O365 SMTP | Yes | Graph `sendMail` PREFERRED. If SMTP, OAuth XOAUTH2 ONLY — basic auth disabled. |

The cloud-vs-on-prem split is the load-bearing decision. Mixing the two in one codebase requires explicit dispatch logic and parallel code paths.

## 3. Library Selection

| Library | Purpose | Status (2026-05) | OS support | When to use | When NOT to use |
|---|---|---|---|---|---|
| `msgraph-sdk` | Microsoft Graph SDK | Active (preferred) | All | All new code talking to Graph | When the friendlier sync API of O365 outweighs the freshness cost (small scripts) |
| `msgraph-core` | HTTP / middleware layer beneath msgraph-sdk | Active | All | Low-level direct HTTP into Graph with msgraph middleware (retry / paging / batching) | Most use cases — use msgraph-sdk instead |
| `O365` | Community wrapper (sync, friendly API) | Active | All | Small scripts, prototypes, education | Production multi-tenant services (use msgraph-sdk; O365 lags on new endpoints) |
| `exchangelib` | EWS client for Exchange Server | Active (LEGACY for Exchange Online) | All | On-prem Exchange Server | Exchange Online (HARD-RULE 1) |
| `extract-msg` | Parse offline `.msg` (Outlook saved email) | Active | All | Forensic / archival mail parsing | Live mailbox access (use Graph) |
| `libpff-python` | Parse `.pst` archives | Active | All (requires libpff-dev) | Offline `.pst` (Outlook archive) parsing | Live mailbox access (use Graph) |
| `libratom` | Higher-level PST workflow built on libpff | Active | All | Bulk PST processing | Single-file extraction (use libpff-python directly) |
| `pymsteams` | (legacy O365 Connector webhook poster) | **LEGACY / RETIRING** | All | NOT for new code | All new code — use Workflows OR Graph `chatMessage` (HARD-RULE 3) |
| `botbuilder-core` | Microsoft Bot Framework SDK | Active | All | Full Teams bots (multi-turn dialogs, state, channels) | Single-shot notifications (use Graph `chatMessage`) |
| `adaptive-cards-py` | Build Adaptive Cards 1.5+ | Active | All | Rich interactive cards in Teams / Outlook / Webex | Plain text messages |
| `defusedxml` | XXE defence | Active | All | Any path that parses XML you don't fully control (some Graph responses include XML — most are JSON) | (always include in security-conscious code) |

## 4. Install Commands

### RHEL 9 / AlmaLinux 9 / Rocky 9

```bash
sudo dnf install -y python3.12 python3-pip python3-devel gcc-c++ libxml2-devel libxslt-devel
python3 -m pip install --upgrade pip
python3 -m pip install msgraph-sdk azure-identity msal pyjwt cryptography defusedxml
python3 -m pip install extract-msg
# Optional, on-prem Exchange:
python3 -m pip install exchangelib
# Optional, .pst parsing (system dep):
sudo dnf install -y libpff-devel  # may need EPEL
python3 -m pip install libpff-python libratom
# Optional, Teams bots:
python3 -m pip install botbuilder-core botbuilder-schema adaptive-cards-py
# Optional, community wrapper:
python3 -m pip install O365
```

### Debian 12 / Ubuntu 24.04

```bash
sudo apt update
sudo apt install -y python3.12 python3-pip python3-dev build-essential libxml2-dev libxslt1-dev
python3 -m pip install --upgrade pip
python3 -m pip install msgraph-sdk azure-identity msal pyjwt cryptography defusedxml extract-msg
sudo apt install -y libpff-dev    # Debian 12 stable; Ubuntu may need build from source
python3 -m pip install libpff-python libratom exchangelib botbuilder-core adaptive-cards-py O365
```

### Windows 11

```powershell
winget install --id Python.Python.3.12 -e --silent
python -m pip install --upgrade pip
python -m pip install msgraph-sdk azure-identity msal "msal[broker]" pyjwt cryptography `
    defusedxml extract-msg exchangelib botbuilder-core adaptive-cards-py O365
# libpff is fiddly on Windows; prebuilt wheels exist for some versions
python -m pip install libpff-python
```

## 5. Capability Matrix (one row per Graph resource type × library)

| Resource | msgraph-sdk | O365 | exchangelib | extract-msg / libpff |
|---|---|---|---|---|
| Mail (Exchange Online) | yes | yes (delegated friendlier) | NO (EWS retiring) | offline only |
| Mail (Exchange on-prem) | NO (no Graph reach) | NO | yes | offline only |
| Calendar | yes | yes | yes (on-prem) | no |
| Contacts | yes | yes | yes (on-prem) | no |
| Teams chats / channels | yes | partial | no | no |
| Teams meetings | yes | partial | no | no |
| SharePoint sites / lists | yes (drive + lists endpoints) | partial | no | no |
| OneDrive files | yes (drive endpoints) | yes | no | no |
| Users / groups admin | yes | partial | no | no |
| Webhooks (change notifications) | yes | partial | no | no |
| Offline .msg parsing | no | no | no | yes (extract-msg) |
| Offline .pst parsing | no | no | no | yes (libpff-python) |

## 6. Authentication

Link-and-defer to `ms-office-enterprise-sso-python`. Quick summary:

- **Delegated** (user-context) — broker on Win, browser on Linux/Mac, device code as last resort. Token has `scp` (scopes) and reflects the user's permissions intersected with consented scopes.
- **Application-only** (daemon) — client credentials with certificate. Token has `roles` (application permissions) and reflects what the app was granted at admin consent.

The msgraph-sdk constructor accepts a credential from `azure-identity` directly:

```python
from azure.identity import DefaultAzureCredential   # or specific credential
from msgraph import GraphServiceClient
client = GraphServiceClient(credentials=DefaultAzureCredential(), scopes=["https://graph.microsoft.com/.default"])
```

For explicit MSAL token control:

```python
import msal
from msgraph import GraphServiceClient
from azure.core.credentials import AccessToken
class StaticTokenCredential:
    def __init__(self, token): self._token = token
    def get_token(self, *scopes, **_): return AccessToken(self._token, ...)
# Acquire token via msal as per ms-office-enterprise-sso-python §6.1, then:
client = GraphServiceClient(credentials=StaticTokenCredential(token), scopes=[...])
```

## 7. Delegated vs application permissions

Two fundamentally different consent models:

| Aspect | Delegated | Application |
|---|---|---|
| Context | User signed in | No user; service principal acts on its own behalf |
| Token claim | `scp` (space-separated scopes) | `roles` (array of granted roles) |
| Consent | User consents (or admin on behalf) | Admin must consent |
| Permission shape | `Mail.Read` (this user's mail) | `Mail.Read.All` (every user's mail in tenant) |
| Mitigation for over-broad app perms | n/a (user's scope is the scope) | Application Access Policy (HARD-RULE 2) |

**Application Access Policy** pattern (PowerShell — run by tenant admin, not in your Python code):

```powershell
New-ApplicationAccessPolicy -AppId <app-client-id> `
    -PolicyScopeGroupId security-group@contoso.com `
    -AccessRight RestrictAccess `
    -Description "Limit app to monitored mailboxes"
```

Without that policy, your `Mail.Send` application permission lets the service send mail as ANY user in the tenant. With it, only the specified group.

Document the Application Access Policy in code comments or README — it's enforced server-side but invisible from the Python side, so reviewers can't see it.

## 8. msgraph-sdk patterns

### Paging

Graph responses for collection endpoints (users, messages, files) are paged with `@odata.nextLink`. The SDK exposes async iteration:

```python
# CONFIDENCE: minimal viable pattern — pair with the Throttling pattern below and §15 Security Hardening; full references/ guide planned (v1.1).
async for message in client.me.messages.get_async_iter(top=50):
    process(message)
```

### Throttling (Retry-After)

Graph returns `429 Too Many Requests` with a `Retry-After` header. The SDK's default middleware retries; if you bypass middleware (raw HTTP), you handle it yourself:

```python
import time
resp = ...  # your HTTP call
if resp.status_code == 429:
    time.sleep(int(resp.headers.get("Retry-After", "30")))
    # retry
```

DO NOT exponential-backoff blindly past 60 seconds — investigate the cause (likely batch-size or fan-out misconfigured).

### Batching

Up to 20 requests per batch:

```python
from msgraph_core.requests import BatchRequestContent, BatchRequestItem
# build BatchRequestItem instances, post to client.batch
```

Reduces round-trip count significantly for fan-out reads / writes.

### Change tracking (delta links)

For incremental sync (mail, files, users), use delta queries:

```python
delta = await client.me.messages.delta.get_async()
# delta.value is the changeset; delta.odata_delta_link is the token to resume next time
```

Persist the delta link between runs — re-running with the same link gets only what changed.

### Webhooks (change notifications)

Subscribe to a resource; Graph POSTs change events to your validated endpoint. Validation flow:

1. POST `/subscriptions` with a `notificationUrl`.
2. Graph immediately POSTs `validationToken` to that URL — your endpoint MUST echo it back as plain text within 10 seconds.
3. Periodically renew the subscription (Graph subscriptions expire — most resources max 3 days).

The webhook validation token + the subscription notification URL are both bearer-like — protect them (HARD-RULE 4).

## 9. EWS-to-Graph migration map

Capability table for migrating `exchangelib` code to `msgraph-sdk`:

| EWS capability | Graph equivalent | Notes |
|---|---|---|
| Get / send / delete messages | `me.messages.get` / `me.send_mail.post` / `me.messages[id].delete` | Direct |
| Calendar items | `me.events` | Direct |
| Contacts | `me.contacts` | Direct |
| Folder operations | `me.mail_folders` | Direct (with hierarchy support) |
| **Mailbox rules** | **No direct equivalent** | Limited via `messageRule` API; some features missing |
| **Public folders** | **No equivalent in Graph** | Stays on EWS for on-prem; migrate workflows away |
| **Online archive (Exchange Online Archiving)** | **No direct equivalent** | Limited via `archiveFolder` API |
| **Impersonation** (`X-AnchorMailbox`, EWS impersonation) | Application permissions + AAP | Different model — application-context, scoped via AAP |
| **In-place hold / litigation hold** | `complianceCase` API (E5 feature) | Different API surface |
| **Public folders calendar** | No equivalent | Migrate to shared mailboxes / Group mailboxes |
| Attachments | `me.messages[id].attachments` | Direct (with size limits — 4 MB inline, 150 MB for large attachments) |
| Streaming notifications | `subscriptions` (webhook) | Different model — webhook POSTs vs streaming connection |

Code that depends on the "no equivalent" rows must EITHER keep an `exchangelib` path against on-prem (if applicable) OR change the workflow.

## 10. Offline mail parsing (.msg, .pst)

For forensic / archival / migration work where talking to a live tenant is not possible or appropriate:

```python
# CONFIDENCE: minimal viable pattern — see the Security note below (size-guard, XXE/zip-bomb) and §15 Security Hardening; full references/ guide planned (v1.1).
import extract_msg
msg = extract_msg.Message("saved_email.msg")
print(msg.sender, msg.to, msg.subject, msg.body[:100])
```

```python
import pypff
pst = pypff.file()
pst.open("archive.pst")
for folder in pst.root_folder.sub_folders:
    for item in folder.sub_messages:
        print(item.subject, item.delivery_time)
```

`libratom` wraps `libpff-python` for bulk-PST workflows (eDiscovery use case).

**Security note**: PST files are commonly several GB; size-guard the input. `.msg` files are zip-like; XXE / zip-bomb defences apply if the source is untrusted.

## 11. Teams: incoming webhooks via Workflows, bots, Adaptive Cards, RSC

### Modern webhook replacement (Workflows)

Power Automate Workflows replaced O365 Connectors. The Workflow creates an HTTPS endpoint; you POST JSON to it; the Workflow posts the formatted message into the Teams channel.

```python
import requests, json
requests.post(WORKFLOW_URL, json={"text": "Build #4567 passed.", "title": "CI"})
```

The Workflow URL is itself a secret — treat as a bearer token. (HARD-RULE 4 redaction guidance applies.)

### Graph `chatMessage` POST

```python
# CONFIDENCE: minimal viable pattern — permission/consent notes below and §15 Security Hardening; full references/ guide planned (v1.1).
from msgraph import GraphServiceClient
from msgraph.generated.models.chat_message import ChatMessage
from msgraph.generated.models.item_body import ItemBody
client = GraphServiceClient(credentials=..., scopes=[...])
message = ChatMessage(body=ItemBody(content="Build #4567 passed."))
await client.teams.by_team_id(TEAM_ID).channels.by_channel_id(CHANNEL_ID).messages.post_async(message)
```

Requires `ChannelMessage.Send` (delegated) OR `ChannelMessage.Send.Group` (application + RSC) consent.

### Bot Framework (interactive bots)

`botbuilder-core` for multi-turn dialogs, state management, channel adapters. Significantly more setup than a webhook. Use when you need real conversation, not just one-shot notifications.

### Adaptive Cards

`adaptive-cards-py` builds rich JSON payloads. Render in Teams, Outlook, Webex, and other Adaptive-Card-aware surfaces.

### RSC (Resource-Specific Consent)

For Teams app permissions, RSC lets a Teams app request permissions on a per-team basis (rather than tenant-wide). Smaller blast radius. Documented in the app manifest; consumed via Graph at runtime. See Microsoft Learn.

## 12. SharePoint / OneDrive

SharePoint and OneDrive share the same Graph drive model. Sites, lists, libraries, drives, drive items.

```python
# CONFIDENCE: minimal viable pattern — production hardening notes in §15 Security Hardening below; full references/ guide planned (v1.1).
# Get the default drive of a SharePoint site by hostname / site path
site = await client.sites.by_site_id("contoso.sharepoint.com:/sites/marketing").get_async()
drive = await client.sites.by_site_id(site.id).drive.get_async()
# List root children
items = await client.drives.by_drive_id(drive.id).items.by_drive_item_id("root").children.get_async()
for item in items.value:
    print(item.name, item.size, item.last_modified_date_time)
```

OneDrive is the same model with `/me/drive` or `/users/{user}/drive`.

For SharePoint list operations (custom-schema lists), the `lists` endpoint exposes columns, items, content types. For document libraries, the drive endpoint is usually a cleaner fit.

## 13. SMTP fallback (with OAuth XOAUTH2 only — basic auth disabled)

If `Mail.Send` via Graph isn't appropriate (legacy SMTP-only integrations), use OAuth XOAUTH2 — Microsoft disabled basic auth (username + password) for SMTP/IMAP/POP in Exchange Online in 2022.

```python
# CONFIDENCE: minimal viable pattern — token-scope notes below and §15 Security Hardening; full references/ guide planned (v1.1).
import smtplib, base64
auth_string = f"user={USER_EMAIL}\x01auth=Bearer {ACCESS_TOKEN}\x01\x01"
smtp = smtplib.SMTP_SSL("smtp.office365.com", 465)
smtp.ehlo()
smtp.docmd("AUTH XOAUTH2", base64.b64encode(auth_string.encode()).decode())
# send mail via smtp.sendmail(...)
```

The `ACCESS_TOKEN` must come from an MSAL flow that consented to `SMTP.Send` (delegated) or `Mail.Send` (application) — see `ms-office-enterprise-sso-python`.

Prefer Graph `sendMail` for new code. SMTP is for compatibility with existing integrations.

## 14. National-cloud notes

Sovereign clouds use different Graph endpoints — see `ms-office-enterprise-sso-python` §12 for the authority URL matrix. msgraph-sdk accepts the alternate endpoint via the `scopes` and underlying credential:

```python
client = GraphServiceClient(
    credentials=AzureSovereignCredential(...),
    scopes=["https://graph.microsoft.us/.default"],   # GCC-H example
)
```

Some endpoints / features ship later (or not at all) in sovereign clouds. Test per resource on Microsoft Learn before relying.

## Canonical Pattern (modified C3)

**Send an email via Graph as a daemon (service-to-service), with Application Access Policy enforcing per-mailbox scope** — the canonical M365-from-Python pattern.

```python
# CONFIDENCE: minimal viable pattern — production hardening notes in §15 Security Hardening below; auth detail in ms-office-enterprise-sso-python §6.4; full references/ guide planned (v1.1).
import asyncio
from azure.identity import CertificateCredential
from msgraph import GraphServiceClient
from msgraph.generated.models.message import Message
from msgraph.generated.models.item_body import ItemBody
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.users.item.send_mail.send_mail_post_request_body import SendMailPostRequestBody

# Credential from a cert in a vault — NOT a literal in source
cred = CertificateCredential(tenant_id=TENANT_ID, client_id=CLIENT_ID, certificate_path=CERT_PATH_FROM_VAULT)
client = GraphServiceClient(credentials=cred, scopes=["https://graph.microsoft.com/.default"])

async def send(sender_upn: str, to_upn: str, subject: str, body_text: str):
    msg = Message(
        subject=subject,
        body=ItemBody(content_type="Text", content=body_text),
        to_recipients=[Recipient(email_address=EmailAddress(address=to_upn))],
    )
    req = SendMailPostRequestBody(message=msg, save_to_sent_items=True)
    await client.users.by_user_id(sender_upn).send_mail.post_async(req)

asyncio.run(send("monitor@contoso.com", "ops@contoso.com", "Build alert", "Build #4567 failed."))
```

This pattern enforces three things: certificate-based credential (not a hardcoded `client_secret`), explicit sender UPN (so Application Access Policy can scope), and `save_to_sent_items=True` so the action is auditable in the sender mailbox.

## 15. Security Hardening (consolidated, ~18 items)

See `ms-office-security-python` for the family checklist. Area-specific items:

- HARD-RULEs 1-4 above are the load-bearing items: no EWS for new Exchange Online code, AAP on application permissions, no `pymsteams` for new Teams integrations, never log tokens / webhook URLs.
- Application Access Policy is documented in code comments — it's invisible at the API layer.
- Use delegated permissions where the user identity matters; use application permissions only for true daemon scenarios and ALWAYS gate with AAP.
- Webhook subscription endpoints MUST validate `clientState` on every notification — Graph passes back whatever opaque string you set at subscription time; rejection signals replay attack or misconfiguration.
- Subscription renewal windows are short (most resources max 3 days). Failing to renew causes data gaps; implement an idempotent re-subscribe path with monitoring.
- Throttling responses (`429`) carry sensitive information (your app's request volume); don't expose them in user-facing error messages.
- The `extract-msg` / `libpff-python` paths bypass tenant DLP — document the legitimate need for offline parsing in code or design docs.
- `exchangelib` against on-prem Exchange supports impersonation; use it only with an explicit service-account-with-impersonation-rights configuration, not via shared credentials.
- For SharePoint document downloads, validate the `eTag` / `cTag` on subsequent reads — a file replaced underneath you between read calls is a tampering vector.
- Adaptive Cards rendered server-side (e.g., in your Workflow / bot logic) accept user-controlled content — sanitize against script-tag-in-text and link injection (the cards model resists XSS more than HTML but the principle stands).
- Audit-log every privileged Graph operation (Send, Delete, Move, permission changes) with principal `oid`, target user / site / file, and outcome.
- For `libpff-python` parsing of untrusted `.pst`, run in a sandboxed subprocess — historical CVEs in the C library exist.
- `exchangelib` auto-discovery (`autodiscover_url`) can be exploited to redirect to attacker-controlled servers if DNS or HTTPS aren't trusted; pin the Exchange URL explicitly in production.
- Validate the `tid` claim on tokens received for delegated app-Graph calls — multi-tenant apps must reject foreign-tenant tokens (cross-references SSO HARD-RULE 4).
- Pin `msgraph-sdk`, `azure-identity`, `msal`, `cryptography`, `lxml`, `defusedxml` versions explicitly. CVE-watch via `dep-currency-check`.
- For Teams bot webhook endpoints, validate the inbound JWT against the Bot Framework's JWKS — Bot Framework signs the request with its own keys.
- `O365` community wrapper stores token cache in a default file path; review `tokens.txt` placement before deploying — easy oversight.
- The Power Automate Workflow URL is itself a bearer secret — store in a vault, not in source / config / env vars.

## Selection Cheatsheet

- "Send email from a daemon" → msgraph-sdk + `users[upn].send_mail.post` + Application Access Policy
- "Send email as a user (delegated)" → msgraph-sdk + delegated token + `me.send_mail.post`
- "Read shared mailbox" → application permissions + AAP scoping to that mailbox
- "Post a Teams message from CI" → Power Automate Workflow (single line `requests.post(WORKFLOW_URL, json=...)`)
- "Build a Teams bot with dialog state" → `botbuilder-core` + Bot Framework registration
- "Upload a file to SharePoint" → msgraph-sdk + drive endpoints
- "Sync a OneDrive folder" → msgraph-sdk + delta queries
- "Migrate an exchangelib codebase to Graph" → see §9 migration map
- "Parse `.pst` archive offline" → `libpff-python` (or `libratom` for bulk)
- "Parse `.msg` file offline" → `extract-msg`
- "SMTP from a Linux service to O365" → SMTP XOAUTH2 (basic auth disabled) or — better — Graph `sendMail`

## Gotchas

- `pymsteams` will continue to "work" against unmaintained / not-yet-cleaned Connector endpoints for a while. It is still LEGACY for new code (HARD-RULE 3) — do not let the working-today behaviour mislead.
- `msgraph-sdk` is async-first; sync callers must `asyncio.run(...)` or use a sync wrapper. The community `O365` library is sync but lags behind on new Graph features.
- `exchangelib` against Exchange Online will continue to work until Microsoft's announced shutdown date — but new code must NOT depend on it (HARD-RULE 1).
- Graph `Retry-After` can be in seconds OR HTTP-date format; handle both.
- Webhook validation has a 10-second timeout — slow handlers cause Graph to retry the validation up to 4 times then mark the subscription failed.
- Application permissions consent grants are TENANT-WIDE unless gated by AAP. The consent dialog shows "this app will be able to read mail in your organization" without listing scoped policies — invisible in the consent UX.
- Graph throttling thresholds vary per resource; mail / Teams / SharePoint each have separate buckets and separate limits (documented but easy to miss).
- `libpff-python` requires `libpff-dev` system package; on Ubuntu it may need building from source if the Debian-derived package is too old.
- Webhook URL minted by Graph for change notifications looks like a regular HTTPS URL but contains a session-bound secret — treat as a secret in storage, logs, and error reports.
- `extract-msg` follows embedded attachments — for forensic mail parsing of untrusted input, this is a recursive attack surface; cap attachment depth.

## Update Triggers (per Codex M-1 — alf will scan these)

- Major version bump of: `msgraph-sdk`, `azure-identity`, `msal`, `exchangelib`, `libpff-python`, `O365`, `botbuilder-core`, `adaptive-cards-py`, `extract-msg`.
- Microsoft Graph version bump (current is `v1.0`; the `beta` endpoint can change underfoot).
- EWS retirement date changes — current schedule per Microsoft (as of 2026-05) — verify before locking dates.
- Office 365 Connectors API enforcement / shutdown completion.
- CVE published against `lxml`, `cryptography`, `libpff`.
- Annual review on: 2027-05-22.

## See Also

| Need | Skill |
|---|---|
| Acquire the token in the first place | `ms-office-enterprise-sso-python` |
| Generate / parse the Office file you're sending or storing | `ms-office-excel-python`, `ms-office-word-python`, `ms-office-powerpoint-python` |
| Hardening / validator / checklist | `ms-office-security-python` |
| Server-side Python OAuth/OIDC (non-Microsoft IdPs) | `python-auth-security` |
| Confluence / Jira (Atlassian, not Microsoft) | `confluence-rest-api`, `jira-rest-api` |
| Dependency CVE scanning | `dep-currency-check` |
