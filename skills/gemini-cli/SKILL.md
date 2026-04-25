---
name: gemini-cli
description: Use when working with Google Gemini CLI (`gemini`) — headless and interactive modes, the policy engine, skills, extensions, hooks migration, MCP servers, A2A and ACP protocols, GEMINI.md hierarchy, and authentication. Covers Gemini CLI 0.36.0 (April 2026). Includes verified ground truth from the local install.
---

# Gemini CLI

Task-indexed reference for Google Gemini CLI 0.36.0. Verified locally on 2026-04-08 from `gemini --help` and the built-in `skill-creator` plugin source.

This SKILL.md is the navigation index. Detailed documentation lives in `references/`. Read only what the current task needs.

## When to use

- Building anything that calls `gemini` from the shell or a script (headless `-p` mode)
- Authoring or porting Gemini skills, extensions, MCP servers, hooks
- Editing `~/.gemini/settings.json`, `~/.gemini/GEMINI.md`, project `GEMINI.md`
- Migrating Claude Code hooks via `gemini hooks migrate`
- Cross-referencing Gemini against Claude Code, Codex CLI, or GitHub Copilot CLI
- Writing the Policy Engine policy files that replaced `--allowed-tools`

## Versions covered

| Component | Version (verified locally 2026-04-08) |
|---|---|
| Gemini CLI | 0.36.0 |
| `@google/gemini-cli-a2a-server` (A2A GA) | 0.36.0 (npm, published 2026-04-07) |
| Built-in skill-creator | bundled with 0.36.0 |

## Quick task index

### Headless / scripted invocation

| Task | Read |
|---|---|
| Run a one-shot prompt and exit | `references/headless.md` |
| Approval modes (default / auto_edit / yolo / plan) | `references/headless.md` (Approval Modes section) |
| Output formats (text / json / stream-json) | `references/headless.md` (Output formats section) |
| Sandbox mode | `references/headless.md` (Sandbox section) |
| Hybrid mode (`-i, --prompt-interactive`) | `references/headless.md` (Hybrid section) |
| Resume / list / delete sessions | `references/headless.md` (Sessions section) |

### Skills and extensions

| Task | Read |
|---|---|
| Author a Gemini skill (frontmatter rules) | `references/skills-and-extensions.md` (Skill Format section — verified from built-in skill-creator) |
| Install a skill from git or local path | `gemini skills install <git-url-or-path>` (see `skills-and-extensions.md`) |
| Symlink a skill for in-place dev | `gemini skills link <path>` |
| List, enable, disable, uninstall skills | `gemini skills {list,enable,disable,uninstall}` |
| Author / use extensions | `references/skills-and-extensions.md` (Extensions section) |
| Generate extension boilerplate | `gemini extensions new <path> [template]` |
| Validate an extension manifest | `gemini extensions validate <path>` |

### Policy engine and tool control

| Task | Read |
|---|---|
| Replace deprecated `--allowed-tools` | `references/policy-engine.md` |
| Write a read-only CI policy | `references/policy-engine.md` (Read-only CI policy section) |
| Difference between `--policy` and `--admin-policy` | `references/policy-engine.md` (Scope semantics section) |

### Memory, context, files

| Task | Read |
|---|---|
| `GEMINI.md` hierarchy and `@file.md` imports | `references/gemini-md.md` |
| Add extra include directories | `--include-directories` flag |
| Settings.json schema | `references/settings-schema.md` |

### Hooks (migrated from Claude Code)

| Task | Read |
|---|---|
| Migrate Claude Code hooks to Gemini | `references/hooks.md` (`gemini hooks migrate`) |
| Limitations and live-compat semantics | `references/hooks.md` (Limitations section) |

### MCP servers

| Task | Read |
|---|---|
| Add a stdio or http MCP server | `gemini mcp add <name> <commandOrUrl> [args...]` (see `references/mcp.md`) |
| List, enable, disable, remove MCP servers | `gemini mcp {list,enable,disable,remove}` |
| Restrict to specific MCP servers per invocation | `--allowed-mcp-server-names` |
| Use in `~/.gemini/settings.json` | `references/settings-schema.md` |
| Already-installed example | `references/mcp.md` (`nanobanana` extension example) |

### A2A and ACP

| Task | Read |
|---|---|
| Run Gemini CLI as an A2A server | `references/a2a-and-acp.md` (A2A section — `@google/gemini-cli-a2a-server@0.36.0` verified GA) |
| Run Gemini CLI as an ACP server (e.g. for Zed editor) | `references/a2a-and-acp.md` (ACP section — `--acp` flag) |
| Difference between A2A, ACP, and MCP | `references/a2a-and-acp.md` (Three protocols section) |

### Authentication

| Task | Read |
|---|---|
| OAuth personal account (default) | `references/auth.md` (OAuth section — `gemini auth login`) |
| Direct API key | `references/auth.md` (`GEMINI_API_KEY`) |
| Vertex AI via ADC | `references/auth.md` (Vertex section — `GOOGLE_GENAI_USE_VERTEXAI=1`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `gcloud auth application-default login`) |
| Service account JSON | `references/auth.md` (`GOOGLE_APPLICATION_CREDENTIALS=<path.json>`) |
| Auth decision table | `references/auth.md` (Decision table section) |

