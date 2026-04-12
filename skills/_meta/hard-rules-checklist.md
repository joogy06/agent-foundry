# Hard Rules Checklist

Compact summary of critical HARD-RULEs across the ecosystem. **Read this at every decision checkpoint** — before spawning agents, before claiming completion, before routing tasks.

This file exists because AI models lose track of rules in long sessions. It is a nudge, not a replacement for the full skill files.

---

## When to Read This File

| Checkpoint | Trigger |
|-----------|---------|
| **Session start** | First message in a new project directory — run project context + wiki binding checks, then autonomy/forge prompts |
| **First skill invocation** | First time ANY skill is triggered in a session — scan CLAUDE.md global + project-local for hard rules and surface them to the user |
| **Before spawning design team** | About to run forge design exploration |
| **Before spawning bob** | About to delegate to executor |
| **Before spawning alf** | About to run a review |
| **Before claiming work complete** | About to tell user "done" |
| **Before any gate check** | About to run gates.py G1/G2/G3 (subprocess, not prose) |
| **Before any ledger transition** | About to apply a transition request via claims.apply_request_idempotent |
| **Before metacognitive audit** | About to spawn cold-context auditor via audit_spawn.py |
| **Mid-session (every 3-4 tool calls)** | Ambient check — scan the list, verify compliance |
| **When uncertain** | Feeling like you might be skipping something |

---

## The Rules (grouped by when they matter)

### SESSION START

- [ ] **Project context check** — before any work in a project directory, read (in this order): `PROJECT.md`, `history.md`, `tasks.md`, `docs/plans/*.md`, `docs/components/*/COMPONENT.md`, `session_control.md`, `index.md`. Don't repeat finished work, don't re-litigate settled decisions.
- [ ] **Wiki binding check** — check for `.wiki-link` (root or parent), `.wiki/` subdirectory, and `~/.wiki-registry.yaml` entries matching CWD. If bound, mention the wiki(s) in the session opening. Honor `auto_consult` and `auto_filing` flags. Shared wikis still require approval for NEW pages/ingestions.
- [ ] **Autonomy prompt FIRST, then forge prompt** — ask autonomy mode, STOP, wait for answer. ONLY after the user responds, ask the forge prompt. NEVER combine the two into a single message. NEVER present both at once.
- [ ] **CLAUDE.md hard-rule scan — automated** — `~/.claude/skills/_meta/scan_hard_rules.py` scans global + project-local CLAUDE.md for HARD-RULE directives and diffs against this checklist. Runs automatically via **SessionStart hook** (injects `additionalContext` at session start) and also as **forge Step 1** (catches subagent / post-`cd` invocations). If the scan surfaces potentially missing rules, surface the diff to the user with a 1-line summary and ask: "add to checklist / wire into a skill / apply ad-hoc / ignore?" — do NOT silently skip. Manual fallback: `python3 ~/.claude/skills/_meta/scan_hard_rules.py` (plain mode).
- [ ] **Superpowers version tracker** — on session start, compare latest plugin version to `~/.claude/skills/forge/superpowers-tracked.md`. If drift, alert the user and offer a review.

### DESIGN PHASE (forge)

- [ ] **Codex + Gemini in parallel for MEDIUM/COMPLEX** — ALWAYS run Codex AND Gemini alongside Claude agents. Three models, not one. If either is unavailable, note the gap explicitly. Check Gemini via `mcp__gemini-cli__ping()`.
- [ ] **Never code before design approval** — no implementation until design is presented and user approves.
- [ ] **Performance expectations** — if task touches endpoints/queries/UI, ask about concurrency, latency, hot-path.
- [ ] **Gap detection** — check if needed skills exist before design exploration. Follow gap-detection.md protocol.

### EXECUTION PHASE (bob)

- [ ] **Bob does NOT orchestrate teams** — for 3+ WPs, delegate ALL orchestration to agent-teams.
- [ ] **Bob direct-execute for small jobs** — 1-2 S-complexity WPs with no cross-component deps can skip agent-teams.
- [ ] **Test discovery before "run tests"** — read PROJECT.md testing section, scan for framework, don't assume.
- [ ] **Caller-aware output** — detect if spawned by forge/alf/PA/standalone and adjust output accordingly.
- [ ] **Structured checkpoints** — for 7+ WPs, write YAML checkpoint to .bob-checkpoint.md.

### CONTRACT-DRIVEN EXECUTION (new)

