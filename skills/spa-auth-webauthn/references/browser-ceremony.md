# Browser ceremony

Reference for `spa-auth-webauthn` §2. TypeScript, React-agnostic (wrap in hooks as you like).

## Contents

- 1. Library or native
- 2. Registration
- 3. Sign-in (with passkey autofill)
- 4. Step-up assertion
- 5. Errors and what to tell the user
- 6. Fetch helper (cookie + CSRF)
- 7. Credential management UI

## 1. Library or native

| Approach | Use when |
|---|---|
| `@simplewebauthn/browser` (`startRegistration`, `startAuthentication`) | Default. Handles base64url conversion of options and responses, autofill abort handling, and normalises errors |
| Native `navigator.credentials.create/get` + `PublicKeyCredential.parseCreationOptionsFromJSON` / `parseRequestOptionsFromJSON` + `credential.toJSON()` | Every target browser supports the WebAuthn Level 3 JSON helpers (see FRESHNESS block in SKILL.md) and you want zero dependencies |

The server side does not need to match: any server library accepts the standard JSON shapes.
Pin the browser library exactly (see `modern-frontend` supply-chain reference); it runs in the
auth path.

## 2. Registration

```ts
import { startRegistration } from "@simplewebauthn/browser";
import { api } from "./api";   // §6

export async function registerPasskey(label: string) {
  const optionsJSON = await api.post("/api/auth/passkey/register/options", {});
  let attResp;
  try {
    attResp = await startRegistration({ optionsJSON });
  } catch (err) {
    throw toUserError(err);                    // §5
  }
  return api.post("/api/auth/passkey/register/verify", { response: attResp, label });
}
```

- Registration happens **after** the user is signed in (adding a passkey to an account) or as the
  first step of a passkey-only sign-up flow the server has opened. When the account already has a
  passkey, run step-up (§4, `kind: "passkey.add"`) first; the server refuses the options otherwise.
- The server returns `excludeCredentials` with the user's existing credentials, so registering the
  same authenticator twice fails with `InvalidStateError` instead of creating a duplicate.
- Let the user label the passkey ("Work laptop") and show the list (§7).

## 3. Sign-in (with passkey autofill)

```tsx
import { startAuthentication, browserSupportsWebAuthnAutofill } from "@simplewebauthn/browser";

// Form: <input name="username" autoComplete="username webauthn" />
// Start conditional UI once, on mount of the sign-in page.
useEffect(() => {
  let cancelled = false;
  (async () => {
    if (!(await browserSupportsWebAuthnAutofill())) return;
    const optionsJSON = await api.post("/api/auth/passkey/login/options", {});
    try {
      const asseResp = await startAuthentication({ optionsJSON, useBrowserAutofill: true });
      if (!cancelled) await finishSignIn(asseResp);
    } catch (err) {
      if (!isAbort(err)) reportSignInError(err);
    }
  })();
  return () => { cancelled = true; };   // the library aborts the pending autofill request on the next ceremony
}, []);

// Explicit button: "Sign in with a passkey"
async function onPasskeyButton() {
  const optionsJSON = await api.post("/api/auth/passkey/login/options", {});
  const asseResp = await startAuthentication({ optionsJSON });   // modal; cancels the autofill request
  await finishSignIn(asseResp);
}

async function finishSignIn(response: unknown) {
  await api.post("/api/auth/passkey/login/verify", { response });   // server sets the session cookie
  resetCsrf();                                                       // new session, new CSRF token
  await queryClient.resetQueries();                                 // drop anything cached pre-auth
  navigate(returnTo ?? "/");
}
```

- `autocomplete="username webauthn"` on the username field is required for passkey autofill
  (conditional mediation); the `webauthn` token must be last.
- Only one WebAuthn request can be pending; the library cancels the pending autofill request when
  a modal ceremony starts.
- For usernameless sign-in the server returns empty `allowCredentials`; the authenticator offers
  discoverable credentials and returns the user handle.
- After sign-in the session lives in the cookie; the SPA never sees or stores a token.

## 4. Step-up assertion

