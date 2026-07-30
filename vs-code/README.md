# `vs-code/` — the VS Code + GitHub Copilot arm of foundry-lab

<!-- REVIEW-BY: 2026-10-31 -->
**Foundation laid 2026-07-29 against VS Code 1.130.** Deliberately basic — enough to be correct and
extensible, to be enhanced on the target machine.

**There is no separate VS Code repo.** That decision was taken 2026-07-29 and supersedes the
`vs-code-foundry` wind-down intent in task #212. One repo, one release cadence, one place to look.

## What already works with no bridge at all

**Agent Skills are native to Copilot CLI and VS Code 1.123+, and both auto-discover
`~/.claude/skills/`.** So every skill in this library is already available in VS Code once the
`claude` install target has run. Nothing here re-implements or copies them.

**VS Code also collects `CLAUDE.md`** as an always-on instruction file, alongside `AGENTS.md` and
`.github/copilot-instructions.md`. So the harness's standing instructions port with zero translation.

That is why this folder is small. **It covers only what does NOT come across for free.**

## Parity matrix — what maps, what differs, what is absent

| foundry-lab | VS Code / Copilot | Status |
|---|---|---|
| `skills/*/SKILL.md` | auto-discovered from `~/.claude/skills/` | **works as-is** |
| `CLAUDE.md` | collected as always-on instructions | **works as-is** |
| MCP servers | `.vscode/mcp.json` | direct equivalent |
| agents (`bob`, `alf`, `pa`) | `.agent.md` custom agents | **needs porting** — no auto-discovery |
| slash commands | `.prompt.md` prompt files | **needs porting** |
| scoped instructions | `.instructions.md` + `applyTo` globs | **richer than Claude's** — use it |
| **SessionStart hooks (6)** | **no equivalent** | **the real gap** — see `docs/startup.md` |
| `_meta/gates.py` | invoked as a task or MCP tool | works, wired differently |
| model routing (`smart-config`) | **`model:` in `.agent.md` frontmatter** — single id or prioritised list | **tier pinned per agent**; no per-project resolver |
| forge → bob → alf cascade | `handoffs:` + `agents:` frontmatter | maps more directly than expected |

## Layout

```
vs-code/
  AGENTS.md                    workspace always-on instructions (template)
  instructions/                .instructions.md with applyTo globs
  agents/                      .agent.md ports of the custom agents
  prompts/                     .prompt.md — slash commands
  mcp.json                     .vscode/mcp.json template
  scripts/detect_models.py     runtime model detection — NO hardcoded versions
  docs/model-routing.md        how to reach each model, and cost control
  docs/startup.md              re-expressing the SessionStart hooks
```

## The two things to understand before extending this

**1. No model versions are hardcoded, anywhere.** Copilot's model roster changes frequently and
differs by plan, org policy and region. Every version in this folder is *detected* — at install time
and again at runtime — never asserted. A stale model id in a config is a silent failure that looks
like a permissions problem. See `scripts/detect_models.py`.

**2. Startup is the genuine design problem, not the file formats.** Everything else here is a
mapping exercise. The harness rests six SessionStart hooks on session open, and VS Code has no
equivalent trigger. `docs/startup.md` sets out the options and what each honestly costs.

## Platform note

`~/.claude/` is read on Windows and macOS as well as Linux, but **the differences are in how
skills, agents, hooks, scripts and `_meta` gates are invoked**, not in whether the directory is
found. Path separators, shell availability and script interpreters all differ; anything here that
shells out must not assume bash or POSIX paths.
