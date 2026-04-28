---
name: design-drift-arbiter
description: Use AFTER visual-arbiter returns `reject` on a visual verification run, when bob needs to know whether the failures are micro-drift (auto-approvable as a patch-version bump) or material change (escalate to user review). Pure-Python algorithmic comparison — no LLM, no browser. Consumes a rejected visual-verdict JSON + skeleton tokens + an active profile from `_meta/config.yaml` (strict | lenient | project_override) and emits one JSON verdict on stdout. Bob persists the verdict; the arbiter never writes to `.design-ledger/` (CB4 boundary, mirrors visual-arbiter).
---

# design-drift-arbiter

Pure-Python micro-drift auto-approver. Runs **after** visual-arbiter's initial pass, and **only** if visual-arbiter returned `reject`. If every per-element failure is micro-drift (bbox within profile tolerance, or token-mismatch where the computed value is in the **same token family** as the declared token), the deviation auto-approves as a skeleton patch-version bump. Anything else escalates to user review.

## When to invoke

From bob's UI-VERIFIED gate flow, chained after visual-arbiter:

```
visual-arbiter → reject
  └── design-drift-arbiter → auto_approved   → skeleton patch-version bump
                           → escalate_to_user → file skeleton-challenge (§2.8)
```

Do NOT invoke when visual-arbiter returned `pass` or `warn` — there's nothing to auto-approve.

## Invocation

Subprocess, not a Claude Code Agent. Bob spawns it as (10-positional-arg, mirrors `verification_arbiter_spawn.py` + `visual_arbiter_spawn.py`):

```bash
python3 ~/.claude/skills/_meta/design_drift_arbiter_spawn.py \
  <verdict_path> <verdict_hash> <request_id> <attempt_id> \
  <prior_state_version> <tokens_path> <skeleton_hash> \
  <inventory_hash> <runner_version> <rubric_version>
```

Keyword-style overrides (`--verdict-path`, `--tokens-path`, `--profile`, `--config-path`, `--project-root`) are also accepted for test harnesses and explicit profile selection.

Bob captures stdout; the arbiter writes nothing to disk.

## Input tuple (8 fields echoed back)

Mirrors visual-arbiter exactly:

| Field | Format | Purpose |
|---|---|---|
| `request_id` | 32-hex | Causal linkage to open visual verification request |
| `attempt_id` | non-empty string | Retry counter |
| `prior_state_version` | non-empty string | Ledger state at request-open |
| `skeleton_hash` | 64-hex (sha256) | Frozen skeleton the drift was measured against |
| `impl_hash` | 64-hex (sha256) | Built artifact hash — inherited from visual-verdict |
| `inventory_hash` | 64-hex (sha256) | env-adoption inventory at verification time |
| `runner_version` | non-empty string | trusted_runner version |
| `rubric_version` | non-empty string | Drift-arbiter rubric version (this SKILL.md, hashed) |

The `tuple_echo` block on the output is what `claims.consume_visual_verdict` checks; any mismatch → `rejected_tuple_mismatch`.

## Output (stdout only)

Exactly ONE JSON object:

```json
{
  "status": "auto_approved" | "escalate_to_user",
  "tuple_echo": { ... 8 fields echoed verbatim ... },
  "classification_per_element": [
    {
      "element_id": "step_card_1",
      "breakpoint": "desktop",
      "failures": [ ... ],
      "classification": "micro-drift" | "material",
      "reasons": ["bbox_drift worst=1px ≤ tolerance 2px → micro", ...]
    }
  ],
  "profile_used": "strict",
  "rubric_version": "drift-arbiter-v1.0.0"
}
```

`status="auto_approved"` only when EVERY element in `classification_per_element` is `micro-drift` AND at least one element was evaluated. `status="escalate_to_user"` otherwise (any material classification, or empty input → conservative escalate).

## Profiles (static, not self-adjusting — §6.1 Q2)

Loaded from `~/.claude/skills/_meta/config.yaml`, key `design_drift_arbiter`:

```yaml
design_drift_arbiter:
  active_profile: strict
  profiles:
    strict:
      bbox_tolerance_px: 2
      token_swap_allowed: false
    lenient:
      bbox_tolerance_px: 8
      token_swap_allowed: true
      token_swap_same_family_only: true
    project_override:
      path: ".design-ledger/drift-profile.yaml"
```

The `active_profile` pointer determines which profile wins. `project_override` resolves against the project root (passed via `--project-root`) and reads a YAML containing the profile fields directly (`bbox_tolerance_px`, `token_swap_allowed`, `token_swap_same_family_only`).

