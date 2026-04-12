# Authentication in Gemini CLI

Gemini CLI 0.36.0 supports four authentication flows. Pick the right one for the environment.

## The four flows

| Flow | When to use | Setup |
|---|---|---|
| **OAuth personal** (default) | Local dev with a personal Google account | `gemini auth login` (interactive browser) |
| **`GEMINI_API_KEY`** | Quick CLI use, no Google account, AI Studio key | `export GEMINI_API_KEY=...` |
| **Vertex AI via ADC** | GCP-based deployments, enterprise auth | Set env vars + `gcloud auth application-default login` |
| **Service account JSON** | Server / CI / GCP Workstations | `export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json` |

## Decision table

| Environment | Recommended | Why |
|---|---|---|
| Personal laptop, single-user | OAuth personal | Simplest, no config |
| Personal laptop, no Google account | `GEMINI_API_KEY` | Bypass OAuth |
| GCP Workstation | Vertex via ADC | Metadata server provides ADC automatically — no key file |
| GCE VM, single project | Vertex via ADC | Same as above |
| GitHub Actions / CI | Service account JSON | No interactive browser available |
| Cross-tool dev with Claude Code on Vertex | Vertex via ADC | Both Claude and Gemini share the same ADC |
| Cross-tool dev with Claude Code on Bedrock | OAuth personal or `GEMINI_API_KEY` | Bedrock is AWS, ADC is GCP — pick per-tool |

## OAuth personal (default)

```bash
gemini auth login
# opens browser, you sign in with Google
gemini auth status
```

The credentials live in `~/.config/gemini-cli/` (or similar — exact path is **UNVERIFIED** locally; flagged for first-boot).

### Logout

```bash
gemini auth logout
```

(The exact `auth` subcommand surface is research-grade — verify with `gemini auth --help`.)

## API key (AI Studio)

```bash
export GEMINI_API_KEY=AIza...
gemini -p "test"
```

The key comes from <https://aistudio.google.com/app/apikey>. This is the simplest flow but does not unlock Vertex-only features.

## Vertex AI via Application Default Credentials

```bash
# 1. Tell Gemini to use Vertex
export GOOGLE_GENAI_USE_VERTEXAI=1

# 2. Tell Gemini which project and location
export GOOGLE_CLOUD_PROJECT=my-project
export GOOGLE_CLOUD_LOCATION=us-central1

# 3. Authenticate via ADC
gcloud auth application-default login

# 4. Use it
gemini -p "test"
```

On GCP Workstations and GCE VMs, the metadata server provides ADC automatically — `gcloud auth application-default login` is unnecessary. Just set the env vars and Gemini picks up the metadata identity.

### Verify

```bash
gcloud auth application-default print-access-token   # shows the ADC token
gcloud config get-value project                      # shows the active project
gemini -p "test"                                     # actual API call
```

If the project doesn't match `GOOGLE_CLOUD_PROJECT`, Gemini may pick the wrong one. Set both.

## Service account JSON

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/secrets/gemini-sa.json
gemini -p "test"
```

The service account needs (at minimum):

- `roles/aiplatform.user` — to call the Vertex Gemini API
- `roles/aiplatform.modelUser` — for model access

Use this for CI/CD pipelines, automated jobs, and any non-interactive environment. **Do not** ship key files in container images — fetch at runtime via Secret Manager.

## Cross-tool auth alignment

| Tool | This machine default | GCP Workstation recommendation |
|---|---|---|
| Claude Code | OAuth | `CLAUDE_CODE_USE_VERTEX=1` + ADC |
| Gemini CLI | OAuth personal | Vertex via ADC (env vars + metadata) |
| Codex CLI | OpenAI account | OpenAI account (no GCP path) |
| GitHub Copilot CLI | Device flow (UNVERIFIED) | Device flow with `gcloud workstations start-tcp-tunnel` |

See `gcp-workstations/references/auth-per-tool.md` for the canonical recommendation when running everything on a GCP Workstation.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Could not load default credentials` | ADC not configured | `gcloud auth application-default login` |
| `quota exceeded for project X` but you set project Y | Wrong project picked | Both `GOOGLE_CLOUD_PROJECT` and `gcloud config set project` must match |
| Gemini uses Vertex when you expected AI Studio | `GOOGLE_GENAI_USE_VERTEXAI=1` is set somewhere | `unset GOOGLE_GENAI_USE_VERTEXAI` |
| `Permission denied` on the SA key | wrong roles | `roles/aiplatform.user` minimum |
| `connection reset` from CLI | clock drift on the VM | `chronyc tracking; chronyc sources` then sync |
| OAuth browser opens in cloud VM where there's no display | Only happens with `gemini auth login` on GCP Workstations | Use Vertex ADC instead, or `gcloud workstations start-tcp-tunnel` to forward localhost |

## Anti-patterns

| Don't | Why |
|---|---|
| Hard-code `GEMINI_API_KEY` in scripts | Use env vars or Secret Manager. Never commit. |
| Mix Vertex env vars with `GEMINI_API_KEY` | Conflicting auth — Vertex takes precedence with `GOOGLE_GENAI_USE_VERTEXAI=1` set, otherwise the key |
| Export secrets via `/etc/profile.d/` | Visible to all users on the box. Use-time fetch only — see `gcp-workstations/references/secrets-and-security.md` |
| Ship SA key files in container images | Pull from Secret Manager at startup |
| Skip `gemini auth status` after setup | Confirms which identity Gemini sees |
