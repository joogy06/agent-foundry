# ms-office-python family — master library status table

Single source of truth for library status across the family. Each child skill cites this and adds its own per-area columns (OS support, capability matrix).

Status values:

- **Active** — maintained, suitable for new code.
- **Maintenance mode** — minor releases only, no major roadmap; stable but plan for divergence if formats evolve.
- **Legacy** — superseded by a modern equivalent; use only for short-term maintenance of existing integrations.
- **EOL** — end-of-life; do not use for new code. Migrate existing code as a priority.

## File-format libraries

| Library | Status (2026-05) | Notes |
|---|---|---|
| `openpyxl` | Active | Industry standard for .xlsx; multiple XXE CVEs historically — pair with `defusedxml`; recommend `read_only=True` for untrusted input |
| `xlsxwriter` | Active | Write-only .xlsx, fast |
| `pandas` | Active | DataFrame I/O, uses openpyxl/xlsxwriter backends |
| `xlrd` | Active (LEGACY for .xlsx) | Cannot read .xlsx since v2.0 — `.xls` only |
| `xlwings` | Active | Windows/macOS only; requires Excel installed |
| `msoffcrypto-tool` | Active | Decrypt password-protected workbooks |
| `pycel` / `formulas` | Active | Formula evaluation in Python; useful when calculated values must be derived without Excel |
| `python-docx` | Active | Maintained; not full-fidelity Word (no complex fields / track-changes layout) |
| `docx2txt` | Active | Fast plaintext extraction |
| `mammoth` | Active | .docx → HTML/Markdown |
| `docx2pdf` | Active | Windows/macOS only — COM wrapper around Word |
| `pypandoc` | Active | Wraps pandoc system binary |
| `python-pptx` | **Maintenance mode** | Stable, minor releases, no major roadmap — flag in Gotchas |
| `LibreOffice` (headless, CLI) | Active | External binary; used for rendering / conversion when Office is unavailable |

## Microsoft Graph / Microsoft 365 libraries

| Library | Status (2026-05) | Notes |
|---|---|---|
| `msgraph-sdk` | Active (preferred) | Microsoft-blessed; Kiota-generated; async-first |
| `msgraph-core` | Active (low-level layer, not "old version") | HTTP/middleware layer beneath msgraph-sdk |
| `O365` | Active (community) | Friendlier sync API; lags behind msgraph-sdk on new features |
| `exchangelib` | Active (LEGACY for Exchange Online) | EWS retiring for Exchange Online (per Microsoft's announced schedule); remains current for Exchange Server on-prem |
| `extract-msg` | Active | Offline .msg parsing |
| `libpff-python` | Active | .pst parsing; requires libpff-dev system package |
| `libratom` | Active | Higher-level PST workflow built on libpff |
| `pymsteams` | **LEGACY / RETIRING** | Targets retired O365 Connectors API. Migration path: Workflows OR Graph `chatMessage`. |
| `botbuilder-core` | Active | Microsoft Bot Framework SDK |
| `adaptive-cards-py` | Active | Adaptive Cards 1.5+ |

## Auth libraries

| Library | Status (2026-05) | Notes |
|---|---|---|
| `msal` | Active (preferred for M365 auth) | Microsoft Authentication Library — direct Graph/M365 auth |
| `msal[broker]` / `pymsalruntime` | Active | WAM broker bindings; required for CA compliance on Windows |
| `msal-extensions` | Active | Encrypted token cache (DPAPI/Keychain/libsecret) |
| `azure-identity` | Active | High-level credential abstractions; primarily for Azure SDK; some Graph use |
| `azure-identity-broker` | Active (separate package!) | `InteractiveBrowserBrokerCredential`; Linux broker GA (verify per-package release notes before shipping). Distinct from `azure-identity`. |
| `authlib` | Active | Generic OIDC/OAuth2 — use for non-Microsoft IdPs |
| `requests-oauthlib` | Active | Simpler than authlib for basic OAuth2 |
| `pyspnego` | Active (preferred) | Modern unified SPNEGO/NTLM/Kerberos |
| `requests-gssapi` | Active | Kerberos for requests on Linux/Mac |
| `requests-negotiate-sspi` | Active | Windows-specific Negotiate via SSPI |
| `requests-kerberos` | **LEGACY** | Superseded by requests-gssapi + pyspnego |
| `pysaml2` | Active | Powerful SAML; easy to misconfigure XML signature verification |
| `python3-saml` | Active | OneLogin's SAML toolkit |
| `pyjwt[crypto]` | Active | JWT signing/validation |
| `python-jose[cryptography]` | Active | Alternative to pyjwt; supports JWE |
| `cryptography` | Active | Foundation; CVE-watch |
| `fido2` | Active | WebAuthn/FIDO2 client |
| `pyscard` | Active | PC/SC smart cards (CAC/PIV) |
| `python-pkcs11` | Active | PKCS#11 token access |
| `keyring` | Active | Cross-platform OS-keyring access |
| `adal` | **EOL** | Predecessor to msal, deprecated June 2023 — do not use for new code |

## Windows-specific bindings

| Library | Status (2026-05) | Notes |
|---|---|---|
| `pywin32` | Active | Windows COM bindings |
| `comtypes` | Active | Alternative COM lib |

## XML / supply-chain helpers

| Library | Status (2026-05) | Notes |
|---|---|---|
| `defusedxml` | Active | XXE defence for stdlib XML parsing |
| `lxml` | Active | Used by openpyxl / python-docx internally — CVE-watch |
| `pip-audit` (CLI) | Active | Run alongside the validator for CVE detection — separate concern |
| `bandit` (CLI) | Active | Generic Python SAST — complements the validator |
| `gitleaks` (CLI) | Active | Generic secret scanner — complements the validator |
