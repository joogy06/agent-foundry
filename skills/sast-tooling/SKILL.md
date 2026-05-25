---
name: sast-tooling
description: Use when running Static Application Security Testing (SAST) on a codebase — wraps bandit (Python), semgrep (multi-language, OSS rule packs), eslint-security (JavaScript/TypeScript), and CodeQL (GitHub-hosted, license-gated for private repos). Standardises on SARIF 2.1.0 output, feeds the G_SECURE gate in _meta/gates.py, integrates with forge Step 1 advisory, alf sweeps, and pre-commit/CI workflows. Trigger on - SAST, static analysis, bandit, semgrep, CodeQL, eslint-security, SARIF, security linting, code-injection scan, "scan code for vulnerabilities", "find security bugs", "OWASP scan".
---

# SAST Tooling

## Overview

Static Application Security Testing (SAST) — find security defects in source code without running it. SAST catches the LOW-MEDIUM hygiene defects (`verify=False`, `eval(user_input)`, hardcoded `password=` strings, unsafe deserialisation, weak cryptography) that secret-scanning and dep-currency-check don't cover. Per the S038 alf sweep verdict, this skill closes the "no SAST runner" gap (finding F-H2).

The runner choices in 2026, with Gemini freshness-probe corroboration (2026-05-22):

