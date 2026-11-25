# Skill Authoring Rules

Reference for `research-for-skills` Step 7 (drafting). Originally cherry-picked from `superpowers:writing-skills` v5.0.6 (historical credit) with local overrides. The methodology below is now the canonical source for skill drafting in this ecosystem.

## Contents

- Frontmatter (mandatory)
- Description (critical)
- Size, references and paths
- Structure Template
- Word Count Limits
- Content Rules
- CSO (Claude Search Optimization)
- Cross-Model Compatibility
- Naming Conventions
- Testing (reference — do not duplicate)
- Last step: the audit
- Quality Checklist

## Frontmatter (mandatory)

```yaml
---
name: skill-name-with-hyphens
description: "[Subject]: [what the skill does]. Use when [the situations that call for it]."
---
```

- `name`: lowercase letters, digits and single hyphens, at most 64 characters, the same as the directory name. The reserved words `anthropic` and `claude` are not allowed in a new name.
- `description`: see the next section. The specification limit is 1,024 characters (claude.ai uploads and the Skills API reject more); Claude Code cuts each listing entry at 1,536 characters and drops whole descriptions when the listing is over budget, so short descriptions are the ones that survive.
- Allowed top-level keys are the specification keys (`name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`) and the keys Claude Code reads (for example `when_to_use`, `disable-model-invocation`, `user-invocable`, `model`, `effort`, `context`, `paths`). The one list is `SPEC_KEYS` and `CLAUDE_CODE_KEYS` in `_meta/skill_audit.py`; the audit and `verify-skill-portability.sh` both read it.
- Custom data (version, family, disambiguation, tags, author) goes under `metadata:` as quoted single-line strings. Any other top-level key fails the audit (A1); an unquoted number, boolean or date under `metadata:` fails too (A2).

```yaml
metadata:
  version: "1.2.0"
  family: "performance"
```

- Use a Claude Code key only when the skill needs what it does. Claude Code keys are a hard error on claude.ai upload and in the Skills API, which accept the six specification keys only.

## Description (critical)

**Open with the subject, say what the skill does, then say when to use it.**

- **Subject first.** The first words are the domain words a request would contain (`WooCommerce checkout`, `Db2 for z/OS`). Listings are cut from the end and scanned from the start, so an opening such as "Use when" spends the strongest position on words every skill shares. The audit fails a description that opens with "Use when" (A5).
- **What plus when.** One clause for what the skill covers, one for the situations that call for it. A description that gives only triggers leaves the model guessing what it would get; one that gives only the subject never triggers.
- **Third person.** The description is injected into the system prompt: "Processes…", "Covers…", never "I can…" or "You can…".
- **About 200 characters.** The audit fails over 250 (A5). No XML-like tags such as `<name>` (A4).
- **Name the capability, not the procedure.** Local testing showed that when a description narrates the steps, the model follows the description and skips the body: one saying "code review between tasks" produced ONE review although the body required TWO. State what the skill covers; leave the order of work to the body.

```yaml
# BAD: opens with "Use when" and narrates the procedure
description: Use when executing plans - dispatches subagent per task with code review between tasks

# BAD: triggers only; nothing says what the skill provides
description: Use when executing implementation plans with independent tasks in the current session

# GOOD: subject, what, when
description: "Plan execution with subagents: task dispatch, review gates and result collection. Use when an implementation plan has independent tasks to run in the current session."
```

## Size, references and paths

| Rule | Why | Audit |
|---|---|---|
| `SKILL.md` is at most 500 lines | The whole body enters context when the skill loads; detail belongs in references, read on demand | A6 |
| Every rule that must hold sits in the first 20 KB of `SKILL.md` | After a context compaction only the start of an invoked skill is re-attached (about 5,000 tokens) | A11, N1 |
| References are one level deep: `SKILL.md` names each reference file by its skill-relative path (`references/limits.md`, not the bare file name) | A file reached only through another reference gets a partial read or none | A7, A10 |
| A reference over 100 lines opens with a contents list (`## Contents`) in its first 30 lines | A partial read still shows what the file holds | A8 |
| The skill's own files are cited by skill-relative path (`references/x.md`, `scripts/y.sh`) | A home path breaks in a mirror, a plugin or a checkout | A9 |

A home path to a shared helper or to another skill (`_meta/`, a sibling skill directory) is reported as a note (N2), not a fail.

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

## Last step: the audit

When the draft is complete, run the audit and fix every `fail` before review:

```bash
python3 skills/_meta/skill_audit.py audit --only <name> --strict        # from the repo root
python3 skills/_meta/skill_audit.py audit --root <dir> --strict         # a draft outside the repo: <dir> holds <name>/SKILL.md
```

Exit 0 with no `fail` line means the frontmatter, description, size, reference and path rules above hold. Notes (N1, N2) never fail.

## Quality Checklist

Before deployment, verify:

- [ ] Name: lowercase, hyphens, verb-first, no reserved word
- [ ] Description: subject first, what plus when, third person, about 200 chars, no "Use when" opening, no procedure narration
- [ ] Frontmatter: specification and Claude Code keys only; custom data under `metadata:` as quoted strings
- [ ] `SKILL.md` at most 500 lines; must-hold rules in the first 20 KB
- [ ] References one level deep, each named in `SKILL.md`; contents list in any reference over 100 lines
- [ ] Own files cited by skill-relative path
- [ ] Word count within limits
- [ ] Anti-patterns table present
- [ ] Specific data with sources (no generic advice)
- [ ] Decision frameworks (tables, not prose)
- [ ] Cross-model compatible language
- [ ] CSO keywords throughout
- [ ] Codex symlink created (unless in skip list)
- [ ] Last: `skill_audit.py audit --only <name> --strict` prints no `fail`
