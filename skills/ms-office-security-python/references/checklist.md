# ms-office-python family — Consolidated security checklist (advisory only)

This is the human-readable checklist for code review. It cross-references per-skill HARD-RULEs and the validator's machine-readable rule manifest (`ms_office_security_check/rules.yaml`).

**Advisory only — not a security gate.** Findings inform reviewer judgement. Generic security findings belong to `bandit` / `semgrep` / `gitleaks` / `pip-audit` / `dep-currency-check`.

## How to use

1. Run the validator: `python3 -m ms_office_security_check . --format md`.
2. Walk this checklist alongside the report.
3. For each finding, either fix or document a justified suppression (`# msosec: ignore <id>`).
4. Re-run `bandit -r .`, `pip-audit`, `gitleaks detect` for the items deferred to those tools.

## 1. Authentication

- [ ] **No `adal` imports** — EOL since June 2023. Validator rule MSOSEC-A001. Cross-ref: `ms-office-enterprise-sso-python` glossary.
- [ ] **Broker enabled on Windows client code** — `PublicClientApplication(enable_broker_on_windows=True)`. Validator rules MSOSEC-A002, MSOSEC-A003. Cross-ref: `ms-office-enterprise-sso-python` §2 decision matrix + §6.1 recipe + HARD-RULE 1.
- [ ] **No ROPC usage** — `acquire_token_by_username_password` is incompatible with MFA / CA / passwordless. Cross-ref: `ms-office-enterprise-sso-python` HARD-RULE 2.
- [ ] **No hardcoded `client_secret`** — Managed Identity on Azure compute; certificate-from-vault elsewhere. Validator rule MSOSEC-A004. Cross-ref: `ms-office-enterprise-sso-python` HARD-RULE 3 + §6.5/6.6 recipes.
- [ ] **JWT signature verification enabled** — never `verify=False` or `options={"verify_signature": False}`. Validator rule MSOSEC-A009. Cross-ref: `ms-office-enterprise-sso-python` HARD-RULE 4.
- [ ] **JWT algorithm pinned** — explicit `algorithms=["RS256"]`. Validator rule MSOSEC-A010. Cross-ref: same.
- [ ] **JWT issuer + `tid` validated** — multi-tenant apps reject foreign tenants. Validator rule MSOSEC-A013. Cross-ref: same + §9 JWT validation pattern.
- [ ] **Token cache encrypted** — `msal-extensions` `PersistedTokenCache` with OS-native backend (DPAPI / Keychain / libsecret). Cross-ref: `ms-office-enterprise-sso-python` §7.
- [ ] **No raw token logging** — wrap msal/azure-identity debug loggers with a redactor. Cross-ref: `ms-office-graph-python` HARD-RULE 4.

## 2. Authorization (Graph scopes)

- [ ] **Project scope allowlist present** — `[tool.ms-office-security.scopes]` in `pyproject.toml` OR `ms-office-security.yaml`. Without it, validator MSOSEC-C001 fires on every scope literal.
- [ ] **`.default` only with `ConfidentialClientApplication`** — not in delegated public-client flows. Validator rule MSOSEC-C002.
- [ ] **Broad `.All` / `.ReadWrite.All` scopes documented** — entry in scope allowlist + reviewer-confirmed Application Access Policy server-side. Validator rule MSOSEC-C003. Cross-ref: `ms-office-graph-python` HARD-RULE 2.
- [ ] **Application Access Policy verified server-side** — for any Graph application permission (Mail.Send, Mail.ReadWrite, Calendars.ReadWrite, Files/Sites .ReadWrite.All). PowerShell `Get-ApplicationAccessPolicy` confirms scope.
- [ ] **RSC for Teams app permissions where applicable** — per-team rather than tenant-wide consent.

## 3. Transport

- [ ] **TLS verification on Graph calls** — `verify=` not `False` on requests/httpx to `graph.microsoft.*` URLs. Validator rule MSOSEC-B001.
- [ ] **No `urllib3.disable_warnings()` near Graph code** — signals deliberate TLS bypass nearby (covered by `bandit` B501 too).
- [ ] **OAuth XOAUTH2 for SMTP** — Microsoft disabled SMTP basic auth on Exchange Online 2022. Cross-ref: `ms-office-graph-python` §13.

## 4. Deprecated APIs

- [ ] **No `exchangelib` in code paths targeting Exchange Online** — Validator rule MSOSEC-E001. Comment `# on-prem Exchange only` suppresses the finding on legitimate on-prem paths. Cross-ref: `ms-office-graph-python` HARD-RULE 1 + parent HARD-RULE 3.
- [ ] **No `pymsteams` for new code** — Validator rule MSOSEC-E005. Cross-ref: `ms-office-graph-python` HARD-RULE 3.
- [ ] **No `requests-kerberos`** — superseded. Validator rule MSOSEC-E004. Cross-ref: `ms-office-enterprise-sso-python` Library Selection.
- [ ] **No `pywin32` COM automation for server contexts** — Validator rule MSOSEC-E003 flags Outlook COM specifically; same principle applies to Excel/Word/PowerPoint server-side COM. Cross-ref: per-skill Library Selection tables.

