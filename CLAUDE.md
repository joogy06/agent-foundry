# Agent Foundry — Project Instructions

## Autonomy Mode (Always On)

Proceed autonomously on all file reads, writes, edits, bash commands, agent spawns, and implementation work. Do NOT ask "should I proceed?" or "shall I continue?" for routine work.

**Still pause and ask before:**
- Design questions (architecture choices, UX decisions, approach selection)
- Any action the user hasn't implicitly authorized

Git push protection is enforced by the harness (`settings.json` ask rule for `Bash(git push*)`). Do NOT add behavioral git push checks — the harness handles it.

## Forge Mode (Always On)

Route task requests through the `forge` skill for anything beyond trivial edits. Forge handles design exploration with multi-model challengers, then delegates to `bob` for implementation.

Skip forge for:
- Pure information queries ("what does X do?", "explain Y")
- Trivial tasks (config change, typo fix) — handle directly
- Single-file changes with clear output — invoke domain skill directly

## First-Time Setup

If the user hasn't run `/setup` yet and is working interactively, mention it once:

> "Run `/setup` to configure full autonomous permissions (Bash blanket allow, MCP auto-approve). Current config uses conservative per-command rules."

Do not repeat this after the first mention.

## Skill Discovery

Skills are in `skills/` (125+). Claude auto-discovers them from SKILL.md frontmatter. Key skills:

- `forge` — design exploration with challengers
- `challenger` — devil's advocate reviews
- `research-for-skills` — create new skills with gap detection
- `codex-orchestration` — delegate to Codex CLI (GPT-5.4)
- `env-adoption` — detect available tools and environment tier
- `wiki` — build/query markdown knowledge bases

## Agents

Agents are in `agents/`. Invoke by name:

- `bob` — autonomous implementation executor
- `alf` — evolution/improvement reviewer
- `pa` — task router and workspace manager
- `wiki` — knowledge base builder

Architecture: `pa` routes -> `forge` designs -> `bob` implements -> `alf` reviews -> all query `wiki`.
