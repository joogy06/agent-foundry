# Composition, not Extension

This skill **composes** `integration-flow-testing` (IFT) — it does NOT
extend or fork IFT. Why this matters, and the boundary contract.

## The rule

`ever-test-gen` MUST NOT:

1. Import IFT's internal modules directly (only its public `scripts/run.py` is fair game)
2. Modify IFT's SKILL.md, schemas/, or references/
3. Add IFT-namespaced files into IFT's directory tree
4. Re-derive IFT's flow-test algorithm in ever-test-gen scripts

`ever-test-gen` IS ALLOWED to:

1. Invoke IFT via subprocess with input files (the official integration
   surface)
2. Read IFT's output artifacts (the test files it produces)
3. Prepend the evo confidence header to those output artifacts before
   handing them to bob

## Why?

If we fork IFT, every time the integration-flow-testing skill evolves
we'd have to chase its changes in ever-test-gen too. Forks lose context;
composition tracks upstream automatically.

If we extend IFT (add ever-test-gen knowledge into IFT itself), we
poison a general-purpose skill with v-specific knowledge. IFT serves
many callers (bob's normal flow, dep-currency-check, etc.) — none of
them should pay the EVO complexity tax.

## The composition surface in v1

`scripts/compose_iflow.py` defines the single integration point:

```python
compose(component_id, plan_path, intent_map_path, *, mode) -> list[dict]
```

For v1, the implementation is a stub that returns `[]`. This is
intentional. The v1 ship covers regression / migration / cve-proof
tests fully — IFT-flow-test composition is a v1.1 follow-up where the
incremental value justifies the integration cost.

When v1.1 lands and the stub gets a real implementation, callers (run.py
and tests) don't need to change. The contract is the stub.

## How a future v1.1 composition would work

1. Read plan.yaml's flows[]
2. For each flow, subprocess `integration-flow-testing/scripts/run.py
   --flow-id <FLOW-X>` to get a flow-test file
3. Take that file's bytes, prepend our test_header.build_header() output,
   write to `tests/test_evo_<mode>_<flow_id>__flow.py`
4. Include in the manifest returned to bob

The skill remains a thin wrapper — IFT does the work, we just label
the output with evo provenance.

## Anti-patterns to refuse

- "Just copy the IFT flow-test code into compose_iflow.py" — that's a
  fork, not composition
- "Add evo-specific markers into IFT's test header generator" — that
  pollutes IFT
- "Symlink IFT's scripts directory into ever-test-gen/" — that's tight
  coupling masquerading as composition
- "Import private IFT helpers via `from integration_flow_testing._internal import ...`" —
  using non-public surface is forking by another name
