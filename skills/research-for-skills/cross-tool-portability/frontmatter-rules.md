# Frontmatter Rules

What goes in a SKILL.md frontmatter when the skill must work across Claude Code, Antigravity CLI (`agy`), Codex CLI, and (via AGENTS.md) GitHub Copilot CLI.

## Contents

- The format
- Which keys are allowed
- What goes where
- `name` rules
- `description` rules
- YAML escaping
- Validation
- Anti-patterns

## The format

```yaml
---
name: <lowercase letters, digits and single hyphens, max 64 chars>
description: "<single line: the subject, what the skill does, when to use it; about 200 chars>"
metadata:
  version: "1.0.0"
---
```

`name` and `description` are required. Everything else is optional, and most skills need nothing else.

## Which keys are allowed

A top-level key is legal when it is on one of two lists. Both are data at the top of `_meta/skill_audit.py` (`SPEC_KEYS`, `CLAUDE_CODE_KEYS`); the audit and `scripts/verify-skill-portability.sh` read them from there, so that file is the list to check.

| Set | Keys | Where it works |
|---|---|---|
| Specification (agentskills.io) | `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools` | Every tool; the only keys claude.ai upload, the Skills API and `package_skill.py` accept |
| Claude Code | `when_to_use`, `disable-model-invocation`, `user-invocable`, `model`, `effort`, `context`, `paths` and the rest of `CLAUDE_CODE_KEYS` | Claude Code. Codex ignores a key it does not know; claude.ai upload and the Skills API reject it with a hard error |

Any other top-level key fails the audit (A1). **Custom data goes under `metadata:` as strings**: quote every value, because an unquoted number, boolean or date is not a string and fails (A2).

A skill that will be uploaded to claude.ai or shipped through the Skills API keeps to the six specification keys.

## What goes where

| You want to specify... | Put it in... |
|---|---|
| Pre-approved tools | `allowed-tools` (a specification key) |
| Model, effort, forked context, path scoping | The Claude Code key (`model`, `effort`, `context`, `paths`), when the skill needs it and runs in Claude Code |
| Extra trigger phrases | `when_to_use` (Claude Code), or the last clause of `description` |
| Version | `metadata.version: "1.0.0"` |
| Tags, family, disambiguation, author | A quoted string under `metadata:` |
| A tool list or input contract for the reader | A section in the body |

## `name` rules

| Rule | Pattern |
|---|---|
| Allowed characters | `^[a-z0-9-]+$` |
| Max length | 64 characters |
| Must match directory name | A skill in the directory `foo-bar/` is named `foo-bar` |
| No reserved word | `anthropic` and `claude` fail the audit in a new name (A3) |
| Single hyphens, none leading or trailing | `foo--bar` and `-foo` are INVALID |
| No underscores | `foo_bar` is INVALID |
| No uppercase | `FooBar` is INVALID |
| No dots, slashes, spaces | All INVALID |

Examples:

| Name | Valid? |
|---|---|
| `gh-copilot-cli` | YES |
| `gcp-workstations` | YES |
| `gh_copilot_cli` | NO (underscore) |
| `GhCopilotCLI` | NO (uppercase) |
| `gh.copilot.cli` | NO (dot) |
| `gh-copilot-cli-v2.0` | NO (dot) |
| `claude-helper` | NO for a new skill (reserved word) |
| `a` | YES (technically valid; not useful) |
| `a-very-long-skill-name-that-goes-on-and-on-...` | DEPENDS on length (≤64) |

## `description` rules

| Rule | Notes |
|---|---|
| Single line | NO line breaks. NO multi-line YAML. |
| Opens with the subject | The domain words first. A description that opens with "Use when" fails the audit (A5) |
| Says what and when | What the skill covers, then the situations that call for it |
| Third person | "Covers…", "Processes…"; never "I can…" or "You can…" |
| Length | About 200 characters; the audit fails over 250 (A5). The specification limit is 1,024 |
| No XML-like tags | `<component>` in a description fails the audit (A4) |
| Cross-model neutral | Doesn't say "Use the X tool" — say "do X" |

### Good descriptions

```yaml
description: "Claude Code CLI (`claude`): headless and interactive modes, flags, agents, plugins, MCP servers, hooks, settings and sessions. Use when running, scripting or configuring the CLI."
```

```yaml
description: "Cross-CLI skill portability: frontmatter, naming, body length, install matrix and common mistakes. Use when authoring a skill that must load in Claude Code, Codex CLI, agy and Copilot CLI."
```

### Bad descriptions

```yaml
description: A skill for doing things.
# ❌ Vague, no subject, no triggers; the model won't know when to load it
```

```yaml
description: Use when integrating with REST APIs.
# ❌ Opens with "Use when" and never says what the skill provides
```

```yaml
description: "Multi-line\ndescription\nwith line breaks"
# ❌ Multi-line. Single-line YAML string only.
```

```yaml
description: File reading with the Read tool. Use when files must be read.
# ❌ Tool-specific (Read tool). Cross-model compat broken.
```

```yaml
description: |
  Long
  multi
  line
# ❌ YAML block scalar — same as multi-line, not allowed
```

## YAML escaping

If your description contains a colon, wrap in quotes:

```yaml
description: "REST API integration: HTTP methods, status codes, content negotiation. Use when calling or designing an HTTP API."
```

If it contains a quote, escape or use single-quoted form:

```yaml
description: 'Tutorial scaffolding for "hello world" examples. Use when writing a first-run tutorial.'
```

If it contains both, use single quotes outside, escape internal singles:

```yaml
description: 'Preference handling for "user input" and the user''s saved settings. Use when a form reads stored preferences.'
```

## Validation

The validator script `scripts/verify-skill-portability.sh` enforces:

1. Frontmatter is present
2. Every top-level key is a specification key or a Claude Code key (the list is read from `_meta/skill_audit.py` at run time); a Claude Code key is accepted with a warning that it is Claude Code only
3. `name` matches `^[a-z0-9-]+$`
4. `name` ≤ 64 chars
5. `description` is a single string (not list, not multi-line)
6. `description` ≤ 1024 chars, with a warning over the audit's limit
7. `description` does not open with "Use when"

The full standard (metadata value types, references, contents lists, home paths, must-hold rules in the first 20 KB) is checked by `python3 skills/_meta/skill_audit.py audit --only <name> --strict`, which is the last authoring step.

## Anti-patterns

| Don't | Why |
|---|---|
| `tags: [...]`, `version: 1.0.0`, `author: ...` at the top level | Not a specification or Claude Code key; fails the audit (A1). Put it under `metadata:` as a quoted string |
| `metadata:` values left unquoted (`version: 1.0`, `stable: true`) | Not strings; fails the audit (A2) |
| A Claude Code key in a skill bound for claude.ai upload or the Skills API | Hard error there; keep to the six specification keys |
| Multi-line description | YAML allows it; the validator and several loaders do not |
| `name: my_skill` | Underscores forbidden |
| `name: MySkill` | Uppercase forbidden |
| Description opening with "Use when" | The subject goes first; fails the audit (A5) |
| Description starting with "This skill ..." | Spends the opening on filler; lead with the domain words |
| Description mentioning the Read/Bash/Edit tool | Cross-model compat — name capabilities, not tool names |
| Description as a YAML list | Single string only |
