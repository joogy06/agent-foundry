---
name: gcp-workstations
description: Use when provisioning, configuring, or operating Google Cloud Workstations as a single-developer AI/dev environment with Claude Code, Gemini CLI, GitHub Copilot CLI, and supporting tooling. Covers cluster/config/workstation lifecycle, custom images, persistent home semantics, per-tool authentication strategies, networking, cost optimization, and security gotchas.
---

# GCP Workstations for AI Dev

Single-developer Google Cloud Workstations playbook. Provisions a workstation that runs Claude Code 2.1, Gemini CLI 0.36, GitHub Copilot CLI 1.0, and supporting tooling, with sensible auth and cost defaults.

This is **not** a multi-tenant guide. Single-dev assumptions apply throughout.

## When to use

- Spinning up a new GCP Workstation for AI-assisted development
- Authoring or updating the custom image with the AI CLI stack
- Picking the right auth flow per tool on a cloud VM
- Estimating monthly cost (or comparing against alternatives)
- Diagnosing persistence, networking, or credential-store issues

## Versions and assumptions

| Component | Version targeted |
|---|---|
| Google Cloud Workstations | API v1 (April 2026) |
| Base image | `us-central1-docker.pkg.dev/cloud-workstations-images/predefined/code-oss:latest` |
| Node.js | 22 LTS (for the AI CLIs) |
| Claude Code | 2.1.x via `@anthropic-ai/claude-code` |
| Gemini CLI | 0.36.x via `@google/gemini-cli` |
| GitHub Copilot CLI | 1.0.x via `@github/copilot` |

## Quick task index

| Task | Read |
|---|---|
| Provision a new cluster/config/workstation | `references/provision.md` |
| Build the custom Dockerfile (AI CLIs preinstalled) | `references/custom-image.md` + `scripts/Dockerfile.ai-dev` |
| Push image to Artifact Registry | `references/custom-image.md` (Push section) |
| Pick auth per tool (Claude / Gemini / Copilot) | `references/auth-per-tool.md` |
| Understand `$HOME` vs `/var`/`/tmp` persistence | `references/persistent-home.md` |
| Manage secrets (Secret Manager + use-time fetch) | `references/secrets-and-security.md` |
| Configure networking (public/private, IAP, egress) | `references/networking.md` |
| Estimate cost and pick the right tier | `references/cost-optimization.md` |
| Common gotchas (libsecret, clock drift, OAuth) | `references/gotchas-and-fixes.md` |
| Run the lifecycle from end to end | `scripts/create-workstation.sh` |
| Workstation startup hook with use-time secret fetch | `assets/startup-script.sh` |

## Lifecycle in three commands

```bash
# 1. Cluster (one per project, region)
gcloud workstations clusters create my-cluster \
  --region=us-central1 \
  --network=projects/$PROJECT/global/networks/default \
  --subnetwork=projects/$PROJECT/regions/us-central1/subnetworks/default

# 2. Config (one per machine type / image / persistent disk shape)
gcloud workstations configs create ai-dev-config \
  --cluster=my-cluster \
  --region=us-central1 \
  --machine-type=e2-standard-4 \
  --container-custom-image=us-central1-docker.pkg.dev/$PROJECT/ai-dev/ai-dev:latest \
  --pd-disk-type=pd-ssd \
  --pd-disk-size=200 \
  --idle-timeout=1800s \
  --running-timeout=43200s

# 3. Workstation
gcloud workstations create my-station \
  --cluster=my-cluster \
  --config=ai-dev-config \
  --region=us-central1
```

`scripts/create-workstation.sh` runs this end-to-end with idempotency and error handling.

## Persistence summary

| Path | Persists across stop/start? | Persists across delete-workstation? |
|---|---|---|
| `$HOME` (e.g. `/home/user`) | YES | YES (the persistent disk is decoupled from the workstation lifecycle) |
| `/var`, `/tmp`, `/etc`, `/usr` | NO | NO |
| Hidden caches outside `$HOME` (e.g. `/root/.cache`) | NO | NO |

This means:

