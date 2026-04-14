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
| **Gemini CLI** | `~/.gemini/skills/<name>/` | `gemini skills link ~/.claude/skills/<name>` | `link` (not `install`) so edits are live |
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

# 3. Gemini symlink (uses gemini skills link, not install)
gemini skills link "$HOME/.claude/skills/$SKILL_NAME"

# 4. (No GitHub Copilot CLI install — see AGENTS.md bridge below)
```

## Why `gemini skills link`, not `gemini skills install`

`gemini skills install` is for distributing pre-packaged `.skill` files (zip with `.skill` extension). It expects to:

- Pull from a git URL or `.skill` file
- Copy to a managed location
- Treat as opaque — edits don't propagate

`gemini skills link` is the dev-friendly path:

- Symlinks the source directory
- Edits to the source take effect immediately
- Perfect for the "canonical source in `~/.claude/skills/`" pattern

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
| Gemini CLI | `<project>/.gemini/skills/<name>/` |
| Codex CLI | `<project>/.codex/skills/<name>/` |
| Copilot CLI | `<project>/AGENTS.md` reference |

These override user-global skills with the same name. Use sparingly — most skills should be global.

## Verify installation

After symlinking, run:

```bash
# Claude
ls ~/.claude/skills/<name>/SKILL.md
# Gemini
gemini skills list | grep <name>
# Codex
ls ~/.codex/skills/<name>/SKILL.md
```

If all three resolve, the skill is installed for the three skill-aware CLIs. For Copilot, verify the AGENTS.md reference is in place in any project that should use it.

## Skip list (Claude-specific skills NOT to symlink)

Some skills depend on Claude Code internals and should NOT be symlinked to other tools:

```
agent-teams
codex-orchestration
forge
nano-banana
vertex-banana
research-for-skills
challenger
```

These reference Claude-specific files, hooks, or agent definitions. They will fail or be confusing on other tools. Keep them Claude-only.

## Refresh cycle

When you update the canonical skill at `~/.claude/skills/<name>/`:

```bash
# Edits are live for Claude (it reads from canonical source)
# Edits are live for Codex (symlink, no copy)
# Edits are live for Gemini (symlink via `gemini skills link`)
# Copilot picks up changes via AGENTS.md reference at next session start
```

No re-install needed. That's the point of the symlink pattern.

## Anti-patterns

| Don't | Why |
|---|---|
| `gemini skills install` for cross-tool skills | Replaces symlink with managed copy; edits don't propagate |
| `cp -r` instead of `ln -sfn` | Diverging copies — fix one, not the others |
| Edit `~/.gemini/skills/<name>/` directly | Edits the symlink target, but easy to forget you're not in the canonical source |
| Skip the symlink for Codex | Codex won't find the skill |
| Copy instead of symlink for project-local overrides | The override doesn't track the global skill |
| Symlink Claude-internal skills | They'll break on other tools — see skip list |
| Forget to verify with `gemini skills list` after linking | Symlink can be present but the skill missing if frontmatter is wrong |
