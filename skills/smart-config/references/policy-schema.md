# model-policy schema v1 — normative contract

This is the **normative contract** for the `model-policy` schema (S059). It is the
single source of truth for any consumer — the Claude Code consumer that ships now, and
the VS Code Copilot consumer that `vs-code-foundry` will build later against this same
schema (decision C1). Where prose elsewhere and this file disagree, **this file wins**.

## 0. Field partition (the C1 contract)

| Class | Fields | Owned by |
|---|---|---|
| **Normative** (cross-consumer) | `version`, `defaults`, `tiers`, `agents`, `rubric` | the schema (this file) |
| **Consumer-private semantics** | surface dialects, alias->full-id table, `[1m]` handling, decisions-log location/slug | each host's resolver |

A second consumer MUST honor the normative fields identically. It is FREE to implement
its own surface dialects and model id mapping — Copilot's headless model control
(`github.copilot.chat.*` + the chat model picker) is materially more constrained, so
**schema compatibility is promised, not surface parity**.

## 1. Top-level keys

```yaml
version: 1                # REQUIRED. Integer. v1 only.
defaults:
  tier: medium            # tier landed on when grading is inconclusive. Uncertainty
                          # biases UP, never to light.
tiers:                    # role-named tiers. Keys are TIER names, NEVER model names.
  complex: { claude-code: fable }
  medium:  { claude-code: opus }
  light:   { claude-code: sonnet }
  # trivial: { claude-code: haiku }   # optional 4th tier — presence enables it
agents:                   # optional per-agent pins — beat tier resolution
  bob: opus[1m]
rubric: |                 # written grading rubric (prose). The orchestrator grades
  ...                     # against this at spawn time.
```

- **Unknown top-level keys** -> `validate` WARNING (forward-compat), not an error.
- **Reserved v2 keys** (`fallbacks`, `escalation`) are KNOWN names: present them
  without an "unknown key" warning, but v1 consumers ignore them.

## 2. `tiers`

- Keys are tier names. The canonical ordered chain is
  `[trivial, light, medium, complex]` (used by `--escalate`). **User-defined tier
  keys are permitted** (validate allows them); they are simply off the escalate chain.
- Each tier leaf is a **host-keyed mapping**: `{ <host-key>: <model value> }`.
- A `null` leaf (`{ claude-code: null }`) REPLACES on merge and means **inherit**
  (omit the model param).

### Host-key registry

| Host key | Status |
|---|---|
| `claude-code` | **live** (v1 consumer) |
| `vscode-copilot` | reserved (vs-code-foundry to implement) |
| `codex` | reserved |

`init` emits ONLY the `claude-code` host key — no dead `vscode-copilot: null` stubs in
user files. Other host keys are added by hand when a consumer for them exists.

## 3. `agents`

- Per-agent pins. A pin **beats** tier resolution (precedence:
  `agents.<name>` -> `tiers.<tier>.<host>`).
- Pin values are **model values/aliases only, NEVER tier names** (`validate` rejects a
  tier name as a pin value).
- In schema v1, `agents` values are **claude-code-scoped scalars**
  (`bob: opus[1m]`). The host-keyed mapping form (`bob: { claude-code: ..., codex: ... }`)
  is **reserved for v2** — declared here so the C1 contract is explicit that `agents`
  is asymmetric with `tiers` in v1.

## 4. Merge semantics (normative)

Merge order: **builtin <- global (`~/.claude/model-policy.yaml`) <- project
(`<root>/.claude/model-policy.yaml`)**.

- Mappings **recurse**; scalars **replace**; **project wins per leaf**.
- An explicit `null` leaf in the project layer **replaces** the global value and means
  inherit (= omit the model param).
- **`version` mismatch between layers** -> `validate` exit 3; `resolve` uses the merged
  result with a warning (fail-open, never blocks a spawn).
- **Unknown tier keys under `tiers:`** are allowed (user-defined tiers).

### Builtin layer (normative)

`defaults.tier: medium` + **EMPTY `tiers`** (every tier resolves to `model: null` =
inherit) + no `agents` pins. Consequence: with no readable config anywhere, degradation
is ALWAYS inheritance — the builtin layer never routes models on its own.

