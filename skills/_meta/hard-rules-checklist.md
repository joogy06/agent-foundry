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

- [ ] **Check for `PROJECT.md`** — hierarchical architecture map: components, integration edges, external dependencies. Read this FIRST for project understanding.
- [ ] **Check for `session_control.md`** — contains session-specific instructions and priorities.
- [ ] **Project context check** — before any work in a project directory, read (in this order): `PROJECT.md`, `history.md` (head+tail only if >400 lines; check `history/INDEX.md` for older context), `tasks.md`, `docs/plans/*.md`, `docs/components/*/COMPONENT.md`, `session_control.md`, `index.md`. Don't repeat finished work, don't re-litigate settled decisions.
- [ ] **Wiki binding check** — check for `.wiki-link` (root or parent), `.wiki/` subdirectory, and `~/.wiki-registry.yaml` entries matching CWD. If bound, mention the wiki(s) in the session opening. Honor `auto_consult` and `auto_filing` flags. Shared wikis still require approval for NEW pages/ingestions.
- [ ] **Autonomy + Forge are always-on (no prompt)** — autonomy is globally configured in `~/.claude/settings.json` (acceptEdits + Bash(*) + git push ask). Forge routing is always-on per CLAUDE.md. Do NOT ask the user about autonomy or forge mode. Just route tasks through forge automatically per the Routing by Complexity rules in CLAUDE.md. The only session-start questions should be about the user's TASK, not about mode configuration.
- [ ] **CLAUDE.md hard-rule scan — automated** — `~/.claude/skills/_meta/scan_hard_rules.py` scans global + project-local CLAUDE.md for HARD-RULE directives and diffs against this checklist. Runs automatically via **SessionStart hook** (injects `additionalContext` at session start) and also as **forge Step 1** (catches subagent / post-`cd` invocations). If the scan surfaces potentially missing rules, surface the diff to the user with a 1-line summary and ask: "add to checklist / wire into a skill / apply ad-hoc / ignore?" — do NOT silently skip. Manual fallback: `python3 ~/.claude/skills/_meta/scan_hard_rules.py` (plain mode).
- [ ] **Superpowers version tracker** — on session start, compare latest plugin version to `~/.claude/skills/forge/superpowers-tracked.md`. If drift, alert the user and offer a review.

### DESIGN PHASE (forge)

- [ ] **Codex + Antigravity (agy) in parallel for MEDIUM/COMPLEX** — ALWAYS run Codex AND agy alongside Claude agents. Three models, not one. If either is unavailable, note the gap explicitly. Check agy availability via `command -v agy` (then a `agy -p "ping"` smoke call); agy returns plain text on stdout, not structured fields.
- [ ] **Never code before design approval** — no implementation until design is presented and user approves.
- [ ] **Performance expectations** — if task touches endpoints/queries/UI, ask about concurrency, latency, hot-path.
- [ ] **Gap detection** — check if needed skills exist before design exploration. Follow gap-detection.md protocol.

### EXECUTION PHASE (bob)

