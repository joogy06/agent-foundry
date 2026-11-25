---
name: spa-auth-webauthn
description: "Passkey (WebAuthn) auth for a same-origin SPA in front of an API: browser ceremony, server verification, cookie sessions and CSRF, step-up for sensitive actions, CSP and Trusted Types. Use when adding passkey login to an SPA."
license: MIT
metadata:
  version: "1.0.0"
  family: "frontend"
---

# SPA Auth with WebAuthn (Passkeys)

<!-- FRESHNESS:v1
volatility: medium
anchors:
  - kind: external_fact
    subject: webauthn-level-3
    source_url: https://www.w3.org/TR/webauthn-3/
    verified_on: 2026-10-26
    review_by: 2027-04-26
    claim: "Web Authentication Level 3 is a W3C Recommendation (2026-08-25); defines parseCreationOptionsFromJSON, parseRequestOptionsFromJSON, getClientCapabilities and the signalUnknownCredential / signalAllAcceptedCredentials / signalCurrentUserDetails methods."
  - kind: external_fact
    subject: simplewebauthn-browser
    source_url: https://www.npmjs.com/package/@simplewebauthn/browser
    verified_on: 2026-10-26
    review_by: 2027-01-26
    claim: "@simplewebauthn/browser 14.0.0 (server 14.0.3): startRegistration({ optionsJSON, useAutoRegister? }), startAuthentication({ optionsJSON, useBrowserAutofill?, verifyBrowserAutofillInput? }), browserSupportsWebAuthnAutofill, sendSignal; read from the published typings."
  - kind: external_fact
    subject: py-webauthn
    source_url: https://pypi.org/project/webauthn/
    verified_on: 2026-10-26
    review_by: 2027-01-26
    claim: "py_webauthn (PyPI webauthn) 3.0.1: generate_registration_options, verify_registration_response, generate_authentication_options, verify_authentication_response, options_to_json; VerifiedAuthentication fields credential_id, new_sign_count, credential_device_type, credential_backed_up, user_verified; signatures read from the installed package."
  - kind: external_fact
    subject: trusted-types-baseline
    source_url: https://developer.mozilla.org/en-US/docs/Web/API/Trusted_Types_API
    verified_on: 2026-10-26
    review_by: 2027-04-26
    claim: "Trusted Types API is Baseline newly available since February 2026; react-dom 19.3.1 assigns dangerouslySetInnerHTML.__html to innerHTML unchanged, so TrustedHTML passes through."
  - kind: external_fact
    subject: owasp-csrf
    source_url: https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
    verified_on: 2026-10-26
    review_by: 2027-04-26
    claim: "OWASP CSRF Prevention Cheat Sheet: synchronizer or signed double-submit token, custom request headers, Fetch Metadata (Sec-Fetch-Site) checks; SameSite cookies as defence in depth."
-->

## Overview

A single-page app served from the **same origin** as its API can sign people in with passkeys and
hold the session in an **HttpOnly cookie** — no token ever reaches JavaScript. This skill covers
the four pieces that have to agree: the browser ceremony, the server's verification contract, the
session and CSRF model, and step-up re-authentication for sensitive actions; plus the CSP and
Trusted Types policy that keeps the bundle that runs those ceremonies honest.

**Seams (route, do not duplicate):**

| Concern | Owner |
|---|---|
| OAuth2 / OIDC with PKCE against an external identity provider (react-oidc-context, angular-oauth2-oidc) | `modern-frontend` (`api-auth-forms.md` §5) |
| Password hashing, JWT rules, RBAC / ABAC, tenant isolation, OWASP Top 10 in Flask / FastAPI | `python-auth-security` |
| What an approval card looks like and when an action needs step-up | `operator-console-ux` |
| Dependency pins, SRI, no runtime CDN for the bundle | `modern-frontend` (`supply-chain-hygiene.md`) |
| Serving the built SPA and the API on one origin | `modern-frontend` (`vite-behind-api.md`) |
| Threat model of the whole system | `threat-modeling` |

