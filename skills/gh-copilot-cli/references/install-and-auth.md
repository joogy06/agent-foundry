# Install and Authentication

## Package and binary

- npm package: `@github/copilot` (verified on npm: version 1.0.21 on 2026-04-08)
- **The package is `@github/copilot`, NOT `@github/copilot-cli`** — the latter is a 404 on npm
- Binary name: `copilot`
- Repository: <https://github.com/github/copilot-cli>
- Description (from npm): *"GitHub Copilot CLI brings the power of Copilot coding agent directly to your terminal."*

## Install paths

### npm (verified)

```bash
# Global install (requires root or rootless npm prefix)
npm install -g @github/copilot

# Verify
copilot --version
which copilot
```

If you don't have root access for `/usr/local/lib/node_modules`, use a user prefix:

```bash
mkdir -p ~/.npm-global
npm config set prefix ~/.npm-global
export PATH=~/.npm-global/bin:$PATH
npm install -g @github/copilot
```

Or for a one-shot test (the binary lives at `<prefix>/node_modules/.bin/copilot`):

```bash
npm install --prefix /tmp/copilot-test @github/copilot
/tmp/copilot-test/node_modules/.bin/copilot --version
```

### Homebrew `[UNVERIFIED]`

```bash
brew install copilot-cli
```

The brew formula name is research-grade. Verify on `brew search copilot` before relying.

### winget `[UNVERIFIED]`

```powershell
winget install GitHub.Copilot
```

The winget package ID is research-grade. Verify on `winget search copilot` first.

## Authentication — verified ground truth

From `copilot login --help` (verified locally on 2026-04-08):

> Authenticate with Copilot via OAuth device flow. The default authentication mode is a web-based browser flow. After completion, an authentication token will be stored securely in the system credential store. If a credential store is not found or there is an issue using it, the token will be stored in a plain text config file under `~/.copilot/`.
>
> Alternatively, Copilot CLI will use an authentication token found in environment variables. The following are checked in order of precedence: `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`.
>
> Supported token types include fine-grained personal access tokens (v2 PATs) with the "Copilot Requests" permission, OAuth tokens from the GitHub Copilot CLI app, and OAuth tokens from the GitHub CLI (`gh`) app.
>
> Classic personal access tokens (`ghp_`) are NOT supported.

### OAuth device flow (interactive default)

```bash
copilot login
# prints an 8-digit user code, opens browser, enter code, approve
copilot --version    # confirm logged in
```

The credential is stored in:
1. System credential store (macOS Keychain, Linux Secret Service, Windows Credential Manager)
2. Fallback: plaintext at `~/.copilot/<credentials-file>` if no credential store available

### Environment variable (headless)

```bash
# Highest precedence
export COPILOT_GITHUB_TOKEN=github_pat_v2_...

# Next
export GH_TOKEN=github_pat_v2_...

# Lowest
export GITHUB_TOKEN=github_pat_v2_...

copilot -p "test" --allow-all-tools
```

Use the highest-precedence variable to avoid clashing with `gh` CLI which also reads `GH_TOKEN`/`GITHUB_TOKEN`.

### Token type requirements

| Token type | Supported? |
|---|---|
| Fine-grained PAT (v2, `github_pat_...`) with "Copilot Requests" permission | YES |
| OAuth token from the GitHub Copilot CLI app | YES |
| OAuth token from the GitHub CLI (`gh`) app | YES |
| Classic personal access token (`ghp_...`) | **NO** — explicitly rejected |
| GitHub App installation token | `[UNVERIFIED]` |

## Subscription requirement

You need an active GitHub Copilot subscription (Individual, Business, or Enterprise) to use Copilot CLI. The CLI itself is free; the model behind it is not.

`[UNVERIFIED]`: whether the free trial unlocks Copilot CLI in particular, vs only the IDE plugins.

## On a GCP Workstation

Browser-based OAuth on a cloud VM is awkward — the browser opens on the VM, not the user's laptop. Two workarounds:

1. **TCP tunnel** — `gcloud workstations start-tcp-tunnel` from the laptop, OAuth completes via localhost forward
2. **Pre-issued token** — generate a fine-grained PAT on the laptop, store in Secret Manager, fetch at use-time on the workstation:

```bash
export COPILOT_GITHUB_TOKEN=$(gcloud secrets versions access latest --secret=copilot-token)
copilot -p "..." --allow-all-tools
```

See `gcp-workstations/references/auth-per-tool.md` for the canonical recommendation.

## Verification after install

```bash
copilot --version             # version sanity
copilot --help | head -20     # confirm CLI surface
copilot login --help          # confirm auth subcommand
which copilot                 # path
ls -la ~/.copilot/            # config dir created on first run
```

The bundled `scripts/verify-copilot-install.sh` runs all of the above and writes a report.

## Anti-patterns

| Don't | Why |
|---|---|
| Use `@github/copilot-cli` as the package name | 404 on npm. The correct package is `@github/copilot`. |
| Use `ghp_*` classic tokens | Explicitly not supported. Generate a fine-grained v2 PAT with "Copilot Requests" permission. |
| Set `GH_TOKEN` and expect Copilot to use it when `COPILOT_GITHUB_TOKEN` is also set | Higher-precedence variable wins. |
| Skip `copilot login` and just install | Without auth, Copilot will block on first request. |
| Run `copilot login` in CI | Device flow needs a human. Use a token env var instead. |
| Store the token in a file checked into git | Use a credential store, env var, or Secret Manager. |
