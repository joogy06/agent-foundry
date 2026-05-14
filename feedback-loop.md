# feedback-loop.md

A running compatibility log + report template for **agent-foundry** (and the agents/skills/commands it installs).

Most of this collection was developed on a single Linux host. When you install on a different OS / shell / Python version / container / air-gapped environment, things may break in ways nobody saw coming. **If something fails on your system, capture it here** — your workaround becomes the next user's starting point.

---

## How to report an issue

Three options, in increasing order of effort. Pick the one that matches the size of the problem:

1. **GitHub Issue** — `https://github.com/joogy06/agent-foundry/issues/new` — best for bugs that need a fix. Use the template below for the body so it's actionable.
2. **PR appending to this file** — best for "I hit this on macOS Sonoma, here's the fix, here's the proof it works." Add an entry under the right OS section + open a small PR.
3. **Annotate inline in your own clone** — if you're patching locally to keep moving and don't want to upstream yet, leave a comment in this file in your clone so you remember what you did. Optional.

---

## Reporting template

Copy this block, fill it in, paste it into a GitHub Issue body or a PR adding to a section below.

```markdown
### Issue: <one-line summary>

**Environment**
- OS + version:           (e.g. "Windows 11 Pro 23H2", "macOS Sonoma 14.4", "Ubuntu 24.04 LTS", "RHEL 9.4")
- Shell:                  (e.g. bash 5.2, zsh 5.9, PowerShell 7.4, Git Bash 2.46)
- Python version:         (output of `python3 --version` or `py --version`)
- Claude Code version:    (output of `claude --version`)
- Codex CLI version:      (output of `codex --version`, or "not installed")
- Gemini CLI version:     (output of `gemini --version`, or "not installed")
- Install method:         (`bootstrap-environment.py` / `install.py` / manual cp -r / other)
- Network mode:           (online / behind corporate proxy / air-gapped / WSL with VPN)
- Filesystem:             (e.g. ext4 / NTFS / APFS / XFS — only mention if it might matter, e.g. symlinks failed)

**What you ran**
```
<exact command>
```

**What happened**
```
<exact error output, copy-paste — strip credentials if any leaked through>
```

**What you expected**
<one line>

**Workaround you tried (if any)**
- <what>
- <whether it worked>

**Status**
- [ ] open — needs a fix from maintainers
- [ ] workaround-known — listed below in the relevant section
- [ ] fixed-in-vX.Y — closed; reference the commit / release tag
```

Tips for a useful report:
- Run `bash scripts/secrets-scan.sh --verbose` on your error output before pasting — it'll catch any tokens that accidentally leaked into the trace.
- If the issue is install-time, attach the output of `python3 bootstrap-environment.py --dry-run` so we can see what would have changed.
- For runtime issues, attach the relevant `.ledger/` events or `~/.claude/state/inventory.json` so we can see your detected capabilities.

---

## What was actually TESTED in development

Anything not in this list is "designed for, not validated." See the next section for what's known to be untested.

| Layer | Tested value |
|---|---|
| OS | Rocky Linux 10 / RHEL 10 (development host) |
| Shell | bash 5.2 |
| Python | 3.12.12 stdlib |
| Claude Code | 2.1.140 |
| Codex CLI | 0.130.0 (plugin v1.0.4) |
| Gemini CLI | 0.42.0 (with `gemini-3.1-pro-preview` OAuth pin) |
| gh CLI | 2.87.0 |
| Docker | 29.4.3 (Linux daemon) |
| Filesystem | ext4 with symlinks enabled |
| Network | direct internet + GitHub HTTPS + PyPI + npm registry + crates.io + OSV.dev |
| Git remotes | `https://github.com/...` (not SSH) |
| Repo bootstrap | `python3 bootstrap-environment.py` end-to-end |

---

## What was DESIGNED FOR but not yet validated

The installers + skills carry code paths for these environments but they have **not been run end-to-end on the real OS**. If you're on one of these, you're an early user — your feedback is the most valuable.

