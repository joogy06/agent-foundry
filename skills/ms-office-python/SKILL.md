---
name: ms-office-python
description: Use when working with Microsoft Office or Microsoft 365 from Python — reading/writing Excel (.xlsx), Word (.docx), PowerPoint (.pptx); calling Microsoft Graph for mail/calendar/Teams/SharePoint/OneDrive; authenticating to Entra ID via MSAL/WAM broker, SAML, or Kerberos; or hardening any of the above. Parent skill for the ms-office-python-* family. Routes to ms-office-excel-python, ms-office-word-python, ms-office-powerpoint-python, ms-office-graph-python, ms-office-enterprise-sso-python, ms-office-security-python.
family: ms-office
disambiguation: The FAMILY entry point — routes to the per-format and per-API siblings. Microsoft Graph calls specifically are ms-office-graph-python.
---

# Microsoft Office + Microsoft 365 — Python Family (parent)

Parent skill for the `ms-office-python-*` family. Covers Python's Office and Microsoft 365 surface end-to-end: file formats (Excel / Word / PowerPoint), Microsoft Graph APIs (Outlook / Teams / SharePoint / OneDrive), enterprise SSO (MSAL / WAM broker / SAML / Kerberos), and a consolidated security checklist with a runnable validator.

For specialized areas, see companion skills: `ms-office-excel-python`, `ms-office-word-python`, `ms-office-powerpoint-python`, `ms-office-graph-python`, `ms-office-enterprise-sso-python`, `ms-office-security-python`.

This family is **complementary**, not a replacement, for:

- `python-auth-security` — server-side OAuth/OIDC/SAML/JWT patterns for Python web apps (generic).
- `windows-sso` — PowerShell-based AD FS / Entra ID infrastructure administration (no Python).

The family covers what those two don't: **Python client code consuming enterprise SSO from desktop / CLI / server contexts** and **Python automation against Microsoft Office artifacts and Graph endpoints**.

<HARD-RULE>
Cloud-first preference for user-data operations. Microsoft Graph inherits Conditional Access, audit logging, DLP, eDiscovery, and tenant retention policies that file-based code (openpyxl / python-docx / extract-msg) bypasses entirely. For mail / calendar / chat / documents owned by an M365 tenant, the Graph path is the compliance-correct path. File-based code is correct only for offline / archival / migration / forensic scenarios where you have an explicit reason to operate outside the tenant boundary.
</HARD-RULE>

<HARD-RULE>
Credentials live in vaults, Managed Identity, certificates, or OS credential stores — NEVER in source code, NEVER in config files committed to git, NEVER in environment variables containing plaintext secrets. See `ms-office-enterprise-sso-python` HARD-RULEs for the per-context concrete rules (`client_secret` on Azure compute, ROPC, device code on managed Windows, hardcoded bearer tokens). This rule deliberately defers to the SSO skill to avoid duplicate maintenance — a single source of truth for credential rules.
</HARD-RULE>

<HARD-RULE>
EWS retirement: per Microsoft's currently announced schedule (as of 2026-05), Exchange Online disabled-by-default 2026-10-01 with permanent shutdown 2027-04-01. Verify on Microsoft Learn before locking dates into production migration plans. On-prem Exchange Server retains EWS. New Python code targeting Exchange Online MUST use `msgraph-sdk`. `exchangelib` remains the correct choice for Exchange Server on-prem environments and for forensic / archival work against historical EWS data.
</HARD-RULE>

---

## 1. Overview

The family answers four overlapping questions a Python developer faces in any Microsoft-tenant environment:

1. **File-format code** — read, write, transform Excel / Word / PowerPoint files without needing Office installed.
2. **Graph code** — call Microsoft 365 APIs for mail, calendar, Teams, SharePoint, OneDrive, users, groups.
3. **Auth code** — get a token, with or without a UI, on or off a managed device, with or without a broker.
4. **Hardening** — make sure none of the above leaks secrets, bypasses Conditional Access, or pulls in deprecated libraries.

Each child skill covers one area. The parent covers the cross-cutting concerns: preflight, OS bootstrap, library philosophy, glossary, anti-patterns.

## 2. Preflight checklist (BEFORE choosing libraries)

