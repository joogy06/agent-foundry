# Install Matrix

How to install a cross-tool skill so all four CLIs can find and load it.

## Canonical location

All cross-tool skills live at:

```
~/.claude/skills/<skill-name>/
  ├── SKILL.md
  ├── references/
  ├── scripts/
  └── assets/
```

This is the **canonical source**. Other tools symlink to it.

## Per-tool install

| Tool | Path | How to install | Notes |
|---|---|---|---|
| **Claude Code** | `~/.claude/skills/<name>/` | `mkdir`, place files | The canonical source. Edit here. |
| **Antigravity CLI (`agy`)** | agy-managed (config under `~/.antigravity/`) | `agy plugin import claude` (imports Claude plugins/skills) | TODO(agy): verify per-skill live-symlink path. `agy plugin import` is the verified bulk-import path. |
| **Codex CLI** | `~/.codex/skills/<name>/` | `ln -sfn ~/.claude/skills/<name> ~/.codex/skills/<name>` | Plain symlink |
| **GitHub Copilot CLI** | (no skill concept) | Reference from `AGENTS.md` or wrap as MCP server | See below |

## Symlink commands

```bash
SKILL_NAME=my-skill

# 1. Source of truth — write here
mkdir -p ~/.claude/skills/$SKILL_NAME/{references,scripts,assets}
# ...write SKILL.md, references/*, scripts/*, assets/* ...

# 2. Codex symlink (directory-level — NOT per-file; see common-mistakes.md § Per-file symlinks)
# -sfn flags are critical:
#   -s = symbolic link
#   -f = force-replace if target exists
#   -n = if target is a symlink to a directory, do NOT follow it (replace atomically)
# This single command is idempotent: safe to run on fresh install, updates, or re-runs.
ln -sfn "$HOME/.claude/skills/$SKILL_NAME" "$HOME/.codex/skills/$SKILL_NAME"

# Verify the link landed correctly (directory symlink, resolves to Claude side)
test -L "$HOME/.codex/skills/$SKILL_NAME" \
  && [[ "$(readlink -f "$HOME/.codex/skills/$SKILL_NAME")" == "$HOME/.claude/skills/$SKILL_NAME" ]] \
  || { echo "FAIL: Codex symlink not set correctly"; exit 1; }

# 3. Antigravity (agy) — import Claude plugins/skills into agy
agy plugin import claude

# 4. (No GitHub Copilot CLI install — see AGENTS.md bridge below)
```

## Getting skills into `agy`

`agy plugin import claude` pulls Claude plugins/skills into agy — the verified path for reusing the existing skill set rather than re-authoring (see the `antigravity-cli` skill). It is a bulk import keyed to the Claude plugin/skill set, not a per-skill symlink.

TODO(agy): verify equivalent — whether agy supports a per-skill live-symlink (the way `~/.codex/skills/<name>` symlinks back to the Claude canonical source). Until verified, treat `agy plugin import` as a re-runnable import rather than a live symlink, and re-import after substantial canonical-source edits.

## GitHub Copilot CLI bridge

Copilot CLI doesn't have a skills concept. Two options:

### Option A: Reference from `AGENTS.md`

Add a one-liner to the project's `AGENTS.md`:

```markdown
# Project context

For the [skill-name] capability, read `~/.claude/skills/<skill-name>/SKILL.md`
and follow its guidance.
```

This makes the skill content discoverable when Copilot loads `AGENTS.md` at session start. The model can decide to read the SKILL.md file as needed.

### Option B: Wrap as an MCP server

For skills that need deterministic execution (not just guidance), wrap the scripts in an MCP server and add to `~/.copilot/mcp-config.json`:

```json
{
  "mcpServers": {
    "my-skill-tools": {
      "command": "node",
      "args": ["/home/user/.claude/skills/my-skill/mcp-wrapper.js"]
    }
  }
}
```

The MCP wrapper exposes the skill's scripts as MCP tools that Copilot can call.

## Per-project overrides

For project-scoped skills (rare), use the project-local skill location of each tool:

| Tool | Project-local skill location |
|---|---|
| Claude Code | `<project>/.claude/skills/<name>/` (loaded with `--add-dir`) |
| Antigravity CLI (`agy`) | TODO(agy): verify equivalent — no verified project-local skill path; use `--add-dir <project>` to add the workspace |
| Codex CLI | `<project>/.codex/skills/<name>/` |
| Copilot CLI | `<project>/AGENTS.md` reference |

These override user-global skills with the same name. Use sparingly — most skills should be global.

## Verify installation

After symlinking, run:

```bash
# Claude
ls ~/.claude/skills/<name>/SKILL.md
# Antigravity (agy) — list imported plugins
agy plugin list | grep <name>   # TODO(agy): verify exact list output / skill-vs-plugin granularity
# Codex
ls ~/.codex/skills/<name>/SKILL.md
```

If Claude and Codex resolve and the agy import succeeded, the skill is available to the skill-aware CLIs. For Copilot, verify the AGENTS.md reference is in place in any project that should use it.

## Symlink gating — the .no-codex-symlink sentinel

Symlink every skill into `~/.codex/skills/` UNLESS the skill directory contains a
`.no-codex-symlink` sentinel file (affordance-advisor precedent — host-gated skills
that must not load on other CLIs). There is NO hardcoded skip list to maintain:

```bash
[ -e ~/.claude/skills/<skill>/.no-codex-symlink ] || ln -sfn ~/.claude/skills/<skill> ~/.codex/skills/<skill>
```


## Refresh cycle

When you update the canonical skill at `~/.claude/skills/<name>/`:

```bash
# Edits are live for Claude (it reads from canonical source)
# Edits are live for Codex (symlink, no copy)
# For agy: re-run `agy plugin import claude` after substantial canonical-source edits
#          (TODO(agy): verify whether agy tracks live edits or needs re-import)
# Copilot picks up changes via AGENTS.md reference at next session start
```

No re-install needed for the symlinked tools (Claude, Codex). agy import currency depends on whether it symlinks or copies — verify and re-import if needed.

## Anti-patterns

| Don't | Why |
|---|---|
| Edit the agy-imported copy directly instead of the canonical Claude source | Canonical source is `~/.claude/skills/<name>/`; agy import is downstream |
| `cp -r` instead of `ln -sfn` for Codex | Diverging copies — fix one, not the others |
| Skip the symlink for Codex | Codex won't find the skill |
| Copy instead of symlink for project-local overrides | The override doesn't track the global skill |
| Symlink Claude-internal skills | They'll break on other tools — see skip list |
| Forget to re-run `agy plugin import claude` after canonical edits | The agy copy may be stale (TODO(agy): verify import currency) |