| Environment | What was designed | Untested risk |
|---|---|---|
| **Windows 10/11** | `install.cmd` + `install.ps1` + `bootstrap-environment.ps1` (PowerShell 5.1+, no `-ExecutionPolicy Bypass` in the new ps1, no dot-source, no `-Command`). Probes `py` / `python3` / `python` in that order. Vendored cytoscape.min.js for air-gap rendering. | Real-WIN11-with-locked-down-policy run. Symlink behaviour under Developer Mode vs admin token. UTF-8 / CRLF line endings in generated test files. PowerShell `[CmdletBinding()]` named-param dispatch in unfamiliar profiles. |
| **WSL / WSL2** | POSIX path expected; should work via `~/.claude/...` mapping into the user's Windows home. | Path translation when Claude Code runs from the Linux side but the user opens VS Code from Windows. Symlink visibility across the `/mnt/c/` boundary. |
| **macOS (Intel + ARM)** | All POSIX shell + Python stdlib; no Linux-specific syscalls assumed. | BSD `find` / `sed` / `grep` flag differences vs GNU. macOS gatekeeper blocking unsigned scripts. Apple Silicon arch-specific Python wheel issues. |
| **Ubuntu 22.04 / 24.04 LTS** | Same POSIX path as RHEL; closest cousin of the development host. | apt vs dnf wrt prerequisite packages; older bash; Python 3.10 vs 3.12. |
| **Air-gapped / corporate-policy hosts** | `offline-cold-cache` grounding mode in `dep-currency-check`; vendored cytoscape.min.js for `visual-companion`; `git-cli-bridge` skill for Gemini/Copilot fallback when local CLIs are unreachable; `bootstrap-environment.py` `--dry-run` flag. | First-boot setup with no internet (would need to seed `~/.codex/skills/`, `~/.claude/state/inventory.json` manually). Strict-airgap end-to-end. Real corporate cert chain on Python TLS calls. |
| **Containers** (Docker / Podman / Codespaces / GCP Workstations) | `gcp-workstations` skill documents tier-2 environment adoption; everything else is filesystem-portable. | Codespaces dev-container post-create script wiring. Podman rootless symlink permissions. GCP Workstations persistent-home semantics for `~/.cache/`. |
| **Older Python (3.10, 3.11)** | Code targets 3.10+ minimum per `pyproject.toml` declarations. | New stdlib features assumed (e.g. `match` statement, `Self` type) — may break on 3.9 if anyone tries. |

---

## Known compatibility issues

When something specific breaks on a specific environment, add an entry under the relevant section below. Keep them sorted newest-first inside each section.

### POSIX (Linux / macOS / WSL)

_(none reported yet)_

### Windows (native PowerShell / cmd)

_(none reported yet)_

### Containers (Docker / Podman / dev-containers / Codespaces / GCP Workstations)

_(none reported yet)_

### Air-gapped / corporate-policy environments

_(none reported yet)_

### Tool-specific

_(none reported yet — entries here when the issue is a CLI version delta, e.g. "Codex 0.130 vs 0.131 changed `codex exec` flag")_

---

## Entry format (when filling in a section above)

```markdown
#### YYYY-MM-DD — <one-line summary>

- **Environment**: <OS + version + shell + Python>
- **Trigger**: <command or skill that breaks>
- **Symptom**: <error or wrong behaviour>
- **Workaround**: <what works, if anything>
- **Status**: open / workaround-known / fixed-in-<commit-sha-or-tag>
- **Reporter**: <github handle, optional>
```

---

## Fix status reference

When an issue is resolved, update its **Status** line and (if substantial) reference the fix in the project's commit history:

- `fixed-in-<short-sha>` for in-repo fixes
- `closed-as-duplicate-of-#NN` for cross-references to GitHub Issues
- `cannot-reproduce` if multiple environments have tried and failed to reproduce
- `wontfix-rationale-<one-line>` for explicit decisions not to fix (e.g. "OS officially EOL")

---

## Cross-references

- `bootstrap-environment.py` / `bootstrap-environment.ps1` — fresh-machine setup (the most common first point of failure)
- `install.py` / `install.cmd` / `install.ps1` / `install.sh` — minimal install path
- `scripts/secrets-scan.sh` / `scripts/secrets-scan.py` — pre-push secrets gate (run before pasting error output that may contain tokens)
- `docs/dependencies/README.md` — install-tier matrix
- `~/.claude/skills/env-adoption/` — runtime capability detection (cache at `~/.claude/state/inventory.json`)
- `~/.claude/skills/knowledge-grounding/` — internet reachability + air-gap detection
- `~/.claude/skills/git-cli-bridge/` — sandbox-aware Gemini/Copilot fallback when local CLIs unreachable