Answer these five questions before reading the child skills. The answers determine which child applies and which libraries are appropriate.

| Question | Why it matters |
|---|---|
| **Target tenant**: Exchange Online (M365) / Exchange Server on-prem / both? | EWS path lives in `exchangelib`; Graph path lives in `msgraph-sdk`. Mixed environments need both with explicit dispatching. |
| **National cloud**: Commercial / GCC / GCC-H / DoD / China (21Vianet) / Germany / Other? | Different authority URLs, different Graph endpoints, different consent / app-registration story. See §12 of `ms-office-enterprise-sso-python`. |
| **Auth context**: Domain-joined Windows / Linux desktop / headless server / container in Azure / container elsewhere / CI? | Determines which of the four auth branches (Win broker / Linux broker / headless daemon / Kerberos) you need. See `ms-office-enterprise-sso-python` §2. |
| **Office installed locally**: yes / no? | Determines whether `xlwings`, `docx2pdf`, and pywin32 COM automation are viable. None of those work on headless Linux. |
| **License tier**: E3 / E5 / F1-F3 / EDU? | Affects Graph feature availability (E5 unlocks advanced eDiscovery, Defender, etc.; F-line restricts kiosk access). Don't assume tenant-wide Graph access without confirming the license. |

**National-cloud preflight banner (D7).** If the answer to "national cloud" is anything other than Commercial:

- Authority URL changes (`login.microsoftonline.us`, `login.microsoftonline.de`, `login.partner.microsoftonline.cn`).
- Graph endpoint changes (`graph.microsoft.us`, `graph.microsoft.de`, `microsoftgraph.chinacloudapi.cn`).
- Some Graph endpoints and library features ship later (or never) in sovereign clouds — verify per resource.
- Service Principal app registration ALSO happens in the sovereign portal (different URL).

The child skills assume Commercial unless explicitly noted. Sovereign clouds are flagged at the points where they materially affect code.

## 3. When to use which child (decision tree)

```
Start
  |
  +-- Working with .xlsx / .xls / .xlsb files? -------------------> ms-office-excel-python
  |
  +-- Working with .docx / .doc / .docm files? ------------------> ms-office-word-python
  |
  +-- Working with .pptx / .ppt / .potx files? ------------------> ms-office-powerpoint-python
  |
  +-- Calling Microsoft Graph (mail, calendar, Teams,
  |   SharePoint, OneDrive, users, groups, admin)? -------------> ms-office-graph-python
  |
  +-- Authenticating to Entra ID / AD FS from a Python client? -> ms-office-enterprise-sso-python
  |
  +-- Hardening any of the above (checklist / validator) -------> ms-office-security-python
  |
  +-- Server-side web-app OAuth/OIDC/SAML/JWT (generic) --------> python-auth-security
  |
  +-- PowerShell AD FS / Entra ID infrastructure admin --------> windows-sso
```

A typical "silent SSO from a domain-joined Windows laptop into Outlook via Graph" task pulls in three children: `ms-office-enterprise-sso-python` (acquire the token), `ms-office-graph-python` (call the endpoint), `ms-office-security-python` (verify the result).

## 4. Family-wide library philosophy

Two opinionated defaults the family enforces unless you have a reason to deviate:

**4.1 Cloud-first over file-first for tenant-owned data.**

If the data lives in an M365 tenant — mail, calendar, OneDrive files, SharePoint documents, Teams messages — read it via Graph, not via files. Reasons:

- Graph inherits tenant policy (Conditional Access, DLP, audit log).
- File-based code (download .msg via Outlook export, parse with extract-msg) leaves no audit trail on the tenant side.
- Forensic / archival / migration use cases are the exception, not the rule — and they are first-class in `ms-office-graph-python` (§10 offline mail parsing).

**4.2 Microsoft-blessed library over community wrapper when the gap is small.**

`msgraph-sdk` (Microsoft, Kiota-generated) is preferred over `O365` (community wrapper) for new code, even though `O365` has a friendlier sync API. Reasons:

- Auto-generated from the OData metadata — keeps up with new endpoints automatically.
- Async-first — matches modern Python.
- Microsoft support story (issues / docs) is direct.