## 5. Model values, aliases, `[1m]`

- Model values must match `^[A-Za-z0-9.\[\]-]+$` (Codex #18 hygiene — they reach argv,
  never shell strings; bad values are rejected/dropped).
- **YAML quoting:** a `[1m]` suffix in **flow** style (`{ claude-code: opus[1m] }`) is a
  YAML parse error and fails the whole layer open to inherit. QUOTE it:
  `{ claude-code: "opus[1m]" }`. **Block** style (`bob: opus[1m]`) is safe unquoted.
- Claude aliases (consumer-private): `fable->claude-fable-5`, `opus->claude-opus-4-8`,
  `sonnet->claude-sonnet-4-6`, `haiku->claude-haiku-4-5`. UNKNOWN values pass through
  with a warning (new models ship faster than any enum).
- `[1m]` (1M-context) handling is **surface-dialect** (consumer-private):
  - **agent** surface — unexpressable; strip + warn (warn-on-loss).
  - **workflow** surface — V-2 conservative default: strip + warn (pending verification
    that workflow `opts.model` accepts `alias[1m]`).
  - **headless** surface — V-1 verified: native alias + `alias[1m]` acceptance; emit
    as-is (no expansion).

## 6. `resolve` output contract

Exactly one JSON object on stdout, always:

```json
{"ok": true, "model": "<surface-shaped value or null>", "tier": "<resolved>",
 "tier_requested": "<input>", "escalated": <bool>, "surface": "<agent|workflow|headless>",
 "agent": "<name or null>", "source": "<builtin|global|project|agent-pin>",
 "warnings": ["..."]}
```

`model: null` = inherit. Exit code is `0` on EVERY resolve path including all fail-open
paths; `2` only for usage errors.

## 7. Exit codes (all subcommands)

| Subcommand | Codes |
|---|---|
| `resolve` | `0` always (fail-open incl. missing/malformed/unknown), `2` usage |
| `validate` | `0` valid (warnings allowed), `3` schema error, `2` usage; `--strict` promotes warnings to errors |
| `show` / `log` | `0` ok, `3` unreadable state, `2` usage |
| `init` | `0` written, `3` target exists without `--force`, `2` usage |

## 8. Decisions log (consumer-private)

- Location: `~/.claude/projects/<project-slug>/model-decisions.jsonl`. **Slug rule:**
  replace every char of the absolute project-root path not in `[A-Za-z0-9]` with `-`
  (`/path/to/project` -> `-path-to-project`;
  `/home/adm01/.claude` -> `-home-adm01--claude`). No project root -> 
  `~/.claude/state/model-decisions.jsonl`.
- Per-line schema: `{at, task, tier_requested, tier, escalated, surface, agent, model,
  source, reason, policy_sha256}` where `policy_sha256` = sha256 of the sorted-keys
  compact-JSON of the merged effective policy.
- `O_APPEND` single line, never-raise, never blocks resolve. Rotation at 1MB under
  non-blocking `flock` (skip if not acquired), `os.replace`, one generation kept.
  Honesty: `O_APPEND` non-interleaving is a Linux-local-fs property, not POSIX (NFS
  caveat).

## 9. Reserved for v2 (declared, NOT implemented in v1)

- `fallbacks:` — a resolver cannot detect rate limits, so a fallback list would be
  theater. Reserved as a known name only.
- `escalation:` as config — the 2-failures rule lives in rubric prose + the
  `--escalate` flag (the orchestrator owns the attempt count; there is no durable
  counter in v1).
- Host-keyed `agents` pins (per §3).
- Surface-override blocks in user config (surface dialects stay consumer-private).

## vs-code-foundry handoff note

This document IS the handoff artifact. To build the Copilot consumer: honor §1-§4 and
§6-§7 exactly; implement your own §5 (Copilot model ids) and §8 (your log location);
feasibility of headless model control is your call (Copilot is materially more
constrained than `claude -p`). Promise: **schema compatibility, not surface parity.**
