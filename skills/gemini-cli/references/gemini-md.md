# GEMINI.md Hierarchy

The `GEMINI.md` file is Gemini CLI's equivalent of Claude's `CLAUDE.md`. It contains persistent instructions, project conventions, and context that the model loads at session start.

## Hierarchy (Gemini docs — UNVERIFIED locally)

From Google's documentation (not yet verified on this machine):

```
~/.gemini/GEMINI.md            # User-global
./GEMINI.md                    # Project root
./<subdir>/GEMINI.md           # Scoped to subdirectory
```

Loaded in cascading order — global first, then project, then more specific subdirectories. Later files override earlier ones for conflicting instructions.

**This entire hierarchy is research-grade.** Locally we have confirmed `gemini` reads `--include-directories` correctly, but the cascading file load order has not been tested. **Flagged for first-boot verification.**

## `@file.md` imports

Gemini supports imports inside GEMINI.md:

```markdown
# Project conventions

@./docs/coding-style.md
@./docs/architecture.md

## Persona
You are a code reviewer focused on Python type safety.
```

The imported file content is inlined at load time. Imports support relative paths from the GEMINI.md file's location.

**UNVERIFIED**: nested imports (`@file.md` inside an imported file) — flagged for first-boot.

## Recommended size limits

Google's docs recommend (UNVERIFIED hard limits):

- ~6,000 chars per file
- ~12,000 chars total across all loaded GEMINI.md files

Going over may cause silent truncation or context budget warnings. Test on first deployment.

## Cross-tool canonical pattern

The cross-tool portability rules in this project recommend canonical content in **`AGENTS.md`** (which Copilot CLI reads natively) with thin pointer files for Claude (`CLAUDE.md`) and Gemini (`GEMINI.md`). For example:

`~/AGENTS.md` (canonical):
```markdown
# Agent instructions

You are a helpful assistant on this machine.

## Conventions
- Use absolute paths
- Cite sources for any factual claim
- Run tests after every change
...
```

`~/.gemini/GEMINI.md` (pointer):
```markdown
@~/AGENTS.md
```

`~/.claude/CLAUDE.md` (pointer or symlink to AGENTS.md):
```markdown
# Same as AGENTS.md
@~/AGENTS.md
```

The local user already has `~/.claude/AGENTS.md -> ~/.claude/CLAUDE.md` as a symlink. Whether Claude Code natively reads AGENTS.md is **UNVERIFIED** — see G2 in the design doc.

## Anti-patterns

| Don't | Why |
|---|---|
| Put 50 KB of context in a single GEMINI.md | Context budget will be blown. Use `@file.md` imports + progressive references. |
| Embed secrets in GEMINI.md | Plaintext. Use environment variables or `gcloud secrets versions access` at use-time. |
| Diverge GEMINI.md from CLAUDE.md content silently | Use the AGENTS.md canonical pattern + symlinks/pointers to keep them in sync. |
| Assume `@file.md` works for absolute paths in all versions | Test first with the literal `@~/AGENTS.md` syntax. May need a `--include-directories` argument as backup. |

## See also

- `cross-tool-portability/agents-md-canonical.md` for the recommended convergence pattern
- `claude-code-cli/references/memory.md` for the equivalent CLAUDE.md hierarchy
- `gh-copilot-cli/references/instruction-files.md` for the four-level Copilot hierarchy
