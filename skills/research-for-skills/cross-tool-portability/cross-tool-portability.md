# Cross-Tool Portability — Authoring Rulebook

When authoring or reviewing a skill that must work across multiple AI CLIs (Claude Code, Antigravity CLI (agy), Codex CLI, GitHub Copilot CLI), follow these rules. **Read this file first** before drafting or modifying any cross-tool skill.

This is a sub-skill of `research-for-skills`. It is content, not a registered skill — load it via `Read` when authoring or reviewing.

## Why this matters

The four major AI coding CLIs in 2026 (Claude Code, Antigravity CLI (agy), Codex CLI, GitHub Copilot CLI) all support skill-like extensions, but with subtle differences. A skill that works perfectly on Claude may silently fail on another tool if the frontmatter has extra fields. A reference file that loads on one CLI may exceed Copilot's instruction-file budget.

The rules here are the **intersection** — strict enough that any compliant skill works on all four tools. (`agy` can import Claude plugins/skills directly via `agy plugin import claude` — see the `antigravity-cli` skill.)

## The five hard rules (memorise these)

1. **Frontmatter is `name + description` only.** No `allowed-tools`, no `model`, no `tools`, no `context`, no anything else. The skill-creator convention silently rejects extras; Claude tolerates them; Copilot ignores them; Codex flags them. Strict intersection wins.

2. **Naming**: `^[a-z0-9-]+$`, max 64 chars. No underscores, no uppercase, no dots. Same constraint in all four tools.

3. **Body**: SKILL.md `<500` lines. Move detail to `references/*.md`. Hard limit under the skill-creator convention, recommended in Claude/Codex.

4. **Directory structure**: `scripts/`, `references/`, `assets/`. Same in all four tools.

5. **Description leads with trigger language**. "Use when ..." is the canonical opening. The model only sees the description before deciding to load the body — vague descriptions = skill never triggers.

## Authoring checklist

Before publishing a cross-tool skill, verify EVERY item:

- [ ] Frontmatter contains ONLY `name` and `description`
- [ ] `name` matches `^[a-z0-9-]+$`, ≤64 chars
- [ ] `description` is single-line, ≤1024 chars
- [ ] `description` leads with "Use when ..." or equivalent trigger
- [ ] SKILL.md body <500 lines (use `wc -l SKILL.md`)
- [ ] All `references/*.md` links from SKILL.md resolve
- [ ] Body uses tool-agnostic language ("Read the file" not "Use the Read tool")
- [ ] Anti-patterns table at the end of SKILL.md
- [ ] Has been validated with `scripts/verify-skill-portability.sh`
- [ ] Cross-references other skills via `<skill-name>` not `<absolute-path>`

## Reference files

Detailed guidance lives in companion files in this directory:

| File | Read when |
|---|---|
| [`frontmatter-rules.md`](frontmatter-rules.md) | Authoring SKILL.md frontmatter |
| [`install-matrix.md`](install-matrix.md) | Setting up symlinks across `~/.claude/`, `~/.codex/` (and agy plugin import) |
| [`agents-md-canonical.md`](agents-md-canonical.md) | Designing AGENTS.md / CLAUDE.md content |
| [`hooks-portability.md`](hooks-portability.md) | Authoring hooks (Claude-native; agy equivalent unverified) |
| [`headless-invocation.md`](headless-invocation.md) | Translating `claude -p` patterns to `agy -p` and `copilot -p` |
| [`verification-first-boot.md`](verification-first-boot.md) | Validating a new skill on first install |
| [`common-mistakes.md`](common-mistakes.md) | The five most common breaking mistakes |
| [`challenger-concerns.md`](challenger-concerns.md) | Hook re-entrancy, name collisions, multi-user auth |

## Validator

Run `scripts/verify-skill-portability.sh <SKILL.md>` against any skill before publishing. The script checks:

- Frontmatter contains only `name` and `description`
- `name` matches the pattern
- `description` is single-line and within size limits
- Body is `<500` lines
- All referenced files exist
- Description leads with trigger language

It exits 0 on pass, non-zero with line-level diagnostics on failure.

## Cross-tool decision flowchart

```
              Is this skill needed in multiple CLIs?
                          │
              ┌───────────┴───────────┐
             YES                      NO
              │                       │
   Read this file's checklist      Single-tool skill — use that tool's
   Use scripts/verify-...sh        native conventions, no cross-tool work
              │
   ┌──────────┼──────────┐
   │          │          │
Claude    Antigravity Copilot/Codex
~/.claude/ (agy)      ~/.copilot/
skills/    plugin     (no skills)
           import      │
              │        │
   Symlink from ~/.claude/skills/<name>/ for Codex
   `agy plugin import claude` to pull Claude skills into agy
   AGENTS.md pointer for Copilot
```

## Anti-patterns

| Don't | Why |
|---|---|
| Add `allowed-tools` to frontmatter for Claude convenience | The strict skill-creator convention rejects extras → skill may never load on another tool |
| Use uppercase or underscores in `name` | All four tools require lowercase + hyphens |
| Inline >500 lines in SKILL.md | Skill-creator hard limit; Claude's recommended limit |
| Reference skills by absolute path | Path differs across machines; use `<skill-name>` and let the agent resolve |
| Author hooks assuming agy parity | Claude hooks are native; the agy equivalent is unverified. See `hooks-portability.md` (TODO(agy): verify equivalent). |
| Assume all four tools auto-discover skills | Copilot has no skills concept — bridge via AGENTS.md or MCP server |
| Use tool-specific language ("Use the Read tool") | Cross-model compat — say "Read the file" or "open the file" |
| Skip the validator | The five hard rules are easy to break by accident |
| Trust your memory of the rules in long sessions | Re-read this file at every checkpoint |