`O365` remains a legitimate choice when the friendlier API outweighs the freshness cost (small scripts, prototypes, education).

`msal` (Microsoft) is preferred over `authlib` / `requests-oauthlib` for Microsoft IdPs. `authlib` is the right call when the IdP is not Microsoft (Okta, Auth0, Keycloak — covered by `python-auth-security`).

## 5. Common OS prerequisites (per-OS bootstrap)

System dependencies the family needs across all children. Per-skill install commands are in each child's SKILL.md.

### RHEL 9 / AlmaLinux 9 / Rocky 9

```bash
sudo dnf install -y python3.12 python3-pip python3-devel \
  gcc-c++ krb5-devel libxml2-devel libxslt-devel libffi-devel openssl-devel \
  libsecret-devel cyrus-sasl-gssapi
# Optional, per-skill:
# - libpff-devel (for ms-office-graph-python .pst parsing — may need EPEL)
# - libreoffice (for ms-office-word-python / ms-office-powerpoint-python rendering)
# - libxmlsec1-devel (for ms-office-enterprise-sso-python SAML)
```

### Debian 12 / Ubuntu 24.04

```bash
sudo apt update
sudo apt install -y python3.12 python3-pip python3-venv python3-dev \
  build-essential libkrb5-dev libxml2-dev libxslt1-dev libffi-dev libssl-dev \
  libsecret-1-dev libsasl2-modules-gssapi-mit
# Optional, per-skill:
# - libpff-dev (Debian 12 only; Ubuntu may need to build from source)
# - libreoffice
# - libxmlsec1-dev
# - microsoft-identity-broker (for Linux broker — Intune-managed, install from MS repo)
```

### Windows 11

```powershell
# Python 3.12 from python.org or winget
winget install --id Python.Python.3.12 -e --silent
# Optional, per-skill:
#   winget install --id LibreOffice.LibreOffice -e --silent
#   winget install --id Microsoft.VCRedist.2015+.x64 -e --silent  # required by some COM extensions
# pymsalruntime ships its own DLLs; verify with:
#   python -c "import pymsalruntime; print(pymsalruntime.__file__)"
```

### macOS 14+ (Sonoma / Sequoia / Tahoe)

```bash
xcode-select --install                      # REQUIRED to build appscript (xlwings on macOS)
brew install python@3.12
# Optional, per-skill:
#   brew install --cask libreoffice          # headless conversion — the portable route
#   brew install pandoc                      # pypandoc backend
```

**On macOS, driving installed Office goes through Apple Events, not COM** — `xlwings` and
`docx2pdf` use the AppleScript bridge (`appscript`), and the first call raises a TCC consent dialog
that **cannot be answered headlessly**. That makes macOS live-automation unavailable on CI runners
and `launchd` jobs for the same practical reason COM is unavailable on Linux.

**Read `references/macos-automation.md` before writing any macOS automation path** — it covers the
Apple Events grant, Office's App Sandbox containers, the Apple-silicon Homebrew prefix, and the
cross-platform routes (Graph, Office Scripts, LibreOffice headless) that avoid the problem entirely.

**Office installation is NOT a family-wide prerequisite.** Only `xlwings`, `docx2pdf`, and explicit COM-automation patterns require local Office. The defaults (`openpyxl`, `python-docx`, `python-pptx`, `msgraph-sdk`) do not. Each child skill flags Office-dependent libraries in its Library Selection table.

## 6. Common cross-cutting libraries

Libraries every child references. Single source of truth for status + version recommendations is the master family library status table in `references/library-status.md`.

| Library | Used by | Status | Notes |
|---|---|---|---|
| `msal` | SSO, Graph | Active (preferred for M365 auth) | Direct Microsoft auth library |
| `msal-extensions` | SSO, Security | Active | Encrypted token cache (DPAPI / Keychain / libsecret) |
| `msal[broker]` / `pymsalruntime` | SSO | Active | WAM broker bindings (Windows); required for CA compliance |
| `azure-identity` | SSO, Graph | Active | High-level credential abstractions; primarily for Azure SDK |
| `azure-identity-broker` | SSO | Active (separate package!) | `InteractiveBrowserBrokerCredential` for Windows AND Linux broker |
| `msgraph-sdk` | Graph | Active (preferred) | Microsoft-blessed; Kiota-generated; async-first |
| `cryptography` | All | Active | Foundation; CVE-watch |
| `defusedxml` | Excel, Word, PowerPoint, Security | Active | XXE defence for stdlib XML parsing |
| `keyring` | SSO, Security | Active | Cross-platform OS-keyring access |

