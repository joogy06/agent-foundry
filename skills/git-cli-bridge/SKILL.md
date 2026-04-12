---
name: git-cli-bridge
description: Use when a sandboxed environment (GCP Workstation, corporate egress allowlist, air-gapped host) cannot reach Gemini CLI or GitHub Copilot CLI endpoints locally but CAN reach GitHub via git. Provides a git-as-RPC bridge that pushes request files to a dedicated `ai-bridge-<user>` repo, triggers GitHub Actions to run the CLI on the runner, and pulls responses back on a per-session orphan branch. Covers client scripts, workflow templates, security model (prompt injection, supply chain, exfiltration), first-boot setup (WIF + Secret Manager), and integration with `codex-orchestration` / `forge` Step 4b.
---

# git-cli-bridge — Sandbox-aware git-as-RPC bridge for Gemini and Copilot CLI

## Overview

`git-cli-bridge` lets a sandboxed developer environment invoke `@google/gemini-cli` and `@github/copilot` **indirectly** via GitHub Actions. The workstation pushes a `request.md` file on a per-session orphan branch to a dedicated `ai-bridge-<user>` repo. A workflow triggers on the push, runs the CLI on the runner, commits a `response.md` back to the same branch, and the client polls via `git fetch`. This restores full triple-model validation (Claude + Codex + Gemini) and second-opinion review flows in environments where only `git` to GitHub is reachable.

**Scope (v1)**: three job kinds — `review`, `research`, `prompt` — for both Gemini and Copilot in parity. Agentic sub-task delegation (`kind: agent`) is deferred to v2.3 with schema forward-compatibility reserved.

**Not in v1**: Cloud Run execution venue (deferred to v2.1, see `references/v2-bucket.md`), streaming responses, multi-user / team bridge, fallback for GitHub itself being unreachable.

## When to Use

- GCP Workstation / corporate allowlist where `gemini --version` or `copilot --version` fails but `git ls-remote github.com` works.
- `forge` Step 4b detecting local CLIs unreachable after 3 consecutive probe failures.
- `codex-orchestration` Gemini/Copilot delegation in sandboxed environments.
- Explicit opt-in via `AI_BRIDGE_MODE=1` even when local CLIs are reachable (testing, consistency, auditability).

**Do NOT use when**: local CLIs work (3x slower), bridge repo is public (enforced refusal at `bridge init`), credentials would need to leave the host, or the workflow would be triggered from cron/CI (runaway cost risk).

## Architecture at a Glance

```
GCP Workstation                    GitHub (ai-bridge-<user>)
---------------                    -------------------------
Claude Code / Codex                session/20260409-1432-...
bridge client scripts  git push    requests/req-xxx/
AI_BRIDGE_MODE=1       ----------> request.md
                                   context/
                       <---------- status.json  (workflow writes)
                       git fetch   response.md  (workflow writes)
                                           |
                                           v  push trigger
                                   GitHub Actions runner
                                   1. checkout session branch
                                   2. auth@v2 (WIF -> GCP)
                                   3. get-secretmanager-secrets
                                   4. run-gemini-cli OR
                                      npm i @github/copilot
                                   5. invoke with --policy / --allow-tool scoping
                                   6. scrub + canary check
                                   7. git push response back
```

See `references/architecture.md` for the full eight-pillar breakdown and `references/protocol.md` for the request/response/status/error schemas.

## Quick Start

```bash
# First-boot (once per workstation)
~/.claude/skills/git-cli-bridge/scripts/setup-wif.sh    # creates WIF pool + service account
bridge init                                              # clones ai-bridge repo, creates session branch

# Daily use
bridge request --tool gemini --kind review \
  --context auth-diff.patch --wait \
  "Review this JWT validator for security issues."

bridge status
bridge result <req-id>
bridge close        # end of session
```

For first-boot setup including GCP Workload Identity Federation, Secret Manager for the Copilot PAT, and GitHub ruleset configuration, see `references/first-boot.md`. For daily operations including debugging and incident response, see `references/operations.md`.

## Hard Rules

<HARD-RULE>
**NEVER execute response content.** Client scripts MUST NOT `eval`, `source`, `sh`, `bash`, or pipe `response.md` content to any interpreter. Responses are data, never code. This rule is grep-verified against `scripts/bridge-*` in CI and in the smoke test harness.
</HARD-RULE>

