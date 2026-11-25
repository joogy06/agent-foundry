```radar
name: OpenCode
slug: opencode
category: coding-agent
alternative_to: Claude Code, Codex CLI (terminal coding agent)
homepage: https://opencode.ai
repo: https://github.com/anomalyco/opencode
licence_code: MIT
licence_other: n/a
cost: free; you pay the model provider you connect
maturity: v1.19.5 (date not recorded in #369)
mcp: client
ring: assess
reviewed: 2026-10-29
review_by: 2027-01-27
suggested_by: owner (shared video, task #369)
related_skills: [claude-code-cli, codex-orchestration, research-for-skills]
tags: [coding-agent, cli, terminal, open-source, multi-provider, local-models, mcp-client, skills-consumer, agents-md]
verdict: MIT terminal coding agent, 75+ providers; already reads ~/.claude/skills. A possible skills consumer, not a delegate.
origin: #369, docs/reviews/2026-10-29-video-tools-369.md
```

## What it is

An open-source terminal coding agent (formerly sst/opencode) that works with many model providers, including local models.

## Verified facts

- VERIFIED: MIT licence, repository github.com/anomalyco/opencode (moved from sst/opencode); latest release v1.19.5. Source: https://github.com/anomalyco/opencode (via #369, 2026-10-29).
- VERIFIED: 75+ providers and local models; acts as an MCP client. Source: https://opencode.ai (via #369, 2026-10-29).
- VERIFIED: GitHub pull requests from issues work only after GitHub App, workflow and API-key setup. Source: https://opencode.ai (via #369, 2026-10-29).
- VERIFIED: reads `~/.claude/skills` and falls back to `~/.claude/CLAUDE.md` when no AGENTS.md exists. Source: https://opencode.ai (via #369, 2026-10-29).
- VERIFIED (local, read-only): not installed on the foundry host; not listed in `install.py` SKILL_CONSUMERS. Source: #369 review.

## Claims that are false or overstated

- "Opens PRs from issues": not automatic; it needs a GitHub App, a workflow and an API key.

## Foundry fit

- Because it reads `~/.claude/skills`, it would load foundry skills with no install step, and also the Claude-specific global rules through the CLAUDE.md fallback.
- If adopted: declare it in `install.py` SKILL_CONSUMERS and give it a lean global AGENTS.md so it does not inherit Claude-only rules.
- Not a delegate: second-opinion seats are fixed by the roster and the provider-diversity rule.

## Decision and next step

Assess. Document only. If the owner wants a second skills consumer, the next step is the SKILL_CONSUMERS entry plus a lean AGENTS.md, tested on a throwaway home.

## Sources

- https://github.com/anomalyco/opencode (via #369, 2026-10-29)
- https://opencode.ai (via #369, 2026-10-29)
- Foundry review: docs/reviews/2026-10-29-video-tools-369.md (task #369), which checked each claim against primary sources on 2026-10-29. The review keeps its conclusions, not per-fact read receipts: facts marked "via #369" are inherited from it, and the URL beside each is the primary page for that fact (repo URLs from the review or the video's resource page), not a fresh re-read.