```ts
type StepUp = { ceremonyId: string; assertion: unknown };

export async function withStepUp<T>(action: { kind: string; id: string; version: number },
                                    send: (stepUp: StepUp) => Promise<T>): Promise<T> {
  const { ceremonyId, options } = await api.post("/api/stepup/options", action);  // challenge bound to action
  const assertion = await startAuthentication({ optionsJSON: options });          // UV required in options
  try {
    return await send({ ceremonyId, assertion });                               // same request as the action
  } finally {
    resetCsrf();          // the server rotates the session id after step-up; the old token is dead
  }
}

// usage
await withStepUp({ kind: "approval.approve", id: view.id, version: view.version },
  (stepUp) => api.post(`/api/approvals/${view.id}/decision`,
    { decision: "approve", version: view.version, idempotencyKey, stepUp }));
```

- The step-up request is always modal (never autofill) and always for the signed-in user's own
  credentials.
- Do not cache or reuse an assertion; each one answers one server challenge.
- If the action request returns `409` (version changed) the assertion is spent: re-render, let the
  user decide again, and run a new step-up.

## 5. Errors and what to tell the user

| `err.name` | Usual cause | Message / action |
|---|---|---|
| `NotAllowedError` | User cancelled, timed out, or no matching credential on this device | "Sign-in was cancelled or timed out." Offer retry and other devices (hybrid / QR) |
| `InvalidStateError` (create) | Authenticator already registered for this account | "This device already has a passkey for your account." |
| `SecurityError` | RP ID does not match the page's domain, or page not on HTTPS (localhost excepted) | Configuration bug: log it, show a generic error |
| `AbortError` | Another ceremony replaced this one (autofill → modal) | Ignore silently |
| `NotSupportedError` | No supported algorithm or authenticator type | Offer another device or fallback |
| `ConstraintError` | UV or resident key required but not available | Explain that this authenticator cannot be used for this action |

Never reveal whether an account exists from the error shown on the sign-in page.

## 6. Fetch helper (cookie + CSRF)

```ts
let csrf: string | null = null;
export const resetCsrf = () => { csrf = null; };   // call after sign-in, sign-out and step-up

const PRE_AUTH = /^\/api\/auth\/passkey\/login\//;   // no session yet: Fetch Metadata protects these

async function csrfToken(): Promise<string | null> {
  if (!csrf) {
    const res = await fetch("/api/csrf", { credentials: "same-origin" });
    if (!res.ok) return null;                        // signed out: send no header rather than "null"
    csrf = (await res.json()).token;
  }
  return csrf;
}

async function send(path: string, body: unknown): Promise<Response> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = PRE_AUTH.test(path) ? null : await csrfToken();
  if (token) headers["X-CSRF-Token"] = token;
  return fetch(path, { method: "POST", credentials: "same-origin", headers, body: JSON.stringify(body) });
}

export const api = {
  async post(path: string, body: unknown) {
    let res = await send(path, body);
    if (res.status === 403 && res.headers.get("X-CSRF-Failure")) {   // token stale: refetch, retry once
      resetCsrf();
      res = await send(path, body);
    }
    if (!res.ok) throw await ApiError.from(res);
    return res.status === 204 ? null : res.json();
  },
};
```

The CSRF token is bound to the session; refetch it after sign-in, sign-out and session rotation.
With a generated OpenAPI client, put the same header logic in its request interceptor.

## 7. Credential management UI

- List passkeys with label, created, last used, and whether synced (backup state from the server).
- Allow rename and removal; removal requires step-up and must not remove the last sign-in method
  without an explicit recovery path.
- On removal, signal the change to the authenticator where supported (WebAuthn Level 3 signal
  methods; `sendSignal()` in `@simplewebauthn/browser` v14 wraps `signalUnknownCredential`,
  `signalAllAcceptedCredentials` and `signalCurrentUserDetails`). Signals are best effort, fire and
  forget, and not implemented in Firefox (2026-10); feature-detect; they keep the user's passkey picker from offering a credential the server no longer
  accepts, and never replace server-side deletion.
