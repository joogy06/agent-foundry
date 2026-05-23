---
name: ms-office-security-python
description: Use when hardening Python code that touches Microsoft Office files or Microsoft 365 APIs — covers the consolidated security checklist for the ms-office-python-* family, the YAML rule manifest (17 Office-specific rules), and the runnable Python validator (python3 -m ms_office_security_check). All output is advisory-only; defers generic SAST to bandit/semgrep, dependency CVEs to dep-currency-check/pip-audit, secrets to gitleaks/trufflehog, and SBOM to cyclonedx/syft. Part of the ms-office-python-* skill family.
---

# Microsoft Office Security — Python

Companion skill to `ms-office-python` (parent). For other areas see: `ms-office-excel-python`, `ms-office-word-python`, `ms-office-powerpoint-python`, `ms-office-graph-python`, `ms-office-enterprise-sso-python`.

This skill is the family's hardening surface. It ships THREE artifacts (Q1-A1 LOCKED):

1. **Markdown human-readable checklist** — for code review walkthroughs and design docs (`references/checklist.md`).
2. **YAML rule manifest** — machine-readable, the source of truth for what the validator detects (`ms_office_security_check/rules.yaml`).
3. **Runnable Python validator** — `python3 -m ms_office_security_check <project_root> [flags]`, mirroring `dep-currency-check`'s shape.

**ALL VALIDATOR OUTPUT IS ADVISORY ONLY — NOT A SECURITY GATE.** The validator surfaces findings to inform code review; it does not replace `bandit`, `pip-audit`, `gitleaks`, or `semgrep`, all of which run alongside it in a healthy CI pipeline. See §3 (Defer-to-X table) for the explicit boundary list.

<HARD-RULE>
Hardcoded `client_secret`, webhook URL, or bearer token in source code is a HALT-class finding (advisory output → CRITICAL severity → reviewer MUST resolve before merge). The validator emits these as CRITICAL with `confidence: high` — they are typically zero false positives. The remediation is invariably to move the value to a vault, Managed Identity, or OS credential store, NOT to bypass the validator's check with `--ignore`. See `ms-office-enterprise-sso-python` HARD-RULE 3 for the per-context replacement (Managed Identity on Azure compute, certificate-from-vault elsewhere).
</HARD-RULE>

<HARD-RULE>
Application Access Policy (AAP) is MANDATORY for any Graph application permission of the `Mail.Send` / `Mail.ReadWrite` / `Calendars.ReadWrite` / `Files.ReadWrite.All` / `Sites.ReadWrite.All` family. The validator's MSOSEC-C003 rule flags broad `.ReadWrite.All` / `.All` scope usage WITHOUT an allowlist entry in the project's `[tool.ms-office-security.scopes]` config — the allowlist forces a code-review conversation about whether the matching Application Access Policy is actually configured server-side. **The validator cannot verify the server-side policy exists; the code-review conversation is the control.** See `ms-office-graph-python` HARD-RULE 2 for the PowerShell pattern that creates the AAP.
</HARD-RULE>

<HARD-RULE>
`.docm` / `.xlsm` / `.pptm` ingestion paths require explicit, logged user-confirmed feature intent. Silent macro stripping (which `python-docx`, `openpyxl`, `python-pptx` do by default on save) is forbidden. Validator rules MSOSEC-OFFICE001 (`openpyxl.load_workbook` without `keep_vba=False` in untrusted-input contexts) and the per-skill HARD-RULEs (Word HR1, Excel guidance) backstop this with detection. The remediation is either to refuse macro-enabled files in the workflow OR to require an explicit `--accept-macro-strip` flag with a logged decision.
</HARD-RULE>

---

## 1. Overview

The validator is narrowly scoped to Office / MSAL / Graph / Entra patterns — the things that `bandit`, `semgrep`, `gitleaks`, and `pip-audit` don't catch. It does NOT replace those tools; it complements them. Generic Python security issues, generic secret scanning, dependency CVE detection, and SBOM emission all belong elsewhere.

The validator runs entirely offline. No network calls, no live tenant validation, no token introspection. Output is JSON canonical (`msosec.v1`), with Markdown and SARIF as renderings.

## 2. The 17 v1 rules (narrowed from validator design doc's 32)

Per master design doc §8, bob ships exactly **17 rules** in v1 (range 15-19 acceptable). The narrowing applies the following category-level rules: KEEP all Office-specific Auth (6 rules), KEEP Office-specific Transport (1), KEEP all Graph Scopes (3), DROP generic Secrets (defer to gitleaks / dep-currency-check), KEEP all Deprecated APIs (5), DROP Supply chain (defer to dep-currency-check / pip-audit), ADD Office documents (2).

The manifest is at `ms_office_security_check/rules.yaml`. Summary table — each rule has a stable ID (forever), severity, detection mechanism, and references back to the design.

