# Saved Workflows — the deterministic compiler (S055 workflow-adoption keystone)

Home: `~/.claude/workflows/` (user-global, flat). Lab shadow:
`~/.claude/workflows/`. Published to agent-foundry via the
existing publish pipeline (`source.subdirs` gains `workflows` — zero engine
change; **NO scrub rule targets `workflows/`**, G-W3).

These saved `.js` workflows ARE the compiler: an agent-emitted plan artifact
maps to `(saved workflow name, args object)` by a deterministic, judgment-free
mapping. **The main loop NEVER writes fresh JS in response to a plan artifact**
(laundering hazard, W-COMP). Only the compile-and-invoke step is
Claude-main-loop-only; every artifact crossing the boundary (plan, report,
spawn-request, finding batch) is host-neutral DATA (W-HN), executable serially
by any host's executor (Codex / Copilot CLI / VS Code Copilot conform).

`harness-orchestration.md` (research-for-skills) LINKS here and never restates
these rules. Where this file rules, it wins (Slice B is the family arbiter).

---

## Manifest (the 8 v1 workflows — R6 / W1)

| Workflow | Owner | Version | Nesting | Fallback section |
|----------|-------|---------|---------|------------------|
| `design-tournament` | forge | 1.0.0 | none | forge SKILL.md "Step 6B design exploration team (portable, canonical)" |
| `ratify-design` | forge | 1.0.0 | calls `cross-cli-deliberation` | forge SKILL.md Step 8b |
| `bob-serial-exec` | bob | 1.0.0 | none | bob.md HARD-RULE 1 item 3 (serial-with-checkpointing) |
| `alf-sweep` | alf | 1.0.0 | none | alf_sweep_launcher.sh `--inline` mode |
| `adversarial-tournament` | adversarial-team-brainstorm | 1.0.0 | none | adversarial-team-brainstorm SKILL.md inline tournament |
| `cross-cli-deliberation` | cross-cli-deliberation | 1.0.0 | none | cross-cli-deliberation SKILL.md inline two-gate protocol |
| `evo-analyze` | evo | 1.0.0 | none | evo.md C2/C3 (direct spawn / INIT→PLANNED→STOP) |
| `evo-apply` | evo | 1.0.0 | none | evo.md C2 direct bob spawn |

> **Layout — FROZEN by the WP-2 live-shape experiment (forge #159, Claude Code
> 2.1.172, 2026-06-11; record in `env-adoption/references/context-detection.md`):**
> flat `~/.claude/workflows/<name>.js` resolves by `meta.name` via
> `workflow('<name>')` and surfaces in the session listing IMMEDIATELY after
> file write (no restart). Args arrive intact to ~10 KB (larger ⇒ `args_path`
> + sha256, W-A). `schema`×`agentType` COMPOSES. **Nesting is ONE level,
> strictly** — a `workflow()` call from inside a child workflow is REFUSED; so
> `ratify-design` (which wraps `cross-cli-deliberation`) MUST always be invoked
> TOP-LEVEL via `Workflow({name})`, never via `workflow()` from another script.
> **External CLIs from a stage:** the historical stage hang was observed with
> `agy -p --sandbox` — since found (2026-07-02) to be a flag-order bug (`-p`
> swallows `--sandbox` as the prompt; sandbox off, real prompt discarded, agy
> free-runs/recurses). The corrected form `agy --sandbox -p` is UNVERIFIED from
> workflow stages — keep treating agy as UNREACHABLE from stages until re-probed
> (use pre-launched inline transcripts via args, §4.4); `codex exec` UNTESTED —
> attempt with the full guard set + the same inline fallback. The two TEMPORARY probe files
> (`wp2-probe.js`, `wp2-child.js`) were forge's experiment artifacts — they are
> NOT registered here and may be deleted now that the WP-2 results file exists.

All workflows: `MIN-CLAUDE: 2.1.154`; NO native-teams dependency anywhere;
G-W7 registration (lab shadow + this README row + watchlist entry + FRESHNESS
anchor); W-rules compliant; dispatch lines per the receipts protocol below.

---

## Conventions v1 — G-W rules (governance, greppable)

- **G-W1 OWNERSHIP** — every workflow has exactly ONE owning skill/agent, named
  in this README manifest row AND in `meta.description`. No orphans (a README
  row without a file, or a file without a row, is a lint failure).