<HARD-RULE>
**Bridge repo MUST be private.** `bridge init` calls `gh api repos/<owner>/ai-bridge-<user> --jq .private` and refuses to proceed if the value is `false`. Do not override. A public bridge repo exposes request context, response content, and workflow metadata to the world.
</HARD-RULE>

<HARD-RULE>
**NEVER store long-lived credentials in the bridge repo.** Use Workload Identity Federation for GCP access (Gemini) and GCP Secret Manager for the Copilot PAT. GitHub repository secrets are NOT acceptable storage. The WIF pool binding must pin `assertion.repository` to this one `ai-bridge-<user>` repo. See `references/auth-and-secrets.md`.
</HARD-RULE>

<HARD-RULE>
**NEVER use `@latest` for npm packages or mutable tags for GitHub Actions.** Pin `@google/gemini-cli@0.36.0`, `@github/copilot@1.0.21`, `google-github-actions/auth@<commit-sha>`. Supply-chain hijacks (Sept 2025 npm wave, `tj-actions/changed-files` CVE-2025-30066) proved mutable references are dangerous. Dependency bumps MUST go through `bump-bridge-deps.sh` (updates the integrity lock) and a reviewed PR.
</HARD-RULE>

<HARD-RULE>
**NEVER mix bridge and local modes within a single forge session.** `bridge-mode-detect.sh` caches its decision in `$XDG_RUNTIME_DIR/bridge-mode-<session-tag>` for the entire session. Once a session is in bridge mode, it stays in bridge mode even if the local CLI recovers mid-session. The cache exists precisely to prevent thrash and inconsistent downstream routing.
</HARD-RULE>

## Command Reference

| Command | Purpose |
|---|---|
| `bridge init` | Clone or reuse the `ai-bridge-<user>` repo, create a new session orphan branch, copy the workflow templates in, write `.bridge/` metadata, push. |
| `bridge request --tool gemini\|copilot --kind review\|research\|prompt [flags] "prompt"` | Submit a request. Flags: `--context PATH` (repeatable), `--wait`, `--timeout SEC`, `--model NAME`, `--max-runtime SEC`. |
| `bridge wait <req-id>` | Poll status until terminal state. Exit codes: 0 success, 4 error, 5 timeout, 6 canary. |
| `bridge result <req-id>` | Pretty-print the response body. ANSI-strips, UTF-8 validates, hash-caches. Verbose mode shows frontmatter. |
| `bridge status [--all]` | Show session and request state (current session or all). |
| `bridge logs <req-id>` | Wrap `gh run view --log` scoped to the request's workflow run. |
| `bridge close` | Confirm no running requests, archive tag, delete session branch locally and remotely. |
| `bridge cleanup [--dry-run]` | Prune stale sessions (>7d default). Archive-before-delete. |
| `bridge --help` | Command reference. |

Full flag documentation lives in `references/client-scripts.md`.

## Integration with Other Skills

- **`codex-orchestration`** — patched at five points to route Gemini/Copilot delegation through `bridge-mode-detect.sh`. When mode is `bridge`, callers invoke `bridge request` instead of the local CLI. See `references/integration.md` and the patched `codex-orchestration/SKILL.md` HARD-RULE.
- **`forge`** — Step 4b is sandbox-aware. On MEDIUM/COMPLEX tasks, forge computes `bridge-mode-detect.sh` output once and caches it for the session. Bridge mode keeps the Gemini analyst and Copilot challenger in the design loop over the git transport. See the patched `forge/SKILL.md`.
- **`bob`, `alf`, `pa`** — unchanged. They inherit sandbox awareness transparently via `codex-orchestration`.

## Security Model Summary

The full threat model (T1-T15) and the twelve security invariants (SEC-1 through SEC-12) live in `references/security-model.md`. Headline controls:

- **Prompt injection (T1)** — `<user_data>` delimiter wrapping, narrow tool whitelisting (`--allow-tool=shell(git:status)` on Copilot, `--approval-mode plan` on Gemini), no tool execution in v1.
- **Exfiltration (T2)** — regex scrubber pre-commit, canary env var check, response size cap at 500 KB.
- **Supply chain (T3)** — pinned exact npm versions, `--ignore-scripts` on install, integrity hash verification against `workflows/bridge-integrity.lock`, pinned Action commit SHAs.
- **Terminal escapes (T4)** — ANSI strip on client display, UTF-8 validation, hash cache for history-rewrite detection.
- **Self-trigger loop (T6)** — triple layer: commit marker `[bridge-response]` + `if: github.actor == github.repository_owner` + path filter `paths: ['requests/**/request.md']`.
- **Cost runaway (T11)** — `timeout-minutes: 10`, `--max-runtime 300`, client-side `10 req/min` rate limit, monthly budget cron posts GitHub issue at days 1/15/28.