| rule_id | category | severity | rule | detection |
|---|---|---|---|---|
| MSOSEC-A001 | Auth | CRITICAL | `adal` package imported anywhere (EOL since June 2023) | AST |
| MSOSEC-A002 | Auth | HIGH | On Windows-targeting code, `msal` imported but `msal[broker]` / `msal-broker` not in pinned requirements | manifest |
| MSOSEC-A003 | Auth | HIGH | `PublicClientApplication` instantiated without `enable_broker_on_windows=True` (WAM SSO opt-in) | AST |
| MSOSEC-A004 | Auth | CRITICAL | `ConfidentialClientApplication` instantiated with `client_credential=<str-literal>` (plaintext secret in source) | AST |
| MSOSEC-A009 | Auth | CRITICAL | `jwt.decode(...)` called with `options={"verify_signature": False}` or `verify=False` | AST |
| MSOSEC-A010 | Auth | CRITICAL | `jwt.decode(...)` called WITHOUT explicit `algorithms=[...]` (algorithm pinning) | AST |
| MSOSEC-A013 | Auth | HIGH | Issuer (`iss`) claim not validated — `jwt.decode` missing `issuer=` kwarg; for multi-tenant, also missing `tid` validation | AST |
| MSOSEC-B001 | Transport | CRITICAL | Office-specific CA bundle disabled — `requests.<verb>(<graph URL>, verify=False)` or `httpx.<verb>(<graph URL>, verify=False)` | AST (URL-pattern filtered) |
| MSOSEC-C001 | Graph scopes | HIGH | A Graph scope literal in code that is NOT in the project's declared scope allowlist (`[tool.ms-office-security.scopes]`) | regex+config |
| MSOSEC-C002 | Graph scopes | MEDIUM | `.default` scope used in conjunction with `PublicClientApplication` (delegated context — `.default` is for client-credentials only) | AST |
| MSOSEC-C003 | Graph scopes | HIGH | Use of any scope ending in `.ReadWrite.All` or `.All` (broad consent) without an explicit allow-rule in the config — reminds reviewer that Application Access Policy MUST be configured server-side | regex+config |
| MSOSEC-E001 | Deprecated APIs | MEDIUM | `import exchangelib` / `from exchangelib import ...` in code paths that don't carry the on-prem-Exchange comment marker — EWS retiring for Exchange Online (per Microsoft's announced schedule, disabled-by-default 2026-10-01 with permanent shutdown 2027-04-01; verify before treating as hard deadline) | AST |
| MSOSEC-E002 | Deprecated APIs | INFO | (Suppressed-by-A001 duplicate marker — kept for category alignment; documented in §2 of the validator design as deliberate dedup. The validator suppresses E002 emission when A001 fires on the same import site.) | suppressed |
| MSOSEC-E003 | Deprecated APIs | INFO | `pywin32` `win32com.client.Dispatch("Outlook.Application")` (COM automation) — flag as deprecated approach; refer to Graph | AST |
| MSOSEC-E004 | Deprecated APIs | HIGH | `import requests_kerberos` / `from requests_kerberos import ...` — legacy; superseded by `requests-gssapi` + `pyspnego` | AST |
| MSOSEC-E005 | Deprecated APIs | HIGH | `import pymsteams` / `from pymsteams import ...` — targets retired O365 Connectors API; migrate to Workflows OR Graph `chatMessage` | AST |
| MSOSEC-OFFICE001 | Office docs | MEDIUM | `openpyxl.load_workbook(...)` without `keep_vba=False` for untrusted-input contexts (heuristic on file-path provenance) | AST |
| MSOSEC-OFFICE002 | Office docs | HIGH | OOXML XML parsing path without `defusedxml` neutralization (heuristic — `lxml.etree.parse` / `xml.etree.ElementTree.parse` on Office file content) | AST |