The full ~40-row table lives in each child's Library Selection section. The status column reflects 2026-05 ecosystem state.

## 7. Glossary (renames + deprecations developers stumble over)

| Old name | New name | First use |
|---|---|---|
| Azure AD | Entra ID | 2023 — Azure AD renamed to Microsoft Entra ID; Python code still imports as `azure.identity` |
| ADAL (`adal` library) | MSAL (`msal` library) | ADAL deprecated and end-of-life since June 2023 |
| Office 365 Connectors API | Power Automate Workflows / Graph `chatMessage` | Connectors retired 2024-2025; legacy `pymsteams` targets the old API |
| EWS (Exchange Web Services) | Microsoft Graph | EWS retiring for Exchange Online per Microsoft's announced schedule (disabled-by-default 2026-10-01, permanent shutdown 2027-04-01); verify on Microsoft Learn before locking dates |
| `xlrd` for .xlsx | `openpyxl` | `xlrd >= 2.0` only reads `.xls`, not `.xlsx` |
| `requests-kerberos` | `requests-gssapi` / `requests-negotiate-sspi` / `pyspnego` | Legacy as of 2026-05 |
| Azure DevOps Server credential helpers | `azure-identity` Managed Identity | The new path on Azure-hosted CI |

## 8. In-scope / out-of-scope

**In scope:**

- Excel (.xlsx, .xls, .xlsb), Word (.docx, .doc, .docm), PowerPoint (.pptx, .ppt, .potx).
- Microsoft Graph: mail / calendar / contacts / Teams chat & channels & meetings / SharePoint / OneDrive / users / groups.
- Auth: MSAL (Win + Linux broker, daemon, device code, certificate), SAML 2.0 SPs, JWT validation, Kerberos / SPNEGO, hardware keys (FIDO2 / smartcard).
- Hardening: per-skill HARD-RULEs + the consolidated checklist + the runnable Python validator.

**Out of scope (v1):**

- **Microsoft Access / Visio / Project / OneNote** — single-sentence namecheck in `See Also` only; full coverage deferred.
- **Microsoft Copilot APIs (Copilot Studio / M365 Copilot)** — surface still evolving as of 2026-05; deferred to v1.1.
- **SharePoint deep collaboration workflows** (lists, Power Platform integration) — preflight + recipe in `ms-office-graph-python`, but workflow / list / Power Automate coverage deferred to v1.1.
- **Test corpus + golden-output regression** — useful but heavy lift; v1 ships library recommendations verified by approach agents only.
- **Air-gapped enterprise scenarios** (private PyPI, wheelhouse, offline validator) — Gotchas-level coverage in `ms-office-security-python`; full air-gap pattern deferred.

## 9. Selection cheatsheet

| Need | First-line skill | Library |
|---|---|---|
| "Read this .xlsx file" | `ms-office-excel-python` | `openpyxl` |
| "Write a Word doc and PDF" | `ms-office-word-python` | `python-docx` + `docx2pdf` (Windows/macOS) OR `pypandoc` |
| "Send an email through M365 from a service" | `ms-office-graph-python` | `msgraph-sdk` + client-credentials |
| "Get a token silently on a domain-joined laptop" | `ms-office-enterprise-sso-python` | `msal[broker]` + `PublicClientApplication(enable_broker_on_windows=True)` |
| "Authenticate a Linux service to Graph in CI" | `ms-office-enterprise-sso-python` | `azure-identity` + Workload Identity Federation |
| "Parse an offline .pst archive" | `ms-office-graph-python` | `libpff-python` |
| "Check this codebase for hardcoded secrets / disabled JWT verification / EWS imports" | `ms-office-security-python` | `python3 -m ms_office_security_check .` |

## 10. Anti-patterns

