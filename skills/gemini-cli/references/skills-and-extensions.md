# Skills and Extensions in Gemini CLI

Gemini CLI has two complementary mechanisms for extending its behaviour: **skills** and **extensions**. They are different things — extensions can ship skills, but skills can also be standalone.

## Gemini skill format — verified ground truth

Source: `/usr/local/lib/node_modules/@google/gemini-cli/bundle/builtin/skill-creator/SKILL.md` (the official, locally-installed skill-creator from Gemini CLI 0.36.0).

### Frontmatter (mandatory, strict)

```yaml
---
name: <lowercase-hyphens, max 64 chars>
description: <single-line, max 1024 chars, leads with trigger language>
---
```

**Hard rule from Google's own doc** (verbatim quote):

> *"Do not include any other fields in YAML frontmatter."*

This is enforced. Adding `allowed-tools`, `model`, `tools`, `context`, or any other field will cause silent rejection. Cross-tool skills MUST use only `name` and `description`.

### Body

```markdown
# <Title>

<body markdown — must be under 500 lines>
```

Hard limits:

- `<500` lines per SKILL.md body
- Description leads with concrete triggers ("Use when...") — this is the only thing the model sees before deciding to load the skill body
- Naming: `^[a-z0-9-]+$`, max 64 chars

### Directory structure

```
skill-name/
├── SKILL.md (required)
├── scripts/      (optional)   - Executable code (Node/Python/Bash)
├── references/   (optional)   - Markdown loaded on demand
└── assets/       (optional)   - Files used in output (templates, fonts, images)
```

This is identical to Claude Code's convention. A single skill directory works for both tools without modification.

### Progressive disclosure

Three levels:

| Level | When loaded | Size budget |
|---|---|---|
| Metadata (name + description) | Always | ~100 words |
| SKILL.md body | When skill activates | <5k words / <500 lines |
| Bundled resources (`scripts/`, `references/`, `assets/`) | On demand by the model | Unlimited |

Core principle from Google's doc: *"The context window is a public good."* Default assumption is that Gemini CLI is already smart — only add context it doesn't already have.

### Skill discovery and activation

Skills are NOT auto-loaded. The model uses an `activate_skill` tool to load a skill body once it decides the description matches the user's request. This is why the description must lead with concrete triggers.

Discover with:

```bash
gemini skills list           # only enabled
gemini skills list --all     # include disabled
```

### Packaging

A `.skill` file is a zip with the `.skill` extension. Generate with the bundled `package_skill.cjs`. Install with:

```bash
gemini skills install <path/to/name.skill> [--scope user|workspace]
```

After install the **user must** run `/skills reload` in an interactive session — agents cannot do this themselves. Verify with `gemini skills list`.

### Installation sources

```bash
# from a packaged .skill file
gemini skills install ./dist/my-skill.skill --scope user

# from a git repository
gemini skills install https://github.com/user/repo.git --scope workspace

# from a local path (treated as a packaged skill)
gemini skills install /home/me/projects/my-skill.skill

# from a local directory in dev (symlink, lives in place)
gemini skills link /home/me/projects/my-skill
```

`gemini skills link` is the dev-friendly path: edits to the source directory take effect immediately. `gemini skills install` may replace symlinks with real directories — use `link` for the cross-tool symlink pattern in `cross-tool-portability/install-matrix.md`.

### Subcommand reference

| Command | Purpose |
|---|---|
| `gemini skills list [--all]` | List discovered skills (add `--all` for disabled) |
| `gemini skills enable <name>` | Enable a skill |
| `gemini skills disable <name> [--scope]` | Disable a skill |
| `gemini skills install <source> [--scope] [--path]` | Install from git URL or local path |
| `gemini skills link <path>` | Symlink a skill from local path (in-place dev) |
| `gemini skills uninstall <name> [--scope]` | Uninstall by name |

`gemini skills` and `gemini skill` are aliases.

## Extensions

Extensions are richer than skills. They can bundle multiple skills, MCP servers, tools, GEMINI.md context, and configuration — all under one installable unit.

### Manifest

`gemini-extension.json` at the root of an extension. Defines:

- Name, version, description
- Bundled MCP servers
- Bundled skills
- Bundled tools
- GEMINI.md content to inject
- Configuration schema

### Subcommand reference (verified)

| Command | Purpose |
|---|---|
| `gemini extensions install <source> [--auto-update] [--pre-release]` | Install from git URL or local path |
| `gemini extensions uninstall [names..]` | Uninstall one or more extensions |
| `gemini extensions list` | List installed |
| `gemini extensions update [<name>] [--all]` | Update one or all |
| `gemini extensions enable [--scope] <name>` | Enable |
| `gemini extensions disable [--scope] <name>` | Disable |
| `gemini extensions link <path>` | Symlink for in-place dev |
| `gemini extensions new <path> [template]` | Create boilerplate from a template |
| `gemini extensions validate <path>` | Validate the manifest |
| `gemini extensions config [name] [setting]` | Configure extension settings |

`gemini extensions` and `gemini extension` are aliases.

### Quick boilerplate

```bash
gemini extensions new ./my-extension default
gemini extensions validate ./my-extension
gemini extensions link ./my-extension
gemini extensions list
```

## Skills vs extensions — when to use which

| Need | Use |
|---|---|
| One self-contained domain workflow with optional scripts/references/assets | **Skill** |
| MCP server bundled with skills and config schema | **Extension** |
| Custom GEMINI.md content auto-loaded | **Extension** |
| Cross-tool portable (also runs on Claude/Codex) | **Skill** (extensions are Gemini-only) |
| In-place dev iteration | Either, with `link` |

## Cross-tool portability

For skills that must also run on Claude Code, Codex CLI, and (via AGENTS.md) GitHub Copilot CLI: read `~/.claude/skills/research-for-skills/cross-tool-portability/cross-tool-portability.md`. Critical rules:

- Frontmatter ONLY `name` and `description` (Gemini's strict rule wins)
- Naming `^[a-z0-9-]+$`, <64 chars
- Body <500 lines, split to `references/` if longer
- Directory `scripts/`, `references/`, `assets/` (works in both tools)
- Canonical install path: `~/.claude/skills/<name>/`. Symlink to `~/.gemini/skills/<name>/` and run `gemini skills link`.
