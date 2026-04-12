# AGENTS.md Canonical Pattern

How to keep instructions in sync across Claude Code, Gemini CLI, GitHub Copilot CLI, and Codex CLI without writing the same thing four times.

## The pattern

**Canonical content lives in `AGENTS.md`** (repo root or `~/AGENTS.md` for global). Other tool-specific files are thin pointers.

```
~/                           Project root
  AGENTS.md                  ← canonical (Copilot reads this natively)
  CLAUDE.md   → AGENTS.md    ← symlink (Claude reads CLAUDE.md)
  GEMINI.md                  ← @AGENTS.md (Gemini supports @ imports)
  .codex/AGENTS.md → ../AGENTS.md   (Codex reads AGENTS.md natively)
```

## Why AGENTS.md as the source

| Tool | AGENTS.md handling |
|---|---|
| GitHub Copilot CLI | **Reads natively** (verified via `--no-custom-instructions` flag description) |
| Codex CLI | **Reads natively** (AGENTS.md is the Codex CLI convention) |
| Gemini CLI | Supports `@file.md` imports — `GEMINI.md` can be `@AGENTS.md` |
| Claude Code | **UNVERIFIED** — symlink CLAUDE.md → AGENTS.md as a workaround until first-boot test G2 confirms native support |

Two of the four tools read AGENTS.md natively. Gemini imports it. Claude is the holdout (or maybe not — pending G2 test).

## Setting up the symlinks/imports

### Global (`~/`)

```bash
# 1. Author the canonical content
cat > ~/AGENTS.md <<'EOF'
# Global agent instructions

You are a helpful coding assistant on this machine.

## Conventions
- Use absolute paths
- Cite sources for any factual claim
- Run tests after every change
- Never `git push` to main without explicit confirmation

## Forbidden
- Force pushes without explicit user instruction
- Editing /etc, /var, /usr without explicit user instruction
- Disabling tests to make CI green
EOF

# 2. Symlink for Claude Code
ln -sfn ~/AGENTS.md ~/.claude/CLAUDE.md
# OR if CLAUDE.md must contain Claude-specific content too:
echo '@~/AGENTS.md' >> ~/.claude/CLAUDE.md
echo '<!-- below: Claude-specific additions -->' >> ~/.claude/CLAUDE.md
echo '...' >> ~/.claude/CLAUDE.md

# 3. Pointer for Gemini
echo '@~/AGENTS.md' > ~/.gemini/GEMINI.md

# 4. Codex reads ~/AGENTS.md natively (or the user's home AGENTS.md)
# No setup needed beyond creating the file
```

### Per-project

```bash
cd /path/to/project

# 1. Canonical
cat > AGENTS.md <<'EOF'
# Project: my-project

## Build
- `npm install && npm run build`

## Test
- `npm test`

## Conventions
- TypeScript strict mode
- Prettier auto-format
EOF

# 2. Claude pointer
ln -sfn AGENTS.md CLAUDE.md
# OR Claude reads CLAUDE.md from project root only if `.claude/` is configured

# 3. Gemini pointer
echo '@AGENTS.md' > GEMINI.md

# 4. Copilot bootstrap (writes .github/copilot-instructions.md from AGENTS.md content)
copilot init   # analyses repo, writes .github/copilot-instructions.md
# Then optionally edit the result to say "see AGENTS.md for canonical conventions"
```

## Existing user setup (this machine)

The user has `~/.claude/AGENTS.md -> ~/.claude/CLAUDE.md` (symlink, created in S008 for Codex compat). This is **inverted** from the recommended pattern — the source of truth is CLAUDE.md, and AGENTS.md is the symlink.

**Pros of the existing setup:**
- Codex sees the same content as Claude
- No content duplication

**Cons:**
- Claude may or may not natively read AGENTS.md (UNVERIFIED — first-boot test G2)
- The naming implies CLAUDE.md is the source, which it is — but Copilot/Codex would more naturally name the source `AGENTS.md`

**Recommendation:** Leave the existing setup alone (it works for Claude + Codex) but document the inversion in the project memory. New cross-tool projects should follow the AGENTS.md-as-source pattern documented in this file.

## Content structure

A good `AGENTS.md` is short and structured:

```markdown
# Project name

## What this project does
1-2 sentences

## Build and test
- Build: `cmd`
- Test: `cmd`
- Lint: `cmd`

## Coding conventions
- Language: ...
- Formatter: ...
- Type checking: ...

## Project structure
- `src/` — source code
- `tests/` — test files
- `docs/` — documentation

## Forbidden
- Don't ...
- Never ...

## Cross-references
For [topic], see `docs/<file>.md`.
```

Keep it under 6 KB if possible (Gemini's recommended `@file.md` import budget).

## When to diverge

Sometimes you legitimately need tool-specific instructions:

| Scenario | Approach |
|---|---|
| Claude needs a hook config | `~/.claude/CLAUDE.md` has `@~/AGENTS.md` followed by Claude-specific content |
| Gemini needs Vertex env vars hint | `~/.gemini/GEMINI.md` has `@~/AGENTS.md` followed by Gemini-specific |
| Copilot needs `applyTo:` path-scoped instructions | `.github/instructions/<name>.instructions.md` (separate file) |

The canonical `AGENTS.md` stays generic. Tool-specific additions go in tool-specific pointer files.

## Anti-patterns

| Don't | Why |
|---|---|
| Maintain four identical files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.copilot-instructions.md`) | Drift. Use one source + pointers. |
| Put tool-specific content in `AGENTS.md` | Defeats the canonical purpose |
| Embed secrets in `AGENTS.md` | Plaintext, committed |
| Use absolute paths in `@file.md` imports | Breaks across machines. Use relative or `~/` for home. |
| Skip the symlink/import for Claude assuming AGENTS.md works natively | UNVERIFIED. Set up the symlink as a workaround until G2 test confirms. |
| Make `AGENTS.md` >10 KB | Context budget. Reference long content via `@docs/<topic>.md`. |
| Forget that `copilot init` overwrites `.github/copilot-instructions.md` | Run it once, then point at AGENTS.md as canonical |
