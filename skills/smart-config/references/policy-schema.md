# model-policy schema v1 — normative contract

This is the **normative contract** for the `model-policy` schema (S059). It is the
single source of truth for any consumer — the Claude Code consumer that ships now, and
the VS Code Copilot consumer that `vs-code-foundry` will build later against this same
schema (decision C1). Where prose elsewhere and this file disagree, **this file wins**.

## 0. Field partition (the C1 contract)

| Class | Fields | Owned by |
|---|---|---|
| **Normative** (cross-consumer) | `version`, `defaults`, `tiers`, `agents`, `rubric` | the schema (this file) |
| **Consumer-private semantics** | surface dialects, alias key set, `[1m]` handling, decisions-log location/slug | each host's resolver |

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
  complex: { claude-code: opus }     # the Claude main tier (skills/_meta/model_roster.py)
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

### `effort` (#311, additive to v1)

A tier may carry a reserved key `effort` beside its host keys — itself a **host-keyed mapping**
of reasoning-effort levels (`low | medium | high | xhigh | max`):

```yaml
tiers:
  complex: { claude-code: opus,   effort: { claude-code: high } }
  medium:  { claude-code: opus }                                   # effort per WP grade
  light:   { claude-code: sonnet, effort: { claude-code: low } }
```

- `effort` is never a host key. It merges like any mapping (project wins per leaf; a `null`
  leaf means inherit).
- **Ceiling `high` (#311 fix rounds 1–2):** an `xhigh` or `max` leaf is a `validate` error on any
  layer, and `resolve` caps it to `high` with a warning. xhigh and max are reserved for protected
  seats (seat_model) and explicit overrides; a policy file never reaches them.
- **No `effort` leaf on the execution tier `medium`:** it is a `validate` error, and `resolve`
  ignores it with a warning, so ungraded execution work keeps the ungraded default (`high`)
  rather than being starved by a policy file.
- A tier-leaf effort is reported as `effort_source: policy` with `grade: null` (a grade is the
  WP's S/M/L; `policy` is not a reserved source).
- **Fail-open, same as the model:** a missing, null or malformed effort leaf means the effort is
  OMITTED and the spawn inherits the session's. `validate` reports a non-mapping `effort` or an
  unknown level as an error; `resolve` warns and inherits.
- **The execution tier** (`medium`) takes its effort per work package: `resolve --grade S|M|L
  [--file PATH ...]` applies `skills/_meta/effort_policy.py` (S low, M medium, L high; S/M one
  step up when a declared file fires a `review_risk` family). With no `--grade`, a configured
  `medium` tier with no effort leaf resolves the ungraded default `high` (`default-ungraded`).
  The builtin layer (no readable config) never routes an effort on its own.
- **`--effort-step N`** raises a `policy` level N steps, capped at `high`. With `--grade` or on the
  ungraded default it is refused (warning, ignored) until phase 2. It is the phase-2 retry carrier
  and is deliberately distinct from `--escalate`, which moves the model tier.
- **Protected seats** (`code_reviewer`, `consultant_main`, `arbiter`, `escalation`) take their
  effort from `seat_model.ROLE_TABLE` only; no layer of this file reaches them.
- **Surfaces:** the workflow (`agent({effort})`) and headless (`--effort`) surfaces carry the
  effort. The Agent tool has no effort parameter, so on `--surface agent` the effort is reported
  as `inherit` with a warning (the agent file's static frontmatter applies). VS Code Copilot has
  no effort control; a second consumer ignores the key.

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
- **Consequence of that scoping (S080 D9):** a pin is applied only when resolving for
  the `claude-code` host. Asked for any other `--host`, the Claude Code resolver SKIPS
  the pin, resolves through `tiers.<tier>.<host>` instead, and emits a warning (in
  `warnings[]` and on stderr) naming the pin, the agent and the host. `source` then
  reports the tier path that served (`builtin|global|project`), never `agent-pin`.
  Handing a Claude alias to a non-Claude host with `ok: true` and no warning was the
  defect. The `agents` map shape itself is unchanged in v1.

## 4. Merge semantics (normative)

Merge order: **builtin <- global (`~/.claude/model-policy.yaml`) <- project
(`<root>/.claude/model-policy.yaml`)**.

- Mappings **recurse**; scalars **replace**; **project wins per leaf**.
- An explicit `null` leaf in the project layer **replaces** the global value and means
  inherit (= omit the model param).
- **`version` mismatch between layers** -> `validate` exit 3; `resolve` uses the merged
  result with a warning (fail-open, never blocks a spawn).
- **Unknown tier keys under `tiers:`** are allowed (user-defined tiers).
- **Non-mapping shapes (S080 D8).** `defaults`, `tiers` and `agents` must be mappings
  and `defaults.tier` a string. A wrong shape (e.g. `tiers: [complex]`) is a `validate`
  error where validate checks it (`tiers`, `agents`); `resolve` warns, treats the
  section as empty (`defaults.tier` falls back to `medium`) and still exits `0` with one
  JSON object. A list-shaped `tiers` therefore lands on `defaults.tier` with
  `model: null` (inherit). Note a project-layer list REPLACES a global mapping on merge.

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
- **Benched models (Claude Code consumer, #291).** The harness roster
  (`skills/_meta/model_roster.py`) names the Claude main tier, the support tier and the
  benched families. A benched value on any layer — a tier's `claude-code` leaf or an
  `agents:` pin, spelled as an alias, `alias[1m]` or a full id — is REPLACED by the main
  tier with a warning before the layers merge: never an error, never inherit. The
  benched test is `seat_model.is_benched`, imported from the harness, not re-implemented;
  a failed import NEVER lets a benched value through (#291 fix round 1): the refusal falls
  back to `model_roster.CLAUDE_BENCHED` via the pure `model_ids` normaliser, then to the
  hard floor `_FLOOR_BENCHED`, with a warning, replacing with a usable main tier or else
  inherit; the final shaped value is re-checked. Other host keys are not touched. A second consumer that routes Claude models SHOULD apply the same rule.
- Claude alias KEY SET (consumer-private): `fable`, `opus`, `sonnet`, `haiku` (a key
  of the set is still refused while the roster benches its family). The
  resolver keeps NO alias->full-id table: every surface accepts the alias itself, an
  alias auto-upgrades, and a versioned full id pinned beside it rots on the next release
  (the S059 table had rotted by S080). Any value outside the key set — a full id, or a
  model newer than the set — passes through with an "unknown model id" warning, never an
  error.
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
 "effort": "<level or null>", "effort_source": "<grade|promotion|default-ungraded|policy|inherit>",
 "grade": "<S|M|L or null>", "effort_step": <int>,
 "policy_hash": "<effort_policy hash or null>", "warnings": ["..."]}
```

`effort: null` = inherit (omit the effort param). A tier-leaf effort reports `effort_source:
policy` with `grade: null`.

`model: null` = inherit. `source: agent-pin` only when a pin was actually applied (host
`claude-code`, §3). Exit code is `0` on EVERY resolve path including all fail-open
paths and non-mapping shapes (§4); `2` only for usage errors.

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
  `/home/USER/.claude` -> `-home-USER--claude`). No project root -> 
  `~/.claude/state/model-decisions.jsonl`.
- Per-line schema: `{at, task, tier_requested, tier, escalated, surface, agent, model,
  source, reason, policy_sha256, effort, effort_source, grade, effort_step}` (the last four
  #311) where `policy_sha256` = sha256 of the sorted-keys
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
