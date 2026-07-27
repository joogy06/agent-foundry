---
name: secret-scanning
description: Use when scanning a codebase for hardcoded secrets (API keys, tokens, passwords, PEM keys, AWS creds, JWTs) — wraps gitleaks (fast regex pre-commit), trufflehog (slower CI-time live-credential verification with --only-verified), and the in-house regex catalog at scripts/secrets-scan.sh as defense-in-depth. Use for pre-push hooks, CI gates, alf sweeps, the G_SECRETS_SCAN gate in _meta/gates.py, and ad-hoc audits. ALSO owns the host-wide secrets STORAGE standard (~/.secrets/<project>.env + loader + blocking pre-commit hook) — see references/storage-standard.md. Trigger on - secret scanning, secrets storage, where do I put credentials, .env handling, secrets management, hardcoded credentials, leaked tokens, PEM keys in repo, AWS keys in code, secret detection, gitleaks, trufflehog, secret-in-code, .env in git, credential audit, pre-push secrets.
---

# Secret Scanning

## Overview

Detect hardcoded secrets — API keys, tokens, passwords, PEM private keys, AWS access keys, GitHub PATs, JWTs, Slack tokens, OpenAI keys — before they land in commits, pushes, or production. This skill wraps three layered tools:

| Tool | Speed | False-positive rate | Live-verify? | Use case |
|---|---|---|---|---|
| **gitleaks** | Fast (regex-based) | Medium | No | Pre-commit / pre-push hooks; CI quick gate |
| **trufflehog** | Slower (verifies via API calls) | Low (`--only-verified`) | Yes | CI deeper scan; reduce triage noise |
| **in-house** `scripts/secrets-scan.sh` | Fast (regex catalog of ~18 patterns) | Medium-high (curated allowlist) | No | Defense-in-depth; covers patterns gitleaks may miss; offline-safe; POSIX shells (Linux/macOS/Git Bash) |
| **in-house** `scripts/secrets-scan.py` | Fast (same catalog — stdlib-only Python port of the `.sh`, full parity) | Medium-high (same curated allowlist) | No | Cross-platform (Linux/macOS/Windows, Python 3.10+); enterprise Windows where bash/PowerShell are blocked |

The recommended posture in 2026 is **layered**: gitleaks at pre-commit for speed, trufflehog with `--only-verified` in CI to eliminate triage burden, in-house regex as a backstop.

<HARD-RULE>
NEVER auto-install pre-commit / pre-push hooks into arbitrary user repositories. Hook installation is opt-in per project, prompted at `bootstrap-environment.py` time OR explicitly invoked. Auto-install corrupts user repos and can trigger noisy failures on commits unrelated to secret-scanning. The `dep-currency-check` skill SKILL.md anti-patterns table calls this out as a prior failure mode in this ecosystem.
</HARD-RULE>

<HARD-RULE>
NEVER commit secrets-scan output containing redacted-but-positional matches (filename + line number). An attacker reading the output can correlate against the public repo to locate the exact secret on disk before redaction. Scanner output goes to stderr or a temp file, not the commit log, not the PR description.
</HARD-RULE>

<HARD-RULE>
Secret-scanning is NECESSARY but NOT SUFFICIENT. A clean scan does NOT prove the codebase is secret-free — only that the scanner's pattern catalog did not match. Pair with: env-var-based secret loading (never embed in source), `.gitignore` for `.env*` and `*.pem`, vault integration for production (Azure Key Vault, AWS Secrets Manager, HashiCorp Vault, Windows Credential Manager, Linux libsecret), and rotation procedures for accidentally-committed secrets (rotate immediately, don't just delete).
</HARD-RULE>