## When to Use

- Adding passkey sign-in or registration to a React (or any) SPA whose API is on the same origin.
- Choosing between a cookie session and a bearer token for that SPA, and adding CSRF defence.
- Requiring re-authentication before approve, grant, revoke, delete or similar actions.
- Writing the CSP and Trusted Types policy for a built Vite bundle.
- Symptoms: `NotAllowedError` from `navigator.credentials`, `SecurityError` on RP ID, a session
  token in `localStorage`, CSRF findings on a cookie-auth API, "approve" protected only by the
  login session.
- **Not for:** third-party identity providers (OIDC), native mobile apps, cross-site embedded
  widgets.

## Ask before generating (ambiguity gate)

Before producing auth code or a policy, settle these; if any is missing and would change the
output, ask ONE compact question that covers them:

1. **Origins** - the exact origin(s) users load the SPA from, and whether the API is on the same
   origin (same scheme, host and port). This fixes the RP ID and expected origin.
2. **Account model** - passkey-only (usernameless, discoverable credentials) or passkeys added to an
   existing account with another sign-in method; one user or many.
3. **Sensitive actions** - which actions need step-up, and how recent the user verification must be.
4. **Server stack** - framework and language for the verification side (Python reference here).

## Binding rules

<HARD-RULE>
Verification happens on the server only. The server generates every challenge (random, at least
16 bytes, single use, short-lived, bound to the session or the pending ceremony), verifies origin,
RP ID hash, challenge, signature, user-presence and user-verification flags, and stores the
credential. The browser library's result is never trusted as proof.
</HARD-RULE>

<HARD-RULE>
For a same-origin SPA, the session lives in an HttpOnly, Secure, SameSite cookie (prefer the
`__Host-` prefix, Path=/, no Domain). Never put a session or bearer token in localStorage or
sessionStorage. A cookie session requires CSRF defence on every state-changing request.
</HARD-RULE>

<HARD-RULE>
Sensitive actions require step-up: a fresh WebAuthn assertion with userVerification "required"
(and require_user_verification=True on the server),
whose server challenge is bound to the specific action (its id and version), checked on the server
at the moment the action executes. A long-lived login session alone never authorises approve,
grant, revoke or delete. Adding a passkey to an account that already has one is a sensitive action
too: a key registered from a hijacked session would pass every later step-up.
</HARD-RULE>

<HARD-RULE>
The built bundle runs under a CSP with no 'unsafe-inline' and no 'unsafe-eval' for scripts,
scripts only from 'self' (no runtime CDN), and object-src 'none', base-uri 'none',
frame-ancestors 'none'. Roll out Trusted Types enforcement where the browser supports it, starting
in report-only mode.
</HARD-RULE>

## 1. Architecture at a glance

```text
Browser (SPA, origin https://ops.example)            API (same origin)
  │ POST /api/auth/passkey/register/options  ───────►  generate options, store challenge
  │ ◄──── PublicKeyCredentialCreationOptionsJSON
  │ navigator.credentials.create()  (via @simplewebauthn/browser startRegistration)
  │ POST /api/auth/passkey/register/verify   ───────►  verify, store credential
  │ POST /api/auth/passkey/login/options     ───────►  challenge (+ allowCredentials if known user)
  │ navigator.credentials.get()     (startAuthentication)
  │ POST /api/auth/passkey/login/verify      ───────►  verify, update counter, rotate session id
  │ ◄──── Set-Cookie: __Host-session=…; HttpOnly; Secure; SameSite=Strict; Path=/
  │ every mutating fetch: cookie + X-CSRF-Token header (or Sec-Fetch-Site check)
  │ POST /api/stepup/options {action, id, version} ─►  challenge bound to the action
  │ POST /api/approvals/{id}/decision + assertion ──►  verify assertion + binding, then act
```