- **G-W2 SCHEMA TWIN** — every schema a workflow emits/consumes has its
  CANONICAL JSON Schema in the owner's `schemas/` dir; the script embeds a
  hash-annotated literal twin (`// SCHEMA-TWIN: <id> sha256:<first16>`); the
  watchlist lint recomputes and compares.
- **G-W3 ZERO PRIVATE STRINGS** — defined by the publish scrubber's
  private-pattern list (private roots, hostnames, business names).
  Ecosystem-relative paths (`progress/…`, `.alf/`, `.ledger/evo/runs/`) are
  explicitly FINE. NO scrub rule may target `workflows/` (prod↔foundry
  byte-identical — this is what tripped identity_check in the P0c false
  positive).
- **G-W4 D1 BOUNDARY** — the Workflow Boundary (forge SKILL.md §5.9): user
  interaction, HMAC signing/session-key custody, gate verdict authority,
  classification authority, the decision to orchestrate, durable doc writes,
  and test-execution provenance NEVER move into a workflow stage.
- **G-W5 DETERMINISM** — no `Date.now()` / `Math.random()`; no retry
  randomness (retries are deterministic functions of prior stage output); all
  run variation arrives via args.
- **G-W6 WORKTREE** — no machinery-emitting stage (`.ledger/requests/`,
  claim heartbeats, `.wiring/runs/`) runs under worktree isolation; those are
  canonical-tree bob stages always. Only `executor: worker` WPs
  (`machinery: []` + `worktree_ok: true`) run worktree-isolated.
- **G-W7 REGISTRATION** — a workflow is SHIPPED only when it has: lab shadow
  file + this README manifest row + a `governance_watchlist.json` entry +
  a FRESHNESS anchor. Missing any one ⇒ it is not shipped.

## Conventions v1 — W-rules (file format + args)

- **W-N naming/home** — flat `~/.claude/workflows/<name>.js`, kebab-case, plain
  `.js`; `meta.name` MUST equal the filename stem (lint). Lab shadow
  `~/.claude/workflows/`.
- **W-H header block** — every file opens with:
  `// WORKFLOW: <name> v<semver>`, `// OWNER:`,
  `// PROVENANCE: hand-authored, reviewed, committed — never agent-emitted (S052)`,
  `// FALLBACK: <the SKILL.md/agent.md section that is the complete portable protocol>`,
  `// MIN-CLAUDE: 2.1.154`, `// NESTING: none | calls:<child>`,
  `// PROHIBITED: <greppable prohibitions>`. Semver: patch = prompt tweaks,
  minor = additive stages/args, major = renames/phase changes; the README
  manifest row mirrors the version.
- **W-A args contract** — ONE flat JSON args object. Standard fields in every
  family workflow: **`run_started_at`** (ISO-8601 UTC, caller-stamped — scripts
  cannot read the clock) and **`run_label`** (caller-generated correlation id;
  evo workflows carry it IN ADDITION to `run_id`). **Hash-pairing rule:** every
  `<x>_path` arg is paired with `<x>_sha256` computed by the caller at
  invocation and interpolated into stage prompts (this is what makes journal
  resume semantically safe). The resume-binding aliases `plan_hash` /
  `consult_log_hash` are accepted (each is the content sha256 of its paired
  `*_path`); the W-rules lint accepts both suffixes, and EVERY `*_path` —
  including `request_path` in evo-apply — MUST carry one. Large args (>~2 KB)
  go through `args_path` + `args_sha256` indirection. No env reads inside
  scripts — the main loop resolves env into args. Budget-derived numbers stay
  OUT of stage prompts where possible (use `budget.remaining()` thunks or
  budget TIERS) so top-ups don't invalidate caches.
