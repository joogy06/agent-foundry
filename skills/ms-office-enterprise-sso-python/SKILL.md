---
name: ms-office-enterprise-sso-python
description: Use when authenticating a Python client to Microsoft Entra ID / Azure AD / on-prem AD FS — covering the four enterprise auth topologies (Windows brokered interactive via msal[broker]/pymsalruntime, Linux brokered interactive via azure-identity-broker on Intune-managed Linux, headless / daemon with client credentials + certs + Managed Identity + Workload Identity Federation, and legacy on-prem via pyspnego / requests-gssapi / requests-negotiate-sspi). Plus SAML 2.0 SPs (pysaml2, python3-saml), JWT validation (pyjwt[crypto]), encrypted token cache (msal-extensions), hardware keys (fido2, pyscard). Covers Conditional Access claim semantics, MFA step-up, national clouds, device join state (dsregcmd matrix), and the WAM broker DLL load path. Part of the ms-office-python-* skill family.
family: ms-office
disambiguation: Authenticating a PYTHON CLIENT to Entra ID or AD FS — the auth topologies and their libraries. Configuring the SSO infrastructure itself on Windows is windows-sso.
---

# Microsoft Enterprise SSO — Python

Companion skill to `ms-office-python` (parent). For other areas see: `ms-office-excel-python`, `ms-office-word-python`, `ms-office-powerpoint-python`, `ms-office-graph-python`, `ms-office-security-python`.

This is the family's KEYSTONE skill — the largest body of content, the most cited from siblings, and the one most likely to be wrong about a Microsoft detail. It covers the **Python client** side of enterprise SSO. For PowerShell-based **infrastructure** administration (AD FS server install, Entra ID tenant configuration, WAP deployment), see `windows-sso`. For server-side Python web apps consuming generic OAuth/OIDC/SAML against non-Microsoft IdPs, see `python-auth-security`.

<HARD-RULE>
NEVER use device-code flow on a managed Windows endpoint when a broker is available. Device code authenticates via `https://microsoft.com/devicelogin` in a separate browser, bypassing the WAM broker entirely. The resulting token lacks the device-compliance, device-join, and PRT (Primary Refresh Token) claims that Conditional Access uses to gate sensitive resources. The CA evaluation engine sees a "compliant-device required" policy and either blocks the request outright OR (worse, silently) downgrades the principal's permissions for that session. Use `PublicClientApplication(enable_broker_on_windows=True)` and the broker interactive + silent flow on managed Windows. Device code is correct ONLY for CI / unmanaged / no-browser-available contexts.
</HARD-RULE>

<HARD-RULE>
NEVER use ROPC (Resource Owner Password Credentials, `acquire_token_by_username_password`) for new code. ROPC is incompatible with MFA, Conditional Access, password-less auth, and federated identity providers. Microsoft has marked it deprecated repeatedly; tenants are increasingly blocking it via tenant-level policy. Legacy code using ROPC must be migrated. The correct replacements are: interactive flows for user-context (broker preferred), client credentials for daemon-context, managed identity for Azure compute. There is no scenario in 2026 where ROPC is the right answer for new code.
</HARD-RULE>

