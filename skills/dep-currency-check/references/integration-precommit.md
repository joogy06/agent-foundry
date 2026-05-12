# Integration: pre-commit hook

## Two templates ship with this skill

- `scripts/pre-commit-dep-currency.sh` — POSIX (bash/dash)
- `scripts/pre-commit-dep-currency.ps1` — Windows enterprise-hardened
- `scripts/pre-commit-dep-currency.cmd` — thin Windows wrapper that invokes `.ps1` correctly

## Install (POSIX)

```bash
cp ~/.claude/skills/dep-currency-check/scripts/pre-commit-dep-currency.sh \
   .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

## Install (Windows)

```cmd
copy %USERPROFILE%\.claude\skills\dep-currency-check\scripts\pre-commit-dep-currency.cmd .git\hooks\pre-commit
copy %USERPROFILE%\.claude\skills\dep-currency-check\scripts\pre-commit-dep-currency.ps1 .git\hooks\pre-commit-dep-currency.ps1
```

The `.cmd` wrapper is what git invokes; it then calls `pwsh.exe`/`powershell.exe` with the hardened flags.

## Exit-code contract

Same as CLI (see SKILL.md):
- 0 = pass
- 1 = strict block (only if `--mode strict` passed — pre-commit does NOT)
- 2 = soft finding — reportable, advisory only
- 3 = environmental error
- 4 = offline + cold cache (warn unless `--strict-airgap`)

**Pre-commit defaults to advisory** — it does NOT pass `--mode strict`. Commit-time MUST be fast and never block on noise. Defense-in-depth blocking is at the `G_DEP_CURRENCY` gate level.

## Behavior

1. `git diff --cached --name-only --diff-filter=ACM` to find staged changes
2. Filter to manifests + lockfiles (regex on package.json / pyproject.toml / etc.)
3. If no manifest changes → exit 0 immediately
4. Otherwise → invoke `python3 -m dep_currency_check $REPO_ROOT --changed-manifests $CHANGED --severity critical --format json --quiet`
5. Exit on whatever the CLI returned

## Why advisory at commit time

- Defense-in-depth: commit-time hook catches the obvious (you added a CVE-bearing dep RIGHT NOW). Wider scan happens at `G_DEP_CURRENCY` gate.
- Speed: commit hooks must be sub-second when there are no manifest changes; ~5s when there are. `--mode strict` could escalate latency.
- Noise: a strict hook that fires on transitive-dep CVEs would block commits unrelated to the new code. Bad UX.

## Windows hardening (mirrors vs-code-foundry)

See `references/windows-hardening.md` for the enterprise rules. tl;dr:

- NO `-ExecutionPolicy Bypass`
- NO dot-source
- ALWAYS `-NoProfile -NonInteractive -File`
- Try `pwsh.exe` first, fall back to `powershell.exe`
- Use call operator `&` for Python invocation

## Manifest regex

```
package\.json|pyproject\.toml|requirements[^/]*\.txt|Cargo\.toml|go\.mod|Gemfile|pom\.xml|build\.gradle.*|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|go\.sum|Gemfile\.lock
```

Same regex in both POSIX and PowerShell scripts.