| Don't | Why |
|---|---|
| Use `exchangelib` to talk to Exchange Online in 2026+ | EWS retiring for Exchange Online (per Microsoft's announced schedule, verify before relying); use `msgraph-sdk` |
| Use `adal` for any new code | EOL since June 2023; use `msal` |
| Use `pymsteams` for new Teams integrations | Targets the retired O365 Connectors API; use Workflows OR Graph `chatMessage` POST |
| Use `requests-kerberos` for new Kerberos code | Legacy; use `requests-gssapi` (Linux/macOS) + `requests-negotiate-sspi` (Windows) + `pyspnego` |
| Mix `openpyxl` with `xlrd` for .xlsx | `xlrd >= 2.0` cannot read `.xlsx`; pick `openpyxl` |
| Skip the preflight checklist (§2) | Library choice depends on tenant, cloud, auth context, Office presence, license — guessing wastes a sprint |
| Treat MSAL and azure-identity as interchangeable | MSAL is for direct M365 / Graph auth; azure-identity is primarily for Azure SDK and abstracts over many credential sources; see SSO skill §4 for the boundary |
| Hardcode a Graph access token in source | A001/A006-grade finding; `ms-office-security-python` flags it; use msal + msal-extensions cache |
| Use device-code flow on a managed Windows laptop when a broker is available | Bypasses WAM → token lacks device-compliance claim → Conditional Access blocks or silently downgrades |
| Assume Graph endpoints / features are identical across sovereign clouds | They aren't — preflight per §2 question 2 |

## 11. Related skills

| Skill | When to use it instead of / alongside this family |
|---|---|
| `python-auth-security` | Server-side Python web-app OAuth/OIDC/SAML/JWT against non-Microsoft IdPs (Okta, Auth0, Keycloak, Cognito). This family link-and-defers to it for generic JWT validation patterns. |
| `windows-sso` | PowerShell AD FS / Entra ID **infrastructure** administration. No Python code. Use when the question is "how do I configure the IdP / WAP / Conditional Access policy", not "how does my Python client talk to it." |
| `python-flask-developer` / `python-data-engineer` | When the Python code involves Flask / SQLAlchemy more than it involves Office or Graph. The Office family covers the Office surface; the Flask/data skills cover the surrounding app. |
| `dep-currency-check` | Run BEFORE writing code — surfaces stale versions / CVEs in the libraries this family recommends. `ms-office-security-python` validator does NOT duplicate dep-currency-check; they are layered. |
| `linux-centrify` | When the on-prem authentication path is Centrify-managed (not native Kerberos). The SSO skill covers Kerberos / pyspnego; Centrify-specific configuration lives in `linux-centrify`. |

## Update Triggers (per Codex M-1 — alf will scan these)

The following events should force a review of this skill and its children:

- **Microsoft deprecation announcements** affecting: EWS, Office 365 Connectors API, ADAL, basic auth for SMTP / IMAP / POP, any msgraph-sdk major version, any `azure-identity` major version, broker DLL distribution model.
- **Major version bumps** of: `msal` (currently 1.x), `msgraph-sdk` (currently 1.x), `azure-identity` (currently 1.x), `cryptography` (CVE-watch), `defusedxml`.
- **National-cloud changes** — new sovereign endpoints, authority URL changes, GCC-H / DoD onboarding model changes.
- **Annual review anniversary**: 2027-05-22 (one year after creation). Sweep the family for `pymsteams` removal eligibility, EWS post-shutdown rule updates, library status table refresh.

## See Also

| Resource | Where |
|---|---|
| Microsoft Graph reference | https://learn.microsoft.com/graph/api/overview |
| MSAL Python docs | https://learn.microsoft.com/entra/msal/python/ |
| Azure Identity for Python | https://learn.microsoft.com/python/api/overview/azure/identity-readme |
| EWS retirement timeline (verify before locking dates) | https://learn.microsoft.com/exchange/clients-and-mobile-in-exchange-online/ews-retirement |
| openpyxl docs | https://openpyxl.readthedocs.io |
| python-docx docs | https://python-docx.readthedocs.io |
| python-pptx docs | https://python-pptx.readthedocs.io |
| Microsoft Authentication Library architecture | https://github.com/AzureAD/microsoft-authentication-library-for-python |
| Validator package layout precedent | `~/.claude/skills/dep-currency-check/` |
