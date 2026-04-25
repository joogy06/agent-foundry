---
name: visual-arbiter
description: Use when bob needs a mechanical verdict on whether a built UI product satisfies a frozen design-skeleton as part of the UI-INTEGRATED → UI-VERIFIED transition. Invoked as a subprocess (not a Claude Code Agent). Renders the built product with puppeteer at each required breakpoint, measures bbox / computed styles / interaction wiring against the skeleton, and emits ONE JSON visual-verdict.v1 object on stdout. Pure-Python decision path — NO LLM subprocess (CB4: bob is sole writer of .design-ledger/visual-verdicts/).
---

# visual-arbiter

Mechanical visual verifier invoked by bob at the UI-INTEGRATED → UI-VERIFIED gate (ecosystem-keystone §2.6, §2.9, §5.5, §5.6). Mirrors the CLI shape of `verification-arbiter` (S027) exactly, but the decision path is **pure Python** — puppeteer is used only for DOM measurement, never for judgment.

## When to invoke

From bob at the UI-INTEGRATED → UI-VERIFIED transition (ecosystem-keystone HARD-RULE 6). Runs in sequence: visual-arbiter first; if it rejects with micro-drift only, bob may then invoke `design-drift-arbiter` for auto-approval. Either arm rejecting blocks UI-VERIFIED.

Prerequisites:
- Frozen `design-skeleton.v1` (signed `index.yaml` + per-screen yamls in `.design-ledger/skeletons/`)
- Built product reachable via `file://` or `http(s)://` URL
- `claims.open_visual_verification_request(...)` must have opened a request for the produced tuple BEFORE invoking the arbiter

## Invocation

Subprocess, not an Agent. Bob spawns it as:

```bash
python3 ~/.claude/skills/_meta/visual_arbiter_spawn.py \
  <skeleton_path> <skeleton_hash> <request_id> <attempt_id> \
  <prior_state_version> <built_product_url> <product_hash> \
  <inventory_hash> <runner_version> <rubric_version>
```

All 10 arguments are positional and required. Bob captures stdout; the arbiter writes **nothing** to disk.

## Input tuple (8 fields echoed back verbatim — §2.9)

| Field | Format | Purpose |
|---|---|---|
| `request_id` | 32-hex | Causal linkage to the open visual-verification request |
| `attempt_id` | non-empty string | Distinguishes retries against the same component |
| `prior_state_version` | non-empty string | Pins verdict to ledger state at request-open time |
| `skeleton_hash` | 64-hex (sha256) | Content hash of the frozen skeleton bundle |
| `product_hash` | 64-hex (sha256) | Built product two-layer hash (source dir + rendered HTML) |
| `inventory_hash` | 64-hex (sha256) | env-adoption inventory at verification time |
| `runner_version` | non-empty string | trusted_runner version that produced the bundle |
| `rubric_version` | non-empty string | Arbiter's evaluation rubric version (see below) |

Tuple mismatch on any field → bob's `claims.consume_visual_verdict` returns `rejected_tuple_mismatch` and discards the verdict.

## Output (stdout only)

One JSON object matching `visual-verdict.v1` (design §2.9). Top-level `verdict`:

- `pass` — every element at every required breakpoint verified; no fail-status element verdicts; no blocker concerns
- `warn` — all elements verified but ≥1 warning-severity concern (e.g. fonts.ready >2s)
- `reject` — ≥1 element_verdict has `status: fail` (missing_from_dom, bbox_drift beyond tolerance, token_mismatch, or dead_handler)
- `AUDIT_UNAVAILABLE` — reserved for the spawn script on environmental failure (chrome crash, schema violation). Bob MUST escalate to user; NEVER auto-approve.

Element verdict fields (§2.6):

- `missing_from_dom` — selector resolves to nothing at the given breakpoint
- `bbox_drift_px: {x, y, w, h}` — per-dim signed drift; compared against `tolerance_for(element) = min(must_satisfy.tolerance_px, spacing.unit_px / 2)`
- `token_mismatch: {field, computed, expected}` — hardcoded hex/rgb found in inline style (or computed value fails var(--...) indirection)
- `dead_handler: [{event, binds_to, reason}]` — interaction declared but no listener fires (and uri.resolve confirms target unreachable if binds_to is set)
- `interactions_ok: [{event, binds_to, status}]` — per-interaction success

Overall:
- pass iff every element verdict is `pass` AND no blocker concerns
- reject iff any element verdict is `fail`
- warn iff all pass but warnings exist

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Valid schema-compliant verdict emitted on stdout; all 8 tuple fields echoed correctly |
| `3` | Environmental / usage error (wrong argv count, hash not 64-hex, unreadable skeleton) |
| `4` | `AUDIT_UNAVAILABLE` — measurement subprocess crashed, timed out, chrome unreachable, or produced unparseable output |

Design §2.6 / §5.6: arbiter **never writes** `.design-ledger/visual-verdicts/`. Bob is the sole ledger writer (CB4 preserved).

## Decision rubric (v1.0.0 — pure-Python, no LLM)