## 2. Browser ceremony

Use `@simplewebauthn/browser` (v14 takes one options object: `startRegistration({ optionsJSON })`,
`startAuthentication({ optionsJSON, useBrowserAutofill })`) or the WebAuthn Level 3 JSON helpers
(Level 3 became a W3C Recommendation on 2026-08-25), so base64url encoding is not hand-rolled. Key
decisions:

| Option | Registration | Sign-in | Step-up |
|---|---|---|---|
| `residentKey` | `"required"` for usernameless sign-in | — | — |
| `userVerification` | `"preferred"` (or `"required"` for an admin console) | `"preferred"` or `"required"` | **`"required"`** |
| `attestation` | `"none"` unless you must restrict authenticator models | — | — |
| `allowCredentials` | — | empty for usernameless / autofill | the signed-in user's credentials |
| `mediation` | — | `"conditional"` for passkey autofill on the username field | not conditional |

Ceremony code, error handling (`NotAllowedError` = user cancelled or timed out, `InvalidStateError`
= credential already registered), autofill and the abort rules: `references/browser-ceremony.md`.

## 3. Server verification contract

Framework-neutral; the Python reference uses `py_webauthn` (PyPI package `webauthn`).

1. **Options:** generate with the RP ID (the registrable domain or the exact host), RP name, a
   stable opaque user handle (random bytes, never an email), and `excludeCredentials` on
   registration. Store the challenge server-side keyed to the session or a ceremony id, with a
   2–5 minute expiry.
2. **Verify registration:** expected challenge, expected origin (exact string, scheme and port
   included), expected RP ID, `require_user_verification` per policy. Persist: credential id,
   public key, sign count, transports, backup-eligible and backed-up flags, created-at, a user label.
3. **Verify authentication:** look up the credential by id, check it belongs to the user handle
   returned, verify, then update the sign count and last-used time. A sign count of 0 on both sides
   is normal for synced passkeys; a non-zero count that goes backwards is a clone signal — log and
   alert, and decide by policy whether to block.
4. **Consume the challenge** on every attempt, success or failure.
5. **Session:** on success, create a new session id (rotate, never reuse the pre-auth one), set the
   cookie, record `auth_time` and the user-verification flag.

Full Python reference (FastAPI routes) and the storage schema: `references/server-verification.md`.

## 4. Session: cookie vs bearer for a same-origin SPA

| | HttpOnly cookie session | Bearer token in JS memory |
|---|---|---|
| XSS can steal it | No (script cannot read it) | Yes, while the page runs |
| XSS can use it | Yes, while the page is open (same for both) | Yes |
| CSRF exposure | Yes, needs defence (§5) | No (not sent automatically) |
| Survives reload | Yes | No, needs a refresh mechanism, which usually means a cookie anyway |
| Server revocation | Immediate (delete the session row) | Needs short expiry or a denylist |
| Works with `EventSource` (SSE) | Yes, cookies are sent | No, `EventSource` cannot set headers |
| **Verdict for same-origin SPA** | **Default** | Only when the API is consumed cross-origin or by non-browser clients |

Cookie: `__Host-session=<opaque id>; Path=/; Secure; HttpOnly; SameSite=Strict` (or `Lax` if users
arrive by links that must land signed in). Server-side session store with idle and absolute
timeouts; rotate the id on sign-in and on privilege change; delete it server-side on sign-out.

## 5. CSRF for a cookie-auth SPA

SameSite is defence in depth, not the whole defence. Use two layers:

1. **Fetch Metadata check (server middleware):** reject state-changing requests whose
   `Sec-Fetch-Site` is present and not `same-origin`; also verify `Origin` matches on unsafe methods.
2. **Token or custom header:** a signed double-submit token (HMAC of session id + random, readable
   cookie or a `GET /api/csrf` response) sent back in an `X-CSRF-Token` header on every
   POST/PUT/PATCH/DELETE; the server checks it against the session. A custom header alone forces a
   CORS preflight cross-origin and is acceptable when combined with a strict CORS policy (no
   wildcard, no credentials for foreign origins).