- [ ] **G1 via subprocess** — `gates.py G1` returns 0 before any contract-driven skill runs. Prose NEVER/MUST NOT is a backstop only; the subprocess is the gate. After the ledger exists, never pass `--no-ledger-binding`.
- [ ] **G2 via subprocess** — `gates.py G2` returns 0 before any contract-driven skill runs. Fail fast on any V1-V15 violation.
- [ ] **G3 via bob-issued claims** — bob runs `claims.issue_claim(wp, skill)`, hands the skill an opaque UUID, and the skill NEVER writes claim files itself (CB4).
- [ ] **Frozen-map as freeze-the-world** — gaps during execution trigger `pause_state.py` freeze. Forge updates map with revision increment. Teams reconcile (or force-restart) on resume. Never edit the signed YAML in place.
- [ ] **Ledger is bob-only** — skills emit transition requests to `.ledger/requests/`; bob applies via `claims.apply_request_idempotent`. Skills NEVER edit `progress/integration-ledger.md` directly.
- [ ] **Metacognitive audit is cold-context** — `audit_spawn.py` spawns a fresh Claude subagent via `claude -p --output-format json` AND runs `codex exec --ephemeral -s read-only`. Both must return strict JSON with ≥3 structured disagreements. AUDIT_UNAVAILABLE = escalate, never auto-approve.
- [ ] **Flow tests are declared only** — `integration-flow-testing` uses the `flows:` block in the contract map. NEVER auto-traverse the call graph (M5 fix).
- [ ] **Semantic types required** — inputs lacking `semantic_type` from the v1 registry (or project-local override) or a valid `technical: <closed-list>` or `kind: opaque` fail G2.
- [ ] **Trusted runner owns execution** — bob's `trusted_runner.run_trusted_test_suite` runs tests and produces bundles tagged `produced_by: bob-trusted-runner`. Skills NEVER execute tests (CB3).
- [ ] **Anti-drift is event-triggered** — re-read this checklist at structural events (before any gate check, before any ledger transition, before metacognitive audit), not on a turn count.
- [ ] **Drift canary** — emit ledger header `drift_canary: "ALDEBARAN-7"` verbatim every 20 events. Paraphrase or omission = drift detected, halt.
- [ ] **Skill file checksums** — bob logs sha256 of every invoked skill file at startup and before each gate check. Any mid-session skill-file mutation is caught.

### REVIEW / COMPLETION

- [ ] **Evidence before assertions** — never claim "done" or "passing" without showing command output.
- [ ] **Spot-check verification** — re-run at least one verification artifact independently.
- [ ] **Performance dimension** — if change touches hot-path/API/DB, include performance measurement in evidence.

### ROUTING (PA / CLAUDE.md)

- [ ] **Complexity pre-filter** — TRIVIAL/SIMPLE bypass forge. MEDIUM/COMPLEX go through forge.
- [ ] **PA is optional** — skills work standalone. Conditionally integrate with PA if MCP available.
- [ ] **Forge is a skill (inline)** — not a subagent. Runs in same thread, no context loss.

### GAP DETECTION

- [ ] **Never block active task** — log gap, proceed with general knowledge, offer creation at task completion.
- [ ] **Use policy matrix** — don't classify criticality on gut feeling. Score 0-4.
- [ ] **Dedup gaps** — check gap_key before logging. Update existing entry, don't append duplicates.
- [ ] **Inline notice for CRITICAL** — show notice NOW, offer at completion in same response.

### TEMP FILES

- [ ] **Always mktemp -d** — never hardcode /tmp/ paths. `$(mktemp -d /tmp/<prefix>-XXXXXXXXXX)`.
- [ ] **Session-scoped** — each invocation gets its own temp dir. No cross-session collisions.

### CROSS-MODEL (Codex + Gemini)

- [ ] **env-adoption session state** — verify `~/.claude/state/inventory.json` exists and is <24h old. If missing or stale, run `bash ~/.claude/skills/env-adoption/scripts/probe.sh check` once. Read capabilities from session state, not inline probing.
- [ ] **Timeout all codex exec** — wrap with `timeout 120`. Fallback on timeout.
- [ ] **Escalation terminates** — Claude 2x → Codex 1x → user. Never loop.
- [ ] **Session-scoped Codex availability** — read `tools.codex.installed` from inventory. Don't re-probe every invocation.
- [ ] **Gemini for COMPLEX tasks** — MEDIUM = Codex only. COMPLEX = Codex + Gemini. Don't use Gemini for simple tasks (quota waste).
- [ ] **Gemini availability check** — read `capabilities.gemini_analyst` from session state. Fallback to Codex-only if false.
- [ ] **Gemini 1M context** — use Gemini for large file analysis, codebase-wide reviews, and research where context size matters. Codex for focused code review and challenger work.

---

### WIKI (wiki agent and skill)

- [ ] **Cite every claim** — every factual statement in a `wiki/` page gets `[Source: raw/<file>, p.<N>]`. No exceptions. Lint check #3 enforces.
- [ ] **Raw layer is immutable** — never modify files in `raw/` after deposit. Re-ingest creates numeric-suffixed (`-2`, `-3`) versions.
- [ ] **Single-writer lock** — check `.wiki.lock` before any write; acquire, write, release in finally.
- [ ] **Lint after batch ingest** — mandatory trigger for batch mode. See `~/.claude/skills/wiki/lint.md` mandatory triggers.
- [ ] **Index-first navigation** — read `index.md` first, grep second, targeted reads third. Never walk the full `wiki/` tree.
- [ ] **Interactive mode confirms** — single-source ingests must present the page plan and get user approval before writing.

## How to Use

This is NOT a skill to invoke. It is a reference file to READ at checkpoints.

```
Pattern for any agent/skill at a decision point:

1. Pause before the action
2. Scan the relevant section above (2-3 seconds)
3. Check: am I violating any of these?
4. If yes: correct before proceeding
5. If no: proceed
```

**For forge specifically:**
- Read "DESIGN PHASE" section before Step 6 (design exploration)
- Read "CROSS-MODEL" section before spawning Codex agents
- Read "EXECUTION PHASE" section before Step 9 (spawn bob)

**For bob specifically:**
- Read "EXECUTION PHASE" section before Step 3 (delegate)
- Read "REVIEW / COMPLETION" section before Step 5 (compile report)

---

## Maintenance

When HARD-RULEs are added or changed in any skill/agent, update this file.
Alf should check this file's freshness during sweeps — compare against actual HARD-RULE tags in skills.
