# Verification on First Boot

A checklist to run when you publish a new cross-tool skill, to confirm it actually works in all four CLIs.

## When to run this

- After authoring a new cross-tool skill
- After substantial edits to an existing one
- After upgrading any of the CLIs (Claude, Antigravity CLI (agy), Copilot, Codex)
- During alf sweeps when reviewing skill portability

## Checklist

### 1. Validate frontmatter

```bash
bash ~/.claude/skills/research-for-skills/cross-tool-portability/scripts/verify-skill-portability.sh \
  ~/.claude/skills/<skill-name>/SKILL.md
```

Expected: exit 0, no errors.

If it fails: fix per the error output, re-run.

### 2. Check Claude Code can find the skill

```bash
ls ~/.claude/skills/<skill-name>/SKILL.md
# Should exist

# In a Claude session
claude -p "/skill <skill-name>" --bare
# Or test that the description triggers it organically:
claude -p "<sample query that should match the description>" --bare
```

Expected: skill loads, body is read.

### 3. Check Antigravity (agy) can find the skill

```bash
# After importing Claude plugins/skills via `agy plugin import claude`
agy plugin list | grep <skill-name>   # TODO(agy): verify exact list output / skill granularity
# Should appear if agy surfaces imported skills individually

# Test a query that should trigger it (agy takes no model flag and no env-key prefix)
agy -p "<sample query>"
# Output is plain text on stdout — parse text, not JSON.
```

TODO(agy): verify equivalent — the gemini `/skills enable` + `/skills reload` flow has no confirmed agy analogue. Confirm how agy enables/refreshes imported skills before documenting it in install instructions.

### 4. Check Codex can find the skill

```bash
ls ~/.codex/skills/<skill-name>/SKILL.md
# Should exist (symlink)

# Codex doesn't have explicit skill commands like Claude.
# Skills resolve by content discovery via the codex-orchestration workflow.
# Verify the symlink resolves and the file is readable.
readlink ~/.codex/skills/<skill-name>
cat ~/.codex/skills/<skill-name>/SKILL.md | head -10
```

### 5. Check Copilot AGENTS.md reference

For project-scoped Copilot integration:

```bash
cd /path/to/project
grep -l '<skill-name>' AGENTS.md
# Should show AGENTS.md if you've referenced the skill

# Test by triggering Copilot in that project
copilot -p "<query that should benefit from the skill>" --allow-all-tools -s
```

For wrapper MCP servers (advanced):

```bash
copilot mcp list | grep <skill-name>
```

### 6. Check no broken intra-skill links

```bash
SKILL_DIR=~/.claude/skills/<skill-name>
cd "$SKILL_DIR"

# Find all markdown links in SKILL.md and references/
grep -roE '\(references/[a-zA-Z0-9_-]+\.md\)' SKILL.md references/ \
  | awk -F'[()]' '{print $2}' \
  | sort -u \
  > /tmp/declared-links.txt

# Find what actually exists
find references/ -type f -name '*.md' | sort > /tmp/existing-files.txt

# Diff
diff /tmp/declared-links.txt /tmp/existing-files.txt
```

Any difference = broken link. Fix.

### 7. Check the body is under 500 lines

```bash
wc -l ~/.claude/skills/<skill-name>/SKILL.md
```

Expected: ≤500.

If over: split detail into `references/*.md`.

### 8. Check the description leads with trigger language

```bash
sed -n '/^description:/p' ~/.claude/skills/<skill-name>/SKILL.md
```

Expected: starts with "Use when ..." or similar.

### 9. Check anti-patterns table is present

```bash
grep -c "^## Anti-patterns" ~/.claude/skills/<skill-name>/SKILL.md
```

Expected: ≥1 (the section exists).

### 10. Test hook re-entrancy guard (if the skill defines hooks)

If the skill includes hook scripts, verify they have an `AI_CLI_CALL_DEPTH` guard:

```bash
grep -l 'AI_CLI_CALL_DEPTH' ~/.claude/skills/<skill-name>/scripts/*.sh
```

Expected: every hook script that calls `claude`, `agy`, `codex`, or `copilot` has the guard.

## Continuous verification (in alf sweeps)

Add this checklist to alf's skill audit. Every cross-tool skill should pass on every sweep.

## Anti-patterns

| Don't | Why |
|---|---|
| Skip the validator | The five hard rules are easy to break by accident |
| Trust frontmatter without parsing | YAML edge cases will surprise you |
| Assume `agy plugin list` shows all imported skills | A skill might be imported but rejected due to bad frontmatter (TODO(agy): verify list granularity) |
| Assume agy auto-refreshes imported skills | TODO(agy): verify equivalent — the gemini `/skills reload` step has no confirmed agy analogue |
| Test only on Claude | The whole point is cross-tool — test in all four |
| Ignore broken intra-skill links | Model loads SKILL.md, follows link, gets 404 — silently degrades |