Never make state changes on GET. Details, middleware sketch and the fetch wrapper:
`references/session-csrf-stepup.md`.

## 6. Step-up re-authentication

- The server marks actions that need step-up and answers `428` with a step-up requirement (never
  `401`, which the SPA reserves for "session expired")
  when the session's last user verification is older than the action's `max_age` (for example 5
  minutes) or when the action always requires a fresh assertion.
- `POST /api/stepup/options` with `{kind, id, version}`; the server creates a challenge, stores it
  with that binding under a ceremony id, and returns the id plus options with
  `userVerification: "required"` and the user's `allowCredentials`.
- The client runs `startAuthentication`, then sends `{ceremonyId, assertion}` **with the action
  request**, and refreshes its CSRF token afterwards (the session id rotates).
- The server verifies the assertion, checks the stored binding equals the action being executed,
  checks UV was performed, consumes the challenge, executes the action, and records who, what,
  when, and which credential in the audit log.
- Optional short elevation window (`elevated_until` on the session) only for low-risk batches;
  never for grants or irreversible actions.

The same shape maps to OAuth's step-up challenge (RFC 9470: `acr_values` / `max_age`) when an
external identity provider is in front.

## 7. CSP and Trusted Types for the built bundle

Starting policy for a Vite SPA served by the API (adjust `connect-src` for SSE and API paths):

```text
Content-Security-Policy:
  default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:;
  font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none';
  frame-ancestors 'none'; form-action 'self';
  require-trusted-types-for 'script'; trusted-types app-html dompurify
```

Trusted Types support differs by browser, Vite's inline-script behaviour, React's use of
`innerHTML`, and the report-only rollout: `references/csp-trusted-types.md`.

## Reference files

| File | Read when |
|---|---|
| `references/browser-ceremony.md` | Writing the registration, sign-in, autofill and step-up calls in the SPA |
| `references/server-verification.md` | Implementing the server side (framework-neutral contract, Python `py_webauthn` reference, storage schema) |
| `references/session-csrf-stepup.md` | Cookie session settings, CSRF middleware and client wrapper, step-up flow end to end |
| `references/csp-trusted-types.md` | Writing and rolling out the CSP and Trusted Types policy for the built bundle |

## Anti-Patterns

| Don't | Why | Do instead |
|---|---|---|
| Generate the challenge in the browser | An attacker replays any assertion they captured | Server-generated, single-use, expiring challenge bound to the ceremony |
| Accept any origin or a prefix match | A look-alike or subdomain origin passes | Exact expected origin string(s), exact RP ID |
| Store the session token in `localStorage` | Any XSS exfiltrates it and replays it from anywhere | HttpOnly `__Host-` cookie |
| Rely on SameSite alone for CSRF | Same-site sibling subdomains and older clients bypass it | Fetch Metadata / Origin check plus a CSRF token header |
| Protect approve and grant with the login session only | A hijacked or unattended session approves anything | Action-bound step-up with UV required |
| Use the user's email as the WebAuthn user handle | Leaks PII to authenticators; breaks on email change | Random opaque 32–64 byte handle |
| Treat sign count 0 as a clone | Synced passkeys report 0 forever | Flag only a non-zero counter that does not increase |
| Load the bundle or polyfills from a CDN at runtime | A CDN compromise runs code in the auth origin | Self-host everything; CSP `script-src 'self'` |
| Ship `'unsafe-inline'` because a build step injected an inline script | Re-opens the XSS door the cookie closed | Remove the inline script (configure the bundler) or hash it |
| Let any signed-in session add a passkey | A hijacked session registers the attacker's key, which then passes step-up | Step-up before adding when a credential exists; notify the user on every add |
| Show "approved" when the assertion was sent | The server may reject the binding or UV | Render the server's result |