<HARD-RULE>
NEVER hardcode `client_secret` for confidential clients on Azure compute. On Azure compute (VM, App Service, Container Apps, AKS, Functions, etc.) use Managed Identity — no secret in code, in config, or in a vault. The platform issues the credential. On non-Azure compute (on-prem, AWS, GCP, developer laptop) use **certificate-based auth** with the certificate stored in a vault (Key Vault, HashiCorp Vault, Conjur) or the OS credential store. Workload Identity Federation (OIDC trust between Entra ID and the workload's native identity, e.g. GitHub Actions OIDC token, AWS IAM role) is the modern preferred path for cross-cloud and CI scenarios. `client_secret` is never the answer on Azure; rarely the answer elsewhere.
</HARD-RULE>

<HARD-RULE>
Validate every JWT claim. `pyjwt.decode(...)` MUST be called with explicit `algorithms=[...]` (algorithm pinning — never accept `none`, never accept HS-* against an asymmetric key), explicit `audience=...` (rejects tokens minted for a different resource), explicit `issuer=...` (rejects tokens from a foreign tenant in multi-tenant apps), and explicit verification of `exp`, `nbf`, `iat`. For multi-tenant apps, validate the `tid` claim against an allowlist of accepted tenants. Validate `azp` (authorized party) when the access token was minted for a downstream API. Missing `tid` validation in multi-tenant apps is a cross-tenant token-replay vulnerability — see `ms-office-security-python` rule MSOSEC-A013 and the canonical pattern in this skill's JWT section.
```python
jwt.decode(token, signing_key, algorithms=["RS256"], audience=client_id,
           issuer=f"https://login.microsoftonline.com/{expected_tid}/v2.0",
           options={"require": ["exp", "iat", "nbf", "iss", "aud"]})
```
</HARD-RULE>

---

## Overview

Authenticating a Python client to Microsoft Entra ID involves picking the right flow for the right context, configuring it correctly, hardening the token cache, and validating every token claim on receipt. The wrong choice silently degrades security (device code on a managed device, ROPC anywhere, hardcoded secrets); the right choice composes cleanly with Conditional Access, MFA, device compliance, and tenant-wide audit logging.

This skill covers the four enterprise auth topologies — each is a peer, not a footnote — and the supporting concerns (token cache, JWT validation, SAML, Kerberos, national clouds, hardware keys, troubleshooting).

## 2. Authentication Decision Framework

The opening section — answer this matrix BEFORE choosing a library.

| Device state | Recommended flow | Library |
|---|---|---|
| Win 11 AAD-joined | Broker interactive + silent | `msal[broker]` |
| Win 11 Hybrid-joined | Broker interactive + silent (with hedging — see §6.1) | `msal[broker]` |
| Win 11 Workplace-joined | Broker if it engages, else system browser fallback | `msal[broker]` |
| Win 11 unjoined | System browser (no broker) | `msal` |
| Linux + Intune-managed | Linux broker via DBus | `azure-identity-broker` (`InteractiveBrowserBrokerCredential`) |
| Linux + unmanaged | Device code OR cert-based client credentials | `msal` / `azure-identity` |
| Headless server | Client credentials with certificate | `azure-identity` (`CertificateCredential`) or `msal` (`ConfidentialClientApplication`) |
| Container in Azure | Managed Identity OR Workload Identity Federation | `azure-identity` (`ManagedIdentityCredential` / `WorkloadIdentityCredential`) |
| Container elsewhere (AWS / GCP / on-prem) | Workload Identity Federation OR cert from vault | `azure-identity` (`WorkloadIdentityCredential` / `CertificateCredential`) |
| CI (GitHub Actions / GitLab) | OIDC Federated Credential | `azure-identity` (`WorkloadIdentityCredential` using the runner's OIDC token) |
| On-prem service (Kerberos realm) | Kerberos / SPNEGO | `requests-gssapi` (Linux/macOS) / `requests-negotiate-sspi` (Windows) / `pyspnego` (unified) |
| Disconnected / air-gapped service | Cert-based client credentials with cert pre-staged | `msal` / `azure-identity` |

This matrix decides everything else. Mismatched flow ↔ device state = Conditional Access failures (the most common production incident this family sees).

## 3. The `dsregcmd /status` matrix (Windows)

When the recommended flow on Windows isn't behaving as expected, the first diagnostic is `dsregcmd /status` on the client. Five rows you'll see in real environments:

| Row | What to look for | Implication |
|---|---|---|
| AAD-joined | `AzureAdJoined: YES`, `EnterpriseJoined: NO`, `DomainJoined: NO` | Cloud-only managed device; broker preferred |
| Hybrid-joined | `AzureAdJoined: YES`, `EnterpriseJoined: YES`, `DomainJoined: YES` | Both on-prem AD and Entra ID; broker works; PRT issued |
| Workplace-joined | `WorkplaceJoined: YES`, `AzureAdJoined: NO`, `DomainJoined: NO` | Personal device with work profile; broker engages when available, falls back to browser |
| AD-only (on-prem AD-joined) | `DomainJoined: YES`, `AzureAdJoined: NO` | No Entra ID identity on device; cannot use broker; use Kerberos for on-prem services, device-code or browser for Entra ID resources |
| Unjoined | All `NO` | Personal / unmanaged device; system browser only |

Other diagnostic fields worth checking:

- `WamDefaultSet: YES` and `WamDefaultGUID: { ... }` — the Web Account Manager is wired up.
- `AzureAdPrt: YES` — Primary Refresh Token issued; required for SSO across Microsoft 365.
- `KeySignTest: PASSED` — the device's key for binding tokens is healthy.
- `DeviceAuthStatus: SUCCESS` — Entra ID accepts the device's certificate.

If any of those report `NO` / `FAILED`, the broker path will misbehave; document the diagnostic in the troubleshooting flow.

## 4. Library Selection

| Library | Purpose | Status (2026-05) | OS support | When to use | When NOT to use |
|---|---|---|---|---|---|
| `msal` | Microsoft Authentication Library — direct M365 / Graph auth | Active (preferred for M365 auth) | All | Default for any Python client → Microsoft IdP path | Generic non-Microsoft IdP (use `authlib`); Azure SDK auth abstraction (use `azure-identity`) |
| `msal[broker]` / `pymsalruntime` | WAM broker bindings for Windows | Active | Windows | Conditional-Access compliance on managed Windows | Linux (separate broker package); Mac (no Win broker) |
| `msal-extensions` | Encrypted token cache | Active | All | Persisting the MSAL token cache across runs without leaking tokens | When the cache is genuinely transient (single-shot CLI) |
| `azure-identity` | High-level credential abstractions | Active | All | Azure SDK auth, Managed Identity, Workload Identity Federation, `DefaultAzureCredential` chains | Direct Graph auth where MSAL's contract is closer to your needs |
| `azure-identity-broker` | `InteractiveBrowserBrokerCredential` (separate package) | Active | Windows + Linux (Intune-managed) | Brokered auth from azure-identity contexts; Linux broker via DBus | Mac (use msal[broker] equivalent path); unmanaged Linux (no broker) |
| `authlib` | Generic OIDC/OAuth2 client | Active | All | Non-Microsoft IdPs (Okta, Auth0, Keycloak) | Microsoft IdPs — MSAL is better-fitting |
| `requests-oauthlib` | Simpler OAuth2 for `requests` | Active | All | Lightweight non-Microsoft OAuth2 | Microsoft IdPs (MSAL is more correct) |
| `pyspnego` | Modern unified SPNEGO/NTLM/Kerberos | Active (preferred) | All | Kerberos / SPNEGO against on-prem services | Cloud-only (no on-prem identity) |
| `requests-gssapi` | Kerberos for `requests` on Linux/Mac | Active | Linux / macOS | Adding Kerberos to existing `requests` code on UNIX | Windows (use `requests-negotiate-sspi`) |
| `requests-negotiate-sspi` | Windows Negotiate via SSPI | Active | Windows | Adding Kerberos to existing `requests` code on Windows | Linux / macOS |
| `requests-kerberos` | (legacy unified Kerberos) | **LEGACY** (superseded) | All | NOT for new code | Migrate to pyspnego + requests-gssapi / requests-negotiate-sspi |
| `pysaml2` | SAML 2.0 SP / IdP | Active | All | Talking SAML to a legacy IdP | Modern OIDC paths exist (prefer those when offered) |
| `python3-saml` | OneLogin's SAML toolkit | Active | All | SAML when pysaml2 doesn't fit | Same as pysaml2 |
| `pyjwt[crypto]` | JWT signing/validation | Active | All | Validating Entra-issued access / id tokens | Generic JWS / JWE (use `python-jose`) |
| `python-jose[cryptography]` | JWT / JWE / JWK | Active | All | When JWE is required (rare in Microsoft surface) | Standard JWT (`pyjwt` is enough) |
| `cryptography` | Foundation crypto | Active | All | Everywhere via dependency chain | (always pinned, CVE-watch) |
| `fido2` | WebAuthn / FIDO2 client | Active | All | Hardware-key auth flows | Server-side FIDO2 validation (see `python-auth-security`) |
| `pyscard` | PC/SC smart cards (CAC / PIV) | Active | All | Smartcard / CAC / PIV scenarios | Software-only auth |
| `python-pkcs11` | PKCS#11 token access | Active | All | HSM / HW token integration | Software keys |
| `keyring` | Cross-platform OS keyring | Active | All | Single-secret retrieval from OS credential store | Full credential management (use msal-extensions for MSAL caches) |
| `adal` | (predecessor to msal) | **EOL** | All | NOT for any new code; migrate immediately | All cases — replaced by `msal` |

**Boundary clarifier (Codex H-29):** MSAL is for direct M365 / Graph auth; azure-identity is for Azure SDK auth and high-level credential abstraction (which includes some Graph use via `GraphServiceClient(credentials=...)`). They overlap — pick MSAL when you want explicit token control, azure-identity when you want credential abstraction and Managed Identity / Workload Identity primitives.

## 5. Install Commands

### RHEL 9 / AlmaLinux 9 / Rocky 9

```bash
sudo dnf install -y python3.12 python3-pip python3-devel gcc-c++ \
  krb5-devel libxml2-devel libxslt-devel libsecret-devel libxmlsec1-devel cyrus-sasl-gssapi
python3 -m pip install --upgrade pip
python3 -m pip install msal msal-extensions azure-identity pyjwt cryptography defusedxml pyspnego
# Optional, per branch:
python3 -m pip install azure-identity-broker      # Linux broker (Intune-managed)
python3 -m pip install requests-gssapi             # Kerberos on requests
python3 -m pip install pysaml2 python3-saml        # SAML
python3 -m pip install fido2 python-pkcs11 keyring # hardware keys
```

For Linux broker support (Intune-managed devices only):

```bash
# Add Microsoft's Linux repo (Ubuntu/Debian have similar steps)
sudo dnf install -y microsoft-identity-broker  # only available on supported distros
```

### Debian 12 / Ubuntu 24.04

```bash
sudo apt update
sudo apt install -y python3.12 python3-pip python3-dev build-essential \
  libkrb5-dev libxml2-dev libxslt1-dev libsecret-1-dev libxmlsec1-dev libsasl2-modules-gssapi-mit
python3 -m pip install --upgrade pip
python3 -m pip install msal msal-extensions azure-identity pyjwt cryptography defusedxml pyspnego
python3 -m pip install azure-identity-broker requests-gssapi
python3 -m pip install pysaml2 python3-saml fido2 python-pkcs11 keyring
# Optional, Linux broker:
# curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | sudo gpg --dearmor -o /usr/share/keyrings/microsoft.gpg
# sudo apt install -y microsoft-identity-broker
```

### Windows 11

```powershell
winget install --id Python.Python.3.12 -e --silent
python -m pip install --upgrade pip
python -m pip install msal "msal[broker]" msal-extensions azure-identity azure-identity-broker `
    pyjwt cryptography defusedxml requests-negotiate-sspi pyspnego pysaml2 python3-saml fido2 keyring
# Verify broker DLLs load:
python -c "import pymsalruntime; print(pymsalruntime.__file__)"
```

## 6. Flow recipes (one canonical example per flow per modified-C3)

### 6.1 Broker interactive + silent + fallback (Windows)

```python
# CONFIDENCE: minimal viable pattern — production hardening notes in §7 Token cache hardening and the Security Hardening section below; full references/ guide planned (v1.1).
import msal
app = msal.PublicClientApplication(
    client_id=CLIENT_ID,
    authority=f"https://login.microsoftonline.com/{TENANT_ID}",
    enable_broker_on_windows=True,
)
accounts = app.get_accounts()
if accounts:
    result = app.acquire_token_silent(scopes=SCOPES, account=accounts[0])
else:
    result = None
if not result:
    result = app.acquire_token_interactive(scopes=SCOPES, parent_window_handle=msal.PublicClientApplication.CONSOLE_WINDOW_HANDLE)
# result["access_token"] is the bearer; result["id_token_claims"] has user info
```

Three things this pattern enforces: broker explicitly enabled (`enable_broker_on_windows=True`), silent attempted first (cache hit avoids broker UI), `parent_window_handle` passed (required for the broker pop-up to actually appear and not silently fail).

### 6.2 Broker interactive (Linux, Intune-managed)

```python
# CONFIDENCE: minimal viable pattern — production hardening notes in §7 Token cache hardening and the Security Hardening section below; full references/ guide planned (v1.1).
from azure.identity.broker import InteractiveBrowserBrokerCredential
cred = InteractiveBrowserBrokerCredential(
    tenant_id=TENANT_ID, client_id=CLIENT_ID,
    parent_window_handle=0,   # 0 = unbound on Linux DBus; broker prompt appears in foreground
)
token = cred.get_token(*SCOPES)
# token.token is the bearer
```

Verify broker availability first: `microsoft-identity-broker` package installed and `microsoft-identity-broker.service` running. Without it the credential silently falls back to system browser.

### 6.3 Device code (CI / unmanaged)

```python
# CONFIDENCE: minimal viable pattern — production hardening notes in §7 Token cache hardening and the Security Hardening section below; full references/ guide planned (v1.1).
import msal
app = msal.PublicClientApplication(client_id=CLIENT_ID,
                                   authority=f"https://login.microsoftonline.com/{TENANT_ID}")
flow = app.initiate_device_flow(scopes=SCOPES)
print(flow["message"])  # prints "go to microsoft.com/devicelogin and enter CODE"
result = app.acquire_token_by_device_flow(flow)
```

DO NOT use this on a managed Windows endpoint. See HARD-RULE 1.

### 6.4 Client credentials with certificate (daemon)

```python
# CONFIDENCE: minimal viable pattern — production hardening notes in the Security Hardening section below (cert/key handling: vault-only); full references/ guide planned (v1.1).
import msal
with open(CERT_PATH, "rb") as fh:
    cert_pem = fh.read()
with open(KEY_PATH, "rb") as fh:
    key_pem = fh.read()
app = msal.ConfidentialClientApplication(
    client_id=CLIENT_ID,
    authority=f"https://login.microsoftonline.com/{TENANT_ID}",
    client_credential={"private_key": key_pem, "thumbprint": CERT_THUMBPRINT, "public_certificate": cert_pem},
)
result = app.acquire_token_for_client(scopes=[f"{RESOURCE}/.default"])
```

Cert and key MUST come from a vault — not from disk paths checked into git. The path above is illustrative.

### 6.5 Managed identity (Azure compute)

```python
# CONFIDENCE: minimal viable pattern — production hardening notes in the Security Hardening section below; full references/ guide planned (v1.1).
from azure.identity import ManagedIdentityCredential
cred = ManagedIdentityCredential()                       # system-assigned MI
# cred = ManagedIdentityCredential(client_id=USER_ASSIGNED_MI_CLIENT_ID)  # user-assigned MI
token = cred.get_token("https://graph.microsoft.com/.default")
```

No secret. No cert. The Azure platform issues the credential. Works on App Service, VM, Container Apps, AKS, Functions, Container Instances, Logic Apps.

### 6.6 Workload identity federation (K8s / GitHub Actions)

```python
# CONFIDENCE: minimal viable pattern — production hardening notes in the Security Hardening section below; full references/ guide planned (v1.1).
from azure.identity import WorkloadIdentityCredential
cred = WorkloadIdentityCredential(
    tenant_id=TENANT_ID, client_id=CLIENT_ID,
    token_file_path="/var/run/secrets/azure/tokens/azure-identity-token",   # AKS injects this
)
token = cred.get_token("https://graph.microsoft.com/.default")
```

For GitHub Actions, the OIDC token comes from `ACTIONS_ID_TOKEN_REQUEST_TOKEN` / `ACTIONS_ID_TOKEN_REQUEST_URL`. For GitLab, the equivalent OIDC token. The federated credential is configured in the Entra ID app registration.

### 6.7 Kerberos against on-prem

```python
# CONFIDENCE: minimal viable pattern — production notes in §13 Troubleshooting and the Security Hardening section below; full references/ guide planned (v1.1).
import requests
from requests_gssapi import HTTPSPNEGOAuth   # or requests_negotiate_sspi.HttpNegotiateAuth on Windows
session = requests.Session()
session.auth = HTTPSPNEGOAuth()
resp = session.get("https://onprem-service.example.com/api/data")  # uses ambient Kerberos ticket
```

Requires a valid Kerberos ticket on the client (`klist` to verify). For service accounts, `kinit` from a keytab. `pyspnego` is the modern unified path if you need NTLM fallback or direct SPNEGO control.

## 7. Token cache hardening

`msal.SerializableTokenCache()` produces a JSON blob that holds access tokens, refresh tokens, and ID tokens. Persisting it to disk without encryption = a token leak vector. `msal-extensions` wraps it in OS-native encrypted storage:

| Platform | Backend |
|---|---|
| Windows | DPAPI (per-user encryption) |
| macOS | Keychain |
| Linux | libsecret (GNOME Keyring / KWallet) — falls back to file-based with explicit warning if unavailable |

Use `msal_extensions.PersistedTokenCache` with the appropriate `PersistenceBuilder` for the OS. Reading the cache without `msal-extensions` (e.g., from a different binary) is unsupported and breaks the security model.

## 8. Conditional Access semantics

What the broker gets you that the browser doesn't:

- **Device-compliance claim** (`deviceid`, `is_compliant`) — proves the device is enrolled and meets policy.
- **PRT (Primary Refresh Token)** — issued at sign-in to AAD-joined devices; mints application tokens silently for the SSO session lifetime.
- **MFA-already-satisfied claim** — avoids re-prompting MFA when the device sign-in was MFA-attested.
- **Hybrid SSO** — Kerberos + Entra ID in one session on hybrid-joined devices.

Conditional Access policies evaluate these claims. A token without them is treated as a token from an unmanaged device — for sensitive resources, that's a block.

Common CA error codes :

| Code | Meaning |
|---|---|
| `AADSTS53003` | Access blocked by Conditional Access policies |
| `AADSTS50158` | External security challenge required (step-up MFA) |
| `AADSTS50076` | Multi-factor authentication required |
| `AADSTS50132` | Sign-in session became invalid (often device-state change) |
| `AADSTS65001` | Consent required (admin or user) |
| `AADSTS50105` | Entitled application not assigned to user (RBAC / SP role mismatch) |
| `AADSTS50034` | User account doesn't exist in directory (often typo'd UPN) |
| `AADSTS900971` | No reply address provided (app-registration redirect URI mismatch) |
| `AADSTS70011` | Invalid scope (the scope literal you requested isn't valid for the resource) |
| `AADSTS70008` | Refresh token expired |

When these surface in logs, the fix is configuration / policy — not retrying the same call.

## 9. JWT validation patterns

For deep generic JWT validation patterns, see `python-auth-security` JWT Best Practices. Microsoft-specific notes:

- **`tid` (tenant ID)** — multi-tenant apps MUST validate. Without it, a token from tenant B can replay against your tenant-A app.
- **`azp` (authorized party)** — for access tokens minted for a downstream API, identifies the client app that received the token. Validate when you delegate the call.
- **`acr` / `amr` (authentication context references / methods)** — tells you what MFA / hardware-key / passwordless was used. Step-up flows depend on this.
- **`oid` (object ID)** — the user's immutable ID in Entra ID. Prefer over `email` / `upn` for joins and audit (those can change).
- **`tid` validation example**:

```python
# CONFIDENCE: minimal viable pattern — claim checklist above + Security Hardening section below; deep JWT patterns in the python-auth-security skill; full references/ guide planned (v1.1).
import jwt
from jwt import PyJWKClient
jwks_client = PyJWKClient(f"https://login.microsoftonline.com/{TENANT_ID}/discovery/keys")
signing_key = jwks_client.get_signing_key_from_jwt(token).key
claims = jwt.decode(
    token, signing_key,
    algorithms=["RS256"],
    audience=AUDIENCE,
    issuer=f"https://login.microsoftonline.com/{TENANT_ID}/v2.0",
    options={"require": ["exp", "iat", "nbf", "iss", "aud", "tid"]},
)
assert claims["tid"] == EXPECTED_TID, f"Token from wrong tenant: {claims['tid']}"
```

Algorithm-pin (`algorithms=["RS256"]`) is mandatory. JWKS caching via `PyJWKClient` is mandatory (don't fetch JWKS per token validation).

## 10. SAML 2.0 for legacy IdPs

See `python-auth-security` for the generic SAML patterns. Microsoft-specific notes:

- **Entra ID can act as a SAML IdP** (in addition to OIDC). The metadata endpoint is `https://login.microsoftonline.com/{tenant_id}/federationmetadata/2007-06/federationmetadata.xml`.
- **AD FS** is the on-prem SAML IdP. Metadata at `https://adfs.example.com/FederationMetadata/2007-06/FederationMetadata.xml`.
- **Library selection**: `pysaml2` and `python3-saml` are both viable. `pysaml2` is more powerful but easier to misconfigure XML signature verification (a CVE class historically). `python3-saml` (OneLogin) has simpler defaults and is the safer first pick.
- Always verify XML signatures. Always pin signing algorithm (RSA-SHA256). Always reject SAML responses without `InResponseTo` matching your original AuthnRequest ID.

## 11. Hardware keys / smart cards / FIDO2

Overview only. Deep coverage will live in `python-auth-security` if expanded:

- **FIDO2 / WebAuthn** — `fido2` library; CTAP2 protocol; YubiKey + Feitian + SoloKey support.
- **Smart cards (CAC / PIV)** — `pyscard` for PC/SC; `python-pkcs11` for PKCS#11 backend.
- **Cert-on-token** — useful for `ConfidentialClientApplication` when the cert lives on a hardware token; load the private key through the PKCS#11 interface, sign assertions there.

Entra ID supports passwordless / phishing-resistant FIDO2 since 2022; the client side is straightforward (browser handles WebAuthn). What Python clients do is rarely the FIDO2 protocol itself; usually they consume tokens that were minted via a FIDO2-attested sign-in.

## 12. National clouds

Different authorities, different Graph endpoints:

| Cloud | Authority URL | Graph endpoint |
|---|---|---|
| Commercial | `https://login.microsoftonline.com/{tenant}` | `https://graph.microsoft.com` |
| GCC (Government Community Cloud) | Same as Commercial | Same as Commercial (GCC L4 uses Commercial endpoints) |
| GCC-H (High) | `https://login.microsoftonline.us/{tenant}` | `https://graph.microsoft.us` |
| DoD | `https://login.microsoftonline.us/{tenant}` | `https://dod-graph.microsoft.us` |
| Germany (closed 2021; historical mention) | n/a | n/a |
| China (21Vianet) | `https://login.partner.microsoftonline.cn/{tenant}` | `https://microsoftgraph.chinacloudapi.cn` |

The Python libraries support sovereign clouds — pass the appropriate `authority` URL to MSAL or use `azure-identity` with the sovereign endpoint constants. Some Graph endpoints / features ship later (or not at all) in sovereign clouds; verify per resource on Microsoft Learn before relying.

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `AADSTS53003` block | Conditional Access policy requires compliant device / MFA | Switch to broker flow on managed Windows; comply with policy |
| `pymsalruntime` DLL load failure on import | Missing VC++ runtime; ARM64 Python on x64 broker DLLs | Install VC++ 2015-2022 redist; verify `python -c "import platform; print(platform.architecture())"` matches broker |
| `3399614473` API contract violation | Mismatch between broker DLL version and msal version | Upgrade both `msal[broker]` and `pymsalruntime` together |
| Missing HWND on Windows broker prompt | `parent_window_handle` not passed | Pass `msal.PublicClientApplication.CONSOLE_WINDOW_HANDLE` for CLI, or actual HWND for GUI |
| `acquire_token_silent` returns None unexpectedly | Cache expired, refresh token revoked, tenant policy revoked session | Fall through to interactive — silent + interactive together is the correct pattern |
| `DefaultAzureCredential` succeeds in dev, fails in prod | Different credential source available in each env (cached CLI vs Managed Identity) | Use explicit `ManagedIdentityCredential` in prod, not `DefaultAzureCredential` |
| `AADSTS500011` (no service principal in tenant) | App registered in one tenant, consumed from another, no MT consent | Run admin consent in target tenant: `https://login.microsoftonline.com/{tenant}/adminconsent?client_id=...` |

## Security Hardening

See `ms-office-security-python` for the consolidated checklist. Area-specific items:

- HARD-RULEs 1-4 are the load-bearing items: no device code on managed Windows, no ROPC, no hardcoded secret on Azure, validate every JWT claim.
- Token cache MUST use msal-extensions encryption — never plain `SerializableTokenCache` to disk.
- For confidential clients on non-Azure compute, certificate auth from a vault; rotate certs on a schedule shorter than their issued validity.
- Workload Identity Federation eliminates the need for any secret rotation by trusting the workload's native identity provider — prefer it where feasible.
- NEVER log raw tokens. msal debug logs and azure-identity verbose logs CAN emit raw `Authorization: Bearer ...` headers. Wrap the logger with a token-redacting filter before enabling debug.
- Validate `tid` for multi-tenant apps (HARD-RULE 4). The default behaviour of pyjwt is to NOT require `tid` — you must request it explicitly via `options["require"]`.
- For SAML, pin signing algorithm to RSA-SHA256 minimum; validate `InResponseTo`; validate `Issuer`; never skip signature verification.
- Hardware-key sign-in is phishing-resistant — recommend it for highly-privileged accounts (Global Admin, Privileged Role Administrator).
- Audit-log every token acquisition with the principal (`oid`), tenant (`tid`), scopes requested, and outcome. The audit trail is what differentiates a forensic story from a vague "we got hacked."
- Pin `msal`, `azure-identity`, `cryptography`, `pyjwt`, `lxml` versions explicitly. CVE-watch via `dep-currency-check`.
- For Kerberos integrations, prefer `pyspnego` over `requests-kerberos`; modern, unified, no `gssapi`-vs-`pykerberos` confusion.

## Selection Cheatsheet

- "Token on managed Windows, silently" → `msal[broker]` + `PublicClientApplication(enable_broker_on_windows=True)`
- "Token on managed Linux (Intune)" → `azure-identity-broker` + `InteractiveBrowserBrokerCredential`
- "Token from a daemon on Azure compute" → `azure-identity` + `ManagedIdentityCredential`
- "Token from a daemon on AWS / GCP / on-prem" → certificate auth via `msal.ConfidentialClientApplication` OR `azure-identity` + `CertificateCredential`
- "Token from GitHub Actions / GitLab CI" → `azure-identity` + `WorkloadIdentityCredential` (Federated Credential)
- "Token from a service on a Kerberos realm to a Kerberos resource" → `pyspnego` or `requests-gssapi`
- "Validate a token I received" → `pyjwt` + `PyJWKClient` with explicit `algorithms`, `audience`, `issuer`, and `options["require"]`
- "Talk SAML to an old SAML 2.0 IdP" → `python3-saml` first; `pysaml2` if you need more control

## Gotchas

- `msal[broker]` extras require the `pymsalruntime` package which ships compiled DLLs. ARM64 Python on x64 broker DLLs (or vice-versa) fails at import. Match architectures.
- `azure-identity-broker` is a SEPARATE package from `azure-identity` (not an extra). It must be `pip install azure-identity-broker` explicitly.
- The Linux broker requires `microsoft-identity-broker` from Microsoft's repo AND an Intune-enrolled device. Without enrolment, the credential silently falls back to system browser.
- `DefaultAzureCredential` chains many sources and is convenient but produces wildly different behaviour across environments. Prefer explicit credentials in production.
- Conditional Access can issue a token that is technically valid but lacks the claims your downstream resource demands. Validate the claim set, not just the signature.
- ADAL is EOL since June 2023. Any `from adal import ...` is a finding — see `ms-office-security-python` rule MSOSEC-A001.
- ROPC will silently succeed on legacy tenants that haven't disabled it — making the bug invisible until the next tenant policy refresh. HARD-RULE 2 stands regardless of whether it currently works.
- `dsregcmd /status` requires admin context for some fields. The non-admin fields are usually enough to diagnose; document the admin path in troubleshooting.
- Refresh tokens issued to public clients are bound to the device's PRT (where applicable). Migrating a token cache between machines does NOT carry the device binding — silent acquire fails on the new machine.

## Update Triggers (per Codex M-1 — alf will scan these)

- Major version bump of: `msal`, `azure-identity`, `azure-identity-broker`, `pymsalruntime`, `pyjwt`, `cryptography`, `pyspnego`, `pysaml2`, `python3-saml`.
- Microsoft announcement affecting: ADAL removal, ROPC tenant-wide policy enforcement, broker DLL distribution model, Conditional Access claim set, national-cloud endpoint changes.
- CVE published against `cryptography`, `pyjwt`, `lxml` (XXE class), `pysaml2` (signature-bypass class).
- Annual review on: 2027-05-22.

## See Also

| Need | Skill |
|---|---|
| Generic Python web-app OAuth/OIDC/SAML/JWT (non-Microsoft IdPs) | `python-auth-security` |
| PowerShell-based AD FS / Entra ID infrastructure administration | `windows-sso` |
| Linux ⇄ AD via Centrify | `linux-centrify` |
| Calling Graph after acquiring the token | `ms-office-graph-python` |
| Hardening / validator / checklist | `ms-office-security-python` |
| Dependency CVE scanning of the auth libs | `dep-currency-check` |
| Active Directory infrastructure side | `windows-ad-admin` |