- [ ] **Contract map routing (caller-independent)** — after reading the design in Step 1, bob MUST determine if it introduces components. If yes and no contract map exists, HALT. This applies regardless of whether forge, alf, pa, or a user spawned bob. See Step 1 → Step 1.5 Gate routing table.
- [ ] **Orchestration inversion (S055)** — the agent-spawn facility (`Agent`) and the workflow facility (`Workflow`) are MAIN-LOOP-ONLY. Bob as a subagent/workflow stage has NEITHER. Delegation flows UP: for 3+ WPs or M/L, bob delegates POLICY to agent-teams in-context, materializes `progress/work-packages.yaml` (host-neutral DATA, never executable JS — S052), and HALTs `PARTIAL needs: plan-execution`. The MAIN LOOP runs the plan (preferred: `bob-serial-exec` workflow when `capabilities.workflow_tool` true via `probe.sh`; fallback: serial-with-checkpointing). NEVER attempt a spawn "just in case" — a failed spawn is proof you are a subagent, not a retry candidate.
- [ ] **Orchestration decision rule** — `can_orchestrate = capabilities.<surface> AND context == main-loop`. `capabilities.*` alone NEVER authorizes orchestration (session files are shared with subagents). Read capabilities via `probe.sh get capabilities.<name>` ONLY — no raw jq, no inline `claude --version`.
- [ ] **BOB_MODE stage personas (S055)** — `BOB_MODE: execute-work-package | finalize | resume-amendment` in the spawn prompt OVERRIDES Steps 1-3 + HR1 items 1-4. execute-work-package is bound to plan_hash + wp_id, skips decomposition, forbids further orchestration, and emits a schema-mapped `execution-report.v1`. Validate the run lease (`claims.validate_run_lease`) on EVERY bob-owned mutation.
- [ ] **AWAITING_AMENDMENT park (S055)** — a scope-pause that needs user amendment parks via `PAUSED → AWAITING_AMENDMENT` (non-expiring) and exits `PARTIAL needs: forge-amendment-mode`. Do NOT stay PAUSED (rolls back at 600s). Resume ONLY via `BOB_MODE: resume-amendment` after a fresh plan revision — resume across an amendment is structurally impossible (cache-key change).
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
- [ ] **Worktree isolation strands pipeline-machinery artifacts** — skills that emit .ledger/requests/*.request.yaml, claim heartbeats, or .wiring/runs/ MUST run in the canonical tree, NOT inside an isolated git worktree (workflow agent isolation worktree or EnterWorktree) — otherwise transition requests and heartbeats land in the worktree, invisible to bob's request queue and heartbeat-revocation sweep. If an orchestrator isolates a WP, it must copy these artifacts back before bob's next sweep.

### EVERGREENING PHASE (evo)

- [ ] **Sole-orchestrator, never sole-writer** — evo orchestrates skills and spawns bob but NEVER writes `.ledger/scope-deltas/*` or `progress/integration-ledger.md` directly (bob stays sole CB4 writer); promotion to `.ledger/evo/latest.json` is bob's job under flock.
- [ ] **Bug-for-bug compatibility (B1 lock)** — NEVER fix pre-existing legacy bugs during an upgrade; legacy behaviour is the oracle for differential snapshot tests. Optimizations are advisory-only findings, never auto-applied.
- [ ] **G1 hard HALT on degraded CVE data** — mode-c (cve-fix) HALTs immediately with `EVO_HALT_DEGRADED_DATA` if dep-currency-check returns `gap_kind: unknown` on any direct dep. No warn-and-proceed; modes a/b continue.
- [ ] **Consultation default-on-timeout** — every consultation prompt declares an explicit default answer (reject unless auto-applicable patch-version CVE fix with passing tests) that fires after `EVO_CONSULT_TIMEOUT_HOURS`; decisions append-only to consult-log.jsonl.
- [ ] **Max 3 diagrams per consultation turn** — C4 container/component level only, never function-level; intent-map-render rejects function-level attempts with `EVO_HARD_RULE_5_VIOLATION`.
- [ ] **Sandbox path 0700** — clone path MUST be `$HOME/.cache/evo/sessions/<run_id>/clone/` with mode 0700, NEVER `/tmp/`; TTL cleanup mandatory; persistent artifacts live under `.ledger/evo/runs/<id>/`, not the sandbox.
- [ ] **Two-arm verification on prose intent** — `confidence_level: grounded` requires evidence_edges resolving in static.jsonl AND a cold-context second pass at ≥0.95 semantic similarity; single-arm output is `interpretive` and NEVER feeds gates or test generation.
- [ ] **Budget honesty → PARTIAL** — any env-budget exhaustion (tokens/files/lookups/runtime) marks the verdict PARTIAL with skipped work listed in `follow_ups[]`; never silently degrade output.
- [ ] **Out-of-scope remediations emit a handoff doc** — material fixes outside the current mode's scope MUST invoke the `handoff` skill (`/tmp/handoff-evo-<topic>-<date>-<uuid>.md`) with the suggested re-invocation; `follow_ups[]` entries cross-reference the handoff doc path. (Renumbered from HR8, 2026-06-10.)

### KNOWLEDGE GROUNDING

- [ ] **Check grounding tier before factual claims** — before stating facts, determine if the answer is verified (tier 1), grounded (tier 2), inferred (tier 3), or training-only (tier 4). Cite the source when tier 1-3.
- [ ] **Respect strict_airgap** — if `strict_airgap: true` in `~/.knowledge-grounding.yaml`, tier 4 answers require explicit user override. Never silently proceed with training-only data in strict mode.
- [ ] **Read sources.json, don't ad-hoc probe** — check `~/.claude/state/sources.json` for source availability. Don't bypass the manifest with inline checks.

### REVIEW / COMPLETION

- [ ] **Evidence before assertions** — never claim "done" or "passing" without showing command output.
- [ ] **Spot-check verification** — re-run at least one verification artifact independently.
- [ ] **Performance dimension** — if change touches hot-path/API/DB, include performance measurement in evidence.
- [ ] **Commit hygiene — no AI attribution** — never add `Co-Authored-By: Claude` (or any AI attribution) trailers to commit messages. Universal user preference across all projects. Inherited from `vs-code-personal-os` / `vs-code-foundry` AGENTS.md R6; promoted to global 2026-05-13.

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

### CROSS-MODEL (Codex + Antigravity (agy))

- [ ] **env-adoption session state** — verify `~/.claude/state/inventory.json` exists and is <24h old. If missing or stale, run `bash ~/.claude/skills/env-adoption/scripts/probe.sh check` once. Read capabilities from session state, not inline probing.
- [ ] **Timeout all codex exec** — wrap with `timeout 600`. Fallback on timeout.
- [ ] **Escalation terminates** — Claude 2x → Codex 1x → user. Never loop.
- [ ] **Session-scoped Codex availability** — read `tools.codex.installed` from inventory. Don't re-probe every invocation.
- [ ] **agy for COMPLEX tasks** — MEDIUM = Codex only. COMPLEX = Codex + agy. Don't use agy for simple tasks (quota waste).
- [ ] **agy availability check** — read `tools.agy.installed` (or the equivalent capability flag) from session state. Fallback to Codex-only if false.
- [ ] **agy large-context analysis** — use agy for large file analysis, codebase-wide reviews, and research where context size matters. Codex for focused code review and challenger work. agy is invoked headless via `agy -p "..."` (plain-text stdout; no `-m`/model flag, no env-key prefix — see the `antigravity-cli` skill).

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