- `~/.claude/`, `~/.gemini/`, `~/.copilot/`, `~/.config/gh/`, `~/.npm/`, `~/.cargo/`, `~/.npm-global/` all persist
- Anything you `apt install` is gone after restart unless it's baked into the image
- Build a custom image (`scripts/Dockerfile.ai-dev`) for everything that should survive

## Auth per tool — one-line summary

| Tool | Recommended on GCP Workstation | Why |
|---|---|---|
| Claude Code | Vertex AI ADC (`CLAUDE_CODE_USE_VERTEX=1`) | Metadata server provides ADC; no key file; same region as Vertex |
| Gemini CLI | Vertex AI ADC | Same. Set `GOOGLE_GENAI_USE_VERTEXAI=1`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` |
| GitHub Copilot CLI | Device flow with TCP tunnel fallback | OAuth opens a browser; use `gcloud workstations start-tcp-tunnel` to forward localhost to your laptop |
| Codex CLI | OpenAI account login | No GCP integration; works on cloud VM with copy-paste device code |

See `references/auth-per-tool.md` for the full table and exact commands.

## Cost realistic numbers

- ~$144/mo fixed cluster fee (you pay this even with no workstations running, per cluster)
- ~$30/mo compute for an `e2-standard-4` running ~6 h/day on a 1800s idle timeout
- ~$20/mo for the 200 GB pd-ssd persistent disk
- **Total realistic for daily-use single dev: $170-280/mo**

Cheaper alternative: a non-spot GCE VM with a manually built custom image. ~50% cheaper but no managed image lifecycle, no built-in IDE-in-browser, no auto-stop.

**Spot VMs are NOT recommended** for persistent dev — interruptions kill long-running operations and `$HOME` is on a separate disk regardless.

See `references/cost-optimization.md` for detail.

## Anti-patterns

| Don't | Why |
|---|---|
| Run `apt install` and expect it to persist | `/usr` does not survive restart. Bake into the custom image. |
| Export secrets via `/etc/profile.d/` | Plaintext on disk + visible to all users. Use Secret Manager + use-time fetch. See `references/secrets-and-security.md`. |
| Use spot VMs for persistent dev | Interruptions kill in-flight operations. Use regular workstations. |
| Skip `libsecret-1-0` in the Dockerfile | Without it, CLI credential stores fail and tokens go to plaintext fallbacks |
| Skip `chrony` in the Dockerfile | Clock drift causes OAuth 401s and TLS handshake failures |
| Forget the `--network` flag on cluster creation | Default cluster has no inbound; you'll need to recreate. |
| Mix multiple users on one workstation | Single-dev assumption holds throughout this skill. Multi-user is out of scope. |
| Use the legacy `code-oss` image without updating | Pin to `:latest` is fine for personal dev; lock to a digest for reproducibility. |
| Run `gcloud auth login` on the workstation expecting browser to open on your laptop | The browser opens on the VM (no display). Use `gcloud auth application-default login --no-launch-browser` and copy the URL. |
| Embed the SA key file in the image | Key files in images are an audit nightmare. Use ADC via metadata server. |

## See also

- `references/provision.md` — exact gcloud commands
- `references/custom-image.md` — Dockerfile, build, push
- `references/auth-per-tool.md` — canonical auth recommendation
- `references/persistent-home.md` — what survives restarts
- `references/secrets-and-security.md` — Secret Manager pattern, anti-patterns
- `references/networking.md` — public/private, IAP, egress allow list
- `references/cost-optimization.md` — pricing breakdown, alternatives
- `references/gotchas-and-fixes.md` — libsecret, clock drift, browser OAuth, marketplace
- `scripts/Dockerfile.ai-dev` — the actual Dockerfile (ready to `docker build`)
- `scripts/create-workstation.sh` — idempotent lifecycle script
- `assets/startup-script.sh` — workstation startup template with use-time secret fetch
- `claude-code-cli`, `gemini-cli`, `gh-copilot-cli` — per-tool docs
- `docker-fundamentals`, `docker-security` — for Dockerfile review and hardening
- `ubuntu-server-admin` — for OS-level tuning if you switch from code-oss to a base image