**Source of truth: this SKILL.md plus `visual_arbiter_spawn.py`, both hashed.** Bump the rubric version (semver) when changes affect verdict semantics. v1.0.0 rules:

1. **Per-element at every required breakpoint.** For each element in each screen's `elements[]`, iterate `must_satisfy.required_breakpoints`. If the element declares `null` at a breakpoint, it is correctly hidden there — no verification needed. Otherwise:

2. **bbox check.** Measured `getBoundingClientRect()` compared to declared `bbox.<breakpoint>`. Per-dim drift = `measured - declared`. Element passes bbox iff every `abs(drift[dim]) <= tolerance_px` where `tolerance_px = min(must_satisfy.tolerance_px, spacing.unit_px // 2)` — taken directly from the skeleton's own declarations; NEVER a hardcoded constant.

3. **Token back-resolution.** For each `tokens_used` mapping, the element's computed styles must go through a `var(--<token-name>)` reference (e.g. `var(--accent-sun)` for `$color.accent.sun`) OR at minimum NOT contain a hardcoded hex/rgb in its inline `style` attribute. Hardcoded hex in inline style → `token_mismatch` fail with `{field, expected, computed}`.

4. **Interaction wiring.** For each declared `interactions[].event`:
   - `visual_only: true` — no binding required; pass automatic
   - `binds_to == null` and NOT visual_only → schema violation → `dead_handler`
   - `binds_to` set → arbiter fires the event via `dispatchEvent`, then checks (a) inline `on*` attribute, (b) `data-arbiter-wired="true"` opt-in flag, OR (c) an `el.__arbiter_handler_ran` flag the handler itself set. None of those → `dead_handler` fail
   - If `uri` module available: `binds_to` URI resolved via `uri.resolve(binds_to, project_root)`; UriError → `dead_handler` with reason `binds_to unresolvable`

5. **Font-load concern.** `fonts.ready + 300ms` wait is mandatory. Wait >2000ms → `warning` concern (does not block `pass` but downgrades to `warn`). Also emits `claude_observe('external_tool_slow', ...)` fail-open.

6. **Chrome crash handling.** Measurement subprocess non-zero exit or timeout → emit `external_tool_fail` / `external_tool_slow` observation (fail-open) and exit with code 4 + `AUDIT_UNAVAILABLE`.

7. **Tuple echo discipline.** All 8 tuple fields echoed **verbatim** — bob's `claims.consume_visual_verdict` rejects on any mismatch.

## Env vars

| Variable | Default | Purpose |
|---|---|---|
| `VISUAL_ARBITER_CHROME_PATH` | `/bin/google-chrome` | Chrome/Chromium binary (must match what puppeteer-core can drive) |
| `VISUAL_ARBITER_NODE_BIN` | `node` | Node binary for the measurement subprocess |
| `VISUAL_ARBITER_TIMEOUT_S` | `180` | Measurement subprocess timeout (chrome launch + per-bp measurement) |

## Relationship to other verifiers

| Arbiter | Scope | Decision engine |
|---|---|---|
| `verification-arbiter` (S027) | Functional — test coverage against frozen plan | Cold Claude + coverage scoring |
| `visual-arbiter` (this) | Visual — bbox + tokens + interactions against frozen skeleton | Pure Python; puppeteer = measurement only |
| `design-drift-arbiter` (WP-10) | Micro-drift auto-approval post-rejection | Pure Python profile rules |

Visual-arbiter runs **before** design-drift-arbiter. bob invokes drift-arbiter only if visual-arbiter rejected with micro-drift-only reasons (bbox within expanded profile tolerance OR token swap within same family). See ecosystem-keystone §5.6 / HARD-RULE 6.

## Scope boundaries

| In scope | Out of scope |
|---|---|
| Measuring bbox/tokens/interactions at each breakpoint | Creating/amending the skeleton (visual-architect owns) |
| Mechanical comparison against declared tolerances | Judgment calls about what a user "really wants" — v2 deferral (§1.3) |
| 8-field tuple echo | Consuming the verdict or writing visual-verdicts/ (bob owns via claims.consume_visual_verdict) |
| Emitting `AUDIT_UNAVAILABLE` via exit 4 | Model-emitted `AUDIT_UNAVAILABLE` (there is no model in the verdict path) |
| fail-open `claude_observe` for chrome slow/fail | Being authoritative for observability — that's observability skill (S026) |

## References

- Design doc: `docs/plans/2026-04-23-ecosystem-keystone-design.md` (§2.6 pure-Python arbiter, §2.9 visual-verdict.v1 schema, §5.5 claims.consume_visual_verdict, §5.6 HARD-RULE 6, §5.9 external-wrapper observations)
- Contract map: `progress/contract-map.yaml` — component `visual-arbiter` (TS-VAR-01..05)
- Sibling subprocess (S027): `~/.claude/skills/_meta/verification_arbiter_spawn.py`
- Binary: `~/.claude/skills/_meta/visual_arbiter_spawn.py`
- Measurement driver: `~/.claude/skills/_meta/visual_arbiter_measure.mjs`
- Tests: `~/.claude/skills/visual-arbiter/tests/test_visual_arbiter.py` (TS-VAR-01..05)