Companion skills:
- `dep-currency-check` — dependency CVE check; closest local pattern for the gate-wrapper architecture
- `python-auth-security` — credential storage patterns (where the secrets SHOULD live)
- `docker-security` — secrets-in-images (separate domain)
- `llm-security` — secrets in LLM prompts (don't put secrets in prompts; LLM07 / LLM06)

---

## 0. Secrets storage standard (host-wide, adopted 2026-07-25)

Detection is half the job. Where secrets LIVE is the other half — and the reason
detection keeps having work to do. The standard:

```
~/.secrets/<project>.env   ->   loader   ->   process environment   ->   your code
   storage (0600)                              delivery (ephemeral)
```

**Storage and delivery are different questions.** An environment variable is how a
process *receives* a secret, not where one is *kept*. Full spec, rationale, honest
caveats and the migration recipe: **`references/storage-standard.md`**.

| Layer | Rule |
|---|---|
| Storage | `~/.secrets/<project>.env` (0600), dir 0700; shared values in `common.env` |
| Delivery | `scripts/load-secrets.sh` (bash) or `scripts/load_secrets.py` (python) |
| Precedence | real env **>** `<project>.env` **>** `common.env` |
| In repo | `.env.example` (names only), `.gitignore` rule, loader call — nothing else |
| Enforcement | **pre-commit** hook, blocking |

### Enforcement — one pattern set, three call sites

The commit hook, the push hook and the gate all invoke the SAME scanner, so their
rules cannot drift apart:

| When | Mechanism |
|---|---|
| `git commit` | `hooks/pre-commit` → `secrets-scan.py --staged` (reads the **git index**) |
| `git push` | `.git/hooks/pre-push` → `secrets-scan.py` (worktree) |
| Agent cycles | `G_SECRETS_SCAN` in `_meta/gates.py` |

```bash
bash ~/.claude/skills/secret-scanning/hooks/install.sh   # per repo, commit-time
```

Two deliberate design choices, both learned the hard way:

- **`install.sh` REFUSES to install if no scanner resolves.** An inert hook is worse
  than no hook — it advertises protection that does not exist.
- **The hook fails CLOSED if the scanner disappears after install.** Same reasoning.
  `git commit --no-verify` remains the explicit, visible escape hatch.

Commit-time is the one that matters most: push-time stops a secret leaving the
machine, commit-time stops it entering history at all.

### Honest limits — do not oversell

- `~/.secrets/` is **plaintext on disk**. Fewer copies and one audit point, but it is
  NOT encryption and NOT a secret manager. Upgrade path: `age`+`sops` or `pass`
  (none installed on this host today).
- **Env vars are not a security boundary** — readable via `/proc/<pid>/environ` by the
  same user, inherited by every subprocess, visible in `ps`. Fine for delivery.
- **Scrubbing is not rotation.** A credential that was ever committed must be rotated
  at the provider; removing it from files does nothing for the exposure.

## 1. Tool selection — when to use which

| Scenario | Tool | Mode |
|---|---|---|
| Pre-commit hook (local dev, <2s budget) | gitleaks | regex |
| Pre-push hook (allow ~10s) | gitleaks OR in-house | regex |
| CI on every PR (allow ~60s) | gitleaks + trufflehog (--only-verified) | layered |
| CI nightly deep scan (allow several min) | trufflehog (--only-verified) + gitleaks | layered |
| Offline / air-gapped environments | gitleaks OR in-house | regex (no live verify) |
| Forge Step 1 advisory check on new project | in-house (always present) | advisory |
| bob WP-completion gate | G_SECRETS_SCAN strict mode | configurable scanner |
| alf sweep | G_SECRETS_SCAN advisory mode | configurable scanner |
| Historical git-history scan (whole repo back to root) | trufflehog `git` mode OR gitleaks `git` | one-shot |

**Why three tools instead of one:** different tools catch different patterns. gitleaks is regex-heavy and fast; trufflehog adds live-verification (the secret is actually valid against its provider's API) which drastically reduces false-positives. The in-house catalog covers patterns specific to our local ecosystem (e.g. `.bob-checkpoint.md` token-shaped strings that aren't real but pattern-match) and runs offline.

---

## 2. Install Commands

### RHEL 9 / AlmaLinux 9 / Rocky 9
```bash
# gitleaks — official binary release
curl -sSfL https://github.com/gitleaks/gitleaks/releases/latest/download/gitleaks_linux_x64.tar.gz | sudo tar -C /usr/local/bin -xzf - gitleaks
sudo chmod +x /usr/local/bin/gitleaks
gitleaks version

# trufflehog — official binary release
curl -sSfL https://raw.githubusercontent.com/trufflesecurity/trufflehog/main/scripts/install.sh | sudo sh -s -- -b /usr/local/bin
trufflehog --version
```

### Debian 12 / Ubuntu 24.04
```bash
# gitleaks
curl -sSfL https://github.com/gitleaks/gitleaks/releases/latest/download/gitleaks_linux_x64.tar.gz | sudo tar -C /usr/local/bin -xzf - gitleaks
sudo chmod +x /usr/local/bin/gitleaks

# trufflehog
curl -sSfL https://raw.githubusercontent.com/trufflesecurity/trufflehog/main/scripts/install.sh | sudo sh -s -- -b /usr/local/bin
```

### macOS
```bash
brew install gitleaks trufflesecurity/trufflehog/trufflehog
```

### Windows 11
```powershell
# gitleaks — via Scoop / Chocolatey or release ZIP
scoop install gitleaks
# OR
choco install gitleaks

# trufflehog — via release binary; no Scoop package in 2026
# Download from https://github.com/trufflesecurity/trufflehog/releases/latest
```

Verify availability via env-adoption probe:
```bash
bash ~/.claude/skills/env-adoption/scripts/probe.sh check --force
jq '.tools | {gitleaks, trufflehog}' ~/.claude/state/inventory.json
```

---

## 3. Canonical patterns

### 3.1 Local pre-push hook (bash for POSIX shells, Python for cross-platform)

Two installer/scanner pairs ship in your project root's `scripts/` — pick by environment:

- **POSIX shells (Linux / macOS / Git Bash):** `scripts/install-pre-push-hook.sh` installs a hook that runs `secrets-scan.sh`.
- **Cross-platform / enterprise Windows** (Execution Policy / AppLocker / Constrained Language Mode blocks PowerShell, but Python is present): `scripts/install-pre-push-hook.py` wires `scripts/secrets-scan.py` — stdlib-only, full parity with the bash pair (same patterns, allowlist, severity tiers, exit codes). Idempotent; backs up any unmanaged pre-push hook to `pre-push.bak`; `--uninstall` removes only the managed hook.

```bash
# Python pair (Linux, macOS, Windows)
python3 scripts/install-pre-push-hook.py                      # install into cwd
python3 scripts/install-pre-push-hook.py --target-repo PATH   # install into a specific repo
python3 scripts/install-pre-push-hook.py --uninstall          # remove the managed hook
```

To add gitleaks as a second pre-push pass, append to `.git/hooks/pre-push` (after the existing inhouse scan):

```bash
# gitleaks pre-push gate (additional layer)
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks dir . --no-banner --redact --exit-code 1 >&2 || {
    echo "[gitleaks] BLOCKING — secrets detected. Override: git push --no-verify"
    exit 1
  }
fi
```

### 3.2 GitHub Actions CI workflow

```yaml
# .github/workflows/secret-scan.yml
name: secret-scan
on: [pull_request, push]
jobs:
  gitleaks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITLEAKS_NOTIFY_USER_LIST: '@security-team'

  trufflehog-verified:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - name: trufflehog (verified only)
        uses: trufflesecurity/trufflehog@main
        with:
          extra_args: --only-verified --fail
```

### 3.3 G_SECRETS_SCAN gate (S038 Batch B)

The gate at `_meta/gates.py` wraps all three scanners. Auto-picks gitleaks > trufflehog > in-house.

```bash
# Advisory mode (never fails build; reports findings)
python3 ~/.claude/skills/_meta/gates.py G_SECRETS_SCAN /path/to/project \
  --secrets-mode advisory

# Strict mode (fails on any finding)
python3 ~/.claude/skills/_meta/gates.py G_SECRETS_SCAN /path/to/project \
  --secrets-mode strict --scanner gitleaks
```

Exit codes match the existing gate contract:
- 0 = pass (no findings OR advisory mode)
- 2 = fail (strict mode AND findings detected)
- 3 = environmental error (no scanner available)

### 3.4 gitleaks custom config (.gitleaks.toml at repo root)

The `dep-currency-check` skill has an established allowlist convention. Mirror that pattern for project-specific noise:

```toml
# .gitleaks.toml
title = "<project>-gitleaks-config"

[extend]
useDefault = true

[allowlist]
description = "project-specific known FPs"
paths = [
  '''docs/.*tutorial.*\.md''',
  '''.*\.test\.(js|ts|py)$''',
]
regexes = [
  '''aws_access_key_id\s*=\s*AKIAIOSFODNN7EXAMPLE''',  # AWS docs example
  '''ghp_[A-Za-z0-9]{36}.*example.*''',                 # placeholder PATs
]
```

---

## 4. Defense-in-depth layering

Use ALL THREE tools — they catch different things:

| Pattern | gitleaks | trufflehog | in-house |
|---|---|---|---|
| GitHub PAT (classic) | ✓ | ✓ (verifies) | ✓ |
| AWS access key | ✓ | ✓ (verifies) | ✓ |
| Slack bot token | ✓ | ✓ (verifies) | ✓ |
| OpenAI sk- key | ✓ | ✓ (verifies) | ✓ |
| Generic high-entropy string | ✓ | ✓ | ✗ (would FP-storm) |
| PEM private key header | ✓ | ✓ | ✓ |
| JWT in source | ✓ | ✗ | ✓ |
| Inline `password=...` assignment | partial | partial | ✓ (in-house has this specifically) |
| Internal hostname leak | ✗ | ✗ | ✓ (`*.internal`, `*.corp`) |
| Live-credential verification (the secret is actually valid) | ✗ | ✓ | ✗ |

Trufflehog's `--only-verified` flag is the headline 2026 improvement — by hitting each candidate against its real provider API, it eliminates almost all false-positives. The trade-off is speed (each verify is an HTTP round-trip) and the assumption that you trust your CI runner to make those API calls (in air-gapped environments, skip --only-verified).

---

## 5. Security Hardening

1. **`.gitignore` `.env*` and `*.pem`** before adding the scan — the scan is the safety net, not the policy.
2. **Pre-commit AND pre-push, not just one** — pre-commit catches local mistakes; pre-push catches anything that bypassed it (rebase, cherry-pick, force-push to a new branch).
3. **CI gate on PR + push** — local hooks can be bypassed with `--no-verify`; CI cannot.
4. **Custom config per project** — every project accumulates legitimate FP patterns over time. Maintain a `.gitleaks.toml` (or equivalent) with documented justifications.
5. **Rotate on detection, don't just delete** — if a real secret was committed, even briefly, treat it as leaked. Rotate the secret with the provider. `git filter-repo` to scrub history is theatre if the secret was visible for any minute via cloning/pushing.
6. **Audit log scanner runs** — when, who, what findings. The G_SECRETS_SCAN gate emits stdout; capture it in CI artifacts.
7. **Don't ignore `--no-verify` overrides** — log who used the override and investigate. If `--no-verify` is routine in your team, the hook is too noisy and needs allowlist tuning.
8. **Tune the in-house allowlist with care** — every entry is a documented exception. Review the allowlist quarterly; remove entries whose context no longer applies.
9. **Scan generated artifacts too** — build outputs, Docker images (`trivy fs` overlaps here), test fixtures with mock secrets. A "test-only" secret committed by accident is still a secret if it works against any real service.
10. **Keep scanner versions current via `dep-currency-check`** — gitleaks and trufflehog ship pattern updates regularly. A stale scanner misses new providers' secret formats.

---

## 6. Anti-patterns

| Anti-pattern | Why it fails | Correct approach |
|---|---|---|
| `--no-verify` becomes routine | Defeats the safety net; team normalises bypass | Tune the allowlist OR raise the false-positive rate as a real bug |
| One tool only | Each tool has blind spots; no single catalog is complete | Layer at least two of {gitleaks, trufflehog, in-house} |
| Scan only pre-commit | Force-push / rebase / cherry-pick / branch creation bypass commit-time hooks | Add pre-push AND CI |
| Trust `--only-verified` to find everything | Many tokens are not live-verifiable (proprietary providers, locked-down APIs) | Pair with regex scanner; treat live-verify as drift-reducer, not gospel |
| Treat detection as the whole defense | Detection finds what's already there; you also need policy (env vars, vault, .gitignore) | Detection is a backstop, not a strategy |
| Auto-install hooks across all user repos | Corrupts repos; surprises contributors; impossible to roll back cleanly | Opt-in per repo via `bootstrap-environment.py` prompt |
| Embed allowlist in scanner config without justification comment | Six months later nobody knows why X is allowlisted | Every allowlist entry MUST carry a one-line comment with the documented reason |
| Scan-and-delete without rotation | The secret was visible for at least one commit window; treat as leaked | Rotate at the provider; THEN scrub history (optional) |

---

## 7. Selection Cheatsheet

- **Need a pre-commit hook right now** → `gitleaks protect --staged`
- **Need a CI gate with zero false positives** → trufflehog `--only-verified --fail`
- **Need a one-shot scan of an existing repo's full history** → `trufflehog git file://. --no-update`
- **Need a defense-in-depth backstop offline** → in-house `scripts/secrets-scan.sh` (always present in this ecosystem)
- **Need a programmatic gate inside bob WP-completion** → `gates.py G_SECRETS_SCAN <root> --secrets-mode strict`
- **Need a forge Step 1 advisory check** → `gates.py G_SECRETS_SCAN <root> --secrets-mode advisory`

---

## 8. Gotchas

| Gotcha | Detail |
|---|---|
| gitleaks pre-commit treats new files only | Use `gitleaks dir .` for full-repo scan; `gitleaks protect --staged` for staged-only |
| trufflehog `--only-verified` needs network | In air-gapped CI, drop the flag and accept the FP burden, OR pre-allowlist known FPs |
| In-house scanner allowlist is centralized | One `scripts/secrets-scan.sh`, one allowlist; cross-project FP-tuning is shared |
| `.gitleaks.toml` is git-tracked | Allowlist additions are visible to anyone who clones — don't write secrets INTO the allowlist itself (use regex patterns that match the *shape*) |
| `git filter-repo` history scrub is destructive | Coordinate with anyone holding the repo; force-push afterwards; rotate the secret regardless |
| Some legacy regex catalogs (in-house pre-2026) flagged tutorial placeholders | The in-house catalog has a curated allowlist for this — see `scripts/secrets-scan.sh` source |
| Docker image scans are NOT covered here | Use `trivy image <ref>` for image-mode scans (see `docker-security` skill) |
| Encrypted secrets at rest are not in scope | If you encrypt secrets in source (sops, git-crypt, age), the scanner sees the ciphertext and won't flag it — but that's *intended*. Decrypted files MUST be `.gitignore`d. |

---

## 9. Update triggers (alf scans these)

- gitleaks major version bump (currently 8.x as of 2026-05)
- trufflehog major version bump (currently 3.x)
- New provider added to gitleaks default config (auto-detected via `gitleaks version` output)
- New secret-shape provider widely deployed (e.g. a new cloud's tokens become common in the wild)
- In-house `scripts/secrets-scan.sh` pattern catalog update
- Annual review on 2027-05-24

---

## 10. See Also

| Need | Skill |
|---|---|
| Dependency CVE scanning (parallel pattern) | `dep-currency-check` |
| Credential storage patterns (env / vault / keyring) | `python-auth-security` |
| LLM prompts must not contain secrets | `llm-security` (LLM06, LLM07) |
| Docker image secret scans | `docker-security` |
| Pre-commit hook install pattern (POSIX + Windows hardened PS1) | `dep-currency-check` (precedent) |
| The G_SECRETS_SCAN gate it wraps | `~/.claude/skills/_meta/gates.py` |
| Bootstrap-environment hook offer | `~/.claude/skills/_meta/` + `installer/bootstrap-environment.py` |
