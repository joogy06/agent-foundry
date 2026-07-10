# Global Instructions

## Session Start — Project Context Check

When starting work in ANY project directory, IMMEDIATELY check for existing project context before doing anything else:

1. **Check for `PROJECT.md`** — hierarchical architecture map: components, integration edges, external dependencies. Read this FIRST for project understanding.
2. **Check for `history.md`** — contains session history. **If `history.md` exceeds 400 lines, read only the head (~50 lines) and tail (~200 lines), and check for `history/INDEX.md`** for archive pointers. Read the full file only if the task requires older context.
3. **Check for `tasks.md`** — contains current task list, priorities, and completion status
4. **Check for `docs/plans/`** — contains design documents and implementation plans
5. **Check for `docs/components/`** — per-component architecture docs (COMPONENT.md files)
6. **Check for `session_control.md`** — contains session-specific instructions and priorities

```
Look for these files in the project root and docs/ directory:
- PROJECT.md
- history.md
- tasks.md
- docs/plans/*.md
- docs/components/*/COMPONENT.md
- session_control.md
- index.md
```

If any of these exist, read them BEFORE asking questions or starting work. They contain critical context about:
- What was already done (don't repeat work)
- What's in progress (continue where we left off)
- What decisions were made and why (don't revisit settled decisions)
- Current priorities and blockers

If NONE exist, proceed normally — the project has no tracked history yet.

## Session Start — Wiki Binding Check

After reading project context, check if this project is bound to one or more wikis:

7. **Check for `.wiki-link`** in the project root (or any parent directory)
8. **Check for `.wiki/` subdirectory** with embedded WIKI.md
9. **Check `~/.wiki-registry.yaml`** for a registered wiki whose path matches CWD

If a `.wiki-link` file is found, read it and mention the bound wiki(s) in the session opening:
> "This project is bound to wiki: **trading** (shared, at /path/to/wiki-local/trading). I can query it for prior decisions and research, or file new findings to it during this session."

**Auto-consult behavior**: If `.wiki-link` has `auto_consult: true` for any bound wiki, the wiki agent should be silently consulted (Tier 1 grep) when the user asks questions that look like they could benefit from prior knowledge — without needing explicit user request.

**Anti-pollution default**: Even when bound, NEW pages or NEW ingestions still require user approval for shared wikis (`role: shared`). Auto-filing only applies if `auto_filing: true` AND the wiki is `role: specific`.

**Wiki registry location**: `~/.wiki-registry.yaml` (user home, not inside `~/.claude/`, because wikis are cross-tool — Obsidian, Codex, any markdown editor).

If no wiki binding exists, proceed normally — the project is wiki-unaware.

## Autonomy Mode (Always On)

Proceed autonomously on all file reads, writes, edits, bash commands, agent spawns, and implementation work. Do NOT ask "should I proceed?" or "shall I continue?" for routine work.

**Still pause and ask before:**
- Design questions (architecture choices, UX decisions, approach selection)
- Any action the user hasn't implicitly authorized

Git push protection is enforced by the harness (`settings.json` ask rule for `Bash(git push*)`). Do NOT add behavioral git push checks — the harness handles it.

## Forge Mode (Always On)

Route ALL task requests through `forge` skill automatically — no session-start prompt needed. See **Routing by Complexity** below for skip rules.

## Session Start — Environment Adoption

On session start, run the env-adoption probe to detect available tools and compute the environment tier:

```bash
bash ~/.claude/skills/env-adoption/scripts/probe.sh check
```

If the inventory (`~/.claude/state/inventory.json`) is less than 24 hours old, `check` reuses it and only creates fresh session state. Report the result:
- "Environment: Tier 2 (full) -- all tools available"
- "Environment: Tier 1 (standard) -- missing: copilot, docker"
- "Environment: Tier 0 (minimal) -- missing: codex, agy, gh"

Skills should read the manifest (`~/.claude/state/inventory.json` for persistent state, `$XDG_RUNTIME_DIR/env-adoption/session-*.json` for session capabilities) instead of inline `command -v` or `--version` probing. See the `env-adoption` skill for full schema.

## Session Start — Knowledge Grounding

After env-adoption, run the knowledge-grounding probe to discover available knowledge sources:

```bash
bash ~/.claude/skills/knowledge-grounding/scripts/discover.sh discover --silent
```

If the sources manifest (`~/.claude/state/sources.json`) is less than 24 hours old, `discover` reuses it and only creates fresh session state. The manifest tracks:
- Available knowledge sources (wikis, project docs, configured enterprise endpoints)
- Internet reachability (DNS canary)
- Grounding mode (`internal-only` if air-gapped, `full` if internet reachable)

Skills should read `~/.claude/state/sources.json` for source availability instead of ad-hoc checks. When answering factual questions, check grounding tier (verified/grounded/inferred/training-only) and cite sources. See the `knowledge-grounding` skill for routing logic and grounding tiers.

## Session Start — Memory & User Preferences

Two-tier file memory: **global** `~/.claude/memory/` (who the user is + durable cross-project preferences) is loaded **every** session, layered with **per-project** `~/.claude/projects/<slug>/memory/` (project facts) when inside a project — project wins on a direct conflict, surfaced, never silently merged. The `_meta/memory_primer.py` SessionStart hook prints which tiers loaded plus the live `skills · agents · gates` count.

Durable user preferences live as per-domain profiles under `~/.claude/memory/preferences/` (`coding` / `presentations` / `email` / `tone`, extensible), managed via the `user-preferences` skill (`scripts/prefs.py`).

- **Capture is EXPLICIT only.** Record a preference (`prefs.py set <domain> <key> <val>` or `prefs.py note <domain> <text>`) ONLY when the user states one — "remember I prefer X", "always do Y", "I don't like Z", "from now on …". NEVER auto-infer a durable preference from a single choice; you MAY *ask* "want me to remember that?" and record on yes.
- **Apply before domain work.** Before writing/refactoring code, building a deck, drafting an email, or choosing tone/voice, run `prefs.py load <domain>` and honor the recorded preferences. The live request always overrides a stored preference.

## Hard Rules Checkpoint

Before key actions (spawning agents, design teams, claiming completion), read `~/.claude/skills/_meta/hard-rules-checklist.md`. This is a compact nudge file that prevents rule drift in long sessions.

**Mandatory checkpoints:**
- Before spawning any design team → read DESIGN PHASE section
- Before spawning bob → read EXECUTION PHASE section
- Before claiming "done" → read REVIEW / COMPLETION section
- Every 3-4 major tool calls in a long session → quick scan of relevant section

This exists because AI models lose track of HARD-RULEs in long conversations. The checklist is the safety net.

## Skill Library

- Claude skills: `~/.claude/skills/` (184 skills)
- Codex skills: `~/.codex/skills/` (188 symlinked from Claude + native Codex-only skills)
- New skills MUST be symlinked to Codex (see `research-for-skills` skill for process)
- Write skills in cross-model-compatible language (see tool mapping patterns in `research-for-skills`)
- `affordance-advisor`: host-native command suggestions, single-CLI scope (gated, not symlinked to Codex/Gemini — drop a `.no-codex-symlink` sentinel for similar exceptions)

## Routing by Complexity

TRIVIAL (config change, typo fix, single known edit):
  -> Handle directly. No skill needed.

SIMPLE (single-file change, clear output, one domain skill):
  -> Invoke domain skill directly. Skip forge.
  -> Examples: "change port to 8080", "add a CSS class", "update the README"

MEDIUM (2-3 files, some decisions, clear approach):
  -> Invoke forge with Simple complexity. Forge skips design team, does single-agent + optional Codex.
  -> Examples: "add form validation", "refactor this function"

COMPLEX (architecture decision, multiple approaches, cross-layer):
  -> Full forge cycle (design team, challengers, Codex, bob).
  -> Examples: "design a new auth system", "build a checkout flow"

Default: if unsure, start at MEDIUM. Forge's own complexity assessment will escalate if needed.

When `using-superpowers` would route to ANY other workflow skill (brainstorming, writing-plans, executing-plans, subagent-driven-development), invoke `forge` instead. Forge subsumes all of these.

Only skip forge for:
- Pure information queries ("what does X do?", "explain Y")
- TRIVIAL tasks (config change, typo fix, single known edit) — handle directly
- SIMPLE tasks (single-file change, clear output) — invoke domain skill directly
- Reading/reviewing without changes

Only invoke `superpowers:brainstorming` directly if the user explicitly requests it by name.

## Superpowers Plugin Version Tracker

On session start, check if the superpowers plugin has been updated:

1. Read the latest version: `cat ~/.claude/plugins/cache/superpowers-marketplace/superpowers/*/package.json | grep '"version"' | sort -V | tail -1`
2. Read tracked version: check `last_reviewed_version` in `~/.claude/skills/forge/superpowers-tracked.md`
3. If versions differ, alert the user:
   > "Superpowers plugin updated from [OLD] to [NEW]. Review needed to check for features to uplift into forge. Run review now?"
4. If user approves: diff all SKILL.md files between versions, identify changes in brainstorming/writing-plans/using-superpowers/executing-plans/subagent-driven, flag new features worth uplifting to forge, update the tracker after review.

## Cross-Model Collaboration

- Codex CLI (GPT-5.6) is available for second opinions, challenger reviews, and research
- For brainstorming/design/creative tasks: always run Codex in parallel (see `forge` skill)
- When stuck after 2+ attempts: escalate to Codex before asking the user
- See `codex-orchestration` skill for delegation patterns

### Antigravity CLI (`agy`) — host-specific directive

The Antigravity CLI (`agy`, `~/.local/bin/agy`) is the **PRIMARY** delegate for ALL
second-opinion / challenger / research work on this host (the gemini CLI (v0.50.x) remains
installed as an available fallback — kept per user direction 2026-07-10; `agy` is PRIMARY). When delegating a headless prompt on this host, use:

```bash
timeout 600 agy --sandbox -p "..." < /dev/null
```

- **STDIN RULE (mandatory):** headless `agy` MUST have stdin closed (`< /dev/null`) or piped —
  agy reads non-TTY stdin until EOF before the model call; in background/harness shells stdin
  never EOFs → agy hangs forever at 0 bytes, and `--print-timeout` does NOT fire (it only guards
  the print phase). Always pair with a shell `timeout`. Root-caused 2026-06-05 (#135); prompt
  size is irrelevant.
- **FLAG ORDER RULE (mandatory):** every flag BEFORE `-p`, prompt LAST — `-p` is a string flag
  and consumes the next token, so `agy -p --sandbox "X"` runs UN-sandboxed with the literal
  prompt `--sandbox` and discards "X"; agy then improvises from its implicit memory (root
  cause of the 2026-07-01/02 rogue-edit incidents and of "agy does work instead of
  consulting"). Correct: `agy --sandbox [--add-dir D] [--print-timeout 15m] -p "…"`.
- **SANDBOX RULE (mandatory for consultancy/read-only delegation):** `--sandbox` on every agy
  call that should only ADVISE — agy has write/shell/git tools ON by default and headless `-p`
  auto-approves them (verified 2026-07-02: a plain `agy -p` created a file with no permission
  flag; an un-sandboxed "analyst" has authored and git-committed code — S052 incident, #157).
  Scope caveat: `--sandbox` constrains shell/git commands only, NOT agy's native file writes
  (verified 2026-07-02 on 1.0.15) — so never `--add-dir` a writable live repo on a consultancy
  call (pipe content instead), and after any call that exposed a repo run `git status --short`
  as a tripwire. Omit `--sandbox` ONLY when the task explicitly requires writes, and say so in
  the prompt. Belt-and-braces: open consultancy prompts with "Advisory only — do not modify
  any files; answer on stdout." (`~/.gemini/agy.md` also enforces an advise-only default.)
- **Convention: no model flag.** As of agy ≥1.0.5 a `--model` flag exists (and an `agy models`
  subcommand lists choices), but our convention is to omit it and let `agy` use the
  Antigravity-account configured model — do NOT add `--model` unless a call explicitly needs a
  specific model. There is no short `-m` alias.
- **No env prefix.** `agy` authenticates via the Antigravity account (`~/.antigravity/`); the
  old `GOOGLE_CLOUD_PROJECT= GEMINI_API_KEY=` OAuth-forcing prefix does NOT apply.
- **Headless prompt:** `-p` / `--print` / `--prompt`. Output is plain text on stdout.
  `--print-timeout` defaults to `5m`; raise it for long deliberations.
- Capture `served_by` at the call layer where verdict provenance matters (append a probe
  line to the prompt) — self-reported model identity is unreliable.
- Skills delegating headlessly should call `agy --sandbox -p` and follow this pattern. See the
  `antigravity-cli` skill for full operational notes.
