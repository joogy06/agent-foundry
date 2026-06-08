# Custom Image

The flagship artifact of this skill is `scripts/Dockerfile.ai-dev` — a Dockerfile that bakes Node 22 LTS, the three AI CLIs, supporting tooling, `libsecret-1-0`, and `chrony` into a workstation image.

## Why a custom image

GCP Workstations uses Docker images as the OS layer. The default `code-oss:latest` image gives you VS Code in the browser but **nothing else**. Every `apt install` is lost on restart.

For an AI dev workstation, you want:

- Node.js 22 LTS (for the npm-based AI CLIs)
- `@anthropic-ai/claude-code`, `@github/copilot` preinstalled (npm); Antigravity CLI (agy) too — TODO(agy): confirm agy install method on the image (agy is NOT an npm package; it ships as the `agy` binary at `~/.local/bin/agy`)
- `gh` CLI for GitHub access
- `git` (already in code-oss but pin a recent version)
- `libsecret-1-0` so credential stores work
- `chrony` so clocks don't drift (causes OAuth 401s)
- `python3`, `pipx` for Python tooling
- `docker` (Docker-in-Docker if you build images on the workstation) — optional
- A non-root user mapped to `$HOME`

All baked once, reused on every restart.

## Dockerfile (see `scripts/Dockerfile.ai-dev`)

The Dockerfile uses the `code-oss:latest` base from the public Cloud Workstations image registry, then layers on the tooling.

Key principles:

1. **Base = `code-oss:latest`** so the browser IDE works out of the box
2. **Pin Node 22 LTS** via NodeSource APT repo
3. **Install AI CLIs globally** via `npm install -g`
4. **Install `libsecret-1-0` and `chrony`** (the two #1 gotchas)
5. **Set up `chrony` to start at boot**
6. **Add a non-root user** that owns `/home/user`
7. **Inject `/etc/skel/.bashrc` additions** for ADC env vars

## Build

```bash
PROJECT=my-gcp-project
REGION=us-central1
REGISTRY=$REGION-docker.pkg.dev/$PROJECT/ai-dev
IMAGE=$REGISTRY/ai-dev:latest

docker build -t $IMAGE -f scripts/Dockerfile.ai-dev .
```

Build takes ~5-10 minutes the first time, ~1 minute on incremental rebuilds (layer cache).

## Push to Artifact Registry

```bash
# 1. Create the registry (one-time)
gcloud artifacts repositories create ai-dev \
  --repository-format=docker \
  --location=$REGION \
  --project=$PROJECT

# 2. Authenticate Docker to GCR
gcloud auth configure-docker $REGION-docker.pkg.dev

# 3. Push
docker push $IMAGE
```

## Use in the config

```bash
gcloud workstations configs create ai-dev-config \
  --container-custom-image=$IMAGE \
  ...
```

Workstations pulls the image on next start. To force a refresh:

```bash
# Bump the tag
docker tag $IMAGE $REGISTRY/ai-dev:v2
docker push $REGISTRY/ai-dev:v2
gcloud workstations configs update ai-dev-config \
  --container-custom-image=$REGISTRY/ai-dev:v2 \
  --cluster=... --region=...
```

For reproducibility, lock to a digest instead of `:latest`:

```bash
# After push, get the digest
DIGEST=$(gcloud artifacts docker images list $REGISTRY/ai-dev --format='value(version)' | head -1)
gcloud workstations configs update ai-dev-config \
  --container-custom-image=$REGISTRY/ai-dev@$DIGEST \
  --cluster=... --region=...
```

## Image layer guidance

| Layer | What goes here | Why |
|---|---|---|
| Base | `code-oss:latest` | Don't reinvent VS Code-in-browser |
| OS packages | `libsecret-1-0`, `chrony`, `gh`, `python3`, `pipx`, `git`, `curl`, `jq`, `unzip`, `vim`, `tmux` | Things that change rarely; update the base periodically |
| Node | Node 22 LTS via NodeSource | Pinned LTS, separate layer for cache |
| AI CLIs | `@anthropic-ai/claude-code`, `@github/copilot` (npm) + Antigravity CLI (agy) | The point of the image; bumps a few times per month. TODO(agy): confirm agy install method (binary, not npm) |
| Python | `pipx install ...` for tools you want isolated | After Node so partial rebuilds skip Node |
| User setup | Non-root user, default shell, dotfile skeleton | Last layer — most likely to change |

Order matters for cache reuse. Put slow-changing layers first.

## Verification

```bash
docker run --rm $IMAGE bash -c '
  claude --version &&
  agy --version &&
  copilot --version &&
  gh --version &&
  node --version &&
  python3 --version &&
  test -f /usr/lib/x86_64-linux-gnu/libsecret-1.so.0 && echo libsecret OK &&
  command -v chronyd && echo chrony OK
'
```

All commands should succeed before pushing the image.

## Anti-patterns

| Don't | Why |
|---|---|
| Skip the dockerfile and `apt install` on the workstation | Lost on restart |
| Use `latest` everything in the Dockerfile | Reproducibility nightmare; pin major versions at minimum |
| Bake auth tokens into the image | Use Secret Manager + use-time fetch |
| Use `RUN apt-get update && apt-get install -y X && Y && Z` in one giant layer | Cache busts on every change. Split logical groups. |
| Skip `--no-install-recommends` on apt | Bloats the image with optional packages |
| Forget to remove `/var/lib/apt/lists/*` after `apt install` | Adds tens of MB to image size |
| Skip the `USER` directive | Image runs as root by default; workstations expect a regular user |
