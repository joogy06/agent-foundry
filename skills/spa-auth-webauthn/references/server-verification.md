# Server verification

Reference for `spa-auth-webauthn` §3. A framework-neutral contract, then a Python reference with
`py_webauthn` (PyPI package `webauthn`) and FastAPI. Other stacks: SimpleWebAuthn server
(TypeScript), webauthn4j / java-webauthn-server (Java), go-webauthn (Go), Fido2NetLib (.NET); the
contract is the same.

## Contents

- 1. Contract (any language)
- 2. Storage schema
- 3. Python reference: registration
- 4. Python reference: authentication and session
- 5. Step-up verification
- 6. Configuration values
- 7. Tests that must exist

## 1. Contract (any language)

| Step | Server must |
|---|---|
| Adding a credential | When the user already has one, require step-up first (it is a privilege change); notify the user out of band on every addition |
| Options | Generate a random challenge (≥16 bytes, CSPRNG), store it server-side with: purpose (`register`, `login`, `stepup`), user (if known), binding (step-up action), expiry (2–5 min) |
| Verify | Load and **delete** the stored challenge (single use, even on failure); verify `clientDataJSON.type`, challenge, origin (exact match against an allowlist), RP ID hash, UP flag, UV flag when required, signature with the stored public key, and on registration the attestation format (accept `none`) |
| Credential lookup (login) | By credential id; the returned `userHandle` must match the credential's owner |
| Counter | If both stored and received counts are 0, accept. If received ≤ stored and either is non-zero, reject (py_webauthn does this) and alert as a possible clone |
| Persist | On registration: credential id, public key, sign count, transports, AAGUID, backup-eligible, backed-up, user handle, label, created-at. On login: new sign count, backed-up flag, last-used-at |
| Session | Rotate the session id on success; store `auth_time`, `uv`, credential id |
| Audit | Log ceremony outcomes (success and failure reason) without logging raw challenges or keys |

## 2. Storage schema

```sql
CREATE TABLE webauthn_credential (
  id               BYTEA PRIMARY KEY,          -- credential id (raw bytes)
  user_id          UUID NOT NULL REFERENCES app_user(id),
  user_handle      BYTEA NOT NULL,             -- random, stable per user, not PII
  public_key       BYTEA NOT NULL,             -- COSE key
  sign_count       BIGINT NOT NULL DEFAULT 0,
  transports       TEXT[] NOT NULL DEFAULT '{}',
  aaguid           UUID,
  backup_eligible  BOOLEAN NOT NULL,
  backed_up        BOOLEAN NOT NULL,
  label            TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_used_at     TIMESTAMPTZ
);

CREATE TABLE webauthn_challenge (
  id          UUID PRIMARY KEY,                -- ceremony id, also kept in the pre-auth session
  challenge   BYTEA NOT NULL,
  purpose     TEXT NOT NULL CHECK (purpose IN ('register','login','stepup')),
  user_id     UUID,
  binding     JSONB,                            -- step-up: {"kind","id","version"}
  expires_at  TIMESTAMPTZ NOT NULL
);
```

Store challenges in the database or a server-side session store, not in a client-readable cookie.

## 3. Python reference: registration

