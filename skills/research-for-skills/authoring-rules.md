# Skill Authoring Rules

Reference for `research-for-skills` Step 7 (drafting). Originally cherry-picked from `superpowers:writing-skills` v5.0.6 (historical credit) with local overrides. The methodology below is now the canonical source for skill drafting in this ecosystem.

## Frontmatter (mandatory)

```yaml
---
name: skill-name-with-hyphens
description: Use when [triggering conditions only]
---
```

- `name`: lowercase, hyphens only, no special chars. Prefer verb-first (e.g., `deploying-containers` not `container-deployment`)
- `description`: **max 1024 characters** (hard limit enforced by Claude Code — skills with longer descriptions are silently skipped at load time). Aim for under 500 chars. Total frontmatter block must also stay under 1024 chars.
- Description MUST start with "Use when..."
- Third person (injected into system prompt context)

## The Description Trap (critical)

**Description = triggering conditions ONLY. Never summarize the skill's workflow.**

Testing proved that when a description summarizes workflow, Claude shortcuts to the description and skips the skill body. A description saying "code review between tasks" caused Claude to do ONE review, even though the skill's flowchart showed TWO reviews.

**Local policy divergence:** Anthropic's official docs currently recommend "what + when" in descriptions. Local evidence shows workflow summaries cause skill-skipping behavior. We intentionally diverge: descriptions contain ONLY triggering conditions.

```yaml
# BAD: Summarizes workflow — Claude may follow this instead of reading skill
description: Use when executing plans - dispatches subagent per task with code review between tasks

# GOOD: Just triggering conditions
description: Use when executing implementation plans with independent tasks in the current session
```

## Structure Template

```markdown
# Skill Name

## Overview
Core principle in 1-2 sentences.

## When to Use
Bullet list with SYMPTOMS and use cases.
When NOT to use.

## [Main Sections]
Tables for scanning. Specific data with sources.
Decision frameworks (when X vs Y).

## Anti-Patterns
| Don't | Why |
|-------|-----|
```

**Anti-patterns table is mandatory.** Every skill must have one.

## Word Count Limits

| Skill Type | Target | Max |
|-----------|--------|-----|
| Frequently-loaded | <500 words | 500 |
| Standard | <800 words | 1200 |
| Reference-heavy | SKILL.md <500, separate reference files | No hard max on reference files |

**If over 1200 words:** split into SKILL.md (orchestration) + reference files (heavy content).
Supporting files only for: heavy reference (100+ lines) or reusable tools/scripts.

## Content Rules

- **Specific data** with sources and dates (no generic advice)
- **Actionable rules** an agent can follow mechanically
- **Decision frameworks** using tables (when X vs Y), not prose
- **Only VERIFIED/LIKELY findings** from web-research — flag UNCERTAIN explicitly
- **No vendor marketing as fact** — check web-research confidence levels
- **Scannable structure** — tables, bullets, code blocks. Minimize paragraph prose.

## CSO (Claude Search Optimization)

Skills are discovered by description matching. Optimize for discovery:

- Include **error messages** agents might encounter: "ENOTEMPTY", "Hook timed out"
- Include **symptoms**: "flaky", "hanging", "zombie", "pollution"
- Include **synonyms**: "timeout/hang/freeze", "cleanup/teardown/afterEach"
- Include **tool names**: actual commands, library names, file types
- Description must answer: "Should I read this skill right now?"

## Cross-Model Compatibility

Skills shared with Codex via symlinks must use tool-agnostic language:

| Instead of | Write |
|-----------|-------|
| "Use the Read tool to..." | "Read the file..." |
| "Use the Agent tool to spawn..." | "Delegate to a subagent..." |
| "Use the Grep tool..." | "Search for..." |
| "Invoke the `X` skill" | "Apply the patterns from the `X` skill" |
| "Claude Code will..." | "The AI agent should..." |

If tool-specific references are unavoidable, add:
```markdown
> **Tool mapping:** Claude uses `Read`/`Edit`/`Grep`. Codex uses shell commands (`cat`/`sed`/`rg`).
```

## Naming Conventions

- Verb-first preferred: `creating-skills` not `skill-creation`
- Hyphens only: `condition-based-waiting` not `condition_based_waiting`
- Descriptive: `root-cause-tracing` not `debugging-techniques`
- Gerunds (-ing) work well for processes: `deploying-containers`, `testing-apis`

## Testing (reference — do not duplicate)

After writing, apply TDD methodology (the steps follow inline; full SDLC enforcement lives in `development-lifecycle`):
- RED: run pressure scenarios WITHOUT skill, document baseline
- GREEN: write skill addressing baseline failures
- REFACTOR: close loopholes, build rationalization table

Do not deploy untested skills. See `development-lifecycle` for the full SDLC enforcement and the inline steps above for skill-specific patterns.

## Quality Checklist

Before deployment, verify:

- [ ] Name: lowercase, hyphens, verb-first
- [ ] Description: starts "Use when...", triggers only, no workflow summary, <500 chars
- [ ] Word count within limits
- [ ] Anti-patterns table present
- [ ] Specific data with sources (no generic advice)
- [ ] Decision frameworks (tables, not prose)
- [ ] Cross-model compatible language
- [ ] CSO keywords throughout
- [ ] Codex symlink created (unless in skip list)