**Arithmetic:** 6 Auth (A001, A002, A003, A004, A009, A010, A013 — that's 7) + 1 Transport (B001) + 3 Graph scopes (C001, C002, C003) + 5 Deprecated (E001, E002 suppressed, E003, E004, E005 — 4 active emitting) + 2 Office docs (OFFICE001, OFFICE002) = 7 + 1 + 3 + 4 + 2 = **17 rules** (E002 listed but always suppressed when A001 fires — counted as 1, design §8 dedup note).

**Rule-overlap check (WP-8 acceptance criterion):** every retained rule covers an Office-specific or MSAL/Graph/Entra-specific pattern that `bandit` (B501 verify=False generic, B105 hardcoded password), `semgrep` (Python ruleset), `gitleaks` (generic secret regex), `pip-audit` (CVE), or `dep-currency-check` (currency + CVE) does not catch. The retained set is intentionally narrow.

## 3. Defer-to-X (what this validator does NOT do)

| Concern | Tool to use instead |
|---|---|
| Generic Python SAST (verify=False on non-Graph URLs, hardcoded passwords, broad exception handling, shell=True, eval/exec) | `bandit -r .` |
| Custom security rule patterns (org-specific banned APIs) | `semgrep --config=auto .` |
| Hardcoded secrets, API keys, AWS keys, generic high-entropy strings | `gitleaks detect` / `trufflehog filesystem` |
| Dependency CVEs in `msal`, `msgraph-sdk`, `cryptography`, `lxml`, `pyjwt`, etc. | `pip-audit` / `dep-currency-check` |
| Stale library versions, deprecation timelines for non-Office libs | `dep-currency-check` |
| SBOM emission (CycloneDX / SPDX) | `cyclonedx-py` / `syft` |
| Live token validation against a tenant | n/a (the validator is offline by design; live validation belongs in the runtime) |
| Generic OAuth/OIDC client misconfiguration for non-Microsoft IdPs | `python-auth-security` skill + your IdP's tooling |

## 4. CLI

```bash
python3 -m ms_office_security_check <project_root> [flags]
```

Module name: `ms_office_security_check` (underscores). Skill directory: `ms-office-security-python/`. The Python package layout mirrors `dep-currency-check/dep_currency_check/`.

### Flags (mirror dep-currency-check shape)

| flag | purpose |
|---|---|
| `--severity {critical,high,medium,info,all}` | Minimum severity to report. Default: `high`. |
| `--format {json,md,sarif}` | Output format. Default: `json` (canonical). `md` and `sarif` are renderings. |
| `--rule <id>` | Run only this rule (repeatable). Useful for development. |
| `--ignore <id>` | Skip this rule (repeatable). Combines with project config `[tool.ms-office-security.ignore]`. |
| `--config <yaml>` | Path to project config (default: `ms-office-security.yaml` at root, else `pyproject.toml`). |
| `--changed-files <list>` | Comma-separated; delta mode for pre-commit (only scan these files). |
| `--mode {advisory,strict}` | Blocking criteria for exit code 1. Default: `advisory`. |
| `--rules-yaml <path>` | Override the bundled rules YAML (for skill development + alf evolution). |
| `--output <path>` | Write report to file instead of stdout. |
| `--quiet` | Suppress non-finding output. |
| `--no-color` | Disable ANSI in `md` rendering. |
| `--version` | Print validator + schema versions and exit 0. |

### Exit codes (mirror dep-currency-check)

| Code | Meaning |
|---|---|
| 0 | Pass — no strict-blocking findings (advisory findings still printed) |
| 1 | STRICT BLOCK — at least one CRITICAL finding AND `--mode strict` |
| 2 | Soft finding — reportable but not blocking; or strict mode with HIGH/MEDIUM only |
| 3 | Environmental error — parse failure, broken AST, missing rules YAML, malformed config |

### Suppression

`# msosec: ignore MSOSEC-A009` at end-of-line OR on the previous line. `# msosec: ignore MSOSEC-A009, MSOSEC-A010` for multiple. `# msosec: ignore file` at top of file suppresses ALL rules in that file. Project-level allowlist via `[tool.ms-office-security.ignore]` in `pyproject.toml` or `ms-office-security.yaml`.

## 5. Output schema (msosec.v1)

JSON canonical:

```json
{
  "schema_version": "msosec.v1",
  "validator_version": "1.0.0",
  "generated_at": "2026-05-22T10:00:00Z",
  "project_root": "/path/to/project",
  "config_source": "ms-office-security.yaml",
  "files_scanned": 142,
  "rules_loaded": 17,
  "rules_run": 17,
  "rules_skipped": [],
  "summary": {"critical": 2, "high": 5, "medium": 3, "info": 1, "suppressed": 4},
  "findings": [
    {
      "rule_id": "MSOSEC-A009",
      "severity": "critical",
      "category": "auth",
      "file": "src/integrations/sso.py",
      "line": 42,
      "col": 12,
      "code_excerpt": "jwt.decode(token, key, options={\"verify_signature\": False})",
      "message": "JWT signature verification disabled.",
      "fix_hint": "Remove options={\"verify_signature\": False}. Pass algorithms=[\"RS256\"] and use PyJWKClient.",
      "references": [
        "skill://ms-office-enterprise-sso-python#jwt-validation",
        "https://pyjwt.readthedocs.io/en/stable/usage.html"
      ],
      "confidence": "high",
      "detection": "ast",
      "advisory_only": true
    }
  ],
  "suppressions": [],
  "advisories": []
}
```

**Advisory-only banner** — the `advisory_only: true` field appears on every finding. Markdown rendering opens with:

> **Advisory only — not a security gate.** This report surfaces Office-specific patterns for code review. Generic security findings belong to `bandit` / `semgrep` / `gitleaks` / `pip-audit` / `dep-currency-check`.

## 6. Integration points

| Caller | How |
|---|---|
| **Pre-commit hook** (POSIX `.sh` + Windows hardened `.ps1`) | `ms_office_security_check/pre-commit-msosec.sh` / `.ps1` — advisory mode by default; mirrors `dep-currency-check` enterprise-hardened pattern (no `-ExecutionPolicy Bypass`, `-NoProfile -NonInteractive -File` for PowerShell entry). |
| **CI (GitHub Actions)** | `python3 -m ms_office_security_check . --format sarif --output msosec.sarif --mode strict` followed by `github/codeql-action/upload-sarif@v3`. SARIF upload populates GitHub Code Scanning. |
| **forge Step 1 advisory** | When forge detects any office-* import / msgraph/msal/exchangelib/O365 in scope, auto-invokes the validator in advisory mode and feeds `ms_office_security` into `shared_context`. |
| **Standalone CLI** | `python3 -m ms_office_security_check .` — JSON to stdout; `--format md` for terminal-readable. |
| **alf Step 2a** | Subprocess-call the CLI; alf reads JSON directly without parsing model output. |

NOT integrated in v1 (deferred): `G_MSOSEC` gate in `_meta/gates.py`, scope_delta source, alf skill-level wiring.

## 7. Consolidated security checklist (Markdown human-readable summary)

The full Markdown checklist lives at `references/checklist.md`. Cross-references to per-skill HARD-RULEs and hardening bullets across the family. Summary of categories:

- **Authentication** — broker enforcement, ROPC removal, hardcoded secret detection, encrypted token cache, JWT validation.
- **Authorization (Graph scopes)** — least-privilege scope selection, Application Access Policy for application permissions, RSC for Teams apps.
- **Transport** — TLS verification on Graph calls, CA bundle integrity, OAuth XOAUTH2 for SMTP.
- **Deprecated APIs** — `adal`, `exchangelib` (Exchange Online), `pymsteams`, `requests-kerberos`, `pywin32` COM automation in server contexts.
- **Office documents** — XXE defence via `defusedxml`, formula-injection sanitization (Excel), macro-strip handling for `.docm`/`.xlsm`/`.pptm`, password-protected workbook decryption.
- **Logging & audit** — never log raw tokens / refresh tokens / webhook URLs; redactor wrappers on debug-level HTTP logging; audit-log every privileged Graph operation.
- **National clouds** — authority URL + Graph endpoint matrix verified per resource; sovereign-cloud feature parity check.
- **Operational** — token cache hardening (msal-extensions), webhook subscription validation, throttling backoff caps, certificate rotation policy.

## 8. Anti-Patterns

| Don't | Why |
|---|---|
| Treat validator output as gating | It's advisory only — reviewer judgement determines disposition |
| Add a rule that duplicates `bandit` or `gitleaks` | Family contract is Office-specific; generic SAST/secrets belong to other tools |
| Skip `--ignore` discipline (suppress everything) | Suppressions need code-review justification; bulk-ignore defeats the point |
| Run the validator without `--severity high` baseline | Default is `high`; running `--severity info` floods the report |
| Modify the rule manifest YAML in v1 to add new rules | Rule IDs are stable forever; new rules belong in v1.1 with code review |
| Add live network calls (JWKS fetch, token introspection) | Validator is offline-safe by design — network belongs in runtime, not the scanner |

## 9. Update Triggers (per Codex M-1 — alf will scan these)

- Microsoft deprecation announcements affecting: EWS, Office 365 Connectors API, ADAL, basic auth for SMTP / IMAP / POP, any msgraph-sdk major version, `azure-identity` major version, broker DLL distribution model.
- Major version bumps of: any of the libraries the rule manifest references.
- New Office-specific CVE class (e.g., a new XXE in `lxml` / `openpyxl`).
- `dep-currency-check` ↔ this validator boundary changes (e.g., dep-currency-check grows secret scanning — in which case revisit whether the deferred Category D should remain dropped).
- Annual review on: 2027-05-22.

## See Also

| Need | Skill |
|---|---|
| Generic Python SAST | `bandit` (external tool) |
| Generic secret scanning | `gitleaks` / `trufflehog` (external tools) |
| Dependency CVE / currency | `dep-currency-check` |
| SBOM emission | `cyclonedx-py` / `syft` (external tools) |
| Per-skill HARD-RULEs and hardening bullets | `ms-office-excel-python`, `ms-office-word-python`, `ms-office-powerpoint-python`, `ms-office-graph-python`, `ms-office-enterprise-sso-python` |
| Authentication HARD-RULEs (load-bearing for this checklist) | `ms-office-enterprise-sso-python` |
| Graph application permissions + Application Access Policy | `ms-office-graph-python` |