```python
# py_webauthn 3.0.1 API (signatures read from the installed package, 2026-10-26)
from webauthn import (generate_registration_options, verify_registration_response,
                      options_to_json, base64url_to_bytes)
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, ResidentKeyRequirement,
                                      UserVerificationRequirement, PublicKeyCredentialDescriptor,
                                      AuthenticatorTransport)
from webauthn.helpers.exceptions import InvalidAuthenticationResponse
import json
from webauthn.helpers.cose import COSEAlgorithmIdentifier

RP_ID = settings.rp_id                 # e.g. "ops.example" (host, no scheme, no port)
RP_NAME = settings.rp_name
ORIGINS = settings.expected_origins    # e.g. ["https://ops.example"]

@router.post("/auth/passkey/register/options")
def register_options(user=Depends(current_user), db=Depends(db_session)):
    # Adding a passkey is a privilege change: with attestation "none", a hijacked session could
    # register an attacker's key that then passes every later step-up. If the user already has a
    # credential, require a fresh step-up (UV required, binding {"kind": "passkey.add"}) first.
    if user.credentials:
        require_recent_stepup(user, kind="passkey.add", max_age_s=300)
    opts = generate_registration_options(
        rp_id=RP_ID, rp_name=RP_NAME,
        user_id=user.webauthn_user_handle,          # bytes, random, stable
        user_name=user.username, user_display_name=user.display_name,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=c.id) for c in user.credentials],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.PREFERRED),
        supported_pub_key_algs=[COSEAlgorithmIdentifier.EDDSA,
                                COSEAlgorithmIdentifier.ECDSA_SHA_256,
                                COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256],
    )
    store_challenge(db, purpose="register", user_id=user.id, challenge=opts.challenge)
    return Response(options_to_json(opts), media_type="application/json")

@router.post("/auth/passkey/register/verify")
def register_verify(body: RegisterBody, user=Depends(current_user), db=Depends(db_session)):
    challenge = pop_challenge(db, purpose="register", user_id=user.id)   # deletes; raises if absent/expired
    v = verify_registration_response(
        credential=body.response,                  # dict or JSON string from the browser
        expected_challenge=challenge,
        expected_rp_id=RP_ID,
        expected_origin=ORIGINS,
        require_user_verification=False,           # True for admin-only consoles
    )
    db.add(WebauthnCredential(
        id=v.credential_id, user_id=user.id, user_handle=user.webauthn_user_handle,
        public_key=v.credential_public_key, sign_count=v.sign_count,
        transports=body.response.get("response", {}).get("transports", []),
        aaguid=v.aaguid, backup_eligible=v.credential_device_type == "multi_device",
        backed_up=v.credential_backed_up, label=body.label))
    audit(db, user.id, "passkey.registered", credential_id=v.credential_id)
    notify_user_out_of_band(user, "A new passkey was added to your account")   # alert on every add
    return {"ok": True}
```

## 4. Python reference: authentication and session

```python
from webauthn import generate_authentication_options, verify_authentication_response

@router.post("/auth/passkey/login/options")
def login_options(request: Request, db=Depends(db_session)):
    opts = generate_authentication_options(
        rp_id=RP_ID, user_verification=UserVerificationRequirement.PREFERRED)   # no allowCredentials: usernameless
    ceremony_id = store_challenge(db, purpose="login", user_id=None, challenge=opts.challenge)
    resp = Response(options_to_json(opts), media_type="application/json")
    resp.set_cookie("__Host-ceremony", str(ceremony_id), secure=True, httponly=True,
                    samesite="strict", path="/", max_age=300)
    return resp

@router.post("/auth/passkey/login/verify")
def login_verify(body: LoginBody, request: Request, db=Depends(db_session)):
    # pop_* helpers delete the challenge and COMMIT in their own transaction before verifying,
    # so a verification failure cannot roll the deletion back (single use even on failure).
    challenge = pop_challenge_by_id(db, request.cookies.get("__Host-ceremony"), purpose="login")
    cred = db.get(WebauthnCredential, base64url_to_bytes(body.response["rawId"]))
    if cred is None or base64url_to_bytes(body.response["response"]["userHandle"]) != cred.user_handle:
        raise AuthFailed()                               # same error for every failure
    try:
        v = verify_authentication_response(
            credential=body.response, expected_challenge=challenge,
            expected_rp_id=RP_ID, expected_origin=ORIGINS,
            credential_public_key=cred.public_key,
            credential_current_sign_count=cred.sign_count,
            require_user_verification=False)
    except InvalidAuthenticationResponse as exc:
        if "sign count" in str(exc):                     # py_webauthn rejects a non-increasing non-zero counter
            alert_possible_clone(cred, exc)              # log + alert; the sign-in is already refused
        raise AuthFailed() from exc
    cred.sign_count, cred.backed_up, cred.last_used_at = v.new_sign_count, v.credential_backed_up, now()
    session = rotate_session(request, user_id=cred.user_id, auth_time=now(),
                             uv=v.user_verified, credential_id=cred.id)
    resp = JSONResponse({"ok": True})
    set_session_cookie(resp, session.id)                  # see session-csrf-stepup.md
    resp.delete_cookie("__Host-ceremony", path="/", secure=True, httponly=True, samesite="strict")
    # Starlette's delete_cookie defaults to secure=False; browsers ignore a __Host- cookie without Secure
    return resp
```