- **W-EXT external-model anti-laundering envelope** — MANDATORY on every schema
  field-group carrying codex/agy/copilot output:
  `invocation {command, exit_code, timeout_s, stdin_closed}` + `raw_transcript`
  (byte-for-byte; truncation only with an explicit marker) + `transcript_path`
  + `transcript_sha256` + `served_by` (observed-but-UNTRUSTED) +
  `absence {unreachable, reason}`. Two-layer verbatim enforcement: schema
  transcript + tee'd file + sha256 recompute + substring cross-check of every
  extracted verdict. **Operational hard rules in EVERY example and composed
  command: `agy --sandbox` (MANDATORY — #157), `codex exec -s read-only`,
  `< /dev/null` stdin guard (#135/#155), shell `timeout`.** **Command custody =
  args-supplied:** consultant command lines are composed inline by the invoking
  skill and arrive via args (`consultant_cmds`); NO workflow file embeds an
  external-CLI command line (single update site when flags change).
- **W-D determinism** — no `Date.now()`/`Math.random()`; no retry randomness;
  all run variation via args.
- **W-COMP — the compiler ruling** — agent-emitted plan artifacts execute ONLY
  through the committed saved-workflow library. "Compilation" = a deterministic,
  judgment-free mapping `plan → (saved workflow name, args object)`. The main
  loop NEVER writes fresh JS in response to a plan artifact. Ad-hoc main-loop
  workflow scripts remain legal but may not consume a plan artifact, may not use
  bob stages, may not touch pipeline machinery.
- **W-KEY session-key custody** — the literal strings `.forge/session.key` /
  `session.key` are PROHIBITED in every workflow file, args object, and stage
  prompt (deterministic lint, rides the watchlist walk).
- **W-HN host-neutrality** — every plan/report/finding schema in the registry
  is host-neutral data; field semantics never reference Claude-only tools;
  consumption instructions in skills/agents use capability language with the
  Claude tool name parenthesized. A non-Claude executor consuming any registry
  artifact serially is a CONFORMING execution.
- **W-F versioning/FRESHNESS** — FRESHNESS:v1 block inside a JS block comment at
  END of file (`/* <!-- FRESHNESS:v1 ... --> */`); every family workflow carries
  `tool_version` anchors for the Claude Code surface + any external CLI its args
  compose.

## Schema-home decision table (W-S)

| Schema class | Canonical home |
|--------------|----------------|
| Owned by exactly one SKILL (portable fallback needs it) | `~/.claude/skills/<owner>/schemas/<name>.v1.schema.json` |
| Owned by an AGENT (bob/alf/evo) or cross-artifact pipeline machinery | `~/.claude/skills/_meta/schemas/<name>.v1.json` |

`deliverable.v1` → `skills/agent-teams/schemas/`. The frozen machine registry
is `~/.claude/skills/_meta/schemas/registry.v1.json` — no schema ships outside
it (R9).

---

## Dispatch / receipts protocol — `progress/workflow-runs.jsonl` (MANDATORY — R11)

**The main loop is the sole writer.** One JSON line
(`workflow-run-record.v1`) per state transition:

```json
{"state":"claimed","workflow":"bob-serial-exec","plan_hash":"sha256:..","plan_revision":2,
 "run_label":"...","run_id":null,"args_sha256":"..","resumed_from":null,
 "claim_token":"<uuid>","at":"<ISO — caller-stamped>"}
```

- **States**: `emitted` (plan artifact written by an agent; the agent's HALT
  report cites the plan path — the main loop appends `emitted` on receipt) →
  `claimed` → `executing` (Workflow invoked; `run_id` recorded) →
  `complete | failed`.
- **Atomic claim, exactly-once**: claims go through `_meta/workflow_dispatch.py`
  (main-loop Bash invocation): `flock` on a sidecar lock, scan the log for an
  existing live `claimed`/`executing` line for the same `(plan_hash,
  plan_revision)`, refuse if found (a second caller / double-resume
  structurally cannot execute the same plan twice), else append the `claimed`
  line with a fresh `claim_token`. `O_APPEND` writes; the flock spans only the
  single helper call.
- **Resume audit**: every resume appends an `executing` line with `resumed_from`;
  a `resumed_from` line appearing after a higher `plan_revision` line for the
  same plan is mechanically detectable = the "no resume across amendment" audit.
- Mandatory for ALL eight family workflows' invocations; doubles as the #147
  enforcement hook and the #124 cost-correlation point (designed now, enforced
  never this cycle).

## Family bridge rule

`MODE=bridge` hosts use the portable inline fallback for ALL external-model
calls in every family workflow (v1 limitation — bridge sessions are stateful
and main-loop-owned).

<!-- FRESHNESS:v1
anchors:
  - kind: tool_version
    subject: claude-code-workflow-surface
    verified_against: "2.1.173 (gating is by manifest harness.* field, never this number)"
    verified_on: "2026-06-11"
    volatility: high
  - kind: status_snapshot
    subject: saved-workflow-file-layout
    verified_against: "FROZEN — flat ~/.claude/workflows/<name>.js, meta.name resolve, 1-level nesting (WP-2 live, forge #159)"
    verified_on: "2026-06-11"
    volatility: high
-->
