# Gotchas and Fixes

Real issues that bite when running an AI dev environment on a GCP Workstation. Each item lists symptom, cause, and fix.

## #1: `libsecret-1-0` missing → CLI credential stores fail

**Symptom**: `copilot login` succeeds but tokens land in plaintext at `~/.copilot/<file>`. `gh auth login` complains about no credential store. Subsequent restarts may lose tokens.

**Cause**: The Linux Secret Service API requires `libsecret-1-0`. The default `code-oss:latest` base image does not include it.

**Fix**: Bake into the Dockerfile.

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsecret-1-0 \
 && rm -rf /var/lib/apt/lists/*
```

Then rebuild and push the image. After restart, credential stores work and tokens land in the system keyring.

For tools that need an actual gnome-keyring daemon running (not just the lib): also install `gnome-keyring` and ensure it's started. Most CLIs are happy with just the lib.

## #2: Clock drift → OAuth 401s, TLS handshake failures

**Symptom**: Random 401 errors from Google APIs, `x509: certificate signed by unknown authority`, JWT validation failures. Tools work for a while then start failing.

**Cause**: VM clocks drift if NTP isn't running. JWT and TLS both have a small window of tolerance (usually 5 min). Drift past that and everything breaks.

**Fix**: Install and start `chrony`:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends chrony \
 && rm -rf /var/lib/apt/lists/*

# Optional: replace default config to use Google's NTP
RUN echo 'pool metadata.google.internal iburst' > /etc/chrony/chrony.conf

# chrony usually starts via systemd. If your image doesn't run systemd, start it manually:
COPY scripts/start-chrony.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/start-chrony.sh
```

Verify after restart:

```bash
chronyc tracking
chronyc sources
date -u   # compare to a known-good time
```

## #3: Browser OAuth on cloud VM → no display

**Symptom**: `gemini auth login`, `gcloud auth login`, `copilot login` open a browser on the **VM** (no display), or print a URL the user is supposed to open. The user is on a different machine.

**Cause**: The OAuth flow defaults to opening a browser on the local machine. On a cloud VM, the local machine is the headless VM.

**Fix**: Three options:

### Option A: `--no-launch-browser` and copy URL

```bash
gcloud auth application-default login --no-launch-browser
# Outputs a URL — copy it to your laptop browser, complete OAuth, paste the resulting code back
```

### Option B: TCP tunnel to laptop

```bash
# On laptop
gcloud workstations start-tcp-tunnel my-station --cluster=... --config=... --region=... --port=80 --local-host-port=:8080

# Then OAuth flows that try to redirect to localhost will land on the laptop
```

### Option C: Pre-issued tokens (best for unattended)

Use ADC for Google APIs (no OAuth flow needed) and env-var tokens for everything else. See `references/auth-per-tool.md`.

## #4: VS Code extension marketplace vs Open VSX

**Symptom**: Some VS Code extensions you use locally are not available in the workstation's `code-oss`. You search the marketplace and they're missing.

**Cause**: The `code-oss` distribution uses **Open VSX** (open-source extension marketplace), not the proprietary VS Code marketplace. Microsoft's marketplace is licensed only for the official VS Code build.

**Fix**: Three options:

1. **Install via VSIX** — download the `.vsix` file from the publisher's website and `code --install-extension <file>.vsix`
2. **Find an Open VSX equivalent** — many popular extensions are also published there
3. **Configure the marketplace URL** (advanced, may break) — point code-oss at a different gallery

Most popular extensions (Python, ESLint, Prettier, Docker, Remote-Containers) are on Open VSX.

## #5: Fractional L4 GPU availability — UNVERIFIED

**Symptom**: Documentation mentions fractional L4 GPUs as a workstation machine type for ML workloads. You try to provision and it's not available in your region.

**Cause**: GPU SKUs (especially fractional) are region-limited and quota-limited.

**Status**: **UNVERIFIED** as of 2026-04-08. The design doc mentions this as a research-grade claim.

**Fix**: Check live availability:

```bash
gcloud compute machine-types list --filter='guestAccelerators.acceleratorCount>0' --zones=us-central1-a
```

If fractional L4 isn't there, fall back to a regular GPU machine (e.g. `n1-standard-4` + `nvidia-tesla-t4`) or accept CPU-only for now.

## #6: `apt install` doesn't persist

**Symptom**: You install a package with `sudo apt install foo`, use it for a while, restart the workstation, and `foo` is gone.

**Cause**: `/usr` doesn't persist. See `references/persistent-home.md`.

**Fix**: Bake `apt install foo` into the Dockerfile. Rebuild. Push. Restart.

For one-off temporary installs, this is annoying but expected.

## #7: `pipx` packages persist but Python tooling outside `$HOME` doesn't

**Symptom**: You `pipx install some-tool`, it works, restart, still works. You `sudo apt install python3-foo`, restart, it's gone.

**Cause**: `pipx` installs to `~/.local/pipx`, which is in `$HOME` and persists. System packages go to `/usr` and don't.

**Fix**: Use `pipx` for any Python tool you want to keep. Use `pip install --user` for libraries you need from your own scripts.

## #8: Docker-in-Docker storage on persistent disk

**Symptom**: You enable Docker on the workstation, build a few images, and `df -h /var/lib/docker` is huge — but after restart, all your images are gone.

**Cause**: Docker's default `data-root` is `/var/lib/docker`, which doesn't persist.

**Fix**: Configure Docker's `data-root` to a path inside `$HOME`:

```json
// ~/.config/docker/daemon.json
{
  "data-root": "/home/user/.docker-data"
}
```

Or, better, use a separate persistent disk dedicated to Docker images and mount it at `/var/lib/docker`. Most users don't need this — pull images each time on restart.

## #9: `gh` CLI tries to use system credential store, falls back to plaintext

**Symptom**: `gh auth login` succeeds, token is in `~/.config/gh/hosts.yml` as plaintext.

**Cause**: Same as #1 — `libsecret-1-0` missing or credential store not running.

**Fix**: Same as #1.

## #10: Persistent disk permissions wrong on first use

**Symptom**: First time you start a workstation with a fresh persistent disk, files in `$HOME` are owned by `root` or by a different UID. Can't write.

**Cause**: The Dockerfile didn't set up the user/UID before the persistent disk was attached, or the UID in the Dockerfile mismatches the workstation's runtime UID.

**Fix**: Ensure the Dockerfile creates a user with UID matching what GCP Workstations expects (typically `1000`):

```dockerfile
RUN useradd --uid 1000 --create-home --shell /bin/bash user
USER user
WORKDIR /home/user
```

## Anti-patterns

| Don't | Why |
|---|---|
| Skip `libsecret-1-0` and `chrony` | The two #1 causes of cred-store and OAuth failures |
| Run `apt install` interactively expecting persistence | Lost on restart |
| Use Microsoft VS Code marketplace URL with code-oss | License violation; install via VSIX |
| Trust the L4 GPU claim without verifying | Region/quota limited; check live |
| Forget `--no-launch-browser` for OAuth on the workstation | Browser opens on the VM, no display |