### Verification

Run `scripts/verify-gemini-install.sh` after a `gemini` upgrade. The script:

1. Captures `gemini --version`, `gemini --help`, `gemini skills --help`, `gemini extensions --help`, `gemini hooks --help`, `gemini mcp --help`
2. Lists `gemini skills list --all` and `gemini extensions list`
3. Verifies `gemini hooks migrate` subcommand still exists
4. Checks `~/.gemini/settings.json` parses as JSON if present
5. Reports auth state hint

## Top-level subcommands (verified)

```
mcp              Manage MCP servers (add | remove | list | enable | disable)
extensions       Manage extensions (install | uninstall | list | update | enable | disable | link | new | validate | config)
skills           Manage agent skills (list | enable | disable | install | link | uninstall)
hooks            Manage hooks — only one subcommand: migrate (one-shot import from Claude Code)
[query..]        Default — launches interactive mode unless -p/--prompt is set
```

`gemini extensions` and `gemini extension` are aliases. Same for `gemini skills` / `gemini skill`. Same for `gemini hooks` / `gemini hook`.

## Headless (`-p`) cheat sheet

```bash
# Force OAuth subscription path when the shell has GOOGLE_CLOUD_PROJECT / GEMINI_API_KEY set for other Google tooling
export GOOGLE_CLOUD_PROJECT=
export GEMINI_API_KEY=

# One-shot prompt, plain text
gemini -p "summarize this file" < notes.md

# JSON output
gemini -p --output-format json "list TODOs in this repo"

# Hybrid: run a prompt then drop into interactive
gemini -i "investigate this bug" --include-directories ./src

# Auto-approve all (YOLO) — sandbox + non-interactive
gemini -p -y -s "refactor this function"

# Read-only plan mode
gemini -p --approval-mode plan "what would you change in this file?"

# Restrict via Policy Engine
gemini -p --policy ./ci-readonly.policy "review this PR"

# Pin specific extensions
gemini -p -e my-skill -e nanobanana "build a thumbnail for this post"

# Resume the most recent session
gemini -r latest "continue where we left off"
```

See `references/headless.md` for the full surface and `references/policy-engine.md` for policy file format.

## Approval modes (verified)

| Mode | Behaviour |
|---|---|
| `default` | Prompt for approval on each tool use |
| `auto_edit` | Auto-approve edit tools, prompt for everything else |
| `yolo` | Auto-approve all tools (also via `-y`) |
| `plan` | Read-only mode |

## Anti-patterns

| Don't | Why |
|---|---|
| Add fields to skill frontmatter beyond `name` and `description` | Gemini silently rejects extras. Verified from built-in `skill-creator/SKILL.md`: *"Do not include any other fields in YAML frontmatter."* |
| Use `--allowed-tools` | DEPRECATED. Use the Policy Engine (`--policy`, `--admin-policy`). The flag still works but throws a deprecation warning. |
| Expect `gemini skills install` to update the symlink that bob created | `install` will likely replace symlinks with real directories. Use `gemini skills link <path>` for in-place dev. Canonical source stays in `~/.claude/skills/`. |
| Treat A2A and ACP as the same thing | A2A is agent-to-agent (`@google/gemini-cli-a2a-server`). ACP is the Agent Client Protocol — Gemini CLI acts as an ACP server for clients like Zed. Different protocols. |
| Expect `gemini hooks migrate` to keep migrated hooks in sync | One-shot import. Treat the output as a generated artifact. Re-run after editing source hooks. |
| Skip the JSON parse check on `~/.gemini/settings.json` | Malformed JSON silently breaks Gemini config loading. Run the verify script. |
| Put all skills under `~/.gemini/skills/` and forget about Claude | Canonical location is `~/.claude/skills/<name>/`. Symlink to `~/.gemini/skills/<name>/` and run `gemini skills link <path>`. See `cross-tool-portability/install-matrix.md`. |
| Use `--raw-output` without `--accept-raw-output-risk` | Disables sanitization of model output, allows ANSI escapes. Security risk if model output is untrusted. |

## See also

- `references/skills-and-extensions.md` — verified Gemini skill format from local built-in
- `references/hooks.md` — `gemini hooks migrate` semantics
- `references/policy-engine.md` — what replaced `--allowed-tools`
- `references/a2a-and-acp.md` — A2A GA confirmation, ACP --acp flag
- `references/auth.md` — 4 auth flows, decision table
- `references/settings-schema.md` — `~/.gemini/settings.json` structure (Gemini-research only — unverified)
- `references/gemini-md.md` — GEMINI.md hierarchy, imports
- `references/mcp.md` — `gemini mcp` subcommands, nanobanana example
- `claude-code-cli` — Claude Code CLI counterpart
- `gh-copilot-cli` — GitHub Copilot CLI counterpart
- `gcp-workstations` — Vertex auth on a GCP Workstation
- `research-for-skills/cross-tool-portability/` — rules for skills that span multiple CLIs
- `codex-orchestration` — Gemini MCP integration patterns
