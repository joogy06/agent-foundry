# Authentication per tool

The canonical recommendation for a single-developer GCP Workstation. Each tool has its own auth model — there's no one flow that fits everything.

## Decision table

| Tool | On a GCP Workstation | Why |
|---|---|---|
| **Claude Code** | Vertex AI ADC | Metadata server provides ADC; no key file; same region as Vertex; CLAUDE_CODE_USE_VERTEX flag is single switch |
| **Gemini CLI** | Vertex AI ADC | Same metadata server; `GOOGLE_GENAI_USE_VERTEXAI=1` is the single switch |
| **GitHub Copilot CLI** | Device flow with TCP tunnel fallback | OAuth flow needs a browser; `gcloud workstations start-tcp-tunnel` forwards to laptop |
| **Codex CLI** | OpenAI account login | No GCP path; copy-paste a device code from the workstation terminal to your laptop browser |

## Claude Code → Vertex AI ADC

Set on the workstation (via Dockerfile `/etc/skel/.bashrc` or per-user `~/.bashrc`):

```bash
export CLAUDE_CODE_USE_VERTEX=1
export ANTHROPIC_VERTEX_PROJECT_ID=$GOOGLE_CLOUD_PROJECT
export ANTHROPIC_VERTEX_REGION=$GOOGLE_CLOUD_LOCATION   # e.g. us-central1
```

ADC is provided automatically by the metadata server — no `gcloud auth application-default login` needed inside the workstation.

Verify:

```bash
gcloud auth application-default print-access-token   # token from metadata
claude --version
claude -p "say hello" --bare  # bypasses auto-auth, uses ADC via Vertex
```

The runtime service account on the workstation needs `roles/aiplatform.user`.

## Gemini CLI → Vertex AI ADC

```bash
export GOOGLE_GENAI_USE_VERTEXAI=1
export GOOGLE_CLOUD_PROJECT=my-project
export GOOGLE_CLOUD_LOCATION=us-central1
gemini -p "say hello"
```

Same ADC, same metadata server, same service account permission. No key file.

### If the user has an AI Pro / Gemini Advanced subscription instead of Vertex

`gemini-cli` routes based on env vars at invocation time:

- **OAuth subscription (AI Pro / Gemini Advanced)** — default when `~/.gemini/oauth_creds.json` exists with `selectedType: oauth-personal` AND no conflicting env vars are set
- **Cloud AI Companion API** — forced whenever `GOOGLE_CLOUD_PROJECT` is a non-empty string, requires `cloudaicompanion.googleapis.com` enabled on that project
- **`GEMINI_API_KEY` auth** — takes precedence over OAuth when set (non-empty)

On a workstation configured for Vertex ADC, the whole-shell `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` env vars will silently force subscription users onto the Cloud AI Companion path and return 403 if the Companion API isn't enabled. For an AI Pro subscription user on this workstation, override per-invocation:

```bash
GOOGLE_CLOUD_PROJECT= GEMINI_API_KEY= gemini -p "say hello"
```

Or in a multi-call script, `export GOOGLE_CLOUD_PROJECT=` and `export GEMINI_API_KEY=` at the top of the block. This is the same trick the MCP server config uses (`claude mcp add gemini-cli -s user -e GOOGLE_CLOUD_PROJECT= -e GEMINI_API_KEY= ...`). See `~/.claude/skills/gemini-cli/references/auth.md` for the canonical routing note.

## GitHub Copilot CLI → Device flow with TCP tunnel

OAuth device flow opens a browser. On a cloud VM, the browser opens **on the VM** (no display). Two workarounds:

### Option A: TCP tunnel to laptop browser

```bash
# On your laptop
gcloud workstations start-tcp-tunnel my-station \
  --cluster=my-cluster --config=ai-dev-config --region=us-central1 \
  --port=80 --local-host-port=:8080

# In the workstation terminal (via the browser IDE)
copilot login
# Paste the displayed URL into your laptop browser instead of the VM browser
```

### Option B: Pre-issued token (recommended for unattended)

```bash
# On your laptop, generate a fine-grained PAT with "Copilot Requests" permission
# Store in Secret Manager
gcloud secrets create copilot-token --data-file=-  <<< "github_pat_v2_..."

# On the workstation, fetch at use time
export COPILOT_GITHUB_TOKEN=$(gcloud secrets versions access latest --secret=copilot-token)
copilot -p "..." --allow-all-tools
```

The runtime service account needs `roles/secretmanager.secretAccessor` for the secret.

## Codex CLI → OpenAI account login

Codex uses OpenAI's auth (separate from anything in GCP). The login is interactive but works via a copy-paste device code flow:

```bash
codex auth login
# Outputs a URL and device code
# On your laptop, visit the URL, enter the code, approve
# The workstation terminal completes the flow
```

The token is stored in `~/.codex/` (which persists since it's in `$HOME`).

For unattended (CI), use `OPENAI_API_KEY` env var instead:

```bash
export OPENAI_API_KEY=sk-...
codex exec "..."
```

## What to put where

| Where | Contents |
|---|---|
| Service account `roles` | `aiplatform.user`, `secretmanager.secretAccessor`, `artifactregistry.reader` |
| Workstation env vars (`/etc/skel/.bashrc`) | `CLAUDE_CODE_USE_VERTEX=1`, `GOOGLE_GENAI_USE_VERTEXAI=1`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `ANTHROPIC_VERTEX_*` |
| Secret Manager | `copilot-token`, `openai-api-key`, any other long-lived tokens |
| User home | OAuth credentials only after manual login (Codex), Vertex ADC cached by metadata server |

## What NOT to do

| Don't | Why |
|---|---|
| Export tokens via `/etc/profile.d/` | Plaintext on disk, visible to all users |
| Bake key files into the Dockerfile | Audit nightmare; rebuild every rotation |
| Run `gcloud auth login` on the workstation | Browser opens on VM (no display). Use ADC instead, or `--no-launch-browser` for the device flow. |
| Use the `gh auth login` browser flow on the workstation | Same browser issue. Use `GH_TOKEN` env var or device flow. |
| Mix `OPENAI_API_KEY` and `codex auth login` | Pick one. Codex prefers env var if set. |
| Forget to set `ANTHROPIC_VERTEX_REGION` | Defaults to a region that may not have Claude available |
