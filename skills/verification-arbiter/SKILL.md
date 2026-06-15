---
name: verification-arbiter
description: Use when bob needs an independent verdict on an evidence bundle as part of the INTEGRATED → VERIFIED transition. Invoked as a subprocess (not a Claude Code Agent). Reads a frozen evidence bundle + frozen test plan, runs a cold-context Claude to score coverage against the plan and self-check the bundle hash, and emits one JSON verdict on stdout. Bob persists the verdict; the arbiter never writes to .ledger/ (CB4 boundary per design §5.6).
---

# verification-arbiter

Independent verifier invoked by bob. NOT a peer to bob — bob initiates, controls inputs, and consumes outputs.

## When to invoke

From bob's Step 4.5 (Phase 2B wiring — live since S048 (#116)): after `trusted_runner` produces a sanitized evidence bundle and bob has opened a verification request in `.ledger/requests/verification/<request_id>.request.yaml`. Arbiter runs in parallel with `audit_spawn.py`; both verdicts are required for a VERIFIED transition.

## Invocation

Subprocess, not an Agent. Bob spawns it as:

```bash
python3 skills/_meta/verification_arbiter_spawn.py \
  <bundle_path> <bundle_hash> <request_id> <attempt_id> \
  <prior_state_version> <plan_path> <plan_hash> \
  <inventory_hash> <runner_version> <rubric_version>
```

All 10 arguments are positional and required. Bob captures stdout; the arbiter writes nothing to disk.

## Input tuple (8 fields echoed back verbatim)

| Field | Format | Purpose |
|---|---|---|
| `request_id` | 32-hex | Causal linkage to the open verification request |
| `attempt_id` | non-empty string | Distinguishes retries against the same component |
| `prior_state_version` | non-empty string | Pins verdict to ledger state at request-open time |
| `bundle_hash` | 64-hex (sha256) | Content hash of the evidence bundle being verified |
| `plan_hash` | 64-hex (sha256) | Test plan version the arbiter scored coverage against |
| `inventory_hash` | 64-hex (sha256) | env-adoption inventory at verification time |
| `runner_version` | non-empty string | trusted_runner version that produced the bundle |
| `rubric_version` | non-empty string | Arbiter's evaluation rubric version (see below) |

Bob's full 8-field tuple-match is the outer gate on VERIFIED per design §5.3; this skill only enforces echo-back.

## Output (stdout only)

One JSON object matching [`verdict_schema.json`](../_meta/verdict_schema.json). Top-level `verdict` is one of:

- `VERIFIED` — full coverage, no blocker concerns, bundle self-hash matches input
- `VERIFIED_WITH_CONCERNS` — full coverage, one or more `warning`-severity concerns
- `REJECTED` — uncovered required requirements OR `self_hash_check.matches_input == false` OR any `blocker` concern
- `AUDIT_UNAVAILABLE` — **reserved for the spawn script.** The cold-context model MUST NOT emit this verdict; doing so triggers exit 4 and a rejection.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Valid schema-compliant verdict emitted on stdout; all 8 tuple fields echoed correctly |
| `3` | Environmental / usage error (wrong argv count, bundle_hash not 64-hex, unreadable input file) |
| `4` | `AUDIT_UNAVAILABLE` — subprocess crashed, timed out, produced non-JSON stdout, schema-invalid verdict, tuple mismatch, or model-emitted `AUDIT_UNAVAILABLE`. Bob MUST escalate; never auto-approve. |

Design §5.6: arbiter never writes `.ledger/`. On any failure it exits with code 4 and a single-line stderr diagnostic; bob is sole ledger writer.

## Rubric (v1.2.0)

**Source of truth: this SKILL.md file itself, hashed.** Bump the rubric version (semver) when changes to this file affect verdict semantics. The `rubric_version` bob passes (10th positional arg) is the CUTOVER KEY: bob's R6 (`claims.assert_verified_preconditions`) requires citation-corroboration only when the verdict's `rubric_version >= 1.2.0` (older verdicts skip it deterministically — no silent-disable gap). Current rubric covers:

1. **Self-hash check.** The model MUST recompute the bundle hash from on-disk bytes using the canonical JSON form (sort_keys=True, separators=`(",", ":")`, ensure_ascii=False, exclude the `bundle_hash` field itself — imported from `skills/_meta/trusted_runner.py:canonical_bundle_bytes` / `bundle_hash_hex`). Result populates `self_hash_check.bundle_recomputed_hash` + `matches_input`. Mismatch forces `REJECTED`.

2. **Coverage scoring.** For each requirement in the frozen plan (`test_plan_schema.json` — REQ-NNN entries with `test_types`, `required_tier`, `skip_if_tier_below`):
   - **Covered.** At least one matching test in the bundle passed or was intentionally xfailed.
   - **Uncovered.** No matching test — listed in `coverage.uncovered[]`.
   - **Skipped with reason.** Test exists in bundle but was skipped due to tier shortfall or declared `skip_if_tier_below`; listed in `coverage.skipped_with_reason[]` with `requirement_id`, `reason`, and `tier_required` when applicable. **A skip with declared reason is NOT a coverage gap** (design §1 goal 5).

3. **Plan-bundle shape checks.** Plan must be parseable against `test_plan_schema.json`; bundle must be parseable and contain test results. Parse failure on either → `REJECTED` with a `blocker` concern.

4. **Tier awareness.** If the current inventory tier (from `inventory_hash`-referenced manifest) is below a requirement's `required_tier` AND the requirement declares `skip_if_tier_below`, skip declarations are valid. If not declared, the missing coverage is a `blocker` concern.

5. **Security verdict (NEW in v1.1.0 — S038 Batch E, 2026-05-25).** Bundle MUST include a `security_status` field populated from the relevant gate outputs. The arbiter scores it into the verdict's `security_verdict` arm with values:
   - `passed` — `G_SECURE` and `G_SECRETS_SCAN` (when configured) both PASS, OR the plan does not declare `security_required: true`. No `blocker` raised.
   - `advisory` — gates ran but in advisory mode AND produced findings. Not a `blocker`, but emit a `concern` of severity `medium` so bob's report surfaces it.
   - `not_applicable` — the frozen plan explicitly sets `security_required: false`. Skip-with-reason recorded.
   - `failed` — `G_SECURE --sast-mode strict` OR `G_SECRETS_SCAN --secrets-mode strict` returned exit 2. Forces `REJECTED` with a `blocker`.
   - `unavailable` — gates not configured for the project (no SAST runner, no scanner) AND `security_required: true` in plan. Emit a `concern` of severity `high` and `AUDIT_UNAVAILABLE` (exit 4), forcing bob to escalate. Never silently auto-approve.

   **Plan flag.** `test_plan_schema.json` v1.1 (S038 Batch E) adds optional `security_required: bool` at plan-level (default `false` for backwards compat). When `true`, missing `security_status` field in the bundle = `unavailable`.

   **Companion skills:** `sast-tooling` (G_SECURE), `secret-scanning` (G_SECRETS_SCAN), `dep-currency-check` (G_DEP_CURRENCY — referenced separately by bob, not part of arbiter rubric since dep-check runs at design-time not test-time).