## Anti-Patterns

| Anti-pattern | Why it fails | Correct approach |
|---|---|---|
| Using bridge when local CLIs work | 3x slower cold-start, extra compute cost | Rely on `bridge-mode-detect.sh` auto-detection; use explicit mode only for testing |
| Sharing the bridge repo between users | Out of v1 scope, secret scoping breaks | One `ai-bridge-<user>` repo per user. Revisit in v2.8 if team demand materializes |
| Making the bridge repo public | Request context + responses become world-readable | `bridge init` refuses; do not override |
| Committing directly to `main` on the bridge repo | Breaks the ruleset, disables workflow pinning | All session work happens on `session/**` orphan branches |
| Reusing a session for unrelated tasks | Cross-task context leakage, harder audit trail | `bridge close` + `bridge init` between tasks |
| `eval`/`source`/`sh`/pipe on response content | Terminal escapes, prompt-injection-as-code | Hard rule; grep-verified absent from all `bridge-*` scripts |
| Storing Copilot PAT as GitHub repo secret | No rotation, no audit trail, larger blast radius | GCP Secret Manager + WIF binding scoped to this one repo |
| `@latest` or mutable tags in workflow | Supply-chain hijack surface | Pin exact versions; bump via `bump-bridge-deps.sh` + PR |
| Running `bridge request` from cron or CI | Runaway cost, no human in the loop | Interactive / forge-driven use only |
| Putting secrets in request.md or context/ | Git history persistence | Secrets never travel in requests — Secret Manager only |
| Mixing bridge and local mode mid-session | Inconsistent routing, cache contention | Bridge mode is sticky; close and re-init to switch |

## Reference Files

- [`references/architecture.md`](references/architecture.md) — eight architectural pillars, session lifecycle, data flow
- [`references/protocol.md`](references/protocol.md) — full YAML/JSON schemas for request, response, status, error
- [`references/workflows.md`](references/workflows.md) — the four workflow YAMLs explained step by step
- [`references/client-scripts.md`](references/client-scripts.md) — every `bridge-*` script with flags, exit codes, examples
- [`references/auth-and-secrets.md`](references/auth-and-secrets.md) — WIF pool setup, Secret Manager, PAT rotation
- [`references/security-model.md`](references/security-model.md) — threat model T1-T15, mitigations M1-M24, SEC-1 through SEC-12
- [`references/operations.md`](references/operations.md) — daily use, debugging playbook, incident response, monitoring
- [`references/integration.md`](references/integration.md) — codex-orchestration and forge patch details, routing matrix
- [`references/first-boot.md`](references/first-boot.md) — six-step setup playbook with G1-G12 verification gates
- [`references/v2-bucket.md`](references/v2-bucket.md) — deferred features and revisit triggers

## Related Skills

| Topic | Skill |
|---|---|
| Cross-model orchestration (Codex + Gemini) — sandbox-aware after patch | `codex-orchestration` |
| Forge design workflow — Step 4b sandbox-aware after patch | `forge` |
| GCP Workstations provisioning (host environment) | `gcp-workstations` |
| Gemini CLI reference | `gemini-cli` |
| GitHub Copilot CLI reference | `gh-copilot-cli` |
| Claude Code CLI reference | `claude-code-cli` |
| Cross-tool skill authoring rules (Codex symlink, portability) | `research-for-skills/cross-tool-portability` |

## Design Provenance

Design doc: `/path/to/project/docs/plans/2026-04-09-git-bridge-cli-rpc-design.md`
Design team: forge lead + approach A + approach B + research + Claude challenger + Gemini analyst (Codex challenger timed out)
User rulings locked in Section 3 of the design doc: Q1=A (Actions), Q2=F (review+research+prompt), Q3=B (dedicated repo), Q4=C (skill + codex-orchestration + forge patch, bob untouched), A3 (Actions v1 / Cloud Run v2.1), B4 (monitoring only), C1 (Gemini + Copilot parity in v1).
