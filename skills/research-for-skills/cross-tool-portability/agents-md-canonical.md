# AGENTS.md Canonical Pattern

How to keep instructions in sync across Claude Code, Antigravity CLI (`agy`), GitHub Copilot CLI, and Codex CLI without writing the same thing four times.

## The pattern

**Canonical content lives in `AGENTS.md`** (repo root or `~/AGENTS.md` for global). Other tool-specific files are thin pointers.

```
~/                           Project root
  AGENTS.md                  ← canonical (Copilot reads this natively)
  CLAUDE.md   → AGENTS.md    ← symlink (Claude reads CLAUDE.md)
  .codex/AGENTS.md → ../AGENTS.md   (Codex reads AGENTS.md natively)
  # agy: TODO(agy): verify equivalent — no confirmed AGENTS.md / @-import contract.
  #      agy may honour something via `agy plugin import` — verify before relying.
```

## Why AGENTS.md as the source

| Tool | AGENTS.md handling |
|---|---|
| GitHub Copilot CLI | **Reads natively** (verified via `--no-custom-instructions` flag description) |
| Codex CLI | **Reads natively** (AGENTS.md is the Codex CLI convention) |
| Antigravity CLI (`agy`) | TODO(agy): verify equivalent — the gemini `@file.md` / `GEMINI.md` import mechanism has no confirmed agy analogue. agy config lives under `~/.antigravity/`; agy may pull instructions via `agy plugin import claude` — verify before relying. |
| Claude Code | **UNVERIFIED** — symlink CLAUDE.md → AGENTS.md as a workaround until first-boot test G2 confirms native support |

Two of the four tools read AGENTS.md natively. Claude is the holdout (or maybe not — pending G2 test); agy's instruction-file contract is unverified.

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

# 3. agy: TODO(agy): verify equivalent — no confirmed global instruction-file
#    pointer (the gemini `~/.gemini/GEMINI.md` `@`-import has no agy analogue).
#    Consider `agy plugin import claude` to reuse Claude-side context; verify first.

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

# 3. agy: TODO(agy): verify equivalent — no confirmed per-project instruction-file
#    pointer (the gemini `@AGENTS.md` `GEMINI.md` import has no agy analogue).
#    Use `agy --add-dir <project>` to add the workspace; verify any instruction-file contract.

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

Keep it under 6 KB if possible (a safe instruction-file budget across tools; the gemini `@file.md` import budget that originally motivated this number no longer applies).

## When to diverge

Sometimes you legitimately need tool-specific instructions:

| Scenario | Approach |
|---|---|
| Claude needs a hook config | `~/.claude/CLAUDE.md` has `@~/AGENTS.md` followed by Claude-specific content |
| agy needs tool-specific context | TODO(agy): verify equivalent — no confirmed agy instruction-file pointer; agy authenticates via the Antigravity account (no Vertex env-var hint needed) |
| Copilot needs `applyTo:` path-scoped instructions | `.github/instructions/<name>.instructions.md` (separate file) |

The canonical `AGENTS.md` stays generic. Tool-specific additions go in tool-specific pointer files.

## Anti-patterns

| Don't | Why |
|---|---|
| Maintain multiple identical instruction files (`AGENTS.md`, `CLAUDE.md`, `.copilot-instructions.md`, …) | Drift. Use one source + pointers. |
| Put tool-specific content in `AGENTS.md` | Defeats the canonical purpose |
| Embed secrets in `AGENTS.md` | Plaintext, committed |
| Use absolute paths in `@file.md` imports | Breaks across machines. Use relative or `~/` for home. |
| Skip the symlink/import for Claude assuming AGENTS.md works natively | UNVERIFIED. Set up the symlink as a workaround until G2 test confirms. |
| Make `AGENTS.md` >10 KB | Context budget. Reference long content via `@docs/<topic>.md`. |
| Forget that `copilot init` overwrites `.github/copilot-instructions.md` | Run it once, then point at AGENTS.md as canonical |
