# Session, CSRF and step-up

Reference for `spa-auth-webauthn` §4–§6. Python (FastAPI / Starlette) sketches; the rules are
framework-neutral.

## Contents

- 1. Session cookie settings
- 2. Server-side session store
- 3. CSRF: Fetch Metadata + Origin check
- 4. CSRF: signed token in a header
- 5. Client wrapper
- 6. Step-up end to end
- 7. Sign-out and revocation
- 8. Checklist

## 1. Session cookie settings

| Attribute | Value | Why |
|---|---|---|
| Name | `__Host-session` | The `__Host-` prefix forces `Secure`, `Path=/` and no `Domain`, so a sibling subdomain cannot set or shadow it |
| Value | Opaque random id (≥128 bits), never a JWT with claims the client could read | The session is server state; the cookie is only a handle |
| `HttpOnly` | Yes | Script cannot read it |
| `Secure` | Yes | HTTPS only (required by the prefix) |
| `SameSite` | `Strict` for an internal console; `Lax` if users must land signed in from links in mail or chat | Cross-site requests do not carry it |
| `Max-Age` | Omit for a browser-session cookie, or match the absolute timeout | Server timeouts are authoritative either way |

```python
def set_session_cookie(resp, session_id: str):
    resp.set_cookie("__Host-session", session_id, secure=True, httponly=True,
                    samesite="strict", path="/")          # no domain=
```

## 2. Server-side session store

- Table or key-value store: `id`, `user_id`, `created_at`, `last_seen_at`, `auth_time`,
  `last_uv_at`, `credential_id`, `elevated_until` (optional), `ip`, `user_agent` (for display in a
  "your sessions" page, not for binding).
- **Idle timeout** (e.g. 30 minutes for an admin console) and **absolute timeout** (e.g. 12 hours).
- **Rotate the id** on sign-in, on step-up elevation, and on any privilege change; delete the old
  row.
- Store sessions where they can be revoked immediately (database, Redis); signed-cookie sessions
  without server state cannot be revoked before expiry.

## 3. CSRF: Fetch Metadata + Origin check

```python
SAFE = {"GET", "HEAD", "OPTIONS"}

@app.middleware("http")
async def csrf_fetch_metadata(request, call_next):
    if request.method not in SAFE:
        site = request.headers.get("sec-fetch-site")
        if site is not None and site != "same-origin":    # fetch/XHR from the SPA is always same-origin
            return JSONResponse({"detail": "cross-site request blocked"}, status_code=403)
        origin = request.headers.get("origin")
        if origin is not None and origin not in settings.expected_origins:
            return JSONResponse({"detail": "bad origin"}, status_code=403)
    return await call_next(request)
```

- `Sec-Fetch-Site` is sent by all current major browsers; when it is absent (old clients, some
  tools) fall through to the token check (§4) rather than allowing.
- `"none"` (a user-initiated navigation such as a typed URL) is rejected on unsafe methods too: the
  SPA's own `fetch` calls are always `same-origin`, so nothing legitimate is lost.
- Keep GET, HEAD and OPTIONS free of side effects, always.

## 4. CSRF: signed token in a header

```python
import hmac, hashlib, secrets

def make_csrf(session_id: str) -> str:
    nonce = secrets.token_urlsafe(16)
    mac = hmac.new(settings.csrf_key, f"{session_id}.{nonce}".encode(), hashlib.sha256).hexdigest()
    return f"{nonce}.{mac}"

def check_csrf(session_id: str, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    nonce, mac = token.split(".", 1)
    good = hmac.new(settings.csrf_key, f"{session_id}.{nonce}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(mac, good)

@router.get("/csrf")
def csrf(session=Depends(require_session)):
    return {"token": make_csrf(session.id)}
```

- Check it in a dependency or middleware on every unsafe method, after the session is resolved;
  answer `403` with a marker header (`X-CSRF-Failure: 1`) so the client can refresh the token once.
- The token is bound to the session id, so it changes when the session rotates.
- This is the HMAC-signed variant of the token pattern in the OWASP CSRF Prevention Cheat Sheet;
  a per-session synchronizer token stored server-side is equally good.
- The pre-auth sign-in endpoints (`/auth/passkey/login/*`) have no session yet: rely on §3 there,
  and on the ceremony cookie being `SameSite=Strict`.

## 5. Client wrapper

See `browser-ceremony.md` §6 for the `fetch` wrapper that sends `credentials: "same-origin"` and the
`X-CSRF-Token` header, and refreshes the token once on a CSRF failure. With a generated OpenAPI
client, add the header in its request interceptor. `EventSource` GET streams need no CSRF token
(they must not change state).

## 6. Step-up end to end

```text
1. UI: operator clicks "Approve…" on approval A (version 7)
2. UI -> POST /api/stepup/options {kind:"approval.approve", id:"A", version:7}
3. API: authorise (may this user approve A at all?) -> challenge stored with binding, UV required;
   returns {ceremonyId, options}
4. UI: startAuthentication(options) -> user verifies (biometric / PIN)
5. UI -> POST /api/approvals/A/decision {decision, version:7, idempotencyKey, stepUp:{ceremonyId, assertion}}
6. API, one transaction:
     re-authorise; load A FOR UPDATE; check A.version == 7 and state == pending and not expired
     verify_stepup(ceremonyId, binding = {approval.approve, A, 7}, UV required) -> credential id
     (the challenge row was deleted and committed before verification: single use even on failure)
     apply decision; write audit {user, action, target, version, credential id, time, outcome}
7. API -> 200 {state:"approved"} | 409 {current} | 410 expired | 403 {code:"stepup_failed"}
   (401 is reserved for "session expired, sign in again", so the UI can tell the two apart)
```

- A step-up is **not authorisation**: step 3 and step 6 both check that the user may perform the
  action.
- When the action is asynchronous (a grant issued by another service), step 6 records the
  decision and returns `202 {state:"approving"}`; the UI follows the state by push or polling.
- `max_age` alternative: for a set of low-risk actions, accept the session's `last_uv_at` if it is
  younger than N minutes instead of a fresh assertion each time; never for grants, revocations or
  irreversible actions.
- With an external OAuth/OIDC provider in front, the equivalent signal is the step-up challenge
  in RFC 9470 (`insufficient_user_authentication` with `acr_values` / `max_age`); the action
  binding then has to be carried by your own API, because the provider does not know about it.

## 7. Sign-out and revocation

- Sign-out: delete the server session row, then expire the cookie
  (`Set-Cookie: __Host-session=; Max-Age=0; Path=/; Secure; HttpOnly; SameSite=Strict`), then
  close the SSE stream and clear the client query cache.
- "Sign out other sessions" and passkey removal both delete session rows for that user (except the
  current one) and require step-up.
- On session expiry, the API answers `401` with a body the SPA recognises; the SPA keeps the
  current URL as the return target and shows the sign-in screen.

## 8. Checklist

- [ ] `__Host-` cookie with `HttpOnly`, `Secure`, `SameSite`, `Path=/`, no `Domain`
- [ ] Server-side sessions with idle and absolute timeouts; id rotated on sign-in and privilege change
- [ ] Fetch Metadata / Origin check on unsafe methods
- [ ] CSRF token header on unsafe methods, bound to the session
- [ ] No state change on GET
- [ ] Step-up bound to action id + version, UV required, verified in the action's transaction
- [ ] Audit entry per sensitive action with the credential id used
- [ ] Sign-out deletes the server session
