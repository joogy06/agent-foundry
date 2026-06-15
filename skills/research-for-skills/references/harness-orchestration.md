# Harness-orchestration authoring reference (HO-1..HO-7, S055)

This reference is LINKED from the research-for-skills Step-7 HO gate. It gives the
capability model, the three-layer pattern, copy-paste templates, the
companion-workflow decision table, the schema-twin rule, the ledger/worktree
hazards, the cross-model phrasing guide, and the anti-patterns — so EVERY future
skill that wants to fan out is correct by construction.

The canonical orchestration conventions live in `~/.claude/workflows/README.md`
(G-W / W-rules) and the live capability recipe in
`~/.claude/skills/env-adoption/references/context-detection.md`. This file does
NOT restate them — it teaches a skill author how to comply.

## The capability model

| # | Question | Answered by | Lifecycle |
|---|----------|-------------|-----------|
| Q1 | Does this HOST have an orchestration-capable Claude Code? | `inventory.json → harness.*` | persistent, 24h |
| Q2 | Does this SESSION's harness expose the surface? | session file `capabilities.*` | per-session |
| Q3 | Can THIS context call it RIGHT NOW? | `probe.sh context` / tool-list check | live, NEVER cached |

The decision rule, restated verbatim in every consumer:

```
can_orchestrate = capabilities.<surface> AND context == main-loop
```

`capabilities.*` alone NEVER authorizes orchestration — session files are keyed
by the ROOT session ID and are SHARED with subagents (children inherit
`CLAUDE_CODE_SESSION_ID`). `probe.sh get capabilities.<name>` is the ONLY
capability read API: no raw `jq` on `inventory.json`, no inline `claude --version`.

## The three-layer pattern (HO-3 fallback-first)

1. **Portable flow (PRIMARY, always documented):** the skill's instructions
   complete with zero orchestration primitives. This is what Codex / Copilot /
   VS Code / older-Claude / every subagent runs.
2. **Fast-path enhancement (clearly fenced):** when (and only when)
   `capabilities.<surface> AND context == main-loop`, the main loop MAY invoke
   the companion workflow. Always fall back to the portable flow on any failure.
3. **Subagent behavior (HO-4):** a skill running as a subagent either runs the
   portable flow, OR emits a plan ARTIFACT (host-neutral DATA — never executable
   JS, S052) and HALTs, citing the artifact path. A failed spawn is proof you are
   a subagent, not a retry candidate.

### Conditional fast-path stanza (copy-paste)

```markdown
## Fast path — `<workflow>` workflow (optional, main-loop only)

When `probe.sh get capabilities.<surface>` is true AND `probe.sh context ==
main-loop` (the ONLY capability API; capabilities.* alone never authorizes), the
main loop MAY run the `<workflow>` saved workflow: <one-line phase summary>. The
schemas live in `schemas/`. <What stays inline — user decisions, doc writes,
gate verdicts.> On any fast-path failure, fall back to the portable flow below.
```

### W-EXT wrapper stanza (external-model output)

```markdown
Every external-CLI field group carries the W-EXT envelope (invocation /
raw_transcript / transcript_path / transcript_sha256 / served_by / absence).
EVERY composed command includes `agy --sandbox` (#157), `codex exec -s
read-only`, `< /dev/null` (#135/#155), and a shell `timeout`. Command custody is
args-supplied — no workflow file embeds an external-CLI command line. NOTE
(WP-2): agy is UNREACHABLE from workflow stages — pre-launch the transcript
inline and pass it via args.
```

## Companion-workflow decision table (HO-6)

| Ship a companion workflow? | Condition |
|---|---|
| YES | inline-main-loop primary callers AND stable reusable fan-out (≥3 sequential stages OR ≥2 parallel agents) AND deterministic stage boundaries AND schema-checkable outputs |
| NO | knowledge-only skill; mid-flow user interaction (G-W4); machinery-under-worktree (G-W6); primary callers are AGENTS (they cannot invoke workflows) |

Shipping a companion workflow triggers G-W7 registration: lab shadow + README
manifest row + governance_watchlist entry + FRESHNESS anchor, or it is not
shipped.

## Schema-twin rule (HO-5 / G-W2)

The canonical JSON Schema lives in the skill's `schemas/` (owned by a SKILL) or
`_meta/schemas/` (owned by an agent / cross-artifact machinery). The companion
workflow embeds a hash-annotated literal twin
(`// SCHEMA-TWIN: <id> sha256:<first16>`); the watchlist lint recomputes and
compares. Every schema is REGISTERED in `_meta/schemas/registry.v1.json` (R9 —
no schema ships unregistered).

## Ledger / worktree hazards

- **Ledger + checkpoint are bob-only (CB4):** `progress/integration-ledger.md`,
  `.ledger/**`, `.bob-checkpoint.md`. A skill NEVER writes them; it emits
  transition requests to `.ledger/requests/` and bob applies them.
- **Worktree isolation strands pipeline-machinery artifacts:** a stage that emits
  `.ledger/requests/`, claim heartbeats, or `.wiring/runs/` MUST run in the
  canonical tree, never under worktree isolation. Only pure-implementation
  `executor: worker` WPs go worktree-isolated, merged via the controlled merge
  step (`_meta/worktree_merge.py`, forbidden-path rejection).

## Cross-model phrasing guide (HO-7 host-neutral)

- Name CAPABILITIES, not Claude-only tools: "the agent-spawn facility (`Agent` on
  Claude Code; see env-adoption tool-mapping for Codex/Copilot)".
- Every plan/report artifact is host-neutral data executable serially by any host
  (VS Code Copilot / Codex conform).
- Only workflow COMPILATION is described as Claude-main-loop-only.
- The skill DESCRIPTION never names Workflow / native teams — that is CSO
  pollution on other hosts (their skill listing would mislead).

## Anti-patterns

- Make a skill DEPEND on Workflow/native teams → breaks Codex/Copilot and every
  subagent context. Fix: optional + feature-detected + fallback-first +
  host-neutral.
- Inline-probe `claude --version` or raw-jq `inventory.json` for a capability →
  use `probe.sh get capabilities.<name>`.
- Trust `capabilities.*` without the context conjunct → a subagent will
  misclassify itself as the main loop.
- Embed an external-CLI command line in a workflow file → command custody is
  args-supplied (single update site).

<!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: claude-code-workflow-surface
    verified_against: "2.1.173 (orchestration surface; layout frozen WP-2 forge #159)"
    verified_on: "2026-06-11"
    volatility: high
-->