| Tool | Languages | Maintenance | Speed | False positives | Use case |
|---|---|---|---|---|---|
| **bandit** | Python only | Active (v1.9.4 Feb 2026, py3.10+ required) | Fast | Low-medium | Python-specific; CI gate; pre-commit |
| **semgrep** | Multi-language (Python/JS/TS/Java/Go/Ruby/PHP/C/+more) | Active (v1.x, no breaking v2.0 — Agentic IDE hooks added 2025-26) | Fast | Medium (configurable per ruleset) | The de-facto multi-language SAST; default choice for polyglot repos |
| **eslint-security** | JavaScript / TypeScript | Active (eslint-plugin-security) | Fast | Medium | JS/TS-specific; runs as ESLint plugin; CI gate |
| **CodeQL** | Many (C/C++/C#/Go/Java/JS/Python/Ruby/Swift) | Active (GitHub) | Slower (compile-then-analyze) | Low (deep dataflow) | Best for high-stakes / open-source; license-gated for private repos since Apr 2025 |

<HARD-RULE>
NEVER ship SAST findings AS production gates without false-positive tuning. The first run on any real codebase will produce dozens-to-hundreds of advisory findings; running with `--strict` from day one will block all commits and the team will learn to use `--no-verify`. Mandatory rollout pattern: advisory mode for 2-4 weeks → triage existing findings into "fix" / "suppress with reason" / "accept" → strict mode only AFTER the baseline is clean. The G_SECURE gate enforces this via the advisory|strict knob.
</HARD-RULE>

<HARD-RULE>
NEVER use `bandit --confidence-level LOW` in CI gating without explicit baseline tuning. Bandit's LOW-confidence rules produce so many false positives they create alert fatigue. Default CI: `bandit -ll` (medium severity, medium confidence). Tighten only after baselining.
</HARD-RULE>

<HARD-RULE>
NEVER suppress findings via inline comments (`# nosec`, `// nosemgrep`) without a documented justification IN THE COMMENT. Every suppression is a permanent exception; future maintainers (and alf sweeps) need to know why. Required format - `# nosec: B608 — query is parameterised on line 47, false positive on string concat`. Bare suppressions are an anti-pattern reviewed by the sweep.
</HARD-RULE>

Companion skills:
- `python-auth-security` — what the findings SHOULD look like (no `eval`, parameterised SQL, etc.)
- `secret-scanning` — sister skill for secrets (gitleaks/trufflehog)
- `dep-currency-check` — sister skill for dependency CVEs (orthogonal to source-level SAST)
- `llm-security` — sister skill for LLM-specific defects
- `_meta/gates.py` (G_SECURE) — the gate this skill feeds

---

## 1. Tool selection — when to use which

| Scenario | Tool |
|---|---|
| Pure-Python project | **bandit** (cheap, Python-specific) + optional `semgrep --config p/python` for broader coverage |
| JS/TS project | **eslint-security** in eslint config + optional `semgrep --config p/javascript` |
| Polyglot repo (Python + JS + Go + ...) | **semgrep** with bundled or custom rulesets — single runner, single SARIF output |
| Public repo on GitHub | **CodeQL** via Actions (free for public repos) + semgrep for fast iteration |
| Private repo on GitHub with GHAS Code Security | **CodeQL** + semgrep |
| Private repo without GHAS budget | **semgrep** + tool-specific (bandit / eslint-security) — CodeQL is $30/committer/month standalone since Apr 2025 |
| Air-gapped / offline environment | bandit + semgrep (both offline-capable with bundled rulesets) |
| Quick-iteration developer-loop scan | semgrep autofix (`--autofix`) for the small set of safe-auto-fix rules |
| Highest-confidence deep dataflow analysis | CodeQL |

**The default 2026 setup for a polyglot CI gate:** semgrep + bandit (Python) + eslint-security (JS/TS), each emitting SARIF, aggregated by G_SECURE. CodeQL adds the dataflow tier when budget / license permits.

---

## 2. Install Commands

### RHEL 9 / AlmaLinux 9 / Rocky 9
```bash
# bandit
pip install --user bandit
bandit --version  # expects 1.9.x

# semgrep
pip install --user semgrep
semgrep --version  # expects 1.16x.x

# eslint-security (Node.js project)
npm install --save-dev eslint eslint-plugin-security

# CodeQL CLI (standalone — for use outside GHAS)
# Download from: https://github.com/github/codeql-cli-binaries/releases
# Place under ~/.local/bin/codeql
```

### Debian 12 / Ubuntu 24.04
```bash
# Same pip / npm commands as RHEL
pip install --user bandit semgrep
# eslint-security per project
```

### Windows 11
```powershell
# Via pip (Python tools)
py -m pip install --user bandit semgrep
# Or scoop/chocolatey:
scoop install semgrep
```

Verify via env-adoption (S038 Batch A added these to the inventory):
```bash
jq '.tools | {bandit, semgrep, "pip-audit", "osv-scanner"}' ~/.claude/state/inventory.json
```

---

## 3. SARIF as the canonical output

[SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html) is the multi-tool standard. Every wrapper this skill describes emits SARIF, and G_SECURE consumes SARIF. This means findings from bandit / semgrep / eslint-security / CodeQL aggregate uniformly into one report, ingestable by GitHub Advanced Security, VS Code, JetBrains, Sonarqube, and most enterprise dashboards.

```bash
# bandit → SARIF
bandit -r src/ -f sarif -o /tmp/bandit.sarif

# semgrep → SARIF
semgrep --config auto --sarif --output /tmp/semgrep.sarif

# eslint-security → SARIF
npx eslint --format @microsoft/eslint-formatter-sarif --output-file /tmp/eslint.sarif src/

# CodeQL → SARIF (via Action; CLI: codeql database analyze --format=sarif-latest)
```

G_SECURE aggregates by reading SARIF and applying the configured severity threshold.

---

## 4. Canonical CI integration

### 4.1 GitHub Actions (.github/workflows/sast.yml)

```yaml
name: sast
on: [pull_request, push]
jobs:
  semgrep:
    runs-on: ubuntu-latest
    permissions: { security-events: write }
    steps:
      - uses: actions/checkout@v4
      - uses: returntocorp/semgrep-action@v1
        with:
          config: >-
            p/python p/javascript p/typescript p/security-audit p/secrets
            p/r2c-security-audit p/owasp-top-ten
          generateSarif: true
      - uses: github/codeql-action/upload-sarif@v3
        with: { sarif_file: semgrep.sarif }

  bandit:
    runs-on: ubuntu-latest
    if: contains(github.event.repository.topics, 'python') # gate on python repos
    permissions: { security-events: write }
    steps:
      - uses: actions/checkout@v4
      - run: pip install bandit
      - run: bandit -r . -ll -f sarif -o bandit.sarif || true
      - uses: github/codeql-action/upload-sarif@v3
        with: { sarif_file: bandit.sarif }

  codeql:
    # Optional — CodeQL for deeper dataflow
    runs-on: ubuntu-latest
    permissions: { security-events: write }
    strategy:
      matrix: { language: [python, javascript] }
    steps:
      - uses: actions/checkout@v4
      - uses: github/codeql-action/init@v3
        with: { languages: ${{ matrix.language }} }
      - uses: github/codeql-action/analyze@v3
```

### 4.2 Pre-commit hook (POSIX)

```bash
# .git/hooks/pre-commit (extract)
if command -v semgrep >/dev/null 2>&1; then
  semgrep --config auto --error --quiet --skip-unknown-extensions $(git diff --cached --name-only) \
    || { echo "[semgrep] BLOCKING — review findings"; exit 1; }
fi
```

### 4.3 The G_SECURE gate (S038 Batch E)

```bash
python3 ~/.claude/skills/_meta/gates.py G_SECURE /path/to/project \
  --sast-mode advisory                # never blocks; reports
python3 ~/.claude/skills/_meta/gates.py G_SECURE /path/to/project \
  --sast-mode strict \
  --severity high                     # blocks on high+critical
python3 ~/.claude/skills/_meta/gates.py G_SECURE /path/to/project \
  --sast-mode strict \
  --severity critical \
  --runner semgrep                    # explicit runner choice
```

Exit codes mirror the family:
- 0 = pass (no findings at/above severity, OR advisory mode)
- 2 = fail (strict mode AND findings at/above severity)
- 3 = environmental error (no SAST runner available)

---

## 5. Per-runner notes

### 5.1 bandit (Python)

- Confidence levels: HIGH / MEDIUM / LOW. Default rules-loaded at all levels. `-ll` = medium-or-higher severity + medium-or-higher confidence. **Recommended CI baseline.**
- `-ll` filter is the most-cited 2026 baseline by the OpenSSF Python WG (the LOW-confidence rules produce too many FPs).
- Common-rule cheat-sheet:
  - B101 — assert outside tests (False in production)
  - B105/106/107 — hardcoded password strings/funcargs/defaults
  - B301 — pickle deserialisation (HIGH severity)
  - B324 — weak hash (md5/sha1)
  - B501 — `verify=False` in requests
  - B602/603/605/607 — subprocess shell-injection variants
  - B608 — SQL string concat
  - B701 — Jinja2 autoescape disabled
- Inline suppress: `# nosec: <rule-id> — justification`
- Project config: `bandit.yaml` or `pyproject.toml [tool.bandit]`

### 5.2 semgrep (multi-language)

- Free-tier rulesets: `p/security-audit`, `p/owasp-top-ten`, `p/secrets`, language-specific `p/python` / `p/javascript` / etc. The 2026 build has Agentic IDE hooks (Claude Code / Windsurf integration).
- Autofix: `semgrep --autofix` for the small subset of rules marked `fix:` in the YAML. Safe-by-default — only applies fixes that don't change semantics.
- Custom rules: YAML under `.semgrep/`. Pattern-based matching with metavariables; far more flexible than bandit.
- Inline suppress: `// nosemgrep: <rule-id>` (or language-comment variant)
- Project config: `.semgrep.yml` or `--config <path>`

### 5.3 eslint-security (JS/TS)

- `eslint-plugin-security` provides a focused security-only ruleset; add to your eslint config:
  ```json
  {"extends": ["plugin:security/recommended"], "plugins": ["security"]}
  ```
- Coverage is narrower than semgrep for JS — they're complementary, not redundant.
- Key rules: `detect-eval-with-expression`, `detect-non-literal-fs-filename`, `detect-non-literal-regexp`, `detect-unsafe-regex`, `detect-object-injection`.

### 5.4 CodeQL

- GHAS Code Security add-on standalone: $30/committer/month (since Apr 2025 — Gemini freshness probe).
- Open-source / public repos: free via GitHub Actions.
- Strengths: deep dataflow analysis catches taint flows that pattern-matchers miss.
- Slow (compile-then-analyse) — use for nightly / pre-release scans, not every PR.
- Output: SARIF, ingestable by GHAS or third parties.

---

## 6. Security Hardening (the rules for THIS skill's usage)

1. **Layer SAST + secrets + deps + LLM-security** — each tool catches different things; none is sufficient alone.
2. **Run advisory first**, baseline existing findings, then go strict.
3. **Document every suppression** — `# nosec: B608 — reason` not bare `# nosec`.
4. **CI gates use SARIF** — feed into GitHub Advanced Security / Sonarqube / enterprise dashboards.
5. **CI runs at least one SAST runner** (semgrep is the cheapest baseline).
6. **Pin SAST runner versions** — semgrep's rule packs change, bandit's rule list updates; record the version in CI logs (`bandit --version` / `semgrep --version`).
7. **Keep SAST runner versions current via `dep-currency-check`** — semgrep ships new rule packs continuously.
8. **Don't `--autofix` blindly in CI** — review the diff. Auto-fixed code can change semantics for edge cases the fix-rule didn't anticipate.
9. **Custom rules are project-specific** — file under `.semgrep/` in the repo, code-review additions.
10. **alf sweep includes SAST runner currency** — sees `bandit`/`semgrep`/`gitleaks` versions in the inventory and flags if the project's pinned version drifts.

---

## 7. Anti-patterns

| Anti-pattern | Why it fails | Correct approach |
|---|---|---|
| Run `bandit` with default confidence (`LOW`) in CI gate from day one | FP storm; team learns to `--no-verify` | Use `bandit -ll`; tune over time |
| One tool only | Each catches different things | Layer at least 2 of {semgrep, bandit, eslint-security} |
| `# nosec` without justification | Permanent exception with no traceable reason | Required format: `# nosec: <id> — reason` |
| Auto-fix in CI without review | Rule-based fixes can break edge-case semantics | `--autofix` only locally, then code-review the diff |
| Skip SAST because dep-currency-check + secret-scanning are running | Sister skills cover different threats; SAST adds source-level findings | Run all three (G_SECRETS_SCAN + G_DEP_CURRENCY + G_SECURE) |
| Treat SAST FPs as bugs in the SAST tool | Triaging FPs is the work; modern SAST is by-design over-reporting | Triage, suppress with reason, OR tune the ruleset |
| Run CodeQL on every PR | Slow; eats GHAS minutes; better for nightly | semgrep / bandit on PR, CodeQL nightly |
| Custom rules in a single project's `.semgrep/` without sharing back | Reinvents the wheel across projects | Maintain shared org-level rule packs |

---

## 8. Selection Cheatsheet

- **Polyglot CI gate, fast** → semgrep `--config auto` with `--severity ERROR --error`
- **Python project + needs deep dataflow** → bandit + CodeQL (Python)
- **JS/TS in mixed repo** → semgrep `p/javascript` + eslint-security inside ESLint
- **Just want quick "is this code obviously bad" check locally** → `semgrep --config p/security-audit --autofix` (local only)
- **Need SARIF aggregated to GitHub Advanced Security** → upload via `github/codeql-action/upload-sarif@v3`
- **Need G_SECURE for bob WP-completion gate** → `python3 ~/.claude/skills/_meta/gates.py G_SECURE --sast-mode strict`
- **Need an advisory pass for forge Step 1** → `--sast-mode advisory`

---

## 9. Gotchas

| Gotcha | Detail |
|---|---|
| semgrep `--config auto` requires `metrics: on` (default) to authenticate | For air-gapped, use `--config p/<ruleset>` with explicit packs |
| bandit can't analyse code that doesn't parse | If your code uses syntax newer than the bandit-supporting Python (1.9.4 → py 3.14), bandit will fail; pin a compatible Python |
| eslint-plugin-security needs eslint flat-config in modern repos | `.eslintrc.json` legacy format still works, but new repos default to `eslint.config.js` |
| CodeQL pricing changed Apr 2025 | Public repos free; private repos require GHAS Code Security add-on at $30/committer/month |
| SARIF schema versions can clash | All four runners standardise on 2.1.0 as of 2026; older outputs may need conversion |
| semgrep autofix on `==` → `===` (JS) is safe-mostly but rarely "what the developer wanted" | Review every autofix |
| Custom rule false-positives in semgrep need careful pattern design | Use `pattern-not` and `metavariable-regex` to scope tightly |
| bandit B105 flags `password = "changeme"` even in test fixtures | Suppress with `# nosec: B105 — test fixture, not a real credential` |

---

## 10. Update triggers (alf scans these)

- bandit major version bump (currently 1.9.x as of 2026-05)
- semgrep major version bump (still on 1.x, but 2.0 would be material)
- semgrep rule pack additions for new attack patterns
- ESLint flat-config completion (deprecation of `.eslintrc.*` formats)
- New OWASP Top 10 edition (rules need re-mapping)
- CodeQL pricing / availability change
- New SARIF version (currently 2.1.0)
- Annual review on 2027-05-24

---

## 11. See Also

| Need | Skill |
|---|---|
| Dependency CVE check (orthogonal to SAST) | `dep-currency-check` |
| Secrets in code (orthogonal to SAST) | `secret-scanning` |
| LLM-specific defects (prompt injection, etc.) | `llm-security` |
| Python web-app auth patterns | `python-auth-security` |
| The G_SECURE gate this feeds | `~/.claude/skills/_meta/gates.py` |
| Pre-commit hook patterns (POSIX + Windows hardened PS1) | `dep-currency-check` (precedent) |
| Bootstrap hook offer | `installer/bootstrap-environment.py` |
