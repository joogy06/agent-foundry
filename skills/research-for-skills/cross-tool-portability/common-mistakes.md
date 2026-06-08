# The Five Most Common Breaking Mistakes

These are the cross-tool portability mistakes that bite even experienced skill authors. Each is documented with symptom, cause, and fix.

## #1: Non-standard frontmatter keys

**Mistake**: Adding fields like `allowed-tools`, `model`, `tools`, `tags`, `context`, `version`, `author` to the YAML frontmatter.

```yaml
---
name: my-skill
description: Use when ...
allowed-tools: [Bash, Read]   # ❌ BREAKS STRICT LOADERS
model: claude-opus            # ❌ BREAKS STRICT LOADERS
tags: [api, rest]             # ❌ BREAKS STRICT LOADERS
---
```

**Symptom**: Skill works on Claude. On a strict-loading tool, the skill listing doesn't show it. Trying to use it fails silently — the model never knows it exists.

**Cause**: The skill-creator convention's hard rule: *"Do not include any other fields in YAML frontmatter."* Extra fields are silently rejected by strict loaders.

**Fix**:

```yaml
---
name: my-skill
description: Use when ...
---
```

Move tool/model/tag info into the body (a `## Permissions` section, `## Model` section, etc.) or out of the skill entirely (track tags in `~/.claude/skills/_meta/inventory.json`).

## #2: Uppercase/underscores in `name`

**Mistake**:

```yaml
name: MyCoolSkill   # ❌
name: my_cool_skill # ❌
name: my.cool.skill # ❌
```

**Symptom**: Skill rejected by validator. May appear to work in Claude (which is more lenient) but fail in a strict-loading tool.

**Cause**: All four tools require `^[a-z0-9-]+$`. Hyphens only.

**Fix**:

```yaml
name: my-cool-skill
```

Also rename the directory: `~/.claude/skills/my-cool-skill/`. The directory name MUST match the frontmatter `name`.

## #3: Assuming Copilot auto-discovers skills

**Mistake**: Symlinking the skill into a non-existent `~/.copilot/skills/` directory and expecting Copilot to find it.

**Symptom**: Skill is invisible to Copilot. No errors, just absence.

**Cause**: GitHub Copilot CLI does not have a skills concept. It reads instructions from `AGENTS.md` and `.github/copilot-instructions.md` (and the unverified path-scoped instructions).

**Fix**: Use the AGENTS.md bridge:

```markdown
# AGENTS.md (in repo root)

For [skill-name] capability, read `~/.claude/skills/<skill-name>/SKILL.md`
and follow its guidance.
```

Or wrap as an MCP server in `~/.copilot/mcp-config.json` for tools that need deterministic execution.

See `agents-md-canonical.md` for the full pattern.

## #4: SKILL.md body over 500 lines

**Mistake**: A SKILL.md with 800 lines of content all in the main body.

**Symptom**: On a strict-loading tool, the body is truncated or rejected. On Claude, the body loads but consumes massive context budget. Cross-tool portability breaks.

**Cause**: The skill-creator hard limit: `<500` lines per SKILL.md body. Claude is more lenient but still wastes context.

**Fix**: Use progressive disclosure:

```
my-skill/
  SKILL.md            (~200 lines: index, quick reference, anti-patterns)
  references/
    detail-1.md       (~400 lines: deep dive on topic 1)
    detail-2.md       (~400 lines: deep dive on topic 2)
    examples.md       (~300 lines: code samples)
```

The model loads SKILL.md first, then loads `references/<file>.md` only when needed.

Rule of thumb: SKILL.md is the **navigation index**. Content lives in `references/`.

## #5: Assuming hooks port to other CLIs

**Mistake**: Authoring hooks in Claude's `settings.json` and assuming another CLI (e.g. `agy`) will run them, or symlinking `settings.json` across tools.

```bash
ln -sfn ~/.claude/settings.json ~/.antigravity/settings.json   # ❌ unverified contract
```

**Symptom**: Hooks fire on Claude but the other tool ignores them (or errors). Hard to debug because there is no shared hooks contract.

**Cause**: Hooks are a **Claude Code-native** mechanism. Only Claude's hooks system is verified. The retired Gemini CLI had `gemini hooks migrate`; that tool is gone, and **agy has no verified hooks system** (TODO(agy): verify equivalent).

**Fix**: Keep hook **logic** in standalone scripts that Claude's settings reference via `command:`. Run the hook on the Claude side. Do not assume any other CLI runs lifecycle hooks without verifying `agy help` first.

