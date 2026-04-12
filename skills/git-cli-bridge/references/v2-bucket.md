# v2 Bucket Reference — git-cli-bridge

Features intentionally deferred to v2 with explicit revisit triggers. Ports Section 6.9 and 9.9 of the design doc. Do NOT build these features in v1; they are listed so future bob/forge cycles have a clear starting point.

## Quick table

| ID | Feature | Trigger to revisit | Rough effort |
|---|---|---|---|
| v2.1 | **Cloud Run webhook execution venue** | User's Actions latency proves unacceptable (>120s p50) AND user is willing to maintain a Cloud Run service | M — 2-3 weeks |
| v2.2 | **Namespace refs** (`refs/sessions/<id>`) | Branch proliferation becomes annoying; requires `repository_dispatch` workaround for triggers | M — 1 week |
| v2.3 | **`kind: agent`** — full agentic delegation | v1 usage shows concrete need for multi-file edits, sandbox policy, commit budgets | L — ~2.5x v1 effort |
| v2.4 | **B3 Contents API transport** | User wants unified audit log AND `gh` CLI confirmed always available on target hosts | M — 1 week |
| v2.5 | **Gemini A2A protocol integration** | `@google/gemini-cli-a2a-server` moves from preview to stable; protocol bridges may replace git transport | M — 1-2 weeks |
| v2.6 | **Bob integration (direct Gemini/Copilot calls from bob's own code paths)** | Bob gains NEW code paths that call `mcp__gemini-cli__ask-gemini` or `copilot -p` directly (bypassing `codex-orchestration`) | S — 1-3 days |
| v2.7 | **Streaming responses** | Unlikely to ship — fundamentally conflicts with git-only transport | L — would require a different transport |
| v2.8 | **Multi-user / team bridge** | Explicitly out of scope; do NOT retrofit | L — new trust model, new secret scoping |

## v2.1 — Cloud Run webhook

**What**: Replace GitHub Actions as the execution venue with a Cloud Run service that the workstation can hit via webhook over HTTPS. Expected latency drops from ~90s cold to ~2-5s.

**Why deferred**: User ruling A3 prefers Actions v1 to avoid operating a Cloud Run service. Actions is simpler, free-tier-friendly, and audit-transparent. Cloud Run adds deployment, secrets, autoscaling, logs, billing — real ops overhead.

**Revisit when**: measured p50 latency is consistently above 120s for 2+ weeks AND the user explicitly asks for faster turnaround. Keep Actions as a fallback even after Cloud Run ships; this is a "second venue", not a replacement.

**Schema impact**: add `venue: actions | cloudrun` to request.md frontmatter; clients choose venue per request. Workflow YAML is replaced by a small FastAPI / Cloud Functions server reading the same schema.

## v2.2 — Namespace refs

**What**: Use `refs/sessions/<id>` instead of `refs/heads/session/<id>` for session refs. This hides sessions from the normal branch list (`gh branch list`) without breaking git transport, and lets `git for-each-ref refs/sessions/*` do clean enumeration.

**Why deferred**: Branch pushes to `refs/sessions/**` do not trigger `on: push: branches: ...` workflows out of the box. GitHub Actions requires `repository_dispatch` or a different event trigger, which is a bigger change than the benefit warrants in v1.

**Revisit when**: branch proliferation becomes visually annoying in the bridge repo's `branches` page; multi-session workflows are normal; user wants a cleaner `gh pr list` experience.

## v2.3 — `kind: agent`

**What**: Add a fourth job kind that lets the CLI act as an agent inside the workflow runner, making multiple file edits, invoking tools, and committing changes back. Requires a sandbox policy, file allowlist, max commit budget, and auto-review hooks.

**Why deferred**: User ruling Q2=F restricts v1 to `review + research + prompt`. Agentic delegation is a much bigger surface — prompt injection becomes multi-step, cost becomes unbounded, audit becomes harder. Ship v1, learn, then add.

**Schema impact**: The `request.md` schema already reserves forward-compatible fields for `kind: agent`:

- `agent_config.sandbox_policy: strict | moderate | permissive`
- `agent_config.file_allowlist: [glob, ...]`
- `agent_config.max_commits: int`
- `agent_config.max_tool_calls: int`
- `agent_config.require_human_review_before_push: bool`

**Revisit when**: v1 is stable for 2+ weeks AND a concrete use case is documented (e.g., "forge wants Gemini to write a test file and commit it back").

## v2.4 — Contents API transport (Approach B3)

**What**: Instead of `git push` / `git fetch`, use the GitHub Contents REST API to write `request.md` and read `response.md`. Pros: unified audit log (every read/write is a GitHub API event), no git dependency on the workstation for bridge operations, simpler cleanup. Cons: requires `gh` CLI or a PAT on the workstation, loses git history for free.

**Why deferred**: Approach A (per-session orphan branches) won in the forge design exploration; B3 is a clean v2 path when GitHub tightens permissions on `gh` CLI.

**Revisit when**: `gh` CLI is a hard dependency on all target workstations AND user wants the unified audit log benefit.

## v2.5 — Gemini A2A integration

**What**: Google's Gemini CLI ships a preview A2A (Agent-to-Agent) protocol server (`@google/gemini-cli-a2a-server@0.36.0` as of 2026-04-07). If it goes GA stable and gains wide adoption, it may provide a standard wire protocol for agent-to-agent calls that could replace the git transport for the Gemini path.

**Why deferred**: A2A is still in preview; the git transport is uniform across Gemini and Copilot (Copilot has no equivalent protocol); introducing A2A as a Gemini-only alternative fragments the architecture.

**Revisit when**: A2A is GA AND Copilot ships a compatible protocol AND the standard has wider industry adoption.

## v2.6 — Bob integration clarification

**What**: v1 explicitly leaves `bob` untouched (integration scope C per ruling Q4). Bob's Gemini/Copilot delegation happens via `codex-orchestration`, which v1 patches to be bridge-aware. **Bob therefore inherits bridge mode transparently in v1 — no direct bob changes needed for the current call graph.**

**Revisit trigger**: v2.6 is specifically reserved for the future case where bob gains NEW code paths that call `mcp__gemini-cli__ask-gemini` or `copilot -p` directly, bypassing `codex-orchestration`. That does not exist today. Revisit only when such a path is proposed in a future design.

**If it happens**: the patch surface is small — add the same `bridge-mode-detect.sh` conditional to any bob file that directly invokes Gemini/Copilot. Mirror the `codex-orchestration` patch shape.

## v2.7 — Streaming responses

**What**: Stream tokens from the CLI to the client as they are generated, instead of waiting for a full `response.md` commit.

**Why deferred**: Git is a block-oriented transport. There is no meaningful "stream" over `git push` / `git fetch`. Implementing would require a second channel (HTTP SSE, WebSocket) which contradicts the git-only premise. This is the one v2 item most likely to NEVER ship.

**Revisit when**: a new transport arrives (v2.1 Cloud Run would make streaming feasible).

## v2.8 — Multi-user / team bridge

**What**: A single `ai-bridge-<team>` repo shared by multiple users, with per-user sessions, per-user auth, and quota tracking per user.

**Why deferred AND explicitly out of scope**: The v1 threat model is single-user and single-trust. Adding multi-user breaks most of the invariants: the PAT becomes team-wide, the WIF binding needs to federate across users, `github.actor == github.repository_owner` stops making sense, blast radius grows.

**Revisit when**: a genuinely new design covers the trust and isolation model. This is not a retrofit — it is a v2 rewrite. Do NOT attempt to extend v1.

## Non-v2 — things we thought about and rejected

- **Self-hosted runners** instead of GitHub-hosted. Rejected because they re-introduce the outbound network problem the bridge is meant to solve.
- **Putting the bridge in the work repo** (same-repo `.ai-bridge/` directory). Rejected per ruling Q3=B — blast radius, coupling to the work repo's git history, collisions with real PRs.
- **Long-polling webhook** from the workstation to GitHub. Rejected because the workstation has no inbound network; only outbound git is reachable.

## Principles for v2 work

- **Every v2 item starts as a new forge design cycle**, not an in-place edit of this skill.
- **v2 changes MUST preserve v1 backward compatibility** — existing `session/**` branches and workflow YAMLs must continue to work on the day v2 ships.
- **Schema version bumps** go through the version handshake in `protocol.md` §8. `schema_version: 2` requests must never be accepted by a `schema_version: 1` workflow.
- **Security invariants SEC-1 through SEC-12 are load-bearing** — do not relax them in v2 without forge-level design review.
