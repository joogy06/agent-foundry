```radar
name: Git AI
slug: git-ai
category: git-tooling
alternative_to: Co-Authored-By trailers and manual notes for tracking AI-written code
homepage: https://usegitai.com
repo: https://github.com/git-ai-project/git-ai
licence_code: Apache-2.0
licence_other: n/a (Git AI for Teams is a separate paid product)
cost: CLI free; Git AI for Teams (prompt store, analytics) paid, early access, no public price
maturity: v1.7.5 (2026-09-09)
mcp: unknown
ring: assess
reviewed: 2026-10-29
review_by: 2027-01-27
suggested_by: owner (2026-10-29)
related_skills: [claude-code-cli, codex-orchestration, process-observation]
tags: [git, ai-attribution, git-notes, provenance, ai-authored-code, blame, agent-hooks, claude-code, codex]
verdict: Apache-2.0 git extension recording line-level AI authorship in git notes. Useful provenance; it rewrites agent hooks, so trial only in a throwaway home.
origin: owner request 2026-10-29 (tool-radar intake)
```

## What it is

A git extension that records which lines an AI agent wrote, and with which agent, model and session. It hooks the coding agents (not git) to take checkpoints after each edit, and on commit writes line-level attribution to git notes under `refs/notes/ai`.

## Verified facts

- VERIFIED: Apache-2.0; repository github.com/git-ai-project/git-ai (originally acunniffe/git-ai); about 2.9k stars. Source: https://github.com/git-ai-project/git-ai (read 2026-10-29).
- VERIFIED: latest tag v1.7.5, dated 2026-09-09. Source: https://github.com/git-ai-project/git-ai/tags (read 2026-10-29).
- VERIFIED: install is a piped script (`curl -sSL https://usegitai.com/install.sh | bash`; a PowerShell equivalent on Windows); no per-repo setup or git hooks. Source: https://github.com/git-ai-project/git-ai (read 2026-10-29).
- VERIFIED: supports Claude Code, Codex, Cursor, GitHub Copilot, OpenCode, Windsurf, Gemini, Junie and others; blame plugins for VS Code, Cursor, Windsurf, Antigravity and Emacs magit. Source: same (read 2026-10-29).
- VERIFIED: it "registers a pre/post tool-calls for every supported agent"; checkpoints live in `.git/ai`; attribution goes only to `refs/notes/ai`. Source: https://usegitai.com/docs/cli/how-git-ai-works (read 2026-10-29).
- VERIFIED: it "manages the agent hooks and checks/updates them daily". Source: README FAQ, https://github.com/git-ai-project/git-ai (read 2026-10-29).
- VERIFIED: prompts ARE saved by default, locally and outside git, after being "scanned and redacted"; the notes hold only links to sessions. Sessions can instead live in Git AI Cloud or a self-hosted store. Sources: https://github.com/git-ai-project/git-ai and https://usegitai.com/docs/cli/how-git-ai-works (read 2026-10-29).
- VERIFIED: authorship is not kept through server-side squash or rebase merges unless you run Git AI for Teams or the open-source CI action (`git ai ci github install`). Source: https://usegitai.com/docs/team-usage/ci-workflows (read 2026-10-29).
- LIKELY: GitHub does not show git notes in its web UI. Source: https://usegitai.com/docs (read 2026-10-29, via search summary).
- VERIFIED: Thoughtworks Technology Radar Vol. 34 (April 2026) places Git AI in Assess. Source: https://www.thoughtworks.com/radar/tools/git-ai (read 2026-10-29).
- UNCERTAIN: telemetry is not addressed on the pages read; no MCP mentioned.
- VERIFIED (local, read-only): not installed (no `git-ai` on PATH; no `refs/notes/ai` in the foundry repo). Source: local read-only check (2026-10-29).

## Other candidates

Several projects share the name; this entry is the best known.

- jgalego/git-ai (PyPI `git-ai-tracker`, MIT, 1 star, "highly experimental"): a different `git ai track` command set that also uses `refs/notes/ai`. Do not mix the two in one repo.
- esafak/git-ai, BoSeal/git-ai: unrelated AI-in-git helpers (commit message generation and similar).

## Claims that are false or overstated

- "No setup": true per repo, but it changes every supported agent's hook configuration on the machine and re-applies that daily.

## Foundry fit

- Fills a real gap: foundry records which seat reviewed what (process observation, ledgers), but not which lines in a commit an agent wrote.
- Conflict: foundry's `~/.claude/settings.json` hooks are installer-managed (`install.py` injects the SessionStart hooks); a tool that rewrites agent hooks daily is unbacked state the installer does not know about. A trial must use a throwaway home, never the live one.
- No conflict with the commit-message policy: attribution goes into git notes, not trailers.
- Install is `curl | bash`; it needs the owner's approval and an intake scan first.
- Prompts are stored locally by default (redacted, but redaction is not a guarantee): keep secrets out of agent prompts, as the harness already requires for codex briefs.

## Decision and next step

Assess. Next step, if the owner wants AI-authorship provenance: install into a throwaway `HOME` and a scratch repo, record exactly which agent config files it writes, and check whether its hooks coexist with the installer's. Only then consider trial.

## Sources

- https://github.com/git-ai-project/git-ai (read 2026-10-29)
- https://github.com/git-ai-project/git-ai/tags (read 2026-10-29)
- https://usegitai.com/docs/cli/how-git-ai-works (read 2026-10-29)
- https://usegitai.com/docs/team-usage/ci-workflows (read 2026-10-29)
- https://www.thoughtworks.com/radar/tools/git-ai (read 2026-10-29)
