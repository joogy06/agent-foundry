# Bug-for-Bug Oracle

The migration-confirmation tests in this skill treat the LEGACY codebase's
output as the oracle, NEVER as a target for improvement.

## Why bug-for-bug?

HARD-RULE 2 (design §13): EVO must NEVER fix pre-existing legacy bugs as
part of an upgrade. If the legacy returns the wrong value for input X,
the upgraded code MUST return the same wrong value for input X.

This is non-negotiable. Stack-migrations that "accidentally" fix old bugs
violate the safety contract because users can't tell whether they're
seeing a fix-they-wanted or a regression-they-don't-know-about.

## How the oracle is built

For each `breaking_lines[]` entry in api_delta:

1. **Identify a representative input** — usually the call site mentioned
   in the breaking line. The skill stubs `TODO-IMPLEMENT-FIXTURE` and the
   user fills in.

2. **Capture pre-migration output** — by running the legacy code against
   the representative input, before any deps are bumped. The captured
   output is stored under `tests/fixtures/legacy_oracle_<bl_slug>.json`.

3. **Replay post-migration** — the generated `test_migration_<bl>_bug_for_bug`
   exercises the upgraded code on the SAME input and asserts equivalence
   with the captured oracle.

If equivalence fails, the user has two choices:
- Roll back the upgrade (bug-for-bug violated)
- Document an explicit `evo_acknowledged_legacy_bug` annotation in the
  test (caller explicitly accepts the divergence as a known-fix)

## What equivalence means

- For JSON-shaped outputs: deep-equal via Python `==`
- For numeric outputs: exact (no floating-point tolerance, because
  tolerance hides bugs)
- For exceptions: same class AND same message (catch-and-stringify)
- For HTTP responses: status code + canonical body

The skill doesn't bake in equivalence — the user implements it in the
generated stub. We just enforce the discipline at code-review time
through the `requires_user_review` marker.

## Optimisation suggestions are advisory-only

Per HARD-RULE 2: any optimisation that would CHANGE the legacy oracle
must NOT be auto-applied during version-upgrade. Such suggestions live
in `drift-report.findings[].kind=optimization_suggestion` as advisory
output only. v2 may add `--apply-optimizations` as a separate, opt-in
flag.