## 5. Office documents

- [ ] **XXE defence in OOXML parsing** — `defusedxml` paired with `openpyxl` / `python-docx` / `python-pptx`. Validator rule MSOSEC-OFFICE002. Cross-ref: per-skill Security Hardening sections.
- [ ] **Formula injection sanitized at Excel write time** — strip / escape leading `=`, `+`, `-`, `@`, `\t`, `\r` in user-controlled cell values. Cross-ref: `ms-office-excel-python` HARD-RULE 1.
- [ ] **Macro-strip handled explicitly for `.docm` / `.xlsm` / `.pptm`** — refuse or require `--accept-macro-strip` with logged decision. Validator rule MSOSEC-OFFICE001. Cross-ref: `ms-office-word-python` HARD-RULE 1, parent skill family hardening guidance.
- [ ] **Password-protected workbook decryption uses vault password** — never literal in source. Cross-ref: `ms-office-excel-python` §"Encrypted workbooks".
- [ ] **`load_workbook(path, read_only=True)` for untrusted input** — bounds memory; pairs with XXE defence.
- [ ] **Document metadata stripped before external publishing** — `doc.core_properties` (author, last_modified_by, comments, keywords) carry PII.

## 6. Logging & audit

- [ ] **Token redactor in logger setup** — before enabling msal / azure-identity / msgraph-sdk debug logs.
- [ ] **Webhook URLs never logged** — Graph subscription `notificationUrl` is bearer-like.
- [ ] **Audit-log every privileged Graph operation** — `Send`, `Delete`, `Move`, permission changes — with principal `oid`, target, outcome.
- [ ] **Audit-log every encrypted workbook decryption** — filename + actor + timestamp.
- [ ] **Audit-log every offline `.pst` / `.msg` parse** — bypasses tenant DLP.

## 7. National clouds

- [ ] **Authority URL matches target cloud** — Commercial vs GCC / GCC-H / DoD / China. Cross-ref: `ms-office-enterprise-sso-python` §12.
- [ ] **Graph endpoint matches target cloud** — `graph.microsoft.com` vs `graph.microsoft.us` vs `microsoftgraph.chinacloudapi.cn`.
- [ ] **Sovereign-cloud feature parity verified per resource** — some Graph endpoints / features ship later in sovereign clouds.

## 8. Operational

- [ ] **Token cache encryption verified per OS** — DPAPI / Keychain / libsecret. Cross-ref: `ms-office-enterprise-sso-python` §7.
- [ ] **Subscription renewal monitored** — Graph webhook subscriptions max 3 days; missed renewal = data gap.
- [ ] **Throttling backoff capped** — never exponential-backoff blindly past 60s.
- [ ] **Certificate rotation scheduled** — for ConfidentialClientApplication cert-based auth, rotate before validity expires.
- [ ] **`MAX_BYTES` / `MAX_ROWS` budget on untrusted file input** — bounds memory against pathological files.
- [ ] **LibreOffice headless contention avoided** — per-process `UserInstallation` profile dir in parallel CI.

## 9. Family-wide

- [ ] **Library versions pinned** — `msal`, `msgraph-sdk`, `azure-identity`, `cryptography`, `lxml`, `defusedxml`, `pyjwt` explicit pins. Run `dep-currency-check` to surface stale or CVE-bearing versions.
- [ ] **Cloud-first preference for tenant-owned data** — Graph inherits Conditional Access, DLP, audit. Cross-ref: parent skill HARD-RULE 1.
- [ ] **Credentials in vault / Managed Identity / OS credential store** — never source / config / env-plaintext. Cross-ref: parent skill HARD-RULE 2.
- [ ] **EWS migration scheduled for Exchange Online code paths** — per Microsoft's announced schedule (disabled-by-default 2026-10-01, permanent shutdown 2027-04-01). Cross-ref: parent skill HARD-RULE 3.

## 10. What this checklist does NOT cover (defer to other tools)

| Concern | Tool |
|---|---|
| Generic Python SAST (verify=False non-Graph, eval/exec, shell=True) | `bandit -r .` |
| Custom org-specific patterns | `semgrep --config=auto .` |
| Hardcoded secrets / API keys / generic high-entropy strings | `gitleaks detect` |
| Dependency CVEs in any library | `pip-audit` / `dep-currency-check` |
| Stale library versions / deprecation timelines (non-Office) | `dep-currency-check` |
| SBOM emission | `cyclonedx-py` / `syft` |
| Live runtime token validation | n/a — belongs in runtime, not the scanner |