6. **Evidence-map citations (NEW in v1.2.0 — S048 / #116, the non-LLM verification arm).** The verdict MUST carry a top-level `evidence_map: {<REQ-ID>: [<nodeid>, ...]}` — for each REQ-ID scored as covered, the verbatim passing-test nodeid(s) (`outcome == "passed"`) from the bundle's `results[].tests[]` cited as satisfying it. This is a REQUIRED top-level key (in `verdict_schema.json` + `verification_arbiter_spawn.REQUIRED_TOP_KEYS` — without it there, the arbiter's own hand-rolled `validate_verdict` would reject its output and bob would halt). Bob's deterministic arm (`deterministic_arm.corroborate_citations`, invoked by R6) verifies every cited nodeid EXISTS in the bundle AND passed, and REJECTS the INTEGRATED→VERIFIED transition if any cited nodeid is absent or non-passing (an invented/misattributed-evidence tell — the correlated-hallucination signal). Empty `{}` is valid (degraded/returncode-only or jest bundle with no per-test records, or coverage by skips-with-reason only); on such bundles citation-corroboration is recorded `unavailable` and does NOT veto. **Honest residual:** catches *invented* evidence, NOT *irrelevant-but-real* citations (a real passing test cited for the wrong criterion). The deeper semantic-test-adequacy residual (tests that pass but encode the wrong oracle) is deferred to #151.

   This couples with R6's deterministic-evidence conjunct: VERIFIED now requires `audit_arm passes ∧ arbiter_arm passes ∧ deterministic_evidence == GREEN ∧ citations_corroborated` (a flat conjunction, NOT a quorum — the deterministic arm can only VETO). The deterministic GREEN/RED/INDETERMINATE verdict is derived by R6 *from the hash-addressed bundle itself* (`deterministic_arm.classify_bundle_evidence`), never from a producer-written archive boolean and never from `gate-runs.jsonl`.

## Env vars

| Variable | Default | Purpose |
|---|---|---|
| `AUDIT_CLAUDE_BIN` | `claude` | Cold-context Claude CLI binary path (shared with `audit_spawn.py`) |
| `AUDIT_CLAUDE_MODEL` | `claude-opus-4-6[1m]` | Model ID for the cold-context verifier |
| `ARBITER_FRESHNESS_WINDOW_S` | `1800` | Seconds after `opened_at` before a pending verification request is considered abandoned (design §9.5). Consumed by Phase 2B's `recover_verification_requests()` sweeper in `claims.py`. |

Timeout for the inner `claude -p` subprocess is `DEFAULT_TIMEOUT_S = 180` (matches `audit_spawn.py`). Design §9.5 rationale: the 1800s freshness window is 10× the inner timeout, leaving headroom for bob restart + arbiter retry.

## Relationship to audit_spawn.py

Per design §5.6, the two run **in parallel** after a bundle is produced; bob consumes both verdicts before applying VERIFIED. They are complementary, not redundant:

- `audit_spawn.py` — metacognitive audit (Claude + Codex, disagreement detection). Unchanged by Phase 2A.
- `verification_arbiter_spawn.py` — single-verifier coverage + self-hash check against the frozen test plan. New in Phase 2A-1.

Either arm REJECTED blocks VERIFIED. Either arm AUDIT_UNAVAILABLE forces escalation (no auto-approve).

## Scope boundaries

| In scope | Out of scope |
|---|---|
| Scoring bundle coverage against frozen plan | Creating or amending the test plan (test-architect owns that; §5.5) |
| Recomputing `bundle_hash` from on-disk bytes | Writing `.ledger/verdicts/*.verdict.yaml` (bob owns; §5.6) |
| Echoing the 8-field tuple | Deciding INTEGRATED → VERIFIED (bob owns; §5.3 outer tuple-match gate) |
| Emitting `AUDIT_UNAVAILABLE` via exit 4 | Model-emitted `AUDIT_UNAVAILABLE` (rejected by spawn script) |
| Reading inventory via its hash | Live env-adoption probe (inventory is a frozen input) |

## References

- Design doc: `docs/plans/2026-04-21-tester-split-design.md` (§5.1 role, §5.3 tuple, §5.6 CB4 boundary, §5.7 atomic writes, §9.5 freshness window)
- Handoff: `docs/plans/2026-04-21-tester-split-phase2-handoff.md`
- Schemas: `skills/_meta/verdict_schema.json`, `skills/_meta/test_plan_schema.json`
- Binary: `skills/_meta/verification_arbiter_spawn.py`
- Tests: `skills/_meta/tests/test_verification_arbiter_spawn.py` (12 tests, all passing)
- Sibling subprocess (runs in parallel): `~/.claude/skills/_meta/audit_spawn.py`