See `hooks-portability.md`.

## Bonus mistakes

These don't make the top 5 but are common enough to mention:

### Tool-specific language in the body

```markdown
## Usage
Use the Read tool to open the file.   # ❌ Tool-specific
```

```markdown
## Usage
Read the file.   # ✅ Tool-agnostic
```

The body is shared across all four CLIs. Use neutral language.

### Forgetting the symlink for Codex

```bash
# Authored skill in ~/.claude/skills/my-skill/
# Forgot to symlink to Codex
ls ~/.codex/skills/my-skill   # 404
```

Codex won't find the skill. Always create the symlink:

```bash
ln -sfn ~/.claude/skills/my-skill ~/.codex/skills/my-skill
```

(Unless the skill is on the skip list — see `install-matrix.md`.)

### Per-file symlinks when the directory symlink already exists (DATA LOSS)

This is the single most dangerous mistake in the skill install flow. If `~/.codex/skills/<name>` is already a directory symlink to `~/.claude/skills/<name>` (the canonical pattern — see `install-matrix.md`), then **every path under it resolves through the symlink back to the Claude side**. Doing per-file symlinks at that point creates self-referential links that **destroy the content**.

```bash
# SETUP: ~/.codex/skills/my-skill is a directory symlink → ~/.claude/skills/my-skill (correct, common)

# BUG: trying to "install" files one by one via per-file symlinks
for f in SKILL.md references/*.md scripts/*; do
    ln -sf "$HOME/.claude/skills/my-skill/$f" "$HOME/.codex/skills/my-skill/$f"   # ❌ DATA LOSS
done
# Because ~/.codex/skills/my-skill/$f resolves to ~/.claude/skills/my-skill/$f,
# this is "ln -sf X X" — ln overwrites X with a symlink pointing to itself.
# The original file content is GONE.
```

**The rule**: the directory symlink delivers full parity for every file under the skill directory. Once `~/.codex/skills/<name>` points at `~/.claude/skills/<name>`, **never touch anything under the Codex path again**. All additions, updates, and deletions happen on the Claude side only.

**The guard** (use this before any file-level work on the Codex side):

```bash
TARGET="$HOME/.codex/skills/$SKILL_NAME"
if [[ -L "$TARGET" ]] && [[ "$(readlink -f "$TARGET")" == "$HOME/.claude/skills/$SKILL_NAME" ]]; then
    echo "Codex directory symlink already in place — parity delivered. Skipping per-file work."
    exit 0
fi
# Only here does it make sense to do anything on the Codex side (initial install):
ln -sfn "$HOME/.claude/skills/$SKILL_NAME" "$TARGET"
```

Precedent: S022 lost all 12 new/modified files mid-session to this bug; recovered by rewriting verbatim from prior writes. Don't repeat.

### Description that doesn't lead with a trigger

```yaml
description: A skill for working with REST APIs.   # ❌ vague
```

```yaml
description: Use when integrating with REST APIs — HTTP methods, status codes, content negotiation.   # ✅ trigger-led
```

The model decides whether to load the skill based on the description. Vague descriptions = skill never triggers.

### Reference files that don't exist

SKILL.md says:

```markdown
For X, see [references/x.md](references/x.md).
```

But `references/x.md` doesn't exist. The model follows the link, gets a 404, silently degrades.

Verify with:

```bash
SKILL_DIR=~/.claude/skills/my-skill
grep -oE 'references/[a-z0-9-]+\.md' "$SKILL_DIR/SKILL.md" \
  | while read f; do
      [ -f "$SKILL_DIR/$f" ] || echo "MISSING: $f"
    done
```

## Anti-patterns

| Don't | Why |
|---|---|
| Add `allowed-tools` to frontmatter for "convenience" | Breaks strict loaders. The whole skill becomes invisible there. |
| Use uppercase or underscores in `name` | Rejected by validator |
| Symlink skills to a non-existent Copilot skills directory | Copilot doesn't have one. Use AGENTS.md instead. |
| Inline 1000 lines in SKILL.md | Strict loaders truncate; Claude wastes context |
| Share `settings.json` / hooks across tools | Hooks are Claude-native; agy's hooks contract is unverified |
| Use tool-specific language in the body | Cross-model compat broken |
| Skip the Codex symlink | Codex won't find the skill |
| Vague description | Skill never triggers |
| Broken intra-skill links | Silent degradation |
| Skip the validator | The five hard rules are easy to break by accident |
