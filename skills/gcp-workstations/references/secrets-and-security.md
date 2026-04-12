# Secrets and Security

The single most important rule on a cloud workstation: **fetch secrets at use-time, never bake into images or export at boot**.

## The anti-pattern: `/etc/profile.d/` secret export

```bash
# DO NOT DO THIS
sudo tee /etc/profile.d/secrets.sh <<'EOF'
export GITHUB_TOKEN=ghp_xxxx
export OPENAI_API_KEY=sk-xxxx
export STRIPE_SECRET_KEY=sk_live_xxxx
EOF
```

Why this is wrong:

1. **Plaintext on disk** — anyone with read access to `/etc/profile.d/` sees the secrets
2. **Visible in env** — `env`, `ps eww`, `/proc/<pid>/environ` expose them
3. **Persists in shell history** — copy-paste workflows leak them
4. **Survives across users** — if multi-user (out of scope here), all users get them
5. **Survives across processes** — every child process inherits the env, including ones that should be air-gapped

`/etc` doesn't even persist on a GCP Workstation, but `apt install`-ing your way around that and committing to a custom image makes it worse.

## The right pattern: Secret Manager + use-time fetch

Store secrets in GCP Secret Manager:

```bash
# One-time, per secret, on your laptop
echo -n "github_pat_v2_xxxxxxxxxxxxx" \
  | gcloud secrets create copilot-token --data-file=-

echo -n "sk-proj-xxxxxxxxxxxxx" \
  | gcloud secrets create openai-api-key --data-file=-

echo -n "sk_live_xxxxxxxxxxxxx" \
  | gcloud secrets create stripe-secret-key --data-file=-
```

Fetch at use time (in the workstation):

```bash
# Helper function — put in ~/.bashrc on the workstation
secret() {
  gcloud secrets versions access latest --secret="$1" 2>/dev/null
}

# Use it just-in-time
COPILOT_GITHUB_TOKEN=$(secret copilot-token) copilot -p "..." --allow-all-tools
OPENAI_API_KEY=$(secret openai-api-key) codex exec "..."
STRIPE_SECRET_KEY=$(secret stripe-secret-key) ./scripts/charge-test.sh
```

The token lives in the env of one specific child process and is gone when the process exits. It never touches disk and never goes into shell history (the assignment happens before the command).

## Required IAM

The workstation runtime service account needs:

```bash
gcloud secrets add-iam-policy-binding copilot-token \
  --member="serviceAccount:workstation-runtime@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

Per-secret. Not blanket.

## Versions and rotation

```bash
# Rotate
echo -n "new-token" | gcloud secrets versions add copilot-token --data-file=-

# Old version is still accessible if you specify it
gcloud secrets versions access 1 --secret=copilot-token

# Disable old versions
gcloud secrets versions disable 1 --secret=copilot-token
```

`secret_name` always gives `latest` enabled version. Rotation is transparent to the workstation.

## Audit

```bash
# Who accessed what
gcloud logging read \
  'protoPayload.serviceName="secretmanager.googleapis.com"
   AND protoPayload.methodName="google.cloud.secretmanager.v1.SecretManagerService.AccessSecretVersion"' \
  --limit=20 --format=json
```

Every access is logged. If you see a fetch you didn't do, rotate immediately.

## What about `~/.copilot/credentials` and friends?

OAuth tokens stored by `copilot login`, `gh auth login`, `claude auth login`, etc. live in `$HOME/.<tool>/`. They persist (good) but they're plaintext if the system credential store fails.

Mitigation:
1. Install `libsecret-1-0` in the Dockerfile so credential stores work (Linux Secret Service / gnome-keyring)
2. For tools that don't use the credential store, prefer env-var auth (Secret Manager → env var → tool)

## OAuth tokens vs API keys

| Token type | Lifespan | Revocable? | Best for |
|---|---|---|---|
| OAuth access token (Claude, Gemini, gh) | Hours | Yes | Interactive use |
| OAuth refresh token | Days-months | Yes | `~/.tool/` storage with credential store |
| Fine-grained PAT (GitHub) | Weeks-months | Yes | Headless / CI |
| Service account JSON key | Years | Yes (rotate via IAM) | Server-to-server |
| API key (OpenAI, GEMINI_API_KEY) | Indefinite | Yes (revoke in console) | Quick use, prefer scoped |

Prefer revocable, short-lived tokens over long-lived API keys where possible.

## Network security

| Concern | Mitigation |
|---|---|
| Egress to malicious URLs | Configure allow-list at workstation level. See `references/networking.md`. |
| Inbound SSH | Disable. Use IAP for tunneling instead. |
| Public IP exposure | Use private cluster (`--enable-private-endpoint`). |
| Outdated TLS | The base image bundles current OpenSSL; refresh image quarterly. |

## Anti-patterns

| Don't | Why |
|---|---|
| Export secrets via `/etc/profile.d/` | See top of this file |
| Bake API keys into Dockerfile | Visible in image layers, audit nightmare |
| `ENV API_KEY=...` in Dockerfile | Same as above |
| Commit `.env` files with real values | History rewrite + revoke |
| Use `gcloud secrets versions access` in shell history | Use a function so the call is one shell-history entry, not the value |
| Skip `roles/secretmanager.secretAccessor` (use admin instead) | Least privilege; admin can delete secrets |
| Run `chmod 644 ~/.copilot/*` | Default `600` is correct; widening exposes tokens |
| Send secrets to logs | Use `--secret-env-vars=NAME` on Copilot, scrub manually elsewhere |
| Grant the workstation SA `roles/secretmanager.admin` | Read-only is enough |
