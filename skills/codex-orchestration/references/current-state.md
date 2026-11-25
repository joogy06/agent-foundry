# Codex Orchestration — current state and verified facts

Read this file for what is installed, configured and verified on this host. When it is read, return to SKILL.md.

"Seat Models" is a section of SKILL.md. The "Reasoning-Effort Tiers" detail is in `references/effort-tiers.md`.

## Current State (verified 2026-09-14)

| Component | Version / Value |
|---|---|
| Codex CLI | v0.154.0 (`codex-cli`; `client_version` in `~/.codex/models_cache.json`, and `codex --version` agrees) |
| Antigravity CLI | v1.4.3 (`agy`; `~/.claude/state/inventory.json`, and `agy --version` agrees) — headless `agy -p`, self-authenticating, no MCP wrapper |
| Codex model | **Pinned per role** by `seat_model.py` — never inherited from `config.toml`. TOP auto-follows the roster (`gpt-6-astra`); the sized light/medium main seats read the codex std tier and `consultant_support` the codex support tier, both from `skills/_meta/model_roster.py` (current values in "Seat Models"). What resolves right now: `seat_model.py emit --json` |
| agy model | **Pinned per role** by `seat_model.py argv --provider agy` — the newest listed version of the roster family, `model_roster.AGY_FAMILY` (rev 6: `gemini-4-argon-high` / `-medium`; with `--size` the level follows the task size, rev 7: light `-low`, medium `-medium`, complex `-high`). The account default (an older Gemini model, self-reported, of a now-forbidden family) is never relied on |
| Reasoning effort | pinned per call inside the same seat fragment (see Reasoning-Effort Tiers) — the config default is TUI-persisted and untrustworthy for headless calls |
| Claude seats | Named by TIER: the Claude main tier and support tier come from `skills/_meta/model_roster.py` (current values in "Seat Models"; swapping them: `docs/model-roster-swap.md`). The aliases resolve vendor-side: `seat_model.py model --role <role> --provider claude` |
| Codex plugin | **NOT INSTALLED** — every `/codex:*` command is a dead path |
| Handover mechanism | session-scoped temp dirs + `codex exec -o` |

### System Configuration

```toml
# ~/.codex/config.toml (as of 2026-09-24) — whatever the TUI last persisted.
# Effort levels for gpt-6-sol: low | medium | high | xhigh | max | ultra
model = "gpt-6-sol"
model_reasoning_effort = "medium"  # TUI-persisted; do NOT rely on either line — seat_model pins both per call
```

### Model Override — pin the model, never inherit it

The interactive `/model` picker persists both `model` and `model_reasoning_effort` into
`config.toml`, and headless `codex exec` inherits both. **Earlier versions of this skill said
"omit `-m` in delegation calls and pin only the EFFORT". That instruction was the bug:** an
unpinned call runs on whatever model the TUI last selected. Pin the model on EVERY delegation
call, for exactly the reason the effort is already pinned:
`PIN="$(python3 ~/.claude/skills/_meta/seat_model.py argv --role <role> --provider codex)" && timeout <T> codex exec … $PIN …`
(roles, timeouts, `--ephemeral` and budget in "Seat Models"). A hand-typed `-m <slug>` is
acceptable only for a deliberate one-off outside the role table; never hardcode a TOP slug as a
recommended pin, because TOP roles follow the roster.

### Cross-Model Advantage

Claude and the role-pinned Codex model have different strengths. Use both:

| Strength | Claude (main-tier seats) | Codex (role-pinned model) |
|---|---|---|
| Context window | 1M tokens | provider default (not verified per model) |
| Tool ecosystem | MCP, skills, agents, Read/Edit/Grep | Shell, file I/O, web search |
| Code editing | Precise Edit tool with diffs | Full-file rewrites |
| Orchestration | Agent spawning, parallel teams | Multi-agent feature |
| Unique value | Skill library, conversation memory | Independent perspective, web search |

**Key principle**: Use Codex for tasks where a *different model's perspective* adds value — challenger reviews, second opinions, independent research. Don't use it as a replacement for Claude's tool ecosystem.

### New since 0.118 (subcommands added through 0.137.0)

The Codex CLI grew several subcommands between 0.118 and 0.137. Most are experimental backend
services, not day-to-day delegation entry points — `codex exec` remains the orchestration
surface (the plugin commands are a dead path on this host). Confirm any of these with `codex <sub> --help` before relying on it.

| Subcommand | What it is | Relevance to orchestration |
|---|---|---|
| `codex exec-server` | [EXPERIMENTAL] Run the standalone exec-server service | Persistent backend that serves repeated `codex exec` requests without per-call spawn — relevant only if you orchestrate many non-interactive runs and want to amortise startup. |
| `codex app-server` | [experimental] Run the app server / related tooling | Backend for an app/IDE integration. Not used by headless delegation; ignore unless wiring Codex into an app. |
| `codex remote-control` | [experimental] Manage the app-server daemon with remote control enabled | Drives an app-server daemon out-of-process. Niche; not part of the `codex exec` path. |
| `codex cloud` | [EXPERIMENTAL] Browse Codex Cloud tasks and apply changes locally | Cloud delegation of long-running tasks (billed). Surfaced as an affordance; treat as opt-in. |
| `codex features` | Inspect feature flags | Read which feature flags are active (pairs with the `--enable`/`--disable` / `-c features.<name>=…` overrides). Handy when a capability is gated. |

(Also present but already documented elsewhere in this skill: `archive` / `unarchive` for saved
sessions, `mcp-server` to run Codex itself as an MCP server, `completion` for shell completions.)

## Verified facts (verified 2026-09-14)

| Fact | Status |
|---|---|
| `codex exec --search` flag | **DOES NOT EXIST** (re-checked against `codex exec --help`, 0.154.0). Codex web search is automatic via the model's tool use when the sandbox allows. |
| Codex CLI version | 0.154.0 (`client_version` in `~/.codex/models_cache.json`; `codex --version` agrees) |
| agy version | 1.4.3 (`~/.claude/state/agy-models.json` 2026-10-20; `agy --version` agrees) |
| Codex plugin | **NOT INSTALLED** — `~/.claude/plugins/installed_plugins.json` lists only `superpowers@claude-plugins-official` |
| Codex roster (`visibility == "list"`, 2026-09-24) | `gpt-6-astra` (priority 1), `gpt-6-sol` (2, the std tier), `gpt-6-luna` (3), `gpt-5.6-sol` (4; **priority FLAPS** — observed 4 at 2026-09-15T14:38:49Z, 1 at 20:45:50Z tied with `gpt-6-astra`, 4 at 22:25:15Z, 1 again at 22:38:08Z; in those ties `gpt-6-astra` held TOP by generation), `gpt-5.6-terra` (7, the support tier), `gpt-5.6-luna` (8), `gpt-5.5` (12, retires 2026-10-14); hidden: `gpt-reserve` (3), `codex-auto-review` (43); no GPT-6 Terra exists; `upgrade` null on every 5.6/6 entry (it flaps — never auto-follow it); `minimal` supported by none. A tie between astra and `gpt-6-sol` (both generation 6) is decided by incumbent, then slug; a TOP that resolves to a std/support model is flagged `top_resolved_to_std` |