**Why static, not self-adjusting:** observation-count-driven tuning creates feedback poisoning (noisy-but-correct arbiter raises its own tolerance until nothing fails) AND breaks the hash-chain reproducibility invariant. Profile switching is explicit, versioned, and human-reviewed.

If the active profile is missing from config, the arbiter emits a `skill_bug` observation (fail-open) and falls back to `strict`.

## Same-family algorithms (mechanical, per §2.7)

Not judgmental — pure math.

**Colors.** A computed hex `#fe0000` swaps for declared token `accent.sun` → same family iff:
1. Both token references share the same namespace prefix (e.g. both `accent.*`).
2. ΔE2000 ≤ 3 in CIELAB (canonical Sharma/Wu/Dalal 2005 formulation, implemented inline — no `colormath` dependency).
3. Lightness bucket: |L*1 − L*2| ≤ 10.

Per D2 (strict token binding), a hardcoded hex that is NOT a token reference NEVER establishes same-family with a token — it's a token-binding violation, not a drift.

**Typography.** `{family, weight, size_px}` comparison:
- Same family name (exact match).
- Weight step ±1 (100-unit CSS steps): 400→600 OK, 400→900 NOT.
- Size within 10% (`|new − old| / old ≤ 0.10`).

**Spacing.** Token refs like `spacing.8`, `spacing.12`:
- Resolve to numeric values, look up index in `tokens.spacing.scale[]`.
- Same family iff `|idx1 − idx2| ≤ 1`.
- `spacing.8 → spacing.12` OK (adjacent); `spacing.8 → spacing.32` NOT.

**Bounding boxes.** Per-dim drift (x, y, w, h) ≤ `profile.bbox_tolerance_px`. Any single axis exceeding → material.

## Always-material (never micro-drift)

Regardless of profile, these failure kinds NEVER auto-approve:

- `missing_from_dom` — element entirely absent (material omission)
- `dead_handler` — interaction not wired (functional regression)
- `interaction_fail` — declared interaction failed at runtime

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Valid verdict emitted on stdout |
| `3` | Environmental / usage error (bad args, unreadable inputs) |

No code `4` — unlike LLM arbiters, there is no subprocess to be unavailable; the arbiter is pure Python.

## Scope boundaries

| In scope | Out of scope |
|---|---|
| Classify rejected-verdict failures as micro-drift vs material | Re-running visual-arbiter; verdict is input, not recomputed |
| Read token refs from skeleton `index.yaml` for family lookup | Writing `.design-ledger/`; bob persists the drift verdict |
| Emit fail-open `skill_bug` observation on malformed config | Self-adjusting profile tuning (explicitly forbidden by Q2) |
| Read `_meta/config.yaml` for active profile | Falling back when profile is missing (uses `strict` defaults) |

## Determinism invariant

Given identical inputs (verdict JSON + tokens + profile) the arbiter produces a **byte-identical** output JSON. This is required by the hash-chain invariant — drift verdicts participate in the same signed-tuple consume pattern as visual verdicts. No randomness. No time-dependence. No external calls.

## Aliases

The canonical id of this skill is **`design-drift-arbiter`** — matches the
skill directory name, matches the evidence path
`.ledger/evidence/design-drift-arbiter/`, and matches the binary file name
`design_drift_arbiter_spawn.py`. The S028 `progress/contract-map.yaml`
(now archived under `progress/archive/s028-ecosystem-keystone/`, read-only)
referred to this component by the short-form id **`drift-arbiter`**. A future
bob run that consults that archive for context should treat the two ids as
equivalent (`drift-arbiter` ≡ `design-drift-arbiter`). New contract maps
SHOULD use `design-drift-arbiter`. (S030-quickwins #49.)

## References

- Design doc: `docs/plans/2026-04-23-ecosystem-keystone-design.md` (§2.7 drift-arbiter, §6.1 D3 tolerance formula, §6.2 Q2 profile rationale, §7.1 components inventory)
- Contract map: `progress/contract-map.yaml` component `drift-arbiter` (TS-DA-01..04)
- Binary: `~/.claude/skills/_meta/design_drift_arbiter_spawn.py`
- Config: `~/.claude/skills/_meta/config.yaml` (key `design_drift_arbiter`)
- Tests: `~/.claude/skills/design-drift-arbiter/tests/test_drift_arbiter.py`
- Sibling subprocess (runs first): `~/.claude/skills/_meta/visual_arbiter_spawn.py` (WP-9)
- Downstream consumer: `_meta/claims.py:consume_visual_verdict` (WP-5)
- ΔE2000 reference: Sharma, Wu, Dalal, "The CIEDE2000 Color-Difference Formula" (2005); http://zschuessler.github.io/DeltaE/learn/#toc-delta-e-2000
