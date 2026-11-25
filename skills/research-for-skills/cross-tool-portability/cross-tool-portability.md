# Cross-Tool Portability — Authoring Rulebook

When authoring or reviewing a skill that must work across multiple AI CLIs (Claude Code, Antigravity CLI (agy), Codex CLI, GitHub Copilot CLI), follow these rules. **Read this file first** before drafting or modifying any cross-tool skill.

This is a sub-skill of `research-for-skills`. It is content, not a registered skill — load it via `Read` when authoring or reviewing.

## Contents

- Why this matters
- The five hard rules (memorise these)
- Authoring checklist
- Reference files
- Validator
- Cross-tool decision flowchart
- Anti-patterns

## Why this matters

The four major AI coding CLIs in 2026 (Claude Code, Antigravity CLI (agy), Codex CLI, GitHub Copilot CLI) all support skill-like extensions, but with subtle differences. A skill that works perfectly on Claude Code can be rejected elsewhere if the frontmatter carries a key outside the specification. A reference file that loads on one CLI may exceed Copilot's instruction-file budget.

The rules here are the **intersection** — strict enough that any compliant skill works on all four tools. (`agy` can import Claude plugins/skills directly via `agy plugin import claude` — see the `antigravity-cli` skill.)

## The five hard rules (memorise these)

1. **Frontmatter keys come from two lists.** The specification keys (`name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`) work everywhere. The Claude Code keys (`model`, `context`, `paths` and the others in `_meta/skill_audit.py`) work in Claude Code, are ignored by Codex, and are a hard error on claude.ai upload and in the Skills API. Anything else is custom data and goes under `metadata:` as a quoted string.

2. **Naming**: `^[a-z0-9-]+$`, max 64 chars. No underscores, no uppercase, no dots. Same constraint in all four tools.

3. **Body**: SKILL.md `<500` lines. Move detail to `references/*.md`. Hard limit under the skill-creator convention, recommended in Claude/Codex.

4. **Directory structure**: `scripts/`, `references/`, `assets/`. Same in all four tools.

5. **Description opens with the subject**, then says what the skill does and when to use it, in the third person and in about 200 characters. The model only sees the description before deciding to load the body — vague descriptions = skill never triggers. An opening "Use when" fails the audit.

## Authoring checklist

Before publishing a cross-tool skill, verify EVERY item:

- [ ] Frontmatter keys are specification or Claude Code keys; custom data is under `metadata:` as quoted strings
- [ ] `name` matches `^[a-z0-9-]+$`, ≤64 chars
- [ ] `description` is single-line, ≤1024 chars
- [ ] `description` opens with the subject, says what and when, and does not open with "Use when"
- [ ] SKILL.md body <500 lines (use `wc -l SKILL.md`)
- [ ] All `references/*.md` links from SKILL.md resolve
- [ ] Body uses tool-agnostic language ("Read the file" not "Use the Read tool")
- [ ] Anti-patterns table at the end of SKILL.md
- [ ] Has been validated with `scripts/verify-skill-portability.sh`, then with `python3 skills/_meta/skill_audit.py audit --only <name> --strict` (the last authoring step)
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

- Every frontmatter key is a specification key or a Claude Code key (the list is read from `_meta/skill_audit.py`)
- `name` matches the pattern
- `description` is single-line and within size limits
- Body is `<500` lines
- All referenced files exist
- Description does not open with "Use when"

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
| Add a top-level key that is on neither list (`tags`, `version`, `tools`) | Fails the audit (A1) and is rejected by claude.ai upload and the Skills API; put custom data under `metadata:` as a quoted string |
| Use uppercase or underscores in `name` | All four tools require lowercase + hyphens |
| Inline >500 lines in SKILL.md | Skill-creator hard limit; Claude's recommended limit |
| Reference skills by absolute path | Path differs across machines; use `<skill-name>` and let the agent resolve |
| Author hooks assuming agy parity | Claude hooks are native; the agy equivalent is unverified. See `hooks-portability.md` (TODO(agy): verify equivalent). |
| Assume all four tools auto-discover skills | Copilot has no skills concept — bridge via AGENTS.md or MCP server |
| Use tool-specific language ("Use the Read tool") | Cross-model compat — say "Read the file" or "open the file" |
| Skip the validator | The five hard rules are easy to break by accident |
| Trust your memory of the rules in long sessions | Re-read this file at every checkpoint |
