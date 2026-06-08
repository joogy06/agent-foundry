# Frontmatter Rules

The single source of truth for what goes in a SKILL.md frontmatter when the skill must work across Claude Code, Antigravity CLI (`agy`), Codex CLI, and (via AGENTS.md) GitHub Copilot CLI.

## The strict format

```yaml
---
name: <lowercase-hyphens-only, max 64 chars>
description: <single-line, max 1024 chars, leads with "Use when ...">
---
```

**That's it.** No other fields. Period.

## Hard rule (from the skill-creator convention)

The skill-creator convention (originally surfaced verbatim by the local `gemini-cli` 0.36.0 built-in skill-creator, and the prevailing cross-tool standard) is unambiguous:

> *"Do not include any other fields in YAML frontmatter."*

This is NOT a recommendation. A strict skill loader silently rejects skills with extra fields — the skill effectively does not exist there.

Claude Code tolerates extras, but at the cost of cross-tool compat. Don't.

## What goes where instead

| You want to specify... | Don't put it in frontmatter | Put it in... |
|---|---|---|
| Allowed tools | `allowed-tools: [Bash, Read]` | A `Permissions` section in the body, OR rely on the parent agent/CLI to enforce |
| Model | `model: claude-sonnet-4-6` | A `Model` section in the body, OR let the user pick |
| Tool list | `tools: ...` | A `Tools` section in the body |
| Context to inject | `context: ...` | An `Inputs` section in the body, or `references/<file>.md` |
| Tags / categories | `tags: [...]` | Don't track tags in skills. Track in `~/.claude/skills/_meta/inventory.json`. |
| Version | `version: 1.0.0` | A `Versions` section in the body, or commit history |
| Author | `author: Alice` | A `Maintainer` section in the body, or git blame |

## `name` rules

| Rule | Pattern |
|---|---|
| Allowed characters | `^[a-z0-9-]+$` |
| Max length | 64 characters |
| Must match directory name | If skill is at `~/.claude/skills/foo-bar/`, name MUST be `foo-bar` |
| No underscores | `foo_bar` is INVALID |
| No uppercase | `FooBar` is INVALID |
| No dots, slashes, spaces | All INVALID |

Examples:

| Name | Valid? |
|---|---|
| `claude-code-cli` | YES |
| `gh-copilot-cli` | YES |
| `gcp-workstations` | YES |
| `claude_code_cli` | NO (underscore) |
| `ClaudeCodeCLI` | NO (uppercase) |
| `claude.code.cli` | NO (dot) |
| `claude-code-cli-v2.0` | NO (dot) |
| `a` | YES (technically valid; not useful) |
| `a-very-long-skill-name-that-goes-on-and-on-...` | DEPENDS on length (≤64) |

## `description` rules

| Rule | Notes |
|---|---|
| Single line | NO line breaks. NO multi-line YAML. |
| Max length | 1024 characters |
| Leads with trigger language | "Use when ...", "Use this skill when ...", or equivalent |
| Specifies what the skill DOES | Not just what it is |
| Mentions key triggers/contexts | The model uses this to decide whether to load the body |
| Cross-model neutral | Doesn't say "Use the X tool" — say "do X" |

### Good descriptions

```yaml
description: Use when working with the Claude Code CLI (`claude`) — headless and interactive modes, flags, agents, plugins, MCP servers, hooks, settings, sessions.
```

```yaml
description: Use when authoring a skill that must work across multiple AI CLIs (Claude Code, Antigravity CLI (agy), Codex CLI, Copilot CLI). Covers frontmatter, naming, body length, install matrix, and common mistakes.
```

### Bad descriptions

```yaml
description: A skill for doing things.
# ❌ Vague, no triggers, model won't know when to load it
```

```yaml
description: "Multi-line\ndescription\nwith line breaks"
# ❌ Multi-line. Single-line YAML string only.
```

```yaml
description: Use when you want to use the Read tool to read files.
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
description: "Use when integrating with REST APIs: HTTP methods, status codes, content negotiation."
```

If it contains a quote, escape or use single-quoted form:

```yaml
description: 'Use when responding to "hello world" examples in tutorials.'
```

If it contains both, use single quotes outside, escape internal singles:

```yaml
description: 'Use when handling "user input" with the user''s preferences.'
```

## Validation

The validator script `scripts/verify-skill-portability.sh` enforces:

1. Frontmatter is parseable YAML
2. Only `name` and `description` keys present
3. `name` matches `^[a-z0-9-]+$`
4. `name` ≤ 64 chars
5. `description` is a single string (not list, not multi-line)
6. `description` ≤ 1024 chars
7. `description` leads with "Use when" (case-insensitive, allows leading verbs like "Use this skill when")

## Anti-patterns

| Don't | Why |
|---|---|
| `allowed-tools: [...]` | Claude-only. A strict skill loader rejects it. |
| `model: ...` | Pin a model in the body if needed, not frontmatter |
| Multi-line description | YAML allows it; the strict rule does not |
| `name: my_skill` | Underscores forbidden |
| `name: MySkill` | Uppercase forbidden |
| Description starting with "This skill ..." | Not a trigger; model won't pick it up |
| Description mentioning the Read/Bash/Edit tool | Cross-model compat — name capabilities, not tool names |
| Description as a YAML list | Single string only |
