# The Five Most Common Breaking Mistakes

These are the cross-tool portability mistakes that bite even experienced skill authors. Each is documented with symptom, cause, and fix.

## #1: Non-standard frontmatter keys

**Mistake**: Adding fields like `allowed-tools`, `model`, `tools`, `tags`, `context`, `version`, `author` to the YAML frontmatter.

```yaml
---
name: my-skill
description: Use when ...
allowed-tools: [Bash, Read]   # ❌ BREAKS GEMINI
model: claude-opus            # ❌ BREAKS GEMINI
tags: [api, rest]             # ❌ BREAKS GEMINI
---
```

**Symptom**: Skill works on Claude. On Gemini, `gemini skills list` doesn't show it. Trying to use it fails silently — the model never knows it exists.

**Cause**: Gemini's hard rule (verbatim from local `skill-creator`): *"Do not include any other fields in YAML frontmatter."* Extra fields are silently rejected.

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

**Symptom**: Skill rejected by validator. May appear to work in Claude (which is more lenient) but fail in Gemini.

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

**Symptom**: On Gemini, the body is truncated or rejected. On Claude, the body loads but consumes massive context budget. Cross-tool portability breaks.

**Cause**: Gemini's hard limit: `<500` lines per SKILL.md body. Claude is more lenient but still wastes context.

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

## #5: Sharing one hooks file across Claude and Gemini

**Mistake**:

```bash
ln -sfn ~/.claude/settings.json ~/.gemini/settings.json
```

Or manually copy-paste the hooks block between the two files.

**Symptom**: Some hooks fire on one tool but not the other. Some fire twice. Some produce errors. Hard to debug because the schemas are similar but not identical.

**Cause**: Schemas differ. Event names may differ. Matcher syntax may differ.

**Fix**: Author hooks in Claude's `settings.json`. Run `gemini hooks migrate` once. Commit both files. Treat Gemini's as a generated artifact. Re-run migration after Claude-side edits.

For portable hook **logic**, put it in standalone scripts that both tools' settings reference via `command:`. The script is portable; the inline definitions are not.

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
| Add `allowed-tools` to frontmatter for "convenience" | Breaks Gemini. The whole skill becomes invisible there. |
| Use uppercase or underscores in `name` | Rejected by validator |
| Symlink skills to a non-existent Copilot skills directory | Copilot doesn't have one. Use AGENTS.md instead. |
| Inline 1000 lines in SKILL.md | Gemini truncates; Claude wastes context |
| Share `settings.json` between Claude and Gemini | Schemas differ subtly |
| Use tool-specific language in the body | Cross-model compat broken |
| Skip the Codex symlink | Codex won't find the skill |
| Vague description | Skill never triggers |
| Broken intra-skill links | Silent degradation |
| Skip the validator | The five hard rules are easy to break by accident |