`py_webauthn` itself rejects a non-zero sign count that did not increase (0/0 is accepted), so
there is no separate counter check to write: catch that case to raise the clone alert.
`py_webauthn` raises on any verification failure; catch its exceptions at the route and return one
generic 401 so the response does not reveal which check failed. Log the specific reason
server-side.

## 5. Step-up verification

```python
@router.post("/stepup/options")
def stepup_options(action: StepUpAction, session=Depends(require_session), db=Depends(db_session)):
    assert_action_allowed(session.user_id, action)       # authorisation first; step-up is not authorisation
    opts = generate_authentication_options(
        rp_id=RP_ID,
        allow_credentials=[PublicKeyCredentialDescriptor(
                               id=c.id, transports=[AuthenticatorTransport(t) for t in c.transports])
                           for c in user_credentials(db, session.user_id)],   # enums, not strings
        user_verification=UserVerificationRequirement.REQUIRED)
    ceremony_id = store_challenge(db, purpose="stepup", user_id=session.user_id,
                                  challenge=opts.challenge, binding=action.model_dump())  # {"kind","id","version"}
    return {"ceremonyId": str(ceremony_id), "options": json.loads(options_to_json(opts))}

def verify_stepup(db, session, ceremony_id, assertion, kind: str, target_id: str, version: int):
    # Pop by ceremony id (committed separately, see above); then compare the stored binding.
    row = pop_challenge_by_id(db, ceremony_id, purpose="stepup", user_id=session.user_id)
    if row.binding != {"kind": kind, "id": target_id, "version": version}:
        raise StepUpFailed()                              # assertion was for a different action
    cred = owned_credential(db, session.user_id, assertion["rawId"])
    v = verify_authentication_response(
        credential=assertion, expected_challenge=row.challenge,
        expected_rp_id=RP_ID, expected_origin=ORIGINS,
        credential_public_key=cred.public_key,
        credential_current_sign_count=cred.sign_count,
        require_user_verification=True)
    cred.sign_count, cred.last_used_at = v.new_sign_count, now()
    session.last_uv_at = now()
    return cred.id                                        # record in the action's audit entry
```

`require_user_verification` defaults to `False` in `py_webauthn`: the server must pass `True` for
step-up. Setting `userVerification: "required"` in the options alone enforces nothing.

Call `verify_stepup` inside the action handler, in the same transaction that performs the action,
after re-checking authorisation and the target's current version.

## 6. Configuration values

| Setting | Value |
|---|---|
| RP ID | The host the users see, or a registrable parent domain if several subdomains share passkeys. Cannot be changed later without re-registering every passkey; choose deliberately |
| Expected origins | Exact list, scheme + host + port (`https://ops.example`, `https://ops.example:8443`). `http://localhost:<port>` only in development configuration |
| Challenge expiry | 2–5 minutes |
| Timeout in options | 60–300 s (a hint to the browser; the server expiry is what counts) |
| Algorithms | EdDSA, ES256, RS256 (RS256 for older Windows Hello) |
| Attestation | `none` unless you have a policy that needs authenticator model attestation |

LAN-only or VPN-only deployments still need a secure context: HTTPS with a certificate the
browsers trust (an internal CA installed on clients, or a public certificate for an internal DNS
name). WebAuthn does not work over plain `http://` except on `localhost`.

## 7. Tests that must exist

- Replay: the same assertion posted twice fails the second time (challenge consumed).
- Wrong origin and wrong RP ID fail.
- Expired challenge fails.
- Step-up: an assertion bound to approval A cannot execute approval B, nor approval A at a newer
  version.
- Step-up with UV not performed fails.
- Counter: 0/0 accepted; a non-increasing non-zero counter is refused and raises the clone alert.
- Adding a passkey when one exists requires step-up; every add notifies the user.
- Step-up options for a credential with stored transports serialise (transports are enums).
- Session id changes after sign-in.
